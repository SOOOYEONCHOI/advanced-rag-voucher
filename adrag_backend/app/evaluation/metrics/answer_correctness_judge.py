"""RAGAS AnswerAccuracy 기반 Answer Correctness Judge."""

from importlib.metadata import PackageNotFoundError, version
from typing import Any, Dict

from app.core.config import get_settings
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

_SKIP_BEHAVIORS = {"guardrail", "permission_denied", "not_enough_info"}


def _ragas_version() -> str:
    try:
        return version("ragas")
    except PackageNotFoundError:
        return "unavailable"


def _build_answer_accuracy(backend: str, model: str, temperature: float):
    """설정에 맞는 RAGAS AnswerAccuracy scorer를 생성한다."""
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerAccuracy

    settings = get_settings()
    if backend == "openai":
        api_key = getattr(settings, "openai_api_key", None)
        if not api_key:
            raise ValueError("openai_api_key is required for openai judge backend")
        client = AsyncOpenAI(api_key=api_key, timeout=settings.vllm_timeout)
    elif backend == "vllm":
        client = AsyncOpenAI(
            api_key=settings.vllm_api_key,
            base_url=f"{settings.vllm_api_url.rstrip('/')}/v1",
            timeout=settings.vllm_timeout,
        )
    else:
        raise ValueError(f"unsupported judge backend: {backend}")

    llm = llm_factory(
        model,
        provider="openai",
        client=client,
        temperature=temperature,
    )
    return AnswerAccuracy(llm=llm)


async def evaluate_correctness_judge(
    question: str,
    gold_answer: str,
    system_answer: str,
    config: Dict[str, Any],
    *,
    expected_behavior: str = "answer",
) -> Dict[str, Any]:
    """RAGAS AnswerAccuracy 결과를 기존 metric 반환 계약으로 변환한다."""
    judge_config = config.get("answer_correctness_judge") or {}

    if not judge_config.get("enabled", True):
        return {"value": None, "status": "excluded", "reason": "judge_disabled", "metadata": {}}
    if expected_behavior in _SKIP_BEHAVIORS:
        return {"value": None, "status": "excluded", "reason": "expected_behavior_not_answer", "metadata": {}}
    if not question or not question.strip():
        return {"value": None, "status": "excluded", "reason": "missing_question", "metadata": {}}
    if not gold_answer or not gold_answer.strip():
        return {"value": None, "status": "excluded", "reason": "missing_gold_answer", "metadata": {}}
    if not system_answer or not system_answer.strip():
        return {"value": 0.0, "status": "evaluated", "reason": "empty_system_answer", "metadata": {}}

    backend = str(judge_config.get("backend", "vllm"))
    settings = get_settings()
    model = str(
        judge_config.get("model")
        or ("gpt-4.1-mini" if backend == "openai" else settings.vllm_model_name)
    )
    temperature = float(judge_config.get("temperature", 0.0))
    metadata: Dict[str, Any] = {
        "method": "ragas_answer_accuracy",
        "implementation": "ragas",
        "metric_version": "answer_accuracy.1",
        "ragas_version": _ragas_version(),
        "backend": backend,
        "model": model,
    }

    try:
        scorer = _build_answer_accuracy(backend, model, temperature)
        result = await scorer.ascore(
            user_input=question,
            response=system_answer,
            reference=gold_answer,
        )
        value = float(result.value)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"RAGAS score out of range: {value}")
        return {
            "value": round(value, 4),
            "status": "evaluated",
            "reason": str(getattr(result, "reason", "") or ""),
            "metadata": metadata,
        }
    except Exception as exc:
        logger.warning(
            "[eval][judge] RAGAS AnswerAccuracy 실패 type=%s: %s",
            type(exc).__name__,
            exc,
        )
        return {
            "value": None,
            "status": "error",
            "reason": f"ragas_error: {type(exc).__name__}",
            "metadata": metadata,
        }
