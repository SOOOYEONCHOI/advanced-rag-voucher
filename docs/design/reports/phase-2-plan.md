# Phase 2 착수 계획 — 청크·이미지 적재 (승인됨)

> 작성 2026-10-16 · 관련 ID: F-2-03~05, F-3-04 / R2-1, R3-1~4, R4-1 / D-08, D-21, D-22 · 근거: DB 구조 변경안 v0.1과 그 코드 대조 검토(둘 다 삭제 — 결정은 이 문서, 이월 이슈는 `06_미결_이슈_목록.md`)
> 표의 "검토 3(a)·B7" 등은 삭제한 검토 보고서의 절 번호다. 요지는 각 행에 적었고, 남은 이슈는 06 문서 2절에 같은 번호로 있다.
> **2026-10-16 사용자 승인(P2-1~P2-13).**
> 이 문서대로 구현하고 `reports/phase-2.md`를 쓴다.
> 2026-10-16 갱신: 스키마 보완(`05_DB_스키마_보완안_v1.0.md`, Alembic `0002_schema_hardening` 적용) 반영 — Phase 2 리비전은 **`0003_versions_chunks_images`**, P2-13 추가.

## 1. Phase 2 범위

엑셀 전용 처리기(Phase 1) 결과 중 아직 버리고 있는 것을 저장하고, 답변·검수·평가가 쓸 수 있는 원천 데이터를 PostgreSQL에 남긴다.

| 포함 | 제외(다른 Phase) |
|---|---|
| 문서 버전 행(현재는 v1만), 청크 원천 테이블, 사진 저장·배치(역할·Step·신뢰도·검수 상태), 흐름도 저장, 긴 청크 분할, 텍스트 청크의 연결 사진 ID | 개정본 업로드·전환(Phase 3), 답변에 사진 붙이기·문서 권한·용어 사전(Phase 4), 검수 화면·VLM(Phase 5) |

## 2. 결정 추천안

### 지금 필요한 결정 (Phase 2)

