"""
시맨틱 메타데이터 추출기 (Phase 3, v2).

vLLM에 연결된 LLM을 사용하여 청크 텍스트에서
keywords, entities, summary, topics, intent를 추출한다.
JSON Schema의 entity/numericValue 구조에 맞춤.
"""

import json
from typing import Any, Dict, List

# 2026.07.16(sooyeon.choi) 수정 - httpx 직접 사용 제거, 공유 클라이언트로 전환
from .metadata_schema import SemanticMeta


SEMANTIC_EXTRACTION_PROMPT = """당신은 산업안전보건 분야 문서 분석 전문가입니다.
주어진 텍스트를 분석하여 아래 JSON 스키마에 맞는 메타데이터를 추출하세요.

## 추출 스키마

| 필드 | 타입 | 규칙 |
|------|------|------|
| summary | string | 핵심 내용을 1~2문장으로 요약. 한국어, 100자 이내. 원문의 핵심 의미를 보존할 것 |
| keywords | string[] | 검색에 유용한 핵심 키워드. 최대 10개. 구체적 용어 우선 (예: "안전관리자" > "안전") |
| topics | string[] | 텍스트의 핵심 주제 1개. 구체적이고 검색에 유용한 한국어 명사구로 작성 |
| intent | string | 텍스트의 목적. regulation/guidance/case/faq/report 중 하나 |
| section_title | string/null | 텍스트가 속한 섹션/장의 제목. 원문에 명시된 경우만 추출. 없으면 null |

## intent 판단 기준
- regulation: 법 조문, 시행령, 시행규칙, 의무/벌칙 규정
- guidance: 해설, 가이드라인, 매뉴얼, 지침, 안내서
- case: 사고 사례, 판례, 재해 조사 결과
- faq: 질의응답, FAQ
- report: 통계, 보고서, 현황 분석

## Few-shot 예시

### 입력 1:
"제4조(사업주와 경영책임자등의 안전 및 보건 확보의무) ① 사업주 또는 경영책임자등은 사업주나 법인 또는 기관이 실질적으로 지배·운영·관리하는 사업 또는 사업장에서 종사자의 안전·보건상 유해 또는 위험을 방지하기 위하여 그 사업 또는 사업장의 특성 및 규모 등을 고려하여 다음 각 호에 해당하는 안전보건관리체계의 구축 및 그 이행에 관한 조치를 하여야 한다."

### 출력 1:
{"summary":"사업주 또는 경영책임자가 종사자의 안전·보건을 위해 안전보건관리체계를 구축하고 이행할 의무를 규정","keywords":["경영책임자","안전보건관리체계","안전확보의무","종사자","유해위험방지"],"topics":["안전보건관리체계 구축의무"],"intent":"regulation","section_title":"제4조(사업주와 경영책임자등의 안전 및 보건 확보의무)"}

### 입력 2:
"태안화력발전소 압사사고: 2018.12.10.(월) 00발전기술(주) 소속 망 김00이 야간 업무에 투입되어 작업 중 컨베이어에서 끼여 사망함."

### 출력 2:
{"summary":"태안화력발전소에서 하청 근로자가 컨베이어에 끼여 사망한 산업재해 사례","keywords":["태안화력발전소","압사사고","컨베이어","하청근로자","사망재해"],"topics":["컨베이어 끼임 사망재해"],"intent":"case","section_title":"태안화력발전소 압사사고"}

## 출력 규칙
- 반드시 JSON만 출력. 설명이나 마크다운 없이 순수 JSON만 응답
- 원문에 없는 정보를 추측하지 말 것
- entities의 text는 원문 그대로 표기 (의역 금지)"""


VALID_INTENTS = {"regulation", "guidance", "case", "faq", "report"}


def _parse_llm_response(raw_text: str) -> Dict[str, Any]:
    """LLM 응답에서 JSON을 파싱한다."""
    if "</think>" in raw_text:
        raw_text = raw_text.split("</think>", 1)[1]
    text = raw_text.strip()
    if "```" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


class SemanticEnricher:
    """vLLM 기반 시맨틱 메타데이터 추출기."""

    def __init__(
        self,
        vllm_api_url: str = "http://vllm-llm:8000",
        model_name: str = "Qwen/Qwen3.5-9B",
        api_key: str = "EMPTY",
        timeout: float = 120.0,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ):
        self.vllm_api_url = vllm_api_url.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }


    async def extract_semantic(self, text: str) -> SemanticMeta:
        """단일 텍스트에서 시맨틱 메타데이터를 추출한다."""
        # LLM 기반 추출
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": SEMANTIC_EXTRACTION_PROMPT},
                {"role": "user", "content": text[:3000]},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "stop": ["</think>", "Thinking Process:"],
        }

        try:
            # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient + 요청 단위 타임아웃
            from app.core.http import get_shared_async_client
            resp = await get_shared_async_client().post(
                f"{self.vllm_api_url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            raw_content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            parsed = _parse_llm_response(raw_content)

            intent = parsed.get("intent")
            if intent not in VALID_INTENTS:
                intent = None

            # section_title 파싱 (빈 문자열이면 None)
            raw_section_title = parsed.get("section_title")
            section_title = raw_section_title.strip() if isinstance(raw_section_title, str) and raw_section_title.strip() else None

            return SemanticMeta(
                summary=(parsed.get("summary") or "")[:200],
                keywords=parsed.get("keywords", [])[:10],
                topics=parsed.get("topics", [])[:1] or None,
                intent=intent,
                section_title=section_title,
            )

        except Exception:
            return SemanticMeta()

    async def extract_batch(
        self, texts: List[str], *, max_concurrent: int = 5
    ) -> List[SemanticMeta]:
        """여러 텍스트를 배치로 처리한다."""
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _limited(t: str) -> SemanticMeta:
            async with semaphore:
                return await self.extract_semantic(t)

        return await asyncio.gather(*[_limited(t) for t in texts])
