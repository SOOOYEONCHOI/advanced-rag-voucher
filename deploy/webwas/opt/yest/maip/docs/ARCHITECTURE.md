# 아키텍처

근거: DECISIONS DEC-001, DEC-034, O-9.

제조AI플랫폼은 **비전 검사**, **AI 학습데이터 관리**, **디지털 입력 전환**(검사양식·작성·결과)을 한 Django 프로젝트에서 처리한다.
현장의 비전검사 클라이언트가 보낸 검사 이미지는 접수 즉시 해당 비전검사항목의 데이터로
저장되고, 웹 화면에서 라벨링·검수·스냅샷(Export zip)으로 이어진다.
시스템 관리(사용자·권한·메뉴) 위에 세 기능을 둔 구조다.

화면별 기능과 데이터 흐름은 [FEATURES.md](FEATURES.md), 테이블은 [DATA_MODEL.md](DATA_MODEL.md), 실행·테스트는 [DEVELOPMENT.md](DEVELOPMENT.md),
운영 설치는 [DEPLOYMENT.md](DEPLOYMENT.md), "근거:" 줄의 결정 ID 는 [DECISIONS.md](DECISIONS.md) 에 있다.

---

## 1. 구성 요소

```text
 검사 PC                                  사무실
┌──────────────────────────┐           ┌──────────────┐
│ 비전검사 클라이언트         │           │ 웹 브라우저    │
│ (VisionInspectionClient)  │           └──────┬───────┘
└────────────┬─────────────┘                  │ 세션 쿠키
             │ X-Client-ID + X-API-Key        │
             ▼                                ▼
┌──────────────────────────────────────────────────────────┐
│ nginx → gunicorn → Django (웹)                             │
│   /api/v1/...        비전검사 API                           │
│   /api/v1/datasets/... 학습 플랫폼 스냅샷 API                 │
│   /gui/... /api/...  업무 화면 · 화면용 API                  │
│   WezardGateway ──▶ Wezard 추론 API (설정 없으면 Stub)        │
└───────┬──────────────────────────────┬───────────────────┘
        │                              │
        ▼                              ▼
┌──────────────────┐          ┌────────────────────────────┐
│ PostgreSQL 16     │◀────────│ 워커 (manage.py run_worker) │
│ DB yest           │          │ 스냅샷 Export(zip)           │
└──────────────────┘          └────────────────────────────┘
   STORAGE_ROOT (업로드·파생 파일·로그) · DISTRIBUTION_ROOT (배포물)
```

| 구성 요소 | 하는 일 | 비고 |
|---|---|---|
| 웹 (gunicorn) | 화면·화면용 API·비전검사 API | Django 5.2 LTS / Python 3.12 |
| 워커 (`run_worker`) | `BackgroundJob` 큐 처리(스냅샷 Export zip) · 하루 한 번 DB 로그·만료 세션 정리 | 없으면 작업이 대기 상태로 남는다. §8 |
| PostgreSQL 16 | 단일 DB(`DB_NAME`, 기본 `yest`), `search_path=public` | 다른 프로젝트와 인스턴스를 공유한다 |
| `STORAGE_ROOT` | 업로드 원본·썸네일·Export ZIP·첨부·로그 | 웹에 공개하지 않는다. §9 |
| `DISTRIBUTION_ROOT` | 클라이언트 배포 zip·LGPL 대응 소스 | 인증 없이 내려준다. §9 |
| 비전검사 클라이언트 | 검사 PC 에서 촬영·전송·Overlay 표시 | **별도 프로젝트.** 서버측 기능은 전부 이 프로젝트 안에 있다 |
| Wezard | 모델 학습·추론. 스냅샷을 `/api/v1/datasets` 로 가져간다 | **별도 플랫폼.** `WEZARD_BASE_URL`·`WEZARD_API_KEY` 가 없으면 추론은 Stub 이다. §7 |

외부(브라우저·클라이언트)는 이 웹 서버만 호출한다. Wezard 를 직접 부르지 않는다.

---

## 2. 디렉터리 구조

Django 앱은 `app`(진입·화면)과 `domain`(모델·업무 로직) 둘이고, 업무는 디렉터리로 나눈다.

