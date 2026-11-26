import cv2
import numpy as np
from collections import deque

def extract_math_features(kpts_seq, prev_head_y=None, return_state=False):
    T = len(kpts_seq)
    feats = np.zeros((T, 38), dtype=np.float32)

    for t in range(T):
        kpts = kpts_seq[t]
        xy = kpts[:, :2]
        conf = kpts[:, 2]

        if np.sum(conf > 0.3) < 4:
            prev_head_y = None
            continue

        shoulder = (xy[5] + xy[6]) * 0.5
        hip = (xy[11] + xy[12]) * 0.5
        ankle = (xy[15] + xy[16]) * 0.5

        torso_vec = shoulder - hip
        torso_len = np.linalg.norm(torso_vec)
        if torso_len < 1e-3:
            prev_head_y = None
            continue

        norm_xy = (xy - hip) / torso_len
        feats[t, :34] = norm_xy.flatten()

        dx, dy = torso_vec[0], torso_vec[1]
        torso_angle = np.arctan2(abs(dx), max(-dy, 1e-3))

        valid_xy = xy[conf > 0.3]
        w = np.max(valid_xy[:, 0]) - np.min(valid_xy[:, 0])
        h = np.max(valid_xy[:, 1]) - np.min(valid_xy[:, 1])
        aspect_ratio = h / (w + 1e-6)

        head_y = xy[0, 1] if conf[0] > 0.3 else shoulder[1]
        vy = (head_y - prev_head_y) / torso_len if prev_head_y is not None else 0.0
        prev_head_y = head_y

        rel_height = (ankle[1] - shoulder[1]) / torso_len
        feats[t, 34:] = [torso_angle, aspect_ratio, vy, rel_height]

    if return_state:
        return feats, prev_head_y
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

def postprocess(raw_onnx, padl, padt, ratio, dq, prev_head_y=None):
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

    feats, next_head_y = extract_math_features(
        best_kpts[None, ...], prev_head_y=prev_head_y, return_state=True
    )
    feat_38 = feats[0]
    dq.append(feat_38)

    geom = {
        "valid": people > 0 and float(np.sum(feat_38 != 0)) > 0,
        "norm_xy": feat_38[:34].reshape(17, 2),
        "torso_deg": float(np.degrees(feat_38[34])),
        "aspect_ratio": float(feat_38[35]),
    }

    if len(dq) < 10:
        return None, people, pose_conf, geom, next_head_y

    feature = np.array(dq, dtype=np.float32).T[None, ...]  # (1, 38, 10)
    return feature, people, pose_conf, geom, next_head_y