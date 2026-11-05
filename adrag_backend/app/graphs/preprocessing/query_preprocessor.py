"""
규칙 기반 질의 전처리 모듈.

LLM 호출 없이 동기적으로 실행되며, 텍스트 정규화, 사전 기반 약어 확장,
정규표현식 패턴 매칭, 형태소 분석 기반 키워드 추출을 수행한다.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from app.utils.dictionary_loader import load_korean_search_dictionary
from app.utils.kiwi_tokenizer import (
    _normalize_compound_spacing,
    extract_search_terms,
    get_kiwi,
)
from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)

# ── 정규표현식 패턴 ─────────────────────────────────────
LAW_REFERENCE_PATTERN = re.compile(r"제\d+조(?:의\d+)?(?:\s*제\d+항)?")
DATE_PATTERN = re.compile(r"\d{4}[년.]\s*\d{1,2}[월.]?\s*\d{0,2}일?")
_SPACED_LAW_UNIT_PATTERN = re.compile(r"제\s*(\d+)\s*(조|항|호)(\s*의\s*\d+)?")
_BARE_LAW_UNIT_PATTERN = re.compile(r"(?<!제)(\d+)\s*(조|항|호)(\s*의\s*\d+)?(?!원)")

# 제어 문자 제거용 패턴 (탭·줄바꿈 제외)
_CONTROL_CHAR_RE = re.compile(
    r"[^\S \t\n\r]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)


@dataclass
class PreprocessResult:
    """규칙 기반 전처리 결과."""

    normalized_query: str = ""
    expanded_terms: List[str] = field(default_factory=list)
    matched_patterns: Dict[str, List[str]] = field(default_factory=dict)
    extracted_keywords: List[str] = field(default_factory=list)


class QueryPreprocessor:
    """규칙 기반 질의 전처리기.

    LLM 호출 없이 동기적으로 실행되며, 텍스트 정규화 → 약어 확장 →
    패턴 매칭 → 형태소 분석 키워드 추출 순서로 전처리를 수행한다.
    """

    def __init__(self, abbreviation_dict: Dict[str, str] | None = None) -> None:
        # 2026.06.26(sooyeon.choi) 수정 - YAML 통합 사전을 QueryPreprocessor 약어 확장 원천으로 사용
        try:
            dictionary = load_korean_search_dictionary()
            self._abbreviations = (
                abbreviation_dict
                if abbreviation_dict is not None
                else dictionary.abbreviations
            )
            self._aliases = dictionary.aliases
            # 2026.06.29(sooyeon.choi) 수정 - YAML 복합어를 질의 띄어쓰기 정규화에도 공유
            self._compound_terms = dictionary.compound_terms
        except Exception:
            logger.error("약어 사전 로드 실패, 약어 확장을 건너뜁니다.")
            self._abbreviations = abbreviation_dict or {}
            self._aliases = {}
            self._compound_terms = []

        # 2026.04.08(sooyeon.choi) 추가 - konlpy Okt → kiwi 형태소 분석기로 교체 (법령 도메인 패턴 포함)
        # 2026.04.13(sooyeon.choi) 수정 - Kiwi 직접 초기화 제거 → app/utils/kiwi_tokenizer.py 싱글톤 사용
        #   기존: 이 클래스마다 Kiwi 인스턴스를 별도 생성 (vector_repository.py와 중복)
        #   변경: 전역 싱글톤을 공유하여 메모리·초기화 비용 절감
        if get_kiwi() is None:
            logger.warning("Kiwi 미사용 — 형태소 분석 기반 키워드 추출을 건너뜁니다.")

    # ── public API ──────────────────────────────────────

    def preprocess(self, query: str) -> PreprocessResult:
        """규칙 기반 전처리 수행 (동기)."""
        normalized = self._normalize_text(query)
        # 2026.06.29(sooyeon.choi) 수정 - 약어 확장 전에 복합어 띄어쓰기 변형을 표준화
        normalized = _normalize_compound_spacing(normalized, self._compound_terms)
        expanded_text, expanded_terms = self._expand_abbreviations(normalized)
        expanded_text = self._normalize_law_reference_notation(expanded_text)
        matched_patterns = self._match_patterns(expanded_text)
        extracted_keywords = self._extract_keywords(expanded_text)

        # logger.info(
        #     "[Kiwi 형태소 분석 결과] "
        #     "원본 질의='%s' | "
        #     "약어 확장=%s | "
        #     "법령 패턴=%s | "
        #     "추출 키워드(NNG/NNP/SL)=%s",
        #     query,
        #     expanded_terms if expanded_terms else "(없음)",
        #     matched_patterns.get("law_references") or "(없음)",
        #     extracted_keywords if extracted_keywords else "(없음)",
        # )

        return PreprocessResult(
            normalized_query=expanded_text,
            expanded_terms=expanded_terms,
            matched_patterns=matched_patterns,
            extracted_keywords=extracted_keywords,
        )

    # ── private helpers ─────────────────────────────────

    def _normalize_text(self, text: str) -> str:
        """연속 공백 → 단일 공백, 선행/후행 공백 제거, 제어 문자 제거."""
        # 유니코드 정규화 (NFC)
        text = unicodedata.normalize("NFC", text)
        # 제어 문자 제거
        text = _CONTROL_CHAR_RE.sub("", text)
        # 연속 공백 → 단일 공백
        text = re.sub(r"[ \t]+", " ", text)
        # 연속 줄바꿈 정리
        text = re.sub(r"\n+", "\n", text)
        return text.strip()

    def _expand_abbreviations(self, text: str) -> Tuple[str, List[str]]:
        """사전 기반 약어 확장. 확장된 정식 명칭 목록도 함께 반환.

        한글 약어는 본문에서 정식 명칭으로 치환하고, 영문 alias는 원문 토큰을 보존한 채
        expanded_terms에 정식 명칭을 추가해 양방향 검색 후보를 유지한다.
        """
        expanded_terms: List[str] = []
        result = text
        for abbr, full_name in self._abbreviations.items():
            if abbr in result:
                result = result.replace(abbr, full_name)
                if full_name not in expanded_terms:
                    expanded_terms.append(full_name)
        for alias, full_name in self._aliases.items():
            if alias in result and full_name not in expanded_terms:
                expanded_terms.append(full_name)
        return result, expanded_terms

    def _normalize_law_reference_notation(self, text: str) -> str:
        """조문 단위 표기를 ``제N조`` 형식으로 통일한다."""
        text = _SPACED_LAW_UNIT_PATTERN.sub(
            lambda match: f"제{match.group(1)}{match.group(2)}{(match.group(3) or '').replace(' ', '')}",
            text,
        )
        return _BARE_LAW_UNIT_PATTERN.sub(
            lambda match: f"제{match.group(1)}{match.group(2)}{(match.group(3) or '').replace(' ', '')}",
            text,
        )

    def _match_patterns(self, text: str) -> Dict[str, List[str]]:
        """정규표현식 기반 법령 조문/날짜 패턴 매칭."""
        law_refs = LAW_REFERENCE_PATTERN.findall(text)
        date_refs = DATE_PATTERN.findall(text)
        return {
            "law_references": law_refs,
            "date_references": date_refs,
        }

    def _extract_keywords(self, text: str) -> List[str]:
        """키워드 추출: 띄어쓰기 토큰 우선 보존 + Kiwi 형태소 보완.

        # 2026.04.08(sooyeon.choi) 추가 - kiwi API 기반 키워드 추출 (NNG/NNP/SL 품사 필터링)
        # 2026.04.13(sooyeon.choi) 수정 - app/utils/kiwi_tokenizer.extract_nouns()로 위임
        # 2026.04.14(sooyeon.choi) 수정 - 띄어쓰기 토큰 우선 보존 후 Kiwi 형태소 보완
        #   기존: Kiwi만 사용 → "파견근로자보호법" 같은 복합 법령명이 형태소 단위로 분해됨
        #   변경: 띄어쓰기 분리 토큰을 먼저 수집하여 복합어 보존, Kiwi는 보완 역할만 담당

        1단계 — 띄어쓰기 분리: 사용자가 붙여 쓴 복합어(법령명 등)를 단일 토큰으로 보존
        2단계 — Kiwi 형태소 추출: 복합어 내 개별 명사를 추가 확보 (보완)
        3단계 — 합집합: 띄어쓰기 토큰 우선, 중복 제거, 순서 유지

        # 2026.06.29(sooyeon.choi) 수정 - 기능성 불용어는 최종 검색 후보에서 제외
        예) "파견근로자보호법 개정안 알려줘"
            → 띄어쓰기: ['파견근로자보호법', '개정안']
            → Kiwi:     ['파견', '근로자', '보호', '개정안']
            → 결과:     ['파견근로자보호법', '개정안', '파견', '근로자', '보호']
            (Qdrant 실존 검증 단계에서 실제 없는 토큰은 자동 탈락)
        """
        # 2026.06.29(sooyeon.choi) 수정 - BM25/metadata 후보와 동일한 기능성 불용어 정책 사용
        return extract_search_terms(text)
