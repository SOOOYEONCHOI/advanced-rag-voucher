# 이전 버전 복원 구현 보고서 (2026-11-06)

- 관련: UI-12 / SC-06 / R1-5 / VR-01~06 / D-22(신설, D-18 변경)
- 기준: `docs/design/문서_이전버전_복원_백엔드_최종설계_v1.1.md`, `문서_이전버전_복원_화면영역별_API_명세_v1.1.md`, 목업 `mockups/admin_UI-12_이전버전복원_20261104_v0.2.html`
- 범위: 백엔드 전체 + 프런트엔드(시연용, 사용자 직접 구현 요청). 프런트엔드 담당자에게는 목업 v0.2 + API 명세 v1.1 전달 예정
- 모든 코드 변경에 `2026.11.06(sooyeon.choi) 수정` 주석

## 1. 변경 파일

### 백엔드 (`adrag_backend/`)

| 파일 | 내용 |
|---|---|
| `migrations/versions/0006_document_version_restore.py` (신규) | 임베딩 프로필·적용 이력 테이블, `tb_documents.activation_revision·pending_job_id`, 버전 봉인 컬럼, 작업 유형·멱등 키, 작업 단계 제약(`snapshot`·`activate`), 이벤트 `restore`, baseline 이관 |
| `app/core/config.py`, `../.env.example` | `DOCUMENT_VERSION_VECTOR_RETENTION_ENABLED`, `DOCUMENT_VERSION_RESTORE_ENABLED`(기본 false), 복원 ON + 보존 OFF 기동 오류 |
| `app/services/embedding_profile.py` (신규) | 현재 임베딩 프로필 해시·행 보장 |
| `app/services/document_version_restore.py` (신규) | 가능 여부 판정, 접수(멱등·점유), 실행(validate → snapshot → activate), 실패 처리 |
| `app/repositories/ingest_record_repository.py` | 점유 획득·해제·정합성 복구, 적용 이력, 버전 봉인, 복원 전환, 적용 이력 조회, 이력 조회 컬럼 확장, 정리 경로 보호 |
| `app/repositories/ingest_job_repository.py` | 작업 유형·문서·멱등 키·fingerprint 저장, 멱등 키 조회 |
| `app/services/ingest_jobs.py` | restore 분기(맨 앞), restore 재시도 거부, 최신본 변경 실패 시 점유 해제, 재시도 시 점유 재획득, 기동 시 점유 정합성 복구 |
| `app/services/ingest_pipeline.py` | 봉인·적용 이력(upload·replace) 기록, 보존 ON이면 이전 버전 포인트 정리 안 함, OFF면 방금 교체된 버전만 정리 |
| `app/services/version_visibility.py`, `app/graphs/retrieval_engine.py` | 제외 대상에 보존·복구 포인트 포함(삭제 시각만 믿지 않음), 요청 단위 snapshot |
| `main.py` | 보존 ON이면 기동 시 이전 버전 정리 생략 |
| `app/routes/ingest.py` | 목록 `activation_revision`·`pending_operation`, 이력 응답 확장, `POST …/versions/{n}/restore`, `GET …/activations`, 작업 응답 확장, restore 재시도 409, 최신본 변경·삭제의 점유 검사 |
| `app/routes/spreadsheet_resources.py` | 문서별 사진 목록 기본값을 현재 적용 버전으로(`version_no` 인자) |
| `app/models/data_models.py` | `DocumentEventType.RESTORE` |
| `scripts/check_version_restore_availability.py` (신규) | 가용성 점검 도구(dry-run 기본, `--apply`, `--assume-current-profile`) |
| `tests/test_document_version_restore.py` (신규) | 복원 6건 |
| `tests/test_document_versions.py`, `tests/test_database_migrations.py` | 필터 규칙 변경(B-07) 반영, head·테이블 수 |

### 프런트엔드 (`adrag_frontend/`)

| 파일 | 내용 |
|---|---|
| `src/composables/useVersionRestore.js` (신규) | 선택·확인·접수(멱등 키)·진행 확인·결과·오류·새로고침 복원·적용 이력 |
| `src/views/AdminView.vue` | 목업 v0.2 버전 이력·복원 대화상자, 상태 줄, 복원 처리 중 표시·잠금 |
| `src/composables/useDocumentVersions.js`, `useAdminDocuments.js`, `src/api/adminApi.js` | 이력 응답 보관·재조회, 복원 연결, API 2개 |
| `src/router/index.js`, `src/components/AdminSidebar.vue` | 변경 없음(권한 변경으로 관리자 진입 허용을 되돌림) |
| `tests/versionRestore.test.mjs` (신규) | 7건 |

