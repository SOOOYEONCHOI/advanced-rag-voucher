# 검사 서버 API 계약 — `/api/v1`

> **이 문서가 정본이다.** 제조AI플랫폼(검사 서버)이 관리하고 **비전검사 클라이언트**
> (배포물 이름 `VisionInspectionClient`) 담당에게 전달한다. 서버 응답이 이 문서와
> 다르면 **서버가 맞다** — 그때는 알려 달라.
>
> | | |
> |---|---|
> | 판 | **2026-10-27** (§17) |
> | 서버 버전 | `1.1.0` (`GET /api/v1/health` 의 `version`) |
> | 개발 서버 | `http://10.10.10.20:8123` — **평문 HTTP, DEBUG 켜짐**(§13) |
>
> **본문의 JSON 은 모두 실제 서버에서 떠 온 응답이다.** 손으로 쓴 예시가 아니다.
> 지난 회신·변경의 전문은 이 문서의 git 이력에 있다.

## 0. 이번 판

**2026-10-27 — 문서 정정.** 응답·동작은 그대로다. 끝난 R19 §4-4 를 열린 요청에서 뺐다(§0·§9·§17).

**2026-10-26 — Client 0.7.0 반입.** 응답·동작은 그대로다. 배포본을 0.7.0 으로 바꿨다(§10-1·§17).

**2026-10-22 — 문서 정정과 Client 0.1.8 반입.** 응답·동작은 그대로다. 예시를 지금 응답 모양에 맞췄고, 배포본을 0.1.8 로 바꿨다(§10-1·§17).

**2026-10-21 — R22 회신.** 응답 모양·오류 코드는 그대로다. **태블릿 촬영 검사항목(`TAB-`)은 카탈로그에 나오지 않는다** —
서버가 거른다(R22 §5-2). Client 는 거르는 필드를 볼 필요가 없고 지금 0.1.7 에도 바로 적용된다. 그 밖의 회신은 §15 R22.

**6차 전달(2026-10-20) — 치수 측정(`MEASUREMENT`) 검사항목 유형을 더했다.** 고정 거치대에서 찍은 사진으로 **Client 가 치수를 재서**
보내면 서버가 측정점 규격(하한~상한)으로 판정한다. 카탈로그에 `include=measurement` 를 준 Client 에만 나가므로 **지금 Client 는 그대로 동작한다**
(분류를 더할 때와 같은 방식). 다른 유형의 응답 모양·오류 코드는 그대로다 — 응답에 `measurements` 키(`null`)가 하나 늘었을 뿐이다.

| 바뀐 것 | 절 |
|---|---|
| 카탈로그 `include=measurement`(`include=classification,measurement` 처럼 함께), 치수 측정 항목의 `measurement_points` | §5·§5-1 |
| 검사 `metadata` 에 `measurements`(치수 측정 항목은 필수)·`calibration`(선택) | §6-1 |
| 응답에 `measurements`(치수 측정이 아니면 `null`), 판정 규칙 `MEASUREMENT` | §6-3 |
| 오류 `422 MEASUREMENT_INVALID`(재시도 안 함) | §6-6·§11-2 |

**Client 에 요청하는 일**(치수 측정을 쓰려면)

1. 카탈로그·버전에 `include=measurement` 를 주고 `inspection_type: "MEASUREMENT"` 를 받는다
2. 측정점마다 **어디서 어디까지 재는지를 Client 쪽에서 설정**하고, 사진에 함께 찍힌 기준물(크기를 아는 물체)로 배율(mm/화소)을 구해 mm 값을 낸다.
   서버는 측정점의 코드·이름·기준값·하한·상한·단위·측정 방법 안내(`description`)만 준다
3. 측정값을 `metadata.measurements`, 배율을 `metadata.calibration` 으로 보낸다
4. 결과 화면에 측정점별 값·범위·합불을 보인다. 판정 표시는 지금처럼 `abnormal` 하나로 한다
5. 현장 카메라는 **Daheng MER2-503-23GM-P**(2448×2048, 흑백, GigE PoE)와 8mm 렌즈다. 이 카메라를 Client 가 지원하는지,
   찍은 사진이 2448×2048 그대로 오는지 알려 준다 — `VIS-ROT-DIM` 가이드(R22 §5-1)를 이 사진으로 만든다(§15)

- 개발 서버 카탈로그에 NEOCON C2 고정 거치대 검사항목 3개가 늘었다(§13). 모델이 아직 없어 치수 측정 말고는 `RECEIVED` 다. 태블릿 촬영 검사항목(`TAB-`)은 카탈로그에 나오지 않는다(2026-10-21)
- 5차 전달의 Client 할 일 3건은 모두 끝났다(R21)
- **열린 요청** — R19 §4-1 검사항목 묶음 필드(서버 보류), R22 §5-1 `VIS-ROT-DIM` 가이드(진행 중). §15

### 이 문서의 관리

- **서버가 관리한다.** `/api/v1` 응답·오류 코드·경로·메시지를 바꾸면 서버가 이 문서를 먼저 고쳐 전달한다
- **Client 가 차이를 찾으면** 요청서([`SERVER_REQUESTS.md`](SERVER_REQUESTS.md))로 보낸다. 서버는 이 문서로 회신한다 — §15 처리 결과, §17 변경 이력

---

## 1. Endpoint 13개

```text
GET  /api/v1/health                              인증 없음          §4
GET  /api/v1/catalog                             인증 필요          §5
GET  /api/v1/catalog/version                     인증 필요          §5-1
POST /api/v1/inspections                         인증 필요          §6
GET  /api/v1/inspections/by-request/{request_id} 인증 필요          §7
GET  /api/v1/inspections/{id}/heatmap            인증 필요          §8
GET  /api/v1/overlays/{inspection_item_id}       인증 필요          §9
GET  /api/v1/overlays/{inspection_item_id}/image 인증 필요          §9-1
GET  /api/v1/licenses/sources                    인증 없음          §10
GET  /api/v1/licenses/sources/{filename}         인증 없음          §10-2
GET  /api/v1/client-packages                     인증 없음          §10
GET  /api/v1/client-packages/{filename}          인증 없음          §10-2
     /api/v1/{그 밖의 모든 경로}                  인증 없음          §11-1
```

위 표에서 "인증 없음"이 아닌 경로는 모두 두 인증 헤더를 요구한다. 없는 경로는 인증 없이 404 다(§11-1).

**이미지 URL 은 조립하지 않는다.** Overlay 이미지는 응답의 `image`, 배포물은 응답의
`download_url` 을 그대로 GET 한다(§9·§10).

### 제공하지 않는 것

**라우트가 없다.** 호출하면 404 `NOT_FOUND` 봉투다.

```text
GET /api/v1/catalog/processes            통합 catalog 로 대체
GET /api/v1/catalog/products             통합 catalog 로 대체
GET /api/v1/catalog/inspection-items     통합 catalog 로 대체
GET /api/v1/inspections/{inspection_id}  by-request/{request_id} 만 제공
GET /api/v1/inspections/{id}/result-image  미제공 (서버가 결과 이미지를 만들지 않는다)
GET /api/v1/history                      미제공
GET /openapi.json · /docs · /redoc       없다. 이 문서가 Schema 정본이다
```

- 관리자 화면(`/gui/...`, `/page/...`)은 브라우저 세션 기반이며 Client 가 호출하는 REST API 가 아니다
- `/api/v1/datasets/...` 는 학습 플랫폼(Wezard)용이고 이 계약에 들지 않는다. 비전검사 클라이언트 키로 부르면 401 이다

---

## 2. 공통 규약

### 2-1. 응답 봉투

| | 모양 |
|---|---|
| 성공 | `{"data": ...}` |
| 실패 | `{"error": {"code": "...", "message": "...", "retryable": false}}` |

**`/api/v1` 아래 모든 오류가 이 봉투다.** 경로 오류(`/api/v1` 루트 포함)·허용하지 않는
메서드(405)·본문 길이 오류·인증을 통과한 뒤의 처리되지 않은 서버 예외까지 포함한다. 서버가 일부러 내는 봉투 아닌 응답은
**`GET /api/v1/health` 의 503 하나**뿐이다(§4).

봉투 없이 오는 5xx 는 앞단 프록시가 낸 것이거나, 인증 단계에서 DB 가 응답하지 않아 생긴 500 이다. 둘 다 재시도
대상이다(§11-3).

### 2-2. 시각

모든 시각은 **UTC, `Z` 접미사**다. 예: `"2026-10-05T22:53:09.994498Z"`.
Client 가 보내는 `capture_timestamp` 는 시간대를 포함한 ISO 8601 이면 된다(`+09:00` 도 받는다).

### 2-3. 파일 크기 상한

| 항목 | 상한 | 넘으면 |
|---|---|---|
| 이미지 1장 | **30 MiB** | 422 `IMAGE_INVALID` (`파일은 30MB 이하만 업로드할 수 있습니다.`) |
| 이미지 해상도 | **5,000만 픽셀**(가로 × 세로) | 422 `IMAGE_INVALID` |
| `POST /api/v1/inspections` 요청 본문 전체 | **33 MiB** | 인증보다 먼저 413 `IMAGE_TOO_LARGE` |

`image` 파트가 32 MiB 를 넘으면 저장 검사 전에 413 `IMAGE_TOO_LARGE` 로 거절한다. 30 MiB 와 32 MiB 사이는 저장 검사에서
422 `IMAGE_INVALID` 다 — **30 MiB 이하로 보내면 둘 다 생기지 않는다.**

