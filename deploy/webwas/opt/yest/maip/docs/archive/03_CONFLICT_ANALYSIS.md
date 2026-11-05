# 03. Conflict Analysis

> **참고 (2026-09-30)** — 이 문서는 **원본 3개 프로젝트의 분석 기록**이며 원문 그대로 보존한다.
> 이후 사용자 지시로 검사항목이 단일 엔티티로 통합되고 공정·제품·보존정책·이관기능이 제외됐다.
> **목표 구조의 정본은 `USER_DECISIONS.md` §1.6이다.**

- 기준일: 2026-09-30
- 근거: `01_CURRENT_STATE_ANALYSIS.md`
- Severity: `CRITICAL` 결정 없이는 통합 자체가 불가 / `HIGH` 설계를 바꾸지 않으면 반드시 사고 / `MEDIUM` 우회 가능하나 비용 발생 / `LOW` 정리 대상
- 모든 항목의 "확인된 사실"은 **소스 읽기로 확인**한 것이다. 런타임 재현은 하지 않았다.

---

## 0. 충돌 요약

| ID | 영역 | 충돌 | Severity | 관련 결정 |
|---|---|---|---|---|
| C-01 | Python 패키지 | MES·AIDataHub가 `configurations`/`app`/`domain` 3개 최상위 패키지 이름을 공유 | **CRITICAL** | DEC-001 |
| C-02 | Django App Label | MES `domain` vs AIDataHub `ai_domain` — 같은 패키지명, 다른 라벨 | **CRITICAL** | DEC-001 |
| C-03 | Migration | 두 Django 프로젝트의 마이그레이션 히스토리가 `django_migrations`에서 충돌 | **CRITICAL** | DEC-011 |
| C-04 | DB 테이블 | `user_group`·`user_profile`·`user_group_menu`를 양쪽이 같은 이름·다른 컬럼으로 정의 | **CRITICAL** | DEC-002 |
| C-05 | 인가 아키텍처 | MES는 API 인가가 없고, AIDataHub는 API 인가를 전제로 설계됨 | **CRITICAL** | DEC-003, DEC-014 |
| C-06 | 기술 스택 | vision Server가 FastAPI/SQLAlchemy/Alembic — Django ORM으로 이관 필요 | **CRITICAL** | DEC-001, DEC-006 |
| C-07 | 표현 계층 | MES iframe 탭 셸 + WeZonGrid + 동기 Ajax ↔ AIDataHub SPA + 표준 마크업 + 비동기(명문 금지 규약) | **HIGH** | DEC-013 |
| C-08 | 멀티테넌시 | AIDataHub 19테이블 `tenant` FK NOT NULL + RLS, MES·vision에는 개념 없음 | **HIGH** | DEC-004 |
| C-09 | API 응답 규약 | 3종이 모두 다름(MES `{success}`/200 고정, AIDataHub `{ok,data}`+status, vision `{data}`/`{error}`) | **HIGH** | DEC-007, DEC-014 |
| C-10 | 시각 처리 | `USE_TZ` MES `False` / AIDataHub `True` / vision UTC-aware | **HIGH** | DEC-016 |
| C-11 | PK 타입 | int4 / int8 / UUID·String(36) 혼재 | **HIGH** | DEC-017 |
| C-12 | 도메인 의미 | "검사", "공정", "제품", "모델", "프로젝트"가 시스템마다 다른 뜻 | **HIGH** | DEC-025 |
| C-13 | 관리자 사용자 저장소 | vision `admin_users`(독립) vs Django `auth_user` | **HIGH** | DEC-018 |
| C-14 | Model Registry 책임 | vision `models`/`model_mappings` + MES `mlops_*` + 목표 GPU Registry = 3중 | **HIGH** | DEC-009, DEC-010 |
| C-15 | 파일 저장소 | MES `c:\temp\mes21\` / AIDataHub `MEDIA_ROOT`+권한View / vision `storage_root`+`model_root` | **HIGH** | DEC-019 |
| C-16 | 배포 OS/WAS | IIS+wfastcgi(Windows) / nginx+waitress(Linux) / nginx+uvicorn+systemd(Ubuntu) | **HIGH** | DEC-020 |
| C-17 | 백그라운드 작업 | MES `batch_q` vs AIDataHub `BackgroundJob`+워커 프로세스 vs vision CLI+systemd timer | MEDIUM | DEC-022 |
| C-18 | 다국어 | MES `label_code` 4언어 ↔ AIDataHub "라벨 API i18n 도입 금지" | MEDIUM | DEC-021 |
| C-19 | 세션·쿠키·보안 헤더 | 쿠키명·`X_FRAME_OPTIONS`·HSTS·`SECURE_SSL_REDIRECT` 정책 불일치 | MEDIUM | DEC-018, DEC-020 |
| C-20 | Static 자원 | MES `STATIC_ROOT`+`collectstatic`+WhiteNoise ↔ AIDataHub "`STATIC_ROOT` 두지 않음"(nginx 직접) | MEDIUM | DEC-020 |
| C-21 | 템플릿 로더 | MES `DIRS=[BASE_DIR/templates]` + `APP_DIRS` 주석처리 ↔ AIDataHub `APP_DIRS=True` | MEDIUM | DEC-013 |
| C-22 | Context Processor | MES 4개(기본) ↔ AIDataHub +`domain.context_processors.navigation` | LOW | DEC-013 |
| C-23 | 미들웨어 | MES WhiteNoise·`RemoveCriticalResponseHeader` ↔ AIDataHub `RequestIdMiddleware`·`TenantMiddleware` | MEDIUM | DEC-004 |
| C-24 | 의존성 버전 | torch 2.5.1(MES) vs 2.14.0(vision), Pillow 10.3.0 vs 11.x vs 12.3.0, psycopg2+psycopg3 동시 | MEDIUM | DEC-020 |
| C-25 | `DEFAULT_AUTO_FIELD` | `AutoField` vs `BigAutoField` | HIGH(C-11과 동일 뿌리) | DEC-017 |
| C-26 | PG native enum | vision `inspection_type` PostgreSQL enum 타입 — Django는 보통 CharField+choices | MEDIUM | DEC-011 |
| C-27 | 무인증 공개 엔드포인트 | vision `/api/v1/licenses/sources`, `/client-packages`가 인증 없이 파일 제공 | **HIGH** | DEC-024 |
| C-28 | 형상관리 | 세 프로젝트 모두 이 워크스페이스에서 git 저장소가 아님 | **HIGH** | — |
| C-29 | 문서 vs 구현 | MES AGENTS.md의 마이그레이션 관리 방식 서술이 실제와 다름 | MEDIUM | — |
| C-30 | Django 버전 호환 | MES `domain/models/user.py`가 Django 4.0에서 제거된 심볼을 import | **HIGH** | — |

---

## 1. Django / 코드 충돌

### C-01. 최상위 패키지 이름 충돌 — `CRITICAL`

**확인된 사실** `[FACT]`
```text
MES/        configurations/  app/  domain/  manage.py
AIDataHub/  configurations/  app/  domain/  manage.py
```
두 프로젝트가 같은 3개 패키지 이름을 쓴다. `settings.py`, `urls.py`, `wsgi.py`, `app/views/__init__.py`, `domain/gui.py`, `domain/models/user.py`가 **양쪽에 같은 경로로 존재하고 내용이 다르다.**

**영향**
- 파일을 한 트리에 합치면 서로를 덮어쓴다. **"소스 병합"이라는 작업 형태 자체가 성립하지 않는다.**
- AIDataHub를 Django App으로 편입하려면 패키지를 `ai_data`/`vision_data` 등으로 **rename**해야 하고, 그러면 AIDataHub의 모든 `from domain.models import ...`, `from app.views...` import 경로(수백 곳)와 `tests/`의 파일목록 고정 테스트(`test_view_layout` 등)가 전부 깨진다.

**권장 대응** → `DEC-001`
MES 트리를 `manufacturing_ai_platform/`으로 복제해 골격으로 삼고, AIDataHub·vision 기능을 **MES의 `app/views/<업무>/` + `domain/services/<업무>/` + `domain/models/` 규약에 맞춰 이식**한다. AIDataHub 트리를 앱으로 끌어오지 않는다.

---

### C-02. Django App Label 충돌 — `CRITICAL`

**확인된 사실** `[FACT]`
| 프로젝트 | 패키지 | App Label |
|---|---|---|
| MES | `app` | `app` (AppConfig 없음, 기본값) |
| MES | `domain` | `domain` (AppConfig 없음, 기본값) |
| AIDataHub | `app` | `app` (`app.apps.AIDataHubAppConfig`, label 미지정 → `app`) |
| AIDataHub | `domain` | **`ai_domain`** (`domain.apps.AIDataHubDomainConfig`가 명시) |

AIDataHub `AGENTS.md`는 "`domain` 패키지의 앱 라벨은 반드시 `ai_domain`이다. `domain`·`identity` 라벨을 쓰지 않는다"를 규칙으로 못박고 `test_v2_architecture`가 이를 강제한다.

**영향**
- 같은 프로젝트에 App Label `app`이 둘일 수 없다 → `django.core.exceptions.ImproperlyConfigured` `[INFERENCE]`
- AIDataHub 모델의 FK 문자열 참조가 라벨에 묶여 있다: `domain/models/labeling.py`가 `"ai_domain.DataStandard"`를 참조한다 `[FACT]`. 라벨을 바꾸면 이 참조와 마이그레이션이 깨진다.
- `django_content_type` 행의 `app_label`도 바뀐다 → 기존 데이터가 있으면 ContentType/Permission 재매핑이 필요하다.

---

### C-03. Migration 히스토리 충돌 — `CRITICAL`

**확인된 사실** `[FACT]`
| 프로젝트 | 마이그레이션 |
|---|---|
| MES `domain` | `0001_initial`(4952줄, Django 5.0.4, 2026-02-06) ~ `0004_gridcolumn_...` |
| AIDataHub `ai_domain` | `0001_initial` 하나 (2026-09-30에 기존 0001~0007 + 테이블명 변경 `ai_domain_*`→`vision_data_*`를 통합해 **재작성**) |
| vision Server | Alembic `0001_initial` ~ `0013_add_image_migrations` (13개) |

AIDataHub `AGENTS.md` 4절이 명시한 위험:
> "원격 DB의 옛 `ai_domain` 기록은 `0001_initial` 한 줄만 남기고 지운다. FK 제약·자동 인덱스 이름은 원격 DB에 `ai_domain_` 접두어로 남아 있다. **그 전의 migration 파일로 만든 DB는 이어서 쓸 수 없으니 빈 DB에서 다시 `migrate`한다.**"

**영향**
- 한 DB에 두 Django 프로젝트의 `django_migrations` 이력을 넣을 수 없다(app label이 겹치면 동일 `(app, name)` 충돌).
- AIDataHub 기존 DB(`10.10.10.20/aidatahub_v2`)는 **제약·인덱스 이름이 `ai_domain_` 접두어**로 남아 있어, 새로 만든 DB와 스키마 이름이 다르다. 이관 스크립트가 이름에 의존하면 깨진다.
- Alembic → Django migrations 변환은 **자동 변환 수단이 없다.** vision 11테이블을 Django 모델로 재정의하고 `0001`에 담아야 한다.
- AIDataHub `AGENTS.md`는 `migrate --fake`, `--fake-initial`, `django_migrations` 수동 수정을 **금지**한다. 통합 시 이 금지를 유지할지 결정해야 한다.

**권장 대응** → `DEC-011`, `DEC-012`
통합 플랫폼은 **새 DB에 새 `0001_initial` 하나**로 시작한다. 기존 데이터는 마이그레이션이 아니라 **별도 데이터 이관 스크립트**로 옮긴다(옮길지 여부는 `DEC-012`).

---

### C-04. `user_group` / `user_profile` / `user_group_menu` 스키마 충돌 — `CRITICAL`

**확인된 사실** `[FACT]` — 같은 `db_table`, 다른 컬럼.

**`user_group`**

| 컬럼 | MES | AIDataHub |
|---|---|---|
| `id` | `AutoField`(int4) | `BigAutoField`(int8) |
| `Code` | `CharField(50)`, `unique_together [['Code']]` | `CharField(50, unique=True)` |
| `Name` | `CharField(100, default='None')` | `CharField(100)` |
| `Disabled` | `BooleanField(null=True, default=False)` | `BooleanField(default=False)` (NOT NULL) |
| `Description` | `CharField(500, null=True)` | `CharField(500, blank=True)` (NOT NULL, `''`) |
| `_status` `_created` `_modified` `_creater_id` `_modifier_id` | **있음** (`AbstractAuditModel`). **`_created`는 `auto_now_add=True`로 NOT NULL** | **없음** |

→ MES 테이블에 AIDataHub 모델로 INSERT하면 `_created` NOT NULL 위반이 난다 `[INFERENCE]`. 반대로 AIDataHub 테이블에 MES 모델을 쓰면 감사 컬럼이 없어 실패한다.

**`user_profile`**

| 컬럼 | MES | AIDataHub |
|---|---|---|
| `User_id` (PK, OneToOne→`auth_user`) | 있음 | 있음 |
| `UserGroup_id` | FK, `on_delete=DO_NOTHING`, null | FK, `on_delete=PROTECT`, null |
| `Name` | `CharField(100, null=True)` | `CharField(100, blank=True)` NOT NULL |
| `lang_code` | `CharField(30, default='ko-KR')` | 동일 |
| `password_changed` | 있음 | 있음 |
| `Factory_id` | **있음** (FK → `factory`) | 없음 |
| `Company_id` | **있음** (FK → `company`) | 없음 |
| `Depart_id` | **있음** (FK → `depart`) | 없음 |
| `CompCode` | **있음** | 없음 |
| `access_token` / `refresh_token` | **있음** (`CharField(512)`) | 없음 |
| 감사 컬럼 5개 | **있음** | 없음 |
| `index_together` | `[['UserGroup']]` | 없음 |

→ **MES 스키마가 AIDataHub 스키마의 상위집합이다**(감사 컬럼의 NOT NULL만 해결하면). 따라서 MES를 정본으로 택하는 것이 데이터 손실이 없다.

**`user_group_menu`**

| 컬럼 | MES | AIDataHub |
|---|---|---|
| `UserGroup_id` | FK `CASCADE`, **null=True** | FK `CASCADE`, NOT NULL |
| `MenuCode` | `CharField(50)` NOT NULL | 동일 |
| `AuthCode` | `CharField(10)` NOT NULL, **choices 없음** — 판정은 `"R" in authcode` / `"W" in authcode` | `CharField(10, choices=[("R","읽기"),("RW","읽기·쓰기")])` |
| unique | `unique_together [['MenuCode','UserGroup']]` | `UniqueConstraint(['MenuCode','UserGroup'], name='unique_user_group_menu')` — **제약 이름이 다르다** |
| 감사 컬럼 | 있음 | 없음 |

→ `AuthCode` 값 집합은 실질적으로 호환된다(`"RW"`는 MES 판정에서도 R+W로 풀린다). 단 MES는 `"W"`만 있는 값도 허용하고 AIDataHub는 허용하지 않는다.

**추가 사실**: 양쪽 모두 `AUTH_USER_MODEL`을 커스터마이즈하지 않고 `django.contrib.auth.models.User`를 그대로 쓴다. 그리고 양쪽 모두 `post_save(User)` 시그널로 `UserProfile`을 자동 생성한다(MES는 `UserProfile.objects.create` + `instance.userprofile.save()`, AIDataHub는 `get_or_create`). **MES 쪽 시그널은 `created=False`일 때도 `instance.userprofile.save()`를 호출하므로 프로필이 없는 기존 사용자에서 `RelatedObjectDoesNotExist`가 날 수 있다** `[INFERENCE]`.

**권장 대응** → `DEC-002`
MES `UserProfile`/`UserGroup`/`UserGroupMenu`를 정본으로 채택한다. AIDataHub 쪽 코드(`user_is_platform_admin`, `user_display_name`, `set_user_group`, `platform_admin_q`, `menu_auth.check_user_auth`)는 **MES 모델 위에서 동작하도록 어댑터화**한다.

---

### C-05. 인가 아키텍처 충돌 — `CRITICAL`

**확인된 사실** `[FACT]`

MES 측:
- `check_user_auth(user, gui_code)`는 `app/views/__init__.py:240`, 즉 `GUITemplatesView.get()` 한 곳에서만 호출된다.
- `ApiModuleView`에는 인가 검사가 없다(docstring: `'''권한 처리여부 결정할 것'''`).
- `TemplatePathView`(`/page/<folder>/<name>`)에도 인가 검사가 없다.
- `GUIConfiguration.taskview_menu_code_map()`이 만든 `apiPermissionMap`(약 200 항목)을 읽는 함수 `get_menu_code_by_taskview()`는 **프로젝트 전체에서 호출되지 않는다** (grep 결과: 정의 1곳, 호출 0곳).

AIDataHub 측 (`AGENTS.md`):
- "URL은 `configurations/urls.py`에 명시적으로 등록한다. 파일 배치로 라우팅을 추론하는 **동적 import dispatch를 쓰지 않는다 — 권한을 붙일 지점이 사라진다.**"
- "메뉴 숨김은 UX일 뿐 인가 경계가 아니다. 직접 URL·API 요청도 서버에서 거부한다."
- 작업 → capability 매핑은 `ACTION_CAPABILITIES` 한 곳. 없으면 403.

**영향**
- 프롬프트 §4는 "MES 구조와 코딩 패턴을 통합 프로젝트의 기본 규칙으로 우선 적용"을 지시한다. 그대로 적용하면 **AIDataHub가 인가 경계로 삼는 Project 역할·작업그룹 권한을 구현할 지점이 없다.** 이식 자체가 막힌다.
- 동시에 MES의 기존 업무 API 전체가 인가 없이 노출되는 상태를 통합 플랫폼이 물려받는다.

**권장 대응** → `DEC-014`
MES의 동적 dispatch 형태는 유지하되(`/api/<task>/<view>`), `ApiModuleView.dispatch()`에 **인가 훅을 추가**한다. 즉 `apiPermissionMap`을 살려 실제로 검사하고, 그 위에 AIDataHub의 capability 검사를 결합한다. 이것은 MES 패턴의 *보완*이며 변경이 아니다.

---

### C-06. vision Server 기술 스택 충돌 — `CRITICAL`

**확인된 사실** `[FACT]`

| 항목 | vision Server | 통합 대상(Django) |
|---|---|---|
| 프레임워크 | FastAPI 0.141.1 | Django 5.0.4 |
| ORM | SQLAlchemy 2.0.52 (`DeclarativeBase`, `Mapped[]`) | Django ORM |
| 마이그레이션 | Alembic 1.20.0, 13개 | Django migrations |
| 스키마 검증 | Pydantic 모델 + `pydantic-settings` | Django Form / 수동 검증 |
| 템플릿 | Jinja2 | Django Template |
| 세션 | itsdangerous 서명 쿠키 | Django session |
| 비밀번호 | PBKDF2 자체 구현 | Django `set_password` |
| 의존성 주입 | FastAPI `Depends` | 없음(직접 생성) |
| 계층 구조 | api / admin / application / domain / infrastructure (헥사고날, Port/Adapter) | app.views / domain.services (2계층) |

**영향**
- "필요한 기능을 이관한다"는 것은 **77개 Python 파일을 Django 규약으로 재작성**하는 작업이다. 복사로 되는 부분은 순수 로직(이미지 검증, API Key 해시, PBKDF2 파라미터, 좌표 계산)에 한정된다.
- vision의 Port/Adapter 경계는 MES에 대응 개념이 없다. 평탄화하면 테스트 56건이 무의미해진다.
- **반대로 GPU Server로 남기는 부분(추론·모델)은 FastAPI를 그대로 유지하는 것이 유리하다.** 즉 이 충돌은 "전부 Django화"가 아니라 "어디까지 Django화하는가"의 문제다 → `DEC-006`

---

### C-07. 표현 계층 규약 충돌 — `HIGH`

**확인된 사실** `[FACT]` — AIDataHub `AGENTS.md`가 MES의 4가지 핵심 패턴을 **명문으로 금지**한다.

| 항목 | MES 구현 | AIDataHub 규약 | 근거 |
|---|---|---|---|
| 동적 import dispatch | 사용 | **금지** | `AGENTS.md` 1절 |
| iframe 탭 셸 | 사용(`X_FRAME_OPTIONS='SAMEORIGIN'`, `window.parent.$('.page-tabs')`) | **금지**, `X_FRAME_OPTIONS='DENY'` | `AGENTS.md` 1절 / `settings.py` |
| 자체 그리드 위젯 | `WeZonGrid` | **금지** | `AGENTS.md` 1절 |
| 동기 Ajax | 사용(`AjaxUtil.getSyncData`, `layout_page.html`) | **금지** | `AGENTS.md` 1·8절 |
| 화면 이동 | iframe src 교체 | `spa.js`가 `#content-canvas` 교체 | 양쪽 `[FACT]` |
| 스크립트 규약 | 없음 | 최상위 `var`만, `destroy()` 필수, `test_per_page_scripts`가 강제 | `AGENTS.md` 3절 |
| 인라인 `<script>`/`{{ var }}` in JS/`\|safe` | 사용 | **금지**, `test_source_boundaries`가 검출 | `AGENTS.md` 8절 |

