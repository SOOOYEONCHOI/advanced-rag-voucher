"""
문서 로더 추상 기반 클래스
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any

# 로더 반환 타입: 페이지별 {"text": str, "metadata": dict} 리스트
MdMeta = List[Dict[str, Any]]


class BaseDocumentLoader(ABC):
    """모든 문서 로더의 공통 인터페이스"""

    @abstractmethod
    def load(self, file_path: str) -> MdMeta:
        """
        파일을 로드하여 페이지별 마크다운 메타데이터 반환.

        Returns:
            List[{
                "text": str,          # 페이지 마크다운 텍스트
                "metadata": {
                    "page": int,      # 페이지 번호 (1-based)
                    "page_count": int,
                    "file_path": str,
                    "file_type": str, # 확장자 (예: "pdf", "docx")
                }
            }]
        """
        ...

