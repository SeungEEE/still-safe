import paho.mqtt.client as mqtt
import json
import time
import os
from central.rules import decide_level
from central.esp32 import Esp32
from common.messages import SCHEMA, check

TIMEOUT_SEC = 3    # 이 시간 동안 정상 메시지 없을 시 장치 이상
HOLD_SEC = 2       # 주의, 경고 조건 사라지고 이 시간 뒤에 내려감
PING_SEC = 0.2         # ESP32 에 PING 보내는 간격 (ESP32 워치독은 0.5초)
PONG_TIMEOUT_SEC = 1   # 이 시간 동안 PONG 이 없으면 ESP32 응답 없음
REOPEN_SEC = 2         # ESP32 포트가 닫혔을 때 다시 열어 보는 간격
STATE_TOPIC = "stillsafe/central/state"   # 화면, 웹이 구독하는 중앙 상태
STATE_SEC = 1          # 상태가 그대로여도 이 간격마다 한 번씩 발행

last_seen = {}     # 마지막으로 정상 메시지 받은 시각
device_ok = {}     # 지난번 체크 시 장치 정상 여부
latest = {}        # 마지막으로 받은 정상 메시지
last_level = None  # 마지막으로 결정한 단계
short_since = None # 인원 부족이 시작된 시각
drop_since = None  # 더 낮은 단계 판단이 시작된 시각
offline = set()    # offline 알려온 장치
last_ping = 0      # 마지막으로 PING 보낸 시각
sent_level = None  # ESP32 에 마지막으로 보낸 단계 (다시 연결되면 None 으로 되돌려 다시 보냄)
esp_ok = None      # 지난번 체크 시 ESP32 응답 여부
last_state = None  # 마지막으로 발행한 상태 (ts 제외)
last_state_pub = 0 # 마지막으로 상태 발행한 시각

def on_connect(client, userdata, flags, reason_code, properties):
    print("접속 결과: ", reason_code)

    # 다시 연결 됐을 때 구독도 다시 등록
    # stillsafe/# 로 전부 구독하면 내가 발행한 상태 토픽까지 다시 받으므로 필요한 것만
    client.subscribe([("stillsafe/hand", 0), ("stillsafe/fall", 0), ("stillsafe/status/#", 0)])

def on_message(client, userdata, msg):

    # 연결 상태 메시지
    if msg.topic.startswith("stillsafe/status/"):
        name = msg.topic.split("/")[-1]
        data_topic = "stillsafe/" + name
        state = msg.payload.decode()
        print(data_topic, "상태:", state)
        if state == "offline":
            offline.add(data_topic)
        else:
            offline.discard(data_topic)
        return

    if msg.topic not in SCHEMA:
        print("알 수 없는 토픽:", msg.topic)
        return

    # JSON 읽기 (깨진 바이트나 JSON 이 아닌 글자는 버림)
    try:
        data = json.loads(msg.payload.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        print("JSON 으로 못 읽음:", msg.topic, msg.payload[:80])
        return

    # 형식 검사 (규칙은 common/messages.py 의 SCHEMA)
    why = check(data, SCHEMA[msg.topic])
    if why:
        print("버림:", msg.topic, why)
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
client.connect(os.getenv("MQTT_HOST", "localhost"), 1883)

# MQTT 메시지 수신 루프 시작
client.loop_start()

# ESP32 (진짜: /dev/ttyUSB0, 가짜: socket://127.0.0.1:7000)
esp = Esp32(os.getenv("ESP32_PORT", "/dev/ttyUSB0"))
esp.open()

while True:
    now = time.time()

    # 0) ESP32 연결 유지, PING, 응답 확인
    if not esp.alive and now - esp.last_open_try >= REOPEN_SEC:
        if esp.open():
            sent_level = None          # 다시 연결됐으면 지금 단계를 다시 알려줌
        now = time.time()              # open 이 2초 기다리므로 시각 다시 읽음

    if now - last_ping >= PING_SEC:
        esp.send("PING")
        last_ping = now

    ok = esp.alive and now - esp.last_pong <= PONG_TIMEOUT_SEC
    if ok != esp_ok:
        print("ESP32", "정상" if ok else "응답 없음")
        esp_ok = ok

    # 1) 장치 정상 여부 확인
    for topic in SCHEMA:
        ok = (topic in last_seen
              and (now - last_seen[topic]) <= TIMEOUT_SEC
              and topic not in offline)

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

    if last_level is not None and level < last_level[0] and last_level[0] in (1, 2):
        if drop_since is None:
            drop_since = now

        if now - drop_since < HOLD_SEC:
            level, reason = last_level
        else:
            drop_since = None
    else:
        drop_since = None

    if (level, reason) != last_level:
        print(f"단계 {level} ({reason})")
        last_level = (level, reason)

    # 4) 단계가 바뀌었으면 ESP32 에 알림 (보내기 실패하면 다음 바퀴에 다시)
    if level != sent_level and esp.send(f"LEVEL:{level}"):
        sent_level = level

    # 5) 상태 발행 (화면, 웹용): 무엇이든 바뀌면 바로, 아니면 STATE_SEC 마다
    state = {
        "v": 1,
        "level": level,
        "reason": reason,
        "motor": esp.motor,       # 아직 모르면 None (JSON 에서는 null)
        "latched": esp.latched,
        "devices": {
            "hand": device_ok["stillsafe/hand"],
            "fall": device_ok["stillsafe/fall"],
            "esp32": esp_ok,
        },
    }
    if state != last_state or now - last_state_pub >= STATE_SEC:
        # retain: 화면을 나중에 켜도 마지막 상태를 바로 받음
        client.publish(STATE_TOPIC, json.dumps({**state, "ts": now}), retain=True)
        last_state = state
        last_state_pub = now

    time.sleep(0.1)