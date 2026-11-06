# 문서 이전 버전 복원 — 프런트엔드 전달용 화면 영역별 API v1.1

- 작성일: 2026-11-05
- 기준 목업: [admin_UI-12_이전버전복원_20261104_v0.2.html](mockups/admin_UI-12_이전버전복원_20261104_v0.2.html)
- 관련: UI-12 / SC-06 / R1-5
- 상태: 개발 계약안. 신규 API·확장 필드는 백엔드 구현 후 사용할 수 있다. 구현 완료 시 OpenAPI(`/docs`)와 함께 다시 공지한다.
- 전달 대상: 프런트엔드 담당자에게는 **이 문서와 목업 v0.2**만 전달하면 된다. 백엔드 내부 구현은 [백엔드 최종 설계 v1.1](문서_이전버전_복원_백엔드_최종설계_v1.1.md) 참고.
- 이전 판: [v1.0](문서_이전버전_복원_화면영역별_API_명세_v1.0.md). 다르면 v1.1을 따른다.

### v1.1 변경 요약 (v1.0 대비)

| # | 변경 | 프런트엔드 영향 |
|---|---|---|
| 1 | 목록의 기존 `pending_job_id`·`pending_version_no`는 **최신본 변경 전용**임을 명시. 복원 중에는 NULL | 기존 `useDocumentVersions.js`가 복원 작업을 최신본 변경으로 오인하지 않음. 잠금 판단은 `pending_operation` 사용 |
| 2 | 이력 응답에 `collection_display_name`, 행에 `uploaded_by_name` 추가. 기존 행 필드 `job_id`·`job_status`·`error` 유지 명시 | 목업의 “제조 작업표준”, 실패 행 사유 표시 |
| 3 | 행별 불가 사유 산정 규칙 확정(문서 단위 사유가 각 행에 복사됨) | 행의 `restore_block_reason`만 그대로 표시하면 목업과 같아짐 |
| 4 | 진행창 3줄 표시와 `current_step` 매핑표 | 목업 진행창 그대로 구현 가능 |
| 5 | 적용 이력 `operation_type`에 `replace` 추가, `activated_by_name` 추가 | “새 버전 vN 적용” 문구 |
| 6 | 오류 코드 추가: `VERSION_NOT_FOUND`(404), `METADATA_MISSING`(422), `INVALID_REQUEST`(422) | 오류 처리표 갱신 |
| 7 | 화면 영역별 “목업 요소 ↔ 응답 필드” 대응표 추가 | 바인딩 위치 확인 |

## 1. 공통 규칙

- URL은 `/api` 기준, 인증은 기존 `Authorization: Bearer <로그인 토큰>`.
- 권한(2026-11-06 권한 변경, D-22): **문서를 볼 수 있는 사용자는 이력 열람과 복원을 모두 할 수 있다**(관리자 전용 아님, 업로더가 아니어도 됨). 볼 수 없는 문서는 서버가 404. 역할명으로 버튼을 결정하지 말고 서버가 준 `can_restore`를 사용한다.
- 화면 진입은 기존 일반 사용자 문서 관리 화면(`/admin`)이다. 관리자 계정의 진입 규칙(`/admin/users`로 이동)은 바꾸지 않는다.
- 버전 번호는 정수, 파일 크기는 byte, 시간은 기존 API와 같은 **KST 문자열 `YYYY-MM-DD HH:mm:ss`** 또는 `null`. 다시 변환하지 않는다.
- 예시의 ID·파일명·시각·이름은 샘플이다.
- 기존 API 필드는 유지하고 추가 필드로 확장한다. 모르는 필드는 무시한다.
- `null`, 빈 배열, 실패 응답을 구분한다. 실패를 ‘이력 없음’으로 표시하지 않는다.
- 목업 우측 ‘목업 미리보기’ 패널(화면·권한·복원 결과 선택기)은 확인용이며 제품에 구현하지 않는다.

## 2. 화면 영역과 API 매핑