```text
configurations/          settings · test_settings · pg_test_settings · urls · wsgi · middleware/ · log.py · env.py ·
                         storage.py(정적 파일 저장소)
app/views/
  __init__.py            MESBaseView · ApiModuleView(인가 훅) · GUITemplatesView ·
                         TemplatePathView
  api_v1.py              비전검사 API 전부 (한 파일, DEC-C1)
  api_v1_datasets.py     학습 플랫폼 스냅샷 API (DEC-029)
  item/                  데이터 관리 화면 API — MES 동적 dispatch 의 item task (DEC-028)
  vision/ system/ definition/ dig_form/ common/   MES 동적 dispatch 대상
  files/                 media.py(보호된 미디어)
app/templates/           app/(셸) · data/ · vision/ · system/ · definition/ · dig_form/ · page/ · common/
app/static/              assets/(공통 JS·CSS) · wezongrid/ · data/ · lang/ · img/ · js/ · resource/
domain/models/           basic · system · user · data · vision · dig_form · interface
domain/services/         data/(export/ 포함) · vision/(gateway · inspection · model_mapping) · definition/ ·
                         judge_code · dig_form_image(디지털 양식) · interface · plm_bom · receipt(기준정보) · 공통 서비스
domain/gui.py            화면(gui_code) 정의 + API 권한 매핑
domain/tenancy.py        고정 조직 · tenant_atomic()
domain/storage.py        STORAGE_ROOT 경로 · upload_to 함수
domain/migrations/       스키마 · RLS · SQL 함수
domain/management/commands/   seed_initial · seed_dig_form · seed_vision_items · seed_demo · sample_inspection · export_dig_form ·
                              import_interface · apply_interface · run_worker · integration_key · runserver(기본 포트 8123)
domain/management/samples/    seed_dig_form·seed_demo 데이터(dig_form_forms.json · dig_form_images/ · fan_panel.zip)
domain/_sql/i18n/        다국어 시드 SQL
distribution/            배포물 (zip·tar 는 커밋하지 않고 SHA256SUMS.txt·README 만)
scripts/                 maipctl.py(개발 웹·워커 실행) · verify/(검증 스크립트) · dev/(개발 도구) ·
                         systemd/(운영 서비스 유닛)
tests/                   단위 + e2e
```

### 고칠 때 보는 곳

| 바꾸는 것 | 파일 |
|---|---|
| 화면용 API (MES 규약) | `app/views/<task>/<view>.py` + `domain/gui.py` `taskview_menu_code_map()` |
| 데이터 관리 API | `app/views/item/<화면>.py` + `domain/gui.py` `taskview_menu_code_map()` 의 `item/<view>` (규약은 `app/views/item/__init__.py`) |
| 비전검사 API | `app/views/api_v1.py` + `configurations/urls.py`(catch-all **앞**) + `docs/client/SERVER_API_CONTRACT.md` |
| 학습 플랫폼 스냅샷 API | `app/views/api_v1_datasets.py` + `configurations/urls.py`(catch-all **앞**) + `docs/Wezard/maip-api.md` |
| 업무 로직 | `domain/services/<업무>/*.py` |
| Export 형식 | `domain/services/data/export/registry.py`(비전검사항목 유형 → 형식 1:1) + 같은 폴더의 Exporter |
| 화면 | `app/templates/<폴더>/<화면>.html` + `domain/gui.py` `menu_init()` |
| 그리드 공통 동작(폭 채움·페이지 유지·엑셀) · 상세 영역 | `app/static/assets/js/grid.js` `GridUtil` · `common.js` `AjaxUtil.gridRemoteSource`·`DetailForm` |
| 메뉴 행 | `domain/management/commands/seed_initial.py` (재실행 필요 — 공유 개발 DB 는 담당자가 돌린다) |
| 디지털 양식 | `app/views/dig_form/*.py`·`app/views/system/form_edit.py` + `domain/gui.py` `DIG_FORM_MENU_CODES`, 이미지는 `domain/services/dig_form_image.py`, 판정 선택지는 `domain/services/judge_code.py` |
| 좌측 메뉴 트리 | `app/views/system/menus.py` (비전검사항목 노드는 동적 생성) |
| 테이블 | `domain/models/` + `makemigrations` |
| 추론 연결 | `domain/services/vision/gateway.py` (§7) |

---

## 3. URL 공간과 API 규약

근거: DECISIONS DEC-028, DEC-029, DEC-C1, DEC-C2.

규약은 둘이다 — 화면용 MES 동적 dispatch 와 클라이언트용 `/api/v1`. **섞지 않는다.**

