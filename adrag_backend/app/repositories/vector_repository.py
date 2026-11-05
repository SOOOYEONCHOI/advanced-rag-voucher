"""
Qdrant 벡터 저장소 레포지토리.

임베딩 저장·검색·컬렉션 관리 기능을 제공한다.
검색 방식: 벡터 유사도(semantic), 전문 키워드(BM25).
"""

# 2026.07.16(sooyeon.choi) 수정 - os.getenv fallback 제거로 os import 불필요 (B15)
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
    MatchText,
    PayloadSchemaType,
    TextIndexParams,
    TokenizerType,
    # 2026.04.20(sooyeon.choi) 옵션 추가 - sparse vector 지원
    SparseVectorParams,
    SparseIndexParams,
    SparseVector,
    # 2026.07.07(sooyeon.choi) 수정 - Qdrant BM25 IDF 및 서버 측 weighted RRF 지원
)

try:
    from qdrant_client.models import Modifier, Prefetch, Rrf, RrfQuery
except ImportError:  # older clients and lightweight unit-test stubs
    Modifier = Prefetch = Rrf = RrfQuery = None

# 2026.06.29(sooyeon.choi) 수정 - BM25 query 전용 정규화/불용어 정책 API 사용
from app.utils.kiwi_tokenizer import tokenize_corpus, tokenize_query_for_bm25
from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)