**영향**
- MES 셸을 채택하면 AIDataHub 화면 10개·템플릿 33개가 **재작성 대상**이다.
- 그중 **라벨링(BBOX/POLYGON 캔버스)과 검수 화면은 WeZonGrid로 옮길 수 없다** — 그리드가 아니라 좌표 편집 캔버스다. `[INFERENCE]`
- AIDataHub 셸을 채택하면 프롬프트 §4·§15("MES UI/UX와 Template 구조를 Backbone으로")를 위반한다.
- `X_FRAME_OPTIONS`는 프로젝트 전역 설정이다. `SAMEORIGIN`으로 통일하면 AIDataHub가 `DENY`로 막던 클릭재킹 표면이 넓어진다 `[FACT]`.

**권장 대응** → `DEC-013`
공통 셸·메뉴·권한·목록/검색/CRUD 화면은 MES 규약(iframe + WeZonGrid). **라벨링·검수 캔버스 화면만 AIDataHub 구현을 iframe 페이지로 이식**한다. 이 경우 `X_FRAME_OPTIONS='SAMEORIGIN'`을 전역으로 쓰고, 캔버스 화면에서는 `{% block extra_js %}` 대신 MES의 `{% block scripts %}`로 맞춘다.

---

### C-21 / C-22 / C-23. 템플릿·Context Processor·미들웨어 — `MEDIUM` / `LOW` / `MEDIUM`

