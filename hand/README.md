# hand

Pi A 손끼임 파이: AI 카메라로 손 위치를 탐지해 Pi C로 보낸다.

## 저장 영상 추론 및 속도 측정

필요 파일:
- `best.onnx`: 손 세그멘테이션 ONNX 모델
- `hand_video.mp4`: 테스트 영상

현재 스크립트는 위 파일을 사용자 홈 디렉터리에서 읽는다.
모델과 영상은 별도로 준비한다.

### 브라우저로 추론 결과 확인

```bash
python hand_video_test.py
```

브라우저에서 `http://<라즈베리파이 IP>:8080` 접속.

구역은 inner / middle / visible / none으로 구분한다.
구역 좌표는 임시값이며 ZONES에서 수정한다.

### 속도 측정

`hand_video_test.py`와 `hand_benchmark.py`를 같은 폴더에 둔다.

```bash
python hand_benchmark.py --frames 100
```

워밍업 5회 제외. 모델 추론시간과 전체 처리시간을 측정한다.
전체 처리시간에는 영상 읽기, 전처리, 마스크 복원, 구역 판정이 포함된다.
웹 표시와 MQTT 전송은 제외한다.

### 현재 측정 결과

Raspberry Pi 4 CPU, 저장 영상 앞 100프레임 기준:
- 평균 ONNX 추론: 622.47ms
- 평균 전체 처리: 641.43ms
- 처리 속도: 1.56 FPS