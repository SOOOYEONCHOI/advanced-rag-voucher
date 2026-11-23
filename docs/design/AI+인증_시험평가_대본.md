# AI+ 인증 시험 평가 대본 (Recall@10 · NDCG@5 · 반환 시간)

> 기준: 관리자 평가 화면(frontend)·평가 코드(backend) · 관련 ID: R8-7, 시험합의서 시험 1·2·4
> 경로는 `adrag_backend/app/` 기준 · 줄 번호는 커밋 `8d5c6c2` 코드 기준 · 에디터에서 `[AI+ 시험] Recall@10 - 1)`처럼 검색하면 표의 위치가 모두 나온다
> 표기: 🗣 말할 내용 · 🖥 보여주기 · ▶ 실행 · 코드 발췌는 HTML 대본(`AI+인증_시험평가_대본.html`)에 있다

---

## 0. 사전 준비

- [ ] 관리자 > 평가 > 데이터셋: 시험 데이터셋 문항 승인 후 **확정**(골드셋 생성)
- [ ] 리허설: "검색·재정렬 평가" 1회, "전체 RAG 평가" 1회 실행해서 완료되는지 확인
- [ ] 에디터에서 `adrag_backend` 폴더를 열고, 전체 검색창에 `[AI+ 시험]`을 넣어 둔다
- [ ] **반환 시간 판정 기준 합의**: 화면 주요 지표 4는 **첫 토큰 평균 ≤ 5초**로 판정합니다. 합의서 정의(요청 → 최종 답변 완료)는 보조 지표 **“전체 반환 시간”**(목표 15초)으로 표시됩니다. 시험에서 어느 값을 볼지 담당자와 먼저 정해 두세요.

## 1. 도입 (1분)

🗣 “관리자 평가 화면에서 시험 데이터셋으로 평가를 실행하고, 시험 1 검색 완전성(Recall@10), 시험 2 검색 최종 정합성(NDCG@5), 시험 4 답변 생성 평균 반환 시간을 확인하겠습니다. 지표마다 합의서의 소스 코드 확인 항목을 실행 순서대로 보여 드린 뒤, 평가 결과를 확인하겠습니다. 코드에는 항목마다 `[AI+ 시험]` 주석을 달아 두어 바로 찾을 수 있습니다.”

**평가가 시작되는 경로 (한 번만 설명)**

실행 버튼(`EvalRunView.vue` L38–55) → 요청(`useEvalRuns.startRun` L201) → API(`POST /api/eval/runs` · `routes/evaluation.py create_run` L542) → 백그라운드 실행(`eval_runner.start_run` L43 → `_execute_run` L49) → 문항마다 반복(`asyncio.gather(*[_process(item) for item in items])` L94)

🗣 “실행 버튼을 누르면 API가 평가 실행을 등록하고 백그라운드 작업을 시작합니다. 작업은 시험 문항을 하나씩 꺼내(L94) 평가하고, 끝나면 전체를 집계합니다. 평가 범위는 두 가지입니다. ‘검색·재정렬 평가’는 답변 없이 검색과 재정렬만 평가하고(시험 1·2), ‘전체 RAG 평가’는 운영 챗봇과 같이 답변까지 생성해 시간을 잽니다(시험 4).”

---

## 2. 시험 1 · 검색 완전성 Recall@10

🗣 “질의마다 하이브리드 검색 상위 10개에 정답 근거 청크가 하나라도 있으면 ‘포함’으로 셉니다. 포함된 질의 수를 전체 질의 수로 나눈 값이고, 목표는 80% 이상입니다.”

### 소스 코드 확인

#### 1) 시험 데이터 및 정답 데이터를 불러오는 코드
_검색어: [AI+ 시험] Recall@10 - 1)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _execute_run | L58–61 |
| ② | `repositories/evaluation_repository.py` | EvalRepository.get_goldset | L500 |
| ③ | `evaluation/runner/eval_runner.py` | _evaluate_retrieval | L238–240 |

**설명**

- ① 평가 실행 1회에 한 번 실행됩니다. 화면에서 고른 골드셋 ID로 시험 데이터셋을 가져옵니다. 시험 문항 전체(질의문·정답 청크ID)가 `items_snapshot_json`에 JSON으로 들어 있어서, `json.loads`로 문항 목록 `items`로 바꿉니다. 검색할 컬렉션 이름도 함께 읽습니다.
- ② 실제 DB 조회입니다. 골드셋 테이블 `tb_eval_goldsets`에서 해당 골드셋 한 건을 읽습니다. 데이터셋·컬렉션 테이블을 함께 연결해 검색 대상 컬렉션(`qdrant_name`)을 얻습니다.
- ③ 문항마다 한 번씩 실행됩니다(L94의 반복). 문항에서 검색에 넣을 **질의문**과 비교에 쓸 **정답 청크ID**를 꺼냅니다. 정답 청크ID는 JSON 문자열이라 리스트로 바꾸고 `set`(집합)으로 만듭니다. 집합이면 중복이 없고, 뒤에서 “이 청크가 정답인가”를 빠르게 확인할 수 있습니다. `top_k`는 화면에서 넣은 검색 후보 수 N(=10)입니다.

