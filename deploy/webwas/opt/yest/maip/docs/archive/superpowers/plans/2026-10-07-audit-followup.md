# 배포 전 점검 후속(결정 11건 + 정리 8건) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 배포 전 점검에서 남은 보통·낮음 항목과 그 주변 정리를, 사용자가 정한 선택지대로 고친다.

**Architecture:** 항목마다 작은 작업 하나로 나누고, 각 작업은 실패하는 테스트로 시작해 커밋 하나로 끝난다. 화면 동작이 바뀌는 것(라벨링 대기열 페이징·임시 비밀번호 창·엑셀 지연 로드)은 e2e 로, 서버 동작은 단위 테스트로 고정한다. 정적 파일은 whitenoise Manifest 저장소로 바꾸고 템플릿의 `/static/...?v=` 를 `{% static %}` 으로 옮긴다.

**Tech Stack:** Django 5.2.18 · PostgreSQL 16 · whitenoise 6.9 · jQuery 3.7 · Bootstrap 5.3 · WeZonGrid · Playwright

**Spec:** 사용자 결정(2026-10-07) — "6. B안으로, 나머지는 추천안대로". 결정 목록과 추천안은 이 대화의 "바로 할 수 있는 작업 중 의사결정" 정리, 점검 결과는 [2026-10-07-predeploy-audit.md](../../../superpowers/plans/2026-10-07-predeploy-audit.md)

## 결정 (이 계획의 요구사항)

| # | 결정 | 작업 |
|---|---|---|
| 1 | `DEBUG` 기본값 False | T1 |
| 2 | 세션 유휴 만료 8시간, 로그아웃은 GET 유지, 로그 실패 시 로그아웃 결함 수정 | T1 |
| 3 | 검사 결과/이력은 지금대로 모든 검사항목 — DECISIONS 에 기록 | T15 |
| 4 | `docs/archive` 원본 MES 비밀번호 한 줄 마스킹 + 원본 MES 담당에 교체 확인 요청(사용자) | T2 |
| 5 | **B** — gzip 압축 + Manifest(해시 파일명·긴 캐시) + 템플릿 `{% static %}` 전환 + 미사용 JS 제거 + xlsx 지연 로드. brotli 는 넣지 않는다 | T3·T4 |
| 6 | **B** — 라벨링 대기열 서버 페이징 지금 구현 | T5 |
| 7 | DB 로그 보존: 시스템로그 90일, 로그인·메뉴 로그 365일, 워커가 하루 한 번 지운다 | T6 |
| 8 | 사용자 등록 임시 비밀번호를 등록 직후 창으로 한 번 보여 준다(복사 버튼) | T7 |
| 9 | `requirements-dev.txt` 신설, 운영 requirements 에서 `requests`·`urllib3`·`numpy`·`qrcode`·`six` 제거 | T8 |
| 10 | `attach_file` 테이블 삭제 보류, `wm_company` 품목단가 탭만 제거, `ax5ui`·`dropzone`·`component.fileupload.js` 는 실사용 확인 후 삭제 | T9 |
| 11 | PostgreSQL 통합 테스트: DBA 가 `maip_test` 를 만들고 `--keepdb` 로 재사용 | T14 |
| — | 결정 없이: Export 임시 파일(T10), jquery-validation 1.22.1(T11), 이미지 캐시 헤더(T12), 검사항목 관리 N+1(T13), `search_company`·`TenantAccessService.require` 삭제(T9), 무효 설정 정리(T1) | |

## Global Constraints

- 테스트는 `--settings=configurations.test_settings`. e2e 는 `E2E-`·`e2e-` 데이터만 만들고 지운다
- 마이그레이션은 Django 로만. `--fake`·`django_migrations` 직접 수정 금지. 이 계획은 마이그레이션을 만들지 않는다
- 사용자 문구는 `~합니다` 체. 화면에 사용자·Client 값은 `.text()` 로 넣는다(AGENTS [4])
- `/api/v1` 응답은 바꾸지 않는다(이 계획은 `/api/v1` 을 건드리지 않는다)
- 새 패키지를 들이지 않는다(Brotli 포함). `requirements-dev.txt` 는 기존에 쓰던 개발 도구를 옮기는 것이다
- 커밋은 작업마다 하나, 한국어 Conventional Commits. 브랜치 `fix/audit-followup` 에서 하고 끝나면 main 에 병합(push 안 함)
- 정적 JS·CSS 를 고친 작업은 T3 이전이면 `?v=` 를 올린다(T3 이후에는 Manifest 가 해시로 대신한다)

---

### Task 1: 설정·세션·로그아웃 (결정 1·2, 무효 설정 정리)

**Files:**
- Modify: `configurations/settings.py`(DEBUG 기본값, 세션, `SECURE_BROWSER_XSS_FILTER`·`USE_L10N`·`django.contrib.admin` 제거)
- Modify: `app/views/account.py:96-126`(`AccountLogoutView.get`)
- Modify: `.env.example`(DEBUG 설명)
- Test: `tests/test_login.py`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_login.py LoginTest 에 추가
    def test_로그인_기록이_실패해도_로그아웃된다(self):
        from unittest.mock import patch
        self._post()
        with patch('app.views.account.LoginLog.objects.create', side_effect=RuntimeError('db down')):
            self.client.get('/logout/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_세션은_8시간_쓰지_않으면_끝난다(self):
        from django.conf import settings
        self.assertEqual(settings.SESSION_COOKIE_AGE, 8 * 3600)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)   # 요청마다 만료를 미룬다 = 유휴 만료


class SettingsDefaultTest(TestCase):
    def test_DEBUG_기본값은_False(self):
        import importlib, os
        from unittest.mock import patch
        from configurations import env as env_module
        with patch.dict(os.environ, {'DEBUG': '', 'ALLOWED_HOSTS': 'x', 'SECRET_KEY': 'k' * 50}), \
             patch.object(env_module, 'load_dotenv', lambda *a, **k: None):
            import configurations.settings as base
            reloaded = importlib.reload(base)
        self.assertFalse(reloaded.DEBUG)
        importlib.reload(base)   # 다른 테스트를 위해 원래대로
```

`env_bool('DEBUG', ...)` 가 빈 문자열을 어떻게 다루는지 `configurations/env.py` 를 먼저 읽고, 빈 값이 기본값으로 가지 않으면 `os.environ.pop('DEBUG')` 로 바꾼다.

- [ ] **Step 2: 실패 확인** — `.venv/bin/python manage.py test tests.test_login --settings=configurations.test_settings` → 3건 FAIL
- [ ] **Step 3: 구현**

```python
# configurations/settings.py
DEBUG = env_bool('DEBUG', False)   # 개발 PC 는 .env 에 DEBUG=True. 빠뜨린 운영이 DEBUG 로 뜨지 않게 기본은 False

