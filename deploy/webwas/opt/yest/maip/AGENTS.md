# 제조AI플랫폼 — 코드를 고치기 전에 읽는다

제조 현장의 **비전 검사**, **AI 학습데이터 관리**, **디지털 입력 전환**(검사양식·작성·결과)을 하나로 처리하는 Django 프로젝트다.

이 문서는 **규칙**만 적는다. 설명은 [docs/](docs/README.md) 에 있다.

| 알고 싶은 것 | 문서 |
|---|---|
| 구조·API 규약·인가·RLS·고칠 때 보는 곳 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 메뉴·역할·화면별 기능 | [docs/FEATURES.md](docs/FEATURES.md) |
| 테이블·마이그레이션·시드 | [docs/DATA_MODEL.md](docs/DATA_MODEL.md) |
| 개발 환경·테스트·검증 스크립트·**개발 함정** | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| 브랜치·push·마이그레이션 전달·공유 개발 DB 규칙 | [docs/SOURCE_CONTROL.md](docs/SOURCE_CONTROL.md) |
| 배포·운영 | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| 디자인 규칙(색·글꼴·컴포넌트·모달·문구)·화면 추가/수정 체크리스트 | [DESIGN.md](DESIGN.md) |
| **왜 이렇게 만들었나 — 결정의 정본** | [docs/DECISIONS.md](docs/DECISIONS.md). 다른 문서와 충돌하면 이것이 이긴다 |
| 지금 상태·남은 일 | [docs/STATUS.md](docs/STATUS.md) |

## [1] 구성

근거: DECISIONS O-1.

| 항목 | 값 |
|---|---|
| 언어/프레임워크 | Python 3.12 / Django 5.2 LTS(5.2.18) |
| DB | PostgreSQL 16 (`search_path: public`) |
| 운영 | Rocky Linux 9.6 + gunicorn + nginx + systemd (프로세스 **2개**: 웹 `maip`·워커 `maip-worker`) |
| 화면 | Django Template + jQuery + Bootstrap 5 + WeZonGrid(자체 그리드) |

`requirements.txt` 가 실제 의존성이다. **WEB 서버에 `torch` 를 설치하지 않는다**.

## [2] API 규약 (의도된 설계)

근거: DECISIONS DEC-024, DEC-029, DEC-C2.

| 경로 | 규약 | 호출자 | 인가 |
|---|---|---|---|
| `/api/<task>/<view>` | MES 동적 dispatch | MES 계열 화면 | `gui.py` `taskview_menu_code_map()` → `ApiModuleView.dispatch` 훅 |
| `/api/item/<view>` | MES 동적 dispatch(`item` task) | 데이터 관리 화면 | `gui.py` 매핑 + 모듈의 `load_item`(그 조직의 비전검사항목인지). 규약은 `app/views/item/__init__.py` |
| `/api/v1/...` | **비전검사 API** | **비전검사 클라이언트**(별도 프로젝트) | `X-Client-ID` + `X-API-Key` |
| `/api/v1/datasets/...` | **학습 플랫폼 스냅샷 API** | **Wezard**(별도 플랫폼) | `X-API-Key` 하나(`maip_…`, `IntegrationClient`). 공통 규약 `docs/Wezard/integration-protocol.md` |

- **`/api/v1` 은 클라이언트와의 계약이다.** 응답 모양·오류 코드·경로·메시지를 바꾸면
  **docs/client/SERVER_API_CONTRACT.md 를 함께 고친다**
  (§15 처리 결과·§17 변경 이력). 그 문서가 정본이고 서버가 관리한다. 알리지 않고 바꾸면 현장 검사가 멈춘다
- **`/api/v1/datasets` 는 Wezard 와의 계약이다.** 응답·오류 코드·경로를 바꾸면 **docs/Wezard/maip-api.md 를 함께 고친다**
- `/api/v1` 라우트는 `urls.py` 의 `api/v1/<path:rest>` catch-all **앞**에 넣는다. 뒤에 두면 catch-all 이 받아 404 `NOT_FOUND` 봉투가 나간다
- 배포물 이름 `VisionInspectionClient` 는 바꾸지 않는다 — zip 파일명·`SHA256SUMS.txt` 항목·`client-packages` 응답 값이다
- `licenses/sources`·`client-packages` 4경로는 **의도적으로 인증이 없다**(LGPL 대응). 인증을 걸지 않는다
- 데이터 화면의 새 API 는 `/api/item/<view>` 에 둔다. `READ_ACTIONS` 에 조회 action 만 적는다 — 빠진 action 은 POST 로만 받는다

