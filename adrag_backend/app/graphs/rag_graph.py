"""
RAG Query 파이프라인 그래프 빌더.

2026.05.04(sooyeon.choi) 수정 - route_strategy 노드 제거, 검색 전략을 항상 hybrid+BM42로 고정.
  - 기존 11개 노드 → 10개 노드
  - analyze_and_rewrite → build_metadata_filter 직결 (route_strategy 우회)
2026.05.20(sooyeon.choi) 수정 - guardrail 노드 추가.
  - 10개 노드 → 11개 노드
  - validate_input → guardrail → analyze_and_rewrite (rag_query 시)
  - validate_input → guardrail → build_response (차단 시)
2026.10.19 수정 - 사진 답변: collect_answer_images 노드 추가(12개).
  - assemble_context → collect_answer_images → generate_answer
"""

from functools import partial

from langgraph.graph import StateGraph, END

from app.graphs.state import PipelineState
from app.graphs.dependencies import GraphDependencies, default_graph_dependencies
from app.graphs.nodes import (
    validate_input,
    guardrail,
    analyze_and_rewrite,
    build_metadata_filter,
    retrieve,
    rerank,
    assemble_context,
    collect_answer_images,
    generate_answer,
    format_citations,
    fallback_handler,
    build_response,
)
from app.graphs.edges import (
    check_filter_error,
    check_validation,
    check_guardrail,
    # 2026.07.16(sooyeon.choi) 추가 - 검색 시스템 오류 즉시 종료 분기
    check_retrieval,
    check_relevance,
    check_generation,
    check_fallback_retry,
)


def build_rag_graph(deps: GraphDependencies | None = None):
    """11단계 RAG Query 파이프라인 그래프를 생성하고 컴파일하여 반환한다."""
    graph = StateGraph(PipelineState)
    deps = deps or default_graph_dependencies()

    # ── 11개 노드 등록 ──
    graph.add_node("validate_input", partial(validate_input, deps=deps))
    graph.add_node("guardrail", partial(guardrail, deps=deps))
    graph.add_node("analyze_and_rewrite", partial(analyze_and_rewrite, deps=deps))
    graph.add_node("build_metadata_filter", partial(build_metadata_filter, deps=deps))
    graph.add_node("retrieve", partial(retrieve, deps=deps))
    graph.add_node("rerank", partial(rerank, deps=deps))
    graph.add_node("assemble_context", partial(assemble_context, deps=deps))
    # 2026.10.19 추가 - 사진 답변
    graph.add_node("collect_answer_images", partial(collect_answer_images, deps=deps))
    graph.add_node("generate_answer", partial(generate_answer, deps=deps))
    graph.add_node("format_citations", partial(format_citations, deps=deps))
    graph.add_node("fallback_handler", partial(fallback_handler, deps=deps))
    graph.add_node("build_response", build_response)

    # ── 엔트리 포인트 ──
    graph.set_entry_point("validate_input")

    # ── 조건 분기: 입력 검증 결과 ──
    graph.add_conditional_edges("validate_input", check_validation, {
        "guardrail": "guardrail",
        "build_response": "build_response",
    })

    # ── 조건 분기: 가드레일 판별 결과 ──
    graph.add_conditional_edges("guardrail", check_guardrail, {
        "analyze_and_rewrite": "analyze_and_rewrite",
        "build_response": "build_response",
    })

    # ── 순차 엣지: analyze_and_rewrite → build_metadata_filter → ... → rerank ──
    graph.add_edge("analyze_and_rewrite", "build_metadata_filter")
    graph.add_conditional_edges("build_metadata_filter", check_filter_error, {
        "retrieve": "retrieve",
        "build_response": "build_response",
    })
    # 2026.07.16(sooyeon.choi) 수정 - retrieve 시스템 오류(타임아웃/컬렉션 오류/Qdrant 장애)는
    #   재시도 없이 즉시 종료 (B2). 기존 무조건 edge에서 조건 분기로 전환.
    graph.add_conditional_edges("retrieve", check_retrieval, {
        "rerank": "rerank",
        "build_response": "build_response",
    })

    # ── 조건 분기: 관련성 판단 ──
    graph.add_conditional_edges("rerank", partial(check_relevance, deps=deps), {
        "assemble_context": "assemble_context",
        "fallback_handler": "fallback_handler",
    })

    # ── 순차 엣지: assemble_context → collect_answer_images → generate_answer ──
    graph.add_edge("assemble_context", "collect_answer_images")
    graph.add_edge("collect_answer_images", "generate_answer")

    # ── 조건 분기: 답변 생성 결과 ──
    graph.add_conditional_edges("generate_answer", check_generation, {
        "format_citations": "format_citations",
        "fallback_handler": "fallback_handler",
    })

    # ── 순차 엣지: format_citations → build_response ──
    graph.add_edge("format_citations", "build_response")

    # ── 조건 분기: 폴백 재시도 ──
    # retrieve로 직행: fallback이 설정한 top_k/threshold/rewritten_queries를 보존하기 위해
    # analyze_and_rewrite를 우회한다.
    graph.add_conditional_edges("fallback_handler", partial(check_fallback_retry, deps=deps), {
        "retrieve": "retrieve",
        "generate_answer": "generate_answer",
        "build_response": "build_response",
    })

    # ── 종료: build_response → END ──
    graph.add_edge("build_response", END)

    return graph.compile()
