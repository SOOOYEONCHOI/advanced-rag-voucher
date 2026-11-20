# RAG 평가 파이프라인 분석·보완 설계 (2026-11-17)

> 기준: 현재 화면(평가 데이터셋 `EvalDatasetView` / 평가 실행 `EvalRunView` / 평가 대시보드 `EvalDashboardView`)에서 실제로 호출되는 경로.
> 관련 ID: R7-2(신규 모델 재평가), R8-7(회귀 평가 자동화), 미결 Q-2(OpenAI 경로 vs 절대 규칙 7), 미결 B10(골드셋 재매핑).
> 이 문서는 분석·설계만 한다. 코드 변경 없음.

---

## 1. 현재 파이프라인 구조

```
[UI-평가 데이터셋]  POST /api/eval/datasets ─▶ dataset/generator.py (vLLM 또는 OpenAI로 QA 생성)
        │ 검수(승인/수정/반려) ─▶ POST /datasets/{id}/finalize ─▶ tb_eval_goldsets.items_snapshot_json
        ▼
[UI-평가 실행]  POST /api/eval/runs {goldset_id, scope: retrieval|full, config: {retrieval_top_n, rerank_top_k}}
        │  routes/evaluation.py: 서버 설정으로 config 스냅샷 보강(answer_correctness_*, judge backend/model)
        ▼
runner/eval_runner.py  asyncio.create_task (앱 프로세스 안), Semaphore(3) 병렬
        ├─ scope=retrieval → _evaluate_retrieval(): EvalRetriever 채널별(dense/kiwi_bm25/rrf) + EvalReranker
        │                     (질의 재작성·메타 필터 없음, query_type 기본값)
        └─ scope=full      → e2e_evaluator.evaluate_end_to_end(): 운영 LangGraph 그래프 in-process 1회 실행
                               ├ 검색 지표: retrieved_chunks(N) / reranked_chunks(K)
                               ├ 답변: v1(임베딩 코사인) · v2(문장정렬 F1) · f2(F2) · judge(RAGAS AnswerAccuracy, 단일 LLM)
                               │       → answer.correctness = primary(f2) + fallback(judge→v2→v1)
                               ├ Citation 규칙 지표, rule_check, guardrail/threshold-fallback
                               └ citation_detail_json(used_chunks 300자 절단)
        ▼
tb_eval_item_results (항목별 JSON) → _aggregate_and_save_metrics(): all / type:* / tag:* 세그먼트 평균
        ▼
GET /runs/{id} → metric_catalog.present_run_metrics(): 주요 지표 4개
   Retriever Recall@N · Reranked NDCG@K · Answer Correctness · Citation Completeness (목표 80%, useEvalRuns.js PRIMARY_THRESHOLDS)
GET /runs/{id}/results.xlsx → 지표 요약 + 항목별 결과(질문·지표 4개만)
```

## 2. 시험 항목별 충족도

| # | 시험 항목 / 지표 | 현재 상태 | 판정 |
|---|---|---|---|
| 1 | 하이브리드 검색 **Hit@10** ≥ 80% | `hit@k`는 계산·저장됨(`retrieval.rrf.hit@10`). 하지만 화면 주요 지표·Excel은 **Recall@N**만 보여 줌. 다건 정답(멀티홉)이면 Recall < Hit라 같은 실행에서 수치가 다르게 나온다 | △ 계산은 있음, 보고 지표 불일치 |
| 2 | 재랭킹 **NDCG@5** ≥ 80% | `retrieval.rerank.ndcg@5` 주요 지표로 표시. 단 **이진 관련도(정답 청크=1, 나머지=0)**. "청크별 관련도 평가"(등급 관련도)는 없음 | △ |
| 3 | 답변 생성 **LLM-as-a-Judge** ≥ 80% (3종 LLM, Faithfulness·Answer Relevance) | Judge는 RAGAS **AnswerAccuracy**(답변 vs 정답 답변) 1종, 단일 모델(서버 설정 `answer_correctness_judge_backend`=vllm/openai). **Faithfulness·Answer Relevance 없음, 근거 문서 미사용, 다중 모델 없음, 화면 선택 없음.** 화면의 Answer Correctness는 기본값이 f2(임베딩 기반)라 Judge 점수도 아님. 결과 Excel에 생성 답변·근거 데이터 없음 | ✕ |
| 4 | **평균 응답시간(ms)** | `latency_ms`는 항목 평가 전체(그래프 실행 + 인용 보정 LLM + 임베딩 + Judge LLM 호출) 시간이고, 3건 **병렬**·**in-process**(API 미경유). `latency.mean_ms` 집계는 되지만 화면 미표시. `timing_json`에 노드별 시간은 있음 | ✕ API 순차 측정 없음 |

