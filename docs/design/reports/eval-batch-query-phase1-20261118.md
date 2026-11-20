# 일괄 질의·CSV 다운로드·정답 근거 대조 구현 보고서 (2026-11-18)

> 설계: `eval-batch-query-design-v1.0.md`(최종) · 요구사항: `eval-batch-query-requirements-20261117.md`
> 관련: R8-7(평가 실행), N-4(응답 시간), 시험 항목 1(Recall@10 기록), 3(심사 입력 데이터), 4(평균 응답시간)
> 주석 규칙: `2026.11.18(sooyeon.choi) 추가/수정 - 설명`

## 1. 요약

시험기관은 화면에서 질의를 하나씩 입력하지 않고 **API로 질의 파일을 올려 120건을 한 번에 실행**할 수 있습니다. 질의별 답변·인용·검색 상위 10·응답시간은 **CSV(UTF-8 BOM)·xlsx**로 내려받습니다. 같은 흐름을 그대로 실행하는 스크립트도 함께 만들었습니다.

```
POST /api/eval/batch-jobs (질의 파일)  → 202 job_id
GET  /api/eval/batch-jobs/{id}          → 진행률·남은 시간·요약
GET  /api/eval/batch-jobs/{id}/results.csv | results.xlsx
서버: 질의 1건씩 순차로 RAGService.query(input_mode="batch_eval", capture_retrieval=True)
     → 화면 챗봇·/api/query/와 같은 검색 → 재랭킹 → 답변 생성
```

이번 범위: 설계 13장의 11/18~20분입니다.
- 마이그레이션, 저장소, `RAGService` 변경, 실행기, API 6.1~6.6, CSV·xlsx, 본문 정리
- **6.7·7장 정답 근거 대조**: 자동 매칭 → 검토 Excel → 확정 → Recall@10 계산·재계산
- 10장 스크립트(정답 업로드·검토본 업로드 포함)

dev 백엔드 이미지를 다시 빌드해 dev DB를 0012로 올렸고, dev에서만 `EVAL_BATCH_QUERY_ENABLED=true`로 켰습니다.
다음 단계: dev 120건 리허설(11장 기준), 3종 LLM 심사.

## 2. 확정 사항 반영

| ID | 구현 |
|---|---|
| F-01 | API 6종 + `scripts/eval_batch_query.py` |
| F-02 | 실행기가 `RAGService.query()`를 직접 호출(평가 전용 그래프 어댑터 안 씀) |
| F-03 | 질의 순차, 동시 실행 작업 1개. 작업을 꺼낼 때 running 작업이 있으면 대기하고, advisory lock으로 꺼내기를 직렬화해 워커가 여럿이어도 안전 |
| F-04/F-05 | `response_ms` = `processing_time_ms`(서비스 진입 → 검색 → 재랭킹 → 답변·인용 정리 완료), 비스트리밍 |
| F-06 | 앞 `warmup_count`건(기본 3)을 한 번 더 먼저 실행하고 결과는 버림. 워밍업이 실패하면 작업을 `failed`로 끝냄(서버 이상 조기 발견) |
| F-07 | 재시도 없음. 실패·시간 초과(`eval_batch_query_timeout_s`, 기본 120초)는 `오류`로 기록하고 다음 질의로 넘어감 |
| F-08 | 재랭킹 **전** 검색 결과를 중복 제거한 상위 10개(`retrieved_top_json`)와 재랭킹 후 상위 10개(`reranked_top_json`)를 함께 저장 |
| F-12 | CSV UTF-8 BOM + xlsx(요약 시트 + 질의별 결과 시트) |
| F-13 | `answer_plain`: 인용 `[1]`, 사진 `[IMG:…]`, 마크다운 기호 제거(원문은 `answer_text`에 보존) |
| F-14 | `input_mode='batch_eval'`로 질의 로그 기록. **세션을 쓰지 않아 대화 이력이 남지 않음.** 관리자·사용자 통계, 부서·사용자 순위, 문서 참조 집계에서 제외 |
| F-15 | 관리자만 사용. 질의는 작업 등록 관리자 계정으로 실행 |
| F-16 | PostgreSQL 테이블 + 앱 안 단일 실행기(Redis·Celery 없음). 재기동하면 running 작업은 `failed`(완료분 보존)로 정리하고, 대기 작업은 이어서 실행 |
| F-17 | `eval_batch_query_enabled` 기본 false. 끄면 모든 경로가 404 |
| F-18 | 등록 시점 문서 버전 스냅샷 저장. 조회·다운로드 때 바뀌었으면 `doc_version_changed=true`, 요약 시트에 경고 |

