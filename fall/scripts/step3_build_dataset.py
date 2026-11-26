import os
import sys
import numpy as np

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.preprocess import extract_math_features

PROCESSED_DIR = os.path.join(ROOT_DIR, "data", "processed")


def build_sliding_windows(X_list, y_list, window_size=10, stride=2, min_fall_frames=3):
    X_win, y_win = [], []
    for X, y in zip(X_list, y_list):
        for s in range(0, len(X) - window_size + 1, stride):
            wx = X[s : s + window_size]       # (10, 38)
            wy = y[s : s + window_size]       # (10,)
            label = 1 if (np.sum(wy == 1) >= min_fall_frames or wy[-1] == 1) else 0
            X_win.append(wx.T)                # (38, 10)
            y_win.append(label)
    return np.array(X_win, dtype=np.float32), np.array(y_win, dtype=np.int64)


def main():
    s2 = np.load(os.path.join(PROCESSED_DIR, "stage2_keypoints.npz"), allow_pickle=True)
    n_videos = int(s2["n_videos"])

    X_seqs = [extract_math_features(s2[f"kpts_{i}"]) for i in range(n_videos)]
    y_seqs = [s2[f"y_{i}"] for i in range(n_videos)]

    fall_ids = [i for i in range(n_videos) if np.sum(y_seqs[i]) > 0]
    norm_ids = [i for i in range(n_videos) if np.sum(y_seqs[i]) == 0]
    rng = np.random.default_rng(42)
    rng.shuffle(fall_ids)
    rng.shuffle(norm_ids)

    def _split(ids):
        n_tr, n_va = int(len(ids) * 0.7), int(len(ids) * 0.15)
        return ids[:n_tr], ids[n_tr : n_tr + n_va], ids[n_tr + n_va :]

    f_tr, f_va, f_te = _split(fall_ids)
    n_tr, n_va, n_te = _split(norm_ids)
    tr_ids, va_ids, te_ids = f_tr + n_tr, f_va + n_va, f_te + n_te

    X_train, y_train = build_sliding_windows([X_seqs[i] for i in tr_ids], [y_seqs[i] for i in tr_ids], stride=2)
    X_val,   y_val   = build_sliding_windows([X_seqs[i] for i in va_ids], [y_seqs[i] for i in va_ids], stride=2)
    X_test,  y_test  = build_sliding_windows([X_seqs[i] for i in te_ids], [y_seqs[i] for i in te_ids], stride=1)

    out_npz = os.path.join(PROCESSED_DIR, "stage3_dataset.npz")
    np.savez_compressed(
        out_npz,
        X_train=X_train, y_train=y_train,
        X_val=X_val,     y_val=y_val,
        X_test=X_test,   y_test=y_test,
    )

    print(f"3단계 완료: 최종 데이터셋 저장 -> {out_npz}")
    for name, X_arr, y_arr in [("Train", X_train, y_train), ("Val", X_val, y_val), ("Test", X_test, y_test)]:
        print(f"  [{name:5s}] X={X_arr.shape}, y={y_arr.shape} | 낙상 비율: {y_arr.mean() * 100:.2f}%")


if __name__ == "__main__":
    main()