| 경로 | 규약(응답 모양) | 호출자 | 인가 방식 | 인가 지점 |
|---|---|---|---|---|
| `/api/<task>/<view>` | MES 동적 dispatch. 조회는 행 리스트(서버 페이징 목록은 `{"rows", "totalRows"}`), 변경은 `{"success", "message"}` | MES 계열 화면(시스템·품목·입고·비전 검사·디지털 양식) | 세션 + 메뉴 권한 | `ApiModuleView.dispatch` (`app/views/__init__.py`) → `GUIConfiguration.get_menu_code_by_taskview` (`domain/gui.py`) → `authorize_menu_codes` |
| `/api/item/<view>` | 위와 같은 MES 동적 dispatch 의 `item` task. 조회는 dict(목록은 `{"rows", "totalRows"}` — 데이터 목록과 라벨링 대기열(`queue`, 50장)만 서버 페이징), 변경은 `{"success", "message"}`, 업무 오류는 400 `{"success": false, "message"}` | 데이터 관리 화면 7개(비전검사항목 관리 — 분류 API `category` 와 `item_admin`·비전 데이터 등록 `register`·홈·데이터 목록·라벨링·검수·스냅샷) | 세션 + 메뉴 권한 + 그 조직의 비전검사항목 | 위 dispatch + `ApiModuleView._execute_tenant_task` + 모듈의 `load_item`. 규약은 `app/views/item/__init__.py` |
| `/api/v1/...` | 비전검사 API. 성공 `{"data"}` / 실패 `{"error": {"code","message","retryable"}}`, 시각은 UTC `Z` | 비전검사 클라이언트 | `X-Client-ID` + `X-API-Key` (SHA-256 해시 비교, CSRF 면제) | `ClientApiView.dispatch` (`app/views/api_v1.py`) |
| `/api/v1/datasets/...` | 학습 플랫폼 스냅샷 API. 봉투·시각은 위와 같다 | Wezard(학습 플랫폼) | `X-API-Key` 하나(`maip_…`, `IntegrationClient`) | `DatasetApiView`(`app/views/api_v1_datasets.py`) |

MES 계열은 HTTP 메서드로 R/W 를 가른다(GET = `R`, POST = `W`). 변경 action 을 GET 으로 받으면 읽기 권한만으로 바뀌므로 변경 action 은 POST 만 받는다 —
MES 모듈은 변경 action 을 `WRITE_ACTIONS`(`dig_form/dig_form`·`dig_form/judge_code`·`system/form_edit`·`system/product_form`)에 적고,
`item` task 는 조회 action 만 `READ_ACTIONS` 에 적는다(AGENTS [2]). 어느 쪽이든 변경 action 을 GET 으로 부르면 405 다.
`item` task 는 요청 전체를 `tenant_atomic()` 으로 감싸고 `load_item` 이 `AuthorizationService.require()` 로 그 조직의 비전검사항목인지 본다.
`DatasetApiView` 는 `ClientApiView` 를 상속해 `client_model`·`_authenticate` 를 바꾸고 오류 본문에 `request_id` 를 더한다.

- `/api/v1` 의 엔드포인트·응답·오류 코드는 이 문서에 쓰지 않는다(계약 문서가 정본).
- `/api/v1` 아래 미지 경로는 `urls.py` 의 `api/v1/<path:rest>` catch-all(`V1NotFoundView`)이 404 `NOT_FOUND` 봉투로 답한다. `/api/v1/datasets` 아래면 본문에 `request_id` 도 넣는다.
- `/api/v1` 은 `/api/<task>/<view>` 권한 매핑 대상이 아니다. `verify_permission_map.py` 가
  `app/views/` 하위 디렉터리만 훑기 때문이다.

더 볼 곳: `/api/v1` 의 엔드포인트·응답·오류 코드는 client/SERVER_API_CONTRACT.md, 학습 플랫폼 API 는 Wezard/maip-api.md·Wezard/integration-protocol.md.

### 그 밖의 경로

| 경로 | 처리 | 인가 |
|---|---|---|
| `/` | 셸(`app/index.html`) | 로그인 |
| `/gui/<gui_code>/` | `GUITemplatesView` — 업무 화면 | `gui_code` 에 대한 메뉴 권한이 없으면 403 |
| `/page/<folder>/<template>` | `TemplatePathView` — 팝업 | `domain/gui.py` `PAGE_PERMISSION_MAP` |
| `/media/...` | `app/views/files/media.py` — 데이터 관리 이미지·Overlay 미리보기·Export, 디지털 양식 이미지(참고사진·이미지 칸·비전 연결 칸·사진 넣기 Overlay) | 로그인 + 그 조직의 비전검사항목(디지털 양식 경로는 디지털 양식 메뉴 `R`). 경로별은 §9-2 |
| `/login/` `/logout/` | `app/views/account.py` | — |

---

## 4. 인가는 메뉴 권한이다

근거: DECISIONS 사용자 결정 2026-10-21, DEC-003.

```text
요청 ─▶ 메뉴 권한        "이 그룹이 이 화면/기능을 쓸 수 있는가"
            UserGroupMenu(MenuCode, AuthCode)    GET → R, POST → W
        ─▶ (데이터 화면) 그 조직의 비전검사항목인가   AuthorizationService.require
```

### 메뉴 권한

- 판정 함수는 `authorize_menu_codes()`(`app/views/__init__.py`)다. MES 동적 dispatch·
  `TemplatePathView` 가 이것을 부른다. `/gui/<gui_code>/`(`GUITemplatesView`)는
  `AccountService.check_user_auth()` 로 그 화면의 권한만 직접 본다.
- 경로마다 메뉴 코드 목록을 매핑한다. 코드가 여러 개면 **하나라도** 권한이 있으면 통과한다.
  빈 목록 `[]` 은 "로그인만 요구"다.
