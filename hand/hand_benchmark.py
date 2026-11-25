import argparse
import time
from pathlib import Path

import cv2
import numpy as np

from hand_video_test import Segmenter, PRIORITY


def resize_frame(frame):
    h, w = frame.shape[:2]
    scale = min(1.0, 640 / max(h, w))
    if scale < 1:
        frame = cv2.resize(
            frame,
            (max(1, round(w * scale)), max(1, round(h * scale))),
        )
    return frame


def report(name, values):
    values = np.asarray(values, dtype=float)
    print(f"\n{name}")
    print(f"  Average: {values.mean():.2f} ms")
    print(f"  Median : {np.median(values):.2f} ms")
    print(f"  P95    : {np.percentile(values, 95):.2f} ms")
    print(f"  Min/Max: {values.min():.2f} / {values.max():.2f} ms")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=100)
    args = parser.parse_args()
    if args.frames < 1:
        parser.error("--frames must be positive")

    home = Path.home()
    model = Segmenter(home / "best.onnx")
    cap = cv2.VideoCapture(str(home / "hand_video.mp4"))
    if not cap.isOpened():
        raise RuntimeError("Cannot open hand_video.mp4")

    model_times = []
    total_times = []
    try:
        ok, first = cap.read()
        if not ok:
            raise RuntimeError("Cannot decode the first frame")

        first = resize_frame(first)
        print("Warm-up: 5 runs (excluded)", flush=True)
        for _ in range(5):
            model.infer(first)

        # Reopen the video to measure from the first frame.
        cap.release()
        cap = cv2.VideoCapture(str(home / "hand_video.mp4"))
        if not cap.isOpened():
            raise RuntimeError("Cannot reopen video")

        inner_streak = 0
        print(f"Measuring up to {args.frames} frames...", flush=True)

        for number in range(1, args.frames + 1):
            started = time.perf_counter()

            ok, frame = cap.read()
            if not ok:
                break

            frame = resize_frame(frame)
            mask, detections, infer_ms = model.infer(frame)

            chosen = max(
                detections,
                key=lambda item: (
                    PRIORITY[item["zone"]], item["conf"]
                ),
                default=None,
            )
            zone = chosen["zone"] if chosen else "none"
            inner_streak = inner_streak + 1 if zone == "inner" else 0
            inner_confirmed = inner_streak >= 2

            total_ms = (time.perf_counter() - started) * 1000
            model_times.append(infer_ms)
            total_times.append(total_ms)

            # Console output is excluded from the measured processing time.
            if number == 1 or number % 10 == 0:
                print(
                    f"[{number}/{args.frames}] "
                    f"ONNX={infer_ms:.1f} ms "
                    f"total={total_ms:.1f} ms "
                    f"hands={len(detections)} zone={zone} "
                    f"inner_confirmed={inner_confirmed}",
                    flush=True,
                )

    except KeyboardInterrupt:
        print("\nStopped. Reporting completed frames.")
    finally:
        cap.release()

    if not model_times:
        print("No frames measured.")
        return

    print(f"\nMeasured frames: {len(model_times)}")
    report("ONNX inference only", model_times)
    report("Full processing (no drawing, web or MQTT)", total_times)
    print(
        f"\nProcessing throughput: "
        f"{1000 / np.mean(total_times):.2f} FPS"
    )


if __name__ == "__main__":
    main()
