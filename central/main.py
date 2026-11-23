import paho.mqtt.client as mqtt
import json
import time
from central.rules import decide_level

REQUIRED = {
    "stillsafe/hand": ["v", "seq", "ts", "zone", "signal"],
    "stillsafe/fall": ["v", "seq", "ts", "people", "lying", "lying_sec", "signal"],
}

TIMEOUT_SEC = 3
last_seen = {}
device_ok = {}
latest = {}
last_level = None

def on_connect(client, userdata, flags, reason_code, properties):
    print("접속 결과: ", reason_code)
    client.subscribe("stillsafe/#")

def on_message(client, userdata, msg):
    text = msg.payload.decode()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("JSON 디코딩 오류:", text)
        return

    if not isinstance(data, dict):
        print("JSON 데이터가 딕셔너리가 아닙니다:", text)
        return

    if msg.topic not in REQUIRED:
        print("알 수 없는 토픽:", msg.topic)
        return
    
    for key in REQUIRED[msg.topic]:
        if key not in data:
            print("키가 JSON 데이터에 없습니다.", msg.topic, key)
            return
    
    now = time.time()
    if msg.topic in last_seen:
        gap = now - last_seen[msg.topic]
        if gap > TIMEOUT_SEC:
            print(msg.topic, "seq =", data["seq"], f"(지난번보다 {gap:.1f}초 뒤)")
    else:
        print(msg.topic, "seq =", data["seq"], "(처음 메시지)")

    latest[msg.topic] = data
    last_seen[msg.topic] = now


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883)
client.loop_start()

while True:
    now = time.time()
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

    level, reason = decide_level(hand, fall, all_ok)

    if (level, reason) != last_level:
        print(f"단계 {level} ({reason})")
        last_level = (level, reason)
    time.sleep(1)