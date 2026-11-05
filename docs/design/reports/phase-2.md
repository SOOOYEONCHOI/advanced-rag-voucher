# Phase 2 보고서 — 문서 버전·청크·사진·흐름도 적재

> 작성 2026-10-16 · 관련 ID: F-2-03~05, F-3-04 / R2-1, R2-3, R3-1~4, R4-1 / D-08, D-19, D-21, D-22 · 결정: `reports/phase-2-plan.md` P2-1~P2-13(10-16 승인)
> Alembic `0003_versions_chunks_images`. dev DB(`rag_chatbot_dev`) 적용 완료.

## 1. 요약

- **문서 버전 행**(`tb_document_versions`)을 만든다. 지금은 업로드 1건 = v1·active 1행(개정본 전환은 Phase 3). 처리기·원본 해시·확인용 md 폴더·처리 요약(시트·청크·사진 수, 시트별 관리대장 개정 차수)이 버전에 남는다.
- **청크 원천 테이블**(`tb_chunks`)에 excel·docling **두 경로 모두** 청크를 기록한다. `chunk_id = {document_id}:{version}:{source_key}#{part_no}`, Qdrant 포인트 ID = `uuid5(chunk_id)`(결정적). `source_key`는 버전과 무관한 키(예: `09:step:6`)로, 개정 후 검수·평가 승계에 쓴다.
- **엑셀 사진**: excel_ingest가 뽑은 사진 배치를 `tb_spreadsheet_resources`에 바로 `committed`로 저장(역할·Step·인쇄 영역·연결 방식·신뢰도·검수 상태). `resource_id = {document_id}-v{version}-i{순번}`(백엔드 발급, 같은 파일을 여러 번 올려도 충돌 없음). 파일은 기존 위치 `documents/{doc}/resources/{rid}/original/{sha}.{ext}`라 **기존 이미지 API·[첨부 리소스 보기]가 그대로 동작**한다.
- **청크↔사진 연결**(`tb_chunk_resources`) + Qdrant payload `resource_ids`. 사진은 Qdrant에 넣지 않는다(P2-3).
- **흐름도**(`tb_flow_graphs`): 노드·연결·미연결 jsonb, 검수 상태. 흐름도 청크는 텍스트로 적재.
- **긴 청크 분할**: `MAX_CHUNK_SIZE`(기존 설정, 800) 초과 시 행 단위로 나누고 머리말(`[모델 > 시트 > …]`)·열 머리글을 조각마다 반복.
- **제품 모델**: 업로드 폼에 선택 입력 `제품 모델` 추가(`tb_documents.product_model`). 비우면 청크 머리말에 넣지 않는다.
- **staging 분리**(P2-13): 파서가 보낸 staging 리소스는 `tb_spreadsheet_staging_resources`로, 확정 리소스에는 문서 FK(ON DELETE CASCADE).
- **문서 삭제**: 포인트·청크·연결·흐름도 행 삭제, 버전 행은 `retired`로 보존(감사), 사진 파일·리소스 행은 기존 삭제 로직.
- 기존 동작: `EXCEL_PARSE_MODE=docling`(기본)에서도 버전·청크 행은 기록되지만 검색·답변·화면 결과는 같다(이미지 포인트 없음, payload에 필드만 추가).

## 2. 변경 파일

