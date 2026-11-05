# 문서 관리 최신본 변경·버전 이력 — 2026-10-19

사용자 요청: 모델명 1단계(`model-name-step1.md`)에 이어, 문서 목록 "작업" 컬럼에 [최신본 변경]·[버전 이력]을 구현한다. 기존 삭제는 유지하고 API·DB·적재 처리까지 연결한다.
"1단계 후 멈춤" 제한은 사용자가 취소했다.

- 기준: `docs/design/문서 관리 모델명·버전 관리 개선 요청서.md` 4절·9.2(5단계), 문서 관리 목업(10/12, 업데이트판)
- 관련 ID: UI-12, SC-06(개정본 교체), SC-07(등록 실패), D-01(관리자 지정 개정·직렬화·중복 파일), D-04(존재 숨김), D-18(이전 버전 적용)
- 모델명 기능은 유지했다.

## 1. 요약

- **최신본 변경**
  - 문서 행의 [최신본 변경]을 누르면 대화상자에서 새 파일을 고르고 [업로드 및 최신본 변경]으로 접수한다. 접수는 `POST /api/ingest/documents/{id}/versions`로 처리한다.
  - 접수 결과로 `building` 버전 행과 작업이 함께 생긴다.
  - 기존 `document_id`와 모델명(`product_model`)을 그대로 쓴다. 보안 등급·대화 주제·업로더도 바뀌지 않는다.
- **전환 규칙**
  - 새 버전은 다음 순서로 처리된다.
    1. 파싱·청킹·임베딩
    2. Qdrant 저장
    3. **저장 건수 검증**(포인트 수 = 청크 수)
    4. `ready`로 표시
    5. **한 트랜잭션으로 전환**: 이전 `active` → `retired`, 새 버전 → `active`, 문서 행의 파일명·경로·페이지·청크 수·`version_no`·최근 변경일 갱신, 청크 행 기록
  - 전환 뒤에 이전 버전의 Qdrant 포인트를 지운다.
  - 처리 중이거나 실패한 동안에는 문서 행과 활성 버전이 바뀌지 않는다. 따라서 **기존 최신본으로 검색·답변**한다.
- **검색 격리**: 모든 검색 채널(dense·hybrid·sparse·kiwi BM25·BM25)에 같은 제외 조건을 붙인다. 이 조건은 "그 문서의 활성 버전이 아닌 포인트"를 뺀다.
  - 기준은 RDB다(`tb_documents.version_no` = 활성 버전).
  - 개정 이력이 없거나 정리가 끝난 문서에는 조건을 붙이지 않는다. 따라서 기존 검색은 그대로다.
  - 이전 버전 포인트를 지우다 실패해도 구 버전은 검색되지 않는다. 정리는 주기 작업이 다시 시도한다.
- **실패 처리**
  - 이 버전의 포인트와 리소스만 정리하고 버전을 `failed`로 둔다. 문서 행, 기존 최신본의 포인트·리소스·원본은 건드리지 않는다.
  - 목록에는 실패 안내 토스트가 뜨고, 버전 이력에 오류 메시지가 남는다.
  - 기존 작업 재시도 API로 같은 버전을 다시 처리할 수 있다(다시 `building`).
- **동시 교체 방지**
  - 같은 문서는 `pg_advisory_xact_lock`으로 직렬화한다.
  - 처리 중 버전은 문서마다 1개만 허용한다(부분 유일 인덱스). 두 번째 접수는 `409 JOB_IN_PROGRESS`다.
  - 현재 최신본과 같은 파일은 `409 DUPLICATE_FILE`이다.
  - 최신본 변경 처리 중에는 문서를 삭제할 수 없다(409).
- **권한**: 관리자는 모든 문서를 다룰 수 있다. 그 외 사용자는 본인이 업로드한 문서만 다룰 수 있다(삭제·모델명과 같은 규칙).
  - 최신본 변경에서는 대상이 없거나, 볼 수 없거나, 본인 문서가 아니면 모두 **404**로 응답한다(D-01, 존재 숨김).
  - 버전 이력은 볼 수 있는 문서면 조회할 수 있고, 볼 수 없으면 404다.