## [3] 인가는 메뉴 권한이다

근거: DECISIONS DEC-003·사용자 결정 2026-10-21(메뉴 권한만), 사용자 결정 2026-10-19(`capture` 예외).

메뉴 권한(`UserGroupMenu`) 하나다. 비전검사항목은 모두 보이고(삭제 승인 대기는 플랫폼 관리자만), 할 수 있는 일은 그 화면 메뉴의 R·W 가 정한다.
비전검사항목 등록·수정·삭제 승인(`item/item_admin`)과 라벨 문구 수정은 플랫폼 관리자(superuser·그룹 `dev`·`admin`)만 한다.
`API_AUTHZ_MODE=enforce` 에서 **매핑이 없는 API 경로는 즉시 403** 이다. 화면이나 API 를 더하면
`domain/gui.py` 에 매핑도 등록한다 — `scripts/verify/verify_permission_map.py` 가 잡는다.
화면이 **다른 메뉴의 API** 를 부르면 그 메뉴 권한이 없는 그룹에서 403 이 난다. 자기 메뉴의 API 에 필요한 액션을 둔다
(데이터 화면은 `app/views/item/<화면>.py` 하나가 그 화면의 조회를 모두 갖는다).
변경 action 은 그 메뉴의 **W** 를 요구한다. 다른 화면이 미리 알아야 하는 판단(버튼 노출 등)은 `ItemAccessService.can_write(user, 메뉴)` 로 본다.
예외: 디지털 양식의 비전 연결 이미지 칸에 사진을 넣는 것(`capture`)은 데이터 목록 W 없이 그 구분의 검사작성 W 로 비전 데이터 이미지를 만든다.

## [4] 지켜야 할 것

근거: DECISIONS DEC-004(RLS), DEC-019(파일 제공), 사용자 결정 2026-10-21(메뉴로 열 수 없는 화면).

**마이그레이션은 Django 로만 관리한다.** `migrate --fake`, `--fake-initial`, `django_migrations`
직접 수정은 **금지**다. `domain/_sql/i18n/` 은 다국어 시드 SQL 이고 스키마와 무관하다.

**RLS 를 우회하거나 제거하지 않는다.** 데이터 관리 테이블 14개에 `FORCE ROW LEVEL SECURITY` 가
걸려 있다(목록은 DATA_MODEL §6). `tenant_atomic()` **밖에서 읽으면 예외 없이 0건**이다 —
조회가 비면 먼저 테넌트 컨텍스트를 의심한다. 사용자 삭제도 `tenant_atomic()` 안에서 한다.

**파일을 공개 경로로 제공하지 않는다.** 이미지·업로드 원본은 권한을 확인하는 View 로만 내려준다.
`MEDIA_URL` 을 두지 않는다. 새 파일 필드는 `app/views/files/media.py` 방식으로 내고, 응답은
`sendfile()` 로 만든다(운영은 nginx 가 전송 — `FILE_ACCEL_REDIRECT`).

**사용자·Client 값은 화면에 글자로 넣는다.** `.text()`·`$('<option>').text()` 를 쓰고, 값을 문자열로 이어 `.html()`·`innerHTML`
로 넣지 않는다. 파일명·라벨 이름·Client 메타데이터로 스크립트가 실행됐다.

**메뉴로 열 수 없는 화면을 두지 않는다.** 화면은 좌측 메뉴 항목이거나 메뉴 화면 안의 탭이다. 다른 화면의 버튼·링크로만
열리는 화면은 두지 않는다(팝업·모달, 메뉴에서 내린 화면 제외).

**비밀은 소스·커밋·로그·오류 메시지에 넣지 않는다.** API Key·비밀번호·토큰 전부다.
설정은 `.env` 로 읽고 `.env` 는 커밋하지 않는다. 새 키를 더하면 `.env.example` 에 placeholder 를 추가한다.

**`X_FRAME_OPTIONS = 'SAMEORIGIN'` 을 `DENY` 로 바꾸지 않는다.** 화면을 iframe 탭으로 띄우는 셸이다.
`check --deploy` 의 `W019` 경고는 의도된 것이다.

