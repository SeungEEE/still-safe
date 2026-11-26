import os
import cv2
import argparse
import time
import threading
from collections import deque
import numpy as np
import onnxruntime as ort
import traceback

from camera import *
from config import *
from process import *
from mqtt_client import *
from FallStateTracker import *

class FallDetectionSystem:
    def __init__(self, video_path=None):
        self.stop_event = threading.Event()
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.latest_frame_ts = 0.0

        if video_path:
            self.video_path = os.path.join(BASE_DIR, "data", video_path)
        else:
            self.video_path = None
        
        if self.video_path:
            self.cap = cv2.VideoCapture(self.video_path)
            if not self.cap.isOpened():
                raise RuntimeError(f"영상 파일을 열 수 없습니다: {self.video_path}")
            self.video_fps = self.cap.get(cv2.CAP_PROP_FPS) or 10.0
            print(f"[모드] 테스트 영상 ({self.video_path}, {self.video_fps:.1f} FPS)")
        else:
            self.picam2 = init_camera(640, 480)
            print("[모드] 실시간 카메라 (Picamera2 640x480)")

        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess_yolo = ort.InferenceSession(POSE_ONNX, so, providers=["CPUExecutionProvider"])
        self.sess_fall = ort.InferenceSession(FALL_ONNX, so, providers=["CPUExecutionProvider"])
        self._warmup()

        self.mqtt = FallMqttClient(host=BROKER_IP, port=BROKER_PORT, topic=BROKER_TOPIC)
        self.tracker = FallStateTracker()
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

        interval = (1.0 / self.video_fps) if self.video_path else 0.0

        try:
            while not self.stop_event.is_set():
                if self.video_path:
                    ok, frame = self.cap.read()
                    if not ok:
                        print("[경고] test.mp4 프레임 읽기 실패 (ok=False)")
                        time.sleep(0.5)
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    with self.frame_lock:
                        self.latest_frame = frame
                        self.latest_frame_ts = time.time()
                    time.sleep(interval)
                else:
                    ok, frame = read_frame(self.picam2)
                    if ok and frame is not None:
                        with self.frame_lock:
                            self.latest_frame = frame
                            self.latest_frame_ts = time.time()
                    else:
                        time.sleep(0.005)
        except Exception:
            print("[에러] _camera_worker 스레드 사망")
            traceback.print_exc()

    def _inference_worker(self):
        """
            10 FPS 주기
            최신 프레임으로 추론 후 통신
        """
        target_interval = 0.1  # 10 FPS
        lying_start_ts = None
        last_processed_ts = 0.0

        try:
            while not self.stop_event.is_set():
                t0 = time.perf_counter()

                with self.frame_lock:
                    frame = self.latest_frame
                    frame_ts = self.latest_frame_ts

                if frame is None or frame_ts == last_processed_ts:
                    if frame is None: print("[경고] frame is None. _inference_worker")
                    else: print("[경고] frame_ts == last_processed_ts. _inference_worker")

                    time.sleep(0.01)
                    continue
                
                last_processed_ts = frame_ts

                # 전처리 -> YOLO -> 후처리 -> Fall1DCNN

                _, ratio, (padl, padt), x = preprocess(frame)
                raw_onnx = self.sess_yolo.run(None, {"images": x})[0]
                feature, people, pose_conf, geom = postprocess(raw_onnx, padl, padt, ratio, self.dq)

                is_fall = False
                if feature is not None:
                    r_onnx = self.sess_fall.run(None, {"input": feature})[0]
                    exp_logits = np.exp(r_onnx - np.max(r_onnx, axis=1, keepdims=True))
                    probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
                    is_fall = bool(probs[0, 1] > 0.5)

                is_lying, lying_sec, motion = self.tracker.update(is_fall, geom, frame_ts)

                # 추론 시간
                infer_ms = int((time.perf_counter() - t0) * 1000)
                sig = {"fall": is_fall}

                self.mqtt.publish_frame(
                    people=people,
                    lying=is_lying,
                    lying_sec=lying_sec,
                    signal=sig,
                    conf=pose_conf,
                    infer_ms=infer_ms
                )

                print("통신 내용")
                print(f"people: {people}, lying: {is_lying}, lying_sec: {lying_sec}, signal: {sig}, conf: {pose_conf}, infer_ms: {infer_ms}\n")

                # 10 FPS를 맞추기 위한 elapsed
                elapsed = time.perf_counter() - t0
                if elapsed < target_interval:
                    time.sleep(target_interval - elapsed)
        except Exception:
            print("[에러] _inference_worker 스레드 사망")
            traceback.print_exc()

    def run(self):
        t_cam = threading.Thread(target=self._camera_worker, daemon=True)
        t_inf = threading.Thread(target=self._inference_worker, daemon=True)
        t_cam.start()
        t_inf.start()
        print("=== Pi B (카메라 · 추론 · MQTT) 가동 시작 ===")

        try: # 계속 CPU돌아가게 하기
            while not self.stop_event.is_set():
                time.sleep(0.5)
                print("asdf")
        except KeyboardInterrupt: # Ctrl+C 오면 종료
            print("\n종료 신호 수신, 자원 정리 중...")
        finally: # 종료 과정
            self.stop_event.set()
            t_inf.join(timeout=1.0)
            if self.video_path:
                self.cap.release()
            else:
                t_cam.join(timeout=0.2)
                try:
                    self.picam2.stop()
                except Exception:
                    pass
            self.mqtt.close()
            print("=== 안전 종료 완료 ===")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="StillSafe 실시간 낙상 감지 시스템")
    parser.add_argument("-v", "--video", type=str, default=None, help="테스트용 영상 파일 경로 (미지정 시 실시간 카메라)")
    args = parser.parse_args()

    app = FallDetectionSystem(video_path=args.video)
    app.run()