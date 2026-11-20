# 평가 지표 정리 보고서 (2026-11-17)

> 근거: `eval-pipeline-review-20261117.md`(E-01~E-19)의 정리안. 사용자 승인 "삭제 해도 되"(11-17).
> 관련: R8-7(평가 실행), 시험 항목 1(Hit@10)·2(NDCG@5)·4(응답시간), UI-평가 실행·대시보드
> 주석 규칙: 변경 위치마다 `2026.11.17(sooyeon.choi) 추가/수정/삭제 - 설명`

## 1. 요약

계산 방식이 잘못됐거나 같은 값을 이름만 바꿔 다시 저장하던 지표를 삭제했습니다. 집계는 허용 목록에 있는 키만 평균하도록 바꿨습니다.

| 구분 | 남긴 지표 | 삭제한 지표(이유) |
|---|---|---|
| 검색 | `hit@k`, `recall@k`, `ndcg@k`, `rr@k` (k=1,3,5,10 + 설정 N/K) | `fail@k`(=1−hit, 중복), `rr`(=rr@max_k, 중복), `top1_is_relevant`(중복 제거 전 1위 기준이라 hit@1과 값이 다름), `retrieval.rerank.mrr@k` 별칭(=rr@k), `document_*` 문서 단위 지표(청크 정답과 이중 집계) |
| 검색 진단값 | `gold_ranks`, `evidence_rank`, `evidence_count`, `total_retrieved`, `threshold`: 항목 JSON에만 저장 | 평균 집계 금지(기존에는 순위·건수·임계값까지 평균 지표로 저장됨) |
| 답변 | `answer.correctness` = **F2 한 종류로 고정** | v1(전체 답변 cosine), v2 출력과 별칭(`correctness_v2_shadow`, `correctness_v2_f2_shadow`, `.f2`), RAGAS Judge(`answer_correctness_judge.py` 전체), 항목별 fallback 선택(항목마다 다른 방식의 점수가 한 평균에 섞였음), `correctness_mean`, `similarity.mean` |
| 규칙·형식 | `behavior_correct_rate`, `refusal_correct_rate` | `rule_match.mean`(법령 조항 패턴이라 SOP와 맞지 않고, 정답 토큰이 없으면 1.0으로 처리해 평균을 부풀림), `format_correct_rate`(존댓말 종결 정규식) |
| 인용 | `citation.correctness`, `citation.completeness` | `citation_f1`, `citation_validity`, `document_*`, `doc_*` 별칭, `citation_relevance`(correctness와 분모만 다른 중복 지표), 인용 건수 평균 |
| 시간 | 항목별 `latency_ms` = **그래프 실행 시간만**(검색 → 재랭킹 → 답변 생성) | `latency.mean_ms`(지표 계산·인용 보정 LLM 시간이 섞인 항목 전체 시간) |
| 실행 | `run.error_rate` | — |

주 지표 변경(시험 항목 기준):
- 검색 주 지표 `Retriever Recall@N`을 **`검색 완전성 Hit@N`**(`retrieval.rrf.hit@N`)으로 바꿨습니다. 시험기관이 정의한 Recall@10("상위 10개에 정답 청크가 1개 이상")과 같은 계산입니다.
- Recall@N은 보조 지표로 옮겼습니다.
- 보조 MRR 키는 `retrieval.rerank.rr@K`로 바꿨습니다.

## 2. 함께 고친 계산 오류

