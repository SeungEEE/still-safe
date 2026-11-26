# display

Pi C 7인치 화면과 휴대폰에서 보는 상태 화면. 중앙이 발행하는 `stillsafe/central/state`를 MQTT 웹소켓(9001)으로 받아서 보여 준다.

```
central.main ──(1883)──▶ Mosquitto ──(9001, 웹소켓)──▶ index.html (mqtt.js)
```

화면 프로그램은 중앙과 따로 돈다. 화면이 멈추거나 브라우저가 꺼져도 위험 판단과 ESP32 제어는 계속된다.

## 파일
| 파일 | 하는 일 |
| --- | --- |
| `index.html` | 상태 화면 (HTML, CSS, JS 한 파일) |
| `mqtt.min.js` | MQTT.js 5.10.1 브라우저용 (MIT). Pi C가 인터넷이 안 돼도 열리도록 레포에 넣어 둠 |

## 보여 주는 것
- 현재 단계 (0 안전 초록, 1 주의 노랑, 2 경고 주황, 3 위험 빨강 깜빡임)와 원인 (한글)
- 모터 (동작 / 정지), 정지 잠금 (잠김 / 풀림)
- Pi A, Pi B, ESP32 연결 상태
- 최근 단계 변화 6개
- **3초 넘게 상태가 안 오면 "중앙 응답 없음"으로 화면을 덮는다.** 중앙이 retain으로 발행하므로, 중앙이 꺼져도 마지막 상태가 남아 있어서 이게 없으면 화면이 계속 "안전"으로 보일 수 있다.
- 브로커 연결이 끊기면 "브로커 연결 끊김"

## 브로커 설정 (웹소켓)
Mosquitto에 웹소켓 리스너가 있어야 한다.
```
listener 9001
protocol websockets
```
- Pi C: `/etc/mosquitto/conf.d/stillsafe.conf`에 추가하고 `sudo systemctl restart mosquitto`
- Windows 노트북: `C:\Program Files\mosquitto\mosquitto.conf` (관리자). `listener`를 하나라도 쓰면 기본 1883이 사라지므로 `listener 1883 127.0.0.1`, `allow_anonymous true`도 같이 쓴다.

## 열기
접속할 브로커는 주소창의 `?host=`로 정한다. 없으면 페이지를 연 주소, 파일로 열었으면 `localhost`.

| 어디서 | 여는 법 |
| --- | --- |
| 노트북 (개발) | `display/index.html`을 브라우저로 열기 → 로컬 브로커 |
| 노트북에서 Pi C 브로커 보기 | `index.html?host=<Pi C 주소>` |
| Pi C 7인치 화면 | 아래 키오스크 |
| 휴대폰 | Pi C에서 `python3 -m http.server 8080 -d display` 후 `http://<Pi C 주소>:8080/` (같은 와이파이) |

## Pi C 7인치 화면 (키오스크)
Raspberry Pi OS (Bookworm, 데스크톱). 브라우저 이름은 버전에 따라 `chromium-browser` 또는 `chromium`이다.
```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars \
  "file://$HOME/still-safe/still-safe/display/index.html?host=localhost"
```
부팅 시 자동 실행은 데스크톱 환경에 따라 다르다.
- labwc: `~/.config/labwc/autostart`에 위 명령 한 줄 (끝에 `&`)
- wayfire: `~/.config/wayfire.ini`의 `[autostart]`에 `display = chromium-browser --kiosk ...`

키오스크에서 빠져나오기: `Alt + F4`

## 상태 메시지 (`stillsafe/central/state`, retain)
```json
{
  "v": 1, "ts": 1764134400.12,
  "level": 2, "reason": "hand_middle",
  "motor": false, "latched": true,
  "devices": {"hand": true, "fall": true, "esp32": true}
}
```
- 무엇이든 바뀌면 바로, 그대로면 1초마다 발행한다.
- `motor`, `latched`, `esp32`는 아직 모르면 `null`이다 (화면에는 "확인 중").
- `reason`: `safe`, `two_people`, `hand_middle`, `hand_inner`, `fall`, `device_error`
