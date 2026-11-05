"""
문서 파싱 데이터 모델
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/models.py
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class LCDocument:
    """LangChain 호환 문서 모델 (청킹 파이프라인 내부 표현)"""
    page_content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"page_content": self.page_content, "metadata": self.metadata}

# 로더가 반환하는 페이지별 원시 데이터 타입
# List[{"text": str, "metadata": {"page": int, "page_count": int, "file_path": str, ...}}]
MdMeta = List[Dict[str, Any]]


@dataclass(frozen=True)
class DocumentTypeDecision:
    """Resolved document type and the evidence used to select it."""

    requested_doc_type: str
    effective_doc_type: str
    source: str
    law_detected: bool = False
    manual_detected: bool = False
    detector_details: Optional[Dict[str, Any]] = None