| 영역 | 목업 요소 | 이벤트 | API / 처리 |
|---|---|---|---|
| A. 문서 목록 | `#currentBadge`, `#docFile`, `#docPages`, `#updatedAt`, `#replaceButton`, 삭제 버튼, `#pageStatus` | 최초 진입·새로고침·복원 완료/실패 | `GET /ingest/documents` |
| B. 버전 이력 헤더·목록 | 헤더 모델명·대화 주제, `#historyFile`, `#historyNotice`, `.history-count`, `#versions` | ‘버전 이력’(`#openHistory`) 클릭 | `GET /ingest/documents/{document_id}/versions` |
| C. 버전 선택·하단 | `.version-option`, `#selectionSummary`, `#restoreSelected` | 행 선택 / ‘선택 버전 복원’ | **API 없음**(로컬 단일 선택) |
| D. 복원 확인 | `#restoreOverlay`, `#restoreBody`, `#confirmRestore` | ‘이 버전으로 복원’ | `POST /ingest/documents/{document_id}/versions/{version_no}/restore` |
| E. 복원 진행·결과 | `#restoreTitle`, `#backgroundRestore`, `#completeRestore`, `#retryRestore`, `#toast`, `#pageStatus` | 접수 후 폴링 | `GET /ingest/jobs/{job_id}` |
| F. 적용 이력 | `details` 펼치기, `#activationLog` | 처음 펼칠 때 / ‘더 보기’ | `GET /ingest/documents/{document_id}/activations` |

선택 상태는 `selectedVersionNo` 하나만 보관한다. 행을 눌러도 즉시 복원하지 않는다. 확인창 ‘취소’는 서버 요청이 없으므로 취소 API는 없다.

## 3. A 영역 — 문서 목록

`GET /api/ingest/documents?collection_name={기존 필터값}` — 기존 목록·필터 그대로. 문서마다 아래 두 필드가 추가된다.

```json
{
  "documents": [
    {
      "document_id": "doc-demo",
      "product_model": "조립 공정 A",
      "filename": "조립작업표준_v3.xlsx",
      "collection_name": "demo_sop",
      "version_no": 3,
      "total_pages": 18,
      "updated_at": "2026-11-03 14:20:00",
      "can_edit": true,
      "pending_version_no": null,
      "pending_job_id": null,
      "activation_revision": 3,
      "pending_operation": null
    }
  ],
  "total": 1
}
```

진행 중 작업이 있으면 `pending_operation`:

```json
{
  "job_id": "job-restore-demo",
  "operation_type": "restore",
  "status": "running",
  "current_step": "snapshot",
  "target_version_no": 1
}
```

| 필드 | 화면 처리 |
|---|---|
| `version_no` | `#currentBadge` “v{n}” |
| `filename` | `#docFile` |
| `total_pages` | `#docPages` |
| `updated_at` | `#updatedAt` ‘최근 변경일’. 복원 완료 시 서버가 갱신한다 |
| `pending_operation` | NULL이 아니면 해당 행의 [최신본 변경]·[삭제]를 비활성화하고 `GET /ingest/jobs/{job_id}` 폴링을 재개한다 |
| `pending_operation.operation_type` | `replace`(최신본 변경) 또는 `restore`(복원) |
| `pending_operation.target_version_no` | 복원이면 `#pageStatus` “v{target} 복원 처리 중 · 현재 v{version_no}으로 서비스 중” |

- `pending_operation`은 `queued/running`일 때만 값이 있다. 완료·실패 후에는 NULL.
- **기존 `pending_job_id`·`pending_version_no`는 최신본 변경 작업일 때만 값이 있다.** 복원 중에는 NULL이다. 기존 최신본 변경 화면 로직은 그대로 두고, 새로 만드는 잠금·복원 폴링 판단은 `pending_operation`을 사용한다.
- 새로고침 후 `pending_operation`이 있으면 폴링을 이어간다. localStorage 저장은 필요 없다.

## 4. B 영역 — 버전 이력 조회

`GET /api/ingest/documents/{document_id}/versions`

