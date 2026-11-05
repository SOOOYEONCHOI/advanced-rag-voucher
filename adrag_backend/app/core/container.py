"""
파이프라인 컴포넌트 조립 컨테이너 (Composition Root).

2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 인터페이스 도입
  기존: 컴포넌트 싱글턴이 노드 파일마다 모듈 전역으로 흩어져 있어
        (retrieve.py 6개, rerank.py 1개, analyze_and_rewrite.py 1개 ...)
        구현을 교체하려면 생성 지점을 전부 찾아야 했음.
  변경: 조립을 이 컨테이너 한 곳으로 단일화. 구현 교체 = 여기 한 곳 수정.
        각 컴포넌트는 cached_property로 지연 생성되어 기존 lazy 싱글턴과
        동일한 초기화 시점을 유지한다 (기능 변화 없음).

  테스트에서는 PipelineContainer를 직접 구성해 GraphDependencies에 주입한다.
"""

from functools import cached_property

from app.clients.embedding_client import EmbeddingClient
from app.clients.kiwi_bm25_encoder import KiwiBm25Encoder
from app.clients.reranker_client import RerankerClient
from app.clients.sparse_encoder import SparseEncoder
from app.core.config import Settings, get_settings
from app.graphs.preprocessing import QueryPreprocessor
from app.graphs.retrieval_engine import (
    RetrievalOrchestrator,
    create_retrieval_orchestrator,
)
from app.interfaces import (
    EmbeddingProvider,
    LLMProvider,
    QueryPreprocessorProtocol,
    Reranker,
    VectorStore,
)
from app.repositories.vector_repository import VectorRepository
from app.services.collection_service import CollectionService
from app.services.llm_service import get_local_llm_service
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

_EMBEDDING_FACTORIES = {"vllm": lambda settings: EmbeddingClient(settings)}
_VECTOR_STORE_FACTORIES = {
    "qdrant": lambda settings: VectorRepository(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        sparse_encoder_type=settings.sparse_encoder_type,
        bm25_k1=settings.bm25_k1,
        bm25_b=settings.bm25_b,
        kiwi_bm25_vector_name=settings.kiwi_bm25_vector_name,
    )
}
_RERANKER_FACTORIES = {"vllm": lambda settings: RerankerClient(settings)}


def _create(registry, name: str, settings, component: str):
    try:
        return registry[name](settings)
    except KeyError as exc:
        raise ValueError(f"지원하지 않는 {component} provider: {name}") from exc


class PipelineContainer:
    """RAG 파이프라인 컴포넌트의 단일 조립 지점.

    속성 타입은 구체 클래스가 아닌 인터페이스(Protocol)로 노출한다.
    구현 교체 시 이 클래스의 해당 cached_property만 수정하면 된다.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ── 검색 계층 ────────────────────────────────────────────────────────────

    @cached_property
    def embedding(self) -> EmbeddingProvider:
        """임베딩 프로바이더 (기본: vLLM EmbeddingClient)."""
        return _create(_EMBEDDING_FACTORIES, self.settings.embedding_provider, self.settings, "embedding")

    @cached_property
    def vector_store(self) -> VectorStore:
        """벡터 저장소 (기본: Qdrant VectorRepository)."""
        return _create(_VECTOR_STORE_FACTORIES, self.settings.vector_store_provider, self.settings, "vector store")

    @cached_property
    def sparse_encoder(self) -> SparseEncoder:
        """BM42/SPLADE sparse 인코더 (sparse_encoder_type=none이면 비활성)."""
        return SparseEncoder(self.settings)

    @cached_property
    def kiwi_bm25_encoder(self) -> KiwiBm25Encoder:
        """Qdrant BM25 적재/검색 정책을 공유하는 Kiwi 인코더."""
        return KiwiBm25Encoder(self.settings)

    @cached_property
    def retrieval_orchestrator(self) -> RetrievalOrchestrator:
        """legacy 검색 채널 오케스트레이터 (retrieval_engine=legacy 전용)."""
        return create_retrieval_orchestrator(
            vector_repo=self.vector_store,
            embedding_client=self.embedding,
            sparse_encoder_factory=lambda: self.sparse_encoder,
        )

    @cached_property
    def collection_service(self) -> CollectionService:
        """컬렉션 검증/관리 서비스."""
        return CollectionService()

    # ── 전처리/리랭킹 ────────────────────────────────────────────────────────

    @cached_property
    def query_preprocessor(self) -> QueryPreprocessorProtocol:
        """규칙 기반 질의 전처리기 (기본: Kiwi 기반 QueryPreprocessor)."""
        return QueryPreprocessor()

    @cached_property
    def reranker(self) -> Reranker:
        """리랭커 (기본: vLLM /v1/score RerankerClient)."""
        return _create(_RERANKER_FACTORIES, self.settings.reranker_provider, self.settings, "reranker")

    # ── LLM ─────────────────────────────────────────────────────────────────

    @property
    def local_llm(self) -> LLMProvider:
        """내부 파이프라인 단계(질의 재작성·가드레일)용 로컬 vLLM 싱글턴."""
        return get_local_llm_service()


# ── 컨테이너 싱글턴 ──────────────────────────────────────────────────────────

_container: PipelineContainer | None = None


def get_container() -> PipelineContainer:
    """프로세스 전역 컨테이너를 반환한다 (지연 생성)."""
    global _container
    if _container is None:
        _container = PipelineContainer()
        logger.info("[container] PipelineContainer 생성")
    return _container