### 2-4. `Content-Length`

`POST` 는 `Content-Length` 가 **필수**다. chunked 전송은 **인증보다 먼저**
411 `LENGTH_REQUIRED` 로 거절한다. 상한 초과도 인증보다 먼저 413 이다.

---

## 3. 인증

§1 에서 인증이 필요한 경로에 아래 두 헤더가 **필수**다.

```http
X-Client-ID: CLIENT-001
X-API-Key: <api_key>
```

멱등성에는 `X-Request-ID` 를 쓰지 않는다. 멱등성은 multipart `metadata` 안의 `request_id` 가 맡는다(§6-4).

서버는 **모든 응답에 `X-Request-ID` 헤더**를 붙인다. 요청에 1~64자 `[A-Za-z0-9._-]` 값을 실어 보내면 그대로 돌려주고,
없거나 형식이 다르면 새로 만든다. 장애를 문의할 때 이 값을 알려 주면 서버 로그를 찾을 수 있다.

### 3-1. 실패 응답

| 상황 | HTTP | `error.code` |
|---|---|---|
| 두 헤더 중 하나라도 없음 | 401 | `AUTH_REQUIRED` |
| 없는 `X-Client-ID` · `X-API-Key` 불일치 · 비활성 Client | 401 | `AUTH_INVALID` |

```json
HTTP 401
{"error": {"code": "AUTH_INVALID", "message": "인증에 실패했습니다.", "retryable": false}}
```

`AUTH_REQUIRED` 도 `message` 가 같다. **없는 Client 와 비활성 Client 는 의도적으로 같은 코드다** — 어느 `client_id` 가
등록돼 있는지 알려 주지 않는다. 두 코드 모두 재전송하지 않는다(`retryable: false`).
인증 실패 로그에는 `client_id` 와 실패 사유만 남는다. **API Key 는 마스킹한 값도 기록하지 않는다.**

### 3-2. 발급과 재발급

- **발급은 서버 관리자에게 요청한다.** 관리 화면에서 발급하며 **그 순간 한 번만** 평문 키가 보인다. 서버에는 SHA-256 해시만 남아 다시 조회할 수 없다
- 발급 값은 **문서·메일 본문·채팅에 평문으로 넣지 않고** 담당자에게 직접 전달한다
- 분실·유출 시 재발급한다. `client_id` 는 그대로여서 과거 검사 이력이 남고, 이전 키는 즉시 `401 AUTH_INVALID` 가 된다
- 인증 실패에 대한 rate limit·계정 잠금은 **없다**(§16 질문 4)

Client 는 받은 키를 설정 파일에 평문으로 두지 않는다(Windows DPAPI 로 사용자 프로필에 암호화 저장 — Client 쪽 구현).

---

## 4. `GET /api/v1/health`

인증 없음. DB `SELECT 1` 과 Storage 쓰기→삭제를 **실제로 수행**한 뒤 응답한다.

```json
HTTP 200
{
  "status": "ok",
  "components": {"database": "ok", "storage": "ok"},
  "version": "1.1.0",
  "timestamp": "2026-10-03T05:35:45.526354Z"
}
```

- `components` 값은 `"ok"` 또는 `"error"` 두 가지다. 구성요소에 `"degraded"` 를 쓰지 않는다
- 하나라도 실패하면 **HTTP 503**, 최상위 `status: "degraded"`, 실패 항목만 `"error"` 다(예: `"components": {"database": "error", "storage": "ok"}`)
- **이 503 은 오류 봉투가 아니다.** 위 모양 그대로 낸다. 재시도 판단에 쓰지 않는다
- `components.gpu`(추론 서버)는 **넣지 않는다.** 추론 서버 장애가 health 503 이 되면 저장·라벨링까지 되는 서버를
  멈춘 것처럼 보이게 한다. 추론 서버 장애는 검사 응답의 `FAILED` 로 드러난다(§6-5).
  넣기로 하면 값의 뜻과 503 판단에 포함하는지를 이 문서에 먼저 적고 알린다

---

## 5. `GET /api/v1/catalog`

인증 필요. 공정→제품→검사항목을 중첩해 한 번에 반환한다. **활성 항목만** 나온다.

| 쿼리 | 뜻 |
|---|---|
| `include=classification` | 분류(`CLASSIFICATION`) 검사항목도 내보낸다. 없으면 `DETECTION`·`ANOMALY` 만 나온다 — 분류를 모르는 Client(0.1.6 이하)가 파싱하다 깨지지 않게 한다 |
| `include=measurement` | 치수 측정(`MEASUREMENT`) 검사항목도 내보낸다. 분류와 함께 받으려면 쉼표로 잇는다 — `include=classification,measurement` |

아래는 개발 서버의 `GET /api/v1/catalog?include=classification` 응답이다. 파라미터가 없으면 `FAN-PANEL-CLS` 가 빠지고
`version` 이 `8f07041de71311ee` 로 달라진다. 세 검사항목은 한 부품을 유형별로 나눈 것이다(§6-7).
이 예시는 2026-10-12 응답이다 — 지금 개발 서버 카탈로그에는 NEOCON C2 고정 거치대 검사항목 3개가 더 있다(§13).

```json
HTTP 200
{
  "data": {
    "version": "cf8c8ad4e78c403d",
    "processes": [
      {
        "id": 1, "code": "ALL", "name": "전체", "display_order": 0, "active": true,
        "products": [
          {
            "id": 1, "process_id": 1, "code": "ALL", "name": "전체",
            "description": null, "active": true,
            "inspection_items": [
              {
                "id": 961, "product_id": 1, "code": "FAN-PANEL-CLS", "name": "냉각팬 패널 단면(분류)",
                "description": null, "inspection_type": "CLASSIFICATION", "display_order": 0,
                "active": true, "overlay": {"available": true, "version": 1}
              },
              {
                "id": 604, "product_id": 1, "code": "FAN-PANEL", "name": "냉각팬 패널 단면(이상탐지)",
                "description": null, "inspection_type": "ANOMALY", "display_order": 1,
                "active": true, "overlay": {"available": true, "version": 1}
              },
              {
                "id": 962, "product_id": 1, "code": "FAN-PANEL-DET", "name": "냉각팬 패널 단면(객체탐지)",
                "description": null, "inspection_type": "DETECTION", "display_order": 2,
                "active": true, "overlay": {"available": true, "version": 1}
              }
            ]
          }
        ]
      }
    ]
  }
}
```

치수 측정 검사항목은 `measurement_points` 를 더 갖는다(다른 유형에는 **키가 없다**). 아래는 `include=measurement` 로 받은
개발 서버의 치수 측정 항목 `VIS-ROT-DIM` 이다(2026-10-20). `description` 은 길어서 줄였다 — 실제로는 촬영·판정·근거 세 줄이다.

```json
{
  "id": 1803, "product_id": 1, "code": "VIS-ROT-DIM", "name": "Rotor 치수(수입)",
  "description": "촬영: 고정 거치대. 입고된 Rotor 를 크기를 아는 기준물과 함께 위에서 찍는다(높이 약 650mm, Overlay 로 맞춤). …",
  "inspection_type": "MEASUREMENT", "display_order": 16, "active": true,
  "overlay": {"available": false, "version": null},
  "measurement_points": [
    {"code": "A", "name": "치수 A", "nominal": 540.0, "lower": 539.0, "upper": 541.0, "unit": "mm", "description": null},
    {"code": "B", "name": "치수 B", "nominal": 540.0, "lower": 539.0, "upper": 541.0, "unit": "mm", "description": null},
    {"code": "C", "name": "치수 C", "nominal": 154.0, "lower": 153.0, "upper": 155.0, "unit": "mm", "description": null}
  ]
}
```

측정점 이름(`치수 A`)과 `description` 은 도면을 받으면 서버 화면에서 고친다 — 그때 카탈로그 `version` 이 바뀐다.

| `measurement_points[]` | 형식 |
|---|---|
| `code` | 문자열(20자까지, 영문·숫자·`_`·`-`). 측정값을 돌려보낼 때 이 코드를 쓴다. 검사항목 안에서 겹치지 않는다 |
| `name` | 화면에 보일 이름 |
| `nominal` · `lower` · `upper` | 숫자. 기준값·하한·상한. **합격 범위는 `lower <= 값 <= upper`(경계 포함)** 다 |
| `unit` | 단위(기본 `mm`). 측정값은 이 단위로 보낸다 |
| `description` | 측정 방법 안내(어디서 어디까지). 없으면 `null` |
| 순서 | 배열 순서가 화면 순서다 |

### 공정·제품은 합성값이다

**이 서버에는 공정·제품 테이블이 없다.** Client 가 `processes[].products[].inspection_items[]` 중첩을 강제하므로 서버가
응답 생성 시점에 **고정 공정 1개·제품 1개를 만들어 끼운다** — `processes[0]`·`products[0]` 모두 `id: 1`, `code: "ALL"`,
`name: "전체"` 이고 **항상 1건씩**이다. Client 는 받은 `process_id`·`product_id` 를 그대로 되돌려 보내면 된다 — 서버는 검증하지 않는다.

### 그 밖