| ID | 내용 | 조치 |
|---|---|---|
| E-01 | Full 평가 어댑터가 `retrieval_override`(후보 N, 컨텍스트 K)를 넣었지만, `validate_input` 노드가 매 실행 None으로 초기화해서 실제로는 적용되지 않았음 | 효과 없는 코드를 삭제했습니다. 평가는 원래대로 운영과 같은 단계별 설정(`candidate_top_k`/`reranker_top_k`/`context_top_k`)으로 돌고, N/K는 지표 cutoff로만 씁니다 |
| E-02 | Full 평가 검색 지표가 설정 N/K 한 값으로만 계산돼 Hit@10·NDCG@5가 비어 있을 수 있었음 | K=1,3,5,10 + N/K를 항상 계산 |
| E-03 | 검색 전용 평가의 재랭킹 입력이 RRF 상위 N(10)개뿐이라 운영(후보 40개 → 10개)과 NDCG@5가 달랐음 | 재랭킹 입력을 `max(N, candidate_top_k)`, 출력을 `max(K, reranker_top_k)`로 운영과 맞춤 |
| E-04 | 응답시간에 지표 계산·평가 전용 인용 보정 시간이 포함됐음 | 어댑터에서 `graph.ainvoke`만 측정(`latency_ms`) |
| E-05 | 평가 전용 인용 보정(`repair_missing_citations`)이 운영에 없는 LLM 재호출로 답변을 바꿔, 평가 답변·인용 지표가 운영과 달랐음 | 설정 `eval_citation_repair_enabled`(기본 false)로 끔. 운영 답변 그대로 평가(사용자 결정 11-17) |

## 3. 변경 파일

백엔드(`adrag_backend/`):
- `app/evaluation/metrics/retrieval_metrics.py`: 중복 지표 삭제, `is_aggregated_retrieval_metric()` 허용 목록 추가
- `app/evaluation/metrics/citation_metrics.py`: `citation_precision_recall()`·`map_cited_chunk_ids()` 삭제, 출력 키 정리
- `app/evaluation/metrics/similarity.py`: `rule_check()`·`extract_critical_tokens()`·`count_citation_tags()` 삭제
- `app/evaluation/metrics/answer_correctness_v1.py`: `check_format()` 삭제, 거절 판정(`check_refusal`)만 남김
- `app/evaluation/metrics/answer_correctness_judge.py`: **파일 삭제**
- `app/evaluation/runner/e2e_evaluator.py`: F2 단일, `_evaluate_answer_alignment()`(v2 문장 정렬만), 검색 cutoff 확장. `_aggregate_correctness`·`_evaluate_answer_correctness`·`_check_refusal` 삭제
- `app/evaluation/runner/eval_runner.py`: 항목 상태·집계를 허용 목록 기준으로 정리, 재랭킹 입력 수를 운영과 맞춤, 시간 측정 변경
- `app/evaluation/adapters/rag_pipeline_adapter.py`: `retrieval_override` 삭제, `latency_ms` 측정
- `app/evaluation/metric_catalog.py`: 주 지표 Hit@N, 보조 지표 Recall@N·rr@K·NDCG@N
- `app/evaluation/excel_exporter.py`: 열 `검색 완전성 Hit@N`, `Answer Correctness (F2)`
- `app/routes/evaluation.py`: snapshot에서 v1·judge·primary·fallback 삭제, `_METRIC_VERSION` `rule-v1.1` → `rule-v1.2`
- `app/core/config.py`: `answer_correctness_primary`·`answer_correctness_fallback_chain`·`answer_correctness_judge_*` 설정과 검증기 삭제(`extra="ignore"`라서 `.env`에 이름이 남아도 기동 오류 없음)
- 테스트: `tests/test_eval_e2e.py`, `test_eval_runner.py`, `test_rule_based_metric_regressions.py`, `test_eval_routes.py`, `test_eval_run_excel_export.py`

루트: `.env.example`. `ANSWER_CORRECTNESS_JUDGE_*` 주석을 삭제 표기로 바꿨습니다.

화면(`adrag_frontend/src/`): `composables/useEvalDashboard.js`, `composables/useEvalRuns.js`, `views/EvalRunView.vue`
→ 테스트 실행 중 HEAD 내용으로 되돌아간 것을 확인해 11-17 사용자 확인 후 다시 적용. `vite build` 통과.

DB 스키마는 바꾸지 않았습니다. `tb_eval_item_results`의 `answer_correctness_v1_json` 등 기존 열은 남아 있고, 새 실행에서는 값을 쓰지 않습니다.

## 4. 검증

