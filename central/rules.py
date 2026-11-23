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
    if hand["signal"]["outer"]:
        return 2, "hand_outer"

    # 1 주의
    if short_sec >= TWO_PERSON_SEC:
        return 1, "two_people"

    # 0 안전
    return 0, "safe"

if __name__ == "__main__":

    # 0. 안전
    hand = {"signal": {"outer": False, "inner": False}}
    fall = {"people": 2, "signal": {"fall": False}}
    print("기대 0:", decide_level(hand, fall, True, 0))

    # 1. 손 바깥 구역 + 사람 2명
    hand = {"signal": {"inner": False, "outer": True}}
    fall = {"people": 2, "signal": {"fall": False}}
    print("기대 2:", decide_level(hand, fall, True, 0))

    # 2. 사람 1명
    hand = {"signal": {"inner": False, "outer": False}}
    fall = {"people": 1, "signal": {"fall": False}}
    print("기대 1:", decide_level(hand, fall, True, 5))

    # 3. 손 바깥 + 사람 1명
    hand = {"signal": {"inner": False, "outer": True}}
    fall = {"people": 1, "signal": {"fall": False}}
    print("기대 2:", decide_level(hand, fall, True, 0))

    # 4. 쓰러짐 + 손 바깥
    hand = {"signal": {"inner": False, "outer": True}}
    fall = {"people": 2, "signal": {"fall": True}}
    print("기대 3:", decide_level(hand, fall, True, 0))

    # 5. 장치 이상
    hand = {"signal": {"inner": False, "outer": False}}
    fall = {"people": 2, "signal": {"fall": False}}
    print("기대 3:", decide_level(hand, fall, False, 0))

    # 6. 손 안쪽 구역
    hand = {"signal": {"inner": True, "outer": False}}
    fall = {"people": 2, "signal": {"fall": False}}
    print("기대 3:", decide_level(hand, fall, True, 0))

    # 사람 1명 + short_sec = 1
    hand = {"signal": {"inner": False, "outer": False}}
    fall = {"people": 1, "signal": {"fall": False}}
    print("기대 0:", decide_level(hand, fall, True, 1))