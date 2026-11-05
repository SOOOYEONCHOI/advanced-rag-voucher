# 07. Implementation Plan — ManufacturingAIPlatform 시스템 구축 작업 계획

- 기준일: 2026-09-30
- 상위 규범: `ManufacturingAIPlatform_MES_Backbone_통합구축_프롬프트.md` §18 (Phase 0~11)
- **rev.2 (2026-09-30)**: `USER_DECISIONS.md` **§1.6** 반영 — 검사항목 단일화, 검사 접수 시점 자동 연계,
  공정·제품·보존정책·이관기능 제외. Task 4.2·5.1·5.6 삭제, Task 4.6 재작성(76 → 72 Task).
- 확정 근거: `USER_DECISIONS.md` §1·§1.5·**§1.6**, `04_TARGET_ARCHITECTURE.md`, `05_DATABASE_MIGRATION_PLAN.md`, `06_API_COMPATIBILITY_PLAN.md`, `SCREEN_MAPPING.md`
- **이 문서는 승인 대기 상태다.** 승인 전에는 코드를 변경하지 않는다.

---

## 0. 계획 요약

| Phase | 제목 | Task 수 | 주요 산출물 |
|---|---|---:|---|
| 0 | Baseline 확보 · MES Backbone 복제 · 불필요 Domain 제거 | 8 | 부팅 가능한 최소 MES |
| 1 | MES System Management 정리 | 6 | 시스템관리 15화면 + 인가 훅 |
| 2 | AIDataHub Model / Service 이식 | 7 | 데이터 도메인 모델·서비스·워커 |
| 3 | AIDataHub Web 화면 이식 | 11 | 데이터 관리 11화면(검사항목 포함) + Canvas 모듈 추출 |
| 4 | vision-inspection Model / Service 이식 (GPU Runtime 제외) | 5 | 비전 도메인 모델·서비스·Gateway Stub·검사 접수 연계 |
| 5 | vision-inspection Admin/Web 화면 이식 | 5 | 비전 검사 관리 5화면 |
| 6 | VisionInspectionClient API 호환 계층 | 5 | `/api/v1/*` 6종 + 호환 계층 |
| 7 | Menu / Permission 통합 | 4 | 메뉴 트리 · 2단계 인가 전면 적용 |
| 8 | DB Migration 및 Seed | 5 | `0001_initial` · Seed 4종 · (조건부) 데이터 이관 |
| 9 | 통합 기능 검증 | 5 | 화면 전수 점검 결과 |
| 10 | 신규 Test 작성 | 7 | `tests/` 7개 영역 |
| 11 | E2E / Regression Test | 5 | E2E 시나리오 · 회귀 세트 |
| | **합계** | **73** | |

### 진행 원칙

1. **Phase 순서를 지킨다.** 앞 Phase의 완료 조건을 만족하지 못하면 다음으로 넘어가지 않는다.
2. **Big Bang Merge를 하지 않는다.** Task 단위로 변경하고 즉시 동작을 확인한다.
3. 새 의사결정이 생기면 **구현을 중지**하고 `USER_DECISIONS.md`에 DEC 항목을 추가한다.
4. 각 Task 완료 시 `IMPLEMENTATION_STATUS.md`에 변경 파일·검증 결과를 기록한다.
5. **기존 프로젝트 테스트를 이관하지 않는다.** 통과 여부는 완료 조건이 아니다(Backbone §2·§19).
6. `torch`·`torchvision`·`scikit-learn`·`paho-mqtt`·`pyodbc`·`wfastcgi`를 의존성에 넣지 않는다.
7. **원본 3개 프로젝트를 수정하지 않는다.** 참조 전용이다.

### 검증 명령 (Phase 0에서 고정)

```bash
export PYTHONUTF8=1
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test tests --settings=configurations.test_settings
for f in app/static/assets/js/*.js app/static/data/*.js; do node --check "$f"; done
python scripts/verify_rls.py
python scripts/verify_permission_map.py     # 신규 — apiPermissionMap 전수 정합성
python scripts/verify_menu.py               # 신규 — gui.py ↔ menu_item 정합성
```

> **테스트는 반드시 `--settings=configurations.test_settings`로 실행한다.** 빼면 운영 PostgreSQL에 테스트 DB가 생긴다(AIDataHub에서 확인된 사고 유형).

---

## Phase 0 — Baseline 확보 · MES Backbone 복제 · 불필요 Domain 제거

**목적**: MES를 복제해 ManufacturingAIPlatform의 골격을 만들고, 범위 밖 업무 Domain을 제거해 **부팅 가능한 최소 상태**에 도달한다.

**완료 기준**: `manage.py check` 0건, `runserver` 기동, 로그인 화면 표시, 시스템관리 메뉴 진입.

---

### Task 0.1 — 원본 스냅샷 및 신규 리포지토리 생성

- **Related Decisions**: DEC-001(A), C-28
- **목적**: 형상관리가 없는 상태(세 프로젝트 모두 git 저장소 아님)를 해소하고 복구 지점을 만든다.
- **Source**: `C:\projects\yest\{MES, AIDataHub, vision-inspection}`
- **수정 대상**: 없음(원본 무수정)
- **구현 내용**
  1. 원본 3개 디렉터리를 읽기 전용 스냅샷으로 보존(`_reference/` 또는 별도 보관 위치).
  2. `MES/`를 `manufacturing_ai_platform/`으로 **복제**.
  3. 신규 리포지토리에서 `git init` + `.gitignore`(`__pycache__`, `*.pyc`, `media/`, `static/`, `.env`, `.venv`) + 초기 커밋 `chore: MES 기준소스 복제로 ManufacturingAIPlatform 초기화`.
  4. 원본 3개도 각각 `git init` + 초기 커밋을 권장(변경 추적 가능 상태 확보). **원본 파일 내용은 수정하지 않는다.**
- **Dependency**: 없음
- **DB 변경 / API 변경 / Migration**: 없음
- **테스트**: `git status` 클린. 복제본 파일 수가 원본과 일치.
- **완료 조건**: `manufacturing_ai_platform/`에 MES 전체가 복제되고 초기 커밋이 있다.
- **Rollback**: 디렉터리 삭제 후 재복제.

---

### Task 0.2 — settings 환경변수화 및 부팅 결함 수정

- **Related Decisions**: DEC-011(A), DEC-016(B), DEC-017(A), DEC-019(A), DEC-020(A) / 부채 D2·D3·D5
- **목적**: MES settings의 부팅 결함과 비밀값 하드코딩을 제거한다.
- **Source**: `MES/configurations/settings.py`
- **수정 대상**: `configurations/settings.py`, `configurations/test_settings.py`(신규), `requirements.txt`, `.env.example`(신규)
- **구현 내용**
  1. **`TEMPLATES`를 `if DEBUG:` 블록 밖으로 이동**(D3 — `DEBUG=False`에서 앱이 뜨지 않던 결함).
  2. `SECRET_KEY`·DB 접속정보·`STORAGE_ROOT`·`ALLOWED_HOSTS`·`CSRF_TRUSTED_ORIGINS`를 환경변수로. 기본값은 개발값, 운영은 환경변수로 덮는다(AIDataHub 패턴).
  3. `DEBUG=False` + `ALLOWED_HOSTS=['*']`이면 `ImproperlyConfigured`로 부팅 거부(AIDataHub 패턴).
  4. 보안 설정 추가: `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY='same-origin'`, `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`/`HSTS`/`SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`는 `HTTPS_ENABLED` 연동. `X_FRAME_OPTIONS='SAMEORIGIN'` 유지(iframe 셸).
  5. `DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'`. `USE_TZ=False` 유지.
  6. DB: 신규 DB, `CONN_MAX_AGE=60`, `CONN_HEALTH_CHECKS=True`, ENGINE을 `django.db.backends.postgresql`로.
  7. Windows 경로 5개(`FILE_UPLOAD_PATH` 등) → `STORAGE_ROOT` 기반 경로로 교체(DEC-019 레이아웃).
  8. MQTT/`SITE_NAME`/`HMI_*`/`AI_API_HOST`/`SF_LOG_KEY` 설정 제거.
  9. `SESSION_COOKIE_NAME='map'`, `SESSION_COOKIE_HTTPONLY=True`.
  10. `requirements.txt` 정리 — **제거**: torch, scikit-learn, lightgbm, xgboost, imbalanced-learn, matplotlib, seaborn, plotly, pandas(사용처 확인 후), pyodbc, paho-mqtt, basyx-python-sdk, pyecma376-2, wfastcgi, djangorestframework-jwt, PyJWT, psycopg2, qrcode(사용처 확인 후). **추가**: `gunicorn`. **유지**: Django, psycopg[binary], Pillow, openpyxl, whitenoise(정적 서빙 보조), python-dateutil.
  11. `configurations/test_settings.py` 신규 — SQLite 기반, `TENANT_RLS_ENABLED=False`, `STORAGE_ROOT`는 임시 디렉터리.
  12. `domain/models/user.py:10`의 `from django.contrib.postgres.fields import JSONField` **삭제**(D5 — Django 4.0에서 제거된 심볼, 실제 미사용).
- **Dependency**: Task 0.1
- **DB 변경**: 없음(설정만)
- **API 변경**: 없음
- **Migration**: 없음
- **테스트**: `manage.py check` 0건. `DEBUG=False`로도 `check` 통과. `check --deploy` 경고 목록 기록.
- **완료 조건**: 환경변수 없이 개발 기동, 환경변수로 운영값 주입 가능.
- **Rollback**: `git revert`.

---

### Task 0.3 — 범위 밖 MES 업무 Domain 제거

- **Related Decisions**: DEC-023(B), DEC-009(A)
- **목적**: 데이터관리·비전검사·시스템관리 3개 도메인 밖의 MES 자산을 제거한다.
- **Source**: 복제된 MES 트리
- **수정 대상**: `app/views/`, `app/templates/`, `domain/services/`, `domain/models/`
- **구현 내용**
  1. **`app/views/` 제거**: `sales/ schedule/ production/ inventory/ lot/ shipment/ haccp/ haccp_std/ hcp_*/ maintenance/ person/ das/ tagdata/ spc/ test/ check/ summary/ dashboard/ support/ ai/ sequence/ mobile.py public.py` + `app/views/pda/`
  2. **유지**: `system/ definition/(선별) common/ files/ popup/ account.py static.py schema.py __init__.py`
  3. `app/views/definition/`에서 **`unit.py company.py depart.py code_info.py`만 유지**, 나머지 31개 제거.
  4. **`app/templates/` 제거**: 위 업무 폴더 전체 + `samples/ document/(선별) pda/`
  5. **`domain/services/` 제거**: `sales/ schedule/ production/ inventory/ shipment/ haccp/ maintenance/ person/ das/ dashboard/ quality/ calculation/ interface/ support/ ai/ setup/ mqtt.py`
  6. **`domain/models/` 정리**: `haccp.py check.py mlops.py` **삭제**. `mes.py`에서 `Factory` `Company` `Depart` `Unit`만 남긴 `basic.py`로 축소하고 `mes.py` 삭제. `sequence.py` 유지, `system.py`에서 범위 밖 모델(`DocumentForm` 이후 업무 모델, `WorkCalendar`, `Calendar`, `ActionMaster/Data`, `RelationData`, `BundleHead`, `StoryboardItem`, `Board*`, `BatchLog`, `BatchQ`, `SFLog`) 제거.
  7. `domain/gui.py`에서 유지 대상 **15개 gui 항목 외 전부 삭제**(약 359개). `apiPermissionMap`도 같은 범위로 축소.
  8. `configurations/urls.py`에서 제거: `das_device`, `ai/nl2sql/sse`, `ai/mes_chatbot/sse`, `pda/<...>`, `api/v1/token/*`, `public/exhibition/`, `mobile/`, `dt/<filename>`.
  9. `domain/migrations/` **전부 삭제**(Phase 8에서 `0001_initial` 신규 작성).
  10. `app/static/`에서 미사용 자산 정리는 **하지 않는다**(Phase 9에서 실사용 확인 후).
- **Dependency**: Task 0.2
- **DB 변경**: 없음(이 단계에서는 모델 정의만 제거)
- **API 변경**: 제거된 `task/view` 경로는 404
- **Migration**: 없음(Phase 8에서 신규 생성)
- **테스트**: `manage.py check` 0건. `grep -rn "from domain.models.mes import"` 등 잔존 import 0건. `runserver` 기동 후 로그인 화면 200.
- **완료 조건**: 제거 후에도 `check`·기동·로그인 화면이 정상. 잔존 import 오류 없음.
- **Rollback**: `git revert`. 삭제 범위가 크므로 **커밋을 영역별로 나눈다**(views / templates / services / models / gui).

---

### Task 0.4 — 미들웨어·공통 계층 정리

