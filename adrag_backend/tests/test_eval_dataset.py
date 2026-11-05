"""테스트셋 생성 로직(P4) 테스트 — 순수 함수(라이브 Qdrant/LLM 불필요).

prompts(자립성 필터·프롬프트) / sampler(층화·멀티홉) / generator(유형배분·인터리빙·
JSON 파싱·①축 자동 태깅) 검증.
"""


import pytest


def _chunk(doc, idx, text_len=250, section=None):
    return {
        "chunk_id": f"{doc}-{idx}", "document_id": doc, "chunk_index": idx,
        "text": "가" * text_len, "section_title": section or f"{doc}-sec{idx}",
        "header_path": [section] if section else [f"{doc}/sec{idx}"],
    }


# ── prompts ──────────────────────────────────────────────────────────────────

def test_deictic_filter_and_prompt():
    from app.evaluation.dataset.prompts import (
        has_deictic_reference, build_qa_generation_prompt,
    )
    assert has_deictic_reference("이 문서에서 안전기준은?") is True
    assert has_deictic_reference("본문의 기준은?") is True
    assert has_deictic_reference("작업발판 폭 기준은 얼마인가요?") is False

    p = build_qa_generation_prompt("multihop", "본문A", second_chunk_text="본문B", section_title="3장")
    assert "모든 항목에 빠짐없이" in p
    assert "불필요한 도입이나 반복 없이" in p
    assert "의미 단위의 문장으로 분리" in p
    assert "조건, 예외, 시점, 수치 또는 단위" in p
    assert "본문 1과 본문 2의 핵심 사실이 각각 포함" in p
    assert "본문A" in p and "본문B" in p and "[본문 1]" in p and "3장" in p
    p2 = build_qa_generation_prompt("factual", "단일본문")
    assert "단일본문" in p2 and "[본문 1]" not in p2


# ── 샘플러 ───────────────────────────────────────────────────────────────────

def test_sample_chunks_respects_limits():
    from app.evaluation.dataset.sampler import sample_chunks
    chunks = [_chunk("d1", i) for i in range(10)] + [_chunk("d2", i) for i in range(10)]
    chunks.append(_chunk("d1", 99, text_len=50))  # 짧은 청크 → 필터

    out = sample_chunks(chunks, target_count=6, max_per_doc=2, min_chunk_chars=200, seed=1)
    assert len(out) == 4  # 문서 2개 × 상한 2
    from collections import Counter
    per_doc = Counter(c["document_id"] for c in out)
    assert all(v <= 2 for v in per_doc.values())
    assert all(len(c["text"]) >= 200 for c in out)  # 짧은 청크 제외


def test_sample_chunks_is_reproducible_with_fixed_seed():
    from app.evaluation.dataset.sampler import sample_chunks
    chunks = [_chunk("d1", i) for i in range(10)] + [_chunk("d2", i) for i in range(10)]

    first = sample_chunks(chunks, target_count=6, max_per_doc=3, seed=42)
    second = sample_chunks(chunks, target_count=6, max_per_doc=3, seed=42)

    assert [c["chunk_id"] for c in first] == [c["chunk_id"] for c in second]


def test_sample_multihop_pairs_only_adjacent():
    from app.evaluation.dataset.sampler import sample_multihop_pairs
    chunks = [_chunk("d1", 0), _chunk("d1", 1), _chunk("d1", 5), _chunk("d2", 0)]
    pairs = sample_multihop_pairs(chunks, target_count=10, min_chunk_chars=200, seed=1)
    idx_pairs = {(a["chunk_index"], b["chunk_index"]) for a, b in pairs if a["document_id"] == "d1"}
    assert (0, 1) in idx_pairs       # 인접
    assert (1, 5) not in idx_pairs   # 비인접 제외


# ── 생성기 유형 배분/인터리빙/파싱 ───────────────────────────────────────────

def test_allocate_type_counts_sums_to_target():
    from app.evaluation.dataset.generator import _allocate_type_counts
    counts = _allocate_type_counts(30, {"factual": 5, "procedural": 3, "comparative": 1, "multihop": 1})
    assert sum(counts.values()) == 30
    assert counts["factual"] >= counts["procedural"] >= counts["comparative"]


