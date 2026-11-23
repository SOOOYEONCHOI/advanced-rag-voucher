# AI+ 인증 시험 평가 대본 (Recall@10 · NDCG@5 · 반환 시간)

> 기준: 운영 frontend(`adrag_frontend`)·backend(`adrag_backend`) 평가 기능 · 관련 ID: R8-7, 시험합의서 시험 1·2·4
> 표기: 🗣 말할 내용 · 🖥 화면·코드 보여주기 · ▶ 실행
> 경로: `app/…` = `adrag_backend/app/…`, `src/…` = `adrag_frontend/src/…`

---

## 0. 사전 준비

- [ ] 관리자 > 평가 > 데이터셋: 시험 데이터셋 문항 승인 후 **확정**(골드셋 생성)
- [ ] 리허설: "검색·재정렬 평가" 1회, "전체 RAG 평가" 1회 실행해서 완료되는지 확인
- [ ] 에디터에 아래 파일 탭 미리 열기
  - `src/views/EvalRunView.vue`, `src/composables/useEvalRuns.js`
  - `app/routes/evaluation.py`
  - `app/evaluation/runner/eval_runner.py`, `app/evaluation/runner/e2e_evaluator.py`
  - `app/evaluation/adapters/retrieval_adapter.py`, `reranker_adapter.py`, `rag_pipeline_adapter.py`
  - `app/evaluation/metrics/retrieval_metrics.py`, `app/evaluation/metric_catalog.py`
  - `app/graphs/nodes/retrieve.py`
- [ ] **반환 시간 판정 기준 확인**: 화면 주요 지표 4는 "첫 토큰 평균 ≤ 5초"로 판정하고, 합의서 정의(요청 → 최종 답변 완료)는 보조 지표 "전체 반환 시간"(목표 15초)으로 표시된다. 시험에서 어느 값을 볼지 미리 합의한다.

---

## 1. 도입 (1분)

🗣 "We.RAG의 관리자 평가 화면에서 시험 데이터셋으로 평가를 실행하고, 시험 1 검색 완전성(Recall@10), 시험 2 검색 최종 정합성(NDCG@5), 시험 4 답변 생성 평균 반환 시간을 확인하겠습니다."

🗣 "지표마다 ① 평가를 실행하고 ② 그 값을 만든 소스 코드를 순서대로 보여 드리겠습니다."

### 1-1. 평가 실행 흐름 (세 지표 공통, 한 번만 설명)

🖥 화면 → 코드 순서로 짚는다.

| 단계 | 🖥 화면 / 코드 |
|---|---|
| 실행 버튼 | 평가 > **평가 실행** 화면 · `src/views/EvalRunView.vue` L38–55 (골드셋·평가 범위·N/K 선택) |
| 요청 전송 | `src/composables/useEvalRuns.js` → `startRun` (L201) → `POST /api/eval/runs` |
| 실행 API | `app/routes/evaluation.py` → `create_run` (L542) → `start_run` (L601) |
| 문항별 평가 | `app/evaluation/runner/eval_runner.py` → `_execute_run` (L49) → `_evaluate_item` (L105) |
| 전체 집계·저장 | `eval_runner.py` → `_aggregate_and_save_metrics` (L331) |
| 결과 화면 | `app/routes/evaluation.py` → `get_run` (L623) → `metric_catalog.present_run_metrics` (L87) → 화면 지표 카드 |

🗣 "평가 범위가 두 가지입니다. '검색·재정렬 평가'는 답변을 만들지 않고 검색과 재정렬만 평가하고(시험 1·2), '전체 RAG 평가'는 운영 챗봇과 같이 답변까지 생성해 반환 시간을 잽니다(시험 4)."

---

## 2. 시험 1 · 검색 완전성 Recall@10

🗣 "질의마다 하이브리드 검색 상위 10개에 정답 근거 청크가 하나라도 있으면 포함으로 셉니다. 포함된 질의 수를 전체 질의 수로 나눈 값이고, 목표는 80% 이상입니다."

### 2-1. 실행

▶ 평가 실행 화면에서 골드셋 = 시험 데이터셋, 평가 범위 = **검색·재정렬 평가**, N = 10, K = 5 → **실행 시작**
🖥 실행 이력의 진행률이 120/120이 되면 해당 실행을 선택한다.
🖥 "검색 품질 (지표 1·2)" 카드의 **검색 완전성 Recall@10** 값과 만족/불만족 표시를 보여 준다.

### 2-2. 소스 코드 확인

