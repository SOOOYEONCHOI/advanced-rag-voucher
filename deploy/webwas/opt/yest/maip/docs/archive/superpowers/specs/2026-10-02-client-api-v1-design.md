# Client `/api/v1` 요청 9건 대응 — 설계

> 기준일 2026-10-02 · 요청서 [docs/client/SERVER_REQUESTS.md](../../client/SERVER_REQUESTS.md) R1~R9
> 계약 [docs/client/SERVER_API_CONTRACT.md](../../client/SERVER_API_CONTRACT.md) · 구 서버 소스 `tmp/vision_inspection_server/`(참조 전용)

VisionInspectionClient 0.1.4 가 `http://10.10.10.20:8123` 에서 **인증을 통과하지 못해
카탈로그를 받지 못하고, 촬영·검사가 불가능하다.** 배포·라이선스 경로가 없어 0.1.4 배포본도
보류돼 있다. 이 문서는 그 9건 중 **서버 코드로 고칠 5건(R5~R9)** 의 설계이며, 확인만 필요한
R2·R3·R4 와 운영 영역인 R1 은 회신 문서로 닫는다.

## 1. 실측 9건의 코드상 원인

| # | 원인 | 위치 |
|---|---|---|
| R5 | `_authenticate()` 가 모든 실패에 `None` 을 돌려 `AUTH_REQUIRED` 하나로 뭉갠다. 자격증명은 `seed_demo` 가 만든 `CLIENT-001` + 그때 출력된 키만 유효하고, 구 서버(`:8005`) 키는 해시가 달라 영구히 통과하지 못한다. 발급·재발급 화면은 이미 있다 | `app/views/api_v1.py:103`, `app/views/vision/client.py` |
| R6 | 라우트 없음. `/api/v1/client-packages` 는 2-segment 라 범용 `api/<task>/<view>` 가 받아 401 HTML, `/api/v1/licenses/sources` 는 3-segment 라 Django 기본 404 HTML | `configurations/urls.py:49-57`, `:71` |
| R7 | 라우트 없음 + heatmap 을 담을 컬럼도 없다. `InferenceGateway` 가 Stub 이라 heatmap 이 생길 경로 자체가 없다 | `domain/models/vision.py`, `domain/services/vision/gateway.py` |
| R8 | `HealthView` 가 `{"data":{status, server_time}}` 를 낸다. 계약은 최상위 `status`·`components`·`version`·`timestamp` + 실패 시 503 | `app/views/api_v1.py:120-127` |
| R9 | `/api/v1` catch-all 이 없어 미지 경로가 봉투를 못 쓴다. `Content-Length` 검사 지점이 없다. DEBUG 노출은 `.env` 문제 | `configurations/urls.py` |

## 2. 결정