- **버전 이력**: `GET /api/ingest/documents/{id}/versions`로 실제 버전 목록을 최신 순으로 돌려준다.
  - 항목: 버전, 원본 파일명, 상태(적용 중·이전 버전·처리 중·전환 대기·처리 실패), 활성 여부, 등록·적용·교체 일시, 업로더, 처리기, 페이지, 청크 수, 크기, 실패 오류.
  - **D-18 [이 버전 적용]**: 기존 코드에 없어서 만들지 않았다. 응답에 `restore_supported=false`를 넣었고 화면에 버튼이 없다.
- **목록 화면**
  - "작업" 컬럼은 [최신본 변경] [버전 이력] [삭제] 순서다.
  - 처리 중이면 "현재 버전" 칸에 `v2` 옆으로 `⟳ v3`을 표시하고, [최신본 변경]과 삭제를 비활성화한다.
  - 3초마다 작업 상태를 확인한다. 끝나면 목록을 다시 읽은 뒤 성공 또는 실패를 안내한다. 새로고침해도 목록의 `pending_job_id`로 확인을 이어간다.
- **설정**: `DOCUMENT_VERSION_REPLACE_ENABLED`(기본 true). false면 접수 API가 403이고 버튼이 숨겨진다. 버전 이력은 유지된다.
  - 이 기능을 쓰지 않으면 기존 동작은 그대로다(개정 이력이 없으면 검색 조건도 바뀌지 않음).

## 2. 설계 결정 (요청서 4.2의 "안전한 처리 순서")

| 항목 | 결정 | 이유 |
|---|---|---|
| 상태 전이 | `building`(접수) → `ready`(포인트 저장·검증) → `active`(전환) / 실패 `failed` | 요청서 4.2. 기존 CHECK 값을 그대로 씀 |
| 전환 원자성 | 이전 active 은퇴·새 버전 활성·문서 행 갱신·청크 행을 한 RDB 트랜잭션으로 | 검색 기준이 RDB라서 이 트랜잭션 커밋 시점에 검색 결과가 바뀜 |
| RDB↔Qdrant 비원자성 | 새 포인트는 먼저 저장하되 검색 제외(비활성), 전환 후 이전 포인트 삭제. 삭제 실패는 `vectors_purged_at` NULL로 남겨 계속 제외 + 주기 정리 | 어느 단계에서 멈춰도 구·신 버전이 섞여 검색되지 않음 |
| 제외 조건 | 문서별 `must_not[document_id=X AND NOT (version_no=활성 OR (활성=1 AND version_no 없음))]` | Phase 2 이전 포인트(payload에 version_no 없음)는 v1로 취급 |
| 버전 행 PK | 기존 `(document_id, version_no)` 그대로. `version_id`·`current_version_id`는 추가하지 않음 | `tb_documents.version_no`가 활성 버전을 가리켜 충분 |
| 원본 파일 | v2부터 `{날짜}_{document_id}_v{N}{확장자}` | 같은 날 교체해도 이전 버전 원본을 덮어쓰지 않음(버전별 보존) |
| 엑셀 사진 | 기존 규칙 `{document_id}-v{버전}-i{순번}` | 버전별 리소스가 충돌 없이 보존됨 |
| 청크 행 | 버전별로 남김(`tb_chunks`의 version_no) | 이력·검수 승계용(source_key). 검색은 Qdrant 포인트 기준 |
| 파서·문서 유형 | 기존 문서의 설정을 쓰고, 새 파일 형식에 맞지 않으면 docling·자동 | 대화상자는 파일만 받음(목업) |
| 문서 삭제 | 모든 버전 포인트·리소스·**모든 버전 원본 파일** 삭제, 버전 행은 retired(감사) | 이전 버전 원본이 남지 않도록 보완 |

## 3. 변경 파일

**백엔드 (`adrag_backend/`)**
- `migrations/versions/0005_document_version_replace.py` (신규)
  - `tb_document_versions.vectors_purged_at`
  - 부분 유일 인덱스 `uq_doc_versions_in_progress`(building·ready, 문서당 1개)
  - 기존 retired 행 채움
