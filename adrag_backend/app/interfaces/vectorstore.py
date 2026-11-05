"""
벡터 저장소 인터페이스 (검색 경로 계약).

2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 인터페이스 도입
기준 구현: app/repositories/vector_repository.py VectorRepository (Qdrant)
Weaviate 등 다른 벡터DB 교체 검토(ECR-004) 시 이 계약을 기준으로
어댑터를 작성한다. 검색 결과는 (chunk_id, score, payload) 튜플 리스트.

주: 인덱싱/관리(upsert, 컬렉션 관리) 계약은 인제스트 파이프라인 분해(6단계)와
함께 정의 예정이며, 이 Protocol은 질의 파이프라인이 사용하는 검색 메서드만 다룬다.
"""

from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

SearchResult = Tuple[str, float, Dict[str, Any]]


@runtime_checkable
class VectorStore(Protocol):
    """질의 파이프라인용 벡터 검색 계약."""

    def search_similar(
        self,
        query_vector: List[float],
        top_k: int,
        collection_name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Dense 벡터 유사도 검색."""
        ...

    def search_bm25(
        self,
        query_text: str,
        top_k: int,
        collection_name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """키워드(BM25) 검색."""
        ...

    def search_sparse(
        self,
        sparse_indices: List[int],
        sparse_values: List[float],
        top_k: int,
        collection_name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Sparse 벡터(BM42/SPLADE) 검색."""
        ...

    # 2026.07.28(sooyeon.choi) 수정 - 평가용 Kiwi BM25 단독 검색 계약 추가
    def search_kiwi_bm25(
        self,
        query: Any,
        top_k: int,
        collection_name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Qdrant kiwi_bm25 named sparse vector를 직접 검색한다."""
        ...

    def search_hybrid(self, *args: Any, **kwargs: Any) -> List[SearchResult]:
        """서버측 Dense+Sparse hybrid 검색 (가중 RRF 병합)."""
        ...

    def ensure_collection(self, collection_name: str, vector_size: int) -> bool:
        """Create the collection and payload indexes when absent."""
        ...

    def upsert_points(self, collection_name: str, points: List[Any], batch_size: int = 64) -> bool:
        """Insert or update indexed points."""
        ...

    def delete_by_document_id(self, document_id: str, collection_name: str) -> bool:
        """Delete every point belonging to one document."""
        ...

    def delete_collection(self, collection_name: str) -> bool:
        """Delete a collection."""
        ...