- **Related Decisions**: DEC-013(B), DEC-020(A)
- **목적**: 공통 요청 처리 계층을 통합 기준으로 맞춘다.
- **Source**: MES `configurations/middleware/`, AIDataHub `configurations/middleware/request_id.py`
- **수정 대상**: `configurations/middleware/`, `configurations/settings.py`
- **구현 내용**
  1. AIDataHub `RequestIdMiddleware` 이식 — 요청마다 `X-Request-ID` 생성/전파, 로그 상관관계.
  2. MES `RemoveCriticalResponseHeader` 유지.
  3. `TenantMiddleware`는 **이식하지 않는다**. 대신 Task 2.1의 고정 Tenant 주입 유틸로 대체(DEC-004 B).
  4. 미들웨어 순서 확정: `whitenoise → security → RequestId → session → common → csrf → auth → messages → clickjacking → RemoveCriticalResponseHeader`.
- **Dependency**: Task 0.2
- **DB/API/Migration**: 없음
- **테스트**: 응답 헤더에 `X-Request-ID` 존재. 로그에 request id 출력.
- **완료 조건**: 모든 요청이 상관관계 ID를 갖는다.
- **Rollback**: `git revert`.

---

### Task 0.5 — 공통 셸 정리 (동기 Ajax 제거)

- **Related Decisions**: DEC-013(B) / 부채 D9
- **목적**: MES 공통 셸의 동기 Ajax를 제거하고 Canvas 화면을 담을 수 있는 상태로 만든다.
- **Source**: `app/templates/app/{index.html, index_page.js, layout_page.html, system.js}`
- **수정 대상**: 동상
- **구현 내용**
  1. `layout_page.html`의 즐겨찾기 로드 `AjaxUtil.getSyncData('/api/system/bookmark')` → **비동기**로 교체.
  2. `index_page.js`의 동기 호출 전수 확인 후 비동기화.
  3. `layout_page.html`에 `{% block extra_css %}`·`{% block extra_js %}` 추가(Canvas 화면용 번들 로딩 지점).
  4. 전시회 CSS 주석·디지털트윈 링크 등 사용하지 않는 참조 제거.
  5. 타이틀을 `SF ALL SYSTEM` → `Manufacturing AI Platform`으로.
- **Dependency**: Task 0.3
- **DB/API/Migration**: 없음
- **테스트**: 브라우저 콘솔 오류 0건. 메뉴 탭 전환·모달 열기 동작. 즐겨찾기 토글 동작.
- **완료 조건**: 동기 Ajax 0건(`grep -rn "getSyncData" app/` 결과 0).
- **Rollback**: `git revert`.

---

### Task 0.6 — 파일 저장소 계층 정비

- **Related Decisions**: DEC-019(A)
- **목적**: `STORAGE_ROOT` 단일 루트와 권한 확인 파일 제공 계층을 만든다.
- **Source**: MES `app/views/files/`, AIDataHub `domain/storage.py` + Private View 4종
- **수정 대상**: `domain/storage.py`(신규), `app/views/files/`
- **구현 내용**
  1. `domain/storage.py` — `STORAGE_ROOT` 하위 경로 생성 함수(`dataset_image_path`, `inspection_image_path`, `overlay_path`, `export_path`, `cover_path`, `standard_image_path`).
  2. `app/views/files/__init__.py` — 권한 확인 후 파일을 스트리밍하는 공통 헬퍼. `FileResponse` + `Content-Disposition` + 경로 정규화(상위 경로 탈출 차단).
  3. 업로드 상한 설정: `FILE_UPLOAD_MAX_MEMORY_SIZE=30MB`, `DATA_UPLOAD_MAX_MEMORY_SIZE=35MB`, `FILE_UPLOAD_PERMISSIONS=0o640`.
  4. nginx는 `/static/`만 직접 서비스. **`/media/`를 nginx에 노출하지 않는다.**
  5. MES 기존 `files/` 뷰 중 범위 내 것(`upload`, `download`, `image`, `excel_export`)만 유지.
- **Dependency**: Task 0.2, 0.3
- **DB/API/Migration**: 없음
- **테스트**: 경로 탈출(`../`) 시도 403. 미인증 요청 401.
- **완료 조건**: 모든 파일 제공이 권한 확인 View를 거친다.
- **Rollback**: `git revert`.

---

### Task 0.7 — 검증 스크립트 골격

- **Related Decisions**: DEC-014(A), DEC-022(A)
- **목적**: 이후 Phase에서 정합성을 자동 확인할 스크립트를 미리 만든다.
- **수정 대상**: `scripts/verify_permission_map.py`, `scripts/verify_menu.py`, `scripts/verify_rls.py`
- **구현 내용**
  1. `verify_permission_map.py` — `app/views/<task>/<view>.py` 파일 전수를 스캔해 `apiPermissionMap` 키와 **양방향 대조**. 누락/고아 항목을 출력하고 exit code로 보고.
  2. `verify_menu.py` — `gui.py GUI_ITEMS` 키 ↔ `menu_item.MenuCode` 양방향 대조.
  3. `verify_rls.py` — AIDataHub 원본 이식(Phase 2에서 실제 동작).
- **Dependency**: Task 0.3
- **DB/API/Migration**: 없음
- **테스트**: 세 스크립트가 현재 상태에서 실행되고 결과를 출력한다.
- **완료 조건**: 스크립트 3개 동작.
- **Rollback**: 파일 삭제.

---

### Task 0.8 — Phase 0 회귀 확인

- **Related Decisions**: —
- **목적**: 제거 작업이 Backbone을 깨뜨리지 않았는지 확인한다.
- **구현 내용**: 수동 점검 — 로그인/로그아웃, 홈 진입, 시스템관리 메뉴 15개 화면 진입, 사용자 목록 조회, 사용자그룹 조회, 메뉴권한 조회, 코드정보 CRUD, 단위정보 CRUD.
- **Dependency**: Task 0.1~0.7
- **테스트**: 위 항목 전부 수동 확인. 결과를 `IMPLEMENTATION_STATUS.md`에 기록.
- **완료 조건**: **MES 기존 DB(`yest`)에 연결한 상태**에서 위 화면이 전부 동작한다. (이 시점에는 아직 신규 DB가 없다. 읽기 전용으로만 확인하고 데이터를 변경하지 않는다.)
- **Rollback**: 실패 항목별 원인 분석 후 해당 Task로 복귀.

> **주의**: 이 확인은 기존 운영/개발 DB에 접속한다. **쓰기 작업을 하지 않는다.** 위험하다고 판단되면 이 Task를 Phase 8 이후로 미루고, Phase 0의 완료 조건을 `manage.py check` + 기동 + 로그인 화면 렌더까지로 축소한다.

---

## Phase 1 — MES System Management 정리

**목적**: 시스템 관리 기능을 통합 플랫폼 기준으로 정리하고, **API 인가 훅**을 넣는다.

**완료 기준**: 시스템관리 15화면 동작, 모든 `/api/<task>/<view>` 호출이 메뉴 권한 검사를 거친다.

---

### Task 1.1 — `ApiModuleView` 인가 훅 추가 (1단계: 경고 모드)

- **Related Decisions**: DEC-014(A), DEC-003(B) / 충돌 C-05
- **목적**: MES의 인가 공백(로그인만 하면 모든 업무 API 호출 가능)을 메운다.
- **Source**: `app/views/__init__.py`, `domain/gui.py`(`apiPermissionMap`, `get_menu_code_by_taskview`)
- **수정 대상**: `app/views/__init__.py`, `domain/gui.py`
- **구현 내용**
  1. `ApiModuleView.dispatch()`에 인가 단계 삽입:
     ```text
     로그인 확인 → get_menu_code_by_taskview(task, view)
       ├ 화이트리스트(ANONYMOUS_SAFE_VIEWS)  → 통과
       ├ 매핑 없음  → [1단계] 경고 로그 + 통과
       └ 매핑 있음  → check_user_auth(user, menu_code) 로 판정
                       GET → 'R' 필요 / POST → 'W' 필요 / 불충족 시 403
     ```
  2. `get_menu_code_by_taskview()`가 여러 메뉴 코드를 돌려주면 **하나라도 권한이 있으면 통과**(기존 `apiPermissionMap` 구조가 리스트다).
  3. 화이트리스트를 `apiPermissionMap`의 `['']` 항목에서 **명시 상수로 분리**: `system/combo`, `system/menus`, `system/myinfo`, `system/bookmark`, `files/upload`, `files/download`, `files/excel_export`, `popup/*`.
  4. `TemplatePathView`(`/page/<folder>/<name>`)에도 동일 검사 추가. 팝업은 부모 화면의 gui_code를 쿼리로 받아 판정하거나 화이트리스트에 둔다.
  5. `FilesView`도 동일 검사 적용(CSRF 면제는 유지하되 인가는 건다).
- **Dependency**: Phase 0
- **DB 변경**: 없음
- **API 변경**: 권한 없는 호출이 **403**으로 바뀐다(기존 200). 1단계에서는 매핑 누락이 경고만.
- **Migration**: 없음
- **테스트**: `tests/permissions/` 초안 — 권한 없는 사용자가 `/api/system/user`를 호출하면 403. 화이트리스트 경로는 200.
- **완료 조건**: 경고 로그 모드로 동작. 시스템관리 화면이 모두 정상.
- **Rollback**: 인가 단계를 설정 플래그(`API_AUTHZ_MODE=off|warn|enforce`)로 감싸 즉시 끌 수 있게 한다.

---

### Task 1.2 — 로그인 하드닝

- **Related Decisions**: DEC-018(A)
- **목적**: vision Server의 검증된 로그인 보안 기능을 MES 로그인에 이식한다.
- **Source**: `vision-inspection/server/src/.../admin/dependencies/{auth,login_throttle}.py` (참조 전용)
- **수정 대상**: `app/views/account.py`, `domain/services/account.py`, `domain/models/system.py`(`LoginLog`)
- **구현 내용**
  1. **로그인 시도 제한**: 같은 `username`/IP 조합에 대해 실패 N회(기본 5) 후 M분(기본 10) 잠금. 저장은 `login_log` 집계 또는 캐시.
  2. **세션 DB 재확인**: 요청마다 `user.is_active`와 `user_profile.UserGroup` 유효성을 확인한다(계정 비활성화 시 기존 세션도 즉시 무효). `MESBaseView.dispatch()`에 추가.
  3. `LoginLog`에 `ip_address`·`user_agent`·`fail_reason` 컬럼 추가.
  4. 로그인 성공/실패 모두 기록.
  5. `app/views/system/user.py`의 **초기 비밀번호 `'1'` 하드코딩 제거** — 관리자가 입력하거나 임시 비밀번호를 생성해 1회 노출.
- **Dependency**: Task 1.1
- **DB 변경**: `login_log` 컬럼 3개 추가
- **API 변경**: 로그인 실패 응답에 잠금 안내
- **Migration**: Phase 8 `0001_initial`에 반영
- **테스트**: 실패 5회 후 잠금. 잠금 해제 시각 이후 성공. 비활성화된 계정의 기존 세션이 즉시 거부.
- **완료 조건**: 위 테스트 통과.
- **Rollback**: `git revert`.

---

### Task 1.3 — 시스템관리 화면 정리

- **Related Decisions**: DEC-023(B), DEC-021(A), DEC-022(A)
- **목적**: 유지 대상 15화면을 통합 플랫폼 기준으로 정리한다.
- **Source**: `SCREEN_MAPPING.md` §4
- **수정 대상**: `app/views/system/`, `app/templates/system/`, `app/views/definition/`, `domain/gui.py`
- **구현 내용**
  1. 유지 화면: `wm_user`, `wm_user_group`, `wm_user_group_menu`, `wm_code`, `wm_unit`, `wm_company`, `wm_depart`, `wm_multi_language`, `wm_menu_language`, `wm_prop_master`, `wm_login_log`, `wm_menu_log`, `wm_system_log`, `wm_batch_log`.
  2. `wm_batch_log` 화면의 조회 대상을 `batch_log` → **`BackgroundJob`**으로 변경(DEC-022). 컬럼: 작업종류·상태·요청자·시작/완료·오류·재시도 횟수.
  3. `system/` 하위에서 범위 밖 모듈 제거: `das_config.py das_server*.py plc_write.py tag_data_make.py storyboard.py notice*.py title_notice.py shift.py kpc_kpi_log.py sflog.py factory_setup.py`(화면 없이 API만 남길지 확인 후), `master_t.py`, `db_schema.py`.
  4. `definition/`에서 `unit.py company.py depart.py code_info.py`만 유지.
  5. `gui.py` `GUI_ITEMS`를 15개 + `wm_noauth_default`로 확정.
- **Dependency**: Task 1.1
- **DB 변경**: 없음
- **API 변경**: 제거된 `system/*` 경로 404
- **테스트**: 15화면 전수 진입 + 목록 조회. `verify_permission_map.py` 고아 항목 0건.
- **완료 조건**: 15화면 동작, 권한 매핑 정합.
- **Rollback**: `git revert`.

---

### Task 1.4 — `user_profile` 스키마 조정

