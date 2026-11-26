import os
import sys
import numpy as np
import torch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.model import Fall1DCNN
from src.preprocess import extract_math_features

STAGE2_PATH = os.path.join(ROOT_DIR, "data", "processed", "stage2_keypoints.npz")
PT_PATH = os.path.join(ROOT_DIR, "models", "fall_1dcnn.pt")


def get_test_video_ids(s2):
    """step3_build_dataset.py와 동일한 seed=42 분할로 Test 영상 ID 복원"""
    n_videos = int(s2["n_videos"])
    y_seqs = [s2[f"y_{i}"] for i in range(n_videos)]

    fall_ids = [i for i in range(n_videos) if np.sum(y_seqs[i]) > 0]
    norm_ids = [i for i in range(n_videos) if np.sum(y_seqs[i]) == 0]
    rng = np.random.default_rng(42)
    rng.shuffle(fall_ids)
    rng.shuffle(norm_ids)

    def _test_slice(ids):
        n_tr, n_va = int(len(ids) * 0.7), int(len(ids) * 0.15)
        return ids[n_tr + n_va :]

    return _test_slice(fall_ids) + _test_slice(norm_ids)


@torch.no_grad()
def evaluate_video_events(model, feats, labels, thr=0.70, trigger_streak=2):
    """
    라즈베리파이 실시간 추론과 동일하게 1프레임씩 밀면서
    연속 trigger_streak 이상 양성 시 낙상 이벤트 확정
    """
    T = len(feats)
    streak = 0
    detected_frames = []

    for t in range(9, T):
        win = feats[t - 9 : t + 1].T[None, ...]  # (1, 38, 10)
        logits = model(torch.from_numpy(win).float())
        prob = float(torch.softmax(logits, dim=1)[0, 1].item())

        if prob >= thr:
            streak += 1
        else:
            streak = 0

        if streak >= trigger_streak:
            detected_frames.append(t)

    has_gt_fall = bool(np.sum(labels) > 0)
    pred_fall = len(detected_frames) > 0

    # 실제 낙상 구간(±10프레임 여유) 안에 감지가 포함되었는지 확인
    if has_gt_fall:
        fall_indices = np.where(labels == 1)[0]
        gt_start, gt_end = int(fall_indices[0]), int(fall_indices[-1])
        in_range = any((gt_start - 5) <= f <= (gt_end + 15) for f in detected_frames)
        return has_gt_fall, in_range, detected_frames
    else:
        return has_gt_fall, pred_fall, detected_frames


def main():
    s2 = np.load(STAGE2_PATH, allow_pickle=True)
    rel_paths = s2["rel_paths"]
    test_ids = get_test_video_ids(s2)

    ckpt = torch.load(PT_PATH, map_location="cpu", weights_only=True)
    model = Fall1DCNN(in_channels=38, num_classes=2)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    saved_thr = ckpt["threshold"]

    print(f"총 Test 영상 수: {len(test_ids)}개 (저장된 최적 threshold={saved_thr:.2f})\n")

    for thr in [0.55, 0.60, saved_thr]:
        tp_vid, fn_vid, fp_vid, tn_vid = 0, 0, 0, 0
        missed_list, false_alarm_list = [], []

        for vid_id in test_ids:
            feats = extract_math_features(s2[f"kpts_{vid_id}"])
            labels = s2[f"y_{vid_id}"]
            name = str(rel_paths[vid_id])

            has_gt, hit, det_frames = evaluate_video_events(
                model, feats, labels, thr=thr, trigger_streak=2
            )

            if has_gt:
                if hit:
                    tp_vid += 1
                else:
                    fn_vid += 1
                    missed_list.append(name)
            else:
                if hit:
                    fp_vid += 1
                    false_alarm_list.append((name, det_frames))
                else:
                    tn_vid += 1

        ev_rec = tp_vid / max(tp_vid + fn_vid, 1) * 100
        ev_prec = tp_vid / max(tp_vid + fp_vid, 1) * 100
        ev_f1 = 2 * ev_prec * ev_rec / max(ev_prec + ev_rec, 1e-6)

        print(f"=== [영상(이벤트) 단위 평가 | thr={thr:.2f}, streak=2] ===")
        print(f"- 영상 단위 Recall   : {ev_rec:.1f}% ({tp_vid}/{tp_vid + fn_vid}개 낙상 영상 감지)")
        print(f"- 영상 단위 Precision: {ev_prec:.1f}% (정상 영상 오경보 {fp_vid}/{fp_vid + tn_vid}개)")
        print(f"- 영상 단위 F1-Score : {ev_f1:.2f}%")
        if missed_list:
            print(f"  * 놓친 낙상 영상   : {missed_list}")
        if false_alarm_list:
            print(f"  * 오경보 정상 영상 : {[x[0] for x in false_alarm_list]}")
        print()


if __name__ == "__main__":
    main()