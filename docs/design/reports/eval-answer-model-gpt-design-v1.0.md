# RAG 평가 답변 생성 모델 — GPT(OpenAI) 선택 설계 v1.0 (폐기)

> **폐기 (2026-11-23 사용자 결정).** 평가 실행에서 고르는 모델은 답변을 *만드는* 모델이 아니라 *심사하는* 모델이다. 답변은 챗봇 기본 모델이 만들고, 고른 모델(vLLM 또는 GPT-6.1 Sol)은 답변 생성 정확도(지표 3)만 판정한다 → `eval-llm-judge-design-v2.0.md`를 따른다. 이 문서 기준으로 일부 구현했던 코드(답변 생성 모델 선택·GPT 답변 생성)는 커밋 전에 되돌렸다. OpenAI 클라이언트 보완(오류 문구 키 가림, 파라미터 방식)만 심사에서 재사용하려고 남겼다.

- 작성: 2026-11-23 (sooyeon.choi)
- 목적: 전체 RAG 평가에서 답변 생성 모델로 사내 vLLM 모델 외에 **GPT(OpenAI API)** 도 고를 수 있게 한다. GPT를 고르면 **모델명과 API 키**를 입력한다. 1차 대상 모델은 **GPT-6.1 Sol**.
- 선행: 2026-11-23 "평가 답변 생성 모델 선택(vLLM)" 구현(`answer_llm_model`, `eval_vllm` 프로바이더)
- 관련: `eval-llm-judge-design-v2.0.md`(심사 모델 GPT-6.1 Sol 선택지), 메모 "평가 심사 외부 API 허용(개발 서버, 11-17)"
- 상태: **초안. 9장 D1 승인 전에는 구현하지 않는다**(절대 규칙 7 관련).

## 1. 원칙

1. **기본은 지금 동작 그대로.** 설정 `EVAL_EXTERNAL_ANSWER_LLM_ENABLED`(기본 **false**)가 켜진 서버에서만 GPT 선택지가 보이고 API가 받는다. 운영 서버는 켜지 않는다.
2. **바뀌는 것은 답변 생성 단계뿐이다.** 질문 분석·가드레일·검색·재정렬은 사내 모델 그대로(vLLM 선택 기능과 같은 범위). 인용 보정이 켜져 있으면 그 호출도 같은 GPT를 쓴다.
3. **API 키는 DB 실행 기록·로그·화면에 남기지 않는다.** 저장이 필요하면 기존 관리자별 암호화 저장(`tb_eval_settings.openai_api_key_enc`)만 쓴다. 실행에는 메모리로만 전달한다.
4. **호출 주소는 OpenAI 공식 주소(`api.openai.com`)로 고정한다.** 화면에서 주소를 받지 않는다(다른 곳으로 문서가 나가는 것 방지).
5. DB 마이그레이션 없음.

## 2. 외부로 나가는 데이터 (D1 판단 근거)

| 항목 | 내용 | 비고 |
|---|---|---|
| 질의문 | 평가 문항 질문 | |
| **검색된 문서 본문** | 재랭킹 상위 K개 청크 원문(시스템 프롬프트의 컨텍스트) | **심사 예외(11-17)보다 범위가 넓다.** 심사는 정답 근거·답변만 보냈다 |
| 시스템 프롬프트 | 챗봇 답변 지시문 | |
| 보내지 않는 것 | 이미지·도면 파일, 사용자 정보, 다른 컬렉션 | 답변 생성 입력이 텍스트뿐 |

- 120문항 × 문항당 컨텍스트 수천 토큰 규모. 응답의 `usage`(입력·출력 토큰)는 지금도 항목별로 저장되므로 실행 후 사용량을 합계로 보여 준다.

## 3. 사용자 흐름 (평가 실행 화면)

```
평가 범위: [전체 RAG 평가 ▼]
답변 생성 모델 종류: (●) 사내 vLLM   ( ) GPT (OpenAI)        ← 설정이 켜진 서버에서만 보임
 ├ 사내 vLLM: [gemma-4-12B-it (챗봇 기본) ▼]               (기존)
 └ GPT:
     모델명   [gpt-6.1-sol          ]  ← 기본값 = 설정 EVAL_OPENAI_ANSWER_DEFAULT_MODEL
     API 키   ✓ 저장된 키 사용 [키 변경]  /  [sk-...      ] □ 이 키 저장
     [연결 확인]  → "연결됨 · 응답 모델 gpt-6.1-sol-… · 0.8초"   (문서 내용 없이 짧은 문장 1건)
     ⚠ 검색된 문서 내용이 OpenAI로 전송됩니다. 반환 시간 지표는 외부 API 기준 참고값입니다.
[실행 시작]
```

- 실행 설정 카드·결과 xlsx 요약: `답변 생성 모델: GPT · gpt-6.1-sol (OpenAI)`, 토큰 사용량 합계.

## 4. API