| # | 🗣 확인 항목 | 🖥 보여줄 코드 |
|---|---|---|
| 1 | 시험 데이터·정답 데이터 불러오기 | `eval_runner.py` → `_execute_run` L55–57: 골드셋 스냅샷(`items_snapshot_json`)에서 질의·정답 청크ID 로드 / `_evaluate_retrieval` L225–226: `question`, `gold_ids` |
| 2 | 임베딩 모델·하이브리드 검색 구성 요소 불러오기 | `retrieval_adapter.py` → `EvalRetriever.__init__` L62–68: `get_vector_repo()`(Qdrant), `get_embedding_client()`(임베딩), Dense·Kiwi BM25 채널 |
| 3 | 의미 검색 + BM25 키워드 검색 | `eval_runner.py` → `_evaluate_retrieval` L244–249 → `retrieval_adapter.py` → `search_rrf` (L126) → `retrieve.py` → `_search_qdrant_hybrid` (L79): `embed_query`(의미 검색) + `encode_query`(BM25) |
| 4 | 통합 후 상위 10개 추출 | `retrieve.py` L111–124 → `vector_repository.py` → `search_hybrid` (L572, RRF 통합) → `retrieval_adapter.py` L165–166 `boosted[:top_k]` (top_k = N = 10) |
| 5 | 정답 포함 여부 비교 | `eval_runner.py` L250–255 → `retrieval_metrics.py` → `compute_channel_metrics` (L122) → `hit_at_k` (L39) |
| 6 | 전체 Recall@10 산출 | `eval_runner.py` → `_aggregate_and_save_metrics` L391–398(키 `retrieval.rrf.hit@10` 수집) → L453–457(합계 ÷ 전체 질의 수) / 키 정의 `metric_catalog.py` L18, L46–47 |

🗣 (5번에서) "합의서 정의가 '정답이 포함된 질의 비율'이라 코드에서는 `hit_at_k` 함수로 계산합니다. 같은 청크가 여러 번 나오면 중복을 제거한 순위로 봅니다(`_dedup_preserve_order` L13)."
🗣 (6번에서) "검색 오류나 정답이 없는 질의도 0으로 세고, 분모는 전체 질의 수입니다."

🖥 (선택) 문항 표에서 한 건을 눌러 **QA 결과 상세 > 채널별 검색 결과**와 **정답 근거 청크 원문**을 대조해 보여 준다.

---

## 3. 시험 2 · 검색 최종 정합성 NDCG@5

🗣 "하이브리드 검색 결과를 Reranker 모델로 다시 정렬하고, 상위 5개 안에 정답이 얼마나 높은 순위로 있는지 NDCG@5로 계산합니다. 질의별 값을 평균하고, 목표는 0.8 이상입니다."

### 3-1. 실행

🖥 시험 1과 **같은 실행 결과**에서 **검색 최종 정합성 NDCG@5** 카드를 보여 준다. (같은 "검색·재정렬 평가" 1회로 두 지표가 함께 계산된다.)

### 3-2. 소스 코드 확인

| # | 🗣 확인 항목 | 🖥 보여줄 코드 |
|---|---|---|
| 1 | 시험 데이터·정답 데이터 불러오기 | `eval_runner.py` → `_execute_run` L55–57: 골드셋 스냅샷에서 질의·정답 청크ID 로드 / `_evaluate_retrieval` L225–228: `question`, `gold_ids`, `rerank_top_k`(K=5) |
| 2 | 임베딩 모델·Reranker 모델 불러오기 | 임베딩: `EvalRetriever.__init__` L62–68 / Reranker: `reranker_adapter.py` → `_get_client` (L15): `RerankerClient(get_settings())` |
| 3 | 의미 검색 + BM25 키워드 검색 | `eval_runner.py` L264–267: 운영과 같은 후보 수(`candidate_top_k`)로 `search_rrf` 호출 |
| 4 | Reranker로 관련도 평가·재정렬 | `eval_runner.py` L269 → `reranker_adapter.py` → `EvalReranker.rerank` (L25): 중복 제거 `dedup_chunks_by_text` → `_build_rerank_text` → `RerankerClient.rerank` (L50) |
| 5 | 상위 5개 vs 정답 → 질의별 NDCG@5 | `eval_runner.py` L270–273 → `compute_channel_metrics` → `retrieval_metrics.py` → `ndcg_at_k` (L82) |
| 6 | 전체 평균 | `_aggregate_and_save_metrics`: 키 `retrieval.rerank.ndcg@5` → L453–457 (합계 ÷ 전체 질의 수) / 키 정의 `metric_catalog.py` L19, L48–49 |

🗣 (4번에서) "Reranker 입력은 운영 챗봇의 재랭킹 노드와 같게 문서명·섹션 머리말을 붙인 본문입니다."
🗣 (5번에서) "정답 청크면 관련도 1, 아니면 0입니다. 순위 i의 점수 1/log₂(i+1)를 더한 값(DCG)을, 정답이 1위부터 채워진 이상적인 경우(IDCG)로 나눕니다."

---

## 4. 시험 4 · 답변 생성 평균 반환 시간

🗣 "운영 챗봇과 같은 RAG 파이프라인으로 질의를 1건씩 순서대로 실행합니다. 질의마다 답변 생성 요청을 시작한 시점부터 문서 검색, 재랭킹, 최종 답변 생성이 끝날 때까지 시간을 재고 평균을 냅니다."

