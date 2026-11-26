# central

Pi C 중앙통제: Pi A(손 끼임), Pi B(쓰러짐)의 탐지 결과를 받아 위험 단계(0~3)를 판단하고 ESP32에 명령한다.
메시지 형식과 규칙은 통신 약속 문서를 따른다.

## 실행
저장소 맨 위에서 실행한다 (`central.rules`, `common.messages`를 불러오기 때문).
```
python -m central.main       # 중앙 프로그램
python -m central.rules      # 판단 규칙 시험
python -m common.messages    # 메시지 형식 검사 시험
```
브로커 주소는 환경 변수 `MQTT_HOST`로 받는다. 없으면 `localhost`.
- Pi C에서 실행: 브로커가 자기 자신이라 그대로 실행 (`localhost`)
- 노트북에서 Pi C 브로커로 시험: `MQTT_HOST=<Pi C 주소> python -m central.main` (주소는 통신 약속 문서 참고)

ESP32 포트는 환경 변수 `ESP32_PORT`로 받는다. 없으면 `/dev/ttyUSB0`.
- Pi C에서 실행: 보드에 따라 `ESP32_PORT=/dev/ttyACM0`
- Windows에서 실물 ESP32: `COM3`처럼 장치 관리자에 보이는 이름

### 가짜 ESP32로 시험 (실물 없이)
`tools/fake_esp32.py`가 통신 약속 6장대로 ESP32인 척한다. 터미널 두 개를 쓴다.
```
# 터미널 1
python -m tools.fake_esp32

# 터미널 2 (Mac / Linux)
ESP32_PORT=socket://127.0.0.1:7000 python -m central.main

# 터미널 2 (Windows PowerShell, 두 줄을 따로 입력)
$env:ESP32_PORT="socket://127.0.0.1:7000"
python -m central.main
```
- 가짜 ESP32는 `PING` → `PONG`, `LEVEL:3` → 정지 + 잠금, `UNLOCK`, `START`(잠금 중이면 거부)를 처리하고, 0.5초마다 `MOTOR`, `LATCH`를 보고한다.
- 켜질 때 잠금 상태로 시작하고, `PING`이 0.5초 넘게 끊기면 스스로 정지 + 잠금한다.
- 부저·LED 패턴은 흉내 내지 않는다. USB 포트 특유의 문제(포트 이름 바뀜 등)도 재현하지 못하므로 실물 시험이 따로 필요하다.

## 파일
| 파일 | 하는 일 |
| --- | --- |
| `main.py` | MQTT 수신, 형식 검사, 장치 끊김 감지, 단계 판단, ESP32에 `PING`·`LEVEL` 전송 |
| `rules.py` | 위험 단계 판단 함수 `decide_level` + 시험 18개 |
| `esp32.py` | ESP32 시리얼 연결 `Esp32` (열기, 한 줄 보내기, 받는 스레드, 끊김 처리) |
| `../tools/fake_esp32.py` | 시험용 가짜 ESP32 (TCP `127.0.0.1:7000`) |
| `../common/messages.py` | 메시지 형식 표 `SCHEMA`, 검사 함수 `check` + 시험 (Pi A·B도 같이 씀) |

## 흐름
```
[MQTT 수신 스레드]   메시지 -> 형식 검사 -> latest, last_seen 저장
                     상태 메시지(online/offline) -> offline 목록 갱신
[ESP32 받는 스레드]  한 줄씩 읽기 -> PONG 시각, MOTOR, LATCH 저장
[메인 while, 0.1초]  ESP32 다시 열기 / PING -> 장치 정상 여부 -> 인원 부족 시간
                     -> decide_level -> 유지 규칙 -> 바뀌면 출력 + LEVEL 전송
```

## ESP32 연결 (통신 약속 6장)
- 포트를 열면 ESP32가 재부팅될 수 있어서 2초 기다린 뒤, 그동안 들어온 글자는 버린다.
- `PING`을 0.2초마다 보낸다. ESP32 워치독(0.5초)에 걸리지 않게 하기 위해서다.
- `PONG`이 1초 넘게 없으면 `ESP32 응답 없음`을 출력한다 (단계는 바꾸지 않음).
- `LEVEL:n`은 단계가 바뀔 때만 보낸다. 포트를 다시 열면 지금 단계를 한 번 더 보낸다.
- 보내기나 읽기가 실패하면 포트를 닫고, 메인 루프가 2초마다 다시 연다. 중앙 프로그램은 멈추지 않는다.
- 받는 스레드와 메인 루프가 같은 포트를 쓰므로, `close()`는 정리를 끝낸 뒤 마지막에 `alive = False`로 알리고, `send()`는 포트를 지역 변수에 먼저 담아 쓴다.

