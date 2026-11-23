# 2026.11.23(sooyeon.choi) 추가 - AI+ 인증 시험 1·2 공통: 모델·검색 구성 요소 불러오기 + 하이브리드 검색·재랭킹 (R8-7)
"""운영 챗봇과 같은 검색·재랭킹 코드를 시험 스크립트에서 호출한다.

- 검색은 운영 그래프 노드 `retrieve`(app/graphs/nodes/retrieve.py)를,
  재랭킹은 운영 그래프 노드 `rerank`(app/graphs/nodes/rerank.py)를 그대로 호출한다.
  설정도 운영 그래프와 같은 `default_graph_dependencies()`(관리자 화면 설정 반영)를 쓴다.
- 운영과 다른 점은 하나: **LLM 질의 재작성(analyze_and_rewrite)을 하지 않는다.**
  합의서 시험 방법이 "시험 데이터를 입력하여 임베딩 기반 의미 검색과 BM25 기반 키워드 검색을 수행"이므로
  시험 질의문 원문만 검색어로 쓴다. 규칙 기반 전처리(정규화·약어 확장·조문 패턴·키워드, LLM 없음)는
  운영과 같게 적용한다.
- 권한 필터는 넣지 않는다(관리자 기준 전체 문서). 시험 컬렉션은 공개 법령 문서다.

이 모듈은 백엔드 실행 환경(백엔드 컨테이너 또는 같은 .env를 쓰는 가상환경)에서만 import한다.
"""

import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 앱 import·노드 실행의 INFO 이하 로그(질의별 수십 줄)를 끄고 시험 출력만 보이게 한다. --verbose면 그대로 출력.
if "--verbose" not in sys.argv:
    logging.disable(logging.INFO)

from app.graphs.dependencies import GraphDependencies, default_graph_dependencies  # noqa: E402
from app.graphs.nodes.rerank import rerank  # noqa: E402
from app.graphs.nodes.retrieve import retrieve  # noqa: E402


def load_components(with_reranker: bool) -> GraphDependencies:
    """[확인 항목] 임베딩 모델·하이브리드 검색 구성 요소(·Reranker 모델)를 불러오는 코드.

    모델은 GPU 서버에서 따로 서비스되므로 여기서는 각 서버에 연결하는 클라이언트를 만든다.
      - container.embedding         : 임베딩 모델 클라이언트(app/clients/embedding_client.py) — 의미 검색 질의 벡터
      - container.kiwi_bm25_encoder : Kiwi 형태소 분석 + BM25 질의 인코더(app/clients/kiwi_bm25_encoder.py) — 키워드 검색
      - container.vector_store      : Qdrant 저장소(app/repositories/vector_repository.py) — Dense·BM25 검색과 RRF 통합
      - container.query_preprocessor: 규칙 기반 질의 전처리(app/graphs/preprocessing/query_preprocessor.py)
      - container.reranker          : Reranker 모델 클라이언트(app/clients/reranker_client.py) — 시험 2만
    """
    deps = default_graph_dependencies()
    container = deps.container
    _ = (container.embedding, container.kiwi_bm25_encoder, container.vector_store, container.collection_service)
    if deps.settings.enable_query_preprocessing:
        _ = container.query_preprocessor
    if with_reranker:
        if not deps.settings.enable_reranking:
            raise SystemExit("ENABLE_RERANKING=false 입니다. 시험 2는 Reranker가 켜져 있어야 합니다.")
        _ = container.reranker
    return deps


def describe(deps: GraphDependencies, with_reranker: bool) -> List[str]:
    """재현 근거로 출력할 모델·검색 설정 (서버 주소·키는 출력하지 않는다)."""
    s = deps.settings
    lines = [
        f"임베딩 모델     : {s.embedding_model_name}",
        f"검색 방식       : {s.retrieval_engine} (Dense + Kiwi BM25 {s.kiwi_bm25_encoder_version}, "
        f"가중 RRF k={s.hybrid_rrf_k}, prefetch dense {s.dense_prefetch_k}/sparse {s.sparse_prefetch_k})",
        f"검색 후보 수    : {s.candidate_top_k} · 규칙 전처리 {'사용' if s.enable_query_preprocessing else '미사용'} · LLM 질의 재작성 미사용",
    ]
    if with_reranker:
        lines.append(f"Reranker 모델   : {s.reranker_model_name} (재정렬 상위 {s.reranker_top_k})")
    return lines


