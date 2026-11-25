import torch
from Fall1DCNN import Fall1DCNN
import onnx
import onnxruntime as ort
from ultralytics import YOLO

def export_onnx():
    YOLO("yolo11n-pose.pt").export(format="onnx", imgsz=320, opset=17)

    model = Fall1DCNN()
    model.eval()
    dummy = torch.randn(1, 38, 10)
    print("model(dummy) =", model(dummy).detach().numpy())
    torch.onnx.export(model, dummy, "fall1dcnn.onnx", dynamo=False)

export_onnx()

# 2026-11-25 임시 ONNX 만들기 끝

# print("저장:", "fall1dcnn.onnx")

# m = onnx.load("fall1dcnn.onnx")

# onnx.checker.check_model(m)

# sess = ort.InferenceSession("fall1dcnn.onnx", providers=["CPUExecutionProvider"])

# print("사용 provider: ", sess.get_providers())

# inp = sess.get_inputs()[0]

# in_name = inp.name

# print("이름:", in_name, "| shape:", inp.shape, "| type:", inp.type)