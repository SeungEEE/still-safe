import os
from src.preprocess import convert_to_10fps, load_frames_and_labels, extract_keypoints, extract_math_features
from src.config import *
from ultralytics import YOLO
import numpy as np
import glob

# DATA_DIR = "/kaggle/input/falldataset-imvia"
# CLEAN_DIR = "/content/clean_videos"
# ex) vid_path = '/kaggle/input/falldataset-imvia/Coffee_room_01/Coffee_room_01/Videos/video (1).avi'

def Custom_Le2i(vid_path):

  # -----------------------------------------------------------------------
  # 0. 기본 준비
  # -----------------------------------------------------------------------

  # annotation파일 경로
  ann_path = vid_path.replace('Videos', 'Annotation_files').replace('.avi', '.txt')

  # 상대경로로 바꾼 후 .mp4로 변환
  # ex) 'Coffee_room_01/Coffee_room_01/Videos/video (1).mp4' 이렇게 나옴
  rel_path = os.path.relpath(vid_path, DATA_DIR).replace(".avi", ".mp4")

  # CLEAN_DIR에다가 rel_path붙임
  # ex) '/content/clean_videos/Coffee_room_01/Coffee_room_01/Videos/video (1).mp4' 이렇게 나옴
  out_path = os.path.join(CLEAN_DIR, rel_path)

  model = YOLO("yolo11n-pose.pt")

  # -----------------------------------------------------------------------
  # 1. Le2i 영상의 오디오 제거 및 10fps로 변환
  # -----------------------------------------------------------------------

  convert_to_10fps(vid_path, out_path)

  # -----------------------------------------------------------------------
  # 2. frame과 Annotation_files추출
  # -----------------------------------------------------------------------

  data_frames, data_labels = load_frames_and_labels(vid_path, out_path, ann_path)

  # -----------------------------------------------------------------------
  # 3. 관절좌표 추출
  # -----------------------------------------------------------------------

  kpts_seq = extract_keypoints(data_frames, model)

  # -----------------------------------------------------------------------
  # 4. 수학 수식 적용
  # -----------------------------------------------------------------------

  feats = extract_math_features(kpts_seq)

  return data_labels, feats

vid_files = sorted(glob.glob(f"{DATA_DIR}/**/*.avi", recursive=True))

for vid_file in vid_files:
  data_labels, feats = Custom_Le2i(vid_file)
  
  print(f"{vid_file} 완료.")
  print(np.array(data_labels).shape, feats.shape)
  print()