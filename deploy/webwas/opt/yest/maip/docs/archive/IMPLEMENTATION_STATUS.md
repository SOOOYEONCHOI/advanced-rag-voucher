# 구축 진행 상태

`07_IMPLEMENTATION_PLAN.md` 기준 진행 기록. 정본 결정은 `USER_DECISIONS.md` §1.5·§1.6·§1.7.

- **대상 DB**: `10.10.10.20:5432 / yest` (접속정보는 `.env`, 커밋하지 않음)
- **브랜치**: `phase-0`
- **실행 환경**: Python 3.12 / Django 5.0.4 / psycopg 3.1.18 / `.venv`

---

## 요약

| Phase | 내용 | 상태 |
|---|---|---|
| 0 | Baseline · MES 복제 · 범위 밖 Domain 제거 | **완료** |
| 1 | System Management 정리 · 인가 훅 enforce | **완료** |
| 2 | 데이터 관리 모델 · 서비스 · 워커 | **완료** |
| 3 | 데이터 관리 화면 10개 · API 23경로 | **완료** |
| 4 | 비전 모델 · 서비스 · GPU 경계 Stub | **완료** |
| 5 | 비전 관리 화면 5개 | **완료** |
| 6 | 비전검사 클라이언트용 `/api/v1` 13경로 | **완료** |
| 7 | 메뉴 · 2단계 인가 전면 적용 | **완료** |
| 8 | Migration · Seed | **완료** |
| 9 | 통합 기능 검증 | **완료** (스모크 + E2E) |
| 10 | 신규 테스트 | **부분** (단위 59 + E2E 48. 커버리지 확대 필요) |
| 11 | E2E / 회귀 | **완료** (Playwright 42건) |

## 검증 결과

| 항목 | 결과 |
|---|---|
| `manage.py check` | 0건 |
| `manage.py test tests --settings=configurations.test_settings` | **59건 통과** |
| `pytest tests/e2e` (Playwright, 실브라우저) | **48건 통과** |
| `node scripts/verify_screen_js.js` | **PASS** (스크립트 블록 149개) |
| `scripts/verify_permission_map.py` | **PASS** |
| `scripts/verify_menu.py` | **PASS** (화면 28 / 메뉴 28) |
| 실서버 스모크 (화면 23 + API 23) | 전부 200 |

### 핵심 목표 연계 (§1.6 O-9) — 실서버 확인

```
GET  /api/v1/catalog            → 검사항목 3개 (합성 공정·제품 1건씩)
POST /api/v1/inspections        → 201 / status=RECEIVED
  → ImageAsset 생성: UPLOADED / UNLABELED / 썸네일 O
  → dataset = 검사항목의 업로드 데이터셋 (자동 생성)
  → source_inspection_id = 검사 id (추적)
  → 업로더 = 클라이언트 전용 계정 "1호기 비전검사 클라이언트"
  → 라벨링 대기열에 즉시 노출
GET  /api/v1/inspections/by-request/<id> → 같은 검사 반환
```

## 구축 규모

| 구분 | 수 |
|---|---|
| 화면 (gui_code) | 21 |
| API 경로 | MES dispatch 39 + 데이터 REST 23 + 비전검사 `/api/v1` 13 |
| DB 테이블 | MES 29 + 데이터관리 21 + 비전 5 = **55** |
| 마이그레이션 | 8 (RLS · SQL 함수 · 뷰 포함) |
| 도메인 서비스 | 데이터 31 + 비전 2 |

## 동기 Ajax 제거 (2026-10-01)

`getSyncData` 호출 34곳을 콜백으로 바꾸고 헬퍼 자체를 삭제했다. 동기 XHR 은
UI 스레드를 멈추고 브라우저가 폐기를 예고한 기능이다.

| 대상 | 건수 |
|---|---|
| 공통 유틸 (콤보 3종 · i18n 라벨) | 4 |
| 화면 템플릿 | 27 |
| 값을 돌려주던 함수 (컬럼설정 · 라벨팝업) | 2 |
| 죽은 코드 삭제 (`checkApplyDate` · `fillSelectSyncData`) | 2 |

- 기존 호출부를 깨지 않도록 콤보 헬퍼는 **시그니처 끝에 선택적 콜백만** 더했다.
- `scripts/verify_screen_js.js` 를 추가했다. 템플릿 인라인 스크립트는 화면을
  열어 보기 전에는 아무도 파싱하지 않아 문법이 깨져도 드러나지 않는다.
