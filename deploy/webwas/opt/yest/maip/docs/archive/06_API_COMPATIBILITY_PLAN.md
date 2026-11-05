# 06. API Compatibility Plan (확정)

- 기준일: 2026-09-30 (**구현 반영 2026-10-03** — 아래 "구현 상태" 참조)
- 적용 Decision: DEC-007(A), DEC-008(A·조정), DEC-014(A), DEC-015(A·설계만), DEC-016(B), DEC-019(A), §1.5 O-1
- 계약 정본: `vision-inspection/server/docs/API.md`

---

## 0-0. 구현 상태 (2026-10-03)

이 문서가 적어 둔 계약 중 **구현이 따라가지 못했던 것들을 Client 요청서(R5~R9) 대응으로
맞췄다.** 결정은 [USER_DECISIONS.md](USER_DECISIONS.md) §1.65, 회신은
[client/SERVER_API_CONTRACT.md](client/SERVER_API_CONTRACT.md) — Client 에 전달하는
계약 정본이다.

| 이 문서의 계약 | 2026-10-03 이전 | 지금 |
|---|---|---|
| health 의 `status`·`components`·`version` | `{"data":{status, server_time}}` 였다 | **맞췄다.** DB·Storage 를 실제 점검하고 실패 시 503 `degraded` |
| `AUTH_REQUIRED` / `AUTH_INVALID` 구분 | 전부 `AUTH_REQUIRED` 였다 | **구분한다** |
| `404 NOT_FOUND` 봉투 | 미지 경로가 401·404 HTML 이었다 | **봉투로 답한다**(`api/v1/<path:rest>` catch-all) |
| `HEATMAP_NOT_FOUND` | 라우트가 없어 404 HTML | **라우트 추가.** GPU 미연결이라 항상 이 코드 |
| `licenses/sources`·`client-packages` 무인증 공개 | 라우트가 없었다 | **4경로 추가.** HTTP Range 이어받기 포함 |
| 411 `LENGTH_REQUIRED` 가 인증보다 먼저 | 401 이 먼저였다 | **순서를 맞췄다** |

**아직 다른 것 — 결정이 필요하다.**

| 항목 | 이 문서 | 구현 | 비고 |
|---|---|---|---|
| health `components.gpu` | `"not_configured"` 를 함께 낸다 | **없다** — `database`·`storage` 둘뿐 | Client 계약서(`client/SERVER_API_CONTRACT.md` §4)에는 이 필드가 없다. Client 는 모르는 필드를 무시하므로 더해도 깨지지 않고, "GPU 가 붙었는가"를 운영이 자주 묻는다. **더할지 결정하면 `client/SERVER_API_CONTRACT.md` 도 함께 갱신해야 한다** |
| 뷰 파일 배치 | `app/views/api_v1/` 패키지 | `app/views/api_v1.py` **단일 파일** | §1.65 DEC-C1(사용자 지시). 권한 매핑 등록이 필요 없다는 부수 이득이 있다 |

응답 필드·오류 코드가 Client 계약서와 다른 지점은 **서버 현 구조를 정본**으로 두기로
했다(§1.65 DEC-C2). 차이 전체 목록은 `client/SERVER_API_CONTRACT.md` §14 에 있다.

---

## 0. ManufacturingAIPlatform의 API 규약 — 3종 공존(의도된 설계)

| 경로 | 규약 | 사용자 | 인증 |
|---|---|---|---|
| `/api/v1/*` | **vision 계약** — 성공 `{"data":{...}}` / 실패 `{"error":{"code","message","retryable"}}` + 의미 있는 HTTP status + UTC `Z` | VisionInspectionClient.exe | `X-Client-ID` + `X-API-Key` |
| `/api/<task>/<view>` | **MES 규약** — 조회는 행 리스트, 변경은 `{"success":bool,"message":str}`, status 200 | Web 화면 | 세션 + 2단계 인가 |
| (장래) WEB → GPU | 신규 계약 — `X-Service-Key` | 내부 서비스 | 이번 범위 미구현 |

**세 규약을 섞지 않는다.** `/api/v1/*`는 `ApiModuleView`를 거치지 않고 전용 뷰 클래스 계층(`app/views/api_v1.py`)을 쓴다.