### 문서

- `docs/design/01_결정사항_변경로그.md` — D-22 추가
- 이 보고서

## 2. 동작 요약

1. 보존 ON에서 최신본 변경이 성공하면 이전 버전 포인트·청크·사진·원본을 남기고, 새 버전에 프로필·벡터 명세(포인트 수·ID 해시)·문서 snapshot을 기록(봉인)한다. 검색은 RDB `tb_documents.version_no` 기준으로 현재 버전만 본다.
2. 버전 이력 GET이 행마다 `can_restore`·`restore_block_code`·`restore_block_reason`을 준다(문서 단위 사유는 행에 복사, 현재 행은 `ALREADY_ACTIVE`).
3. 문서를 볼 수 있는 사용자가 POST하면 문서 잠금 아래 멱등 키·예상 버전·적용 순번·점유를 검사하고 queued 작업 + `pending_job_id`를 저장한다(202).
4. 작업: validate(실행자의 문서 접근 권한·상태 재검사) → snapshot(원본 파일, 청크 ID 해시, 사진 파일, Qdrant 포인트 존재·문서·버전 일치) → activate(한 트랜잭션: 버전 상태·문서 행·적용 순번·적용 이력·이벤트·작업 완료·점유 해제).
5. 실패하면 기존 버전 유지, 작업 failed + `error_code`, 점유 해제. 실패는 적용 이력에 남지 않는다.

## 3. 완료 기준 충족 근거

| 검증(설계 10절) | 결과 | 근거 |
|---|---|---|
| 정상 전환·재임베딩 0 | 충족 | `test_restore_end_to_end_switches_without_reembedding`: v2 → v1 후 문서 행(파일명·페이지·청크·모델명 유지)·버전 상태 일치, 포인트 ID 집합 전후 동일 |
| 반복 적용·이력 | 충족 | 같은 테스트: v1 → v2 재복원, 적용 순번 2 → 3 → 4, 이력 restore·replace·upload 순서, 커서 페이지 |
| 신규 업로드 번호 | 충족 | 복원 후 최신본 변경 접수 v3 |
| 점유·상태 경쟁 | 충족 | 진행 중 최신본 변경·삭제·다른 복원 409, 같은 키 재전송 같은 작업(202/끝나면 200), 키 재사용 409 |
| 장애 | 충족 | `test_failed_verification_keeps_current_version_and_releases_lock`: 포인트 누락 `VECTOR_MISSING`, 원본 없음 `SOURCE_MISSING`, 기존 v2 유지, 점유 해제 |
| 보안 | 충족 | 업로더가 아닌 일반 사용자도 볼 수 있으면 복원 가능, 볼 수 없으면 이력·POST 404, 접수 후 권한이 빠지면 실행 실패(`NOT_FOUND`, 기존 버전 유지) |
| 설정 | 충족 | 기능 OFF 403·`restore_supported=false`, 복원 ON + 보존 OFF `Settings` 오류 |
| 과거 데이터 | 충족 | `test_legacy_purged_version_is_blocked_with_specific_reason`: 보존 OFF로 교체된 버전 `VECTOR_MISSING`, 프로필 다르면 `MODEL_UNSUPPORTED` |
| 보존·검색 | 충족 | `test_retention_keeps_old_points_hidden_and_records_seal_and_activations`: v1 포인트 보존 + 검색 제외 |
| 재시작 | 일부 | restore 분기가 파일 경로 로직 앞에서 동작, 커밋된 작업은 적용 이력으로 확인 후 완료 처리(코드). 프로세스 중단 재현 테스트는 없음 |
| 부하(필터 크기·지연) | 미측정 | 11절 Q-2: 대표 보존량 측정은 운영 데이터 기준으로 남김 |

테스트 결과(2026-11-06, 로컬 PostgreSQL 테스트 DB)

- 신규 복원 테스트: `pytest tests/test_document_version_restore.py` → 6 passed
- 관련 기존 테스트(마이그레이션 왕복·최신본 변경·파이프라인·레코드·삭제): 57 passed(필터 규칙 변경으로 기존 1건 기대값 수정)
- 전체: 아래 4절
- 프런트엔드: `node --test tests/*.test.mjs` → 11건 중 10 passed. 실패 1건 `answerImages.test.mjs`는 `src/utils/answerImages.js`가 없어 나는 기존 실패(이번 변경과 무관). `vite build` 성공

## 4. 전체 테스트

`pytest -q -p no:logging -m "not e2e and not voice" --continue-on-collection-errors` (2026-11-06): **489 passed, 14 failed, 17 skipped, 7 errors**. 이후 이번 변경 관련 2건을 고치고 관련 파일 묶음 재실행 → 70 passed / 4 skipped.