- **Related Decisions**: DEC-002(A′)
- **목적**: 범위 밖 컬럼을 제거한다.
- **수정 대상**: `domain/models/user.py`, `domain/services/account.py`, `app/views/system/user.py`
- **구현 내용**
  1. `UserProfile`에서 `access_token`·`refresh_token` **제거**(PDA 범위 밖 + DB에 토큰 저장은 바람직하지 않음).
  2. `CompCode` 유지 여부 확인 — 사용처가 없으면 제거.
  3. `AccountService.get_user_list`/`get_user_detail`의 raw SQL에서 제거된 컬럼 참조 정리.
  4. AIDataHub 사용자 함수 5종(`user_is_platform_admin`, `user_display_name`, `set_user_display_name`, `set_user_group`, `platform_admin_q`)을 **MES 모델 위에서 동작하도록** `domain/services/account.py`에 어댑터로 추가(Phase 2·3에서 데이터 도메인이 사용).
     - `user_is_platform_admin`: MES 규칙(`is_superuser` 또는 `UserGroup.Code in ('dev','admin')`)을 따른다.
- **Dependency**: Task 1.3
- **DB 변경**: `user_profile` 컬럼 2~3개 제거
- **Migration**: Phase 8에 반영
- **테스트**: 사용자 CRUD 동작. 어댑터 함수 단위 테스트.
- **완료 조건**: 사용자 화면 정상, 어댑터 5종 제공.
- **Rollback**: `git revert`.

---

### Task 1.5 — 인가 훅 2단계 전환 (기본 거부)

- **Related Decisions**: DEC-014(A)
- **목적**: 매핑 누락을 전수 해소한 뒤 기본 거부로 전환한다.
- **수정 대상**: `domain/gui.py`, `configurations/settings.py`
- **구현 내용**
  1. `verify_permission_map.py`로 누락 0건 확인.
  2. `API_AUTHZ_MODE='enforce'`로 전환 — 매핑 없는 `task/view`는 **403**.
  3. 경고 로그 모드에서 수집된 누락 항목을 전부 매핑에 등록.
- **Dependency**: Task 1.1, 1.3
- **API 변경**: 매핑 없는 경로 403
- **테스트**: `verify_permission_map.py` PASS. 시스템관리 15화면 전수 재확인.
- **완료 조건**: enforce 모드에서 모든 화면 정상.
- **Rollback**: `API_AUTHZ_MODE='warn'`으로 즉시 복귀.

> Phase 3·5에서 화면을 추가할 때마다 **매핑 등록이 누락되면 즉시 403**이 된다. 각 Task의 완료 조건에 `verify_permission_map.py` PASS를 포함한다.

---

### Task 1.6 — Phase 1 회귀 확인

- **구현 내용**: 로그인(정상/실패/잠금), 사용자 CRUD, 사용자그룹 CRUD, 메뉴권한 부여·회수 후 화면/API 접근 변화 확인, 공통코드·단위·업체·부서 CRUD, 로그 3종 조회.
- **완료 조건**: 전 항목 동작 + 권한 회수 시 화면·API 모두 차단됨을 확인.
- **Rollback**: 해당 Task로 복귀.

---

## Phase 2 — AIDataHub Model / Service 이식

**목적**: 데이터 관리 도메인의 **모델·서비스·워커**를 이식한다. 화면은 Phase 3.

**완료 기준**: 데이터 도메인 모델 21개 정의, 서비스가 단위 테스트로 동작, 워커 기동.

---

### Task 2.1 — 테넌시 기반 구조 이식 (단일 Tenant 고정)

- **Related Decisions**: DEC-004(B)
- **목적**: AIDataHub 서비스가 의존하는 테넌트 구조를 **스키마 변경 없이** 단일 조직으로 고정한다.
- **Source**: `AIDataHub/domain/{tenancy.py, models/tenancy.py}`
- **수정 대상**: `domain/models/data.py`, `domain/tenancy.py`(신규)
- **구현 내용**
  1. `Tenant`·`TenantMembership`·`Group`·`GroupMember`·`TenantOwnedModel`·`TenantScopedManager` 이식(테이블명 `vision_data_*` 유지).
  2. `Tenant`에 **단일 행 CheckConstraint** 추가(고정 UUID).
  3. `TenantMiddleware`를 이식하지 않고 `current_tenant()` 헬퍼로 대체 — 항상 고정 Tenant를 반환하며 캐시한다.
  4. `tenant_atomic(tenant)` 이식 — `SET LOCAL app.tenant_id`. RLS 유지.
  5. 조직 선택 화면·조직 관리 화면은 **이식하지 않는다**(Backbone §5).
- **Dependency**: Phase 1
- **DB 변경**: `vision_data_tenant`, `..._tenantmembership`, `..._group`, `..._groupmember` 신설
- **Migration**: Phase 8
- **테스트**: `current_tenant()`가 항상 같은 행 반환. `tenant_atomic` 안에서 `SET LOCAL` 적용 확인.
- **완료 조건**: 단일 Tenant가 보장되고 RLS 컨텍스트가 설정된다.
- **Rollback**: `git revert`.

---

### Task 2.2 — 데이터 도메인 모델 이식

- **Related Decisions**: DEC-017(A), DEC-025(A), **§1.6 O-8·O-9·O-13**
- **목적**: 데이터 관리 모델 전체를 이식한다.
- **Source**: `AIDataHub/domain/models/{project,dataset,image,labeling,governance}.py`
- **수정 대상**: `domain/models/data.py`
- **구현 내용**
  1. 이식 대상 17개: `Project`, `ProjectAssignment`, `ProjectGroupAccess`, `ProjectDeletionRequest`, `LabelClass`, `ActivityLog`, `Dataset`, `ImageAsset`, `Annotation`, `StandardImage`, `LabelingTask`, `DataStandard`, `QualityRun`, `QualityFinding`, `DatasetVersion`, `ExportJob`, `BackgroundJob`.
  2. **변경**:
     - **`Project` → `InspectionItem`(테이블 `vision_data_item`)으로 개명**하고 검사항목 속성을 흡수한다(§1.6 O-8·O-13): `code`(전역 unique), `display_order`. `task_type`이 검사 유형을 겸한다.
     - `ProjectAssignment`/`ProjectGroupAccess`/`ProjectDeletionRequest`도 `Item*`으로 개명(테이블 `vision_data_item*`). **삭제 승인 절차는 유지**한다(§1.6 Q9).
     - `ImageAsset.source_inspection_id`(null 허용) 추가 — 어느 검사에서 들어온 이미지인지 추적.
     - `BackgroundJob`: `attempt_count`·`next_retry_at` 추가, `error_message`를 `TextField`로. **`MIGRATION` 유형은 추가하지 않는다**(§1.6 O-9).
  3. `AuthenticationLog`·`UserGroup`·`UserProfile`·`UserGroupMenu`는 **이식하지 않는다**(MES 것 사용).
  4. 모델 docstring·`verbose_name`을 한국어로 유지.
- **Dependency**: Task 2.1
- **DB 변경**: 17개 테이블 신설
- **Migration**: Phase 8
- **테스트**: `manage.py check` 0건. 모델 임포트 테스트.
- **완료 조건**: 모델 정의 완료, `makemigrations` 시 오류 없음.
- **Rollback**: `git revert`.

---

### Task 2.3 — 데이터 서비스 이식 (1) — 데이터셋·이미지·정제

- **Related Decisions**: DEC-013(B), DEC-019(A)
- **목적**: 이미지 수집·조회·정제 로직을 이식한다.
- **Source**: `AIDataHub/domain/services/dataset/{image,preprocess}.py`
- **수정 대상**: `domain/services/data/{dataset,image,preprocess}.py`
- **구현 내용**
  1. `ImageService` 이식 — 업로드(sha256 중복 차단), 썸네일 생성, 목록·상세, 삭제 규칙.
  2. `PreprocessService` 이식 — 회전·원근 보정·크롭·크기 조정, 원본 보존(`original_file`), 연산 목록(`preprocess` JSON). **`REUSE_LOGIC`** — 알고리즘을 그대로 옮긴다.
  3. 저장 경로를 `domain/storage.py`(Task 0.6) 기준으로 교체.
  4. `DatasetService` 신설 — 데이터셋 목록·상태 전이(RAW→VALIDATED→LABELED→CURATED→EXPORTED).
- **Dependency**: Task 2.2
- **DB/API 변경**: 없음(서비스 계층)
- **테스트**: `tests/data/test_image_service.py`, `test_preprocess.py` — 중복 sha256 거부, 회전 후 원본 보존, 썸네일 생성.
- **완료 조건**: 단위 테스트 통과.
- **Rollback**: `git revert`.

---

### Task 2.4 — 데이터 서비스 이식 (2) — 라벨링·어노테이션·검수

- **Related Decisions**: DEC-003(B)
- **목적**: 라벨링 작업 흐름과 어노테이션 기하 로직을 이식한다.
- **Source**: `AIDataHub/domain/services/dataset/{labeling_task,annotation,review,workflow}.py`
- **수정 대상**: `domain/services/data/{labeling_task,annotation,review}.py`
- **구현 내용**
  1. `LabelingTaskService` 이식 — claim(임대 토큰·만료), heartbeat, draft 저장, submit. **이미지당 활성 작업 1개** 부분 unique 제약 유지.
  2. `AnnotationService` 이식 — **`REUSE_LOGIC`**: BBOX/POLYGON 기하 검증, 좌표 범위 검사, `attributes` 처리. 도형 화이트리스트 유지(세그멘테이션 RLE는 범위 밖).
  3. `ReviewService` 이식 — 승인(`APPROVED`)·재작업(`REWORK` + 사유).
  4. 분류/탐지/이상탐지 3유형 분기 유지.
- **Dependency**: Task 2.2
- **테스트**: `tests/data/test_labeling_tasks.py`, `test_annotation_geometry.py`, `test_review.py` — 동시 claim 시 1명만 성공, 임대 만료 후 재claim, 좌표 범위 밖 어노테이션 거부.
- **완료 조건**: 단위 테스트 통과.
- **Rollback**: `git revert`.

---

### Task 2.5 — 데이터 서비스 이식 (3) — 품질·스냅샷·Export

- **Related Decisions**: DEC-022(A)
- **목적**: 데이터 거버넌스 로직을 이식한다.
- **Source**: `AIDataHub/domain/services/workspace/{quality,version}.py`, `dataset/export/*`
- **수정 대상**: `domain/services/data/{quality,version,export/}`
- **구현 내용**
  1. `QualityService` 이식 — 품질 점검 4종, `readiness`(READY/WARNING/NOT_READY), findings. **검수 승인 이미지만 대상**이라는 규칙 유지.
  2. `VersionService` 이식 — 불변 `DatasetVersion` + manifest.
  3. **Exporter 8종 `REUSE_LOGIC`** — `coco.py yolo.py imagefolder.py classification.py mvtec.py base.py registry.py`를 거의 그대로 옮긴다. `PROJECT_EXPORT_FORMATS` 매핑 유지.
  4. 저장 경로만 `domain/storage.py` 기준으로 교체.
- **Dependency**: Task 2.2, 2.3
- **테스트**: `tests/data/test_export_{coco,yolo,classification,mvtec}.py` — 각 포맷 산출물 구조 검증. `test_export_registry.py` — 과제 유형별 지원 포맷.
- **완료 조건**: 8포맷 전부 zip 생성 성공.
- **Rollback**: `git revert`.

---

### Task 2.6 — 백그라운드 워커 이식 + 재시도 추가

- **Related Decisions**: DEC-022(A)
- **목적**: 비동기 작업 기반을 구축한다.
- **Source**: `AIDataHub/domain/services/dataset/job.py`, `domain/management/commands/{run_worker,process_jobs}.py`
- **수정 대상**: `domain/services/data/job.py`, `domain/management/commands/`
- **구현 내용**
  1. `JobService` 이식 — `enqueue_*`, `_claim_next`(**`FOR UPDATE SKIP LOCKED`**), `_run_claimed`(claim과 본문 **트랜잭션 분리**), `_execute` 분기 한 곳.
  2. `run_worker`(상주) / `process_jobs`(1회) 이식.
  3. **신규**: 재시도·백오프 — `attempt_count`, `next_retry_at`. 최대 3회, 지수 백오프(1분/5분/15분). `_queued_jobs`가 `next_retry_at <= now()` 조건을 포함한다.
  4. `error_message`를 `TextField`로(절단 방지).
  5. 작업 본문은 `tenant_atomic(tenant)` 안에서 실행.
  6. systemd unit 템플릿 작성(`deploy/map-worker.service`).
- **Dependency**: Task 2.2, 2.5
- **DB 변경**: `vision_data_backgroundjob` 컬럼 추가
- **테스트**: `tests/integration/test_background_jobs.py` — 워커 2개 동시 실행 시 중복 claim 0건, 실패 시 재시도 스케줄, 3회 후 FAILED 확정.
- **완료 조건**: `process_jobs --limit 20`으로 큐가 비워진다.
- **Rollback**: `git revert`.

---

### Task 2.7 — 과제 권한 서비스 이식 (2단계 인가의 2차)

