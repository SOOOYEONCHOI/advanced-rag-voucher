"""
문서 파싱/청킹 모듈

주요 인터페이스:
    DocumentChunkingProcessor  - 메인 진입점
    ChunkingConfig             - 청킹 설정
    LCDocument                 - 청크 데이터 모델
"""

from .processor import DocumentChunkingProcessor
from .config import ChunkingConfig, DEFAULT_CONFIG
from .models import LCDocument

__all__ = [
    "DocumentChunkingProcessor",
    "ChunkingConfig",
    "DEFAULT_CONFIG",
    "LCDocument",
]
