// ===================================================
//  Still Safe ESP32 펌웨어 (통신 약속 6장)
//  Pi C 와 USB 시리얼(115200)로 "한 줄에 명령 하나"를 주고받는다.
//
//  Pi C -> ESP32 : PING, LEVEL:0~3, UNLOCK, START
//  ESP32 -> Pi C : PONG, MOTOR:0/1, LATCH:0/1, SWITCH:START,
//                  SWITCH:A:0/1, SWITCH:B:0/1,
//                  BACKUP:HAND:0/1, BACKUP:FALL:0/1, ERR:<이유>
//
//  ESP32 가 스스로 멈추는 경우 (Pi C 명령 없이도)
//    - PING 이 0.5초 넘게 안 옴          -> 정지 + 잠금
//    - 백업선 GPIO25 또는 26 이 LOW      -> 정지 + 잠금
//    - 전원을 켰을 때                     -> 잠금 상태로 시작
//    - 도는 중 시작 스위치가 하나라도 내려감 -> 정지 (잠그지 않음)
// ===================================================

// ---- 핀 (실제 배선 기준) ----
const int MOTOR_EN    = 23;   // L293D EN (PWM)
const int MOTOR_IN1   = 22;   // L293D IN1
const int MOTOR_IN2   = 21;   // L293D IN2
const int LED_G       = 4;    // 초록 LED
const int LED_Y       = 17;   // 노랑 LED
const int LED_R       = 16;   // 빨강 LED
const int BUZZER      = 18;   // 부저 (능동 부저: HIGH = 소리)
const int SW_A        = 32;   // 시작 스위치 A -> GND (내부 풀업, LOW = 올림)
const int SW_B        = 33;   // 시작 스위치 B -> GND (내부 풀업, LOW = 올림)
const int BACKUP_HAND = 25;   // <- Pi A GPIO27 (내부 풀다운, LOW = 위험)
const int BACKUP_FALL = 26;   // <- Pi B GPIO17 (내부 풀다운, LOW = 위험)

// ---- 설정 ----
// 시작 스위치 개수: 2 = A·B 둘 다 (B안), 1 = A 하나, 0 = 스위치 없음 (시험용: START 명령만으로 시작)
const int SWITCH_COUNT = 0;
const bool USE_BACKUP   = true;   // Pi A·B 없이 책상에서 시험할 때만 false. 실제 운전에서는 반드시 true

const int SPEED = 255;                     // 모터 속도 0~255
const unsigned long WATCHDOG_MS = 500;     // PING 이 이 시간 넘게 없으면 정지 + 잠금
const unsigned long REPORT_MS   = 500;     // MOTOR, LATCH 보고 간격
const unsigned long TOGETHER_MS = 500;     // 두 스위치가 이 시간 안에 함께 올라가야 시작 요청
const unsigned long DEBOUNCE_MS = 30;      // 스위치 떨림 무시 시간
const unsigned long BRAKE_MS    = 300;     // 브레이크 거는 시간
const unsigned int  MAX_LINE    = 32;      // 한 줄 최대 길이

// ---- 상태 ----
int level = 0;                    // Pi C 가 보낸 단계
unsigned long levelSince = 0;     // 단계가 바뀐 시각 (1단계 부저 1회용)
bool latched = true;              // 정지 잠금 (전원 켜면 잠금)
String latchReason = "power_on";  // 왜 잠겼는지
bool latchQuiet = true;           // 부저 없이 조용히 잠긴 상태 (전원 켤 때, 모터가 서 있을 때 PING 끊김)
bool motorOn = false;
bool braking = false;
unsigned long brakeStart = 0;
unsigned long lastPing = 0;
unsigned long lastReport = 0;

bool backupHand = false;          // true = 위험
bool backupFall = false;
bool backupReported[2] = {false, false};
bool backupFirst = true;          // 처음 한 번은 무조건 보고

// 스위치: [0] = A, [1] = B
const int SW_PIN[2] = {SW_A, SW_B};
const char SW_NAME[2] = {'A', 'B'};
bool swRaw[2] = {false, false};             // 방금 읽은 값 (true = 올림)
bool swUp[2] = {false, false};              // 떨림이 가라앉은 값
unsigned long swChangedAt[2] = {0, 0};
unsigned long swUpAt[2] = {0, 0};           // 올라간 시각
bool armed = false;                          // 둘 다 내려간 적이 있어야 시작 요청 가능

// 줄 읽기
String buf = "";
bool skipping = false;            // 너무 긴 줄은 줄 끝까지 버림


// ---------- 모터 ----------
void motorStart() {
  braking = false;
  digitalWrite(MOTOR_IN1, HIGH);
  digitalWrite(MOTOR_IN2, LOW);
  ledcWrite(MOTOR_EN, SPEED);
  if (!motorOn) {
    motorOn = true;
    Serial.println("MOTOR:1");
  }
}

