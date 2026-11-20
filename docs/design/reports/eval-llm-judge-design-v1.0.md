# 3종 LLM 심사(Faithfulness · Answer Relevance) 구현 설계 v1.0 (2026-11-17)

> **2026-11-19 대체됨** → `eval-llm-judge-design-v2.0.md`. 사전 점검용으로 심사 모델 1종(vLLM 오픈소스 또는 GPT-6.1 Sol)을 골라 합의서 PASS/FAIL 기준으로 판정하는 방식으로 바뀌었다. 이 문서는 기록용으로만 남긴다.

> 시험 항목 3 / 시험기관 요구 5번: "생성 답변을 정답 답변과 비교하지 않고, **근거 문서와의 일치(Faithfulness)** 와 **질의 의도에 대한 적절성(Answer Relevance)** 을 GPT·Claude·Gemini 3종 LLM-as-a-Judge로 평가."
> 입력 데이터는 `eval-batch-query-design-v1.0.md`의 일괄 질의 결과(질의별 생성 답변)와 정답 근거(시험기관 제공)를 그대로 쓴다.
> `eval-pipeline-review-20261117.md` 4장의 설계(골드셋 평가 실행에 붙이는 안)는 이 문서로 대체한다.

---

## 1. 무엇을 평가하나

| 지표 | 심사 LLM에 주는 것 | 묻는 것 | 점수 |
|---|---|---|---|
| **Faithfulness** (근거 충실성) | 생성 답변(본문) + **정답 근거 문서 내용** | 답변의 각 주장이 근거 문서로 뒷받침되는가 | 뒷받침된 주장 수 / 전체 주장 수 (0~1) |
| **Answer Relevance** (답변 적절성) | 질의문 + 생성 답변(본문) | 질의 의도에 직접·충분히 답했는가 | 1~5점 → (점수−1)/4 (0~1) |

- 정답 답변(gold answer)은 쓰지 않는다.
- 답변은 "본문" 정리본(인용 `[1]`, 사진 표식 `[IMG:…]`, 마크다운 기호 제거)을 쓴다. 심사 LLM이 볼 수 없는 표식 때문에 감점되지 않게 하기 위해서다.
- 두 지표는 **따로 호출**한다(서로의 판단이 섞이지 않게). 질의 120 × 모델 3 × 지표 2 = 720회.

## 2. 채점 프롬프트 (3개 모델 공통, `prompt_version = rag-judge.1`)

### 2.1 Faithfulness
```
[역할] 당신은 제조 작업표준(SOP) 답변의 사실 검증관입니다.
[근거 문서] {evidence}            ← 정답 근거 내용(근거가 여럿이면 번호 붙여 이어 붙임)
[답변] {answer_plain}
[지시]
1. 답변을 검증 가능한 사실 주장 단위로 나눕니다. 인사말·안내 문구("확인해 주세요" 등)는 주장이 아닙니다.
2. 각 주장이 근거 문서로 뒷받침되면 supported, 근거와 어긋나면 contradicted, 근거에 없으면 not_found로 판정합니다.
3. 근거 문서에 없는 지식으로 판단하지 않습니다.
[출력] JSON만:
{"claims":[{"text":"...","verdict":"supported|contradicted|not_found","evidence_quote":"근거 일부"}],
 "reason":"한두 문장"}
```
점수 = supported 수 / 주장 수 (서버가 계산 — LLM이 점수를 직접 쓰지 않게 해 계산 일관성 확보). 주장 0개 → `excluded: no_claims`.

### 2.2 Answer Relevance
```
[역할] 당신은 제조 현장 작업자 질문에 대한 답변 품질 평가자입니다.
[질문] {query}
[답변] {answer_plain}
[기준]
5: 질문에 직접 답하고 필요한 절차·수치를 빠짐없이 제시
4: 직접 답하나 사소한 누락 또는 불필요한 내용 약간
3: 부분적으로만 답함
2: 질문과 관련은 있으나 핵심에 답하지 않음
1: 무관하거나 답변 거절
사실 정확성은 평가하지 않습니다(별도 지표).
[출력] JSON만: {"score":1-5,"reason":"한두 문장"}
```