def _initial_state(question: str, collection: str, deps: GraphDependencies) -> Dict[str, Any]:
    """retrieve 노드 입력 state — 운영 analyze_and_rewrite의 규칙 전처리만 수행하고 재작성은 원문 1개."""
    preprocess_result: Dict[str, Any] = {}
    if deps.settings.enable_query_preprocessing:
        result = deps.container.query_preprocessor.preprocess(question)
        preprocess_result = {
            "normalized_query": result.normalized_query,
            "expanded_terms": result.expanded_terms,
            "matched_patterns": result.matched_patterns,
            "extracted_keywords": result.extracted_keywords,
        }
    return {
        "original_query": question,
        "collection_name": collection,
        "rewritten_queries": [question],
        "rewritten_query_embeddings": None,  # retrieve 노드가 임베딩 모델로 직접 계산
        "preprocess_result": preprocess_result,
        "filters": None,
        "timing": {},
    }


async def hybrid_search(question: str, collection: str, deps: GraphDependencies) -> Dict[str, Any]:
    """[확인 항목] 시험 질의로 임베딩 기반 의미 검색 + BM25 키워드 검색을 수행하고 결과를 통합한다.

    운영 retrieve 노드 내부 흐름(app/graphs/nodes/retrieve.py `_search_qdrant_hybrid`):
      1) embedding.embed_query(질의)            → Dense 질의 벡터
      2) kiwi_bm25_encoder.encode_query(질의)   → BM25 sparse 질의
      3) vector_store.search_hybrid(...)        → Qdrant가 Dense 검색·BM25 검색(prefetch 2개)을 각각 하고
                                                   가중 RRF로 통합해 후보 candidate_top_k개 반환
      4) apply_soft_boost(...)                  → 키워드 일치 가산 후 재정렬
    반환: {"state": 재랭킹에 넘길 state, "chunks": 통합 순위 청크 목록, "ms": 검색 시간}
    """
    state = _initial_state(question, collection, deps)
    started = time.perf_counter()
    result = await retrieve(state, deps)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if result.get("retrieval_status") != "ok":
        raise RuntimeError(result.get("error") or "검색 실패")
    state.update(result)
    return {"state": state, "chunks": result["retrieved_chunks"], "ms": elapsed_ms}


async def rerank_chunks(state: Dict[str, Any], deps: GraphDependencies) -> Dict[str, Any]:
    """[확인 항목] 하이브리드 검색 결과를 Reranker 모델에 넣어 질의-청크 관련도를 평가하고 재정렬한다.

    운영 rerank 노드 내부 흐름(app/graphs/nodes/rerank.py `rerank`):
      1) dedup_chunks_by_text      → 같은 본문 청크 중복 제거
      2) _build_rerank_text        → [문서명]·[섹션] 머리말 + 본문
      3) reranker.rerank(질의, 텍스트들, top_k=reranker_top_k) → 관련도 점수 내림차순 (원본 순번, 점수)
    Reranker 장애·꺼짐이면 운영은 대체 결과를 내지만, 시험에서는 정상 재랭킹이 아니므로 오류로 본다.
    """
    started = time.perf_counter()
    result = await rerank(state, deps)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    status = result.get("rerank_status")
    if status not in ("ok", "empty"):
        raise RuntimeError(f"재랭킹 비정상(rerank_status={status})")
    return {"chunks": result["reranked_chunks"], "ms": elapsed_ms}


def chunk_label(chunk: Dict[str, Any]) -> str:
    """결과 CSV용 '문서명 > 조항' 표시."""
    meta = chunk.get("metadata") or {}
    name = meta.get("original_filename") or meta.get("filename") or ""
    path = meta.get("header_path") or []
    location = " > ".join(path) if path else meta.get("section_title") or ""
    return f"{name} > {location}" if location else name