# 세션 / 보안
# 유휴 8시간이면 끝난다(한 근무조). 브라우저를 닫아도 끝난다(account.py set_expiry(0)).
# ponytail: 요청마다 세션 행을 다시 쓴다. 쓰기가 부담되면 N 분마다만 저장하는 미들웨어로 바꾼다.
SESSION_COOKIE_AGE = 8 * 3600
SESSION_SAVE_EVERY_REQUEST = True
```

같은 파일에서 `SECURE_BROWSER_XSS_FILTER = True`(Django 4.0 부터 무효), `USE_L10N = True`(5.0 부터 무효), `INSTALLED_APPS` 의 `'django.contrib.admin'`(URL·참조 없음 — `grep -rn "contrib.admin\|admin.site" app domain configurations` 0건 확인) 을 지운다.

```python
# app/views/account.py AccountLogoutView.get — logout 을 기록 try 밖으로
        if user.is_anonymous:
            return render(request, login_page, data)
        try:
            LoginLog.objects.create(
                Type='logout', User=user, Username=user.username,
                IPAddress=login_throttle.client_address(request),
                UserAgent=request.META.get('HTTP_USER_AGENT', '')[:300])
        except Exception as ex:
            LogWriter.add_dblog('error', 'AccountLogoutView get loginlog.save', ex)
        # 기록이 실패해도 로그아웃은 한다(배포 전 점검 #16)
        logout(request)
        return render(request, login_page, data)
```

`.env.example` 의 `DEBUG=True` 위에 `# 비우면 False(운영). 개발 PC 만 True.` 를 단다. 개발 서버의 `.env` 는 이미 `DEBUG=True` 다(확인함).

- [ ] **Step 4: 통과 확인** — 단위 전체 `OK`, `manage.py check` 이상 없음, 운영값 `check --deploy` 가 `W019` 하나
- [ ] **Step 5: 커밋** — `fix: DEBUG 기본값을 끄고 세션 유휴 만료 8시간, 로그아웃 결함을 고친다`

---

### Task 2: `docs/archive` 원본 MES 비밀번호 마스킹 (결정 4)

**Files:** Modify `docs/archive/01_CURRENT_STATE_ANALYSIS.md:232`, `AGENTS.md`(archive 예외 한 줄)

- [ ] **Step 1:** 232행의 원본 MES DB 비밀번호 값을 `****` 로 바꾸고, `SECRET_KEY='cc69427f-...'` 는 그대로(이미 잘림) 둔다
- [ ] **Step 2:** 원래 값으로 `git grep` 해서 0건
- [ ] **Step 3:** AGENTS [4] "문서는..." 단락의 "`docs/archive/` 는 고치지 않는다" 뒤에 "— 비밀이 들어 있으면 그 값만 가린다" 를 붙인다
- [ ] **Step 4: 커밋** — `docs: archive 문서의 원본 MES DB 비밀번호를 가린다`
- [ ] **Step 5: 사용자 몫(보고에 포함)** — 원본 MES 담당에게 보낼 문구: "제조AI플랫폼 저장소 이력에 원본 MES 운영 DB 비밀번호(`yest` 계정)가 평문으로 남아 있었습니다. 지금도 그 값을 쓰고 있다면 교체를 부탁드립니다." git 이력은 다시 쓰지 않는다

---

### Task 3: 정적 파일 Manifest·gzip·`{% static %}` 전환 (결정 5 B)

**Files:**
- Create: `configurations/storage.py`
- Modify: `configurations/settings.py`(STORAGES, WHITENOISE_*)
- Modify: `/static/` 를 직접 쓰는 모든 템플릿 — 목록은 `grep -rln '"/static/' app/templates`
- Modify: `docs/DEVELOPMENT.md` §5.19(수동 `?v=` → Manifest), `docs/DEPLOYMENT.md`(collectstatic 이 해시본·gzip 을 만든다)
- Test: `tests/test_static_storage.py`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_static_storage.py
"""정적 파일은 해시 이름·gzip 으로 나가고, 템플릿은 /static/ 을 직접 쓰지 않는다(배포 전 점검 #10)."""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATES = pathlib.Path(settings.BASE_DIR) / 'app' / 'templates'


class StaticStorageTest(SimpleTestCase):
    def test_운영_저장소는_해시_이름과_압축본을_만든다(self):
        self.assertEqual(settings.STORAGES['staticfiles']['BACKEND'], 'configurations.storage.StaticStorage')

    def test_템플릿은_static_경로를_직접_쓰지_않는다(self):
        offenders = []
        for path in TEMPLATES.rglob('*.html'):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if re.search(r'''(src|href)=["']/static/''', line):
                    offenders.append(f'{path.relative_to(TEMPLATES)}:{number}')
        self.assertEqual(offenders, [])
```

- [ ] **Step 2: 실패 확인** — 2건 FAIL(두 번째는 위반 목록이 나온다 — 그것이 고칠 범위다)
- [ ] **Step 3: 저장소**

```python
# configurations/storage.py
"""정적 파일 저장소 — 해시 이름(긴 캐시) + gzip. collectstatic 이 만든다.

벤더 CSS 가 가리키는 파일 중 배포본에 없는 것(쓰지 않는 글꼴·이미지)이 있어 엄격 모드면 collectstatic 이 멈춘다.
없는 파일은 해시하지 않고 원래 이름으로 둔다 — 그 참조는 지금도 404 다.
"""
from whitenoise.storage import CompressedManifestStaticFilesStorage


class StaticStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False

    def hashed_name(self, name, content=None, filename=None):
        try:
            return super().hashed_name(name, content, filename)
        except ValueError:
            return name
```

```python
# configurations/settings.py (STATIC_ROOT 아래)
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'configurations.storage.StaticStorage'},
}
# 해시 이름 파일은 whitenoise 가 1년 immutable 로 낸다. 해시가 없는 파일(JS 가 문자열로 만든 경로)만 이 값.
WHITENOISE_MAX_AGE = 3600
```

`configurations/test_settings.py` 에 `STORAGES = {..., 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}` 를 둔다(테스트는 collectstatic 없이 템플릿을 그린다). 첫 번째 테스트는 `configurations.settings` 모듈 값을 직접 읽도록 `from configurations import settings as base` 로 바꾼다.

- [ ] **Step 4: 템플릿 전환** — 각 파일 맨 위에 `{% load static %}` 이 없으면 더하고, `src="/static/X?v=..."` → `src="{% static 'X' %}"`(쿼리 `?v=` 는 지운다). `layout_page.html`·`index.html`·`login_mes.html` 이 대부분이다. JS 가 문자열로 정적 경로를 만드는 곳은 `grep -rn "'/static/" app/templates app/static/assets/js` 로 찾아 목록만 남긴다(Manifest 밖이라 `WHITENOISE_MAX_AGE` 를 받는다)
- [ ] **Step 5: collectstatic 확인** — `DEBUG=False ALLOWED_HOSTS=127.0.0.1 SECRET_KEY=x .venv/bin/python manage.py collectstatic --noinput` 성공, `static/staticfiles.json` 생성, `static/assets/js/common.*.js.gz` 존재. 끝나면 `static/` 은 사용자가 지운다(훅이 `rm -rf` 를 막는다 — 지난번과 같다)
- [ ] **Step 6: gunicorn 실측**(8002, DEBUG=False, 점검 Task 9 Step 3 과 같은 명령) — `curl -sI -H 'Accept-Encoding: gzip' <해시된 common.js 경로>` 에 `Content-Encoding: gzip`, `Cache-Control: max-age=315360000, public, immutable`. 로그인 화면·셸·데이터 목록이 깨지지 않는다(콘솔 오류 0). 끝나면 gunicorn 종료
- [ ] **Step 7: 통과 확인** — 단위 전체, `verify_screen_js`·`verify_links`·`verify_tokens`, e2e `test_menu`·`test_workflow`(개발 서버는 DEBUG=True 라 해시 없이 그대로 나간다)
- [ ] **Step 8: 문서** — DEVELOPMENT §5.19 를 "정적 파일은 `{% static %}` 으로 싣는다. 해시 이름은 collectstatic(운영)이 붙이므로 `?v=` 를 쓰지 않는다" 로 고친다. DEPLOYMENT §4 의 collectstatic 줄에 "해시본·gzip 을 만든다"
- [ ] **Step 9: 커밋** — `perf: 정적 파일을 해시 이름·gzip 으로 내고 템플릿을 {% static %} 으로 옮긴다`

---

### Task 4: 셸 미사용 JS 제거 + xlsx 지연 로드 (결정 5)

**Files:**
- Modify: `app/templates/app/index.html:13,237-242`(jsvectormap CSS·apexcharts·jsvectormap·world 맵 제거), `app/templates/app/layout_page.html:12`(jsvectormap CSS), `:68-69`(xlsx `<script>` 제거, URL 만 남김)
- Modify: `app/static/assets/js/grid.js`(`GridUtil.exportExcel`, `exportAll`)
- Modify: 엑셀 호출 7곳 — `definition/unit.html:231`·`definition/code_info.html:384`·`system/user.html:565`·`definition/depart.html:219`·`system/multi_language.html:256,343`·`definition/company.html:1072`
- Test: `tests/e2e/test_grid_common.py`(기존 엑셀 테스트 + 새 테스트)

- [ ] **Step 1: 실패하는 e2e**

```python
# tests/e2e/test_grid_common.py 에 추가
def test_엑셀_라이브러리는_엑셀을_누를_때만_싣는다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    loaded = []
    page.on('request', lambda r: loaded.append(r.url) if 'xlsx' in r.url or 'apexcharts' in r.url or 'jsvectormap' in r.url else None)
    page.goto(f'{base_url}/gui/wm_user/', wait_until='networkidle')
    assert loaded == [], loaded
    with page.expect_download():
        page.evaluate("() => GridUtil.exportExcel(page.grid, { fileName: 'e2e-users.xlsx' })")
    assert any('xlsx' in url for url in loaded)