```json
{
  "document_id": "doc-demo",
  "product_model": "조립 공정 A",
  "collection_name": "demo_sop",
  "collection_display_name": "제조 작업표준",
  "current_original_filename": "조립작업표준_v3.xlsx",
  "current_version_no": 3,
  "activation_revision": 3,
  "total_versions": 3,
  "next_version_no": 4,
  "restore_supported": true,
  "can_restore": true,
  "restore_block_code": null,
  "restore_block_reason": null,
  "pending_operation": null,
  "versions": [
    {
      "version_no": 3,
      "status": "active",
      "is_active": true,
      "original_filename": "조립작업표준_v3.xlsx",
      "file_size": 2800000,
      "file_format": "xlsx",
      "parser_type": "excel_ingest",
      "processing_engine": "excel_ingest",
      "total_pages": 18,
      "chunk_count": 126,
      "uploaded_by": "demo",
      "uploaded_by_name": "데모",
      "created_at": "2026-11-03 14:20:00",
      "activated_at": "2026-11-03 14:20:00",
      "retired_at": null,
      "job_id": "job-upload-v3",
      "job_status": "completed",
      "error": null,
      "can_restore": false,
      "restore_block_code": "ALREADY_ACTIVE",
      "restore_block_reason": "현재 적용 중인 버전입니다."
    },
    {
      "version_no": 2,
      "status": "retired",
      "is_active": false,
      "original_filename": "조립작업표준_v2.xlsx",
      "file_size": 2500000,
      "total_pages": 16,
      "chunk_count": 112,
      "uploaded_by": "demo",
      "uploaded_by_name": "데모",
      "created_at": "2026-10-28 10:30:00",
      "activated_at": "2026-10-28 10:30:00",
      "retired_at": "2026-11-03 14:20:00",
      "job_id": "job-upload-v2",
      "job_status": "completed",
      "error": null,
      "can_restore": true,
      "restore_block_code": null,
      "restore_block_reason": null
    },
    {
      "version_no": 1,
      "status": "retired",
      "is_active": false,
      "original_filename": "조립작업표준_v1.xlsx",
      "file_size": 2100000,
      "total_pages": 14,
      "chunk_count": 98,
      "uploaded_by": "demo",
      "uploaded_by_name": "데모",
      "created_at": "2026-10-20 09:10:00",
      "activated_at": "2026-10-20 09:10:00",
      "retired_at": "2026-10-28 10:30:00",
      "job_id": "job-upload-v1",
      "job_status": "completed",
      "error": null,
      "can_restore": false,
      "restore_block_code": "VECTOR_MISSING",
      "restore_block_reason": "보관된 벡터 데이터가 없어 복원할 수 없습니다."
    }
  ]
}
```

(지면상 v2·v1 행에서 `file_format` 등 일부 필드를 생략했다. 실제 응답에는 모든 행에 같은 필드가 있다.)

**목업 요소 ↔ 필드**

| 목업 요소 | 필드 |
|---|---|
| 헤더 굵은 글씨 “조립 공정 A” | `product_model` |
| 헤더 “· 제조 작업표준” | `collection_display_name` (`collection_name`은 내부 이름이므로 표시하지 않음) |
| `#historyFile` | `current_original_filename` |
| `.history-count` “최신순 · 총 N개 버전” | `total_versions` |
| 행 “v{n}” | `version_no` |
| 행 배지 | `is_active=true` → ‘현재 적용 중’(초록), 선택한 행 → ‘복원 대상 선택됨’(파랑, 로컬 상태), 그 외 → `status` 문구 |
| 행 파일명 | `original_filename` |
| 행 상세 “{날짜} 등록 · N페이지 · N청크 · N MB” | `created_at` · `total_pages` · `chunk_count` · `file_size`(byte → MB 변환은 화면) |
| 행 하단 사유 `.version-reason` | `restore_block_reason` (현재 적용 행은 표시하지 않음) |
| `#historyNotice` | 아래 “안내 문구” 참고 |

**필드 규칙**