- `tests/e2e/test_crud.py` 6건으로 등록→조회→수정→삭제 순서를 실제 조작으로 확인했다.
  동기 호출은 순서를 코드가 보장했지만 콜백은 그렇지 않다.

---

## 메뉴 구조 재편 (2026-10-01)

사용자 지시로 좌측 메뉴를 다시 짰다. 자세한 트리는 `SCREEN_MAPPING.md` §1.

| 요청 | 결과 |
|---|---|
| 폴더 순서 | 비전 검사 관리 -> 데이터 관리 -> 시스템 관리 |
| 기준정보 폴더 삭제 | 메뉴 행만 제거. 화면 정의·테이블은 남겼다(`seed_initial.RETIRED_FROM_MENU`) |
| 남의 화면을 가리키던 메뉴 삭제 | `wm_data_quality` · `wm_data_export` · `wm_data_activity` · `wm_vis_dashboard` — 화면 정의까지 제거 |
| rename 실수 | "검사 검사항목" **57곳**(21개 파일)을 `검사항목` 으로 |
| 메뉴 코드·이름 교정 | `wm_sys_model_mapping` -> `wm_vis_model_mapping`, `wm_data_image` 이름 "데이터 관리" -> "데이터 목록" |
| 검사항목별 3단 메뉴 | 데이터 관리 폴더에 검사항목명이 나오고, 펼치면 하위 5개 화면이 `?project=<id>` 로 열린다 |

메뉴 행 28 -> **21**. 그중 5개(`wm_data_item_detail`·`image`·`labeling`·`review`·`snapshot`)는
폴더 최상단에서 감추고 검사항목 노드 아래에만 쓴다. 행을 지우지 않는 이유는 그 코드가
`DATA_API_MENUS` 와 메뉴권한 화면의 기준점이기 때문이다.

메뉴를 지울 때 `DATA_API_MENUS` 의 기준점을 함께 옮겼다. 그대로 두면 메뉴 행과 함께
권한이 사라져 **스냅샷 화면의 Export·품질 점검 버튼과 홈의 활동 이력이 403** 이 된다.

## 배포 준비 정리 (2026-10-01)

문서를 `docs/` 로 모으고(`docs/README.md` 인덱스), 배포 문서를 썼다
(`docs/08_DEPLOYMENT.md` — 대상 OS 는 **Ubuntu 확정**, N4 해소).

### 소스에서 제거한 자격증명

| 파일 | 내용 |
|---|---|
| `domain/_sql/database.sql` | `CREATE USER ... WITH PASSWORD '...'` — 전시회용 MES(`exh`)의 DB 부트스트랩 7줄. 비밀번호가 평문이었다. 이 프로젝트와 무관한 DB·사용자이고 코드에서 참조하지 않았다 |
| `domain/services/sql.py` | 주석에 남은 ODBC 접속문자열(`dsn=...;uid=...;pwd=...`) |

둘 다 **git 히스토리에는 남아 있다.** 해당 DB 계정이 아직 살아 있다면 비밀번호를
교체해야 한다. DB 생성 절차는 `docs/08_DEPLOYMENT.md` §2 로 옮겼다 —
`createuser --pwprompt` 로 대화형 입력을 받아 비밀번호가 파일·셸 히스토리에
남지 않는다.

### 제거한 죽은 코드

| 대상 | 근거 |
|---|---|
| `SystemDefaultRenderer.mobile` · `.setup` | URLConf 에 없고, 쓰던 템플릿(`app/mobile_index.html`·`setup.html`)과 설정(`MOSQUITTO_HOST`·`TOPIC_*`)이 모두 사라진 상태였다. 호출되면 즉시 `AttributeError` 다 |
| `SystemDefaultRenderer.notfound403` · `.notfound404` | URLConf 에 없는 중복. `MESBaseView.response403/404` 가 같은 템플릿으로 응답한다 |
| `DbUtil.sp_exec` · `query_test1/2` · `sp_test1/2` | MSSQL 전용. `cursor.nextset()` 과 T-SQL(`declare @ret`, `exec`)을 쓰므로 PostgreSQL 에서 동작하지 않는다. 호출부도 없다 |
| `AjaxUtil.addNewTab` · `addNewTabPop` | 주석에 `not used` 가 적혀 있고 존재하지 않는 `/pageinfo` 를 호출한다 |
| 템플릿 4개 (782줄) | `app/login.html`(실제 로그인은 `login_mes.html`), `app/layout_page_nocss.html`, `data/_password_dialog.html`, `data/item_detail.html` — 어디서도 참조하지 않는다 |
| `domain/_sql/numeric_scale3/` (3,819줄) | MES 업무 테이블(bom·수주·재고)의 NUMERIC 전환 SQL. **그 테이블이 이 프로젝트에 없다**(DB 확인: 66개 테이블 중 해당 없음). 헤더에 "작성 시점에는 실행하지 않았다"고 적혀 있다 |

