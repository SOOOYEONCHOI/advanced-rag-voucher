from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.graphs.nodes.assemble_context import (
    _CONTEXT_TOKEN_SAFETY_MARGIN,
    _prompt_tokens,
    assemble_context,
)
from app.graphs.nodes.format_citations import format_citations
from app.utils.citation_parser import extract_citation_ids


# 2026.07.10(sooyeon.choi) 수정 - 공백 인용 허용과 줄 시작 번호 목록 제외 규칙 회귀 검증
@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("내용입니다[1].", [1]),
        ("내용입니다 [1].", [1]),
        ("내용입니다\t[1].", [1]),
        ("내용입니다 [1][2].", [1, 2]),
        ("내용입니다 [1] [2].", [1, 2]),
        ("첫 문장 [1]. 둘째 문장 [1].", [1, 1]),
        ("[1] 첫 번째 항목", []),
        ("  [2] 두 번째 항목", []),
        ("- [3] 세 번째 항목", []),
        ("[1] 항목\n설명입니다 [2].", [2]),
    ],
)
def test_extract_citation_ids(answer, expected):
    assert extract_citation_ids(answer) == expected


def _chunk(chunk_id, document_id, text, score):
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "text": text,
        "score": score,
        "metadata": {
            "filename": f"{document_id}.pdf",
            "section_name": "기준",
            "header_path": [],
            "page_number": 1,
        },
    }


@pytest.mark.asyncio
async def test_assemble_context_returns_only_numbered_context_chunks():
    # 2026.07.10(sooyeon.choi) 수정 - 중복 제거 후 final_context 번호와 context_chunks 순서가 같은지 검증
    first = _chunk("chunk-a", "doc-a", "첫 번째 실제 컨텍스트", 0.9)
    duplicate = _chunk("chunk-a-copy", "doc-copy", "첫 번째 실제 컨텍스트", 0.8)
    second = _chunk("chunk-b", "doc-b", "두 번째 실제 컨텍스트", 0.7)
    state = {
        "reranked_chunks": [first, duplicate, second],
        "citation_limit": 3,
        "relevance_threshold": 0.1,
        "timing": {},
    }
    settings = SimpleNamespace(
        max_context_chars=10_000,
        relevance_threshold=0.1,
        context_max_chunks_per_document=2,
    )

    with (
        patch(
            "app.graphs.nodes.assemble_context.get_settings",
            return_value=settings,
        ),
        patch(
            "app.graphs.nodes.assemble_context.get_retrieval_config",
            return_value=SimpleNamespace(context_top_k=3),
        ),
        # 2026.07.10(sooyeon.choi) 수정 - 진단 로그 설정도 테스트 환경 값으로 고정
        patch(
            "app.graphs.utils.get_settings",
            return_value=SimpleNamespace(rag_diagnostic_log=False),
        ),
    ):
        result = await assemble_context(state)

    assert result["context_chunk_count"] == 2
    assert result["context_chunks"] == [first, second]
    assert "[1]" in result["final_context"]
    assert "[2]" in result["final_context"]


@pytest.mark.asyncio
async def test_assemble_context_respects_full_prompt_token_budget():
    first = _chunk("chunk-a", "doc-a", "안전 " * 100, 0.9)
    second = _chunk("chunk-b", "doc-b", "관리 " * 100, 0.8)
    question = "안전 기준을 알려줘"
    first_context = f"[1] [doc-a.pdf] 기준\n{first['text']}"
    first_prompt_tokens = _prompt_tokens(question, first_context, 1)
    settings = SimpleNamespace(
        max_context_chars=10_000,
        relevance_threshold=0.1,
        context_max_chunks_per_document=2,
        vllm_max_model_len=first_prompt_tokens + _CONTEXT_TOKEN_SAFETY_MARGIN + 100,
        vllm_max_tokens=100,
    )
    state = {
        "original_query": question,
        "reranked_chunks": [first, second],
        "citation_limit": 2,
        "relevance_threshold": 0.1,
        "timing": {},
    }

    with (
        patch("app.graphs.nodes.assemble_context.get_settings", return_value=settings),
        patch(
            "app.graphs.nodes.assemble_context.get_retrieval_config",
            return_value=SimpleNamespace(context_top_k=2),
        ),
        patch(
            "app.graphs.utils.get_settings",
            return_value=SimpleNamespace(rag_diagnostic_log=False),
        ),
    ):
        result = await assemble_context(state)

    assert result["context_chunks"] == [first]
    assert second["text"] not in result["final_context"]