```

(`page.grid` 이름은 `system/user.html` 에서 확인한다. 셸(`/`)에서도 apexcharts·jsvectormap 요청이 0 인지 같은 방식으로 본다.)

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**

```html
<!-- layout_page.html: <script src=xlsx> 대신 -->
<script>window.XLSX_URL = "{% static 'assets/vendor/xlsx/xlsx.full.min.js' %}";</script>
```

```javascript
// grid.js GridUtil 안
    // SheetJS(0.9MB)는 엑셀을 누를 때 한 번만 싣는다(배포 전 점검 #10). 화면마다 싣던 것을 뺐다.
    _xlsxPromise: null,
    loadXlsx() {
        if (window.XLSX) return Promise.resolve();
        if (!this._xlsxPromise) {
            this._xlsxPromise = new Promise(function (resolve, reject) {
                const script = document.createElement('script');
                script.src = window.XLSX_URL;
                script.onload = function () { resolve(); };
                script.onerror = function () { GridUtil._xlsxPromise = null; reject(new Error('엑셀 라이브러리를 불러오지 못했습니다.')); };
                document.head.appendChild(script);
            });
        }
        return this._xlsxPromise;
    },
    exportExcel(grid, options) {
        return this.loadXlsx().then(function () { grid.exportToExcel(options); })
            .catch(function (error) { Alert.alert('', error.message); });
    },
```

`exportAll` 의 `temp.exportToExcel({ fileName })` 를 `GridUtil.exportExcel(temp, { fileName })` 로, 7곳의 `X.exportToExcel({...})` 를 `GridUtil.exportExcel(X, {...})` 로 바꾼다. T3 이전에 하면 `grid.js?v=` 를 올린다.

- [ ] **Step 4: 통과 확인** — 새 테스트 + 기존 `test_grid_common` 엑셀 테스트(내용 검증) 통과, `verify_screen_js` PASS
- [ ] **Step 5: 커밋** — `perf: 셸이 쓰지 않는 차트·지도 JS 를 빼고 엑셀 라이브러리는 누를 때 싣는다`

---

### Task 5: 라벨링 대기열 서버 페이징 (결정 6 B)

**Files:**
- Modify: `app/views/item/labeling.py:53-80`(`_queue`)
- Modify: `app/templates/data/labeling.html`(대기열 패널 페이저, `loadQueue`, `updatePosition`, `moveNext`, `submitTask`, `searchMainData`)
- Modify: `app/static/data/main.css`(페이저 한 줄)
- Test: `tests/test_item_api.py` `LabelingApiTest`, `tests/e2e/test_data_screens.py`

**Interfaces:**
- Produces: `GET /api/item/labeling?action=queue&item_id=&page=&page_size=&image_id=` →
  `{item, actor_id, labels, images: [작업할 것만, id 오름차순], page, page_size, totalRows, counts: {total, complete, remaining}, requested: payload|null}`
  - 작업할 것 = `label_status` 가 `UNLABELED`·`IN_PROGRESS`·`REWORK`(화면 `visibleImages()` 와 같다)
  - `page_size` 기본 50, 1~200 으로 자른다. `totalRows == counts.remaining`
  - `requested`: `image_id` 가 이 페이지에 없으면 그 한 장(상태 무관), 있으면 null
- 정렬을 `id` 오름차순(먼저 들어온 것부터)으로 바꾼다 — 지금의 "최근 수정 순"은 작업을 시작·저장할 때마다 행이 페이지를 옮겨 다닌다

- [ ] **Step 1: 실패하는 단위 테스트**

```python
# LabelingApiTest 에 추가
    def _queue(self, **params):
        return self.http(self.worker).get('/api/item/labeling', {'action': 'queue', 'item_id': self.item.id, **params}, **AJAX).json()

    def test_대기열은_작업할_이미지만_페이지로_준다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image(f'q{i}.png', color=(i * 20, 9, 9)) for i in range(4)], actor=self.worker)
            done = ImageAsset.objects.for_tenant(self.tenant).order_by('id').last()
            ImageAsset.objects.for_tenant(self.tenant).filter(id=done.id).update(label_status=ImageAsset.LabelStatus.SUBMITTED)
        first = self._queue(page=1, page_size=2)
        self.assertEqual((first['page'], first['page_size'], first['totalRows']), (1, 2, 4))
        self.assertEqual(first['counts'], {'total': 5, 'complete': 1, 'remaining': 4})
        ids = [i['id'] for i in first['images']] + [i['id'] for i in self._queue(page=2, page_size=2)['images']]
        self.assertEqual(ids, sorted(ids))
        self.assertNotIn(done.id, ids)
        self.assertEqual(len(ids), 4)

    def test_페이지_밖의_이미지를_요청하면_따로_준다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('r.png', color=(1, 99, 9))], actor=self.worker)
            last = ImageAsset.objects.for_tenant(self.tenant).order_by('id').last()
        body = self._queue(page=1, page_size=1, image_id=last.id)
        self.assertEqual([i['id'] for i in body['images']], [self.image.id])
        self.assertEqual(body['requested']['id'], last.id)
        self.assertIsNone(self._queue(page=1, page_size=1, image_id=self.image.id)['requested'])
