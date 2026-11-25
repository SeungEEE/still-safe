import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
from picamera2 import Picamera2


PAGE = """<!doctype html>
<html lang="ko">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>라즈베리파이 카메라</title>
<style>
body{background:#17202b;color:white;font:18px sans-serif;margin:24px}
img{width:100%;max-width:800px;border:2px solid #738399}
</style>
<h2>라즈베리파이 카메라 실시간 영상</h2>
<p>카메라 앞에서 손을 움직여 영상이 바뀌는지 확인하세요.</p>
<img src="/stream.mjpg" alt="카메라 영상">
</html>"""

condition = threading.Condition()
stop = threading.Event()
latest = {"jpeg": None, "seq": 0}


def capture_loop(camera):
    try:
        while not stop.is_set():
            frame = camera.capture_array("main")
            ok, encoded = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )
            if not ok:
                raise RuntimeError("JPEG encoding failed")

            with condition:
                latest["jpeg"] = encoded.tobytes()
                latest["seq"] += 1
                condition.notify_all()
    except Exception as error:
        print(f"Camera error: {error}", flush=True)
        stop.set()
        with condition:
            condition.notify_all()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path != "/stream.mjpg":
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "multipart/x-mixed-replace; boundary=frame"
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        last_seq = 0
        try:
            while not stop.is_set():
                with condition:
                    condition.wait_for(
                        lambda: latest["seq"] != last_seq or stop.is_set(),
                        timeout=2,
                    )
                    if stop.is_set():
                        break
                    if latest["seq"] == last_seq:
                        continue
                    jpeg = latest["jpeg"]
                    last_seq = latest["seq"]

                self.wfile.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode()
                    + b"\r\n\r\n" + jpeg + b"\r\n"
                )
                self.wfile.flush()
        except OSError:
            pass


def main():
    camera = Picamera2()
    server = None
    thread = None
    try:
        camera.configure(camera.create_video_configuration(
            main={"size": (640, 480), "format": "RGB888"},
            controls={"FrameRate": 10},
            buffer_count=4,
            queue=False,
        ))
        camera.start()
        server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
        server.daemon_threads = True

        thread = threading.Thread(
            target=capture_loop, args=(camera,), daemon=True
        )
        thread.start()

        print("Open http://192.168.20.11:8080", flush=True)
        print("Press Ctrl+C to stop.", flush=True)
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        with condition:
            condition.notify_all()
        if server is not None:
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)
        camera.close()


if __name__ == "__main__":
    main()