- `app/services/version_visibility.py` (신규): 비활성 버전 검색 제외 조건(RDB 기준).
- `app/repositories/vector_repository.py`
  - 5개 검색 메서드에 제외 조건(`_visible`) 적용.
  - `delete_document_version_points`(한 버전만, 또는 활성 버전을 뺀 나머지) 추가.
  - `count_document_version_points` 추가.
- `app/repositories/ingest_record_repository.py`: 문서 잠금, 처리 중 버전, 다음 번호, 현재 해시, building 생성, 상태 변경, 실패 버전 경로 기록, **전환(activate_version)**, 정리 완료 표시, 정리 대상, 이력 조회. 삭제 시 정리 시각 기록.
- `app/services/ingest_pipeline.py`
  - `target_document_id`·`version_no` 처리: 기존 ID 사용, 버전별 원본·사진·청크 ID.
  - 저장 후 검증 → ready → 전환 트랜잭션 → 이전 포인트 정리.
  - 새 버전 전용 실패 보상(`_compensate_new_version`).
  - 새 문서 경로는 동작 그대로 두고 함수로만 나눴다.
- `app/services/ingest_service.py`
  - `ingest()`에 `target_document_id`·`version_no` 인자 추가.
  - 원본 저장 파일명에 버전을 붙인다.
  - 문서 삭제 시 모든 버전 원본을 지운다.
- `app/services/ingest_jobs.py`: 실패 시 버전 `failed`. 재시도 시 같은 버전을 다시 `building`으로(다른 교체가 처리 중이면 409).
- `app/routes/ingest.py`
  - 업로드 검증·임시 저장을 함수로 분리했다(업로드 동작 동일).
  - `POST`·`GET /documents/{id}/versions` 추가.
  - 목록에 `pending_version_no`·`pending_job_id` 추가.
  - 처리 중 삭제 409.
  - `/ingest/options`에 `version_replace_enabled` 추가.
- `app/core/config.py`: `document_version_replace_enabled`.
- `main.py`: 주기 작업(`resource_cleanup_interval_seconds`)에 이전 버전 포인트 재정리 추가.
- `tests/test_document_versions.py` (신규, 6개).
- `tests/test_database_migrations.py`: HEAD → 0005.
- `scripts/gen_table_definition.py`: 설명 갱신.

**프런트엔드 (`adrag_frontend/`, 주석 `2026.10.19(sooyeon.choi) 추가/수정`)**
- `src/composables/useDocumentVersions.js` (신규): 최신본 변경 대화상자, 접수, 작업 상태 확인(3초, 새로고침 복원), 버전 이력 조회.
- `src/composables/useAdminDocuments.js`: 버전 기능 연결, 목록을 읽을 때 처리 중 작업 동기화.
- `src/composables/useDocumentUpload.js`: 서버 옵션 `version_replace_enabled`.
- `src/api/adminApi.js`: `replaceDocumentVersion()`·`documentVersions()`.
- `src/views/AdminView.vue`: 작업 컬럼 버튼 3개, 처리 중 표시, 최신본 변경·버전 이력 대화상자, 스타일. 기존 대화상자·버튼 색을 기준으로 했고 목업 CSS는 복사하지 않았다.
- `tests/documentVersions.test.mjs` (신규).

**문서**
- `docs/design/03_테이블_정의서_현행_v1.0.md`: 재생성, 0005 기준.
- `docs/design/06_미결_이슈_목록.md`
- 이 보고서

목업·요구사항 원본, `excel_ingest`, docling-parser는 수정하지 않았다.

## 4. 검증 결과