`domain/_sql/` 에 남은 것은 `i18n/` 뿐이다 — 다국어 라벨 시드 SQL 로 배포 시
`psql` 로 실행한다. **현재 DB 에는 아직 적용되지 않았다**(`label_code` 0건).

### 찾는 데 쓴 방법

- 자격증명: 추적 파일 전체를 패턴 2종(대입형·접속문자열형)으로 훑었다.
  1차 스캔은 `dsn=…;uid=…;pwd=…` 형태의 세미콜론 접속문자열을 놓쳤다
- 죽은 참조: `settings.X` 중 실제로 없는 속성, `render()` 가 가리키는 없는 템플릿
- 죽은 템플릿: 템플릿 50개를 .py/.html/.js 전체 본문과 대조

### 남겨 둔 것 (보고만)

| 대상 | 이유 |
|---|---|
| `DbUtil.get_rows_list` · `get_row_list` · `sql_remove_comment` | 호출부는 없지만 정상 동작하는 범용 헬퍼다. 쓰이는 형제 메서드와 1:1 대응이라 지우면 되레 비대칭이 된다 |
| 실제 로그인 템플릿 이름이 `login_mes.html` | 짝이던 `login.html` 을 지워 접미사가 혼란스럽지만, 이름 변경은 기능과 무관한 변경이다 |
| `TEMPLATES['DIRS']` 가 없는 `BASE_DIR/templates` 를 가리킨다 | `app_directories.Loader` 로 해석되므로 무해하다 |
| 기준정보 화면 4개(`wm_code`·`wm_unit`·`wm_company`·`wm_depart`) | 메뉴에서만 내렸다. 뷰·템플릿·서비스는 남아 있다 |

## 이 과정에서 고친 결함

브라우저·실서버 검증으로만 드러난 것들이다.

| # | 결함 | 발견 경로 |
|---|---|---|
| 1 | `TEMPLATES` 가 `if DEBUG:` 안에 있어 `DEBUG=False` 부팅 불가 | 코드 검토 |
| 2 | `SECRET_KEY`·DB 비밀번호 하드코딩 | 코드 검토 |
| 3 | 첨부파일 제공 View 에 인증이 없어 누구나 다운로드 | 코드 검토 |
| 4 | 업로드 경로를 요청 파라미터로 문자열 결합 — 상위 경로 탈출 | 코드 검토 |
| 5 | `apiPermissionMap` 200여 건이 호출되지 않는 죽은 코드 (인가 공백) | 코드 검토 |
| 6 | 권한 거부·404·오류가 **HTTP 200** 으로 응답 | 인가 E2E 테스트 |
| 7 | 계정을 비활성화해도 기존 세션이 계속 살아 있음 | 로그인 테스트 |
| 8 | `fn_code_name`·`fn_class_data_text`·`v_menu_folder` 가 원본 DB 에만 존재 | 실서버 기동 |
| 9 | `ComboService.menu_template` 이 결과를 반환하지 않음 | 코드 검토 |
| 10 | **메뉴 폴더가 펼쳐지지 않음** — 한글 폴더명이 DOM id 라 CSS 선택자 파손 | **Playwright** |
| 11 | 이식한 화면이 등록되지 않은 API 경로 호출 | **Playwright** |
| 12 | 작업자 계정에 메뉴 권한이 없어 아무 화면도 못 엶 | **Playwright** |
| 13 | `statistics` 가 `USE_TZ=False` 에서 `ValueError` | 실서버 기동 |
| 14 | 여러 줄 `{# #}` 주석이 **화면에 그대로 출력** — Django 의 `{# #}` 는 한 줄 전용이다. `data/_base.html` 이라 데이터 관리 화면 8개가 전부 영향 | 사용자 보고 |
| 15 | **메뉴 폴더 두 개가 함께 열림** — 한글 폴더명을 치환해 DOM id 로 써서 글자 수가 같은 '데이터 관리'·'시스템 관리' 가 모두 `fld_______` 가 됐다. Bootstrap collapse 는 선택자에 맞는 요소를 전부 토글한다. 폴더 PK 기반 id 로 교체 | 사용자 보고 |
| 16 | `wm_data_item_detail`(검사항목 홈)에 메뉴 행이 없어 **superuser 외 전부 403**. 검사항목 목록에서 드릴다운이 막혀 있었다 | 메뉴 재편 중 |
| 17 | 좌측 메뉴의 검사항목 조회가 **RLS 때문에 빈 결과** — 예외 없이 조용히 사라진다. `tenant_atomic()` 안에서 읽도록 수정 | 브라우저 |
| 18 | 3단 메뉴의 탭 이름이 잎 이름뿐이라 검사항목이 둘이면 `라벨링 작업` 탭이 두 개 생겨 구분 불가. `data-tab-title` 도입 | 브라우저 |