**확인된 사실** `[FACT]`

| 항목 | MES | AIDataHub |
|---|---|---|
| `TEMPLATES.DIRS` | `[BASE_DIR/templates]` — **그런데 실제 템플릿은 `app/templates/`에 있다** | `[]` |
| `APP_DIRS` | **주석 처리** + `loaders`에 `filesystem.Loader`와 `app_directories.Loader`를 직접 지정 | `True` |
| `TEMPLATES` 정의 위치 | **`if DEBUG:` 블록 안** → `DEBUG=False`면 미정의 | 최상위 |
| context_processors | `debug`, `request`, `auth`, `messages` | `request`, `auth`, `messages`, **`domain.context_processors.navigation`** |
| 미들웨어 | `whitenoise` → security → session → common → csrf → auth → messages → clickjacking → **`configurations.middleware.response.RemoveCriticalResponseHeader`** | security → **`RequestIdMiddleware`** → session → common → csrf → auth → **`domain.tenancy.TenantMiddleware`** → messages → clickjacking |

**영향**
- `TEMPLATES`가 `if DEBUG:` 안에 있는 것은 **운영 배포 시 앱 부팅 실패**로 이어진다 `[INFERENCE]`. 통합 시 반드시 고친다.
- `TenantMiddleware`는 로그인·테넌트 선택을 모든 요청에서 먼저 막는 장치다. 제거하면 AIDataHub 화면 권한 전제가 사라진다 → `DEC-004`
- `navigation` context processor는 AIDataHub SPA 셸 전용이다. MES 셸 채택 시 불필요.

---

### C-30. Django 버전 호환 — `HIGH`

**확인된 사실** `[FACT]`
- `MES/requirements.txt`: `Django==5.0.4`
- `MES/domain/models/user.py:10`: `from django.contrib.postgres.fields import JSONField` (try/except 없음, 모듈 최상위)
- 같은 파일에서 `JSONField`는 **실제로 사용되지 않는다**(모델 필드 정의에 등장하지 않음).
- `MES/domain/models/mes.py:4`는 같은 import가 **주석 처리**되어 있다 → 과거에 문제를 겪고 주석 처리한 흔적 `[INFERENCE]`

**영향**
`django.contrib.postgres.fields.JSONField`는 Django 3.1에서 deprecated, **4.0에서 제거**되었다. Django 5.0.4에서는 `ImportError`가 발생할 것으로 보인다 `[NEEDS_CONFIRMATION]` — 이 워크스페이스에 Django가 설치되어 있지 않아 실행 확인을 못 했다. 그러나 MES가 실제로 운영 중이라는 전제와 모순되므로, **배포 환경의 Django 버전이 requirements와 다를 가능성**이 있다 → `01_CURRENT_STATE_ANALYSIS.md` N2.

**대응**: 이관 시 이 import를 삭제한다(사용되지 않으므로 무손실). 동시에 배포 Django 버전을 확인한다.

---

## 2. Domain 의미 충돌

### C-12. 동일 명칭 / 다른 의미 — `HIGH`

**확인된 사실** `[FACT]`

