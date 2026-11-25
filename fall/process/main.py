import time
import threading
from collections import deque
import numpy as np
import onnxruntime as ort

from camera import *
from config import *
from process import *
from mqtt_client import *

class FallDetectionSystem:
    def __init__(self):
        self.stop_event = threading.Event()
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.latest_frame_ts = 0.0

        self.picam2 = init_camera(640, 480)

        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess_yolo = ort.InferenceSession(POSE_ONNX, so, providers=["CPUExecutionProvider"])
        self.sess_fall = ort.InferenceSession(FALL_ONNX, so, providers=["CPUExecutionProvider"])
        self._warmup()

        self.mqtt = FallMqttClient(host=BROKER_IP, port=BROKER_PORT, topic=BROKER_TOPIC)
        self.dq = deque(maxlen=10)

    def _warmup(self):
        """
            ONNX 파일들 전부 warmup
        """
        dummy_yolo = np.zeros((1, 3, 320, 320), dtype=np.float32)
        dummy_fall = np.zeros((1, 38, 10), dtype=np.float32)
        fall_in = self.sess_fall.get_inputs()[0].name
        for _ in range(3):
            self.sess_yolo.run(None, {"images": dummy_yolo})
            self.sess_fall.run(None, {fall_in: dummy_fall})

    def _camera_worker(self):
        """
            frame과 frame_ts 획득
        """
        while not self.stop_event.is_set():
            ok, frame = read_frame(self.picam2)
            if ok and frame is not None:
                with self.frame_lock:
                    self.latest_frame = frame
                    self.latest_frame_ts = time.time()
            else:
                time.sleep(0.005)

    def _inference_worker(self):
        """
            10 FPS 주기
            최신 프레임으로 추론 후 통신
        """
        target_interval = 0.1  # 10 FPS
        lying_start_ts = None
        last_processed_ts = 0.0

        while not self.stop_event.is_set():
            t0 = time.perf_counter()

            with self.frame_lock:
                frame = self.latest_frame
                frame_ts = self.latest_frame_ts

            if frame is None or frame_ts == last_processed_ts:
                time.sleep(0.01)
                continue

            # 전처리 -> YOLO -> 후처리 -> Fall1DCNN
            _, ratio, (padl, padt), x = preprocess(frame)
            raw_onnx = self.sess_yolo.run(None, {"images": x})[0]
            feature, people, pose_conf = postprocess(raw_onnx, padl, padt, ratio, self.dq)

            is_fall = False
            if feature is not None:
                r_onnx = self.sess_fall.run(None, {"input.1": feature})[0]
                exp_logits = np.exp(r_onnx - np.max(r_onnx, axis=1, keepdims=True))
                probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
                is_fall = bool(probs[0, 1] > 0.5)

            if is_fall:
                if lying_start_ts is None:
                    lying_start_ts = frame_ts
                lying_sec = round(frame_ts - lying_start_ts, 2)
            else:
                lying_start_ts = None
                lying_sec = 0.0

            # 추론 시간
            infer_ms = int((time.perf_counter() - t0) * 1000)

            self.mqtt.publish_frame(
                people=people,
                lying=is_fall,
                lying_sec=lying_sec,
                signal={"fall": is_fall},
                conf=pose_conf,
                infer_ms=infer_ms
            )

            # 10 FPS를 맞추기 위한 elapsed
            elapsed = time.perf_counter() - t0
            if elapsed < target_interval:
                time.sleep(target_interval - elapsed)

    def run(self):
        t_cam = threading.Thread(target=self._camera_worker, daemon=True)
        t_inf = threading.Thread(target=self._inference_worker, daemon=True)
        t_cam.start()
        t_inf.start()
        print("=== Pi B (카메라 · 추론 · MQTT) 가동 시작 ===")

        try: # 계속 CPU돌아가게 하기
            while not self.stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt: # Ctrl+C 오면 종료
            print("\n종료 신호 수신, 자원 정리 중...")
        finally: # 종료 과정
            self.stop_event.set()
            t_cam.join(timeout=1.0)
            t_inf.join(timeout=1.0)
            self.picam2.stop()
            self.mqtt.close()
            print("=== 안전 종료 완료 ===")

if __name__ == "__main__":
    app = FallDetectionSystem()
    app.run()