응답시간 통계는 정상 건만으로 계산합니다(평균·p50·p90·p95·최대·최소, 결과 유형별 평균). 오류 건수는 따로 표시하고 숨기지 않습니다.
`llm_error`·`retrieval_error`·`system_error`·`validation_error`처럼 답변을 만들지 못한 결과 코드는 상태를 `오류`로 둡니다.

## 2-1. 정답 근거 대조 (설계 6.7·7장)

```
POST /api/eval/batch-jobs/{id}/gold            정답 파일 → 자동 매칭(다시 올리면 덮어씀)
GET  /api/eval/batch-jobs/{id}/gold-review.xlsx  검토 Excel(검토 / 후보 상세 / 안내 시트)
POST /api/eval/batch-jobs/{id}/gold-review     사람이 고친 검토 Excel → 확정 → Recall@10
GET  /api/eval/batch-jobs/{id}/recall?basis=retrieved|reranked&k=10   기준을 바꿔 재계산(재실행 불필요)
```

| 단계 | 규칙 |
|---|---|
| 정답 파일 | 열 `질의ID`·`근거 문서명`·`근거 내용`(필수), `근거순번`·`근거 위치`(선택). 근거순번이 없으면 질의별로 1부터 붙임. 작업에 없는 질의ID·빈 근거·중복 순번은 행 번호와 함께 400으로 반환하고 반영하지 않음 |
| 문서 찾기 | 문서명 정규화(확장자·괄호·버전 표기·공백·기호 제거, NFKC·소문자) 후 `original_filename`·`title`과 일치 → 포함 관계 → 없으면 컬렉션 전체(검토 Excel에 "못 찾음" 표시) |
| 후보 청크 | 활성 버전 청크(`tb_chunks`, 검색과 같은 chunk_id). 근거 위치에 시트명·단계 번호(`3단계`, `단계 3`, `step 3`)가 있으면 먼저 좁힘. 그 안에서 못 찾으면 문서 전체로 되돌림 |
| 점수 | 문자 3-gram 포함률 `|근거 ∩ 청크| / |근거|`(근거가 6자 미만이면 포함 여부) |
| 판정 | 포함률 ≥ `eval_batch_gold_match_threshold`(0.5)인 청크 전부(최대 10개, 점수순) → "자동 매칭". 없으면 "매칭 없음" + 최고점 3개를 참고 후보로 표시 |
| 검토·확정 | `확정 청크ID` 칸에 자동 후보가 미리 채워져 있음. 사람이 수정(쉼표·줄바꿈 구분)하거나 `제외(Y)` 표시. 컬렉션에 없는 청크ID, 빠진 근거, 정답 파일에 없는 근거가 있으면 400으로 반환하고 확정하지 않음 |
| Recall@10 | 질의별 정답 = 제외되지 않은 근거의 확정 청크 합집합. 재랭킹 **전** 상위 10(중복 제거)에 1개 이상 있으면 적중(`hit_at_k` 재사용). 분모 = 정답이 확정된 질의. 실행 오류 질의는 미적중으로 셈. 근거가 모두 제외됐거나 확정 청크가 없는 질의는 분모에서 빼고 건수 표시. 정답 청크 ID의 버전이 작업 등록 시점 문서 버전과 다르면 `version_mismatch` 건수 표시 |
| 결과 반영 | 정답 확정 뒤에는 진행 조회 `summary.recall_at_10`, CSV·xlsx의 `Recall@10 적중`·`정답 적중 순위` 열, xlsx 요약 시트에 자동으로 들어감 |