## 계획에서 벗어난 판단

| 항목 | 계획 | 실제 | 사유 |
|---|---|---|---|
| 데이터 관리 화면 | `REWRITE` (WeZonGrid 재작성) | **`ADAPT`** | 라벨링 캔버스 포함 동작하는 화면 11개를 다시 만드는 위험이 크다. 템플릿·CSS·JS 를 보존하고 셸과 API 경로만 맞췄다. 대가로 두 가지 화면 양식이 공존한다 |
| 데이터 API 라우팅 | MES 동적 dispatch | **RESTful + 미들웨어 인가** | 동적 dispatch 는 권한을 붙일 지점이 사라진다 |
| `wm_batch_log` | BackgroundJob 으로 전환 | **제거** | `wm_data_queue` 가 이미 같은 테이블을 본다 |
| `wm_data_dataset` | 신규 화면 추가 | **철회** | Dataset 은 내부 컨테이너다 (§1.6 O-9) |
| `wm_data_labelclass` | 신규 화면 | **철회** | 원본 `system/groups` 는 사용자그룹 관리 화면이었다. 라벨 클래스는 검사항목 상세에서 관리 |
| `settings.DBMS` | 제거 | **유지** | raw SQL 37곳이 분기에 쓴다 |
| 화면 단위 동기 Ajax | Task 0.5 에서 0건 | **완료** | E2E 를 갖춘 뒤 34곳 전부 전환하고 `getSyncData` 헬퍼까지 삭제했다 |
| Phase 8 `0001_initial` | Phase 8 | **Phase 0** | 대상 DB 가 빈 DB 라 스키마 없이는 회귀 확인이 불가능했다 |

## 비전검사 클라이언트 작업 요청 R1~R9 대응 (2026-10-03)

클라이언트 담당의 [요청서](client/SERVER_REQUESTS.md) 중 서버 코드로 고칠 5건을 처리했다.
결정은 [USER_DECISIONS.md](USER_DECISIONS.md) §1.65(DEC-C1~C10), 회신은
[SERVER_API_CONTRACT.md](client/SERVER_API_CONTRACT.md) — 2026-10-06 에 회신문을
계약서로 합쳤다(클라이언트에 전달하는 문서는 이것 하나).

| # | 요청 | 처리 |
|---|---|---|
| R5 | 클라이언트 인증이 통과하지 않음 | 모든 실패가 `AUTH_REQUIRED` 로 뭉개지던 것을 `AUTH_INVALID` 와 구분. **자격증명 재발급은 운영 작업으로 남았다** |
| R6 | 배포·라이선스 Endpoint 없음 | 4경로 추가(인증 없음). `SHA256SUMS.txt` 기록값 사용, HTTP Range 이어받기 직접 구현 |
| R7 | Heatmap Endpoint 없음 | **라우트만** 추가. GPU 미연결이라 항상 404 봉투이고 `heatmap_url` 을 응답에 넣지 않는다 |
| R8 | health 형식이 계약과 다름 | 최상위 `status`·`components`·`version`·`timestamp` 로 되돌리고 DB·Storage 를 실제로 점검해 실패 시 503 |
| R9 | 오류 봉투·처리 순서 | `/api/v1` 미지 경로를 404 봉투로, `Content-Length` 없는 요청을 인증보다 먼저 411 로 |

`/api/v1` 경로가 **7 → 13** 으로 늘었다(heatmap 1 + 배포물 4 + catch-all 1).

확인한 것(단위 테스트 96건 통과, 실파일 검증 포함):

