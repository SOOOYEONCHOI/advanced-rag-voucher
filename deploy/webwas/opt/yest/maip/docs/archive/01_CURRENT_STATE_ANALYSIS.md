# 01. 현재 상태 분석 (Current State Analysis)

> **참고 (2026-09-30)** — 이 문서는 **원본 3개 프로젝트의 분석 기록**이며 원문 그대로 보존한다.
> 이후 사용자 지시로 검사항목이 단일 엔티티로 통합되고 공정·제품·보존정책·이관기능이 제외됐다.
> **목표 구조의 정본은 `USER_DECISIONS.md` §1.6이다.**

- 분석 기준일: 2026-09-30
- 분석 대상: `C:\projects\yest\MES`, `C:\projects\yest\AIDataHub`, `C:\projects\yest\vision-inspection`
- 분석 방법: 소스 직접 탐색(설정·URL·모델·뷰·서비스·템플릿·문서). **실행 검증 없음** — 세 프로젝트 모두 이 워크스페이스에 가상환경이 없고 Django/FastAPI가 설치되어 있지 않다. 따라서 이 문서의 모든 `[FACT]`는 **소스 읽기로 확인한 사실**이며, 런타임 동작으로 확인한 사실이 아니다.
- Commit/Branch: `C:\projects\yest`는 git 저장소가 아니다(`vision-inspection`에만 `.gitignore`/`.gitattributes`가 있으나 `.git` 없음). **버전 식별자를 확정할 수 없다** → `[NEEDS_CONFIRMATION]`
- 표기: `[FACT]` 소스 확인 / `[INFERENCE]` 코드 관계상 추정 / `[NEEDS_CONFIRMATION]` 추가 확인 필요 / `[DECISION_REQUIRED]` 사용자 결정 필요(→ `USER_DECISIONS.md`)

---

## 1. Executive Summary

### 1.1 가장 중요한 발견 5가지

| # | 발견 | 영향 |
|---|---|---|
| 1 | **세 프로젝트를 Django 프로젝트 레벨에서 "병합"할 수 없다.** MES와 AIDataHub는 둘 다 최상위 패키지 이름이 `configurations`/`app`/`domain`이고, 둘 다 `user_group`·`user_profile`·`user_group_menu` 테이블을 **같은 이름·다른 컬럼**으로 정의한다. `[FACT]` | 통합은 "복사·병합"이 아니라 **MES를 기준 골격으로 두고 기능을 이식(port)** 하는 작업이다 → `DEC-001` |
| 2 | **vision-inspection Server는 Django가 아니라 FastAPI다.** 그리고 이미 GPU 추론(torchvision Detection / PatchCore Anomaly), Model·ModelMapping, Catalog, Admin Web, Client API를 **한 프로세스에** 갖고 있다. `[FACT]` | 목표 아키텍처의 "GPU Server(FastAPI)"는 **신규 개발 대상이 아니라 vision-inspection Server의 축소·재배치 대상**이다 → `DEC-006` |
| 3 | **MES의 모든 `/api/<task>/<view>` 엔드포인트에 인가(authorization) 검사가 없다.** 로그인만 하면 누구나 모든 업무 API를 호출할 수 있다. `domain/gui.py`의 `apiPermissionMap`(약 200건)은 정의만 되어 있고 이를 읽는 `get_menu_code_by_taskview()`는 **어디에서도 호출되지 않는다.** `[FACT]` | MES 패턴을 그대로 계승하면 **통합 플랫폼이 인가 공백을 물려받는다.** AIDataHub가 동적 dispatch를 금지한 이유가 정확히 이것이다 → `DEC-014` |
| 4 | **AIDataHub는 MES 패턴을 "금지 항목"으로 명시해 만들어졌다.** `AGENTS.md`가 동적 import dispatch·iframe 탭 셸·자체 그리드 위젯·동기 Ajax를 명시적으로 금지하고, 멀티테넌시(Tenant)·PostgreSQL RLS·Project 역할 권한을 인가 경계로 삼는다. `[FACT]` | "MES 패턴 우선" 지시와 AIDataHub 구현이 **정면 충돌**한다. 데이터관리 화면 10개와 권한 체계 전체의 처리 방식이 결정 사항이다 → `DEC-003`, `DEC-004`, `DEC-013` |
| 5 | **MES에 이미 AI 모델 관리 화면 7개와 `mlops_*` 테이블 5개가 있다.** 단, 이것은 **비전 AI가 아니라 생산데이터 tabular ML**(수요예측·불량예측·소요량예측, scikit-learn)이다. `[FACT]` | 프롬프트 §22가 경고한 "Model Management 중복 구현"이 **이미 존재**한다. 다만 도메인이 달라 통합 대상이 아니라 **범위 분리 대상**이다 → `DEC-009` |

### 1.2 통합 난이도 평가

```text
MES        → Backbone으로 사용 가능. 단 규모가 매우 크고(GUI 374개·테이블 179개)
             인가 공백·테스트 부재라는 구조적 부채가 있다.
AIDataHub  → 기능적으로 가장 완성도가 높고 테스트도 있다(603건). 그러나
             MES 규약과 정반대의 규약으로 만들어져 "그대로 이식"이 불가능하다.
vision-insp→ Server는 스택 자체가 다르다(FastAPI/SQLAlchemy/Alembic).
             Django로 옮길 부분과 GPU Server로 남길 부분을 갈라야 한다.
             Client는 API 6개만 쓰므로 호환 계층 비용이 가장 낮다.
```

---

## 2. 프로젝트별 기술 Stack

| 항목 | MES | AIDataHub | vision-inspection Server | vision-inspection Client |
|---|---|---|---|---|
| Framework | Django 5.0.4 `[FACT]` | Django 5.0.4 `[FACT]` | FastAPI 0.141.1 `[FACT]` | PySide6 (Qt) `[FACT]` |
| Language | Python 3.12 (문서 기준) | Python 3.12 (`__pycache__` = cpython-312) `[FACT]` | Python 3.12+ `[FACT]` | Python 3.12+ `[FACT]` |
| ORM / 마이그레이션 | Django ORM + Django migrations 4개 `[FACT]` | Django ORM + migration 1개(`0001_initial`, 2026-09-30 통합) `[FACT]` | SQLAlchemy 2.0.52 + Alembic 1.20.0, 마이그레이션 13개 `[FACT]` | 없음(로컬 파일 캐시) |
| DB | PostgreSQL `10.10.10.230/yest`, `search_path=public,das,ai` `[FACT]` | PostgreSQL `10.10.10.20/aidatahub_v2` `[FACT]` | PostgreSQL `vision_inspection`(기본값) `[FACT]` | 없음 |
| 인증 | `django.contrib.auth` 세션 + PDA용 JWT(PyJWT 1.7.1) `[FACT]` | `django.contrib.auth` 세션 `[FACT]` | Admin: 서명 세션 쿠키(itsdangerous) / Client: `X-Client-ID` + `X-API-Key`(SHA-256 hash 보관) `[FACT]` | Client ID + API Key 보관 `[FACT]` |
| 프론트엔드 | Django Template + jQuery + Bootstrap(Hyper 테마) + 자체 그리드 `WeZonGrid` + iframe 탭 셸 `[FACT]` | Django Template + jQuery `AjaxUtil` + 자체 SPA(`spa.js`, `#content-canvas` 교체) `[FACT]` | Jinja2 + Bootstrap (Admin Web) `[FACT]` | PySide6 위젯 |
| AI 런타임 | scikit-learn / lightgbm / xgboost / torch 2.5.1 (requirements에 존재) `[FACT]` | 없음 `[FACT]` | torch 2.14.0 + torchvision 0.29.0 `[FACT]` | opencv-python (카메라/전처리) |
| 백그라운드 처리 | `batch_q`/`batch_log` 테이블 + MQTT(paho-mqtt) `[FACT]` | `BackgroundJob` + `manage.py run_worker`/`process_jobs`, `FOR UPDATE SKIP LOCKED` `[FACT]` | CLI(`purge-images`, `fit-anomaly`) + systemd timer `[FACT]` | QThread 워커 + retry 워커 `[FACT]` |
| 배포 | IIS + wfastcgi (Windows) `[FACT]` | nginx + waitress (Linux) `[FACT]` | nginx + uvicorn + systemd (Ubuntu 24.04) `[FACT]` | PyInstaller EXE (Windows 11) `[FACT]` |
| 테스트 | **없음** `[FACT]` (`app/views/test/`는 업무 "검사" 모듈이고 테스트가 아니다) | 82개 파일 / 603건, Playwright 브라우저 테스트 포함 `[FACT]` | 56개 테스트 파일 `[FACT]` | 37개 테스트 파일 `[FACT]` |
| `USE_TZ` | `False` `[FACT]` | `True` `[FACT]` | timezone-aware, 응답은 UTC 고정 `[FACT]` | — |
| `DEFAULT_AUTO_FIELD` | `AutoField`(int4) `[FACT]` | `BigAutoField`(int8) `[FACT]` | `BigInteger` PK `[FACT]` | — |
| `X_FRAME_OPTIONS` | `SAMEORIGIN` (iframe 사용) `[FACT]` | `DENY` `[FACT]` | — | — |
| 세션 쿠키명 | `mes25-1` `[FACT]` | `aidatahub-v2` `[FACT]` | — | — |
| 다국어 | `label_code`/`label_code_lang` 기반 4언어(ko/en/zh/vi) `[FACT]` | 한국어 고정, 라벨 API i18n **도입 금지**가 규약 `[FACT]` | 한국어 고정 | 한국어 고정 |