- 온도 0, 출력은 각 제공자의 JSON 강제 기능 사용(4.2). 파싱 실패 시 1회 재요청 → 그래도 실패면 `error: parse_error`.
- 프롬프트는 시험기관에 공개·합의한다(C-J1). 시험기관이 자체 프롬프트를 쓰면 그 문구로 `prompt_version`만 바꿔 같은 모듈로 돌린다.

## 3. 실행 위치 — 내부 개발 서버(외부망 사용 가능)

> 2026-11-17 사용자 결정: 시험은 **내부 개발 서버**에 올려 진행하며, 이 서버는 외부 AI API 호출이 가능하다. 폐쇄망 대응(오프라인 심사)은 하지 않는다.
> 절대 규칙 7의 예외로 **평가 심사 용도에 한해** 외부 AI API를 허용한다 → 변경로그에 결정 항목으로 추가 필요. 운영 서버에서는 설정 기본값(false)으로 꺼 둔다.

| 항목 | 내용 |
|---|---|
| 실행 | 화면에서 GPT / Claude / Gemini 체크 → **서버가 직접 호출**(백그라운드) |
| 켜고 끄기 | `eval_external_judge_enabled` 기본 false, 개발 서버 `.env`에서만 true |
| 외부 전송 범위 | 질의문, 생성 답변 본문, 정답 근거 내용. 문서 원본·이미지·내부 정보는 보내지 않는다 |
| 시험기관이 직접 심사할 경우 | 심사 입력 파일(JSONL) 내려받기만 제공(4.4) — 별도 오프라인 실행기는 만들지 않음 |

## 4. 구현

### 4.1 파일

```
app/evaluation/judge/
  prompts.py          # 2장 프롬프트, prompt_version
  schemas.py          # 입력·출력 데이터 구조, JSON 스키마
  providers/
    base.py           # JudgeProvider: async complete_json(system, user, schema) -> dict
    openai.py         # httpx, POST {base}/v1/chat/completions, response_format=json_schema
    anthropic.py      # httpx, POST {base}/v1/messages, 도구 1개(입력 스키마=출력 스키마) 강제 호출로 JSON 확보
    gemini.py         # httpx, POST {base}/v1beta/models/{model}:generateContent, responseMimeType=application/json + responseSchema
  engine.py           # 항목 × 모델 × 지표 실행, 제공자별 동시 실행 제한, 429/5xx 백오프(최대 3회), 시간·토큰 기록
  aggregate.py        # 모델별 평균, 3모델 평균, 통과율, 합의도
  io.py               # 심사 입력 JSONL 내보내기(시험기관 제공용)
app/evaluation/judge_runner.py  # 일괄 작업 단위 백그라운드 심사 실행(진행률·취소)
```

- 새 SDK 없이 httpx만 사용(의존성 추가 없음).
- API 키: 관리자 계정별 제공자 키 암호화 저장(기존 평가용 OpenAI 키 저장 방식을 제공자 3종으로 일반화, `tb_eval_judge_keys`). 키가 없으면 서버 환경변수 `EVAL_JUDGE_OPENAI_API_KEY`, `EVAL_JUDGE_ANTHROPIC_API_KEY`, `EVAL_JUDGE_GEMINI_API_KEY`를 사용. 키는 로그·결과 파일·응답에 쓰지 않는다.
- 모델 ID는 설정값으로만: `eval_judge_openai_model`, `eval_judge_anthropic_model`(예: `claude-opus-5-5`), `eval_judge_gemini_model`. 시험기관이 지정한 정확한 ID로 채운다(C-J2).

### 4.2 심사 입력 파일(JSONL, 질의 1건 = 1줄)
```json
{"job_id":12,"query_key":"Q001","query":"…","answer_plain":"…",
 "evidence":[{"seq":1,"source":"문서명 › 시트 › 단계","text":"…"}],
 "outcome_code":"success","prompt_version":"rag-judge.1"}
```
제외 규칙(심사 호출 안 함):
- 답변 생성 오류 → 두 지표 모두 `error: answer_error`(0점이 아니라 오류로 집계, 건수 표시)
- 근거 없음·거절 답변(`no_context`, `guardrail_blocked`) → **호출해서 그대로 채점**(Relevance가 낮게 나오는 것이 정확한 결과). Faithfulness는 주장 0개면 `excluded: no_claims`
- 정답 근거 없음 → Faithfulness만 `excluded: missing_evidence`