void motorStop() {
  // 양쪽 HIGH = 브레이크. delay 없이 BRAKE_MS 뒤 loop 에서 전원을 끈다
  digitalWrite(MOTOR_IN1, HIGH);
  digitalWrite(MOTOR_IN2, HIGH);
  ledcWrite(MOTOR_EN, 255);
  braking = true;
  brakeStart = millis();
  if (motorOn) {
    motorOn = false;
    Serial.println("MOTOR:0");
  }
}

void updateBrake() {
  if (braking && millis() - brakeStart >= BRAKE_MS) {
    ledcWrite(MOTOR_EN, 0);
    digitalWrite(MOTOR_IN1, LOW);
    digitalWrite(MOTOR_IN2, LOW);
    braking = false;
  }
}

// 정지 + 잠금. 이미 잠겨 있고 모터도 서 있으면 아무것도 안 한다 (ERR 반복 방지)
void stopAndLatch(const char* reason) {
  if (latched && !motorOn) return;
  bool wasRunning = motorOn;
  motorStop();
  if (!latched) {
    latched = true;
    latchReason = reason;
    // 모터가 서 있을 때 Pi C 가 꺼진 것(PING 끊김)은 위험이 아니므로 부저 없이 잠그기만 한다
    latchQuiet = strcmp(reason, "heartbeat_lost") == 0 && !wasRunning;
    Serial.println("LATCH:1");
  }
  Serial.print("ERR:");
  Serial.println(reason);
}


// ---------- 백업 직통선 ----------
bool backupDanger() {
  return USE_BACKUP && (backupHand || backupFall);
}

void readBackup() {
  if (!USE_BACKUP) return;
  backupHand = digitalRead(BACKUP_HAND) == LOW;
  backupFall = digitalRead(BACKUP_FALL) == LOW;

  if (backupFirst || backupHand != backupReported[0]) {
    Serial.println(backupHand ? "BACKUP:HAND:1" : "BACKUP:HAND:0");
    backupReported[0] = backupHand;
  }
  if (backupFirst || backupFall != backupReported[1]) {
    Serial.println(backupFall ? "BACKUP:FALL:1" : "BACKUP:FALL:0");
    backupReported[1] = backupFall;
  }
  backupFirst = false;

  if (backupHand) stopAndLatch("backup_hand");
  else if (backupFall) stopAndLatch("backup_fall");
}


// ---------- 시작 스위치 (B안: 둘 다 올려야 시작, 하나라도 내리면 정지) ----------
int switchCount() {
  return SWITCH_COUNT;
}

bool allSwitchesUp() {
  for (int i = 0; i < switchCount(); i++) if (!swUp[i]) return false;
  return true;
}

bool allSwitchesDown() {
  for (int i = 0; i < switchCount(); i++) if (swUp[i]) return false;
  return true;
}

void readSwitches() {
  if (SWITCH_COUNT == 0) return;       // 스위치 없음: 시작 요청도, 스위치로 멈추기도 없음
  unsigned long now = millis();

  for (int i = 0; i < switchCount(); i++) {
    bool raw = digitalRead(SW_PIN[i]) == LOW;
    if (raw != swRaw[i]) {             // 값이 바뀌면 시계를 다시 잰다
      swRaw[i] = raw;
      swChangedAt[i] = now;
    }
    if (now - swChangedAt[i] >= DEBOUNCE_MS && swUp[i] != swRaw[i]) {
      swUp[i] = swRaw[i];              // 떨림이 가라앉았으니 확정
      if (swUp[i]) swUpAt[i] = now;
      Serial.print("SWITCH:");
      Serial.print(SW_NAME[i]);
      Serial.println(swUp[i] ? ":1" : ":0");
    }
  }

  if (allSwitchesDown()) armed = true;

  // 도는 중 하나라도 내려가면 바로 정지 (사람이 일부러 멈춘 것이라 잠그지 않음)
  if (motorOn && !allSwitchesUp()) {
    motorStop();
    Serial.println("ERR:switch_released");
  }

  // 둘 다 내렸다가 함께 올렸을 때만 시작 요청
  if (armed && allSwitchesUp()) {
    armed = false;
    bool together = true;
    if (SWITCH_COUNT == 2) {
      unsigned long gap = swUpAt[0] > swUpAt[1] ? swUpAt[0] - swUpAt[1] : swUpAt[1] - swUpAt[0];
      together = gap <= TOGETHER_MS;
    }
    Serial.println(together ? "SWITCH:START" : "ERR:switch_not_together");
  }
}


// ---------- 명령 처리 ----------
void setLevel(int n) {
  if (n != level) {
    level = n;
    levelSince = millis();
  }
  if (level == 3) stopAndLatch("danger");
}