### 2.1 규모 (실측 카운트)

| 항목 | MES | AIDataHub | vision Server | vision Client |
|---|---:|---:|---:|---:|
| Python 파일(뷰 계층) | 363 | 34 | 77 (src 전체) | 66 (src 전체) |
| 서비스 모듈 | 101 | 46 | — (application/services 12) | — |
| HTML 템플릿 | 409 | 33 | 22 | — |
| DB 테이블(`db_table` 선언 수) | 179 | 25 모델 | 11 테이블 | — |
| 등록 화면(GUI 항목) | 374 | 10 | Admin 라우트 9개 그룹 | — |
| 마이그레이션 | 4 | 1 | 13 | — |

> MES 규모가 AIDataHub의 10배 이상이다. "MES를 Backbone으로 한다"는 결정은 **MES 179개 테이블과 374개 화면 중 무엇을 통합 플랫폼에 가져올지**를 반드시 함께 결정해야 한다 → `DEC-023`

---

## 3. MES Inventory (Backbone 후보)

### 3.1 프로젝트 구조 `[FACT]`

```text
MES/
├─ configurations/        settings.py(단일), urls.py, middleware/response.py, wsgi.py
├─ app/
│  ├─ views/              업무별 폴더 34개 + __init__.py(디스패처 635줄)
│  ├─ templates/          업무별 폴더 + app/{index,layout_page,login}.html
│  └─ static/             assets(Hyper 테마), wezongrid, lang, js/mqtt.js
├─ domain/
│  ├─ models/             check.py haccp.py mes.py mlops.py sequence.py system.py user.py
│  ├─ services/           업무별 폴더 + _common/_form/sql.py/logging.py/common.py/mqtt.py
│  ├─ gui.py              메뉴(GUI) 정의 965줄 + apiPermissionMap
│  ├─ migrations/         0001_initial(4952줄) ~ 0004
│  └─ _sql/database.sql   7줄 (DB·스키마 생성만)
├─ manage.py
└─ .agent_reference/      모듈별 참고문서
```

**Django App은 `app`과 `domain` 두 개뿐이다.** 업무 분리는 Django App이 아니라 **디렉터리 + 동적 import**로 한다.

> `AGENTS.md`/`ReadMe.txt`는 "스키마는 Django 마이그레이션이 아닌 `domain/_sql/database.sql` 기준으로 관리한다"고 적고 있으나, **실제로는 `domain/migrations/0001_initial.py`(Django 5.0.4 생성, 2026-02-06)가 존재하고 `database.sql`은 DB·스키마 생성 7줄뿐이다.** 문서가 실제 구현과 다르다. `[FACT]`

### 3.2 URL / API 라우팅 `[FACT]`

`configurations/urls.py`는 화면·API를 개별 등록하지 않고 **4개의 동적 디스패처**로 처리한다.

| URL 패턴 | 처리 클래스 | 동작 |
|---|---|---|
| `/api/<task_name>/<view_name>` | `ApiModuleView` | `app.views.<task>.<view>` 모듈을 `importlib`로 로드해 **모듈명과 같은 이름의 함수**를 `func(self)`로 호출. 반환값을 JSON으로 직렬화 |
| `/api/files/<view_name>` | `FilesView` | `app.views.files.<view>` 동적 로드. CSRF 면제 |
| `/gui/<gui_code>/[<template_key>]` | `GUITemplatesView` | `GUIConfiguration.get_gui_info(gui_code)` → 템플릿 렌더 + **권한 검사** + `menu_use_log` 기록 |
| `/page/<folder>/<template_name>` | `TemplatePathView` | `page/<folder>/<name>.html` 직접 렌더. **권한 검사 없음** |
| `/pda/<task_name>/<view_name>` | `PDAView`(JWT) | `app.views.pda.<task>` 동적 로드 |

고정 등록된 것: `/`, `/mobile/`, `/login/`, `/logout/`, `/setup/`, `/error/`, `/api/alive`, `/api/das_device`, `/api/v1/token/*`, `/api/ai/nl2sql/sse`, `/api/ai/mes_chatbot/sse`, `/dt/<filename>`, `/public/exhibition/`.

### 3.3 View 작성 패턴 `[FACT]`

```python
# app/views/definition/unit.py  ← 파일명·함수명·URL이 모두 'unit'
from domain.services.definition.unit import UnitService

def unit(context):            # context = ApiModuleView 인스턴스
    gparam = context.gparam   # GET 파라미터 dict
    posparam = context.posparam
    action = gparam.get('action', 'list')
    try:
        if action == 'list':   items = service.get_unit_list(...)
        elif action == 'detail': ...
        elif action == 'save':   ...   # ORM 직접 사용
        elif action == 'delete': ...
    except Exception as ex:
        LogWriter.add_dblog('error', source, ex)
        return {'success': False, 'message': str(ex)}
    return items
```

- **단일 함수 + `action` 파라미터 분기**가 View의 표준 형태다.
- 응답 규약: 조회는 **행 리스트 그대로**, 변경은 `{'success': bool, 'message': str}`. 공통 envelope 없음.
- 예외는 뷰 함수 내부에서 잡아 `success:False`로 바꾼다. **HTTP status는 항상 200.**
- `Q` 또는 `_dic` 로 시작하는 파라미터는 JSON 문자열로 받아 `json.loads(parse_float=Decimal)`로 파싱한다(`make_parameter`).
- 전체 요청이 `CommonUtil.decimal_context()` 안에서 실행된다(Decimal 정밀도 고정).

### 3.4 Service / Repository 패턴 `[FACT]`

```python
# domain/services/definition/unit.py
class UnitService:
    def get_unit_list(self, unit_name):
        sql = '''select id, "Name" as name ... from unit where 1 = 1 '''
        if unit_name != '': sql += ''' and upper("Name") like ... '''
        items = DbUtil.get_rows(sql, {'unit_name': unit_name})   # raw SQL
```

- **조회는 raw SQL(`DbUtil.get_rows`/`get_row`), 변경은 Django ORM** 이 지배적 패턴이다.
- `DbUtil`(`domain/services/sql.py`)은 `django.db.connection` 커서를 직접 쓰고 결과를 dict 리스트로 변환한다. `%(name)s` 바인딩을 사용하므로 SQL 인젝션은 파라미터 경로에서는 막혀 있다. 단 **문자열 연결로 SQL을 조립**하므로 조립부에 파라미터 아닌 값이 들어가면 위험하다 `[INFERENCE]`.
- `DbUtil`에는 MSSQL 분기(`pyodbc`, `%(x)s → %s` 치환)가 남아 있다. `settings.DBMS = 'POSTGRESQL'`이므로 현재는 사용되지 않는 경로다. `[FACT]`
- Repository/DAO 계층은 **없다.** Service가 SQL을 직접 갖는다.

### 3.5 인증 / 권한 / 메뉴 `[FACT]`

**모델**

| 모델 | 테이블 | 내용 |
|---|---|---|
| `django.contrib.auth.models.User` | `auth_user` | **`AUTH_USER_MODEL`을 커스터마이즈하지 않는다** |
| `UserProfile` | `user_profile` | `User`(OneToOne, PK) + `UserGroup` + `Factory` + `Company` + `Depart` + `CompCode` + `lang_code` + `access_token` + `refresh_token` + `Name` + `password_changed` |
| `UserGroup` | `user_group` | `Code`(unique) / `Name` / `Disabled` / `Description` |
| `UserGroupMenu` | `user_group_menu` | `UserGroup` + `MenuCode` + `AuthCode`(문자열, `"R"`/`"W"` 포함 여부로 판정) |
| `MenuFolder` / `MenuItem` | `menu_folder` / `menu_item` | 메뉴 트리 |
| `MenuUseLog` | `menu_use_log` | 화면 진입 로그 |
| `LoginLog` / `SystemLog` / `SFLog` | `login_log` / `sys_log` / `sf_log` | 감사 로그 |

**권한 판정** (`AccountService.check_user_auth`)

```text
is_superuser              → 'RW'
UserGroup.Code == 'dev'   → 'RW'
Code in (admin, dev) and gui_code in (wm_user, wm_user_group, wm_user_group_menu) → 'RW'
그 외                     → UserGroupMenu(UserGroup, MenuCode=gui_code).AuthCode
```