| 용어 | MES | AIDataHub | vision-inspection | 통합 시 문제 |
|---|---|---|---|---|
| **검사(Inspection/Test)** | `test_*` 테이블군 = **품질검사**(수입검사·공정검사·시험항목·시험방법). `check_*` = **설비 점검** | 없음 (`Project`가 "검사 과제") | `inspections` = **비전 검사 1회 실행 기록** | 메뉴·테이블·용어가 3중으로 겹친다. 사용자 혼란 |
| **공정(Process)** | `process` 테이블 = **제조 공정**(Factory FK, 라우팅의 단위, `OutSourcingYN`) | 없음 | `processes` 테이블 = **검사 공정 그룹**(code/name/display_order만) | 테이블명은 `process` vs `processes`로 다르지만 **개념이 겹친다.** 하나로 합칠지 별도로 둘지 |
| **제품(Product/Material)** | `material` 테이블 = **자재·반제품·제품 통합 품목 마스터**(BOM·재고·LOT의 축) | 없음 | `products` 테이블 = **검사 대상 제품**(process FK, code/name) | vision `products`를 MES `material`에 매핑할지, 별도 마스터로 둘지 |
| **모델(Model)** | `mlops_model` = **생산데이터 tabular ML 모델**(수요예측·불량예측, scikit-learn) | 없음 | `models` = **비전 AI 모델**(torchvision/patchcore artifact) | 이름은 같고 도메인이 완전히 다르다. 통합 Registry로 합치면 안 된다 |
| **프로젝트(Project)** | 없음(고객사 프로젝트는 소스 파생 개념) | `Project` = **검사 과제**(데이터셋·라벨클래스·작업자 배정의 축) | 없음 | vision의 `Process→Product→InspectionItem`과 병렬 계층이 된다 |
| **사용자(User)** | `auth_user` + `user_profile`(Factory/Company/Depart 포함) | `auth_user` + `user_profile`(최소) | **`admin_users`**(독립) + `clients`(장치) | C-04, C-13 |
| **클라이언트(Client)** | `company` = **거래처**. `mat_company` = 자재 거래처 | 없음 | `clients` = **검사 PC 장치** | "Client 관리" 메뉴가 거래처로 오해될 수 있다 |
| **라벨(Label)** | `label_code` = **다국어 UI 라벨** | `LabelClass` = **어노테이션 클래스**, `label_status` = 라벨링 진행 상태 | 없음 | 용어 충돌. C-18과 연결 |
| **그룹(Group)** | `UserGroup` = **권한 그룹**, `mat_grp`/`equ_grp` = 분류 그룹 | `UserGroup`(권한) + **`Group`(작업그룹, 테넌트 소속)** | 없음 | `Group`과 `UserGroup`이 같은 프로젝트에 공존하면 혼란 |
| **버전(Version)** | 없음 | `DatasetVersion`(스냅샷), `Dataset.version` | `models.version`, `overlays.version`, `catalog.version` | 의미가 다 다르다(스냅샷 / 모델버전 / 캐시키) |
| **작업(Job/Task)** | `batch_q` = 배치 작업, `job_res` = **작업지시 실적** | `BackgroundJob`(큐), `LabelingTask`(라벨링 단위) | 없음 | `job`이 생산 작업지시를 뜻하는 곳에 큐 개념을 섞으면 혼란 |

**권장 대응** → `DEC-025`
통합 플랫폼의 **용어 사전(Glossary)을 먼저 확정**하고, 충돌하는 이름은 도메인 접두어로 구분한다. 예:
```text
vision_process     / vision_product     / vision_inspection_item
(MES) process      / material           / test_*
data_project(검사 과제) / label_class
gpu_model / gpu_model_version   vs   mlops_model(현재 범위 밖)
```

---

### C-14. Model Registry 3중 충돌 — `HIGH`

**확인된 사실** `[FACT]`

| 위치 | 테이블/화면 | 내용 |
|---|---|---|
| MES | `mlops_model`, `mlops_model_config`, `mlops_train_dataset`, `mlops_train_run`, `mlops_prediction` (전부 `managed=False`) + 화면 7개(`wm_mlops_model_master`, `_config`, `_data`, `_train`, `_eval`, `wm_mlops_predict_monitor`, `_report`) | **생산데이터 tabular ML.** `ai_analysis.py`가 scikit-learn `LinearRegression`/`Ridge`/`GradientBoostingRegressor`로 수요예측·불량예측·소요량예측. `mlops_train_run`에 accuracy/precision/recall/f1/mape/rmse |
| vision Server | `models`(name, inspection_type, version, artifact_path, runtime, threshold, active), `model_mappings`(inspection_item_id, model_id, active) + Admin 화면 | **비전 AI 모델.** torchvision Detection / PatchCore Anomaly |
| 목표(프롬프트 §2.3, §10) | GPU Server Model Registry: Model, ModelVersion, Model Loading, Deployment, Training Result, Evaluation Result | 신규 |

**영향**
- 프롬프트 §22가 경고한 "AI Model Management가 Web/WAS와 GPU에 중복 구현되는 문제"가 **이미 MES 안에 존재한다.**
- 그러나 두 Registry는 **도메인이 다르다**(tabular 생산예측 vs 비전검사). 하나로 합치면 오히려 잘못이다.
- `mlops_*`는 `managed=False`이고 **DDL 원본이 `domain/_sql/`에 없다** → 통합 DB에 어떻게 만들지 불명 `[NEEDS_CONFIRMATION]`(N11).

**권장 대응** → `DEC-009`
`mlops_*`와 MLOps 화면 7개를 **현재 범위에서 제외**(`[FUTURE]`)한다. GPU Server Registry는 비전 모델 전용으로 신규 설계하고, 이름을 `gpu_model*`처럼 구분한다. 나중에 `mlops_*`를 가져올 때 이름이 겹치지 않는다.

---

### C-10. `model_mappings`의 Cross-Service FK — `HIGH`

**확인된 사실** `[FACT]`
```python
class ModelMappingRow(...):
    inspection_item_id: FK → inspection_items.id   # 프롬프트: WEB 소유
    model_id:           FK → models.id             # 프롬프트: GPU 소유
    # 검사항목당 active 매핑 1개: 부분 unique index WHERE active
```

**영향**
- 프롬프트 §2.2 C는 `검사항목 ↔ 모델 매핑`을 **WEB 책임**으로, §2.3 A는 `Model Registry`를 **GPU 책임**으로 정한다.
- 같은 PostgreSQL을 쓰면 DB FK를 유지할 수 있으나, **WEB이 GPU 소유 테이블에 FK 제약을 갖는다** → GPU가 모델을 삭제할 때 WEB 테이블이 막는다(또는 반대로 WEB 매핑이 유령 모델을 가리킨다).
- Model Version까지 생기면 매핑이 `model_id`가 아니라 `model_version_id`를 가리켜야 하는지도 결정 사항이다.

**권장 대응** → `DEC-010`
WEB이 `vision_item_model_mapping`을 소유하고, GPU 모델은 **DB FK 없이 식별자(모델 코드 + 버전 문자열)로 참조**한다. 유효성은 WEB이 저장 시점에 GPU `GET /models`로 확인한다. 무결성보다 서비스 독립성을 택한다.

---

### C-05b. `Project`(AIDataHub) ↔ `Process/Product/InspectionItem`(vision) 계층 충돌 — `HIGH`

**확인된 사실** `[FACT]`

```text
AIDataHub:  Tenant → Project(task_type) → Dataset → ImageAsset → Annotation
                              └→ LabelClass, DataStandard, LabelingTask

vision:     Process → Product → InspectionItem(inspection_type) → ModelMapping → Model
                                        └→ Overlay, Inspection(결과)
```

- `Project.task_type`: `OBJECT_DETECTION` / `CLASSIFICATION` / `ANOMALY_DETECTION` (3종)
- `InspectionItem.inspection_type`: `DETECTION` / `ANOMALY` (2종, **PostgreSQL native enum**)
- **`CLASSIFICATION`에 대응하는 검사 유형이 없다.**
- `LabelClass`(과제별 라벨 클래스)와 검사 결과의 `defects[].class_name`(모델이 내는 클래스명)이 **연결되어 있지 않다** — 별개의 문자열이다.

**영향**
- "어떤 검사항목의 데이터를 어떤 과제에서 라벨링하는가"를 잇는 관계가 **양쪽 어디에도 없다.** 신규 설계가 필요하다.
- 두 계층을 그대로 두면 사용자가 같은 대상을 두 곳에서 관리한다(검사항목 등록 + 과제 등록).
- `inspection_type`이 PG native enum이므로 값 추가(`CLASSIFICATION`)는 `ALTER TYPE`이 필요하다 → C-26.