> **URL 공간 정리**: MES `urls.py`의 `api/v1/token/{login,autologin,logout,refresh}` 4개(PDA용)는 **이관하지 않는다**(DEC-023으로 PDA가 범위 밖). `/api/v1`은 Client 계약이 단독으로 쓴다.

---

## 1. VisionInspectionClient ↔ ManufacturingAIPlatform

### 1.1 Client 변경 범위

| 항목 | 변경 |
|---|---|
| Client 코드 | **없음** |
| Client 설정 | `base_url` 만 ManufacturingAIPlatform 주소로 변경 |
| Client 재빌드 | 불필요 |
| Client ID / API Key | 통합 플랫폼에서 재발급(기존 해시는 이관 시 그대로 옮길 수 있음 — 같은 SHA-256 방식) |

### 1.2 Endpoint 계약 (KEEP 6종)

#### ① `GET /api/v1/health` — 인증 불필요

```json
{ "status": "ok", "version": "1.0.0",
  "components": { "database": "ok", "storage": "ok", "gpu": "not_configured" } }
```
- 200 정상 / 503 이상. Client는 `status`·`components.database`·`components.storage`·`version`을 읽는다.
- **`components.gpu`를 추가**한다. Client는 모르는 필드를 무시하므로 계약 위반이 아니다(API.md §40 Enum 확장 원칙).
- `gpu` 값은 이번 단계에서 항상 `"not_configured"`이며, **`status`를 `error`로 만들지 않는다**(GPU 미구성이 서비스 장애는 아니다).

#### ② `GET /api/v1/catalog` — 통합 카탈로그

```json
{ "data": { "version": "<hash>",
  "processes": [ { "id":1, "code":"SOURCE", "name":"원류 관리", "display_order":10, "active":true,
    "products": [ { "id":10, "process_id":1, "code":"ROTOR", "name":"Rotor", "description":null, "active":true,
      "inspection_items": [ { "id":103, "product_id":10, "code":"SCRATCH", "name":"Scratch",
        "description":null, "inspection_type":"DETECTION", "display_order":10, "active":true,
        "overlay": { "available": true, "version": 3 } } ] } ] } ] } }
```
- 활성 항목만 반환. `version`은 카탈로그 해시(변경 감지용).

**합성 계층 (§1.6 O-11).** DB에는 공정·제품이 없다. Client가 `data["processes"][*]["products"][*]["inspection_items"]` 중첩을 강제하므로(`server_client.py:283`, 키가 없으면 `KeyError`), 서버가 응답 생성 시점에 **고정 공정 1개·제품 1개를 상수로 합성**한다.

| 필드 | 고정값 |
|---|---|
| `processes[0]` | `id=1, code="ALL", name="전체", display_order=0, active=true` |
| `products[0]` | `id=1, process_id=1, code="ALL", name="전체", description=null, active=true` |
| `inspection_items[*].product_id` | 항상 `1` |

- 이 두 값을 **테이블로 만들지 않는다.** 만들면 §1.6 O-8과 모순된다.
- `inspection_items[*].id` = `vision_data_item.id`. `inspection_type`은 `task_type`에서 사상한다 (`OBJECT_DETECTION`→`DETECTION`, `ANOMALY_DETECTION`→`ANOMALY`).
- **`CLASSIFICATION` 검사항목은 카탈로그에서 제외한다**(§1.6 O-14). Client enum이 2종뿐이라 내보내면 파싱이 깨진다.
- `status=DELETION_PENDING` 검사항목도 제외한다(§1.6 Q9).
- Client 화면에는 "전체" 탭 하나만 표시된다 — 기능 손실은 없고 외형만 바뀐다.
- 기존 vision 데이터를 버리므로(§1.6 Q7) `id` 보존 요건은 사라졌다. 카탈로그 `version` 지문이 바뀌면 Client가 자동으로 다시 받는다.

#### ③-1 검사 접수 시 데이터 관리 연계 (§1.6 O-9)

검사 1건을 접수하면 **같은 트랜잭션에서** 데이터 관리 쪽 이미지가 만들어진다. 별도 이관 단계가 없다.

