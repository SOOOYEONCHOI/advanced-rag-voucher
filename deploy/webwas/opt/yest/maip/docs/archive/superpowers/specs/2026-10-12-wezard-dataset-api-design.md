# Wezard 스냅샷 연동 API 설계

- 날짜: 2026-10-12
- 상태: 사용자 승인(2026-10-12)
- 계획: [../plans/2026-10-12-wezard-dataset-api.md](../plans/2026-10-12-wezard-dataset-api.md)

## 목적

검수를 마친 이미지로 만든 스냅샷(zip)을 **Wezard**(GPU·학습 플랫폼)가 가져가 데이터셋을 만들고 모델을 학습한다.
Wezard 개발을 맡은 AI 에이전트가 **문서 하나만 읽고** 스냅샷 목록을 보고, 정보를 확인하고, zip 을 받아 검증할 수 있게 한다.

지금은 zip 을 화면 세션(`/media/export/<id>/`)으로만 받을 수 있다.

## 사용자 결정(2026-10-12)

| 항목 | 결정 |
|---|---|
| 인증 | **전용 키 테이블** `IntegrationClient`. 비전검사 클라이언트 키(`VisionClient`)와 섞지 않는다 |
| 키 관리 | **관리 화면** "외부 연동 키"(`wm_integration_client`, 시스템 관리 · 플랫폼 관리자 전용) |
| 열람 범위 | 키 하나로 **전체 검사항목**의 스냅샷 |
| 경로 | `/api/v1/datasets/...` — `/api/v1` 의 인증 헤더·봉투·오류 형식을 그대로 쓴다 |
| 문서 | `docs/Wezard/maip-api.md` 를 정본으로 새로 둔다. 클라이언트 계약 문서에는 "이 경로는 비전검사 클라이언트용이 아님" 한 줄만 |

## 구성

### 1. 인증 — `IntegrationClient`

- 테이블 `integration_client`: `client_id`(unique) · `name` · `api_key_hash`(SHA-256) · `active` · `last_seen_at` · 생성·수정 시각.
  조직 소유 테이블이 아니다(VisionClient 와 같다 — RLS 대상 아님).
- 헤더는 `/api/v1` 과 같은 `X-Client-ID` + `X-API-Key`. **대조 테이블만 다르다.**
  `ClientApiView` 에 `client_model`·`client_attr` 클래스 속성을 두어 인증 코드를 그대로 쓴다.
  - 연동 키로 `/api/v1/inspections` → 401 `AUTH_INVALID`
  - 검사 키로 `/api/v1/datasets/...` → 401 `AUTH_INVALID`

### 2. 관리 화면 — "외부 연동 키"

- 클라이언트 관리(`vision/client.html`)를 본뜬다: 목록 · 등록 · 수정(이름·사용) · 키 재발급 · 삭제. 키는 발급 응답에서 한 번만 보인다.
- 서비스 계정은 만들지 않는다(연동 키는 데이터를 올리지 않는다). 삭제 제한도 없다.
- `/api/system/integration_client` — 플랫폼 관리자가 아니면 `PermissionDenied`(403).
- 등록 지점: `domain/gui.py`(화면·API 매핑) · `seed_initial.MENU_TREE`(시스템 관리) · `PLATFORM_ADMIN_MENU_CODES`.

### 3. API

모두 GET, 성공 `{"data": ...}` / 실패 `{"error": {"code","message","retryable"}}`, 시각은 UTC `Z`.
기준 Export 는 **스냅샷마다 가장 최근 ExportJob** 이다(스냅샷 관리 화면과 같다).

| 경로 | 내용 |
|---|---|
| `GET /api/v1/datasets/snapshots` | 목록. `item_code`·`task_type`·`status`(최근 Export 상태)·`created_after`(ISO 8601) 필터, `page`·`page_size`(기본 50, 최대 200). 최신순 |
| `GET /api/v1/datasets/snapshots/{id}` | 정보. 목록 행 + 제외 이미지 수, 분포 통계(스냅샷 상세 화면의 `_analyze_manifest` 그대로), 실패 사유 |
| `GET /api/v1/datasets/snapshots/{id}/download` | zip. 단일 Range 이어받기(206/416), 운영은 nginx 전송 |

