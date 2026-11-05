# Wezard ↔ 제조AI플랫폼 통신 규약 v1

> 두 시스템이 서로를 호출할 때 함께 지키는 공통 규칙이다. 엔드포인트별 요청·응답은 각 API 문서에 있다.
> 두 저장소에 같은 내용으로 둔다. 바꿀 때는 두 쪽이 합의하고 §13 에 적는다.

## 1. 범위와 문서

| 방향 | 부르는 쪽 → 받는 쪽 | 무엇 | 키 발급 | API 문서(정본) |
|---|---|---|---|---|
| ① | Wezard → 제조AI플랫폼 | 스냅샷(학습 데이터셋) 목록·정보·다운로드 | 제조AI플랫폼 | [maip-api.md](maip-api.md) — 제조AI플랫폼 관리 |
| ② | 제조AI플랫폼 → Wezard | 모델 목록·정보·추론 | Wezard | [wezard-api.md](wezard-api.md) — Wezard 관리 |

세 문서는 같은 파일 이름으로 같은 폴더에 둔다(제조AI플랫폼 `docs/Wezard/`, Wezard `docs/maip/`).

## 2. 접속 설정

부르는 쪽은 상대의 주소와 키를 환경 변수로 둔다. 코드·저장소·로그에 키를 넣지 않는다.

| 시스템 | 변수 | 값 |
|---|---|---|
| 제조AI플랫폼 | `WEZARD_BASE_URL` | Wezard 주소. 개발 `http://10.10.10.20:8000` |
| 제조AI플랫폼 | `WEZARD_API_KEY` | Wezard 가 발급한 키(`wz_…`) |
| Wezard | `MAIP_BASE_URL` | 제조AI플랫폼 주소. 개발 `http://10.10.10.20:8123` |
| Wezard | `MAIP_API_KEY` | 제조AI플랫폼이 발급한 키(`maip_…`) |

운영 주소는 운영 서버를 세울 때 정해 환경 변수만 바꾼다(§11).

## 3. 인증

- 모든 요청에 헤더 **`X-API-Key: <키>` 하나**를 붙인다. 다른 식별 헤더는 쓰지 않는다.
- 키 접두사는 발급한 시스템이다 — 제조AI플랫폼 `maip_`, Wezard `wz_`. 재발급·폐기하면 이전 키는 바로 401 이다.
- 키는 문서에 적지 않고 따로 전달한다.
- 실패: 401. 제조AI플랫폼 `AUTH_REQUIRED`(헤더 없음)·`AUTH_INVALID`(틀림·폐기), Wezard `UNAUTHORIZED`. **재시도하지 않는다.**

## 4. 요청 추적 — `X-Request-ID`

- 부르는 쪽은 요청마다 `X-Request-ID` 를 보낸다. 형식: **1~64자, `[A-Za-z0-9._-]`**.
- 받는 쪽은 형식이 맞으면 그 값을, 없거나 틀리면 새 값(32자리 hex)을 쓴다. 형식 때문에 거절하지 않는다.
- 받는 쪽은 그 값을 응답 헤더 `X-Request-ID` 와 오류 본문 `request_id`(§5)로 돌려주고 자기 기록에 남긴다.
- 제조AI플랫폼이 현장 검사를 추론하러 부를 때는 검사의 `request_id`(UUID 36자)를 그대로 쓴다.

## 5. 응답과 오류

성공 본문은 각 시스템이 지금 쓰는 모양 그대로다.

| 받는 쪽 | 성공 | 오류 |
|---|---|---|
| 제조AI플랫폼 | `{"data": ...}` | `{"error": {"code", "message", "retryable"}, "request_id"}` |
| Wezard | 감싸지 않은 JSON | `{"ok": false, "error": {"code", "message", "detail", "retryable"}, "request", "request_id", "timestamp"}` |

부르는 쪽은 오류에서 **아래 네 값만** 읽는다.

| 경로 | 뜻 |
|---|---|
| HTTP 상태 | 4xx 요청 문제, 5xx 서버 문제 |
| `error.code` | 분기에 쓰는 값(대문자 스네이크). 바꾸지 않는다 |
| `error.retryable` | `true` 면 같은 요청을 다시 보내도 된다(§6) |
| `request_id` | §4 의 값 |