def test_build_single_jobs_interleaves_and_reuses():
    from app.evaluation.dataset.generator import _build_single_jobs
    singles = [_chunk("d1", i) for i in range(3)]
    # 목표 6인데 고유 청크 3개 → 재사용으로 유형 채움
    jobs = _build_single_jobs(singles, {"factual": 4, "procedural": 2, "comparative": 0}, target_needed=6)
    assert len(jobs) == 6
    types = [t for t, _, _ in jobs]
    assert "factual" in types and "procedural" in types


def test_build_single_jobs_always_reaches_large_targets():
    from app.evaluation.dataset.generator import _build_single_jobs
    singles = [_chunk("d1", 0), _chunk("d2", 0)]
    type_counts = {"factual": 25, "procedural": 15, "comparative": 5}

    jobs_30 = _build_single_jobs(singles, type_counts, target_needed=30)
    jobs_50 = _build_single_jobs(singles, type_counts, target_needed=50)

    assert len(jobs_30) == 30
    assert len(jobs_50) == 50
    assert {job[1]["chunk_id"] for job in jobs_50} == {"d1-0", "d2-0"}


def test_parse_qa_json():
    from app.evaluation.dataset.generator import _parse_qa_json
    assert _parse_qa_json('앞 {"question": "작업발판 기준은?", "answer": "40cm 이상"} 뒤') == (
        "작업발판 기준은?", "40cm 이상"
    )
    assert _parse_qa_json('{"question": "짧", "answer": "짧"}') is None  # 5자 미만
    assert _parse_qa_json(
        '{"question": "안전管理 기준은 무엇인가요?", "answer": "관련 法令을 따릅니다."}'
    ) is None
    assert _parse_qa_json(
        '{"question": "확장 한자 \ud840\udc00가 포함됐나요?", "answer": "확장 문자가 포함된 답변입니다."}'
    ) is None
    assert _parse_qa_json("json 아님") is None


@pytest.mark.asyncio
async def test_call_llm_for_qa_retries_when_cjk_is_generated():
    from app.evaluation.dataset.generator import _call_llm_for_qa

    class FakeLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return '{"question":"안전管理 기준은 무엇입니까?","answer":"관련 法令을 따라야 합니다."}'
            return '{"question":"안전관리 기준은 무엇입니까?","answer":"관련 법령을 따라야 합니다."}'

    llm = FakeLLM()
    result = await _call_llm_for_qa(
        llm, "factual", {"text": "안전관리 기준 원문"}, None, "vllm"
    )

    assert result == ("안전관리 기준은 무엇입니까?", "관련 법령을 따라야 합니다.")
    assert llm.calls == 2


# ── ①축 자동 태깅 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_llm_for_qa_adds_undetected_regeneration_instruction():
    from app.evaluation.dataset.generator import _call_llm_for_qa

    class FakeLLM:
        def __init__(self):
            self.messages = None

        async def chat(self, messages, **kwargs):
            self.messages = messages
            return '{"question":"재생성된 안전관리 기준 질문은 무엇입니까?","answer":"재생성된 기준 답변입니다."}'

    llm = FakeLLM()
    result = await _call_llm_for_qa(
        llm,
        "factual",
        {"text": "안전관리 기준 원문", "section_title": "안전관리"},
        None,
        "vllm",
        previous_question="최초 검색 미검출 질문은 무엇입니까?",
    )

    assert result is not None
    prompt = llm.messages[1]["content"]
    assert "[재생성 지시]" in prompt
    assert "최초 검색 미검출 질문은 무엇입니까?" in prompt
    assert "상위 10개" in prompt


def test_auto_tags_korean_segments():
    from app.evaluation.dataset.generator import _auto_tags
    assert "legal_reference" in _auto_tags("제38조의2 안전조치 기준은?")
    assert "legal_reference" in _auto_tags("산업안전보건법 시행규칙 별표의 내용은?")
    assert "abbreviation" in _auto_tags("PSM 12대 요소는 무엇인가요?")
    assert "compound_term" in _auto_tags("위험성 평가 절차는?")  # 공백 제거 후 '위험성평가' 매칭
    assert _auto_tags("작업발판 폭은 얼마인가요?") == []


# ── 모듈 import (어댑터 wiring; langgraph 불필요) ─────────────────────────────

def test_dataset_modules_import():
    import app.evaluation.dataset.generator  # noqa: F401
    import app.evaluation.dataset.sampler  # noqa: F401
    import app.evaluation.dataset.validator  # noqa: F401
    import app.evaluation.adapters.chunk_store_adapter  # noqa: F401
