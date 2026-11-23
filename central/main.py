import paho.mqtt.client as mqtt
import json
import time
from central.rules import decide_level

# 토픽 별 필수 값
REQUIRED = {
    "stillsafe/hand": ["v", "seq", "ts", "zone", "signal"],
    "stillsafe/fall": ["v", "seq", "ts", "people", "lying", "lying_sec", "signal"],
}


TIMEOUT_SEC = 3    # 이 시간 동안 정상 메시지 없을 시 장치 이상

last_seen = {}     # 마지막으로 정상 메시지 받은 시각
device_ok = {}     # 지난번 체크 시 장치 정상 여부
latest = {}        # 마지막으로 받은 정상 메시지
last_level = None  # 마지막으로 결정한 단계
short_since = None # 인원 부족이 시작된 시각

def on_connect(client, userdata, flags, reason_code, properties):
    print("접속 결과: ", reason_code)

    # 다시 연결 됐을 때 구독도 다시 등록
    client.subscribe("stillsafe/#")

def on_message(client, userdata, msg):

    # 메시지 처리
    text = msg.payload.decode()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("JSON 디코딩 오류:", text)
        return

    # 메시지 유효성 검사
    if not isinstance(data, dict):
        print("JSON 데이터가 딕셔너리가 아닙니다:", text)
        return

    # 필수 키 확인
    if msg.topic not in REQUIRED:
        print("알 수 없는 토픽:", msg.topic)
        return
    
    for key in REQUIRED[msg.topic]:
        if key not in data:
            print("키가 JSON 데이터에 없습니다.", msg.topic, key)
            return

    # 처음 받았거나 오래 끊겼다가 다시 온 경우
    now = time.time()
    if msg.topic in last_seen:
        gap = now - last_seen[msg.topic]
        if gap > TIMEOUT_SEC:
            # 장치 이상 메시지 이후 정상 메시지
            print(msg.topic, "seq =", data["seq"], f"(지난번보다 {gap:.1f}초 뒤)")
    else:
        print(msg.topic, "seq =", data["seq"], "(처음 메시지)")

    # 마지막으로 받은 정상 메시지 기록
    latest[msg.topic] = data
    last_seen[msg.topic] = now


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883)

# MQTT 메시지 수신 루프 시작
client.loop_start()

while True:
    now = time.time()

    # 1) 장치 정상 여부 확인
    for topic in REQUIRED:
        ok = topic in last_seen and (now - last_seen[topic]) <= TIMEOUT_SEC
        before = device_ok.get(topic)

        if ok != before:
            if ok:
                print(topic, "정상")
            else:
                print(topic, "장치 이상")
            device_ok[topic] = ok

    all_ok = device_ok["stillsafe/hand"] and device_ok["stillsafe/fall"]
    hand = latest.get("stillsafe/hand")
    fall = latest.get("stillsafe/fall")

    # 2) 인원 부족 시간 계산
    if fall is not None and fall["people"] < 2:
        if short_since is None:
            short_since = now
        short_sec = now - short_since
    else:
        short_since = None
        short_sec = 0

    # 3) 단계 결정
    level, reason = decide_level(hand, fall, all_ok, short_sec)

    if (level, reason) != last_level:
        print(f"단계 {level} ({reason})")
        last_level = (level, reason)
    time.sleep(1)