| # | 결정 | 근거 |
|---|---|---|
| DEC-C1 | 신규 코드는 **`app/views/api_v1.py` 한 파일**에 전부 둔다(최종 약 600줄) | 사용자 결정. 부수 이득 — `verify_permission_map.py` 는 `app/views/` 하위 **디렉터리만** 훑으므로(`:41-42`) 최상위 모듈인 이 파일은 권한 매핑 등록 대상이 아니다 |
| DEC-C2 | `/api/v1` 응답 필드·오류 코드는 **서버 현 구조를 정본**으로 두고 Client 가 맞춘다 | 사용자 결정. 0.1.4 는 R6 때문에 배포 보류 중이고 사내 베타 0.1.0~0.1.3 은 구 서버 `:8005` 를 쓴다 → **현장에 `:8123` 응답을 파싱하는 배포본이 없다** |
| DEC-C3 | health 는 **계약 형식으로 되돌린다** | DEC-C2 의 예외다. `components`·`version` 은 서버가 알려줄 가치가 있는 정보이고, Client 연결 테스트 화면이 그것을 읽는다 |
| DEC-C4 | HTTP Range 를 **Django 뷰에서 직접 구현**한다 | Django 5.0.4 에는 Range 처리가 **전혀 없다**(`HTTP_RANGE`·`Content-Range` 문자열이 패키지 전체에 없음). nginx 에 맡기면 개발·운영 동작이 갈린다 |
| DEC-C5 | heatmap 은 **라우트만** 만든다. 저장 컬럼·마이그레이션 없음 | GPU 가 Stub 이라 heatmap 이 생기지 않는다. `heatmap_url` 을 응답에 넣지 않으므로 Client 는 호출하지 않는다. 라우트는 "경로가 비어 404 HTML" 을 없애기 위한 것 |
| DEC-C6 | 배포물은 **저장소 루트 `distribution/`** 에 둔다 | `app/static/` 은 앱 static 디렉터리라 `collectstatic` 이 1.07GB 를 `STATIC_ROOT` 로 복사하고, whitenoise 가 `/static/distribution/...` 로 **같은 파일을 두 번째 경로로** 내보낸다 |
| DEC-C7 | `:8123` 은 **개발 서버로 남긴다.** `DEBUG=False`·TLS 는 별도 운영 인스턴스의 과제 | 사용자 결정(D1·D2) |
| DEC-C8 | rate limit(429)·`meta.count`·`CLIENT_VERSION_UNSUPPORTED` 는 **제공하지 않음으로 확정** | 요청서에 없고 Client 는 없어도 동작한다. 계약 문서에서 삭제하도록 회신 |
| DEC-C9 | `RECEIVED` 무한 폴링은 **회신으로만** 알린다 | GPU 미연결 상태에서 `RECEIVED` 는 종결 상태다. 구분 필드를 늘리면 Client 도 바꿔야 하므로 GPU 연결 시 함께 한다 |
| DEC-C10 | `APP_VERSION = '1.0.0'`, 운영 반입 경로 `/var/lib/manufacturing-ai-platform/distribution` | 사용자 결정(D6·D7) |

## 3. 공통 기반 — `ClientApiView`

### 3.1 테넌트 플래그

`use_tenant` 클래스 속성을 더한다(기본 `True`). `False` 면 `tenant_atomic()` 밖에서 실행한다.

health 와 downloads 4개가 `False` 다. 둘 다 테넌트 데이터를 읽지 않는다. **이 플래그가 없으면
health 가 DB 장애 때 503 이 아니라 500 을 낸다** — 현재 `dispatch` 가 모든 예외를
`INTERNAL_ERROR` 로 바꾸고 `tenant_atomic()` 진입 자체가 DB 를 쓰기 때문이다.

### 3.2 인증 오류 구분 (R5)

`_authenticate()` 가 `(client, error_code)` 를 돌려준다.

| 상황 | HTTP | `error.code` |
|---|---|---|
| 두 헤더 중 하나라도 없음 | 401 | `AUTH_REQUIRED` |
| `X-Client-ID` 가 없는 Client | 401 | `AUTH_INVALID` |
| `X-API-Key` 불일치 | 401 | `AUTH_INVALID` |
| `active=False` | 401 | `AUTH_INVALID` |

구분은 **응답 코드에서만** 한다. 로그에는 `client_id` 와 실패 사유만 남기고 **API Key 는 어떤
형태로도 기록하지 않는다**(마스킹한 값도 남기지 않는다). 상수 시간 비교(`hmac.compare_digest`)는
현행 유지.

### 3.3 요청 선검사 — 인증보다 먼저 (R9-2)

`dispatch` 의 인증 **앞에** 가드를 둔다. 모든 `/api/v1` 뷰가 이 클래스를 거치므로 한 곳이면 전부 덮는다.

- `POST`/`PUT` 에 `Content-Length` 없음(chunked) → **411 `LENGTH_REQUIRED`**
- `Content-Length` 가 서버 상한 초과 → **413 `IMAGE_TOO_LARGE`**

상한은 현행 `MAX_IMAGE_BYTES`(32MiB) + multipart 여유 1MiB 를 쓴다. 숫자를 따로 적지 않고
기존 상수에서 계산한다 — 상수를 올렸을 때 이 가드가 먼저 막으면 원인을 찾기 어렵다.

### 3.4 미지 경로 404 봉투 (R9-1)

`urls.py` 의 범용 `api/<task>/<view>` **앞에** `path('api/v1/<path:rest>', V1NotFoundView)` 를 넣는다.
**순서가 핵심이다** — 뒤에 두면 `client-packages` 가 계속 401 HTML 을 받는다.
응답은 404 `NOT_FOUND`, `retryable: false`. `require_auth=False`·`use_tenant=False`.

