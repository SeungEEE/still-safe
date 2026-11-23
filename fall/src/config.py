import os

# 1. 프로젝트 루트 경로 자동 계산 (윈도우 · 리눅스 어디서든 동일 동작)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 2. 데이터 및 모델 경로
DATA_DIR = os.path.join(BASE_DIR, "data", "raw_le2i")
CLEAN_DIR = os.path.join(BASE_DIR, "data", "clean_videos")
PROCESSED_PATH = os.path.join(BASE_DIR, "data", "processed", "le2i_10fps.npz")

MODEL_DIR = os.path.join(BASE_DIR, "models")
POSE_MODEL_PATH = os.path.join(MODEL_DIR, "yolo11n-pose.pt")
FALL_ONNX_PATH = os.path.join(MODEL_DIR, "fall_conv1d.onnx")

# 3. 시계열 및 피처 하이퍼파라미터 (학습 & 라즈베리파이 추론 공통 기준)
TARGET_FPS = 10
WINDOW_SIZE = 10       # 1.0초 (10 FPS * 1초)
STRIDE = 2             # 학습 시 슬라이딩 간격 (0.2초)
NUM_FEATURES = 38      # 정규화 관절 34 + 수학 피처 4
CONF_THRESH = 0.3      # 관절 유효 신뢰도 임계값