| 파일 | 내용 |
|---|---|
| `adrag_backend/migrations/versions/0003_versions_chunks_images.py` (신규) | 신규 5테이블(`tb_document_versions`·`tb_chunks`·`tb_chunk_resources`·`tb_flow_graphs`·`tb_spreadsheet_staging_resources`), `tb_documents` +`doc_key`·`product_model`·`active_activated_at`, `tb_spreadsheet_resources` +14컬럼·`status<>'staging'` CHECK·문서 FK CASCADE. 기존 문서 v1 이관, staging 행 이동, **문서 없는 확정 리소스가 있으면 upgrade 중단**(자동 삭제 안 함). upgrade는 추가만(DROP·ALTER COLUMN 없음), downgrade 제공 |
| `adrag_backend/app/repositories/ingest_record_repository.py` (다시 작성) | 버전 생성·retired, 청크·연결·흐름도 기록/삭제, 문서별 개수 |
| `adrag_backend/app/ingest/records.py` (신규) | `assign_chunk_identity`(chunk_id·uuid5 point_id), 청크 행·연결 행·흐름도 행 변환 |
| `adrag_backend/app/ingest/excel_images.py` (신규) | excel_ingest assets·placements → 사진 파일 저장 + 배치 행 |
| `adrag_backend/app/ingest/excel_chunks.py` | `source_key`(중복 시 `~2`), 분할(P2-9), `resource_ids` |
| `adrag_backend/app/ingest/excel_runner.py` | 요약에 `sheet_revisions`(관리대장 매칭 시트별 개정 차수, R2-3). md 출력의 LATEST·보관 정리를 잠금 안에서 처리(동시 적재 경합 수정, 3절) |
| `adrag_backend/app/services/ingest_pipeline.py` | ParseStep 원본 해시, ChunkStep 엑셀 사진 계획, IndexStep **한 트랜잭션**: 문서 행 → doc_key·product_model → (docling) 리소스 commit → 엑셀 사진 파일·행 → 버전 → 청크 → 연결 → 흐름도 |
| `adrag_backend/app/services/ingest_service.py` | 포인트 ID를 청크 메타의 `point_id`로, payload `version_no`·`point_type`·`source_key` 추가, `ingest()`에 `product_model`·`job_id`, 삭제 시 청크·흐름도 삭제·버전 retired |
| `adrag_backend/app/repositories/vector_repository.py` | payload 인덱스 `version_no`·`point_type`·`source_key` |
| `adrag_backend/app/repositories/spreadsheet_resource_repository.py`, `app/services/spreadsheet_resource_service.py` | staging 테이블 분리(`get_staging`, commit 시 행 이동) |
| `adrag_backend/app/routes/ingest.py` | 업로드 Form `product_model` |
| `adrag_backend/app/routes/spreadsheet_resources.py` | 리소스 파일 경로 계산에서 `sqlite_db_path` 의존 1곳 제거 |
| `adrag_frontend/src/views/AdminView.vue`, `composables/useAdminDocuments.js`, `composables/useDocumentUpload.js` | 업로드 폼 `제품 모델`(선택). 변경 지점마다 `2026.10.16(sooyeon.choi) 추가` 주석 |
| `adrag_backend/scripts/gen_table_definition.py`, `docs/design/03_테이블_정의서_현행_v1.0.md` | 새 테이블·컬럼 설명, 복합 FK 표시 지원, 재생성(29테이블·357컬럼) |
| `adrag_backend/tests/test_database_migrations.py` | 테이블 수 29·HEAD 0003, 0003 이관·staging 왕복·고아 리소스 중단·물리 삭제 CASCADE·active 1개 제약 |
| `adrag_backend/tests/test_excel_ingest_pipeline_sample.py` (구 `test_excel_ingest_phase1_sample.py` 개명) | Phase 1 + Phase 2 완료 기준(샘플 엑셀) |
| `adrag_backend/tests/test_ingest_records.py` (신규) | 분할·중복 키·결정적 ID·docling 경로 버전·청크 기록 |
| `adrag_backend/tests/test_spreadsheet_resource_service.py`, `test_spreadsheet_resource_analysis.py` | 수집 제외 해제, staging 분리에 맞게 헬퍼 수정. 옛 계보 설계를 검증하던 5건은 사유를 적어 skip |
| `adrag_backend/tests/conftest.py` | `collect_ignore` 사유 갱신(옛 계보 Phase 2 명세 3파일은 계속 제외) |

## 3. 완료 기준 충족 근거 (`phase-2-plan.md` 4절)

