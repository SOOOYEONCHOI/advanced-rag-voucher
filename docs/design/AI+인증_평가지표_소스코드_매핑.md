# AI+ 인증 평가 지표 — 소스 코드 매핑 (Recall@10 · NDCG@5 · 반환 시간)

> 작성 2026-11-23 · 관련 ID: R8-7, 시험합의서 시험 1·2·4, UI 평가 실행(EvalRunView)
> 경로는 저장소 루트 기준. 줄 번호는 2026-11-23 작업본 기준(수정 시 달라질 수 있음).

시연은 두 갈래로 나뉜다.

- **A. UI에서 평가를 실행하는 경로**: 관리자 > 평가 > 평가 실행 화면 → `POST /api/eval/runs` → `eval_runner`
- **B. 시험 PC에서 실행하는 스크립트**: `adrag_backend/scripts/aiplus_test1_recall10.py`, `aiplus_test2_ndcg5.py`, `aiplus_test4_latency.py`

두 경로는 **같은 지표 계산 함수**(`app/evaluation/metrics/retrieval_metrics.py`)와 **같은 운영 검색 함수**(`app/graphs/nodes/retrieve.py`의 `_search_qdrant_hybrid`), **같은 Reranker 클라이언트**를 쓴다.

---

## 0. 공통 구성 요소 (세 지표 모두에서 가리키게 될 코드)

| 구분 | 파일 | 함수·클래스 | 하는 일 |
|---|---|---|---|
| 임베딩 모델 클라이언트 | `adrag_backend/app/clients/embedding_client.py` | `EmbeddingClient.embed_query` (L169), `embed_texts` (L116) | GPU 서버의 임베딩 모델에 질의 벡터 요청 |
| BM25 질의 인코더 | `adrag_backend/app/clients/kiwi_bm25_encoder.py` | `KiwiBm25Encoder.encode_query` (L58) | Kiwi 형태소 분석 → BM25 sparse 질의 |
| 벡터 DB(Qdrant) | `adrag_backend/app/repositories/vector_repository.py` | `search_hybrid` (L572), `search_kiwi_bm25` (L648) | Dense·BM25 prefetch 2개 → Qdrant 서버측 가중 RRF 통합 |
| 하이브리드 검색 본체 | `adrag_backend/app/graphs/nodes/retrieve.py` | `_search_qdrant_hybrid` (L79), `retrieve` 노드 (L130), 클라이언트 getter `get_embedding_client`(L51)·`get_vector_repo`(L55)·`get_kiwi_bm25_encoder`(L64) | ① 임베딩 → ② BM25 인코딩 → ③ `search_hybrid` 호출 |
| 키워드 가산 재정렬 | `adrag_backend/app/graphs/retrieval_engine.py` | `apply_soft_boost` (L492), `classify_query_type` (L79) | 키워드 일치 가산 후 재정렬 |
| Reranker 모델 클라이언트 | `adrag_backend/app/clients/reranker_client.py` | `RerankerClient.rerank` (L64) | GPU 서버 Reranker(vLLM score API) 호출 → (원본 순번, 점수) |
| 재랭킹 노드 | `adrag_backend/app/graphs/nodes/rerank.py` | `rerank` (L90), `_build_rerank_text` (L47) | 중복 제거 → `[문서명]·[섹션]` 머리말 + 본문 → Reranker |
| 본문 중복 제거 | `adrag_backend/app/graphs/utils.py` | `dedup_chunks_by_text` (L23) | 같은 본문 청크 제거 |
| **지표 계산(순수 함수)** | `adrag_backend/app/evaluation/metrics/retrieval_metrics.py` | `hit_at_k` (L39), `recall_at_k` (L51), `ndcg_at_k` (L82), `first_rank` (L108), `gold_ranks` (L100), `compute_channel_metrics` (L122), `_dedup_preserve_order` (L13) | 상위 k 안 정답 포함·NDCG 계산 |
| 지표 정의·목표값 | `adrag_backend/app/evaluation/metric_catalog.py` | `AGREEMENT_RECALL_KEY="retrieval.rrf.hit@10"` (L18), `AGREEMENT_NDCG_KEY="retrieval.rerank.ndcg@5"` (L19), `RESPONSE_TIME_KEY`·`FIRST_TOKEN_KEY` (L21–22), `ALL_DENOMINATOR_KEYS` (L24), `metric_catalog` (L42), `present_run_metrics` (L87) | 화면 주요 지표 키·라벨·목표·계산식 문구 |
| 집계 모델 | `adrag_backend/app/evaluation/metrics/models.py` | `MetricResult` (L11), `MetricAggregate.from_results` (L42) | 항목 결과 → 평균·건수 |

