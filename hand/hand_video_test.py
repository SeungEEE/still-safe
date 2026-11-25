import argparse
import json
import math
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort


# Temporary zones: left, top, right, bottom (relative coordinates).
ZONES = {
    "inner": (0.27, 0.18, 0.71, 0.48),
    "middle": (0.18, 0.15, 0.82, 0.60),
}
COLORS = {
    "inner": (0, 0, 255),
    "middle": (0, 165, 255),
}
PRIORITY = {"inner": 3, "middle": 2, "visible": 1, "none": 0}

PAGE = """<!doctype html>
<html lang="ko">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>손 탐지 영상 테스트</title>
<style>
body{background:#17202b;color:#edf2fa;font:17px system-ui;
margin:24px;max-width:960px}
img{width:100%;max-width:800px;border:1px solid #738399}
pre{white-space:pre-wrap;background:#243143;padding:16px}
</style>
<h2>저장 영상 · 손 탐지 테스트</h2>
<p>영상의 모든 프레임을 순서대로 추론합니다.
추론이 느리면 원본보다 천천히 진행됩니다.</p>
<p id="state">첫 추론 결과를 기다리는 중...</p>
<img id="image" alt="첫 추론 결과를 기다리는 중">
<pre id="details"></pre>
<p>inner: 위험구역 / middle: 경고구역<br>
visible: 손은 있지만 두 구역 밖 / none: 손 미검출</p>
<p>구역은 임시 좌표입니다. inner_confirmed는 2프레임 연속
inner 판정 여부이며, 실제 GPIO 출력은 하지 않습니다.</p>
<script>
let lastFrame=0;
async function update(){
  try{
    const r=await fetch('/status',{cache:'no-store'});
    if(!r.ok)throw Error(r.status);
    const s=await r.json();
    document.getElementById('state').textContent=
      s.error?'오류: '+s.error:
      !s.frame?'첫 추론 결과를 기다리는 중...':
      (s.finished?'영상 처리 완료 | ':'처리 중 | ')+
      '손 '+s.hands+'개 | 구역 '+s.zone+
      ' | 추론 '+s.infer_ms+' ms';
    if(s.frame && s.frame!==lastFrame){
      document.getElementById('image').src='/frame.jpg?v='+s.frame;
      lastFrame=s.frame;
    }
    document.getElementById('details').textContent=
      JSON.stringify(s,null,2);
  }catch(e){
    document.getElementById('state').textContent=
      '서버 연결 실패: PuTTY 실행 상태를 확인하세요.';
  }
  setTimeout(update,500);
}
update();
</script>
</html>"""


