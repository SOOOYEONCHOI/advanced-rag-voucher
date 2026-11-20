# 시험 대응 일괄 질의·CSV 다운로드 최종 설계 v1.0 (2026-11-17)

> 앞선 문서 `eval-batch-query-requirements-20261117.md`(요구사항)의 결정 항목을 확정하고 구현 단위까지 내린 최종본이다. 값이 다르면 이 문서를 따른다.
> 대상 시험 항목: 1 검색 완전성(Recall@10), 3 LLM-as-a-Judge 입력 데이터, 4 평균 응답시간 · 관련 R8-7, N-4
> 3종 LLM 심사(GPT·Gemini·Claude) 자체는 이 문서 범위가 아니다(`eval-pipeline-review-20261117.md` 4장, 외부 반출 승인 DQ-1 대기).

---

## 0. 확정 사항

### 0.1 우리 쪽에서 확정한 것

| ID | 항목 | 확정값 | 근거 |
|---|---|---|---|
| F-01 | 실행 방식 | **일괄 작업 API**(등록 → 진행 조회 → 다운로드) + 이 API를 호출하는 **스크립트** 제공. 시험기관이 직접 호출해도, 우리가 입회하에 스크립트로 실행해도 같은 결과 | 시험기관 접속 방식 미정이라 두 경우 모두 지원 |
| F-02 | 답변 경로 | 운영 질의 API와 **같은 `RAGService.query()`** 를 서버 안에서 호출. 평가 전용 그래프 실행(`rag_pipeline_adapter`)은 쓰지 않음 | "We.RAG에 입력" 조건. 화면 챗봇과 같은 검색·재랭킹·생성 |
| F-03 | 실행 순서 | 질의 **1건씩 순차**, 동시에 도는 작업은 **1개**(나머지는 대기) | 응답시간 시험이 "순차 호출" 기준 |
| F-04 | 응답시간 정의 | `RAGService.query()` 진입 → 문서 검색 → 재랭킹 → 답변 생성·인용 정리 완료까지(ms). 기존 `processing_time_ms`와 같은 구간 | 시험 정의와 같은 구간. 질의 로그 값과도 일치 |
| F-05 | 응답 방식 | 비스트리밍 전체 응답 완료 기준. 첫 글자 시간은 측정하지 않음 | 시험 정의가 "최종 답변 생성 완료 시점" |
| F-06 | 워밍업 | 작업 시작 시 첫 질의 **3건**을 한 번 더 먼저 실행하고 결과·평균에서 제외(설정값) | 모델 첫 호출 지연 배제 |
| F-07 | 재시도 | **재시도 없음**(설정 기본 0). 실패는 실패로 기록 | 재시도하면 응답시간이 왜곡됨. 시험에서 정직한 수치 |
| F-08 | Recall@10 "상위 10개" | 재랭킹 **전** 하이브리드 검색 결과(`retrieved_chunks`, 운영 후보 40개) 중 중복 제거 후 상위 10개 | 시험 정의 "검색 결과 상위 10개". 재랭킹 후 10개(`reranked_chunks`)도 함께 기록해 기준이 바뀌어도 재실행 없이 재계산 |
| F-09 | Recall@10 판정 | 정답 청크 중 **1개 이상**이 상위 10개에 있으면 1. 기존 `hit_at_k()` 그대로 사용 | 시험기관 정의(1번 회신) |
| F-10 | 정답 청크 확정 | 시험기관 정답(근거 내용+출처) → 자동 매칭 → **사람이 검토 Excel에서 확정** → 확정본 업로드 | 청크 단위가 달라 자동만으로는 오판 가능 |
| F-11 | 자동 매칭 기준 | 출처(문서명·시트·단계)로 후보를 좁히고, 근거 내용의 문자 3-gram 중 청크에 들어 있는 비율 **≥ 0.5** 인 청크를 정답 후보로(여러 개 허용) | 7장 |
| F-12 | 결과 파일 | CSV(**UTF-8 BOM**, 엑셀에서 바로 열림) + 같은 내용의 xlsx(요약 시트 포함) | |
| F-13 | 답변 본문 정리본 | 원문과 별도로 인용 표시 `[1]`, 사진 표식 `[IMG:…]`, 마크다운 기호를 뺀 "본문" 열 | 3종 심사 입력용 |
| F-14 | 질의 로그 | `tb_query_logs`에 `input_mode='batch_eval'`로 기록. 관리자 통계·많이 찾는 질문에서 제외. **대화 이력(세션)은 저장하지 않음** | 운영 통계·대화 이력 오염 방지 |
| F-15 | 권한 | 작업 등록·조회·다운로드는 관리자만. 질의는 작업 등록자 권한으로 실행하고 기존 `_authorize_query_collection()` 그대로 거침 | 절대 규칙 8 |
| F-16 | 저장·실행 | PostgreSQL 신규 테이블 + 앱 프로세스 안 단일 실행기(기존 평가 실행과 같은 구조). Redis·Celery 없음 | 절대 규칙 4 |
| F-17 | 켜고 끄기 | `eval_batch_query_enabled` 기본 **false**. 끄면 API 404, 기존 동작 변화 없음 | 절대 규칙 6 |
| F-18 | 문서 동결 확인 | 작업 등록 시 컬렉션의 문서별 활성 버전 목록을 저장. 실행 중·정답 확정 후 버전이 바뀌면 결과에 경고 | 청크 ID에 버전 번호 포함(`{document_id}:{version_no}:…`) |
| F-19 | 화면 | 1단계는 API·스크립트만. 관리자 화면 "일괄 질의" 탭은 2단계(시험 일정 여유 시) | 11/23 전 필수 범위 우선 |