@pytest.mark.asyncio
@pytest.mark.parametrize("budget_kind", ["characters", "tokens"])
async def test_assemble_context_skips_oversized_spreadsheet_and_keeps_citation_mapping(budget_kind):
    oversized = _chunk("large", "doc-a", "Process Fan 1400 RPM", 0.99)
    oversized["metadata"].update({
        "document_type": "spreadsheet",
        "display_markdown": "| Process Fan | 1400 RPM |\n" * 1000,
    })
    smaller = _chunk("small", "doc-a", "Process Fan 1400 RPM test", 0.9)
    settings = SimpleNamespace(
        max_context_chars=500 if budget_kind == "characters" else 100_000,
        relevance_threshold=0.25,
        context_max_chunks_per_document=2,
        vllm_max_model_len=8192,
        vllm_max_tokens=2048,
    )
    with (
        patch("app.graphs.nodes.assemble_context.get_settings", return_value=settings),
        patch("app.graphs.nodes.assemble_context.get_retrieval_config",
              return_value=SimpleNamespace(context_top_k=2)),
        patch("app.graphs.utils.get_settings",
              return_value=SimpleNamespace(rag_diagnostic_log=False)),
    ):
        result = await assemble_context({
            "original_query": "Process Fan 1400 RPM",
            "reranked_chunks": [oversized, smaller],
            "timing": {},
        })

    assert result["context_chunks"] == [smaller]
    assert result["context_chunk_count"] == 1
    assert result["final_context"].startswith("[1] ")
    assert smaller["text"] in result["final_context"]
    assert "[2]" not in result["final_context"]
    assert len(result["final_context"]) <= settings.max_context_chars
    assert _prompt_tokens("Process Fan 1400 RPM", result["final_context"], 1) <= (
        settings.vllm_max_model_len - settings.vllm_max_tokens - _CONTEXT_TOKEN_SAFETY_MARGIN
    )


@pytest.mark.asyncio
async def test_format_citations_uses_context_chunk_numbering():
    # 2026.07.10(sooyeon.choi) 수정 - reranked 중간 청크가 제외돼도 [2]가 실제 두 번째 컨텍스트를 가리키는지 검증
    removed_chunk = _chunk("removed", "removed-doc", "제외된 중복 청크", 0.99)
    first_context = _chunk("chunk-a", "doc-a", "첫 번째 실제 컨텍스트", 0.8)
    second_context = _chunk("chunk-b", "doc-b", "두 번째 실제 컨텍스트", 0.7)
    state = {
        "generated_answer": "두 번째 문서의 내용입니다 [2].",
        "reranked_chunks": [first_context, removed_chunk, second_context],
        "context_chunks": [first_context, second_context],
        "context_chunk_count": 2,
        "citation_limit": 2,
        "original_query": "두 번째 문서",
        "preprocess_result": {"extracted_keywords": ["두 번째"]},
        "timing": {},
    }

    with (
        patch(
            "app.graphs.nodes.format_citations.get_settings",
            return_value=SimpleNamespace(max_citation_results=2),
        ),
        patch("app.graphs.nodes.format_citations.ManualDisplayService"),
    ):
        result = await format_citations(state)

    assert [c["citation_id"] for c in result["citations"]] == [2]
    assert result["citations"][0]["chunk_id"] == "chunk-b"
    assert result["citations"][0]["document_id"] == "doc-b"


