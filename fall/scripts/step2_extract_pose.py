import os
import cv2
import numpy as np
from tqdm import tqdm
from ultralytics import YOLO

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.path.join(ROOT_DIR, "data")
VIS_VID_DIR = os.path.join(DATA_ROOT, "2_pose_vis")
PROCESSED_DIR = os.path.join(DATA_ROOT, "processed")
os.makedirs(VIS_VID_DIR, exist_ok=True)

# 시각화 영상 저장 여부 (전체 190개 저장: True / 관절 추출만 빠르게: False)
SAVE_VIS = True

SKELETON = [
    (0, 1), (0, 2), (1, 3), (2, 4),
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16)
]


def draw_pose_and_label(frame: np.ndarray, kpts: np.ndarray, label: int, frame_idx: int) -> np.ndarray:
    vis = frame.copy()
    is_fall = (label == 1)
    color = (0, 0, 255) if is_fall else (0, 220, 0)
    status_text = f"Frame {frame_idx:03d} | {'FALL (1)' if is_fall else 'NORMAL (0)'}"

    for i, j in SKELETON:
        if kpts[i, 2] > 0.3 and kpts[j, 2] > 0.3:
            pt1 = (int(kpts[i, 0]), int(kpts[i, 1]))
            pt2 = (int(kpts[j, 0]), int(kpts[j, 1]))
            cv2.line(vis, pt1, pt2, color, 2)

    for k in range(17):
        if kpts[k, 2] > 0.3:
            cv2.circle(vis, (int(kpts[k, 0]), int(kpts[k, 1])), 3, (255, 255, 0), -1)

    cv2.rectangle(vis, (5, 5), (270, 32), (0, 0, 0), -1)
    cv2.putText(vis, status_text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    return vis


def main():
    pose_model = YOLO("yolo11n-pose.pt")
    s1 = np.load(os.path.join(PROCESSED_DIR, "stage1_meta.npz"), allow_pickle=True)
    n_videos = int(s1["n_videos"])
    clean_paths = s1["clean_paths"]
    rel_paths = s1["rel_paths"]

    stage2_dict = {}
    valid_rel_paths = []
    valid_idx = 0

    for i in tqdm(range(n_videos), desc="2단계: 관절 추출 및 시각화 영상 생성"):
        vid_path = str(clean_paths[i])
        rel_path = str(rel_paths[i])
        labels = s1[f"y_{i}"]

        cap = cv2.VideoCapture(vid_path)
        frames = []
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
        cap.release()

        if len(frames) == 0:
            continue

        kpts_seq = []
        for b in range(0, len(frames), 16):
            results = pose_model(
                frames[b : b + 16], imgsz=320, conf=0.25, iou=0.7, device="cpu", verbose=False
            )
            for res in results:
                if res.keypoints is None or res.boxes is None or len(res.boxes) == 0:
                    kpts_seq.append(np.zeros((17, 3), dtype=np.float32))
                    continue
                kpts = res.keypoints.data.cpu().numpy()
                best_idx = int(res.boxes.conf.argmax().item()) if len(kpts) > 1 else 0
                kpts_seq.append(kpts[best_idx] if len(kpts) > 0 else np.zeros((17, 3), dtype=np.float32))

        kpts_seq = np.array(kpts_seq, dtype=np.float32)
        stage2_dict[f"kpts_{valid_idx}"] = kpts_seq
        stage2_dict[f"y_{valid_idx}"] = labels[: len(kpts_seq)]
        valid_rel_paths.append(rel_path)
        valid_idx += 1

        if SAVE_VIS:
            vis_out_path = os.path.join(VIS_VID_DIR, rel_path)
            os.makedirs(os.path.dirname(vis_out_path), exist_ok=True)
            h, w = frames[0].shape[:2]
            writer = cv2.VideoWriter(vis_out_path, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (w, h))
            for t, (frm, kpt, lbl) in enumerate(zip(frames, kpts_seq, labels)):
                writer.write(draw_pose_and_label(frm, kpt, int(lbl), t))
            writer.release()

    stage2_dict["n_videos"] = np.array(valid_idx)
    stage2_dict["rel_paths"] = np.array(valid_rel_paths)

    out_npz = os.path.join(PROCESSED_DIR, "stage2_keypoints.npz")
    np.savez_compressed(out_npz, **stage2_dict)
    print(f"2단계 완료 ({valid_idx}개): 관절 저장({out_npz}) 및 시각화 영상({VIS_VID_DIR}) 생성 완료")


if __name__ == "__main__":
    main()