🗣 **요약** “확정된 시험 데이터셋을 DB에서 한 번 읽어 오고, 문항마다 질의문과 정답 청크ID를 꺼내 씁니다.”

#### 2) 임베딩 모델 및 하이브리드 검색에 필요한 구성 요소를 불러오는 코드
_검색어: [AI+ 시험] Recall@10 - 2)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _evaluate_retrieval | L255 |
| ② | `evaluation/adapters/retrieval_adapter.py` | EvalRetriever.__init__ | L67–72 |
| ③ | `graphs/nodes/retrieve.py` | get_embedding_client · get_vector_repo · get_kiwi_bm25_encoder | L54 · L59 · L70 |
| ④ | `core/container.py` | _EMBEDDING_FACTORIES · _VECTOR_STORE_FACTORIES · PipelineContainer.kiwi_bm25_encoder | L43 · L45 · L96 |
| ⑤ | `clients/embedding_client.py` | EmbeddingClient.__init__ | L33 |
| ⑥ | `clients/kiwi_bm25_encoder.py` | KiwiBm25Encoder.__init__ | L21–26 |

**설명**

- ① 평가 코드가 검색기(`EvalRetriever`)를 만듭니다. 바로 아래 하이브리드 검색에서 이 검색기를 씁니다.
- ② 검색기가 만들어질 때 **Qdrant 벡터 DB**와 **임베딩 모델 클라이언트**를 받아 옵니다. `_channels`는 의미 검색만, BM25만 따로 비교할 때 쓰는 보조용입니다.
- ③ 받아 오는 함수는 운영 챗봇 검색 노드(`retrieve.py`)의 함수입니다. 세 함수 모두 공용 컨테이너에 맡깁니다. 그래서 **평가와 운영 챗봇이 같은 객체**를 씁니다.
- ④ 컨테이너가 실제로 객체를 만드는 곳입니다. 임베딩 클라이언트, Qdrant 연결(호스트·포트·BM25 벡터 이름), BM25 인코더를 처음 요청받을 때 한 번만 만들고 이후에는 재사용합니다. 그래서 문항마다 다시 연결하지 않습니다.
- ⑤ 임베딩 모델 설정입니다. 모델 이름(`embedding_model_name`)과 GPU 서버 주소를 설정값에서 읽습니다. 모델은 GPU 서버(vLLM)에서 돌고, 여기서는 그 서버를 부르는 클라이언트를 준비합니다.
- ⑥ BM25 키워드 검색 설정입니다. BM25 계산 상수(k1, b, 평균 문서 길이)와 Kiwi 형태소 토큰 정책을 정합니다. 문서를 적재할 때와 같은 정책이라, 질의와 문서가 같은 기준으로 단어가 나뉩니다.

🗣 **요약** “의미 검색용 임베딩 모델, 키워드 검색용 BM25 인코더, 두 검색을 수행하는 Qdrant 벡터 DB 세 가지를 운영 챗봇과 같은 공용 객체로 불러옵니다.”

#### 3) 시험 데이터를 입력하여 임베딩 기반 의미 검색과 BM25 기반 키워드 검색을 수행하는 코드
_검색어: [AI+ 시험] Recall@10 - 3)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _evaluate_retrieval | L262 |
| ② | `evaluation/adapters/retrieval_adapter.py` | _build_eval_query_bundle | L44–58 |
| ③ | `evaluation/adapters/retrieval_adapter.py` | EvalRetriever.search_rrf | L149 |
| ④ | `graphs/nodes/retrieve.py` | _search_qdrant_hybrid | L96–107 |
| ⑤ | `clients/embedding_client.py` | EmbeddingClient.embed_query | L171–180 |
| ⑥ | `clients/kiwi_bm25_encoder.py` | KiwiBm25Encoder.encode_query | L61–66 |

**설명**

- ① 시험 질의문(`question`)을 검색기에 넣어 하이브리드 검색을 요청합니다. 상위 `top_k`(=10)개를 받습니다.
- ② 검색 입력을 만듭니다. LLM으로 질의를 바꾸지 않고 **시험 질의 원문** 그대로 씁니다. 의미 검색에는 원문(`dense_queries`)을, 키워드 검색에는 정규화한 원문(`kiwi_bm25_query`)을 넣습니다.
- ③ 운영 챗봇과 같은 하이브리드 검색 함수 `_search_qdrant_hybrid`를 호출합니다.
- ④ 두 검색의 질의를 동시에 준비합니다. `embed_query`로 질의를 숫자 벡터로 바꾸고(의미 검색), `encode_query`로 BM25 키워드 질의를 만듭니다(키워드 검색).
- ⑤ **의미 검색 질의**: 질의 앞에 모델 권장 안내문(instruct)을 붙여 GPU 서버 임베딩 모델에 보내고, 받은 벡터를 정규화합니다. 뜻이 비슷한 문서를 찾는 데 씁니다.
- ⑥ **키워드 검색 질의**: Kiwi 형태소 분석으로 질의를 단어로 나누고(`normalize_query`) Qdrant BM25 형식으로 만듭니다. 같은 단어가 들어 있는 문서를 찾는 데 씁니다.