```text
POST /api/v1/inspections
  1. metadata 검증 · 이미지 검증(형식·크기)
  2. ImageService.upload_images(item, [image], actor=<client 전용 계정>, requires_labeling=True)
       → ImageAsset(status=UPLOADED, label_status=UNLABELED, source_inspection_id=<검사 id>)
  3. vision_inspection 행 저장 (image_asset FK. 파일 경로 컬럼은 없다)
  4. 활성 모델 매핑 조회
       없음 → status="RECEIVED"
       있음 → InferenceGateway.infer()  ← 현 단계 Stub, GPU_INFERENCE_NOT_CONFIGURED
              → status="RECEIVED" + error_message 기록 + 경고 로그
  5. 응답
```

| 규칙 | 내용 |
|---|---|
| 원본 이미지 | **무조건 저장**. 모델 매핑 유무·추론 성공 여부와 무관 |
| 파일 사본 | **한 벌만**. `ImageAsset.file`이 실체를 갖고 `vision_inspection`은 FK로 참조 |
| sha256 중복 | **허용**. `upload_images`의 중복 차단을 Client 경로에서만 우회한다. 사람이 화면에서 올리는 업로드의 중복 차단은 유지 |
| 라벨링 대상 | 항상 `requires_labeling=True` |
| 행위자 | `vision_client` 등록 시 자동 생성되는 전용 계정. 웹 로그인 불가(`set_unusable_password()`) |
| 연계 실패 시 | **검사 접수를 실패시키지 않는다.** 이미지 저장 실패는 422로 되돌리되, 그 외 데이터 관리 쪽 오류(ActivityLog 등)는 로그만 남기고 `RECEIVED`로 응답한다 |
| 테넌트 | 고정 Tenant. `tenant_atomic()` 안에서 실행한다(세션이 아니라 API Key 인증이므로 미들웨어가 아니라 호출부에서 설정) |

#### ③ `POST /api/v1/inspections` — 검사 요청

요청: `multipart/form-data` — `image`(파일) + `metadata`(JSON 문자열)

```json
{ "request_id":"UUID4", "client_id":"CLIENT-001", "process_id":1, "product_id":10,
  "inspection_item_id":103, "capture_timestamp":"2026-09-14T09:12:00+09:00",
  "client_version":"1.0.0", "camera":{"vendor":"basler","serial_number":"..."} }
```

- 검증에 쓰는 값: `request_id`(idempotency key), `inspection_item_id`.
- **`process_id`·`product_id`는 받되 검증하지 않고 버린다**(§1.6 O-11). Client는 여전히 두 값을 보내고 자체적으로 `> 0`을 요구하므로 필드 자체는 유지된다. 서버의 "소속 제품/공정 일치" 검증(원본 `inspection.py:85-92`)은 **제거한다.**
- `client_id`는 받기만 하고 쓰지 않는다(헤더로 식별).
- 길이 상한: `request_id` 36 / `client_version` 50 / `camera.*` 100 → 초과 시 **422 `METADATA_INVALID`, 이미지 미저장**.

처리 순서는 `04_TARGET_ARCHITECTURE.md` §10과 동일.

응답 (현 단계 — 추론 미실행):
```json
{ "data": { "inspection_id":"<uuid>", "request_id":"<uuid>",
  "inspection_type":"DETECTION", "status":"RECEIVED",
  "created_at":"2026-09-30T02:11:00Z" } }
```

응답 (GPU 연결 후 — DETECTION):
```json
{ "data": { "inspection_id":"...", "request_id":"...", "inspection_type":"DETECTION",
  "status":"SUCCESS", "abnormal":true,
  "model":{"name":"rotor-defect-detector","version":"1.3.0"},
  "defects":[{"class_name":"scratch","confidence":0.9512,
              "bbox":{"x1":120,"y1":80,"x2":440,"y2":300}}],
  "result_image_url":"/api/v1/inspections/<id>/result-image",
  "inference_ms":41.2, "created_at":"...Z" } }
```

응답 (GPU 연결 후 — ANOMALY): 위에서 `defects` 대신 `anomaly_score`·`threshold`·`heatmap_url`.

> **현 단계에서 `status`는 `RECEIVED`로만 나간다.** Client는 이미 이 상태를 처리한다(활성 ModelMapping이 없을 때 vision Server가 내던 값과 같다). 계약 변경이 아니다.

#### ④ `GET /api/v1/inspections/by-request/{request_id}`