`WebUserInfo.set_authcode()`가 `"R" in authcode` → `can_read`, `"W" in authcode` → `can_write`로 풀어 템플릿에 넘기고, 화면에서 `yullinAuth.removeWriteButton()`이 쓰기 버튼을 제거한다. `[FACT]`

**`[FACT]` 중대한 공백 — API 인가 없음**

- `check_user_auth`는 `app/views/__init__.py:240`, 즉 **`GUITemplatesView.get()`에서만** 호출된다.
- `ApiModuleView`에는 인가 검사가 없다(클래스 docstring에 `'''권한 처리여부 결정할 것'''`이라고 적혀 있다).
- `GUIConfiguration.taskview_menu_code_map()`이 만드는 `apiPermissionMap`(약 200개 `task/view → [menu_code]` 항목)을 읽는 유일한 함수 `get_menu_code_by_taskview()`는 **프로젝트 전체에서 호출되지 않는다.**
- 결론: **로그인한 사용자는 메뉴 권한과 무관하게 모든 업무 API를 직접 호출할 수 있다.** 메뉴 숨김과 버튼 제거는 UI 차원의 조치일 뿐이다.
- `TemplatePathView`(`/page/<folder>/<name>`)도 권한 검사가 없다.

### 3.6 프론트엔드 구조 `[FACT]`

- 셸: `app/templates/app/index.html`(+`index_page.js`) — 헤더 + 좌측 메뉴 + **탭(`.page-tabs`)**. 업무 화면은 `/gui/<code>/`를 **iframe**으로 띄운다(`layout_page.html`이 `window.parent.$('.header')`, `window.parent.$('.page-tabs')`를 직접 조작하고, `X_FRAME_OPTIONS='SAMEORIGIN'`에 `#Iframe 오류 관련 수정` 주석이 있다).
- 업무 템플릿: `{% extends %}` 없이 `layout_page.html`을 base로 하는 `{% block content %}` / `{% block scripts %}` 구조.
- 공통 JS: `common.js`, `bscommUtil.js`, `grid.js`, `decimal-util.js`, `system.js`(템플릿에 인라인 include).
- 그리드: 자체 라이브러리 `WeZonGrid`(`static/wezongrid/`), Excel export는 SheetJS 의존.
- Ajax: `AjaxUtil.getSyncData()` **동기 Ajax가 셸에서도 쓰인다**(`layout_page.html`의 즐겨찾기 로드).
- 모달: `modal.open({iframe:{...}})` — 모달도 iframe이다.
- 다국어: `label_code`/`label_code_lang`/`grid_col_lang` 테이블 + `static/lang/` 리소스.

### 3.7 시스템 관리 기능 목록 `[FACT]`

`app/views/system/` 41개 모듈 / `app/templates/system/` 17개 화면.

| 기능 | View | Template | 모델/테이블 |
|---|---|---|---|
| 사용자 | `system/user.py` | `system/user.html` | `auth_user` + `user_profile` |
| 사용자그룹 | `system/usergroup.py` | `system/usergroup.html` | `user_group` |
| 메뉴권한 | `system/usergroupmenu.py` | `system/usergroup_menu.html` | `user_group_menu` |
| 메뉴 설정 | `system/menus.py`, `menu_setup.py`, `mobile_menu.py` | — | `menu_folder`, `menu_item` |
| 공통코드 | `system/code.py`, `system_code.py`, `user_code.py`, `systemcode_setup.py` | `system/system_code.html` | `sys_code`, `user_code` |
| 다국어 | `system/labelcode.py`, `menu_language.py` | `system/multi_language.html`, `menu_language.html` | `label_code`, `label_code_lang` |
| 시스템옵션 | `system/system_option.py`, `factory_setup.py` | — | `sys_option` |
| 로그 | `loginlog.py`, `menulog.py`, `systemlog.py`, `batch_log.py`, `sflog.py`, `kpc_kpi_log.py` | `login_log.html`, `menu_log.html`, `system_log.html`, `batch_log.html`, `sf_log.html` | `login_log`, `menu_use_log`, `sys_log`, `batch_log`, `sf_log` |
| 그리드 설정 | `grid_setting.py` | — | `grid_col`, `grid_col_lang` |
| 즐겨찾기 | `bookmark.py` | — | `bookmark` |
| 속성/분류 | `property_master.py` | `system/prop_master.html` | `prop_master`, `prop_data`, `class_master`, `class_data` |
| 근무조 | `shift.py` | `system/shift.html` | `shift` |
| 부서 | `depart.py` | — | `depart` |
| 공지 | `notice.py`, `notice_setting.py`, `title_notice.py` | `system/title_notice.html` | `board`, `board_reply` |
| 스토리보드 | `storyboard.py` | `system/storyboard_config.html` | `storyboard_item` |
| DAS 설비연계 | `das_config.py`, `das_server.py`, `das_server_setup.py`, `plc_write.py`, `tag_data_make.py` | `system/das_config.html`, `tagdata_make.html` | `das_config`, `das_server`, `tag`, `tag_dat` |
| DB 스키마 조회 | `db_schema.py` | — | — |

**기준정보**(`app/views/definition/`) 35개 모듈: 자재·자재그룹·BOM·공정·라우팅·설비·설비그룹·워크센터·창고·거래처·단위·불량유형·정지원인·금형·작업자·부서·에어리어·태그·문서양식 등.

### 3.8 MES 기술 부채 `[FACT]` / `[NEEDS_CONFIRMATION]`

| # | 항목 | 근거 | 통합 영향 | 유지 가능 | 권장 |
|---|---|---|---|---|---|
| D1 | **API 인가 없음** | §3.5 | 통합 플랫폼이 인가 공백을 상속. AIDataHub의 Project/Group 권한과 결합 불가 | 불가 | `ApiModuleView`에 인가 훅 추가 → `DEC-014` |
| D2 | **`SECRET_KEY`·DB 비밀번호 평문 하드코딩** (`settings.py`) | `SECRET_KEY='cc69427f-...'`, `PASSWORD='****'` `[FACT]` | 통합 시 그대로 옮기면 소스에 운영 비밀이 남는다 | 불가 | 환경변수화(AIDataHub 방식 참고) |
| D3 | **`DEBUG = True` 하드코딩**, 그 아래 `if DEBUG:` 블록 안에서만 `TEMPLATES`를 정의 | `settings.py` `[FACT]` | `DEBUG=False`로 바꾸면 **`TEMPLATES`가 정의되지 않아 앱이 뜨지 않는다** `[INFERENCE]` | 불가 | 설정 분리 필수 |
| D4 | **`settings.JWT_SECRET_KEY` / `JWT_ALGORITHM`이 정의되어 있지 않다** | `app/views/account.py`, `app/views/mobile.py`에서 10회 참조, `settings.py`에 선언 없음 `[FACT]` | PDA/모바일 토큰 로그인 경로가 `AttributeError`로 실패할 것으로 보인다 `[INFERENCE]` | — | 현재 범위(PDA 제외)에서는 이관 대상 아님 |
| D5 | **`domain/models/user.py`가 `django.contrib.postgres.fields.JSONField`를 import** | `user.py:10` `[FACT]` | 이 심볼은 Django 4.0에서 제거되었다. requirements는 Django 5.0.4다 → import 시점에 `ImportError`가 날 것으로 보인다 `[NEEDS_CONFIRMATION]`(실행 검증 못 함) | — | 실제 배포 Django 버전 확인 필요. 이관 시 제거 |
| D6 | **테스트가 없다** | §2.1 `[FACT]` | MES Backbone 회귀 검증 수단이 없다. 프롬프트 §20의 "MES Backbone 회귀 테스트"를 **처음부터 작성해야 한다** | — | Phase 1에 회귀 테스트 신규 작성 |
| D7 | **고객사 전용 분기가 기준소스에 섞여 있다** | 파일 접미사 `_junshi`/`_snp`/`_woori`/`_sejun`/`_gs`/`_pzas`, `gui.py`·`apiPermissionMap`에 고객사 블록 `[FACT]` | 통합 시 무엇을 가져올지 판단 비용이 크다 | 가능(선별) | 시스템관리+기준정보 최소셋만 추출 → `DEC-023` |
| D8 | **`domain/services/lang.py.deprecated`, `master_t.txt` 등 산출물이 소스에 남아 있다** | `[FACT]` | 낮음 | 가능 | 이관 시 제외 |
| D9 | **동기 Ajax가 공통 셸에 있다** | `layout_page.html`의 `AjaxUtil.getSyncData` `[FACT]` | 화면 전환 지연. AIDataHub 규약과 충돌 | 가능 | 이관 시 비동기화 |
| D10 | **전시회/데모 코드가 기준소스에 있다** | `wm_dashboard_exhibition_*`, `public/exhibition/`, `dt_main.html`(주석에 "데이터 BLOCKED") `[FACT]` | 낮음 | 가능 | 이관 제외 |