| 필드 | 화면 처리 |
|---|---|
| `restore_supported` | 서버 기능 설정. false면 복원 기능 안내만 하고 하단 복원 버튼을 숨기거나 비활성화 |
| 최상위 `can_restore` | 현재 사용자·문서·작업 상태에서 복원 실행 가능 여부. 가능한 행이 반드시 있다는 뜻은 아님 |
| 행 `can_restore` | 행 선택 가능 여부. **최상위와 행이 모두 true일 때만 선택 가능** |
| 행 `restore_block_reason` | 불가 행 아래 표시. 문서 단위 사유(작업 중·기능 꺼짐)는 서버가 각 행에 복사해 준다 → 화면은 행 값만 표시하면 됨 |
| `next_version_no` | 확인창 “복원 후 새 파일을 등록하면 v{N}로 추가됩니다” |
| `activation_revision`, `current_version_no` | POST 본문에 그대로 전달 |
| `status`(행) | active=현재 적용 중, retired=이전 버전, building=처리 중, ready=전환 대기, failed=처리 실패 |
| `error`(행) | `status=failed`일 때 실패 사유(기존 필드) |

**안내 문구(`#historyNotice`)** — 최상위 `restore_block_code` 기준

| 조건 | 문구(목업 기준) |
|---|---|
| `JOB_IN_PROGRESS` | 최신본 변경 작업이 진행 중입니다. 완료 후 복원할 수 있습니다. (`pending_operation.operation_type=restore`면 “복원 작업이 진행 중입니다.”) |
| `FEATURE_DISABLED` 또는 `restore_supported=false` | 현재 적용 중인 버전만 검색과 질의응답에 사용됩니다. (복원 문구 없음) |
| 그 외 | 현재 적용 중인 버전만 RAG 검색·답변에 사용됩니다. 이전 버전 복원 시 검색 데이터와 출처도 함께 전환됩니다. |

- 목록은 버전 번호 내림차순. `total_versions`에는 처리 중·실패 버전도 포함된다.
- 현재 버전은 번호가 가장 큰 행이 아니라 `is_active=true` 행이다(복원 후에는 v1이 현재일 수 있음).
- v1이 불가여도 v2가 가능하면 v2는 선택할 수 있다.
- 응답을 새로 받거나 다른 문서로 바꿀 때 선택을 초기화한다.
- 상태: 요청 중 → loading(“버전 이력을 불러오는 중입니다.”), HTTP 오류 → 조회 실패 + ‘다시 불러오기’, `versions=[]` → “버전 이력이 없습니다.”

## 5. C·D 영역 — 선택과 확인, 복원 접수

행 선택 시 `#selectionSummary`에 “**v{current_version_no} → v{selectedVersionNo}** 복원 예정 · 확인 단계가 한 번 더 표시됩니다.”를 표시하고 `#restoreSelected`를 활성화한다. 유효한 선택 전에는 “복원할 이전 버전을 선택하세요.”와 비활성.

확인창(`#restoreBody`)은 같은 GET 응답만 사용한다.

| 확인창 항목 | 필드 |
|---|---|
| 현재 적용 v / 파일명 | `current_version_no` / `current_original_filename` |
| 복원할 버전 v / 파일명 | 선택 행 `version_no` / `original_filename` |
| “복원 후 새 파일을 등록하면 vN로 추가됩니다.” | `next_version_no` |

`POST /api/ingest/documents/{document_id}/versions/{version_no}/restore`

```json
{
  "expected_current_version_no": 3,
  "expected_activation_revision": 3,
  "idempotency_key": "16df778b-f257-4700-bf59-23f3a6dc9abb"
}
```

- 경로 `version_no` = 선택한 대상. 본문에 파일·벡터 데이터 없음.
- `idempotency_key`: ‘이 버전으로 복원’ 클릭 시 한 번 만드는 UUID(`crypto.randomUUID()`). 네트워크 재전송에는 같은 키·같은 본문.
- 클릭 즉시 버튼을 비활성화해 중복 클릭을 막는다.
- 서버 버전·적용 순번이 바뀌었으면 409. 예상값을 임의로 고쳐 자동 재실행하지 않는다.

접수 `202 Accepted`:

```json
{
  "job_id": "job-restore-demo",
  "operation_type": "restore",
  "status": "queued",
  "current_step": "queued",
  "document_id": "doc-demo",
  "from_version_no": 3,
  "target_version_no": 1
}
```

