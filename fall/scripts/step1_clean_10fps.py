import os
import glob
import subprocess
import cv2
import numpy as np
import imageio_ffmpeg
from tqdm import tqdm
import re

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.path.join(ROOT_DIR, "data")
RAW_DIR = os.path.join(DATA_ROOT, "raw_le2i")
CLEAN_VID_DIR = os.path.join(DATA_ROOT, "1_clean_10fps")
PROCESSED_DIR = os.path.join(DATA_ROOT, "processed")

os.makedirs(CLEAN_VID_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)


def get_orig_fps(vid_path: str) -> float:
    """ffmpeg -i 헤더 출력에서 정규식으로 원본 FPS만 안전하게 추출"""
    res = subprocess.run(
        [FFMPEG_EXE, "-hide_banner", "-i", vid_path],
        capture_output=True, text=True, encoding="utf-8", errors="ignore"
    )
    # 출력 예: "Stream #0:0: Video: mpeg4 ..., 320x240, 25 fps, 25 tbr"
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", res.stderr)
    return float(m.group(1)) if m else 0.0


def get_fall_range(vid_path: str) -> tuple[int, int]:
    norm_path = vid_path.replace(os.sep, "/")
    candidates = [
        norm_path.replace("/Videos/", "/Annotation_files/").replace(".avi", ".txt"),
        norm_path.replace("/Videos/", "/Annotations_files/").replace(".avi", ".txt"),
    ]
    ann_path = next((p for p in candidates if os.path.exists(p)), None)
    if ann_path is None:
        return 0, 0
    with open(ann_path, encoding="utf-8", errors="ignore") as f:
        lines = [line.strip() for line in f if line.strip()]
    if len(lines) < 2:
        return 0, 0
    try:
        return int(lines[0]), int(lines[1])
    except ValueError:
        return 0, 0


def main():
    if not os.path.exists(RAW_DIR):
        raise FileNotFoundError(f"데이터 폴더가 없습니다: {RAW_DIR}")

    vid_files = sorted(glob.glob(os.path.join(RAW_DIR, "**", "*.avi"), recursive=True))
    print(f"원본 영상 발견: {len(vid_files)}개")

    stage1_dict = {}
    clean_paths, rel_paths = [], []
    idx = 0
    fall_vid_count = 0

    for vid_path in tqdm(vid_files, desc="1단계: 10FPS 정제 및 라벨 매칭"):
        orig_fps = get_orig_fps(vid_path)
        if orig_fps <= 0:
            continue

        rel_path = os.path.relpath(vid_path, RAW_DIR).replace(".avi", ".mp4")
        out_path = os.path.join(CLEAN_VID_DIR, rel_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            subprocess.run(
                [FFMPEG_EXE, "-y", "-loglevel", "error", "-i", vid_path,
                 "-an", "-r", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path],
                check=False
            )

        fall_start, fall_end = get_fall_range(vid_path)
        cap = cv2.VideoCapture(out_path)
        labels = []
        t_idx = 0
        while True:
            ret, _ = cap.read()
            if not ret:
                break
            orig_idx = int(round(t_idx * (orig_fps / 10.0))) + 1
            labels.append(1 if (fall_start > 0 and fall_start <= orig_idx <= fall_end) else 0)
            t_idx += 1
        cap.release()

        if len(labels) < 10:
            continue

        y_arr = np.array(labels, dtype=np.int64)
        if np.sum(y_arr) > 0:
            fall_vid_count += 1

        stage1_dict[f"y_{idx}"] = y_arr
        clean_paths.append(out_path)
        rel_paths.append(rel_path)
        idx += 1

    stage1_dict["n_videos"] = np.array(idx)
    stage1_dict["clean_paths"] = np.array(clean_paths)
    stage1_dict["rel_paths"] = np.array(rel_paths)

    out_npz = os.path.join(PROCESSED_DIR, "stage1_meta.npz")
    np.savez_compressed(out_npz, **stage1_dict)
    print(f"1단계 완료: 총 {idx}개 (낙상 포함 {fall_vid_count}개 / 정상 전용 {idx - fall_vid_count}개) -> {out_npz}")


if __name__ == "__main__":
    main()