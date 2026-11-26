import os
import time
import argparse
from collections import deque
import cv2
import numpy as np
import onnxruntime as ort

from config import *
import process as proc
from FallStateTracker import *

# COCO 17 관절 뼈대 연결 쌍
SKELETON = [
    (0, 1), (0, 2), (1, 3), (2, 4),
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
]


def fallback_letterbox(img, size=320, color=114):
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top, left = (size - nh) // 2, (size - nw) // 2
    out = np.full((size, size, 3), color, dtype=np.uint8)
    out[top : top + nh, left : left + nw] = resized
    x = out[..., ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    return out, r, (left, top), x


def get_best_kpts_xy_conf(raw_onnx, padl, padt, ratio, conf_thr=0.25):
    """
    (1, 56, 2100) 형태의 YOLO Pose 출력에서 가장 신뢰도 높은 1명의 (17, 3) [x, y, conf] 복원
    """
    if hasattr(proc, "decode_pose_yolo"):
        boxes, scores, kpts = proc.decode_pose_yolo(raw_onnx)
        if len(kpts) > 0:
            kpts = kpts.copy()
            kpts[..., 0] = (kpts[..., 0] - padl) / ratio
            kpts[..., 1] = (kpts[..., 1] - padt) / ratio
            idx = int(np.argmax(scores)) if len(scores) > 0 else 0
            return kpts[idx], len(kpts), float(scores[idx]) if len(scores) > 0 else 0.0

    pred = np.squeeze(raw_onnx, axis=0)  # (56, 2100)
    if pred.shape[0] < 56:
        return None, 0, 0.0

    person_scores = pred[4, :]
    mask = person_scores >= conf_thr
    if not np.any(mask):
        return None, 0, 0.0

    valid_scores = person_scores[mask]
    best_local = int(np.argmax(valid_scores))
    best_col = pred[:, mask][:, best_local]

    kpts_raw = best_col[5:].reshape(17, 3).copy()
    kpts_raw[:, 0] = (kpts_raw[:, 0] - padl) / ratio
    kpts_raw[:, 1] = (kpts_raw[:, 1] - padt) / ratio
    return kpts_raw, int(np.sum(mask)), float(valid_scores[best_local])


def draw_top_left_hud(
    frame: np.ndarray,
    kpts: np.ndarray,
    frame_idx: int,
    sim_sec: float,
    people: int,
    pose_conf: float,
    fall_prob: float,
    is_fall: bool,
    is_lying: bool,
    lying_sec: float,
    motion: float,
    geom: dict,
    infer_ms: int,
) -> np.ndarray:
    canvas = frame.copy()
    h, w = canvas.shape[:2]

    # 상태별 색상 결정 (누움: 빨강 / 낙상 감지: 주황 / 정상: 초록)
    if is_lying:
        state_color = (0, 0, 255)
        state_label = "LYING"
    elif is_fall:
        state_color = (0, 140, 255)
        state_label = "FALL!"
    else:
        state_color = (0, 220, 0)
        state_label = "NORMAL"

    # 1. 관절 및 뼈대 그리기
    if kpts is not None and kpts.shape == (17, 3):
        for i, j in SKELETON:
            if kpts[i, 2] > 0.3 and kpts[j, 2] > 0.3:
                p1 = (int(round(kpts[i, 0])), int(round(kpts[i, 1])))
                p2 = (int(round(kpts[j, 0])), int(round(kpts[j, 1])))
                cv2.line(canvas, p1, p2, state_color, 2)

        for k in range(17):
            if kpts[k, 2] > 0.3:
                kx, ky = int(round(kpts[k, 0])), int(round(kpts[k, 1]))
                cv2.circle(canvas, (kx, ky), 3, (0, 255, 255), -1)

    # 2. 좌측 상단 반투명 HUD 패널 그리기
    panel_w = min(w - 10, 305)
    panel_h = 112
    overlay = canvas.copy()
    cv2.rectangle(overlay, (6, 6), (6 + panel_w, 6 + panel_h), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.72, canvas, 0.28, 0, canvas)
    cv2.rectangle(canvas, (6, 6), (6 + panel_w, 6 + panel_h), state_color, 1)

    torso_deg = float(geom.get("torso_deg", 0.0)) if isinstance(geom, dict) else 0.0
    hw_ratio = float(geom.get("aspect_ratio", 0.0)) if isinstance(geom, dict) else 0.0

    lines = [
        (f"[{state_label}] lying_sec: {lying_sec:5.2f}s | prob: {fall_prob:.2f}", state_color, 0.52, 2),
        (f"F:{frame_idx:04d} ({sim_sec:4.1f}s) | P:{people} | conf:{pose_conf:.2f} | {infer_ms}ms", (235, 235, 235), 0.44, 1),
        (f"is_fall: {str(is_fall):5s} | lying: {str(is_lying):5s} | mot: {motion:.2f}", (210, 230, 255), 0.44, 1),
        (f"Torso: {torso_deg:5.1f} deg | H/W: {hw_ratio:4.2f}", (180, 220, 180), 0.44, 1),
    ]

    y_pos = 24
    for text, color, scale, thick in lines:
        cv2.putText(canvas, text, (14, y_pos), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)
        y_pos += 23

    return canvas


def main():
    parser = argparse.ArgumentParser(description="관절 + 좌측 상단 HUD 시각화 영상 생성기")
    parser.add_argument("-v", "--video", type=str, required=True, help="입력 영상 파일명(BASE_DIR/data 기준) 또는 경로")
    parser.add_argument("-o", "--output", type=str, default="visual_result.mp4", help="저장할 결과 영상 파일명 또는 경로")
    parser.add_argument("--thr", type=float, default=0.70, help="낙상 확률 임계값 (기본 0.70)")
    parser.add_argument("--fps", type=float, default=10.0, help="출력 영상 FPS 및 시간 간격 기준 (기본 10.0)")
    args = parser.parse_args()

    vid_path = args.video if os.path.isabs(args.video) else os.path.join(BASE_DIR, "data", args.video)
    if not os.path.exists(vid_path) and os.path.exists(args.video):
        vid_path = args.video

    out_path = args.output if os.path.isabs(args.output) else os.path.join(BASE_DIR, args.output)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    cap = cv2.VideoCapture(vid_path)
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {vid_path}")

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out_fps = float(args.fps)
    dt = 1.0 / out_fps

    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_yolo = ort.InferenceSession(POSE_ONNX, so, providers=["CPUExecutionProvider"])
    sess_fall = ort.InferenceSession(FALL_ONNX, so, providers=["CPUExecutionProvider"])

    yolo_in = sess_yolo.get_inputs()[0].name
    fall_in = sess_fall.get_inputs()[0].name

    # Warm-up
    for _ in range(3):
        sess_yolo.run(None, {yolo_in: np.zeros((1, 3, 320, 320), dtype=np.float32)})
        sess_fall.run(None, {fall_in: np.zeros((1, 38, 10), dtype=np.float32)})

    tracker = FallStateTracker()
    dq = deque(maxlen=10)
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), out_fps, (w, h))

    frame_idx = 0
    sim_sec = 0.0

    print(f"[시작] 입력: {vid_path} ({w}x{h}) -> 출력: {out_path} ({out_fps} FPS)")

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break

            t0 = time.perf_counter()
            sim_sec += dt

            if hasattr(proc, "preprocess"):
                _, ratio, (padl, padt), x = proc.preprocess(frame)
            else:
                _, ratio, (padl, padt), x = fallback_letterbox(frame, size=320)

            raw_onnx = sess_yolo.run(None, {yolo_in: x})[0]
            kpts, det_people, det_conf = get_best_kpts_xy_conf(raw_onnx, padl, padt, ratio)

            feature, people, pose_conf, geom = proc.postprocess(raw_onnx, padl, padt, ratio, dq)
            if people == 0 and det_people > 0:
                people = det_people
            if pose_conf == 0.0 and det_conf > 0.0:
                pose_conf = det_conf

            fall_prob = 0.0
            is_fall = False
            if feature is not None:
                r_onnx = sess_fall.run(None, {fall_in: feature.astype(np.float32)})[0]
                exp_logits = np.exp(r_onnx - np.max(r_onnx, axis=1, keepdims=True))
                probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
                fall_prob = float(probs[0, 1])
                is_fall = bool(fall_prob > args.thr)

            is_lying, lying_sec, motion = tracker.update(is_fall, geom, sim_sec)
            infer_ms = int((time.perf_counter() - t0) * 1000)

            vis_frame = draw_top_left_hud(
                frame=frame,
                kpts=kpts,
                frame_idx=frame_idx,
                sim_sec=sim_sec,
                people=people,
                pose_conf=pose_conf,
                fall_prob=fall_prob,
                is_fall=is_fall,
                is_lying=is_lying,
                lying_sec=lying_sec,
                motion=motion,
                geom=geom,
                infer_ms=infer_ms,
            )
            writer.write(vis_frame)

            if frame_idx % 10 == 0 or is_lying or is_fall:
                print(
                    f"F{frame_idx:04d} ({sim_sec:4.1f}s) | prob={fall_prob:.2f} | "
                    f"fall={is_fall} | lying={is_lying} ({lying_sec:.2f}s) | {infer_ms}ms"
                )

            frame_idx += 1
    finally:
        cap.release()
        writer.release()
        print(f"[완료] 총 {frame_idx}프레임 저장됨 -> {out_path}")


if __name__ == "__main__":
    main()