### 4.1 실행 생성 `POST /api/eval/runs` (확장)
```json
{
  "goldset_id": 12, "scope": "full",
  "config": {
    "retrieval_top_n": 10, "rerank_top_k": 5,
    "answer_llm_backend": "openai",          // "vllm"(기본) | "openai"
    "answer_llm_model": "gpt-6.1-sol",
    "openai_api_key": "sk-...",              // 선택. 없으면 저장된 키
    "save_openai_api_key": false             // true면 암호화 저장(기존 키 교체)
  }
}
```
서버 처리
1. `answer_llm_backend == "openai"`인데 설정이 꺼져 있으면 **403** "이 서버에서는 외부 모델 평가가 꺼져 있습니다".
2. 모델명: 비면 400. 허용 문자 `[A-Za-z0-9._:-]`, 최대 100자.
3. 키: 요청 키 → 없으면 저장 키(`resolve_dataset_generation_openai_key`) → 둘 다 없으면 400.
4. 실행 설정(`config_json`)에는 `answer_llm_backend`, `answer_llm_model`, `answer_llm_key_source`(`input`/`saved`)만 저장한다. **키 원문·해시·끝자리는 저장하지 않는다.**
5. `start_run(run_id, secrets={"openai_api_key": key})` — 키는 실행 작업(메모리)에만 있다. 서버가 재시작되면 실행은 기존 규칙대로 "서버 재시작으로 중단됨"이 되고 키도 사라진다.

### 4.2 연결 확인 `POST /api/eval/settings/openai/check` (신규)
- 입력: `{model, openai_api_key?}` (키 없으면 저장 키)
- 동작: "연결 확인" 짧은 메시지 1건(문서 내용 없음)으로 `chat` 호출 → `{ok, model(응답에 적힌 모델), elapsed_ms, param_mode}` 또는 OpenAI 오류 문구(키 부분 가림).
- 같은 호출로 4.4의 파라미터 호환 방식을 정해 화면에 돌려준다.

### 4.3 모델 목록 `GET /api/eval/settings/dataset-generation/models` (확장)
- 응답에 `external_enabled: bool`, `openai_default_model: str`, `has_openai_api_key: bool` 추가 → 화면이 GPT 선택지 표시 여부를 정한다.

### 4.4 최신 GPT 모델 파라미터 호환
최근 OpenAI 추론형 모델은 Chat Completions에서 `max_tokens` 대신 `max_completion_tokens`를 요구하고, `temperature`는 기본값만 허용하는 경우가 있다. GPT-6.1 Sol의 정확한 제약은 **연결 확인으로 확인**한다(문서로 단정하지 않음).

| 방식 `param_mode` | 보내는 값 |
|---|---|
| `legacy` | `max_tokens`, `temperature` (지금 `OpenAILLMClient`) |
| `completion` | `max_completion_tokens`, `temperature` 생략 |

- `OpenAILLMClient`에 `param_mode` 인자를 추가한다(기본 `legacy` → 기존 데이터셋 생성·채팅 동작 그대로).
- 연결 확인에서 `legacy`가 "Unsupported parameter" 400이면 `completion`으로 다시 시도해 성공한 방식을 실행 설정에 저장(`answer_llm_param_mode`)하고 실행에 쓴다.
- 추론형 모델은 출력 한도에 추론 토큰이 포함될 수 있어, `completion` 방식의 기본 한도는 설정 `EVAL_OPENAI_MAX_COMPLETION_TOKENS`(기본 4096)로 따로 둔다.

## 5. 실행 경로

```
create_run ── secrets(키) ──▶ start_run(run_id, secrets) ─▶ _execute_run
                                                               │ (문항마다, 동시 1건 — 기존 full 규칙)
evaluate_end_to_end(item, config, collection, secrets)
  └ EvalRagPipeline.run(llm_provider="openai", llm_model=모델명, openai_api_key=키)
       └ resolve_llm_from_state → 기존 'openai' 프로바이더 → LLMService(OpenAILLMClient)
            └ generate_answer 노드: chat_stream (첫 토큰 시간 기록 그대로)
```

- `openai` 프로바이더는 이미 등록돼 있고 상태의 `llm_api_key`로 고른다. 평가에서만 `param_mode`를 넘기도록 팩토리 인자를 하나 늘린다(`eval_openai` 프로바이더로 분리해 채팅 경로는 건드리지 않는 쪽을 제안).
- 오류 처리: 401(키 오류)·404(모델 없음)는 **첫 문항에서 실행 전체 중단**(나머지 119건이 같은 오류로 끝나는 것 방지). 429·5xx는 문항 오류로 기록하고 계속(재시도 없음 — 반환 시간 왜곡 방지, 일괄 질의와 같은 원칙). 시간 제한은 `VLLM_TIMEOUT` 대신 `EVAL_OPENAI_TIMEOUT_S`(기본 120초).
- 오류 문구 저장 전 `sk-…` 형태를 가린다(OpenAI 오류 문구에 키 일부가 들어갈 수 있음).