| 실패·오류 | 판단 | 근거 |
|---|---|---|
| `test_spreadsheet_resource_service::test_list_api…` | **이번 변경 원인 → 수정** | B-10 행 접근을 이름 기준으로 변경 후 통과 |
| `test_document_version_restore::test_settings_reject…` | **이번 변경 원인 → 수정** | 전체 실행에서 설정 모듈이 가짜로 바뀌는 순서 대응(검사 함수 직접 호출) |
| `test_deletion_consistency`, `test_eval_kiwi_direct_search` 2건, `test_spreadsheet_payload`, `test_eval_e2e`, `test_eval_routes`, `test_rule_based_metric_regressions` 2건 | 기존 실행 순서 의존 | 파일 단독 실행 시 모두 통과 |
| 수집 오류 `test_stats_api`, `test_voice_asr_client`, `test_voice_routes` | 기존 실행 순서 의존 | 여러 테스트가 `sys.modules["app.core.config"]`를 가짜로 바꿈. 단독 수집 정상 |
| `test_auth_audit` 3건, `test_excel_ingest_routing` 1건 오류 | 실행 옵션 탓 | `-p no:logging`으로 `caplog` 비활성(로그 출력 억제용으로 준 옵션) |
| `parsers/test_parse_regression::test_no_fixture_disappeared_silently` | 기존 | 파서 fixture 문제, 이번 변경 파일과 무관 |
| `test_query_log_repository` | 기존 | `l.feedback_reasons` 컬럼 없음(스키마와 코드 불일치) |
| `test_multi_document_upload::test_job_owner_permissions…` | 기존 | 테스트가 저장소에 없는 `requeue_failed`를 호출(이번 변경 전에도 없음) |
| `test_unified_auth_routes::test_admin_uses_unified_auth…` | 기존 | 응답에 `ui_type` 추가 필드 |
| `test_ingest_queue_versions` | 기존 | 없는 모듈 `app.ingest.doc_key` 참조 |

기존 실패(위 "기존")는 이번 범위에서 고치지 않았다.

## 5. 마이그레이션

- `0006_document_version_restore` (down_revision `0005_document_version_replace`). dev 컨테이너는 기동 시 `init_database.py`로 자동 적용.
- downgrade: 기능 OFF·진행 작업 없음 상태에서 실행. 적용 이력·restore 이벤트·restore 작업 행을 지우므로 필요하면 먼저 백업. Qdrant 보존 벡터는 지우지 않는다.

## 6. 되돌리는 방법

1. `.env`에서 `DOCUMENT_VERSION_RESTORE_ENABLED=false`(신규 접수 중단). 보존 데이터를 유지하려면 `DOCUMENT_VERSION_VECTOR_RETENTION_ENABLED`는 그대로 둔다.
2. 코드 되돌림이 필요하면 `alembic downgrade 0005_document_version_replace` 후 이번 변경 파일을 되돌린다. 0005 코드는 기동 시 비활성 버전 포인트를 정리하므로, 보존 데이터를 남기려면 되돌리기 전에 백업한다.

## 7. 시연 절차 (dev)

1. `.env`에 `DOCUMENT_VERSION_VECTOR_RETENTION_ENABLED=true`, `DOCUMENT_VERSION_RESTORE_ENABLED=true` 추가 후 백엔드 재기동(0006 자동 적용).
2. 일반 사용자로 로그인 → 사이드바 [문서 관리] → 새 문서 업로드(v1) → [최신본 변경]으로 v2, v3 등록.
3. [버전 이력]에서 v1 선택 → [선택 버전 복원] → [이 버전으로 복원] → 진행·완료 확인, [적용 이력 보기].
4. 기능 켜기 전에 교체된 기존 문서의 이전 버전은 `VECTOR_MISSING`으로 표시된다(정상).

## 8. 설계와 다르게 한 점

- 행 불가 사유 순서: 설계 8절은 프로필 → snapshot → 검증 → 벡터 순이나, `vector_storage_state='missing'`(삭제 확정)은 프로필 불명보다 먼저 판정한다. 기존 버전 대부분이 벡터 삭제 상태라 사용자에게 더 정확한 사유를 보여 주기 위함.
- 보존 OFF의 즉시 정리: 기존 `keep_version_no`(현재 버전 외 전부 삭제) → `version_no=방금 교체된 버전`만 삭제. 보존 기간에 남긴 다른 버전을 설정 OFF만으로 지우지 않기 위함(설계 10절). 기동 시 주기 정리도 봉인된(available) 정상 버전은 제외.
- 검색 제외 대상: `vectors_purged_at IS NULL` → `vectors_purged_at IS NULL OR vector_storage_state <> 'missing'`(설계 7.2의 "버전 2개 이상이면 항상"보다 좁힘 — 포인트 삭제가 확정된 버전은 필터에서 빠져 필터 크기를 줄임).
- 요청 단위 snapshot은 다중 채널(legacy) 검색 경로에 적용했다. 운영 기본(`qdrant_hybrid`)은 Qdrant 질의 1회라 원래 한 시점만 본다.
- 문서 삭제 시 이전 버전의 확인용 md 폴더 정리(B-09)는 이번에 구현하지 않았다(남은 이슈).