void unlock() {
  if (!latched) {
    Serial.println("LATCH:0");
    return;
  }
  if (backupDanger()) {                 // 백업선이 아직 위험이면 거부
    Serial.println("ERR:still_danger");
    return;
  }
  if (level == 3) {                     // Pi C 는 LEVEL:0 을 먼저 보내야 함
    Serial.println("ERR:still_danger");
    return;
  }
  if (millis() - lastPing > WATCHDOG_MS) {
    Serial.println("ERR:heartbeat_lost");
    return;
  }
  latched = false;
  latchReason = "";
  Serial.println("LATCH:0");
}

void startMotor() {
  if (latched) {
    Serial.println("ERR:start_blocked");
    return;
  }
  if (!allSwitchesUp()) {
    Serial.println("ERR:switch_off");
    return;
  }
  motorStart();
}

void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line == "PING") {
    lastPing = millis();
    Serial.println("PONG");
  } else if (line.startsWith("LEVEL:")) {
    String v = line.substring(6);
    if (v.length() == 1 && v[0] >= '0' && v[0] <= '3') {
      setLevel(v[0] - '0');
    } else {
      Serial.println("ERR:bad_level");
    }
  } else if (line == "UNLOCK") {
    unlock();
  } else if (line == "START") {
    startMotor();
  } else {
    Serial.println("ERR:unknown_command");
  }
}

// 글자를 바구니(buf)에 모았다가 줄 끝(\n)이 오면 한 줄로 처리한다.
// readStringUntil 은 줄 끝을 최대 1초 기다리며 loop 를 멈추므로 쓰지 않는다.
void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (!skipping) handleLine(buf);
      buf = "";
      skipping = false;
    } else if (c != '\r' && !skipping) {
      buf += c;
      if (buf.length() > MAX_LINE) {   // 줄 끝 없이 쓰레기만 계속 오는 경우
        Serial.println("ERR:line_too_long");
        buf = "";
        skipping = true;
      }
    }
  }
}


// ---------- 워치독 ----------
void checkWatchdog() {
  if (!latched && millis() - lastPing > WATCHDOG_MS) {
    stopAndLatch("heartbeat_lost");
  }
}


// ---------- 부저, LED (통신 약속 6-2) ----------
void updateOutputs() {
  unsigned long now = millis();
  bool g = false, y = false, r = false, bz = false;

  if (latched) {
    r = (now / 100) % 2 == 0;            // 빨강 빠르게 깜빡임
    // 조용한 잠금이라도 잠긴 뒤에 위험(단계 3, 백업선)이 오면 울린다
    bz = !latchQuiet || level == 3 || backupDanger();
  } else if (level == 3) {
    r = (now / 100) % 2 == 0;
    bz = true;
  } else if (level == 2) {
    y = (now / 500) % 2 == 0;            // 노랑 깜빡임
    bz = y;                              // 0.5초 간격 반복
  } else if (level == 1) {
    y = true;                            // 노랑 켜짐
    bz = now - levelSince < 500;         // 0.5초 1회
  } else {
    g = true;                            // 초록 켜짐
  }

  digitalWrite(LED_G, g);
  digitalWrite(LED_Y, y);
  digitalWrite(LED_R, r);
  digitalWrite(BUZZER, bz);
}


// ---------- 주기 보고 ----------
void report() {
  if (millis() - lastReport >= REPORT_MS) {
    lastReport = millis();
    Serial.println(motorOn ? "MOTOR:1" : "MOTOR:0");
    Serial.println(latched ? "LATCH:1" : "LATCH:0");
  }
}


void setup() {
  Serial.begin(115200);

  pinMode(MOTOR_IN1, OUTPUT);
  pinMode(MOTOR_IN2, OUTPUT);
  ledcAttach(MOTOR_EN, 1000, 8);
  ledcWrite(MOTOR_EN, 0);
  digitalWrite(MOTOR_IN1, LOW);
  digitalWrite(MOTOR_IN2, LOW);

  pinMode(LED_G, OUTPUT);
  pinMode(LED_Y, OUTPUT);
  pinMode(LED_R, OUTPUT);
  pinMode(BUZZER, OUTPUT);

  pinMode(SW_A, INPUT_PULLUP);
  pinMode(SW_B, INPUT_PULLUP);
  pinMode(BACKUP_HAND, INPUT_PULLDOWN);
  pinMode(BACKUP_FALL, INPUT_PULLDOWN);

  // 켤 때 이미 올라가 있는 스위치는 그대로 기억 (둘 다 내렸다가 올려야 시작 요청)
  for (int i = 0; i < 2; i++) {
    swRaw[i] = swUp[i] = digitalRead(SW_PIN[i]) == LOW;
  }
}

void loop() {
  readSerial();       // 1) Pi C 명령
  checkWatchdog();    // 2) PING 끊김
  readBackup();       // 3) 백업 직통선
  readSwitches();     // 4) 시작 스위치
  updateBrake();      // 5) 브레이크 끝내기
  updateOutputs();    // 6) 부저, LED
  report();           // 7) MOTOR, LATCH 주기 보고
}
