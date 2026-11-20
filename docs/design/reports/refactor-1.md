# 백엔드 리팩토링 1차 — 중복 제거·모듈 분리 (2026-11-09, 브랜치 refactor-1)

> 범위: `adrag_backend/app`만. **프런트엔드는 수정하지 않았다**(사용자 지시).
> 원칙: 기존 API·DB·설정·검색 동작 유지. 위험도 낮은 항목만 수정하고, 동작이 바뀌거나 판단이 필요한 항목은 6절에 승인 요청으로 남겼다.
> 관련 규칙: CLAUDE.md 절대 규칙 8(권한 판단 한 곳), 요구사항 정의서의 권한·버전 관리 항목(UI-12 문서 관리, D-22 이전 버전 복원)

## 1. 분석 요약

| 항목 | 방법 | 결과 |
|---|---|---|
| 미사용 import | AST 분석(문자열 주석 포함) | `app/` 0건(같은 날 앞 작업에서 정리됨, 2절) |
| 참조 없는 최상위 함수·메서드 | 저장소 전체(app·tests·scripts·main·migrations·json) 이름 검색 | 라우트 핸들러(데코레이터 등록)·로그 핸들러(`logger.json`이 문자열로 참조)를 빼면 `PermissionsRepository.get_user_collection_permissions`, `LCDocument.to_dict`, `services/maintenance.py` 정도. 앞 둘은 저장소 공개 메서드라 효과가 작아 유지, maintenance는 6절 |
| 파일 간 같은 코드 블록(7줄 이상) | 공백·주석 제거 후 비교 | 실제 통합 가치가 있는 것: 인증 Depends 3종, 질의 API 2종, 대화 이력 저장 2곳(3절). LLM 클라이언트 2종은 payload 규칙이 달라 통합하지 않음(6절) |
| 이름은 같고 내용이 다른 함수 | `_dedup_preserve_order`, `_record_repo`, `_resolve_collection_id`, `_row_to_dict` 등 | 반환 형식·인자가 서로 달라 통합 대상 아님 |

## 2. 같은 날 앞 작업(커밋 전, 이번 보고서에 함께 포함)

- 문서 열람 범위 계산을 `app/utils/security.document_scope`·`in_document_scope` 하나로 통합
  (`routes/ingest.py`·`routes/spreadsheet_resources.py`·`services/document_version_restore.py`). 테스트 `tests/test_document_scope.py`.
- `routes/ingest.py` `list_documents`의 행 → 응답 변환을 `_to_document_item`으로 분리, 모델명 수정 API의 조회·판정을 `_load_visible_document`로 통일.
- 미사용 import·함수 제거(`retrieval_metrics.aggregate_mean`, `docling_loader`·`collections`·`document_version_restore`의 import).

## 3. 이번 변경

| 파일 | 내용 | 동작 영향 |
|---|---|---|
| `app/utils/security.py` | `get_current_admin`·`get_current_principal`·`get_current_user`가 각자 하던 토큰 유무·복호화 확인을 `_decode_bearer_payload`로 | 없음(401 문구·`WWW-Authenticate` 헤더 동일, 테스트로 고정) |
| `app/routes/query.py` | `rag_query`·`rag_query_stream`이 복사해 쓰던 대화 주제 권한 확인(403)·저장 API 키 조회·서비스 인자를 `_authorize_query_collection`·`_resolve_openai_api_key`·`_service_kwargs`로 | 없음(확인 순서: 권한 → 키 조회 → 서비스, 복호화 실패 시 None) |
| `app/services/rag_service.py` | `query()`와 `_save_stream_history`의 이력 1턴 저장 본문을 `_store_history_turn`으로 | 없음. **저장 조건 차이는 그대로 유지**: `query()`는 대화 주제 이름만 있으면 저장(collection_id를 못 찾아도), 스트리밍은 collection_id가 있을 때만 |
| `app/models/ingest_models.py` (신규) | `routes/ingest.py`의 요청·응답 스키마 15개를 기존 관례(`stats_models.py`·`llm_models.py`)대로 분리 | 없음. 라우트 모듈이 같은 이름으로 import해 `app.routes.ingest.DocumentItem` 등 기존 참조 유지 |
| `app/routes/ingest.py` | 위 스키마 import로 교체, 미사용 pydantic import 제거 | 1104 → 958줄 |
| `tests/test_refactor_characterization.py` (신규) | 리팩토링 **전** 코드에서 먼저 통과시킨 동작 고정 테스트 15개(인증 401·반환값, 질의 API 403·API 키·서비스 인자·500, 이력 저장 형식·20개 유지·다른 사용자 이력 무시·저장 조건 차이·실패 무시) | — |

