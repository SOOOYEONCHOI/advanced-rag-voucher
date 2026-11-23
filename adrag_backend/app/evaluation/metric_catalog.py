"""DB 지표 키를 UI용 주요/보조 지표로 변환한다.

2026.11.19(sooyeon.choi) 수정 - 주요 지표를 AI+ 인증 시험 합의서(시험 1~4) 기준으로 변경
  시험 1 검색 완전성 Recall@10  = 하이브리드 검색(재랭킹 전) 상위 10개에 정답 근거 청크가 1개 이상 포함된 질의 수
                                 / 전체 시험 질의 수  (키 retrieval.rrf.hit@10, 목표 ≥ 80%)
  시험 2 검색 최종 정합성 NDCG@5 = 재랭킹 상위 5개의 질의별 NDCG@5 평균, 분모 전체 질의 수
                                 (키 retrieval.rerank.ndcg@5, 목표 ≥ 80%)
  시험 3 답변 생성 정확도      = 3종 LLM PASS/FAIL 다수결의 PASS 수 / 전체 평가 데이터 수
                                 (키 answer.judge_accuracy, 목표 ≥ 80%) — 심사 미구현이라 '미측정'으로 표시
  시험 4 답변 생성 평균 반환 시간 = 반환 시간 합계 / 전체 시험 데이터 수
                                 (키 answer.response_time_ms, 목표 ≤ 15초)
  컷오프 10·5는 합의서 고정값이다. 실행 설정의 N·K가 다르면 그 값은 보조 지표로 함께 보여 준다.
  그 밖의 지표(Recall 커버율, MRR, F2 정답 유사도, 인용 지표, 첫 토큰 시간 등)는 보조 지표.
"""

from typing import Any

# [AI+ 시험] Recall@10 - 6) 전체 시험 데이터에 대한 검색 완전성(Recall@10)을 산출하는 코드 (지표 키)
# [AI+ 시험] NDCG@5 - 6) 전체 시험 데이터에 대한 질의별 NDCG@5의 평균을 산출하는 코드 (지표 키: AGREEMENT_NDCG_KEY)
AGREEMENT_RECALL_KEY = "retrieval.rrf.hit@10"
AGREEMENT_NDCG_KEY = "retrieval.rerank.ndcg@5"
JUDGE_ACCURACY_KEY = "answer.judge_accuracy"
# [AI+ 시험] 반환 시간 - 5) 전체 시험 데이터의 반환 시간을 평균하여 답변 생성 평균 반환 시간을 산출하는 코드 (지표 키: 최종 답변 완료 기준)
RESPONSE_TIME_KEY = "answer.response_time_ms"
# [AI+ 시험] 반환 시간 - 5) 전체 시험 데이터의 반환 시간을 평균하여 답변 생성 평균 반환 시간을 산출하는 코드 (지표 키: 첫 토큰 기준, 화면 주요 지표 4)
FIRST_TOKEN_KEY = "answer.first_token_ms"
# 합의서 계산식: 분모 = 전체 시험 질의 수(실행 오류·정답 없음은 0으로 센다)
# [AI+ 시험] Recall@10 - 6), NDCG@5 - 6) 분모 = 전체 시험 질의 수(오류·정답 없음 질의는 0)
ALL_DENOMINATOR_KEYS = frozenset({AGREEMENT_RECALL_KEY, AGREEMENT_NDCG_KEY})
RESPONSE_TIME_TARGET_MS = 15_000
# 2026.11.19(sooyeon.choi) 수정 - 평가 화면 지표 4 판정 기준을 첫 토큰 반환 시간 평균 ≤ 5초로 변경(사용자 결정).
#   합의서 시험 4(요청 시작 → 최종 답변 생성 완료, ≤ 15초)는 보조 지표 '전체 반환 시간'과
#   시험기관용 일괄 질의 스크립트(scripts/eval_batch_query.py) 출력에서 그대로 확인한다.
FIRST_TOKEN_TARGET_MS = 5_000


def _ratio(key: str, label: str, group: str, target: float | None = None, desc: str = "") -> dict:
    return {"key": key, "label": label, "group": group, "unit": "ratio", "direction": "ge",
            "target": target, "formula": desc}


def _ms(key: str, label: str, group: str, target: float | None = None, desc: str = "") -> dict:
    return {"key": key, "label": label, "group": group, "unit": "ms", "direction": "le",
            "target": target, "formula": desc}