**권장 대응** → `DEC-005`
`Project`(검사 과제)를 유지하고, `Project ↔ InspectionItem` 연결 필드를 추가한다(1:1 또는 1:N). `LabelClass ↔ 모델 클래스명` 매핑도 설계 대상으로 명시한다.

---

## 3. Auth 충돌

### C-13. 관리자 사용자 저장소 이중화 — `HIGH`

**확인된 사실** `[FACT]`
- vision Server는 `admin_users` 테이블(`username` unique, `password_hash` PBKDF2, `active`, `last_login_at`)과 자체 세션(itsdangerous, 기본 8시간, `require_admin`이 세션 + **DB 재확인** + CSRF)을 쓴다.
- Admin 권한 등급은 **1개**다(세분화 없음). `AdminAuditLog`는 "관리하지 않기로 결정" 상태.
- MES·AIDataHub는 `auth_user`를 쓴다.

**영향**
- 통합 후 관리자가 두 곳에 존재하면 계정 관리가 갈라진다.
- vision Admin 기능을 Django로 옮기면 **권한이 1등급에서 MES `UserGroupMenu` 다등급으로 세분화**되므로, 어떤 메뉴에 어떤 권한을 매핑할지 신규 설계가 필요하다.
- vision의 `login_throttle`과 세션 무효화(`test_admin_session_revocation.py`)는 MES에 없는 보안 기능이다. 버리면 보안 후퇴다.

**권장 대응** → `DEC-018`
`admin_users` 폐기, MES 사용자/권한으로 통합. 단 `login_throttle`과 세션 DB 재확인은 **MES 로그인에 이식**한다.

---

### C-27. 무인증 공개 엔드포인트 — `HIGH`

**확인된 사실** `[FACT]` (`settings.py` 주석)
> "API로 내려주는 배포물 위치. licenses/(LGPL 대응 소스)와 client/(Client 배포 zip)를 둔다(API.md §49·§50). **이 아래 파일은 인증 없이 공개된다** — 내부망 한정은 방화벽이 지킨다."

**영향**
목표 아키텍처에서 ManufacturingAIPlatform은 **Public Subnet**에 있고 외부 사용자가 접근한다(프롬프트 §1.1). vision Server는 내부망 전제였다. 이 엔드포인트를 그대로 옮기면 **공개 인터넷에 무인증 파일 다운로드 경로가 열린다.**

**권장 대응** → `DEC-024`
현재 범위에서 `[REMOVE]`. Client 배포는 웹 플랫폼 밖의 경로(사내 파일서버)로 분리하거나, 인증을 붙인 뒤 이관한다.

---

### C-19. 세션 / 쿠키 / 보안 헤더 정책 — `MEDIUM`

**확인된 사실** `[FACT]`

| 설정 | MES | AIDataHub |
|---|---|---|
| `SESSION_COOKIE_NAME` | `mes25-1` | `aidatahub-v2` |
| `SESSION_COOKIE_SECURE` | 미설정(기본 False) | `HTTPS_ENABLED` 연동 |
| `SESSION_COOKIE_HTTPONLY` | 미설정(기본 True) | `True` 명시 |
| `CSRF_COOKIE_SECURE` / `_HTTPONLY` | 미설정 | `HTTPS_ENABLED` / `False` |
| `SECURE_SSL_REDIRECT` | 미설정 | `HTTPS_ENABLED` |
| `SECURE_HSTS_SECONDS` | 미설정 | 31,536,000(HTTPS 시) |
| `SECURE_PROXY_SSL_HEADER` | 미설정 | `("HTTP_X_FORWARDED_PROTO","https")` |
| `SECURE_CONTENT_TYPE_NOSNIFF` | 미설정 | `True` |
| `SECURE_REFERRER_POLICY` | 미설정 | `same-origin` |
| `SECURE_BROWSER_XSS_FILTER` | `True`(현대 브라우저에서 무의미) | 미설정 |
| `X_FRAME_OPTIONS` | `SAMEORIGIN` | `DENY` |
| `ALLOWED_HOSTS` | `["*"]` 고정 | 운영 모드에서 `["*"]`면 **`ImproperlyConfigured`로 부팅 거부** |
| `CSRF_TRUSTED_ORIGINS` | 미설정 | 환경변수 |
| 응답 헤더 제거 미들웨어 | `RemoveCriticalResponseHeader` | 없음 |

**영향**: 프롬프트 §1이 HTTPS 443 종단을 전제하므로 **AIDataHub 쪽 설정이 목표에 더 맞다.** MES 설정을 그대로 쓰면 HSTS·Secure 쿠키·SSL 리다이렉트가 전부 빠진다.

**권장 대응** → `DEC-020` 과 함께: 설정 파일은 MES 구조(단일 `settings.py`)를 유지하되 **AIDataHub의 보안 설정값과 환경변수 패턴을 채택**한다.

---

## 4. DB 충돌

### C-08. 멀티테넌시 / RLS — `HIGH`

**확인된 사실** `[FACT]`
- `TenantOwnedModel`(추상)이 `tenant = FK(Tenant, on_delete=PROTECT)` **NOT NULL**을 강제한다. AIDataHub 업무 모델 대부분이 이를 상속한다.
- `Tenant.id`는 **UUID**.
- `0001_initial`의 `TENANT_TABLES` **19개 테이블**에 RLS 정책(`vision_data_<모델>_tenant_scope`)이 걸려 있다.
- 거의 모든 unique 제약과 index가 `tenant`를 **첫 컬럼**으로 포함한다(예: `unique_dataset_version_in_tenant_project`, `image_list_dataset_label_idx`).
- `tenant_atomic(tenant)`가 `SET LOCAL app.tenant_id`를 걸고, 워커도 같은 규칙을 따른다.
- `AGENTS.md`: "RLS를 임의로 제거·우회하지 않는다. 성능 문제도 RLS를 끄는 방식으로 풀지 않는다."
- MES·vision Server에는 테넌트 개념이 **없다**. MES `UserProfile.Factory`가 유사하지만 인가 경계로 쓰이지 않는다 `[INFERENCE]`.

**영향 — 세 가지 선택의 비용**

| 선택 | 스키마 변경 | 코드 변경 | 위험 |
|---|---|---|---|
| (A) Tenant 제거 | 19테이블 `tenant` 컬럼 삭제 + 모든 unique/index 재정의 + RLS 정책 삭제 | 서비스 46개에서 `tenant` 인자·`tenant_atomic` 제거, `TenantScopedManager` 제거 | **매우 큼.** AIDataHub 테스트 603건 대부분이 테넌트 픽스처를 쓴다 |
| (B) 단일 Tenant 고정 | 없음 | `TenantMiddleware`를 "고정 테넌트 주입"으로 축소, 조직 선택 화면 제거 | **작다.** 다만 UUID FK와 RLS가 영구히 남는다 |
| (C) 그대로 유지 | 없음 | MES 사용자/권한과 Tenant 소속을 잇는 설계 추가 | 사용자에게 "조직" 개념이 새로 생긴다. MES에는 없는 축이다 |

**권장 대응** → `DEC-004`: **(B)** — 스키마를 건드리지 않고 단일 조직으로 고정. RLS는 유지하되 사용자에게 노출하지 않는다. 필요 시 나중에 (A)로 간다.

---

### C-11 / C-25. PK 타입 / `DEFAULT_AUTO_FIELD` — `HIGH`

**확인된 사실** `[FACT]`

| 시스템 | 기본 PK | 예외 |
|---|---|---|
| MES | `AutoField` = int4. 모델마다 `id = models.AutoField(primary_key=True)` 명시 | — |
| AIDataHub | `BigAutoField` = int8 | `Tenant.id` = **UUID** |
| vision | `BigInteger` | `inspections.id`/`request_id` = **String(36)**, `retention_policies.id` = Integer 고정 1, `image_migrations.inspection_id` = String(36) PK/FK |

**영향**
- 한 프로젝트에 `DEFAULT_AUTO_FIELD`는 하나다. MES 모델은 PK를 명시하므로 영향이 없지만, **이식하는 AIDataHub/vision 모델은 전역 설정을 따른다.**
- MES를 따라 `AutoField`로 통일하면 AIDataHub 기존 데이터의 int8 값이 int4 범위를 넘을 수 있다 `[NEEDS_CONFIRMATION]`(N1).
- `BigAutoField`로 통일하면 MES 모델은 명시 PK라 그대로 유지되고 신규 테이블만 int8이 된다 → **혼재하지만 안전하다.**
- `inspections.id`가 UUID 문자열인 것은 **API 계약(`inspection_id`)에 노출되어 있다** → 바꾸면 Client 계약이 깨진다. 유지해야 한다.