- **태블릿으로 찍는 검사항목은 나오지 않는다**(어떤 `include` 로도). 서버 관리 화면에서 검사항목마다 촬영 방식(고정 거치대·태블릿)을 정하고, 카탈로그는 고정 거치대 항목만 내보낸다. 태블릿 항목은 디지털 양식 사진 넣기로만 쓴다
- `inspection_type` 은 `"CLASSIFICATION"`·`"DETECTION"`·`"ANOMALY"`·`"MEASUREMENT"` 다. `"CLASSIFICATION"`·`"MEASUREMENT"` 는 `include` 로 요청할 때만 나온다
- `overlay` 는 항상 있다. Overlay 가 없거나 **`visible: false` 면 `{"available": false, "version": null}`** 이다 — 둘을 구분하지 않는다.
  이때 §9·§9-1 은 모두 404 `OVERLAY_NOT_FOUND` 다. `available: false` 면 §9 를 호출하지 않는다
- `code` 는 검사항목 코드다. 서버 관리 화면에서 새로 만든 검사항목은 `ITEM-<id>`(예: `ITEM-7`)로 정해진다. 화면 표시는 `name`, 식별은 `id` 로 한다
- `version` 은 카탈로그 내용의 해시다. 내용이 바뀔 때만 달라진다
- 시작 시 한 번 받아 캐시하면 된다(개발 서버 기준 약 1 KB)

### 5-1. `GET /api/v1/catalog/version`

지문만 받는다. 캐시 무효화 판단용이다. **`include` 를 카탈로그와 똑같이 준다** — 지문은
내보낸 목록으로 계산하므로 한쪽에만 주면 늘 다르게 나온다. 측정점 규격이 바뀌어도 지문이 바뀐다.

```json
HTTP 200
{"data": {"version": "cf8c8ad4e78c403d", "updated_at": "2026-10-12T08:01:42.753810Z"}}
```

`updated_at` 은 **이 응답을 만든 시각**이며 카탈로그가 바뀐 시각이 아니다. 변경 감지는 `version` 으로만 한다.

---

## 6. `POST /api/v1/inspections`

인증 필요. `multipart/form-data` 로 이미지와 메타데이터를 보낸다.

```http
POST /api/v1/inspections
X-Client-ID: CLIENT-001
X-API-Key: <api_key>
Content-Type: multipart/form-data
Content-Length: <필수>

image:    <binary>        JPEG 또는 PNG
metadata: {"request_id":"...","process_id":1,"product_id":1,"inspection_item_id":1,
           "capture_timestamp":"2026-10-06T09:00:00+09:00","client_version":"0.1.4",
           "camera":{"vendor":"basler","serial_number":"SN-1"}}
```

### 6-1. `metadata` 필드

| 필드 | 필수 | 형식 | 서버가 쓰는 방식 |
|---|---|---|---|
| `request_id` | **예** | UUID 문자열을 쓴다, **36자까지**. 서버는 길이만 검사하고 형식은 보지 않는다 | 멱등성 키(§6-4) |
| `inspection_item_id` | **예** | 정수(카탈로그 `id`). 정수로 읽히지 않으면 422 — 소수(`12.7`)·`true`/`false` 도 422 | 카탈로그 정합성 검증 |
| `process_id` · `product_id` | 아니오 | 정수 | **받지만 검증하지 않는다**(§5) |
| `capture_timestamp` | 아니오 | ISO 8601 + 시간대. 시각으로 읽히지 않으면 422 | 검사 기록에 저장 |
| `client_version` | 아니오 | **50자까지** | 검사 기록에 저장. 값(버전)은 검사하지 않는다 |
| `camera.vendor` · `camera.serial_number` | 아니오 | **각 100자까지**. `camera` 는 JSON 객체 — 빼거나 `null` 이면 없는 것으로 보고, 그 밖의 객체가 아닌 값(`[]`·`""`·`0`·`false` 포함)은 422 | 검사 기록에 저장 |
| `client_id` | 아니오 | — | 받기만 하고 쓰지 않는다. 식별은 헤더로 한다 |
| `measurements` | **치수 측정 항목이면 예** | `[{"code": "A", "value": 540.32}, …]` — 카탈로그 `measurement_points` 의 **모든 코드를 한 번씩**. `value` 는 숫자(측정점 단위). 문자열·참거짓·`NaN`·무한대는 안 된다. 어긋나면 422 `MEASUREMENT_INVALID` | 측정점 규격으로 판정(§6-3). **다른 유형의 검사항목이면 무시한다** |
| `calibration` | 아니오(보내기를 권한다) | JSON 객체. 예: `{"method": "REFERENCE", "mm_per_px": 0.2831, "reference": "CAL-100"}`. 객체가 아니면 422 `METADATA_INVALID`, 글자 값은 **각 50자까지**. 빼거나 `null` 이면 없음 | 검사 기록에 그대로 저장 — 어떤 배율로 쟀는지 되짚는 데 쓴다. 응답에는 없다 |

- **길이 상한을 넘으면 거절한다. 자르지 않는다** — 422 `METADATA_INVALID`(§6-6). `request_id` 를 잘라 저장하면 보낸 값으로 재조회할 수 없다
- `metadata` 는 **JSON 객체**여야 한다(배열·숫자·문자열은 422)
- `capture_timestamp`·`client_version`·`camera` 는 응답에 **포함되지 않는다.** "어느 카메라로 언제 찍었는가"를 나중에 되짚는 값이므로 가능하면 채워 보낸다
- **파일 확장자는 신뢰하지 않는다.** 서버가 실제로 디코딩해 포맷을 판별하고 저장 경로의 확장자도 그 결과로 정한다

### 6-2. 성공 응답

신규 저장은 **201**, 같은 `request_id` 재전송은 **200**이며 **본문은 동일**하다. 아래는 개발 서버 `FAN-PANEL-DET`(객체 탐지)에
결함 표본(§15)을 보낸 응답이다 — 왼쪽 아래의 긁힘을 감싸는 박스 1개다.

```json
HTTP 201
{
  "data": {
    "id": "e29b9821-a426-41fb-bdda-32c0f81a6116",
    "request_id": "f40dc650-0f1f-4c3a-9dc0-127a02fdb43a",
    "inspection_item_id": 962,
    "inspection_type": "DETECTION",
    "status": "SUCCESS",
    "abnormal": true,
    "defects": [
      {"class_name": "scratch", "name": "스크래치", "confidence": 0.938766598701477,
       "bbox": {"x1": 228, "y1": 486, "x2": 597, "y2": 1083}}
    ],
    "anomaly_score": null,
    "threshold": null,
    "classification": null,
    "measurements": null,
    "inference_ms": 94.0,
    "model": {"name": "fan-panel-det", "version": "4"},
    "created_at": "2026-10-13T07:44:32.605452Z"
  }
}
```

**검사 식별자는 `id` 다** — `inspection_id` 가 아니다. 모델이 매핑되지 않은 검사항목이면 `status: "RECEIVED"`,
판정 필드는 `null`·`[]`, `model` 은 `null` 이다(§6-3).

### 6-3. 판정 필드 — 모델이 매핑된 검사항목만 채워진다

서버 관리 화면에서 모델을 매핑한 검사항목만 추론 서버(Wezard)로 추론한다. 매핑이 없거나 그 모델이 배포돼 있지 않으면
판정 없이 `RECEIVED` 다. **이미지는 어느 경우든 정상 저장되고 라벨링 대기열에도 올라간다.**
추론 서버가 모델을 다시 배포하면 버전과 이상 탐지 임계값이 바뀐다 — 고정값으로 두지 않고 응답 값을 쓴다(개발 서버 모델은 §13).

| 필드 | 추론하지 않았을 때(`RECEIVED`) | 추론했을 때(`SUCCESS`) |
|---|---|---|
| `status` | `"RECEIVED"` | `"SUCCESS"`. 추론이 실패하면 `"FAILED"` |
| `abnormal` | `null` | `true`/`false` |
| `defects` | `[]` | DETECTION 의 bbox 목록 |
| `anomaly_score` · `threshold` | `null` | ANOMALY 의 점수·임계값 |
| `classification` | `null` | CLASSIFICATION 의 1순위 클래스 `{label, name, score}` |
| `measurements` | `null` | MEASUREMENT 의 측정점별 결과(아래) |
| `model` | 매핑이 없거나 매핑한 모델을 서버에서 쓰지 않게 해 두었으면 `null`. **그 밖에는 매핑한 모델 이름과 `"version": "latest"`**(`FAILED` 도 같다) | 추론 서버가 실제로 쓴 `{"name": "...", "version": "..."}` |
| `inference_ms` | `null` | 추론 서버가 잰 추론 시간(ms) |
| `heatmap_url` | **키 자체가 없다** | ANOMALY 이고 Heatmap 을 만들었을 때만 `"/api/v1/inspections/{id}/heatmap"`. 그 밖에는 **키 자체가 없다**(§8). `result_image_url` 은 만들지 않는다 |

**키는 있고 값이 `null` 이다**(`heatmap_url` 만 예외 — 없으면 키가 없다). "키가 있으면 추론됨"으로 판단할 수 없다.
**`model` 이 있어도 추론한 것이 아니다** — 추론 여부는 `status` 로만 본다.

