"""평가 답변의 누락된 인라인 인용을 한 번 보정하는 헬퍼."""

from typing import Any, Dict, Optional

from app.core.user_messages import is_no_context_answer
from app.utils.citation_parser import extract_citation_ids


def has_valid_citation(answer: str, context_count: int) -> bool:
    """답변에 실제 컨텍스트 범위 안의 [N]이 하나라도 있는지 확인한다."""
    return any(1 <= citation_id <= context_count for citation_id in extract_citation_ids(answer))


async def repair_missing_citations(
    *,
    answer: str,
    final_context: str,
    context_count: int,
    llm_provider: Any,
) -> Optional[str]:
    """내용은 유지하고 인용만 보정하며, 유효한 [N]을 얻었을 때만 반환한다."""
    if (
        not answer.strip()
        or context_count <= 0
        or is_no_context_answer(answer)
        or has_valid_citation(answer, context_count)
    ):
        return None

    available_numbers = ", ".join(f"[{index}]" for index in range(1, context_count + 1))
    messages: list[Dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "당신은 답변의 인용 표기만 교정합니다. 답변의 내용, 순서, 문장 의미를 변경하지 마십시오. "
                "각 문장을 제공 문서와 대조하여 근거가 확인되는 문장 끝에만 [N]을 추가하십시오. "
                f"사용 가능한 인용 번호는 {available_numbers}뿐입니다. 수정된 최종 답변만 출력하십시오."
            ),
        },
        {
            "role": "user",
            "content": f"[제공 문서]\n{final_context}\n\n[인용이 누락된 답변]\n{answer}",
        },
    ]
    response = await llm_provider.chat(messages, temperature=0.0)
    repaired = response.choices[0].message.content.strip() if response.choices else ""
    return repaired if has_valid_citation(repaired, context_count) else None