## 3. 발견 사항 (보완점)

### 3.1 검색·재랭킹 (시험 1·2)

| ID | 내용 | 영향 | 보완 |
|---|---|---|---|
| E-01 | 주요 지표가 Recall@N. 시험 지표 Hit@10과 다름 | 보고 수치 혼동 | `metric_catalog`에 `retrieval.rrf.hit@{N}`를 주요 지표로 추가(Recall은 보조로 내림). Excel 항목별 시트에 Hit@N 열 추가 |
| E-02 | `scope=retrieval`은 운영 경로와 다름: 질의 재작성 없음, 메타데이터 필터 없음, `classify_query_type({})` 기본값 | 시험 수치가 실제 서비스와 다를 수 있음 | 시험용 공식 수치는 **`scope=full`의 retrieval_json**(운영 그래프 결과) 기준으로 확정. 화면에 "운영 경로 기준" 표기. retrieval 범위는 "빠른 진단"으로 문구 변경 |
| E-03 | `scope=full`의 검색 지표는 cutoff를 N·K 하나씩만 계산 (`compute_channel_metrics(..., (cutoff,))`) | N≠10으로 실행하면 Hit@10이 아예 없음 | full에서도 `(1,3,5,10,N)` / `(1,3,K,5)` 계산. 시험 실행은 N=10, K=5 고정 프리셋 제공 |
| E-04 | **골드셋 청크 ID가 버전 포함** (`{document_id}:{version_no}:{key}#{part}`, `ingest/records.py:32`) → 문서 재등록·새 버전 후 정답 ID가 사라져 조용히 0점 | 시험 직전 문서 갱신 시 Hit 급락 | (미결 B10) 실행 전 **골드셋 유효성 검사**: 정답 청크 ID가 현재 활성 버전에 있는지 확인, 없으면 `source_key`(key#part)로 최신 버전에 재매핑 제안 또는 해당 항목 `excluded: stale_gold_chunk`로 집계 |
| E-05 | NDCG 이진 관련도 | "청크별 관련도 평가" 요구와 차이 | 1차 범위는 이진 유지 + 근거 명시(정답 청크=rel 1). 등급 관련도(0~2)가 필요하면 골드셋에 `gold_chunk_grades` 추가 — **결정필요(DQ-2)** |
| E-06 | 재랭커 임계값(`relevance_threshold`) 미만 청크가 걸러져 reranked가 K보다 적을 수 있음 | NDCG@5 분모(IDCG)는 그대로, 분자만 줄어 하락 | 현행 유지(운영과 동일해야 함). 항목 상세에 "임계값 탈락으로 K 미만" 진단 표시 |
| E-07 | 평가용 청크 저장소가 버전 제외 조건 없이 컬렉션 전체 scroll (미결 목록) | 데이터셋 생성 시 구버전 청크가 정답이 될 수 있음 | 활성 버전만 샘플링 |

### 3.2 답변 생성 (시험 3)

| ID | 내용 | 보완 |
|---|---|---|
| E-08 | Judge 지표가 AnswerAccuracy뿐. Faithfulness·Answer Relevance 없음 | 새 Judge 모듈(4장)로 두 지표 추가 |
| E-09 | Judge에 근거 문서 미전달 | `gold_chunk_texts`(골드셋 스냅샷) 전달. 옵션으로 실제 사용 컨텍스트(`context_chunks`) 기준 Faithfulness도 계산(진단용) |
| E-10 | 단일 모델, 서버 설정으로만 바꿈. 화면 선택 없음 | 실행 생성 시 3종 다중 선택 |
| E-11 | 화면 Answer Correctness = f2(임베딩) 우선 → "LLM-as-a-Judge 80%" 근거로 쓸 수 없음 | Judge 지표를 별도 KPI 카드로 분리(기존 Answer Correctness는 그대로 유지) |
| E-12 | 결과 Excel에 생성 답변·근거 없음. `used_chunks` 300자 절단 | "답변·근거" 시트 추가(질문, 정답, 생성 답변 전문, 정답 근거 원문, 사용 컨텍스트, 인용, 모델별 점수·사유) |
| E-13 | `gold_chunk_texts`는 생성 시점 값. 검수 화면에서 `gold_chunk_ids`를 바꿔도 텍스트 갱신 안 됨(`update_qa_item`) | 수정 시 텍스트 재조회, 또는 실행 시점에 ID로 원문 조회 |
| E-14 | 평가 질의 120개 규모 확인 수단 없음 | 골드셋 확정 시 건수·유형 분포 표시(이미 item_count 있음) + 시험 프리셋에서 "120건 아님" 경고 |

### 3.3 응답시간 (시험 4)

| ID | 내용 | 보완 |
|---|---|---|
| E-15 | `latency_ms`에 평가 부가 작업(인용 보정, 임베딩, Judge) 포함 | 그래프 실행 시간만 `pipeline_latency_ms`로 분리 저장 |
| E-16 | 병렬 3건, in-process 실행, 운영 API(`/api/query/`, `/api/query/stream`) 미경유 | **별도 스크립트** `scripts/eval_api_latency.py`: 로그인 → 골드셋 질문을 **순차** 호출 → 총 응답시간·첫 토큰 시간(stream) 측정 → p50/p90/p95/평균/최대 CSV·MD 출력. 워밍업 N건 제외. 쿼리 로그 오염 방지용 `X-Eval-Run` 헤더 또는 평가 전용 계정 사용(결정필요 DQ-5) |
| E-17 | 화면에 응답시간 미표시 | 실행 결과 보조 지표에 `latency.pipeline_mean_ms` 추가(참고용, 공식 수치는 E-16 스크립트) |

### 3.4 공통·운영

| ID | 내용 | 보완 |
|---|---|---|
| E-18 | 러너가 앱 프로세스 안 asyncio task → 재기동 시 run이 `running`으로 남음 | 기동 시 `running` → `failed(interrupted)` 정리(현 구조 유지, 큐 워커 전환은 별건) |
| E-19 | 외부 LLM 호출(OpenAI)이 절대 규칙 7·미결 Q-2와 충돌. 3종 Judge는 질문·답변·근거 원문을 사외로 보냄 | **결정필요(DQ-1)**. 5장 참고 |

## 4. 추가 개발 설계 — 3종 LLM Judge (Faithfulness · Answer Relevance)

### 4.1 목표

- 평가 실행 화면에서 **GPT / Gemini / Claude** 를 체크박스로 골라(복수 선택) 전체 RAG 평가 또는 기존 실행 재채점에 사용한다.
- 모델마다 **근거 충실성(Faithfulness)**, **답변 관련성(Answer Relevance)** 을 0~1로 매기고, 모델별 점수·3모델 평균·합의도를 보여 준다.
- 기본값은 꺼짐(설정값). 끄면 기존 동작과 완전히 같다(절대 규칙 6).

### 4.2 채점 방식

같은 채점 기준(프롬프트·출력 JSON 형식)을 3개 제공자에 똑같이 적용한다. RAGAS는 제공자별 지원 차이가 있고 Answer Relevancy가 임베딩 모델에 의존해 모델 간 비교가 흐려지므로, **자체 루브릭 프롬프트**를 권장한다(결정필요 DQ-3, 대안: RAGAS Faithfulness + ResponseRelevancy).

| 지표 | 입력 | 계산 |
|---|---|---|
| Faithfulness | 생성 답변 + **정답 근거 문서**(`gold_chunk_texts`) | 답변을 주장(claim) 단위로 나눠 각 주장이 근거로 뒷받침되는지 `supported / not_supported` 판정 → 지지 비율. 주장 0개면 `excluded: no_claims` |
| Answer Relevance | 질문 + 생성 답변 (+ 정답 답변 참고) | 질문 의도에 맞게 직접 답했는지 1~5점 → (점수−1)/4 |

한 번 호출에 두 지표를 함께 받는다(모델당 항목 1회, 120건×3모델=360회).

출력 JSON(모든 제공자 공통, 파싱 실패 시 1회 재요청 후 `error: parse_error`):
```json
{"claims":[{"text":"...","verdict":"supported","evidence":"근거 일부"}],
 "faithfulness": 0.86, "answer_relevance_score": 5, "reason": "한국어 한두 문장"}
```

집계(세그먼트 all/type/tag 동일 규칙):
- `answer.judge.faithfulness.{openai|gemini|anthropic}`, `answer.judge.relevance.{...}`
- `answer.judge.faithfulness.ensemble`, `answer.judge.relevance.ensemble` = 항목별 평가된 모델 평균의 평균
- `answer.judge.agreement` = 항목별 모델 간 점수 표준편차 평균(낮을수록 합의)
- 합격 판정 방식은 **결정필요(DQ-4)**: (a) 평균 점수 ≥ 0.8, (b) 항목 통과율(점수 ≥ 0.8인 항목 비율) ≥ 80%, (c) 3모델 중 2개 이상 통과 항목 비율. 화면은 세 값을 모두 계산해 두고 선택된 방식만 KPI 판정에 쓴다.

### 4.3 백엔드 변경

| 파일 | 변경 |
|---|---|
| `app/core/config.py` | `eval_external_judge_enabled: bool = False`, 제공자별 `eval_judge_{openai,gemini,anthropic}_model: Optional[str] = None`, `eval_judge_{...}_base_url`(사내 프록시 대응), `eval_judge_timeout_s`, `eval_judge_concurrency_per_provider: int = 2`, `eval_judge_max_retries: int = 3`, `eval_judge_evidence_max_chars` |
| `app/evaluation/judges/` (신규) | `base.py`(JudgeProvider 프로토콜: `async judge(prompt) -> dict`), `openai_judge.py`, `gemini_judge.py`, `anthropic_judge.py` — **httpx로 REST 직접 호출**(새 SDK 의존성 없이 폐쇄망 휠 반입 부담 최소화), `prompts.py`(공통 루브릭), `rag_judge.py`(항목 1건 × 선택 모델 병렬 실행, 제공자별 Semaphore, 429/5xx 지수 백오프) |
| `app/evaluation/runner/e2e_evaluator.py` | `config["llm_judges"]`가 있으면 `rag_judge.evaluate(...)` 호출 → `fields["llm_judge_json"]`. 기존 `answer_correctness_judge`는 그대로 |
| `app/evaluation/runner/eval_runner.py` | `_aggregate_and_save_metrics`에 4.2 키 집계 추가, `pipeline_latency_ms` 분리(E-15) |
| `app/evaluation/metric_catalog.py` | full 범위 주요 지표에 `Hit@N`(E-01), `Faithfulness(평균)`, `Answer Relevance(평균)` 추가(judge 선택 시) |
| `app/evaluation/schemas.py` | `RuleEvaluationConfig.judge_providers: List[Literal["openai","gemini","anthropic"]] = []` (extra=forbid라 명시 추가 필요). `JudgeKeyRequest{api_key}`, `RejudgeRequest{providers}` |
| `app/routes/evaluation.py` | `create_run`: 선택 제공자 검증(전역 플래그 off·모델 미설정·키 미등록이면 400, 사유 한국어) → config 스냅샷 `llm_judges={providers:[{provider, model, prompt_version}], evidence_source:"gold_chunks"}`. 키 원문은 config에 저장하지 않고 런타임 주입(기존 dataset 키 패턴). 신규 API 아래 |
| `app/repositories/evaluation_repository.py` | 키 저장 일반화, `llm_judge_json` 저장·조회 |
| `app/evaluation/excel_exporter.py` | "답변·근거" 시트(E-12), 모델별 점수 열 |
| `migrations/versions/0012_eval_llm_judge.py` | ① `tb_eval_item_results.llm_judge_json JSONB NULL`, `pipeline_latency_ms INTEGER NULL` ② `tb_eval_judge_keys(admin_id, provider, api_key_enc, updated_at, PK(admin_id, provider))` + 기존 `tb_eval_settings.openai_api_key_enc`를 `provider='openai'`로 복사. downgrade는 컬럼·테이블 삭제(기존 openai 키 컬럼은 그대로 두므로 손실 없음) |

신규 API (화면·API ID는 `02_화면_API_ID_목록.md`에 번호 부여 필요):

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/eval/settings/judge-providers` | `[{provider, label, model, has_key, available, unavailable_reason}]` — 화면 체크박스 활성/비활성 근거 |
| PUT / DELETE | `/api/eval/settings/judge-keys/{provider}` | 제공자별 키 암호화 저장·삭제(원문 미노출, `has_key`만 반환) |
| POST | `/api/eval/runs/{run_id}/rejudge` | 완료된 full 실행의 저장된 답변으로 **답변 재생성 없이** 선택 모델만 다시 채점(비용·시간 절약, 모델 추가 비교용). 실행 중 상태는 run의 `judge_status`로 표시 |

`llm_judge_json` 항목 예:
```json
{"evidence_source":"gold_chunks","prompt_version":"rag-judge.1",
 "results":{"openai":{"model":"...","status":"evaluated","faithfulness":0.86,"answer_relevance":1.0,
                       "claims":[...],"reason":"...","latency_ms":2310,"usage":{...}},
            "gemini":{"status":"error","reason":"rate_limited"},
            "anthropic":{...}},
 "ensemble":{"faithfulness":0.9,"answer_relevance":0.95,"evaluated_models":2}}
```

제외 규칙(기존 judge와 동일): `expected_behavior`가 guardrail/permission_denied/not_enough_info → excluded, 근거 원문 없음 → Faithfulness만 excluded(`missing_gold_evidence`), 빈 답변 → 0점 evaluated.

### 4.4 프런트엔드 변경

| 파일 | 변경 |
|---|---|
| `src/api/evalApi.js` | `getJudgeProviders`, `saveJudgeKey(provider,key)`, `deleteJudgeKey`, `rejudgeRun(runId, providers)` |
| `src/composables/useEvalSettings.js` | OpenAI 단일 키 → 제공자별 키 상태로 일반화(기존 데이터셋 생성 화면은 `provider='openai'`로 그대로 동작) |
| `src/composables/useEvalRuns.js` | `runForm.judge_providers: []`, 제공자 목록 로드, KPI 매핑(`answer.judge.*` 목표 0.80), 항목 상세에 모델별 점수·사유·주장 판정 |
| `src/views/EvalRunView.vue` | 아래 배치 |

```
┌ 새 평가 실행 ───────────────────────────────┐
│ 골드셋 [ ▼ ]   평가 범위 [전체 RAG 평가 ▼]   │
│ 검색 후보 수 N [10]  최종 문서 수 K [5]       │
│ LLM 심사 모델 (전체 RAG 평가에서만 표시)      │
│  [✓ GPT  모델명]  [✓ Gemini 모델명]  [ Claude 모델명 ]│
│   └ 키 없음: "키 등록" 링크 → 키 입력 모달    │
│   └ 서버 비활성: 회색 + "관리자 설정에서 꺼져 있음" │
│  ⓘ 질문·답변·근거 원문이 외부 AI 서비스로 전송됩니다 │
│ [▶ 실행 시작]                                 │
└─────────────────────────────────────────────┘
결과 영역: [Hit@10][NDCG@5][Faithfulness 평균][Answer Relevance 평균][Citation]
           모델별 표: 모델 | Faithfulness | Relevance | 평가/제외/오류 | 합의도
           완료된 실행: [다른 모델로 재채점] 버튼
```

- 체크박스는 `available=false`이면 비활성 + 사유 툴팁. 하나도 안 고르면 기존과 동일하게 실행.
- 외부 전송 안내 문구는 체크 시 항상 표시(첫 선택 시 확인 모달 1회).
- 수정 주석 규칙 준수: `// 2026.11.17(sooyeon.choi) 추가 - 3종 LLM 심사 모델 선택`.

### 4.5 시험 항목 1·2·4용 스크립트

| 스크립트 | 내용 |
|---|---|
| `scripts/eval_hit_at_k.py --goldset-id --n 10` | 운영 그래프 경로로 120건 실행 → 항목별 Hit@1/3/5/10, 정답 순위, 집계 CSV·MD. 골드셋 유효성 검사(E-04) 선행 |
| `scripts/eval_rerank_ndcg.py --goldset-id --k 5` | 재랭킹 전/후 순위, 청크별 재랭커 점수·관련도 표(rel 0/1, DQ-2 결정 시 등급), NDCG@5 |
| `scripts/eval_api_latency.py --goldset-id --base-url --warmup 3 --stream` | 4.3 E-16. 순차 호출, ms 단위 평균·p50/p90/p95/최대, 첫 토큰 시간 |

화면 실행과 스크립트는 같은 지표 함수(`retrieval_metrics.py`)를 써서 수치가 일치해야 한다. 완료 기준: 같은 골드셋으로 화면 결과와 스크립트 결과의 Hit@10·NDCG@5가 소수 넷째 자리까지 일치.

### 4.6 테스트

- 단위: 제공자별 요청 본문·응답 파싱(httpx MockTransport), JSON 파싱 실패 재시도, 429 백오프, 앙상블·합의도 계산, 제외 규칙, 키 미등록 400, 플래그 off 시 기존 config 스냅샷과 동일.
- 마이그레이션: 0012 upgrade/downgrade 왕복(`tests/test_database_migrations.py` 패턴).
- 외부 호출 실제 테스트는 `-m external_judge` 표식으로 분리(기본 실행 제외).

### 4.7 작업량(대략)

| 묶음 | 내용 | 규모 |
|---|---|---|
| A | E-01·E-03·E-15·E-17 지표/카탈로그/Excel 보완 | 0.5일 |
| B | E-04 골드셋 유효성 검사·재매핑 | 1일 |
| C | Judge 모듈 3종 + 집계 + 마이그레이션 0012 + API | 2~2.5일 |
| D | 화면(선택·키 모달·결과·재채점) | 1.5일 |
| E | 시험 스크립트 3종 + 화면/스크립트 일치 검증 | 1일 |

## 5. 결정 필요 목록

| ID | 질문 | 제안 |
|---|---|---|
| DQ-1 | 외부 AI API(GPT·Gemini·Claude) 호출이 절대 규칙 7("외부 AI API 호출 금지", "데이터 사내망 밖 반출 금지")·미결 Q-2와 충돌. 평가 전용 예외로 승인하는가? 운영 서버는 폐쇄망이라 호출 자체가 불가 | 예외 승인 시: `eval_external_judge_enabled` 기본 false, **외부망 접근 가능한 dev/평가 환경에서만** 켬. 운영은 끔. 미승인 시: 재채점 API 대신 "답변·근거 JSONL 내보내기 → 외부망 PC에서 채점 스크립트 → 점수 가져오기" 오프라인 방식으로 대체 |
| DQ-2 | NDCG@5의 "청크별 관련도"는 이진(정답 청크=1)인가, 등급(0/1/2)인가 | 1차 이진 유지 |
| DQ-3 | 채점 방식: 자체 루브릭(3모델 동일 프롬프트) vs RAGAS Faithfulness/ResponseRelevancy | 자체 루브릭 |
| DQ-4 | "80% 이상" 판정: 평균 점수 / 항목 통과율 / 3모델 다수결 | 시험 기관과 협의. 세 값 모두 산출 |
| DQ-5 | 응답시간 측정 대상: 비스트리밍 전체 응답 / 스트리밍 첫 토큰 / 둘 다, 동시 1명 순차 기준 맞는지, 쿼리 로그에 남길지 | 둘 다 측정, 평가 전용 계정으로 호출 후 로그 구분 |
| DQ-6 | 모델 ID: "GPT-6.1 sol", "Gemini 4 Argon"의 정확한 API 모델 ID, Claude는 `claude-opus-5-5` | 설정값으로만 두고 코드에 고정하지 않음 |
| DQ-7 | Faithfulness 근거: 정답 근거 문서(gold) 기준만인가, 실제 검색 컨텍스트 기준도 함께 볼 것인가 | 공식=gold, 진단=context 병행 |

## 6. 요구사항 정의서·기능 목록에 반영할 것

- 평가 기능(R8-7)에 시험 항목 4종(Hit@10, NDCG@5, LLM-as-a-Judge 3종 모델 Faithfulness·Answer Relevance, 평균 응답시간)과 판정 방식 추가.
- 외부 Judge 사용 시 데이터 반출 범위(질문·생성 답변·정답 근거 원문)와 승인 근거 명시.
- 신규 API 3종의 API ID 부여(`02_화면_API_ID_목록.md`).