- 사용자의 권한 코드는 `AccountService.check_user_auth()`(`domain/services/account.py`)가 낸다.
  superuser 와 `dev` 그룹은 전부 `RW`, `admin` 그룹은 사용자·그룹·메뉴 권한 화면만 자동 `RW`
  이고 나머지는 `UserGroupMenu` 행을 따른다.

`API_AUTHZ_MODE`(기본 `enforce`) 가 매핑이 **없는** 경로를 어떻게 다룰지 정한다.

| 값 | 매핑 없음 | 매핑 있음 |
|---|---|---|
| `enforce` | **즉시 403** (경고 로그) | 권한 판정 |
| `warn` | 경고 로그만 남기고 통과 | 권한 판정 |
| `off` | 검사하지 않는다 | 검사하지 않는다 |

디지털 양식 쓰기는 매핑(디지털 양식 메뉴 아무 곳의 권한)을 통과한 뒤 모듈이 그 양식 구분 메뉴의 `W` 를 다시 본다(`require_write`, `app/views/dig_form/dig_form.py`).

화면이나 API 를 더하면 `domain/gui.py`(`taskview_menu_code_map()`·`PAGE_PERMISSION_MAP`)에 매핑도 등록한다. 빠뜨리면 `enforce` 에서 403 이고 `verify_permission_map.py` 가 미리 잡는다(AGENTS [3]).

### 데이터 화면 — 비전검사항목

- 진입점: `AuthorizationService.require(request, action, item)`
  (`domain/services/data/authorization.py`). 작업 이름이 `ACTIONS` 에 있는지 보고(없으면 거부),
  그 조직의 비전검사항목인지 `ItemAccessService.require()`(`domain/services/data/item_access.py`)가 본다.
  무엇을 할 수 있는지는 디스패치가 이미 본 메뉴 R·W 다.
- 보이는 비전검사항목(`ItemAccessService.visible_items`)은 조직의 전부다. 삭제 승인 대기 항목은 플랫폼 관리자만 본다.
- 다른 화면이 미리 알아야 하는 판단은 그 메뉴의 W 로 본다(`ItemAccessService.can_write`):
  홈 [비전검사항목 편집]·라벨 클래스·측정점 = 비전검사항목 홈 W, 검수·검수 완료 데이터 삭제 = 검수 작업 W,
  스냅샷 [등록] = 스냅샷 관리 W. 플랫폼 관리자(superuser 또는 그룹 `dev`·`admin`)는 늘 참이다.
- 거부는 `PermissionDenied` 이고 MES 동적 dispatch(`ApiModuleView`)가 403 으로 바꾼다.
  `item` task 는 서비스의 메시지를 그대로 담는다.

더 볼 곳: 화면별로 할 수 있는 일은 FEATURES.md.

### 로그인

- 세션 인증. 쿠키 이름 `map`, HttpOnly, SameSite=Lax.
- 로그인 실패 제한: (아이디, 접속 주소) 단위로 5회 실패 시 5분(300초) 잠금
  (`domain/services/login_throttle.py`). 접속 주소는 `127.0.0.1`·`::1` 에서 온 요청일 때만 `X-Real-IP` 를 믿는다. 실패 횟수는 Django 캐시(파일 캐시 `STORAGE_ROOT/cache` — 같은 서버의 웹 워커가 함께 센다)에 쌓는다.
- `MESBaseView` 가 매 요청 계정 활성 여부를 다시 보고, 비활성이면 로그아웃시킨다.
- 세션은 요청이 없으면 8시간 뒤 끝나고(`SESSION_COOKIE_AGE`·`SESSION_SAVE_EVERY_REQUEST`), 브라우저를 닫아도 끝난다(로그인 때 `set_expiry(0)`).

---

## 5. 단일 조직과 RLS

근거: DECISIONS DEC-004.

조직(Tenant)은 **YEST 하나로 고정**이다. 조직 선택 화면도 조직
미들웨어도 없다. `domain/tenancy.py` 의 `current_tenant()` 가 늘 같은 행을 돌려주고,
DB 의 CHECK 제약(`ck_single_tenant`)이 두 번째 조직 행을 막는다.

그래도 데이터 관리 테이블에는 PostgreSQL **`FORCE ROW LEVEL SECURITY`** 가 걸려 있다
(14개). 정책은
`tenant_id::text = current_setting('app.tenant_id', true)` 다. 조직이 늘 때 스키마를
바꾸지 않아도 되고, 코드가 조직 필터를 빠뜨려도 DB 가 막는다.

`tenant_atomic()` 이 트랜잭션을 열고 `SET LOCAL app.tenant_id` 를 건다. 이 안에서만
데이터를 다룬다.

