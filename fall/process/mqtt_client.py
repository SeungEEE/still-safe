import json, time
import paho.mqtt.client as mqtt

BROKER_IP = "192.168.20.21"
BROKER_PORT = 1883
TOPIC = "stillsafe/fall"

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # paho-mqtt 2.x
client.connect(BROKER_IP, BROKER_PORT, keepalive=5)
client.loop_start()

def mqtt_client(people, lying, lying_sec, signal, conf, infer_ms):
    seq = 0
    try:
        while True:
            frame_time = time.time()   # 프레임을 찍은 시각
            # ... 탐지 → zone, hands ...
            msg = {
                "v": 1,
                "seq": seq,
                "ts": frame_time, # 1763452800.456
                "people": people, # 2
                "lying": lying, # True
                "lying_sec": lying_sec, # 2.4
                "signal": signal, # {"fall":False}
                "conf": conf, # 0.81
                "infer_ms": infer_ms # 0.143
            }
            client.publish(TOPIC, json.dumps(msg))
            seq += 1
            print("보내기 완료")
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n종료 중...")

    finally:
        client.loop_stop()
        client.disconnect()