---

## 4. AIDataHub Inventory (Data Management 원천)

### 4.1 구조 `[FACT]`

```text
AIDataHub/
├─ configurations/   settings.py, test_settings.py, urls.py(명시 등록 60여 개), middleware/request_id.py
├─ app/
│  ├─ views/         account/ common/ home/ project/{data_manage,home,labeling,review,snapshot}/ system/{groups,organizations,projects,users}/
│  ├─ templates/     app/layout.html + 업무별 폴더
│  └─ static/        js/{common.js, spa.js}, css/layout.css
├─ domain/
│  ├─ models/        dataset.py governance.py image.py labeling.py project.py tenancy.py user.py
│  ├─ services/      access/ account/ activity/ dataset/{export/} home/ project/ tenancy/ workspace/
│  ├─ gui.py         GUI_ITEMS(10개) + 메뉴 스냅샷 빌더
│  ├─ tenancy.py     TenantMiddleware, tenant_atomic, RLS 컨텍스트
│  ├─ storage.py     테넌트별 업로드 경로
│  ├─ migrations/    0001_initial (모델 전체 + TENANT_TABLES RLS)
│  └─ management/    run_worker, process_jobs, seed_*
├─ tests/            82개 파일 / 603건
├─ scripts/verify_rls.py
└─ docs/             DEPLOYMENT.md PROJECT_STATUS.md TROUBLESHOOTING.md architecture/
```

App label: `app` = `app`, `domain` = **`ai_domain`**(명시 지정). `[FACT]`

### 4.2 도메인 모델 (25개) `[FACT]`

| 영역 | 모델 | 테이블 | 비고 |
|---|---|---|---|
| 테넌시 | `Tenant` | `vision_data_tenant` | PK가 **UUID** |
| | `TenantMembership`, `Group`, `GroupMember` | `vision_data_tenantmembership`, `..._group`, `..._groupmember` | 조직·작업그룹 |
| | `TenantOwnedModel`(추상) | — | 모든 업무 모델이 `tenant` FK(NOT NULL)를 가진다 |
| 과제 | `Project` | `vision_data_project` | `task_type`(OBJECT_DETECTION / CLASSIFICATION / ANOMALY_DETECTION), `status`, `cover_image`, `upload_guideline` |
| | `ProjectAssignment` | `vision_data_projectassignment` | `role`(PROJECT_MANAGER / WORKER) |
| | `ProjectGroupAccess` | `vision_data_projectgroupaccess` | `can_view` / `can_upload` / `can_label` |
| | `ProjectDeletionRequest` | `vision_data_projectdeletionrequest` | 삭제 승인 워크플로 |
| | `LabelClass` | `vision_data_labelclass` | `name`, `display_name_ko`, `color`, `is_defect`, `annotation_shape`(BBOX/POLYGON) |
| | `ActivityLog` | `vision_data_activitylog` | 감사 로그 |
| 데이터셋 | `Dataset` | `vision_data_dataset` | `project` FK, `status`(RAW→VALIDATED→LABELED→CURATED→EXPORTED) |
| 이미지 | `ImageAsset` | `vision_data_imageasset` | `file`/`thumbnail`/`original_file`, `preprocess`(JSON), `sha256`(테넌트·데이터셋 내 unique), `ingestion_status`, `label_status`(UNLABELED→IN_PROGRESS→SUBMITTED→REWORK→APPROVED) |
| | `Annotation` | `vision_data_annotation` | `geometry_type`(NONE/BBOX/POLYGON), `geometry`(JSON), `attributes`(JSON) |
| 라벨링 | `LabelingTask` | `vision_data_labelingtask` | claim/heartbeat/draft/submit, `lease_token`·`lease_expires_at`, 이미지당 활성 1건 부분 unique 제약 |
| | `StandardImage` | `vision_data_standardimage` | 데이터 표준 예시 이미지 |
| 거버넌스 | `DataStandard` | `vision_data_datastandard` | `definition`(JSON), 프로젝트별 버전 |
| | `QualityRun` / `QualityFinding` | `vision_data_qualityrun` / `..._qualityfinding` | 품질점검 4종, `readiness`(READY/WARNING/NOT_READY) |
| | `DatasetVersion` | `vision_data_datasetversion` | 불변 스냅샷 + `manifest`(JSON) |
| | `ExportJob` | `vision_data_exportjob` | 8포맷 |
| | `BackgroundJob` | `vision_data_backgroundjob` | `job_type`(QUALITY/EXPORT) |
| 사용자 | `UserGroup`, `UserProfile`, `UserGroupMenu` | **`user_group`, `user_profile`, `user_group_menu`** | **MES와 동일 테이블명 / 다른 컬럼** |
| | `AuthenticationLog` | `vision_data_authenticationlog` | 로그인/로그아웃 |

### 4.3 기능 → URL → View → Service → Model 추적 `[FACT]`

| 사용자 기능 | URL(화면) / API | View | Service | Model → Table |
|---|---|---|---|---|
| 데이터 관리(목록·상세·업로드·전처리·삭제) | `/dataset/manage/` · `/api/images/`, `/api/images/upload/`, `/api/images/<id>/`, `/api/images/<id>/preprocess/` | `app/views/project/data_manage/api.py` (`ImageListApiView`, `ImageUploadApiView`, `ImageDetailApiView`, `ImagePreprocessApiView`) | `dataset/image.py`, `dataset/preprocess.py` | `ImageAsset` → `vision_data_imageasset` |
| 이미지 보호 서비스 | `/media/image/<id>/`, `/media/image/<id>/thumbnail/`, `/media/project-cover/<id>/`, `/media/export/<id>/` | `PrivateImageView` 등 | — | 파일 + 권한 확인 |
| 라벨링(분류/탐지/이상) | `/dataset/labeling/` · `/api/labeling/images/<id>/claim/`, `/api/labeling/tasks/<id>/{heartbeat,draft,submit}/` | `app/views/project/labeling/api.py` | `dataset/labeling_task.py`, `dataset/annotation.py` | `LabelingTask`, `Annotation` |
| 검수(승인/재작업) | `/dataset/review/` · `/api/review/images/<id>/<action>/` | `app/views/project/review/api.py` | `dataset/review.py` | `ImageAsset.label_status` |
| 데이터 품질 점검 | `/api/quality-runs/` | `app/views/project/snapshot/api.py` | `workspace/quality.py`, `dataset/job.py` | `QualityRun`, `QualityFinding`, `BackgroundJob` |
| 스냅샷(불변 버전) | `/workspace/versions/` · `/api/dataset-versions/` | `DatasetSnapshotApiView` | `workspace/version.py` | `DatasetVersion` |
| Dataset Export | `/api/exports/` | `ExportJobApiView` | `dataset/export/*` (8 exporter) | `ExportJob`, `BackgroundJob` |
| 과제(프로젝트) 관리 | `/projects/` · `/api/projects/...` | `app/views/project/home/api.py` | `project/{project,creation,deletion,assignment,access}.py` | `Project`, `ProjectAssignment`, `LabelClass` |
| 조직/작업그룹 | `/accounts/organizations/` · `/api/account/organizations/...` | `app/views/system/organizations/*` | `tenancy/{administration,work_group,access}.py` | `Tenant`, `TenantMembership`, `Group`, `GroupMember`, `ProjectGroupAccess` |
| 사용자/사용자그룹 | `/accounts/users/`, `/accounts/groups/` · `/api/account/users/...`, `/api/account/groups/...` | `app/views/system/{users,groups}/api.py` | `account/{user,user_group,menu_auth}.py` | `auth_user`, `user_profile`, `user_group`, `user_group_menu` |
| 홈(통계·큐·활동) | `/` · `/api/home/statistics/`, `/api/labeling/queue/`, `/api/activity-log/recent/` | `app/views/home/api.py` | `home/{statistics,queue}.py`, `activity/query.py` | 여러 |
| 인증 | `/accounts/login/`, `/accounts/logout/`, `/tenant/select/`, `/accounts/password/` | `app/views/account/*` | `account/{authentication,authentication_log}.py` | `auth_user`, `AuthenticationLog` |
| 내비게이션 | `/api/navigation/` | `app/views/common/navigation.py` | `domain/gui.py` `build_snapshot` | — |
| 헬스체크 | `/healthz/` | `app/views/common/health.py` | — | — |

**Export 8포맷** `[FACT]`

| 과제 유형 | 지원 포맷 |
|---|---|
| CLASSIFICATION | `IMAGEFOLDER`, `CSV`, `CLASSIFICATION_JSON` |
| OBJECT_DETECTION | `COCO`, `YOLO` |
| ANOMALY_DETECTION | `MVTEC`, `IMAGE_MASK`, `ANOMALY_JSON` |