같은 키·같은 요청 재전송 → 같은 `job_id`. queued/running이면 202, 이미 completed/failed면 200. 두 경우 모두 `job_id`로 결과를 조회한다. 200만 보고 성공으로 판단하지 않는다.

## 6. E 영역 — 진행, 완료, 실패

`GET /api/ingest/jobs/{job_id}` — 기존 `status`(`queued/running/completed/failed`)·`result`·`error`·`error_code`를 유지하고 restore 작업에 필드를 추가한다.

```json
{
  "job_id": "job-restore-demo",
  "operation_type": "restore",
  "document_id": "doc-demo",
  "from_version_no": 3,
  "target_version_no": 1,
  "status": "running",
  "current_step": "snapshot",
  "result": null,
  "error": null,
  "error_code": null
}
```

**진행창 3줄 표시(목업 v0.2) ↔ `current_step`**

| `current_step` | 1줄 “복원 요청 접수” | 2줄 “v{target}의 검색 데이터와 원본 확인 중” | 3줄 “적용 버전 전환 대기” |
|---|---|---|---|
| `queued` | 진행 중 | 대기 | 대기 |
| `validate`, `snapshot` | ✓ | 진행 중 | 대기 |
| `activate` | ✓ | ✓ | 진행 중(“적용 버전 전환 중”) |
| `completed` | 성공 화면으로 전환 | | |

- 진행률 %는 없다. 2초 간격으로 조회하고, 오래 걸리거나 일시 장애가 나면 5초까지 늘린다. `completed/failed`에서 멈추고 화면을 떠나면 타이머를 정리한다.
- ‘닫고 계속하기’(`#backgroundRestore`)와 Esc는 창만 닫는다. 작업 취소가 아니다(취소 API 없음). 닫은 뒤에는 `#pageStatus`에 진행 상태를 표시하고 폴링을 계속한다.

완료:

```json
{
  "job_id": "job-restore-demo",
  "operation_type": "restore",
  "document_id": "doc-demo",
  "from_version_no": 3,
  "target_version_no": 1,
  "status": "completed",
  "current_step": "completed",
  "result": {
    "document_id": "doc-demo",
    "from_version_no": 3,
    "current_version_no": 1,
    "activation_revision": 4,
    "activation_id": 104,
    "activated_at": "2026-11-04 13:10:00",
    "activated_by": "admin-demo",
    "activated_by_name": "작업자",
    "original_filename": "조립작업표준_v1.xlsx",
    "total_pages": 14,
    "chunk_count": 98
  },
  "error": null,
  "error_code": null
}
```

| 성공 화면 항목 | 필드 |
|---|---|
| “현재 적용 버전이 v{n}으로 변경되었습니다.” | `result.current_version_no` |
| 파일명 / “N페이지 · N개 청크” | `result.original_filename` / `result.total_pages` · `result.chunk_count` |
| “실행자: …” | `result.activated_by_name` (NULL이면 `activated_by`) |

완료 시 A 목록·B 이력을 다시 조회하고, F 적용 이력을 이미 열었으면 함께 갱신한다. 현재 버전·파일명·페이지·최근 변경일은 재조회 결과로 바꾼다. 성공을 예측해 먼저 바꾸지 않는다. 창을 닫은 상태면 `#toast` “v{n} 복원 완료”와 `#pageStatus` 성공 문구.

실패:

```json
{
  "job_id": "job-restore-demo",
  "operation_type": "restore",
  "document_id": "doc-demo",
  "from_version_no": 3,
  "target_version_no": 1,
  "status": "failed",
  "current_step": "snapshot",
  "result": null,
  "error": "검색 데이터 확인 중 연결이 끊어졌습니다.",
  "error_code": "DEPENDENCY_UNAVAILABLE"
}
```

- 실패 화면에 `error`를 표시하고 목록·이력을 다시 조회한다. “현재 적용 버전은 vN으로 유지됩니다”의 N은 **재조회한 `version_no`** 를 쓴다(`from_version_no`를 그대로 쓰지 않는다).
- HTTP 타임아웃·폴링 장애는 작업 실패가 아니다. ‘상태 확인 중’으로 두고 재시도한다.
- ‘다시 시도’(`#retryRestore`): 최신 이력 조회 → 대상이 여전히 선택 가능한지 확인 → 확인창 → **새 키**로 POST. `/jobs/{job_id}/retry`는 restore에 쓰지 않는다(409).
- 창을 닫았으면 `#toast` “복원 실패 · 기존 버전 유지”와 `#pageStatus` 실패 문구, ‘버전 이력 확인’에서 최신 이력을 연다.