### 0.2 시험기관 확인이 필요한 것 (가정값으로 진행, 바뀌어도 재실행 불필요)

| ID | 질문 | 가정값 | 바뀔 때 영향 |
|---|---|---|---|
| C-01 | "상위 10개"가 재랭킹 전 기준인가 | 재랭킹 전 | 재랭킹 후 상위 10도 저장해 두므로 **재계산만**(API 6.7) |
| C-02 | 정답 청크 판정을 내용 겹침으로 할 때 기준 비율 | 0.5 | 설정값. 정답 재매칭만 다시 하면 됨 |
| C-03 | 응답시간 워밍업 제외 건수 | 3건 | 설정값 |
| C-04 | 시험기관 접속 방식(직접 호출 / 입회 실행) | 입회 실행 | 둘 다 지원 |
| C-05 | 정답 파일 형식 | 7.1 형식 | 열 이름 대응표만 바꾸면 됨 |

## 1. 범위

| 포함 | 제외 |
|---|---|
| 질의 파일 업로드, 순차 실행, 진행 조회·취소, 결과 CSV/xlsx | 3종 LLM 심사 실행(별도 문서) |
| 재랭킹 전/후 상위 10개, 단계별 시간 기록 | 스트리밍 첫 글자 시간 |
| 정답 근거 자동 매칭·검토 Excel·확정 업로드, Recall@10 계산 | NDCG@5 공식 산출(필요 시 같은 저장값으로 추가 가능) |
| 일괄 호출 스크립트 | 관리자 화면 탭(2단계) |

## 2. 구성

```
[시험기관 or 입회 실행 스크립트]
   │ ① POST /api/eval/batch-jobs (질의 파일) ─────────────┐
   │ ② GET  /api/eval/batch-jobs/{id}  (진행률)             │
   │ ③ GET  /api/eval/batch-jobs/{id}/results.csv          │
   ▼                                                        ▼
routes/eval_batch.py ──▶ tb_eval_batch_jobs / tb_eval_batch_items (PostgreSQL)
                               ▲
evaluation/batch/runner.py  (앱 안 단일 실행기, 순차)
   for item in items:  RAGService.query(..., input_mode="batch_eval", capture_retrieval=True)
                         validate → guardrail → analyze_and_rewrite → build_metadata_filter
                         → retrieve(후보 40) → rerank(10) → assemble_context(6)
                         → collect_answer_images → generate_answer → format_citations
                       → 답변·인용·상위 10(전/후)·단계별 시간 저장 → 다음 질의

정답 대조: POST gold → evaluation/batch/gold_matcher.py → tb_eval_batch_gold
           GET gold-review.xlsx → 사람 확인 → POST gold-review(확정) → Recall@10 계산
```

## 3. 데이터 모델 — Alembic `0012_eval_batch_query`

