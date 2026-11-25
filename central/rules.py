TWO_PERSON_SEC = 3

def decide_level(hand, fall, all_ok, short_sec):
    """hand, fall: 마지막으로 받은 메시지 (딕셔너리)
    all_ok: 장치 두 개가 모두 정상이면 True
    돌려주는 값: (단계, 이유)"""

    # 3 위험
    if not all_ok:
        return 3, "device_error"

    if hand["signal"]["inner"]:
        return 3, "hand_inner"

    if fall["signal"]["fall"]:
        return 3, "fall"

    # 2 경고
    if hand["signal"]["middle"]:
        return 2, "hand_middle"

    # 1 주의
    if short_sec >= TWO_PERSON_SEC:
        return 1, "two_people"

    # 0 안전
    return 0, "safe"


# ---------- 시험 ----------

def make_hand(inner=False, middle=False, zone=None):
    """Pi A 메시지 중 판단에 쓰는 부분만 만든다.
    zone을 안 주면 signal에 맞춰 정한다."""
    if zone is None:
        zone = "inner" if inner else "middle" if middle else "none"
    return {"zone": zone, "signal": {"inner": inner, "middle": middle}}


def make_fall(fall=False, people=2):
    """Pi B 메시지 중 판단에 쓰는 부분만 만든다."""
    return {"people": people, "signal": {"fall": fall}}


# (설명, hand, fall, all_ok, short_sec, 기대 단계, 기대 이유)
CASES = [
    # 기본: 하나씩만 걸릴 때
    ("안전",                    make_hand(),            make_fall(),                True,  0,   0, "safe"),
    ("경고 구역",               make_hand(middle=True), make_fall(),                True,  0,   2, "hand_middle"),
    ("위험 구역",               make_hand(inner=True),  make_fall(),                True,  0,   3, "hand_inner"),
    ("쓰러짐",                  make_hand(),            make_fall(fall=True),       True,  0,   3, "fall"),
    ("인원 부족 5초",           make_hand(),            make_fall(people=1),        True,  5,   1, "two_people"),
    ("장치 이상",               make_hand(),            make_fall(),                False, 0,   3, "device_error"),

    # 우선순위: 둘 이상 동시에 걸릴 때 (높은 단계, 같은 단계면 위에서 먼저 검사한 것)
    ("장치 이상 + 위험 구역",   make_hand(inner=True),  make_fall(),                False, 0,   3, "device_error"),
    ("위험 구역 + 쓰러짐",      make_hand(inner=True),  make_fall(fall=True),       True,  0,   3, "hand_inner"),
    ("위험 + 경고 신호 동시",   make_hand(inner=True, middle=True), make_fall(),    True,  0,   3, "hand_inner"),
    ("쓰러짐 + 경고 구역",      make_hand(middle=True), make_fall(fall=True),       True,  0,   3, "fall"),
    ("쓰러짐 + 사람 1명",       make_hand(),            make_fall(fall=True, people=1), True, 5, 3, "fall"),
    ("경고 구역 + 인원 부족",   make_hand(middle=True), make_fall(people=1),        True,  5,   2, "hand_middle"),

    # 경계값: TWO_PERSON_SEC = 3
    ("인원 부족 2.9초",         make_hand(),            make_fall(people=1),        True,  2.9, 0, "safe"),
    ("인원 부족 정확히 3초",    make_hand(),            make_fall(people=1),        True,  3,   1, "two_people"),
    ("인원 부족 1초",           make_hand(),            make_fall(people=1),        True,  1,   0, "safe"),

    # zone과 signal이 다를 때: 판단은 확정값(signal)으로만 한다
    ("위험 구역 첫 프레임 (확정 전)", make_hand(zone="inner"), make_fall(),         True,  0,   0, "safe"),
    ("zone만 middle, signal 아직", make_hand(zone="middle"), make_fall(),           True,  0,   0, "safe"),
    ("손 보임, 박스 밖",        make_hand(zone="visible"), make_fall(),             True,  0,   0, "safe"),
]


if __name__ == "__main__":
    passed = 0
    for desc, hand, fall, all_ok, short_sec, want_level, want_reason in CASES:
        got = decide_level(hand, fall, all_ok, short_sec)
        if got == (want_level, want_reason):
            passed += 1
        else:
            print(f"실패: {desc}")
            print(f"  기대 {(want_level, want_reason)}, 결과 {got}")

    print(f"통과 {passed} / 전체 {len(CASES)}")
