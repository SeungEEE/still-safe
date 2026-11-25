from pathlib import Path
import cv2
import numpy as np

home = Path.home()
image = cv2.imread(str(home / "hand_test.jpg"))
mask_image = cv2.imread(
    str(home / "hand_mask.png"),
    cv2.IMREAD_GRAYSCALE,
)

if image is None or mask_image is None:
    raise RuntimeError("테스트 이미지 또는 손 마스크가 없습니다.")

h, w = image.shape[:2]
if mask_image.shape != (h, w):
    raise RuntimeError("이미지와 손 마스크의 크기가 다릅니다.")

hand_mask = mask_image > 0

# 임시 구역: 왼쪽, 위쪽, 오른쪽, 아래쪽의 상대 좌표
# 0~1 범위이며, 실제 설비 완성 후 수정할 값입니다.
zones = {
    "inner":  (0.40, 0.40, 0.60, 0.60),
    "middle": (0.30, 0.30, 0.70, 0.75),
}

colors = {
    "inner": (0, 0, 255),
    "middle": (0, 165, 255),
}

overlaps = {}
result = image.copy()

for name, coords in zones.items():
    x1, y1, x2, y2 = (
        round(coords[0] * w),
        round(coords[1] * h),
        round(coords[2] * w),
        round(coords[3] * h),
    )

    overlaps[name] = int(hand_mask[y1:y2, x1:x2].sum())

    cv2.rectangle(
        result, (x1, y1), (x2, y2), colors[name], 2
    )
    cv2.putText(
        result, name, (x1, max(y1 - 8, 20)),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, colors[name], 2,
    )

# 모든 손을 합친 마스크로 가장 위험한 구역부터 확인
# 이번 기능 테스트에서는 1픽셀 이상 겹치면 진입으로 판정
zone = "visible" if hand_mask.any() else "none"
for name in ("inner", "middle"):
    if overlaps[name] > 0:
        zone = name
        break

# 손 마스크 표시
result[hand_mask] = (
    result[hand_mask] * 0.55
    + np.array([255, 100, 0]) * 0.45
).astype(np.uint8)

cv2.putText(
    result, f"zone: {zone}", (20, 40),
    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2,
)

output = home / "hand_zone_result.jpg"
if not cv2.imwrite(str(output), result):
    raise RuntimeError("구역 결과 이미지 저장에 실패했습니다.")

for name, pixels in overlaps.items():
    print(f"{name} 내부의 손 픽셀 수: {pixels}")

print("최종 구역:", zone)
print("결과 이미지:", output)
