"""
파이프라인 컴포넌트 인터페이스(Protocol) 패키지.

2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 인터페이스 도입
  parser / retrieval / 전처리 / rerank / 모델(LLM·임베딩)을 코드 수정 없이
  교체할 수 있도록 각 컴포넌트의 계약을 Protocol로 정의한다.

  - 기존 구현체(EmbeddingClient, RerankerClient, VectorRepository, LLMService,
    QueryPreprocessor, 각 Loader/Chunker)는 시그니처가 이미 부합하므로(덕타이핑)
    코드 수정 없이 이 계약을 만족한다.
  - 새 구현 추가 = 이 Protocol에 맞는 클래스 작성 + 레지스트리/컨테이너 등록.
  - 소비자(노드/서비스)는 구체 클래스가 아닌 Protocol 타입에 의존한다.
"""

from app.interfaces.llm import LLMProvider
from app.interfaces.embedding import EmbeddingProvider
from app.interfaces.reranker import Reranker
from app.interfaces.vectorstore import VectorStore
from app.interfaces.parser import DocumentParser
from app.interfaces.chunker import Chunker
from app.interfaces.preprocessor import QueryPreprocessorProtocol

__all__ = [
    "LLMProvider",
    "EmbeddingProvider",
    "Reranker",
    "VectorStore",
    "DocumentParser",
    "Chunker",
    "QueryPreprocessorProtocol",
]
