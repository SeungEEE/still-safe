import numpy as np

def get_joint_center(xy: np.ndarray, conf: np.ndarray, i1: int, i2: int, thr: float = 0.3):
    """양쪽 관절이 모두 보이면 중점, 한쪽만 보이면 해당 관절 좌표 반환"""
    v1, v2 = conf[i1] > thr, conf[i2] > thr
    if v1 and v2:
        return (xy[i1] + xy[i2]) * 0.5, True
    if v1:
        return xy[i1], True
    if v2:
        return xy[i2], True
    return None, False


def extract_math_features(kpts_seq: np.ndarray, prev_head_y=None, return_state: bool = False):
    """
    kpts_seq: (T, 17, 3) -> [x, y, conf]
    반환: (T, 38) float32  (return_state=True 시 (feats, prev_head_y) 반환)
    """
    T = len(kpts_seq)
    feats = np.zeros((T, 38), dtype=np.float32)
    conf_thr = 0.3

    for t in range(T):
        kpts = kpts_seq[t]
        xy, conf = kpts[:, :2], kpts[:, 2]

        if np.sum(conf > conf_thr) < 4:
            prev_head_y = None
            continue

        shoulder, ok_s = get_joint_center(xy, conf, 5, 6, conf_thr)
        hip, ok_h      = get_joint_center(xy, conf, 11, 12, conf_thr)
        ankle, ok_a    = get_joint_center(xy, conf, 15, 16, conf_thr)

        if not (ok_s and ok_h):
            prev_head_y = None
            continue

        torso_vec = shoulder - hip
        torso_len = float(np.linalg.norm(torso_vec))
        if torso_len < 1e-3:
            prev_head_y = None
            continue

        # [0:34] 골반 중심 & 척추 길이 정규화 좌표 (미검출 관절 0 마스킹)
        norm_xy = (xy - hip) / torso_len
        norm_xy[conf <= conf_thr] = 0.0
        feats[t, :34] = np.clip(norm_xy, -5.0, 5.0).flatten()

        # [34:38] 몸통 각도, 종횡비(H/W), 하강 속도(vy), 상대 높이 비율
        dx, dy = float(torso_vec[0]), float(torso_vec[1])
        torso_angle = float(np.arctan2(abs(dx), max(-dy, 1e-3)))

        valid_xy = xy[conf > conf_thr]
        w = float(np.max(valid_xy[:, 0]) - np.min(valid_xy[:, 0]))
        h = float(np.max(valid_xy[:, 1]) - np.min(valid_xy[:, 1]))
        aspect_ratio = float(np.clip(h / (w + 1e-6), 0.0, 10.0))

        head_y = float(xy[0, 1]) if conf[0] > conf_thr else float(shoulder[1])
        vy = float(np.clip((head_y - prev_head_y) / torso_len, -5.0, 5.0)) if prev_head_y is not None else 0.0
        prev_head_y = head_y

        rel_height = float(np.clip((ankle[1] - shoulder[1]) / torso_len, -5.0, 5.0)) if ok_a else 0.0
        feats[t, 34:] = [torso_angle, aspect_ratio, vy, rel_height]

    if return_state:
        return feats, prev_head_y
    return feats