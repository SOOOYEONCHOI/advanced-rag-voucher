# 문서 이전 버전 복원 — 프런트엔드 전달용 화면 영역별 API v1.0

- 작성일: 2026-11-05
- **대체됨: [v1.1](문서_이전버전_복원_화면영역별_API_명세_v1.1.md)을 전달한다.** 이 문서는 이력 보존용이다.
- 기준 목업: [admin_UI-12_이전버전복원_20261104_v0.2.html](mockups/admin_UI-12_이전버전복원_20261104_v0.2.html)
- 관련: UI-12 / SC-06 / R1-5
- 상태: 최종 개발 계약안. 신규 API·확장 필드는 백엔드 구현 후 사용 가능하다.
- 백엔드 내부 구현은 [백엔드 최종 설계](문서_이전버전_복원_백엔드_최종설계_v1.0.md)를 참고한다. 프런트엔드 담당자에게는 본 명세와 목업을 전달하면 된다.

## 1. 공통 규칙

- 모든 URL은 `/api` 기준이며 기존 `Authorization: Bearer <로그인 토큰>`을 사용한다.
- 이력 열람은 기존 문서 접근 권한, 복원 실행은 관리자 전용이다. 역할명만으로 버튼을 결정하지 말고 서버가 반환한 `can_restore`를 사용한다.
- 현재 프런트엔드는 관리자 `/admin` 진입을 다른 페이지로 이동시킨다. 관리자용 문서 관리 진입 경로 연결은 프런트엔드 담당 범위다. 일반 사용자 권한으로 복원을 허용하는 계약이 아니다.
- 버전 번호는 정수, 파일 크기는 byte, 시간 필드는 기존 API와 같은 KST 표시 문자열 `YYYY-MM-DD HH:mm:ss` 또는 NULL이다. UTC로 다시 변환하지 않는다.
- 예시 ID·파일명·시각은 샘플이다. 실제 값은 응답을 사용한다.
- 기존 API의 필드는 유지하고 추가 필드로 확장한다. 아래 예시는 화면 연결에 필요한 필드 중심이다.
- `null`, 빈 배열, 실패 응답을 구분한다. 실패를 ‘이력 없음’으로 표시하지 않는다.
- 목업의 우측 ‘목업 미리보기’와 상태·권한·성공/실패 선택기는 개발 확인용이며 실제 제품에 구현하지 않는다.

## 2. 화면 영역과 API 매핑

| 영역 | 목업 요소 | 이벤트 | API / 처리 |
|---|---|---|---|
| A. 문서 목록 | `#currentBadge`, `#docFile`, `#docPages`, `#updatedAt`, `#pageStatus` | 최초 진입·새로고침·복원 완료 | GET `/ingest/documents` |
| B. 버전 이력 헤더·목록 | `#historyFile`, `#historyNotice`, `#versions`, `.history-count` | ‘버전 이력’ 클릭 | GET `/ingest/documents/{document_id}/versions` |
| C. 버전 선택·하단 | `.version-option`, `#selectionSummary`, `#restoreSelected` | 행 선택 / 선택 버전 복원 | 로컬 단일 선택, API 호출 없음 |
| D. 복원 확인 | `#restoreOverlay`, `#restoreBody`, `#confirmRestore` | 마지막 ‘이 버전으로 복원’ | POST `/ingest/documents/{document_id}/versions/{version_no}/restore` |
| E. 복원 진행·결과 | `#restoreTitle`, `#backgroundRestore`, `#completeRestore`, `#retryRestore`, `#toast` | 접수 후 상태 확인 | GET `/ingest/jobs/{job_id}` |
| F. 적용 이력 | `details`, `#activationLog` | ‘적용 이력 보기’ 펼치기 | GET `/ingest/documents/{document_id}/activations` |

하단 선택은 `selectedVersionNo` 하나만 보관한다. 행을 눌러도 즉시 복원하지 않는다. 확인창의 취소는 서버 요청이 없으므로 작업 취소 API가 필요 없다.

## 3. A 영역 — 문서 목록

`GET /api/ingest/documents?collection_name={기존 필터값}`

기존 목록·필터를 그대로 사용한다. 각 문서에 아래 필드를 추가한다.

