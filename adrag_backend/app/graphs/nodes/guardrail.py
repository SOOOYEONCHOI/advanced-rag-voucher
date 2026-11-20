"""
가드레일 노드.

RAG 검색 수행 전 질의 유형을 판별한다.
1차 Rule-based → (불확실 시) 2차 LLM Classifier 순서로 처리한다.

판별 결과:
- rag_query      : should_retrieve=True  → analyze_and_rewrite → RAG 파이프라인 진행
- 그 외 (6종)   : should_retrieve=False → build_response로 분기 (사전 정의 응답 반환)

intent 종류:
  greeting         단순 인사말
  smalltalk        잡담성 대화
  irrelevant       서비스 도메인과 무관한 질문
  unsafe           금지된 요청 (보안·개인정보 등)
  empty_or_invalid 의미 없는 문자열
  rag_query        문서 검색이 필요한 정상 질의
"""

import json
import os
import re
import string
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

import yaml

from app.core.config import get_settings
from app.core.user_messages import GREETING_MESSAGE, UserMessageType, get_user_message
from app.graphs.dependencies import GraphDependencies
from app.graphs.state import PipelineState
from app.graphs.utils import timed_node
from app.services.llm_service import get_local_llm_service
from app.utils.log.log import LoggingLogger
from app.prompts.pipeline import GUARDRAIL_CLASSIFIER_PROMPT as _CLASSIFIER_PROMPT

# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용
logger = LoggingLogger().getLogger(__name__)

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "guardrail_config.yaml"
)

VALID_INTENTS = frozenset({
    "greeting", "smalltalk", "irrelevant", "unsafe", "empty_or_invalid", "rag_query"
})

# LLM이 규칙으로 판별하기 어려운 경우(smalltalk·irrelevant·rag_query) 사용하는 분류 프롬프트.
# max_tokens=128로 호출하여 응답 속도를 최소화한다.

def _load_config() -> Dict[str, Any]:
    """파일 버전이 바뀌면 다음 요청에서 자동으로 다시 로드한다."""
    try:
        version = os.stat(_CONFIG_PATH).st_mtime_ns
    except FileNotFoundError:
        version = 0
    return _load_config_version(version)


@lru_cache(maxsize=4)
def _load_config_version(version: int) -> Dict[str, Any]:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning(f"가드레일 설정 파일 없음: {_CONFIG_PATH} — 빈 규칙으로 실행 (LLM fallback 적용)")
        return {}
    except Exception as e:
        logger.error(f"가드레일 설정 파일 로드 실패: {e}")
        return {}


def _normalize(text: str) -> str:
    """소문자 변환 및 앞뒤 구두점·공백 제거."""
    strip_chars = string.punctuation + " \t~^"
    return text.lower().strip().strip(strip_chars)


def _rule_based_check(query: str, config: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """
    규칙 기반 1차 판별.

    처리 순서: empty_or_invalid → unsafe → greeting → rag_keywords
    위 유형에 해당하지 않으면 None을 반환하여 LLM fallback에 위임한다.

    Returns:
        (intent, reason) 또는 None.
    """
    q_stripped = query.strip()
    q_lower = q_stripped.lower()

    # ── 1) 무의미한 입력 ──────────────────────────────────
    for pattern in config.get("empty_or_invalid_patterns", []):
        try:
            if re.fullmatch(pattern, q_stripped):
                return "empty_or_invalid", "의미 없는 문자열"
        except re.error as e:
            logger.warning(f"가드레일 정규식 오류 ({pattern!r}): {e}")

    # ── 2) 금지 키워드 ────────────────────────────────────
    for kw in config.get("unsafe_keywords", []):
        if kw.lower() in q_lower:
            return "unsafe", f"금지 키워드 포함: {kw}"

    # ── 3) 인사말 (구두점 제거 후 정확히 일치) ───────────
    normalized = _normalize(q_stripped)
    for pattern in config.get("greeting_patterns", []):
        if normalized == pattern.lower():
            return "greeting", "단순 인사말"

    # 2026.11.04(sooyeon.choi) 추가 - 조립 작업표준 업무 키워드 포함 시 LLM 분류 없이 rag_query
    # ── 4) 업무 키워드 ────────────────────────────────────
    if config.get("rag_keywords_enabled", False):
        for kw in config.get("rag_keywords", []):
            if kw.lower() in q_lower:
                return "rag_query", f"업무 키워드 포함: {kw}"

    return None


async def _llm_classify(query: str, llm_service=None) -> Tuple[str, str]:
    """
    LLM 기반 2차 분류. rule-based로 판별 불가한 경우에만 호출된다.

    Returns:
        (intent, reason). 오류 시 ("rag_query", "LLM 분류 실패") 반환.
    """
    try:
        llm_service = llm_service or get_local_llm_service()
        messages = [
            {"role": "system", "content": _CLASSIFIER_PROMPT},
            {"role": "user", "content": query},
        ]
        response = await llm_service.chat(messages, max_tokens=128)
        text = response.choices[0].message.content.strip() if response.choices else ""

        # ```json ... ``` 래핑 대응
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]

        parsed = json.loads(text)
        intent = parsed.get("intent", "rag_query").lower().strip()
        reason = parsed.get("reason", "LLM 분류")

        if intent not in VALID_INTENTS:
            logger.warning(f"LLM이 알 수 없는 intent 반환 ({intent!r}) — rag_query로 처리")
            intent = "rag_query"

        return intent, reason
    except Exception as e:
        logger.error(f"가드레일 LLM 분류 실패 — rag_query로 처리: {e}")
        return "rag_query", "LLM 분류 실패"


@timed_node("guardrail")
async def guardrail(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    """질의 유형 판별 및 가드레일 처리 노드."""
    settings = deps.settings if deps else get_settings()

    # 가드레일 비활성화 시 즉시 통과
    if not settings.enable_guardrail:
        return {
            "intent": "rag_query",
            "should_retrieve": True,
            "guardrail_reason": None,
            "response_type": "rag",
        }

    query = state["original_query"].strip()
    config = _load_config()

    # ── 1차: Rule-based ──────────────────────────────────
    rule_result = _rule_based_check(query, config)

    if rule_result is not None:
        intent, reason = rule_result
    elif settings.guardrail_llm_fallback:
        # ── 2차: LLM Classifier ───────────────────────────
        intent, reason = await _llm_classify(
            query, deps.container.local_llm if deps else None
        )
    else:
        intent, reason = "rag_query", "LLM fallback 비활성화"

    should_retrieve = intent == "rag_query"
    response_type = "rag" if should_retrieve else "guardrail"

    result: Dict[str, Any] = {
        "intent": intent,
        "should_retrieve": should_retrieve,
        "guardrail_reason": reason,
        "response_type": response_type,
    }

    if not should_retrieve:
        if intent == "greeting":
            answer = GREETING_MESSAGE
        else:
            response_types = config.get("response_types", {})
            message_type = response_types.get(
                intent, UserMessageType.INVALID_QUESTION.value
            )
            try:
                answer = get_user_message(message_type)
            except ValueError:
                logger.warning(
                    "알 수 없는 가드레일 응답 유형: intent=%r, type=%r",
                    intent,
                    message_type,
                )
                answer = get_user_message(UserMessageType.INVALID_QUESTION)
        result["generated_answer"] = answer
        # 2026.06.19(sooyeon.choi) 추가 - 가드레일 종료 결과 코드 기록
        result["outcome_code"] = "guardrail_blocked"
    else:
        pass

    return result