## 2-2. 첫 토큰 시간·NDCG@5 추가 (사용자 요청, 11-18)

| 항목 | 정의 |
|---|---|
| 첫 토큰(ms) | 요청 시작 → 검색 → 재랭킹 → **LLM 첫 답변 토큰 수신**. 답변 생성 노드는 원래 LLM을 스트리밍으로 호출하므로, 실행 경로를 바꾸지 않고 첫 토큰을 받은 시각만 기록함 |
| 재시도 | LLM을 다시 생성하면 덮어써서 마지막 생성 기준이 됨(화면도 재시도 때 앞 글자를 지움) |
| 값이 없는 경우 | 차단·검색 결과 없음 등 답변 생성 노드를 거치지 않은 질의는 빈칸 |
| 요약 | 정상 건 중 값이 있는 건으로 평균·p50·p90·p95·최대 |
| NDCG@5 | 재랭킹 **후** 상위 5(중복 제거)·이진 관련도(`ndcg_at_k` 재사용). Recall과 같은 분모(정답 확정 질의), 실행 오류 질의는 0. 질의별 값은 결과 열, 평균은 요약 시트 |

- 결과 파일 열: 19 → **21열**. `정답 적중 순위` 뒤에 `NDCG@5`, `응답시간(ms)` 뒤에 `첫 토큰(ms)`이 붙습니다.
- 저장 방식: `timing_json.first_token_ms`(마이그레이션 없음). 이전에 실행한 작업은 빈칸입니다.
- 기존 코드 변경
  - `app/graphs/nodes/generate_answer.py`: 첫 토큰 시각을 `timing`에 기록(키 `generate_first_token_at`)
  - `app/services/rag_service.py`: 요청 시작 기준 ms로 바꿔 `QueryResponse.first_token_ms`에 넣고, 시각 키는 `timing`에서 제거
  - 운영 챗봇 동작은 바뀌지 않습니다.

## 2-3. 평가 실행 결과 Excel에 응답시간·첫 토큰 추가 (사용자 요청, 11-18)

평가 화면의 "평가 실행 결과" Excel(`GET /api/eval/runs/{id}/results.xlsx`)에도 시간 값을 넣었습니다.
- 지표 요약 시트에 "응답 시간" 표를 추가했습니다(전체 RAG 평가만). 행은 답변 생성 응답시간과 첫 토큰 반환 시간이고, 열은 평균·p50·p90·p95·최대·건수입니다. 정상 항목만으로 계산합니다.
- 항목별 결과 시트에 `응답시간(s)`·`첫 토큰(s)` 열을 추가했습니다(7 → 9열). 검색·재정렬 평가는 '해당 없음'으로 표시합니다.
- 표시 단위는 **초(s), 소수 둘째 자리**입니다(사용자 요청). DB에는 ms로 저장합니다. 일괄 질의 결과 파일은 시험 항목 4 정의("평균 응답시간(ms)")에 맞춰 ms를 유지합니다.
- 평가 어댑터(`rag_pipeline_adapter.py`)도 그래프 시작 시각 기준으로 `first_token_ms`를 계산해 `timing_json`에 저장합니다.
- 응답시간은 그래프 실행 시간(검색 → 재랭킹 → 답변 생성)이고, 지표 계산 시간은 포함하지 않습니다.
- 변경 파일: `app/evaluation/adapters/rag_pipeline_adapter.py`, `app/evaluation/excel_exporter.py`, `tests/test_eval_run_excel_export.py`
- 이전에 실행한 평가에는 첫 토큰 값이 없습니다. 11-17 이전 실행의 응답시간은 지표 계산 시간이 섞인 값입니다. 새로 실행해야 정확한 값이 나옵니다.