폴더 구조 변경: `app/models/ingest_models.py` 추가 1건(기존 `app/models/` 아래). 이동·삭제한 폴더 없음.

### 작업 중 발견: 다른 사람의 동시 수정

`app/services/rag_service.py`가 이번 작업 도중 외부에서 바뀌었다(`2026.11.05(woojin.jung)` — 대화 이력 저장을 질의 로그 기록보다 먼저).
제 변경은 그 위에 적용했고 순서 변경은 그대로 남아 있다. 프런트 `ChatView.vue`도 작업 중 바뀐 흔적이 있으나 손대지 않았다.

## 4. 검증

| 검증 | 결과 |
|---|---|
| 전체 테스트(로컬, `-m "not e2e and not voice" --continue-on-collection-errors`) 리팩토링 전 | 522 passed / 11 failed / 17 skipped / 수집 오류 3 |
| 같은 명령 리팩토링 후 | 525 passed / 14 failed / 26 skipped / 수집 오류 3 — 늘어난 실패 3건은 다른 작업의 0008 마이그레이션 때문(5절) |
| langgraph 필요 테스트(dev 컨테이너: `test_answer_images`·`test_eval_dataset`·`test_eval_e2e`·`test_rag_stream`·동작 고정·`test_unified_auth_routes`) 전/후 | 전 59 passed / 2 failed, 후 59 passed / 2 failed (실패 2건은 기존: `test_rag_stream` 가짜 설정에 `sqlite_db_path` 없음, 로그인 응답 `ui_type`) |
| API 계약 | HEAD 커밋 코드와 현재 코드의 OpenAPI 스키마(경로 91개, 124,845바이트)가 바이트 단위로 같음 |
| 문법·import | `py_compile` 통과, 미사용 import 재분석 0건, 컨테이너에서 `main` import·라우트 등록 정상 |

기존 실패 11건(전후 동일 목록): `test_parse_regression`, `test_deletion_consistency`, `test_eval_e2e`, `test_eval_kiwi_direct_search` 2, `test_eval_routes`, `test_multi_document_upload`, `test_rule_based_metric_regressions` 2, `test_spreadsheet_payload`, `test_unified_auth_routes` — 모두 이전 보고서(fix-0007 4절)의 순서 의존 stub 오염·낡은 기대값 문제.
수집 오류 3건(`test_stats_api`, `test_voice_*`)도 기존과 같다.

미검증: 실제 vLLM·Qdrant·임베딩 서버를 거치는 질의(e2e), 음성(voice) 테스트 — 이번 변경은 그 호출 경로를 바꾸지 않았다.

## 5. 리팩토링 후 전체 테스트

- 결과: 525 passed / 14 failed / 26 skipped / 수집 오류 3 (12분 03초).
- 기준선과 다른 실패 3건은 모두 `test_database_migrations`(`HEAD` 기대값 `0007` ≠ 실제 `0008_query_feedback_detail`).
  작업 도중 다른 작업이 추가한 `migrations/versions/0008_query_feedback_detail.py` 때문이고 이번 변경과는 관계없다.
  그 작업에서 테스트의 `HEAD` 상수를 0008로 올려야 한다. 나머지 실패 11건·수집 오류 3건은 기준선과 같다.

## 5-1. 주석 정리 (사용자 요청 2026-11-09)

범위: `app/` 전체. 날짜 이력 주석(`YYYY.MM.DD(sooyeon.choi) 추가/수정 - …`)의 형식은 그대로 유지했다.

| 정리 | 건수 | 내용 |
|---|---|---|
| 내부 작업 태그 제거 | 147줄 | `[P2-2]`·`(P2-13)`·`P2-6~P2-10`, `(B7)`·`B4/B5`, 복원 설계 검토 번호 `B-01`·`B-15`, `(설계서 C1)`·`C2 —`. 남긴 것: 문서 ID(`UI-`·`F-`·`SC-`·`R…`·`D-`·`N-`·`VR-`·`SCR-`·`SFR-`·`Q-`·`ECR-`)와 `Phase N` |
| 주석으로 막아 둔 코드 삭제 | 82줄(12개 파일) + 짝 잃은 설명 3줄 | `# logger.info(...)`(여러 줄 포함), 그 로그 전용 `# source = …`·`# must_count = …`·`# context_preview = …` |
| 오늘 추가한 주석 다듬기 | 약 30줄 | "(리팩토링, … 기존과 같음)" 같은 작업 경위 설명을 빼고 무엇을 하는지만 남김 |