## 받는 메시지 처리 (통신 약속 3-4)
아래 중 하나면 **버리고 이유를 출력**한다. 버린 메시지는 "살아 있음"으로 치지 않는다.
1. 모르는 토픽 (`stillsafe/hand`, `stillsafe/fall`만 받음)
2. JSON으로 못 읽음 (깨진 바이트 포함)
3. `common/messages.py`의 `SCHEMA`와 맞지 않음
   - 필수 값이 빠짐 (`signal` 안쪽 값 포함)
   - 종류가 틀림 (예: `people`이 `"2"`, `signal.fall`이 `"false"`, `people`이 `true`)
   - `zone`이 `inner` / `middle` / `visible` / `none` 중 하나가 아님 (예전 이름 `outer`도 버림)

표에 없는 값(선택 값, 디버깅용)은 검사하지 않는다.

### 연결 상태 (Last Will)
- `stillsafe/status/hand`, `stillsafe/status/fall`로 `online` / `offline`(글자, JSON 아님)을 받는다.
- `offline`을 받으면 3초를 기다리지 않고 **바로** 장치 이상으로 본다. `online`이 오면 풀린다.

## 위험 단계 판단
높은 단계부터 검사하고, 처음 걸리는 것을 쓴다.

| 단계 | 이유 (`reason`) | 조건 |
| --- | --- | --- |
| 3 | `device_error` | 장치 하나라도 정상 메시지가 3초 넘게 없음 (한 번도 못 받은 것 포함), 또는 `offline` 수신 |
| 3 | `hand_inner` | 손 위험 구역 (`signal.inner`) |
| 3 | `fall` | 쓰러짐 확정 (`signal.fall`) |
| 2 | `hand_middle` | 손 경고 구역 (`signal.middle`) |
| 1 | `two_people` | `people < 2`가 3초 이상 이어짐 |
| 0 | `safe` | 해당 없음 |

- 판단은 확정값 `signal`로만 한다. `zone`(한 프레임 값)이 `inner`여도 `signal.inner`가 `false`면 아직 안전이다.
- 위험끼리 겹치면 위에서 먼저 검사한 이유 하나만 나온다 (예: 위험 구역 + 쓰러짐 → `hand_inner`).
- 올라갈 때는 바로 바뀐다.
- 주의(1), 경고(2)에서 내려갈 때는 낮은 판단이 2초 이어져야 내려간다 (깜빡임 방지).
- 지금은 GPIO 대신 MQTT 메시지의 `signal` 값으로 판단한다 (6단계에서 GPIO로 교체).

## 설정값
| 이름 | 값 | 뜻 |
| --- | --- | --- |
| `TIMEOUT_SEC` | 3 | 장치 끊김 기준 |
| `HOLD_SEC` | 2 | 주의·경고 유지 시간 |
| `TWO_PERSON_SEC` | 3 | 인원 부족 지속 기준 (**팀 미정**, 임시값) |
| `PING_SEC` | 0.2 | `PING` 보내는 간격 |
| `PONG_TIMEOUT_SEC` | 1 | 이 시간 넘게 `PONG`이 없으면 응답 없음 |
| `REOPEN_SEC` | 2 | 포트가 닫혔을 때 다시 열어 보는 간격 |

## 진행 상황
| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | MQTT 수신 | 완료 |
| 2 | 형식 검사 (`SCHEMA`, 값 종류까지) | 완료 |
| 3 | 장치 끊김 감지 (3초, `offline` 즉시) | 완료 |
| 4 | 위험 단계 판단, 인원 부족 지속, 2초 유지 | 완료 |
| 5 | ESP32 시리얼 (`PING`, `LEVEL`, 끊기면 다시 열기) | 완료 (가짜 ESP32로 확인, 실물 시험 전) |
| 6 | GPIO 위험 신호 읽기 | |
| 7 | 로그 CSV | |
| 8 | 재가동 흐름, 위험 잠금 | |

## 아직 안 된 것
- 위험(3)이 자동으로 풀림 -> 8단계에서 잠금으로 바꿈
- 모터가 돌 때만 경보 -> ESP32 모터 상태(`esp.motor`)를 받으므로 이제 넣을 수 있음
- `LEVEL`을 바뀔 때만 보냄 -> ESP32가 혼자 재부팅되면(포트는 열린 채) 단계를 모름. 1초마다 다시 보내기 검토
- ESP32 응답 없음을 장치 이상(3단계)으로 볼지 -> 팀 결정 필요
- 실물 ESP32 펌웨어가 아직 통신 약속 명령(`PING`, `LEVEL` 등)을 처리하지 않음
- 위험이 겹칠 때 이유를 하나만 남김 -> 7단계(로그)에서 여러 개 남기기
- GPIO 콜백이 들어오면 수신 스레드와 겹침 -> 6단계에서 큐 하나로 모아 메인 루프에서만 판단