목록 행:

```json
{"id": 12, "version_tag": "v3.0", "created_at": "2026-10-12T01:23:45Z",
 "item": {"id": 604, "code": "FAN-PANEL", "name": "산업용 냉각팬 패널 단면 검사", "task_type": "ANOMALY_DETECTION"},
 "image_count": 20,
 "export": {"status": "COMPLETED", "format": "MVTEC", "format_label": "MVTec AD",
            "size_bytes": 1234567, "sha256": "…", "completed_at": "…Z",
            "download_url": "/api/v1/datasets/snapshots/12/download"}}
```

오류 코드:

| 상황 | 상태 | code | retryable |
|---|---|---|---|
| 헤더 없음 / 키 틀림 | 401 | `AUTH_REQUIRED` / `AUTH_INVALID` | false |
| 쿼리 값이 틀림 | 400 | `INVALID_PARAMETER` | false |
| 스냅샷 없음 | 404 | `SNAPSHOT_NOT_FOUND` | false |
| Export 가 대기·생성 중 | 409 | `EXPORT_NOT_READY` | true |
| Export 실패 | 409 | `EXPORT_FAILED` | false |
| DB 행은 있는데 파일이 없음 | 404 | `EXPORT_FILE_NOT_FOUND` | false |
| 범위가 파일 밖 | 416 | `RANGE_NOT_SATISFIABLE` | false |

받기를 시작할 때(전체 요청 또는 Range 시작이 0) 감사 로그 `SNAPSHOT_DOWNLOADED`(payload: 스냅샷·Export id, `client_id`)를 남긴다.
이어받기 조각마다 남기지 않는다.

### 4. 받은 파일 검증 — `ExportJob.file_size`·`file_sha256`

- 새 zip: `ExportService.run` 이 임시 파일을 저장하기 전에 크기와 SHA-256 을 계산해 함께 저장한다.
- 예전 zip(값이 비어 있음): 정보 API·다운로드 API 가 처음 부를 때 한 번 계산해 저장한다. 목록은 계산하지 않는다(비어 있으면 `null`).
- 마이그레이션은 `IntegrationClient` 와 묶어 `0002` 하나.

### 5. 문서

- 새 정본 `docs/Wezard/maip-api.md`: 인증, API 3개(요청·응답 예), 오류·재시도, 이어받기와 SHA-256 검증, zip 구조(ImageFolder / COCO / MVTec AD + `metadata.json`, 공통 `manifest.json`), 권장 수집 절차.
- 함께 고침: `docs/README.md`(문서 지도), `client/SERVER_API_CONTRACT.md`(한 줄), `DECISIONS.md`(DEC-029), `ARCHITECTURE.md`(API 규약 표), `FEATURES.md`, `DATA_MODEL.md`, `STATUS.md`, `AGENTS.md` [2] 표.

## 빼는 것

- 웹훅(완료 알림): Wezard 가 목록을 주기적으로 본다. 필요해지면 더한다.
- 키별 검사항목 범위: 결정대로 전체. 필요해지면 연결 테이블을 더한다.
- 예전 zip 일괄 해시 계산 명령: 처음 조회할 때 채운다.

## 검증

- 단위: 인증 두 방향, 목록 필터·페이징·잘못된 값, 정보의 통계·지연 해시, 다운로드 200/206/404/409/416, 감사 로그, Export 시 크기·SHA-256 저장, 관리 API(발급·해시만 저장·재발급·삭제·비관리자 403).
- e2e: 관리 화면에서 등록 → 키 모달 → 삭제.
- 실측: 발급한 키로 `curl` 목록 → 정보 → 받기, `sha256sum` 대조, `curl -C -` 이어받기.