코드 영향: 로그 문구 2곳(`build_metadata_filter`의 `[P2-4] 파이프라인 내부 컬렉션 권한 차단`, `[P2-2] 컬렉션 권한 차단`)에서 태그 접두어만 빠졌다.
검증: 주석만 바꾼 파일 47개를 HEAD와 AST 비교(docstring 제외) → 46개 동일, 1개는 위 로그 문구 2곳 외 동일. `compileall` 통과.
남은 일: 2026-07~10 이력 주석의 문장 다듬기(약 720개)는 하지 않았다(태그 제거만).

## 6. 승인이 필요한 항목 (수정하지 않음)

| # | 내용 | 위험·이유 | 제안 |
|---|---|---|---|
| A1 | **검색 필터와 화면 API의 권한 규칙이 다르다.** `graphs/nodes/build_metadata_filter.py`는 `accessible_collections`가 비면 대화 주제 필터를 걸지 않는다("전체 허용"). 문서 목록·원본 열기·사진 API(`document_scope`)는 빈 목록 = 열람 불가. 대화 주제를 지정하지 않은 질의(`collection_name` 없음)에서는 권한 행의 주제 목록이 빈 사용자가 보안 등급 범위 안의 모든 주제를 검색할 수 있다 | 규칙 8(권한 판단 한 곳) 위반 소지. 바꾸면 검색 결과가 달라짐 | 의도(관리 편의상 "빈 목록 = 전체")인지 확인 후 하나로 통일 |
| A2 | `services/maintenance.py`(GC_FILES·PURGE_POINTS)가 어디에서도 호출되지 않는다. 이를 쓰는 `test_ingest_queue_versions.py`는 conftest `collect_ignore`(Phase 3 재구현 전). 만료 staging·참조 없는 asset 정리가 운영에서 돌지 않는 상태 | 삭제하면 Phase 3 계획 코드 손실, 연결하면 새 동작 | Phase 3 작업 큐 확정 때 연결할지, 그때까지 유지할지 결정 |
| A3 | `async` 라우트 안의 동기 DB 호출: `routes/query.py` `_get_accessible_collections`·저장 키 조회, `routes/ingest.py` 업로드의 권한 조회, `routes/auth.py` 등 | 요청이 몰리면 이벤트 루프 지연. `asyncio.to_thread`로 감싸면 동작은 같지만 일부 테스트의 monkeypatch 방식에 영향 가능 | 측정(동시 질의 지연) 후 적용 여부 결정 |
| A4 | `clients/llm_client.py`(vLLM)와 `clients/openai_client.py`가 거의 같은 구조 | temperature 0 처리(`or` vs `is not None`), `**kwargs`·`stop`·`chat_template_kwargs` 전달이 서로 달라 합치면 LLM 호출 payload가 바뀔 수 있음 | 통합하지 않음 권장(현 상태 유지) |
| A5 | `openai_client.py`가 외부 `api.openai.com`을 호출할 수 있다(사용자가 OpenAI 모델을 고른 경우, 평가 judge) | CLAUDE.md 절대 규칙 7(외부 AI API 금지)과 충돌. 기존 기능 | 운영에서 OpenAI 모델을 비활성화하는지 확인. 필요하면 설정으로 차단 |
| A6 | `vector_repository.py`(16곳) 등의 넓은 `except Exception` | 좁히면 지금 "조용히 빈 결과"로 처리되던 오류가 예외로 바뀜 | 파일별로 검색 실패·빈 결과 구분 테스트를 먼저 만든 뒤 단계적으로 |
| A7 | 설정 이름 `sqlite_db_path`가 PostgreSQL 전환 후에도 저장소 생성자 인자로 쓰임 | 환경변수 호환·테스트 stub(`sqlite_db_path` 필수)에 걸려 있음 | 이름 정리는 별도 작업으로(Q-15.7) |

## 7. 마이그레이션·되돌리기

- 마이그레이션: 없음(DB·Qdrant·설정·환경변수 변경 없음).
- 되돌리기: 이번 변경 파일 5개(`security.py`, `query.py`, `rag_service.py`, `ingest.py`, 신규 `ingest_models.py`)와 테스트 1개를 이전 상태로. 로컬 git 커밋은 하지 않았다(작업 폴더에 앞 작업의 미커밋 변경이 섞여 있어 사용자 확인 후 커밋).

## 8. 요구사항 정의서·기능 목록에 반영할 것

- 없음(기능 변경 없음). A1 결정 결과는 권한 요구사항에 명시 필요.