| 검증 | 결과 |
|---|---|
| `pytest tests/test_document_versions.py` | **6 passed**: ① 접수→처리 전 기존본 유지·목록 처리 중 표시·제외 조건, 처리 중 재접수·삭제 409, 처리 후 ID·모델명 유지·파일명·페이지·청크·버전 갱신·버전별 원본 경로·이전 포인트 정리·버전별 청크 이력·이력 API ② 같은 파일 409, 없는 문서·타인 문서 404, 권한 밖 주제 이력 404, 관리자 허용 ③ 5개 동시 접수 → 1개만 성공 ④ 파싱 실패 → failed·문서 행·포인트 불변·실패 원본 경로 기록·재시도 시 building ⑤ 전환 트랜잭션 중 실패 → 새 포인트만 삭제·문서 행·청크 롤백 ⑥ **in-memory Qdrant로 실제 필터 동작**(처리 중 v2 숨김, 정리 전 구 버전 숨김, 권한 필터와 결합, 버전 정보 없는 기존 포인트=v1) |
| 기존 관련 테스트(모델명·엑셀 적재·적재 기록·삭제·라우팅·마이그레이션) | 95 passed(변경 후), 삭제·버전 22 passed |
| 프런트 `node --test`(3개 파일) | **3 passed**: 권한 없는 문서 대화상자 미개방, 409 오류 대화상자 표시, 접수→처리 중→완료 시 목록 재조회·안내, 새로고침 복원→실패 안내, 이력 조회 |
| `vite build` | 통과 |
| 로컬 dev DB alembic | 0004 → 0005 upgrade → downgrade 0004 → upgrade, head 0005 |
| **dev 서버 E2E**(엑셀 샘플, backend 모드) | v1 등록(243청크) → v2 접수 202 → 처리 중 목록 v1 + 대기 v2, 재접수 409, 삭제 409, 비소유 사용자 404 → v2 완료(108초): 파일명 rev2·version 2·모델명 유지·최근 변경일 증가, Qdrant 포인트 {v2: 243}만 남음, 이력 v2 active·v1 retired, 같은 파일 409 → v3(빈 엑셀) 실패: 오류 "적재할 내용을 찾지 못했습니다", 문서 행·검색 포인트 v2 그대로, 이력 v3 failed + 오류, 처리 중 표시 해제 |
| **실제 Qdrant 서버 검색 격리** | 처리 중 버전(v99) 포인트를 넣으면 필터 없는 검색 1위가 v99인데, 서비스의 `search_similar`·`search_hybrid`는 v2만 반환. 확인 후 정리 |
| 브라우저(로컬 vite + dev 백엔드, 1600px·390px) | 작업 컬럼 버튼 3개, 버전 이력 대화상자(v3 실패 오류·v2 적용 중·v1 이전 버전), 최신본 변경 대화상자(모델명·현재 버전·안내·파일 선택) → 접수 → 행에 `v2 ⟳v4`, [최신본 변경]·삭제 비활성 → 새로고침 후에도 처리 중 유지 → 완료 시 자동으로 v4·파일명·최근 변경일 갱신 + 안내 → 390px에서 이력 대화상자 351px·페이지 가로 넘침 없음 → 기존 삭제 버튼으로 삭제(벡터·리소스·모든 버전 원본 정리 확인) |
| 백엔드 전체 회귀 | 6절 |

**하지 않은 검증·제약**
- docling 경로(PDF 등)로 새 버전을 실제 처리하는 것은 단위 테스트(가짜 파서)로만 확인했다. 로컬에서 docling-parser 서버로 실처리하지 않았다.
- docling 경로 **엑셀**(`EXCEL_PARSE_MODE=docling`)의 리소스 ID는 parser가 `{document_id}-r{순번}`으로 정한다. 그래서 개정본에서 같은 ID가 겹칠 수 있다(Phase 2 이슈 B6). 겹치면 리소스 업로드가 거부되어 새 버전이 **실패하고 기존본이 유지된다**. 운영 기본인 backend 모드 엑셀은 버전별 ID라 문제가 없다. parser 코드는 수정하지 않았다(절대 규칙 5).
- 테스트 중 E2E 문서 업로더를 로컬 테스트 사용자로 바꿔 브라우저 흐름을 확인했고, 확인 뒤 삭제했다.

## 5. 마이그레이션·되돌리는 방법

- 마이그레이션: **있음.** `0005_document_version_replace`(컬럼 1개와 부분 유일 인덱스 1개, 기존 retired 행 채움).
- 기능만 끄기: `DOCUMENT_VERSION_REPLACE_ENABLED=false`로 두고 백엔드를 재시작한다. 버전 이력과 검색 제외 조건은 그대로 동작한다.
- DB 되돌리기: `alembic downgrade 0004_document_model_name`. 인덱스와 컬럼이 삭제된다.
  - v2 이상 버전 행과 버전별 청크 행은 남는다. 0003 스키마에서도 유효하다.
  - 단, 0005 이전 코드는 이 행들을 버전 전환으로 해석하지 않는다.
  - 되돌리기 전에 처리 중(building·ready) 버전이 없는지 확인한다.
