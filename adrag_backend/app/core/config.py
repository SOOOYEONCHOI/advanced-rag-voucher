"""
중앙 설정 모듈 (pydantic-settings 기반).

# 2026.04.21(sooyeon.choi) 수정 - .env 단일 소스 관리 방식으로 전환
#   배포 관련 기본값 제거, 타입 선언만 유지
#   모든 설정값은 .env 에서 관리
"""

import os
from functools import lru_cache
from typing import Literal, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """애플리케이션 전체 설정. 모든 값은 .env 에서 주입."""

    # ── FastAPI ──────────────────────────────────────────
    app_name: str = "Advanced RAG Framework API"
    debug: bool = False
    log_level: str = "DEBUG"
    log_retention_days: int = Field(default=30, gt=0)
    log_error_retention_days: int = Field(default=90, gt=0)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level is invalid")
        return normalized

    # ── vLLM LLM 서빙 ───────────────────────────────────
    vllm_api_url: str
    vllm_model_name: str
    vllm_api_key: str
    vllm_max_tokens: int
    vllm_temperature: float
    vllm_max_model_len: int
    vllm_tp_size: int
    vllm_timeout: float = 120.0             # 요청 타임아웃 (코드 레벨 기본값)

    # R5-1 / F-4-05: 사내 ASR 주소가 없으면 STT 비활성화(503).
    voice_asr_api_url: Optional[str] = None
    voice_asr_api_key: Optional[str] = None
    voice_asr_model_name: str = "Qwen/Qwen3-ASR-1.7B"
    voice_asr_timeout: float = Field(default=30.0, gt=0)
    voice_max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    # ── vLLM Embedding 서빙 ──────────────────────────────
    embedding_api_url: str
    embedding_api_key: str = "EMPTY"
    embedding_model_name: str
    embedding_dim: int
    embedding_max_model_len: int
    embedding_batch_size: int = 32          # 배치 크기 (코드 레벨 기본값)
    embedding_timeout: float = 60.0         # 요청 타임아웃 (코드 레벨 기본값)
    embedding_instruct_template: str = (
        "Instruct: Given a web search query, retrieve relevant passages "
        "that answer the query\nQuery: {query}"
    )
    # 2026.07.16(sooyeon.choi) 추가 - vLLM 서버측 토큰 truncation (B3)
    #   -1: 모델 최대 길이로 서버가 안전하게 잘라냄 (reranker와 동일 규약)
    #    0: 파라미터 미전송 (truncate_prompt_tokens를 지원하지 않는 서버용)
    #   >0: 지정 토큰 수로 truncation
    embedding_truncate_prompt_tokens: int = -1

    # ── Reranker (vLLM score API) ─────────────────────────
    # 2026.04.21(sooyeon.choi) reranker api 호출 분기 처리 추가
    enable_reranking: bool
    reranker_api_url: str
    reranker_api_key: str
    reranker_model_name: str
    reranker_timeout: float = 30.0          # 요청 타임아웃 (코드 레벨 기본값)
    # 2026.07.07(sooyeon.choi) 수정 - vLLM score 입력 truncation과 장애 시 후보 상한 명시
    reranker_truncate_prompt_tokens: int = -1
    reranker_degraded_top_k: int = 3
    retrieve_timeout: float = 90.0          # retrieve 노드 전체 타임아웃 (임베딩 + Qdrant 검색 합산)

    # ── Docling 파싱 서버 ───────────────────────────────
    docling_parser_host: str
    docling_api_key: str = ""               # 선택적 (없으면 빈 문자열)
    docling_connect_timeout: int = 10       # Docling 서버 TCP 연결 타임아웃 (초)
    docling_read_timeout: int = 1200        # Docling 파일 업로드·결과 조회 타임아웃 (초)
    docling_max_wait_seconds: int = 1200    # Docling Job 폴링 총 대기 상한 (초)

    # ── Qdrant ──────────────────────────────────────────
    qdrant_host: str
    qdrant_port: int

    # ── Sparse Vector 인코더 ─────────────────────────────
    # 2026.04.20(sooyeon.choi) 옵션 추가
    # "none"  : sparse vector 미사용
    # "bm42"  : fastembed BM42 로컬 실행
    # "splade": 외부 SPLADE 서버 API 호출
    sparse_encoder_type: str
    bm42_model_name: str = "Qdrant/bm42-all-minilm-l6-v2-attentions"
    splade_api_url: str = "http://splade-server:8000"
    splade_model_name: str = "naver/splade-cocondenser-ensembledistil"

    # ── SQLite ──────────────────────────────────────────
    # 2026.10.16 수정 - Phase 1.5: 앱 DB는 PostgreSQL(app.core.db_config). 이 값은 저장소 생성자 하위 호환 인자와
    #   이관 스크립트 원본 경로로만 남는다(설계 Q-15.7, 정리는 Phase 2).
    sqlite_db_path: str = "./instance/db/db_rag_metadata.db"

    # ── 청킹 ────────────────────────────────────────────
    max_chunk_size: int
    chunk_overlap: int
    top_k_results: int
    max_query_top_k: int = 20               # 최대 쿼리 top_k (코드 레벨 기본값)
    # 2026.06.29(sooyeon.choi) 추가 - retrieve→rerank→assemble_context 단계별 독립 top_k
    candidate_top_k: int = 40              # 검색 후보 수 (retrieve 단계)
    # 2026.07.07(sooyeon.choi) 수정 - 중복 reranker_top_k 선언을 단계별 설정 한 곳으로 통합
    reranker_top_k: int = 10               # 재랭킹 대상 수 (rerank 단계)
    context_top_k: int = 6                 # 최종 LLM 컨텍스트 포함 수 (assemble_context 단계)
    # 2026.07.08(sooyeon.choi) 수정 - 단일 문서의 유사 청크가 컨텍스트를 독점하지 않도록 제한
    context_max_chunks_per_document: int = 2
    max_citation_results: int = 5           # 최대 인용 결과 수 (코드 레벨 기본값)
    max_collections: int = 5                # 사용자당 최대 컬렉션 수 (코드 레벨 기본값)
    max_context_chars: int = 32000          # assemble_context 최대 문자 수 (한국어 ~16,000 토큰)
    query_min_length: int = 2              # 질의 최소 문자 수
    query_max_length: int = 2000           # 질의 최대 문자 수

    # ── 시맨틱 보강 (LLM enrichment) ────────────────────
    enable_semantic_enrichment: bool

    # ── HuggingFace ──────────────────────────────────────
    hf_cache_dir: str
    hf_token: Optional[str] = None          # 선택적 (없으면 None)

    # ── 보안 ────────────────────────────────────────────
    jwt_secret_key: str
    jwt_algorithm: str
    jwt_expiration_minutes: int = 1440      # 토큰 만료 시간 (코드 레벨 기본값)

    # ── 메타데이터 필터링 ────────────────────────────────
    # 2026.04.21(sooyeon.choi) 수정 - enable_metadata_reranking, cross_encoder_weight,
    #   metadata_weight, filter_hard/soft_threshold 제거 (vLLM CE score 단일 방식 단순화)
    enable_metadata_filtering: bool
    enable_query_preprocessing: bool
    rag_diagnostic_log: bool = False
    # 2026.06.29(sooyeon.choi) 추가 - 기본 검색은 Dense+Kiwi BM25, BM42는 프로필로 선택
    retrieval_profile: str = "dense_kiwi"
    # 2026.07.07(sooyeon.choi) 수정 - Qdrant 서버 측 Dense+Kiwi BM25 hybrid 검색 전환
    retrieval_engine: str = "qdrant_hybrid"  # "legacy" | "qdrant_hybrid"
    hybrid_rrf_k: int = 60                  # Hybrid RRF 상수 (코드 레벨 기본값)
    # 2026.06.29(sooyeon.choi) 추가 - 법령 문서용 BM25 빈도 포화·문서 길이 보정값을 환경 설정으로 분리
    bm25_k1: float = 1.2
    bm25_b: float = 0.5
    bm25_avg_len: float = 128.0
    kiwi_bm25_vector_name: str = "kiwi_bm25"
    kiwi_bm25_encoder_version: str = "kiwi-bm25-v1"
    dense_prefetch_k: int = 80
    sparse_prefetch_k: int = 80
    # relevance_threshold: float = 0.3        # rerank 후 컨텍스트 포함 최소 관련성 점수
    relevance_threshold: float = 0.25        # rerank 후 컨텍스트 포함 최소 관련성 점수
    fallback_relevance_threshold: float = 0.1  # fallback 재시도 시 완화된 관련성 점수
    fallback_max_retries: int = 1           # fallback 최대 재시도 횟수 (코드 레벨 기본값)
    soft_boost_keyword: float = 0.05
    soft_boost_tag: float = 0.03
    soft_boost_document_type: float = 0.10
    soft_boost_intent: float = 0.05
    menu_hint_terms: list[str] = ["메뉴", "화면", "버튼", "탭", "페이지", "기능", "클릭", "선택"]
    narrative_hint_terms: list[str] = ["사고", "재해", "사례", "발생", "현장", "작업자", "피해", "원인", "경위"]
    embedding_provider: str = "vllm"
    vector_store_provider: str = "qdrant"
    reranker_provider: str = "vllm"
    # 2026.04.13(sooyeon.choi) 추가 - anonymous 사용자 기본 허용 컬렉션
    # 빈 리스트([])면 source_collection 필터 미적용 (전체 허용)
    anonymous_default_collections: str = "[]"

    # ── 가드레일 ────────────────────────────────────────
    # False로 설정하면 모든 질의를 RAG 파이프라인으로 통과시킨다.
    enable_guardrail: bool = True
    # False로 설정하면 Rule-based 판별 불가 시 rag_query로 처리 (LLM 호출 생략).
    guardrail_llm_fallback: bool = True

    # ── Answer Correctness 평가 ─────────────────────────
    # 네 지표는 항상 계산·저장하고 primary는 UI 주 지표 하나만 선택한다.
    answer_correctness_primary: str = "f2"  # v1 | v2 | f2 | judge
    answer_correctness_fallback_chain: list[str] = Field(
        default_factory=lambda: ["judge", "v2", "v1"]
    )
    answer_correctness_v2_dedupe_threshold: float = 0.92
    answer_correctness_v2_precision_candidate_ratio: int = 3
    answer_correctness_v2_min_sentence_chars: int = 10
    answer_correctness_v2_max_sentences_per_answer: int = 30
    answer_correctness_judge_backend: str = "vllm"
    answer_correctness_judge_model: Optional[str] = None
    answer_correctness_judge_temperature: float = 0.0
    openai_api_key: Optional[str] = None

    @field_validator("answer_correctness_primary")
    @classmethod
    def validate_answer_correctness_primary(cls, value: str) -> str:
        if value not in {"v1", "v2", "f2", "judge"}:
            raise ValueError("answer_correctness_primary must be v1, v2, f2, or judge")
        return value

    @field_validator("answer_correctness_fallback_chain")
    @classmethod
    def validate_answer_correctness_fallback_chain(cls, value: list[str]) -> list[str]:
        allowed = {"v1", "v2", "f2", "judge"}
        if len(value) != len(set(value)) or any(item not in allowed for item in value):
            raise ValueError("answer_correctness_fallback_chain contains invalid or duplicate metrics")
        return value

    @field_validator("answer_correctness_judge_backend")
    @classmethod
    def validate_answer_correctness_judge_backend(cls, value: str) -> str:
        if value not in {"vllm", "openai"}:
            raise ValueError("answer_correctness_judge_backend must be vllm or openai")
        return value

    # ── 파일 저장 ────────────────────────────────────────
    # 원본 업로드 파일 영구 보관 경로 (연/월 하위 폴더 자동 생성)
    uploaded_files_base_dir: str = "instance/data"
    # 2026.05.22(sooyeon.choi) 추가 - Docling 파싱 결과 마크다운 저장 경로 (빈 문자열이면 저장 안 함)
    md_save_dir: str = "instance/parsed_md"
    # 2026.10.16 추가 - 엑셀 전용 처리기(excel_ingest) 분기 모드
    #   docling(기본): 기존 동작 그대로 — 엑셀도 docling 파서로 처리하고 .xls는 거부
    #   backend      : xlsx·xlsm·xls를 excel_ingest로 처리(문서 유형·파서 선택 무시). .xls는 LibreOffice로 변환
    excel_parse_mode: Literal["docling", "backend"] = "backend"
    # 확인용 md를 실행(job)별로 몇 개까지 남길지 (md_save_dir/excel/{doc_key}/{job_id}/)
    excel_md_keep_last: int = Field(default=5, gt=0)
    # .xls → .xlsx LibreOffice 변환 제한 시간(초)
    excel_xls_convert_timeout: int = Field(default=120, gt=0)
    # 2026.10.22(sooyeon.choi) 추가 - 엑셀 사진 전부 자동 연결
    #   true : 장식·양식 머리글을 뺀 모든 사진을 셀 위치 기준(Step → 행 겹침 → 가장 가까운 청크)으로 청크에 연결
    #   false: Phase 2 동작(SOP Step 사진만 연결). 이미 적재한 문서는 다시 등록해야 바뀐다
    excel_image_link_all: bool = True
    # 2026.10.19 추가 - 문서 목록 [최신본 변경]
    document_version_replace_enabled: bool = True
    # 2026.10.19 추가 - 사진 답변·출처 패널·이미지 뷰어
    #   false면 사진 후보를 프롬프트에 넣지 않고 응답 images도 비운다(기존 답변 흐름 그대로).
    #   사진이 연결된 엑셀 문서가 근거일 때만 프롬프트가 바뀐다(그 외 문서는 후보 0건 → 기존과 같음).
    answer_images_enabled: bool = True
    rag_max_images: int = Field(default=4, ge=0)          # 답변 1건에 표시할 최대 사진 수(RAG_MAX_IMAGES)
    rag_image_candidates: int = Field(default=8, ge=0)    # LLM에 보여줄 사진 후보 수
    answer_image_auto_attach: bool = True                 # 인용이 없을 때 Step 사진 1장 자동 첨부
    # 2026.08.27(sooyeon.choi) 추가 - excel resource 영구 저장/내부 업로드 설정
    resource_storage_root: str = "instance/xl_res"
    resource_internal_api_key: str = ""
    resource_max_upload_bytes: int = 50 * 1024 * 1024
    resource_staging_ttl_hours: int = Field(default=24, gt=0)
    resource_cleanup_interval_seconds: int = Field(default=3600, gt=0)
    # 2026.08.28(sooyeon.choi) 추가 - resource 전달 방식 (pull | push)
    resource_delivery: str = "pull"

    # ── CORS ────────────────────────────────────────────
    cors_origins: str

    # ── SCR-006 통계 ─────────────────────────────────────
    # 2026.06.16(sooyeon.choi) 추가 - 모델별 API 비용 단가 (USD per 1,000 tokens)
    model_pricing_usd: dict = {
        "gpt-4o-mini":  {"input": 0.00015, "output": 0.0006},
        "gpt-4.1":      {"input": 0.002,   "output": 0.008},
        "gpt-4.1-mini": {"input": 0.0004,  "output": 0.0016},
        "local":        {"input": 0.0,     "output": 0.0},
    }
    stats_stale_days: int = 90   # "갱신 필요" 판정: 미참조 N일 이상
    stats_dead_days: int = 60    # "미참조 경고" 판정: N일 이상 미인용

    model_config = SettingsConfigDict(
        # 2026.05.04(sooyeon.choi) 추가 - .env를 프로젝트 루트로 이동함에 따라 탐색 경로 추가
        # 우선순위: 환경변수 > ../.env (프로젝트 루트, 로컬 실행 시) > .env (하위 호환)
        # Docker 컨테이너 내부에서는 env_file + environment로 주입되므로 파일 탐색 불필요
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """싱글턴 Settings 인스턴스를 반환합니다."""
    return Settings()


# 로거용 로그 저장 경로 — pydantic Settings 초기화 이전에도 사용 가능한 단순 상수
LOG_PATH = os.getenv("LOG_PATH", "./instance/log")
