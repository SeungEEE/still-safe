import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSE_ONNX = os.path.join(BASE_DIR, "onnx", "yolo11n-pose.onnx")
FALL_ONNX = os.path.join(BASE_DIR, "onnx", "fall1dcnn.onnx")

BROKER_IP = "192.168.20.21"
BROKER_PORT = 1883
BROKER_TOPIC = "stillsafe/fall"

VIDEO = 0