위치는 **구체 `api/v1/...` 라우트 전부 뒤, 범용 `api/<task>/<view>` 앞** 이다. Django 는
`urlpatterns` 를 위에서부터 맞추므로 이 사이가 아니면 안 된다 — 앞에 두면 정상 Endpoint 가
전부 404 가 되고, 뒤에 두면 `client-packages` 가 계속 401 HTML 을 받는다.

## 4. Endpoint

### 4.1 `GET /api/v1/health` — 교체 (R8)

```json
{"status":"ok","components":{"database":"ok","storage":"ok"},"version":"1.0.0","timestamp":"2026-10-02T05:56:40.383877Z"}
```

- DB 는 `SELECT 1`, Storage 는 `STORAGE_ROOT/.healthcheck` 쓰기→삭제를 **실제로 수행**한다(구 서버와 같은 방식)
- 하나라도 실패 → **503 + `status:"degraded"`**, 실패 항목만 `"error"`. `components` 에 `"degraded"` 는 쓰지 않는다
- 이 503 은 `/api/v1` 에서 **오류 봉투가 아닌 유일한 응답**이다
- `version` 은 `settings.APP_VERSION`. 플랫폼에 버전 문자열이 아무 곳에도 없어 상수를 새로 둔다. `.env` 로 빼지 않는다 — 환경이 아니라 배포물의 성질이다

### 4.2 `GET /api/v1/inspections/<id>/heatmap` — 신규 (R7)

인증 필요. 소유 확인 후:

| 상황 | 응답 |
|---|---|
| 없는 id 또는 다른 Client 소유 | 404 `INSPECTION_NOT_FOUND` |
| 그 외 (= 현재는 전부) | 404 `HEATMAP_NOT_FOUND` |

`GET /api/v1/inspections/<id>` 는 만들지 않는다 — Client 가 쓰지 않는다(계약 §1).

### 4.3 배포·라이선스 4개 — 신규 (R6)

```text
GET /api/v1/licenses/sources                   DISTRIBUTION_ROOT/licenses/
GET /api/v1/licenses/sources/<filename>
GET /api/v1/client-packages                    DISTRIBUTION_ROOT/client/
GET /api/v1/client-packages/<filename>
```

`require_auth=False`·`use_tenant=False`. 소스를 받을 권리는 바이너리를 받은 사람 전부에게
있고, 설치 전 PC 에는 API Key 가 없다.

**목록** — 두 경로 모두 같은 형식.

```json
{"data":[{"filename":"qt-everywhere-src-6.11.2.tar.xz","size_bytes":1019661552,
          "sha256":"6dcfbca2…","download_url":"/api/v1/licenses/sources/qt-everywhere-src-6.11.2.tar.xz"}]}
```

- 폴더 **바로 아래 파일만**, 이름순. 하위 폴더는 공개 대상이 아니다
- `sha256` 은 같은 폴더 `SHA256SUMS.txt` 에 적힌 값, 없으면 `null`. `SHA256SUMS.txt` 자신도 목록에 나온다. **1GB 파일을 요청마다 해싱하지 않는다**
- `SHA256SUMS.txt` 는 `<해시>  <파일명>` 과 `<해시> *<파일명>` 두 형식을 읽는다
- 폴더가 없으면 빈 목록(500 이 아니다)

**다운로드**

- 경로 이탈 차단은 **구 서버 방식**을 쓴다 — 이름을 경로로 조립하지 않고 **목록에서 이름이 같은 파일을 찾는다.** `../` 가 섞인 이름은 목록에 있을 수 없으니 구조적으로 나갈 수 없다
- `Accept-Ranges: bytes` 를 항상 붙이고 `Content-Disposition: attachment` 로 내려 브라우저가 저장하게 한다
- Range: 단일 범위(`bytes=N-`, `bytes=N-M`)만 — `curl -C -` 가 쓰는 형태다. 206 + `Content-Range: bytes N-M/total`. 범위 밖이면 416 + `Content-Range: bytes */total`. 헤더 없으면 200 전체. **다중 범위는 무시하고 200 전체**로 답한다(multipart/byteranges 를 만들지 않는다)
- 없는 파일 → 404 `SOURCE_ARCHIVE_NOT_FOUND` / `CLIENT_PACKAGE_NOT_FOUND`
- 파일 자체는 서버 담당이 직접 반입한다. 코드가 받아오지 않는다
- 루트는 **요청 시점에 `settings.DISTRIBUTION_ROOT` 를 읽는다.** 모듈 상수로 굳히면
  `override_settings` 가 듣지 않아 §7 의 테스트가 실파일을 보게 된다

