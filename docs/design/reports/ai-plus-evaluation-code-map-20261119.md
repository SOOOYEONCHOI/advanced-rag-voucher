# AI+ 인증 시험 합의서 — 평가 코드 위치 안내

작성일: 2026-11-19

기준 문서: [AI+인증 시헙합의서.pdf](../../../AI+인증%20시헙합의서.pdf), 3~6페이지.

시험 현장에서 “합의서의 이 항목은 이 코드에서 처리합니다”라고 설명하기 위한 안내다. 현재 구현된 기능과 미구현 기능을 구분한다. 코드 링크는 이 문서 위치를 기준으로 한 상대 경로이며, 줄 번호는 아래 표에 별도로 표기한다. 이후 코드 변경 시 줄 번호는 달라질 수 있다.

## 1. 데이터셋 준비·일괄 평가 API

| 구분 | 용도 | 실행 API |
|---|---|---|
| 골드셋 평가 | 화면에서 확정한 데이터셋 전체 평가 | `POST /api/eval/runs` |
| 파일 일괄 평가 | 시험 질의 CSV·Excel 업로드 후 순차 실행 | `POST /api/eval/batch-jobs` |

| 설명할 내용 | 코드 파일 | 줄 | 함수·역할 |
|---|---|---:|---|
| 시험 데이터셋 Excel 다운로드 | [routes/evaluation.py](../../../adrag_backend/app/routes/evaluation.py) | 207 | `download_testset_excel()` — 질의·정답 근거 파일 다운로드 |
| 시험 데이터셋 Excel 구성 | [evaluation/excel_exporter.py](../../../adrag_backend/app/evaluation/excel_exporter.py) | 245 | `build_testset_workbook()` — 질의·근거·출처 정보 구성 |
| 검수 데이터셋을 골드셋으로 확정 | [routes/evaluation.py](../../../adrag_backend/app/routes/evaluation.py) | 372 | `POST /api/eval/datasets/{dataset_id}/finalize` |
| 골드셋 일괄 평가 시작 | [routes/evaluation.py](../../../adrag_backend/app/routes/evaluation.py) | 419 | `create_run()` — 골드셋과 설정으로 실행 생성 |
| 골드셋의 질의를 하나씩 평가 | [runner/eval_runner.py](../../../adrag_backend/app/evaluation/runner/eval_runner.py) | 49 | `_execute_run()` — 전체 RAG 평가는 순차 실행 |
| 시험 질의 파일 업로드·실행 | [routes/eval_batch.py](../../../adrag_backend/app/routes/eval_batch.py) | 140 | `create_batch_job()` — 파일 검증 후 작업 등록 |
| CSV·Excel 질의 읽기 | [batch/file_reader.py](../../../adrag_backend/app/evaluation/batch/file_reader.py) | 124 | `read_query_file()` |
| 정답 근거 파일 읽기 | [batch/gold_matcher.py](../../../adrag_backend/app/evaluation/batch/gold_matcher.py) | 189 | `read_gold_file()` |
| 정답 근거 업로드 | [routes/eval_batch.py](../../../adrag_backend/app/routes/eval_batch.py) | 298 | `POST /api/eval/batch-jobs/{job_id}/gold` — 청크 ID가 있으면 직접 확정 |
| 파일의 전체 질의 순차 실행 | [batch/runner.py](../../../adrag_backend/app/evaluation/batch/runner.py) | 165 | `run_job()` — 질의별 RAG 호출 및 결과 저장 |

설명 예시:

> 화면 평가에서는 확정한 골드셋을 불러오고, 파일 평가에서는 CSV·Excel을 읽습니다. 등록된 질의는 실행기가 순차 처리합니다.

## 2. 시험 1 — 검색 완전성 Recall@10

합의서 계산식:

```text
상위 10개에 정답 근거 청크가 1개 이상 포함된 질의 수
÷ 전체 시험 질의 수 × 100
```