```sql
CREATE TABLE tb_eval_batch_jobs (
  job_id            BIGSERIAL PRIMARY KEY,
  name              TEXT NOT NULL,
  collection_name   TEXT NOT NULL,                -- qdrant_name
  status            TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','completed','failed','cancelled')),
  total_count       INTEGER NOT NULL,
  done_count        INTEGER NOT NULL DEFAULT 0,
  error_count       INTEGER NOT NULL DEFAULT 0,
  warmup_count      INTEGER NOT NULL DEFAULT 3,
  config_json       JSONB NOT NULL,               -- 실행 시점 설정 스냅샷(모델명, candidate/reranker/context top_k, threshold 등)
  doc_versions_json JSONB NOT NULL,               -- {document_id: version_no} 등록 시점
  summary_json      JSONB,                        -- 평균·p50·p90·p95·최대, 성공 건수, Recall@10
  gold_status       TEXT NOT NULL DEFAULT 'none'
                    CHECK (gold_status IN ('none','matched','confirmed')),
  error_message     TEXT,
  created_by        TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at        TIMESTAMPTZ,
  finished_at       TIMESTAMPTZ
);

CREATE TABLE tb_eval_batch_items (
  item_id            BIGSERIAL PRIMARY KEY,
  job_id             BIGINT NOT NULL REFERENCES tb_eval_batch_jobs(job_id) ON DELETE CASCADE,
  seq                INTEGER NOT NULL,             -- 파일 행 순서
  query_key          TEXT NOT NULL,                -- 시험기관 질의ID
  query_text         TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','ok','error','skipped')),
  outcome_code       TEXT,                         -- success / no_context / guardrail_blocked / llm_error ...
  answer_text        TEXT,
  answer_plain       TEXT,                         -- F-13 정리본
  citations_json     JSONB,                        -- 인용 문서명·시트·단계·청크ID·내용
  retrieved_top_json JSONB,                        -- 재랭킹 전 상위 10 [{rank, chunk_id, document_id, filename, sheet, step, score, text}]
  reranked_top_json  JSONB,                        -- 재랭킹 후 상위 10 (같은 구조 + rerank score)
  response_ms        INTEGER,                      -- F-04
  timing_json        JSONB,                        -- 노드별 시간(s) 원본
  log_id             BIGINT,                       -- tb_query_logs 연결
  error_message      TEXT,
  started_at         TIMESTAMPTZ,
  finished_at        TIMESTAMPTZ,
  UNIQUE (job_id, seq)
);
CREATE INDEX ix_tb_eval_batch_items_job ON tb_eval_batch_items(job_id, seq);

CREATE TABLE tb_eval_batch_gold (
  gold_id          BIGSERIAL PRIMARY KEY,
  job_id           BIGINT NOT NULL REFERENCES tb_eval_batch_jobs(job_id) ON DELETE CASCADE,
  query_key        TEXT NOT NULL,
  evidence_seq     INTEGER NOT NULL,               -- 한 질의의 근거 순번
  source_doc       TEXT,                           -- 시험기관 근거 문서명
  source_loc       TEXT,                           -- 시험기관 근거 위치(시트·단계·페이지)
  evidence_text    TEXT NOT NULL,
  matched_json     JSONB,                          -- 자동 매칭 후보 [{chunk_id, score, filename, sheet, step}]
  confirmed_ids    JSONB,                          -- 사람이 확정한 chunk_id 목록
  match_status     TEXT NOT NULL DEFAULT 'auto'
                   CHECK (match_status IN ('auto','unmatched','confirmed','excluded')),
  UNIQUE (job_id, query_key, evidence_seq)
);

-- 질의 로그 입력 경로에 batch_eval 추가 (0009의 CHECK 교체)
ALTER TABLE tb_query_logs DROP CONSTRAINT <0009에서 만든 input_mode CHECK 이름>;
ALTER TABLE tb_query_logs ADD CONSTRAINT ck_tb_query_logs_input_mode
  CHECK (input_mode IN ('text','voice','recommended','popular','batch_eval'));
```