🗣 **요약** “시험 질의 원문을 임베딩 모델로 벡터로 바꿔 의미 검색을, Kiwi 형태소 분석으로 키워드로 바꿔 BM25 검색을 합니다. 운영 챗봇과 같은 검색 함수를 씁니다.”

#### 4) 검색 결과를 통합하여 질의별 상위 10개 문서 청크를 추출하는 코드
_검색어: [AI+ 시험] Recall@10 - 4)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `graphs/nodes/retrieve.py` | _search_qdrant_hybrid | L110–131 |
| ② | `repositories/vector_repository.py` | VectorRepository.search_hybrid | L605–630 |
| ③ | `evaluation/adapters/retrieval_adapter.py` | EvalRetriever.search_rrf | L171–173 |

**설명**

- ① 두 검색 결과를 합칠 때 쓸 **가중치**(의미 검색 비중, 키워드 검색 비중)를 정하고, Qdrant 검색 함수에 질의 벡터·BM25 질의·`top_k`(=10)·RRF 상수 `rrf_k`를 넘깁니다.
- ② Qdrant 한 번의 요청 안에서 **의미 검색**(`using="dense"`)과 **BM25 검색**(`kiwi_bm25`)을 각각 후보로 뽑고(`Prefetch`), **가중 RRF**로 하나의 순위로 합칩니다. RRF는 각 검색에서의 순위 r마다 1/(k+r) 점수를 주고 가중치를 곱해 더하는 방식이라, 두 검색에서 모두 순위가 높은 청크가 위로 올라옵니다. 결과는 `limit=top_k`개만 돌려받습니다.
- ③ 평가에서는 키워드 가산 목록이 비어 있어(`keywords: []`) 순위가 바뀌지 않습니다. 마지막으로 상위 `top_k`개를 잘라 **질의별 상위 10개 청크**를 돌려줍니다.

🗣 **요약** “의미 검색과 BM25 검색 결과를 Qdrant가 가중 RRF로 하나의 순위로 합치고, 그중 상위 10개 청크를 뽑습니다.”

#### 5) 상위 10개 검색 결과와 정답 데이터를 비교하여 정답 근거 청크의 포함 여부를 확인하는 코드
_검색어: [AI+ 시험] Recall@10 - 5)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _evaluate_retrieval | L267–272 |
| ② | `evaluation/metrics/retrieval_metrics.py` | compute_channel_metrics | L137 |
| ③ | `evaluation/metrics/retrieval_metrics.py` | hit_at_k · _dedup_preserve_order | L39–48 · L13 |

**설명**

- ① 검색 결과에서 **청크ID만 순위대로** 뽑아 목록을 만들고, 정답 청크ID 집합(`gold_ids`)과 함께 지표 계산 함수에 넘깁니다. `k` 값은 1·3·5·10입니다.
- ② `k`마다 `hit_at_k`를 불러 `hit@10` 값을 만듭니다. 이 값이 시험 1의 질의별 포함 여부입니다.
- ③ 판정 함수입니다. 먼저 같은 청크ID가 두 번 나오면 첫 번째만 남깁니다(`_dedup_preserve_order`). 그다음 **상위 10개 중 하나라도 정답 집합에 있으면 1.0, 없으면 0.0**을 돌려줍니다. 정답이 등록되지 않은 문항은 `None`(계산 제외 표시)입니다.

🗣 **요약** “상위 10개 청크ID를 정답 청크ID와 비교해, 하나라도 맞으면 1, 없으면 0으로 질의별 포함 여부를 정합니다. 합의서 정의가 ‘포함된 질의 비율’이라 `hit_at_k` 함수로 계산합니다.”

#### 6) 전체 시험 데이터에 대한 검색 완전성(Recall@10)을 산출하는 코드
_검색어: [AI+ 시험] Recall@10 - 6)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _execute_run | L103 |
| ② | `evaluation/runner/eval_runner.py` | _aggregate_and_save_metrics (질의별 값 수집) | L418–420 |
| ③ | `evaluation/metric_catalog.py` | AGREEMENT_RECALL_KEY · ALL_DENOMINATOR_KEYS | L20 · L29 |
| ④ | `evaluation/runner/eval_runner.py` | _aggregate_and_save_metrics (합계 ÷ 전체 질의 수) | L482–484 |
| ⑤ | `evaluation/runner/eval_runner.py → repositories/evaluation_repository.py` | save_run_metrics | L503 → L734 |

**설명**