## 7. F 영역 — 적용 이력 보기

`GET /api/ingest/documents/{document_id}/activations?limit=20&before_activation_id={커서}`

- 처음 펼칠 때 호출. 다시 펼칠 때 같은 문서·같은 `activation_revision`이면 받은 데이터를 재사용해도 된다.
- `limit` 기본 20, 최대 100. 첫 호출은 커서 생략. 정렬은 최신순(`activation_id` 내림차순).
- 권한은 버전 이력 조회와 같다(문서를 볼 수 있으면 조회 가능, 아니면 404).

```json
{
  "document_id": "doc-demo",
  "activations": [
    {
      "activation_id": 104,
      "operation_type": "restore",
      "from_version_no": 3,
      "to_version_no": 1,
      "activation_revision": 4,
      "activated_by": "admin-demo",
      "activated_by_name": "작업자",
      "activated_at": "2026-11-04 13:10:00"
    },
    {
      "activation_id": 87,
      "operation_type": "replace",
      "from_version_no": 2,
      "to_version_no": 3,
      "activation_revision": 3,
      "activated_by": "demo",
      "activated_by_name": "데모",
      "activated_at": "2026-11-03 14:20:00"
    },
    {
      "activation_id": 12,
      "operation_type": "baseline",
      "from_version_no": null,
      "to_version_no": 2,
      "activation_revision": 1,
      "activated_by": null,
      "activated_by_name": null,
      "activated_at": "2026-10-28 10:30:00"
    }
  ],
  "next_before_activation_id": null
}
```

목업 한 줄 형식 “{activated_at} · {activated_by_name} · {문구}”:

| `operation_type` | 문구 |
|---|---|
| `restore` | v{from} → v{to} 복원 |
| `replace` | 새 버전 v{to} 적용 |
| `upload` | 최초 v{to} 적용 |
| `baseline` | v{to} 기준 상태 등록 (실행자 자리는 ‘시스템’. 실제 업로드 시각처럼 표시하지 않음) |

- `activated_by_name`이 NULL이면 `activated_by`, 둘 다 NULL이면 ‘시스템’.
- `next_before_activation_id`가 있으면 ‘더 보기’를 제공해 다음 페이지를 이어 붙인다(목업의 고정 3줄을 실제 누적 이력에 맞춘 보완).
- 기능 도입 전 기록은 `baseline` 한 건만 있다. 그 이전 업로드 이력은 없다.

## 8. 오류 응답과 화면 처리

신규 복원 API의 업무 오류는 FastAPI `detail` 안에 구조화한다. 기존 API의 문자열 `detail`, 요청 검증 오류의 배열 `detail`도 함께 처리해야 한다.

```json
{
  "detail": {
    "code": "STATE_CHANGED",
    "message": "현재 적용 버전이 변경되었습니다. 버전 이력을 다시 확인하세요."
  }
}
```

메시지 추출: `typeof detail === 'string'` → 그대로, 객체 → `detail.message`, 배열 → 첫 항목 `msg` 또는 일반 문구.

