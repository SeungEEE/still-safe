import cv2
from picamera2 import Picamera2

def init_camera(width=640, height=480):
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"size": (width, height), "format": "RGB888"}
    )
    picam2.configure(config)
    picam2.start()
    return picam2

def read_frame(picam2):
    # Picamera2는 RGB 배열을 주므로 기존 OpenCV(BGR) 코드와 맞추기 위해 변환
    frame_rgb = picam2.capture_array()
    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    return True, frame_bgr