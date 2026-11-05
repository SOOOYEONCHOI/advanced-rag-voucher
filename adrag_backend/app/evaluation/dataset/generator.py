"""테스트셋 QA 자동 생성 파이프라인.

흐름: 청크 샘플링 → 유형별 LLM QA 생성 (JSON 강제) → 자립성 필터
      → self-validation (검색 rank 기록) → ①축 한국어 세그먼트 자동 태깅 → DB 저장

라우터에서 start_generation()으로 백그라운드 실행된다.
(reference app/evaluation/dataset/generator.py 이식 + import 경로 적응 + ①축 자동 태깅)
"""

import asyncio
import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from app.evaluation.adapters.chunk_store_adapter import EvalChunkStore
from app.evaluation.adapters.llm_adapter import EvalLLM
from app.evaluation.adapters.retrieval_adapter import EvalRetriever
from app.evaluation.dataset.prompts import (
    SYSTEM_PROMPT,
    build_qa_generation_prompt,
    has_deictic_reference,
)
from app.evaluation.dataset.sampler import sample_chunks, sample_multihop_pairs
from app.evaluation.dataset.validator import self_validate
from app.repositories.evaluation_repository import EvalRepository
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

_DEFAULT_TYPE_RATIO = {"factual": 5, "procedural": 3, "comparative": 1, "multihop": 1}
_DEFAULT_SAMPLING_SEED = 42
_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
# 생성 QA에서는 중국어 여부를 추정하지 않고 모든 한자 계열 Unicode 문자를 금지한다.
# 통합 한자 확장 영역뿐 아니라 부수·호환 문자·표의문자 반복 기호도 포함한다.
_FORBIDDEN_CJK_PATTERN = re.compile(
    r"[\u2E80-\u2FFF\u3005\u3007\u303B\u3400-\u4DBF\u4E00-\u9FFF\uD800-\uDFFF\uF900-\uFAFF"
    r"\U00020000-\U0002FA1F\U00030000-\U000323AF]"
)
_SINGLE_TYPES = ("factual", "procedural", "comparative")
# 최초 생성 실패·지시어 질문 제외 시 같은 작업을 다시 생성하는 최대 라운드 수
_MAX_GENERATION_ROUNDS = 3

# ①축 — 한국어 검색 취약 세그먼트 자동 태깅 패턴 (설계서 4.1)
_ABBREVIATION_TOKENS = ["PSM", "MSDS", "LOTO", "TBM", "SDS", "RA", "GHS", "KOSHA"]
_LEGAL_MARKERS = ["조", "법", "시행령", "시행규칙", "별표", "부칙"]
_COMPOUND_MARKERS = ["위험성평가", "공정안전관리", "안전보건관리책임자", "작업환경측정", "밀폐공간"]


def _auto_tags(question: str) -> List[str]:
    """질문 텍스트에서 한국어 취약 세그먼트 태그를 추론한다."""
    tags: List[str] = []
    upper = question.upper()
    if re.search(r"제\s?\d+\s?조", question) or any(m in question for m in _LEGAL_MARKERS):
        tags.append("legal_reference")
    if any(tok in upper for tok in _ABBREVIATION_TOKENS):
        tags.append("abbreviation")
    if any(m in question.replace(" ", "") for m in _COMPOUND_MARKERS):
        tags.append("compound_term")
    return tags


def start_generation(dataset_id: int, gen_config: Dict[str, Any]) -> None:
    """이벤트 루프에 생성 태스크를 등록한다 (라우터에서 호출)."""
    asyncio.create_task(_run_generation(dataset_id, gen_config))