> **용어 주의**: 합의서의 "검색 완전성(Recall@10)"은 *질의 단위 포함 여부*(상위 10개에 정답 근거 청크가 1개 이상 있으면 1)이므로 코드에서는 `hit_at_k(…, 10)`, 화면 키는 `retrieval.rrf.hit@10`이다. `recall_at_k`(정답 청크 커버율)는 보조 지표다.

---

## A. UI에서 평가 실행 — 공통 흐름

| 단계 | 파일 | 함수 |
|---|---|---|
| 시험 데이터셋 확정(골드셋 생성) | `adrag_frontend/src/composables/useEvalDatasets.js` → `adrag_backend/app/routes/evaluation.py` → `app/repositories/evaluation_repository.py` | `finalizeDataset` (L604) → `finalize_dataset` (L494–509) → `create_goldset` (L362): 승인 문항을 `tb_eval_goldsets.items_snapshot_json`에 스냅샷 |
| 시험 데이터셋 Excel(스크립트 입력 파일) | `adrag_backend/app/routes/evaluation.py` | `download_testset_excel` (L329, `GET /eval/datasets/{id}/test-set.xlsx`) — '질의'·'정답 근거' 시트 |
| 실행 버튼 | `adrag_frontend/src/views/EvalRunView.vue` (L38–55) / `adrag_frontend/src/composables/useEvalRuns.js` | 평가 범위 select(`retrieval`=검색·재정렬, `full`=전체 RAG) · `startRun` (L201) → `evalApi.createRun` |
| 실행 API | `adrag_backend/app/routes/evaluation.py` | `create_run` (L542, `POST /eval/runs`) → `start_run` 호출 (L601–602) |
| 백그라운드 실행 | `adrag_backend/app/evaluation/runner/eval_runner.py` | `start_run` (L43) → `_execute_run` (L49) → 문항별 `_evaluate_item` (L105) |
| 문항 결과 저장 | `adrag_backend/app/repositories/evaluation_repository.py` | `insert_item_result` (L597) → `tb_eval_item_results` |
| 전체 집계·저장 | `eval_runner.py` / `evaluation_repository.py` | `_aggregate_and_save_metrics` (L331) → `save_run_metrics` (L727) |
| 결과 조회·화면 | `app/routes/evaluation.py` / `useEvalRuns.js` | `get_run` (L623) + `present_run_metrics` → `primaryKpis` (L126), 문항 표 `hit10Metric`·`ndcg5Metric`·`firstTokenMs` (L307–310) |

---

## 지표 1. 검색 완전성 Recall@10

### 1-1. 소스 코드 확인 항목별 위치

| 확인 항목 | A. UI 평가 (`scope=retrieval`, 검색·재정렬 평가) | B. 시험 스크립트 `aiplus_test1_recall10.py` |
|---|---|---|
| ① 시험 데이터·정답 데이터 불러오기 | `eval_runner._execute_run` L55–57: `repo.get_goldset()` → `items_snapshot_json`(질의·`gold_chunk_ids`) / `_evaluate_retrieval` L225–226: `question`, `gold_ids = set(_parse_json_list(item["gold_chunk_ids"]))` | `run()` L41–43 → `scripts/aiplus_common.py` `load_testset` (L63, '질의'·'정답 근거' 시트), `_rows` (L37), `split_chunk_ids` (L58), `assign_collections` (L102) |
| ② 임베딩 모델·하이브리드 검색 구성 요소 불러오기 | `app/evaluation/adapters/retrieval_adapter.py` `EvalRetriever.__init__` (L62–68): `get_vector_repo()`, `get_embedding_client()`, `DenseChannel`·`KiwiBm25Channel` | `run()` L45–47 → `scripts/aiplus_search.py` `load_components(with_reranker=False)` (L35): `default_graph_dependencies()` → `container.embedding`·`kiwi_bm25_encoder`·`vector_store`·`query_preprocessor` / 설정 출력 `describe` (L57) |
| ③ 의미 검색 + BM25 키워드 검색 수행 | `eval_runner._evaluate_retrieval` L244–255 → `EvalRetriever.search_rrf` (L126) → `retrieve._search_qdrant_hybrid` (L79): `embed_query` + `encode_query` + `search_hybrid` (채널 단독 비교용: `search_channel` L77, `_search_sparse_only` L103) | L54–56 `hybrid_search` (`aiplus_search.py` L93) → 운영 `retrieve` 노드 (L130) → `_search_qdrant_hybrid` |
| ④ 통합 후 질의별 상위 10개 추출 | Qdrant 가중 RRF 통합(`vector_repository.search_hybrid` L572, `Rrf(k=rrf_k)` L624) → `apply_soft_boost` → `boosted[:top_k]` (`retrieval_adapter.py` L165–166, `top_k`=화면 N 기본 10) | `top_k_chunk_ids(found["chunks"], 10)` (L30, 중복 ID 제거 후 10개), `TOP_K = 10` (L27) |
| ⑤ 상위 10개와 정답 비교(포함 여부) | `compute_channel_metrics(retrieved_ids, gold_ids, k_values)` (`eval_runner.py` L253) → `hit_at_k(…, 10)` (`retrieval_metrics.py` L39) | L63–65: `hit_at_k(top_ids, gold_chunk_ids, 10)`, `first_rank(…)` |
| ⑥ 전체 시험 데이터 Recall@10 산출 | `_aggregate_and_save_metrics` (L331): 키 `retrieval.rrf.hit@10` 수집 (L391–398) → `MetricAggregate.from_results` (L447) → **분모 = 전체 질의 수** 보정 (L453–457, `ALL_DENOMINATOR_KEYS`) → `save_run_metrics` | L77–79: `recall = hits / total * 100` · 결과 저장 `write_csv`·`write_json` (`aiplus_common.py` L116·L125) · 판정 `pass = recall >= 80.0` |