## 8-1. 검색 필터 C안 (2026-11-06 추가, 설계 v1.1 7.3)

| 파일 | 내용 |
|---|---|
| `app/services/version_visibility.py` | 비활성 버전을 행 단위로 한 번 읽어 nested(문서별 중첩) 또는 doc_version(`match any` 1개) 조건 생성. 설정 `DOCUMENT_VERSION_FILTER_MODE`, snapshot은 두 방식 공통 |
| `app/services/ingest_service.py` | 신규 포인트 payload `doc_version = "{document_id}:{version_no}"` |
| `app/repositories/vector_repository.py` | `doc_version` keyword 인덱스 |
| `app/core/config.py`, `../.env.example` | `DOCUMENT_VERSION_FILTER_MODE`(기본 `nested`) |
| `scripts/backfill_doc_version_payload.py` (신규) | 기존 포인트 키 채우기(dry-run 기본, 옛 포인트 version_no 없음 = v1, 재실행 안전) |
| `tests/test_version_filter_doc_version.py` (신규) | in-memory Qdrant로 두 방식 결과 동일, 조건 수(nested 3 ↔ doc_version 1), 복원 후 즉시 반영, 백필 0건, snapshot 1회 조회 |

검증: 관련 묶음 73 passed(마이그레이션·최신본 변경·복원·검색 채널·파이프라인 포함).
`test_spreadsheet_pipeline_integration.py` 6건 실패는 변경 전 코드(HEAD worktree)에서도 같은 6건이 실패하는 기존 문제다(이번 변경과 무관).

운영 적용 순서: 0006 적용 → `python scripts/backfill_doc_version_payload.py`(건수 확인) → `--apply` → 미기록 0건 확인 → `DOCUMENT_VERSION_FILTER_MODE=doc_version` → 재기동. 되돌리기는 설정을 `nested`로 바꾸면 된다(payload 키는 남아도 무해).

## 8-2. 권한 변경 (2026-11-06, 사용자 결정)

- 관리자 전용 → **문서를 볼 수 있는 모든 사용자**. `ADMIN_REQUIRED` 제거, 실행 시점에 실행자 권한 재확인(`_actor_can_view`, 라우트와 같은 규칙).
- 관리자 `/admin` 진입 허용(router·sidebar)은 원래대로 되돌림.
- 변경: `app/services/document_version_restore.py`, `app/routes/ingest.py`(주석), `tests/test_document_version_restore.py`, 프런트 `useVersionRestore.js`·`tests/versionRestore.test.mjs`.
- 검증: 백엔드 복원·최신본 변경·필터 15 passed, 프런트 10/11(기존 `answerImages` 실패 1건), 빌드 성공.
- 참고: 업로더가 아닌 사용자의 복원도 문서를 점유하므로, 그동안 업로더의 [최신본 변경]·삭제는 409가 된다(완료 후 가능).

## 9. 남은 이슈

1. B-09: 문서 삭제 시 버전별 `md_dir` 정리.
2. 장기 보존 시 검색 필터 크기·지연 측정(VR-T15, Q-2) — nested와 doc_version 비교 수치 필요.
3. 운영 백업 연계(9.1 격리 복구 절차)는 절차서로 별도 작성 필요.
4. 프로세스 중단 중 복원 작업 재개 시나리오 자동 테스트.
5. 프런트엔드 담당자 인수: 목업 v0.2 + API 명세 v1.1 전달, 실제 API로 공동 확인.

## 10. 요구사항 정의서·기능 목록에 반영할 것

- R1-5(이전 개정본 복원): 2차 → 1차(문서를 볼 수 있는 사용자, 설정 기본 OFF).
- UI-12 버전 이력: 이전 버전 선택·[선택 버전 복원]·확인창·진행/결과·[적용 이력 보기].
- API 추가: `POST /api/ingest/documents/{id}/versions/{n}/restore`, `GET /api/ingest/documents/{id}/activations`. 기존 응답 확장: 문서 목록·버전 이력·작업 조회.