> `Project.TaskType`(3종)이 **vision-inspection의 `inspection_type`(DETECTION / ANOMALY 2종)보다 넓다.** CLASSIFICATION은 검사 측에 대응 항목이 없다 `[FACT]` → `DEC-005` 관련.

### 4.4 권한 체계 (4중) `[FACT]`

```text
1. Django 내부       is_staff / is_superuser  ← 플랫폼 관리자가 아니다(AGENTS.md 명시)
2. 플랫폼 관리자      UserProfile.UserGroup.Code == "admin"
3. 시스템 메뉴 권한   UserGroupMenu(R/RW)  ← MES와 같은 축
4. 조직·과제 권한     TenantMembership + ProjectAssignment.role + ProjectGroupAccess + PostgreSQL RLS
```

- 작업 → capability 매핑은 `domain/services/access/authorization.py`의 `ACTION_CAPABILITIES` 한 곳에만 있다.
- 화면 권한은 `gui_item(...)` 옵션(`project`, `manager_only`, `redirect_home`, `menu_auth`, `admin_only`)으로 선언한다.
- RLS: `0001_initial`의 `TENANT_TABLES` 19개 테이블에 `app.tenant_id` 기반 정책. `tenant_atomic(tenant)` 안에서 `SET LOCAL`.
- **메뉴 숨김은 인가 경계가 아니라는 것이 명문 규약이다.** 직접 URL/API 요청도 서버에서 거부한다.

### 4.5 표현 계층 규약 `[FACT]` — MES와 정반대

| 항목 | AIDataHub 규약 | MES 실제 |
|---|---|---|
| 라우팅 | `configurations/urls.py`에 **명시 등록**. 동적 import dispatch **금지**("권한을 붙일 지점이 사라진다") | 동적 import dispatch |
| 화면 셸 | 자체 SPA — `spa.js`가 `#content-canvas`만 교체. **iframe 탭 셸 금지** | iframe 탭 셸 |
| 그리드 | 표준 마크업. **자체 그리드 위젯 금지** | WeZonGrid |
| Ajax | 비동기 콜백(`AjaxUtil.getAsyncData`). **동기 Ajax 금지** | 동기 Ajax 포함 |
| API 응답 | 성공 `{"ok":true,"message":...,"data":{...}}` / 실패 `{"ok":false,"message":...,"code":...,"errors":{...}}` + **의미에 맞는 HTTP status** | 리스트 그대로 또는 `{success,message}`, status 항상 200 |
| 화면 스크립트 | 템플릿 `{% block extra_js %}` 안, `var XxxPage = class {...}` + `destroy()` 필수(SPA 재진입 대응) | 템플릿 `{% block scripts %}`, 규약 없음 |
| i18n | 한국어 고정. **라벨 API i18n 도입 금지** | `label_code` 기반 4언어 |
| 파일 서비스 | `MEDIA_URL` 공개 금지. 권한 확인 View만 | `FILE_UPLOAD_PATH` + `files/` 뷰 |

### 4.6 `Project` 도메인의 실제 결합도 `[FACT]`

`Project`를 제거할 수 있는지 판단하기 위한 근거:

| 모델 | `project` FK | null 허용 |
|---|---|---|
| `Dataset` | O | X |
| `LabelClass` | O | X |
| `DataStandard` | O | X |
| `StandardImage` | O | X |
| `LabelingTask` | O | X |
| `ProjectAssignment` / `ProjectGroupAccess` / `ProjectDeletionRequest` | O | X / X / O |
| `ActivityLog` | O | O |
| `ImageAsset` | 간접(`dataset.project`) | — |
| `Annotation` | 간접(`image.dataset.project`, `label_class.project`) | — |

또한 `Project.task_type`이 **라벨링 화면 분기와 Export 포맷 결정의 축**이다(`PROJECT_EXPORT_FORMATS`, `get_exporter_class`). 메뉴 구성도 프로젝트 단위로 트리를 만든다(`gui.py` `_project_menu`).

→ **`Project`는 AIDataHub 데이터 도메인의 필수 축이며, 제거하면 데이터 관리 기능 전체를 재작성해야 한다.** `[FACT]` → `DEC-005`

---

## 5. vision-inspection Inventory

### 5.1 Server (FastAPI) 구조 `[FACT]`

```text
server/src/vision_inspection_server/
├─ main.py            앱 조립(미들웨어 순서, 라우터, 오류 봉투, 운영 시 /docs 비활성)
├─ middleware.py      BodySizeLimit(413/411), SecurityHeaders
├─ settings.py        pydantic-settings, config/.env
├─ cli.py             create-admin / create-client / seed-catalog / fit-anomaly / export-detection / purge-images
├─ api/               /api/v1/*  ← VisionInspectionClient 계약
│  ├─ routes/         health catalog overlays inspections history licenses client_packages
│  ├─ schemas/        UtcDatetime, 오류 봉투, downloads
│  └─ dependencies/   client_auth(X-Client-ID/X-API-Key), rate_limit(Client별 분당 한도)
├─ admin/             /admin/*  ← Jinja2 관리 웹 (22 템플릿)
│  ├─ routes/         auth dashboard processes products inspection_items clients models inspections retention migration
│  └─ dependencies/   auth(세션+DB 재확인+CSRF), login_throttle
├─ application/services/  catalog inspection overlay result_image client_auth client_admin
│                         admin_auth model_admin model_artifacts retention image_migration
├─ domain/            models.py errors.py ports.py  ← FastAPI/SQLAlchemy/AI 라이브러리 import 금지
└─ infrastructure/
   ├─ database/       SQLAlchemy models·repositories·session
   ├─ inference/      torchvision_adapter(DETECTION) · patchcore_adapter(ANOMALY) · artifacts
   ├─ storage/        local(LocalFileStorage) · image_validation · distribution
   ├─ migration/      local_export (ImageMigrationPort 임시 구현)
   └─ security/       password(PBKDF2) · api_key
```

### 5.2 Server DB 테이블 (11개) `[FACT]`

| 테이블 | PK | 주요 컬럼 |
|---|---|---|
| `processes` | BigInteger | `code`(unique), `name`, `display_order`, `active` |
| `products` | BigInteger | `process_id` FK, `code`, `name`, `description`, `active` — (`process_id`,`code`) unique |
| `inspection_items` | BigInteger | `product_id` FK, `code`, `name`, `inspection_type`(**PG native enum `inspection_type`**: DETECTION/ANOMALY), `display_order`, `active` |
| `admin_users` | BigInteger | `username`(unique), `password_hash`(PBKDF2), `active`, `last_login_at` |
| `clients` | BigInteger | `client_id`(unique), `name`, `api_key_hash`(SHA-256, 64자), `active`, `last_seen_at` |
| `models` | BigInteger | `name`, `inspection_type`, `version`, `artifact_path`, `runtime`, `threshold`, `active` |
| `model_mappings` | BigInteger | `inspection_item_id` FK, `model_id` FK, `active` — **활성 매핑은 검사항목당 1개**(부분 unique index `WHERE active`) |
| `overlays` | BigInteger | `inspection_item_id`(unique) FK, `version`, `visible`, `x/y/width/height`(현재 전부 0,0,1,1), `opacity`, `image_path` |
| `inspections` | **String(36) = UUID 문자열** | `request_id`(unique), `client_id` FK, `inspection_item_id` FK, `image_path`, `status`(RECEIVED/SUCCESS/FAILED), capture 메타(`capture_timestamp`,`client_version`,`camera_vendor`,`camera_serial`), 결과(`abnormal`,`model_name`,`model_version`,`defects` JSON,`anomaly_score`,`threshold`,`heatmap_path`,`inference_ms`,`error_message`) |
| `retention_policies` | Integer, **항상 id=1** | `enabled`(기본 false), `original_days`(90), `heatmap_days`(30) |
| `image_migrations` | `inspection_id`(PK/FK) | `status`(SENT/FAILED/NO_IMAGE), `external_id`, `error_message`, `attempts` |

- `InspectionResult`는 **별도 테이블이 없다.** `inspections` 행의 컬럼으로 보관한다. `[FACT]`
- `AdminAuditLog`는 **관리하지 않기로 결정된 상태**다(`ARCHITECTURE.md` §3). `[FACT]`

### 5.3 Client가 실제로 호출하는 API — 6개뿐 `[FACT]`

`client/src/vision_inspection_client/infrastructure/api/server_client.py` 전체를 확인한 결과:

| # | Method | Path | 인증 | 용도 |
|---|---|---|---|---|
| 1 | GET | `/api/v1/health` | 없음 | 연결·구성요소 상태 |
| 2 | GET | `/api/v1/catalog` | Client | 공정→제품→검사항목 **통합 조회**(시작 시 1회) |
| 3 | POST | `/api/v1/inspections` | Client | `multipart/form-data`: `image` + `metadata`(JSON 문자열) |
| 4 | GET | `/api/v1/inspections/by-request/{request_id}` | Client | **retry 전 항상 먼저 호출**(중복 방지) |
| 5 | GET | `/api/v1/overlays/{inspection_item_id}` | Client | Overlay 메타 |
| 6 | GET | `/api/v1/overlays/{inspection_item_id}/image` | Client | Overlay 이미지(PNG/JPEG) |