## 3. 변경 파일

신규:
- `migrations/versions/0012_eval_batch_query.py`
  - `tb_eval_batch_jobs`·`tb_eval_batch_items`·`tb_eval_batch_gold` 생성
  - `tb_query_logs.input_mode` CHECK를 이름 있는 제약 `ck_tb_query_logs_input_mode`로 바꾸고 `'batch_eval'` 추가
  - downgrade는 batch_eval 로그가 있으면 중단(데이터 보존)
- `app/repositories/eval_batch_repository.py`
- `app/evaluation/batch/__init__.py`, `file_reader.py`, `text_clean.py`, `runner.py`, `exporter.py`(결과·검토 Excel), `gold_matcher.py`(정답 파일 읽기·자동 매칭·검토본 읽기), `recall.py`(Recall@k)
- `app/routes/eval_batch.py`
- `scripts/eval_batch_query.py`: 계정은 환경변수 `EVAL_ADMIN_ID`·`EVAL_ADMIN_PASSWORD`로만 받습니다. `--gold`(정답 업로드 → 검토 Excel 저장), `--gold-review`(검토본 업로드 → 확정)도 지원합니다. Windows 콘솔(cp949)에서 출력할 수 없는 문자는 쓰지 않았습니다.
- `tests/test_eval_batch_query.py`: 20개 테스트

수정:
- `app/services/rag_service.py`: `query(capture_retrieval=False)` 인자 추가
  - `batch_eval`이면 세션 조회·대화 이력 저장을 하지 않습니다.
  - capture가 켜지면 재랭킹 전 상위 N 요약(`_summarize_ranked_chunks`)과 청크 위치(시트·단계·순위)를 담습니다.
- `app/models/data_models.py`
  - `ChunkSummary`에 `sheet_name`·`step_no`·`rank` 추가(기본 None)
  - `QueryResponse`에 `retrieved_chunks`(기본 빈 목록)·`outcome_code` 추가
- `app/repositories/stats_repository.py`: 모든 통계 질의에 `input_mode <> 'batch_eval'` 조건을 넣고, 문서 참조 집계에서 batch_eval 인용 제외
- `app/core/config.py`: `eval_batch_*` 설정 9종(설계 8장 + `eval_batch_query_max_chars`)
- `main.py`: 라우터 등록. 기동 시 설정이 켜져 있으면 중단 작업을 정리하고 실행기를 시작
- `.env.example`: 설정 이름만 기재
- 루트 `.env`(dev, SVN 미반영): `EVAL_BATCH_QUERY_ENABLED=true` 한 줄 추가. 되돌리려면 그 줄을 지움

## 4. 기존 동작 영향

- 설정이 꺼져 있으면 API가 404이고 실행기도 시작하지 않습니다.
- `/api/query/` 응답에는 키 2개(`retrieved_chunks: []`, `outcome_code`)와 청크별 `sheet_name/step_no/rank: null`이 늘어납니다. 화면은 이 키를 쓰지 않습니다.
- `/api/query/`의 `input_mode`는 여전히 `text|voice|recommended|popular`만 받습니다. `batch_eval`은 서버 내부에서만 씁니다.
- 통계 수치: 기존 데이터에는 batch_eval 행이 없으므로 변화가 없습니다.

## 5. 검증

| 항목 | 결과 |
|---|---|
| `tests/test_eval_batch_query.py` 로컬 실행 | **18 통과**, 2 건너뜀(langgraph 필요) |
| 같은 파일 컨테이너 복사본(langgraph 포함) | **20 통과** |
| 다른 테스트가 설정 모듈을 가짜로 바꿔 둔 실행 순서 | 통과(테스트가 필요한 설정값을 직접 주입) |
| dev 백엔드 | 이미지 재빌드 후 기동 로그 `revision=0012_eval_batch_query`, 컨테이너 코드가 로컬과 같음(파일 해시 비교), `/api/eval/batch-jobs` 인증 없이 호출 시 401(기능 켜짐) |
| 마이그레이션 | 테스트 DB에서 conftest가 base → head(0012) 업그레이드 후, 다음 세션 시작 때 0012 → base 다운그레이드까지 성공 |
| 전체 회귀 | 6장 참고 |