| 진입 | `tenant_atomic()` 을 여는 곳 |
|---|---|
| 데이터 관리 API | `app/views/__init__.py` `ApiModuleView._execute_tenant_task`(`item` task) — 요청 전체 |
| 비전검사 API | `ClientApiView.dispatch` — 요청 전체(health·배포물 경로 제외) |
| 보호된 미디어 | `app/views/files/media.py` 각 뷰(디지털 양식 참고사진은 RLS 대상이 아니라 열지 않는다) |
| MES 화면 API | `vision/*`·`system/menus`·`system/user`·`system/form_edit`·`dig_form/dig_form`(거치대 결과 칸 확인) 모듈과 디지털 양식 비전 연결 칸(`domain/services/dig_form_image.py`)이 RLS 테이블을 읽는 부분만 직접 연다 |
| 워커 | `JobService._claim_next` · `_run_claimed` — 작업마다 |

더 볼 곳: 대상 테이블 목록과 DDL 은 DATA_MODEL.md §6.

### 코드에서 지킬 것

| 무엇 | 어떻게 |
|---|---|
| 읽기·쓰기 | `domain.tenancy.tenant_atomic()` 안에서 한다 |
| 조직 얻기 | `current_tenant()` — 항상 고정 조직(`YEST`)을 돌려주고 캐시한다 |
| 쿼리 | `Model.objects.for_tenant(tenant)` (`TenantScopedManager`, `domain/models/data.py`) |
| 컨텍스트 밖에서 읽으면 | **예외 없이 0건**이다. 조회가 비면 테넌트 컨텍스트부터 의심한다(AGENTS [4]) |
| 사용자 삭제 | `tenant_atomic()` 안에서 한다. 밖에서는 RLS 로 가려진 소속 행을 Django 가 보지 못해 외래키에 걸린다 |
| 새 사용자 | `auth_user` `post_save` 시그널이 `UserProfile` 과 `TenantMembership` 을 만든다 (`domain/models/user.py`) |
| `TENANT_RLS_ENABLED` | `False` 는 `SET LOCAL` 만 건너뛴다. 정책은 남으므로 PostgreSQL 에서 끄면 전부 0건이 된다. 운영은 `True`(기본값) |
| 테스트 | `test_settings`(SQLite)는 `TENANT_RLS_ENABLED=False` 라 RLS 를 보지 않는다. RLS 는 `pg_test_settings` 로 본다 |

---

## 6. 화면층

근거: DECISIONS DEC-013, DEC-028.

| 항목 | 내용 |
|---|---|
| 셸 | `app/templates/app/index.html`. 좌측 메뉴(`left_menu_class.html`)가 `/gui/<gui_code>/` 를 **iframe 탭**으로 연다. 그래서 `X_FRAME_OPTIONS` 는 `SAMEORIGIN` 이다 |
| 화면 기반 템플릿 | `app/layout_page.html`. 데이터 관리 화면도 이것이다 |
| 그리드 | WeZonGrid (`app/static/wezongrid/`, 고치지 않는다). 공통 동작은 §2 "고칠 때 보는 곳" |
| Ajax | `AjaxUtil.getAsyncData`·`postAsyncData` (`app/static/assets/js/common.js`) |

더 볼 곳: 디자인 토큰·버튼·모달·확인창·문구 어조는 DESIGN.md.

---

## 7. 검사 수신과 추론 경계

### 7-1. 검사 1건이 처리되는 순서

근거: DECISIONS DEC-C12, O-11.

`POST /api/v1/inspections` → `InspectionCreateView` → `InspectionService.receive_capture()`
(`domain/services/vision/inspection.py`).

1. 본문 길이 확인 — 인증보다 먼저(`ClientApiView._precheck`)
2. 클라이언트 인증, `tenant_atomic()` 진입
3. `metadata` 검증 — **이미지를 쓰기 전에**. 길이 초과는 자르지 않고 거절한다
4. `request_id` 멱등 처리 — 이미 있으면 같은 클라이언트에게는 기존 결과, 다른 클라이언트면 충돌
5. 비전검사항목 확인(활성 상태만). 공정·제품은 검증하지 않는다 — 응답 시점 합성값이다
6. 이미지 형식 판정(JPEG·PNG만, 실제 바이트 기준)
7. `ImageService.upload_images()` 로 **비전검사항목 데이터로 저장** + `vision_inspection` 행 생성 — 한 트랜잭션.
   이미지 실체는 데이터 관리의 `ImageAsset` 하나이고 검사 행은 그것을 가리킨다
8. 치수 측정 비전검사항목은 5 다음에 `measurements` 를 판정하고(`judge_measurements`, 이미지를 쓰기 전에 거절) 추론 없이 `SUCCESS` 다.
   그 밖의 유형은 활성 모델 매핑이 있으면 추론 시도(`_run_inference`)

더 볼 곳: 상태 코드·응답 필드는 client/SERVER_API_CONTRACT.md.

### 7-2. 추론은 Wezard 가 한다

근거: DECISIONS DEC-030, DEC-033, DEC-C11, O-1, O-12.