- Client retry 워커가 **재전송 전 항상 먼저 호출**한다.
- 같은 Client의 요청이면 기존 결과 200. **다른 Client의 `request_id`면 409 `REQUEST_ID_CONFLICT`**.
- 없으면 404.

#### ⑤ `GET /api/v1/overlays/{inspection_item_id}`

```json
{ "data": { "inspection_item_id":103, "version":3, "visible":true, "opacity":0.70,
  "image_url":"/api/v1/overlays/103/image?version=3", "updated_at":"...Z" } }
```
- 없으면 404 `OVERLAY_NOT_FOUND`.
- **위치·크기 필드를 넣지 않는다**(API.md §21 — 제거된 필드).

#### ⑥ `GET /api/v1/overlays/{inspection_item_id}/image`

- `image/png` 또는 `image/jpeg`. `Cache-Control: private, max-age=86400`. `?version=` 쿼리로 캐시 무효화.

### 1.3 COMPATIBILITY_LAYER (Client 미사용, 계약상 제공)

| Endpoint | 현 단계 동작 |
|---|---|
| `GET /api/v1/catalog/version` | 제공 |
| `GET /api/v1/catalog/{processes,products}` | 제공 — **합성 고정값 1건씩**(§1.6 O-11) |
| `GET /api/v1/catalog/inspection-items` | 제공 |
| `GET /api/v1/inspections/{id}` | 제공 |
| `GET /api/v1/inspections/{id}/result-image` | **404 `RESULT_IMAGE_NOT_AVAILABLE`** (추론 결과가 없음) |
| `GET /api/v1/inspections/{id}/heatmap` | **404 `HEATMAP_NOT_FOUND`** |
| `GET /api/v1/history` | 제공 |

### 1.4 REMOVE

| Endpoint | 사유 |
|---|---|
| `GET /api/v1/licenses/sources[/{f}]` | 무인증 공개 경로. Public Subnet 노출 위험(DEC-024) |
| `GET /api/v1/client-packages[/{f}]` | 동상 |

### 1.5 오류 코드 (그대로 유지)

| Status | code | retryable | 상황 |
|---|---|:-:|---|
| 401 | `AUTH_REQUIRED` | false | 헤더 누락 |
| 401 | `AUTH_INVALID` | false | Client 없음 / 키 불일치 / 비활성 (존재 여부 비노출) |
| 404 | `NOT_FOUND` | false | 검사항목·제품·공정 없음 또는 비활성 |
| 404 | `OVERLAY_NOT_FOUND` | false | Overlay 미등록 |
| 404 | `RESULT_IMAGE_NOT_AVAILABLE` | false | 결과 이미지 없음 |
| 404 | `HEATMAP_NOT_FOUND` | false | Heatmap 없음 / DETECTION 검사 |
| 404 | `IMAGE_EXPIRED` | false | 보존 기간 경과로 파일 삭제됨 |
| 409 | `REQUEST_ID_CONFLICT` | false | 다른 Client의 `request_id` |
| 411 / 413 | — | false | Content-Length 없음 / 본문 초과 |
| 422 | `METADATA_INVALID` | false | metadata 스키마·길이 위반 |
| 422 | `IMAGE_INVALID` | false | decode 실패 |
| 429 | `RATE_LIMITED` | **true** | Client 분당 한도 초과 |
| 503 | `SERVICE_UNAVAILABLE` | **true** | DB·스토리지 이상 |

**신규(이번 단계)**

| Status | code | retryable | 상황 |
|---|---|:-:|---|
| — | `GPU_INFERENCE_NOT_CONFIGURED` | false | 추론 미구성. **응답 status는 200이고 `data.status="RECEIVED"`로 나간다.** 이 코드는 `vision_inspection.error_message`와 서버 로그에만 남으며 Client 응답의 `error` 봉투로 내보내지 않는다 |

> 이유: 검사 요청 자체는 성공했고(이미지·행 저장 완료) Client는 `RECEIVED`를 이미 정상 상태로 처리한다. 여기서 `error`를 내보내면 Client가 retry 루프에 들어간다.

### 1.6 공통 규칙