class VectorRepository:
    """Repository for vector storage and retrieval operations using Qdrant."""
    
    def __init__(
        self,
        # 2026.07.16(sooyeon.choi) 수정 - os.getenv fallback 제거 (B15)
        #   설정은 Settings 단일 소스에서 주입받는다. 모든 호출부(retrieve/ingest/
        #   collection_service/routes.collections)가 host/port를 명시 전달 중이며,
        #   환경변수 직접 참조는 설정 우선순위를 우회하므로 제거함.
        host: str,
        port: int,
        collection_name: str = "documents",
        # 2026.04.20(sooyeon.choi) 옵션 추가 - sparse encoder 타입 ("none" | "bm42" | "splade")
        sparse_encoder_type: str = "none",
        # 2026.06.29(sooyeon.choi) 수정 - 평가 결과에 따라 코드 변경 없이 조정할 BM25 파라미터
        bm25_k1: float = 1.2,
        bm25_b: float = 0.5,
        kiwi_bm25_vector_name: str = "kiwi_bm25",
    ):
        """Initialize vector repository with Qdrant client."""
        self.host = host
        self.port = port
        self.collection_name = collection_name
        # 2026.04.20(sooyeon.choi) 옵션 추가 - sparse 사용 여부 저장
        self.sparse_encoder_type = sparse_encoder_type
        self.bm25_k1 = bm25_k1
        self.bm25_b = bm25_b
        self.kiwi_bm25_vector_name = kiwi_bm25_vector_name

        try:
            self.client = QdrantClient(host=self.host, port=self.port)
            logger.info(f"Connected to Qdrant at {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            raise
    
    
    def create_collection(
        self,
        collection_name: str,
        vector_size: int,
        distance: Distance = Distance.COSINE
    ) -> bool:
        """Create a new collection in Qdrant."""
        try:
            # 2026.07.07(sooyeon.choi) 수정 - Dense+Kiwi BM25를 항상 같은 컬렉션에 저장
            sparse_vectors = {
                self.kiwi_bm25_vector_name: SparseVectorParams(
                    index=SparseIndexParams(on_disk=False),
                    modifier=Modifier.IDF,
                )
            }
            # 기존 BM42/SPLADE 실험 채널은 별도 named vector로 보존한다.
            if self.sparse_encoder_type != "none":
                sparse_vectors["sparse"] = SparseVectorParams(
                    index=SparseIndexParams(on_disk=False)
                )

            self.client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "dense": VectorParams(size=vector_size, distance=distance)
                },
                sparse_vectors_config=sparse_vectors,
            )
            logger.info(
                "Created hybrid collection: %s (size=%s, sparse=%s)",
                collection_name,
                vector_size,
                list(sparse_vectors),
            )

            self.ensure_payload_indexes(collection_name)
            self.ensure_text_index(collection_name)
            return True
        except UnexpectedResponse as e:
            if e.status_code == 409:
                # Qdrant에 이미 존재 — SQLite 재생성 후 재등록 시 정상 케이스
                logger.warning(f"Collection already exists in Qdrant, reusing: {collection_name}")
                return True
            logger.error(f"Failed to create collection {collection_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to create collection {collection_name}: {e}")
            return False

    # 2026.04.10(sooyeon.choi) 추가 - IngestService의 QdrantClient 직접 접근 제거를 위한 메서드
    def _has_valid_schema(self, collection_name: str, vector_size: int) -> bool:
        """컬렉션의 벡터 스키마가 현재 설정과 일치하는지 확인한다.

        sparse 활성화 시: named "dense" + "sparse" 벡터가 모두 존재해야 함.
        sparse 비활성화 시: unnamed 단일 벡터여야 함.
        """
        try:
            info = self.client.get_collection(collection_name=collection_name)
            vectors_config = info.config.params.vectors
            # 2026.07.07(sooyeon.choi) 수정 - named dense 차원과 Kiwi BM25 sparse 스키마 검증
            if not isinstance(vectors_config, dict) or "dense" not in vectors_config:
                return False
            if vectors_config["dense"].size != vector_size:
                return False
            if vectors_config["dense"].distance != Distance.COSINE:
                return False
            sparse_config = info.config.params.sparse_vectors
            if not sparse_config or self.kiwi_bm25_vector_name not in sparse_config:
                return False
            kiwi_sparse = sparse_config[self.kiwi_bm25_vector_name]
            if getattr(kiwi_sparse, "modifier", None) != Modifier.IDF:
                return False
            if self.sparse_encoder_type != "none" and "sparse" not in sparse_config:
                return False
            return True
        except Exception as e:
            logger.warning(f"컬렉션 스키마 확인 실패: {e}")
            return False

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        """컬렉션이 없으면 생성하고 payload 인덱스를 보장한다.

        이미 존재하더라도 벡터 스키마가 현재 설정과 불일치하면 RuntimeError를 발생시킨다.
        생성 실패 시 RuntimeError를 발생시켜 상위에서 처리한다.
        """
        existing = set(self.list_collections())
        if collection_name not in existing:
            ok = self.create_collection(collection_name, vector_size)
            if not ok:
                raise RuntimeError(f"컬렉션 생성 실패: '{collection_name}'")
            logger.info(f"[VectorRepository] 컬렉션 생성: '{collection_name}' (dim={vector_size})")
        else:
            if not self._has_valid_schema(collection_name, vector_size):
                raise RuntimeError(
                    f"컬렉션 '{collection_name}'의 벡터 스키마가 현재 설정과 불일치합니다. "
                    f"(sparse_encoder_type={self.sparse_encoder_type}) "
                    f"컬렉션을 삭제 후 다시 시도하세요."
                )
            self.ensure_payload_indexes(collection_name)
            self.ensure_text_index(collection_name)

    def upsert_points(
        self,
        collection_name: str,
        points: List[PointStruct],
        batch_size: int = 100,
    ) -> None:
        """포인트 목록을 배치 단위로 Qdrant에 upsert한다.

        2026.04.10(sooyeon.choi) 추가 - IngestService의 QdrantClient 직접 접근 제거를 위한 메서드
        실패 시 RuntimeError를 발생시켜 상위에서 처리한다.
        """
        if not points:
            raise ValueError("upsert할 포인트가 없습니다.")
        try:
            for i in range(0, len(points), batch_size):
                self.client.upsert(
                    collection_name=collection_name,
                    points=points[i:i + batch_size],
                    # 2026.07.07(sooyeon.choi) 수정 - 적재 반영 완료 후 후속 이력 저장 수행
                    wait=True,
                )
            logger.info(f"[VectorRepository] upsert 완료: {len(points)}개 → '{collection_name}'")
        except Exception as e:
            raise RuntimeError(f"Qdrant upsert 실패: {e}") from e

    def ensure_payload_indexes(self, collection_name: str) -> bool:
        """검색 필터에 사용하는 주요 payload 필드 인덱스를 생성한다."""
        indexed_fields = {
            # 2026.08.27(sooyeon.choi) 추가 - spreadsheet 필터 검색용 payload index
            "document_id": PayloadSchemaType.KEYWORD,
            "source_collection": PayloadSchemaType.KEYWORD,
            "security_level": PayloadSchemaType.KEYWORD,
            "document_type": PayloadSchemaType.KEYWORD,
            "sheet_index": PayloadSchemaType.INTEGER,
            "sheet_name": PayloadSchemaType.KEYWORD,
            "block_type": PayloadSchemaType.KEYWORD,
            "chunk_type": PayloadSchemaType.KEYWORD,
            "content_type": PayloadSchemaType.KEYWORD,
            "resource_ids": PayloadSchemaType.KEYWORD,
            "keywords": PayloadSchemaType.KEYWORD,
            "intent": PayloadSchemaType.KEYWORD,
            # 2026.10.16 추가 - Phase 2(P2-2): 버전 전환·포인트 종류 필터·버전 무관 키
            "version_no": PayloadSchemaType.INTEGER,
            "point_type": PayloadSchemaType.KEYWORD,
            "source_key": PayloadSchemaType.KEYWORD,
        }
        try:
            for field_name, field_schema in indexed_fields.items():
                self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                )
            logger.info("Ensured payload indexes for collection: %s", collection_name)
            return True
        except Exception as e:
            logger.warning(
                "Failed to ensure payload indexes for collection %s: %s",
                collection_name,
                e,
            )
            return False

    def ensure_text_index(self, collection_name: str) -> bool:
        """BM25 검색을 위한 text 필드 전문(Full-Text) 인덱스를 생성한다.

        이미 존재하는 경우 Qdrant가 무시하므로 멱등 호출이 안전하다.
        
        """
        try:
            self.client.create_payload_index(
                collection_name=collection_name,
                field_name="text",
                field_schema=TextIndexParams(
                    type="text",
                    tokenizer=TokenizerType.WORD,
                    min_token_len=2,
                    max_token_len=15,
                    lowercase=True,
                ),
            )
            logger.info("text 전문 인덱스 생성 완료: %s", collection_name)
            return True
        except Exception as e:
            logger.warning("text 전문 인덱스 생성 실패 (이미 존재할 수 있음): %s", e)
            return False

    def search_bm25(
        self,
        query_text: str,
        top_k: int = 10,
        collection_name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Qdrant 전문 인덱스 기반 BM25 검색.

        처리 흐름:
          1. MatchText 필터로 키워드 매칭 후보를 Qdrant에서 가져온다 (top_k * 3).
          2. rank_bm25(BM25Okapi)로 후보 텍스트에 대해 BM25 점수를 계산한다.
          3. 점수 내림차순 정렬 후 top_k개를 반환한다.

        Args:
            query_text: 검색 질의 문자열.
            top_k: 반환할 최대 결과 수.
            collection_name: 검색할 Qdrant 컬렉션명.
            filters: 기존 메타데이터 필터 (search_similar와 동일 포맷 지원).

        Returns:
            List of (chunk_id, bm25_score, payload) tuples, score 내림차순 정렬.
        """
        collection = collection_name or self.collection_name
        try:
            from rank_bm25 import BM25Okapi

            # ── 1단계: MatchText + 기존 필터 조합 ──
            # MatchText: Qdrant 전문(Full-Text) 검색 필터.
            #   - ensure_text_index()로 생성한 text 필드 인덱스를 활용한다.
            #   - query_text를 토큰으로 분리하여 하나라도 포함된 문서를 반환한다.
            #   - MatchValue/MatchAny(정확히 일치)와 달리 부분 키워드 매칭을 지원한다.
            #   - 이 단계는 필터(있다/없다)만 판단하며 점수를 부여하지 않는다.
            #     → 실제 BM25 점수는 2단계에서 rank_bm25가 별도 계산한다.
            # 2026.06.29(sooyeon.choi) 수정 - 원문 전체 대신 Kiwi가 추출한 핵심 검색어로 Qdrant 후보 조회
            tokenized_query = tokenize_query_for_bm25(query_text)
            match_text = " ".join(tokenized_query) if tokenized_query else query_text
            text_condition = FieldCondition(
                key="text", match=MatchText(text=match_text)
            )
            must_conditions = [text_condition]
            should_conditions: List[FieldCondition] = []

            if filters:
                if "must" in filters or "should" in filters:
                    must_conditions += self._build_conditions(filters.get("must", {}))
                    should_conditions = self._build_conditions(filters.get("should", {}))
                else:
                    must_conditions += self._build_conditions(filters)

            query_filter = Filter(
                must=must_conditions,
                should=should_conditions if should_conditions else None,
            )
            # 2026.10.19(sooyeon.choi) 추가 - 활성 버전만 검색(최신본 변경 중·정리 전 버전 제외)
            query_filter = self._visible(query_filter)

            # BM25 재랭킹을 위해 후보를 top_k * 10 수준으로 넓게 가져온다
            # top_k * 3은 진짜 BM25 상위 문서가 후보에서 제외될 수 있어 상향
            candidates, _ = self.client.scroll(
                collection_name=collection,
                scroll_filter=query_filter,
                limit=top_k * 10,
                with_payload=True,
                with_vectors=False,
            )

            if not candidates:
                logger.debug("BM25 후보 없음 (컬렉션: %s)", collection)
                return []

            # ── 2단계: BM25 점수 계산 ──
            # 참조: reference_code/.../vector_db.py retrieve_vector_db_ensemble()
            #   - corpus: kiwi_instance.morphs(doc) — 전체 형태소 토크나이즈
            #   - query:  kiwi_instance.morphs_query(query) — 검색용 품사(명사·형용사·부사)만 추출
            # 2026.06.29(sooyeon.choi) 수정 - corpus/query는 Task 3 토큰 정책을 공유하고 k1/b는 설정값 사용
            #   k1: 단어 빈도 포화 계수, b: 문서 길이 정규화 계수
            texts = [
                (point.payload.get("text", "") if point.payload else "")
                for point in candidates
            ]
            tokenized_corpus = [tokenize_corpus(text) for text in texts]
            logger.info("[Kiwi BM25 토크나이즈] 쿼리='%s' → 토큰=%s", query_text, tokenized_query)

            bm25 = BM25Okapi(
                tokenized_corpus,
                k1=self.bm25_k1,
                b=self.bm25_b,
            )
            scores = bm25.get_scores(tokenized_query)

            # ── 3단계: BM25=0 필터링 후 점수 순 정렬, top_k 반환 ──
            # 참조: reference_code/.../vector_db.py retrieve_vector_db_ensemble_rrf()
            #   if bm25_scores[idx] > 0: → BM25 점수가 0인 문서(쿼리 토큰 미포함) 제외
            #   쿼리 키워드와 무관한 문서가 RRF 점수로 섞여드는 것을 방지한다.
            ranked = sorted(
                (
                    (point, float(score))
                    for point, score in zip(candidates, scores.tolist())
                    if score > 0.0
                ),
                key=lambda x: x[1],
                reverse=True,
            )[:top_k]

            output = [
                (str(point.id), score, point.payload or {})
                for point, score in ranked
            ]
            logger.debug("BM25 검색 결과: %d개 (컬렉션: %s)", len(output), collection)
            return output

        except ImportError:
            logger.error("rank_bm25 패키지 미설치 — BM25 검색 불가. pip install rank-bm25")
            return []
        except Exception as e:
            logger.error("BM25 검색 실패 (컬렉션: %s): %s", collection, e)
            return []
    
    # 2026.04.20(sooyeon.choi) 옵션 추가 - Qdrant sparse vector 검색 (bm42/splade 사용 시)
    def search_sparse(
        self,
        sparse_indices: List[int],
        sparse_values: List[float],
        top_k: int = 10,
        collection_name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Qdrant sparse vector 검색.

        Python BM25 대신 Qdrant 내부 역색인을 사용하여 후보 fetch 없이
        직접 top_k 결과를 반환한다.
        """
        collection = collection_name or self.collection_name
        try:
            query_filter = None
            if filters:
                has_must_should = "must" in filters or "should" in filters
                if has_must_should:
                    must_conditions = self._build_conditions(filters.get("must", {}))
                    should_conditions = self._build_conditions(filters.get("should", {}))
                    query_filter = Filter(
                        must=must_conditions if must_conditions else None,
                        should=should_conditions if should_conditions else None,
                    )
                else:
                    conditions = self._build_conditions(filters)
                    if conditions:
                        query_filter = Filter(must=conditions)
            # 2026.10.19(sooyeon.choi) 추가 - 활성 버전만 검색
            query_filter = self._visible(query_filter)

            # 2026.05.06(sooyeon.choi) 수정 - NamedSparseVector → using 파라미터 방식으로 변경
            #   query_points()는 NamedSparseVector 타입을 query 인자로 지원하지 않음
            search_response = self.client.query_points(
                collection_name=collection,
                query=SparseVector(indices=sparse_indices, values=sparse_values),
                using="sparse",
                limit=top_k,
                query_filter=query_filter,
            )

            results = [
                (str(hit.id), hit.score, hit.payload if hit.payload else {})
                for hit in search_response.points
            ]
            logger.debug("Sparse 검색 결과: %d개 (컬렉션: %s)", len(results), collection)
            return results

        except Exception as e:
            logger.error("Sparse 검색 실패 (컬렉션: %s): %s", collection, e)
            return []

    def delete_collection(self, collection_name: str) -> bool:
        """Delete a collection from Qdrant."""
        try:
            self.client.delete_collection(collection_name=collection_name)
            logger.info(f"Deleted collection: {collection_name}")
            return True
        # 2026.06.18(sooyeon.choi) 수정 - 이미 삭제된 Qdrant 컬렉션은 삭제 완료로 처리
        except UnexpectedResponse as e:
            if e.status_code == 404:
                logger.info(f"Collection already absent from Qdrant: {collection_name}")
                return True
            logger.error(f"Failed to delete collection {collection_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete collection {collection_name}: {e}")
            return False

    # 2026.06.25(sooyeon.choi) 수정 - Qdrant 직접 삭제 여부 확인을 위한 단일 컬렉션 존재 확인 메서드 추가
    def collection_exists(self, collection_name: str) -> bool:
        """Qdrant 컬렉션 존재 여부를 확인하여 존재하면 True 반환

        Qdrant 오류 발생 시 예외 발생.
        목적: 컬렉션 없음과 서버 장애를 구분하기 위함.
        """
        try:
            self.client.get_collection(collection_name=collection_name)
            return True
        except UnexpectedResponse as e:
            if e.status_code == 404:
                return False
            raise
    
    def list_collections(self) -> List[str]:
        """List all collections in Qdrant."""
        try:
            collections = self.client.get_collections()
            collection_names = [col.name for col in collections.collections]
            logger.debug(f"Found {len(collection_names)} collections")
            return collection_names
        except Exception as e:
            logger.error(f"Failed to list collections: {e}")
            return []
    
    def _build_conditions(self, filter_dict: Dict[str, Any]) -> List[FieldCondition]:
        """Build FieldCondition list from a flat filter dictionary.
        
        - 리스트 값 → MatchAny
        - 문자열 및 기타 값 → MatchValue
        """
        conditions = []
        for key, value in filter_dict.items():
            if isinstance(value, list):
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchAny(any=value)
                    )
                )
            else:
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )
        return conditions

    # 2026.10.19(sooyeon.choi) 추가 - 최신본 변경: 문서마다 활성 버전 포인트만 검색에 남긴다.
    #   제외 조건은 RDB 기준(app/services/version_visibility.py). 개정 이력이 없으면 필터를 바꾸지 않는다.
    def _visible(self, query_filter: Optional[Filter]) -> Optional[Filter]:
        from app.services.version_visibility import with_version_exclusion

        return with_version_exclusion(query_filter)

    def delete_document_version_points(
        self,
        document_id: str,
        collection_name: Optional[str] = None,
        *,
        version_no: Optional[int] = None,
        keep_version_no: Optional[int] = None,
    ) -> bool:
        """한 버전의 포인트(version_no) 또는 활성 버전을 뺀 나머지(keep_version_no)를 지운다."""
        collection = collection_name or self.collection_name
        if (version_no is None) == (keep_version_no is None):
            raise ValueError("version_no와 keep_version_no 중 하나만 지정")
        doc = FieldCondition(key="document_id", match=MatchValue(value=document_id))
        if version_no is not None:
            selector = Filter(must=[doc, FieldCondition(key="version_no", match=MatchValue(value=version_no))])
        else:
            selector = Filter(must=[doc], must_not=[FieldCondition(key="version_no", match=MatchValue(value=keep_version_no))])
        try:
            self.client.delete(collection_name=collection, points_selector=selector, wait=True)
            return True
        except Exception as e:
            logger.error("Failed to delete version points document=%s: %s", document_id, e)
            return False

    def count_document_version_points(self, document_id: str, version_no: int, collection_name: Optional[str] = None) -> int:
        collection = collection_name or self.collection_name
        return self.client.count(
            collection_name=collection,
            count_filter=Filter(must=[
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                FieldCondition(key="version_no", match=MatchValue(value=version_no)),
            ]),
            exact=True,
        ).count

    def _build_filter(self, filters: Optional[Dict[str, Any]]) -> Optional[Filter]:
        """검색 채널에 공통 적용할 Qdrant 필터를 생성한다."""
        # 2026.07.07(sooyeon.choi) 수정 - Dense/Sparse prefetch의 권한 필터 정책 통일
        if not filters:
            return None
        if "must" in filters or "should" in filters:
            must = self._build_conditions(filters.get("must", {}))
            should = self._build_conditions(filters.get("should", {}))
            if not must and not should:
                return None
            return Filter(
                must=must or None,
                should=should or None,
            )
        conditions = self._build_conditions(filters)
        return Filter(must=conditions) if conditions else None

    def search_hybrid(
        self,
        dense_vectors: List[List[float]],
        sparse_query: Any,
        top_k: int,
        collection_name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        dense_prefetch_k: int = 80,
        sparse_prefetch_k: int = 80,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
        rrf_k: int = 60,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Qdrant Query API에서 multi-query Dense+Kiwi BM25를 weighted RRF로 병합한다."""
        # 2026.07.07(sooyeon.choi) 수정 - scroll 후보 재계산 → 전체 sparse index 검색으로 대체
        collection = collection_name or self.collection_name
        # 2026.10.19(sooyeon.choi) 수정 - 활성 버전만 검색. 버전 조회 실패는 검색 실패로 올린다.
        query_filter = self._visible(self._build_filter(filters))
        if not dense_vectors:
            raise ValueError("Dense query vector가 없습니다.")
        # 2026.07.08(sooyeon.choi) 수정 - rewrite 수와 무관하게 Dense 채널 총가중치 유지
        per_dense_weight = dense_weight / len(dense_vectors)
        try:
            response = self.client.query_points(
                collection_name=collection,
                prefetch=[
                    *[
                        Prefetch(
                            query=dense_vector,
                            using="dense",
                            limit=dense_prefetch_k,
                            filter=query_filter,
                        )
                        for dense_vector in dense_vectors
                    ],
                    Prefetch(
                        query=sparse_query,
                        using=self.kiwi_bm25_vector_name,
                        limit=sparse_prefetch_k,
                        filter=query_filter,
                    ),
                ],
                query=RrfQuery(
                    rrf=Rrf(
                        k=rrf_k,
                        weights=[
                            *[per_dense_weight for _ in dense_vectors],
                            sparse_weight,
                        ],
                    )
                ),
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
            return [
                (str(hit.id), float(hit.score), hit.payload or {})
                for hit in response.points
            ]
        except Exception as e:
            # 정상 0건과 Qdrant 장애를 구분하도록 상위로 전달한다.
            raise RuntimeError(
                f"Qdrant hybrid 검색 실패 (컬렉션: {collection}): {e}"
            ) from e

    # 2026.07.28(sooyeon.choi) 수정 - 평가용 Kiwi BM25 named sparse vector 직접 검색 추가
    #   운영 RAG는 기존 search_hybrid()를 그대로 사용하며 이 메서드는 평가 어댑터 전용이다.
    def search_kiwi_bm25(
        self,
        query: Any,
        top_k: int,
        collection_name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Qdrant kiwi_bm25 named sparse vector를 RRF 없이 직접 검색한다."""
        collection = collection_name or self.collection_name
        # 2026.10.19(sooyeon.choi) 수정 - 활성 버전만 검색. 버전 조회 실패는 검색 실패로 올린다.
        query_filter = self._visible(self._build_filter(filters))
        try:
            response = self.client.query_points(
                collection_name=collection,
                query=query,
                using=self.kiwi_bm25_vector_name,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
            return [
                (str(hit.id), float(hit.score), hit.payload or {})
                for hit in response.points
            ]
        except Exception as e:
            raise RuntimeError(
                f"Qdrant Kiwi BM25 검색 실패 (컬렉션: {collection}): {e}"
            ) from e

    def search_similar(
        self,
        query_vector: List[float],
        top_k: int = 10,
        collection_name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Search for similar vectors with optional filtering.
        
        Supports two filter formats:
        1. Structured: {"must": {...}, "should": {...}} — must/should treated as separate condition groups
        2. Flat dict (backward compatible): all conditions treated as must
        """
        collection = collection_name or self.collection_name
        
        try:
            # Build filter if provided
            query_filter = None
            if filters:
                has_must_should = "must" in filters or "should" in filters
                
                if has_must_should:
                    # Structured format: separate must/should groups
                    must_conditions = self._build_conditions(filters.get("must", {}))
                    should_conditions = self._build_conditions(filters.get("should", {}))
                    
                    if must_conditions or should_conditions:
                        query_filter = Filter(
                            must=must_conditions if must_conditions else None,
                            should=should_conditions if should_conditions else None,
                        )
                else:
                    # Flat dict format (backward compatible): all conditions as must
                    conditions = self._build_conditions(filters)
                    if conditions:
                        query_filter = Filter(must=conditions)
            # 2026.10.19(sooyeon.choi) 추가 - 활성 버전만 검색
            query_filter = self._visible(query_filter)
            
            # 2026.04.08(sooyeon.choi) 추가 - client.search() → client.query_points() 변경 (qdrant-client 신버전 대응)
            # 2026.04.09(sooyeon.choi) 수정 - 보안 Fallback 제거
            # 2026.04.20(sooyeon.choi) 옵션 추가 - sparse 활성화 시 named vector("dense") 사용
            # 2026.05.06(sooyeon.choi) 수정 - NamedVector → using 파라미터 방식으로 변경
            #   query_points()는 NamedVector 타입을 query 인자로 지원하지 않음
            #   named vector 지정은 using 파라미터로 전달해야 함
            # 2026.07.07(sooyeon.choi) 수정 - 신규 컬렉션은 항상 named dense vector 사용
            using = "dense"
            search_response = self.client.query_points(
                collection_name=collection,
                query=query_vector,
                using=using,
                limit=top_k,
                query_filter=query_filter,
                score_threshold=score_threshold,
            )

            # Format results
            results = []
            for hit in search_response.points:
                results.append((
                    hit.id,    # chunk_id
                    hit.score, # similarity score
                    hit.payload if hit.payload else {},  # metadata
                ))
            
            logger.debug(f"Found {len(results)} similar vectors in {collection}")
            return results
            
        except Exception as e:
            logger.error(f"Failed to search similar vectors: {e}")
            return []
    
    def delete_by_document_id(
        self,
        document_id: str,
        collection_name: Optional[str] = None
    ) -> bool:
        """Delete all vectors associated with a document ID."""
        collection = collection_name or self.collection_name
        
        try:
            # Delete points with matching document_id
            self.client.delete(
                collection_name=collection,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id)
                        )
                    ]
                ),
                wait=True,
            )
            logger.info(f"Deleted vectors for document: {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete vectors for document {document_id}: {e}")
            return False

    def count_by_document_id(
        self,
        document_id: str,
        collection_name: Optional[str] = None,
    ) -> int:
        """Return the exact number of points associated with a document ID."""
        collection = collection_name or self.collection_name
        try:
            result = self.client.count(
                collection_name=collection,
                count_filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id),
                        )
                    ]
                ),
                exact=True,
            )
            return result.count
        except Exception as e:
            logger.error(
                "Failed to count vectors for document %s in %s: %s",
                document_id,
                collection,
                e,
            )
            raise RuntimeError(
                f"Qdrant 문서 포인트 조회 실패: document_id={document_id}"
            ) from e
    
