"""테스트셋 QA 생성 프롬프트 (질문 유형별, 산업안전 도메인 특화).

(reference app/evaluation/dataset/prompts.py 이식)
"""

# 2026.08.03(sooyeon.choi) 수정 - 운영 RAG의 형식 지시를 제외하고 내용 품질 원칙 반영
_COMMON_RULES = """규칙:
1. 질문은 반드시 자립적이어야 합니다 — "이 문서", "위 내용", "해당 조항" 같은 지시어를 절대 사용하지 마십시오.
2. 질문은 실제 산업안전 담당자가 검색창에 입력할 법한 자연스러운 한국어 질문이어야 합니다.
3. 답변은 제공된 본문에만 근거해야 하며, 본문에 없는 내용을 추가하지 마십시오.
4. 답변에 수치, 기준값, 법규 조항이 있으면 정확히 그대로 인용하십시오.
5. 질문에 여러 대상, 조건, 절차 또는 비교 항목이 있으면 모든 항목에 빠짐없이 답하십시오.
6. 답변은 불필요한 도입이나 반복 없이 질문의 답부터 직접 작성하십시오.
7. 답변은 자연스러운 한국어 하십시오체의 완전한 문장으로 작성하십시오.
8. 서로 독립적인 기준, 조건 또는 절차는 의미 단위의 문장으로 분리하십시오.
9. 본문에 적용 대상, 조건, 예외, 시점, 수치 또는 단위가 있으면 누락하거나 바꾸지 마십시오.
10. 질문과 답변에는 중국어와 한자를 단 한 글자도 사용하지 마십시오. 원문에 한자가 있으면 의미를 유지하여 한글로 풀어 쓰십시오.
11. 반드시 아래 JSON 형식으로만 출력하십시오. 다른 텍스트를 붙이지 마십시오.

출력 형식:
{"question": "...", "answer": "..."}"""

_TYPE_INSTRUCTIONS = {
    "factual": """다음 본문에서 **사실 확인형** 질문 1개를 생성하십시오.
수치, 기준값, 정의, 명칭 등 구체적 사실을 묻는 질문이 좋습니다.
예: "안전난간의 상부 난간대 높이 기준은 얼마인가요?\"""",
    "procedural": """다음 본문에서 **절차/방법형** 질문 1개를 생성하십시오.
작업 절차, 조치 순서, 수행 방법을 묻는 질문이 좋습니다.
예: "밀폐공간 작업 전 산소농도 측정은 어떤 절차로 해야 하나요?\"""",
    "comparative": """다음 본문에서 **비교형** 질문 1개를 생성하십시오.
본문 내 두 가지 이상의 항목·조건·기준을 대비하는 질문이 좋습니다.
예: "일반 작업과 중량물 취급 작업의 안전조치는 어떻게 다른가요?\"""",
    "multihop": """다음 **두 개의 본문을 모두 참고해야만 답할 수 있는** 질문 1개를 생성하십시오.
한 본문만으로는 답변이 불완전해야 하며, 답변에는 본문 1과 본문 2의 핵심 사실이 각각 포함되어야 합니다.
예: 본문1의 기준과 본문2의 절차를 결합해야 답할 수 있는 질문""",
}

SYSTEM_PROMPT = (
    "당신은 산업안전 분야 RAG 시스템의 평가용 질문-답변 데이터셋을 만드는 전문가입니다. "
    "질문과 답변은 한글 기반의 한국어로만 작성하고 중국어 또는 한자를 단 한 글자도 사용하지 않으며, "
    "지정된 JSON 형식으로만 출력합니다."
)


def build_qa_generation_prompt(
    question_type: str,
    chunk_text: str,
    second_chunk_text: str | None = None,
    section_title: str | None = None,
) -> str:
    """질문 유형별 QA 생성 사용자 프롬프트를 만든다."""
    instruction = _TYPE_INSTRUCTIONS.get(question_type, _TYPE_INSTRUCTIONS["factual"])
    parts = [instruction, "", _COMMON_RULES, ""]
    if section_title:
        parts.append(f"[섹션] {section_title}")
    if question_type == "multihop" and second_chunk_text:
        parts.append(f"[본문 1]\n{chunk_text}")
        parts.append(f"\n[본문 2]\n{second_chunk_text}")
    else:
        parts.append(f"[본문]\n{chunk_text}")
    return "\n".join(parts)


# 지시어 포함 질문 자동 필터 (자립성 검사)
DEICTIC_PATTERNS = [
    "이 문서", "위 내용", "해당 문서", "해당 조항", "본 문서",
    "이 조항", "위 문서", "이 본문", "위 본문", "이 표", "위 표",
    "이 자료", "본문에", "본문의",
]


def has_deictic_reference(question: str) -> bool:
    """질문에 지시어가 포함되어 있으면 True (자동 반려 대상)."""
    return any(pattern in question for pattern in DEICTIC_PATTERNS)