| 필드 | 형식 |
|---|---|
| `defects[].bbox` | `{x1, y1, x2, y2}` — **원본 이미지 Pixel 좌표** 정수. `0 <= x1 < x2 <= 너비`, `0 <= y1 < y2 <= 높이`. 추론 서버의 실수 좌표를 바깥쪽 정수로 넓혀 이미지 안으로 자르고, 넓이가 0 인 박스는 버린다. 기준은 EXIF 방향을 적용한 이미지다 |
| `defects[].class_name` | 문자열. **라벨 코드**다(예: `scratch`) |
| `defects[].name` | 문자열. **표시 이름**이다(예: `"스크래치"`) — 화면에는 이것을 쓴다. 검사항목에 없는 라벨이면 `class_name` 과 같은 코드다. 2026-10-13 이전 기록에는 없다 — 없으면 `class_name` 을 쓴다 |
| `defects[].confidence` | `0.0`~`1.0` 실수 |
| `abnormal` | `true`/`false`. Client 판정 표시는 이 값 하나만 본다(아래 판정 규칙) |
| `anomaly_score` · `threshold` | ANOMALY 의 실수. **0~1 로 정규화한 값이 아니다**(개발 서버 실측 점수 정상 21.3~23.0·결함 41.1~51.1, 임계값 33.26) |
| `classification` | CLASSIFICATION 의 `{"label": str, "name": str, "score": 0.0~1.0}`. `label` 은 클래스 코드, `name` 은 표시 이름(화면에는 이것을 쓴다), `score` 는 그 클래스의 확률. 키 순서는 의미가 없다 |
| `model` | `{"name": str, "version": str}` |
| `inference_ms` | 숫자(ms). 추론 서버 안의 시간이라 네트워크 왕복은 들어가지 않는다(개발 서버 실측 35~190). 추론 서버가 모델을 처음 불러오는 요청은 2초를 넘을 수 있다 |
| `heatmap_url` | ANOMALY `SUCCESS` 이고 Heatmap 이 있을 때만 키가 있다. `/api/v1/` 아래 **상대경로**. 이미지 규격은 §8 |
| `measurements` | MEASUREMENT 의 `[{"code", "name", "value", "lower", "upper", "unit", "ok"}]` — 측정점 순서. `value` 는 보낸 값 그대로, `lower`·`upper`·`unit`·`name` 은 **판정할 때의 규격**(나중에 규격이 바뀌어도 이 기록은 그대로), `ok` 는 `lower <= value <= upper` |

DETECTION 은 `defects`, ANOMALY 는 `anomaly_score`·`threshold`·`heatmap_url`, CLASSIFICATION 은 `classification`, MEASUREMENT 는 `measurements` 를 채운다. 섞지 않는다.

**MEASUREMENT 는 모델을 쓰지 않는다.** 추론 서버를 부르지 않고 접수하자마자 `SUCCESS` 다 — `model`·`inference_ms` 는 `null` 이다.
사진은 다른 유형처럼 저장하지만(증빙) 라벨링·학습 데이터에는 쓰지 않는다.

**판정 규칙** — `abnormal` 을 정하는 방법이다.

| 유형 | `abnormal` 이 `true` 인 경우 |
|---|---|
| ANOMALY | `anomaly_score >= threshold` |
| DETECTION | 박스가 **하나라도** 있다. 클래스가 무엇인지는 보지 않는다. 신뢰도 임계값보다 낮은 박스는 오지 않는다(임계값은 서버의 모델 매핑에 남아 있는 값을 쓰고, 없으면 추론 서버 기본값 0.25. 개발 서버 `fan-panel-det` 은 0.7) |
| CLASSIFICATION | 1순위 클래스가 그 검사항목의 **불량 클래스**다. 검사항목에 없는 클래스가 오면 `true` 로 본다. 분류에는 임계값이 없다 |
| MEASUREMENT | 측정점이 **하나라도** `ok: false` 다 |

ANOMALY·CLASSIFICATION 실제 응답(개발 서버, 2026-10-13) — §6-2 와 같은 결함 표본을 보낸 것이다. 둘 다 이상으로 판정됐다.

```json
{
  "data": {
    "id": "ed73455a-31b4-4975-af83-1ff3e1717aa6",
    "request_id": "ed130011-b647-49dd-bd99-dbbbba25bfba",
    "inspection_item_id": 604,
    "inspection_type": "ANOMALY",
    "status": "SUCCESS",
    "abnormal": true,
    "defects": [],
    "anomaly_score": 51.11032485961914,
    "threshold": 33.26475238800049,
    "classification": null,
    "measurements": null,
    "inference_ms": 116.0,
    "model": {"name": "fan-panel", "version": "3"},
    "created_at": "2026-10-13T07:44:31.238766Z",
    "heatmap_url": "/api/v1/inspections/ed73455a-31b4-4975-af83-1ff3e1717aa6/heatmap"
  }
}
```

```json
{
  "data": {
    "id": "439ef3e8-2512-44a4-8151-ddb3d0600722",
    "request_id": "7f299e5a-6de0-479a-aaa1-1edbcc46e21c",
    "inspection_item_id": 961,
    "inspection_type": "CLASSIFICATION",
    "status": "SUCCESS",
    "abnormal": true,
    "defects": [],
    "anomaly_score": null,
    "threshold": null,
    "classification": {"name": "불량", "label": "defect", "score": 0.6655997037887573},
    "measurements": null,
    "inference_ms": 36.0,
    "model": {"name": "fan-panel-cls", "version": "3"},
    "created_at": "2026-10-13T07:44:32.050165Z"
  }
}
```

MEASUREMENT 실제 응답(개발 서버 `VIS-ROT-DIM`, 2026-10-20) — 측정점 C 가 상한(155)을 넘어 이상이다. 보낸 `metadata` 는
`"measurements": [{"code": "A", "value": 540.32}, {"code": "B", "value": 539.85}, {"code": "C", "value": 155.18}]`,
`"calibration": {"method": "REFERENCE", "mm_per_px": 0.2831, "reference": "CAL-100"}` 이다(이 기록은 지웠다).

```json
HTTP 201
{
  "data": {
    "id": "34fe0e21-d9a2-40fb-bd2c-8a1661274faf",
    "request_id": "ca11979b-72b9-4d18-bd75-4eccfc1bfc69",
    "inspection_item_id": 1803,
    "inspection_type": "MEASUREMENT",
    "status": "SUCCESS",
    "abnormal": true,
    "defects": [],
    "anomaly_score": null,
    "threshold": null,
    "classification": null,
    "measurements": [
      {"code": "A", "name": "치수 A", "value": 540.32, "lower": 539.0, "upper": 541.0, "unit": "mm", "ok": true},
      {"code": "B", "name": "치수 B", "value": 539.85, "lower": 539.0, "upper": 541.0, "unit": "mm", "ok": true},
      {"code": "C", "name": "치수 C", "value": 155.18, "lower": 153.0, "upper": 155.0, "unit": "mm", "ok": false}
    ],
    "inference_ms": null,
    "model": null,
    "created_at": "2026-10-20T05:19:43.397488Z"
  }
}
```

`status: "FAILED"` 는 추론 실패이며 Client 는 "판정 없음"으로 표시하고 다시 보내지 않는다.
**이 형식을 바꿔야 하면 바꾸기 전에 이 문서로 먼저 알린다.**

### 6-4. 멱등성

같은 `request_id` 로 다시 보내면 이미지를 다시 저장하지 않고 **기존 기록을 그대로** 돌려준다(200).
네트워크 재시도 때 **같은 `request_id` 를 반드시 재사용한다.**

- 같은 `request_id` 를 **다른 Client 가 이미 썼으면** 409 `REQUEST_ID_CONFLICT` 다. UUID 로 만들면 생기지 않는다
- **같은 사진을 새 `request_id` 로 보내면 별건으로 저장된다.** 화면 업로드는 sha256 중복을 막지만 Client 경로는 중복을 허용한다 — 같은 장면을 다시 찍어 보낼 수 있어서다

### 6-5. `RECEIVED` 를 받았을 때 — 폴링하지 않는다

**`RECEIVED` 는 종결 상태다.**

- `RECEIVED` 는 **"추론하지 않았다"**(모델 미매핑·매핑한 모델을 서버에서 쓰지 않게 해 둠·추론 서버 미설정·매핑한 모델이 배포돼 있지 않음)만 뜻한다. 재조회해도 바뀌지 않는다
- 모델이 매핑·배포돼 있으면 `POST /inspections` 가 **추론을 마친 뒤** `SUCCESS`/`FAILED` 로 응답한다.
  서버는 추론에 **20초**(모델 조회 5초 + 추론 15초)를 두어 Client 의 읽기 timeout(30초)보다 먼저 끝낸다.
  단계마다의 연결·읽기 한도라 이미지 저장 시간을 더하면 20초를 조금 넘을 수 있지만 30초 안이다. 재시도는 하지 않는다
- 추론 서버에 닿지 않거나 시간을 넘기거나 오류를 내면 `FAILED` 다. 추론 도중 그 모델의 배포가 풀리면 `RECEIVED` 다
- 비동기 처리가 필요해지면 새 상태(`PROCESSING`)를 따로 만든다. **그 경우 배포 전에 이 문서로 먼저 알린다** — `RECEIVED` 의 뜻은 바꾸지 않는다

### 6-6. 오류 응답

