import os
import sys
import inspect
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import onnx
import onnxruntime as ort
from sklearn.metrics import (
    precision_recall_fscore_support,
    average_precision_score,
    confusion_matrix,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.model import Fall1DCNN

DATA_PATH = os.path.join(ROOT_DIR, "data", "processed", "stage3_dataset.npz")
MODEL_DIR = os.path.join(ROOT_DIR, "models")
os.makedirs(MODEL_DIR, exist_ok=True)

PT_PATH = os.path.join(MODEL_DIR, "fall_1dcnn.pt")
ONNX_PATH = os.path.join(MODEL_DIR, "fall_1dcnn.onnx")

FLIP_PAIRS = [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16)]


class WindowDataset(Dataset):
    def __init__(self, X, y, augment=False, flip_prob=0.5, noise_std=0.015):
        self.X = X
        self.y = y
        self.augment = augment
        self.flip_prob = flip_prob
        self.noise_std = noise_std

    def __len__(self):
        return len(self.X)

    def _augment(self, x_ct: np.ndarray) -> np.ndarray:
        # x_ct: (38, 10) -> (10, 38)로 변환해 증강 후 복원
        x = x_ct.T.copy()
        valid_mask = np.any(x != 0, axis=1, keepdims=True)

        if np.random.rand() < self.flip_prob:
            xy = x[:, :34].reshape(-1, 17, 2)
            xy[:, :, 0] = -xy[:, :, 0]
            for l_idx, r_idx in FLIP_PAIRS:
                xy[:, [l_idx, r_idx]] = xy[:, [r_idx, l_idx]]
            x[:, :34] = xy.reshape(-1, 34)

        if self.noise_std > 0:
            noise = np.random.normal(0.0, self.noise_std, size=x.shape).astype(np.float32)
            x = x + noise * valid_mask

        return x.T.copy()

    def __getitem__(self, idx):
        x = self._augment(self.X[idx]) if self.augment else self.X[idx]
        return torch.from_numpy(x).float(), torch.tensor(self.y[idx], dtype=torch.long)


@torch.no_grad()
def predict_probs(model, loader, device):
    model.eval()
    all_probs, all_targets = [], []
    for xb, yb in loader:
        logits = model(xb.to(device))
        probs = torch.softmax(logits, dim=1)[:, 1].cpu().numpy()
        all_probs.append(probs)
        all_targets.append(yb.numpy())
    return np.concatenate(all_probs), np.concatenate(all_targets)


def find_best_threshold(probs, targets):
    best_thr, best_f1 = 0.5, 0.0
    for thr in np.arange(0.20, 0.85, 0.05):
        preds = (probs >= thr).astype(int)
        _, _, f1, _ = precision_recall_fscore_support(
            targets, preds, average="binary", zero_division=0
        )
        if f1 > best_f1:
            best_f1 = f1
            best_thr = float(round(thr, 2))
    return best_thr, best_f1


def export_and_verify_onnx(model, onnx_path):
    model_cpu = model.to("cpu").eval()
    dummy_input = torch.randn(1, 38, 10, dtype=torch.float32)

    export_kw = {"dynamo": False} if "dynamo" in inspect.signature(torch.onnx.export).parameters else {}
    torch.onnx.export(
        model_cpu,
        dummy_input,
        onnx_path,
        export_params=True,
        opset_version=17,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        **export_kw,
    )

    onnx_model = onnx.load(onnx_path)
    onnx.checker.check_model(onnx_model)

    # PyTorch vs ONNX Runtime 수치 일치 검증
    test_x = np.random.randn(8, 38, 10).astype(np.float32)
    with torch.no_grad():
        pt_out = model_cpu(torch.from_numpy(test_x)).numpy()

    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    ort_out = sess.run(None, {"input": test_x})[0]
    max_diff = float(np.max(np.abs(pt_out - ort_out)))

    size_kb = os.path.getsize(onnx_path) / 1024
    print(f"\n[ONNX 변환 완료] {onnx_path} ({size_kb:.1f} KB)")
    print(f"- PyTorch vs ONNXRuntime 최대 오차: {max_diff:.2e}")
    assert max_diff < 1e-4, "ONNX 변환 오차가 허용치를 초과했습니다!"


def main():
    torch.manual_seed(42)
    np.random.seed(42)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    data = np.load(DATA_PATH)
    X_train, y_train = data["X_train"], data["y_train"]
    X_val, y_val = data["X_val"], data["y_val"]
    X_test, y_test = data["X_test"], data["y_test"]

    train_loader = DataLoader(WindowDataset(X_train, y_train, augment=True), batch_size=64, shuffle=True)
    val_loader = DataLoader(WindowDataset(X_val, y_val, augment=False), batch_size=128, shuffle=False)
    test_loader = DataLoader(WindowDataset(X_test, y_test, augment=False), batch_size=128, shuffle=False)

    # 클래스 불균형 가중치 계산 (정상 vs 낙상)
    n_neg = int(np.sum(y_train == 0))
    n_pos = int(np.sum(y_train == 1))
    pos_weight = min(n_neg / max(n_pos, 1), 12.0)  # 과도한 오탐 방지를 위해 상한 12.0 제한
    class_weights = torch.tensor([1.0, pos_weight], dtype=torch.float32, device=device)
    print(f"학습 장치: {device} | 클래스 가중치: [1.0, {pos_weight:.2f}]")

    model = Fall1DCNN(in_channels=38, num_classes=2, dropout=0.3).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=40)

    best_val_f1 = -1.0
    best_thr = 0.5
    epochs = 40

    for ep in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(xb)
        scheduler.step()

        val_probs, val_targets = predict_probs(model, val_loader, device)
        thr, val_f1 = find_best_threshold(val_probs, val_targets)
        val_preds = (val_probs >= thr).astype(int)
        prec, rec, _, _ = precision_recall_fscore_support(
            val_targets, val_preds, average="binary", zero_division=0
        )

        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            best_thr = thr
            torch.save({"model_state": model.state_dict(), "threshold": best_thr}, PT_PATH)

        if ep % 5 == 0 or ep == 1:
            print(
                f"Epoch {ep:02d}/{epochs} | Loss: {total_loss/len(X_train):.4f} | "
                f"Val F1: {val_f1:.4f} (P={prec:.3f}, R={rec:.3f}, thr={thr:.2f})"
            )

    # 최고 성능 체크포인트 로드 후 Test 최종 평가
    ckpt = torch.load(PT_PATH, map_location=device, weights_only=True)
    model.load_state_dict(ckpt["model_state"])
    best_thr = ckpt["threshold"]

    test_probs, test_targets = predict_probs(model, test_loader, device)
    test_preds = (test_probs >= best_thr).astype(int)

    prec, rec, f1, _ = precision_recall_fscore_support(
        test_targets, test_preds, average="binary", zero_division=0
    )
    pr_auc = average_precision_score(test_targets, test_probs)
    cm = confusion_matrix(test_targets, test_preds)

    print("\n" + "=" * 55)
    print(f"[최종 Test 평가 결과] (운영 임계값 threshold = {best_thr:.2f})")
    print(f"- Recall (재현율) : {rec * 100:.2f}%")
    print(f"- Precision(정밀도): {prec * 100:.2f}%")
    print(f"- F1-Score        : {f1:.4f}")
    print(f"- PR-AUC          : {pr_auc:.4f}")
    print(f"- Confusion Matrix (행=실제 [0,1], 열=예측 [0,1]):\n{cm}")
    print("=" * 55)

    export_and_verify_onnx(model, ONNX_PATH)


if __name__ == "__main__":
    main()