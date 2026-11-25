import json, time
import paho.mqtt.client as mqtt

class FallMqttClient:
    def __init__(self, host, port, topic):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # paho-mqtt 2.x
        self.client.connect(host, port, keepalive=5)
        self.client.loop_start()
        self.topic = topic
        self.seq = 0

    def publish_frame(self, people, lying, lying_sec, signal, conf, infer_ms):
        while True:
            frame_time = time.time()   # 프레임을 찍은 시각
            msg = {
                "v": 1,
                "seq": self.seq,
                "ts": frame_time, # 1763452800.456
                "people": people, # 2
                "lying": lying, # True
                "lying_sec": lying_sec, # 2.4
                "signal": signal, # {"fall":False}
                "conf": conf, # 0.81
                "infer_ms": infer_ms # 0.143
            }
            self.client.publish(self.topic, json.dumps(msg))
            self.seq += 1

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()