| 설명할 내용 | 코드 파일 | 줄 | 함수·역할 |
|---|---|---:|---|
| 임베딩·BM25·reranker 구성 요소 생성 | [core/container.py](../../../adrag_backend/app/core/container.py) | 75 | `PipelineContainer` — 모델 클라이언트 제공. `embedding` 75줄, `kiwi_bm25_encoder` 90줄, `reranker` 119줄 |
| 의미 검색과 BM25 검색 수행 | [nodes/retrieve.py](../../../adrag_backend/app/graphs/nodes/retrieve.py) | 79 | `_search_qdrant_hybrid()` — 질의 임베딩·BM25 인코딩 후 검색 호출 |
| 검색 결과 통합 | [repositories/vector_repository.py](../../../adrag_backend/app/repositories/vector_repository.py) | 572 | `search_hybrid()` — Dense·Kiwi BM25 결과를 weighted RRF로 병합 |
| 상위 k개에 정답이 있는지 판정 | [metrics/retrieval_metrics.py](../../../adrag_backend/app/evaluation/metrics/retrieval_metrics.py) | 39 | `hit_at_k()` — 중복 제거 후 정답 포함 시 1, 아니면 0 |
| 파일 평가의 전체 질의 집계 | [batch/recall.py](../../../adrag_backend/app/evaluation/batch/recall.py) | 34 | `compute_recall()` — 적중 수 ÷ 전체 질의 수 |
| 골드셋 평가의 전체 집계 | [runner/eval_runner.py](../../../adrag_backend/app/evaluation/runner/eval_runner.py) | 311 | `_aggregate_and_save_metrics()` |
| 저장 결과로 지표 조회 | [routes/eval_batch.py](../../../adrag_backend/app/routes/eval_batch.py) | 443 | `GET /api/eval/batch-jobs/{job_id}/recall?basis=retrieved&k=10` |

설명 예시:

> 의미 검색과 BM25 결과를 통합한 뒤, 재랭킹 전 상위 10개 청크 ID를 정답 ID와 비교합니다. 하나라도 포함되면 적중이며, 전체 질의 중 적중 비율을 계산합니다.

합의서 명칭은 Recall@10이지만, 해당 정의에 맞춰 내부 함수는 **`hit_at_k()`**를 사용한다. 같은 파일의 `recall_at_k()`는 별도의 정답 청크 커버율이며 이번 주요 지표와 다르다.

## 3. 시험 2 — 검색 최종 정합성 NDCG@5

계산 구조:

```text
질의별 NDCG@5 = 실제 정답 순위의 DCG ÷ 이상적인 정답 순위의 IDCG
전체 지표 = 질의별 NDCG@5 합계 ÷ 전체 시험 질의 수
```

현재 구현의 이진 관련도 수식:

```text
rel_i = 순위 i의 청크가 정답 청크이면 1, 아니면 0
DCG@5 = Σ rel_i / log2(i + 1), i = 1 ... 상위 5개
IDCG@5 = Σ 1 / log2(i + 1), i = 1 ... min(정답 청크 수, 5)
NDCG@5 = DCG@5 / IDCG@5
```

| 설명할 내용 | 코드 파일 | 줄 | 함수·역할 |
|---|---|---:|---|
| 검색 청크를 reranker에 전달 | [nodes/rerank.py](../../../adrag_backend/app/graphs/nodes/rerank.py) | 90 | `rerank()` — 관련도 평가 후 재정렬 |
| reranker 점수로 순위 정렬 | [clients/reranker_client.py](../../../adrag_backend/app/clients/reranker_client.py) | 64 | `RerankerClient.rerank()` — 점수 내림차순 정렬 |
| 모델 점수 API 호출 | [clients/reranker_client.py](../../../adrag_backend/app/clients/reranker_client.py) | 93 | `_call_score_api()` |
| 질의별 NDCG 계산식 | [metrics/retrieval_metrics.py](../../../adrag_backend/app/evaluation/metrics/retrieval_metrics.py) | 82 | `ndcg_at_k()` — DCG·IDCG 계산 |
| 파일 평가의 NDCG@5 평균 | [batch/recall.py](../../../adrag_backend/app/evaluation/batch/recall.py) | 34 | `compute_recall()` — 반환값의 `ndcg` |
| 전체 RAG 결과의 검색 지표 계산 | [runner/e2e_evaluator.py](../../../adrag_backend/app/evaluation/runner/e2e_evaluator.py) | 275 | `_compute_pipeline_retrieval_metrics()` |