async def _run_generation(dataset_id: int, gen_config: Dict[str, Any]) -> None:
    repo = EvalRepository()
    try:
        dataset = repo.get_dataset(dataset_id)
        collection_name = dataset.get("qdrant_name")
        if not collection_name:
            repo.update_dataset_status(dataset_id, "failed", "컬렉션(qdrant_name)을 찾을 수 없습니다")
            return

        target_count = int(gen_config.get("target_count", 30))
        max_per_doc = int(gen_config.get("max_per_doc", 5))
        max_per_doc_ratio = gen_config.get("max_per_doc_ratio")
        min_chunk_chars = int(gen_config.get("min_chunk_chars", 200))
        type_ratio = gen_config.get("type_ratio", _DEFAULT_TYPE_RATIO)
        concurrency = int(gen_config.get("concurrency", 4))
        llm_backend = gen_config.get("llm_backend", "vllm")
        sampling_seed = int(gen_config.get("sampling_seed", _DEFAULT_SAMPLING_SEED))

        # 1) 청크 수집 + 샘플링
        store = EvalChunkStore()
        all_chunks = await store.scroll_chunks(collection_name)
        if not all_chunks:
            repo.update_dataset_status(dataset_id, "failed", "컬렉션에 청크가 없습니다")
            return

        # 문서별 청크 수 비율 기반 상한 계산 (max_per_doc_ratio가 지정된 경우)
        per_doc_limits = None
        if max_per_doc_ratio is not None:
            ratio = float(max_per_doc_ratio)
            eligible_per_doc = Counter(
                c.get("document_id", "?")
                for c in all_chunks
                if len((c.get("text") or "").strip()) >= min_chunk_chars
            )
            per_doc_limits = {
                doc_id: max(3, int(count * ratio))
                for doc_id, count in eligible_per_doc.items()
            }

        type_counts = _allocate_type_counts(target_count, type_ratio)
        single_total = sum(v for k, v in type_counts.items() if k != "multihop")
        multihop_total = type_counts.get("multihop", 0)

        singles = sample_chunks(
            all_chunks,
            target_count=single_total,
            max_per_doc=max_per_doc,
            per_doc_limits=per_doc_limits,
            min_chunk_chars=min_chunk_chars,
            seed=sampling_seed,
        )
        pairs = sample_multihop_pairs(
            all_chunks,
            target_count=multihop_total,
            min_chunk_chars=min_chunk_chars,
            seed=sampling_seed,
        )

        # 유형 배정 — 멀티홉 먼저 배정하고, 부족분(페어 못 찾음)은 단일 청크 생성으로 이월
        jobs: List[Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]] = []
        for a, b in pairs:
            jobs.append(("multihop", a, b))

        single_target_needed = max(0, target_count - len(jobs))
        jobs.extend(_build_single_jobs(singles, type_counts, single_target_needed))

        total = len(jobs)
        repo.update_dataset_progress(dataset_id, 0, total)
        logger.info(
            f"[eval] dataset {dataset_id} 생성 시작 — {total}건 "
            f"(컬렉션: {collection_name}, sampling_seed: {sampling_seed})"
        )

        llm = EvalLLM(
            openai_api_key=gen_config.get("openai_api_key"),
            openai_model=gen_config.get("openai_model", "gpt-4.1-mini"),
        )
        retriever = EvalRetriever()
        semaphore = asyncio.Semaphore(concurrency)
        generated = 0

        async def _generate_one(
            qtype: str,
            chunk: Dict[str, Any],
            second: Optional[Dict[str, Any]],
        ) -> bool:
            nonlocal generated
            async with semaphore:
                try:
                    qa = await _call_llm_for_qa(llm, qtype, chunk, second, llm_backend)
                    if qa is None:
                        return False
                    question, answer = qa
                    if has_deictic_reference(question):
                        logger.info(f"[eval] 지시어 포함 질문 자동 제외: {question[:50]}")
                        return False

                    gold_chunk_ids = [chunk["chunk_id"]]
                    gold_document_ids = [chunk.get("document_id", "")]
                    gold_texts = [chunk.get("text", "")]
                    if second is not None:
                        gold_chunk_ids.append(second["chunk_id"])
                        doc2 = second.get("document_id", "")
                        if doc2 not in gold_document_ids:
                            gold_document_ids.append(doc2)
                        gold_texts.append(second.get("text", ""))

                    rank = await self_validate(
                        retriever, question, gold_chunk_ids, collection_name
                    )
                    if rank is None:
                        logger.info(
                            "[eval] dataset %s 검색 미검출로 QA 1회 재생성: "
                            "type=%s gold_chunk_ids=%s question=%s",
                            dataset_id,
                            qtype,
                            gold_chunk_ids,
                            question[:100],
                        )
                        regenerated = await _call_llm_for_qa(
                            llm,
                            qtype,
                            chunk,
                            second,
                            llm_backend,
                            previous_question=question,
                        )
                        if regenerated is None:
                            logger.warning(
                                "[eval] dataset %s 검색 미검출 QA 재생성 실패; 최초 QA 유지: "
                                "gold_chunk_ids=%s",
                                dataset_id,
                                gold_chunk_ids,
                            )
                        else:
                            regenerated_question, regenerated_answer = regenerated
                            if has_deictic_reference(regenerated_question):
                                logger.warning(
                                    "[eval] dataset %s 검색 미검출 QA 재생성 질문에 지시어 포함; "
                                    "최초 QA 유지: question=%s",
                                    dataset_id,
                                    regenerated_question[:100],
                                )
                            else:
                                regenerated_rank = await self_validate(
                                    retriever,
                                    regenerated_question,
                                    gold_chunk_ids,
                                    collection_name,
                                )
                                question, answer, rank = (
                                    regenerated_question,
                                    regenerated_answer,
                                    regenerated_rank,
                                )
                                logger.info(
                                    "[eval] dataset %s 검색 미검출 QA 재생성 완료: "
                                    "gold_chunk_ids=%s rank=%s question=%s",
                                    dataset_id,
                                    gold_chunk_ids,
                                    rank,
                                    question[:100],
                                )

                    repo.insert_qa_item(
                        dataset_id=dataset_id,
                        question=question,
                        gold_answer=answer,
                        gold_chunk_ids=gold_chunk_ids,
                        gold_document_ids=[d for d in gold_document_ids if d],
                        gold_chunk_texts=gold_texts,
                        question_type=qtype,
                        self_valid_rank=rank,
                        expected_behavior="answer",
                        tags=_auto_tags(question),
                        source_meta={
                            "original_filename": chunk.get("original_filename"),
                            "section_title": chunk.get("section_title"),
                            "header_path": chunk.get("header_path") or [],
                            "page_number": chunk.get("page_number"),
                        },
                    )
                    generated += 1
                    repo.update_dataset_progress(dataset_id, generated, total)
                    return True
                except Exception as e:
                    logger.error(f"[eval] dataset {dataset_id} QA 생성 실패 ({qtype}): {e}")
                    return False

        pending_jobs = jobs
        for round_no in range(1, _MAX_GENERATION_ROUNDS + 1):
            results = await asyncio.gather(*[_generate_one(*job) for job in pending_jobs])
            pending_jobs = [job for job, succeeded in zip(pending_jobs, results) if not succeeded]
            if not pending_jobs:
                break
            logger.warning(
                f"[eval] dataset {dataset_id} {round_no}차 생성 후 "
                f"{len(pending_jobs)}건 미완료 — 보충 생성 시도"
            )

        if generated == 0:
            repo.update_dataset_status(dataset_id, "failed", "생성된 QA가 없습니다 (LLM 응답 확인 필요)")
        else:
            repo.update_dataset_status(dataset_id, "review")
            if generated < total:
                logger.warning(
                    f"[eval] dataset {dataset_id} 생성 일부 완료 — {generated}/{total}건 "
                    f"(최대 {_MAX_GENERATION_ROUNDS}회 시도)"
                )
            else:
                logger.info(f"[eval] dataset {dataset_id} 생성 완료 — {generated}/{total}건")
    except Exception as e:
        logger.error(f"[eval] dataset {dataset_id} 생성 오류: {e}")
        repo.update_dataset_status(dataset_id, "failed", str(e)[:500])


