from ultralytics import YOLO

teacher = YOLO(
    "configs/hand/teacher/yolo11x-seg.pt"
)

teacher.train(
    data="datasets/hand/processed/data.yaml",
    epochs=100,
    imgsz=640,
    batch=2,
    device=0,
    amp=True,
    seed=42,
    project="results/hand",
    name="teacher"
)