## 5. 설정·파일 배치

| 항목 | 값 |
|---|---|
| `settings.APP_VERSION` | `'1.0.0'` |
| `settings.DISTRIBUTION_ROOT` | `Path(env('DISTRIBUTION_ROOT', BASE_DIR / 'distribution'))` |
| 저장소 위치 | `app/static/distribution/` → **`distribution/`** 으로 이동. `git mv` 가 아니라 `mv` 다 — 배포물은 Git 에 없다 |
| Git 에 넣는 것 | 각 폴더의 `SHA256SUMS.txt` 와 `README.md`. 배포물은 **확장자로** 제외한다 |
| 운영 반입 경로 | `/var/lib/manufacturing-ai-platform/distribution` (`DISTRIBUTION_ROOT` 로 지정) |

`.gitignore` 는 **`distribution/` 한 줄로 막지 않는다** — 그러면 Git 에 남겨야 하는
`SHA256SUMS.txt` 와 `README.md` 까지 사라진다. 확장자로 막는다.

```gitignore
distribution/**/*.zip
distribution/**/*.tar.xz
```

`distribution/README.md` 는 구 서버 문서가 그대로 복사돼 `server/distribution/` 과
`/var/lib/vision-inspection/` 을 가리킨다 — 이 프로젝트 기준으로 재작성한다.

## 6. DEC-C2 로 **바꾸지 않는** 것 — 회신에 전부 적는다

| 계약 문서 | 이 서버의 실제 | Client 영향 |
|---|---|---|
| `data.inspection_id` | `data.id` (+ `inspection_item_id` 추가 제공) | **가장 큰 변경** — 0.1.5 파서 수정 |
| overlay `data.image_url`, `updated_at` | `data.image`, `updated_at` 없음 | Overlay 이미지 수신 경로 수정 |
| `VALIDATION_ERROR` 422 (image 파트 없음) | `IMAGE_REQUIRED` 422 | 분기 추가 |
| `INVALID_REQUEST` 400 (디코딩 실패) | `IMAGE_INVALID` 422 | 분기 추가 |
| `UNSUPPORTED_IMAGE_FORMAT` 415 | 없음 — `IMAGE_INVALID` 422 로 묶임 | 분기 추가 |
| 이미지 20MiB / 본문 21MiB | **32MiB** / 35MiB | Client 상한만 넓히면 됨 |
| `429 RATE_LIMITED` | 미구현 | 서버가 내지 않는다 |
| `result_image_url`·`meta.count`·`CLIENT_VERSION_UNSUPPORTED` | 없음 | 계약 문서에서 삭제 |
| `process_id`/`product_id` 정합성 400 | **검증하지 않는다**(§1.6 O-11 합성 공정·제품) | 없음 |

`retryable: true` 를 내는 응답은 **`500 INTERNAL_ERROR` 하나**다(R2-1 의 답). 503·504 는
서버가 내지 않으며, 앞단에 nginx 를 두면 봉투 없는 5xx 로 나올 수 있다(R2-2).

## 7. 검증

`tests/test_client_api.py` 에 TDD(RED → GREEN)로 추가한다. **1GB 실파일은 쓰지 않는다** —
`override_settings(DISTRIBUTION_ROOT=<tmp>)` 에 수십 바이트 가짜 파일과 손으로 쓴
`SHA256SUMS.txt` 를 둔다.

