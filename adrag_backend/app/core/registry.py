"""
LLM 프로바이더 레지스트리.

2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 인터페이스 도입
  기존: generate_answer 노드 내부에 `state.get("llm_provider") == "openai"` 문자열
        분기가 있어 프로바이더 추가마다 노드 수정이 필요했음.
  변경: 이름→팩토리 레지스트리로 분리. Gemini/Claude 등 신규 프로바이더는
        LLMProvider 계약을 만족하는 서비스 작성 + register_llm_provider() 등록만으로
        노드 수정 없이 편입된다. (SFR-025 Multi LLM Routing의 기반)
"""

from typing import Any, Callable, Dict, Optional

from app.core.config import Settings
from app.interfaces.llm import LLMProvider
from app.services.llm_service import LLMService, get_local_llm_service
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

# 프로바이더 팩토리: (settings, model, api_key) → LLMProvider
_LLMFactory = Callable[[Settings, Optional[str], Optional[str]], LLMProvider]

_llm_providers: Dict[str, _LLMFactory] = {}


def register_llm_provider(name: str, factory: _LLMFactory) -> None:
    """LLM 프로바이더 팩토리를 등록한다. 동일 이름은 마지막 등록이 우선."""
    _llm_providers[name] = factory
    logger.info("[registry] LLM 프로바이더 등록: %s", name)


def create_llm_provider(
    name: str,
    settings: Settings,
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> LLMProvider:
    """등록된 팩토리로 LLM 프로바이더를 생성한다."""
    if name not in _llm_providers:
        supported = ", ".join(sorted(_llm_providers))
        raise ValueError(f"등록되지 않은 LLM 프로바이더입니다: {name} (지원: {supported})")
    return _llm_providers[name](settings, model, api_key)


def resolve_llm_from_state(state: Any, settings: Settings) -> LLMProvider:
    """PipelineState의 llm_provider/llm_model/llm_api_key로 LLM 프로바이더를 선택한다.

    generate_answer 노드에 있던 선택 규칙을 그대로 이동:
      - provider가 등록되어 있고 model·api_key가 갖춰지면 해당 프로바이더
      - 그 외에는 로컬 vLLM 싱글턴 (내부 파이프라인 단계와 동일 인스턴스 재사용)
    """
    provider = state.get("llm_provider")
    if (
        provider
        and provider != "local"
        and provider in _llm_providers
        and state.get("llm_api_key")
        and state.get("llm_model")
    ):
        return create_llm_provider(
            provider,
            settings,
            model=state["llm_model"],
            api_key=state["llm_api_key"],
        )
    return create_llm_provider("local", settings)


# ── 기본 프로바이더 등록 ──────────────────────────────────────────────────────

def _local_factory(settings: Settings, model: Optional[str], api_key: Optional[str]) -> LLMProvider:
    # 설정이 고정된 로컬 vLLM은 싱글턴 재사용 (객체 생성 오버헤드 제거)
    return get_local_llm_service()


def _openai_factory(settings: Settings, model: Optional[str], api_key: Optional[str]) -> LLMProvider:
    # OpenAI는 요청마다 api_key·model이 달라질 수 있어 새 인스턴스 생성
    return LLMService(settings, openai_api_key=api_key, openai_model=model)


register_llm_provider("local", _local_factory)
register_llm_provider("openai", _openai_factory)