| 항목 | 값 |
|---|---|
| 시각 | 응답은 **UTC `Z` 고정**. 요청은 offset 있으면 무엇이든 수용(KST 허용) |
| 이미지 URL | **반드시 `/api/v1` 하위 상대경로**. Client가 그 밖의 경로를 거부한다(A-9) |
| CSRF | `/api/v1/*` 면제. API Key 인증으로 보호 |
| Rate limit | Client별 분당 120건(설정값, 0이면 무제한) |
| Body size | 검사 이미지 10MB, Overlay 10MB. 초과 413, `Content-Length` 없으면 411 |
| `X-Request-ID` | 수신 시 로그 상관관계에 사용. 없으면 서버가 생성 |
| 미구현 계약 | 목록 응답 `meta.count`, `CLIENT_VERSION_UNSUPPORTED` — **계속 미구현**(원본과 동일) |

### 1.7 Contract Test (Phase 10)

vision `tests/integration/test_*_api.py`를 **이관하지 않고**(Backbone §2), 위 계약표를 근거로 `tests/api/` 에 **신규 작성**한다.

```text
tests/api/test_client_auth.py           헤더 누락/불일치/비활성 → 401 코드 구분
tests/api/test_health.py                200/503, components 키
tests/api/test_catalog.py               중첩 구조, active 필터, overlay.available, version 변화
tests/api/test_inspection_submit.py     multipart, 카탈로그 정합성, 422 코드, RECEIVED 응답
tests/api/test_idempotency.py           같은 request_id 재전송 / 다른 Client 409 / 동시 요청
tests/api/test_overlay.py               메타·이미지·404·Cache-Control·version 쿼리
tests/api/test_error_envelope.py        모든 오류가 {"error":{code,message,retryable}} 형태
tests/api/test_datetime_contract.py     모든 시각이 UTC Z
tests/api/test_image_url_prefix.py      응답의 모든 이미지 URL이 /api/v1 하위 상대경로
tests/api/test_rate_limit.py            429 + retryable=true
```

---

## 2. ManufacturingAIPlatform ↔ GPU Server (이번 범위 미구현 — 계약만 정의)

Backbone §9·§10에 따라 **구현하지 않는다.** 아래는 향후 구현 시 지킬 계약이며, 지금은 `GpuServerClient`에 상수·타입만 둔다.

### 2.1 Endpoint (설계)

```text
GET  /health
GET  /models
GET  /models/{model_code}
POST /models/{model_code}/load
POST /inference/detection      multipart: image + {model_code, model_version, threshold, request_id}
POST /inference/anomaly        동상
POST /inference/classification 동상
```

### 2.2 응답 (설계)

```json
{ "request_id":"uuid", "status":"SUCCESS",
  "model":{"code":"rotor-defect-detector","version":"1.3.0"},
  "result":{ /* task 별 schema */ },
  "elapsed_ms": 41.2 }
```

| task | `result` |
|---|---|
| detection | `{"abnormal":bool, "defects":[{"class_name","confidence","bbox":{x1,y1,x2,y2}}]}` bbox는 **원본 픽셀 좌표** |
| anomaly | `{"abnormal":bool, "anomaly_score":float, "threshold":float, "heatmap_png":"<base64>"}` |
| classification | `{"class_name":str, "confidence":float, "scores":{...}}` |

### 2.3 인증 (설계)

- `X-Service-Key` 헤더. GPU가 해시 비교. 환경변수 `GPU_SERVICE_KEY`로 주입.
- Private Subnet 격리 + 애플리케이션 인증의 2중 방어.
- `X-Request-ID` 전파(Client `request_id` 사용).

### 2.4 Timeout / Retry / 장애 매핑 (설계)

타임아웃 예산: Client read 30s 안에서 `WEB 처리 + GPU 호출 ≤ 20s`, **GPU 호출 타임아웃 15s**.

