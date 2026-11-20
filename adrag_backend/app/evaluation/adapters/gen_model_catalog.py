"""데이터셋 생성용 vLLM 모델 목록.

2026.11.18(sooyeon.choi) 추가 - 데이터셋 생성 시 vLLM에 띄워진 모델 중 선택(예: Gemma-4-31B 8112)
  - 후보: 챗봇 기본 LLM(VLLM_API_URL·VLLM_MODEL_NAME) + EVAL_GEN_VLLM_MODELS("모델명=주소" 쉼표 구분)
  - 켜짐 여부는 각 서버 /v1/models 응답에 그 모델명이 있는지로 판단
  - 서버 주소는 화면에 보내지 않는다. 생성 요청의 모델명으로 서버에서 다시 찾는다
"""

from typing import Any, Dict, List, Optional

from app.core.config import Settings, get_settings
from app.core.http import get_shared_async_client
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

_HEALTH_TIMEOUT_S = 3.0


def _parse_extra_models(raw: str) -> List[Dict[str, str]]:
    """'모델명=주소,모델명=주소' 를 파싱한다. 형식이 틀린 항목은 경고 후 건너뛴다."""
    entries: List[Dict[str, str]] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, url = part.partition("=")
        name, url = name.strip(), url.strip().rstrip("/")
        if not sep or not name or not url:
            logger.warning("EVAL_GEN_VLLM_MODELS 항목 형식 오류(모델명=주소): 건너뜀")
            continue
        entries.append({"model": name, "url": url})
    return entries


def generation_model_candidates(settings: Optional[Settings] = None) -> List[Dict[str, Any]]:
    """생성 후보 목록(주소 포함, 서버 내부용). 첫 항목은 챗봇 기본 LLM."""
    settings = settings or get_settings()
    candidates: List[Dict[str, Any]] = [{
        "model": settings.vllm_model_name,
        "url": settings.vllm_api_url.rstrip("/"),
        "is_default": True,
    }]
    seen = {settings.vllm_model_name}
    for entry in _parse_extra_models(settings.eval_gen_vllm_models):
        if entry["model"] in seen:
            continue
        seen.add(entry["model"])
        candidates.append({**entry, "is_default": False})
    return candidates


def resolve_generation_model(model: str, settings: Optional[Settings] = None) -> Optional[Dict[str, Any]]:
    """모델명으로 후보를 찾는다. 목록에 없으면 None."""
    for candidate in generation_model_candidates(settings):
        if candidate["model"] == model:
            return candidate
    return None


async def is_model_served(candidate: Dict[str, Any], settings: Optional[Settings] = None) -> bool:
    """서버 /v1/models 응답에 후보 모델명이 있으면 True."""
    settings = settings or get_settings()
    try:
        resp = await get_shared_async_client().get(
            f"{candidate['url']}/v1/models",
            headers={"Authorization": f"Bearer {settings.vllm_api_key}"},
            timeout=_HEALTH_TIMEOUT_S,
        )
        if resp.status_code != 200:
            return False
        served = {item.get("id") for item in resp.json().get("data", [])}
        return candidate["model"] in served
    except Exception as e:
        logger.info("데이터셋 생성 모델 응답 없음: model=%s (%s)", candidate["model"], type(e).__name__)
        return False


async def list_generation_models(settings: Optional[Settings] = None) -> List[Dict[str, Any]]:
    """화면용 목록 — 모델명·기본 여부·켜짐 여부만 반환(주소 제외)."""
    settings = settings or get_settings()
    items = []
    for candidate in generation_model_candidates(settings):
        items.append({
            "model": candidate["model"],
            "is_default": candidate["is_default"],
            "available": await is_model_served(candidate, settings),
        })
    return items