**권장 대응** → `DEC-017`: `DEFAULT_AUTO_FIELD = BigAutoField`. MES 기존 모델은 명시 `AutoField`를 그대로 둔다. `inspections.id`는 String(36) 유지.

---

### C-26. PostgreSQL native enum — `MEDIUM`

**확인된 사실** `[FACT]`
```python
inspection_type: Mapped[InspectionTypeEnum] = mapped_column(
    Enum(InspectionTypeEnum, name="inspection_type", native_enum=True), nullable=False)
```
`processes`가 아니라 `inspection_items`와 `models` 두 테이블이 같은 PG 타입 `inspection_type`을 공유한다.

**영향**
- Django ORM은 관례적으로 `CharField` + `choices`를 쓴다. native enum을 유지하려면 커스텀 필드 또는 `RunSQL` 마이그레이션이 필요하다.
- `CLASSIFICATION` 값을 추가하려면 `ALTER TYPE inspection_type ADD VALUE`가 필요하고, **PostgreSQL에서 이 문장은 트랜잭션 안에서 실행할 수 없다**(버전에 따라 제약) `[NEEDS_CONFIRMATION]`.

**권장 대응** → `DEC-011`: 이관 시 `CharField(max_length=..., choices=...)`로 바꾼다. API 응답 문자열 값은 그대로이므로 Client 계약에 영향이 없다.

---

### C-15. 파일 저장소 — `HIGH`

**확인된 사실** `[FACT]`

| 시스템 | 경로 | 서비스 방식 |
|---|---|---|
| MES | `FILE_UPLOAD_PATH='c:\temp\mes21\'`, `FILE_TEMP_UPLOAD_PATH`, `MES_FORM_PATH`, `HMI_BACKGROUND_IMAGE_PATH`, `HMI_NODE_IMAGE_PATH` (**Windows 절대경로 하드코딩**, 부팅 시 `os.makedirs`) | `app/views/files/` 뷰 |
| AIDataHub | `MEDIA_ROOT = BASE_DIR/media`, `MEDIA_URL='/media/'`, 테넌트별 경로(`domain/storage.py`) | **권한 확인 View만**. "공개 `MEDIA_URL`로 파일 서비스, nginx가 `/media/`를 직접 서비스"를 **금지**. `FILE_UPLOAD_PERMISSIONS=0o640` |
| vision Server | `storage_root=/var/lib/vision-inspection/storage`(원본·heatmap·overlay), `model_root=.../models`, `migration_export_root=.../export`, `distribution_root=.../distribution` | 인증 라우트(`distribution`만 무인증) |

**영향**
- Windows 경로와 Linux 경로가 섞여 있다 → 배포 OS 결정(`DEC-020`)에 종속.
- 업로드 상한: MES 미설정(Django 기본 2.5MB 메모리), AIDataHub `FILE_UPLOAD_MAX_MEMORY_SIZE=30MB`/`DATA_UPLOAD_MAX_MEMORY_SIZE=35MB`, vision은 경로별 Body size limit 미들웨어(413/411). **검사 이미지와 데이터셋 이미지가 같은 Django에 올라오므로 상한 정책을 통합해야 한다.**
- Object Storage는 프롬프트 §1.1에서 **명시 제외**다. 따라서 로컬 파일시스템 레이아웃이 설계 대상이다(프롬프트 §1.1은 "서버 내부 저장 디렉터리 구조는 핵심 설계 대상이 아니다"라고 하지만, **보존 정책·권한 서비스·검사↔데이터셋 이미지 공유가 여기에 걸린다**).

**권장 대응** → `DEC-019`: 단일 루트 아래 용도별 하위 디렉터리 + **모든 이미지는 권한 확인 View로만 제공**(AIDataHub 규약 채택). nginx가 `/static/`만 직접 서비스.

---

### C-24. 의존성 버전 충돌 — `MEDIUM`

**확인된 사실** `[FACT]`

| 패키지 | MES | AIDataHub | vision Server |
|---|---|---|---|
| Django | 5.0.4 | 5.0.4 | — |
| psycopg | **`psycopg 3.1.18` + `psycopg2 2.9.9` + `psycopg-binary` 동시 설치** / ENGINE은 `postgresql_psycopg2` | `psycopg[binary]>=3.2,<3.4` / ENGINE은 `postgresql` | `psycopg[binary] 3.3.5` |
| Pillow | 10.3.0 | >=11.0,<12.0 | 12.3.0 |
| torch | 2.5.1 | — | 2.14.0 |
| torchvision | — | — | 0.29.0 |
| WSGI 서버 | `wfastcgi 3.0.0`(IIS) | `waitress>=3.0,<4` | `uvicorn[standard] 0.52.4` |
| 정적파일 | `whitenoise 6.9.0` | 없음(nginx) | 없음(nginx) |
| 기타 무거운 의존성 | scikit-learn, lightgbm, xgboost, matplotlib, seaborn, plotly, pandas, numpy, pyodbc, paho-mqtt, basyx-python-sdk, qrcode, lxml, PyJWT 1.7.1, djangorestframework, djangorestframework-jwt | playwright | — |

**영향**
- MES `requirements.txt`는 통합 플랫폼에 불필요한 의존성이 많다(MQTT·MSSQL ODBC·AAS SDK·시각화 라이브러리·tabular ML). 그대로 가져오면 배포 이미지가 커지고 취약점 표면이 넓어진다.
- `psycopg2`와 `psycopg`(v3)를 동시에 두는 것은 혼란이다. ENGINE도 `postgresql_psycopg2`(구형 별칭)를 쓴다.
- `djangorestframework-jwt`는 **유지보수가 끝난 패키지**이고 `PyJWT 1.7.1`은 2019년 버전이다 `[INFERENCE]`. PDA 기능이 범위 밖이므로 제거 대상.
- **torch를 WEB과 GPU 양쪽에 두지 않는다** — 목표 구조에서 추론은 GPU Server 전담이므로 WEB requirements에서 torch·scikit-learn 계열을 빼야 한다.

---

## 5. Migration 충돌

C-03에 통합 서술. 추가로:

| 항목 | 내용 | Severity |
|---|---|---|
| MES `domain/_sql/database.sql`이 7줄뿐 | DB·사용자·스키마(`das`, `ai`) 생성만. **179개 테이블 DDL이 어디에도 없다.** 실제 스키마는 Django 마이그레이션이 만든다 | MEDIUM (C-29) |
| MES `search_path=public,das,ai` | `das`/`ai` 스키마에 어떤 테이블이 있는지 소스에서 알 수 없다 | MEDIUM `[NEEDS_CONFIRMATION]` N8 |
| `mlops_*`가 `managed=False` | Django가 만들지 않고 DDL 원본도 없다. 통합 DB에 어떻게 생성할지 불명 | MEDIUM `[NEEDS_CONFIRMATION]` N11 |
| AIDataHub 기존 DB의 제약·인덱스 이름이 `ai_domain_` 접두어 | 새로 만든 DB와 이름이 다르다. 이관 스크립트가 이름에 의존하면 실패 | HIGH(이관 시) |
| vision Alembic → Django | 자동 변환 없음. 11테이블 재정의 필요 | HIGH |

---

## 6. API 충돌

### C-09. 응답 규약 3종 — `HIGH`

**확인된 사실** `[FACT]`

| 시스템 | 성공 | 실패 | HTTP status |
|---|---|---|---|
| MES | 행 리스트 그대로 또는 `{'success':True, ...}` | `{'success':False,'message':str(ex)}` | **항상 200** (뷰 함수가 예외를 삼킨다) |
| AIDataHub | `{"ok":true,"message":"...","data":{...}}` | `{"ok":false,"message":"...","code":"...","errors":{...}}` | **의미에 맞는 status** |
| vision | `{"data":{...}}` | `{"error":{"code":"...","message":"...","retryable":bool}}` | 400/401/404/409/413/422/429/503 등 |

**영향**
- **VisionInspectionClient는 vision 규약에 묶여 있다.** `server_client.py`가 `payload["data"]`를 읽고 `error.code`/`retryable`로 retry를 판단한다. MES 규약으로 바꾸면 Client를 고쳐야 한다.
- 따라서 **`/api/v1/*`는 MES 응답 규약을 적용할 수 없다.** MES의 `ApiModuleView` 경로와 분리된 별도 뷰 계층이 필요하다.
- 화면용 내부 API는 MES 규약을 쓸 수 있으나, AIDataHub 화면 스크립트는 `{ok, data}`와 실패 콜백 `(xhr, status, error)` 3번째 인자에서 메시지를 읽는 규약에 묶여 있다 `[FACT]`.