- ① 모든 문항 평가가 끝난 뒤 한 번 전체 집계를 시작합니다.
- ② DB에 저장된 문항별 결과를 다시 읽어, `retrieval.rrf.hit@10` 같은 키로 **질의별 값(1 또는 0)**을 모읍니다. `rrf`는 재랭킹 전 하이브리드 검색 결과라는 뜻입니다.
- ③ 시험 1 지표 키가 `retrieval.rrf.hit@10`이고, 이 키는 **분모를 전체 시험 질의 수로 계산하는 지표**로 지정돼 있습니다.
- ④ 계산식입니다. 포함된 질의의 1을 모두 더한 합계를 **전체 질의 수**(오류·정답 없음 문항 포함)로 나눕니다. 오류가 난 문항도 분모에 들어가 0으로 계산됩니다. 예: 120건 중 100건 포함 → 100 ÷ 120 = 0.8333(83.3%).
- ⑤ 집계 결과를 평가 지표 테이블 `tb_eval_run_metrics`에 저장합니다. 화면의 지표 카드가 이 값을 보여 줍니다.

🗣 **요약** “질의별 포함 여부(1/0)를 모두 더해 전체 시험 질의 수로 나눈 값이 검색 완전성 Recall@10이고, DB에 저장돼 화면에 표시됩니다.”

### 평가 실행 및 결과 확인

▶ 1. 평가 > 평가 실행: 골드셋 = 시험 데이터셋
▶ 2. 평가 범위 = **검색·재정렬 평가**, 검색 후보 수 N = 10, 최종 문서 수 K = 5
▶ 3. **실행 시작** → 진행률 120/120 확인
🖥 “검색 품질 (지표 1·2)” 카드의 **검색 완전성 Recall@10** 값과 만족/불만족 표시. (선택) 문항 1건을 열어 **채널별 검색 결과**와 **정답 근거 청크 원문**을 대조

---

## 3. 시험 2 · 검색 최종 정합성 NDCG@5

🗣 “하이브리드 검색 결과를 Reranker 모델로 다시 정렬하고, 상위 5개 안에 정답이 얼마나 높은 순위로 있는지 NDCG@5로 계산합니다. 질의별 값을 평균하고, 목표는 0.8 이상입니다.”

### 소스 코드 확인

#### 1) 시험 데이터 및 정답 데이터를 불러오는 코드
_검색어: [AI+ 시험] NDCG@5 - 1)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _execute_run | L58–61 |
| ② | `repositories/evaluation_repository.py` | EvalRepository.get_goldset | L500 |
| ③ | `evaluation/runner/eval_runner.py` | _evaluate_retrieval | L238–241 |

**설명**

- ① 평가 실행 1회에 한 번, 화면에서 고른 골드셋(시험 데이터셋)의 문항 전체를 `items` 목록으로 불러옵니다.
- ② 실제 DB 조회입니다. 골드셋 테이블 `tb_eval_goldsets`에서 골드셋과 검색 대상 컬렉션을 읽습니다.
- ③ 문항마다 **질의문**과 **정답 청크ID 집합**을 꺼냅니다. NDCG@5에서는 화면에서 넣은 **최종 문서 수 K(=5)**(`rerank_top_k`)도 함께 읽어, 재정렬 후 상위 몇 개를 볼지 정합니다.

🗣 **요약** “Recall@10과 같은 방식으로 시험 데이터셋을 읽고, 문항마다 질의문·정답 청크ID와 평가할 상위 개수 K=5를 꺼냅니다.”

#### 2) 임베딩 모델 및 Reranker 모델을 불러오는 코드
_검색어: [AI+ 시험] NDCG@5 - 2)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _evaluate_retrieval (검색기 생성) | L255 |
| ② | `evaluation/adapters/retrieval_adapter.py` | EvalRetriever.__init__ | L67–68 |
| ③ | `graphs/nodes/retrieve.py → core/container.py` | get_embedding_client → _EMBEDDING_FACTORIES | L54 → L43 |
| ④ | `clients/embedding_client.py` | EmbeddingClient.__init__ | L33 |
| ⑤ | `evaluation/adapters/reranker_adapter.py` | _get_client | L15–21 |
| ⑥ | `clients/reranker_client.py` | RerankerClient.__init__ | L48–61 |

**설명**

- ① 평가 코드가 검색기를 만듭니다. Reranker에 넘길 후보를 이 검색기로 찾습니다.
- ② 검색기가 **임베딩 모델 클라이언트**를 받아 옵니다(의미 검색용).
- ③ 운영 챗봇과 같은 공용 컨테이너에서 받아 옵니다. 컨테이너가 처음 한 번 `EmbeddingClient`를 만들고 이후 재사용합니다.
- ④ 임베딩 모델 이름을 설정값에서 읽습니다. 모델은 GPU 서버에서 돕니다.
- ⑤ **Reranker 모델 클라이언트**를 처음 필요할 때 한 번만 만들고 재사용합니다(`_reranker_client`에 보관).
- ⑥ Reranker 설정입니다. 모델 이름(`reranker_model_name`), GPU 서버 주소, 시간 제한, 출력 개수(`reranker_top_k`)를 설정값에서 읽습니다. 운영 챗봇과 같은 설정을 씁니다.

🗣 **요약** “검색 후보를 찾는 임베딩 모델 클라이언트와, 후보를 다시 정렬하는 Reranker 모델 클라이언트를 운영과 같은 설정으로 불러옵니다.”