```

기존 `test_대기열_쿼리_수는_이미지_수와_무관하다` 는 그대로 통과해야 한다(페이지 크기 안에서 일정).

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 서버**

```python
# app/views/item/labeling.py
from django.db.models import Count, Q

QUEUE_PAGE_SIZE = 50
WORK_STATUSES = [ImageAsset.LabelStatus.UNLABELED, ImageAsset.LabelStatus.IN_PROGRESS, ImageAsset.LabelStatus.REWORK]
DONE_STATUSES = [ImageAsset.LabelStatus.SUBMITTED, ImageAsset.LabelStatus.APPROVED]


def _int(context, key, default, low, high):
    try:
        return min(max(int(param(context, key, default)), low), high)
    except (TypeError, ValueError):
        return default


def _queue(context):
    item = load_item(context, 'item.read')
    tenant, user = context.request.tenant, context.request.user
    page = _int(context, 'page', 1, 1, 10 ** 6)
    size = _int(context, 'page_size', QUEUE_PAGE_SIZE, 1, 200)
    snapshot_ids = {}
    can_manage = ItemAccessService.can_manage_item(user=user, tenant=tenant, item=item)

    def payload(image):
        if image.dataset_id not in snapshot_ids:
            snapshot_ids[image.dataset_id] = ImageService.snapshot_image_ids(image.dataset)
        return ImageListService.detail_payload(image, user, snapshot_ids=snapshot_ids[image.dataset_id],
                                               can_manage=can_manage)

    counts = (ImageAsset.objects.for_tenant(tenant).filter(dataset__item=item)
              .aggregate(total=Count('id'), complete=Count('id', filter=Q(label_status__in=DONE_STATUSES)),
                         remaining=Count('id', filter=Q(label_status__in=WORK_STATUSES))))
    # 관계는 한 번에 붙여 읽는다(쿼리 수가 이미지 수와 무관 — 배포 전 점검 #7).
    images = (ImageListService.query(tenant, item).filter(label_status__in=WORK_STATUSES).order_by('id')
              .select_related('dataset__item').prefetch_related(*image_prefetches()))
    rows = list(images[(page - 1) * size: page * size])
    requested = None
    image_id = param(context, 'image_id', '')
    if image_id and str(image_id) not in {str(row.id) for row in rows}:
        found = (ImageListService.query(tenant, item).filter(id=image_id)
                 .select_related('dataset__item').prefetch_related(*image_prefetches()).first())
        requested = payload(found) if found else None
    return {
        'item': {'id': item.id, 'name': item.name, 'task_type': item.task_type},
        'actor_id': user.id,
        'labels': list(LabelClass.objects.for_tenant(tenant).filter(item=item)
                       .values('id', 'display_name_ko', 'color', 'annotation_shape')),
        'images': [payload(image) for image in rows],
        'page': page, 'page_size': size, 'totalRows': counts['remaining'], 'counts': counts,
        'requested': requested,
    }
```

`image_id` 가 숫자가 아니면 `filter(id=...)` 가 ValueError 를 낸다 — `str(image_id).isdigit()` 일 때만 찾는다.

- [ ] **Step 4: 단위 통과 확인**
- [ ] **Step 5: 실패하는 e2e**

```python
# tests/e2e/test_data_screens.py 에 추가 — item 픽스처에 3장을 올리고 한 페이지 2장으로 본다
def test_라벨링_대기열은_페이지로_나누고_다음_작업이_다음_페이지로_넘어간다(page, base_url, item, tmp_path):
    from PIL import Image
    paths = []
    for index in range(3):
        path = tmp_path / f'e2e-q{index}.png'
        Image.new('RGB', (64, 48), (index * 60, 30, 30)).save(path)
        paths.append(str(path))
    goto(page, base_url, f"wm_data_image/?project={item['id']}")
    page.get_by_role('button', name='데이터 추가').click()
    page.set_input_files('#imageFiles', paths)
    send(page, lambda: page.click('#startUpload'))
    page.wait_for_selector('#uploadModal', state='hidden', timeout=15000)
    goto(page, base_url, f"wm_data_labeling/?project={item['id']}")
    page.evaluate("() => { page.pageSize = 2; return page.loadQueue(1); }")
    page.wait_for_timeout(800)
    assert page.locator('#imageQueue .image-item').count() == 2
    assert page.inner_text('#queuePageInfo') == '1 / 2'
    page.locator('#imageQueue .image-item').nth(1).click()
    page.wait_for_timeout(500)
    page.click('#nextTask')                                  # 페이지 끝 → 다음 페이지 첫 장
    page.wait_for_timeout(1000)
    assert page.inner_text('#queuePageInfo') == '2 / 2'
    assert page.inner_text('#imagePosition') == '3 / 3'
    assert page.inner_text('#labelProgress') == '0%'
```

- [ ] **Step 6: 화면**

```html
<!-- labeling.html: #imageQueue 아래 -->
<div id="queuePager" class="queue-pager is-hidden">
    <button id="queuePrev" class="icon-button" type="button" aria-label="이전 페이지">‹</button>
    <span id="queuePageInfo">1 / 1</span>
    <button id="queueNext" class="icon-button" type="button" aria-label="다음 페이지">›</button>
</div>
```

```javascript
// 생성자: this.page = 1; this.pageSize = 50; this.totalRows = 0; this.counts = { total: 0, complete: 0, remaining: 0 };
// this.images 주석을 "지금 페이지의 작업할 이미지(서버가 50장씩 준다)" 로 바꾼다.

        // 대기열 한 페이지를 받는다. selectId 가 있으면 그 이미지를(페이지 밖이면 서버가 requested 로 준다),
        // 없으면 첫 장을 연다. last 면 마지막 장을 연다(이전 페이지로 갈 때).
        async loadQueue(page, selectId, last) {
            let _this = this;
            let data = { page: page, page_size: _this.pageSize };
            if (selectId) data.image_id = selectId;
            let response = await labelingApi('queue', data, true);
            if (_this.destroyed) return response;
            _this.images = response.images || [];
            _this.page = response.page;
            _this.totalRows = response.totalRows;
            _this.counts = response.counts;
            let pages = Math.max(1, Math.ceil(_this.totalRows / _this.pageSize));
            $('#queuePageInfo').text(_this.page + ' / ' + pages);
            $('#queuePager').toggleClass('is-hidden', pages <= 1);
            $('#queuePrev').prop('disabled', _this.page <= 1);
            $('#queueNext').prop('disabled', _this.page >= pages);
            _this.renderImages();
            let target = response.requested
                || (selectId && $.grep(_this.images, function (i) { return String(i.id) === String(selectId); })[0])
                || (last ? _this.images[_this.images.length - 1] : _this.images[0]);
            if (target) _this.selectImage(target);
            else _this.clearActiveImage();
            return response;
        }