```json
{
  "documents": [
    {
      "document_id": "doc-demo",
      "product_model": "조립 공정 A",
      "filename": "조립작업표준_v3.xlsx",
      "version_no": 3,
      "total_pages": 18,
      "chunk_count": 126,
      "updated_at": "2026-11-03 14:20:00",
      "activation_revision": 3,
      "pending_operation": null
    }
  ],
  "total": 1
}
```

`pending_operation`이 있으면 해당 문서의 최신본 변경·삭제·복원을 잠그고 작업 상태 조회를 재개한다.

```json
{
  "job_id": "job-restore-demo",
  "operation_type": "restore",
  "status": "running",
  "current_step": "snapshot",
  "target_version_no": 1
}
```

- 작업 유형은 `replace / restore`다. 기존 `pending_job_id`, `pending_version_no`는 기존 업로드 호환용으로 유지하되 복원 판정은 `pending_operation`을 사용한다.
- pending은 점유 상태이므로 `queued/running`에서만 반환한다. 완료·실패 뒤에는 NULL이다.
- 화면 새로고침 후 목록의 pending 작업이 있으면 작업 조회를 다시 시작한다. 별도 localStorage 저장은 필수가 아니다.

## 4. B 영역 — 버전 이력 조회

`GET /api/ingest/documents/{document_id}/versions`

```json
{
  "document_id": "doc-demo",
  "product_model": "조립 공정 A",
  "collection_name": "제조 작업표준",
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
      "created_at": "2026-11-03 14:20:00",
      "activated_at": "2026-11-03 14:20:00",
      "retired_at": null,
      "uploaded_by": "demo",
      "processing_engine": "excel_ingest",
      "total_pages": 18,
      "chunk_count": 126,
      "file_size": 2800000,
      "can_restore": false,
      "restore_block_code": "ALREADY_ACTIVE",
      "restore_block_reason": "현재 적용 중인 버전입니다."
    },
    {
      "version_no": 2,
      "status": "retired",
      "is_active": false,
      "original_filename": "조립작업표준_v2.xlsx",
      "created_at": "2026-10-28 10:30:00",
      "activated_at": "2026-10-28 10:30:00",
      "retired_at": "2026-11-03 14:20:00",
      "uploaded_by": "demo",
      "processing_engine": "excel_ingest",
      "total_pages": 16,
      "chunk_count": 112,
      "file_size": 2500000,
      "can_restore": true,
      "restore_block_code": null,
      "restore_block_reason": null
    },
    {
      "version_no": 1,
      "status": "retired",
      "is_active": false,
      "original_filename": "조립작업표준_v1.xlsx",
      "created_at": "2026-10-20 09:10:00",
      "activated_at": "2026-10-20 09:10:00",
      "retired_at": "2026-10-28 10:30:00",
      "uploaded_by": "demo",
      "processing_engine": "excel_ingest",
      "total_pages": 14,
      "chunk_count": 98,
      "file_size": 2100000,
      "can_restore": false,
      "restore_block_code": "VECTOR_MISSING",
      "restore_block_reason": "보관된 벡터 데이터가 없어 복원할 수 없습니다."
    }
  ]
}
```

| 필드 | 화면 처리 |
|---|---|
| `restore_supported` | 서버 기능 설정. false면 복원 기능 사용 불가 안내 |
| 최상위 `can_restore` | 현재 사용자·문서·작업 상태에서 복원 실행 가능 여부. 가능한 행이 반드시 있다는 의미는 아님 |
| 행의 `can_restore` | 개별 버전 선택 가능 여부. 최상위와 행이 모두 true일 때 선택 가능 |
| `restore_block_reason` | 불가 행 하단 또는 문서 전체 안내에 표시 |
| `total_versions` | ‘최신순 · 총 N개 버전’ |
| `next_version_no` | 확인창의 ‘복원 후 새 파일을 등록하면 vN로 추가됩니다’ |
| `activation_revision` | 조회 당시 적용 순번. POST 본문에 그대로 전달 |

- 목록은 서버에서 버전 번호 내림차순으로 반환한다. 총 개수에는 처리 중·실패 버전도 포함한다.
- 현재 버전은 번호가 가장 큰 행이 아니라 `is_active=true`인 행이다.
- 상태 문구: active=현재 적용 중, retired=이전 버전, building=처리 중, ready=전환 대기, failed=처리 실패.
- 같은 응답에서 v1이 불가여도 v2가 가능하면 v2는 선택할 수 있다.
- 응답이 새로 반영될 때 선택을 초기화한다. 다른 문서로 변경할 때도 초기화한다.
- `versions=[]`면 빈 상태, HTTP 오류면 조회 실패 상태, 요청 중이면 loading 상태를 표시한다.