| 상황 | HTTP | `error.code` | 판단 시점 |
|---|---|---|---|
| `Content-Length` 없음(chunked) | 411 | `LENGTH_REQUIRED` | **인증보다 먼저** |
| 본문이 33 MiB 초과 | 413 | `IMAGE_TOO_LARGE` | **인증보다 먼저** |
| 인증 실패 | 401 | §3 참조 | — |
| `image` 파트가 없음 | 422 | `IMAGE_REQUIRED` | |
| `metadata` 파트가 없음 / JSON 파싱 실패 / multipart 본문 형식이 깨짐 | 422 | `METADATA_INVALID` | **이미지를 보기 전** |
| `metadata` 가 JSON 객체가 아님(배열·숫자·문자열) / `camera` 가 객체가 아님(`null` 은 제외) | 422 | `METADATA_INVALID` | 〃 |
| `request_id` 또는 `inspection_item_id` 누락 | 422 | `METADATA_INVALID` | 〃 |
| `inspection_item_id` 가 정수가 아님(소수·참거짓 포함) / `capture_timestamp` 가 시각이 아님 | 422 | `METADATA_INVALID` | 〃 |
| 길이 상한 초과 — `request_id` 36 · `client_version` 50 · `camera.*` 각 100 · `calibration` 의 글자 값 각 50 | 422 | `METADATA_INVALID` | 〃 |
| `calibration` 이 객체가 아님(`null` 은 제외) | 422 | `METADATA_INVALID` | 〃 |
| 이미지 32 MiB 초과 | 413 | `IMAGE_TOO_LARGE` | |
| 이미지 30 MiB 초과(32 MiB 이하) | 422 | `IMAGE_INVALID` | §2-3 |
| 해상도 5,000만 픽셀 초과 | 422 | `IMAGE_INVALID` | |
| 이미지가 디코딩되지 않음(손상·위장·압축 폭탄) | 422 | `IMAGE_INVALID` | |
| JPEG/PNG 가 아닌 형식 | 422 | `IMAGE_INVALID` | 디코딩 실패와 **같은 코드** |
| `inspection_item_id` 가 없거나 비활성 | 404 | `INSPECTION_ITEM_NOT_FOUND` | |
| `request_id` 를 다른 Client 가 사용 | 409 | `REQUEST_ID_CONFLICT` | |
| 치수 측정 항목인데 `measurements` 가 없음 / 배열이 아님 / 측정점이 빠지거나 모르는 코드·같은 코드 두 번 / 값이 숫자가 아님(문자열·참거짓·`NaN`·무한대) | 422 | `MEASUREMENT_INVALID` | 검사항목을 찾은 뒤, **이미지를 보기 전** |
| 처리되지 않은 서버 오류 | 500 | `INTERNAL_ERROR` | **`retryable: true`** |

```json
HTTP 422
{"error": {"code": "METADATA_INVALID", "message": "client_version 은 50자 이하여야 합니다.", "retryable": false}}
```

```json
HTTP 422
{"error": {"code": "MEASUREMENT_INVALID", "message": "측정점 A, B, C 을 한 번씩 보내야 합니다.", "retryable": false}}
```

`metadata`·`measurements` 오류는 **이미지를 저장하기 전에** 판단한다. 거절된 요청은 검사 기록도 이미지도 남기지 않는다.
`message` 는 사람이 읽는 문장이고 바뀔 수 있다 — **분기는 `code` 로 한다.**
**`429 RATE_LIMITED` 는 제공하지 않는다.** 분당 요청 한도가 없다(§13).

### 6-7. 유형별로 나눈 검사항목

한 부품을 여러 방식으로 판정하려면 서버에 **유형마다 검사항목을 따로** 만든다. 개발 서버의 냉각팬 패널이 그렇다.

| 검사항목 | `inspection_type` | 판정 결과가 오는 필드 |
|---|---|---|
| `FAN-PANEL` 냉각팬 패널 단면(이상탐지) | `ANOMALY` | `anomaly_score`·`threshold` |
| `FAN-PANEL-CLS` 냉각팬 패널 단면(분류) | `CLASSIFICATION` | `classification` (카탈로그에 `include=classification` 일 때만 나온다) |
| `FAN-PANEL-DET` 냉각팬 패널 단면(객체탐지) | `DETECTION` | `defects` |

- **셋은 서로 독립된 검사항목이다.** id·코드·Overlay·모델이 각자 있다. 카탈로그에 셋을 묶는 필드는 없다 —
  이름 끝의 `(분류)` 같은 글자로 묶지 않는다. 묶는 체계는 서버 보류다(§15 R19 §4-1)
- **검사 1건 = 검사항목 1개다.** 한 번 찍은 사진을 여러 유형으로 판정하려면 같은 이미지를 검사항목마다
  **서로 다른 `request_id`** 로 따로 보낸다(§6-4) — 검사항목마다 기록이 하나씩 생긴다
- 응답도 검사항목마다 따로 온다. 각 응답의 `abnormal` 을 그 검사항목의 판정으로 표시한다. 여러 판정을 하나로 합쳐
  보일지는 Client 가 정한다(서버는 합친 판정을 만들지 않는다). 순서대로 보내면 응답 시간이 검사항목 수만큼 늘어난다
- Overlay 는 검사항목마다 받는다(§9). 세 검사항목이 같은 가이드를 쓰더라도 `version` 은 따로 오른다

---

## 7. `GET /api/v1/inspections/by-request/{request_id}`

인증 필요. 응답은 §6-2 의 POST 성공 응답과 **완전히 동일**하다(이상 탐지 `SUCCESS` 면 정상 판정이어도 `heatmap_url` 이 있다).
Client 가 재접속했거나 POST 응답을 받지 못했을 때 같은 본문을 다시 받는다.

**자기 Client 가 만든 검사만 조회된다.** 다른 Client 소유이거나 없는 `request_id` 면 구분 없이 404 다 — 존재 여부를 노출하지 않는다.

| 상황 | HTTP | `error.code` |
|---|---|---|
| 없거나 다른 Client 소유 | 404 | `INSPECTION_NOT_FOUND` |

`GET /api/v1/inspections/{inspection_id}`(id 로 조회)는 **제공하지 않는다.**

---

## 8. `GET /api/v1/inspections/{id}/heatmap`

인증 필요. 소유 확인을 한다. **이상 탐지(ANOMALY)가 `SUCCESS` 일 때 서버가 Heatmap 을 만들어 둔다.** 그 검사의 응답에
`heatmap_url` 이 있고, 이 경로가 그 이미지(`200`, `Content-Type: image/jpeg`)를 내준다. `heatmap_url` 이 없는 검사는 부르지 않는다.

| 상황 | HTTP | `error.code` |
|---|---|---|
| 없는 id 또는 다른 Client 소유 | 404 | `INSPECTION_NOT_FOUND` |
| 해당 검사에 Heatmap 이 없음 | 404 | `HEATMAP_NOT_FOUND` (`"Heatmap 이 없습니다."`) |

| 항목 | 규격 |
|---|---|
| 대상 | ANOMALY, `status: "SUCCESS"` 일 때만 — 정상 판정(`abnormal: false`)에도 있다. `RECEIVED`·`FAILED`·다른 유형은 `heatmap_url` 키가 없다 |
| 시점 | `POST /inspections` 응답을 받을 때 이미 받을 수 있다. 추론과 같은 요청 안에서 만든다 |
| 내용 | **원본 위에 색 지도를 겹친 완성 이미지**다. 색 지도의 불투명도는 0.45 — 결함 자리가 색으로 보이고 제품 모양은 그대로 보인다. Client 가 합성할 필요가 없다 |
| 크기 | **서버가 받은 원본(EXIF 방향 적용)과 같은 가로·세로 Pixel** — 원본과 바꿔 보여도 위치가 그대로다 |
| Content-Type | `image/jpeg`(품질 90). 개발 서버 1448×1086 실측 약 150~170 KB |
| 색 | jet 컬러맵. **색 기준은 그 검사 응답의 `threshold`(T) 고정이다** — 0.5T 이하 파랑, T 초록, 1.5T 이상 빨강(이미지마다 다시 맞추지 않는다). 정상 이미지는 거의 전체가 옅은 파랑이고 결함 부위만 노랑~빨강이다. **색은 판정 기준이 아니다.** 판정은 `abnormal` 로만 한다 |
| 만들지 못했을 때 | 추론 서버가 Heatmap 을 주지 않았거나 이미지를 만들지 못하면 판정은 그대로 `SUCCESS` 이고 `heatmap_url` 만 없다 |
| 보관 | 검사 기록과 같다. 서버 관리 화면에서 그 검사 이미지를 지우면 Heatmap 도 지워지고 이 경로는 `HEATMAP_NOT_FOUND` 가 된다 |

---

## 9. `GET /api/v1/overlays/{inspection_item_id}`

인증 필요. Camera Preview 위에 얹어 작업자가 부품을 같은 위치에 놓도록 돕는 이미지다.

```json
HTTP 200
{
  "data": {
    "inspection_item_id": 604,
    "version": 1,
    "visible": true,
    "opacity": 1.0,
    "image": "/api/v1/overlays/604/image"
  }
}
```

**키 이름은 `image` 다** — `image_url` 이 아니고, `updated_at` 도 없다.

- **가이드는 Camera 촬영 영역 전체를 덮는다.** 위치·크기 필드가 없다. 가이드 이미지를 촬영 영역에 맞춰 그대로 늘려 그린다.
  기준은 **실제 Camera 이미지 영역**이며 Widget 테두리·툴바·Letterbox 영역이 아니다