| 항목 | 결과 |
|---|---|
| 평가 관련 8개 파일(`test_eval_e2e`, `test_eval_runner`, `test_rule_based_metric_regressions`, `test_retrieval_evaluation`, `test_eval_repository`, `test_eval_routes`, `test_eval_run_excel_export`, `test_evaluation_task9`) | **82 통과, 1 건너뜀, 0 실패** |
| 전체 `pytest -m "not e2e and not voice" --continue-on-collection-errors` | 548 통과 / 15 실패 / 26 건너뜀 / 수집 오류 9 |
| 전체 실행 실패 15건 단독 재실행 | 10건 통과(실행 순서에 따른 오염), 5건은 단독으로도 실패 |

단독으로도 실패하는 5건과 수집 오류 9건은 이번 변경과 관련 없습니다. 이번 작업에서 건드리지 않은 파일의 기존 문제입니다.
- `test_database_migrations` 3건: head를 `0010`으로 기대하는데 현재 head는 `0011_user_pwd_changed_at`입니다.
- `test_unified_auth_routes` 1건: 비밀번호 변경 기능 추가로 응답 키가 하나 늘었습니다.
- `parsers/test_parse_regression` 1건: fixture 확인 실패입니다.
- 수집 오류 9건: `app/routes/ingest.py:96`이 import 시점에 `get_settings().sheet_preview_max_concurrency`를 읽습니다. 그런데 일부 테스트가 수집 단계에서 `sys.modules["app.core.config"]`를 가짜 모듈로 바꿔 두어 실패합니다.
- 전체 실행에서만 실패한 10건도 같은 가짜 모듈 오염 때문입니다. 새로 쓴 설정 테스트는 원본 설정 파일을 직접 로드하게 해서 오염 영향을 받지 않습니다.

기준선(10-20, 473/11/3) 이후 브랜치 `refactor-1`에 커밋 안 된 변경이 많습니다. 그래서 위 실패가 언제부터 있었는지는 이번에 따로 확인하지 않았습니다.

## 5. 남은 이슈

1. (해결) 화면 파일 3개 되돌려짐 → 다시 적용함.
2. (해결) 평가 전용 인용 보정 → 기본 끔. 다시 켜려면 `.env`에 `EVAL_CITATION_REPAIR_ENABLED=true`. 끈 뒤에는 인용 [N]을 빠뜨린 답변의 Citation 지표가 이전 실행보다 낮게 나올 수 있다(운영 실제 수준).
3. **검색 전용 평가와 운영의 차이**: `retrieval_adapter`는 질의 재작성·메타데이터 필터 없이 검색합니다. 그래서 검색 전용 평가 수치는 운영 경로의 근사치입니다. 공식 Hit@10은 일괄 질의 설계(F-07: 재랭킹 전 상위 10개)로 잽니다.
4. **이전 실행 표시**
   - `rule-v1.1` 실행의 `answer.correctness`는 그때 설정된 primary 방식의 값입니다. 새 실행(`rule-v1.2`)의 F2 값과 추이 그래프에서 섞여 보일 수 있습니다.
   - 이전 실행의 `mrr@5` 추이는 새 키 `rr@5`와 이어지지 않습니다.
5. `offline_evaluation/`(CLI 도구)는 이번 범위에서 제외했습니다. 같은 이름의 지표 계산이 남아 있습니다.
6. 변경로그(`01_결정사항_변경로그.md`)에 "평가 심사 한정 외부 API 허용(절대 규칙 7 예외)" 결정 항목을 추가하는 일이 아직 남아 있습니다.

## 6. 되돌리는 방법

- 백엔드: 위 변경 파일을 `git checkout -- <파일>`로 되돌리고, `app/evaluation/metrics/answer_correctness_judge.py`를 `git checkout HEAD -- <경로>`로 복구합니다.
- 마이그레이션이 없어서 DB 조치는 필요 없습니다. 새로 저장된 실행은 `metric_version=rule-v1.2`로 구분됩니다.

## 7. 요구사항 정의서·기능 목록에 반영할 것

- R8-7: 평가 주 지표를 "검색 완전성 Hit@10, 재랭킹 NDCG@5, Answer Correctness(F2), Citation Completeness"로 명시합니다.
- N-4: 평가 화면의 항목별 응답시간은 그래프 실행 시간 기준입니다. 공식 측정은 일괄 질의 기능으로 합니다.