`get_inference_gateway()`(`domain/services/vision/gateway.py`)는 `WEZARD_BASE_URL`·`WEZARD_API_KEY` 가 둘 다 있으면
`WezardGateway` 를, 아니면 Stub(`InferenceGateway`, 항상 `GpuNotConfiguredError`)을 돌려준다.

1. 매핑(`VisionItemModelMapping.model_code`)은 Wezard `model_name` 이다. `GET /api/v1/models?model_name=…&deployed=true&status=READY&category=vision&limit=1`
   로 그때의 최신 배포 `model_id` 를 찾는다(재학습하면 바뀐다)
2. `POST /api/v1/inference/{model_id}` — multipart `files` 에 원본 바이트, 매핑 임계값 재지정이 있으면 `anomaly_threshold`·`score_threshold`, 이상 탐지는 `return_heatmap=true`.
   헤더 `X-API-Key`, `X-Request-ID` = 검사 `request_id`(Wezard 추론 이력에 남는다)
3. 이상 탐지는 `is_anomaly`·`anomaly_score`·`threshold`, 객체 탐지는 `detections` → `Defect`(bbox 를 정수로 넓혀 이미지 안으로 자르고 넓이 0 은 버린다),
   분류는 1순위 `label`·`score`(판정은 §7-3). 이상 탐지의 `heatmap_png_base64` 는 Heatmap 파일로 검사에 저장한다(§9-2). 검사에는 Wezard 가 실제로 쓴 `model_name`·`version` 을 기록한다

HTTP 는 표준 라이브러리 `urllib` 다 — 운영 의존성을 늘리지 않고, WEB 서버에 `torch`·`torchvision` 을 두지 않는다(AGENTS [1]).
키는 헤더로만 보내고 로그·예외 문구에 넣지 않는다.

| 상황 | `status` | `error_message` | 이미지 |
|---|---|---|---|
| 모델 매핑 없음 | `RECEIVED` | 없음 | 저장 |
| 매핑 있음, Wezard 설정 없음 | `RECEIVED` | `GPU_INFERENCE_NOT_CONFIGURED` | 저장 |
| 매핑 있음, 그 이름의 배포 모델 없음(목록 0건·추론 404/409) | `RECEIVED` | `WEZARD_MODEL_NOT_DEPLOYED` | 저장 |
| 시간 초과·연결 실패·Wezard 401·5xx·그 밖의 예외 | `FAILED` | 예외 요약(화면 전용, 클라이언트에 안 나감) | 저장 |
| 추론 성공 | `SUCCESS` | 없음 | 저장 |

- 미설정·배포 없음은 `FAILED` 가 아니다(이력 화면은 `error_message` 로 "추론 미실행"을 구분한다). `RECEIVED` 는 **영구히 "추론하지 않음"** 이라 재조회해도 바뀌지 않는다. 시간 예산은 모델 조회 5초 + 추론 15초 — 검사 POST 20초 안이고 재시도하지 않는다.
- 보낸 검사 이미지와 추론 결과는 Wezard 서버에 보관된다.

더 볼 곳: Wezard API 는 Wezard/wezard-api.md, 공통 규칙은 Wezard/integration-protocol.md.

### 7-3. 모델 매핑

근거: DECISIONS DEC-010, DEC-031.

비전검사항목 관리 상세(`wm_data_item`)의 AI 모델 칸이 [수정] 때 `/api/item/item_admin?action=models&item_id=` 로 그 비전검사항목 유형의
Wezard 배포 모델(이름별 최신)을 받는다(로직 `domain/services/vision/model_mapping.py`). 저장하면 이름을 배포 목록에서 다시 확인하고, 로컬 `VisionModel` 을
**이름표**(`version = 'latest'`, `runtime = 'wezard'`)로 맞춘 뒤 매핑한다 — 매핑 FK 를 그대로 두려는 것이다.
분류 비전검사항목은 Wezard `classification` 모델을 고른다. 분류 결과는 `label`·`score` 를 받아 검사 서비스가 라벨 클래스의
`is_defect` 로 `abnormal` 을 정하고, 비전검사항목에 없는 라벨은 이상으로 본다.

## 8. 작업 큐와 워커

근거: DECISIONS DEC-022, F-8.

스냅샷 Export 는 이미지 수천 건을 읽고 ZIP 을 만든다. 웹 요청 안에서 하지 않고
`BackgroundJob`(`vision_data_backgroundjob`) 큐에 넣는다.

```text
스냅샷 등록 → DatasetVersionService.create_snapshot → JobService.enqueue_export → BackgroundJob(QUEUED)
                                                              │
run_worker → JobService.run_pending                           ▼
   requeue_stale 오래된 RUNNING(워커가 죽은 작업)을 QUEUED 로 되돌림
   _claim_next   짧은 트랜잭션, SELECT ... FOR UPDATE SKIP LOCKED → RUNNING 커밋
   _run_claimed  작업마다 별도 tenant_atomic() → COMPLETED / FAILED(error_message)
```