### 4-1. 실행

▶ 평가 실행 화면에서 골드셋 = 시험 데이터셋, 평가 범위 = **전체 RAG 평가** → **실행 시작**
🖥 완료 후 "답변 품질" 카드의 **답변 생성 평균 반환 시간**, 보조 지표의 **전체 반환 시간**을 보여 준다.
🖥 문항 표의 시간 열(첫 토큰 / 전체)로 질의별 값을 보여 준다.

### 4-2. 소스 코드 확인

| # | 🗣 확인 항목 | 🖥 보여줄 코드 |
|---|---|---|
| 1 | 시험 데이터 불러오기 | `eval_runner.py` → `_execute_run` L55–57 (골드셋 스냅샷) |
| 2 | We.RAG에 질의별 답변 생성 요청 | `eval_runner.py` → `_evaluate_item` L119–124 → `e2e_evaluator.py` → `evaluate_end_to_end` (L57, L70–75) → `rag_pipeline_adapter.py` → `EvalRagPipeline.run` (L61) → 운영 RAG 그래프 `ainvoke` (L97) / 순차 실행 `Semaphore(1)` (`eval_runner.py` L68) |
| 3 | 요청 시작 → 검색·재랭킹·답변 완료 시간 측정 | `rag_pipeline_adapter.py` L95 `started = time.monotonic()` → L97 그래프 실행(질의 분석 → 검색 → 재랭킹 → 답변 생성) → L98 `latency_ms` / 첫 토큰: `app/graphs/nodes/generate_answer.py` L70–71 → adapter L100–105 |
| 4 | 질의별 반환 시간 저장 | `e2e_evaluator.py` L80 `fields["latency_ms"]` → `eval_runner.py` `_timing_metrics` (L138) → `app/repositories/evaluation_repository.py` → `insert_item_result` (L597) |
| 5 | 평균 반환 시간 산출 | `eval_runner.py` → `_aggregate_and_save_metrics` L439–441 → `MetricAggregate.from_results` (`app/evaluation/metrics/models.py` L42) / 키 `answer.response_time_ms`·`answer.first_token_ms` (`metric_catalog.py` L21–22) |

🗣 (2번에서) "평가 전용 경로가 아니라 운영 챗봇이 쓰는 RAG 그래프를 그대로 호출합니다. 답변 시간이 서로 영향을 주지 않게 질의를 1건씩 순서대로 실행합니다."
🗣 (3번에서) "시간은 그래프 실행 구간만 잽니다. 그 뒤 지표 계산 시간은 넣지 않습니다."
🗣 (5번에서) "측정이 빠진 질의가 있으면 일부 평균을 공식 값으로 보여 주지 않습니다(L450–452)."

---

## 5. 마무리 (1분)

🖥 실행 이력의 **평가 결과 Excel 다운로드** → 질의별 지표·시간 확인
- 코드: `app/routes/evaluation.py` → `GET /eval/runs/{run_id}/results.xlsx` (L640), `app/evaluation/excel_exporter.py`

🗣 "세 지표 결과는 실행 이력으로 저장돼 다시 열어 볼 수 있고, 질의별 결과는 Excel로 받을 수 있습니다."

---

## 예상 질문 대응

| 질문 | 답변 |
|---|---|
| Recall@10인데 왜 `hit_at_k`인가요? | 합의서 정의가 "정답 근거 청크가 1개 이상 포함된 질의 비율"이기 때문입니다. `recall_at_k`는 정답 청크 커버율로, 보조 지표로 따로 보여 줍니다. |
| 검색·재정렬 평가에서 LLM 질의 재작성을 하나요? | 하지 않습니다. 시험 질의 원문으로 검색합니다(`retrieval_adapter.py` `_build_eval_query_bundle` L42). 전체 RAG 평가는 운영과 같이 재작성까지 포함합니다. |
| 같은 청크가 여러 번 나오면? | 중복을 제거한 순위로 계산합니다(`retrieval_metrics.py` `_dedup_preserve_order` L13). |
| 오류 난 질의는 어떻게 세나요? | Recall@10·NDCG@5는 0으로 세고 분모는 전체 질의 수입니다(`eval_runner.py` L453–457, `metric_catalog.ALL_DENOMINATOR_KEYS`). |
| 반환 시간에 네트워크 시간이 포함되나요? | 서버 안에서 RAG 그래프를 실행한 시간이라 네트워크 전송 시간은 포함되지 않습니다. |
| 주요 지표 4는 첫 토큰 기준인데 합의서는 최종 완료 기준 아닌가요? | 화면 주요 카드는 첫 토큰 평균이고, 합의서 정의(최종 답변 완료)는 보조 지표 "전체 반환 시간"으로 함께 보여 줍니다. |
