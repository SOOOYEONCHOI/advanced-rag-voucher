"""
BGE Reranker v2 M3 클라이언트 (vLLM /v1/score API 기반).

# 2026.04.21(sooyeon.choi) 수정 - FlagEmbedding 로컬 추론 → vLLM /v1/score HTTP API 방식으로 전환
vLLM score 엔드포인트를 통해 query-document 쌍의
관련성 점수를 계산하고 재순위화합니다.
"""

import math
from typing import Any, List, Optional, Tuple

from app.core.config import Settings
# 2026.07.16(sooyeon.choi) 수정 - 요청마다 AsyncClient 생성 → 공유 클라이언트 재사용
from app.core.http import get_shared_async_client
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)


class RerankerResponseError(RuntimeError):
    """vLLM score 응답 형식 또는 내용이 요청과 일치하지 않을 때 발생한다."""


# 2026.11.19(sooyeon.choi) 수정 - Qwen3-Reranker 공식 입력 형식(모델 학습 형식, 원문 그대로 유지)
_QWEN3_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query "
    'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
    "<|im_start|>user\n"
)
_QWEN3_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def format_rerank_inputs(
    prompt_format: str, instruction: str, query: str, documents: List[str]
) -> Tuple[str, List[str]]:
    """2026.11.19(sooyeon.choi) 수정 - 설정한 형식으로 (질의, 문서 목록)을 만든다. plain은 그대로."""
    if prompt_format != "qwen3":
        return query, documents
    return (
        f"{_QWEN3_PREFIX}<Instruct>: {instruction}\n<Query>: {query}\n",
        [f"<Document>: {document}{_QWEN3_SUFFIX}" for document in documents],
    )


class RerankerClient:
    """vLLM /v1/score 기반 Reranker 클라이언트."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # 2026.11.24(sooyeon.choi) 추가 - AI+ 시험 소스 코드 확인 위치
        # [AI+ 시험] NDCG@5 - 2) 임베딩 모델 및 Reranker 모델을 불러오는 코드 (⑥ Reranker 모델 이름·GPU 서버 주소·시간 제한·출력 개수 설정)
        self.top_k = settings.reranker_top_k
        # 2026.04.21(sooyeon.choi) 수정 - 로컬 모델 로드 제거, vLLM API URL/모델명 사용
        self.api_url = settings.reranker_api_url.rstrip("/")
        self.api_key = settings.reranker_api_key
        self.model_name = settings.reranker_model_name
        self.timeout = settings.reranker_timeout
        # 2026.07.07(sooyeon.choi) 수정 - 모델 입력 한도 초과 시 vLLM 기본 truncation 사용
        self.truncate_prompt_tokens = settings.reranker_truncate_prompt_tokens
        # 2026.11.19(sooyeon.choi) 수정 - 입력 형식(plain 기본 / qwen3), 설정이 없는 가짜 설정은 plain
        self.prompt_format = getattr(settings, "reranker_prompt_format", "plain")
        self.instruction = getattr(settings, "reranker_instruction", "")

    # ── 재순위화 ─────────────────────────────────────────

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None,
    ) -> List[Tuple[int, float]]:
        """
        query와 documents 쌍의 관련성 점수를 계산하고 상위 top_k개를 반환합니다.

        Returns:
            [(원본_인덱스, 점수), ...] — 점수 내림차순 정렬
        """
        # 2026.07.07(sooyeon.choi) 수정 - top_k=0을 기본값으로 오인하지 않도록 None만 fallback
        # 2026.07.07(sooyeon.choi) 수정 - doc 텍스트를 반환값에서 제거 (_call_score_api 검증으로 충분)
        k = self.top_k if top_k is None else top_k

        if not documents:
            return []

        # 2026.11.24(sooyeon.choi) 추가 - AI+ 시험 소스 코드 확인 위치
        # [AI+ 시험] NDCG@5 - 4) 하이브리드 검색 결과를 Reranker 모델에 입력하여 질의와 문서 청크 간 관련도를 평가하고 검색 결과를 재정렬하는 코드 (⑤ 질의–청크 관련도 점수 계산 후 점수 순 정렬, 상위 개수 반환)
        scores = await self._call_score_api(query, documents)

        scored = list(enumerate(scores))
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored[:k]

    # ── 내부 HTTP 호출 ────────────────────────────────────

    # 2026.04.21(sooyeon.choi) 수정 - vLLM /v1/score 엔드포인트 호출 메서드 추가
    # 2026.11.24(sooyeon.choi) 추가 - AI+ 시험 소스 코드 확인 위치
    # [AI+ 시험] NDCG@5 - 4) 하이브리드 검색 결과를 Reranker 모델에 입력하여 질의와 문서 청크 간 관련도를 평가하고 검색 결과를 재정렬하는 코드 (⑥ GPU 서버 Reranker 모델(vLLM /v1/score) 점수 요청)
    async def _call_score_api(
        self,
        query: str,
        documents: List[str],
    ) -> List[float]:
        """vLLM /v1/score 엔드포인트 호출."""
        # 2026.11.19(sooyeon.choi) 수정 - 입력 형식 적용(문서 개수·순서는 그대로라 응답 index 검증은 동일)
        text_1, text_2 = format_rerank_inputs(self.prompt_format, self.instruction, query, documents)
        payload = {
            "model": self.model_name,
            "text_1": text_1,
            "text_2": text_2,
            # 2026.07.07(sooyeon.choi) 수정 - CE threshold가 항상 활성화 점수 기준이 되도록 고정
            "use_activation": True,
            "truncate_prompt_tokens": self.truncate_prompt_tokens,
        }

        headers = {"Authorization": f"Bearer {self.api_key}"}
        # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient + 요청 단위 타임아웃
        client = get_shared_async_client()
        response = await client.post(
            f"{self.api_url}/v1/score",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        # 2026.07.07(sooyeon.choi) 수정 - 응답 index/개수/점수 유효성을 검증해 오매핑 방지
        try:
            data = response.json()
            items: List[dict[str, Any]] = data["data"]
            if not isinstance(items, list):
                raise TypeError("data가 list가 아닙니다.")

            indexed_scores: dict[int, float] = {}
            for item in items:
                index = int(item["index"])
                score = float(item["score"])
                if index in indexed_scores:
                    raise ValueError(f"중복 index: {index}")
                if index < 0 or index >= len(documents):
                    raise ValueError(f"범위를 벗어난 index: {index}")
                if not math.isfinite(score):
                    raise ValueError(f"유효하지 않은 score: {score}")
                indexed_scores[index] = score

            expected_indexes = set(range(len(documents)))
            if set(indexed_scores) != expected_indexes:
                missing = sorted(expected_indexes - set(indexed_scores))
                raise ValueError(f"누락 index: {missing}")
            return [indexed_scores[index] for index in range(len(documents))]
        except (KeyError, TypeError, ValueError) as e:
            raise RerankerResponseError(f"vLLM score 응답 검증 실패: {e}") from e
