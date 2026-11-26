import cv2
import numpy as np
from collections import deque

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

def iou(box, boxes):
    box = np.asarray(box, float); boxes = np.asarray(boxes, float).reshape(-1, 4)
    x1 = np.maximum(box[0], boxes[:, 0]); y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2]); y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = lambda b: (b[..., 2] - b[..., 0]) * (b[..., 3] - b[..., 1])
    return inter / (area(box) + area(boxes) - inter)

def nms(boxes, scores, iou_thr=0.5):
    boxes = np.asarray(boxes, float); scores = np.asarray(scores, float)
    order = np.argsort(-scores)                 # 점수 높은 순
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        rest = order[1:]
        order = rest[iou(boxes[i], boxes[rest]) <= iou_thr]      # 많이 겹치는 박스는 지운다
    return np.array(keep, dtype=int)

def decode_pose_yolo(out, conf_thr=0.25, iou_thr=0.7):
    p = np.asarray(out)[0].T  # (2100, 56)
    boxes_c = p[:, :4]        # (2100, 4) -> cx, cy, w, h
    conf = p[:, 4]            # (2100,)   -> 사람 신뢰도 점수
    kpts = p[:, 5:].reshape(-1, 17, 3)  # (2100, 17, 3) -> x, y, kpt_conf

    m = conf > conf_thr
    if not np.any(m):
        return np.empty((0, 4)), np.empty((0,)), np.empty((0, 17, 3))

    cx, cy, w, h = boxes_c[m].T
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], 1)
    keep = nms(boxes, conf[m], iou_thr)
    return boxes[keep], conf[m][keep], kpts[m][keep]

def letterbox(img, size=320, color=114):
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nw, nh = round(w * r), round(h * r)
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top, left = (size - nh) // 2, (size - nw) // 2
    out = np.full((size, size, 3), color, dtype=np.uint8)
    out[top:top + nh, left:left + nw] = resized
    return out, r, (left, top)

def preprocess(frame):
    lb, ratio, (padl, padt) = letterbox(frame)
    
    x = (lb[..., ::-1].transpose(2, 0, 1)[None] / 255.0).astype(np.float32)

    return lb, ratio, (padl, padt), x

def postprocess(raw_onnx, padl, padt, ratio, dq):
    boxes, scores, kpts = decode_pose_yolo(raw_onnx)
    people = int(len(boxes))

    if people > 0:
        boxes = (boxes - [padl, padt, padl, padt]) / ratio
        kpts[..., :2] = (kpts[..., :2] - [padl, padt]) / ratio
        best_idx = int(np.argmax(scores))
        best_kpts = kpts[best_idx]
        pose_conf = round(float(scores[best_idx]), 3)
    else:
        best_kpts = np.zeros((17, 3), dtype=np.float32)
        pose_conf = 0.0

    feat_38 = extract_math_features(best_kpts[None, ...])[0]  # (38,)
    dq.append(feat_38)

    # 기하학 상태 판단용 딕셔너리 추출
    geom = {
        "valid": people > 0 and float(np.sum(feat_38 != 0)) > 0,
        "norm_xy": feat_38[:34].reshape(17, 2),
        "torso_deg": float(np.degrees(feat_38[34])),
        "aspect_ratio": float(feat_38[35]),
    }

    if len(dq) < 10:
        return None, people, pose_conf, geom

    feature = np.array(dq, dtype=np.float32).T[None, ...]  # (1, 38, 10)
    return feature, people, pose_conf, geom