```

- `updatePosition()`: 위치 = `(this.page - 1) * this.pageSize + index + 1`, 분모 = `this.counts.remaining`, 진행률 = `counts.complete / counts.total`
- `moveNext()`: 페이지 안에 다음 장이 있으면 그것, 없으면 `pages > this.page` 면 `loadQueue(this.page + 1)`, 아니면 `loadQueue(1)`(처음으로)
- `#nextTask` 활성 조건: `this.counts.remaining >= 2`
- `submitTask()` 성공 뒤: `counts.remaining -= 1; counts.complete += 1` 하고, 페이지 안에 남은 작업할 이미지가 있으면 그것, 없으면 `loadQueue(this.page > 1 && this.images.length <= 1 ? this.page - 1 : this.page)`
- `searchMainData()`: `response.images` 를 쓰던 부분을 `await _this.loadQueue(1, requestedId)` 로. `labels`·`item` 은 첫 응답에서 그대로 읽는다(지금 코드 유지 — 첫 호출을 `loadQueue` 로 바꾸고 그 반환값에서 읽는다)
- `$('#queuePrev').on('click', () => page.loadQueue(page.page - 1, null, true)); $('#queueNext').on('click', () => page.loadQueue(page.page + 1));`
- `main.css`: `.queue-pager { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 8px 0; font-size: 12px; }`

- [ ] **Step 7: 통과 확인** — 새 e2e, 기존 `test_data_screens`·`test_image_fit`·`test_write_paths`(라벨링)·`test_client_workflow`(라벨링 흐름)·`test_workflow`. `test_image_fit` 은 `queue['images']` 로 두 장을 claim 한다 — 두 장 모두 작업할 상태라 그대로 통과해야 한다
- [ ] **Step 8: 커밋** — `feat: 라벨링 대기열을 서버에서 50장씩 나눠 준다`

---

### Task 6: DB 로그 보존 (결정 7)

**Files:**
- Create: `domain/services/log_retention.py`
- Modify: `domain/management/commands/run_worker.py:32-52`
- Test: `tests/test_log_retention.py`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_log_retention.py
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from domain.models.system import LoginLog, MenuUseLog, SystemLog
from domain.services import log_retention


class LogRetentionTest(TestCase):
    def _age(self, model, days, **fields):
        row = model.objects.create(**fields)
        model.objects.filter(pk=row.pk).update(_created=timezone.now() - timedelta(days=days))
        return row

    def test_보존_기간이_지난_로그만_지운다(self):
        old_sys = self._age(SystemLog, 91, Type='info', Source='e2e', Message='old')
        new_sys = self._age(SystemLog, 89, Type='info', Source='e2e', Message='new')
        old_login = self._age(LoginLog, 366, Type='fail', Username='x')
        new_login = self._age(LoginLog, 364, Type='fail', Username='x')
        old_menu = self._age(MenuUseLog, 366, MenuCode='wm_user')
        deleted = log_retention.purge()
        self.assertEqual(deleted, {'sys_log': 1, 'login_log': 1, 'menu_use_log': 1})
        self.assertFalse(SystemLog.objects.filter(pk=old_sys.pk).exists())
        self.assertTrue(SystemLog.objects.filter(pk=new_sys.pk).exists())
        self.assertTrue(LoginLog.objects.filter(pk=new_login.pk).exists())
```

필드명(`Type`·`Source`·`Message`·`MenuCode`·`_created`)과 필수값은 `domain/models/system.py` 의 `SystemLog`·`LoginLog`·`MenuUseLog` 정의를 읽고 맞춘다. `USE_TZ=False` 라 `timezone.now()` 는 naive 다.

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**

```python
# domain/services/log_retention.py
"""DB 로그 보존. 워커가 하루 한 번 부른다(run_worker). 파일 로그는 configurations/log.py 가 따로 지운다.

시스템로그는 장애 분석용이라 90일, 로그인·메뉴 로그는 접속 감사용이라 365일(사용자 결정 2026-10-07).
"""
from datetime import timedelta

from django.utils import timezone

from domain.models.system import LoginLog, MenuUseLog, SystemLog

RETENTION_DAYS = ((SystemLog, 90), (LoginLog, 365), (MenuUseLog, 365))


def purge(now=None):
    """보존 기간이 지난 행을 지우고 {테이블: 지운 수} 를 돌려준다."""
    now = now or timezone.now()
    deleted = {}
    for model, days in RETENTION_DAYS:
        count, _ = model.objects.filter(_created__lt=now - timedelta(days=days)).delete()
        deleted[model._meta.db_table] = count
    return deleted
```

```python
# run_worker.py handle() 루프 안(작업 처리 뒤)
PURGE_INTERVAL_SECONDS = 24 * 3600
...
        last_purge = None
        while not self._stop:
            ...
            if last_purge is None or time.monotonic() - last_purge >= PURGE_INTERVAL_SECONDS:
                try:
                    logger.info('DB 로그 보존 정리: %s', log_retention.purge())
                except Exception:
                    logger.exception('DB 로그 보존 정리 실패')
                last_purge = time.monotonic()
```

`--once` 일 때도 한 번 돈다(첫 반복). 워커가 2개면 둘 다 지우지만 같은 조건의 DELETE 라 결과가 같다.

- [ ] **Step 4: 통과 확인** — 단위 전체, `DB_CONN_MAX_AGE=0 .venv/bin/python manage.py run_worker --once` 출력·로그 파일에 "DB 로그 보존 정리"
- [ ] **Step 5: 커밋** — `feat: 워커가 하루 한 번 DB 로그를 보존 기간에 맞춰 지운다`

---

### Task 7: 사용자 등록 임시 비밀번호 창 (결정 8)

**Files:**
- Modify: `app/templates/system/user.html`(모달 + `saveUser` 성공 처리)
- Modify: `scripts/verify_modals.py`(경우 하나 추가 → 10)
- Test: `tests/e2e/test_crud.py` 또는 `tests/e2e/test_write_paths.py` 의 사용자 등록 테스트 근처

- [ ] **Step 1: 실패하는 e2e**

```python
def test_사용자를_등록하면_임시_비밀번호를_한_번_보여_준다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_user')
    login_id = f'e2e-temp-{int(time.time()) % 100000}'
    user_id = None
    try:
        page.click('#btnNew')                         # 실제 버튼 id·필수 칸은 user.html 에서 확인
        page.fill('#login_id', login_id)
        page.fill('#Name', 'E2E 임시')
        page.select_option('#UserGroup_id', index=1)
        with page.expect_response(lambda r: 'user?action=save' in r.url) as saved:
            page.click('#btnSave')
            if page.locator(CONFIRM_OK).is_visible():  # 저장 확인창이 있으면
                page.click(CONFIRM_OK)
        user_id = saved.value.json()['id']
        page.wait_for_selector('#tempPasswordModal.show', timeout=8000)
        value = page.inner_text('#tempPasswordValue').strip()
        assert len(value) == 12
        page.click('#tempPasswordModal .modal-footer .btn-input')
        page.wait_for_selector('#tempPasswordModal', state='hidden')
    finally:
        if user_id:   # 이 테스트가 만든 사용자만 지운다(test_write_paths 의 비밀번호 설정 테스트와 같은 방법)
            deleted = page.evaluate(test_crud.TestUserLifecycle.POST, ['/api/system/user?action=delete', {'id': user_id}])
            assert deleted.get('success'), deleted
```

`tests/e2e/test_write_paths.py` 에 둔다(`test_crud`·`CONFIRM_OK`·`open_gui` 가 이미 import 돼 있다). `#btnNew`·`#login_id`·`#Name`·`#UserGroup_id`·`#btnSave` 는 `system/user.html` 의 실제 id 로 맞춘다.

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — `client.html` 의 `#apiKeyModal`(한 번만 보여 주는 키) 마크업을 따라 만든다

