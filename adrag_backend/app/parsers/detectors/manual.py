"""
매뉴얼 문서 판정 모듈

2026.06.04(sooyeon.choi) 판정 모듈 수정 - 다중 신호 가중치 스코어링 방식으로 전환
  기존: 원형번호(①②③) 개수 + 번호섹션 개수 이진 판정
  변경: title/screen/ui/menu_path/step 등 다중 신호를 가중치 합산하여 점수제로 판정
  변경 이유:
    - 기존 방식은 본문 인라인 원형번호(예: "① 위험성 추정...")를 매뉴얼 시그널로 오인식
    - CONTENTS 목차 항목(01. 02. 03.)이 번호섹션으로 오탐되어 일반 안내서가 매뉴얼로 판정됨
    - 예: "2023 새로운 위험성평가 안내서"가 매뉴얼로 오분류된 사례
"""

import re
from typing import Dict


# 2026.06.04(sooyeon.choi) 추가 - 다중 신호 기반 패턴 정의

# 문서 제목에 매뉴얼 키워드가 명시된 경우 (가중치 최고)
_TITLE_MANUAL_PATTERN = re.compile(
    r"(사용자\s*매뉴얼|사용자\s*설명서|운영\s*매뉴얼|관리자\s*매뉴얼|이용\s*가이드)",
    re.IGNORECASE,
)

# 화면 매뉴얼 전용 용어 (메뉴 구조 설명, 화면 설명 등)
_SCREEN_MANUAL_PATTERN = re.compile(
    r"(화면\s*설명|실행방안|버튼\s*설명|메뉴\s*구조|Level\.1|Level\.2|Dashboard)",
    re.IGNORECASE,
)

# UI 조작 동사 (클릭, 저장, 조회 등 화면 조작에 특화된 단어)
# '이동/확인/지정'은 일반 안내문에서도 빈번하므로 단독 UI 신호에서 제외한다.
_UI_ACTION_PATTERN = re.compile(
    r"(클릭|선택|입력|등록|수정|삭제|저장|조회|검색|업로드|다운로드|첨부|"
    r"로그인|체크|해제|팝업|탭|버튼|메뉴|화면|아이콘|그리드|콤보박스)",
    re.IGNORECASE,
)

# 메뉴 경로 패턴 - '>' 구분자만 허용, 양쪽 한글/영문 2자 이상 필수
# '/' 와 '-' 제외 이유: 분수(1/3), 연도범위(2023-19호) 등의 오탐 방지
_MENU_PATH_PATTERN = re.compile(
    r"[가-힣A-Za-z]{2,}[\s가-힣A-Za-z0-9]*\s*>\s*[가-힣A-Za-z]{2,}"
)

# 줄 시작 원형번호만 카운트 - 인라인 열거 표기 제외
# 기존: r'[①②③④⑤⑥⑦⑧⑨⑩]' (인라인도 카운트되어 오탐)
# 변경: ^ 앵커 추가로 줄 첫 글자가 원형번호인 경우만 매뉴얼 시그널로 인정
_CIRCLED_NUMBER_PATTERN = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]", re.MULTILINE)

# 번호 단계 - 0패딩 번호(01. 02.) 제외
## 0패딩 제외 이유: CONTENTS 목차 항목(01. 위험성평가 개요 등)의 오탐 방지
_NUMBERED_STEP_PATTERN = re.compile(r"^\s*(?!0\d)\d{1,2}\.\s+\S+", re.MULTILINE)

# 일반 안내서/법령 문서 신호 - 이 신호가 많으면 감점
_GENERAL_GUIDE_PATTERN = re.compile(
    r"(발간사|CONTENTS|목차|FAQ|자주\s*묻는\s*질문|참고자료|서식|"
    r"법적\s*근거|고시|시행규칙|제\d+조|도입\s*배경|개요)",
    re.IGNORECASE,
)


def count_manual_signals(text: str) -> Dict[str, int]:
    """매뉴얼 시그널 패턴 개수 집계"""
    return {
        "title_manual":   len(_TITLE_MANUAL_PATTERN.findall(text)),
        "screen_manual":  len(_SCREEN_MANUAL_PATTERN.findall(text)),
        "ui_actions":     len(_UI_ACTION_PATTERN.findall(text)),
        "menu_paths":     len(_MENU_PATH_PATTERN.findall(text)),
        "circled_steps":  len(_CIRCLED_NUMBER_PATTERN.findall(text)),
        "numbered_steps": len(_NUMBERED_STEP_PATTERN.findall(text)),
        "general_guides": len(_GENERAL_GUIDE_PATTERN.findall(text)),
    }


def manual_score(text: str) -> int:
    """매뉴얼 판정 점수 계산

    가중치 기준:
      title_manual  (×5): 문서 제목에 '사용자 매뉴얼' 등 명시 → 강한 신호
      screen_manual (×3): '화면 설명', '버튼 설명' 등 화면 매뉴얼 전용 용어
      ui_actions    (×1): 클릭·저장·조회 등 UI 조작 동사
      menu_paths    (×2): 'A > B' 형태 메뉴 경로
      circled_steps (×1): 줄 시작 원형번호 (①②③)
      numbered_steps(×1): 번호 단계 (1. 2. 3., 최대 10점)
      감점: general_guide 신호 >= 4 이고 ui_actions < 10 → -8점
    """
    c = count_manual_signals(text)

    score = 0
    score += min(c["title_manual"],   3) * 5
    score += min(c["screen_manual"],  10) * 3
    score += min(c["ui_actions"],     30) * 1
    score += min(c["menu_paths"],     10) * 2
    score += min(c["circled_steps"],  20) * 1
    # 일반 문서의 장문 번호 목록만으로 임계값을 넘지 않도록 기여도를 제한한다.
    score += min(c["numbered_steps"], 10) * 1

    # 일반 안내서/법령 신호가 충분하고 UI 조작어가 적으면 감점
    # 임계값 4: 5페이지 샘플 기준 CONTENTS·개요·도입배경 등이 4개 이상이면 안내서로 판단
    if c["general_guides"] >= 4 and c["ui_actions"] < 10:
        score -= 8

    return score


def is_manual_like(text: str, score_threshold: int = 18) -> bool:
    """
    화면 매뉴얼 문서 여부 판정.

    판정 방식: 다중 신호 가중치 스코어링 (기존 이진 카운트 방식 대체)

    강제 매뉴얼 shortcut (점수 무관):
      1. 제목에 '사용자 매뉴얼/설명서' 명시 + UI 조작어 >= 5개
      2. 화면 설명 용어 >= 2 + 메뉴 경로 >= 2 + UI 조작어 >= 10

    기본 판정: 매뉴얼 문맥 신호가 있고 manual_score(text) >= score_threshold
    """
    c = count_manual_signals(text)

    # 제목이 사용자매뉴얼/설명서이고 UI 조작어가 충분하면 무조건 매뉴얼로 판정
    if c["title_manual"] >= 1 and c["ui_actions"] >= 5:
        return True

    # 화면 설명 용어 + 메뉴 경로 + UI 조작어 조합이면 매뉴얼로 판정
    if c["screen_manual"] >= 2 and c["menu_paths"] >= 2 and c["ui_actions"] >= 10:
        return True

    # 번호/원형 단계는 일반 안내서에도 흔하므로 구조 신호만으로는 매뉴얼로 보지 않는다.
    has_manual_context = (
        c["title_manual"] >= 1
        or c["screen_manual"] >= 1
        or c["menu_paths"] >= 1
        or c["ui_actions"] >= 10
    )
    return has_manual_context and manual_score(text) >= score_threshold