| # | 결정할 것 | 추천안 | 이유 |
|---|---|---|---|
| **P2-1** (D-19) | DB 기준 | **현행 스키마 기준, 1차는 "추가만"**(기존 컬럼 삭제·이름·타입 변경 없음) | 04 변경안 그대로. 기존 화면·통계·평가가 깨지지 않음 |
| **P2-2** (D-21) | Qdrant 구조 | **대화 주제별 컬렉션 유지**(공용 `chunks_v1` 안 함). payload에 `chunk_type`(text/image/drawing)·`version_no`·`chunk_id` 추가, `document_id`·`version_no`·`chunk_type` payload 인덱스 | 기존 주제 단위 권한·검색 경로 유지. 기존 포인트는 `chunk_type`이 없어도 "텍스트"로 취급(검색 필터를 `must_not: chunk_type=image`로 쓰면 재색인 불필요) |
| **P2-3** | 이미지 포인트를 Qdrant에 넣을지 | **Phase 2에서는 넣지 않는다.** 사진은 PostgreSQL에만 저장하고, 텍스트 청크 payload `resource_ids`로 연결 | 검토 3(c): 넣으면 기존 검색·근거·인용에 섞임. 1차 요구(R4-3)는 "단계 사진 첨부"라 연결만으로 충분. 사진 검색은 VLM 설명이 생기는 Phase 5에서 재검토 |
| **P2-4** (D-22) | 사진 배치 테이블 | **`tb_spreadsheet_resources` 확장**(04 변경안) + 아래 보정: ① excel_ingest 경로의 `resource_id`는 백엔드가 `{document_id}-v{version}-i{순번}`으로 발급(파서 발급 충돌 회피), ② staging 없이 바로 `committed`, ③ 해시는 새 컬럼 없이 기존 `content_hash`(`sha256:` 형식) 사용, ④ 신뢰도는 `double precision` | 이미지 API·뷰어·[첨부 리소스 보기]·목업이 이미 `resource_id`를 씀 → 화면 수정 없이 사진이 보임. 검토 3(a)의 충돌(파서 ID·staging)은 ①②로 피함. 개정본 때 docling 경로 ID 충돌은 Phase 3에서 처리 |
| **P2-5** | 이미지 원본 중복 제거(`tb_image_assets`) | **Phase 2에서는 만들지 않는다.** 원본은 기존처럼 `documents/{document_id}/resources/{resource_id}/original/`에 저장 | 검토 B7: 공유 원본은 문서 삭제 로직과 충돌. 샘플 1건 이미지 152장 수준이라 용량 문제 작음. 필요해지면 2차 |
| **P2-6** | 문서 버전 | **`tb_document_versions` 신설**(현재는 업로드마다 v1·active 1행), **`tb_documents.version_no` = 현재 적용 버전**으로 의미 확정, 기존 문서는 이관 시 v1 행 생성 | 청크·사진·흐름도를 버전에 묶어 두면 Phase 3에서 재색인 없이 개정본 전환 가능. 검토 3(b): 기존 코드 충돌 없음 |
| **P2-7** | 청크 원천 테이블 | **`tb_chunks` 신설**: `chunk_id`(text PK, `{document_id}:{version}:{원천키}`) · `point_id`(uuid, **Qdrant ID = uuid5(chunk_id)**) · **`source_key`(버전 무관 키, 예: `09:step:6`)**. excel·docling **두 경로 모두** 기록 | PostgreSQL이 원천(Qdrant 재생성 가능, 야간 정합성 점검 기준). 검토 B10: 평가는 계속 포인트 ID로 비교, `source_key`는 개정 후 검수·평가 승계용 |
| **P2-8** | 청크↔사진 연결 | **`tb_chunk_resources`(chunk_id, resource_id, sort_order)** 신설 + payload `resource_ids` | Phase 4 답변 사진 첨부와 Phase 5 검수 반영의 기준 |
| **P2-9** | 긴 청크 분할 | **`MAX_CHUNK_SIZE`(기존 설정) 초과 시 행 단위 분할, 머리말(`[모델 > 시트 > …]`) 반복**, 조각은 같은 `source_key` + 순번 | 표 섹션 청크가 25행 단위라 길어짐(Phase 1 Q-P1-3). 기존 설정 재사용 |
| **P2-10** (D-08) | 흐름도 | **`tb_flow_graphs` 신설**(노드·연결·미연결 jsonb, `review_status`), 흐름도 청크는 지금처럼 텍스트로 적재 | 1차 범위(저장 + 청크 + md). 뷰어·검수 화면은 2차 |
| **P2-11** | 적용 모델명(청크 머리말 `[NEOCON C2 > …]`) | **업로드 폼에 선택 입력 `제품 모델`** 추가, 비우면 머리말 없음. 컬럼 이름은 **`product_model`**(04안 `applied_model` 대신, LLM `model_id`와 구분) | 이전 결정(Phase 2 결정: "model 폼 입력, 비면 prefix 없음")과 같음. 프런트 수정 1곳(주석 규칙 적용) |
| **P2-13** (보완안 P0-2) | staging과 확정 리소스 분리 | **`tb_spreadsheet_staging_resources` 신설**(파서가 보낸 staging 전용), commit 시 확정 행을 `tb_spreadsheet_resources`로 옮기고 **확정 리소스에 `document_id` FK(→ tb_documents, ON DELETE CASCADE)**. 기존 staging 행은 이관 시 새 테이블로 이동 | 지금은 staging 리소스가 문서 행보다 먼저 생겨 문서 FK를 걸 수 없다(docling 경로). 분리하면 확정 리소스가 없는 문서를 가리킬 수 없고, 주제 삭제(문서 물리 삭제) 때 리소스 행도 함께 정리된다(파일은 기존 삭제 로직). 사진 배치 확장(P2-4)과 같은 테이블을 바꾸므로 함께 |
| **P2-12** | `doc_key` | **`tb_documents.doc_key` 추가, 값은 파일명 기준(Phase 1 md 폴더와 같음), 표시·검색 보조만**(D-01: 개정 판단에 쓰지 않음) | 관리대장 문서번호 연결(R2-3)은 관리대장 시트가 있는 문서에서 Phase 2 안에 IR의 개정 정보로 채움 |

### 나중 Phase에서 정해도 되는 것 (추천안만 미리)

| # | 시점 | 추천안 |
|---|---|---|
| D-20 문서 단위 권한 | Phase 4 | `tb_user_document_permissions` + 검색 시 `must_not: document_id ∈ 제외 목록`(payload `acl` 없음). 권한 판단 4곳을 한 함수로 모음, 권한 없음 응답 404 |
| D-23 대화·출처 | Phase 4 | `log_id`=message_id. **대화 이력에 `log_id`를 저장**(검토 B9 텍스트 매칭 제거). 청크 출처는 별도 테이블 대신 **`context_meta`에 시트·셀·버전·resource_ids 추가**(검토 2절) |
| D-24 모델 | Phase 5·7 | `tb_llm_models` + `model_role`, **채팅 모델 목록은 `model_role='llm'`만**(검토 B3) |
| Phase 3 작업 큐 | Phase 3 | 큐 컬럼 이름을 수집 제외된 기존 테스트(`test_ingest_queue_versions.py`)와 맞춤(`attempts`·`next_run_at` 등), 작업 관리자는 `job_type`을 보고 실행 |
| Q-1 사용자별 LLM 선택 | Phase 5 | 1차는 관리자 설정만, 사용자 선택 화면 숨김(테이블 유지) |
| Q-2 OpenAI | Phase 7 | 시드 OpenAI 3행 `is_enabled=false`, 평가 데이터 생성·LLM Judge도 사내 LLM 기본 |
| Q-3 용어 사전 | Phase 4 | `*_hint_terms`는 질의 유형 분류용이라 유지. YAML 검색 사전을 DB 사전 초기 데이터로 옮김. Kiwi는 사전 버전이 바뀌면 다시 만든다 |
| Q-4 주제 이름 권한 | 2차 | 현행 유지(주제 이름은 API로 못 바꿈) |
| Q-5 부서 단위 | 고객 확인 | 현행 "같은 부서 컬렉션만" 규칙 때문에 모델(주제)을 부서 너머로 줄 수 없음 — 1차 권한 범위를 고객과 확인 필요(D-15) |