- downgrade: 세 테이블 삭제, `batch_eval` 로그 행은 `input_mode='text'`로 바꾸지 않고 **삭제하지도 않는다** — downgrade 전에 `batch_eval` 행이 있으면 중단하고 안내(데이터 보존 우선). CHECK를 0009 상태로 되돌림.
- 정답(근거) 원문은 시험기관 자료이므로 작업 삭제 시 함께 삭제(CASCADE).

## 4. 서버 변경 — 기존 코드

| 파일 | 변경 | 기본 동작 영향 |
|---|---|---|
| `app/services/rag_service.py` `query()` | 인자 `capture_retrieval: bool = False` 추가. True일 때만 응답에 `retrieved_chunks`(재랭킹 전 상위 10)를 담음. `input_mode == "batch_eval"`이면 `_store_history_turn()` 건너뜀 | 없음(기본 False, 기존 입력 경로 그대로) |
| `app/models/data_models.py` `QueryResponse` | `retrieved_chunks: List[ChunkSummary] = field(default_factory=list)` 추가, `ChunkSummary`에 `sheet_name`, `step_no`, `rank` 선택 필드 추가 | 빈 목록이 기본 → 기존 응답에 빈 배열 1개 추가. 프런트는 사용 안 함 |
| `app/routes/query.py` | 변경 없음(외부 `/api/query/`에는 `capture_retrieval` 노출 안 함) | 없음 |
| `app/repositories/stats_repository.py` | 통계 질의에 `input_mode <> 'batch_eval'` 조건 | 기존 데이터에는 해당 행이 없으므로 수치 변화 없음 |
| `app/core/config.py` | 8장 설정값 | 없음 |
| `app/main.py`(라우터 등록부) | `eval_batch` 라우터 등록, 기동 시 `running` 작업 정리 | 설정 꺼짐이면 라우트가 404 |

`collection_question_repository.py`의 많이 찾는 질문은 이미 `input_mode IN ('text','voice')`라 변경 불필요.

## 5. 신규 모듈

```
app/evaluation/batch/
  __init__.py
  file_reader.py     # CSV(utf-8/utf-8-sig/cp949 자동 판별)·xlsx 읽기, 열 이름 대응, 행 검증
  runner.py          # 단일 실행기: 대기 작업 1개씩, 워밍업 → 순차 실행 → 요약 계산
  text_clean.py      # F-13 답변 본문 정리
  gold_matcher.py    # 7장 자동 매칭
  recall.py          # Recall@10 계산 (retrieval_metrics.hit_at_k 재사용)
  exporter.py        # CSV·xlsx·정답 검토 xlsx (excel_exporter.safe_excel_text 재사용)
app/repositories/eval_batch_repository.py
app/routes/eval_batch.py
scripts/eval_batch_query.py
```

### 5.1 실행기(runner) 규칙

1. 앱 기동 시: `running` 작업 → `failed`(사유 "서버 재시작으로 중단, 완료 n건 보존"). 이어하기는 같은 파일로 새 작업 등록(완료 건 재실행) — 단순성 우선.
2. 실행 루프는 `asyncio` 태스크 1개. 대기 작업을 `created_at` 순으로 하나씩 꺼냄(`SELECT … FOR UPDATE SKIP LOCKED`).
3. 워밍업: 첫 `warmup_count`건 질의를 먼저 실행하고 결과 버림. 워밍업 실패 시 작업 `failed`(LLM·검색 서버 이상 조기 발견).
4. 각 질의: 취소 요청 확인 → `RAGService.query(query, user_id=작업등록자, collection_name, input_mode="batch_eval", capture_retrieval=True)` → 저장 → `done_count` 증가.
5. `response_ms` = 응답의 `processing_time_ms`(F-04). 질의 사이에 대기 없음.
6. 예외(타임아웃 포함)는 `status='error'`, `error_message` 저장 후 다음 질의. 재시도 없음(F-07).
7. 끝나면 요약 계산(6.6) → `completed`. 취소면 완료 건 보존 후 `cancelled`.
8. 질의 1건 제한 시간: `eval_batch_query_timeout_s`(기본 120초). 초과 시 오류 처리.

### 5.2 단계별 시간 묶음 (`timing_json` → CSV 열)

