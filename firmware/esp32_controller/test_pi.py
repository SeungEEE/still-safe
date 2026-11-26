# ===================================================
#  ESP32 펌웨어 손 시험 도구 (Pi C 없이 ESP32 하나만 시험)
#  esp32_controller.ino 가 올라간 ESP32 를 USB 로 연결하고 실행한다.
#
#    python firmware/esp32_controller/test_pi.py            # 포트 자동 찾기 (Linux)
#    python firmware/esp32_controller/test_pi.py COM3       # Windows
#
#  - 뒤에서 PING 을 0.2초마다 자동으로 보낸다 (워치독에 안 걸리게)
#  - 입력한 줄을 그대로 ESP32 에 보낸다: LEVEL:0~3, UNLOCK, START
#  - p = PING 끄기/켜기 (워치독 시험), q = 종료 (PING 을 끊으므로 ESP32 는 잠김)
#  - MOTOR/LATCH 주기 보고는 바뀔 때만 출력한다
# ===================================================
import glob
import sys
import threading
import time

import serial

PING_SEC = 0.2

# 1) 포트 정하기
if len(sys.argv) > 1:
    port = sys.argv[1]
else:
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if not ports:
        print("ESP32를 못 찾았어요. USB 선을 확인하거나 포트 이름을 직접 주세요 (예: COM3).")
        raise SystemExit
    port = ports[0]

esp = serial.Serial(port, 115200, timeout=0.1)
print(f"ESP32 연결: {port} (재부팅 기다리는 중 2초)")
time.sleep(2)
esp.reset_input_buffer()

lock = threading.Lock()
pinging = True
running = True


def send(line):
    with lock:
        esp.write((line + "\n").encode())


# 2) PING 자동 전송
def ping_loop():
    while running:
        if pinging:
            send("PING")
        time.sleep(PING_SEC)


# 3) ESP32 가 보내는 줄 출력 (PONG 은 숨기고, 주기 보고는 바뀔 때만)
def read_loop():
    last = {}
    while running:
        try:
            line = esp.readline().decode("utf-8", errors="replace").strip()
        except serial.SerialException:
            break
        if not line or line == "PONG":
            continue
        key = line.split(":")[0]
        if key in ("MOTOR", "LATCH"):
            if last.get(key) == line:
                continue
            last[key] = line
        print(f"   [ESP32] {line}")


threading.Thread(target=ping_loop, daemon=True).start()
threading.Thread(target=read_loop, daemon=True).start()

MENU = """
-------------------------------------------
 LEVEL:0 ~ LEVEL:3   단계 보내기
 UNLOCK              잠금 해제 (LEVEL:0 먼저)
 START               모터 시작 (잠금 해제 + 스위치 올림 필요)
 p = PING 끄기/켜기 (0.5초 뒤 ERR:heartbeat_lost)
 q = 종료
-------------------------------------------"""
print(MENU)

# 4) 입력 -> ESP32
while True:
    k = input("> ").strip()
    if k.lower() == "q":
        # PING 만 끊고 끝낸다. 모터가 돌고 있었다면 ESP32 워치독이 0.5초 안에 세운다
        pinging = False
        time.sleep(0.7)
        break
    if k.lower() == "p":
        pinging = not pinging
        print("PING", "켜짐" if pinging else "꺼짐")
    elif k:
        send(k.upper())
    else:
        print(MENU)

running = False
esp.close()
print("종료")