## 5. C·D 영역 — 선택과 확인, 복원 접수

행 선택 시 하단에 `v{current_version_no} → v{selected_version_no}`를 표시한다. 하단 버튼은 유효한 선택 전까지 disabled다. 확인창은 같은 GET 응답의 현재·선택 버전 파일명과 `next_version_no`를 이용한다.

`POST /api/ingest/documents/{document_id}/versions/{version_no}/restore`

```json
{
  "expected_current_version_no": 3,
  "expected_activation_revision": 3,
  "idempotency_key": "16df778b-f257-4700-bf59-23f3a6dc9abb"
}
```

- 경로의 version_no는 선택한 대상이다. 본문에는 파일이나 벡터 데이터를 넣지 않는다.
- idempotency_key는 최종 실행 클릭 시 한 번 생성한 UUID 문자열이다. 단순 네트워크 재전송에서는 같은 키·같은 본문을 사용한다.
- 서버의 버전·적용 순번이 바뀌었으면 409로 거절한다. 클라이언트가 임의로 예상값을 수정해 자동 재실행하지 않는다.

최초 접수 `202 Accepted`:

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

동일 요청을 같은 키로 재전송하면 동일 job_id를 반환한다. queued/running이면 202, completed/failed인 기존 작업이면 200을 반환한다. 두 응답 모두 job_id로 결과 조회를 이어간다. 200만 보고 성공 완료로 판단하지 않는다.

## 6. E 영역 — 진행, 완료, 실패

`GET /api/ingest/jobs/{job_id}`

기존 작업 상태값 `queued / running / completed / failed`와 기존 `result/error/error_code`를 유지한다. restore 작업에는 아래 정보를 추가한다.

진행 예시:

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

| 단계 | 진행창 문구 |
|---|---|
| queued | 복원 요청 접수 |
| validate | 권한과 버전 상태 확인 중 |
| snapshot | 선택 버전의 검색 데이터와 원본 확인 중 |
| activate | 적용 버전 전환 중 |
| completed | 복원 완료 |

진행률 %는 제공하지 않는다. 처음 2초 간격으로 조회하고 장기 대기·일시 장애 시 5초까지 늘릴 수 있다. completed/failed에서 중단하고 화면을 떠날 때 타이머를 정리한다. 창 닫기와 작업 취소는 다르며 취소 API는 이번 범위에 없다.

완료 예시:

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
    "original_filename": "조립작업표준_v1.xlsx",
    "total_pages": 14,
    "chunk_count": 98
  },
  "error": null,
  "error_code": null
}
```

완료 시 목록 A와 버전 이력 B를 다시 조회하고, 적용 이력 F를 이미 열었다면 함께 갱신한다. 서버 재조회 결과로 현재 버전·파일명·페이지·최근 변경일을 바꾼다. 클라이언트에서 성공을 예측해 번호를 먼저 변경하지 않는다.

실패 예시:

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

- 실패 문구는 error를 표시하고 목록·이력을 다시 조회한다. 해당 작업이 기존 버전을 유지했다는 것과 현재도 그 버전이라는 것은 다를 수 있으므로 현재 번호는 재조회한다.
- HTTP 타임아웃이나 폴링 장애는 작업 실패를 의미하지 않는다. ‘상태 확인 중’으로 두고 조회를 재시도한다.
- failed 후 ‘다시 시도’는 최신 이력 조회 → 대상 재선택 또는 유효성 재확인 → 확인창 → 새 키로 POST 순서다. 기존 `/jobs/{job_id}/retry`는 restore에 사용하지 않는다.
- 창을 닫았으면 목록 pending 상태와 완료 토스트로 알리고, ‘버전 이력 확인’에서 최신 이력을 연다.

## 7. F 영역 — 적용 이력 보기

`GET /api/ingest/documents/{document_id}/activations?limit=20&before_activation_id={이전 응답 커서}`

- 처음 펼칠 때 호출한다. 닫았다 다시 펼칠 때 같은 문서·적용 순번이면 이미 받은 데이터를 재사용할 수 있다.
- limit 기본 20, 최대 100. 커서는 첫 호출에 생략한다. 정렬은 activation_id 내림차순이다.

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
      "activated_at": "2026-11-04 13:10:00"
    }
  ],
  "next_before_activation_id": null
}
```