`error.message` 는 바뀔 수 있다 — 분기에 쓰지 않는다.

## 6. 재시도

- `error.retryable == true` 일 때만 자동 재시도한다.
- 간격: 1초에서 두 배씩, 최대 60초, **최대 5회**. `Retry-After` 가 있으면 따른다.
- 예외: 제조AI플랫폼 `409 EXPORT_NOT_READY` 는 **60초 이상** 간격으로 다시 본다.
- 네트워크 오류·타임아웃은 `retryable=true` 와 같다. 다운로드는 `Range` 로 이어받는다.
- 타임아웃(권장): 조회 10초, 추론 60초, 다운로드 연결 10초 + 읽기 60초.

## 7. 목록 페이지

- 쿼리 `limit`(1~200, 기본 50)·`offset`(0 이상, 기본 0).
- 응답 목록은 `items`, `total`, `limit`, `offset`(제조AI플랫폼은 `data` 안에). 정렬은 생성 시각 최신순.
- 다음 페이지는 `offset + limit < total` 일 때 있다.

## 8. 시각과 식별자

- 시각은 ISO 8601 + 시간대다. 제조AI플랫폼은 UTC `Z`, Wezard 는 `+09:00`. 쿼리로 보내는 시각도 시간대를 붙인다.
- 제조AI플랫폼 스냅샷 `id` 는 정수, Wezard `model_id`·`dataset_id` 는 32자리 hex 다.

## 9. 검사 유형과 데이터 형식

### 9-1. 검사 유형 대응표

| 제조AI플랫폼 `task_type` | Wezard `task_type` |
|---|---|
| `CLASSIFICATION` | `classification` |
| `OBJECT_DETECTION` | `detection` |
| `ANOMALY_DETECTION` | `anomaly` |

각 API 는 자기 값을 쓰고, 변환은 부르는 쪽이 한다.

### 9-2. 전송 데이터 형식 — `wezard-dataset/v1`

방향 ① 의 zip 은 Wezard 데이터셋 업로드 zip(`wezard/ARCHITECTURE.md` §12) 그대로다. Wezard 는 변환 없이 데이터셋을 만든다.

```text
dataset.zip
├── dataset.json        "format": "wezard-dataset/v1"
├── images/<sha256>.<jpg|png>
└── masks/<sha256>.png  (이상 탐지의 이상 이미지)
```

| 항목 | 규칙 |
|---|---|
| 대상 | 스냅샷의 검수 승인 이미지. 같은 내용(sha256)은 한 장만. 원본 파일이 없거나 같은 내용으로 겹치거나 내보낼 대상에서 빠진(예: 라벨이 없는 분류 이미지) 이미지는 `meta.maip.skipped` 에 센다 |
| `split` | 넣지 않는다. Wezard 가 나눈다 |
| 분류 `classes` · `label` | 스냅샷에 나오는 라벨 이름 · 이미지의 첫 라벨. 라벨이 없는 이미지는 빠진다 |
| 객체 탐지 `classes` · `boxes` | 결함 라벨 클래스 이름 · `[x1, y1, x2, y2]` 픽셀(Polygon 은 둘러싼 박스, 넓이 0 은 뺀다). 박스가 없으면 `boxes: []`(배경) |
| 이상 탐지 `classes` · `label` | `["good", "defect"]` · 결함 Polygon 이 있으면 `defect`, 없으면 `good` |
| 이상 탐지 `mask` | `defect` 이미지의 Polygon 을 원본 크기 흑백 PNG(이상 255, 정상 0)로 `masks/` 에 둔다 |
| 이상 탐지 결함 유형 | `meta.maip.anomaly_types` 에 기록만 한다. 한 이미지에 유형이 여럿이면 `combined` |
| 좌표계 | EXIF 방향을 적용한 픽셀 기준 |
| 이미지 형식 | PNG·JPEG. 파일 이름은 원본 SHA-256 + 원본 확장자 |
| 최소 조건 | 제조AI플랫폼이 Wezard 최소 조건(train ≥ 10, val ≥ 1, 유형별 조건)을 미리 검사한다. 맞지 않으면 Export 는 `FAILED` 이고 사유가 `error_message` 에 있다 |