**제품 이름은 제조AI플랫폼 하나다.** 기능을 가져온 원본 저장소 이름
(`AIDataHub` · `vision-inspection`)은 소스와 현행 문서에서 쓰지 않는다 — `scripts/verify/verify_naming.py` 가
지킨다(`docs/` 아래 하위 폴더는 보지 않는다). 금지 대상이 **아닌** 것: 테이블 `vision_inspection`·모듈
`vision/inspection`, 배포물 이름 `VisionInspectionClient`, 공유 PostgreSQL 설명에 나오는 다른 프로젝트의
DB 이름(`plant_i`·`vision_user`·`aidatahub` 등).

**동기 Ajax 를 쓰지 않는다.** 조회는 `AjaxUtil.getAsyncData`, 변경은 `postAsyncData` 다.

**사용자에게 보이는 문구는 `~합니다` 체로 쓴다**(`~해 주세요` 포함. `~하세요`·`~할까요?` 는 대상이 아니라 그대로 둔다). 알림·확인창·API 응답 메시지·
검증 오류·화면 안내가 대상이고 로그·주석·docstring 은 아니다. `/api/v1` 메시지를 바꿀 때는 계약 문서도 고친다.

**HTTP 상태줄(`HttpResponse(reason=...)`)에 한글을 넣지 않는다.** latin-1 만 되어 응답이 끊긴다.
사유는 본문의 `message` 로 보낸다.

**테스트는 `--settings=configurations.test_settings` 로 돌린다.** 빼면 운영 PostgreSQL 에 테스트 DB 가
생긴다. 그 설정은 저장소 경로(`STORAGE_ROOT`·`MEDIA_ROOT` 등)도 임시 폴더로 돌린다 — 경로 설정을 더하면
거기에도 다시 지정한다.

**e2e 는 실제 DB 에 쓴다.** `E2E-`·`e2e-` 로 시작하는 자기 데이터만 만들고 `finally`·픽스처로 지운다.
seed 데이터를 바꾸면 같은 테스트 안에서 되돌린다. **요청이 나가면 안 되는 것**을 보는 테스트는 쓰기 요청을
`page.route` 로 끊는다. 자세한 것은 docs/DEVELOPMENT.md 에 있다.

**개발 `.env` 는 `DB_CONN_MAX_AGE=0` 으로 둔다**(예시 파일·운영 gunicorn 은 60). 이 PostgreSQL 은 다른 프로젝트와
공유한다 — 테스트가 이유 없이 흔들리면 코드보다 커넥션 수를 먼저 본다.

**커밋 메시지는 Conventional Commits 다.** type 은 영문, 설명은 한국어로 무엇을 왜 바꿨는지 쓴다(예: `feat: 수입검사 자재입고 검색 팝업에 입고 목록을 붙인다`).
병합 커밋은 `Merge: <무엇을>` 이다.

**커밋·소스에 AI 모델·도구가 작업했다는 표시를 넣지 않는다.** 커밋 메시지의 `Co-Authored-By: Claude …`·`Generated with …` 같은
서명 줄, 모델·도구 이름, 그런 내용을 담은 코드 주석이 대상이다. 에이전트 기본 설정이 붙이라고 해도 이 규칙이 이긴다.
이미 push 한 이력은 고쳐 쓰지 않는다.

**push 전에 최신 main 을 받아 합치고 고친 범위의 테스트를 돌린다.** 로컬 브랜치에서 작업하고 main 에 합쳐 push 한다.
force push 와 이미 push 한 이력을 고쳐 쓰는 일은 하지 않는다.

**공유 개발 DB 에 `migrate`·`seed_initial`·`seed_dig_form`·`seed_vision_items`·`seed_demo` 를 돌리지 않는다.** 개발 DB 는 팀이 같이 쓴다.
적용은 담당자 몫이다 — 담당자가 직접 지시한 경우에만 돌리고, 돌린 결과(지운 메뉴·권한 등 출력)를 보고한다.
모델을 바꾸면 `makemigrations` 만 하고 모델과 마이그레이션 파일만 담은 `migration/<이름>` 브랜치를 push 해 담당자에게 알린다.
모델·마이그레이션 변경을 main 에 직접 push 하지 않는다.
절차는 docs/SOURCE_CONTROL.md 에 있다.