#### 3) 시험 데이터를 입력하여 임베딩 기반 의미 검색과 BM25 기반 키워드 검색을 수행하는 코드
_검색어: [AI+ 시험] NDCG@5 - 3)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _evaluate_retrieval | L282–285 |
| ② | `evaluation/adapters/retrieval_adapter.py` | _build_eval_query_bundle · EvalRetriever.search_rrf | L44–58 · L149 |
| ③ | `graphs/nodes/retrieve.py` | _search_qdrant_hybrid | L96–107 |
| ④ | `clients/embedding_client.py · clients/kiwi_bm25_encoder.py` | embed_query · encode_query | L171–180 · L61–66 |

**설명**

- ① Reranker에 넘길 **후보 수**를 운영 챗봇과 같게 맞춥니다(`candidate_top_k`, 설정값). 앞 단계에서 가져온 결과가 이보다 적으면 그 수만큼 다시 검색합니다. 운영과 같은 후보로 재정렬해야 운영 품질과 같은 값이 나옵니다.
- ② LLM으로 질의를 바꾸지 않고 **시험 질의 원문**으로 검색 입력을 만들어, 운영 챗봇과 같은 하이브리드 검색 함수를 호출합니다.
- ③ 의미 검색 질의와 키워드 검색 질의를 동시에 만들고, Qdrant에서 두 검색을 수행해 가중 RRF로 합칩니다(Recall@10 - 4)와 같은 함수).
- ④ `embed_query`는 질의를 임베딩 벡터로 바꾸고(의미 검색), `encode_query`는 Kiwi 형태소 분석으로 BM25 키워드 질의를 만듭니다(키워드 검색).

🗣 **요약** “Recall@10과 같은 하이브리드 검색을 하되, Reranker에 넘길 후보는 운영 챗봇과 같은 수만큼 가져옵니다.”

#### 4) 하이브리드 검색 결과를 Reranker 모델에 입력하여 질의와 문서 청크 간 관련도를 평가하고 검색 결과를 재정렬하는 코드
_검색어: [AI+ 시험] NDCG@5 - 4)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _evaluate_retrieval | L288 |
| ② | `evaluation/adapters/reranker_adapter.py` | EvalReranker.rerank | L46–56 |
| ③ | `graphs/utils.py` | dedup_chunks_by_text | L24 |
| ④ | `graphs/nodes/rerank.py` | _build_rerank_text | L48 |
| ⑤ | `clients/reranker_client.py` | RerankerClient.rerank | L85–90 |
| ⑥ | `clients/reranker_client.py` | RerankerClient._call_score_api | L96 |

**설명**

- ① 하이브리드 검색 후보(`rrf_hits`)와 시험 질의를 Reranker에 넣어 재정렬을 요청합니다.
- ② 재정렬 순서: 같은 본문 제거 → Reranker 입력 텍스트 만들기 → Reranker 호출 → 원래 청크ID로 되돌리기. 운영 챗봇 재랭킹 노드와 같은 입력을 씁니다.
- ③ 본문이 똑같은 청크는 하나만 남깁니다(본문 해시 비교, 점수 높은 쪽 유지). 같은 내용이 순위를 두 칸 차지하지 않게 하려는 것입니다.
- ④ Reranker가 문맥을 알 수 있도록 본문 앞에 `[문서명]`·`[섹션]` 머리말을 붙입니다.
- ⑤ Reranker 모델이 **질의–청크 쌍마다 관련도 점수**를 매기고, 점수가 높은 순으로 정렬해 상위 개수만 돌려줍니다.
- ⑥ 실제 점수 계산 요청입니다. GPU 서버의 Reranker 모델(vLLM `/v1/score`)에 질의와 청크 텍스트들을 보내고 점수를 받습니다.

🗣 **요약** “검색 후보를 문서명·섹션을 붙인 텍스트로 만들어 Reranker 모델에 넣고, 질의와의 관련도 점수 순으로 다시 정렬합니다.”

#### 5) 재정렬된 상위 5개 문서 청크의 관련도 및 순위를 정답 데이터와 비교하여 질의별 NDCG@5를 산출하는 코드
_검색어: [AI+ 시험] NDCG@5 - 5)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _evaluate_retrieval | L290–293 |
| ② | `evaluation/metrics/retrieval_metrics.py` | compute_channel_metrics | L140 |
| ③ | `evaluation/metrics/retrieval_metrics.py` | ndcg_at_k | L83–99 |

**설명**

- ① 재정렬 결과에서 청크ID만 순위대로 뽑아, 정답 청크ID 집합과 함께 지표 계산 함수에 넘깁니다.
- ② `k`마다 `ndcg_at_k`를 불러 `ndcg@5` 값을 만듭니다.
- ③ 계산식입니다.  
   · **관련도**: 정답 청크면 1, 아니면 0.  
   · **DCG**: 상위 5개 중 정답이 있는 순위 i마다 1/log₂(i+1)을 더합니다. 1위면 1.0, 2위면 0.63, 3위면 0.5처럼 아래 순위일수록 점수가 작습니다.  
   · **IDCG**: 정답이 1위부터 빈틈없이 채워진 가장 이상적인 경우의 DCG입니다.  
   · **NDCG@5 = DCG ÷ IDCG**. 0~1 사이 값이고, 정답이 위쪽에 있을수록 1에 가깝습니다.  
   예: 정답 1개가 1위면 1.0, 2위면 0.63, 상위 5개에 없으면 0.