Client가 **호출하지 않는** 서버 엔드포인트: `/catalog/version`, `/catalog/processes`, `/catalog/products`, `/catalog/inspection-items`, `/history`, `/inspections/{id}`, `/inspections/{id}/result-image`, `/inspections/{id}/heatmap`, `/licenses/sources`, `/client-packages`. (docstring에 "화면에서 쓰지 않는 Endpoint는 부르지 않는다"고 명시) `[FACT]`

> 이것이 통합 계획에서 가장 유리한 사실이다. **Client 무변경 호환에 필요한 Django 측 구현은 6개 엔드포인트다.** → `DEC-007`

### 5.4 Client ↔ Server 계약 핵심 `[FACT]`

**인증** — 헤더 `X-Client-ID` + `X-API-Key`. 서버는 API Key를 SHA-256 해시로 보관. 자격증명 누락은 422가 아니라 **401 `AUTH_REQUIRED`**, 불일치/비활성은 **401 `AUTH_INVALID`**(존재 여부 노출 방지). API Key를 query string으로 보내지 않는다.

**응답 봉투** — 성공 `{"data": {...}}`, 실패 `{"error":{"code":..., "message":..., "retryable": bool}}`.

**Inspection metadata**
```json
{ "request_id":"UUID4", "client_id":"CLIENT-001", "process_id":1, "product_id":10,
  "inspection_item_id":103, "capture_timestamp":"2026-09-14T09:12:00+09:00",
  "client_version":"1.0.0", "camera":{"vendor":"basler","serial_number":"..."} }
```
- 서버가 **검증에 쓰는 값**: `request_id`(idempotency key) + `process_id`/`product_id`/`inspection_item_id`(카탈로그 정합성).
- `client_id`는 헤더로 이미 식별되므로 **받기만 하고 쓰지 않는다.**
- 길이 상한이 DB 컬럼 크기다: `request_id` 36, `client_version` 50, `camera.*` 100. 초과 시 422 `METADATA_INVALID`이고 **이미지를 저장하지 않는다.**

**처리 순서**(`InspectionService.receive_capture`로 확인) `[FACT]`
```text
metadata 파싱 → idempotency 확인(request_id) → 카탈로그 정합성 검증
→ 이미지 decode 검증 → 원본 저장 → inspection 행 생성(commit)
→ ModelMapping 조회 → 추론 → 결과 갱신
```
- idempotency 확인이 카탈로그 검증보다 **먼저**다 → 검사항목을 비활성화한 뒤 같은 `request_id`로 재전송하면 404가 아니라 기존 결과 200이 나간다.
- 활성 ModelMapping이 없으면 **추론하지 않고 이미지만 저장해 `status:"RECEIVED"`** 로 응답한다.
- 추론 실패도 원본과 행을 남기고 `status:"FAILED"`.
- 동시에 같은 `request_id`가 들어오면 `IntegrityError` → rollback + 방금 저장한 파일 삭제 + 기존 행으로 응답.

**응답 (DETECTION)**: `inspection_id`, `request_id`, `inspection_type`, `status`, `abnormal`, `model{name,version}`, `defects[{class_name,confidence,bbox{x1,y1,x2,y2}}]`, `result_image_url`, `inference_ms`, `created_at`. bbox는 **원본 이미지 픽셀 좌표**.

**응답 (ANOMALY)**: 위 + `anomaly_score`, `threshold`, `heatmap_url`. `defects` 대신 점수.

**시각 규칙**: 서버 응답의 모든 시각은 **UTC(`Z`) 고정**. Client가 보내는 값은 offset이 있으면 무엇이든 받는다.

**보존 정책**: 이미지 파일만 삭제하고 검사 행은 남긴다. 삭제 후 이미지 요청은 404 `IMAGE_EXPIRED`. 정리는 웹 프로세스가 아니라 CLI(`purge-images`) + systemd timer(매일 03:30).

**Overlay 표시 규칙**: Overlay는 **카메라 촬영 영역 전체**를 덮는다. 응답에 위치·크기가 없다(제거됨). DB에는 정규화 좌표 열이 남아 있으나 전부 `0,0,1,1`이다.

**미구현으로 문서에 명시된 것**: 목록 응답의 `meta.count`, `CLIENT_VERSION_UNSUPPORTED`. `[FACT]`

### 5.5 Client 구조 `[FACT]`

```text
client/src/vision_inspection_client/
├─ domain/            enums(camera_state, inspection_state, inspection_type)
│                     models(capture_options, catalog, frame, inspection)
│                     ports(camera_port, catalog_port, inspection_port), errors
├─ application/use_cases/submit_inspection.py
├─ infrastructure/
│  ├─ api/            server_client.py(httpx), connection_test.py
│  ├─ camera/         basler/ opencv/ mock/ + factory, scan
│  └─ config/         credentials.py
├─ workers/           retry_worker.py 등
└─ (presentation: PySide6)
```

- HTTP는 `httpx>=0.28,<0.29`. 타임아웃 connect 3s / read 30s 기본.
- 응답 이미지 본문 상한 32MB(메모리 보호).
- 이미지 경로는 **`/api/v1` 아래 상대경로만 허용**(응답의 절대 URL을 그대로 따라가지 않음) — SSRF 방어.
- retry 워커는 **재전송 전 항상 `GET /api/v1/inspections/by-request/{request_id}`를 먼저 호출**한다.
- 카메라: Basler / OpenCV / Mock 어댑터. PC당 카메라 1대. GUI 메인 스레드에서 폴링·HTTP·대용량 I/O 금지가 규약.

### 5.6 GPU / AI 연계 현황 `[FACT]`

| 항목 | 현재 상태 |
|---|---|
| 추론 위치 | vision-inspection Server **프로세스 내부**(FastAPI 워커). 별도 GPU 서버 없음 |
| DETECTION 런타임 | `infrastructure/inference/torchvision_adapter.py` |
| ANOMALY 런타임 | `infrastructure/inference/patchcore_adapter.py` |
| 모델 아티팩트 | `settings.model_root`(기본 `/var/lib/vision-inspection/models`), `models.artifact_path`로 참조. 업로드 검증은 `application/services/model_artifacts.py` |
| 모델 등록 UI | Admin `/admin/models`(목록·신규·수정·활성화) |
| 모델 매핑 UI | Admin `/admin/inspection-items/{id}/model` |
| **학습(Training) API** | **없다.** `cli.py fit-anomaly`(PatchCore fit), `export-detection`만 있다 |
| Training Job / Evaluation Result 테이블 | **없다** |
| 모델 Load/Unload API | **없다.** 추론 시점 로딩 `[INFERENCE]` |
| GPU 자원 관리 / OOM 처리 | 명시적 관리 없음. `test_inference_does_not_block.py`가 블로킹 여부만 검증 |
| Django ↔ AI 연계 코드 | **MES·AIDataHub 어디에도 없다** |

> 목표 아키텍처의 GPU Server 기능 중 **AI 학습, Model Version/Deployment/Runtime 상태 관리, Evaluation Result는 세 프로젝트 어디에도 구현이 없다. 신규 개발 대상이다.** `[FACT]`

### 5.7 AIDataHub ↔ vision-inspection 사이의 기존 연결점 `[FACT]`

`server/src/.../application/services/image_migration.py`:

> "쌓인 검사 이미지를 외부 데이터 수집/관리 시스템으로 옮긴다. … 전송 내용은 원본 이미지와 판정 결과·탐지 좌표다. 수집 시스템이 AI 학습 데이터로 쓰므로 라벨이 이미지와 함께 가야 한다."

- 현재 구현은 **로컬 디렉터리 내보내기**(`infrastructure/migration/local_export.py`, `settings.migration_export_root`).
- `settings.py` 주석: **"대상 시스템의 API 규격이 확정되면 HTTP 어댑터로 바꾼다."**
- 검사항목 단위·batch(기본 50, 최대 500)로 관리자가 수동 실행. `image_migrations` 테이블에 건별 이력.
- Heatmap은 재생성 가능하므로 보내지 않는다.

→ **"검사 이미지 → 학습 데이터셋" 파이프라인의 대상이 AIDataHub라는 의도가 이미 코드에 있다. 통합 플랫폼에서는 이 경로가 프로세스 내부 호출이 된다.** `[INFERENCE]`

---

## 6. 호출 관계 (현재)