| 항목 | 내용 |
|---|---|
| 작업 유형 | `EXPORT`(Export 생성) 하나다. 스냅샷 하나에 비전검사항목 유형의 고정 형식과 `WEZARD` 형식 두 건이 쌓인다 |
| 상태 | `QUEUED` → `RUNNING` → `COMPLETED` / `FAILED` |
| 실행 | `python manage.py run_worker [--once] [--interval 5] [--limit 20]` — `--interval` 폴링 초(기본 5), `--limit` 한 번에 집는 작업 수(기본 20), `--once` 대기 작업을 한 번(최대 `--limit`건) 처리하고 DB 로그 보존 정리를 한 번 한 뒤 끝낸다 |
| 로그 보존 정리 | 작업과 별개로 하루 한 번 DB 로그·만료 세션을 지운다(§10) |
| 여러 개 | 띄워도 된다. `SKIP LOCKED` 로 같은 작업을 두 번 잡지 않는다 |
| 종료 | SIGTERM·SIGINT 를 받으면 지금 집은 묶음(최대 `--limit`)을 끝내고 나간다 |
| 실패 | 다시 돌리지 않는다. `FAILED` 로 끝나고 `error_message` 는 255자로 자른다. 연결된 `ExportJob` 도 `FAILED` 로 맞춘다(본문이 롤백돼 `QUEUED` 로 남지 않게). 저장한 zip 은 지운다. Export 검증 실패는 예외가 아니라 워커 작업은 `COMPLETED` 이고 `ExportJob` 만 `FAILED` 다 |
| 중간에 죽으면 | `started_at` 이 `WORKER_STALE_SECONDS`(기본 3600초)보다 오래된 `RUNNING` 을 다음 `run_pending` 이 `QUEUED` 로 되돌리고 `attempt_count` 를 올린다. 3번째(`JobService.MAX_ATTEMPTS`)면 `FAILED`("워커가 중단되어 작업을 마치지 못했습니다.")다. **한계:** 이 시간보다 오래 도는 정상 작업은 두 번 돈다 — 그런 작업이 생기면 heartbeat 를 더한다. `next_retry_at` 은 쓰지 않는다 |
| 새 유형 | `JobType` 과 `JobService._execute` 분기를 함께 더한다 |

화면은 작업 상태를 폴링한다.

---

## 9. 저장소와 파일 제공

### 9-1. 저장 위치

근거: DECISIONS O-10.

업로드·파생 파일은 `STORAGE_ROOT`, 배포물은 `DISTRIBUTION_ROOT` 아래에 둔다. 보존 정책은 없다.

더 볼 곳: 저장 경로와 `upload_to` 규칙은 DATA_MODEL.md §9.

### 9-2. 공개 경로가 없다

근거: DECISIONS DEC-019.

`MEDIA_URL` 을 두지 않는다. nginx 도 `STORAGE_ROOT` 를 서비스하지 않는다.
파일은 권한을 확인하는 View 로만 나간다.

| 파일 | 경로 | 확인하는 것 |
|---|---|---|
| 데이터 이미지·썸네일·대표 이미지·Overlay 미리보기 | `/media/image/<id>/` 등 (`app/views/files/media.py`) | 로그인 + `item.read`(그 조직의 비전검사항목). 미로그인·없는 id 는 404, 권한이 없으면 403 |
| Export ZIP | `/media/export/<id>/` | 로그인 + `dataset.export`(그 조직의 비전검사항목) |
| 디지털 양식 참고사진(양식 편집기)·이미지 칸 사진(검사작성) | `/media/dig-form-image/<attach_file id>/` | 로그인 + 디지털 양식 메뉴(`domain/gui.py` `DIG_FORM_MENU_CODES`) 중 하나의 `R`. 없으면 404 |
| 디지털 양식 비전 연결 칸 사진(검사작성·검사결과) | `/media/dig-form-asset/<ImageAsset id>/` | 로그인 + 디지털 양식 메뉴 중 하나의 `R` + (저장된 연결 칸 결과가 가리키거나 이번 세션에 이 사용자가 올린 이미지). 아니면 404 |
| 사진 넣기 팝업 Overlay | `/media/dig-form-overlay/<dig_form_item id>/` | 로그인 + 디지털 양식 메뉴 중 하나의 `R` + 칸에 연결된 항목의 Overlay 가 표시 중. 아니면 404 |
| Overlay 이미지(클라이언트용) | `/api/v1/overlays/<id>/image` | 클라이언트 API Key |
| 이상 탐지 Heatmap(클라이언트용) | `/api/v1/inspections/<id>/heatmap` | 클라이언트 API Key + 자기 검사 |
| 스냅샷 zip(Wezard 용) | `/api/v1/datasets/snapshots/<id>/download` | 연동 API Key(`IntegrationClient`) |

