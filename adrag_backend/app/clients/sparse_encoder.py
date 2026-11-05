"""
Sparse Vector 인코더 클라이언트.

# 2026.04.20(sooyeon.choi) 옵션 추가 - sparse_encoder_type 설정에 따라 세 가지 동작:
  - none  : sparse vector 미사용 (기존 Python BM25 유지)
  - bm42  : fastembed BM42 로컬 실행 (CPU 가능, 다국어 지원)
  - splade: 외부 SPLADE 서버 API 호출 (GPU 서버 필요)
"""

import asyncio
from dataclasses import dataclass
from typing import List, Optional

from app.core.config import Settings
from app.utils.log.log import LoggingLogger

# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)


@dataclass
class SparseVectorData:
    """Sparse vector 표현 (indices + values 쌍)."""
    indices: List[int]
    values: List[float]


class SparseEncoder:
    """
    sparse_encoder_type 설정에 따라 인코더를 선택한다.

    is_enabled == False (none) 이면 encode 메서드가 None을 반환하여
    기존 BM25 흐름이 그대로 유지된다.
    """

    def __init__(self, settings: Settings) -> None:
        self.encoder_type = settings.sparse_encoder_type
        self._model = None
        self._settings = settings

        if self.encoder_type == "bm42":
            self._init_bm42(settings.bm42_model_name)
        elif self.encoder_type == "splade":
            self._splade_url = settings.splade_api_url
            self._splade_model = settings.splade_model_name
            logger.info(f"[SparseEncoder] SPLADE 서버: {self._splade_url}")

    def _init_bm42(self, model_name: str) -> None:
        try:
            from fastembed import SparseTextEmbedding
            self._model = SparseTextEmbedding(model_name=model_name)
            logger.info(f"[SparseEncoder] BM42 모델 로드 완료: {model_name}")
        except ImportError:
            raise RuntimeError(
                "fastembed 패키지가 설치되지 않았습니다. pip install fastembed"
            )

    @property
    def is_enabled(self) -> bool:
        return self.encoder_type != "none"

    # ── 배치 인코딩 ────────────────────────────────────────────────────────

    def _encode_bm42_sync(self, texts: List[str]) -> List[SparseVectorData]:
        """BM42 동기 인코딩 (asyncio.to_thread에서 호출)."""
        embeddings = list(self._model.embed(texts))
        return [
            SparseVectorData(
                indices=e.indices.tolist(),
                values=e.values.tolist(),
            )
            for e in embeddings
        ]

    async def _encode_splade(self, texts: List[str]) -> List[SparseVectorData]:
        """외부 SPLADE 서버 API 호출."""
        # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient + 요청 단위 타임아웃 (B6)
        from app.core.http import get_shared_async_client
        response = await get_shared_async_client().post(
            f"{self._splade_url}/encode",
            json={"model": self._splade_model, "texts": texts},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        return [
            SparseVectorData(
                indices=item["indices"],
                values=item["values"],
            )
            for item in data["embeddings"]
        ]

    async def encode_batch(self, texts: List[str]) -> List[SparseVectorData]:
        """텍스트 배치를 sparse vector로 비동기 인코딩한다."""
        if self.encoder_type == "bm42":
            return await asyncio.to_thread(self._encode_bm42_sync, texts)
        elif self.encoder_type == "splade":
            return await self._encode_splade(texts)
        return []

    async def encode_single(self, text: str) -> Optional[SparseVectorData]:
        """단일 텍스트를 sparse vector로 비동기 인코딩한다."""
        if not self.is_enabled:
            return None
        results = await self.encode_batch([text])
        return results[0] if results else None
