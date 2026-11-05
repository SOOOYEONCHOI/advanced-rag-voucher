"""
Golden 데이터셋 후보 생성기.

Qdrant 컬렉션에서 청크를 샘플링한 뒤 Ollama(qwen3:14b)로
후보 QA 쌍을 생성한다.

출력 파일은 사람이 검수하기 위한 후보(candidates)이며,
검수 전까지 Golden 데이터셋으로 사용하면 안 된다.

특히 산업안전·법령 문서는 원문에 실제로 존재하는지 여부가
평가 신뢰성의 전제이므로, LLM 생성 후 반드시 사람이 확인해야 한다.
"""

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import httpx
from qdrant_client import QdrantClient

from app.core.config import get_settings
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# ── 생성 프롬프트 ─────────────────────────────────────────────
_GENERATE_PROMPT = """\
아래 [문서 청크]를 읽고, 이 청크만으로 답변 가능한 질문-답변 쌍을 {n}개 만들어라.

규칙:
- 질문은 실제 사용자가 할 법한 자연스러운 한국어 질문이어야 한다.
- 답변은 청크에 실제로 있는 내용만 사용한다. 추측하거나 보완하지 않는다.
- question_type: factual(단일 사실), procedural(절차·순서), comparative(비교·대조) 중 선택
- difficulty: easy(키워드 직접 포함), normal(약어·동의어 변형), hard(여러 문장 조합 필요) 중 선택

[문서 청크]
{chunk_text}

아래 JSON 배열 형식으로만 출력한다. 다른 텍스트는 절대 출력하지 않는다.
[
  {{
    "question": "질문",
    "expected_answer": "청크 기반 답변",
    "question_type": "factual|procedural|comparative",
    "difficulty": "easy|normal|hard"
  }}
]"""


class GoldenDatasetGenerator:
    """Qdrant 청크 → Ollama LLM 후보 QA 생성기."""

    def __init__(
        self,
        ollama_url: str = "http://49.247.45.119:11434",
        model: str = "qwen3:14b",
        timeout: float = 120.0,
    ):
        settings = get_settings()
        self._qdrant = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
        self._ollama_url = f"{ollama_url.rstrip('/')}/v1/chat/completions"
        self._model = model
        self._timeout = timeout

    async def generate_for_collection(
        self,
        collection_name: str,
        sample_size: int = 50,
        n_per_chunk: int = 2,
        output_dir: str = "offline_evaluation/data/candidates",
        seed: int = 42,
    ) -> str:
        """컬렉션에서 청크를 샘플링해 후보 QA를 생성하고 JSON 파일로 저장한다.

        Returns:
            저장된 파일 경로
        """
        logger.info(f"[generator] {collection_name} 청크 샘플링 시작 (n={sample_size})")
        chunks = self._sample_chunks(collection_name, sample_size, seed)
        logger.info(f"[generator] {len(chunks)}개 청크 샘플링 완료")

        candidates = []
        for i, chunk in enumerate(chunks):
            logger.info(f"[generator] 청크 {i+1}/{len(chunks)} QA 생성 중...")
            qa_list = await self._generate_qa(chunk, n_per_chunk)
            for qa in qa_list:
                candidates.append(self._build_record(chunk, qa, collection_name))

        path = self._save(candidates, collection_name, output_dir)
        logger.info(f"[generator] 후보 {len(candidates)}건 저장 완료: {path}")
        return path

    # ── 내부 헬퍼 ────────────────────────────────────────────

    def _sample_chunks(
        self, collection_name: str, n: int, seed: int
    ) -> List[Dict[str, Any]]:
        """Qdrant scroll로 최대 n개 청크를 랜덤 샘플링한다."""
        points, _ = self._qdrant.scroll(
            collection_name=collection_name,
            limit=min(n * 5, 500),  # 충분히 가져온 뒤 랜덤 추출
            with_payload=True,
            with_vectors=False,
        )
        rng = random.Random(seed)
        sampled = rng.sample(points, min(n, len(points)))

        result = []
        for p in sampled:
            payload = p.payload or {}
            meta = payload.get("metadata") or {}
            result.append({
                "chunk_id": payload.get("chunk_id", str(p.id)),
                "document_id": payload.get("document_id", ""),
                "text": payload.get("text", ""),
                "filename": meta.get("filename", ""),
                "page_number": meta.get("page_number"),
                "section_name": meta.get("section_name", ""),
                "header_path": meta.get("header_path", []),
            })

        # 텍스트가 너무 짧은 청크 제외 (50자 미만)
        return [c for c in result if len(c["text"]) >= 50]

    async def _generate_qa(
        self, chunk: Dict[str, Any], n: int
    ) -> List[Dict[str, str]]:
        """청크 1건에서 QA 후보 n개를 생성한다. 실패 시 빈 리스트 반환."""
        prompt = _GENERATE_PROMPT.format(
            chunk_text=chunk["text"][:2000],
            n=n,
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.7,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._ollama_url, json=payload)
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning(f"[generator] Ollama 호출 실패 (chunk={chunk['chunk_id']}): {exc}")
            return []

        text, _ = LLMService.strip_thinking(raw)
        return self._parse_json_list(text.strip())

    @staticmethod
    def _parse_json_list(text: str) -> List[Dict]:
        """LLM 출력에서 JSON 배열을 추출한다."""
        # 코드 블록 제거
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [
                    d for d in data
                    if isinstance(d, dict)
                    and d.get("question")
                    and d.get("expected_answer")
                ]
        except json.JSONDecodeError:
            pass
        logger.warning(f"[generator] JSON 파싱 실패: {text[:100]!r}")
        return []

    @staticmethod
    def _build_record(
        chunk: Dict, qa: Dict, collection_name: str
    ) -> Dict:
        """청크 + QA → GoldenRecord 후보 딕셔너리 구성."""
        return {
            # id는 검수 후 확정 — 임시 식별자
            "id": f"cand_{chunk['chunk_id'][:8]}_{random.randint(1000, 9999)}",
            "collection_name": collection_name,
            "user_id": "eval_user",
            "question": qa["question"],
            "expected_answer": qa["expected_answer"],
            "expected_evidence": [
                {
                    "document_id": chunk["document_id"],
                    "chunk_id": chunk["chunk_id"],
                    "filename": chunk["filename"],
                    "page_number": chunk["page_number"],
                    # evidence_text는 원문 그대로 — LLM 생성 금지
                    "evidence_text": chunk["text"][:500],
                }
            ],
            "expected_behavior": "answer",
            "question_type": qa.get("question_type", "factual"),
            "difficulty": qa.get("difficulty", "normal"),
            "split": "tune",  # 기본값 tune — 검수 시 test로 변경
            "tags": ["generated"],  # 사람 검수 전 표시
            "notes": "LLM 생성 후보 — 검수 필요",
        }

    @staticmethod
    def _save(candidates: List[Dict], collection_name: str, output_dir: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"candidates_{collection_name}_{ts}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(candidates, f, ensure_ascii=False, indent=2)
        return str(path)
