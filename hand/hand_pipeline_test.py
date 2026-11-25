from pathlib import Path
import json
import os
import runpy
import time

from paho.mqtt import publish

home = Path.home()

print("1. 저장된 사진으로 손 추론 시작")
inference = runpy.run_path(str(home / "hand_infer.py"))

print("\n2. 손 마스크로 구역 판정 시작")
judgment = runpy.run_path(str(home / "hand_zone_test.py"))

# 저장된 사진을 사용하는 테스트 전용 메시지입니다.
# 실제 촬영 시각과 GPIO 확정 신호는 아직 포함하지 않습니다.
message = {
    "test": True,
    "source": "saved_image",
    "zone": judgment["zone"],
    "hands": int(len(inference["keep"])),
    "sent_ts": round(time.time(), 3),
}

host = os.getenv("MQTT_HOST", "192.168.20.21")
topic = "stillsafe/test/hand"

print("\n3. 구역 판정 결과 MQTT 전송")
try:
    publish.single(
        topic=topic,
        payload=json.dumps(message, ensure_ascii=False),
        hostname=host,
        port=1883,
        qos=0,
        retain=False,
    )
except Exception as e:
    print(f"MQTT 전송 실패: {e}")
    raise SystemExit(1)

print("전송 완료")
print("전송 대상:", host)
print("토픽:", topic)
print("메시지:", json.dumps(message, ensure_ascii=False))