## 6. 지표 영향

| 지표 | 영향 |
|---|---|
| 검색 Recall@10·NDCG@5 | 없음(검색은 사내 모델) |
| F2 정답 유사도·인용 지표 | 모델에 따라 달라짐 — 비교 목적 그대로 |
| 지표 4 반환 시간(첫 토큰·전체) | **외부 네트워크·OpenAI 대기열 시간 포함.** 사내 서빙 기준 목표(≤ 5초/15초)와 비교하면 안 됨 → 카드에 "외부 API 기준 참고값" 표시, 달성/미달 판정 숨김(제안) |
| 법령별 집계(합본) | 그대로 |

## 7. 수정 파일 (예상)

| 구분 | 파일 | 내용 |
|---|---|---|
| 설정 | `app/core/config.py` | `eval_external_answer_llm_enabled=False`, `eval_openai_answer_default_model=""`, `eval_openai_timeout_s=120`, `eval_openai_max_completion_tokens=4096` |
| 클라이언트 | `app/clients/openai_client.py` | `param_mode`(legacy/completion), 시간 제한 인자, 오류 문구 키 가림 |
| 평가 | `app/evaluation/adapters/gen_model_catalog.py` | `eval_openai` 프로바이더(모델·키·param_mode로 LLMService 생성) |
| 평가 | `app/evaluation/schemas.py` | `answer_llm_backend`, `openai_api_key`, `save_openai_api_key` (키는 저장 전 config에서 제거) |
| 평가 | `app/routes/evaluation.py` | 실행 생성 검증·키 해석·secrets 전달, 연결 확인 API, 모델 목록 확장 |
| 평가 | `app/evaluation/runner/eval_runner.py`·`run_registry.py` | `start_run(run_id, secrets)`, 401·404 즉시 중단 |
| 평가 | `app/evaluation/runner/e2e_evaluator.py` | backend별 프로바이더 선택 |
| 평가 | `app/evaluation/metric_catalog.py`·`excel_exporter.py` | 외부 모델 실행의 반환 시간 참고값 표시, 요약에 모델·토큰 합계 |
| 화면 | `useEvalRuns.js`·`EvalRunView.vue` | 모델 종류 선택, 모델명·키 입력, 연결 확인, 외부 전송 안내 |
| 테스트 | `test_eval_routes.py`·`test_eval_e2e.py`·`test_openai_client.py`(신규) | 아래 8장 |

## 8. 테스트 (OpenAI 실제 호출 없이 가짜 응답)
1. 설정 꺼짐 → GPT 실행 403, 모델 목록 `external_enabled=false`.
2. 키: 요청 키 / 저장 키 / 없음(400). 실행 기록(`config_json`)·로그에 키 문자열이 없음.
3. `save_openai_api_key=true` → 암호화 저장, 원문 미노출.
4. param_mode: legacy 400 "Unsupported parameter" → completion 재시도 성공, 실행 설정에 기록.
5. 401·404 → 첫 문항에서 실행 실패 처리, 429 → 해당 문항만 오류.
6. 오류 문구의 `sk-…` 가림.
7. 기존 vLLM 선택·기본 실행·데이터셋 생성 OpenAI 경로 회귀 없음.
8. 수동(개발 서버): GPT-6.1 Sol로 합본 3문항 실행 → 답변·인용·토큰 사용량 확인.

## 9. 결정 필요

| # | 질문 | 제안 |
|---|---|---|
| **D1** | 절대 규칙 7 예외 범위를 **RAG 답변 생성(검색된 문서 본문 전송)** 까지 넓힐지. 11-17 예외는 "평가 심사"(정답 근거·답변) 한정이었다 | 승인 시: **외부망 되는 내부 개발 서버에서만**, 설정 기본 false, 운영 끔. 변경로그 결정 항목으로 기록. 대상 컬렉션이 공개 법령(산안·중처)뿐인지 함께 확인 |
| D2 | API 키 보관 | 데이터셋 생성용 저장 키와 **공용**(관리자별 암호화). 요청마다 입력도 허용, 저장은 선택 |
| D3 | GPT-6.1 Sol의 **API 모델 ID** | 화면 이름과 API ID가 다를 수 있다 → OpenAI 콘솔/모델 목록에서 확인한 값을 `EVAL_OPENAI_ANSWER_DEFAULT_MODEL`에 넣는다(코드에 고정하지 않음) |
| D4 | 외부 모델 실행의 지표 4 | 값은 보여 주되 "외부 API 기준 참고값", 달성/미달 판정 숨김 |
| D5 | 401·404 시 실행 전체 중단 | 중단(제안) / 문항별 오류로 계속 |
| D6 | 모델명 입력 방식 | 자유 입력 + 기본값. 허용 목록(설정)으로 제한할지? → 제안: 자유 입력 |
