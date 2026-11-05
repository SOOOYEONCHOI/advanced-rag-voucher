"""
인용 포맷팅 노드.

LLM에 실제 전달된 context_chunks에서 Citation 객체 리스트를 생성하고,
답변 텍스트 내 [N] 참조 번호를 Citation 인덱스에 매핑한다.
답변에서 유효하게 참조된 Citation을 번호 순서대로 반환한다.
"""

import re
from typing import List

from app.core.config import get_settings
from app.graphs.dependencies import GraphDependencies
from app.graphs.images import public_images, validate_answer_images
from app.graphs.state import PipelineState
from app.graphs.utils import timed_node
from app.services.manual_display_service import ManualDisplayService
from app.utils.citation_parser import extract_citation_ids
from app.utils.log.log import LoggingLogger

# 임베딩용으로 제거된 법령 개정 마커의 각도 괄호를 citation 표시용으로 복원
# 예: "개정 2022. 8. 18." → "<개정 2022. 8. 18.>"
_REVISION_RESTORE_RE = re.compile(
    r"(?<!<)((?:전부개정|일부개정|타법개정|개정|신설|삭제|제정)\s+\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?)"
)


def _restore_revision_brackets(text: str) -> str:
    """임베딩용 clean 텍스트에서 법령 개정 마커 각도 괄호를 복원한다."""
    return _REVISION_RESTORE_RE.sub(r"<\1>", text)

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)


# 2026.04.08(sooyeon.choi) 추가 - chunk_text 내 쿼리 관련 문장 추출 (highlight_text 생성)
def extract_highlight_text(
    chunk_text: str,
    query: str,
    keywords: List[str] = None,
) -> str:
    """
    chunk_text에서 쿼리와 가장 관련성 높은 문장을 추출한다.

    - keywords(전처리 추출 명사)가 있으면 우선 사용, 없으면 query 단어 사용
    - 문장 단위로 분리 후 키워드 매칭 점수가 가장 높은 문장을 반환
    - 매칭 문장이 없으면 빈 문자열 반환 (프론트에서 하이라이트 미적용)
    """
    if not chunk_text:
        return ""

    # 검색 키워드 결정: 전처리 명사 우선, 없으면 쿼리 공백 분리
    search_terms = [k.lower() for k in (keywords or []) if len(k) >= 2]
    if not search_terms:
        search_terms = [w.lower() for w in query.split() if len(w) >= 2]
    if not search_terms:
        return ""

    # 문장 분리: 마침표·느낌표·물음표·줄바꿈 기준 (한국어 포함)
    sentences = re.split(r"(?<=[.!?。])\s+|\n+", chunk_text.strip())
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
    if not sentences:
        return ""

    # 문장별 키워드 매칭 점수 계산
    best_score = 0
    best_sentence = ""
    for sentence in sentences:
        sentence_lower = sentence.lower()
        score = sum(1 for term in search_terms if term in sentence_lower)
        if score > best_score:
            best_score = score
            best_sentence = sentence

    return best_sentence if best_score > 0 else ""