- **Related Decisions**: DEC-003(B), DEC-014(A)
- **목적**: 메뉴 권한 위에 얹을 과제 단위 인가를 구현한다.
- **Source**: `AIDataHub/domain/services/{access/authorization.py, project/access.py}`
- **수정 대상**: `domain/services/data/access.py`
- **구현 내용**
  1. `ACTION_CAPABILITIES` 이식 — 작업 → capability 매핑을 **한 곳**에만 둔다. 등록하지 않은 작업은 403.
  2. `ProjectAccessService` 이식 — `visible_projects`, `roles_for`, `role_for`, capability 판정. 입력은 `ProjectAssignment.role` + `ProjectGroupAccess`.
  3. 플랫폼 관리자 판정은 Task 1.4의 MES 어댑터(`user_is_platform_admin`)를 쓴다.
  4. 데코레이터 `@require_project_capability('view'|'upload'|'label')` 제공 — `data/*` 뷰가 사용.
  5. 조직(Tenant) 관련 판정은 단일 Tenant 전제로 단순화한다.
- **Dependency**: Task 2.1, 2.2, Task 1.4
- **테스트**: `tests/permissions/test_project_access.py` — WORKER가 미배정 과제 접근 시 404, PROJECT_MANAGER만 검수 가능, capability 미등록 작업 403.
- **완료 조건**: 단위 테스트 통과.
- **Rollback**: `git revert`.

---

## Phase 3 — AIDataHub 모든 Web 화면 이식

**목적**: `SCREEN_MAPPING.md` §2의 **데이터 관리 12화면**을 MES 패턴으로 구현한다.

**완료 기준**: 12화면 전부 `/gui/wm_data_*/`로 진입·동작. `verify_permission_map.py` PASS.

**공통 작업 규약** (각 Task에 반복 적용)

```text
1. app/views/data/<view>.py        단일 함수 + action 분기 (MES 패턴)
2. domain/services/data/<svc>.py   Phase 2에서 이식한 서비스 호출
3. app/templates/data/<screen>.html  layout_page.html 상속, WeZonGrid 목록
4. domain/gui.py                   GUI_ITEMS + apiPermissionMap 등록
5. @require_project_capability      과제 권한이 필요한 화면에 적용
6. verify_permission_map.py PASS
```

---

### Task 3.0 — Canvas JS 모듈 추출

- **Related Decisions**: DEC-013(B), Backbone §6
- **목적**: AIDataHub의 Canvas 전문 로직을 SPA 의존 없이 재사용 가능한 모듈로 뽑는다.
- **Source**: `AIDataHub/app/templates/project/{labeling,review,data_manage}/index.html`의 `{% block extra_js %}`, `app/static/js/common.js`
- **수정 대상**: `app/static/data/{annotation-canvas.js, labeling-page.js, review-page.js, preprocess-canvas.js, api-adapter.js}`
- **구현 내용**
  1. 템플릿 인라인 스크립트에서 Canvas 로직을 **별도 `.js` 파일로 추출**한다(MES는 인라인 스크립트를 허용하지만, 재사용·문법 검사를 위해 분리).
  2. **보존 대상**(Backbone §6): BBox 편집, Polygon 편집, Mask 편집, Zoom, Pan, 좌표 변환, Annotation 상태 표현, claim/heartbeat/draft/submit 호출 시퀀스, Review 승인·재작업 흐름.
  3. **제거 대상**: `spa.js` 의존, `#content-canvas` 교체, `destroy()` 재진입 처리(iframe에서는 문서가 매번 새로 로드되므로 불필요), `var` 강제 규약.
  4. `api-adapter.js` 신설 — MES 응답 규약(`{success,message}` / 행 리스트)을 Canvas 모듈이 기대하는 `{ok,data}` 형태로 변환(`06_API_COMPATIBILITY_PLAN.md` §3.3).
  5. `node --check`로 문법 검증 가능한 상태로 만든다.
- **Dependency**: Phase 2
- **DB/API/Migration**: 없음
- **테스트**: `node --check` 전 파일 통과. 정적 HTML 하네스에서 BBox 그리기·Polygon 편집·Zoom/Pan 수동 확인.
- **완료 조건**: 모듈 5개가 독립 파일로 존재하고 문법 오류가 없다.
- **Rollback**: `git revert`.

---

### Task 3.1 — 검사항목 화면 (`wm_data_item`)

- **Related Decisions**: DEC-003(B), **§1.6 O-8·O-13**
- **Source**: AIDataHub `system/projects/{index,detail}.html`, `project/home/index.html`, 모달 4종
- **Target**: `app/views/data/project.py` / `templates/data/project.html` + `page/data/{project_edit,project_assign}.html`
- **이식 방식**: `REWRITE`
- **구현 내용**
  1. 목록(WeZonGrid) — 이름·유형(`task_type`)·상태·연결된 검사항목·담당자 수·갱신일. 검색(이름·유형·상태).
  2. 상세 — 개요, 진행률(이미지 상태별 집계), 인원 배정 목록.
  3. 생성/편집 모달 — 코드·이름·유형·설명·대표이미지·업로드 가이드·표시순서. **검사항목 생성 시 업로드 데이터셋이 자동 생성된다**(`get_or_create_upload_dataset`, §1.6 O-9).
  4. 인원 배정 모달 — 사용자 검색 → `ProjectAssignment.role`(PROJECT_MANAGER/WORKER) 부여·회수. 작업그룹 접근권한(`ProjectGroupAccess`)도 여기서 관리.
  5. 대표이미지는 `files/data_cover` 권한 확인 View로 제공.
- **Dependency**: Task 2.2, 2.7, 3.0
- **DB 변경**: 없음(Phase 2에서 정의)
- **API 변경**: `/api/data/project` 신규
- **테스트**: 목록·검색·생성·편집·배정·회수. WORKER는 미배정 과제가 목록에 안 보임.
- **완료 조건**: 화면 동작 + `verify_permission_map.py` PASS.
- **Rollback**: `git revert`.

---

### Task 3.2 — 검사항목 삭제 승인 화면 (`wm_data_item` 탭)

- **Source**: AIDataHub `domain/services/project/deletion.py` (전용 화면 없었음)
- **Target**: `app/views/data/project_deletion.py` / `templates/data/project_deletion.html`
- **이식 방식**: `ADAPT` (**신규 화면**)
- **구현 내용**: 삭제 요청 목록(REQUESTED/APPROVED/REJECTED/CANCELED), 요청 생성(사유), 승인·반려(검토 메모). 승인 권한은 플랫폼 관리자.
- **Dependency**: Task 3.1
- **테스트**: 요청 → 승인 → 과제 상태 `DELETION_PENDING` → 삭제 반영.
- **완료 조건**: 워크플로 전 단계 동작.

---

### Task 3.3 — 데이터셋 · 라벨 클래스 · 데이터 표준 화면

- **Target**:
  - `wm_data_dataset` — `app/views/data/dataset.py` / `templates/data/dataset.html` (**신규 화면**, `ADAPT`)
  - `wm_data_labelclass` — `app/views/data/label_class.py` / `templates/data/label_class.html` (`REWRITE`, 과제 하위 → 독립 메뉴 승격)
  - `wm_data_standard` — `app/views/data/data_standard.py` / `templates/data/data_standard.html` (**신규 화면**, `ADAPT`)
- **구현 내용**
  1. 데이터셋: 과제별 목록·상태·버전·이미지 수. 생성·이름변경.
  2. 라벨 클래스: `name`·`display_name_ko`·`color`·`is_defect`·`annotation_shape`(BBOX/POLYGON)·정렬순서 CRUD. **모델 출력 `class_name`과 이름을 맞추라는 안내 문구 표시**(DEC-026 운영 규칙).
  3. 데이터 표준: `DataStandard`(버전·정의 JSON·활성) + `StandardImage`(예시 이미지 업로드·설명).
- **Dependency**: Task 3.1
- **테스트**: 3화면 CRUD. 라벨 클래스 삭제 시 어노테이션이 있으면 차단(`PROTECT`).
- **완료 조건**: 3화면 동작.

---

### Task 3.4 — 데이터 관리(이미지) 화면 (`wm_data_image`)

- **Related Decisions**: DEC-019(A)
- **Source**: AIDataHub `project/data_manage/index.html` + `modal_upload.html`
- **Target**: `app/views/data/{image,image_upload}.py` / `templates/data/image.html` + `page/data/image_upload.html`
- **이식 방식**: `REWRITE`(화면) + `ADAPT`(업로드 JS)
- **구현 내용**
  1. 목록 — WeZonGrid(파일명·크기·해상도·수집상태·라벨상태·등록일) + **썸네일 그리드 토글**. 필터(라벨상태·수집상태·기간·파일명).
  2. 상세 — 원본 미리보기·메타데이터·어노테이션 요약·정제 이력.
  3. 다중 업로드 모달 — 드래그앤드롭, 진행률, sha256 중복 건너뛰기 결과 보고.
  4. 삭제 — 라벨링 진행 중·승인 완료 이미지는 차단(기존 규칙 유지).
  5. 이미지·썸네일은 `files/data_image`, `files/data_thumbnail` 권한 확인 View로 제공.
- **Dependency**: Task 2.3, 3.0, 3.3
- **API 변경**: `/api/data/image`, `/api/data/image_upload`, `/api/files/data_image`, `/api/files/data_thumbnail`
- **테스트**: 30MB 업로드, 중복 차단, 목록 필터, 권한 없는 사용자의 직접 이미지 URL 접근 403.
- **완료 조건**: 화면 동작 + 이미지가 권한 확인 View로만 노출.

---

### Task 3.5 — 데이터 정제 모달 (`wm_data_image` 내)

- **Source**: AIDataHub `project/data_manage/modal_preprocess.html`
- **Target**: `templates/page/data/image_preprocess.html` + `app/static/data/preprocess-canvas.js`
- **이식 방식**: **`REUSE_LOGIC`**
- **구현 내용**: 회전·원근 보정·크롭·크기 조정 Canvas를 그대로 재사용. 원본(`original_file`) 보존, 연산 목록(`preprocess` JSON) 저장, 되돌리기.
- **Dependency**: Task 3.0, 3.4
- **테스트**: 정제 후 `original_file` 보존, 연산 목록 기록, 썸네일 재생성.
- **완료 조건**: 4종 편집 동작 + 원본 보존.

---

### Task 3.6 — 라벨링 작업 화면 (`wm_data_labeling`)

- **Related Decisions**: DEC-013(B), Backbone §6
- **Source**: AIDataHub `project/labeling/index.html`
- **Target**: `app/views/data/labeling.py` / `templates/data/labeling.html` + `app/static/data/{annotation-canvas,labeling-page}.js`
- **이식 방식**: **`REUSE_LOGIC`** (Canvas) + `REWRITE`(진입 구조)
- **구현 내용**
  1. 작업 대상 선택 → `claim`(임대 토큰) → Canvas 진입.
  2. 과제 유형별 분기: **분류**(이미지 전체 라벨), **객체 탐지**(BBOX/POLYGON), **이상 탐지**(정상/이상 판정 + 결함 POLYGON).
  3. Zoom·Pan, 라벨 클래스 팔레트, 단축키, 어노테이션 목록.
  4. `heartbeat`(임대 연장), `draft`(임시 저장), `submit`(제출 → `label_status=SUBMITTED`).
  5. 이탈 시 임대 해제. 만료 시 다른 작업자가 claim 가능.
  6. `@require_project_capability('label')`.
- **Dependency**: Task 2.4, 3.0, 3.4
- **API 변경**: `/api/data/labeling`
- **테스트**: 3유형 라벨링, 동시 claim 1명만 성공, heartbeat 중단 후 임대 만료·재claim, draft 복구, submit 후 상태 전이.
- **완료 조건**: Backbone §19 "각 화면의 핵심 기능이 동작한다" 충족.

---

### Task 3.7 — 검수 작업 화면 (`wm_data_review`)

- **Source**: AIDataHub `project/review/index.html`
- **Target**: `app/views/data/review.py` / `templates/data/review.html` + `app/static/data/review-page.js`
- **이식 방식**: **`REUSE_LOGIC`** + `REWRITE`
- **구현 내용**: 제출된 이미지 목록 → Canvas로 어노테이션 확인 → 승인(`APPROVED`) / 재작업(`REWORK` + 사유). `manager_only`(PROJECT_MANAGER만).
- **Dependency**: Task 2.4, 3.6
- **테스트**: 승인·재작업 상태 전이, WORKER 접근 시 403, 재작업된 이미지가 라벨링 대기열에 복귀.
- **완료 조건**: 화면 동작 + 권한 분기.

---

### Task 3.8 — 품질 점검 · 스냅샷 · Export 화면

- **Related Decisions**: DEC-022(A)
- **Source**: AIDataHub `project/snapshot/index.html` **1화면 → 3화면으로 분리**
- **Target**:
  - `wm_data_quality` — `app/views/data/quality.py` / `templates/data/quality.html`
  - `wm_data_snapshot` — `app/views/data/snapshot.py` / `templates/data/snapshot.html`
  - `wm_data_export` — `app/views/data/export.py` / `templates/data/export.html`
- **이식 방식**: `ADAPT`(품질·스냅샷) + `REUSE_LOGIC`(Exporter) + `REWRITE`(화면)
- **구현 내용**
  1. 품질 점검: 실행(202 + 폴링 1.5초×10회) → `readiness` + findings 목록(severity별). **검수 승인 이미지만 대상**.
  2. 스냅샷: 불변 `DatasetVersion` 생성(태그·manifest), 목록·상세.
  3. Export: 과제 유형별 지원 포맷만 노출 → 생성(202 + 폴링 3초×20회) → 다운로드(`files/data_export`). 실패 시 오류 메시지 표시.
  4. 폴링 한계 초과 시 "잠시 후 다시 확인해 주세요" 안내(원본 동작 유지).