### 4.3 심사 결과 파일(JSONL)과 DB

결과 1줄 = 질의 × 모델 × 지표:
```json
{"query_key":"Q001","provider":"anthropic","model":"claude-opus-5-5","metric":"faithfulness",
 "status":"evaluated","score":0.857,"raw":{"claims":[…],"reason":"…"},
 "latency_ms":4210,"usage":{"input_tokens":1830,"output_tokens":410},"judged_at":"…"}
```

DB(일괄 질의 설계의 Alembic `0012`에 같이 넣음):
```sql
CREATE TABLE tb_eval_batch_judge (
  judge_id       BIGSERIAL PRIMARY KEY,
  job_id         BIGINT NOT NULL REFERENCES tb_eval_batch_jobs(job_id) ON DELETE CASCADE,
  query_key      TEXT NOT NULL,
  provider       TEXT NOT NULL CHECK (provider IN ('openai','anthropic','gemini')),
  model          TEXT NOT NULL,
  metric         TEXT NOT NULL CHECK (metric IN ('faithfulness','answer_relevance')),
  prompt_version TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('evaluated','excluded','error')),
  score          DOUBLE PRECISION,
  reason         TEXT,
  raw_json       JSONB,
  latency_ms     INTEGER,
  usage_json     JSONB,
  judged_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (job_id, query_key, provider, metric, prompt_version)
);
```
같은 키로 다시 올리면 덮어쓴다(재심사).

### 4.4 API (일괄 질의 API에 추가, 관리자 전용)

| 메서드·경로 | 설명 |
|---|---|
| `GET /api/eval/judge/providers` | 화면용: 제공자별 `{provider, label, model, has_key, available, reason}` |
| `PUT` / `DELETE /api/eval/judge/keys/{provider}` | 제공자 키 암호화 저장·삭제(원문 미노출, `has_key`만 반환) |
| `POST /api/eval/batch-jobs/{id}/judge` `{providers:[…], metrics:["faithfulness","answer_relevance"]}` | 심사 실행(백그라운드). 정답 근거 확정(`gold_status='confirmed'`) 후에만, 일괄 작업 완료 상태에서만. 이미 심사한 질의·모델·지표는 건너뛰고 `force=true`면 재심사 |
| `GET /api/eval/batch-jobs/{id}` | 응답에 `judge: {status, done, total, by_provider:{…}}` 추가 |
| `POST /api/eval/batch-jobs/{id}/judge/cancel` | 심사 취소(완료분 보존) |
| `GET /api/eval/batch-jobs/{id}/judge-input.jsonl` | 시험기관이 직접 심사할 때 넘길 입력 파일 |

심사 실행기: 일괄 질의 실행기와 별도 태스크. 제공자별 동시 호출 수 `eval_judge_concurrency_per_provider`(기본 4), 질의 순서와 무관하게 병렬(응답시간 시험에 영향 없음 — 일괄 질의가 끝난 뒤에만 실행 가능).

### 4.5 집계와 판정

| 값 | 계산 |
|---|---|
| 모델별 평균 | 모델·지표별 `evaluated` 점수 평균 |
| **3모델 평균(공식 후보)** | 질의별 평가된 모델 점수 평균 → 질의 평균 |
| 통과율 | 질의별 3모델 평균 ≥ 0.8인 질의 비율 |
| 다수결 통과율 | 3모델 중 2개 이상이 ≥ 0.8인 질의 비율 |
| 합의도 | 질의별 모델 간 점수 표준편차 평균. 편차 > 0.3인 질의는 "사람 확인 필요" 목록 |

판정 방식(평균 / 통과율 / 다수결)은 시험기관이 정한다(C-J3). 세 값 모두 산출하고 설정 `eval_judge_pass_rule`로 화면 판정에 쓸 값을 고른다. 오류·제외 건수는 항상 같이 표시한다.