| 상황 | GPU 응답 | WEB 처리 | Client 응답 |
|---|---|---|---|
| 미구성(**현 단계**) | — | `status='RECEIVED'`, `error_message='GPU_INFERENCE_NOT_CONFIGURED'` | 200 `RECEIVED` |
| 연결 실패 / Timeout | — | 1회 재시도 후 `status='FAILED'` | 200 `FAILED` |
| 모델 미로딩 | 503 `MODEL_NOT_LOADED` | `/load` 1회 후 재시도 1회 | 실패 시 `FAILED` |
| 모델 없음 | 404 `MODEL_NOT_FOUND` | `FAILED` + 매핑 화면 경고 | `FAILED` |
| GPU OOM | 503 `GPU_RESOURCE_EXHAUSTED` | `FAILED` | `FAILED` |
| 아티팩트 손상 | 500 `MODEL_INVALID` | `FAILED` + 모델 비활성화 제안 | `FAILED` |
| 잘못된 요청 | 422 | **WEB 버그** — 500 로그 + `FAILED` | `FAILED` |
| 추론 실패 | 500 `INFERENCE_FAILED` | `FAILED` | `FAILED` |
| DB 실패 | — | 이미지 저장 롤백 | 503 `SERVICE_UNAVAILABLE`, retryable |

**공통 원칙**: 추론이 실패해도 **원본과 검사 행은 남긴다.** Client는 언제나 `request_id`로 조회할 수 있다.

**재시도**: 연결 실패·503에만 1회. 추론 결과가 나온 뒤의 실패는 재시도하지 않는다.

### 2.5 Ownership

| 데이터 | 소유 |
|---|---|
| 검사 이미지·검사 결과 행 | **ManufacturingAIPlatform 단독 Write** |
| 모델 메타데이터(`vision_model`) | ManufacturingAIPlatform(잠정) → 장래 GPU 이관 |
| 검사항목↔모델 매핑 | ManufacturingAIPlatform |
| 모델 아티팩트 파일 · Runtime 상태 | GPU Server |

GPU Server는 **DB에 쓰지 않는다**(stateless). 이미지는 요청에 실어 보낸다(DEC-008 A).

---

## 3. 화면용 내부 API (MES 규약)

### 3.1 규약

```text
GET  /api/<task>/<view>?action=list|detail|...     → 행 리스트 또는 객체
POST /api/<task>/<view>?action=save|delete|...     → {"success":true} / {"success":false,"message":"..."}
HTTP status 는 항상 200 (예외는 뷰 함수가 잡아 success:false 로 변환)
401/403 은 디스패처(MESBaseView / ApiModuleView 인가 훅)가 반환
```

### 3.2 신규 task 목록

| task | view 예시 | 대응 화면 |
|---|---|---|
| `data` | `project`, `project_deletion`, `dataset`, `image`, `image_upload`, `image_preprocess`, `label_class`, `data_standard`, `labeling`, `review`, `quality`, `snapshot`, `export`, `queue`, `activity` | 데이터 관리 12화면 |
| `vision` | `dashboard`, `client`, `process`, `product`, `inspection_item`, `overlay`, `model`, `inspection`, `retention`, `migration` | 비전 검사 관리 10화면 |
| `system` | `model_mapping` (신규) + MES 기존 | 시스템 관리 |
| `files` | `data_image`, `data_thumbnail`, `data_cover`, `data_export`, `vision_overlay`, `vision_image`, `vision_heatmap` | 권한 확인 파일 제공 |

**모든 신규 `task/view`를 `apiPermissionMap`에 등록한다.** 등록하지 않으면 Phase 7 이후 403이다(DEC-014).

### 3.3 AIDataHub 규약과의 차이 처리

AIDataHub Canvas JS는 `{"ok":true,"data":{...}}`와 실패 콜백 3번째 인자 `error.message`에 묶여 있다. Canvas 모듈을 재사용하되 **응답 어댑터 한 겹**을 둔다.

```javascript
// app/static/data/api-adapter.js
// MES 규약 응답을 AIDataHub Canvas 모듈이 기대하는 형태로 감싼다.
function callApi(url, data, onSuccess, onError) {
    AjaxUtil.getAsyncData(url, data, function (res) {
        if (res && res.success === false) { onError && onError(null, 'error', { message: res.message }); return; }
        onSuccess({ ok: true, data: res });
    }, onError);
}
```

이 어댑터 덕분에 Canvas 모듈 내부는 수정하지 않는다(Backbone §6 "핵심 JavaScript 동작은 최대한 보존").

---

## 4. Related Decision

DEC-007(A) · DEC-008(A, §1.5 O-1 조정) · DEC-010(B) · DEC-013(B) · DEC-014(A) · DEC-015(A, 설계만) · DEC-016(B) · DEC-019(A) · DEC-023(B) · DEC-024(A) · DEC-027(C)