`meta`(Wezard 가 그대로 보존한다):

```json
{
  "source": "maip",
  "external_ref": "maip:FAN-PANEL:v1.0#57",
  "maip": {
    "snapshot_id": 57,
    "item": {"id": 604, "code": "FAN-PANEL", "name": "냉각팬 패널 단면(이상탐지)", "task_type": "ANOMALY_DETECTION"},
    "version_tag": "v1.0",
    "image_ids": {"images/ab12….png": 101},
    "anomaly_types": {"images/cd34….png": "scratch"},
    "skipped": 0
  }
}
```

`image_ids` 는 zip 안 파일 → 제조AI플랫폼 이미지 ID 다.

## 10. 학습 출처와 모델 이름

- `external_ref` = `maip:<검사항목 코드>:<버전 태그>#<스냅샷 id>`(256자 이하). §9-2 `meta` 에 넣는다.
- Wezard 는 이 값을 데이터셋에 저장하고 모델 응답에 `dataset_external_ref` 로 내준다.
- Wezard 는 스냅샷 하나를 한 번만 가져온다 — `Idempotency-Key: maip-snapshot-<id>`, 받은 zip 의 SHA-256 이 스냅샷 정보의 `sha256` 과 같을 때만 만든다.
- 검사항목 코드는 1~50자 `[A-Z0-9-]` 다.
- **`model_name` 은 검사항목 코드를 소문자로 바꾼 값이다**(예: `FAN-PANEL` → `fan-panel`). 다시 학습하면 같은 이름의 `version` 이 오른다.
- 제조AI플랫폼은 `model_name` 으로 매핑하고, 추론할 때마다 배포된 최신 `model_id` 를 찾는다(재학습하면 `model_id` 가 바뀐다).

## 11. 네트워크와 보안

| 항목 | 개발 | 운영 |
|---|---|---|
| 서버 | 한 장비 10.10.10.20 (제조AI플랫폼 8123, Wezard 8000) | 서로 다른 서버 |
| 방향 ① | Wezard → 10.10.10.20:8123 | 제조AI플랫폼 nginx 가 `/api/v1/datasets/` 를 Wezard 서버 IP 에만 연다 |
| 방향 ② | 제조AI플랫폼 → 10.10.10.20:8000 | Wezard 게이트웨이가 공개 경로(모델·추론·chat)를 제조AI플랫폼 서버 IP 에만 연다 |
| 전송 | HTTP(사내망) | HTTPS 권장. 정하기 전까지는 사내망 + IP 제한 |
| 크기 | 다운로드 zip 은 Wezard `DATASET_UPLOAD_MAX_MB`(기본 10240MB) 이하. 제조AI플랫폼은 zip 크기를 검사하지 않는다 — 넘는 zip 은 Wezard 상한에 걸린다 | 같다 |

## 12. 적용 현황

v1 은 두 쪽 모두 반영했다(2026-10-12). 남은 것: §11 운영 IP 제한·HTTPS — 운영 서버를 세울 때 정한다.

## 13. 변경 관리

- **더하기**(응답 필드·선택 쿼리·오류 코드)는 받는 쪽이 자기 API 문서에 적고 알린다. 부르는 쪽은 모르는 필드를 무시한다.
- **바꾸기·빼기**(필드 의미·경로·인증·기존 오류 코드)는 두 쪽이 합의한 뒤 이 문서와 해당 API 문서를 함께 고친다.

| 날짜 | 내용 |
|---|---|
| 2026-10-12 | v1 — 양방향, `X-API-Key` 하나, `X-Request-ID`, 오류 공통 경로, `limit`/`offset`, `wezard-dataset/v1`, `external_ref`, `model_name` = 검사항목 코드 소문자 |
| 2026-10-12 | §9-2 이상 탐지: 결함 Polygon 유무로 `good`/`defect`(판정 라벨 없음), 여러 유형은 `combined` |
| 2026-10-13 | §9-2 같은 내용의 이미지는 한 장만. 문서를 API 에 필요한 내용으로 줄임 |
