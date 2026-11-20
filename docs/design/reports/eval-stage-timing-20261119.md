# 평가 반환 시간·단계별 실패·보조 지표 수정 — 2026-11-19

관련: AI+ 인증 시험 합의서 시험 1·2·4, F-04/F-05(시간 측정), F-08/F-09(검색·재랭킹), F-12(결과 내보내기).

## 적용 범위

사용자가 우선 진행하도록 지정한 반환 시간 측정·집계, 검색·재랭킹·답변 실패 분리, 보조 지표 표시만 수정했다. 3종 LLM 심사와 120건 데이터 통합 기능은 이번 범위에 포함하지 않는다.

## 변경 내용

- 배치 질의는 서비스 요청 직전부터 반환·예외·타임아웃까지 단조 시계로 측정한다. DB 저장 시간과 워밍업은 제외한다. 기존 서버 내부 처리 시간은 `timing_json.server_processing_ms`에 별도로 보관한다.
- 배치 시간 평균과 백분위는 오류를 포함한 전체 질의로 계산한다. 미실행·시간 누락·유효하지 않은 시간이 있으면 공식 평균은 비워 두고 측정 미완료·누락 건수를 표시한다. 정상 건만의 통계는 `response_ms_success`로 분리한다.
- 관리자 전체 RAG 평가는 질의를 순차 실행한다. 실행 예외에도 경과 시간을 남긴다. 전체 결과에 시간이 없으면 부분 평균과 표준편차를 공식 값으로 저장하지 않는다.
- 검색·재랭킹 노드는 각각 `retrieval_status`, `rerank_status`를 반환한다. 재검색 시 이전 재랭킹 상태를 초기화한다. 재랭킹 장애와 비활성화는 운영의 대체 결과를 그대로 반환하되 평가에서 정상 재랭킹으로 취급하지 않는다.
- 배치와 관리자 평가 모두 답변 오류와 독립적으로 성공한 검색 결과를 평가한다. 단계 정보는 기존 JSON 필드에 보관하므로 스키마 변경은 없다.
- 배치 CSV·Excel의 기존 21열 뒤에 검색·재랭킹·답변 생성 상태 3열을 추가했다. 기존 파일의 상태 미기록은 그대로 표시한다.
- 보조 지표는 내부 참고임을 명시한다. F2·인용·청크 커버율 등의 항목별 80% 기준 색상과 문제 항목 분류를 제거한다. 실제 실행 오류·지표 오류·인용 진단은 유지한다.
- 신규 실행 지표 버전은 `rule-v1.3`으로 기록한다. 기존 실행을 자동 재계산하지 않는다.

## 변경 파일

- 그래프: `app/graphs/state.py`, `nodes/validate_input.py`, `nodes/retrieve.py`, `nodes/rerank.py`
- 서비스·모델: `app/models/data_models.py`, `app/services/rag_service.py`
- 평가: `app/evaluation/adapters/rag_pipeline_adapter.py`, `runner/e2e_evaluator.py`, `runner/eval_runner.py`, `metric_catalog.py`, `excel_exporter.py`
- 배치: `app/evaluation/batch/runner.py`, `recall.py`, `exporter.py`, `scripts/eval_batch_query.py`
- API: `app/routes/evaluation.py`, `app/routes/eval_batch.py`
- 화면: `adrag_frontend/src/composables/useEvalRuns.js`, `adrag_frontend/src/views/EvalRunView.vue`
- 테스트: `test_eval_batch_query.py`, `test_eval_runner.py`, `test_eval_e2e.py`, `test_eval_run_excel_export.py`, `test_eval_routes.py`, `test_reranker_prompt_format.py`

위 백엔드 경로는 `adrag_backend/` 기준이다. 기존 작업 폴더의 사전 변경은 보존했다.

## 검증

로컬 개발 컨테이너의 전용 PostgreSQL 테스트 DB에서 평가·배치·Excel·라우트·재랭킹 회귀 테스트를 실행한다. 확인 항목은 오류 시간 포함 평균, 미측정 평균 차단, 타임아웃 시간 저장, 답변 실패 후 검색 적중 유지, 재랭킹 장애·비활성화 분리, 전체 RAG 순차 실행, CSV 단계 상태, 지표 버전이다.

최종 회귀 테스트 7개 파일에서 **113 passed**. `passlib`의 기존 Python `crypt` 폐기 예정 경고 1개가 있었다. 프런트엔드 `npm run build`, JavaScript 구문 검사, CRLF를 고려한 변경 파일 공백 검사는 통과했다.

```text
python -m pytest -q -o log_cli=false tests/test_eval_batch_query.py tests/test_eval_runner.py tests/test_eval_e2e.py tests/test_eval_run_excel_export.py tests/test_rule_based_metric_regressions.py tests/test_reranker_prompt_format.py tests/test_eval_routes.py --basetemp=/tmp/eval-stage-timing-tests
```

## 적용·제약·되돌리기

- 마이그레이션 없음. 백엔드 재시작과 프런트엔드 빌드 반영 후 신규 평가를 실행한다.
- 과거 결과에는 단계 상태·실패 경과 시간이 없을 수 있으므로 새 기준의 증빙이 필요하면 재실행한다. 과거 성공 결과는 기존 정보를 이용해 호환 표시한다.
- 서비스가 응답 객체를 반환하지 못한 예외·작업 타임아웃에서는 중간 그래프 결과를 복구하지 않는다. 기록이 없는 검색을 성공으로 간주하지 않는다.
- 실패까지의 경과 시간을 포함한 평균은 최종 답변 성공률을 보장하지 않는다. 오류 건수와 함께 검토해야 한다. 외부 네트워크 왕복 시간은 측정하지 않는다.
- 워밍업 횟수·운영 fallback·검색 후보 수·관련성 하한은 변경하지 않았다.
- 되돌릴 때는 위 파일의 이번 수정만 되돌린다. 기존 사전 변경을 포함하는 파일 전체 복원은 피한다. DB 스키마와 기존 저장 결과는 변경하지 않았다.