설명 예시:

> 하이브리드 검색 결과를 reranker로 재정렬합니다. 상위 5개에서 정답 청크 여부를 이진 관련도로 두고, 순위에 따른 할인값을 적용해 NDCG를 구한 뒤 전체 질의로 평균합니다.

**reranker 모델 점수 자체를 NDCG 관련도 값으로 쓰지 않는다.** 정답 청크 ID 집합에 포함되면 관련도 1, 아니면 0이다.

## 4. 시험 3 — 근거 기반 답변 생성 정확도

| 설명할 내용 | 코드 파일 | 줄 | 구현 상태 |
|---|---|---:|---|
| 검색·재랭킹·답변 생성 전체 호출 | [services/rag_service.py](../../../adrag_backend/app/services/rag_service.py) | 153 | `RAGService.query()` |
| 근거를 이용한 LLM 답변 생성 | [nodes/generate_answer.py](../../../adrag_backend/app/graphs/nodes/generate_answer.py) | 39 | `generate_answer()` |
| 생성 답변 CSV 다운로드 API | [routes/eval_batch.py](../../../adrag_backend/app/routes/eval_batch.py) | 261 | `GET /api/eval/batch-jobs/{job_id}/results.csv` |
| CSV 내용 생성 | [batch/exporter.py](../../../adrag_backend/app/evaluation/batch/exporter.py) | 116 | `build_results_csv()` |
| 3종 LLM 정확도 지표 정의 | [evaluation/metric_catalog.py](../../../adrag_backend/app/evaluation/metric_catalog.py) | 42 | `answer.judge_accuracy` — 미측정 표시 |
| 3종 PASS/FAIL 심사·다수결 | 해당 계산 코드 없음 | — | **미구현** |

합의서에서 요구하는 계산식:

```text
질의별 최종 판정 = 3종 LLM 중 2종 이상이 일치한 PASS/FAIL
답변 생성 정확도(%) = 최종 PASS 수 ÷ 전체 평가 데이터 수 × 100
```

설명 예시:

> 생성 답변을 CSV로 내려받는 기능까지 구현되어 있습니다. 합의서의 3종 LLM 심사와 다수결 정확도 계산은 아직 구현되지 않았습니다.

[answer_correctness_f2.py](../../../adrag_backend/app/evaluation/metrics/answer_correctness_f2.py) 11줄의 `build_answer_correctness_f2()`는 **임베딩 기반 답변 유사도 보조 지표**이며, 합의서의 LLM Judge 정확도와 구분해야 한다.

## 5. 시험 4 — 최종 답변 생성 평균 반환 시간

합의서 계산식:

```text
질의별 요청 시작 → 검색 → 재랭킹 → 최종 답변 생성 완료 시간의 합계
÷ 전체 시험 질의 수
```

