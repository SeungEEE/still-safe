"""Pi A, B, C가 같이 쓰는 MQTT 메시지 형식 (통신 약속 3장).

SCHEMA 에 적는 규칙
- 종류 (int, bool ...)  : 값이 그 종류여야 한다
- 튜플 (int, float)     : 그중 하나의 종류면 된다
- 리스트 ["a", "b"]     : 그중 하나의 값이어야 한다
- 딕셔너리 {...}        : 안쪽도 같은 방식으로 검사한다

표에 없는 키는 검사하지 않는다 (선택 값, 디버깅용 값은 자유).
"""

NUM = (int, float)   # 시각, 초처럼 소수가 올 수 있는 값

ZONES = ["inner", "middle", "visible", "none"]

SCHEMA = {
    "stillsafe/hand": {
        "v": int,
        "seq": int,
        "ts": NUM,
        "zone": ZONES,
        "signal": {"inner": bool, "middle": bool},
    },
    "stillsafe/fall": {
        "v": int,
        "seq": int,
        "ts": NUM,
        "people": int,
        "lying": bool,
        "lying_sec": NUM,
        "signal": {"fall": bool},
    },
}


def check(data, schema):
    """문제가 있으면 이유(글자)를, 없으면 None 을 돌려준다."""
    if type(data) is not dict:
        return "딕셔너리가 아님"

    for key, rule in schema.items():
        if key not in data:
            return f"{key} 없음"
        value = data[key]

        if type(rule) is dict:          # 안쪽 묶음
            why = check(value, rule)
            if why:
                return f"{key}.{why}"

        elif type(rule) is list:        # 정해진 값 중 하나
            if value not in rule:
                return f"{key} 값이 {rule} 중 하나가 아님: {value!r}"

        else:                           # 종류
            kinds = rule if type(rule) is tuple else (rule,)
            # isinstance 대신 type 을 쓴다: True 가 int 로 통과하지 않게
            if type(value) not in kinds:
                return f"{key} 종류가 틀림: {value!r}"

    return None


if __name__ == "__main__":
    hand_ok = {"v": 1, "seq": 0, "ts": 0, "zone": "none",
               "signal": {"inner": False, "middle": False}}
    fall_ok = {"v": 1, "seq": 0, "ts": 1763452800.123, "people": 2,
               "lying": False, "lying_sec": 0, "signal": {"fall": False}}

    # (설명, 토픽, 메시지, 통과해야 하면 True)
    CASES = [
        ("hand 정상", "stillsafe/hand", hand_ok, True),
        ("fall 정상", "stillsafe/fall", fall_ok, True),
        ("선택 값이 더 있어도 통과", "stillsafe/hand", {**hand_ok, "conf": 0.9, "hands": 2}, True),
        ("딕셔너리가 아님", "stillsafe/hand", [1, 2], False),
        ("필수 값 없음", "stillsafe/hand", {k: v for k, v in hand_ok.items() if k != "seq"}, False),
        ("signal 이 비었음", "stillsafe/hand", {**hand_ok, "signal": {}}, False),
        ("signal 이 딕셔너리가 아님", "stillsafe/hand", {**hand_ok, "signal": 1}, False),
        ("옛 이름 outer", "stillsafe/hand", {**hand_ok, "zone": "outer"}, False),
        ("signal 값이 글자", "stillsafe/fall", {**fall_ok, "signal": {"fall": "false"}}, False),
        ("people 이 글자", "stillsafe/fall", {**fall_ok, "people": "2"}, False),
        ("people 이 true", "stillsafe/fall", {**fall_ok, "people": True}, False),
        ("seq 가 소수", "stillsafe/fall", {**fall_ok, "seq": 1.5}, False),
    ]

    passed = 0
    for desc, topic, data, want_ok in CASES:
        why = check(data, SCHEMA[topic])
        if (why is None) == want_ok:
            passed += 1
        else:
            print(f"실패: {desc} (이유: {why})")
    print(f"통과 {passed} / 전체 {len(CASES)}")