- 가이드 안에서 부품이 놓일 자리는 **가이드 이미지 자체가** 정한다. 촬영 영역과 같은 화면비로 만든다 — 화면비가 다르면 늘어나 보인다
- `opacity` 는 `0.0`~`1.0`
- `visible: false` 면 그리지 않는다(설정은 남긴 채 잠시 끈 상태). 서버는 이 경우 **이 경로와 §9-1 이미지 경로 모두 404
  `OVERLAY_NOT_FOUND`** 로 답하고, 카탈로그에는 `{"available": false, "version": null}` 로 나간다(§5)
- Overlay 가 없는 검사항목도 404 `OVERLAY_NOT_FOUND`(`"Overlay 가 없습니다."`)다. 매번 404 를 받지 않으려면 카탈로그의 `overlay.available` 을 먼저 본다
- 카탈로그에 있는 검사항목만 부른다. 중지된 검사항목은 카탈로그에서 빠지지만 그 id 로 부르면 Overlay 가 응답할 수 있다
- 등록·수정은 서버 관리 화면에서 한다

**지금 등록된 Overlay** — 개발 서버의 데모 검사항목 셋 모두에 녹색 외곽선만 있는 투명 PNG(`version: 1`, `visible: true`,
불투명도 1.0)가 있다. 이 가이드는 **데모 표본 사진(1448×1086, 4:3)에 맞춘 외곽선**이다 — 데모·연동 시험용으로
그대로 둔다(§15 R19 §4-4). 현장 검사항목의 가이드는 현장 카메라 사진(2448×2048)으로 만든다(R22 §5-1).

### 9-1. `GET /api/v1/overlays/{inspection_item_id}/image`

응답의 `image` 가 가리키는 실제 이미지다(`200`, `Content-Type: image/png` — 등록한 파일에 따라 `image/jpeg`).

- URL 에 `version` 쿼리가 **붙지 않는다.** `Cache-Control` 헤더도 **없다**
- 따라서 **URL 을 캐시 키로 쓰면 Overlay 가 바뀌어도 갱신되지 않는다.** 캐시한다면 §9 응답의 `version` 값을 키에 넣는다
- 파일이 없거나 Overlay 가 `visible: false` 면 404 `OVERLAY_NOT_FOUND`. 이 경로의 `message` 는 `"Overlay 이미지가 없습니다."` 다

---

## 10. 배포물 — LGPL 대응 소스와 Client 배포본 (인증 없음)

```text
GET /api/v1/licenses/sources            Qt/PySide6 LGPLv3 대응 소스 목록
GET /api/v1/licenses/sources/{filename}
GET /api/v1/client-packages             Client 배포 zip 목록
GET /api/v1/client-packages/{filename}
```

**의도적으로 인증이 없다.** 대응 소스를 받을 권리는 바이너리를 받은 사람 전부에게 있어 API Key 를 요구하면 그 자체가
LGPL 의무 이행에 조건을 다는 셈이고, 설치 전 검사 PC 에는 Key 가 없다. 내부망 한정은 **서버 방화벽**이 지킨다.

### 10-1. 목록

두 목록은 형식이 같다. 아래는 `client-packages` 다. 최신 배포본 하나만 둔다.
`licenses/sources` 에는 `SHA256SUMS.txt`·`pyside-setup-everywhere-src-6.11.2.tar.xz`·`qt-everywhere-src-6.11.2.tar.xz`(약 1 GB)가 있다.

```json
HTTP 200
{
  "data": [
    {"filename": "SHA256SUMS.txt", "size_bytes": 113, "sha256": null,
     "download_url": "/api/v1/client-packages/SHA256SUMS.txt"},
    {"filename": "VisionInspectionClient-0.7.0-beta-20261026.zip", "size_bytes": 84848580,
     "sha256": "aedddfb38e87647d2dd7f5dd83bbef304dc9a56a83914a2d165cb48be24d1126",
     "download_url": "/api/v1/client-packages/VisionInspectionClient-0.7.0-beta-20261026.zip"}
  ]
}
```

- **`sha256` 은 서버가 계산한 값이 아니라 같은 폴더 `SHA256SUMS.txt` 에 적힌 값이다.** 1 GB 아카이브를 요청마다 해싱하면 목록 조회가 수 초씩 걸린다
- 기록이 없으면 `null` 이다. `SHA256SUMS.txt` 자신도 목록에 나오며 자기 해시는 `null` 이다
- 폴더 **바로 아래 파일만** 나온다. 하위 폴더는 공개하지 않는다. 파일명 오름차순이다
- 폴더가 비어 있거나 없으면 `{"data": []}` 다(500 이 아니다)

### 10-2. 다운로드와 이어받기

`200` 에 `Accept-Ranges: bytes`·`Content-Disposition: attachment; filename="..."` 가 붙는다. `Range` 를 지원한다.

```text
GET /api/v1/licenses/sources/qt-everywhere-src-6.11.2.tar.xz
Range: bytes=1000-1015

HTTP 206
Content-Type: application/octet-stream
Content-Range: bytes 1000-1015/1019661552
Content-Length: 16
Accept-Ranges: bytes
Content-Disposition: attachment; filename="qt-everywhere-src-6.11.2.tar.xz"
```

- **단일 범위만** 지원한다 — `bytes=N-`, `bytes=N-M`, `bytes=-N`. `curl -C -` 와 브라우저 이어받기가 쓰는 형태다
- **다중 범위**(`bytes=0-1,5-6`)는 `multipart/byteranges` 를 만들지 않고 **200 으로 전체**를 보낸다. 해석할 수 없는 `Range` 도 200 전체다
- 범위가 파일 밖이거나, 끝이 시작보다 앞이거나(`bytes=5-3`), `bytes=-0` 이면 416 이다

```json
HTTP 416
Content-Range: bytes */1019661552
{"error": {"code": "RANGE_NOT_SATISFIABLE", "message": "요청한 범위가 파일 밖입니다.", "retryable": false}}
```

- 없는 파일은 404 `SOURCE_ARCHIVE_NOT_FOUND`(`"보관 중인 파일이 아닙니다."`)다. `client-packages` 쪽은 `CLIENT_PACKAGE_NOT_FOUND` 다
- 경로 이탈(`..`, `..%2F...`)도 404 다 — 파일명을 경로로 조립하지 않고 목록에서 이름이 같은 파일을 찾으므로 폴더 밖으로 나가는 요청은 목록에 없다
- 운영 서버에서는 전송을 nginx 가 한다. 응답 코드·`Range`·`Content-Disposition` 은 같고 `Content-Type` 은 확장자에 따라 정해질 수 있다

받은 뒤 대조:

```bash
curl -OJ   http://10.10.10.20:8123/api/v1/licenses/sources/SHA256SUMS.txt
curl -C -  -OJ http://10.10.10.20:8123/api/v1/licenses/sources/qt-everywhere-src-6.11.2.tar.xz
sha256sum -c --ignore-missing SHA256SUMS.txt
```

### 10-3. 보관 기간

LGPL 대응 소스 3개는 **마지막 배포 후 3년간** 보관한다. 검사 이미지 보존 정책과 **무관한 경로**에 있고 자동 삭제 작업이
닿지 않는다. **사외(고객사)에서 이 경로에 닿는지는 아직 결정되지 않았다**(§16 질문 3). 현재 주소는 내부망이라 사외에서 닿지 않는다.

### 10-4. 이 주소는 고지문에 박혀 있다

Client 0.1.4·0.1.5 배포본의 LGPL 고지문에 `http://10.10.10.20:8123/api/v1/licenses/sources` 가 들어 있다.
**host·port·경로를 바꾸면 Client 재빌드·재배포가 필요하므로, 서버는 바꾸기로 결정되면 즉시 알린다.**
평문 포트를 닫더라도 이 경로는 리다이렉트를 남긴다.

---

## 11. 오류 코드 전체

### 11-1. 공통

| HTTP | `error.code` | `retryable` | 언제 |
|---|---|---|---|
| 401 | `AUTH_REQUIRED` | false | 인증 헤더 누락 |
| 401 | `AUTH_INVALID` | false | 없는 Client / 키 불일치 / 비활성 |
| 404 | `NOT_FOUND` | false | **`/api/v1` 아래 없는 경로** |
| 405 | `METHOD_NOT_ALLOWED` | false | 그 경로가 받지 않는 메서드(예: `GET /inspections`). `Allow` 헤더에 받는 메서드가 있다. 인증이 필요한 경로는 인증을 먼저 본다 — 인증 없이 보내면 401 이다 |
| 411 | `LENGTH_REQUIRED` | false | `Content-Length` 없음 |
| 413 | `IMAGE_TOO_LARGE` | false | `image` 파트 32 MiB·본문 33 MiB 초과(§2-3) |
| 500 | `INTERNAL_ERROR` | **true** | 처리되지 않은 서버 오류 |

```json
HTTP 404
{"error": {"code": "NOT_FOUND", "message": "없는 경로입니다.", "retryable": false}}
```

### 11-2. Endpoint 별