| CSV 열 | 합산하는 노드(`timed_node` 이름) |
|---|---|
| 검색(ms) | `validate_input`, `guardrail`, `analyze_and_rewrite`, `build_metadata_filter`, `retrieve` |
| 재랭킹(ms) | `rerank` |
| 답변생성(ms) | `assemble_context`, `collect_answer_images`, `generate_answer`, `format_citations`, `fallback_handler`, `build_response` |
| 응답시간(ms) | `processing_time_ms`(서비스 전체, 위 세 합보다 약간 큼 — 로그 기록 등 포함) |

## 6. API 명세

모두 관리자 인증(`get_current_admin`), `eval_batch_query_enabled=false`면 404. API ID는 `02_화면_API_ID_목록.md`에서 부여(가칭 API-EVB-01~08).

### 6.1 작업 등록 — `POST /api/eval/batch-jobs` (multipart)

| 필드 | 필수 | 설명 |
|---|---|---|
| `file` | ○ | 질의 파일 CSV/xlsx. 열 `질의ID`, `질의문` (영문 `query_id`, `query`도 인식) |
| `collection_name` | ○ | 대상 컬렉션(qdrant_name). 접근 권한 검사 |
| `name` | | 작업 이름(기본: 파일명) |
| `warmup_count` | | 기본 설정값(3) |

검증: 행 1~500, 질의ID 중복 금지, 빈 질의문 금지, 질의문 2,000자 이하. 오류 시 400 + `[{row, column, reason}]`, 작업 미생성.
응답 202: `{"job_id": 12, "status": "pending", "total": 120, "queue_position": 0}`

### 6.2 진행 조회 — `GET /api/eval/batch-jobs/{job_id}`
```json
{"job_id":12,"name":"시험 120","status":"running","total":120,"done":37,"errors":0,
 "started_at":"…","eta_seconds":750,"doc_version_changed":false,
 "summary":null,"gold_status":"none"}
```
완료 후 `summary`: `{"ok":118,"error":2,"response_ms":{"mean":9013,"p50":8700,"p90":11160,"p95":11800,"max":14859},"recall_at_10":null}`

### 6.3 목록 — `GET /api/eval/batch-jobs?limit=20`
### 6.4 취소 — `POST /api/eval/batch-jobs/{job_id}/cancel`
### 6.5 삭제 — `DELETE /api/eval/batch-jobs/{job_id}` (실행 중이면 409)
### 6.6 결과 다운로드 — `GET /api/eval/batch-jobs/{job_id}/results.csv` · `results.xlsx`
완료·취소 상태에서만(실행 중 409). 9장 열 구성. 요약 통계 규칙:
- 응답시간 평균·백분위는 `status='ok'` 건만. 오류 건수는 별도 표기(숨기지 않음).
- `outcome_code`가 `no_context`·`guardrail_blocked`인 건도 "응답한 건"이므로 평균에 포함하고, 결과 유형별 평균을 함께 표시.

### 6.7 정답 대조
| 메서드·경로 | 설명 |
|---|---|
| `POST /api/eval/batch-jobs/{id}/gold` (multipart `file`) | 정답 파일 업로드 → 자동 매칭 → `gold_status='matched'`. 다시 올리면 덮어씀 |
| `GET /api/eval/batch-jobs/{id}/gold-review.xlsx` | 검토용 Excel: 질의ID·근거 내용·출처 / 자동 매칭 후보(청크ID·문서·시트·단계·점수·청크 내용) / **확정 청크ID 입력 열** / 제외 여부 열 |
| `POST /api/eval/batch-jobs/{id}/gold-review` (multipart `file`) | 사람이 고친 검토 Excel 업로드 → `confirmed_ids` 저장 → `gold_status='confirmed'` → Recall@10 계산·요약 갱신 |
| `GET /api/eval/batch-jobs/{id}/recall?basis=retrieved|reranked&k=10` | 기준을 바꿔 재계산(C-01 대응). 재실행 불필요 |

## 7. 정답 근거 자동 매칭 (`gold_matcher.py`)

### 7.1 정답 파일 형식 (시험기관 안내용)

| 열 | 필수 | 예 |
|---|---|---|
| 질의ID | ○ | Q001 |
| 근거순번 | | 1 (근거가 여러 개면 행을 나눔) |
| 근거 문서명 | ○ | 파일명 또는 문서 제목 |
| 근거 위치 | | 시트명 / 단계 번호 / 페이지 |
| 근거 내용 | ○ | 근거 문장 원문 |