class Segmenter:
    def __init__(self, model_path):
        options = ort.SessionOptions()
        options.intra_op_num_threads = 3
        self.session = ort.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        inp = self.session.get_inputs()[0]
        self.name = inp.name
        self.ih = inp.shape[2] if isinstance(inp.shape[2], int) else 640
        self.iw = inp.shape[3] if isinstance(inp.shape[3], int) else 640

        if inp.type not in ("tensor(float)", "tensor(float16)"):
            raise ValueError(f"Unsupported model input: {inp.type}")
        self.dtype = (
            np.float16 if inp.type == "tensor(float16)" else np.float32
        )

    def infer(self, image):
        h, w = image.shape[:2]
        ratio = min(self.iw / w, self.ih / h)
        nw, nh = round(w * ratio), round(h * ratio)
        left, top = (self.iw - nw) // 2, (self.ih - nh) // 2

        resized = cv2.resize(image, (nw, nh))
        padded = cv2.copyMakeBorder(
            resized, top, self.ih - nh - top,
            left, self.iw - nw - left,
            cv2.BORDER_CONSTANT, value=(114, 114, 114),
        )
        tensor = np.ascontiguousarray(
            padded[:, :, ::-1].transpose(2, 0, 1)[None],
            dtype=self.dtype,
        )
        tensor /= 255.0

        started = time.perf_counter()
        outputs = self.session.run(None, {self.name: tensor})
        infer_ms = (time.perf_counter() - started) * 1000

        predictions = [x for x in outputs if x.ndim == 3]
        prototypes = [x for x in outputs if x.ndim == 4]
        if len(predictions) != 1 or len(prototypes) != 1:
            raise ValueError("Expected raw YOLO-seg outputs (nms=False).")

        pred = predictions[0]
        proto = prototypes[0][0].astype(np.float32)
        channels, mh, mw = proto.shape
        if pred.shape[0] != 1 or pred.shape[1] != channels + 5:
            raise ValueError(
                f"Expected one-class hand model; output={pred.shape}"
            )

        pred = pred[0].T
        pred = pred[
            np.isfinite(pred).all(axis=1) & (pred[:, 4] > 0.25)
        ]
        boxes = pred[:, :4].copy()
        boxes[:, :2] -= boxes[:, 2:] / 2

        keep = []
        if len(pred):
            keep = np.asarray(
                cv2.dnn.NMSBoxes(
                    boxes.tolist(), pred[:, 4].tolist(), 0.25, 0.7
                ),
                dtype=int,
            ).reshape(-1)[:20]

        px1 = round(left * mw / self.iw)
        py1 = round(top * mh / self.ih)
        px2 = round((left + nw) * mw / self.iw)
        py2 = round((top + nh) * mh / self.ih)
        flat_proto = proto.reshape(channels, -1)

        combined = np.zeros((h, w), dtype=bool)
        detections = []

        for idx in keep:
            row = pred[idx]
            box = np.concatenate((
                row[:2] - row[2:4] / 2,
                row[:2] + row[2:4] / 2,
            ))
            box[[0, 2]] = ((box[[0, 2]] - left) / ratio).clip(0, w)
            box[[1, 3]] = ((box[[1, 3]] - top) / ratio).clip(0, h)
            x1, y1, x2, y2 = np.rint(box).astype(int)
            if x2 <= x1 or y2 <= y1:
                continue

            logits = (
                row[5:].astype(np.float32) @ flat_proto
            ).reshape(mh, mw)
            logits = cv2.resize(
                logits[py1:py2, px1:px2], (w, h),
                interpolation=cv2.INTER_LINEAR,
            )
            mask = np.zeros((h, w), dtype=bool)
            mask[y1:y2, x1:x2] = logits[y1:y2, x1:x2] > 0
            combined |= mask

            hand_zone = "visible"
            for name, (a, b, c, d) in ZONES.items():
                zx1, zy1, zx2, zy2 = (
                    round(a * w), round(b * h),
                    round(c * w), round(d * h),
                )
                if mask[zy1:zy2, zx1:zx2].any():
                    hand_zone = name
                    break

            detections.append({
                "box": (int(x1), int(y1), int(x2), int(y2)),
                "conf": float(row[4]),
                "zone": hand_zone,
            })

        return combined, detections, infer_ms


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--video", type=Path, default=Path.home() / "hand_video.mp4"
    )
    parser.add_argument(
        "--model", type=Path, default=Path.home() / "best.onnx"
    )
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    for path in (args.video, args.model):
        if not path.is_file():
            parser.error(f"File not found: {path}")

    lock = threading.Lock()
    stop = threading.Event()
    shared = {
        "jpeg": None,
        "status": {"frame": 0, "finished": False, "error": None},
    }

    def worker():
        cap = None
        try:
            print("Loading ONNX model...", flush=True)
            model = Segmenter(args.model)
            cap = cv2.VideoCapture(str(args.video))
            if not cap.isOpened():
                raise RuntimeError("Cannot open video file.")

            fps = float(cap.get(cv2.CAP_PROP_FPS))
            if not math.isfinite(fps) or fps <= 0:
                fps = 30.0
                print("Video FPS unavailable; assuming 30 FPS.", flush=True)

            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_number = 0
            inner_streak = 0
            print(f"Video opened: fps={fps:.2f}, frames={total}", flush=True)

            while not stop.is_set():
                started = time.perf_counter()
                ok, frame = cap.read()
                if not ok:
                    if frame_number == 0:
                        raise RuntimeError("Cannot decode the first frame.")
                    with lock:
                        shared["status"]["finished"] = True
                    print("Video processing finished.", flush=True)
                    return

                frame_number += 1
                h, w = frame.shape[:2]
                scale = min(1.0, 640 / max(h, w))
                if scale < 1:
                    frame = cv2.resize(
                        frame,
                        (max(1, round(w * scale)), max(1, round(h * scale))),
                    )

                mask, detections, infer_ms = model.infer(frame)
                chosen = max(
                    detections,
                    key=lambda item: (
                        PRIORITY[item["zone"]], item["conf"]
                    ),
                    default=None,
                )
                zone = chosen["zone"] if chosen else "none"
                confidence = chosen["conf"] if chosen else 0.0
                inner_streak = inner_streak + 1 if zone == "inner" else 0

                result = frame.copy()
                result[mask] = (
                    result[mask] * 0.55
                    + np.array([255, 100, 0]) * 0.45
                ).astype(np.uint8)

                h, w = result.shape[:2]
                overlaps = {}
                for name, (a, b, c, d) in ZONES.items():
                    x1, y1, x2, y2 = (
                        round(a * w), round(b * h),
                        round(c * w), round(d * h),
                    )
                    overlaps[name] = int(mask[y1:y2, x1:x2].sum())
                    cv2.rectangle(
                        result, (x1, y1), (x2, y2), COLORS[name], 2
                    )
                    cv2.putText(
                        result, name, (x1, max(15, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLORS[name], 1,
                    )

                for item in detections:
                    x1, y1, x2, y2 = item["box"]
                    cv2.rectangle(
                        result, (x1, y1), (x2, y2), (255, 100, 0), 1
                    )
                    cv2.putText(
                        result, f"hand {item['conf']:.2f}",
                        (x1, max(15, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 100, 0), 1,
                    )

                cv2.rectangle(
                    result, (0, 0), (w, min(h, 52)), (25, 25, 25), -1
                )
                cv2.putText(
                    result, f"hands: {len(detections)}  zone: {zone}",
                    (8, 21), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (255, 255, 255), 1,
                )
                cv2.putText(
                    result, f"frame: {frame_number}  ONNX: {infer_ms:.0f} ms",
                    (8, 43), cv2.FONT_HERSHEY_SIMPLEX,
                    0.48, (255, 255, 255), 1,
                )

                ok, encoded = cv2.imencode(
                    ".jpg", result, [cv2.IMWRITE_JPEG_QUALITY, 80]
                )
                if not ok:
                    raise RuntimeError("JPEG encoding failed.")

                status = {
                    "test": True,
                    "source": "saved_video",
                    "frame": frame_number,
                    "total_frames": total,
                    "video_sec": round((frame_number - 1) / fps, 3),
                    "hand_present": bool(detections),
                    "hands": len(detections),
                    "zone": zone,
                    "conf": round(confidence, 3),
                    "inner_streak": inner_streak,
                    "inner_confirmed": inner_streak >= 2,
                    "overlap_pixels": overlaps,
                    "infer_ms": round(infer_ms, 1),
                    "processing_ms": round(
                        (time.perf_counter() - started) * 1000, 1
                    ),
                    "finished": False,
                    "error": None,
                }
                with lock:
                    shared["jpeg"] = encoded.tobytes()
                    shared["status"] = status

                print(
                    f"frame={frame_number}/{total} hands={len(detections)} "
                    f"zone={zone} ONNX={infer_ms:.0f}ms",
                    flush=True,
                )

                remaining = 1 / fps - (time.perf_counter() - started)
                if remaining > 0:
                    stop.wait(remaining)

        except Exception as error:
            traceback.print_exc()
            with lock:
                shared["status"] = {
                    **shared["status"], "error": str(error)
                }
        finally:
            if cap is not None:
                cap.release()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                body = PAGE.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            elif path == "/status":
                with lock:
                    body = json.dumps(shared["status"]).encode("utf-8")
                content_type = "application/json"
            elif path == "/frame.jpg":
                with lock:
                    body = shared["jpeg"]
                if body is None:
                    self.send_error(503, "Waiting for first result")
                    return
                content_type = "image/jpeg"
            else:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    print(f"Open http://192.168.20.11:{args.port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    main()
