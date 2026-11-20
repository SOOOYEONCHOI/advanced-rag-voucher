"""
vLLM 기반 Embedding 비동기 클라이언트.

vLLM의 OpenAI 호환 /v1/embeddings 엔드포인트를 호출하여
텍스트를 벡터로 변환합니다.

Qwen3-Embedding은 query에 instruct prefix를 붙이면 검색 성능이 1~5% 향상됩니다.
문서(passage)에는 instruct를 붙이지 않습니다.
"""

import math
import time
from typing import Any, Dict, List

import httpx
import numpy as np

from app.core.config import Settings
# 2026.07.16(sooyeon.choi) 수정 - 요청마다 AsyncClient 생성 → 공유 클라이언트 재사용
from app.core.http import get_shared_async_client
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)


class EmbeddingClient:
    """vLLM OpenAI-compatible Embedding 비동기 클라이언트."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.embedding_api_url.rstrip("/")
        self.model = settings.embedding_model_name
        self.api_key = settings.embedding_api_key
        self.timeout = settings.embedding_timeout
        self.batch_size = settings.embedding_batch_size
        self.dim = settings.embedding_dim
        self.instruct_template = settings.embedding_instruct_template
        # 2026.07.16(sooyeon.choi) 수정 - 서버측 truncation 도입
        #   기존: 문자 수 × 3 근사만으로 잘라 한국어 장문에서 토큰 한도 초과
        #   → vLLM 400 오류(임베딩/인제스트 실패) 가능성이 있었음.
        #   변경: truncate_prompt_tokens를 vLLM에 전달해 토큰 기준으로 안전하게
        #   서버가 잘라내고, 문자 수 한도는 과대 페이로드 방지용 가드로만 유지.
        self.truncate_prompt_tokens = settings.embedding_truncate_prompt_tokens
        # 과대 페이로드 방지 가드: 토큰 한도 × 3자 (정확한 절단은 서버측 truncation이 담당)
        self._max_chars = settings.embedding_max_model_len * 3

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    # ── 내부: vLLM /v1/embeddings 호출 ──────────────────

    def _truncate(self, texts: List[str]) -> List[str]:
        """max_chars를 초과하는 텍스트를 잘라낸다. 잘린 경우 WARNING 로그를 출력한다."""
        result = []
        for text in texts:
            if len(text) > self._max_chars:
                logger.warning(
                    f"[EmbeddingClient] 텍스트 트런케이션: {len(text)}자 → {self._max_chars}자 "
                    f"(embedding_max_model_len={self._max_chars // 3} tokens 기준)"
                )
                result.append(text[: self._max_chars])
            else:
                result.append(text)
        return result

    async def _request_embeddings(
        self, texts: List[str]
    ) -> List[List[float]]:
        """vLLM /v1/embeddings 엔드포인트를 호출합니다."""
        texts = self._truncate(texts)
        payload: Dict[str, Any] = {
            "model": self.model,
            "input": texts,
        }
        # 2026.07.16(sooyeon.choi) 추가 - 서버측 토큰 truncation
        #   0이면 미전송(미지원 서버 호환), -1이면 모델 최대 길이 기준
        if self.truncate_prompt_tokens != 0:
            payload["truncate_prompt_tokens"] = self.truncate_prompt_tokens

        # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient + 요청 단위 타임아웃
        client = get_shared_async_client()
        resp = await client.post(
            f"{self.base_url}/v1/embeddings",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            logger.error(
                f"Embedding API 오류 {resp.status_code}: {resp.text} "
                f"(texts={len(texts)}, max_len={max(len(t) for t in texts)}chars)"
            )
        resp.raise_for_status()
        data = resp.json()

        # 응답에서 임베딩 추출 (index 순서대로 정렬)
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    @staticmethod
    def _normalize(vectors: List[List[float]]) -> List[List[float]]:
        """L2 정규화."""
        result = []
        for vec in vectors:
            arr = np.array(vec, dtype=np.float32)
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            result.append(arr.tolist())
        return result

    # ── 문서 임베딩 (instruct 없음) ─────────────────────

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        텍스트 리스트를 임베딩 벡터로 변환합니다.
        문서 인덱싱용 — instruct prefix 없이 인코딩합니다.
        """
        all_embeddings: List[List[float]] = []
        batch_count = math.ceil(len(texts) / self.batch_size) if texts else 0

        for i in range(0, len(texts), self.batch_size):   # batch 단위로 API 호출
            batch = texts[i : i + self.batch_size]
            batch_index = i // self.batch_size + 1
            total_chars = sum(len(text) for text in batch)
            max_chars = max((len(text) for text in batch), default=0)
            started_at = time.perf_counter()
            logger.info(
                "[EMBEDDING][batch] 시작 batch=%s/%s texts=%s total_chars=%s max_chars=%s",
                batch_index,
                batch_count,
                len(batch),
                total_chars,
                max_chars,
            )
            try:
                embeddings = await self._request_embeddings(batch)   # API 호출
            except httpx.TimeoutException as exc:
                logger.error(
                    "[EMBEDDING][batch] timeout batch=%s/%s texts=%s "
                    "total_chars=%s max_chars=%s elapsed=%.2fs timeout=%ss "
                    "endpoint=%s exception=%s",
                    batch_index,
                    batch_count,
                    len(batch),
                    total_chars,
                    max_chars,
                    time.perf_counter() - started_at,
                    self.timeout,
                    f"{self.base_url}/v1/embeddings",
                    type(exc).__name__,
                )
                raise
            logger.info(
                "[EMBEDDING][batch] 완료 batch=%s/%s texts=%s elapsed=%.2fs",
                batch_index,
                batch_count,
                len(batch),
                time.perf_counter() - started_at,
            )
            all_embeddings.extend(embeddings)

        return self._normalize(all_embeddings)

    # ── 쿼리 임베딩 (instruct 적용) ─────────────────────

    async def embed_query(self, query: str) -> List[float]:
        """
        검색 쿼리를 임베딩 벡터로 변환합니다.
        Qwen3-Embedding 권장 instruct prefix를 자동 적용합니다.
        """
        instructed = self.instruct_template.format(query=query)
        embeddings = await self._request_embeddings([instructed])
        return self._normalize(embeddings)[0]

    async def embed_queries(self, queries: List[str]) -> List[List[float]]:
        """복수 쿼리를 임베딩합니다 (instruct prefix 적용)."""
        instructed = [
            self.instruct_template.format(query=q) for q in queries
        ]
        return await self.embed_texts(instructed)

    # ── 헬스체크 ─────────────────────────────────────────

    async def health_check(self) -> bool:
        """vLLM Embedding 서버 상태 확인."""
        try:
            # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient 재사용
            resp = await get_shared_async_client().get(
                f"{self.base_url}/v1/models",
                headers=self._headers(),
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Embedding health check failed: {e}")
            return False