🗣 **요약** “재정렬 상위 5개에서 정답이 몇 위에 있는지 보고, 높은 순위일수록 큰 점수를 주는 NDCG@5를 질의마다 계산합니다.”

#### 6) 전체 시험 데이터에 대한 질의별 NDCG@5의 평균을 산출하는 코드
_검색어: [AI+ 시험] NDCG@5 - 6)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _execute_run | L103 |
| ② | `evaluation/runner/eval_runner.py` | _aggregate_and_save_metrics (질의별 값 수집) | L418–420 |
| ③ | `evaluation/metric_catalog.py` | AGREEMENT_NDCG_KEY · ALL_DENOMINATOR_KEYS | L21 · L29 |
| ④ | `evaluation/runner/eval_runner.py` | _aggregate_and_save_metrics (합계 ÷ 전체 질의 수) | L482–484 |
| ⑤ | `evaluation/runner/eval_runner.py → repositories/evaluation_repository.py` | save_run_metrics | L503 → L734 |

**설명**

- ① 모든 문항 평가가 끝난 뒤 전체 집계를 시작합니다.
- ② 문항별 결과에서 `retrieval.rerank.ndcg@5` 키로 **질의별 NDCG@5 값**을 모읍니다. `rerank`는 Reranker로 재정렬한 결과라는 뜻입니다.
- ③ 시험 2 지표 키가 `retrieval.rerank.ndcg@5`이고, 분모를 전체 시험 질의 수로 계산하는 지표로 지정돼 있습니다.
- ④ 질의별 NDCG@5를 모두 더해 **전체 질의 수**로 나눈 평균입니다. 재랭킹 오류·정답 없음 문항도 분모에 들어가 0으로 계산됩니다.
- ⑤ 결과를 평가 지표 테이블 `tb_eval_run_metrics`에 저장하고, 화면 지표 카드에 표시합니다.

🗣 **요약** “질의별 NDCG@5를 모두 더해 전체 시험 질의 수로 나눈 평균이 검색 최종 정합성이고, DB에 저장돼 화면에 표시됩니다.”

### 평가 실행 및 결과 확인

🖥 시험 1과 **같은 “검색·재정렬 평가” 실행 결과**에서 **검색 최종 정합성 NDCG@5** 카드 값과 만족/불만족 표시. (선택) 문항 1건을 열어 재랭킹 순위와 정답 청크를 대조
🗣 “한 번의 검색·재정렬 평가에서 Recall@10과 NDCG@5가 함께 계산됩니다.”

---

## 4. 시험 4 · 답변 생성 평균 반환 시간

🗣 “운영 챗봇과 같은 RAG 파이프라인으로 질의를 1건씩 순서대로 실행합니다. 질의마다 답변 생성 요청을 시작한 시점부터 문서 검색, 재랭킹, 최종 답변 생성이 끝날 때까지 시간을 재고 평균을 냅니다.”

### 소스 코드 확인

#### 1) 시험 데이터를 불러오는 코드
_검색어: [AI+ 시험] 반환 시간 - 1)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _execute_run | L58–59 |
| ② | `repositories/evaluation_repository.py` | EvalRepository.get_goldset | L500 |
| ③ | `evaluation/runner/e2e_evaluator.py` | evaluate_end_to_end | L64 |

**설명**

- ① 평가 실행 1회에 한 번, 화면에서 고른 골드셋의 문항 전체를 `items` 목록으로 불러옵니다.
- ② 실제 DB 조회입니다. 골드셋 테이블 `tb_eval_goldsets`에서 읽습니다.
- ③ 문항마다 We.RAG에 보낼 **질의문**을 꺼냅니다. 반환 시간 측정에는 질의문만 있으면 됩니다.

🗣 **요약** “확정된 시험 데이터셋을 DB에서 읽고, 문항마다 질의문을 꺼냅니다.”

#### 2) 시험 데이터를 We.RAG에 입력하여 질의별 답변 생성을 요청하는 코드
_검색어: [AI+ 시험] 반환 시간 - 2)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _execute_run (1건씩 실행) | L72 |
| ② | `evaluation/runner/eval_runner.py` | _evaluate_item | L132 |
| ③ | `evaluation/runner/e2e_evaluator.py` | evaluate_end_to_end | L72–77 |
| ④ | `evaluation/adapters/rag_pipeline_adapter.py` | EvalRagPipeline.run (입력 구성) | L75–90 |
| ⑤ | `evaluation/adapters/rag_pipeline_adapter.py` | _get_graph | L55 |
| ⑥ | `evaluation/adapters/rag_pipeline_adapter.py` | EvalRagPipeline.run (그래프 실행) | L101 |