```html
<div class="modal fade" id="tempPasswordModal" tabindex="-1" data-bs-backdrop="static" aria-labelledby="tempPasswordTitle">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title" id="tempPasswordTitle">임시 비밀번호</h5></div>
    <div class="modal-body">
      <p class="mb-2">이 창을 닫으면 다시 볼 수 없습니다. 사용자에게 전달하고 첫 로그인 뒤 내 정보에서 바꾸도록 안내합니다.</p>
      <div class="d-flex align-items-center gap-2">
        <code class="fs-5" id="tempPasswordValue"></code>
        <button type="button" class="btn btn-input" id="btnCopyTempPassword">복사</button>
      </div>
    </div>
    <div class="modal-footer"><button type="button" class="btn btn-input" data-bs-dismiss="modal">닫기</button></div>
  </div></div>
</div>
```

```javascript
// saveUser() 의 fnSuccess
                if (res.success) {
                    Notify.success("저장되었습니다.");
                    _this.searchDataBind();
                    if (res.temp_password) {
                        $('#tempPasswordValue').text(res.temp_password);
                        bootstrap.Modal.getOrCreateInstance(document.getElementById('tempPasswordModal')).show();
                    }
                }
// init 에서
            $('#btnCopyTempPassword').on('click', function () {
                navigator.clipboard.writeText($('#tempPasswordValue').text())
                    .then(function () { Notify.success('복사했습니다.'); })
                    .catch(function () { Alert.alert('', '복사하지 못했습니다. 직접 선택해 복사합니다.'); });
            });
            $('#tempPasswordModal').on('hidden.bs.modal', function () { $('#tempPasswordValue').text(''); });
```

`verify_modals.py` 에 "Bootstrap 단독 (임시 비밀번호)" 경우를 더한다 — 기존 "클라이언트 배포본" 경우를 복사해 여는 방법만 `$('#tempPasswordModal')` 직접 show 로 바꾼다. UI_GUIDE §5.1 목록과 §5.4 "아홉 경우" → "열 경우".

- [ ] **Step 4: 통과 확인** — 새 e2e, `verify_modals` PASS(10 경우)
- [ ] **Step 5: 커밋** — `feat: 사용자를 등록하면 임시 비밀번호를 한 번 보여 준다`

---

### Task 8: 개발 의존성 분리 (결정 9)

**Files:** Create `requirements-dev.txt`; Modify `requirements.txt`, `docs/DEVELOPMENT.md` §1(설치), `README.md`(설치 한 줄)

- [ ] **Step 1:** 쓰는 곳 재확인 — `grep -rnE "^\s*(import|from) (requests|urllib3|numpy|qrcode|six)\b" app domain configurations scripts tests` → `scripts/send_inspections.py` 의 `requests` 만
- [ ] **Step 2: 작성**

```text
# requirements-dev.txt — 개발·검증 도구. 운영 서버에는 설치하지 않는다.
-r requirements.txt
requests==2.34.2        # scripts/send_inspections.py (pip-audit 기준 2.33.0 이상)
openpyxl==3.1.5         # e2e 엑셀 내용 검증
et_xmlfile==2.0.0
playwright==1.63.0      # e2e (설치 뒤 `playwright install chromium`)
pytest==9.1.1           # e2e 러너
```

`requirements.txt` 에서 `requests`·`numpy`·`qrcode`·`six`·`openpyxl`·`et_xmlfile` 줄을 지운다(`openpyxl` 은 앱 코드가 쓰지 않는다 — Step 1 grep 에 함께 넣어 0건 확인).
- [ ] **Step 3: 확인** — 임시 venv 에 `pip install -r requirements.txt` 만 설치하고 `manage.py check --settings=configurations.test_settings` + 단위 전체 통과(운영에 필요한 것이 빠지지 않았다). `.venv` 에는 `pip install -r requirements-dev.txt`. pip-audit `-r requirements.txt` 0건
- [ ] **Step 4: 문서** — DEVELOPMENT §1 설치를 `pip install -r requirements-dev.txt` 로, DEPLOYMENT 은 `requirements.txt` 그대로임을 확인
- [ ] **Step 5: 커밋** — `chore: 개발 도구를 requirements-dev.txt 로 나누고 운영 의존성에서 뺀다`

---

### Task 9: 레거시 정리 (결정 10 + `search_company`·`TenantAccessService.require`)

**Files:**
- Modify: `app/templates/definition/company.html`(품목단가 탭 `#tabs_unitcost` 링크·`#tabs_price_tab` 패널·`price_grid` 관련 JS)
- Delete: `app/views/popup/search_company.py`; Modify: `domain/gui.py:146`(`popup/search_company` 매핑)
- Modify: `domain/services/data/tenant_access.py:25-29`(`require` 삭제)
- Delete(확인 후): `app/static/assets/vendor/ax5ui/`, `app/static/assets/vendor/dropzone/`, `app/static/assets/js/ui/component.fileupload.js`

- [ ] **Step 1: 품목단가 탭** — `company.html` 에서 탭 링크(76-77행), 패널(375-~455행 `#tabs_price_tab`), `this.price_grid`·`priceForm`·`mat_price_list`·`save_price` 를 쓰는 JS 를 지운다. 지운 뒤 `grep -n "price" app/templates/definition/company.html` 0건. superuser 로 `/gui/wm_company/` 를 열어 콘솔 오류 0, 업체 목록 조회·선택이 되는지 Playwright 로 확인
- [ ] **Step 2: `search_company`** — 파일·매핑 삭제 후 `verify_permission_map`·`verify_links` PASS
- [ ] **Step 3: `TenantAccessService.require`** — `grep -rn "TenantAccessService.require\|\.require(" domain app` 로 부르는 곳 0건 확인 후 삭제
- [ ] **Step 4: 벤더 실사용 확인** — 모든 화면을 열며 요청을 모은다

```python
# scratchpad — 저장소에 넣지 않는다
import pathlib, django, os, sys
sys.path.insert(0, '.'); os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'configurations.settings'); django.setup()
from domain.gui import GUIConfiguration
from playwright.sync_api import sync_playwright
B = 'http://127.0.0.1:8123'; pw = pathlib.Path('.admin_pw').read_text().strip()
hits = []
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    pg.on('request', lambda r: hits.append(r.url) if any(k in r.url for k in ('ax5', 'dropzone', 'fileupload')) else None)
    pg.goto(B + '/login/'); pg.fill('#loginId', 'admin'); pg.fill('#loginPwd', pw); pg.click('#login'); pg.wait_for_url(B + '/')
    for code in GUIConfiguration.menu_init():
        pg.goto(f'{B}/gui/{code}/?project=3', wait_until='networkidle')
    b.close()
print(sorted(set(hits)) or 'none')
```

`none` 이면 세 경로를 `git rm -r` 로 지운다(`rm -rf` 가 아니라 git 이 지운다 — 되돌릴 수 있다). 하나라도 나오면 그 경로는 남기고 사용처를 보고에 적는다.
- [ ] **Step 5: 통과 확인** — 단위 전체, `verify_*` 전부, e2e `test_menu`·`test_crud`
- [ ] **Step 6: 커밋** — `refactor: 동작하지 않는 품목단가 탭·search_company 와 쓰지 않는 벤더 자산을 지운다`

---