- **Dependency**: Task 2.5, 2.6, 3.4
- **테스트**: 품질 점검 4종 결과, 스냅샷 불변성(수정 시도 거부), 8포맷 다운로드.
- **완료 조건**: 3화면 동작 + 8포맷 생성.

---

### Task 3.9 — 작업 대기열 · 활동 이력 화면

- **Source**: AIDataHub `home/index.html`을 2화면으로 분리
- **Target**:
  - `wm_data_queue` — `app/views/data/queue.py` / `templates/data/queue.html`
  - `wm_data_activity` — `app/views/data/activity.py` / `templates/data/activity.html`
- **이식 방식**: `ADAPT`
- **구현 내용**
  1. 작업 대기열: 내 담당 과제의 라벨링/검수 대기 건수, 바로 작업 시작 링크.
  2. 활동 이력: `ActivityLog` 목록·필터(과제·이벤트유형·행위자·기간) + 데이터 통계(과제별 이미지·라벨 상태 분포).
- **Dependency**: Task 3.6, 3.7
- **테스트**: 대기열 수치가 실제 데이터와 일치. 활동 로그가 주요 작업마다 기록.
- **완료 조건**: 2화면 동작.

---

### Task 3.10 — Phase 3 검증

- **구현 내용**: `SCREEN_MAPPING.md` §2 표의 12화면을 전수 진입·핵심 기능 확인. `verify_permission_map.py` PASS. 브라우저 콘솔 오류 0건.
- **완료 조건**: AIDataHub 업무 화면 **누락 0건**(Backbone §16 검증).

---

## Phase 4 — vision-inspection Model / Service 이식 (GPU Runtime 제외)

**목적**: 비전 검사 도메인의 모델·서비스를 **Django로 재작성**한다. AI Runtime은 제외한다.

**완료 기준**: 비전 도메인 모델 11개 정의, 서비스 단위 테스트 통과, `InferenceGateway` Stub 존재.

> **금지**: `torch`/`torchvision` import, `infrastructure/inference/*` 이관, `DetectionInferencePort`/`AnomalyInferencePort` 이관, 모델 아티팩트 load·검증(Backbone §9·§20-5).

---

### Task 4.1 — 비전 도메인 모델 이식

- **Related Decisions**: DEC-010(B), DEC-017(A), DEC-025(A), §1.5 O-2
- **Source**: `vision-inspection/server/src/.../infrastructure/database/models.py` (SQLAlchemy — **참조 전용**)
- **수정 대상**: `domain/models/vision.py`
- **구현 내용** — SQLAlchemy → Django ORM 재정의(11 → 10 테이블, `admin_users` 제외)

  | Django Model | 테이블 | 비고 |
  |---|---|---|
  | ~~`VisionProcess`~~ | — | **제외**(§1.6 O-8) |
  | ~~`VisionProduct`~~ | — | **제외**(§1.6 O-8) |
  | ~~`VisionInspectionItem`~~ | — | **제외** — `vision_data_item`(Task 2.2)에 통합(§1.6 O-8) |
  | `VisionOverlay` | `vision_overlay` | `item` FK unique → `vision_data_item`. **x/y/width/height 死컬럼 제거** |
  | `VisionClient` | `vision_client` | `client_id` unique, `api_key_hash` SHA-256 |
  | `VisionModel` | `vision_model` | 메타데이터 전용. `artifact_path`는 문자열 |
  | `VisionItemModelMapping` | `vision_item_model_mapping` | `model` FK + **`model_code`/`model_version` 비정규화** + **`threshold_override`** |
  | `VisionInspection` | `vision_inspection` | **`id`/`request_id`는 `CharField(36)`**(Client 계약). `item` FK → `vision_data_item`, **`image_asset` FK**(§1.6 Q3 — 파일 한 벌). `image_path` 컬럼 없음 |
  | ~~`VisionRetentionPolicy`~~ | — | **제외**(§1.6 O-10) |
  | ~~`VisionImageMigration`~~ | — | **제외**(§1.6 O-9) |

  - `TimestampMixin`(`created_at`/`updated_at`)을 MES `AbstractAuditModel`과 조화롭게 정의한다. 비전 테이블은 vision 원본 방식(`created_at`/`updated_at`)을 유지한다.
  - 검사 유형은 `vision_data_item.task_type`이 갖는다. 별도 `InspectionType` choices를 두지 않는다.
  - `VisionClient` 저장 시 **전용 Django 사용자 계정을 자동 생성**한다(§1.6 Q5). `set_unusable_password()`로 웹 로그인을 막고, 업로드·`ActivityLog`의 행위자로 쓴다.
- **Dependency**: Phase 3 (독립적으로 Phase 2와 병행 가능)
- **DB 변경**: **5개** 테이블 신설(`vision_overlay`, `vision_client`, `vision_model`, `vision_item_model_mapping`, `vision_inspection`)
- **테스트**: `manage.py check` 0건, 모델 임포트.
- **완료 조건**: 모델 정의 완료.

---

### Task 4.3 — 카탈로그 · Overlay 서비스 이식

- **Source**: `vision-inspection/server/.../application/services/{catalog,overlay}.py`
- **수정 대상**: `domain/services/vision/{catalog,overlay}.py`
- **이식 방식**: `ADAPT` (SQLAlchemy 조회 → Django ORM)
- **구현 내용**
  1. `CatalogService` — 검사항목 조회(활성만) + **고정 공정 1개·제품 1개 합성**(§1.6 O-11, `06_API_COMPATIBILITY_PLAN.md` §1.2 ②). 합성값은 상수이며 테이블로 만들지 않는다. **카탈로그 버전 해시 계산**(`REUSE_LOGIC` — 해시 산출 방식을 그대로 옮긴다. Client 캐시 무효화 기준).
     - `task_type` → `inspection_type` 사상: `OBJECT_DETECTION`→`DETECTION`, `ANOMALY_DETECTION`→`ANOMALY`.
     - **`CLASSIFICATION`·`DELETION_PENDING` 검사항목은 카탈로그에서 제외**(§1.6 O-14·Q9).
  2. `OverlayService` — **`REUSE_LOGIC`**: Overlay 등록·교체 시 `version` 증가, `opacity` 범위 검증(0.0~1.0), 이미지 형식·10MB 상한 검증. 위치·크기 필드는 제거된 상태로 유지.
  3. 정합성 검증 규칙: 검사항목 `status == ACTIVE` 확인만 한다. **공정·제품 일치 검증은 하지 않는다**(§1.6 O-11).
- **Dependency**: Task 4.1
- **테스트**: `tests/vision/test_catalog.py` — 비활성·분류·삭제대기 항목 제외, 합성 공정/제품이 항상 1건씩, 응답이 Client 파서(`processes[].products[].inspection_items[]`) 형태를 만족, 버전 해시가 변경 시에만 달라짐. `test_overlay.py` — 교체 시 version 증가.
- **완료 조건**: 단위 테스트 통과.

---

### Task 4.4 — Client 인증 · 관리 서비스 이식

- **Related Decisions**: DEC-007(A), DEC-018(A)
- **Source**: `.../application/services/{client_auth,client_admin}.py`, `infrastructure/security/api_key.py`
- **수정 대상**: `domain/services/vision/{client_auth,client_admin}.py`
- **이식 방식**: **`REUSE_LOGIC`**(해시·키 생성) + `ADAPT`
- **구현 내용**
  1. API Key 생성(충분한 엔트로피) + **SHA-256 해시 저장**. 평문은 발급 직후 1회만 노출.
  2. 인증: `X-Client-ID` + `X-API-Key` → 해시 비교 + `active` 확인 + `last_seen_at` 갱신.
  3. 실패 구분: 헤더 누락 `AUTH_REQUIRED`, 불일치/비활성 `AUTH_INVALID`(존재 여부 비노출).
  4. 인증 실패 로깅(vision `test_auth_failure_logging.py`가 검증하던 동작).
  5. Client별 rate limit(분당 기본 120, 0이면 무제한).
  6. **로그와 오류 메시지에 API Key를 남기지 않는다.**
- **Dependency**: Task 4.1
- **테스트**: `tests/vision/test_client_auth.py` — 누락/불일치/비활성 코드 구분, 해시 저장 확인, rate limit 429.
- **완료 조건**: 단위 테스트 통과.

---

### Task 4.5 — GPU Integration Boundary (Stub)

- **Related Decisions**: DEC-006(범위 밖), DEC-008(A 조정), DEC-015(설계만), §1.5 O-1, Backbone §10
- **목적**: GPU Server를 나중에 연결해도 Vision Domain을 다시 설계하지 않도록 경계만 정의한다.
- **수정 대상**: `domain/services/gpu/gateway.py`, `configurations/settings.py`
- **구현 내용**
  1. `InferenceGateway` — `is_configured()` / `infer(...)`. 기본 구현은 `GpuNotConfiguredError`(code `GPU_INFERENCE_NOT_CONFIGURED`) 발생.
  2. `InferenceResult` 데이터 클래스 — `abnormal`, `defects[]`, `anomaly_score`, `threshold`, `heatmap_bytes`, `model_code`, `model_version`, `elapsed_ms`.
  3. `GpuServerClient(InferenceGateway)` — **미구현 껍데기**. `06_API_COMPATIBILITY_PLAN.md` §2의 엔드포인트·헤더·타임아웃 상수만 정의하고 메서드는 `NotImplementedError`.
  4. 설정 키 `GPU_SERVER_BASE_URL`, `GPU_SERVICE_KEY`, `GPU_TIMEOUT_SEC=15`를 `.env.example`에 placeholder로 추가.
  5. 팩토리 `get_inference_gateway()` — 설정이 없으면 Stub 반환. **현재는 항상 Stub.**
  6. **HTTP 라이브러리를 의존성에 추가하지 않는다.**
- **Dependency**: Task 4.1
- **테스트**: `tests/vision/test_inference_gateway.py` — `is_configured()` False, `infer()`가 `GpuNotConfiguredError` 발생, 예외 code 값 확인.
- **완료 조건**: 경계 정의 완료. `grep -rn "import torch" .` 결과 0건.
- **Rollback**: 파일 삭제.

---

### Task 4.6 — 검사 수신 서비스 · 데이터 관리 연계

- **Related Decisions**: DEC-008(A 조정), DEC-019(A), **§1.6 O-9·O-11·O-12**
- **Source**: `.../application/services/{inspection,result_image,model_admin}.py` (참조 전용)
- **수정 대상**: `domain/services/vision/{inspection,result_image,model_admin}.py`
- **이식 방식**: `ADAPT` + `REUSE_LOGIC`(업무 규칙)
- **구현 내용**
  1. **`InspectionService.receive_capture()`** — `06_API_COMPATIBILITY_PLAN.md` §1.2 ③-1 순서를 그대로 구현.
     - idempotency(`request_id` unique) **먼저**, 검사항목 검증 **나중**(원본 순서 유지 — 검사항목 비활성 후 재전송 시 기존 결과 반환).
     - **`process_id`·`product_id`는 받되 검증하지 않는다**(§1.6 O-11). 원본의 "소속 제품/공정 일치" 검증(`inspection.py:85-92`)은 이식하지 않는다.
     - 이미지 decode 검증(Pillow) → **`ImageService.upload_images()` 호출** → `vision_inspection` 행 생성 commit.
     - 동시 요청 `IntegrityError` → rollback + 방금 만든 `ImageAsset` 정리 + 기존 행으로 응답(원본 동작 유지).
     - 활성 매핑 조회 → `InferenceGateway.infer()` → `GpuNotConfiguredError`면 `status='RECEIVED'`, `error_message='GPU_INFERENCE_NOT_CONFIGURED'`.
  2. **데이터 관리 연계**(§1.6 O-9) — 별도 서비스를 만들지 않고 Task 2.3의 `ImageService.upload_images()`를 그대로 부른다.
     - `actor` = Client 전용 계정, `requires_labeling=True` 고정.
     - **sha256 중복 차단을 Client 경로에서만 우회**한다(§1.6 Q4). 화면 업로드의 중복 차단은 건드리지 않는다 — `upload_images`에 `allow_duplicate` 인자를 더하고 기본값을 `False`로 둔다.
     - 고정 Tenant를 `tenant_atomic()`으로 설정한다. API Key 인증이라 미들웨어가 아니라 호출부 책임이다.
     - `ImageAsset.source_inspection_id`에 검사 id를 남긴다.
  3. `ResultImageService` — **현 단계에서는 결과가 없으므로 404 `RESULT_IMAGE_NOT_AVAILABLE`을 반환**한다. bbox 합성 로직은 GPU 연결 시 활성화할 수 있도록 함수 골격만 둔다(Pillow만 사용, torch 불필요).
  4. `ModelAdminService` — `VisionModel` CRUD(메타데이터). **아티팩트 파일 업로드·검증 없음**(§1.5 O-1).
  5. `RetentionService`·`MigrationService`는 **만들지 않는다**(§1.6 O-9·O-10).
