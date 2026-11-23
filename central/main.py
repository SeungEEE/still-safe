import paho.mqtt.client as mqtt
import json

REQUIRED = {
    "stillsafe/hand": ["v", "seq", "ts", "zone", "signal"],
    "stillsafe/fall": ["v", "seq", "ts", "people", "lying", "lying_sec", "signal"],
}

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
    
    print(msg.topic, "seq =", data["seq"])


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883)
client.loop_forever()