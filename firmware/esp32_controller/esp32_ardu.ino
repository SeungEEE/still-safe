// ===================================================
//  4가지 상황 테스트 (시리얼 입력) — 모터 + LED + 부저
//  전원: 건전지 없이 ESP32 VIN(5V) → L293D
//
//  [시작/정지]
//    s = 모터 시작 요청 (토글 ON 역할)   x = 모터 정지 (토글 OFF 역할)
//  [상황] 한 번 누르면 발생, 다시 누르면 해제
//    1 = 쓰러짐        → 모터 정지 + 빨강 LED
//    2 = 2인 1조 아님  → 빨강 LED (모터는 계속)
//    3 = 손 DANGER     → 모터 정지 + 빨강 LED
//    4 = 손 CAUTION    → 노랑 LED + 부저 (모터는 계속)
//    0 = 전부 정상
// ===================================================

// ---- 핀 ----
const int MOTOR_EN  = 23;   // L293D 1번 (PWM)
const int MOTOR_IN1 = 22;   // L293D 2번
const int MOTOR_IN2 = 21;   // L293D 7번
const int LED_Y  = 17;      // 노랑 LED
const int LED_R  = 16;      // 빨강 LED
const int LED_G  = 4;       // 초록 LED
const int BUZZER = 18;      // 부저 (없으면 그냥 비워둬도 됨)

const int SPEED = 255;      // 모터 속도 0~255

// ---- 상황 (true = 발생) ----
bool fall = false, noPair = false, danger = false, caution = false;
bool running = false;       // 모터 도는 중?

// ---------- 모터 ----------
void motorRun() {
  digitalWrite(MOTOR_IN1, HIGH);
  digitalWrite(MOTOR_IN2, LOW);
  ledcWrite(MOTOR_EN, SPEED);
}

void motorBrake() {
  digitalWrite(MOTOR_IN1, HIGH);    // 양쪽 HIGH = 브레이크
  digitalWrite(MOTOR_IN2, HIGH);
  ledcWrite(MOTOR_EN, 255);
  delay(300);
  ledcWrite(MOTOR_EN, 0);
}

// ---------- 화면 출력 ----------
void printState() {
  Serial.printf("[상태] 쓰러짐:%s  2인1조X:%s  DANGER:%s  CAUTION:%s  →  모터:%s\n",
                fall ? "발생" : "-", noPair ? "발생" : "-",
                danger ? "발생" : "-", caution ? "발생" : "-",
                running ? "회전" : "정지");
}

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_IN1, OUTPUT);
  pinMode(MOTOR_IN2, OUTPUT);
  ledcAttach(MOTOR_EN, 1000, 8);    // 23번 PWM
  ledcWrite(MOTOR_EN, 0);

  pinMode(LED_Y, OUTPUT);
  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(BUZZER, OUTPUT);

  delay(500);
  Serial.println("=== 4가지 상황 테스트 ===");
  Serial.println("s=시작  x=정지  1=쓰러짐  2=2인1조X  3=DANGER  4=CAUTION  0=전부정상");
  printState();
}

void loop() {
  // 1) 시리얼 입력
  if (Serial.available()) {
    char c = Serial.read();
    if (c != '\n' && c != '\r' && c != ' ') {
      if      (c == '1') fall    = !fall;
      else if (c == '2') noPair  = !noPair;
      else if (c == '3') danger  = !danger;
      else if (c == '4') caution = !caution;
      else if (c == '0') fall = noPair = danger = caution = false;
      else if (c == 's') {
        if (fall || danger) {
          Serial.println(">> 시작 거부! (쓰러짐 또는 DANGER 상태)");
        } else if (!running) {
          running = true;
          motorRun();
          Serial.println(">> 모터 시작");
        }
      }
      else if (c == 'x') {
        if (running) { running = false; motorBrake(); }
        Serial.println(">> 정지 (s로 다시 시작)");
      }
      else {
        Serial.println("s / x / 1 / 2 / 3 / 4 / 0 중에서 입력");
      }

      // 2) 도는 중에 쓰러짐·DANGER → 즉시 정지
      if (running && (fall || danger)) {
        running = false;
        motorBrake();
        Serial.println(">> 비상 정지! 상황 해제 후 s로 다시 시작");
      }
      printState();
    }
  }

  // 3) LED, 부저 (계속 갱신)
  digitalWrite(LED_G, running);                         // 초록: 운전 중
  digitalWrite(LED_R, fall || danger || noPair);        // 빨강: 정지 상황 / 2인 1조 아님
  digitalWrite(LED_Y, caution);                         // 노랑: CAUTION
  digitalWrite(BUZZER, caution && (millis() / 200) % 2); // CAUTION이면 삑삑

  delay(10);
}