async def _call_llm_for_qa(
    llm: EvalLLM,
    qtype: str,
    chunk: Dict[str, Any],
    second: Optional[Dict[str, Any]],
    backend: str,
    previous_question: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """LLM으로 QA 1건을 생성한다. 파싱 실패 시 1회 재시도."""
    prompt = build_qa_generation_prompt(
        qtype,
        chunk.get("text", ""),
        second_chunk_text=second.get("text", "") if second else None,
        section_title=chunk.get("section_title"),
    )
    if previous_question:
        prompt += (
            "\n\n[재생성 지시]\n"
            "아래 최초 질문은 검색 결과 상위 10개에서 정답 원문을 찾지 못했습니다. "
            "최초 질문과 다른 질문을 생성하되, 원문의 핵심 용어·고유명사·법령명·수치가 "
            "질문에 자연스럽게 포함되도록 다시 작성하십시오. 답변도 새 질문에 맞게 작성하십시오.\n"
            f"[최초 질문]\n{previous_question}"
        )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    for attempt in range(2):
        content = await llm.chat(
            messages,
            temperature=0.7 if attempt == 0 else 0.0,
            max_tokens=1024,
            backend=backend,
        )
        parsed = _parse_qa_json(content)
        if parsed:
            return parsed
    return None


def _parse_qa_json(content: str) -> Optional[Tuple[str, str]]:
    match = _JSON_PATTERN.search(content)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    question = (data.get("question") or "").strip()
    answer = (data.get("answer") or "").strip()
    if len(question) < 5 or len(answer) < 5:
        return None
    if _FORBIDDEN_CJK_PATTERN.search(question) or _FORBIDDEN_CJK_PATTERN.search(answer):
        return None
    return question, answer


def _build_single_jobs(
    singles: List[Dict[str, Any]],
    type_counts: Dict[str, int],
    target_needed: int,
) -> List[Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]]:
    """단일 청크 기반 QA 작업을 배정한다.

    요청 비율(사실/절차/비교)을 인터리빙하고, 유효 청크가 목표보다 적으면
    청크와 유형 시퀀스를 순환 재사용해 target_needed만큼 작업을 구성한다.
    """
    jobs: List[Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]] = []
    if not singles or target_needed <= 0:
        return jobs

    # 1차: 인터리빙 유형 시퀀스 생성 (예: 사실,절차,비교,사실,절차,사실,...)
    remaining = {t: type_counts.get(t, 0) for t in _SINGLE_TYPES}
    type_seq: List[str] = []
    while sum(remaining.values()) > 0:
        for t in _SINGLE_TYPES:
            if remaining[t] > 0:
                type_seq.append(t)
                remaining[t] -= 1

    if not type_seq:
        type_seq = ["factual"]

    for i in range(target_needed):
        jobs.append((type_seq[i % len(type_seq)], singles[i % len(singles)], None))

    return jobs


def _allocate_type_counts(target: int, ratio: Dict[str, int]) -> Dict[str, int]:
    """유형 비율에 따라 목표 건수를 배분한다 (잔여는 factual에)."""
    total_ratio = sum(ratio.values()) or 1
    counts = {
        qtype: (target * weight) // total_ratio
        for qtype, weight in ratio.items()
    }
    remainder = target - sum(counts.values())
    counts["factual"] = counts.get("factual", 0) + remainder
    return counts
