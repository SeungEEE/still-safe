from ultralytics import YOLO

student = YOLO(
    "configs/hand/student/yolo11n-seg.pt"
)

student.train(
    data="datasets/hand/processed/data.yaml",
    epochs=100,
    imgsz=640,
    batch=2,
    device=0,
    amp=True,
    seed=42,
    project="results/hand",
    name="baseline"
)