- **Dependency**: Task 4.1, 4.3, 4.4, 4.5, Task 2.3(ImageService)
- **DB 변경**: 없음(Task 4.1에서 정의)
- **테스트**: `tests/vision/test_inspection_service.py` — idempotency, 검사항목 검증 순서, 동시 요청, GPU 미구성 시 `RECEIVED`, `process_id`/`product_id` 불일치를 거부하지 않음. `tests/integration/test_capture_ingest.py` — 검사 1건 접수 후 `ImageAsset`이 `UPLOADED`/`UNLABELED`로 생성되고 라벨링 작업 대상에 잡히는지, 동일 이미지 재전송 시 **중복 허용**되는지, 파일이 한 벌만 저장되는지.
- **완료 조건**: 단위·통합 테스트 통과.

---

## Phase 5 — vision-inspection 모든 Admin/Web 화면 이식

**목적**: `SCREEN_MAPPING.md` §3의 **비전 검사 관리 5화면**을 MES 패턴으로 구현한다.

**완료 기준**: 5화면 진입·동작. `verify_permission_map.py` PASS.

> **§1.6로 삭제된 화면** — Task 5.1(검사 공정·검사 대상 제품·검사 항목)과 Task 5.6(보존 정책·데이터셋 이관).
> 공정·제품은 만들지 않고(O-8), 검사항목 화면은 Task 3.x의 `wm_data_item` 하나로 통합됐으며(O-8·O-13),
> 보존 정책(O-10)과 이관 기능(O-9)은 범위에서 빠졌다. **Task 번호는 재부여하지 않는다** — 다른 문서의 상호참조를 깨지 않기 위해서다.

---

### Task 5.2 — Overlay 관리 화면 (`wm_vis_overlay`)

- **Source**: vision `inspection_items/overlay.html`
- **Target**: `app/views/vision/overlay.py` / `templates/vision/overlay.html`
- **이식 방식**: `ADAPT` (검사항목 하위 → **독립 메뉴 승격**)
- **구현 내용**: 검사항목별 Overlay 목록, 이미지 업로드(PNG/JPEG, 10MB), 미리보기, `visible`·`opacity` 설정, 삭제. 교체 시 `version` 증가. 이미지는 `files/vision_overlay` 권한 확인 View.
- **Dependency**: Task 4.3, 5.1
- **테스트**: 업로드·교체 시 version 증가, opacity 범위 검증, 10MB 초과 거부.
- **완료 조건**: 화면 동작 + Client Overlay API와 일치.

---

### Task 5.3 — 검사 Client 관리 화면 (`wm_vis_client`)

- **Source**: vision `clients/{list,form,created}.html`
- **Target**: `app/views/vision/client.py` / `templates/vision/client.html` + `page/vision/client_apikey.html`
- **이식 방식**: `REWRITE` + `ADAPT`(키 발급)
- **구현 내용**
  1. 목록: `client_id`·이름·활성·`last_seen_at`·최근 검사 건수.
  2. 등록: `client_id`·이름 → **API Key 1회 노출 모달**(재조회 불가 안내).
  3. API Key 재발급 / 활성·비활성 토글.
  4. **화면 어디에서도 API Key 평문을 다시 보여주지 않는다.**
- **Dependency**: Task 4.4
- **테스트**: 발급 후 재조회 불가, 재발급 시 기존 키 무효, 비활성 Client의 API 호출 401.
- **완료 조건**: 화면 동작 + 키 노출 규칙 준수.

---

### Task 5.4 — AI 모델 화면 (`wm_vis_model`) · 모델 매핑 화면 (`wm_sys_model_mapping`)

- **Related Decisions**: DEC-010(B), §1.5 O-2, Backbone §8
- **Source**: vision `models/{list,form}.html`, `inspection_items/model_mapping.html`
- **Target**: `app/views/vision/model.py` / `templates/vision/model.html` · `app/views/system/model_mapping.py` / `templates/system/model_mapping.html`
- **이식 방식**: `ADAPT` + 일부 `EXCLUDE_GPU_RUNTIME`
- **구현 내용**
  1. **AI 모델 화면**(비전 검사 관리): 목록·등록·수정·활성토글. 필드 `name`·`inspection_type`·`version`·`artifact_path`(문자열)·`runtime`·`threshold`·`active`.
     - **아티팩트 파일 업로드·검증 없음.** 화면에 "모델 파일은 GPU Server에서 관리합니다" 안내 표시.
     - Backbone §8의 "모델 목록·Metadata·버전·활성 상태 조회" 요구를 충족한다.
  2. **모델 매핑 화면**(시스템 관리): 검사항목 선택 → 활성 모델 지정. **검사항목당 활성 매핑 1개**, 기존 매핑은 `active=false`로 이력 보존.
     - **`threshold_override`** 입력(비우면 모델 기본값 사용).
     - 저장 시 `model_code`·`model_version`을 비정규화 컬럼에 함께 기록(장래 GPU 분리 대비).
     - 매핑 이력 목록 표시.
  3. 검사항목 화면(Task 5.1)에서 이 화면으로 바로가기.
- **Dependency**: Task 4.6, 5.1
- **테스트**: 활성 매핑 1개 제약, 이력 보존, `threshold_override` 반영, 비활성 모델 매핑 시 경고.
- **완료 조건**: 2화면 동작.

---

### Task 5.5 — 검사 결과/이력 화면 (`wm_vis_inspection`) · 검사 현황 (`wm_vis_dashboard`)

- **Source**: vision `inspections/{list,detail}.html`, `admin/filters.py`, `dashboard.html`
- **Target**: `app/views/vision/{inspection,dashboard}.py` / `templates/vision/{inspection,dashboard}.html`
- **이식 방식**: `REWRITE` + `REUSE_LOGIC`(bbox 렌더)
- **구현 내용**
  1. 검사 이력 목록(WeZonGrid) + 필터(기간·Client·공정/제품/검사항목·판정(`abnormal`)·상태(RECEIVED/SUCCESS/FAILED)).
  2. 상세: 판정·모델명/버전·`defects`·`anomaly_score`·`threshold`·`inference_ms`·capture 메타(`capture_timestamp`, `client_version`, `camera_*`)·오류 메시지.
  3. 원본 이미지 표시 + **bbox 오버레이 렌더**(`REUSE_LOGIC` — Canvas 좌표 변환 재사용). 결과 이미지·Heatmap은 현 단계에서 없으므로 "추론 미실행" 표시.
  4. 검사 기록 삭제.
  5. 검사 현황 대시보드: 기간별 검사 건수·이상률·상태 분포·Client별 최근 활동. **Backbone §17에 따라 이관 확정**.
  6. 이미지는 `files/vision_image` 권한 확인 View.
- **Dependency**: Task 4.6, 5.1
- **테스트**: 필터 조합, 상세 표시, 보존 정책으로 삭제된 이미지의 `IMAGE_EXPIRED` 표시.
- **완료 조건**: 2화면 동작.

---

### Task 5.7 — Phase 5 검증

- **구현 내용**: `SCREEN_MAPPING.md` §3 표의 10화면 전수 진입·핵심 기능 확인. `verify_permission_map.py` PASS.
- **완료 조건**: vision Admin 업무 화면 **누락 0건**(Backbone §16 검증).

---

## Phase 6 — VisionInspectionClient API 호환 계층

**목적**: Client가 **코드 변경 없이**(base_url만 변경) 동작하도록 `/api/v1/*` 6종을 계약 그대로 제공한다.

**완료 기준**: 실제 `VisionInspectionClient.exe`로 카탈로그 조회 → 검사 전송 → 재전송까지 동작.

> **`/api/v1/*`는 `ApiModuleView`를 거치지 않는다.** 전용 뷰 클래스 계층이며 MES 응답 규약을 쓰지 않는다(`06_API_COMPATIBILITY_PLAN.md` §0).

---

### Task 6.1 — `/api/v1` 기반 계층

- **Related Decisions**: DEC-007(A), DEC-014(A), DEC-016(B)
- **수정 대상**: `app/views/api_v1/__init__.py`, `configurations/urls.py`
- **구현 내용**
  1. `ApiV1BaseView(View)` — CSRF 면제, `X-Client-ID`/`X-API-Key` 인증(Task 4.4 서비스 사용), rate limit, `X-Request-ID` 전파.
  2. 응답 헬퍼 — `ok(data, status=200)` → `{"data": {...}}`, `err(code, message, retryable, status)` → `{"error":{...}}`.
  3. **UTC 직렬화 함수 `to_utc_z(dt)`** — `USE_TZ=False`(naive KST) → UTC `Z` 문자열. **변환 지점은 이 한 곳뿐**(DEC-016).
  4. 예외 → 오류 봉투 매핑(`06_API_COMPATIBILITY_PLAN.md` §1.5 표).
  5. Body size limit — 검사 이미지 10MB / Overlay 10MB. `Content-Length` 없으면 411, 초과 413.
  6. `urls.py`에 `/api/v1/...` 경로 등록. **MES PDA용 `api/v1/token/*` 4개는 이관하지 않는다**(Task 0.3에서 제거 완료).
- **Dependency**: Phase 4, Phase 5
- **API 변경**: `/api/v1/*` 신규
- **테스트**: `tests/api/test_client_auth.py`, `test_error_envelope.py`, `test_datetime_contract.py`.
- **완료 조건**: 인증·오류 봉투·UTC 규약 동작.

---

### Task 6.2 — Health · Catalog · Overlay 엔드포인트

- **수정 대상**: `app/views/api_v1/{health,catalog,overlay}.py`
- **구현 내용**
  1. `GET /api/v1/health` — 인증 불필요. `{"status","version","components":{"database","storage","gpu"}}`. **`gpu`는 항상 `"not_configured"`이며 `status`를 `error`로 만들지 않는다.**
  2. `GET /api/v1/catalog` — 통합 중첩 응답 + `version` 해시 + `overlay:{available,version}`. 활성 항목만.
  3. `GET /api/v1/catalog/version`, `/processes`, `/products`, `/inspection-items` — Client 미사용이나 계약상 제공.
  4. `GET /api/v1/overlays/{id}` — 메타. 없으면 404 `OVERLAY_NOT_FOUND`. **위치·크기 필드 없음.**
  5. `GET /api/v1/overlays/{id}/image` — PNG/JPEG, `Cache-Control: private, max-age=86400`, `?version=` 쿼리 수용.
- **Dependency**: Task 4.3, 6.1
- **테스트**: `tests/api/test_health.py`, `test_catalog.py`, `test_overlay.py`.
- **완료 조건**: 응답 구조가 `06_API_COMPATIBILITY_PLAN.md` §1.2와 일치.

---

### Task 6.3 — Inspection 엔드포인트

- **Related Decisions**: DEC-008(A 조정), §1.5 O-1
- **수정 대상**: `app/views/api_v1/inspections.py`
- **구현 내용**
  1. `POST /api/v1/inspections` — multipart(`image` + `metadata`). `InspectionService.receive_capture()` 호출.
     - metadata 길이 상한 검증(`request_id` 36 / `client_version` 50 / `camera.*` 100) → 위반 시 **422 `METADATA_INVALID`, 이미지 미저장**.
     - `client_id`는 받기만 하고 사용하지 않는다.
     - 응답은 현 단계에서 `status:"RECEIVED"`. **`error` 봉투를 쓰지 않는다**(Client retry 루프 방지).
  2. `GET /api/v1/inspections/by-request/{request_id}` — 같은 Client면 200, 다른 Client면 **409 `REQUEST_ID_CONFLICT`**, 없으면 404.
  3. `GET /api/v1/inspections/{id}` — 제공.
  4. `GET /api/v1/inspections/{id}/result-image` — **404 `RESULT_IMAGE_NOT_AVAILABLE`**(추론 미실행).
  5. `GET /api/v1/inspections/{id}/heatmap` — **404 `HEATMAP_NOT_FOUND`**.
  6. `GET /api/v1/history` — 제공.
  7. **응답의 모든 이미지 URL은 `/api/v1` 하위 상대경로**여야 한다(Client가 그 밖의 경로를 거부한다).
- **Dependency**: Task 4.6, 6.1
- **테스트**: `tests/api/test_inspection_submit.py`, `test_idempotency.py`, `test_image_url_prefix.py`, `test_rate_limit.py`.
- **완료 조건**: idempotency·409·422·RECEIVED 응답이 계약과 일치.

---

### Task 6.4 — 제외 엔드포인트 확인

- **Related Decisions**: DEC-024(A)
- **구현 내용**: `/api/v1/licenses/sources`, `/api/v1/client-packages`를 **구현하지 않는다.** Client가 호출하지 않음을 소스로 재확인하고, 배포물 제공 경로를 운영 문서에 기록한다(사내 파일서버 등).
- **테스트**: 해당 경로 404.
- **완료 조건**: 무인증 파일 제공 경로가 존재하지 않는다.

---

### Task 6.5 — 실제 Client 연동 확인