| HTTP / 코드 | 화면 처리 |
|---|---|
| 401 | 기존 로그인 만료 처리 |
| 404 (코드 없음) | 문서를 찾을 수 없거나 접근할 수 없음. 이력창 닫고 목록 갱신 |
| 404 / `VERSION_NOT_FOUND` | 선택한 버전이 없음. 선택 초기화 후 이력 재조회 |
| 403 / `FEATURE_DISABLED` | 기능 비활성 안내, 이력 재조회 |
| 409 / `STATE_CHANGED` | 선택 초기화 후 이력 재조회, 사용자 재확인 |
| 409 / `JOB_IN_PROGRESS` | 이력 재조회, `pending_operation` 확인, 중복 요청 금지 |
| 409 / `ALREADY_ACTIVE` | 이미 적용된 버전 안내, 목록·이력 갱신 |
| 409 / `IDEMPOTENCY_KEY_REUSED` | 키 재사용 오류. 자동으로 새 키를 만들어 실행하지 않음 |
| 409 / `RESTORE_RETRY_REQUIRES_NEW_REQUEST` | `/jobs/{id}/retry` 사용 오류. 최신 이력 기준 새 POST |
| 422 / `INVALID_REQUEST` | 요청 형식 오류(프런트엔드 버그). 일반 오류 문구 |
| 422 / `VERSION_NOT_RESTORABLE` | 정상 처리 이력이 없는 버전 |
| 422 / `PROFILE_UNKNOWN`, `MODEL_UNSUPPORTED` | 검색 모델 확인 불가 또는 미지원 안내 |
| 422 / `METADATA_MISSING` | 이전 버전 정보가 부족해 복원 불가 안내 |
| 422 / `VERIFICATION_REQUIRED` | 데이터 검증 대기 안내 |
| 422 / `VECTOR_MISSING`, `SOURCE_MISSING`, `RESOURCE_MISSING` | 누락 사유 표시. 재임베딩 버튼 없음 |
| 422 / `VECTOR_INTEGRITY_MISMATCH` | 검증 실패 안내 |
| 503 / `DEPENDENCY_UNAVAILABLE` | 일시 장애 안내. `job_id`를 이미 받았다면 작업 조회 지속 |
| 5xx (코드 없음) | 일반 오류. 이력 조회 실패면 ‘조회 실패’ 상태(빈 목록으로 표시하지 않음) |

- 422 계열 코드는 이력 GET의 행 `restore_block_code`와 같은 값이다. 보통은 GET 단계에서 행이 비활성화되어 POST까지 오지 않으며, GET 이후 상태가 바뀐 경우에만 POST에서 받는다.
- 사용자에게 내부 파일 경로·DB 오류·서버 주소를 보여주지 않는다(서버도 넣지 않는다).

## 9. 연동 체크리스트

1. 일반 사용자 계정으로 문서 관리 → 버전 이력 → 복원이 되는지, 볼 수 없는 문서는 404로 처리되는지 확인(2026-11-06 권한 변경, D-22).
2. 행 선택만으로 POST가 나가지 않고 `#selectionSummary`만 바뀐다.
3. 가능 행만 단일 선택, 한 행의 불가가 다른 정상 행을 막지 않는다.
4. 확인 클릭 한 번에 요청 한 번, 재전송 시 같은 멱등 키.
5. 진행 중 창 닫기·새로고침 후 `pending_operation`으로 폴링 재개.
6. 복원 진행 중 해당 문서 행의 [최신본 변경]·[삭제]가 비활성화된다.
7. 성공 시 목록·이력·열린 적용 이력 재조회, ‘최근 변경일’ 갱신 확인.
8. 실패·폴링 장애·응답 유실 구분. failed의 재시도는 새 확인·새 키.
9. 목업의 v4·실행자명·버전 개수·고정 시각·2.4초 자동 완료를 하드코딩하지 않는다.
10. loading·조회 실패·빈 목록·권한 없음·작업 중·벡터 없음·모델 미지원 상태 확인.
11. 기존 최신본 변경 흐름(`pending_job_id`·`pending_version_no`)이 그대로 동작한다.
12. 백엔드 구현 완료 전에는 목업으로만 확인하고, 완료 후 OpenAPI와 이 명세의 일치를 함께 검증한다.

## 10. 백엔드 구현 전 확정 대기 항목 (프런트엔드 참고)

아래는 백엔드 설계의 결정 대기 항목 중 화면에 영향이 있는 것이다. 확정되면 이 문서를 갱신한다.

- 1차 범위 포함 여부(D-18 변경) — 확정 전까지 기능은 기본 OFF(`restore_supported=false`).
- 기능 도입 전 이전 버전은 벡터가 이미 삭제되어 대부분 `VECTOR_MISSING`으로 표시될 수 있다. 실제 복원 가능한 버전은 기능 활성화 이후 등록된 버전부터다.
