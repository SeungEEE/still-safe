"""Pi C <-> ESP32 시리얼 통신 (통신 약속 6장).

- 보내기(send)는 메인 루프에서만 부른다. 쓰는 곳이 하나라서 명령이 섞이지 않는다.
- 받기는 별도 스레드가 한 줄씩 읽어서 상태(motor, latched, last_pong)에 저장한다.
- USB 가 빠지거나 포트가 없어도 프로그램은 죽지 않는다. alive 가 False 가 되고,
  메인 루프가 잠시 뒤 다시 연다. 그동안 모터는 ESP32 워치독이 멈춘다.

port 에는 진짜 포트(/dev/ttyUSB0) 또는 가짜 ESP32 주소(socket://127.0.0.1:7000)를 쓴다.
"""

import threading
import time 

import serial

BAUD = 115200
RESET_WAIT_SEC = 2   # 포트를 열면 ESP32 가 재부팅되므로 기다린다


class Esp32:
    def __init__(self, port):
        self.port = port
        self.ser = None
        self.alive = False       # 지금 포트가 열려 있고 읽기 스레드가 도는지
        self.last_open_try = 0

        # ESP32 가 알려준 상태 (아직 모르면 None)
        self.motor = None
        self.latched = None
        self.last_pong = 0

    def open(self):
        """포트를 연다. 성공하면 True."""
        self.last_open_try = time.time()
        try:
            self.ser = serial.serial_for_url(self.port, BAUD, timeout=0.1)
        except (serial.SerialException, OSError) as e:
            print("ESP32 포트 열기 실패:", self.port, e)
            self.ser = None
            return False

        print("ESP32 포트 열림:", self.port)
        time.sleep(RESET_WAIT_SEC)
        self.ser.reset_input_buffer()            # 재부팅 중 찍힌 글자는 버림
        self.alive = True
        threading.Thread(target=self._read_loop, args=(self.ser,), daemon=True).start()
        return True

    def close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except (serial.SerialException, OSError):
                pass
        self.ser = None
        self.alive = False

    def send(self, line):
        """한 줄 보낸다. 실패하면 False (연결을 닫고, 메인 루프가 다시 연다)."""
        ser = self.ser                            # 읽기 스레드가 None 으로 바꿔도 안전하게 먼저 쥐어 둠
        if not self.alive or ser is None:
            return False
        try:
            ser.write((line + "\n").encode())
            return True
        except (serial.SerialException, OSError) as e:
            print("ESP32 보내기 실패:", e)
            self.close()
            return False

    def _read_loop(self, ser):
        """받는 스레드: 한 줄씩 읽어서 상태에 저장한다."""
        while self.alive and ser is self.ser:
            try:
                raw = ser.readline()
            except (serial.SerialException, OSError) as e:
                print("ESP32 읽기 실패:", e)
                self.close()
                return
            if not raw:
                continue                          # timeout: 아직 온 줄 없음
            line = raw.decode(errors="replace").strip()
            if line:
                self._handle(line)

    def _handle(self, line):
        if line == "PONG":
            self.last_pong = time.time()
        elif line.startswith("MOTOR:"):
            motor = line[6:] == "1"
            if motor != self.motor:
                print("ESP32 모터:", "동작" if motor else "정지")
            self.motor = motor
        elif line.startswith("LATCH:"):
            latched = line[6:] == "1"
            if latched != self.latched:
                print("ESP32 잠금:", "잠김" if latched else "풀림")
            self.latched = latched
        else:
            # ERR:..., SWITCH:START, BACKUP:... 은 지금은 출력만 (8단계에서 처리)
            print("ESP32:", line)