```
GET /api/v1/health          → 200 {"status":"ok","components":{...},"version":"1.0.0",...}
GET /api/v1/nope            → 404 {"error":{"code":"NOT_FOUND",...}}   (이전: 401 HTML)
GET /api/v1/licenses/sources → 200 파일 3개, 크기·sha256 이 요청서 값과 일치
  qt-everywhere-src-6.11.2.tar.xz   1,019,661,552  6dcfbca2…
  Range: bytes=1000-1015 → 206 / Content-Range: bytes 1000-1015/1019661552
```

**아직 하지 않은 것**: 배포물 실파일(1.07GB)의 물리 이동과 클라이언트 자격증명 재발급.
TLS(R1)·3년 보존 정책(R3)은 인프라·법무 결정 대기다.

## 메뉴·조직 정리와 안내 문구 (2026-10-06)

| 요청 | 결과 |
|---|---|
| 쓰지 않는 메뉴 4개 | AI 모델 · 작업 대기열 · 다국어 설정 · 프라퍼티마스터를 `RETIRED_FROM_MENU` 로. 화면·테이블은 남는다. superuser 는 주소로 열 수 있다 |
| 모델 매핑 | 모델 목록은 GPU 서버(Wezard) 연동 뒤 API 로 받는다. 그 전에는 매핑 화면이 빈 목록 안내를 보인다 |
| 조직 | `YEST` 하나. 모든 사용자는 생성 시 소속된다(User 시그널), 기존 사용자는 `seed_initial` 이 채운다 |
| 검사항목 목록 | 조직 필터·조직 행·소속 조직 선택 제거. 플랫폼 관리자 전용(작업자 트리에서 감춤). `조직원` → `배정 인원` |
| 배정 후보 | 비전검사 클라이언트의 서비스 계정을 뺐다 |
| 안내 문구 | `~합니다` 체로 58곳. `/api/v1` 메시지는 R10~R18 뒤 계약 문서와 함께 바꿨다 |
| 데이터 확인창 | 브라우저 기본 창 대신 제품 확인창 모양의 `<dialog>`. 셸·토스트 통합(C-2·C-3)은 하지 않는다 — [09 §6 C](09_UI_DESIGN_SYSTEM.md) |

그 과정에서 고친 결함:

- 사용자 화면에서 만든 사용자는 어느 검사항목에도 **배정할 수 없었다**(조직 소속이 없었다)
- 조직 소속이 있는 사용자는 사용자 화면에서 **지울 수 없었다**(삭제가 RLS 밖에서 돌았다)
- 검사항목 목록의 **검사항목 추가·상태 전환이 줄곧 404·500** 이었다(라우트 불일치)
- 배정 인원을 **검사항목 관리자로 올릴 수 없었다**(`PROJECT_MANAGER` 를 보냈다)
- 권한 거부 등 오류 응답이 **브라우저에 닿지 않았다**(상태줄에 한글 사유)

## 눌러야 드러나는 경로 점검 — G (2026-10-06)

화면을 열기만 하는 `capture_ui` 와 경로만 보는 `verify_links` 로는 F 단계 결함
6건을 하나도 잡지 못했다. 메뉴에 있는 화면의 쓰기 동작 53개 중 e2e 가 실제로
누르던 것은 2개였다. `tests/e2e/test_write_paths.py` 가 데이터 흐름(업로드 →
편집 → 라벨링 → 검수 → 품질 점검 → 스냅샷 → Export)과 관리·시스템·비전 화면의
쓰기 동작을 누른다. 그 과정에서 고친 결함:

- PUT·PATCH·DELETE 요청은 메뉴 **읽기** 권한만 있어도 통과했다(POST 만 쓰기로 봤다)
- 내 정보의 비밀번호 변경이 **비밀번호 정책을 건너뛰었다**
- 그리드 컬럼 설정·라벨 문구 저장을 **로그인만 하면** 할 수 있었다 → 관리자만
- 검사항목 **삭제 요청을 승인·반려할 화면이 없어** 영구히 묶였다 → 목록 화면에 추가
- 한 번이라도 **로그인한 사용자는 삭제할 수 없었다**(`login_log` 외래키)
- 검사항목을 추가해도 **추가 창이 닫히지 않아** 목록을 누를 수 없었다
- 배정 인원 검색칸의 **Enter 가 405** 를 냈다(`action="#"` 폼)
- 라벨 삭제·배정 인원 제외가 **확인 없이** 실행됐다
- 그리드 컬럼 설정의 저장·초기화가 **동기 Ajax** 였다
- 스냅샷 확인 문구가 **없는 상태('검토 필요')** 를 안내했다 — 실제는 '준비 안 됨'이고 Export 불가

