"""
생성 답변 평가기.

LLM 호출이 필요한 지표(faithfulness, correctness)와
규칙 기반 지표(refusal_correct, format_correct)를 함께 제공한다.

LLM judge는 OllamaJudgeClient(qwen3:14b)를 사용한다.
Ollama가 없거나 오류 시 해당 지표는 None으로 기록된다.
"""

import re
from typing import Dict, Optional

from offline_evaluation.dataset.schema import GoldenRecord
from offline_evaluation.evaluators.base import EvalResult
from offline_evaluation.ollama_client import OllamaJudgeClient

# ── 거절 판정 패턴 ────────────────────────────────────────────
# generate_answer 노드의 시스템 프롬프트가 요구하는 부족 답변 문구와 맞춤
_REFUSAL_PATTERNS = [
    "찾을 수 없", "근거가 없", "정보가 부족", "문서에 없",
    "확인되지 않", "알 수 없", "제공된 문서", "답변하기 어렵",
]

# ── LLM judge 프롬프트 ────────────────────────────────────────
_FAITHFULNESS_PROMPT = """\
[컨텍스트]와 [답변]을 비교한다.
답변이 컨텍스트에 없는 사실을 주장하면 낮은 점수를 준다.
답변이 컨텍스트 근거만 사용했으면 높은 점수를 준다.
0.0(완전 불일치)~1.0(완전 일치) 숫자 하나만 출력한다. 다른 텍스트는 절대 출력하지 않는다.

[컨텍스트]
{context}

[답변]
{answer}

점수:"""

_CORRECTNESS_PROMPT = """\
[기준 답변]과 [실제 답변]의 핵심 사실 일치도를 평가한다.
핵심 사실이 일치하면 높은 점수, 다르거나 누락되면 낮은 점수를 준다.
0.0(완전 불일치)~1.0(완전 일치) 숫자 하나만 출력한다. 다른 텍스트는 절대 출력하지 않는다.

[기준 답변]
{expected}

[실제 답변]
{actual}

점수:"""

# 컨텍스트가 너무 길면 judge 속도가 느려지므로 앞부분만 사용
_CONTEXT_MAX_CHARS = 2000


class AnswerEvaluator:
    """생성 답변 평가기."""

    def __init__(self, ollama_client: OllamaJudgeClient, skip_llm_judge: bool = False):
        self._client = ollama_client
        self._skip_llm_judge = skip_llm_judge

    async def evaluate(self, record: GoldenRecord, result: EvalResult) -> Dict:
        """답변 품질 지표를 계산해 반환한다.

        Returns:
            format_correct   : 한국어 존댓말, <think> 미노출 여부 (규칙 기반)
            refusal_correct  : not_enough_info 케이스의 거절 적합성 (규칙 기반, 해당 없으면 None)
            faithfulness     : 컨텍스트 근거 충실도 0.0~1.0 (LLM judge, 실패 시 None)
            correctness      : 기준 답변과 핵심 사실 일치도 0.0~1.0 (LLM judge, 실패 시 None)
        """
        answer = result.get("generated_answer") or ""
        context = result.get("final_context") or ""
        behavior = record["expected_behavior"]

        return {
            "format_correct": _check_format(answer),
            "refusal_correct": _check_refusal(behavior, answer),
            "faithfulness": None if self._skip_llm_judge else await self._judge_faithfulness(context, answer),
            "correctness": None if self._skip_llm_judge else await self._judge_correctness(
                record["expected_answer"], answer, behavior
            ),
        }

    async def _judge_faithfulness(self, context: str, answer: str) -> Optional[float]:
        """답변이 컨텍스트 밖 정보를 만들어냈는지 판단한다."""
        if not answer or not context:
            return None
        prompt = _FAITHFULNESS_PROMPT.format(
            context=context[:_CONTEXT_MAX_CHARS],
            answer=answer,
        )
        return await _parse_score(self._client.judge(prompt, max_tokens=8))

    async def _judge_correctness(
        self, expected: str, actual: str, behavior: str
    ) -> Optional[float]:
        """기준 답변과 핵심 사실 일치도를 판단한다."""
        # 거절이 맞는 케이스(not_enough_info)는 correctness가 N/A
        if behavior == "not_enough_info" or not actual or not expected:
            return None
        prompt = _CORRECTNESS_PROMPT.format(expected=expected, actual=actual)
        return await _parse_score(self._client.judge(prompt, max_tokens=8))


# ── 규칙 기반 지표 ────────────────────────────────────────────

def _check_format(answer: str) -> bool:
    """한국어 존댓말 종결, <think> 블록 미노출 여부를 확인한다."""
    if not answer:
        return False
    if "<think>" in answer or "</think>" in answer:
        return False
    return bool(re.search(r"(습니다|세요|이에요|예요|합니다|됩니다)\s*\.?\s*$", answer.strip()))


def _check_refusal(behavior: str, answer: str) -> Optional[bool]:
    """not_enough_info 케이스에서 거절 문구가 포함됐는지 확인한다.

    해당 없는 케이스(answer, guardrail 등)는 None을 반환한다.
    """
    if behavior != "not_enough_info":
        return None
    return any(p in answer for p in _REFUSAL_PATTERNS)


# ── 헬퍼 ──────────────────────────────────────────────────────

async def _parse_score(coro) -> Optional[float]:
    """judge 코루틴 결과를 0.0~1.0 float으로 변환한다. 실패 시 None."""
    raw = await coro
    if raw is None:
        return None
    # "0.85" 또는 "점수: 0.85" 등에서 첫 번째 숫자 추출
    match = re.search(r"\d+\.?\d*", raw)
    if not match:
        return None
    try:
        return max(0.0, min(1.0, float(match.group())))
    except ValueError:
        return None