| 기준 | 결과 |
|---|---|
| 1. 0003 왕복·기존 컬럼 보존 | `test_database_migrations.py` **30 passed**(base↔head 왕복, 0003 이관·staging 이동·downgrade 복원, 고아 확정 리소스 시 중단, 문서 물리 삭제 시 버전·청크·리소스 CASCADE, 문서당 active 1개). 0003 upgrade에는 컬럼 삭제·이름·타입 변경이 없다(DROP은 downgrade에만). 0002 제약 유지 |
| 2. 샘플 엑셀 | `test_excel_ingest_pipeline_sample.py` **2 passed**: 사진 배치 **190행·파일 190개 저장(고유 152)**, Step 6 청크 `resource_ids`의 사진이 모두 step_no 6, 흐름도 1건, `tb_chunks` 행 = Qdrant 포인트, 청크 최대 길이 ≤ 800, 검수 필요 수 = 요약 값, 관리대장 매칭 시트 10 |
| 3. 같은 파일 재업로드 | 같은 파일 3건 동시 적재: 문서마다 리소스 190행, 사진·포인트 ID 충돌 0, md 임시 폴더 잔존 0 |
| 4. 문서 삭제 | 청크·연결·흐름도·리소스 0, 버전 `retired`, 포인트 0, 사진 폴더 삭제 |
| 5. docling 경로 | `test_ingest_records.py` **4 passed**: 버전 v1 active(docling)·청크 행 = 포인트, payload `chunk_id` = 포인트 ID(평가 호환). 이미지 포인트 없음 |
| 6. 회귀·실서버 | 아래 |

**전체 회귀** `pytest -m "not e2e and not voice"`: 첫 실행 **425 passed / 13 failed / 1 error**(기준선 399/11/1). 신규 실패 2건(`test_deletion_consistency`의 문서 삭제 2건)은 `IngestService`를 `__new__`로 만든 테스트에서 `self.db`가 없어 난 것 → `delete_document`가 DB 관리자를 `getattr(self, "db", None) or get_database_manager()`로 얻게 고침(파이프라인과 같은 방식), 16 passed. 수정 후 재실행: **427 passed / 11 failed / 1 error — 신규 실패 0**(8절). 나머지 11 실패·1 오류는 기준선과 같은 기존 문제(`phase-1_5.md` 7절: sys.modules stub 순서 의존 8, Phase 3 `requeue_failed` 1, `ui_type` 1, parse_regression 1, `test_stats_api` 수집 오류).

**동시 적재 경합(수정)**: 샘플 테스트를 다른 파일과 함께 돌리면 동시 3건 테스트가 간헐적으로 실패(4회 중 2회). 원인은 같은 문서 폴더에서 작업끼리 `LATEST` 교체·보관 개수 정리(`export_md._cleanup`)가 서로의 폴더를 지우며 `FileNotFoundError` → 이미 자리 잡은 md까지 "출력 실패"로 처리. `excel_runner._export`에서 이 단계를 프로세스 잠금으로 묶고, 실패해도 md 경로는 돌려주게 고침(excel_ingest 모듈은 수정 안 함). 경합 재현 스크립트(3스레드×30회) 실패 0. 다중 워커 프로세스(Phase 3)에서는 파일 잠금이 필요할 수 있다(6절).

**dev 서버 실E2E**(rag-backend-dev, backend 모드, 실제 임베딩 서버·Qdrant, 샘플 48MB, 제품 모델 `NEOCON C2`): 작업 completed 123초, 버전 active·excel_ingest·md 경로·해시 기록, 청크 240 = Qdrant 포인트 240, 리소스 190, 청크↔사진 51, 흐름도 1, 최대 길이 799, 이미지 API 200(image/png). 삭제: 벡터 240 삭제·잔여 0, 청크 0, 버전 retired, 리소스 deleted. 시험 문서 2건은 삭제, md 폴더·컨테이너 임시 파일 정리.

**프런트**: `vite build` 성공(출력은 저장소 밖에 만들고 삭제). 화면은 브라우저로 확인하지 않았다(제품 모델 입력이 업로드 요청에 붙는 것은 dev 서버 E2E에서 API로 확인).

## 4. 마이그레이션

있음 — `0003_versions_chunks_images`(down_revision `0002_schema_hardening`). dev 컨테이너는 기동 시 자동 적용. 운영 이관 순서는 `alembic upgrade 0001_baseline` → 이관 스크립트 → `alembic upgrade head`(0002·0003 포함).

## 5. 되돌리는 방법

- 스키마: `alembic downgrade 0002_schema_hardening` — 신규 5테이블 삭제, staging 행을 `tb_spreadsheet_resources`로 되돌림, 추가 컬럼 삭제. **Phase 2 이후 적재한 문서의 청크·버전·사진 배치 정보는 사라진다**(문서 행·포인트·사진 파일은 남음).
- 코드: 2절 파일을 이전 판으로. Qdrant 포인트는 payload 필드만 늘었으므로 이전 코드에서도 검색된다.

## 6. 계획 대비 편차·남은 이슈