**설명**

- ① 전체 RAG 평가는 **한 번에 1건씩만** 실행하도록 묶어 둡니다(`Semaphore(1)`). 여러 질의가 동시에 돌면 서로 기다리느라 시간이 늘어나므로, 질의마다 순수한 답변 시간을 재기 위한 것입니다.
- ② 평가 범위가 전체 RAG면 문항마다 답변 생성 평가 함수를 부릅니다.
- ③ 시험 질의문을 RAG 파이프라인에 넣어 실행을 요청합니다.
- ④ 운영 RAG 그래프에 넣을 입력(`state`)을 만듭니다. 질의 원문, 검색 컬렉션을 넣고, 이전 대화가 섞이지 않게 세션은 비웁니다.
- ⑤ **운영 챗봇과 같은 RAG 그래프**(`build_rag_graph`)를 처음 한 번 만들고 재사용합니다.
- ⑥ 그래프를 실행합니다. 그래프 안에서 **질의 분석 → 문서 검색 → 재랭킹 → 답변 생성**이 차례로 이뤄집니다.

🗣 **요약** “시험 질의를 1건씩 순서대로, 운영 챗봇과 같은 RAG 그래프에 넣어 검색·재랭킹·답변 생성까지 실행합니다.”

#### 3) 질의별 답변 생성 요청 시작 시점부터 문서 검색, 재랭킹 및 최종 답변 생성 완료 시점까지의 소요 시간을 측정하는 코드
_검색어: [AI+ 시험] 반환 시간 - 3)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/adapters/rag_pipeline_adapter.py` | EvalRagPipeline.run (시작 시점) | L98–99 |
| ② | `graphs/nodes/generate_answer.py` | generate_answer (참고: 첫 토큰 시각) | L72 |
| ③ | `evaluation/adapters/rag_pipeline_adapter.py` | EvalRagPipeline.run (완료 시점) | L103 |
| ④ | `evaluation/adapters/rag_pipeline_adapter.py` | EvalRagPipeline.run (참고: 첫 토큰 ms) | L108–111 |

**설명**

- ① 그래프 실행 **직전에 시작 시각**을 기록합니다. `time.monotonic()`은 시스템 시계가 바뀌어도 영향을 받지 않는 시간 측정용 시계입니다.
- ② (참고) 답변 생성 중 **첫 글자(토큰)가 나온 시각**을 기록합니다.
- ③ 검색·재랭킹·답변 생성이 모두 끝나 그래프가 결과를 돌려준 **직후의 시각**에서 시작 시각을 빼고 1000을 곱해 **ms 단위 반환 시간**을 구합니다. 이후의 지표 계산 시간은 들어가지 않습니다.
- ④ (참고) 첫 토큰 시각에서 시작 시각을 빼 **첫 토큰 시간(ms)**도 구합니다. 화면 주요 지표 4가 이 값입니다.

🗣 **요약** “그래프 실행 직전과 직후의 시각 차이로, 검색·재랭킹·답변 생성 전체에 걸린 시간을 ms로 잽니다.”

#### 4) 질의별 답변 생성 반환 시간을 저장하는 코드
_검색어: [AI+ 시험] 반환 시간 - 4)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/e2e_evaluator.py` | evaluate_end_to_end | L83–85 |
| ② | `evaluation/runner/eval_runner.py` | _evaluate_item | L137–138 |
| ③ | `evaluation/runner/eval_runner.py` | _timing_metrics | L149 |
| ④ | `evaluation/runner/eval_runner.py` | _execute_run → _process | L84 |
| ⑤ | `repositories/evaluation_repository.py` | EvalRepository.insert_item_result | L601 |

**설명**

- ① 측정한 **반환 시간**(`latency_ms`)과 첫 토큰 시간이 담긴 `timing_json`을 문항 결과에 넣습니다.
- ② 안전장치입니다. 반환 시간이 비어 있을 때만 문항 처리 전체 시간으로 채웁니다. 전체 RAG 평가에서는 ①의 값이 항상 있어서 쓰이지 않습니다.
- ③ 문항 결과를 지표 형식으로 정리합니다. 반환 시간과 첫 토큰 시간을 각각 지표 키(`answer.response_time_ms`, `answer.first_token_ms`)에 담고, 값이 없으면 ‘측정 누락’으로 표시합니다.
- ④ 문항 1건이 끝날 때마다 결과를 저장합니다.
- ⑤ 문항 결과 테이블 `tb_eval_item_results`에 한 행씩 넣습니다. 화면 문항 표의 시간 열과 결과 Excel이 이 값입니다.

🗣 **요약** “질의마다 잰 반환 시간과 첫 토큰 시간을 문항 결과 테이블에 한 행씩 저장합니다.”

#### 5) 전체 시험 데이터의 반환 시간을 평균하여 답변 생성 평균 반환 시간을 산출하는 코드
_검색어: [AI+ 시험] 반환 시간 - 5)_