def metric_catalog(scope: str, config: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    n = int(config.get("retrieval_top_n", config.get("top_k", 10)))
    k = int(config.get("rerank_top_k", 5))
    primary = [
        _ratio(AGREEMENT_RECALL_KEY, "검색 완전성 Recall@10", "search", 0.80,
               "상위 10개(재랭킹 전 하이브리드 검색)에 정답 근거 청크가 1개 이상 포함된 질의 수 ÷ 전체 시험 질의 수"),
        _ratio(AGREEMENT_NDCG_KEY, "검색 최종 정합성 NDCG@5", "search", 0.80,
               "재랭킹 상위 5개의 질의별 NDCG@5(이진 관련도) 합계 ÷ 전체 시험 질의 수"),
    ]
    if scope == "full":
        primary.extend([
            {**_ratio(JUDGE_ACCURACY_KEY, "답변 생성 정확도 (LLM-as-a-Judge)", "answer", 0.80,
                      "3종 LLM PASS/FAIL 중 2개 이상 일치한 판정의 PASS 수 ÷ 전체 평가 데이터 수"),
             "required": True, "not_measured_reason": "3종 LLM 심사 미구현"},
            # 2026.11.19(sooyeon.choi) 수정 - 지표 4 = 첫 토큰 반환 시간 평균(목표 ≤ 5초), 전체 반환 시간은 함께 표시
            {**_ms(FIRST_TOKEN_KEY, "답변 생성 평균 반환 시간", "answer", FIRST_TOKEN_TARGET_MS,
                   "질의별 요청 시작 → LLM 첫 답변 토큰 시간의 평균(첫 토큰 기준)"),
             "companion_key": RESPONSE_TIME_KEY},
        ])
    secondary = [
        _ratio("retrieval.rrf.recall@10", "정답 청크 커버율 Recall@10", "search",
               desc="상위 10개가 포함한 정답 청크 수 ÷ 질의별 정답 청크 수(질의별 평균, 정답 확정 질의 기준)"),
        _ratio("retrieval.rerank.hit@5", "재랭킹 적중률 Hit@5", "search",
               desc="재랭킹 상위 5개에 정답 근거 청크가 1개 이상 포함된 질의 비율"),
        _ratio("retrieval.rerank.rr@5", "Reranked MRR@5", "search", desc="재랭킹 상위 5개 첫 정답 순위의 역수 평균"),
        _ratio("retrieval.rrf.ndcg@10", "Retriever NDCG@10", "search", desc="재랭킹 전 상위 10개 NDCG 평균"),
    ]
    if n != 10:
        secondary.append(_ratio(f"retrieval.rrf.hit@{n}", f"검색 적중률 Hit@{n} (실행 설정 N)", "search"))
    if k != 5:
        secondary.append(_ratio(f"retrieval.rerank.ndcg@{k}", f"Reranked NDCG@{k} (실행 설정 K)", "search"))
    if scope == "full":
        secondary.extend([
            _ratio("answer.correctness", "Answer Correctness (F2)", "answer",
                   desc="정답 답변과 생성 답변의 문장 정렬 F2(임베딩 유사도). 합의서 지표 아님, 내부 참고"),
            _ratio("citation.completeness", "Citation Completeness", "answer", desc="답변 인용이 정답 근거를 포함한 비율"),
            _ratio("citation.correctness", "Citation Correctness", "answer", desc="답변 인용 중 정답 근거인 비율"),
            # 2026.11.19(sooyeon.choi) 수정 - 첫 토큰은 주요 지표 4로 이동, 전체 반환 시간(합의서 시험 4 정의)을 보조 지표로
            _ms(RESPONSE_TIME_KEY, "전체 반환 시간", "answer",
                desc="전체 질의의 요청 시작 → 완료·실패 경과 시간 합계 ÷ 전체 질의 수"
                     "(오류 포함, 측정 누락 시 미완료). 합의서 시험 4 기준(≤ 15초)"),
        ])
    return primary, secondary


def present_run_metrics(scope: str, config: dict[str, Any], rows: list[dict]) -> dict[str, Any]:
    by_key = {
        row["metric_key"]: row
        for row in rows
        if row.get("segment") == "all"
    }
    primary_defs, secondary_defs = metric_catalog(scope, config)

    def present(definitions: list[dict]) -> list[dict]:
        output = []
        for definition in definitions:
            row = by_key.get(definition["key"])
            if row is None:
                # 2026.11.19(sooyeon.choi) 추가 - 합의서 필수 지표는 값이 없어도 '미측정'으로 보여 준다
                if definition.get("required"):
                    output.append({
                        **definition, "value": None, "std": None, "status": "not_measured",
                        "evaluated_count": 0, "excluded_count": 0, "error_count": 0, "total_count": 0,
                    })
                continue
            output.append({
                **definition,
                "status": "incomplete" if definition["key"] == RESPONSE_TIME_KEY
                and row.get("metric_value") is None else None,
                "value": row.get("metric_value"),
                "std": row.get("metric_std"),
                "evaluated_count": row.get("evaluated_count", 0),
                "excluded_count": row.get("excluded_count", 0),
                "error_count": row.get("error_count", 0),
                "total_count": row.get("total_count", 0),
            })
        return output

    return {
        "primary_metrics": present(primary_defs),
        "secondary_metrics": present(secondary_defs),
        "law_metrics": present_law_metrics(primary_defs, rows),
    }


def present_law_metrics(primary_defs: list[dict], rows: list[dict]) -> list[dict]:
    """2026.11.20(sooyeon.choi) 수정 - 합본 실행의 법령별 주요 지표(세그먼트 law:*). 단독 실행은 빈 목록.

    같은 실행의 항목 결과를 법령으로 나눠 전체와 같은 식으로 집계한 참고 값(합격 판정은 전체 값).
    """
    by_law: dict[str, dict[str, dict]] = {}
    for row in rows:
        segment = str(row.get("segment") or "")
        if segment.startswith("law:"):
            by_law.setdefault(segment[4:], {})[row["metric_key"]] = row
    output = []
    for law in sorted(by_law):
        metrics = {}
        for definition in primary_defs:
            row = by_law[law].get(definition["key"])
            if row is None:
                continue
            metrics[definition["key"]] = {
                "value": row.get("metric_value"),
                "std": row.get("metric_std"),
                "evaluated_count": row.get("evaluated_count", 0),
                "total_count": row.get("total_count", 0),
            }
        output.append({"law": law, "metrics": metrics})
    return output