| 설명할 내용 | 코드 파일 | 줄 | 함수·역할 |
|---|---|---:|---|
| 질의 순차 실행 | [batch/runner.py](../../../adrag_backend/app/evaluation/batch/runner.py) | 165 | `run_job()` |
| 실제 RAG 서비스 요청 | [batch/runner.py](../../../adrag_backend/app/evaluation/batch/runner.py) | 147 | `_run_query()` |
| 질의별 시간 측정 시작 | [batch/runner.py](../../../adrag_backend/app/evaluation/batch/runner.py) | 197 | `time.perf_counter()` |
| 완료·오류·타임아웃 경과 시간 저장 | [batch/runner.py](../../../adrag_backend/app/evaluation/batch/runner.py) | 209 | `response_ms` 계산 |
| 질의별 측정값 DB 저장 | [repositories/eval_batch_repository.py](../../../adrag_backend/app/repositories/eval_batch_repository.py) | 176 | `save_item_result()` |
| 전체 시간의 평균 계산 | [batch/runner.py](../../../adrag_backend/app/evaluation/batch/runner.py) | 238 | `response_stats()` |
| 전체 측정 완료 여부·오류 포함 집계 | [batch/runner.py](../../../adrag_backend/app/evaluation/batch/runner.py) | 252 | `compute_summary()` — 누락 시 평균 미확정 |

설명 예시:

> 질의를 순차 실행하면서 요청 전후의 단조 시계 차이를 밀리초로 저장합니다. 전체 질의의 시간이 갖춰졌을 때 오류 시간을 포함하여 평균을 계산하며, 누락된 시간이 있으면 측정 미완료로 표시합니다.

현재 배치 측정은 서버 내부 서비스 요청을 기준으로 하며, 시험 PC와 서버 간 네트워크 왕복 시간은 포함하지 않는다. 오류 시간을 포함한 평균은 오류 건수와 함께 검토해야 한다.

### 화면 표시와 합의서 기준 구분

현재 화면의 대표 시간 지표는 **첫 토큰 평균 5초 기준**으로 설정되어 있다. PDF의 **최종 답변 완료 15초 기준**은 전체 반환 시간 `answer.response_time_ms`와 배치 스크립트 출력으로 설명해야 한다.

두 기준의 구분은 [metric_catalog.py](../../../adrag_backend/app/evaluation/metric_catalog.py) 25줄부터 명시되어 있다.

| 구분 | 내부 지표 | 기준 |
|---|---|---|
| 현재 화면 대표 시간 | `answer.first_token_ms` | 요청 시작 → 첫 답변 토큰, 평균 5초 이하 |
| PDF 시험 4 | `answer.response_time_ms` | 요청 시작 → 최종 답변 완료, 15초 목표 |

## 6. 시험 PC용 Python 스크립트에서 보여줄 위치

계산은 백엔드가 수행하고, 기존 스크립트는 API 호출·결과 다운로드·지표 출력을 담당한다.

파일: [scripts/eval_batch_query.py](../../../adrag_backend/scripts/eval_batch_query.py)

| 설명할 내용 | 함수 | 줄 |
|---|---|---:|
| 질의 파일을 일괄 평가 API로 업로드 | `_create_job()` | 62 |
| 작업 진행·완료 조회 | `_wait()` | 85 |
| CSV·Excel 결과 다운로드 | `_download()` | 97 |
| 시험 1·2·4 결과 출력 | `_print_test_metrics()` | 107 |
| 정답 근거 파일 업로드·대조 | `_upload_gold()` | 128 |
| 명령 인자와 전체 실행 흐름 | `main()` | 171 |

## 7. 현장 설명 순서

```text
scripts/eval_batch_query.py :: main()
  → 질의 업로드 API :: create_batch_job()
  → batch/runner.py :: run_job()
  → RAGService.query()
  → retrieve.py :: 의미 검색 + BM25 통합 검색
  → rerank.py :: 관련도 재평가·재정렬
  → generate_answer.py :: 근거 기반 답변 생성
  → retrieval_metrics.py :: hit_at_k(), ndcg_at_k()
  → batch/recall.py :: 전체 질의 검색 지표 집계
  → batch/runner.py :: compute_summary(), 시간 집계
  → 스크립트의 지표 출력·CSV/Excel 다운로드
```

골드셋 화면 평가를 설명할 때는 시작점을 `POST /api/eval/runs` → `eval_runner._execute_run()`으로 바꾸면 된다. 파일 일괄 평가와 골드셋 평가는 실행·집계 진입점이 다르므로 구분해서 설명한다.