| # | 내용 | 처리 |
|---|---|---|
| 편차 1 | payload 새 필드 이름을 계획의 `chunk_type` 대신 **`point_type`**(text/image/drawing)으로 했다. 기존 payload `chunk_type`이 이미 블록 종류(표·본문 등)로 쓰이고 있어 덮으면 기존 검색 메타가 깨진다 | 변경로그·기능 목록에 `point_type`으로 반영 필요(7절) |
| 편차 2 | 검색 필터 `must_not: point_type=image`를 넣지 않았다. 이미지 포인트가 없어 필요 없음 | 이미지 포인트를 넣는 Phase 5에서 |
| 편차 3 | `revision_label`(문서 단위 개정 차수)은 비워 둠. 관리대장 개정 차수가 **시트(공정)마다 달라** 문서 하나의 값으로 정할 기준이 없다. 시트별 값은 버전 `summary_json.sheet_revisions`와 청크 payload `revision`에 있다 | `TODO(결정필요)` — Q-P2-1 |
| 편차 4 | emf/wmf 사진은 변환하지 않고 원본 그대로 저장(브라우저 미표시) | Phase 5 검수 화면 때 변환 여부 결정 |
| 이슈 | docling 경로 개정본의 resource ID(`{document_id}-r{순번}`) 충돌 | Phase 3(06 문서 B6) |
| 이슈 | 포인트 ID uuid4 → uuid5: 기존 평가 골드셋(포인트 ID 기준)은 재적재 문서와 맞지 않음. dev 평가 데이터 0건이라 현재 영향 없음 | Phase 7(06 문서 B10, `source_key`로 재매핑) |
| 이슈 | 동시 md 출력 잠금은 프로세스 안에서만 유효 | Phase 3 다중 워커 설계 때 |
| 이슈 | Q-15.7: 업로드 대기 폴더·저장소 생성자가 여전히 `sqlite_db_path`를 읽음(이번에는 리소스 경로 1곳만 정리) | Phase 3 작업 큐 정리 때 |
| 이슈 | skip한 옛 계보 테스트 5건(`test_spreadsheet_resource_service`·`_analysis`), 수집 제외 3파일(`test_excel_ingest_indexing`·`_sample`·`test_spreadsheet_pipeline_integration`) — 현행 결정과 다른 설계 명세 | 해당 기능 재설계 시 삭제 또는 개정 |
| 환경 | **C: 드라이브 여유 약 3GB(319GB 중)**. 원인은 이 작업 밖(WSL/Docker 가상 디스크로 보임). pytest 임시 폴더는 `D:\Dev\SVNLocal\_pytest_tmp`(저장소 밖)로 옮김 | 사용자 확인 필요 |

### 결정 필요

- **Q-P2-1** 문서 단위 개정 차수(`tb_document_versions.revision_label`)를 무엇으로 할지. 추천: **1차는 비워 두고 시트별 값만 사용**(문서 목록 표시가 필요해지면 "가장 최근 개정일의 차수"로) — Phase 3 개정본 전환 때 함께 결정.

## 7. 요구사항 정의서·기능 목록에 반영할 것

- 신규 테이블 5종(`03_테이블_정의서_현행_v1.0.md`), 청크 ID 규칙 `{document_id}:{version}:{source_key}#{part_no}`, 포인트 ID = uuid5(chunk_id).
- Qdrant payload 신규 필드 `version_no`·`point_type`·`source_key`·`resource_ids`(D-21의 `chunk_type`은 `point_type`으로).
- 엑셀 사진 resource_id 규칙 `{document_id}-v{version}-i{순번}`.
- 업로드 입력 `제품 모델`(선택, UI-12) — 화면 정의에 추가.
- 처리 요약(`summary_json`·작업 결과)에 `sheet_revisions`(R2-3).

## 8. 전체 회귀 재실행 결과

`pytest -m "not e2e and not voice"` (10-16 16:03, 9분 22초): **427 passed / 11 failed / 16 skipped / 1 error**. 실패·오류 목록은 기준선(399/11/1)과 동일 — 신규 실패 0. 통과 28건 증가는 Phase 2 신규·복원 테스트.
이후 샘플 테스트에 관리대장 단언을 추가해 Phase 2 관련 3파일 재실행: 22 passed.