검증한 내용:
- 파일 읽기: CSV BOM·CP949·xlsx, 영문 열 이름, 숫자 ID, 중복·빈 값·길이·행 수 오류의 행 번호 보고
- 본문 정리
- 단계별 시간 묶음, 백분위·요약 통계
- CSV BOM, 19열, 수식 주입 방지
- xlsx 시트 구성
- 실행기: 워밍업 결과 제외, 예외·시간 초과 후에도 계속 진행, 취소 시 완료분 보존, 워밍업 실패 시 작업 실패, running 1개 제한, 재기동 정리
- API: 꺼짐 404, 파일 오류 400, 없는 컬렉션 404, 실행 중 다운로드·삭제 409, 취소 후 다운로드
- 서비스: batch_eval이면 이력 미저장·세션 없음·상위 10 기록, 기본 호출은 기존과 같음
- 통계에서 batch_eval 제외
- 정답 대조: 문서명·텍스트 정규화, 단계 번호 해석, 3-gram 포함률, 위치로 좁힌 뒤 되돌리기, 다른 문서 청크 배제, 매칭 없음 참고 후보
- 정답 파일 오류 행, Recall@10(제외·오류·정답 없음·버전 불일치·재랭킹 후 기준), 확정 청크ID 구분자
- API 흐름: 정답 업로드 → 검토 Excel → 없는 청크ID 거부 → 확정 → 요약·재계산·CSV 열 반영

테스트 중 확인한 점: 0012 downgrade 보호 장치 때문에, 테스트가 batch_eval 로그를 남기면 다음 테스트 세션 시작(conftest의 base 다운그레이드)이 실패합니다. 통계 테스트는 끝날 때 직접 지우도록 했습니다.

## 6. 전체 회귀

| 실행 | 결과 |
|---|---|
| 로컬 전체 `pytest -m "not e2e and not voice" --continue-on-collection-errors` | 566 통과 / 16 실패 / 28 건너뜀 / 오류 13 |
| 같은 명령, 첫 토큰·NDCG@5 추가 후 재실행 | **568 통과 / 15 실패 / 29 건너뜀 / 오류 13**. 일괄 질의 테스트 실패 0 |
| 컨테이너 복사본(`/tmp/bq`, 실행 중인 dev 코드와 분리): `test_eval_batch_query`·`test_eval_e2e`·`test_answer_images` | **50 통과**(langgraph 필요 테스트 포함) |

실패·오류 판정
- **새 테스트:** 전체 실행에서 1건(`test_batch_eval_input_mode_is_allowed_and_excluded_from_stats`)이 실패했습니다. `test_stats_api.py`가 수집 단계에서 `app.repositories.stats_repository`를 가짜 모듈로 바꿔 두기 때문입니다. 원본 파일을 직접 로드하도록 고친 뒤, 그 가짜 모듈과 함께 실행해 통과를 확인했습니다.
- **`test_eval_routes` 실패 2건·오류 4건:** 단독 실행에서는 20건 모두 통과합니다. 설정 가짜 모듈에 따른 실행 순서 의존입니다.
- **나머지:** 이번 변경과 무관한 기존 목록입니다(11-10 기준선과 같음).
  - 마이그레이션 테스트의 head 기대값이 0010으로 남아 있음(3건)
  - 인증 응답 키 1건, 파서 fixture 1건
  - 가짜 설정 모듈 오염(deletion·kiwi·rrf·spreadsheet)
  - 수집 오류 9건(`ingest.py` import 시점 설정 읽기)
