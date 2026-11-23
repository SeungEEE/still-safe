import os
import cv2
import numpy as np
import imageio_ffmpeg
import subprocess

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

# -----------------------------------------------------------------------
# 1. Le2i 영상의 오디오 제거 및 10fps로 변환
# -----------------------------------------------------------------------

def convert_to_10fps(vid_path, out_path):
  os.makedirs(os.path.dirname(out_path), exist_ok=True)
  # -an: 오디오 트랙 완전 무시, -r 10: 아예 10 FPS로 리샘플링까지 동시에 처리!
  # cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", vid_path, "-an", "-r", "10", out_path]
  cmd = [FFMPEG_EXE, "-y", "-loglevel", "error", "-i", vid_path, "-an", "-r", "10", out_path]
  subprocess.run(cmd)

# -----------------------------------------------------------------------
# 2. frame과 Annotation_files추출
# -----------------------------------------------------------------------

def load_frames_and_labels(vid_path, out_path, ann_path):
  cap = cv2.VideoCapture(out_path)
  orig_fps = cv2.VideoCapture(vid_path).get(cv2.CAP_PROP_FPS) # 원본 fps가 나옴.
  trans_fps = 10
  total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) # 변환된 영상의 총 프레임

  data_frames = []
  data_labels = []

  trans_idx = 0

  with open(ann_path, encoding="utf-8", errors="ignore") as f:
      lines = [line.strip() for line in f if line.strip()]

  fall_start_idx = int(lines[0])
  fall_end_idx = int(lines[1])

  while True:
    ret, frame = cap.read()
    if not ret:
      break

    orig_idx = int(round((trans_idx + 1) * orig_fps / trans_fps))

    data_frames.append(frame)
    data_labels.append(1 if (fall_start_idx <= orig_idx <= fall_end_idx) else 0)

    trans_idx += 1

  cap.release()

  return data_frames, data_labels

def extract_keypoints(data_frames, model):
  kpts_seq = []

  for frame in data_frames:
    result = model(frame, verbose=False)[0]
    kpts = result.keypoints.data.cpu().numpy()

    if result.keypoints is None or len(kpts) == 0:
      kpts_seq.append(np.zeros((17, 3), dtype=np.float32))
    elif len(kpts) == 1:
      kpts_seq.append(kpts[0])
    else:
      bext_idx = np.argmax(int(result.boxes.conf.argmax().item()))
      kpts_seq.append(kpts[bext_idx])

  return np.array(kpts_seq, dtype=np.float32)

# -----------------------------------------------------------------------
# 3. 관절좌표 추출
# -----------------------------------------------------------------------

def extract_math_features(kpts_seq):
    """
    kpts_seq: (T, 17, 3) -> [x, y, conf]
    반환: (T, 38) float32
      - [0:34]  골반 중심 기준 & 척추 길이 정규화된 17개 관절 (x, y) 좌표
      - [34]    몸통 기울기 각도 (rad, 수직=0, 수평=pi/2)
      - [35]    높이 대비 너비 비율 (H / W, 서있음>2, 누움<1)
      - [36]    척추 길이 정규화 하강 속도 (vy, 양수=아래로 낙하)
      - [37]    상체 중심(어깨) 상대 높이 비율 ((발목_y - 어깨_y) / 척추길이)
    """
    T = len(kpts_seq)
    feats = np.zeros((T, 38), dtype=np.float32)
    prev_head_y = None

    for t in range(T):
        kpts = kpts_seq[t]
        xy = kpts[:, :2]
        conf = kpts[:, 2]

        # 1. 사람이 감지되지 않은 프레임(0 벡터) 예외 처리
        if np.sum(conf > 0.3) < 4:
            prev_head_y = None
            continue

        # 2. 주요 신체 중심점 계산 (COCO 17 관절 인덱스)
        # 0: 코, 5-6: 어깨, 11-12: 엉덩이(골반), 15-16: 발목
        shoulder = (xy[5] + xy[6]) * 0.5
        hip = (xy[11] + xy[12]) * 0.5
        ankle = (xy[15] + xy[16]) * 0.5

        # 척추 벡터 (골반 -> 어깨) 및 척추 길이 (정규화 기준 스케일)
        torso_vec = shoulder - hip
        torso_len = np.linalg.norm(torso_vec)
        if torso_len < 1e-3:
            prev_head_y = None
            continue

        # 3. 위치·크기 불변 정규화 관절 좌표 (34차원)
        norm_xy = (xy - hip) / torso_len
        feats[t, :34] = norm_xy.flatten()

        # 4. 도메인 수학 수식 피처 4개
        # ① 몸통 기울기 각도 (수직선 대비 각도, 이미지 y축은 아래가 +이므로 -dy 사용)
        dx, dy = torso_vec[0], torso_vec[1]
        torso_angle = np.arctan2(abs(dx), max(-dy, 1e-3))

        # ② 사람 바운딩 박스 높이/너비 비율 (H / W)
        valid_xy = xy[conf > 0.3]
        w = np.max(valid_xy[:, 0]) - np.min(valid_xy[:, 0])
        h = np.max(valid_xy[:, 1]) - np.min(valid_xy[:, 1])
        aspect_ratio = h / (w + 1e-6)

        # ③ 0.1초(10 FPS) 간격 정규화 수직 하강 속도 (머리/어깨 기준)
        head_y = xy[0, 1] if conf[0] > 0.3 else shoulder[1]
        if prev_head_y is not None:
            vy = (head_y - prev_head_y) / torso_len
        else:
            vy = 0.0
        prev_head_y = head_y

        # ④ 발목 대비 어깨 상대 높이 비율
        rel_height = (ankle[1] - shoulder[1]) / torso_len

        feats[t, 34:] = [torso_angle, aspect_ratio, vy, rel_height]

    return feats