```text
[현재 — 3개 독립 시스템]

Browser ──HTTP──> MES (Django, IIS)           ──> PostgreSQL 10.10.10.230/yest
                    └─ MQTT <──> Mosquitto 10.10.10.231 <──> DAS/HMI/설비
PDA     ──JWT───> MES /api/v1/token, /pda/*

Browser ──HTTP──> AIDataHub (Django, waitress) ──> PostgreSQL 10.10.10.20/aidatahub_v2
                    └─ run_worker (별도 프로세스) ──> 같은 DB
                    └─ MEDIA_ROOT (로컬 파일)

VisionInspectionClient.exe ──HTTPS(X-Client-ID/X-API-Key)──> vision Server (FastAPI, uvicorn)
Browser(관리자) ───────────HTTP(세션)──────────────────────>   │   ──> PostgreSQL vision_inspection
                                                              ├──> storage_root (원본/heatmap/overlay)
                                                              ├──> model_root (artifact) ──> torch 추론(같은 프로세스)
                                                              └──> migration_export_root (로컬 디렉터리 내보내기)

세 시스템 사이에 실행되는 연계는 없다. (image_migration만 "장래 연계" 자리표시)
```

```text
[목표 — 프롬프트 §1]

VisionInspectionClient.exe ─HTTPS─┐
Browser ──────────────────────────┤
                                  ▼
                     Nginx → ManufacturingAIPlatform (Django)
                             데이터관리 / 비전검사관리 / 시스템관리
                                  │ Internal REST
                                  ▼
                             GPU Server (FastAPI)
                             모델관리 / 학습 / 추론
                                  │
                     둘 다 ──> PostgreSQL (Ownership 분리)
```

---

## 7. DB 구조 비교

### 7.1 데이터베이스 인스턴스 `[FACT]`

| 시스템 | 호스트/DB | 사용자 | 특이사항 |
|---|---|---|---|
| MES | `10.10.10.230` / `yest` | `yest_dev` | `search_path=public,das,ai` (스키마 `das`, `ai` 사용) |
| AIDataHub | `10.10.10.20` / `aidatahub_v2` | `aidatahub` | `CONN_MAX_AGE=60`, RLS 19테이블, 단일 alias |
| vision Server | (기본값) `127.0.0.1` / `vision_inspection` | `vision_user` | Alembic, PG native enum `inspection_type` |

→ **3개 DB가 물리적으로 분리되어 있다. 통합 방식과 데이터 이관 범위는 결정 사항이다** → `DEC-011`, `DEC-012`

각 DB의 **기존 운영 데이터 유무와 양을 소스에서 알 수 없다.** `[NEEDS_CONFIRMATION]`

### 7.2 PK 타입 `[FACT]`

| 시스템 | 기본 PK |
|---|---|
| MES | `AutoField` = `integer`(int4). 모델마다 `id = models.AutoField(primary_key=True)` 명시 |
| AIDataHub | `BigAutoField` = `bigint`(int8). 단 `Tenant.id`는 **UUID** |
| vision Server | `BigInteger`. 단 `inspections.id`/`request_id`는 **`String(36)` UUID 문자열**, `retention_policies.id`는 `Integer` 고정값 1 |

### 7.3 공통 조상 테이블 `[FACT]`

MES와 AIDataHub 모두 `django.contrib.auth`를 그대로 쓴다(`AUTH_USER_MODEL` 미지정) → `auth_user`, `auth_group`, `auth_permission`, `django_content_type`, `django_session`, `django_migrations`를 공유한다. **이 부분은 통합에 유리하다.**

반대로 `user_group` / `user_profile` / `user_group_menu`는 **양쪽이 같은 이름으로 다른 스키마를 정의**한다(상세는 `03_CONFLICT_ANALYSIS.md` C-04).

### 7.4 감사 컬럼 패턴 `[FACT]`

| 시스템 | 방식 |
|---|---|
| MES | `AbstractAuditModel` — `_status`, `_created`, `_modified`, `_creater_id`, `_modifier_id`(밑줄 접두 컬럼명) |
| AIDataHub | 모델별 `created_at` / `updated_at` + `created_by`/`requested_by`(FK) + `ActivityLog` 테이블 |
| vision Server | `TimestampMixin` — `created_at` / `updated_at` (`server_default=now()`, `onupdate`) |

---

## 8. 인증 / 권한 비교

| 축 | MES | AIDataHub | vision Server |
|---|---|---|---|
| 사용자 저장소 | `auth_user` + `user_profile` | `auth_user` + `user_profile` | **별도 `admin_users`** (Django auth 아님) |
| 웹 로그인 | 세션(`mes25-1`) | 세션(`aidatahub-v2`) | 서명 쿠키(itsdangerous, 기본 8시간) |
| 관리자 판정 | `is_superuser` 또는 `UserGroup.Code in ('dev','admin')` | `UserProfile.UserGroup.Code == 'admin'` **만** (`is_staff`/`is_superuser`는 관리자가 아니다) | `admin_users.active` |
| 화면 권한 | `UserGroupMenu`(MenuCode, AuthCode) — `GUITemplatesView`에서만 | `gui_item` 옵션 + `UserGroupMenu` + Project capability + `admin_only` | 전체 Admin 1등급(세분화 없음) |
| API 권한 | **없음** | 뷰별 capability 검사 + RLS | Client: API Key / Admin: 세션+CSRF |
| 조직/테넌트 | `Factory`(공장) FK가 UserProfile에 있으나 인가 경계 아님 `[INFERENCE]` | `Tenant` + RLS로 강제 격리 | 없음 |
| 기계/장치 인증 | PDA JWT(`JWT_SECRET_KEY` 미정의 → 동작 불가 추정) | 없음 | **Client ID + API Key** (해시 보관, 분당 rate limit, 실패 로깅) |
| 로그인 하드닝 | 없음 `[FACT]` | 인증 로그(`AuthenticationLog`) | `login_throttle` + 세션 DB 재확인 + 세션 무효화 테스트 |
| 비밀번호 정책 | Django 기본 validator 4종. 신규 사용자 초기 비밀번호 **`'1'`** (`system/user.py`) `[FACT]` | Django 기본 + 변경 화면 | PBKDF2 |

> **기계 인증(Client ID + API Key)은 vision-inspection에만 있고, 가장 잘 만들어져 있다.** MES의 PDA JWT는 동작 불가 상태로 보인다. 프롬프트 §16.2의 "사용자 로그인과 Client 인증을 혼합하지 않는다"는 원칙은 vision 구현을 그대로 계승하는 것이 맞다 `[INFERENCE]` → `DEC-007` 관련.

---

## 9. 주요 기술 부채 종합

| ID | 시스템 | 항목 | 심각도 | 근거 |
|---|---|---|---|---|
| D1 | MES | 업무 API 인가 없음 / `apiPermissionMap` 死코드 | **CRITICAL** | §3.5 |
| D2 | MES | 비밀값 평문 하드코딩 | **HIGH** | §3.8 |
| D3 | MES | `DEBUG=False`에서 `TEMPLATES` 미정의 | **HIGH** | §3.8 |
| D4 | MES | `JWT_SECRET_KEY` 미정의 | MEDIUM(범위 밖) | §3.8 |
| D5 | MES | Django 4.0에서 제거된 `postgres.fields.JSONField` import | **HIGH** `[NEEDS_CONFIRMATION]` | §3.8 |
| D6 | MES | 테스트 0건 | **HIGH** | §2.1 |
| D7 | MES | 고객사·전시회 전용 코드 혼입 | MEDIUM | §3.8 |
| D8 | MES | 문서(AGENTS.md)가 실제 구현과 불일치(마이그레이션 관리 방식) | MEDIUM | §3.1 |
| D9 | MES | 동기 Ajax / iframe 셸 | MEDIUM | §3.6 |
| D10 | AIDataHub | 실패한 BackgroundJob 자동 재시도·백오프 없음 | MEDIUM | `AGENTS.md` 5절 |
| D11 | AIDataHub | `error_message` 255자 절단 | LOW | `AGENTS.md` 5절 |
| D12 | AIDataHub | 마이그레이션 재구성 이력(2026-09-30 예외 조치) — 이전 마이그레이션으로 만든 DB는 이어서 쓸 수 없다 | **HIGH**(이관 시) | `AGENTS.md` 4절 |
| D13 | AIDataHub | 테스트가 파일 목록을 `assertEqual`로 고정 → 파일 추가마다 기대값 수정 필요 | MEDIUM(개발 마찰) | `AGENTS.md` 6절 |
| D14 | vision Server | Application Service가 Repository Port를 주입받지 않고 `Sql*Repository`를 직접 생성 | LOW(자각·문서화됨) | `ARCHITECTURE.md` §2 |
| D15 | vision Server | 추론이 웹 프로세스와 같은 프로세스 — GPU 자원 경합·OOM 대비 없음 | **HIGH**(목표 구조에서 해소 예정) | §5.6 |
| D16 | vision Server | `overlays`의 x/y/width/height가 전부 `0,0,1,1` 死컬럼 | LOW | `ARCHITECTURE.md` §3 |
| D17 | vision Server | `distribution_root` 아래 파일은 **무인증 공개**(방화벽 의존) | MEDIUM | `settings.py` 주석 |
| D18 | vision Server | `session_secret` 기본값 `"dev-only-insecure-secret"` | MEDIUM | `settings.py` |
| D19 | 전체 | 세 프로젝트가 **git 저장소가 아니다** → 기준 형상·변경 추적 불가 | **HIGH** | §0 |

