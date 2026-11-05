"""
문서 파싱/청킹 설정
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/config.py
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ChunkingConfig:
    """청킹 설정"""

    # ── 법령 문서 ──────────────────────────────────────────
    law_chunk_size: int = 800
    law_chunk_overlap: int = 0

    # ── 일반 문서 ──────────────────────────────────────────
    general_chunk_size: int = 800
    general_chunk_overlap: int = 160

    # ── 매뉴얼 문서 ────────────────────────────────────────
    manual_chunk_size: int = 800
    manual_chunk_overlap: int = 160

    # ── 법령 판정 ──────────────────────────────────────────
    law_score_threshold: int = 6
    law_article_threshold: int = 2

    # ── 매뉴얼 판정 ────────────────────────────────────────
    # 2026.06.04(sooyeon.choi) 변경 - 다중 신호 스코어링 방식으로 전환
    # 기존: manual_circled_threshold(3), manual_tree_threshold(5) 이진 판정
    # 변경: 가중치 합산 점수가 임계값 이상이면 매뉴얼로 판정 (detectors/manual.py 참조)
    
    # manual_circled_threshold: int = 3   # 원형번호(①②③) 최소 개수
    # manual_tree_threshold: int = 5      # 트리구조(├─└─) 최소 줄 수
    manual_score_threshold: int = 18

    # ── 파서 ───────────────────────────────────────────────
    # "pdfplumber" | "docling"
    parser_type: str = "docling"
    # 사용자가 지정한 문서 유형. auto이면 기존 detector를 실행한다.
    requested_doc_type: str = "auto"
    # 2026.06.04(sooyeon.choi) 변경 - 5 → 8
    # 표지/목차/소개로 구성된 초반 페이지가 많은 화면 매뉴얼에서 UI 시그널이
    # 5페이지 이후부터 등장하여 매뉴얼 미판정되는 문제 해결
    # 예: SWING CMMS 사용자 매뉴얼 - 1~5p 표지+개요, 6p부터 화면 기능설명 시작
    sample_pages: int = 8               # 문서 유형 판정용 샘플 페이지 수

    # ── 테이블 처리 ────────────────────────────────────────
    flatten_tables: bool = False

    # ── Excel 구조 기반 청킹 ──────────────────────────────
    # 2026.08.27(sooyeon.choi) 추가 - SpreadsheetChunker 정본 설정
    spreadsheet_max_records_per_chunk: int = 50
    spreadsheet_max_embedding_chars: int = 4000
    spreadsheet_max_embedding_tokens: int = 1000
    spreadsheet_repeat_headers: bool = True
    spreadsheet_include_sheet_context: bool = True
    spreadsheet_summary_chunks: bool = False
    # 2026.08.27(sooyeon.choi) 추가 - 수식 embedding 정책
    # "off": 표시값만 사용 | "auto": 수식 중심 block | "always": 모든 수식
    spreadsheet_formula_embedding: str = "auto"
    spreadsheet_max_formula_manifest: int = 20

    # ── header_path 설정 ────────────────────────────────────
    include_header_path_in_content: bool = True
    header_path_format: str = "[위치: {path}]"

    # ── 매뉴얼 섹션 prefix ─────────────────────────────────
    # 2026.06.04(sooyeon.choi) 변경 - 청크 본문에 라벨 없이 경로 문자열만 삽입하는 방식으로 전환
    # 이 값은 더 이상 chunkers/manual.py에서 사용하지 않음 (하위 호환용으로 필드 유지)
    manual_section_prefix_format: str = "[섹션: {section_title}]"

    # ── 공통 오버라이드 (설정 시 law/general 양쪽 적용) ────
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None

    def __post_init__(self):
        spreadsheet_limits = {
            "spreadsheet_max_records_per_chunk": self.spreadsheet_max_records_per_chunk,
            "spreadsheet_max_embedding_chars": self.spreadsheet_max_embedding_chars,
            "spreadsheet_max_embedding_tokens": self.spreadsheet_max_embedding_tokens,
        }
        for name, value in spreadsheet_limits.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than 0")
        # 2026.08.27(sooyeon.choi) 추가 - 수식 정책 값 검증
        if self.spreadsheet_formula_embedding not in {"off", "auto", "always"}:
            raise ValueError(
                "spreadsheet_formula_embedding must be one of 'off', 'auto', 'always'"
            )
        if self.spreadsheet_max_formula_manifest < 0:
            raise ValueError("spreadsheet_max_formula_manifest must be 0 or greater")
        if self.chunk_size is not None:
            self.law_chunk_size = self.chunk_size
            self.general_chunk_size = self.chunk_size
        if self.chunk_overlap is not None:
            self.law_chunk_overlap = self.chunk_overlap
            self.general_chunk_overlap = self.chunk_overlap


DEFAULT_CONFIG = ChunkingConfig()