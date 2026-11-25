import argparse
import json
import os
import threading
import time
from pathlib import Path

import cv2
import paho.mqtt.client as mqtt

from hand_video_test import Segmenter, PRIORITY


def resize_frame(frame):
    h, w = frame.shape[:2]
    scale = min(1.0, 640 / max(h, w))
    if scale < 1:
        frame = cv2.resize(
            frame,
            (max(1, round(w * scale)), max(1, round(h * scale))),
        )
    return frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=100)
    args = parser.parse_args()
    if args.frames < 1:
        parser.error("--frames must be positive")

    home = Path.home()
    cap = cv2.VideoCapture(str(home / "hand_video.mp4"))
    if not cap.isOpened():
        raise RuntimeError("Cannot open hand_video.mp4")

    client = None
    loop_started = False
    times = []
    try:
        model = Segmenter(home / "best.onnx")

        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("Cannot decode the first frame")
        frame = resize_frame(frame)

        print("Warm-up: 5 runs, excluded from the average", flush=True)
        for _ in range(5):
            model.infer(frame)

        host = os.getenv("MQTT_HOST", "192.168.20.21")
        topic = "stillsafe/hand"
        status_topic = "stillsafe/status/hand"
        connected = threading.Event()

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code == 0:
                client.publish(
                    status_topic, "online", qos=1, retain=True
                )
                connected.set()
            else:
                print(f"MQTT connection rejected: {reason_code}", flush=True)

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.will_set(
            status_topic, "offline", qos=1, retain=True
        )
        client.connect(host, 1883, keepalive=5)
        client.loop_start()
        loop_started = True

        if not connected.wait(timeout=10):
            raise RuntimeError("MQTT connection timed out")

        print(f"MQTT: {host} / {topic}", flush=True)
        print(f"Measure up to {args.frames} frames", flush=True)

        seq = 0
        inner_streak = 0

        while seq < args.frames:
            # Replay input time, not the original recording timestamp.
            replay_ts = time.time()
            _, detections, infer_ms = model.infer(frame)

            chosen = max(
                detections,
                key=lambda item: (
                    PRIORITY[item["zone"]], item["conf"]
                ),
                default=None,
            )
            zone = chosen["zone"] if chosen else "none"
            confidence = chosen["conf"] if chosen else 0.0

            inner_streak = inner_streak + 1 if zone == "inner" else 0

            # Calculated test signals; no physical GPIO output.
            signal = {
                "inner": inner_streak >= 2,
                "middle": zone == "middle",
            }

            message = {
                "v": 1,
                "seq": seq,
                "ts": round(replay_ts, 3),
                "zone": zone,
                "signal": signal,
                "hands": len(detections),
                "conf": round(confidence, 3),
                "infer_ms": int(round(infer_ms)),
                "test": True,
                "source": "saved_video",
                "gpio_enabled": False,
            }

            info = client.publish(
                topic,
                json.dumps(message),
                qos=0,
                retain=False,
            )
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish failed: {info.rc}")

            info.wait_for_publish(timeout=3)
            if not info.is_published():
                raise RuntimeError("MQTT send timed out")

            times.append(infer_ms)
            seq += 1

            print(
                f"[{seq}/{args.frames}] "
                f"zone={zone} hands={len(detections)} "
                f"ONNX={infer_ms:.1f} ms "
                f"average={sum(times)/len(times):.1f} ms",
                flush=True,
            )

            if seq >= args.frames:
                break

            ok, frame = cap.read()
            if not ok:
                print("End of video", flush=True)
                break
            frame = resize_frame(frame)

    except KeyboardInterrupt:
        print("\nStopped", flush=True)
    finally:
        cap.release()
        if client is not None:
            if client.is_connected():
                try:
                    info = client.publish(
                        "stillsafe/status/hand",
                        "offline", qos=1, retain=True,
                    )
                    info.wait_for_publish(timeout=2)
                except Exception:
                    pass
            client.disconnect()
            if loop_started:
                client.loop_stop()

        if times:
            average = sum(times) / len(times)
            print("\n--- ONNX inference results ---")
            print(f"Measured frames: {len(times)}")
            print(f"Average: {average:.2f} ms")
            print(f"Minimum: {min(times):.2f} ms")
            print(f"Maximum: {max(times):.2f} ms")
            print(f"Inference-only throughput: {1000/average:.2f} FPS")


if __name__ == "__main__":
    main()