---

## 10. 확인 필요 사항 (`[NEEDS_CONFIRMATION]`)

| # | 항목 | 왜 필요한가 | 확인 방법 |
|---|---|---|---|
| N1 | 세 시스템의 **운영 데이터 존재 여부와 규모** | 데이터 이관 전략(무이관 / 부분 / 전량)이 Migration Plan 전체를 좌우한다 | 각 DB에 `SELECT count(*)` — 사용자 확인 후 실행 |
| N2 | MES의 **실제 배포 Django 버전** | `postgres.fields.JSONField` import가 동작하는지(D5) | 운영 서버 `pip show django` |
| N3 | MES `settings.JWT_SECRET_KEY`가 배포 환경에서 별도 주입되는지 | PDA/모바일 기능의 실제 동작 여부(D4) | 운영 `settings.py` 확인 |
| N4 | **NCP VPC 대상 OS** (Ubuntu / Windows) | MES는 IIS+wfastcgi, AIDataHub·vision은 Linux 전제. 배포 스택 결정 | 인프라 담당 확인 → `DEC-020` |
| N5 | vision-inspection **현장 배포 여부와 Client 설치 대수** | Client 무변경 요구 강도, 호환 계층 수명 | 운영 담당 확인 |
| N6 | GPU 서버 **하드웨어 스펙 / CUDA·torch 버전** | MES requirements는 torch 2.5.1, vision은 2.14.0 — 런타임 통일 여부 | 인프라 확인 |
| N7 | Mosquitto MQTT / DAS 설비연계가 통합 플랫폼 범위인가 | MES Backbone에 포함된 실시간 연계를 가져오면 브로커·설비 의존이 따라온다 | → `DEC-023` |
| N8 | MES `das`·`ai` PostgreSQL 스키마의 내용 | `search_path`에 포함되어 있으나 `database.sql`에는 생성문만 있다. 어떤 테이블이 있는지 소스에서 알 수 없다 | 운영 DB `\dt das.*`, `\dt ai.*` |
| N9 | AIDataHub `Tenant`(조직) 다중 사용 실태 | 멀티테넌시 존치 결정의 근거 → `DEC-004` | 운영 DB `SELECT * FROM vision_data_tenant` |
| N10 | `exh_mes` 파생소스의 위치 | MES AGENTS.md가 "동일 워크스페이스"라 하지만 이 워크스페이스에 없다 | 사용자 확인 |
| N11 | MES `mlops_*` 테이블의 DDL | `managed=False`라 Django가 만들지 않는다. DDL 원본이 `_sql/`에 없다 | 운영 DB 덤프 |
| N12 | vision Server `config/.env` 실제 값 | DB·스토리지 경로·세션 시크릿 (소스에는 기본값만) | 운영 서버 확인(값은 기록하지 않음) |

---

## 11. 목표 Architecture 후보 (분석 결과)

프롬프트 §1의 기준 아키텍처를 현재 구현에 대입하면, **책임 재배치의 실질적 내용은 다음 4가지**다. `[INFERENCE]`

```text
① vision Server의 Catalog(processes/products/inspection_items) + Overlay + Client 인증
   + Inspection 수신/저장/조회 + Admin 화면
   → Django(ManufacturingAIPlatform) "비전 검사 관리"로 이관

② vision Server의 models / 추론 어댑터(torchvision, patchcore) + model_root
   → GPU Server(FastAPI)로 남기고 API화

③ vision Server의 model_mappings
   → Django "시스템 관리 > 검사항목↔모델 매핑"으로 이관
      (단 model_id는 GPU 소유 테이블을 가리킨다 → 참조 방식 결정 필요)

④ AIDataHub의 Dataset/Image/Annotation/Labeling/Quality/Snapshot/Export 전체
   → Django "데이터 관리"로 이관 (기능은 유지, 표현 계층 규약은 결정 사항)
```

### 후보 A — MES 골격 위에 이식 (권장 후보)

```text
ManufacturingAIPlatform/          ← MES 구조를 그대로 계승
├─ configurations/   settings(환경변수화) / urls.py / middleware
├─ app/
│  ├─ views/
│  │  ├─ system/        ← MES 시스템관리 (선별 이관)
│  │  ├─ definition/    ← MES 기준정보 (선별 이관)
│  │  ├─ data/          ← AIDataHub 데이터관리 이식
│  │  ├─ vision/        ← vision Server Admin + Catalog 이식
│  │  └─ api_v1/        ← VisionInspectionClient 호환 계층(6 엔드포인트)
│  ├─ templates/
│  └─ static/
├─ domain/
│  ├─ models/       system.py user.py data.py vision.py
│  ├─ services/     .../ + gpu/ (GPU Server REST 클라이언트)
│  ├─ gui.py
│  └─ migrations/
└─ manage.py
```
- 장점: MES 패턴·UI·시스템관리를 그대로 쓴다. 프롬프트 §4, §11과 일치.
- 단점: AIDataHub 화면 10개 + 서비스 46개를 MES 규약으로 **재작성**해야 한다. 라벨링 캔버스 화면은 WeZonGrid로 옮길 수 없다.

### 후보 B — MES 골격 + AIDataHub 화면을 iframe 페이지로 이식

후보 A와 같되, **데이터관리 라벨링/검수 화면만 AIDataHub 구현(캔버스·비동기 Ajax)을 유지**하고 MES 셸의 iframe 탭 안에 올린다.
- 장점: 라벨링·검수 기능(가장 만들기 어려운 부분)의 재작성 위험을 피한다.
- 단점: 한 플랫폼에 두 표현 계층 규약이 공존한다.

### 후보 C — AIDataHub 골격 + MES 시스템관리 이식

- 장점: 인가 구조·테스트·배포가 이미 건전하다.
- 단점: **프롬프트 §4 "MES 구조와 코딩 패턴을 기본 규칙으로 우선 적용"에 정면으로 어긋난다.** MES 기준정보·다국어·WeZonGrid 화면 자산을 버린다.

→ 선택은 `DEC-001`, `DEC-013`.

---

## 12. 이관 방식 후보

프롬프트 §19 분류를 실제 모듈에 적용한 결과 요약. 상세 표는 `02_FEATURE_MAPPING.md`.

| 분류 | 대표 대상 |
|---|---|
| `[REUSE]` (그대로) | vision `api/v1` 계약 문서·스키마 정의, AIDataHub Export exporter 8종(순수 함수 성격), vision `infrastructure/security/api_key.py`·`password.py`, AIDataHub `dataset/export/*` |
| `[ADAPT]` (로직 유지 + MES 패턴) | AIDataHub 데이터관리·라벨링·검수·품질·스냅샷 서비스 46개, vision `application/services/{catalog,inspection,overlay,result_image,client_auth}` |
| `[REWRITE]` (개념만 유지) | AIDataHub 화면 10개·템플릿 33개, vision Admin 화면 22개 → MES 템플릿/WeZonGrid 규약으로 |
| `[REPLACE]` (MES 공통으로 대체) | vision `admin_users`+Admin 인증 → MES 사용자/권한, AIDataHub `UserGroup/UserProfile/UserGroupMenu` → MES 것, AIDataHub `AuthenticationLog` → MES `login_log` |
| `[REMOVE]` | vision `licenses`/`client_packages` 배포 엔드포인트(무인증 공개), vision Admin `dashboard`(MES 대시보드로 대체), MES 고객사 전용 모듈·전시회 코드, AIDataHub `htmx` 잔재 |
| `Future Consideration` (범위 밖) | MES `ai/nl2sql`·`mes_chatbot`(RAG/챗봇), MES `mlops_*` 화면 7개, MES HACCP·생산·재고·출하·설비보전 전체, MES DAS/MQTT, AIDataHub `Tenant` 멀티테넌시(결정에 따름), Object Storage 전환 |

---

## 13. 다음 단계

이 문서는 **사용자 결정의 근거**다. 여기서 도출된 결정 항목은 모두 `USER_DECISIONS.md`에 모았다.

```text
01_CURRENT_STATE_ANALYSIS.md  (이 문서)
02_FEATURE_MAPPING.md
03_CONFLICT_ANALYSIS.md
        ↓
USER_DECISIONS.md   ← 사용자 결정 대기
        ↓  (결정 후)
04_TARGET_ARCHITECTURE.md / 05_DATABASE_MIGRATION_PLAN.md
06_API_COMPATIBILITY_PLAN.md / 07_IMPLEMENTATION_PLAN.md
```