## 3. 수정·신규 파일 (승인 시)

| 파일 | 내용 |
|---|---|
| `migrations/versions/0003_versions_chunks_images.py` (신규) | `tb_document_versions`, `tb_chunks`, `tb_chunk_resources`, `tb_flow_graphs` 신설 / `tb_documents`(+`doc_key`·`product_model`·`active_activated_at`) / `tb_spreadsheet_resources`(+`version_no`·`role_cd`·`section_type`·`step_no`·`step_title`·`anchor_type`·`in_print_area`·`overlay_json`·`link_method`·`link_confidence`·`review_status`·`reviewed_by`·`reviewed_at`·`review_inherited_from`) / 기존 문서 v1 행 이관, downgrade |
| `app/repositories/ingest_record_repository.py` | 고아 파일(옛 계보) → 0002 스키마에 맞게 다시 작성(버전·청크·흐름도 기록) |
| `app/ingest/excel_images.py` (신규) | excel_ingest assets·placements → resource 파일 저장 + 배치 행(emf/wmf 변환 실패 시 원본 보존) |
| `app/ingest/excel_chunks.py` | 분할(P2-9), `source_key`, `resource_ids` |
| `app/services/ingest_pipeline.py`, `ingest_service.py` | IndexStep에서 버전·청크·사진·흐름도 기록(한 트랜잭션), 포인트 ID = uuid5(chunk_id), payload `chunk_type`·`version_no`·`chunk_id` |
| `app/repositories/vector_repository.py` | payload 인덱스(`document_id`·`version_no`·`chunk_type`), 검색 필터에 `must_not: chunk_type=image` |
| `app/routes/ingest.py`, 프런트 `AdminView.vue`·`useDocumentUpload.js` | 업로드 폼 `product_model`(선택) |
| 문서 삭제 경로 | 버전·청크·배치 행 함께 정리(사진 파일은 기존 문서 단위 삭제 그대로) |
| `scripts/gen_table_definition.py` + `03_테이블_정의서` | 새 테이블 설명 추가·재생성, 04안 7장의 "268개 기존 컬럼 보존" 자동 비교 |
| `tests/` | `test_excel_ingest_indexing.py`·`test_excel_ingest_sample.py`(수집 제외 중)를 이 결정 기준으로 고쳐 되살림 |

## 4. 완료 기준

1. 0003 upgrade↔downgrade 왕복, 기존 24테이블 268컬럼(이름·타입) 변동 0, 0002 보완 제약 유지.
2. 샘플 엑셀: 사진 배치 190행·파일 152종 이상 저장, Step 6 청크의 `resource_ids`로 Step 사진을 찾음, 흐름도 1건, `tb_chunks` 행 수 = Qdrant 포인트 수, 청크 최대 길이 ≤ `MAX_CHUNK_SIZE`.
3. 같은 파일 재업로드(다른 문서): 사진 ID 충돌 0.
4. 문서 삭제: 버전·청크·배치 행·사진 파일·포인트 모두 정리.
5. 기존 docling 경로 문서도 `tb_chunks`·버전 v1 기록, 검색 결과 동일(이미지 포인트 없음 확인).
6. 단위 테스트 기준선(387/11/1) 대비 신규 실패 0, dev 서버 실제 업로드 확인.

## 5. 위험

- dev 서버는 자동 마이그레이션이라 0003 작성 중 `rag-backend-dev`를 멈춰야 한다(착수 시 중지 → 완료 후 재기동).
- 포인트 ID를 uuid4 → uuid5로 바꾸면 **기존 평가 골드셋(포인트 ID 기준)**은 재적재 문서에서 맞지 않는다. 현재 dev DB 평가 데이터는 0건이라 영향 없음.
