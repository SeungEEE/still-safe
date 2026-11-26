# esp32_controller

ESP32 펌웨어: Pi C 명령을 받아 모터, 부저, LED, 스위치를 제어한다. 명령은 통신 약속 6장을 따른다.

## 파일
| 파일 | 하는 일 |
| --- | --- |
| `esp32_controller.ino` | 펌웨어 |
| `test_pi.py` | ESP32 하나만 손으로 시험하는 도구 (PING 자동, 명령 직접 입력) |

Arduino IDE에서는 `esp32_controller` 폴더를 열면 된다 (스케치 파일 이름 = 폴더 이름).

## 명령
| 방향 | 명령 | 뜻 |
| --- | --- | --- |
| Pi C → ESP32 | `PING` | 0.2초마다. 0.5초 넘게 안 오면 정지 + 잠금 (`ERR:heartbeat_lost`) |
| Pi C → ESP32 | `LEVEL:0` ~ `LEVEL:3` | 단계. 부저·LED 패턴이 바뀐다. 3이면 정지 + 잠금 (`ERR:danger`) |
| Pi C → ESP32 | `UNLOCK` | 잠금 해제. 백업선 위험, 단계 3, PING 끊김이면 거부 |
| Pi C → ESP32 | `START` | 모터 가동. 잠금 중(`ERR:start_blocked`)이거나 스위치가 안 올라가 있으면(`ERR:switch_off`) 거부 |
| ESP32 → Pi C | `PONG` | PING 응답 |
| ESP32 → Pi C | `MOTOR:0/1`, `LATCH:0/1` | 바뀔 때 + 0.5초마다 |
| ESP32 → Pi C | `SWITCH:A:0/1`, `SWITCH:B:0/1` | 스위치 상태가 바뀔 때 (1 = 올림) |
| ESP32 → Pi C | `SWITCH:START` | 두 스위치를 내렸다가 0.5초 안에 함께 올림 |
| ESP32 → Pi C | `BACKUP:HAND:0/1`, `BACKUP:FALL:0/1` | 백업선 상태가 바뀔 때 (1 = 위험) |
| ESP32 → Pi C | `ERR:<이유>` | `danger`, `heartbeat_lost`, `backup_hand`, `backup_fall`, `start_blocked`, `still_danger`, `switch_off`, `switch_released`, `switch_not_together`, `bad_level`, `unknown_command`, `line_too_long` |

## 핀 (실제 배선 기준)
| ESP32 | 연결 | 비고 |
| --- | --- | --- |
| GPIO 23 | L293D EN | PWM 속도 |
| GPIO 22 / 21 | L293D IN1 / IN2 | 둘 다 HIGH = 브레이크 |
| GPIO 4 / 17 / 16 | LED 초록 / 노랑 / 빨강 | |
| GPIO 18 | 부저 | 능동 부저 (HIGH = 소리) |
| GPIO 32 / 33 | 시작 스위치 A / B → GND | 내부 풀업, LOW = 올림 |
| GPIO 25 | ← Pi A GPIO27 (백업, 손 안쪽) | 내부 풀다운, LOW = 위험 |
| GPIO 26 | ← Pi B GPIO17 (백업, 쓰러짐) | 내부 풀다운, LOW = 위험 |

통신 약속 6-1장 표와 모터·LED 핀 번호가 다르다. 이 표가 실제 배선이면 통신 약속을 고친다.

## 단계별 출력 (통신 약속 6-2)
| 상태 | 부저 | LED |
| --- | --- | --- |
| 0 안전 | 꺼짐 | 초록 켜짐 |
| 1 주의 | 0.5초 1회 | 노랑 켜짐 |
| 2 경고 | 0.5초 간격 반복 | 노랑 깜빡임 |
| 3 위험 / 잠금 | 계속 | 빨강 빠르게 깜빡임 |

아래 두 경우의 잠금은 빨강만 깜빡이고 부저는 울리지 않는다 (위험이 아니라서).
- 전원을 켰을 때
- **모터가 서 있을 때** PING이 끊김 (Pi C를 끄거나 재부팅, `test_pi.py` 종료)

모터가 돌던 중에 PING이 끊기면 부저가 울린다. 조용히 잠긴 뒤라도 단계 3이나 백업선 위험이 오면 울린다.

## 시작 스위치 (B안)
- 두 스위치를 **둘 다 내렸다가 0.5초 안에 함께 올려야** `SWITCH:START`를 보낸다. 켤 때 이미 올라가 있으면 한 번 내려야 한다.
- 도는 중 **하나라도 내려가면** 바로 정지하고 `ERR:switch_released`를 보낸다. 사람이 일부러 멈춘 것이라 잠그지 않는다.
- 스위치 떨림은 30ms 동안 무시한다.

## 설정 (파일 위쪽)
| 이름 | 기본 | 뜻 |
| --- | --- | --- |
| `SWITCH_COUNT` | `0` | 시작 스위치 개수. `2` = A·B (B안), `1` = A 하나, `0` = 스위치 없음 (지금 시험용: `START` 명령만으로 시작, `SWITCH:START`는 안 나감) |
| `USE_BACKUP` | `true` | Pi A·B 없이 책상에서 시험할 때만 `false`. 백업선이 비어 있으면 풀다운 때문에 늘 위험으로 읽혀서 잠금이 안 풀린다. **실제 운전에서는 반드시 `true`** |

## 손 시험 순서 (`test_pi.py`)
1. `LEVEL:0` → 초록. `LEVEL:1` → 노랑 + 삑 1번. `LEVEL:2` → 노랑 깜빡 + 반복 삑.
2. `LEVEL:0` → `UNLOCK` → `[ESP32] LATCH:0`
3. `START` 입력 → `MOTOR:1` (스위치가 있으면 먼저 둘 다 내렸다가 함께 올려 `SWITCH:START` 확인)
4. `LEVEL:3` → `MOTOR:0`, `LATCH:1`, `ERR:danger`
5. 다시 2~3 → `p`로 PING 끄기 → 0.5초 뒤 `ERR:heartbeat_lost`, 정지 + 잠금
6. (스위치가 있을 때만) 다시 2~3 → 스위치 하나 내림 → `ERR:switch_released`, 정지 (잠금 없음)

Pi A·B 백업선을 아직 안 꽂았으면 `USE_BACKUP = false`로 올려야 2번 `UNLOCK`이 된다 (아니면 `ERR:still_danger`).

## 컴파일
```
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/esp32_controller
```
ESP32 보드 패키지 3.x 기준 (`ledcAttach` 사용).
