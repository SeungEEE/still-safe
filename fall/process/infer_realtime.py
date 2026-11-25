import cv2
import matplotlib.pyplot as plt
import onnxruntime as ort
from mqtt_client import mqtt_client
import json
import numpy as np
from picamera2 import Picamera2
import time
import os

from camera import *
from config import *
from process import *
from collections import deque

def init():
    picam2 = init_camera(640, 480)
    so = ort.SessionOptions()
    so.enable_profiling = True
    sess_yolo = ort.InferenceSession(POSE_ONNX,so, providers=["CPUExecutionProvider"])
    sess_fall = ort.InferenceSession(FALL_ONNX,so, providers=["CPUExecutionProvider"])

    # warm-up
    dummy_yolo = np.zeros((1, 3, 320, 320), dtype=np.float32)
    dummy_fall = np.zeros((1, 38, 10), dtype=np.float32)
    fall_in = sess_fall.get_inputs()[0].name
    for _ in range(3):
        sess_yolo.run(None, {"images": dummy_yolo})
        sess_fall.run(None, {fall_in: dummy_fall})

    # deque
    dq = deque(maxlen=10)

    return picam2, sess_yolo, sess_fall, dq

def forward():
    picam2, sess_yolo, sess_fall, dq = init()

    print("=== Pi B 시작 ===")
    
    while True:    
        ok, frame = read_frame(picam2)

        if not ok:
            print("카메라를 통한 읽기에서 문제가 발생했습니다.")
            return
        
        # infer_ms를 위한 time.perf_counter()
        t0 = time.perf_counter()

        lb, ratio, (padl, padt), x = preprocess(frame)
        raw_onnx = sess_yolo.run(None, {"images": x})[0] 

        feature, people, pose_conf = postprocess(raw_onnx, padl, padt, ratio, dq)

        if len(dq) == 10:
            r_onnx = sess_fall.run(None, {"input.1": feature})[0]

            exp_logits = np.exp(r_onnx - np.max(r_onnx, axis=1, keepdims=True))
            probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
            fall_prob = float(probs[0, 1])
            is_fall = bool(fall_prob > 0.5)

            infer_ms = int((time.perf_counter() - t0) * 1000)
            
            mqtt_client(
                people=people,
                lying=is_fall,
                lying_sec=0.0,
                signal={"fall":is_fall},
                conf=pose_conf,
                infer_ms=infer_ms
            )

if __name__ == "__main__":
    forward()


"""
def show(imgs, titles=None, cols=4, size=3.2):
    imgs = list(imgs); rows = (len(imgs) + cols - 1) // cols
    plt.figure(figsize=(size * min(cols, len(imgs)), size * rows))
    for i, im in enumerate(imgs):
        plt.subplot(rows, min(cols, len(imgs)), i + 1); plt.imshow(im); plt.axis("off")
        if titles is not None: plt.title(titles[i], fontsize=9)
    plt.tight_layout(); plt.show()

def asdf():
    cap = cv2.VideoCapture(VIDEO)
    V_FPS, V_N = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    V_W, V_H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 200)
    
    for _ in range(20):
        ok, f = cap.read()
    cap.release()

    if not ok:
        print("cap.read() 실패")
        return
    
    print(f"{VIDEO}: {V_W}x{V_H}, {V_FPS:.0f} FPS, {V_N} 프레임 ({V_N / V_FPS:.1f} 초)")

    return f
"""