**권장 대응** → `DEC-007`, `DEC-014`
```text
/api/v1/*        → vision 계약 그대로 (Client 호환 계층, 독립 뷰 클래스)
/api/<task>/<view> → MES 규약 (화면용)
내부 GPU 호출     → 신규 계약(DEC-015)
```
3개 규약이 공존하는 것을 **의도적 설계로 문서화**한다. 섞지 않는다.

---

### 기타 API 충돌

| ID | 항목 | 내용 | Severity |
|---|---|---|---|
| A-1 | Multipart 처리 | vision: `image`(파일) + `metadata`(JSON 문자열) 2파트. MES: `posparam` dict + `Q`/`_dic` JSON 파싱. **규약이 다르다** | MEDIUM |
| A-2 | Idempotency | vision: `request_id` unique + 동시 요청 시 `IntegrityError` rollback + 파일 삭제. MES·AIDataHub: **개념 없음** | HIGH(신규 이식) |
| A-3 | Timeout | Client connect 3s / read 30s. GPU 추론 시간이 여기 들어가야 한다(`inference_ms` 41~82ms 예시). MES에는 타임아웃 정책이 없다 | HIGH → DEC-015 |
| A-4 | Retry 가능 오류 구분 | vision `error.retryable`. MES·AIDataHub에 없음 | MEDIUM |
| A-5 | Rate limit | vision Client별 분당 120건(설정값). MES·AIDataHub 없음 | MEDIUM |
| A-6 | 시각 형식 | vision 응답 **UTC `Z` 고정**. MES `USE_TZ=False`로 naive datetime을 그대로 직렬화 | HIGH → C-10 |
| A-7 | 오류 코드 집합 | vision: `AUTH_REQUIRED`, `AUTH_INVALID`, `METADATA_INVALID`, `OVERLAY_NOT_FOUND`, `RESULT_IMAGE_NOT_AVAILABLE`, `HEATMAP_NOT_FOUND`, `IMAGE_EXPIRED` 등. MES: 코드 없음(문자열 메시지만) | MEDIUM |
| A-8 | 미구현 계약 | vision `docs/API.md`가 명시: 목록 응답 `meta.count`, `CLIENT_VERSION_UNSUPPORTED` 미구현 | LOW |
| A-9 | 이미지 URL 신뢰 경계 | Client는 `/api/v1` 아래 **상대경로만** 따라간다. 통합 후 이미지 URL이 다른 prefix면 Client가 거부한다 | **HIGH** → DEC-007 |
| A-10 | CSRF | MES `FilesView`는 `csrf_exempt`. `/api/v1/*`는 Client가 CSRF 토큰을 갖지 않으므로 면제 필요 + API Key 인증으로 보호 | MEDIUM |

> **A-9는 놓치기 쉬운 함정이다.** `server_client.py`가 응답의 `image_url`/`result_image_url`/`heatmap_url`을 `/api/v1` 아래 상대경로만 허용하고 그 밖이면 `logger.warning("Refused image path outside /api/v1")`로 거부한다. 통합 플랫폼이 이미지 URL을 `/media/...`나 `/api/vision/...`로 바꾸면 **Client가 이미지를 못 받는다.** `[FACT]`

---

## 7. Client 호환성

**확인된 사실** `[FACT]` — Client가 호출하는 것은 6개 엔드포인트뿐이고, 계약이 문서화되어 있다.

| # | Endpoint | 분류 | 통합 시 필요한 것 |
|---|---|---|---|
| 1 | `GET /api/v1/health` | **KEEP** | `{status, version, components:{database, storage}}` 형태 유지. 200/503 |
| 2 | `GET /api/v1/catalog` | **KEEP** | `data.version` + `processes[].products[].inspection_items[]` 중첩 + 각 항목의 `overlay:{available, version}`. 활성 항목만 |
| 3 | `POST /api/v1/inspections` | **KEEP** | multipart(`image`, `metadata`), idempotency, 카탈로그 정합성 검증, `RECEIVED`/`SUCCESS`/`FAILED`, DETECTION/ANOMALY 응답 스키마, **`result_image_url`/`heatmap_url`은 `/api/v1` 하위 상대경로** |
| 4 | `GET /api/v1/inspections/by-request/{request_id}` | **KEEP** | retry 전 선조회. 다른 Client의 `request_id`면 409 |
| 5 | `GET /api/v1/overlays/{id}` | **KEEP** | `{inspection_item_id, version, visible, opacity, image_url, updated_at}`. 없으면 404 `OVERLAY_NOT_FOUND` |
| 6 | `GET /api/v1/overlays/{id}/image` | **KEEP** | PNG/JPEG, `Cache-Control: private, max-age=86400`, `?version=` 쿼리 |
| — | 인증 헤더 `X-Client-ID`/`X-API-Key` | **KEEP** | SHA-256 해시 비교. 누락 401 `AUTH_REQUIRED`, 불일치/비활성 401 `AUTH_INVALID` |
| — | Base URL | **MODIFY_CLIENT(설정만)** | Client 설정 파일의 base_url 변경. **코드 변경 없음** |

**Client 변경이 필요해지는 경우** `[INFERENCE]`
- 이미지 URL prefix가 `/api/v1` 밖으로 나가면 → A-9
- 응답 봉투를 `{data}`/`{error}`에서 바꾸면
- 인증을 세션/JWT로 바꾸면
- `inspection_id` 타입을 UUID 문자열에서 바꾸면
- HTTPS 인증서가 사설 CA면 → Client 신뢰 저장소 설정 필요 `[NEEDS_CONFIRMATION]`

**권장 대응** → `DEC-007`: **Client 무변경(Base URL만 변경)** 을 목표로 Django에 `/api/v1/*` 호환 계층을 만든다. 6개 엔드포인트 + 인증 + 오류 봉투를 계약대로 구현하고, vision의 `tests/integration/test_*_api.py` 56건을 **Contract Test로 이식**해 회귀를 막는다.

---

## 8. GPU Model 관리 충돌

C-14, C-10에 서술. 추가:

| ID | 항목 | 내용 | Severity |
|---|---|---|---|
| G-1 | 추론이 웹 프로세스 안에 있다 | vision Server는 FastAPI 워커에서 직접 torch 추론. GPU OOM·학습/추론 경합 대비 없음 | **HIGH**(목표 구조에서 해소) |
| G-2 | 모델 로딩 정책 없음 | Load/Unload API 없음, 활성 모델 관리 없음 | HIGH(신규) |
| G-3 | 학습 기능이 CLI 하나 | `fit-anomaly`(PatchCore). Training Job·상태·취소·Checkpoint·Evaluation 없음 | **HIGH**(신규) → DEC-027 |
| G-4 | 학습 데이터 경로 미정 | AIDataHub Export(8포맷)가 만든 zip을 GPU가 어떻게 받는가? 공유 볼륨 / API / DB 참조 중 미결정 | **HIGH** → DEC-026 |
| G-5 | 모델 버전 ↔ 검사 결과 추적 | `inspections.model_name`/`model_version`은 **문자열 스냅샷**이다(FK 아님). 모델이 삭제돼도 기록은 남는다 — 좋은 설계지만 Registry와의 관계 명시 필요 | MEDIUM |
| G-6 | `threshold` 소유 | `models.threshold`(GPU 소유)가 판정 기준이고 응답에 나간다. 업무적으로 조정해야 하면 WEB에서 바꿔야 한다 | MEDIUM → DEC-010 |
| G-7 | 클래스명 매핑 | 모델이 내는 `defects[].class_name`과 AIDataHub `LabelClass.name`이 연결되지 않았다 | MEDIUM → DEC-005 |
| G-8 | torch 버전 분기 | MES 2.5.1 / vision 2.14.0. GPU CUDA 버전과 맞춰야 한다 | MEDIUM `[NEEDS_CONFIRMATION]` N6 |

---

## 9. Shared DB Ownership 문제

프롬프트 §3은 "PostgreSQL을 WEB과 GPU가 모두 직접 접근"하는 것을 전제로 한다. 현재 구현에서 이를 위한 준비는 **전혀 없다**(단일 서비스가 단일 DB를 독점).