restore=`v3 → v1 복원`, upload=`새 버전 vN 적용`(from이 NULL이면 최초 적용), baseline=`vN 기준 상태 등록`으로 표시한다. baseline을 과거 실제 업로드 시각처럼 표시하지 않는다. 다음 커서가 있으면 ‘더 보기’를 제공한다. 더 보기는 목업의 정적 3행을 실제 누적 이력에 맞춘 연동 보완이다.

## 8. 오류 응답과 화면 처리

신규 복원 API의 업무 오류는 기존 FastAPI detail 필드 안에 구조화한다. 기존 공통 HTTP 오류 문자열도 계속 처리할 수 있어야 한다.

```json
{
  "detail": {
    "code": "STATE_CHANGED",
    "message": "현재 적용 버전이 변경되었습니다. 버전 이력을 다시 확인하세요."
  }
}
```

| HTTP / 코드 | 화면 처리 |
|---|---|
| 401 | 기존 로그인 만료 처리 |
| 404 | 문서를 찾을 수 없거나 접근할 수 없음. 이력창 닫고 목록 갱신 |
| 403 / ADMIN_REQUIRED | 권한 안내, 복원 중단 |
| 403 / FEATURE_DISABLED | 기능 비활성 안내, 이력 재조회 |
| 409 / STATE_CHANGED | 선택 초기화 후 이력 재조회, 사용자 재확인 |
| 409 / JOB_IN_PROGRESS | 이력 재조회, pending 작업 확인, 중복 요청 금지 |
| 409 / ALREADY_ACTIVE | 이미 적용된 버전 안내, 목록·이력 갱신 |
| 409 / IDEMPOTENCY_KEY_REUSED | 잘못 재사용한 키. 자동으로 새 키를 만들어 실행하지 않음 |
| 409 / RESTORE_RETRY_REQUIRES_NEW_REQUEST | 기존 job retry 사용 오류. 최신 이력 기준 새 POST 사용 |
| 422 / VERSION_NOT_RESTORABLE | 대상 정상 처리 이력 없음 |
| 422 / PROFILE_UNKNOWN, MODEL_UNSUPPORTED | 검색 모델 확인 불가 또는 미지원 안내 |
| 422 / VERIFICATION_REQUIRED | 데이터 검증 대기 안내 |
| 422 / VECTOR_MISSING, SOURCE_MISSING, RESOURCE_MISSING | 누락 사유 표시, 임의 재임베딩 버튼 없음 |
| 422 / VECTOR_INTEGRITY_MISMATCH | 검증 실패 안내 |
| 503 / DEPENDENCY_UNAVAILABLE | 일시 장애 안내. job_id를 이미 받았다면 작업 조회 지속 |

FastAPI 요청 검증 오류의 detail은 배열일 수 있다. 메시지 추출은 문자열·구조화 객체·배열을 구분한다. 사용자가 보는 오류에 내부 파일 경로·DB 오류·모델 서비스 주소를 표시하지 않는다.

## 9. 연동 체크리스트

1. 관리자 화면 진입과 일반 사용자 조회 경로를 확인한다.
2. 행 선택만으로 POST가 호출되지 않고 하단 선택 요약이 바뀐다.
3. 가능 행만 단일 선택할 수 있고 특정 행의 불가가 다른 정상 행까지 막지 않는다.
4. 마지막 확인 클릭 한 번에 요청 한 번, 네트워크 재전송 시 같은 멱등 키를 사용한다.
5. 진행 중 창 닫기·새로고침 후 pending 작업에서 조회를 이어간다.
6. 성공 시 목록·이력·열려 있는 적용 이력을 다시 조회한다.
7. 실패·폴링 장애·응답 유실을 구분한다. failed의 재시도는 새 확인과 새 요청이다.
8. 목업의 v4·관리자명·버전 개수·고정 시각·자동 완료 시간을 하드코딩하지 않는다.
9. loading·조회 실패·빈 목록·권한 없음·작업 중·벡터 없음·모델 미지원 상태를 확인한다.
10. 접수된 작업과 실제 DB 데이터가 없는 동안에는 목업으로만 확인하고, 구현 완료 후 OpenAPI와 이 계약의 일치를 공동 검증한다.
