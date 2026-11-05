from app.parsers.detectors.manual import (
    count_manual_signals,
    is_manual_like,
    manual_score,
)


def test_numbered_safety_rules_are_not_manual():
    rules = "\n".join(
        f"{number}. 현장에서 지켜야 할 핵심 안전수칙입니다"
        for number in range(1, 21)
    )
    text = f"""현장에서 지켜야 할 핵심 안전수칙
참고자료 20대 수칙
작업 전 상태를 확인하고 안전한 이동 경로를 확인하세요.
{rules}
"""

    signals = count_manual_signals(text)

    assert signals["numbered_steps"] == 20
    assert signals["ui_actions"] == 0
    assert manual_score(text) < 18
    assert is_manual_like(text) is False


def test_numbered_steps_alone_cannot_make_a_manual():
    text = "\n".join(f"{number}. 일반 안내 항목" for number in range(1, 21))

    assert is_manual_like(text, score_threshold=10) is False


def test_explicit_user_manual_with_ui_actions_still_matches():
    text = """사용자 매뉴얼
1. 로그인 화면에서 아이디를 입력합니다.
2. 조회 버튼을 클릭합니다.
3. 항목을 선택하고 저장합니다.
"""

    assert is_manual_like(text) is True


def test_screen_manual_signals_still_match():
    text = """화면 설명
메뉴 구조
관리 메뉴 > 사용자 관리
설정 메뉴 > 권한 관리
버튼을 클릭하고 항목을 선택한 뒤 입력, 등록, 수정, 삭제, 저장, 조회합니다.
화면에서 검색 버튼을 클릭합니다.
"""

    assert is_manual_like(text) is True
