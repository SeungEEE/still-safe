import numpy as np

class FallStateTracker:
    def __init__(self, trigger_streak=2, recover_frames=10, lost_grace_frames=15):
        self.state = "NORMAL"          # "NORMAL" or "FALLEN"
        self.fall_streak = 0           # 연속 낙상 감지 카운트
        self.recover_streak = 0        # 연속 기립 복귀 카운트
        self.lost_frames = 0           # 쓰러진 후 사람 미검출 프레임 수
        self.fall_start_ts = None
        self.prev_norm_xy = None

        self.trigger_streak = trigger_streak
        self.recover_frames = recover_frames
        self.lost_grace_frames = lost_grace_frames

    def update(self, model_fall: bool, geom: dict, frame_ts: float):
        # 1. 관절 프레임 간 이동량(움직임 변화율) 계산
        motion = 0.0
        if geom["valid"] and self.prev_norm_xy is not None:
            motion = float(np.mean(np.linalg.norm(geom["norm_xy"] - self.prev_norm_xy, axis=1)))
        self.prev_norm_xy = geom["norm_xy"].copy() if geom["valid"] else None

        # 2. 상태 머신 분기
        if self.state == "NORMAL":
            if model_fall:
                self.fall_streak += 1
            else:
                self.fall_streak = 0

            # 연속 trigger_streak 이상 낙상 모델이 반응하면 FALLEN 진입
            if self.fall_streak >= self.trigger_streak:
                self.state = "FALLEN"
                self.fall_start_ts = frame_ts
                self.recover_streak = 0
                self.lost_frames = 0

        elif self.state == "FALLEN":
            if not geom["valid"]:
                # 바닥에 쓰러져 관절이 잠깐 가려진 경우 유예 시간 동안 유지
                self.lost_frames += 1
                if self.lost_frames > self.lost_grace_frames:
                    self._reset()
            else:
                self.lost_frames = 0
                # 누워 있음 판별 조건: 몸통 각도 >= 60도 OR 종횡비(H/W) < 1.0
                is_lying_pose = (geom["torso_deg"] >= 60.0) or (geom["aspect_ratio"] < 1.0)
                # 완전히 일어섬 판별 조건: 몸통 각도 < 45도 AND 종횡비(H/W) > 1.3
                is_standing_pose = (geom["torso_deg"] < 45.0) and (geom["aspect_ratio"] > 1.3)

                if is_standing_pose and not is_lying_pose:
                    self.recover_streak += 1
                    if self.recover_streak >= self.recover_frames:
                        self._reset()
                else:
                    self.recover_streak = 0

        is_lying = (self.state == "FALLEN")
        lying_sec = round(frame_ts - self.fall_start_ts, 2) if (is_lying and self.fall_start_ts) else 0.0
        return is_lying, lying_sec, round(motion, 4)

    def _reset(self):
        self.state = "NORMAL"
        self.fall_streak = 0
        self.recover_streak = 0
        self.lost_frames = 0
        self.fall_start_ts = None
        self.prev_norm_xy = None