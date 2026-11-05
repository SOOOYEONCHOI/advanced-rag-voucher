# 제조AI플랫폼(MAIP) API — 스냅샷 목록·정보·다운로드

> 방향 ①(Wezard → 제조AI플랫폼) 계약의 정본입니다. 제조AI플랫폼이 관리합니다.
> 공통 규칙(인증·요청 추적·오류·재시도·페이지·시각·전송 형식)은 [통신 규약 v1](integration-protocol.md)에 있고, 이 문서는 엔드포인트만 적습니다.

## 접속 정보

| 항목 | 값 |
| --- | --- |
| Base URL | `http://10.10.10.20:8123` — 개발 서버(사내망, HTTP). 운영 주소는 정해지면 고쳐 전달합니다 |
| API 키 | 따로 전달합니다(`maip_…`). 환경 변수 `MAIP_API_KEY`에만 둡니다 |

```bash
export MAIP_BASE_URL=http://10.10.10.20:8123
export MAIP_API_KEY='<따로 받은 API 키>'

# 연결 확인 — 200 과 {"data": {"items": [...]}} 가 나오면 됩니다
curl -s -H "X-API-Key: $MAIP_API_KEY" "$MAIP_BASE_URL/api/v1/datasets/snapshots?limit=1"
```

## 1. 한눈에 보기

스냅샷은 검수 승인된 이미지를 한 시점에 고정한 학습 데이터 묶음이고, 만들면 바뀌지 않습니다. 스냅샷마다 `wezard-dataset/v1` zip 이 만들어집니다(규약 §9-2).

| 목적 | 호출 |
| --- | --- |
| 스냅샷 목록(필터·페이지) | `GET /api/v1/datasets/snapshots?status=COMPLETED` |
| 스냅샷 정보(크기·SHA-256·분포 통계·실패 사유) | `GET /api/v1/datasets/snapshots/{id}` |
| zip 받기(이어받기 지원) | `GET /api/v1/datasets/snapshots/{id}/download` |

권장 순서:

1. `status=COMPLETED` 목록을 끝까지 받고, 이미 가져온 스냅샷은 `external_ref`(`maip:<코드>:<버전>#<id>`)로 거릅니다.
2. 정보에서 `sha256`·`size_bytes`를 받습니다.
3. zip 을 받고(끊기면 `Range`로 이어받기) SHA-256 을 비교합니다. 다르면 지우고 다시 받습니다.
4. 같으면 zip 을 그대로 데이터셋 생성에 넘깁니다 — `Idempotency-Key: maip-snapshot-<id>`, `source = "maip"`.

## 2. 공통 규칙

| 항목 | 내용 |
| --- | --- |
| 인증 | 헤더 `X-API-Key` 하나(규약 §3). 없거나 틀리면 `401` |
| 요청 ID | `X-Request-ID`(1~64자 `[A-Za-z0-9._-]`)를 응답 헤더와 오류 본문 `request_id`로 돌려줍니다(규약 §4). 없는 경로의 404 도 같습니다 |
| 성공 본문 | `{"data": ...}` |
| 시각 | ISO 8601, UTC(`Z`) |
| 목록 페이지 | `limit`(1~200, 기본 50), `offset`(기본 0). 응답 `data`에 `items`, `total`, `limit`, `offset` |
| 사용 범위 | 이 키로는 비전검사 클라이언트용 API(`/api/v1/catalog` 등)를 부를 수 없습니다(`401`) |

## 3. 스냅샷 목록 — `GET /api/v1/datasets/snapshots`

쿼리 파라미터(모두 선택):

| 이름 | 값 | 설명 |
| --- | --- | --- |
| `item_code` | 문자열 | 검사항목 코드가 정확히 같은 것만 |
| `task_type` | `CLASSIFICATION` / `OBJECT_DETECTION` / `ANOMALY_DETECTION` | 검사 유형(규약 §9-1) |
| `status` | `QUEUED` / `RUNNING` / `COMPLETED` / `FAILED` | Wezard 형식 zip 의 상태. 받을 것만 보려면 `COMPLETED` |
| `created_after` | ISO 8601 + 시간대 | 이 시각 이후에 만든 것만(같은 시각은 빠집니다) |
| `limit`, `offset` | 정수 | 페이지 |

정렬은 생성 시각 최신순입니다. 값이 틀리면 `400 INVALID_PARAMETER`입니다.

응답 `200`:

