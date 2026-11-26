"""가짜 ESP32: 진짜 ESP32 없이 Pi C 시리얼 코드를 시험한다.

TCP 서버로 동작하고, Pi C 쪽은 pyserial 로 socket:// 주소를 연다.
    python -m tools.fake_esp32                       # 이 창은 켜 둔다
    ESP32_PORT=socket://127.0.0.1:7000 python -m central.main

명령과 응답은 통신 약속 6장과 같다.
- PING        -> PONG
- LEVEL:0~3   -> 3이면 모터 정지 + 잠금
- UNLOCK      -> 잠금 해제
- START       -> 잠금 중이면 ERR:start_blocked, 아니면 모터 동작
- PING 이 0.5초 넘게 없으면 스스로 정지 + 잠금 (워치독)
- 0.5초마다 MOTOR:x, LATCH:x 보고
"""

import socket
import sys
import time

HOST = "127.0.0.1"   # localhost 로 쓰면 Windows 에서 IPv6 를 먼저 시도하느라 접속이 2초 늦어짐
PORT = 7000
WATCHDOG_SEC = 0.5
REPORT_SEC = 0.5


class FakeEsp32:
    def __init__(self, conn):
        self.conn = conn
        self.motor = False
        self.latched = True          # 전원 켜면 잠금 상태로 시작
        self.level = 0
        self.last_ping = time.time()
        self.last_report = 0
        self.pings = 0               # 화면이 넘치지 않게 PING 은 개수만 센다

    def send(self, line):
        self.conn.sendall((line + "\n").encode())
        if line != "PONG":
            print("  보냄 <-", line)

    def report(self):
        self.send(f"MOTOR:{int(self.motor)}")
        self.send(f"LATCH:{int(self.latched)}")

    def stop_and_latch(self, why):
        changed = self.motor or not self.latched
        self.motor = False
        self.latched = True
        if changed:
            print(f"*** 모터 정지 + 잠금 ({why})")
            self.send(f"ERR:{why}")
            self.report()

    def handle(self, cmd):
        if cmd == "PING":
            self.last_ping = time.time()
            self.pings += 1
            self.send("PONG")
            return

        print("받음 ->", cmd)
        if cmd.startswith("LEVEL:"):
            self.level = int(cmd[6:])
            if self.level >= 3:
                self.stop_and_latch("danger")
        elif cmd == "UNLOCK":
            self.latched = False
            self.report()
        elif cmd == "START":
            if self.latched:
                self.send("ERR:start_blocked")
            else:
                self.motor = True
                print("*** 모터 동작")
                self.report()
        else:
            self.send(f"ERR:unknown_{cmd}")

    def run(self):
        self.conn.settimeout(0.05)
        buf = b""
        while True:
            try:
                data = self.conn.recv(1024)
                if not data:
                    print("연결 끊김")
                    return
                buf += data
            except socket.timeout:
                pass

            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                cmd = raw.decode(errors="replace").strip()
                if cmd:
                    self.handle(cmd)

            now = time.time()
            if now - self.last_ping > WATCHDOG_SEC:
                self.stop_and_latch("heartbeat_lost")

            if now - self.last_report > REPORT_SEC:
                self.last_report = now
                self.report()
                print(f"  (지난 보고 뒤 PING {self.pings}번, 단계 {self.level})")
                self.pings = 0


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 리눅스: 껐다 바로 다시 켤 때 "주소 사용 중" 방지
    # Windows 에서는 이 옵션이 같은 포트를 여러 프로그램이 동시에 열게 만들어서 켜지 않는다
    if sys.platform != "win32":
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)
    print(f"가짜 ESP32 대기 중: socket://{HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        print("Pi C 연결됨:", addr)
        try:
            FakeEsp32(conn).run()     # 연결할 때마다 새로 시작 = 진짜 ESP32 재부팅과 같음
        except (ConnectionError, OSError) as e:
            print("연결 오류:", e)
        finally:
            conn.close()


if __name__ == "__main__":
    main()
