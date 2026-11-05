"""
문서 파서(로더) 인터페이스.

2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 인터페이스 도입
기준 구현: app/parsers/loaders/ (DoclingApiLoader, PdfPlumberLoader / BaseLoader ABC)
OpenDataLoader, OCR 전용 파서 등 신규 파서는 이 계약을 만족하는 로더를 작성해
app/parsers/processor.py의 파서 레지스트리(register_parser)에 등록하면
문서 유형/확장자 라우팅에 편입된다. (SFR-015 문서 파서 다중 지원의 기반)
"""

from typing import Any, Dict, List, Protocol, runtime_checkable

# 페이지 단위 마크다운 메타: [{"text": str, "metadata": {"page": int, ...}}, ...]
MdMeta = List[Dict[str, Any]]


@runtime_checkable
class DocumentParser(Protocol):
    """문서 → 페이지 단위 마크다운 변환 계약."""

    def load(self, file_path: str) -> MdMeta:
        """파일을 파싱해 페이지 단위 마크다운 메타 리스트를 반환한다."""
        ...