| HTTP | `error.code` | 어디서 |
|---|---|---|
| 404 | `INSPECTION_ITEM_NOT_FOUND` | `POST /inspections` — 없거나 비활성 검사항목 |
| 409 | `REQUEST_ID_CONFLICT` | `POST /inspections` — 다른 Client 가 쓴 `request_id` |
| 422 | `IMAGE_REQUIRED` | `POST /inspections` — `image` 파트 없음 |
| 422 | `METADATA_INVALID` | `POST /inspections` — JSON 파싱 실패·객체 아님·필수 필드 누락·형식 오류·길이 초과 |
| 422 | `IMAGE_INVALID` | `POST /inspections` — 디코딩 실패·미지원 형식·30 MiB 초과·해상도 초과 |
| 422 | `MEASUREMENT_INVALID` | `POST /inspections` — 치수 측정 항목의 `measurements` 가 측정점과 맞지 않음(§6-6) |
| 404 | `INSPECTION_NOT_FOUND` | `by-request`, `heatmap` — 없거나 남의 것 |
| 404 | `HEATMAP_NOT_FOUND` | `heatmap` — Heatmap 없음 |
| 404 | `OVERLAY_NOT_FOUND` | `overlays`, `overlays/image` — 없거나 `visible: false` |
| 404 | `SOURCE_ARCHIVE_NOT_FOUND` | `licenses/sources/{f}` |
| 404 | `CLIENT_PACKAGE_NOT_FOUND` | `client-packages/{f}` |
| 416 | `RANGE_NOT_SATISFIABLE` | 배포물 다운로드 — 범위가 파일 밖·끝이 시작보다 앞·`bytes=-0`(§10-2) |

### 11-3. 재시도 판단

**`retryable: true` 로 나가는 응답은 `500 INTERNAL_ERROR` 하나뿐이다.**

- `429`·`503`·`504` 를 **서버가 내는 일은 없다**
- `GET /api/v1/health` 의 503 은 오류 봉투가 아니다. 재시도 판단에 쓰지 않는다(§4)
- 앞단에 리버스 프록시를 두면 프록시가 **봉투 없는** 5xx 를 낼 수 있다. 봉투 없는 5xx·연결 실패·timeout 을 재시도 대상으로 두는 현재 Client 동작이 맞다
- 401 은 봉투와 무관하게 재전송하지 않는다 — 현재 Client 동작이 맞다

---

## 12. 이미지 보존

**서버는 검사 이미지를 자동으로 지우지 않는다.** 보존 기간 정책이 없다 — 검사 이미지는 데이터 관리(라벨링·학습 데이터)와
같은 파일 한 벌이라, 기간으로 지우면 데이터셋이 깨진다. 관리자가 화면에서 이미지를 지울 수는 있다.

보존 정책을 도입하게 되면 그 전에 `IMAGE_EXPIRED` 같은 응답 규격을 이 문서에 먼저 추가한다.
**Client 가 이미지를 오래 보관해야 하면 서버에 의존하지 말고 직접 받아 둔다.**

---

## 13. 현재 서버 상태 (Client 가 알아야 하는 제약)

| 항목 | 상태 |
|---|---|
| **추론** | Wezard 로 연결돼 있다. 모델이 매핑되고 배포된 검사항목만 `SUCCESS`·판정이 나오고, 나머지는 `RECEIVED` 다(§6-3). Heatmap 은 이상 탐지 `SUCCESS` 에 있다(§8). health 에 `components.gpu` 를 넣지 않는다(§4) |
| **NEOCON C2 검사항목**(2026-10-20 추가) | 고정 거치대 `VIS-CLN` Cleaning 오염도(분류, 1~10단계 — 1~2단계 정상)·`VIS-ROT-SF` Rotor 표면 결함(이상 탐지)·`VIS-ROT-DIM` Rotor 치수(치수 측정). 태블릿 촬영 검사항목(`TAB-`)은 카탈로그에 나오지 않는다. **모델은 아직 매핑하지 않았다** — 치수 측정 말고는 `RECEIVED` 다. 각 `description` 에 촬영 방식·판정 기준이 있다 |
| **개발 서버 모델** | 세 검사항목 모두 매핑돼 있다 — `FAN-PANEL` `fan-panel` v3(임계값 33.26) · `FAN-PANEL-CLS` `fan-panel-cls` v3 · `FAN-PANEL-DET` `fan-panel-det` v4(신뢰도 임계값 0.7) |
| **모델 품질** | 개발 서버 모델은 연동 시험용이고 학습 데이터가 적다. §15 표본은 대부분 맞히지만 **처음 보는 이미지에서는 보장하지 않는다.** 추론 서버의 권고: 결함 여부는 이상 탐지(`FAN-PANEL`) 결과를 기준으로 보고, 객체 탐지는 결함 위치 표시, 분류는 보조 정보로 쓴다. 판정이 틀려 보이면 모델 문제이지 연동 문제가 아니다 |
| **TLS** | **없다.** 개발 서버는 평문 HTTP 다. 인증 헤더와 촬영 원본이 평문으로 오간다. 운영 서버를 세울 때 정한다(§16) |
| **DEBUG** | **켜져 있다.** 개발 서버로 유지하기로 했다. 단 `/api/v1` 아래는 404 봉투로 답하므로 DEBUG 페이지가 나오지 않는다 |
| rate limit | 없다 |
| CORS | 설정하지 않았다(브라우저에서 호출하는 API 가 아니다) |
| 분류(CLASSIFICATION) 검사항목 | `?include=classification` 을 줄 때만 카탈로그에 나온다(§5) |
| 치수 측정(MEASUREMENT) 검사항목 | `?include=measurement` 를 줄 때만 카탈로그에 나온다(§5). 모델 없이 측정값으로 판정한다(§6-3). 개발 서버에는 `VIS-ROT-DIM`(id 1803, 측정점 A·B·C, Overlay 없음)이 있다 |
| 태블릿 촬영 검사항목 | `TAB-` 로 시작하는 검사항목(I-Marking·안전라벨·Rotor 설치·단자 등)은 현장 태블릿에서 디지털 양식으로 찍어 모으는 학습용이다. **카탈로그에 나오지 않는다**(2026-10-21, §5) |
| 검사항목 묶음 | 없다. 유형별 검사항목은 서로 독립이다(§6-7) |

---

## 14. 이전 계약(Client 저장소, 2026-10-01)과 다른 점

Client 0.1.5 에서 모두 반영해 지웠다(7개 — 식별자 `id`, 판정 키 항상 있음, Overlay `image`, 422 오류 코드, 상한, 공정·제품 검증
없음, 제공하지 않는 기능). 내용은 이 문서의 git 이력에 있다.

---

## 15. 요청 처리 결과

### 열린 요청

| # | 요청 | 처리 | 내용 |
|---|---|---|---|
| R19 §4-1 | 검사항목 묶음 필드 | **보류** | 검사항목을 묶는 체계를 서버에서 먼저 정해야 한다. 정하면 카탈로그 필드를 이 문서로 먼저 알린다. 그때까지 §6-7 그대로다 |
| R22 §5-1 | `VIS-ROT-DIM` 가이드(Overlay) | **진행 중** | 거치대에 실물 Rotor 를 놓고 현장 카메라(2448×2048)로 찍은 사진으로 만든다. 거치대 설치 뒤 등록하고 이 표로 알린다. 그때까지 `overlay.available: false` 다 |

### 끝난 요청

자세한 회신은 이 문서의 git 이력에 있다.

| # | 회신 | 처리 |
|---|---|---|
| R22 §1~4 | 2026-10-21 | 치수 측정 반영 계획 확인 — 측정 창에서 작업자가 두 점을 찍고, 기준물로 사진마다 배율을 구하며, `calibration` 은 항상 보낸다. 측정점 `description` 은 도면을 받으면 서버가 채운다. `calibration` 필수화는 그 빌드가 배포된 뒤 정해 이 문서로 먼저 알린다. 정확도(±1mm ≈ ±3.5화소)는 현장 시험 촬영으로 함께 확인한다 |
| R22 §5-2 | 2026-10-21 | 태블릿 항목 거르기 — 필드 대신 **서버가 카탈로그에서 뺀다**(§5). Client 는 고칠 것이 없다 |
| R19 §4-4 | 2026-10-21 | Overlay 화면비 — 냉각팬 패널 세 검사항목(`FAN-PANEL`·`-CLS`·`-DET`)은 데모 표본 사진(1448×1086) 기준 가이드를 **그대로 둔다**(데모·연동 시험용). 현장 검사항목의 가이드는 현장 카메라 사진(2448×2048)으로 만든다(R22 §5-1) |
| R1~R9 | 1차(2026-10-03) | 모두 종결(Client 확인). R1 TLS 는 §16 질문 1·2, R3 LGPL 보관 주체는 §16 질문 3 |
| R10 | 2차(2026-10-06) | 0.1.4 를 내리고 0.1.5 를 올렸다 |
| R11 · R12 | 2차 | 판정 필드 형식 확정(§6-3) · `RECEIVED` 는 A안 — 추론은 POST 안에서 끝낸다(§6-5) |
| R13 | 2차 | §16 질문 5·6·7 종결. 1~4 는 운영 서버를 세울 때 정한다 |
| R14 · R18 | 2차 | Overlay 실측 데이터, 계약 보완 — 숨긴 Overlay 는 카탈로그 `{available: false, version: null}`(§5·§9) |
| R15 · R16 · R17 | 2차 | 새 자격증명 확인 · `metadata` 길이 초과 500 → 422 `METADATA_INVALID`(§6-6) · 실측 데이터 정리 |
| R19 §3 · §4-2 · §4-3 · §4-5 · §4-6 | 3차(2026-10-13) | `inference_ms` 확인 · `defects[].name` 추가(§6-3) · 결함 표본 전달(아래) · 실측 기록 삭제 · 0.1.7 반입(아래 R21) |
| R20 | 3차 | 이상 탐지 Heatmap(§8) · 객체 탐지 박스(§6-2) |
| R21 | 2026-10-15 | 5차 반영 보고 — 실측 9건 모두 기대 결과와 같음. 0.1.7(`593f78d0…`, 84,826,730 bytes) 반입·해시 확인 종결. 실측 기록 9건과 그 이미지·파일 삭제(`by-request` 로 다시 조회하면 404 `INSPECTION_NOT_FOUND`) |