### 7.2 절차

1. **문서 찾기:** 근거 문서명을 정규화(확장자·공백·괄호·버전 표기 제거, 소문자)해 컬렉션의 `tb_documents.original_filename`과 비교. 일치 없으면 포함 관계 → 그래도 없으면 **컬렉션 전체**를 후보로(경고 표시).
2. **후보 청크:** 그 문서의 **활성 버전** 청크(`tb_chunks`, `version_no = tb_documents.version_no`). 근거 위치에 시트명·단계 번호가 있으면 `sheet_name`·`step_no`로 먼저 좁힘(좁혀서 0건이면 문서 전체로 되돌림).
3. **점수:** 근거 내용과 청크 내용을 정규화(공백·기호 제거, 전각→반각, 소문자)한 뒤 문자 3-gram 집합으로 바꿔
   `포함률 = |근거 ∩ 청크| / |근거|`. 근거가 6자 미만이면 부분 문자열 포함 여부로 판정.
4. **판정:** 포함률 ≥ 0.5(`eval_batch_gold_match_threshold`)인 청크 전부를 후보로(점수순). 하나도 없으면 `unmatched` + 최고점 상위 3개를 참고로 표시.
5. 사람 확인: 검토 Excel에서 후보를 지우거나 다른 청크ID를 넣거나 "제외"로 표시. 제외된 질의는 Recall@10 분모에서 빠지고 요약에 건수 표시.

### 7.3 Recall@10 계산 (`recall.py`)

- 질의별 정답 집합 = 그 질의의 모든 근거의 `confirmed_ids` 합집합.
- `hit = hit_at_k(retrieved_top 의 chunk_id 순서, 정답 집합, 10)` (기존 함수, 중복 제거 포함).
- 요약 = 적중 질의 수 / (정답 확정 질의 수). 실행 오류 질의는 0(미적중)으로 셈 — 숨기지 않음.
- 실행 당시 버전(`doc_versions_json`)과 정답 확정 시점 버전이 다르면 해당 질의에 "버전 불일치" 표시.

## 8. 설정값 (`app/core/config.py`)

| 이름 | 기본 | 설명 |
|---|---|---|
| `eval_batch_query_enabled` | false | 기능 전체 켜고 끔 |
| `eval_batch_max_rows` | 500 | 파일 최대 행 |
| `eval_batch_warmup_count` | 3 | F-06 |
| `eval_batch_retry_count` | 0 | F-07 |
| `eval_batch_query_timeout_s` | 120 | 질의 1건 제한 |
| `eval_batch_top_n_record` | 10 | 재랭킹 전/후 기록 개수 |
| `eval_batch_gold_match_threshold` | 0.5 | F-11 |
| `eval_batch_upload_max_mb` | 10 | 업로드 파일 크기 |

## 9. 결과 파일 열 구성 (CSV·xlsx `질의별 결과` 시트 공통)

| # | 열 | 내용 |
|---|---|---|
| 1 | 순번 | 파일 행 순서 |
| 2 | 질의ID | |
| 3 | 질의문 | |
| 4 | 상태 | 정상 / 오류 |
| 5 | 결과유형 | 답변 / 근거 없음 / 차단 / 오류 (`outcome_code` 변환) |
| 6 | 생성답변(원문) | |
| 7 | 생성답변(본문) | F-13 |
| 8 | 인용 출처 | `[1] 문서명 › 시트 › 단계 n` 줄바꿈 구분 |
| 9 | 인용 근거 내용 | 인용 번호별 청크 원문(전문, 32,000자 초과 시 xlsx만 잘림 표시) |
| 10 | 검색 상위10 | `순위. 문서명 › 시트 › 단계 [청크ID]` |
| 11 | 재랭킹 상위10 | 같은 형식 + 점수 |
| 12 | Recall@10 적중 | 1 / 0 / (정답 미확정이면 빈칸) |
| 13 | 정답 적중 순위 | 상위 10 안 첫 정답 순위 |
| 14 | 응답시간(ms) | F-04 |
| 15 | 검색(ms) · 16 재랭킹(ms) · 17 답변생성(ms) | 5.2 |
| 18 | 오류내용 | |
| 19 | 실행시각 | |