### Task 10: Export 를 임시 파일로 (점검 #9)

**Files:** Modify `domain/services/data/export/__init__.py:28-32`; Test `tests/test_export_formats.py`

- [ ] **Step 1: 실패하는 테스트**

```python
    def test_Export_는_zip_을_메모리에_모으지_않는다(self):
        # 배포 전 점검 #9: BytesIO + getvalue() 로 zip 크기의 2배를 메모리에 올렸다.
        from unittest.mock import patch
        import io
        with patch('domain.services.data.export.io.BytesIO', side_effect=AssertionError('BytesIO 사용')):
            job = self._run_export('COCO')      # 이 파일의 기존 COCO Export 테스트가 쓰는 도우미를 그대로 쓴다
        self.assertEqual(job.status, 'COMPLETED')
```

(도우미 이름은 `tests/test_export_formats.py` 를 읽고 맞춘다. `mvtec.py:23` 의 `BytesIO` 는 마스크 PNG 한 장용이라 대상이 아니다 — patch 대상을 `domain.services.data.export.io` 로 한정한다.)
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**

```python
import tempfile
from django.core.files import File
...
        # zip 을 디스크 임시 파일에 쓴다 — 이미지 수천 장이면 메모리에 모을 수 없다(배포 전 점검 #9).
        with tempfile.TemporaryFile(dir=settings.FILE_TEMP_UPLOAD_PATH) as handle:
            with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as zip_file:
                statistics = exporter.export(zip_file)
                zip_file.writestr("manifest.json", json.dumps(exporter.build_manifest(statistics), ensure_ascii=False, indent=2))
            handle.seek(0)
            export_job.file.save(f"{export_job.dataset_version.version_tag}_{export_job.format.lower()}.zip", File(handle), save=False)
```

`import io` 가 이 파일에서 더 쓰이지 않으면 지운다. `settings` import 를 더한다(`FILE_TEMP_UPLOAD_PATH` 는 `test_settings` 가 임시 폴더로 돌린다).
- [ ] **Step 4: 통과 확인** — `test_export_formats` 8형식 전부, e2e `test_client_workflow`(zip 까지)
- [ ] **Step 5: 커밋** — `perf: Export zip 을 메모리 대신 임시 파일에 만든다`

---

### Task 11: jquery-validation 1.22.1 (점검 #12)

**Files:** Create `app/static/assets/vendor/jquery-validation/1.22.1/jquery.validate.min.js`; Modify 셋을 싣는 템플릿 3곳(`index.html:251`·`layout_page.html:56`·`login_mes.html:112`); Delete `.../1.17.0/`

- [ ] **Step 1:** `curl -sL https://cdn.jsdelivr.net/npm/jquery-validation@1.22.1/dist/jquery.validate.min.js -o <위 경로>` 후 머리말에 `v1.22.1` 확인, `sha256sum` 을 커밋 메시지에 적는다
- [ ] **Step 2:** 템플릿 3곳 경로 교체(T3 이후면 `{% static %}`), `1.17.0/` 은 `git rm -r`
- [ ] **Step 3: 확인** — e2e `test_menu`(로그인 폼 `validate` 사용)·내 정보 화면 열기(`page/account/myinfo.html` 의 `#userForm.validate`), 콘솔 오류 0. 빈 아이디로 로그인하면 기존처럼 검증 문구가 뜬다
- [ ] **Step 4: 커밋** — `chore: jquery-validation 을 1.17.0 에서 1.22.1 로 올린다`

---

### Task 12: 이미지·썸네일 조건부 응답 (점검 #17)

**Files:** Modify `app/views/files/__init__.py`(`sendfile`); Test `tests/test_storage.py` `SendfileTest`

- [ ] **Step 1: 실패하는 테스트**

```python
    def test_바뀌지_않았으면_304(self):
        from django.test import RequestFactory
        from django.utils.http import http_date
        from app.views.files import sendfile
        first = sendfile(self.file, request=RequestFactory().get('/'))
        self.assertIn('no-cache', first['Cache-Control'])
        since = RequestFactory().get('/', HTTP_IF_MODIFIED_SINCE=first['Last-Modified'])
        self.assertEqual(sendfile(self.file, request=since).status_code, 304)
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — `sendfile(path, *, request=None, ...)` 에 `request` 를 더하고, 맨 앞에서

```python
    mtime = path.stat().st_mtime   # 없으면 FileNotFoundError 그대로
    if request is not None and not was_modified_since(request.META.get('HTTP_IF_MODIFIED_SINCE'), int(mtime)):
        return HttpResponseNotModified()
    ...응답을 만든 뒤
    response['Last-Modified'] = http_date(mtime)
    # 이미지는 편집(회전·자르기)하면 같은 주소가 다른 파일이 된다 — 매번 확인하되 바뀌지 않았으면 304.
    response['Cache-Control'] = 'private, no-cache'
```

(`was_modified_since` 는 `django.views.static`, `http_date` 는 `django.utils.http`.) `media.py` 의 `_file_response` 와 `api_v1.py` 배포물 호출에 `request=request` 를 넘긴다(`_file_response(file_field, request, **kwargs)` 로 시그니처를 바꾸고 호출 6곳을 함께 고친다).
- [ ] **Step 4: 통과 확인** — 단위 전체, 개발 서버에서 `curl -sI -b <세션> /media/image/<id>/thumbnail/` 두 번째에 `If-Modified-Since` 로 304
- [ ] **Step 5: 커밋** — `perf: 이미지 응답에 Last-Modified 를 달아 바뀌지 않았으면 304 로 답한다`

---

### Task 13: 검사항목 관리 목록 N+1 (점검 #19)

**Files:** Modify `domain/services/data/item_platform.py:9-23,78-123`; Test `tests/test_item_api.py` `ItemAdminApiTest`

- [ ] **Step 1: 실패하는 테스트** — 검사항목 1개일 때와 4개일 때 `/api/item/item_admin?action=list` 쿼리 수가 같다. `LabelingApiTest.test_대기열_쿼리_수는_이미지_수와_무관하다` 와 같은 모양(`CaptureQueriesContext` 로 두 번 재고 같음을 단언)으로 쓰고, 검사항목은 `InspectionItem.objects.create(tenant=..., code=f'N{i}', ...)` 로 3개 더 만든다. 지금은 검사항목마다 5쿼리씩 는다
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — `list_items` 가 테넌트마다 한 번씩 묶어 센다

```python
    @staticmethod
    def _counts(model, tenant, item_field, **filters):
        """검사항목별 행 수 {item_id: n} — 검사항목마다 count() 를 던지지 않는다."""
        return dict(model.objects.for_tenant(tenant).filter(**filters).values_list(item_field)
                    .annotate(n=Count('id')).values_list(item_field, 'n'))