| | 파일 | 함수 | 줄 |
|---|---|---|---|
| ① | `evaluation/runner/eval_runner.py` | _execute_run | L103 |
| ② | `evaluation/runner/eval_runner.py` | _aggregate_and_save_metrics (질의별 시간 수집) | L462–464 |
| ③ | `evaluation/metric_catalog.py` | RESPONSE_TIME_KEY · FIRST_TOKEN_KEY | L24 · L26 |
| ④ | `evaluation/runner/eval_runner.py → evaluation/metrics/models.py` | MetricAggregate.from_results | L471 → L43–48 |
| ⑤ | `evaluation/runner/eval_runner.py` | _aggregate_and_save_metrics (누락 처리) | L475–477 |
| ⑥ | `evaluation/runner/eval_runner.py → repositories/evaluation_repository.py` | save_run_metrics | L503 → L734 |

**설명**

- ① 모든 문항 평가가 끝난 뒤 전체 집계를 시작합니다.
- ② 전체 RAG 평가일 때 문항별 결과에서 **질의별 반환 시간·첫 토큰 시간**을 모읍니다.
- ③ 지표 키입니다. `answer.response_time_ms`는 최종 답변 완료 기준(합의서 정의), `answer.first_token_ms`는 첫 토큰 기준(화면 주요 지표 4)입니다.
- ④ 평균 계산입니다. 측정된 값만 모아 **합계 ÷ 건수**로 평균을 냅니다. 예: 120건 합계 600,000ms → 600,000 ÷ 120 = 5,000ms(5초).
- ⑤ 측정 누락이 한 건이라도 있으면(측정 건수 ≠ 전체 건수) 일부만의 평균을 공식 값으로 보여 주지 않도록 값을 비웁니다. 그래서 화면에 표시되는 평균은 항상 전체 시험 데이터 기준입니다.
- ⑥ 결과를 평가 지표 테이블 `tb_eval_run_metrics`에 저장하고, 화면 지표 카드에 표시합니다.

🗣 **요약** “전체 시험 질의의 반환 시간을 더해 질의 수로 나눈 평균을 계산하고, 측정이 빠진 질의가 있으면 공식 값으로 보여 주지 않습니다.”

### 평가 실행 및 결과 확인

▶ 1. 평가 > 평가 실행: 골드셋 = 시험 데이터셋
▶ 2. 평가 범위 = **전체 RAG 평가**
▶ 3. **실행 시작** → 진행률 120/120 확인 (1건씩 순차 실행이라 시간이 걸림)
🖥 “답변 품질” 카드의 **답변 생성 평균 반환 시간**(첫 토큰 기준), 보조 지표의 **전체 반환 시간**(최종 완료 기준), 문항 표의 시간 열(첫 토큰 / 전체)

---

## 5. 마무리 (1분)

🖥 실행 이력의 **평가 결과 Excel 다운로드** → 질의별 지표·시간 확인 / 코드: `app/routes/evaluation.py` → `GET /eval/runs/{run_id}/results.xlsx`(L640), `app/evaluation/excel_exporter.py`
🗣 “세 지표 결과는 실행 이력으로 저장돼 다시 열어 볼 수 있고, 질의별 결과는 Excel로 받을 수 있습니다.”

---

## 예상 질문 대응

| 질문 | 답변 |
|---|---|
| Recall@10인데 왜 `hit_at_k`인가요? | 합의서 정의가 “정답 근거 청크가 1개 이상 포함된 질의 비율”이기 때문입니다. `recall_at_k`는 정답 청크 커버율로, 보조 지표로 따로 보여 줍니다. |
| 검색·재정렬 평가에서 LLM 질의 재작성을 하나요? | 하지 않습니다. 시험 질의 원문으로 검색합니다(`retrieval_adapter.py` `_build_eval_query_bundle` L44). 전체 RAG 평가는 운영과 같이 재작성까지 포함합니다. |
| 같은 청크가 여러 번 나오면? | 중복을 제거한 순위로 계산합니다(`retrieval_metrics.py` `_dedup_preserve_order` L13). 재정렬 전에는 본문이 같은 청크도 하나로 합칩니다(`graphs/utils.py` `dedup_chunks_by_text` L24). |
| 오류 난 질의는 어떻게 세나요? | Recall@10·NDCG@5는 0으로 세고 분모는 전체 질의 수입니다(`eval_runner.py` L482–484). 반환 시간은 측정이 빠지면 공식 평균을 표시하지 않습니다(L475–477). |
| 문항마다 모델·DB에 새로 연결하나요? | 아닙니다. 공용 컨테이너(`core/container.py`)가 처음 한 번 만들고 재사용합니다. |
| 반환 시간에 네트워크 시간이 포함되나요? | 서버 안에서 RAG 그래프를 실행한 시간이라 네트워크 전송 시간은 포함되지 않습니다. |
| 주요 지표 4는 첫 토큰 기준인데 합의서는 최종 완료 기준 아닌가요? | 화면 주요 카드는 첫 토큰 평균이고, 합의서 정의(최종 답변 완료)는 보조 지표 “전체 반환 시간”으로 함께 보여 줍니다. |