```json
{
  "data": {
    "items": [
      {
        "id": 91,
        "version_tag": "v1.0",
        "created_at": "2026-10-12T04:04:46.733991Z",
        "item": {"id": 604, "code": "FAN-PANEL", "name": "냉각팬 패널 단면(이상탐지)", "task_type": "ANOMALY_DETECTION"},
        "image_count": 18,
        "export": {
          "status": "COMPLETED",
          "format": "WEZARD",
          "format_label": "Wezard 학습 데이터셋",
          "size_bytes": 30037042,
          "sha256": "753b63d708e4af1c4a6dfe3ded92b295a5dde7b7c2f64c7d9eebc39ce50ad7c4",
          "completed_at": "2026-10-12T04:04:48.847196Z",
          "download_url": "/api/v1/datasets/snapshots/91/download"
        }
      }
    ],
    "total": 1,
    "limit": 5,
    "offset": 0
  }
}
```

| 필드 | 설명 |
| --- | --- |
| `id` | 스냅샷 ID. 다시 쓰이지 않습니다 |
| `version_tag` | 검사항목 안의 버전(`v1.0`, `v2.0` …) |
| `item` | 검사항목. `code`는 1~50자 `[A-Z0-9-]`(규약 §10) |
| `image_count` | 담긴 이미지 수 |
| `export` | 최근 Wezard 형식 zip. 없으면 `null` |
| `export.status` | `QUEUED` / `RUNNING` / `COMPLETED` / `FAILED`(사유는 §4 `error_message`) |
| `export.size_bytes`, `export.sha256` | zip 크기와 SHA-256(소문자 hex). `COMPLETED`일 때만 |
| `export.download_url` | 받을 경로(Base URL 뒤에 붙입니다). `COMPLETED`일 때만, 아니면 `null` |

## 4. 스냅샷 정보 — `GET /api/v1/datasets/snapshots/{id}`

목록 항목과 같은 필드에 아래를 더한 객체 하나입니다. 받기 전에 불러 `sha256`을 확보합니다.

| 추가 필드 | 설명 |
| --- | --- |
| `export.error_message` | `FAILED`일 때 사유(한국어), 아니면 `null`. Wezard 최소 조건 미달이면 여기에 나옵니다 |
| `excluded_image_count` | 검수 승인이 아니어서 빠진 이미지 수(참고용) |
| `statistics` | 내용 분포(아래) |

| `statistics` 필드 | 유형 | 설명 |
| --- | --- | --- |
| `image_count`, `annotation_count` | 공통 | 이미지 수, 주석 수 |
| `annotated_image_count`, `unannotated_image_count` | 공통 | 주석이 있는/없는 이미지 수 |
| `class_distribution` | 공통 | `[[라벨 이름, 주석 수], ...]` 많은 순 |
| `geometry_distribution` | 공통 | `{"BBOX": n, "POLYGON": n, "CLASSIFICATION": n}` 처럼 주석의 `geometry_type` 별 수 — 분류 라벨(도형 없는 주석)은 `CLASSIFICATION` |
| `class_image_distribution`, `unlabeled_image_count`, `imbalance_warning` | 분류 | 이미지당 라벨 분포, 라벨 없는 이미지 수, 한 클래스가 80% 이상이면 `true` |
| `normal_image_count`, `anomaly_image_count`, `anomaly_type_distribution` | 이상 탐지 | 정상 수, 이상 수(결함 Polygon 이 있는 이미지), `[[결함 유형, 수], ...]`(여러 유형이면 `combined`) |

`FAILED`의 `error_message` 예:

```text
Wezard 학습 조건: 학습용 이미지가 10장 이상이어야 합니다(지금 2장, 전체 2장 중). / Wezard 학습 조건: 검증용 이미지가 1장 이상이어야 합니다.
```

## 5. zip 받기 — `GET /api/v1/datasets/snapshots/{id}/download`

- 전체: `200`, `Content-Length`, `Accept-Ranges: bytes`.
- 이어받기: `Range: bytes=<시작>-` → `206`, `Content-Range: bytes <시작>-<끝>/<전체>`. 단일 범위만 지원합니다. 파일 밖이면 `416`.
- 파일 이름(`Content-Disposition`): `snapshot-{id}-{version_tag}-wezard.zip`.
- 받은 뒤 SHA-256 을 §4 `export.sha256`과 비교합니다. 다르면 지우고 처음부터 다시 받습니다.

```bash
curl -fSL -C - -H "X-API-Key: $MAIP_API_KEY" -H "X-Request-ID: wz-dl-91" \
  -o snapshot-91.zip "$MAIP_BASE_URL/api/v1/datasets/snapshots/91/download"
```