```

이미지 상태 집계는 `ImageAsset...values('dataset__item_id').annotate(image_count=..., labeled_count=..., ...)`(지금 `aggregate` 의 Count 들을 그대로) 한 번, 라벨 클래스·배정(`is_active=True`)·데이터셋·스냅샷은 `_counts` 한 번씩. `_summary(item, tenant, stats, counts)` 는 이 사전에서 꺼내 쓰고(없으면 0), 반환 키·값은 지금과 같게 둔다. `detail_for`·`get_detail` 이 쓰는 `_detail` 은 손대지 않는다.
- [ ] **Step 4: 통과 확인** — 단위 전체, e2e `test_crud`(검사항목 관리)·`test_grid_common`(검사항목 관리 화면 안 페이징)
- [ ] **Step 5: 커밋** — `perf: 검사항목 관리 목록의 검사항목별 집계 쿼리를 묶는다`

---

### Task 14: PostgreSQL 통합 테스트 (결정 11 A)

**Files:**
- Create: `configurations/pg_test_settings.py`, `tests/pg/__init__.py`, `tests/pg/test_rls_and_raw_sql.py`
- Modify: `docs/DEVELOPMENT.md` §2(실행 방법), `.env.example`(`PG_TEST_DB_NAME`)

**막는 것:** DBA 가 공유 PostgreSQL 에 빈 DB `maip_test`(소유자 = 이 프로젝트 계정)를 만들어야 한다. 이 계정은 `CREATEDB` 권한이 없다(확인함). 사용자에게 보낼 요청 문구: "공유 PostgreSQL 에 `maip_test` DB 를 만들고 소유자를 `yest` 로 해 주세요. 제조AI플랫폼 통합 테스트 전용이고, 테스트가 테이블을 만들고 비웁니다."

- [ ] **Step 1: 설정**

```python
# configurations/pg_test_settings.py
"""PostgreSQL 통합 테스트(RLS·raw SQL). DBA 가 만든 maip_test 를 --keepdb 로 다시 쓴다.

    python manage.py test tests.pg --settings=configurations.pg_test_settings --keepdb

운영 DB 를 쓰지 않도록 이름을 강제한다 — PG_TEST_DB_NAME 이 maip_test 가 아니면 멈춘다.
"""
from django.core.exceptions import ImproperlyConfigured

from configurations.env import env
from configurations.test_settings import *  # noqa: F401,F403 — 경로·캐시·해시는 test_settings 그대로
from configurations.settings import DATABASES as _BASE

NAME = env('PG_TEST_DB_NAME', 'maip_test')
if NAME != 'maip_test':
    raise ImproperlyConfigured('PG_TEST_DB_NAME 은 maip_test 여야 한다.')
DATABASES = {'default': {**_BASE['default'], 'CONN_MAX_AGE': 0, 'TEST': {'NAME': NAME}}}
TENANT_RLS_ENABLED = True
```

`TEST.NAME` 을 `maip_test` 로 두면 Django 가 그 이름을 테스트 DB 로 쓰고 `--keepdb` 면 만들거나 지우지 않는다. 처음 한 번은 `--keepdb` 가 마이그레이션을 적용한다.
- [ ] **Step 2: 테스트**

```python
# tests/pg/test_rls_and_raw_sql.py
from django.db import connection
from django.test import TestCase

from django.contrib.auth.models import User

from domain.models.data import ImageAsset, InspectionItem
from domain.services.data.image import ImageService
from domain.tenancy import current_tenant, tenant_atomic
from tests.test_data_services import make_image


class RlsTest(TestCase):
    def test_테넌트_밖에서는_0건이고_안에서는_보인다(self):
        tenant = current_tenant()
        with tenant_atomic(tenant):
            item = InspectionItem.objects.create(tenant=tenant, code='PG-RLS', name='PG RLS',
                                                 task_type=InspectionItem.TaskType.OBJECT_DETECTION)
            user = User.objects.create_user('pg-rls', password='x')
            ImageService.upload_images(item, [make_image()], actor=user)
            inside = ImageAsset.objects.for_tenant(tenant).count()
        self.assertGreaterEqual(inside, 1)
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM vision_data_imageasset')
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_FORCE_RLS_가_18테이블에_걸려_있다(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_class WHERE relname IN (SELECT tablename FROM pg_policies) "
                           "AND relrowsecurity AND relforcerowsecurity")
            self.assertEqual(cursor.fetchone()[0], 18)


class MenuTreeSqlTest(TestCase):
    def test_메뉴_트리_재귀_SQL_이_돈다(self):
        from django.core.management import call_command
        call_command('seed_initial', verbosity=0)
        from domain.services.system import SystemService
        admin = User.objects.create_superuser('pg-admin', password='x')
        menus = SystemService().get_web_menu_list(admin, 'ko-KR')   # v_menu_folder·with recursive
        self.assertTrue(menus)
```

`get_web_menu_list` 의 반환 모양(목록·사전)은 실행할 때 읽고 단언을 맞춘다 — DB 가 생기기 전에는 돌려 볼 수 없다. 단위 테스트 러너가 `tests.pg` 를 SQLite 로 돌리지 않도록 `tests/pg/__init__.py` 에서 `connection.vendor != 'postgresql'` 이면 `unittest.SkipTest` 를 낸다.
- [ ] **Step 3: 확인** — `manage.py test tests --settings=configurations.test_settings` 에서 `tests.pg` 는 skip. DB 가 생기면 `--settings=configurations.pg_test_settings --keepdb` 로 통과
- [ ] **Step 4: 문서** — DEVELOPMENT §2 에 실행법과 "maip_test 외 이름은 거부" 를, STATUS 우선순위 5 를 "설정 완료, DB 생성 대기" 로
- [ ] **Step 5: 커밋** — `test: PostgreSQL 통합 테스트(RLS·raw SQL) 설정을 둔다`

---

### Task 15: 문서·전체 검증·병합

**Files:** `docs/DECISIONS.md`, `docs/STATUS.md`, `docs/FEATURES.md`(라벨링 페이징·임시 비밀번호), `docs/UI_GUIDE.md`, `docs/DEVELOPMENT.md`(테스트 수), `docs/superpowers/plans/2026-10-07-predeploy-audit.md`(처리 결과 표에 #9~#19)

- [ ] **Step 1: DECISIONS §8** — 2026-10-07 사용자 결정 행: 결정 1·2·3(검사 이력은 모든 검사항목 — 첫 화면 현황판, 이미지는 검사항목 권한)·5·6·7·8·9·10·11
- [ ] **Step 2: STATUS** — 우선순위 6-1 을 처리 결과로, 5 를 "DB 생성 대기", 3-5 에서 지운 항목(`search_company`·`require`·품목단가 탭·벤더·임시 비밀번호) 정리. 기준일·단위 테스트 수
- [ ] **Step 3: 전체 검증** — 단위 전체, `verify_*` 10개, 전체 e2e(약 12분), 운영값 `check --deploy`(W019 하나), pip-audit `-r requirements.txt` 0건
- [ ] **Step 4: 커밋** — `docs: 배포 전 점검 후속 결정과 처리 결과를 반영한다`
- [ ] **Step 5: 병합** — `git checkout main && git merge --no-ff fix/audit-followup` 후 `git branch -d fix/audit-followup`. push 하지 않는다

---

## 순서와 의존

- T1 → T3 → (T4·T11 은 T3 의 `{% static %}` 위에서) → 나머지는 순서 무관
- T5(대기열 페이징)는 가장 크다. e2e 기존 테스트 3개가 대기열을 쓴다(`test_image_fit`·`test_write_paths`·`test_client_workflow`)
- T14 는 DB 가 생길 때까지 설정·skip 까지만 끝낸다
- 사용자 몫: T2 Step 5(원본 MES 담당 연락), T14(DBA 요청), `static/` 삭제(T3 Step 5 뒤에도 생긴다)
