import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSE_ONNX = os.path.join(BASE_DIR, "onnx", "yolo11n-pose.onnx")
FALL_ONNX = os.path.join(BASE_DIR, "onnx", "fall1dcnn.onnx")

TEST_DATA = os.path.join(BASE_DIR, "data", "video (1).mp4")

BROKER_IP = "127.0.0.1"
BROKER_PORT = 1883
BROKER_TOPIC = "stillsafe/fall"

VIDEO = 0