@pytest.mark.asyncio
async def test_format_citations_keeps_all_valid_references_in_id_order():
    # 2026.07.10(sooyeon.choi) 수정 - score 정렬/후처리 제한 없이 본문이 사용한 유효 ID를 보존하는지 검증
    context_chunks = [
        _chunk("chunk-a", "doc-a", "첫 번째", 0.1),
        _chunk("chunk-b", "doc-b", "두 번째", 0.9),
        _chunk("chunk-c", "doc-c", "세 번째", 0.5),
    ]
    state = {
        "generated_answer": "근거입니다 [3]. 추가 근거입니다 [1]. 범위 밖 [99].",
        "context_chunks": context_chunks,
        "context_chunk_count": 3,
        "citation_limit": 3,
        "original_query": "근거",
        "preprocess_result": {},
        "timing": {},
    }

    with (
        patch(
            "app.graphs.nodes.format_citations.get_settings",
            return_value=SimpleNamespace(max_citation_results=3),
        ),
        patch("app.graphs.nodes.format_citations.ManualDisplayService"),
    ):
        result = await format_citations(state)

    assert [c["citation_id"] for c in result["citations"]] == [1, 3]
    assert [c["chunk_id"] for c in result["citations"]] == ["chunk-a", "chunk-c"]
    assert [c["document_id"] for c in result["citations"]] == ["doc-a", "doc-c"]


# 2026.08.20(sooyeon.choi) 수정 - Excel Markdown과 시트·셀 위치가 컨텍스트/인용에 유지되는지 검증
@pytest.mark.asyncio
async def test_spreadsheet_context_and_citation_use_display_markdown():
    chunk = _chunk("excel-chunk", "excel-doc", "품명: 모터\n수량: 2", 0.9)
    chunk["metadata"].update({
        "filename": "parts.xlsx",
        "document_type": "spreadsheet",
        "display_markdown": "| 품명 | 수량 |\n| --- | --- |\n| 모터 | 2 |",
        "sheet_name": "부품",
        "source_range": "A2:B2",
        "resource_ids": ["resource-1"],
    })
    state = {
        "reranked_chunks": [chunk],
        "citation_limit": 1,
        "relevance_threshold": 0.1,
        "timing": {},
    }
    settings = SimpleNamespace(
        max_context_chars=10_000,
        relevance_threshold=0.1,
        context_max_chunks_per_document=2,
        max_citation_results=1,
    )

    with (
        patch("app.graphs.nodes.assemble_context.get_settings", return_value=settings),
        patch(
            "app.graphs.nodes.assemble_context.get_retrieval_config",
            return_value=SimpleNamespace(context_top_k=1),
        ),
        patch(
            "app.graphs.utils.get_settings",
            return_value=SimpleNamespace(rag_diagnostic_log=False),
        ),
    ):
        context_result = await assemble_context(state)

    assert "[parts.xlsx] 부품 A2:B2" in context_result["final_context"]
    assert "| 품명 | 수량 |" in context_result["final_context"]
    assert "품명: 모터" not in context_result["final_context"]

    citation_state = {
        "generated_answer": "모터 수량은 2입니다 [1].",
        "context_chunks": [chunk],
        "context_chunk_count": 1,
        "citation_limit": 1,
        "original_query": "모터 수량",
        "preprocess_result": {},
        "timing": {},
    }
    with (
        patch("app.graphs.nodes.format_citations.get_settings", return_value=settings),
        patch("app.graphs.nodes.format_citations.ManualDisplayService"),
    ):
        citation_result = await format_citations(citation_state)

    citation = citation_result["citations"][0]
    assert citation["chunk_text"].startswith("| 품명 | 수량 |")
    assert citation["document_type"] == "spreadsheet"
    assert citation["original_filename"] == "parts.xlsx"
    assert citation["sheet_name"] == "부품"
    assert citation["source_range"] == "A2:B2"
    assert citation["display_markdown"].startswith("| 품명 | 수량 |")
    assert citation["resource_ids"] == ["resource-1"]
