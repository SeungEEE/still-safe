from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

home = Path.home()

# 1. 테스트 이미지 읽기
image = cv2.imread(str(home / "hand_test.jpg"))
if image is None:
    raise RuntimeError("테스트 이미지를 읽지 못했습니다.")

h, w = image.shape[:2]
size = 640

# 2. 이미지 비율을 유지하며 크기를 줄이고 여백 추가
ratio = min(size / w, size / h)
nw, nh = round(w * ratio), round(h * ratio)

dw, dh = (size - nw) / 2, (size - nh) / 2
left, right = round(dw - 0.1), round(dw + 0.1)
top, bottom = round(dh - 0.1), round(dh + 0.1)

resized = cv2.resize(image, (nw, nh))
padded = cv2.copyMakeBorder(
    resized, top, bottom, left, right,
    cv2.BORDER_CONSTANT, value=(114, 114, 114),
)

# 3. 모델 입력 형식으로 변환
tensor = np.ascontiguousarray(
    padded[:, :, ::-1].transpose(2, 0, 1)[None],
    dtype=np.float32,
)
tensor /= 255.0

# 4. ONNX Runtime으로 CPU 추론
session = ort.InferenceSession(
    str(home / "best.onnx"),
    providers=["CPUExecutionProvider"],
)
pred, proto = session.run(
    None, {session.get_inputs()[0].name: tensor}
)

# 5. 신뢰도가 0.25보다 높은 손 후보 선택
# 각 후보: 중심 좌표 2개 + 크기 2개 + 손 점수 1개 + 마스크 계수 32개
pred = pred[0].T
pred = pred[pred[:, 4] > 0.25]

# 중복 탐지 제거에 사용할 박스 형식: 왼쪽 위 x, y, 너비, 높이
boxes = pred[:, :4].copy()
boxes[:, :2] -= boxes[:, 2:] / 2

keep = np.empty(0, dtype=int)
if len(pred):
    keep = np.asarray(
        cv2.dnn.NMSBoxes(
            boxes.tolist(),
            pred[:, 4].tolist(),
            score_threshold=0.25,
            nms_threshold=0.7,
        ),
        dtype=int,
    ).reshape(-1)[:100]

# 6. 기본 마스크에서 이미지 여백에 해당하는 범위 계산
channels, mh, mw = proto[0].shape
gain = min(mh / h, mw / w)
pad_x = (mw - w * gain) / 2
pad_y = (mh - h * gain) / 2

mx1 = round(pad_x - 0.1)
my1 = round(pad_y - 0.1)
mx2 = mw - round(pad_x + 0.1)
my2 = mh - round(pad_y + 0.1)

result = image.copy()
combined = np.zeros((h, w), dtype=bool)
colors = [(255, 100, 0), (0, 200, 0), (0, 100, 255)]

# 7. 손별 마스크 복원 및 결과 표시
for number, idx in enumerate(keep, start=1):
    row = pred[idx]

    # 박스를 양쪽 모서리 좌표로 변환
    box = np.concatenate((
        row[:2] - row[2:4] / 2,
        row[:2] + row[2:4] / 2,
    ))

    # 여백과 축소 비율을 되돌려 원본 이미지 좌표로 변환
    box[[0, 2]] = (box[[0, 2]] - left) / ratio
    box[[1, 3]] = (box[[1, 3]] - top) / ratio
    box[[0, 2]] = box[[0, 2]].clip(0, w)
    box[[1, 3]] = box[[1, 3]].clip(0, h)

    # 마스크 계수와 기본 마스크를 조합
    logits = (
        row[5:] @ proto[0].reshape(channels, -1)
    ).reshape(mh, mw)

    # 여백 제거 후 원본 이미지 크기로 확대
    logits = logits[my1:my2, mx1:mx2]
    logits = cv2.resize(
        logits, (w, h),
        interpolation=cv2.INTER_LINEAR,
    )

    # 손 영역을 이진 마스크로 만들고 박스 바깥 부분 제거
    x1, y1, x2, y2 = np.rint(box).astype(int)
    mask = np.zeros((h, w), dtype=bool)
    mask[y1:y2, x1:x2] = logits[y1:y2, x1:x2] > 0
    combined |= mask

    # 사진에 손 마스크를 반투명하게 표시
    color = colors[(number - 1) % len(colors)]
    result[mask] = (
        result[mask] * 0.55 + np.asarray(color) * 0.45
    ).astype(np.uint8)

    cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)

    # OpenCV 기본 글꼴은 한글을 지원하지 않아 번호와 점수만 표시
    cv2.putText(
        result,
        f"#{number} {row[4]:.4f}",
        (x1, max(y1 - 8, 20)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6, color, 2,
    )

    print(
        f"손 {number}: 신뢰도={row[4]:.4f}, "
        f"마스크 픽셀 수={int(mask.sum())}"
    )

# 8. 결과 이미지와 전체 손 이진 마스크 저장
result_path = home / "hand_result.jpg"
mask_path = home / "hand_mask.png"

if not cv2.imwrite(str(result_path), result):
    raise RuntimeError("결과 이미지 저장에 실패했습니다.")

if not cv2.imwrite(str(mask_path), combined.astype(np.uint8) * 255):
    raise RuntimeError("손 마스크 저장에 실패했습니다.")

print("탐지된 손 개수:", len(keep))
print("결과 이미지:", result_path)
print("전체 손 마스크:", mask_path)