- 같은 날 앞선 전체 실행에서 오류 103건이 나온 적이 있습니다. 실행 도중 dev 백엔드 이미지를 빌드·재기동한 시간과 겹쳤고, 해당 파일을 단독으로 다시 돌리면 통과합니다. 그래서 이후 실행은 빌드가 끝난 뒤에 했습니다.

## 7. 남은 이슈

1. **실제 서버 리허설 미실시**
   - dev 백엔드 컨테이너는 이미지 빌드 방식이라 새 코드를 반영하려면 다시 빌드해야 합니다. 그 뒤 `.env`에 `EVAL_BATCH_QUERY_ENABLED=true`를 넣어야 합니다.
   - dev DB는 컨테이너가 재기동할 때 0012로 자동 마이그레이션됩니다.
   - 리허설 기준(설계 11장): 120건, 오류 0, 응답시간 평균이 같은 기간 질의 로그 평균의 ±5% 이내, 엑셀에서 한글이 깨지지 않을 것.
2. **정답 매칭 실데이터 미검증**: 시험기관 정답 파일(11/23)이 오면 자동 매칭률을 확인해야 합니다. 근거 문장이 우리 청크 경계를 넘거나 표기가 많이 다르면 "매칭 없음"이 늘 수 있습니다. 이때는 임계값을 조정(`EVAL_BATCH_GOLD_MATCH_THRESHOLD`, 재업로드만 하면 됨)하거나 검토 Excel에서 수동으로 지정합니다.
3. `eval_batch_retry_count`는 설정만 있고 0 외의 값은 아직 동작하지 않습니다(F-07: 재시도 없음).
4. 관리자 계정으로 실행하므로, 문서 권한 필터는 관리자 기준(전체 문서)입니다. 시험 컬렉션 문서가 모두 대상이라 문제는 없지만, 평가 전용 계정(DQ-B2)을 쓰려면 관리자 권한이 필요합니다.
5. 관리자 질의 로그 화면(주의 요망 질의 외의 로그 목록)에는 batch_eval 질의도 보입니다. 숨길지 결정이 필요합니다.
6. 3종 LLM 심사 테이블(`tb_eval_batch_judge`)은 심사 설계 확정 뒤 별도 revision(0013)으로 추가할 예정입니다. 심사 설계서에는 0012에 넣는다고 되어 있어 변경이 있습니다.
7. 화면 "일괄 질의" 탭은 심사 UI와 함께 구현합니다.
8. 기존 테스트 문제(이번 변경과 무관): `test_refactor_characterization::test_service_arguments_and_saved_api_key` 2건. 11-12 `input_mode` 추가 이후 기대값이 갱신되지 않았습니다.

## 8. 되돌리는 방법

1. `.env`의 `EVAL_BATCH_QUERY_ENABLED=false`(기본): 즉시 기능 정지. 코드가 있어도 기존 동작과 같습니다.
2. 완전 제거
   - batch_eval 로그를 정리(백업 후 `DELETE FROM tb_query_logs WHERE input_mode='batch_eval'`)한 뒤 `alembic downgrade 0011_user_pwd_changed_at`을 실행합니다.
   - 신규 파일을 삭제합니다.
   - `rag_service.py`·`data_models.py`·`stats_repository.py`·`config.py`·`main.py`의 2026.11.18 변경분을 되돌립니다.

## 9. 요구사항 정의서·기능 목록에 반영할 것

- R8-7: API 일괄 질의(파일 업로드)·결과 CSV/xlsx 다운로드 추가. API ID 부여(가칭 API-EVB-01 등록, 02 조회, 03 목록, 04 취소, 05 삭제, 06 CSV, 07 xlsx).
- 테이블 정의서: `tb_eval_batch_jobs`·`tb_eval_batch_items`·`tb_eval_batch_gold` 추가, `tb_query_logs.input_mode`에 `batch_eval` 추가.
- N-4: 응답시간 측정 정의(순차, 비스트리밍 완료, 워밍업 제외, 정상 건 평균).