### 1-2. 스크립트 실행
```bash
# 백엔드 실행 환경(컨테이너 또는 같은 .env 가상환경), adrag_backend 폴더
python scripts/aiplus_test1_recall10.py --file 시험데이터셋.xlsx --collection-map "법령=컬렉션,..." --out ./aiplus_result
```
출력: 화면 `Recall@10 = xx.xx% (hit/total)`, `test1_recall10_items.csv`(질의별 포함 여부·첫 순위·상위 10), `test1_recall10_summary.json`.

---

## 지표 2. 검색 최종 정합성 NDCG@5

### 2-1. 소스 코드 확인 항목별 위치

| 확인 항목 | A. UI 평가 (`scope=retrieval`) | B. 시험 스크립트 `aiplus_test2_ndcg5.py` |
|---|---|---|
| ① 시험 데이터·정답 데이터 불러오기 | 지표 1과 같음 (`_execute_run` L55–57, `_evaluate_retrieval` L225–226) | `run()` L32–34 → `load_testset` |
| ② 임베딩 모델·Reranker 모델 불러오기 | 임베딩: `EvalRetriever.__init__` (L62–68) / Reranker: `app/evaluation/adapters/reranker_adapter.py` `_get_client` (L15, `RerankerClient(get_settings())`) | `run()` L36–38 → `load_components(with_reranker=True)` (`aiplus_search.py` L35, `container.reranker`, `ENABLE_RERANKING` 확인) |
| ③ 의미 검색 + BM25 키워드 검색 | `_evaluate_retrieval` L264–267: 운영과 같은 후보 수 `candidate_top_k`로 `search_rrf` 재호출 | L45–47 `hybrid_search` |
| ④ Reranker로 관련도 평가·재정렬 | `_evaluate_retrieval` L269 → `EvalReranker.rerank` (`reranker_adapter.py` L25): `dedup_chunks_by_text` → `_build_rerank_text` → `RerankerClient.rerank(query, documents, top_k)` (L44–54) | L48–50 `rerank_chunks` (`aiplus_search.py` L114) → 운영 `rerank` 노드 (`rerank.py` L90) |
| ⑤ 재정렬 상위 5개 vs 정답 → 질의별 NDCG@5 | `compute_channel_metrics(reranked_ids, gold_ids, …)` (`eval_runner.py` L271–273) → `ndcg_at_k(…, 5)` (`retrieval_metrics.py` L82: DCG=Σ1/log2(i+1), IDCG=min(정답 수,5)개 이상 순위) | L60–61: `ndcg_at_k(top_ids, gold_chunk_ids, 5)`, `gold_ranks` |
| ⑥ 전체 평균 | `_aggregate_and_save_metrics`: 키 `retrieval.rerank.ndcg@5` → 분모 전체 질의 수 (L453–457) | L74–76: `mean_ndcg = ndcg_sum / total` · `pass = mean_ndcg >= 0.8` |

### 2-2. 스크립트 실행
```bash
python scripts/aiplus_test2_ndcg5.py --file 시험데이터셋.xlsx --collection-map "법령=컬렉션,..." --out ./aiplus_result
```
출력: `NDCG@5 = 0.xxxx (xx.xx%)`, `test2_ndcg5_items.csv`(질의별 NDCG·정답 순위·재랭킹 점수), `test2_ndcg5_summary.json`.

---

## 지표 3. 답변 생성 평균 반환 시간

### 3-1. 소스 코드 확인 항목별 위치