| 문제 | 내용 | Severity |
|---|---|---|
| O-1 | **Owner 부재** | 어떤 테이블을 누가 쓰는지 정의가 없다. 프롬프트 §3의 표를 채우는 것이 Stage 3 작업 | **CRITICAL**(설계 미비) |
| O-2 | `model_mappings`의 cross-service FK | C-10 | HIGH |
| O-3 | `inspections` 동시 Write 가능성 | WEB이 행을 만들고(`RECEIVED`), 추론 결과로 같은 행을 갱신한다. GPU가 직접 갱신하면 **같은 행에 두 서비스가 Write**한다 | **HIGH** → DEC-008 |
| O-4 | Transaction Boundary | vision은 이미지 저장 → 행 생성 commit → 추론 → 결과 갱신으로 트랜잭션을 나눈다. GPU가 분리되면 경계가 네트워크를 넘는다. 부분 실패 정책 필요 | **HIGH** → DEC-008, DEC-015 |
| O-5 | Connection Pool | AIDataHub `CONN_MAX_AGE=60` + `CONN_HEALTH_CHECKS`. MES 미설정(요청마다 연결). GPU는 별도. **한 DB에 세 종류 연결 정책** | MEDIUM |
| O-6 | RLS와 GPU | RLS 정책은 `app.tenant_id` 세션 변수를 요구한다. GPU가 같은 DB에 직접 접근하면 **RLS 정책에 걸려 데이터를 못 읽는다**(또는 BYPASSRLS 권한이 필요하다) | **HIGH** → DEC-004, DEC-011 |
| O-7 | 마이그레이션 소유 | Django migrations가 GPU 소유 테이블도 만드는가, GPU가 Alembic으로 자기 테이블을 만드는가 | HIGH → DEC-011 |
| O-8 | `search_path` | MES는 `public,das,ai`. GPU 연결의 search_path를 어떻게 맞추는가 | MEDIUM |

> **O-6은 특히 중요하다.** `DEC-004`에서 RLS를 유지하기로 하면, GPU Server의 DB 사용자는 RLS 우회 권한이 필요하거나 **테넌트 데이터에 직접 접근하지 않아야 한다.** 후자가 안전하다 → GPU는 DB에서 모델 Registry/Training 테이블만 쓰고, 이미지·데이터셋은 WEB이 API로 넘긴다.

---

## 10. 운영 / 인프라 충돌

### C-16. 배포 스택 — `HIGH`

**확인된 사실** `[FACT]`

| 시스템 | OS | 웹서버 | 앱서버 | 프로세스 관리 |
|---|---|---|---|---|
| MES | Windows (IIS) | IIS | `wfastcgi` | IIS |
| AIDataHub | Linux | nginx | `waitress` | systemd(`aidatahub-v2-worker` 언급) |
| vision Server | Ubuntu 24.04 LTS | nginx | `uvicorn` | systemd + timer(`vision-inspection-purge.timer`) |
| vision Client | Windows 11 | — | PyInstaller EXE | — |
| 목표(프롬프트 §1) | NCP VPC | **Nginx** | Django | — |

**영향**
- 프롬프트가 Nginx를 명시하므로 **Linux(Ubuntu)가 목표에 부합**한다. 그러면 MES의 IIS+wfastcgi 배포 절차와 Windows 절대경로(`c:\temp\mes21\`)를 전부 바꿔야 한다.
- MES가 Windows 전용 코드에 의존하는지 확인 필요 `[NEEDS_CONFIRMATION]`: `pyodbc`(MSSQL, 미사용 경로), 파일 경로, `wfastcgi`.
- GPU Server는 CUDA 때문에 Linux가 사실상 필수 `[INFERENCE]`.

**권장 대응** → `DEC-020`: Ubuntu 24.04 + nginx + (gunicorn 또는 waitress) + systemd. MES의 IIS 배포 문서는 이관 대상에서 제외.

### C-20. Static 자원 정책 — `MEDIUM`

**확인된 사실** `[FACT]`
- MES: `STATIC_ROOT = BASE_DIR/static`, `collectstatic` 사용, `whitenoise` 미들웨어, `DEBUG` 시 `static()` 서빙.
- AIDataHub: **`STATIC_ROOT`를 두지 않는다.** "collectstatic으로 사본을 만들지 않고, 운영에서는 nginx가 `app/static/`을 직접 읽는다(2026-09-21 결정). 모아 둔 사본은 원본과 어긋난 채 배포되기 쉬워 그 단계를 없앴다." Django admin 자산만 `/static/admin/`을 nginx가 따로 잡는다.

**영향**: MES 템플릿은 `/static/assets/...` 절대경로를 하드코딩한다(`{% static %}` 태그 미사용) `[FACT]`. 어느 방식이든 `/static/` prefix가 유지되면 동작한다. `collectstatic` 여부만 결정하면 된다.

### C-17. 백그라운드 작업 — `MEDIUM`

| 시스템 | 방식 | 특징 |
|---|---|---|
| MES | `batch_q` / `batch_log` 테이블 + MQTT(`paho-mqtt`) | 워커 구현이 소스에 명확하지 않다 `[NEEDS_CONFIRMATION]` |
| AIDataHub | `BackgroundJob` + `manage.py run_worker`/`process_jobs` | `FOR UPDATE SKIP LOCKED` claim, claim/본문 트랜잭션 분리, 다중 워커 검증(2026-09-24), **재시도·백오프 없음** |
| vision | CLI + systemd timer (`purge-images` 매일 03:30) | 웹 프로세스와 분리(대량 삭제가 검사 요청을 밀지 않게) |

**권장 대응** → `DEC-022`: AIDataHub `BackgroundJob` + 워커를 채택한다(가장 검증된 구현). vision의 `purge-images`는 Django management command + systemd timer로 이식. MES `batch_q`는 범위 밖.

### C-18. 다국어 — `MEDIUM`

**확인된 사실** `[FACT]`
- MES: `label_code`/`label_code_lang`/`grid_col_lang` 테이블 + `static/lang/` + `system/labelcode.py`·`menu_language.py` 화면. ko/en/zh/vi. `UserProfile.lang_code`.
- AIDataHub: "화면 문구는 템플릿에 한국어로 직접 쓴다. 기존 `data-commonCd`·`data-labelCd` 속성은 그대로 두고 **새로 늘리지 않는다. 라벨 API 기반 i18n은 도입하지 않는다.**" — 단 `UserProfile.lang_code`는 갖고 있다.

**영향**: MES 기준으로 가면 이식하는 모든 데이터관리·비전검사 화면에 라벨코드를 등록해야 한다(화면 10개 + 신규 화면 다수). 상당한 부수 작업이다.

**권장 대응** → `DEC-021`: 1단계는 **한국어 고정**(MES 라벨코드 인프라는 유지하되 신규 화면에 적용하지 않음). 다국어가 요구사항이면 별도 Phase로 분리.

---

## 11. Severity별 정리

### CRITICAL (6) — 결정 없이 진행 불가
C-01 패키지명 / C-02 App Label / C-03 Migration / C-04 사용자 테이블 스키마 / C-05 인가 아키텍처 / C-06 vision 기술 스택
(+ O-1 DB Ownership 정의 부재)

### HIGH (17)
C-07 표현 계층 / C-08 멀티테넌시·RLS / C-09 API 응답 규약 / C-10 시각 / C-11·C-25 PK 타입 / C-12 도메인 용어 / C-13 관리자 저장소 / C-14 Model Registry / C-15 파일 저장소 / C-16 배포 스택 / C-27 무인증 공개 / C-28 형상관리 / C-30 Django 호환 / C-05b Project↔InspectionItem 계층 / C-10(mapping FK) / A-2 Idempotency / A-3 Timeout / A-9 이미지 URL 신뢰 경계 / G-1·G-3·G-4 GPU / O-3·O-4·O-6·O-7

### MEDIUM (13)
C-17 백그라운드 / C-18 다국어 / C-19 보안 헤더 / C-20 Static / C-21 템플릿 로더 / C-23 미들웨어 / C-24 의존성 / C-26 PG enum / C-29 문서 불일치 / A-1 Multipart / A-4 retryable / A-5 rate limit / A-7 오류 코드 / A-10 CSRF / G-5·G-6·G-7·G-8 / O-5·O-8

### LOW (3)
C-22 Context Processor / A-8 미구현 계약 / MES 잔여 산출물(`lang.py.deprecated` 등)

---

## 12. 결정으로 이어지는 항목

이 문서의 모든 충돌은 `USER_DECISIONS.md`의 `DEC-001` ~ `DEC-027`로 집약했다. 결정이 필요 없는 항목(단순 정리·명백한 수정)은 결정 문서에 넣지 않고 구현 계획의 작업으로 둔다:

- MES 비밀값 환경변수화 (D2)
- `TEMPLATES`를 `if DEBUG:` 밖으로 (D3)
- 미사용 `postgres.fields.JSONField` import 삭제 (C-30)
- 초기 비밀번호 `'1'` 하드코딩 제거
- `apiPermissionMap` 死코드 → 실제 사용 (C-05, 단 방식은 DEC-014)
- MSSQL 분기·`pyodbc`·MQTT·tabular ML 의존성 제거 (C-24)
- `overlays` x/y/width/height 死컬럼 제거 (D16)
- 전시회·고객사 전용 코드 제외 (D7, D10)
