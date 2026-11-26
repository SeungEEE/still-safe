# ===================================================
#  Pi C → ESP32 제어 (USB 선으로 명령 전송)
#  ESP32에는 esp32_4situation_test.ino 가 올라가 있어야 함
#
#  s = 모터 시작      x = 모터 정지
#  1 = 쓰러짐         → 모터 정지 + 빨강 LED
#  2 = 2인 1조 아님   → 빨강 LED (모터 계속)
#  3 = 손 DANGER      → 모터 정지 + 빨강 LED
#  4 = 손 CAUTION     → 노랑 LED + 부저 (모터 계속)
#  0 = 전부 정상      q = 종료
#  (1~4는 한 번 누르면 발생, 다시 누르면 해제)
# ===================================================
import glob
import threading
import time
import serial

# 1) ESP32가 꽂힌 USB 포트 자동 찾기
ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
if not ports:
    print("ESP32를 못 찾았어요. ESP32 USB 선이 Pi C에 꽂혀 있는지 확인하세요.")
    raise SystemExit
port = ports[0]
print(f"ESP32 연결: {port}")

esp = serial.Serial(port, 115200, timeout=0.1)
time.sleep(2)   # 연결하면 ESP32가 재부팅되므로 잠깐 기다림


# 2) ESP32가 보내는 메시지를 계속 화면에 출력 (뒤에서 따로 돎)
def read_esp():
    while True:
        try:
            line = esp.readline().decode("utf-8", errors="ignore").strip()
            if line:
                print(f"   [ESP32] {line}")
        except Exception:
            break


threading.Thread(target=read_esp, daemon=True).start()

MENU = """
-------------------------------------------
 s = 시작   x = 정지
 1 = 쓰러짐   2 = 2인1조 아님   3 = DANGER   4 = CAUTION
 0 = 전부 정상   q = 종료
-------------------------------------------"""
print(MENU)

# 3) 키보드 입력 → ESP32로 전송
valid = {"s", "x", "1", "2", "3", "4", "0"}
while True:
    k = input("> ").strip().lower()
    if k == "q":
        esp.write(b"x")          # 끄기 전에 모터 정지
        time.sleep(0.5)
        break
    if k in valid:
        esp.write(k.encode())
        time.sleep(0.3)          # ESP32 답장이 찍힐 시간
    else:
        print(MENU)

esp.close()
print("종료")