| 대상 | 테스트 |
|---|---|
| 인증 (R5) | 헤더 없음 → `AUTH_REQUIRED` / 틀린 키·없는 `client_id`·`active=False` → `AUTH_INVALID` |
| health (R8) | 200 최상위 4키 / DB 커서 예외 주입 → 503 `degraded` + `database:"error"` / Storage 쓰기 실패 → 503 |
| 404 봉투 (R9) | `/api/v1/nope` → 404 `NOT_FOUND` **JSON 봉투** / `/api/v1/client-packages` 가 범용 라우트에 먹히지 않음 |
| 411 (R9) | `CONTENT_LENGTH` 없는 POST → 411, **인증 헤더 없이도** 411(순서) |
| heatmap (R7) | 비인증 401 / 남의 검사 404 `INSPECTION_NOT_FOUND` / 자기 검사 404 `HEATMAP_NOT_FOUND` |
| 목록 (R6) | 4필드 / 해시 없는 파일 `null` / `SHA256SUMS.txt` 도 목록에 / 폴더 없으면 빈 목록 |
| 다운로드 (R6) | 200 + `Accept-Ranges` / `bytes=5-` → 206 + `Content-Range` / `bytes=999-` → 416 / 없는 파일 404 봉투 / 경로 이탈 404 / **인증 없이 200** |

실행: `python manage.py test tests --settings=configurations.test_settings` + `python scripts/verify_permission_map.py`.

**넘기는 것**(서버가 떠 있어야 한다): e2e, `capture_ui.py`, 그리고 **실제 1GB 파일에
`curl -C -` 중단→이어받기 후 `sha256sum -c`** — Range 의 인수 확인이다.

## 8. 산출물

| 파일 | 변경 |
|---|---|
| `app/views/api_v1.py` | `use_tenant`, 인증 코드 구분, 선검사 가드, health 교체, heatmap, downloads 4개 + Range, 404 봉투 뷰 |
| `configurations/urls.py` | 라우트 6개. catch-all 은 구체 라우트 뒤·범용 라우트 앞 |
| `configurations/settings.py` | `APP_VERSION`, `DISTRIBUTION_ROOT` |
| `.env.example` | `DISTRIBUTION_ROOT` placeholder |
| `.gitignore` | `app/static/distribution` 한 줄을 아래로 교체 (+ 마지막 줄 개행) |
| `distribution/` | `app/static/` 밖으로 이동, README 재작성 |
| `tests/test_client_api.py` | 위 7묶음 |
| `docs/client/SERVER_RESPONSES.md` | **신규** — R1~R9 회신 |
| `docs/08_DEPLOYMENT.md` | distribution 반입 절차, 운영 인스턴스의 `DEBUG=False` |
| `docs/USER_DECISIONS.md`·`docs/IMPLEMENTATION_STATUS.md` | DEC-C1~C10 기록 |

## 9. 회신문 구성 — `docs/client/SERVER_RESPONSES.md`

항목별 **처리 결과 / 결정 사항 / 바뀐 API 규격**. 바뀐 Endpoint 는 요청·응답 JSON 예시와
오류 코드 표를 함께 싣는다(요청서 "회신 방법").

되돌려 보낼 질문: R1-2 인증서 방식(B·C 면 PEM 전달 + Client 코드 변경), R1-3 최종 주소·컷오버
일정(**`licenses/sources` 주소는 0.1.4 고지문에 박혀 있어 바꾸면 재빌드다**), R1-5 Key 전량
재발급 일정·전달 경로, R1-6 인증 실패 rate limit·CORS·노출 범위, R3 3년 보존의 정책 반영
주체와 사외 공개 여부, R4 "제공 안 함" 확정, R7-3 GPU·ANOMALY 매핑 일정, R9-4 `/openapi.json`
미제공 확정과 계약 정본 지정.

## 10. 범위 밖

- **R1 TLS** — nginx 종단·인증서·방화벽·Key 재발급. DEC-C7 로 별도 운영 인스턴스 과제다
- **GPU 추론** — `InferenceGateway` 는 Stub 유지. WEB 서버에 `torch` 를 넣지 않는다(§1.6 O-12)
- **rate limit·`meta.count`·`CLIENT_VERSION_UNSUPPORTED`** — DEC-C8 로 미제공 확정
- **`GET /api/v1/inspections/<id>`·`result-image`·`history`** — Client 가 쓰지 않는다