### 4.6 결과 반영

- 일괄 질의 결과 CSV/xlsx에 열 추가: `Faithfulness(GPT/Claude/Gemini/평균)`, `Relevance(GPT/Claude/Gemini/평균)`, `심사 사유(모델별)`, `근거 없는 주장`.
- xlsx `심사 요약` 시트: 4.5 표, 모델 ID, 프롬프트 버전, 심사 일시.
- 화면(일괄 질의 탭): 작업 상세에 "LLM 심사" 영역
  - GPT / Claude / Gemini 체크박스(모델명 표시) + [심사 실행]. 키 없음 → "키 등록" 링크(모달), 설정 꺼짐 → 비활성 + 사유
  - 첫 실행 시 "질의·답변·근거 내용이 외부 AI 서비스로 전송됩니다" 확인 1회
  - 진행률(모델별 n/120), 취소, [다른 모델로 재심사]
  - 결과: 지표 카드 2개(3모델 평균, 목표 0.80), 모델별 표, 합의도, 질의별 상세(주장별 판정·사유), [심사 입력 내려받기]
  - 화면 탭은 일괄 질의 설계 F-19(2단계)였으나, 심사가 화면 클릭 실행이 필요하므로 **같이 구현**한다

## 5. 통과 가능성을 높이는 준비

| 항목 | 내용 |
|---|---|
| 사전 측정 | dev에서 임시 질의 20~30건으로 방식 A를 먼저 돌려 Faithfulness·Relevance 기준선 확인 |
| 근거 범위 합의 | 답변이 정답 근거보다 넓으면 not_found가 늘어 Faithfulness가 떨어진다. 시험기관에 "정답 근거 문서 **전체**" 또는 "정답 근거 + 시스템 인용 근거"로 판정하자고 요청(C-J4). 모듈은 `evidence_scope = gold | gold_document | gold_plus_cited` 설정으로 모두 지원 |
| 답변 간결화 | 시험용 설정으로 답변 프롬프트에 "질문에 필요한 내용만, 근거에 있는 내용만" 강화(기존 동작은 설정 꺼짐이 기본). 응답시간도 줄어듦 |
| 심사 타당성 확인 | 사람이 10건을 직접 판정해 3모델 평균과 비교(차이 크면 프롬프트 조정 후 시험기관과 재합의) |

## 6. 테스트

- 제공자별 요청 본문·응답 파싱(httpx MockTransport), JSON 실패 재요청, 429 백오프, 키 누락 오류
- Faithfulness 점수 계산(주장 0개·모두 지지·혼합), Relevance 정규화, 제외 규칙
- 집계: 평균·통과율·다수결·합의도, 오류 건수 분리
- 입력·결과 JSONL 왕복, 업로드 검증(모르는 질의ID·점수 범위 밖 거부)
- 실제 외부 호출 테스트는 `-m external_judge`로 분리(기본 실행 제외)

## 7. 일정 (일괄 질의 구현 뒤)

| 작업 | 규모 |
|---|---|
| judge 패키지(프롬프트·제공자 3종·엔진·집계) | 1.5일 |
| 심사 실행기·API·키 저장·마이그레이션·결과 열 | 1일 |
| 화면(일괄 질의 탭 + LLM 심사 영역) | 1.5일 |
| 개발 서버 사전 측정·타당성 확인 | 0.5일 |

## 8. 시험기관·사내 확인 필요

| ID | 질문 |
|---|---|
| C-J1 | 심사를 누가 실행하나(시험기관 / 우리). 우리가 하면 프롬프트 합의 |
| C-J2 | 모델 정확한 ID("GPT-6.1 sol", "Gemini 4 Argon", Claude Opus 5.5 = `claude-opus-5-5`) |
| C-J3 | 80% 판정 방식(3모델 평균 / 통과율 / 다수결) |
| C-J4 | Faithfulness 근거 범위(근거 조각 / 근거 문서 전체 / 근거 + 시스템 인용) |
| ~~DQ-1~~ | 해결(11-17): 내부 개발 서버에서 평가 심사 용도로 외부 AI API 허용. 변경로그 결정 항목 추가 필요 |
