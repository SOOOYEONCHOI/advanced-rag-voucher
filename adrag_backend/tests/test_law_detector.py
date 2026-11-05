from app.parsers.detectors.law import is_law_like


def test_existing_toc_law_still_matches():
    text = "\n".join(f"제{i}조(조문 제목 {i})" for i in range(1, 8))

    assert is_law_like(text, first_page_text=text) is True


def test_official_law_body_without_toc_matches():
    text = """산업안전보건법
[시행 2026. 7. 7.] [법률 제21853호, 2026. 7. 7., 일부개정]
# 제1장 총칙
### 제1조(목적) 이 법은 산업재해를 예방함을 목적으로 한다.
### 제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다.
"""

    assert is_law_like(text, first_page_text=text) is True


def test_manual_with_law_references_does_not_match():
    text = """사용자 매뉴얼
관련 법령 제1조 및 제2조를 확인합니다.
1. 메뉴를 클릭합니다.
2. 저장 버튼을 선택합니다.
"""

    assert is_law_like(text, first_page_text=text) is False