- **Related Decisions**: DEC-007(A)
- **구현 내용**
  1. `VisionInspectionClient`(`client/dist/` 또는 `deploy/` 배포본)의 설정에서 `base_url`을 ManufacturingAIPlatform으로 변경.
  2. Mock 카메라 어댑터로 실행 — 연결 테스트 → 카탈로그 수신 → 검사 항목 선택 → Overlay 표시 → 캡처 전송 → `RECEIVED` 결과 표시.
  3. 네트워크 차단 후 재연결 → retry 워커가 `by-request` 선조회 → 중복 저장 없음 확인.
  4. **Client 코드를 수정하지 않았음을 확인한다.**
- **Dependency**: Task 6.1~6.4
- **테스트**: 위 수동 시나리오. 결과를 `IMPLEMENTATION_STATUS.md`에 기록.
- **완료 조건**: Client 무변경으로 전 흐름 동작.
- **Rollback**: 계약 불일치 발견 시 해당 엔드포인트 Task로 복귀. **Client를 고치지 않는다.**

---

## Phase 7 — Menu / Permission 통합

**목적**: 모든 화면을 MES 메뉴·권한 체계에 등록하고 2단계 인가를 전면 적용한다.

**완료 기준**: 메뉴 트리 완성, 권한 부여/회수가 화면·API 양쪽에 반영.

---

### Task 7.1 — 메뉴 트리 구성

- **Related Decisions**: DEC-023(B), Backbone §13
- **수정 대상**: `domain/gui.py`, `domain/management/commands/seed_menu.py`
- **구현 내용**
  1. `GUI_ITEMS` 최종 확정 — 시스템관리 15 + 데이터관리 12 + 비전검사 10 = **37개**(+`wm_noauth_default`).
  2. `menu_folder` 3개(데이터관리 / 비전검사관리 / 시스템관리) + `menu_item` 37건을 `seed_menu`로 생성.
  3. `menu_item.Url`은 `/gui/<gui_code>/` 형식. `_order`로 `SCREEN_MAPPING.md` §1 순서를 재현.
  4. `sys_option.main_menu` 기본값을 `wm_data_queue`로 설정.
- **Dependency**: Phase 3, Phase 5
- **DB 변경**: `menu_folder`·`menu_item` 데이터
- **테스트**: `verify_menu.py` PASS(양방향 일치). 좌측 메뉴에 3그룹 37화면 표시.
- **완료 조건**: 메뉴에서 모든 화면에 도달한다.

---

### Task 7.2 — 권한 매핑 전수 등록

- **Related Decisions**: DEC-014(A)
- **수정 대상**: `domain/gui.py`(`apiPermissionMap`)
- **구현 내용**
  1. 신규 `task/view` 전부 등록 — `data/*`(15), `vision/*`(10), `system/model_mapping`, `files/*`(7).
  2. 화이트리스트 최종 확정 및 **주석으로 사유 기재**.
  3. `API_AUTHZ_MODE='enforce'` 확인.
- **Dependency**: Task 7.1
- **테스트**: `verify_permission_map.py` PASS(누락·고아 0건).
- **완료 조건**: 모든 API가 메뉴 권한 통제를 받는다.

---

### Task 7.3 — 2단계 인가 적용 점검

- **Related Decisions**: DEC-003(B), Backbone §14
- **구현 내용**
  1. `data/*` 뷰 전수에 `@require_project_capability` 적용 여부 확인.
  2. 시나리오 검증:
     ```text
     데이터셋 메뉴 접근 가능(1차)  →  해당 과제 접근 가능(2차)  →  Dataset 조회
     메뉴 권한 있음 + 과제 미배정   →  404 (과제 존재 비노출)
     메뉴 권한 없음                 →  403
     WORKER + 검수 화면             →  403 (manager_only)
     ```
  3. 메뉴 숨김이 인가 경계가 아님을 확인 — 메뉴에서 숨겨도 직접 URL·API 호출이 차단되어야 한다.
- **Dependency**: Task 7.2, Task 2.7
- **테스트**: `tests/permissions/` 전 시나리오.
- **완료 조건**: 위 4가지 시나리오 전부 기대대로 동작.

---

### Task 7.4 — 사용자그룹 기본 구성

- **구현 내용**: 기본 사용자그룹 4종과 메뉴권한 프리셋을 `seed_platform_base`에 정의.

  | 그룹 | 권한 범위 |
  |---|---|
  | `dev` | 전체 RW(우회) |
  | `admin` | 전체 RW |
  | `data_manager` | 데이터관리 RW + 비전검사 R |
  | `data_worker` | 데이터관리 중 라벨링·대기열 RW, 나머지 R |
  | `vision_manager` | 비전검사 RW + 데이터관리 R |

- **Dependency**: Task 7.2
- **테스트**: 각 그룹 계정으로 로그인해 메뉴·API 접근 범위 확인.
- **완료 조건**: 5개 그룹이 의도대로 동작.

---

## Phase 8 — DB Migration 및 Seed

**목적**: 신규 DB에 `0001_initial`을 적용하고 초기 데이터를 넣는다.

**완료 기준**: 빈 DB에서 `migrate` → `seed_*` → 전 화면 동작.

---

### Task 8.1 — `0001_initial` 생성

- **Related Decisions**: DEC-011(A), DEC-017(A), DEC-025(A)
- **수정 대상**: `domain/migrations/0001_initial.py`
- **구현 내용**
  1. `makemigrations domain` — 모델 전체.
  2. `05_DATABASE_MIGRATION_PLAN.md` §5의 **생성 순서**를 확인·조정한다(Vision 기준정보가 `vision_data_project.inspection_item` FK보다 먼저 와야 한다).
  3. `RunSQL`로 부분 unique index 추가 — 활성 매핑 1개, 과제-검사항목 1:1.
  4. `RunSQL`로 CheckConstraint 추가 — Tenant 단일 행, `retention_policy.id=1`.
  5. **`migrate --fake`/`--fake-initial`을 사용하지 않는다.**
- **Dependency**: Phase 7
- **DB 변경**: 전체 스키마 생성
- **테스트**: 빈 DB에 `migrate` 성공. `makemigrations --check --dry-run` → No changes.
- **완료 조건**: 빈 DB에서 스키마가 완성된다.
- **Rollback**: DB DROP 후 재생성(기존 3개 DB는 무관).

---

### Task 8.2 — RLS 정책 적용

- **Related Decisions**: DEC-004(B)
- **수정 대상**: `0001_initial.py`(RunSQL), `scripts/verify_rls.py`
- **구현 내용**
  1. `TENANT_TABLES` 19개에 RLS 활성화 + `vision_data_<t>_tenant_scope` 정책 생성.
  2. 애플리케이션 DB 사용자가 `BYPASSRLS` 권한을 갖지 않도록 확인.
  3. `verify_rls.py`로 정책 존재·동작 검증.
- **Dependency**: Task 8.1
- **테스트**: `verify_rls.py` PASS. `tenant_atomic` 밖에서 테넌트 테이블 조회 시 0행.
- **완료 조건**: RLS 19테이블 적용.

---

### Task 8.3 — Seed 명령 구현

- **수정 대상**: `domain/management/commands/{seed_platform_base,seed_menu,seed_vision_catalog,seed_demo_data}.py`
- **구현 내용**: `05_DATABASE_MIGRATION_PLAN.md` §6 참조. 모든 seed는 **멱등**으로 작성한다(재실행 안전).
  - `seed_platform_base` — Tenant 1행(고정 UUID), 사용자그룹 5종 + 메뉴권한 프리셋, 관리자 계정(비밀번호는 실행 시 입력), `sys_option`.
  - `seed_menu` — `menu_folder`/`menu_item`. `--check` 옵션으로 `gui.py`와 양방향 대조.
  - `seed_vision_catalog` — vision `cli.py seed-catalog` 이식.
  - `seed_demo_data` — 개발용 과제·데이터셋·이미지(선택).
- **Dependency**: Task 8.1
- **테스트**: 빈 DB에서 순서대로 실행 후 로그인·메뉴 표시.
- **완료 조건**: 4개 명령 동작 + 멱등.

---

### Task 8.4 — 운영 데이터 이관 판정 (조건부)

- **Related Decisions**: DEC-012(A 조건부), §1.5 O-6
- **구현 내용**
  1. `05_DATABASE_MIGRATION_PLAN.md` §7의 **확인 쿼리를 사용자 승인 후 실행**한다(읽기 전용).
  2. 판정: `vision_data_annotation`이 수천 건 이상이면 이관, 데모 수준이면 미이관.
  3. **이관으로 판정되면** §7의 T1~T7 절차를 Task 8.5로 추가하고, **사용자 승인을 다시 받는다**(운영 데이터를 다루므로).
  4. 미이관이면 Seed로 진행하고 그 사실을 기록한다.
- **Dependency**: Task 8.3
- **테스트**: 쿼리 결과를 `IMPLEMENTATION_STATUS.md`에 기록.
- **완료 조건**: 판정 결과가 문서에 남는다.

---

### Task 8.5 — (조건부) 데이터 이관 실행

- **선행 조건**: Task 8.4에서 "이관" 판정 + **사용자 명시 승인**
- **구현 내용**: `05_DATABASE_MIGRATION_PLAN.md` §7 T1~T7. 각 단계 전 `pg_dump` 스냅샷. **파일은 이동이 아니라 복사.**
- **테스트**: §8 V1~V10 전 항목.
- **완료 조건**: 검증 10항목 통과.
- **Rollback**: 스냅샷 복원. 신규 DB만 영향받으므로 기존 시스템은 무관.

---

## Phase 9 — 통합 기능 검증

**목적**: `SCREEN_MAPPING.md`를 근거로 **기능 누락이 없는지** 전수 확인한다(Backbone §16·§19).

---

### Task 9.1 — MES Backbone 회귀 확인

- **구현 내용**: 로그인(정상/실패/잠금), 사용자 CRUD, 사용자그룹 CRUD, 메뉴 관리, 권한 부여·회수, 공통코드·단위·업체·부서 CRUD, 공통 Layout(탭·모달·그리드·즐겨찾기), 로그 3종.
- **완료 조건**: Backbone §19 "MES Backbone" 7항목 전부 동작.

---

### Task 9.2 — 데이터 관리 전수 확인

- **구현 내용**: `SCREEN_MAPPING.md` §2의 12화면 × 핵심 기능. 특히:
  - 과제 생성 → 라벨 클래스 등록 → 이미지 업로드 → 정제 → 라벨링(3유형) → 검수 → 품질점검 → 스냅샷 → Export 8포맷 다운로드까지 **한 바퀴**.
- **완료 조건**: Backbone §19 "AIDataHub" 조건 충족 — 기존 화면 전부 접근 가능 + 핵심 기능 동작.

---

### Task 9.3 — 비전 검사 관리 전수 확인

- **구현 내용**: `SCREEN_MAPPING.md` §3의 10화면 × 핵심 기능. 특히:
  - 공정 → 제품 → 검사항목 → Overlay → 모델 등록 → 매핑(+threshold override) → Client 등록/키 발급 → 검사 수신 → 이력 조회 → 보존 정책 → 데이터셋 이관까지 **한 바퀴**.
- **완료 조건**: Backbone §19 "Vision Inspection" 조건 충족.

---

### Task 9.4 — GPU 경계 확인

- **Related Decisions**: §1.5 O-1
- **구현 내용**
  1. `grep -rn "import torch\|torchvision\|patchcore\|DetectionInferencePort\|AnomalyInferencePort" .` → **0건**.
  2. `requirements.txt`에 torch 계열 없음.
  3. 매핑된 검사항목으로 검사 요청 시 `status='RECEIVED'` + `error_message='GPU_INFERENCE_NOT_CONFIGURED'`.
  4. `InferenceGateway` 인터페이스가 정의되어 있고 `GpuServerClient` 껍데기가 존재.
  5. `ai/`·`ml/`·`gpu/`·`inference/` Django App 없음.
- **완료 조건**: Backbone §19 "GPU" 조건 충족 — 추론 미구현 + Boundary 정의됨.

---

### Task 9.5 — 미사용 자산 정리

- **구현 내용**: Phase 0에서 미뤘던 `app/static/` 정리. 실제 참조되지 않는 MES 벤더 자산·이미지·언어 리소스를 제거한다. **제거 전에 템플릿 전수 grep으로 참조 여부를 확인한다.**
- **완료 조건**: 정적 자산 크기 감소 + 화면 깨짐 0건.
- **Rollback**: `git revert`.

---

## Phase 10 — 신규 Test 작성

**목적**: ManufacturingAIPlatform 최종 아키텍처를 기준으로 테스트를 **새로 작성**한다(Backbone §2).

> 기존 3개 프로젝트의 테스트는 이관하지 않는다. 참고 자료로만 읽는다.

**디렉터리**

```text
tests/
├── system/        MES Backbone · 사용자 · 권한 · 메뉴 · 공통코드 · 로그인 하드닝
├── data/          데이터 도메인 서비스 · Export · 어노테이션 기하 · 라벨링 작업
├── vision/        비전 도메인 서비스 · 카탈로그 · Overlay · Client 인증 · 검사 수신
├── api/           /api/v1 Contract Test (06 문서 §1.7)
├── permissions/   2단계 인가 (메뉴 권한 + 과제 권한)
├── integration/   백그라운드 워커 · 데이터셋 이관 · 파일 저장소
└── e2e/           브라우저 시나리오
```