@timed_node("format_citations")
async def format_citations(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    """context_chunks에서 Citation 객체 리스트 생성, 답변 참조 번호 매핑."""
    answer = state.get("generated_answer", "")
    # 2026.07.10(sooyeon.choi) 수정 - LLM에 번호를 부여한 실제 컨텍스트 청크를 단일 매핑 기준으로 사용
    context_chunks = state.get("context_chunks", [])
    settings = deps.settings if deps else get_settings()
    citation_limit = state.get("citation_limit") or settings.max_citation_results
    manual_display_service = ManualDisplayService()

    # 2026.07.10(sooyeon.choi) 수정 - 공백 앞 인용을 허용하고 실제 context_chunks 범위로 검증
    raw_ids = set(extract_citation_ids(answer))
    valid_ids = set(range(1, len(context_chunks) + 1))
    out_of_range = raw_ids - valid_ids
    if out_of_range:
        logger.warning(
            "유효 범위(%s) 초과 인용 번호 제거: %s",
            len(context_chunks),
            sorted(out_of_range),
        )
    referenced_ids = raw_ids & valid_ids

    # 2026.04.08(sooyeon.choi) 추가 - highlight_text 생성을 위해 전처리 키워드 준비
    original_query: str = state.get("original_query", "")
    extracted_keywords: List[str] = state.get("preprocess_result", {}).get("extracted_keywords", [])

    # 2026.07.10(sooyeon.choi) 수정 - 답변의 유효 ID로 context_chunks를 직접 조회해 번호 불일치 방지
    citations: list[dict] = []
    for citation_id in sorted(referenced_ids):
        chunk = context_chunks[citation_id - 1]

        # 임베딩용 clean 텍스트 → citation 표시용으로 개정 마커 괄호 복원
        metadata = chunk["metadata"]
        # 2026.08.27(sooyeon.choi) 수정 - spreadsheet citation은 표시용 Markdown을 우선
        citation_text = (
            metadata.get("display_markdown")
            if metadata.get("document_type") == "spreadsheet"
            else None
        ) or chunk["text"]
        truncated_text = citation_text[:300]
        display_text = _restore_revision_brackets(truncated_text)
        original_filename = (
            metadata.get("original_filename")
            or metadata.get("filename")
            or metadata.get("title")
            or ""
        )
        citation = {
            "citation_id": citation_id,
            "chunk_id": chunk.get("chunk_id", ""),
            "document_id": chunk.get("document_id", ""),
            "original_filename": original_filename,
            "section_name": metadata.get("section_name", ""),
            "header_path": metadata.get("header_path", []),
            "page_number": metadata.get("page_number"),
            "chunk_text": display_text,
            "score": chunk["score"],
            "referenced_in_answer": True,
            # ── 신규 필드 (citation-display) ──
            "title": metadata.get("title") or original_filename,
            "document_type": metadata.get("document_type"),
            "sheet_name": metadata.get("sheet_name"),
            "source_range": metadata.get("source_range"),
            "display_markdown": metadata.get("display_markdown"),
            "resource_ids": metadata.get("resource_ids") or [],
            # 2026.04.08(sooyeon.choi) 추가 - 쿼리 관련 하이라이트 문장
            "highlight_text": extract_highlight_text(
                chunk_text=display_text,
                query=original_query,
                keywords=extracted_keywords,
            ),
        }
        # 2026.07.10(sooyeon.choi) 추가 - 매핑되는 매뉴얼 citation은 표시용 원본 PDF 기준 페이지를 함께 제공
        if citation.get("document_type") == "manual" and citation.get("page_number") is not None:
            manual_display = manual_display_service.resolve(
                original_filename,
                citation.get("page_number"),
            )
            if manual_display.get("mapped"):
                citation.update({
                    "manual_display_mapped": True,
                    "display_filename": manual_display.get("display_filename"),
                    "display_page_number": manual_display.get("display_page"),
                })

        citations.append(citation)

    # 2026.07.10(sooyeon.choi) 수정 - 생성 후 유효 Citation을 score/limit로 삭제하지 않고 정합성만 진단
    if len(citations) > citation_limit:
        logger.error(
            "citation_limit 초과 유효 인용 발생: count=%s limit=%s",
            len(citations),
            citation_limit,
        )

    returned_ids = {int(c["citation_id"]) for c in citations}
    missing_ids = referenced_ids - returned_ids
    if missing_ids:
        logger.error(
            "유효한 본문 인용에 대응하는 Citation 생성 실패: %s",
            sorted(missing_ids),
        )

    # logger.info(
    #     f"인용 포맷팅 완료: 전체 컨텍스트 {len(context_chunks)}개 중 "
    #     f"{len(citations)}개 Citation 생성 ({len(referenced_ids)}개 답변 인용)"
    # )
    # 2026.10.19 추가 - 사진 답변: [IMG:ref] 인용을 후보 기준으로 검증(후보 밖 태그 제거, 최대 rag_max_images)
    #   후보가 없거나 기능이 꺼져 있어도 검증은 돌려 LLM이 지어낸 태그를 지운다. 근거 없음 답변에는 자동 첨부하지 않는다.
    images_enabled = getattr(settings, "answer_images_enabled", False)
    cleaned_answer, images = validate_answer_images(
        answer,
        (state.get("image_candidates") or []) if images_enabled else [],
        context_chunks=context_chunks,
        max_images=getattr(settings, "rag_max_images", 4),
        auto_step_image=(
            images_enabled
            and getattr(settings, "answer_image_auto_attach", True)
            and state.get("outcome_code") == "success"
        ),
    )
    result = {"citations": citations, "answer_images": public_images(images)}
    if cleaned_answer != answer:
        result["generated_answer"] = cleaned_answer
    return result
