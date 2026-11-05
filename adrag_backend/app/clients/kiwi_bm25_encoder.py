"""Kiwi 전처리를 Qdrant BM25 sparse 입력으로 변환한다."""

from typing import TYPE_CHECKING, Any, Dict
from qdrant_client.models import Document
from app.utils.kiwi_tokenizer import tokenize_corpus, tokenize_query_for_bm25

if TYPE_CHECKING:
    from app.core.config import Settings


class KiwiBm25Encoder:
    """적재와 검색에 동일한 Kiwi/BM25 정책을 적용한다."""

    # 2026.07.07(sooyeon.choi) 수정 - 후보 400개 재계산 대신 Qdrant BM25 sparse vector 사용
    def __init__(self, settings: "Settings") -> None:
        self.k1 = settings.bm25_k1
        self.b = settings.bm25_b
        self.avg_len = settings.bm25_avg_len
        self.version = settings.kiwi_bm25_encoder_version

    def _options(self) -> Dict[str, Any]:
        return {
            # 2026.07.07(sooyeon.choi) 수정 - FastEmbed BM25는 language=none을 지원하지 않으므로
            # Kiwi가 만든 공백 토큰을 유지하도록 영문 stemmer만 명시적으로 비활성화한다.
            "language": "english",
            "disable_stemmer": True,
            "k": self.k1,
            "b": self.b,
            "avg_len": self.avg_len,
        }

    def normalize_document(self, text: str) -> str:
        tokens = tokenize_corpus(text)
        return " ".join(tokens) if tokens else text.strip()

    def normalize_query(self, text: str) -> str:
        tokens = tokenize_query_for_bm25(text)
        if not tokens:
            tokens = tokenize_corpus(text)
        normalized = " ".join(tokens) if tokens else text.strip()
        if not normalized:
            raise ValueError("BM25 검색 토큰이 없습니다.")
        return normalized

    def encode_document(self, text: str) -> Document:
        return Document(
            text=self.normalize_document(text),
            model="qdrant/bm25",
            options=self._options(),
        )

    def encode_query(self, text: str) -> Document:
        return Document(
            text=self.normalize_query(text),
            model="qdrant/bm25",
            options=self._options(),
        )