- 코드: 3절의 파일을 이전 상태로 되돌린다. 검색 제외 조건이 빠지므로, **되돌리기 전에 이전 버전 포인트 정리가 끝났는지 확인**한다.

  ```sql
  SELECT count(*) FROM tb_document_versions v JOIN tb_documents d USING (document_id)
  WHERE v.version_no <> d.version_no AND v.vectors_purged_at IS NULL;
  ```

  결과가 0이어야 한다.

## 6. 백엔드 전체 회귀

최종 실행(10-19, 단독 실행): **456 passed / 11 failed / 16 skipped / 3 errors**

- **실패 11건과 오류 3건은 모델명 1단계 기준선(450/11/3)의 목록과 같다.** 신규 실패는 0이다.
- 오류 3건은 테스트 순서 때문에 생기는 수집 오류다(`test_stats_api`, voice 2개). voice 2개는 따로 실행하면 9 passed.
- 통과 6건 증가: 이번에 추가한 `test_document_versions.py` 6개.
- 중간 경과
  - 첫 전체 실행은 다른 pytest를 동시에 돌려 테스트 DB 스키마가 중간에 다시 만들어졌다(오류 51건). 이 결과는 무효로 처리했다.
  - 두 번째 실행에서는 신규 테스트 1개가 기존 순서 의존 문제(다른 테스트가 설정 모듈을 stub으로 바꿈)로 실패했다. 목록 조회용 서비스를 실제 클래스로 직접 만들도록 테스트 준비 코드를 고쳤고, 최종 실행에서 통과했다. 제품 코드 결함은 아니다.
- 다음 Phase 시작 시 기준선: **456 / 11 / 3**.

## 7. 남은 이슈

- **Q-MN-1**: 모델명을 수정해도 기존 엑셀 청크 머리말은 그대로다. 이제 최신본 변경을 하면 새 버전 청크는 **현재 모델명**으로 만들어진다. 남는 것은 "변경 없이 모델명만 고친 경우"다.
- docling 경로 엑셀 개정본의 리소스 ID 충돌(B6). 4절 참조.
- 동시성은 단일 앱 프로세스 기준으로 확인했다. 다중 워커는 Phase 3의 작업 큐에서 처리한다. 접수 직렬화는 DB 잠금이라 다중 프로세스에서도 유효하다.
- 이전 버전 원본 다운로드, 버전 간 변경 시트 비교(D-02 문서 상세)는 미구현이다(Phase 5 문서 상세).
- 실패한 최신본 변경 버전의 원본 파일은 문서를 삭제할 때 정리된다. 별도 정리 작업은 없다.
- 평가용 청크 저장소(`app/evaluation/adapters/chunk_store_adapter.py`)는 컬렉션 전체를 scroll하며 버전 제외 조건을 쓰지 않는다. 운영 검색과는 무관하다.
- 비관리자 권한은 기존 규칙(본인 업로드 문서)을 따랐다. D-04 사용자별 문서 권한이 도입되면 함께 정리한다.

## 8. 요구사항 정의서·기능 목록에 반영할 것

- UI-12 작업 컬럼: [최신본 변경]·[버전 이력]·삭제. 처리 중 표시와 처리 중 변경·삭제 불가.
- 신규 API: `POST /api/ingest/documents/{id}/versions`(최신본 변경 접수, 202), `GET /api/ingest/documents/{id}/versions`(버전 이력). API ID 부여가 필요하다. D-01의 `/api/admin/documents/{doc_id}/versions` 대신 기존 `/api/ingest` 라우터를 확장했다(D-01 "기존 API 확장" 허용).
- 응답 코드: 409 `JOB_IN_PROGRESS`·`DUPLICATE_FILE`, 404(존재 숨김), 처리 중 삭제 409.
- 신규 설정 `DOCUMENT_VERSION_REPLACE_ENABLED`, 신규 컬럼 `tb_document_versions.vectors_purged_at`.
- D-18: 이전 버전 적용은 1차에 제공하지 않는다(기존 코드에 없음).