G 뒤에 이어서 정리한 것(2026-10-06): 스냅샷·품질 점검의 준비 상태를 한글 라벨로
(마이그레이션 0010, SQL 없음) · Overlay 를 지우거나 교체하면 옛 이미지 파일도 지운다 ·
Overlay 표시 전환·삭제와 즐겨찾기의 실패를 화면이 알린다 · 삭제 실패 문구 함수
(`LogWriter.delete_err_message`)가 스스로 예외를 내던 것 · 쓰지 않는 동기 Ajax
헬퍼와 dropzone 업로더 삭제 · `verify_links.py` 가 경로 전체를 해석한다.

남겨 둔 것(보고만): 메뉴에서 내린 `wm_company` 조회가 없는 `material` 테이블을
참조한다 · 벤더 `dropzone`·`ax5ui` 와 `assets/js/ui/component.fileupload.js` 는 싣는
화면이 없어 보인다(확인 전) · `--ct-danger` 는 죽은 선언이 아니다(벤더 40곳이 쓴다).

## 비전검사 클라이언트 작업 요청 R10~R18 대응 (2026-10-06)

요청서 2차분. 결정은 [USER_DECISIONS.md](USER_DECISIONS.md) §1.66(DEC-C11~C16), 회신은
[SERVER_API_CONTRACT.md](client/SERVER_API_CONTRACT.md) §15 "2차 회신".

- **R16** — `metadata` 길이 초과가 500 `retryable: true` 였다. `parse_metadata` 가 이미지 저장 전에
  검증해 422 `METADATA_INVALID` 로 거절한다. 같은 구간의 500(JSON 객체 아님)·오분류(`IMAGE_INVALID`)·
  예외 원문 노출·`request_id` 절단도 함께 고쳤다
- 숨긴 Overlay 의 이미지가 `/overlays/{id}/image` 로 그대로 나갔다 → 404, 카탈로그 `version: null`
- 추론 경계의 `bbox` 를 Client 형식 `{x1,y1,x2,y2}` 로(R11)
- **저장소 누출 3가지** — `test_settings` 가 `MEDIA_ROOT` 를 격리하지 않아 테스트마다 실제
  `storage/media/` 에 파일이 쌓였고, 검사항목 삭제가 편집 원본·대표 이미지를 남겼고, R16 의 500 이
  이미지 1쌍을 남겼다. 원인을 고친 뒤 DB 가 참조하지 않는 파일 2,206개(1.08MB)를 지웠다
- 데이터(R17) — 실측 검사 기록 5건과 그 이미지, 검사항목 5 의 Overlay 를 지웠다

실서버(PostgreSQL)에서 확인: 길이 초과·`[1,2,3]`·시각 오류·40자 `request_id` 가 모두 422,
Overlay 3 은 200·`image/png`, 5 는 두 경로 모두 404, `client-packages` 는 0.1.5 와 `SHA256SUMS.txt`.

---

## 남은 일

1. **테스트 커버리지 확대** — 데이터 서비스(품질·스냅샷·Export·전처리)와 비전 화면 API 가 아직 얇다.
2. **PostgreSQL 통합 테스트 설정** — `test_settings` 는 SQLite 라 raw SQL 경로(메뉴 트리 등)를 검증할 수 없다. 별도 설정이 필요하다.
3. **Phase 11 배포** — nginx·gunicorn·systemd(웹 + `run_worker`) 구성. 대상 OS(N4) 확인 필요.
4. `.git` 히스토리에 삭제한 dt 자산 125MB 가 남아 있다.

## 운영 전 확인 사항

- `.env` 의 `SECRET_KEY`·`DB_PASSWORD` 를 운영값으로 교체하고 `DEBUG=False`, `ALLOWED_HOSTS` 지정.
- `HTTPS_ENABLED=True` 로 두면 HSTS·Secure 쿠키·SSL 리다이렉트가 함께 켜진다.
- `manage.py seed_initial` 을 다시 실행한다(비밀번호 생략 가능). 메뉴 4개 내림·조직명 YEST·
  사용자 조직 소속이 이때 반영된다(2026-10-06).
- `manage.py seed_demo` 는 **개발용**이다. 운영 DB 에서 실행하지 않는다.
- `.admin_pw` · `.demo_pw` · `.demo_apikey` 는 검증 편의용 파일이다. 운영 전에 지우고 비밀번호를 바꾼다.
- 백그라운드 워커(`manage.py run_worker`)를 띄워야 품질 점검·Export 가 처리된다.