**문서는 `docs/` 의 현행 문서에 쓴다.** 새 문서를 만들지 않고, 같은 내용을 두 곳에 쓰지 않는다.
진행 중인 구현 계획·설계만 `docs/superpowers/plans`·`specs` 에 두고, 구현이 끝나면 `docs/archive/superpowers/` 로 옮긴다.
`docs/archive/` 는 고치지 않는다 — 비밀이 들어 있으면 그 값만 가린다.

## [5] 실행과 검증

```bash
python manage.py migrate
python manage.py seed_initial --admin-password '<비밀번호>'
python manage.py seed_vision_items              # 검사 분류와 NEOCON C2 비전검사항목·라벨 클래스·측정점. 운영 포함, 멱등(없는 것만)
python manage.py seed_dig_form                  # 고객 양식(디지털 양식)·비전 연결·분류 매핑. seed_vision_items 다음. 운영 포함, 멱등
python manage.py seed_demo                      # 개발 전용 표본
python manage.py runserver                      # 기본 127.0.0.1:8123. 다른 PC 에서 열려면 0.0.0.0:8123
python manage.py run_worker                     # 별도 터미널 — 스냅샷 Export(zip)
./scripts/maipctl.py start|stop|status|restart [web|worker]   # 위 둘을 백그라운드로 띄우고 끈다(운영은 systemd)
```

각 스크립트가 무엇을 잡는지는 docs/DEVELOPMENT.md 에 있다.

**테스트는 고친 범위만 돌린다. 전체 실행은 사용자 승인을 받는다.**

- 단위 테스트는 고친 코드를 다루는 테스트 모듈만 돌린다(`manage.py test tests.test_snapshot_job tests.test_item_api … --settings=configurations.test_settings`)
- e2e 는 고친 화면·API 를 지나는 파일만 돌린다(`pytest tests/e2e/test_write_paths.py`, 좁힐 수 있으면 `-k`).
  템플릿·화면 JS·CSS·화면이 부르는 API 를 고치지 않았으면 e2e 는 돌리지 않는다
- 정적 검증 스크립트는 몇 초라 돌린다. `verify_modals`·`verify_buttons` 는 화면을 고쳤을 때만, `verify_dig_form_width` 는 디지털 전환 화면을 고쳤을 때만 돌린다
- **전체 단위(`manage.py test tests`)·전체 e2e(`pytest tests/e2e`, 약 15분)는 먼저 묻는다.** 왜 전체가 필요한지
  (공용 코드를 고쳐 영향 범위를 좁힐 수 없다 등)·예상 시간을 말하고 승인받은 뒤 돌린다. 병합 전이라는 이유만으로 돌리지 않는다
- 전체를 제안할 만한 변경: 미들웨어·settings·마이그레이션·권한(`gui.py`·`app/views/item/__init__.py`·`domain/services/data/authorization.py`·`item_access.py`)·공용 JS/CSS·레이아웃 템플릿
- 보고에는 돌린 테스트와 돌리지 않은 테스트를 나눠 적는다

```bash
python manage.py test tests --settings=configurations.test_settings
python -m pytest tests/e2e -q                    # 서버가 떠 있어야 한다. 실제 DB 를 쓴다
node scripts/verify/verify_screen_js.js
python scripts/verify/verify_menu.py
python scripts/verify/verify_permission_map.py
python scripts/verify/verify_response_keys.py
python scripts/verify/verify_tokens.py
python scripts/verify/verify_modals.py                  # 서버 필요
python scripts/verify/verify_buttons.py                 # 서버 필요
python scripts/verify/verify_dig_form_width.py          # 서버 필요. 디지털 전환 화면 1024 폭
python scripts/verify/verify_korean_only.py
python scripts/verify/verify_links.py
python scripts/verify/verify_naming.py
```

CSS 를 고쳤으면 레이아웃이 움직이지 않았는지도 본다(`scripts/verify/verify_layout_stable.py`, 절차는 DEVELOPMENT §4).

시스템 로그는 `LOG_DIR`(비우면 `STORAGE_ROOT/logs`)의 `app-YYYY-MM-DD.log` 다. 화면의 "시스템 로그"(DB)는
한 줄뿐이고 트레이스는 이 파일에 있다.

## [6] 아직 아닌 것

현황·제약은 docs/STATUS.md 에 있다.