---

### Task 10.1 — 테스트 기반 구축

- **구현 내용**: `configurations/test_settings.py` 확정(SQLite, RLS 비활성, 임시 `STORAGE_ROOT`), 공통 픽스처(`tests/support.py` — 사용자·그룹·권한·과제·데이터셋·검사항목 생성 헬퍼), **`PYTHONUTF8=1` 및 파일 읽기 시 encoding 명시 규칙**을 테스트 가이드에 기록.
- **완료 조건**: `manage.py test tests --settings=configurations.test_settings` 실행 가능.

---

### Task 10.2 — `tests/system/`

- 로그인 성공·실패·잠금·해제, 세션 DB 재확인(계정 비활성화 시 즉시 거부)
- 사용자/그룹/메뉴권한 CRUD, `user_profile` 자동 생성 시그널
- 공통코드·단위·업체·부서 CRUD
- 로그 기록(login_log·menu_use_log·sys_log)

### Task 10.3 — `tests/data/`

- 이미지 업로드(중복 sha256 차단), 썸네일, 정제(원본 보존)
- 어노테이션 기하(BBOX/POLYGON 좌표 검증, 범위 밖 거부)
- 라벨링 작업(동시 claim 1명, 임대 만료, draft 복구, submit 전이)
- 검수(승인/재작업 전이)
- 품질 점검 4종, 스냅샷 불변성
- Export 8포맷 산출물 구조 + 과제 유형별 포맷 제한

### Task 10.4 — `tests/vision/`

- 카탈로그 중첩 구조·활성 필터·버전 해시 변화
- Overlay 교체 시 version 증가, opacity 범위, 크기 상한
- Client 인증(누락/불일치/비활성 구분), API Key 해시 저장, rate limit
- 검사 수신(idempotency, 카탈로그 검증 순서, 동시 요청, GPU 미구성 시 RECEIVED)
- 모델 매핑(활성 1개 제약, 이력 보존, threshold override)
- `InferenceGateway` Stub 동작

### Task 10.5 — `tests/api/`

`06_API_COMPATIBILITY_PLAN.md` §1.7의 10개 파일을 작성한다.

### Task 10.6 — `tests/permissions/`

- 메뉴 권한 없는 사용자의 화면 403 / API 403
- 매핑 없는 `task/view` 403(enforce 모드)
- 과제 미배정 시 404, `manager_only` 403
- capability 미등록 작업 403
- **메뉴 숨김만으로는 차단되지 않음을 확인**(직접 URL·API 호출 테스트)

### Task 10.7 — `tests/integration/`

- 워커 2개 동시 실행 시 중복 claim 0건
- 작업 실패 → 재시도 스케줄 → 3회 후 FAILED 확정
- 검사 이미지 → 데이터셋 이관(batch, 재실행 이어하기, 클래스명 불일치 경고)
- 파일 저장소(경로 탈출 차단, 권한 없는 접근 403, 보존 정책 정리)

**Phase 10 완료 조건**: 전 테스트 통과. 실패 시 **테스트를 통과시키려고 아키텍처를 바꾸지 않는다** — 원인이 구현 결함이면 구현을 고치고, 테스트 기대가 틀렸으면 테스트를 고친다.

---

## Phase 11 — E2E / Regression Test

**목적**: 실제 브라우저와 실제 Client로 전 흐름을 검증한다.

---

### Task 11.1 — 브라우저 E2E 시나리오

- **구현 내용**: Playwright 기반 `tests/e2e/`. 콘솔 오류도 수집한다.
  1. 로그인 → 메뉴 탐색 → 로그아웃
  2. 과제 생성 → 라벨 클래스 등록 → 이미지 업로드 → 정제 → 라벨링(탐지) → 검수 승인 → 품질점검 → 스냅샷 → Export 다운로드
  3. 분류 과제 라벨링 / 이상탐지 과제 라벨링
  4. 검사 기준정보 등록(공정→제품→검사항목) → Overlay 등록 → 모델 등록 → 매핑
  5. 검사 이력 조회·필터·상세
  6. 데이터셋 이관 실행 → 이미지가 데이터 관리에 나타남
- **완료 조건**: 6개 시나리오 통과, 콘솔 오류 0건.

---

### Task 11.2 — Client E2E

- **구현 내용**: Task 6.5 시나리오를 정식 회귀 항목으로 고정.
  ```text
  Client 실행 → 연결 테스트 → 카탈로그 수신 → 검사항목 선택 → Overlay 표시
  → 캡처 전송 → RECEIVED 결과 표시 → 네트워크 차단 → 재연결 → 중복 없음 확인
  ```
- **완료 조건**: 전 단계 동작 + Client 무변경.

---

### Task 11.3 — 회귀 세트 확정

- **구현 내용**: Phase 9의 수동 점검 항목을 체크리스트로 문서화(`docs/REGRESSION_CHECKLIST.md`). 자동화 가능한 것은 Phase 10·11 테스트로 편입.
- **완료 조건**: 회귀 체크리스트 존재.

---

### Task 11.4 — 배포 리허설

- **Related Decisions**: DEC-020(A)
- **구현 내용**
  1. Ubuntu 24.04 스테이징에 배포 — nginx + gunicorn + systemd(app / worker / purge timer).
  2. `collectstatic` 여부 결정(MES는 `STATIC_ROOT` 사용, AIDataHub는 미사용 — **MES 방식 유지**).
  3. HTTPS 종단 구성 후 `HTTPS_ENABLED=1`로 HSTS·Secure 쿠키 확인.
  4. `check --deploy` 경고 목록을 판정표로 정리.
  5. 빈 DB → `migrate` → `seed_*` → 전 화면 확인(Phase 9 축약본).
- **완료 조건**: 스테이징에서 전 기능 동작.
- **Rollback**: 이전 릴리스 태그로 복귀.

---

### Task 11.5 — 최종 완료 판정

- **구현 내용**: Backbone §19 완료 조건 전수 확인.

  | 영역 | 조건 | 확인 |
  |---|---|---|
  | MES Backbone | 로그인·사용자·사용자그룹·메뉴·권한·기준정보·공통 Layout | Task 9.1 |
  | AIDataHub | 기존 대상 화면 전부 접근 가능 + 핵심 기능 동작 | Task 9.2, `SCREEN_MAPPING.md` §2 |
  | Vision Inspection | 기존 Admin 대상 화면 전부 접근 가능 + Client API 제공 | Task 9.3, 11.2 |
  | GPU | 추론 미구현 + Boundary/Interface 정의됨 | Task 9.4 |
  | Test | 신규 작성 테스트 통과(기존 테스트 통과 여부는 조건 아님) | Phase 10, 11 |

- **완료 조건**: 5개 영역 전부 충족.

---

## 부록 A — 위험과 대응

| # | 위험 | 영향 | 대응 |
|---|---|---|---|
| R1 | Phase 0 대량 삭제 중 잔존 import로 부팅 실패 | Phase 0 지연 | 영역별 커밋 분리, 삭제 후 즉시 `check` |
| R2 | 인가 훅 적용 시 화면 무더기 403 | Phase 1·7 지연 | `API_AUTHZ_MODE` 3단계(off/warn/enforce), 경고 모드로 누락 수집 후 전환 |
| R3 | Canvas JS를 SPA에서 분리할 때 동작 상실 | Phase 3 핵심 기능 손상 | Task 3.0에서 정적 하네스로 먼저 검증. **원본 로직을 고치지 않고 감싼다** |
| R4 | MES raw SQL의 naive datetime과 `/api/v1` UTC 변환 불일치 | 시각 오차 9시간 | 변환 지점을 `to_utc_z()` 한 곳으로 제한(Task 6.1). `tests/api/test_datetime_contract.py` |
| R5 | Client 계약 미세 불일치로 현장 Client 동작 실패 | Phase 6 실패 | `06_API_COMPATIBILITY_PLAN.md`를 계약 정본으로 삼고 Contract Test 10종 + Task 6.5 실기기 확인 |
| R6 | 이미지 URL prefix 변경으로 Client가 이미지 거부 | Overlay 표시 실패 | `test_image_url_prefix.py`로 전 응답 검사 |
| R7 | RLS 유지로 인한 조회 성능 저하 | 목록 화면 지연 | 인덱스가 `tenant` 선두로 이미 설계됨. 문제 시 인덱스 조정(RLS를 끄지 않는다) |
| R8 | 단일 Tenant 행이 실수로 여러 개 생성 | 데이터 분리 사고 | CheckConstraint로 원천 차단(Task 2.1) |
| R9 | 운영 데이터 이관 판정이 늦어 Phase 8 지연 | 일정 | Task 8.4 이전에 N1 확인을 선행 요청 |
| R10 | 테스트가 없는 MES 기능의 회귀 | 발견 지연 | Phase 1·9의 수동 회귀 + Phase 10 `tests/system/` 신규 작성 |
| R11 | 모델 관리 화면이 아티팩트 없이 반쪽 기능 | 사용자 혼란 | 화면에 "모델 파일은 GPU Server에서 관리" 안내 명시(Task 5.4). `USER_DECISIONS.md` §1.5 O-7 확인 요청 |
| R12 | Phase 2~5 병행 시 모델 정의 충돌 | 마이그레이션 오류 | Phase 8까지 마이그레이션을 만들지 않는다(모델 정의만). Task 4.2로 연결 시점을 명시 |

---

## 부록 B — 선행 확인 요청 (사용자)

| # | 항목 | 필요 Phase | 미확인 시 영향 |
|---|---|---|---|
| N1 | 세 DB의 운영 데이터 규모(`05` 문서 §7 쿼리) | Phase 8 (Task 8.4) | 이관 여부 판정 불가 |
| N4 | NCP 대상 OS 확정 | Phase 11 (Task 11.4) | 배포 리허설 불가 |
| N5 | 현장 Client 설치 대수 · 재배포 가능 여부 | Phase 6 (Task 6.5) | 호환 전략의 위험도 평가 불가 |
| N12 | vision `config/.env` 실제 값(경로·DB) | Phase 8 (이관 시) | 파일 이관 원본 위치 불명 |
| — | MES 운영 DB(`yest`) 읽기 접속 허용 여부 | Phase 0 (Task 0.8) | Task 0.8을 축소 실행 |
| — | §1.5 O-7 — 모델 아티팩트 업로드를 이번 범위에 포함할지 | Phase 5 (Task 5.4) | 현재 계획은 **미포함**으로 진행 |

---

## 부록 C — `IMPLEMENTATION_STATUS.md` 양식

Phase 0 시작과 동시에 생성해 Task마다 갱신한다.

```markdown
# 제조AI플랫폼 구현 진행 상태

## 현재 Phase
- Phase:
- Task:
- 상태:

## Task 현황

| Task ID | Decision ID | 상태 | 변경 파일 | 검증 | 비고 |
|---|---|---|---|---|---|

상태: TODO / IN_PROGRESS / BLOCKED / DONE / ROLLED_BACK

## 새로 발생한 의사결정
- 없으면 "없음". 발생 시 USER_DECISIONS.md에 DEC 추가하고 구현 중지

## 검증 결과
- check:
- makemigrations --check:
- tests:
- verify_permission_map:
- verify_menu:
- verify_rls:
- 수동 회귀:
```

---

## 부록 D — Task ↔ Decision 역참조

| Decision | 관련 Task |
|---|---|
| DEC-001 | 0.1 |
| DEC-002 | 1.4, 8.1 |
| DEC-003 | 2.7, 3.1, 3.7, 7.3, 10.6 |
| DEC-004 | 2.1, 8.2 |
| DEC-005 | 2.2, 3.1, 4.2, 5.6 |
| DEC-006 / O-1 | 4.5, 9.4 |
| DEC-007 | 4.4, 6.1~6.5, 10.5, 11.2 |
| DEC-008 | 4.6, 6.3 |
| DEC-009 | 0.3, 5.4 |
| DEC-010 / O-2 | 4.1, 5.4 |
| DEC-011 | 0.2, 8.1 |
| DEC-012 / O-6 | 8.4, 8.5 |
| DEC-013 | 0.5, 3.0, 3.6, 3.7 |
| DEC-014 | 1.1, 1.5, 7.2, 7.3, 10.6 |
| DEC-015 | 4.5 |
| DEC-016 | 0.2, 6.1 |
| DEC-017 | 0.2, 4.1, 8.1 |
| DEC-018 | 1.2, 5.3 |
| DEC-019 | 0.6, 3.4, 5.2, 5.5 |
| DEC-020 | 0.2, 11.4 |
| DEC-021 | 1.3 |
| DEC-022 | 2.6, 3.8, 5.6, 10.7 |
| DEC-023 | 0.3, 1.3, 7.1 |
| DEC-024 | 6.4 |
| DEC-025 | 4.1, 8.1 |
| DEC-026 | 4.6, 5.6, 10.7 |
| DEC-027 | 4.5, 9.4 |
| O-3 (테스트 미이관) | Phase 10 전체 |
| O-4 (화면 미제외) | 5.5, 5.6, 9.2, 9.3 |
| O-5 (Phase 0~11) | 전체 |