### 결함 표본과 기대 결과

데모 표본 zip 의 사진 3장이다(R19 §4-3). 1448×1086 PNG, EXIF 없음. 모델이 다시 배포되면 이 표로 다시 확인한다.

| 파일 | 크기 | SHA-256 |
|---|---|---|
| `fan-panel-defect-2.png` | 2,009,989 bytes | `1f0c5cc09490e3cc9c2076e6bcd81c47621c924384f0893b4ed437aa487643c0` |
| `fan-panel-defect-12.png` | 1,812,820 bytes | `4a1d0737e5ed1b2a28cf2c907e5b2d033093b56bbf669d1443d93429c098a326` |
| `fan-panel-normal-4.png` | 1,851,218 bytes | `dd2159118bb393ed98347f6d789babc339362fc08c04d6e12739341e64ac6488` |

Client 의 파일 검사는 JPEG 로 다시 인코딩해 보낸다. 아래는 JPEG(품질 95)로 바꿔 잰 값이다
(개발 서버 2026-10-13, `fan-panel` v3 · `fan-panel-cls` v3 · `fan-panel-det` v4).

| 표본 | `FAN-PANEL` 이상 탐지 | `FAN-PANEL-CLS` 분류 | `FAN-PANEL-DET` 객체 탐지 |
|---|---|---|---|
| `defect-2` | **이상** 49.97 / 33.26. Heatmap 결함 자리 노랑~빨강 | **이상** `불량` 1.00 | **이상** 박스 8개 — `scratch`(`스크래치`) 7·`missing_screw`(`나사 누락`) 1, 신뢰도 0.98~1.00 |
| `defect-12` | **이상** 50.44 / 33.26. Heatmap 왼쪽 아래 긁힘 자리 노랑~빨강 | **정상** `정상` 0.56 — 경계에 있는 표본이다. PNG 그대로 보내면 `불량` 0.67 | **이상** 박스 1개 `scratch` 0.94, 약 `{x1: 229, y1: 484, x2: 594, y2: 1082}`(PNG 로는 §6-2 예시) |
| `normal-4` | 정상 22.96 / 33.26. Heatmap 거의 전체 옅은 파랑 | 정상 `정상` 0.99 | 정상, 박스 없음 |

- 세 검사항목의 결함 경로를 모두 보려면 `defect-2` 를 쓴다. 박스 1개로 위치를 보기 쉬운 것은 `defect-12` 다
- 점수·확률·좌표는 인코딩(품질)에 따라 조금 달라진다. 모델이 다시 배포되면 바뀔 수 있다 — 그때는 `model.version` 이 다르다
- 이 표본은 대부분 학습에 쓰인 사진이다. 처음 보는 사진의 판정 품질은 §13 모델 품질

---

## 16. 서버가 되돌려 보내는 질문

운영 서버를 세울 때(TLS·`DEBUG=False`·Key 재발급과 같은 일정) 정해 이 문서로 알린다. 질문 5·6·7 은
R13 답으로 종결했다(§6-3·§6-5·§4·§3-2).

| # | 질문 | 누가 결정 | 왜 급한가 |
|---|---|---|---|
| 1 | **TLS 인증서 방식** — 공인 / 사내 CA / 자체 서명 | 인프라 | **사내 CA·자체 서명이면 CA PEM 을 Client 에 전달해야 하고 Client 코드 변경이 필요하다**(`certifi` 번들만 보므로 Windows 인증서 저장소 설치로는 안 된다). IP 접속이면 SAN 에 `IP:<서버 IP>` 를 넣는다 |
| 2 | **운영 최종 주소와 컷오버 일정** | 인프라 + Client | **`licenses/sources` 주소가 0.1.5 고지문에 박혀 있다**(§10-4). 바뀌면 재빌드다 |
| 3 | **LGPL 소스를 사외에 공개할 것인가** — 외부 공개 경로 vs written offer / 3년 보존을 운영 정책 문서에 올릴 주체 | 법무 + 운영 | 공개하기로 하면 질문 1·2 와 같은 일정으로 묶어야 한다 |
| 4 | **인증 실패 rate limit·계정 잠금 도입 여부** | 인프라 | 현재 없다 |

---

## 17. 변경 이력

최근 판만 적는다. 그 전 이력(2026-10-01 ~ 2026-10-13 4차 전달)은 이 문서의 git 이력에 있다.

| 날짜 | 변경 |
|---|---|
| 2026-10-27 | **문서 정정**(응답·동작은 그대로) — R19 §4-4(2026-10-21 종결)를 열린 요청·§9 가이드 설명에서 바로잡았다(§0·§9) |
| 2026-10-26 | Client 0.7.0 반입(`aedddfb3…1126`, 84,848,580 bytes) — §10-1 예시를 0.7.0 실제 응답으로, 0.1.8 을 내렸다 |
| 2026-10-22 | Client 0.1.8 반입(`34a16265…ea19`, 84,850,271 bytes) — §10-1 예시를 0.1.8 실제 응답으로, 0.1.7 을 내렸다 |
| 2026-10-22 | **문서 정정**(응답·동작은 그대로) — health 예시 `version` 을 `1.1.0` 으로(§4), 6차 전 응답 예시 3개에 `"measurements": null`(§6-2·§6-3), 객체 탐지 임계값 설명을 모델 매핑 기준으로(§6-3), 태블릿 검사항목은 개수 대신 `TAB-` 로(§0·§13) |
| 2026-10-21 | **R22 회신**(응답 모양·오류 코드는 그대로). 태블릿 촬영 검사항목(`TAB-`)을 카탈로그에서 뺐다(§0·§5·§13). R19 §4-4 종결 — 냉각팬 패널 가이드는 유지. `VIS-ROT-DIM` 가이드는 거치대 설치 뒤(§15) |
| 2026-10-20 | **6차 전달 — 치수 측정(`MEASUREMENT`) 유형**(서버 1.1.0). 카탈로그 `include=measurement`·`measurement_points`(§5·§5-1), `metadata.measurements`·`calibration`(§6-1), 응답 `measurements`·판정 규칙(§6-3), 422 `MEASUREMENT_INVALID`(§6-6·§11-2). `include` 는 쉼표로 여러 값을 받는다. 다른 유형은 응답에 `measurements: null` 이 늘었을 뿐이다. R19 §4-4 에 현장 카메라를 적었다(§15). 개발 서버의 NEOCON C2 검사항목 7개(§13) |
| 2026-10-19 | **`metadata` 검증을 이 문서대로 맞췄다**(응답 모양·오류 코드는 그대로, 정상 요청은 영향 없음) — `inspection_item_id` 의 소수·참거짓, 객체가 아닌 `camera`(`[]`·`""`·`0`·`false`), 깨진 multipart 본문이 422 `METADATA_INVALID`(재시도 안 함)다. 전에는 소수는 버림·참거짓은 1/0 으로 읽었고, 빈 비객체 `camera` 는 통과, 깨진 multipart 는 500 `INTERNAL_ERROR`(재시도)였다(§6-1·§6-6). 문서 정정 — `request_id` 는 길이만 검사(§6-1), 416 이 나는 `Range`(§10-2·§11-2), 405 보다 인증을 먼저 봄(§11-1) |
| 2026-10-15 | **문서 정리**(응답·동작은 그대로) — 끝난 회신·지난 변경(§0·§14·§15·§17)과 겹치는 예시(§3·§6·§7·§10)를 줄였다. 경로·필드·오류 코드·메시지·한도·규칙은 바꾸지 않았다. 절 번호는 그대로다. §0 의 5차 Client 할 일 1·2 를 완료로(R21 회신) |
| 2026-10-15 | R21 회신 — 0.1.7 해시 확인 종결, 실측 기록 9건 삭제(§15). 문서 정정 — `RECEIVED`(§6-5)·`model`(§6-3)에 "매핑한 모델을 서버에서 쓰지 않게 해 둠"을 더하고 §1·§3 인증 범위를 "§1 의 인증 필요 경로"로 좁혔다 |
| 2026-10-14 | Client 0.1.7 반입 — §10-1 예시를 0.1.7 실제 응답으로, 0.1.6 을 내렸다 |
| 2026-10-13 5차 전달 | R19·R20 회신. **`defects[].name`**(라벨 표시 이름) 추가(§6-3). 이상 탐지 Heatmap 제공(§8, 색 기준은 응답 `threshold` 고정). 개발 서버 모델 교체와 객체 탐지 박스 실제 응답(§6-2). Overlay 가이드의 기준 화면비(§9), 모델 품질(§13), 결함 표본과 기대 결과(§15). 기존 키·오류 코드·경로는 그대로다 |