| 확인 항목 | A. UI 평가 (`scope=full`, 전체 RAG 평가) | B. 시험 스크립트 `aiplus_test4_latency.py` (시험 PC) |
|---|---|---|
| ① 시험 데이터 불러오기 | `_execute_run` L55–57 (골드셋 스냅샷) | `main()` L127–129 → `load_testset(args.file, with_gold=False)` |
| ② We.RAG에 입력해 답변 생성 요청 | `_evaluate_item` L119–124 → `e2e_evaluator.evaluate_end_to_end` (L57) → `rag_pipeline_adapter.EvalRagPipeline.run` (L61) → `_get_graph().ainvoke(initial_state)` (L97, 운영 RAG 그래프: 질의 분석→검색→재랭킹→답변 생성) · **순차 실행** `Semaphore(1)` (`eval_runner.py` L68) | `ask()` (L57): `POST /api/query/stream` SSE (챗봇과 같은 API, 서버 `app/routes/query.py` `rag_query_stream` L204) · 로그인 `login()` (L45) · 1건씩 순서대로 (L144–147) |
| ③ 요청 시작 → 검색·재랭킹·답변 완료 시간 측정 | 시작 `started = time.monotonic()` (`rag_pipeline_adapter.py` L95) → 완료 `latency_ms` (L98) / 첫 토큰: `generate_answer.py` L70–71 `timing[FIRST_TOKEN_AT_KEY]=time.time()` → `first_token_ms` (adapter L100–105) | 시작 `started = time.perf_counter()` (L61) → 첫 `token` 이벤트 `first_token_ms` (L82) → `done` 이벤트 `total_ms` (L93) |
| ④ 질의별 반환 시간 저장 | `evaluate_end_to_end` L80 `fields["latency_ms"]`, `timing_json` → `_evaluate_item` L127–130 → `_timing_metrics` (L138) → `insert_item_result` (`tb_eval_item_results.latency_ms`) | `results.append`·`rows.append` (L147–151) → `write_csv(test4_latency_items.csv)` (L162) |
| ⑤ 전체 평균 | `_aggregate_and_save_metrics` L439–441 (`answer.response_time_ms`, `answer.first_token_ms`) → `MetricAggregate.from_results` · 누락 있으면 공식 평균 미표시 (L450–452) | L157–160 `stats()` (L102, `statistics.fmean`) · 분모 = 전체 질의 수(오류 질의 포함) |

### 3-2. 스크립트 실행 (시험 PC, httpx·openpyxl만 필요)
```bash
set AIPLUS_USER_ID=<시험 계정>   &  set AIPLUS_PASSWORD=<비밀번호>
python aiplus_test4_latency.py --base-url <We.RAG 주소> --file 시험데이터셋.xlsx --collection-map "..." --warmup-query "<워밍업 질의>" --out ./aiplus_result
```
시험 PC에는 `aiplus_test4_latency.py` + `aiplus_common.py` 두 파일을 같이 둔다.

---

## 시연 전 확인할 차이점 (설명 시 질문받기 쉬운 부분)

1. **UI 검색·재정렬 평가와 스크립트의 질의 전처리가 다르다.**
   - UI(`retrieval_adapter._build_eval_query_bundle` L42): 정규화만, `classify_query_type({})`·`apply_soft_boost(keywords=[])` → 규칙 전처리(약어 확장·조문 패턴·키워드) **미적용**.
   - 스크립트(`aiplus_search._initial_state` L71): 운영 `query_preprocessor` 규칙 전처리 **적용**, LLM 재작성만 미적용.
   - UI 전체 RAG 평가(`full`)는 LLM 질의 재작성까지 포함한 운영 그래프 그대로다.
   → 같은 데이터셋이라도 UI 값과 스크립트 값이 다를 수 있다. 공식 수치는 스크립트 출력으로 제시하고, UI는 "같은 지표 함수로 화면에서 확인"하는 용도로 설명하는 것을 권장.
2. **반환 시간 목표값이 세 곳에서 다르다.** (TODO(결정필요))
   - `metric_catalog.py` L25 `RESPONSE_TIME_TARGET_MS = 15_000`(주석: 합의서 시험 4 = 최종 완료 ≤ 15초)
   - 화면 주요 지표 4는 **첫 토큰 평균 ≤ 5초**(`FIRST_TOKEN_TARGET_MS`, L29, 사용자 결정), 최종 완료 시간은 보조 지표.
   - `aiplus_test4_latency.py` L42 `TARGET_MS = 5000`을 **최종 완료와 첫 토큰 모두에** 적용(L180–181).
   → 합의서의 목표값을 확인해 스크립트 판정 기준을 맞출 필요가 있다.
3. **측정 구간 차이**: UI `full`은 서버 내부 그래프 실행 시간(HTTP·스트리밍 전송 제외), 스크립트는 시험 PC에서 HTTP 요청 직전 → `done` 이벤트 수신까지(네트워크 포함). 합의서 문구("요청 시점부터 최종 답변 생성 완료 시점까지")에는 스크립트 쪽이 더 가깝다.
4. `metric_catalog.py` L28 주석은 시험 4 스크립트를 `scripts/eval_batch_query.py`로 적고 있으나, 현재 합의서용 스크립트는 `scripts/aiplus_test4_latency.py`다.