xlsx `요약` 시트: 작업명, 컬렉션, LLM 모델명, 검색 설정(후보·재랭킹·컨텍스트 수, 임계값), 실행 시작·종료, 워밍업 건수, 전체/정상/오류 건수, 응답시간 평균·p50·p90·p95·최대(결과유형별 포함), Recall@10(기준·정답 확정 건수·제외 건수), 문서 버전 변경 경고.
파일 공통: Excel 수식 주입 방지(`=`,`+`,`-`,`@` 시작 값 앞에 `'`), 내부 IP·설정 비밀값 미포함.

## 10. 스크립트 `scripts/eval_batch_query.py`

```bash
python scripts/eval_batch_query.py \
  --base-url <서버 주소> --collection <qdrant_name> \
  --file 시험질의_120.xlsx [--gold 정답근거.xlsx] --out ./result
# 로그인 계정은 환경변수 EVAL_ADMIN_ID / EVAL_ADMIN_PASSWORD (인자로 받지 않음)
```
동작: 로그인 → 작업 등록 → 10초마다 진행률 출력 → 완료 시 `results.csv`·`results.xlsx` 저장 → `--gold`가 있으면 정답 업로드 후 `gold-review.xlsx` 저장. 시험기관 배포용 사용법을 파일 머리 주석과 `docs/`에 같이 둔다.

## 11. 테스트·완료 기준

| 구분 | 내용 |
|---|---|
| 단위 | 파일 읽기(인코딩 3종·열 이름 대응·오류 행 보고), 본문 정리, 3-gram 포함률·문서명 정규화, Recall@10(중복·정답 다건·오류 질의), 요약 통계(백분위), CSV BOM·수식 주입 방지 |
| 서비스 | `capture_retrieval=False`일 때 `QueryResponse`가 기존과 같음(빈 배열 외 동일), `batch_eval`일 때 대화 이력 미저장, 통계 제외 |
| API | 설정 꺼짐 404, 비관리자 403, 권한 없는 컬렉션 403, 실행 중 다운로드·삭제 409, 취소 시 완료분 보존, 재기동 시 `running` 정리 |
| 마이그레이션 | 0012 upgrade/downgrade 왕복, `batch_eval` 행 존재 시 downgrade 중단 |
| 리허설(dev) | 임시 질의 120건 실행 → 120건 결과 행, 오류 0, `response_ms` 평균이 같은 기간 `tb_query_logs.response_time_ms` 평균과 ±5% 이내, 스크립트로 받은 CSV를 엑셀에서 열어 한글 깨짐 없음 |

기존 회귀: `pytest -q -m "not e2e and not voice"` 기준선(473/11/3) 유지.

## 12. 되돌리기

1. `eval_batch_query_enabled=false` → 즉시 기능 정지(코드 그대로 두어도 기존 동작과 같음).
2. 완전 제거: `alembic downgrade 0011`(batch_eval 로그 행이 있으면 먼저 처리) → 신규 파일 삭제 → `rag_service.py`·`data_models.py`·`stats_repository.py` 변경분 되돌림.

## 13. 일정

| 날짜 | 작업 |
|---|---|
| 11/18 | 마이그레이션 0012, 저장소, `RAGService` 변경, 실행기 |
| 11/19 | API 6.1~6.6, CSV·xlsx 출력, 본문 정리 |
| 11/20 | 정답 매칭·검토 Excel·Recall@10(6.7, 7장) |
| 11/21 | 스크립트, 테스트, dev 리허설 120건, 보고서 |
| 11/23 | 시험 데이터 수령 → 업로드·실행 → 정답 매칭·확인 → 문서 동결 |
| 11/24~ | 리허설 결과 점검 후 시험 |

(관리자 화면 탭 F-19는 이후 1일)

## 14. 요구사항 정의서·기능 목록에 반영할 것

- R8-7: "API 일괄 질의(파일 업로드)·결과 CSV/xlsx 다운로드·정답 근거 대조·Recall@10" 추가.
- N-4: 응답시간 측정 정의(F-04~F-07) 명시, 목표 평균 15,000ms(앞선 검토).
- API 목록: 신규 API 8종 ID 부여. 테이블 정의서: 신규 테이블 3종, `tb_query_logs.input_mode`에 `batch_eval` 추가.