비전 검사 화면의 검사 이미지도 데이터 관리 `ImageAsset` 이므로 `/media/image/<id>/` 로 본다.

파일 응답은 `app/views/files/__init__.py` 의 `sendfile()` 이 만든다(`media.py`·Heatmap·배포물·스냅샷 zip 다운로드).
운영(`FILE_ACCEL_REDIRECT=True`)에서는 권한 확인 뒤 `X-Accel-Redirect` 로 nginx 의 **internal** location
(`/_protected/media/`·`/_protected/distribution/`)에 전송을 넘긴다 — 브라우저가 직접 열 수 없으므로 위 원칙의
예외가 아니다. gunicorn sync 워커가 큰 파일을 흘려보내면 `--timeout` 에 걸려 끊긴다. 개발은 Django 가 보낸다.
예외 둘: 클라이언트용 Overlay 이미지는 `FileResponse` 라 운영에서도 Django 가 보내고(`api_v1.py` `OverlayImageView`),
개발에서 Range 요청(206)은 `ranged_file_response` 가 `StreamingHttpResponse` 로 보낸다.

### 9-3. 의도적으로 인증이 없는 경로

근거: DECISIONS DEC-024.

`/api/v1/licenses/sources`·`/api/v1/licenses/sources/<filename>`·
`/api/v1/client-packages`·`/api/v1/client-packages/<filename>` 4경로다. 접근 범위는 방화벽이
지킨다. 다운로드는 목록에 있는 이름만 찾으므로 `../` 로 폴더 밖에 나갈 수 없다.
`/api/v1/health` 도 인증 없이 응답한다(연결 확인용). `/api/alive`(서버 시각 JSON, `SystemDefaultRenderer.alive`)도 인증이 없다 — 지금 부르는 곳은 없다.

더 볼 곳: 반입 절차는 DEPLOYMENT.md §8-1.

---

## 10. 로그

| 종류 | 위치 | 내용 |
|---|---|---|
| 파일 로그 | `LOG_DIR/app-YYYY-MM-DD.log` | Python `logging` 전부(루트 로거). 형식 `[시각] 레벨 PID 로거 메시지` |
| DB 시스템 로그 | `sys_log` — 화면 "시스템 로그" | `LogWriter.add_dblog()` 가 쓰는 한 줄 요약 |
| 로그인·메뉴 사용 | `login_log`·`menu_use_log` | 화면에서 조회 |
| 접근 로그 | gunicorn(journald)·nginx | 앱 파일 로그에는 없다 |

- `configurations/log.py` `DailyFileHandler` 가 KST 날짜별로 파일을 나눈다. 이름을 바꾸는
  회전이 아니라 그날 파일을 append 로 여는 방식이라, 웹 워커 여러 개와 `run_worker` 가
  한 파일에 같이 쓴다(줄마다 PID). logrotate 는 필요 없고, 걸면 이름을 바꾸는 회전이 겹친다.
- `LOG_RETENTION_DAYS`(기본 30)가 지난 `app-*.log` 를 지운다. 0 이면 지우지 않는다.
- DB 로그는 워커가 하루 한 번 지운다 — `sys_log` 90일·`login_log`·`menu_use_log` 365일, 만료된 `django_session`(`domain/services/log_retention.py`).
- `LOG_LEVEL` 기본 `INFO`. 테스트 설정은 로그를 버린다.
- `LogWriter.add_dblog()`(`domain/services/logging.py`)는 DB 에 한 줄을 남기고, 같은 내용을
  `system` 로거로 파일에도 쓴다. 예외면 **스택 트레이스는 파일에만** 있다. 화면에서 오류를
  보면 같은 시각의 파일 로그를 찾는다.
- 요청마다 `X-Request-ID` 를 받거나 만들어 응답 헤더로 돌려준다(`RequestIdMiddleware`).

더 볼 곳: 운영 폴더 준비·권한은 DEPLOYMENT.md.

---

## 11. 다국어

근거: DECISIONS DEC-021.

지원 언어는 한국어·영어·중국어·베트남어이고 **화면에는 한국어만 내보낸다**.

| 구성 | 위치 |
|---|---|
| 라벨 문구 | `label_code`·`label_code_lang` 테이블, `/api/common/labels` (수정은 플랫폼 관리자만) |
| 그리드 컬럼 문구 | `grid_col`·`grid_col_lang` |
| 정적 리소스 | `app/static/lang/{ko,en,zh,vi}.json` |
| 관리 화면 | 메뉴명 설정(`wm_menu_language`). 다국어 설정(`wm_multi_language`)은 메뉴에서 내렸다(주소로만) |

더 볼 곳: 한국어 전용 규칙과 `verify_korean_only.py` 는 DESIGN.md §6, 시드 SQL 은 DATA_MODEL.md §8.