## 6. zip 내용 — `wezard-dataset/v1`

변환 규칙과 `meta` 구조는 [규약 §9-2](integration-protocol.md)에 있습니다.

```text
dataset.json            "format": "wezard-dataset/v1" (split 없음)
images/<sha256>.png     이미지(원본 확장자, PNG·JPEG)
masks/<sha256>.png      이상 탐지의 defect 이미지
manifest.json           제조AI플랫폼 Export 기록(Wezard 는 쓰지 않습니다)
```

`dataset.json`(일부):

```json
{
  "format": "wezard-dataset/v1",
  "task_type": "anomaly",
  "classes": ["good", "defect"],
  "items": [
    {"file": "images/a11d….png", "label": "good"},
    {"file": "images/b80c….png", "label": "defect", "mask": "masks/b80c….png"}
  ],
  "meta": {"source": "maip", "external_ref": "maip:FAN-PANEL:v1.0#91", "maip": {"snapshot_id": 91, "…": "…"}}
}
```

## 7. 오류 코드

```json
{"error": {"code": "AUTH_REQUIRED", "message": "인증에 실패했습니다.", "retryable": false}, "request_id": "wz-err-1"}
```

HTTP 상태, `error.code`, `error.retryable`, `request_id`만 읽습니다. `retryable`이 `true`일 때만 자동 재시도합니다(규약 §5·§6).

| HTTP | `error.code` | 상황 | `retryable` | 호출 측 처리 |
| --- | --- | --- | --- | --- |
| 401 | `AUTH_REQUIRED` | `X-API-Key`가 없음 | false | 헤더를 붙입니다 |
| 401 | `AUTH_INVALID` | 키가 틀렸거나 폐기됨 | false | 제조AI플랫폼에 키 확인을 요청합니다 |
| 400 | `INVALID_PARAMETER` | 쿼리 값이 틀림 | false | 요청을 고칩니다 |
| 404 | `SNAPSHOT_NOT_FOUND` | 스냅샷이 없음 | false | 건너뜁니다 |
| 409 | `EXPORT_NOT_READY` | zip 이 없거나 대기·생성 중 | **true** | 60초 이상 간격으로 다시 봅니다 |
| 409 | `EXPORT_FAILED` | zip 을 만들지 못함(최소 조건 미달 등) | false | 건너뜁니다. 사유는 §4 `export.error_message` |
| 404 | `EXPORT_FILE_NOT_FOUND` | 기록은 있는데 파일이 없음 | false | 제조AI플랫폼에 알립니다 |
| 416 | `RANGE_NOT_SATISFIABLE` | `Range`가 파일 밖 | false | 받던 파일을 지우고 처음부터 받습니다 |
| 404 | `NOT_FOUND` | 없는 경로 | false | 경로를 고칩니다 |
| 405 | `METHOD_NOT_ALLOWED` | GET 이 아닌 메서드(`HEAD` 포함) | false | GET 으로 부릅니다 |
| 500 | `INTERNAL_ERROR` | 서버 오류 | **true** | 규약 §6 백오프로 재시도합니다 |

## 8. 변경 이력

| 날짜 | 내용 |
| --- | --- |
| 2026-10-12 | 최초 — 목록·정보·다운로드, 통신 규약 v1(`X-API-Key` 하나, `X-Request-ID`, `limit`/`offset`, `wezard-dataset/v1`, 최소 조건 사전 검사) |
| 2026-10-12 | 이상 탐지 통계: 결함 Polygon 이 있으면 이상, 여러 유형은 `combined`(정상 판정 주석 없음) |
| 2026-10-13 | 문서를 API 에 필요한 내용으로 줄임(계약 내용은 그대로) |
| 2026-10-15 | 문서 정정 — 없는 경로의 404 는 본문에 `request_id` 가 없다(응답 헤더 `X-Request-ID` 는 있다). 동작은 그대로 |
| 2026-10-15 | 없는 경로(`/api/v1/datasets/...`)의 404 도 본문에 `request_id` 를 넣는다 — 규약 §4 에 맞췄다. 바로 위 정정의 예외는 없어졌다. 다른 응답은 그대로 |
| 2026-10-19 | 문서 정정 — `geometry_distribution` 의 분류 라벨 키는 `NONE` 이 아니라 `CLASSIFICATION` 이다(manifest 의 `geometry_type` 과 같다). 동작은 그대로 |
| 2026-10-22 | 문서 보완 — §7 에 405 `METHOD_NOT_ALLOWED`(GET 이 아닌 메서드)를 더했다. 동작은 그대로 |
