# Client `/api/v1` 요청 9건(R5~R9) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VisionInspectionClient 가 `/api/v1` 에서 인증을 통과하고, 배포·라이선스 파일을 내려받고, 모든 오류를 봉투로 해석할 수 있게 한다.

**Architecture:** 신규 코드는 `app/views/api_v1.py` 한 파일에 둔다. 공통 동작(테넌트 진입 여부·인증 오류 구분·본문 선검사)은 `ClientApiView` 한 곳에서 고치고 모든 Endpoint 가 상속으로 받는다. 배포물 제공은 인증 없는 2개 계열(목록·다운로드)이고 HTTP Range 를 직접 구현한다.

**Tech Stack:** Python 3.12 · Django 5.0.4 · PostgreSQL 16(테스트는 SQLite) · 표준 라이브러리만. **새 의존성 없음.**

**Spec:** [docs/superpowers/specs/2026-10-02-client-api-v1-design.md](../specs/2026-10-02-client-api-v1-design.md)

## Global Constraints

- **브랜치는 `phase6/client-api-v1`.** `main` 에 직접 커밋하지 않는다. 시작 전 `git status` 로 작업 트리를 확인한다 — 다른 세션의 미커밋 변경(`app/static/data/common.js` 등)이 있으면 **stash 하지 않고 기다린다**
- 커밋 메시지는 **한국어**, Conventional Commits 의 type 만 영문. 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- 테스트는 **반드시** `--settings=configurations.test_settings`. 빼면 운영 PostgreSQL 에 테스트 DB 가 생긴다
- `/api/v1` 성공은 `{"data": ...}`, 실패는 `{"error": {"code","message","retryable"}}`. **예외는 health 의 503 하나**
- 시각은 UTC `Z`. 변환은 `to_utc_z()` 한 곳에서만 한다(`USE_TZ=False`, naive local)
- **API Key 를 로그·응답·오류 메시지에 남기지 않는다.** 마스킹한 값도 남기지 않는다
- 응답 필드명·오류 코드는 **서버 현 구조가 정본**이다(DEC-C2). `id` 를 `inspection_id` 로 바꾸지 않는다
- `tenant_atomic()` 밖에서 테넌트 테이블을 읽으면 **예외 없이 0건**이다. `vision_client`·`vision_inspection`·`vision_overlay` 는 RLS 대상이 아니다(`0007_tenant_rls.py` `TENANT_TABLES` 확인됨)
- 새 마이그레이션 없음. `makemigrations` 를 돌릴 일이 없다
- `api/v1/<path:rest>` catch-all 은 **항상 모든 구체 `api/v1/...` 라우트 뒤, 범용 `api/<task>/<view>` 앞**이어야 한다. 라우트를 더할 때마다 이 순서를 지킨다

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `app/views/api_v1.py` | Client 계약 Endpoint 전부 | 수정 — 공통 기반 3건, health 교체, heatmap·배포물 5개 뷰 추가 |
| `configurations/urls.py` | 라우팅. **순서가 동작을 바꾼다** | 수정 — 라우트 6개 |
| `configurations/settings.py` | `APP_VERSION`, `DISTRIBUTION_ROOT` | 수정 — 2줄 |
| `.env.example` | 새 설정 키의 placeholder | 수정 — 1줄 |
| `.gitignore` | 배포물은 확장자로 제외 | 수정 — 1줄 교체 |
| `distribution/` | 배포물(Qt 소스·Client zip)과 `SHA256SUMS.txt` | `app/static/` 밖으로 이동 + README 재작성 |
| `tests/test_client_api.py` | `/api/v1` 계약 테스트 | 수정 — 기존 health 테스트 교체, 7묶음 추가 |
| `docs/client/SERVER_RESPONSES.md` | R1~R9 회신 | 신규 |
| `docs/08_DEPLOYMENT.md` · `docs/USER_DECISIONS.md` · `docs/IMPLEMENTATION_STATUS.md` | 배포 절차·결정·현황 | 수정 |

---

### Task 1: 공통 기반 — 테넌트 플래그와 인증 오류 구분 (R5)

**Files:**
- Modify: `app/views/api_v1.py:88-117` (`ClientApiView`)
- Test: `tests/test_client_api.py` (`AuthTest`)

**Interfaces:**
- Consumes: 없음(첫 작업)
- Produces: `ClientApiView.use_tenant: bool`(기본 `True`), `ClientApiView._authenticate(request) -> tuple[VisionClient | None, str | None]`. 이후 모든 Task 의 뷰가 `require_auth`·`use_tenant` 두 클래스 속성으로 동작을 고른다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_client_api.py` 의 `AuthTest` 안, 기존 `test_잘못된_키는_401` 과 `test_비활성_Client는_401` 을 아래로 **교체**한다(상태 코드만 보던 것을 코드까지 본다).

```python
    def test_헤더가_없으면_AUTH_REQUIRED(self):
        response = self.http.get('/api/v1/catalog')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_REQUIRED')
        self.assertFalse(response.json()['error']['retryable'])

    def test_헤더가_하나만_있어도_AUTH_REQUIRED(self):
        response = self.http.get('/api/v1/catalog', HTTP_X_CLIENT_ID='CLIENT-TEST')
        self.assertEqual(response.json()['error']['code'], 'AUTH_REQUIRED')

    def test_잘못된_키는_AUTH_INVALID(self):
        response = self.http.get('/api/v1/catalog', **self._headers(HTTP_X_API_KEY='wrong'))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_INVALID')

    def test_없는_Client_ID_는_AUTH_INVALID(self):
        response = self.http.get('/api/v1/catalog',
                                 **self._headers(HTTP_X_CLIENT_ID='CLIENT-NOPE'))
        self.assertEqual(response.json()['error']['code'], 'AUTH_INVALID')

    def test_비활성_Client는_AUTH_INVALID(self):
        VisionClient.objects.filter(pk=self.vision_client.pk).update(active=False)
        response = self.http.get('/api/v1/catalog', **self._headers())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_INVALID')
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python manage.py test tests.test_client_api.AuthTest --settings=configurations.test_settings -v2`
Expected: FAIL — `'AUTH_REQUIRED' != 'AUTH_INVALID'` (지금은 모든 실패가 `AUTH_REQUIRED` 다)

- [ ] **Step 3: `ClientApiView` 를 고친다**

`dispatch` 와 `_authenticate` 를 아래로 교체한다.

```python
    require_auth = True
    # health 와 배포물 Endpoint 는 테넌트 데이터를 읽지 않는다. 이 플래그가 없으면
    # health 가 DB 장애 때 tenant_atomic() 진입에서 먼저 터져 503 이 아니라 500 이 된다.
    use_tenant = True

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        if self.require_auth:
            client, failure = self._authenticate(request)
            if client is None:
                return error(failure, '인증에 실패했다.', 401)
            request.vision_client = client
        try:
            if not self.use_tenant:
                return super().dispatch(request, *args, **kwargs)
            with tenant_atomic():
                return super().dispatch(request, *args, **kwargs)
        except Exception:
            logger.exception('/api/v1 처리 실패: %s', request.path)
            return error('INTERNAL_ERROR', '서버 오류가 발생했다.', 500, retryable=True)

    @staticmethod
    def _authenticate(request):
        """`(client, 실패코드)`. 성공하면 `(client, None)`.

        "헤더가 안 갔다"(`AUTH_REQUIRED`)와 "키가 틀렸다"(`AUTH_INVALID`)를 가른다 —
        Client 는 둘을 같은 방식으로 처리하지만 현장 장애 진단에 필요하다(R5).
        없는 Client 와 비활성 Client 는 구분하지 않는다. 존재 여부를 알려 주지 않는다.
        """
        client_id = request.headers.get('X-Client-ID', '')
        api_key = request.headers.get('X-API-Key', '')
        if not client_id or not api_key:
            return None, 'AUTH_REQUIRED'
        client = VisionClient.objects.filter(client_id=client_id, active=True).first()
        if client is None:
            # API Key 는 어떤 형태로도 남기지 않는다. client_id 만 남긴다.
            logger.info('/api/v1 인증 실패(없거나 비활성): client_id=%s', client_id)
            return None, 'AUTH_INVALID'
        digest = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        # 타이밍 공격을 피하려 상수 시간 비교를 쓴다.
        if not hmac.compare_digest(digest, client.api_key_hash):
            logger.info('/api/v1 인증 실패(키 불일치): client_id=%s', client_id)
            return None, 'AUTH_INVALID'
        VisionClient.objects.filter(pk=client.pk).update(last_seen_at=timezone.now())
        return client, None
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python manage.py test tests.test_client_api --settings=configurations.test_settings`
Expected: PASS (이 파일 전체. 기존 테스트가 깨지지 않아야 한다)

- [ ] **Step 5: 커밋**

```bash
git add app/views/api_v1.py tests/test_client_api.py
git commit -m "$(printf 'fix: Client 인증 실패를 AUTH_REQUIRED 와 AUTH_INVALID 로 구분\n\n헤더가 없는 경우와 키가 틀린 경우가 모두 AUTH_REQUIRED 로 나가\n현장에서 "헤더가 안 갔다"와 "키가 틀렸다"를 가를 수 없었다(R5).\n\n테넌트 컨텍스트 진입 여부를 고르는 use_tenant 플래그도 함께 더한다 —\nhealth 가 DB 장애를 503 으로 보고하려면 tenant_atomic() 밖에서 돌아야 한다.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 2: `GET /api/v1/health` 를 계약 형식으로 되돌린다 (R8)

**Files:**
- Modify: `app/views/api_v1.py:120-127` (`HealthView`), 상단 import
- Modify: `configurations/settings.py` (`APP_VERSION`)
- Test: `tests/test_client_api.py` (`HealthTest` 신규)

**Interfaces:**
- Consumes: `ClientApiView.use_tenant` (Task 1)
- Produces: `settings.APP_VERSION: str`. health 응답은 **봉투로 싸지 않는다**

- [ ] **Step 1: 실패하는 테스트를 쓴다**

기존 `AuthTest.test_health는_인증없이_열린다` 를 **삭제**하고(옛 형식을 검증한다) 새 클래스를 더한다. 파일 상단 import 를 이렇게 손본다.

```python
from unittest.mock import patch            # 새로 더한다

from django.conf import settings           # 새로 더한다
from django.db.utils import OperationalError  # 새로 더한다
from django.test import Client, TestCase, override_settings   # override_settings 를 더한다
```

`import shutil`, `import tempfile`, `from pathlib import Path` 도 함께 더한다 — Task 6 에서도 쓴다.

```python
class HealthTest(ClientApiTestCase):
    def test_인증없이_계약_형식으로_나온다(self):
        response = self.http.get('/api/v1/health')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        # Client 는 최상위 status·components·version 을 읽는다. 봉투로 싸면 못 읽는다.
        self.assertNotIn('data', body)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['components'], {'database': 'ok', 'storage': 'ok'})
        self.assertEqual(body['version'], settings.APP_VERSION)
        self.assertTrue(body['timestamp'].endswith('Z'))

    def test_DB_가_죽으면_503_degraded(self):
        with patch('django.db.connection.cursor', side_effect=OperationalError('down')):
            response = self.http.get('/api/v1/health')
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body['status'], 'degraded')
        self.assertEqual(body['components']['database'], 'error')
        self.assertEqual(body['components']['storage'], 'ok')
        # 이 503 은 오류 봉투가 아니다. Health 본문을 그대로 낸다.
        self.assertNotIn('error', body)

    def test_Storage_에_쓸_수_없으면_503_degraded(self):
        # 평범한 파일을 부모로 지목한다 — mkdir 이 NotADirectoryError 로 실패한다.
        # 권한으로 막는 경로(/proc 등)를 쓰면 root 로 돌릴 때 통과해 버린다.
        blocker = Path(tempfile.mkdtemp(prefix='health-test-')) / 'not-a-dir'
        blocker.write_bytes(b'x')
        self.addCleanup(shutil.rmtree, blocker.parent, True)
        with override_settings(STORAGE_ROOT=blocker / 'storage'):
            response = self.http.get('/api/v1/health')
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body['components']['storage'], 'error')
        self.assertEqual(body['components']['database'], 'ok')
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python manage.py test tests.test_client_api.HealthTest --settings=configurations.test_settings -v2`
Expected: FAIL — `KeyError: 'status'` (지금 응답은 `{"data": {...}}` 다)

- [ ] **Step 3: `APP_VERSION` 을 더한다**

`configurations/settings.py` 의 `DEBUG = env_bool(...)` 바로 위에 넣는다.

```python
# health 응답의 version. 환경이 아니라 배포물의 성질이므로 .env 로 빼지 않는다.
APP_VERSION = '1.0.0'
```

- [ ] **Step 4: `HealthView` 를 교체한다**

상단 import 에 `from pathlib import Path`, `from django.conf import settings`, `from django.db import connection` 을 더한다(`from django.db import models` 는 그대로 둔다).

```python
class HealthView(ClientApiView):
    """`GET /api/v1/health` — 인증 없이 호출한다(Client 연결 확인).

    DB `SELECT 1` 과 Storage 쓰기/삭제를 **실제로 수행**한 뒤 응답한다. 하나라도
    실패하면 503 이고, 이 503 은 `/api/v1` 에서 오류 봉투가 아닌 유일한 응답이다 —
    Client 가 본문의 `components` 를 읽어 무엇이 죽었는지 보여 준다(계약 §4).
    """

    require_auth = False
    # DB 가 죽은 상황을 보고하는 뷰다. tenant_atomic() 안에서 돌면 진입 자체가
    # 먼저 터져 dispatch 의 except 가 500 INTERNAL_ERROR 로 바꿔 버린다.
    use_tenant = False
    http_method_names = ['get']

    def get(self, request):
        components = {'database': self._check_database(), 'storage': self._check_storage()}
        healthy = all(value == 'ok' for value in components.values())
        payload = {
            'status': 'ok' if healthy else 'degraded',
            'components': components,
            'version': settings.APP_VERSION,
            'timestamp': to_utc_z(timezone.now()),
        }
        return JsonResponse(payload, status=200 if healthy else 503,
                            json_dumps_params={'ensure_ascii': False})

    @staticmethod
    def _check_database():
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception:
            logger.exception('health: DB 점검 실패')
            return 'error'
        return 'ok'

    @staticmethod
    def _check_storage():
        probe = Path(settings.STORAGE_ROOT) / '.healthcheck'
        try:
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(b'ok')
            probe.unlink()
        except OSError:
            logger.exception('health: Storage 점검 실패')
            return 'error'
        return 'ok'
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python manage.py test tests.test_client_api --settings=configurations.test_settings`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add app/views/api_v1.py configurations/settings.py tests/test_client_api.py
git commit -m "$(printf 'fix: health 응답을 Client 계약 형식으로 되돌린다\n\n{"data":{status, server_time}} 를 내보내 Client 가 최상위 status 를 찾지\n못하고 구성요소를 둘 다 "error" 로 읽었다(R8). 최상위\nstatus·components·version·timestamp 로 바꾸고, DB·Storage 를 실제로\n점검해 하나라도 실패하면 503 degraded 를 낸다.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 3: 미지 경로 404 봉투와 본문 선검사 (R9-1·R9-2)

**Files:**
- Modify: `app/views/api_v1.py` (`ClientApiView.dispatch`, `V1NotFoundView` 신규, 상수)
- Modify: `configurations/urls.py:57` 뒤
- Test: `tests/test_client_api.py` (`EnvelopeTest` 신규)

**Interfaces:**
- Consumes: `error()` 헬퍼, `MAX_IMAGE_BYTES`
- Produces: `MULTIPART_SLACK_BYTES: int`, `ClientApiView._precheck(request) -> HttpResponse | None`, `V1NotFoundView`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
class EnvelopeTest(ClientApiTestCase):
    def test_없는_v1_경로는_404_봉투다(self):
        response = self.http.get('/api/v1/nope')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response['Content-Type'].split(';')[0], 'application/json')
        self.assertEqual(response.json()['error']['code'], 'NOT_FOUND')
        self.assertFalse(response.json()['error']['retryable'])

    def test_client_packages_는_범용_api_라우트에_먹히지_않는다(self):
        # 범용 api/<task>/<view> 가 먼저 받으면 로그인 세션을 요구해 401 HTML 이 된다.
        response = self.http.get('/api/v1/client-packages')
        self.assertEqual(response['Content-Type'].split(';')[0], 'application/json')
        self.assertNotEqual(response.status_code, 401)

    def test_Content_Length_가_없으면_인증보다_먼저_411(self):
        # 인증 헤더를 일부러 보내지 않는다 — 411 이 인증보다 앞인지 보는 테스트다.
        response = self.http.post('/api/v1/inspections', {'metadata': '{}'},
                                  CONTENT_LENGTH='')
        self.assertEqual(response.status_code, 411)
        self.assertEqual(response.json()['error']['code'], 'LENGTH_REQUIRED')

    def test_본문이_상한을_넘으면_인증보다_먼저_413(self):
        response = self.http.post('/api/v1/inspections', {'metadata': '{}'},
                                  CONTENT_LENGTH=str(64 * 1024 * 1024))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['error']['code'], 'IMAGE_TOO_LARGE')

    def test_GET_은_Content_Length_를_요구하지_않는다(self):
        self.assertEqual(self.http.get('/api/v1/health').status_code, 200)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python manage.py test tests.test_client_api.EnvelopeTest --settings=configurations.test_settings -v2`
Expected: FAIL — `/api/v1/nope` 는 Django 기본 404 HTML, `client-packages` 는 401 HTML, POST 는 401 이다

- [ ] **Step 3: 선검사와 404 뷰를 더한다**

`MAX_IMAGE_BYTES` 아래에 상수를 더한다.

```python
# multipart 경계 문자열과 다른 폼 필드가 차지하는 여유분.
MULTIPART_SLACK_BYTES = 1024 * 1024
_BODY_METHODS = {'POST', 'PUT', 'PATCH'}
```

`ClientApiView.dispatch` 의 인증 **앞에** 세 줄을 끼운다.

```python
    def dispatch(self, request, *args, **kwargs):
        rejection = self._precheck(request)
        if rejection is not None:
            return rejection
        if self.require_auth:
            ...  # 이하 Task 1 의 코드 그대로
```

`_precheck` 를 `_authenticate` 위에 더한다.

```python
    @staticmethod
    def _precheck(request):
        """인증보다 **먼저** 거절해야 하는 것(계약 §8·R9-2).

        본문을 읽지 않고 선언된 길이로만 판단한다. 인증을 통과하지 못할 요청이
        수십 MB 를 먼저 쓰게 하지 않으려는 것이고, 상한 숫자를 따로 적지 않고
        MAX_IMAGE_BYTES 에서 계산하는 것은 상수를 올렸을 때 이 가드가 먼저 막아
        원인을 찾기 어려워지는 일을 막으려는 것이다.
        """
        if request.method not in _BODY_METHODS:
            return None
        declared = request.META.get('CONTENT_LENGTH')
        if not declared:
            return error('LENGTH_REQUIRED', '요청 본문 길이(Content-Length)가 필요하다.', 411)
        try:
            length = int(declared)
        except (TypeError, ValueError):
            return error('LENGTH_REQUIRED', '요청 본문 길이가 올바르지 않다.', 411)
        if length > MAX_IMAGE_BYTES + MULTIPART_SLACK_BYTES:
            return error('IMAGE_TOO_LARGE', '요청 본문이 상한을 넘었다.', 413)
        return None
```

파일 맨 끝(`serialize_inspection` 위)에 404 뷰를 더한다. `ClientApiView` 를 상속하지 **않는다** — 선검사·인증·테넌트가 모두 불필요하고, 상속하면 없는 경로에 411 이 먼저 나갈 수 있다.

```python
class V1NotFoundView(View):
    """`/api/v1` 아래 미지 경로(R9-1).

    봉투 없이 나가면 Client 는 "서버 응답을 해석할 수 없음"으로 처리한다. 지금은
    없는 경로가 범용 `api/<task>/<view>` 에 먹혀 401 HTML, 또는 Django 기본
    404 HTML(DEBUG 면 전체 URL 패턴이 인증 없이 보인다)로 나간다.
    """

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return error('NOT_FOUND', '없는 경로다.', 404)
```

- [ ] **Step 4: 라우트를 더한다**

`configurations/urls.py` 의 import 에 `V1NotFoundView` 를 더하고, `v1-overlay-image` 바로 **뒤**에 넣는다.

```python
    # 미지 `/api/v1` 경로도 봉투로 답한다(R9-1). 위치가 동작을 바꾼다 —
    # 구체 v1 라우트 **뒤**, 범용 `api/<task>/<view>` **앞**이어야 한다.
    # 앞에 두면 정상 Endpoint 가 전부 404 가 되고, 뒤에 두면 2-segment 경로가
    # 범용 라우트에 먹혀 401 HTML 이 된다.
    path('api/v1/<path:rest>', V1NotFoundView.as_view(), name='v1-not-found'),
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python manage.py test tests.test_client_api --settings=configurations.test_settings`
Expected: PASS. `test_client_packages_는_범용_api_라우트에_먹히지_않는다` 는 지금 404 봉투로 통과하고, Task 6 에서 200 목록으로 바뀐다

- [ ] **Step 6: 커밋**

```bash
git add app/views/api_v1.py configurations/urls.py tests/test_client_api.py
git commit -m "$(printf 'fix: /api/v1 미지 경로를 404 봉투로, 본문 선검사를 인증보다 먼저\n\n없는 경로가 범용 api/<task>/<view> 에 먹혀 401 HTML 또는 Django 기본\n404 HTML 로 나가 Client 가 해석하지 못했다(R9-1). catch-all 라우트를\n구체 라우트 뒤·범용 라우트 앞에 넣는다.\n\nContent-Length 없는 요청(chunked)은 411, 상한 초과는 413 으로 인증보다\n먼저 거절한다(R9-2).\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 4: `GET /api/v1/inspections/<id>/heatmap` (R7)

**Files:**
- Modify: `app/views/api_v1.py` (`InspectionHeatmapView` 신규)
- Modify: `configurations/urls.py` (`v1-inspection-by-request` 뒤)
- Test: `tests/test_client_api.py` (`HeatmapTest` 신규)

**Interfaces:**
- Consumes: `ClientApiView`, `VisionInspection`
- Produces: `InspectionHeatmapView`. 라우트 이름 `v1-inspection-heatmap`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
class HeatmapTest(ClientApiTestCase):
    def test_인증이_필요하다(self):
        inspection_id = self._submit().json()['data']['id']
        response = self.http.get(f'/api/v1/inspections/{inspection_id}/heatmap')
        self.assertEqual(response.status_code, 401)

    def test_없는_검사는_INSPECTION_NOT_FOUND(self):
        response = self.http.get('/api/v1/inspections/no-such-id/heatmap',
                                 **self._headers())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'INSPECTION_NOT_FOUND')

    def test_남의_검사는_INSPECTION_NOT_FOUND(self):
        inspection_id = self._submit().json()['data']['id']
        other_key = secrets.token_urlsafe(24)
        with tenant_atomic(self.tenant):
            VisionClient.objects.create(
                client_id='CLIENT-OTHER', name='다른 Client',
                api_key_hash=hashlib.sha256(other_key.encode()).hexdigest())
        response = self.http.get(f'/api/v1/inspections/{inspection_id}/heatmap',
                                 HTTP_X_CLIENT_ID='CLIENT-OTHER', HTTP_X_API_KEY=other_key)
        self.assertEqual(response.status_code, 404)
        # 남의 것인지 아예 없는지 구분해 주지 않는다.
        self.assertEqual(response.json()['error']['code'], 'INSPECTION_NOT_FOUND')

    def test_내_검사라도_heatmap_이_없으면_HEATMAP_NOT_FOUND(self):
        inspection_id = self._submit().json()['data']['id']
        response = self.http.get(f'/api/v1/inspections/{inspection_id}/heatmap',
                                 **self._headers())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'HEATMAP_NOT_FOUND')

    def test_응답에_heatmap_url_을_넣지_않는다(self):
        # 필드가 없으면 Client 는 이 Endpoint 를 호출하지 않는다 — GPU 미연결 상태의 계약이다.
        self.assertNotIn('heatmap_url', self._submit().json()['data'])
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python manage.py test tests.test_client_api.HeatmapTest --settings=configurations.test_settings -v2`
Expected: FAIL — 라우트가 없어 `NOT_FOUND`(Task 3 의 catch-all)가 돌아온다

- [ ] **Step 3: 뷰를 더한다**

`InspectionByRequestView` 아래에 넣는다.

```python
class InspectionHeatmapView(ClientApiView):
    """`GET /api/v1/inspections/<id>/heatmap` (R7).

    GPU 가 Stub 이라 heatmap 이 생기는 경로가 없고 저장 컬럼도 없다 — 소유 확인을
    통과한 모든 검사가 `HEATMAP_NOT_FOUND` 다. 응답에 `heatmap_url` 을 넣지 않으므로
    Client 는 이 경로를 호출하지 않는다. 라우트는 "경로가 없어 404 HTML" 을 없애고
    GPU 가 붙을 때 내부만 채우면 되게 하려는 것이다(DEC-C5).
    """

    http_method_names = ['get']

    def get(self, request, inspection_id):
        inspection = VisionInspection.objects.filter(pk=str(inspection_id)).first()
        if inspection is None or inspection.client_id != request.vision_client.id:
            # 존재 여부를 노출하지 않으려 둘을 같은 코드로 답한다(계약 §9).
            return error('INSPECTION_NOT_FOUND', '검사를 찾을 수 없다.', 404)
        return error('HEATMAP_NOT_FOUND', 'Heatmap 이 없다.', 404)
```

- [ ] **Step 4: 라우트를 더한다**

`configurations/urls.py` — import 에 `InspectionHeatmapView` 를 더하고 `v1-inspection-by-request` **뒤**, catch-all **앞**에 넣는다.

```python
    path('api/v1/inspections/<str:inspection_id>/heatmap', InspectionHeatmapView.as_view(),
         name='v1-inspection-heatmap'),
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python manage.py test tests.test_client_api --settings=configurations.test_settings`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add app/views/api_v1.py configurations/urls.py tests/test_client_api.py
git commit -m "$(printf 'feat: Heatmap 이미지 Endpoint 추가 (GPU 미연결 상태의 404 봉투)\n\n경로가 없어 404 HTML 이 나가 Client 가 해석하지 못했다(R7). 소유 확인은\n실제로 하고, heatmap 이 없으면 HEATMAP_NOT_FOUND 를 낸다.\n\nGPU 가 Stub 이라 지금은 모든 검사가 HEATMAP_NOT_FOUND 다. 응답에\nheatmap_url 을 넣지 않으므로 Client 는 호출하지 않는다.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 5: 배포물을 static 트리 밖으로 옮기고 설정을 더한다 (R6 준비)

**Files:**
- Move: `app/static/distribution/` → `distribution/`
- Modify: `.gitignore`, `configurations/settings.py`, `.env.example`
- Rewrite: `distribution/README.md`

**Interfaces:**
- Produces: `settings.DISTRIBUTION_ROOT: Path`. Task 6·7 의 뷰가 **요청 시점에** 이 값을 읽는다

- [ ] **Step 1: 옮기기 전 상태를 확인한다**

```bash
ls app/static/distribution/licenses app/static/distribution/client
python -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','configurations.settings');django.setup();from django.contrib.staticfiles.finders import find;print('static 트리에서 보인다:', find('distribution/README.md'))"
```

Expected: 파일 5개가 보이고, `find()` 가 **경로를 출력한다**(= `collectstatic` 이 1.07GB 를 복사하고 whitenoise 가 `/static/distribution/...` 로 내보내는 상태)

- [ ] **Step 2: 옮긴다**

`git mv` 가 아니라 `mv` 다 — 배포물은 Git 에 없다.

```bash
mv app/static/distribution distribution
ls distribution/licenses distribution/client
```

- [ ] **Step 3: `.gitignore` 를 고친다**

마지막 줄 `app/static/distribution`(개행 없음)을 아래로 **교체**한다. `distribution/` 한 줄로 막으면 Git 에 남겨야 하는 `SHA256SUMS.txt` 와 `README.md` 까지 사라진다.

```gitignore
distribution/**/*.zip
distribution/**/*.tar.xz
```

- [ ] **Step 4: 제외가 맞는지 확인한다**

```bash
git check-ignore -v distribution/licenses/qt-everywhere-src-6.11.2.tar.xz
git check-ignore -v distribution/client/VisionInspectionClient-0.1.4-beta-20261002.zip
git check-ignore distribution/licenses/SHA256SUMS.txt; echo "SHA256SUMS 종료코드=$? (1 이어야 한다)"
python -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','configurations.settings');django.setup();from django.contrib.staticfiles.finders import find;print('static 트리에서 보인다:', find('distribution/README.md'))"
```

Expected: 배포물 2개는 패턴에 걸리고, `SHA256SUMS.txt` 는 **종료코드 1**(제외되지 않음), `find()` 는 **`None`**

- [ ] **Step 5: 설정을 더한다**

`configurations/settings.py` 의 `STORAGE_ROOT` 아래에 넣는다.

```python
# API 로 내려주는 배포물. licenses/(LGPL 대응 소스)·client/(Client 배포 zip).
# `app/static/` 아래 두지 않는다 — collectstatic 이 1GB 를 STATIC_ROOT 로 복사하고
# whitenoise 가 `/static/distribution/...` 로 같은 파일을 두 번째 경로로 내보낸다.
DISTRIBUTION_ROOT = Path(env('DISTRIBUTION_ROOT', str(BASE_DIR / 'distribution')))
```

`.env.example` 의 `STORAGE_ROOT=` 아래에 넣는다.

```dotenv
# API 로 내려주는 배포물(LGPL 대응 소스·Client zip) 위치.
# 비우면 저장소의 distribution/ 을 쓴다. 운영은 /var/lib/manufacturing-ai-platform/distribution
DISTRIBUTION_ROOT=
```

- [ ] **Step 6: `distribution/README.md` 를 이 프로젝트 기준으로 다시 쓴다**

지금 내용은 구 서버 문서가 그대로 복사돼 `server/distribution/` 과 `/var/lib/vision-inspection/` 을 가리킨다. 아래로 **전체 교체**한다.

```markdown
# distribution

`/api/v1` 로 내려주는 배포물을 두는 곳이다. 위치는 `DISTRIBUTION_ROOT` 로 바꾼다
(기본값은 이 폴더). **`app/static/` 아래 두지 않는다** — `collectstatic` 이 1GB 를
복사하고 whitenoise 가 `/static/...` 으로 같은 파일을 두 번째 경로로 내보낸다.

| 폴더 | 내용 | API |
|---|---|---|
| `client/` | Windows Client 배포 zip | `GET /api/v1/client-packages` |
| `licenses/` | Qt/PySide6 LGPL 대응 소스 | `GET /api/v1/licenses/sources` |

**이 폴더의 파일은 인증 없이 공개된다.** 소스를 받을 권리는 바이너리를 받은 사람
전부에게 있고(LGPLv3), 설치 전 PC 에는 API Key 가 없다. 내부망 한정은 방화벽이
지킨다 — 앱에 IP 허용 목록을 따로 두지 않는다.

넣으면 안 되는 것: API Key·비밀번호·인증서·`.env` 가 들어간 zip, 공개할 수 없는
문서나 데이터.

## Git

배포물(`*.zip`·`*.tar.xz`)은 넣지 않는다 — 루트 `.gitignore` 가 확장자로 제외한다.
**`SHA256SUMS.txt` 와 이 README 는 넣는다.** 어떤 파일이 어떤 해시로 있어야 하는지가
이력으로 남고, 운영에 반입한 파일이 맞는지 이 파일로 대조한다.

## 파일을 넣을 때

1. 파일명에 버전과 날짜를 넣는다. 예: `VisionInspectionClient-0.1.4-beta-20261002.zip`
2. 같은 폴더의 `SHA256SUMS.txt` 를 갱신한다.
   ```bash
   cd distribution/client
   sha256sum *.zip > SHA256SUMS.txt
   sha256sum -c SHA256SUMS.txt
   ```
3. `SHA256SUMS.txt` 변경만 커밋한다.

`SHA256SUMS.txt` 는 `<해시>  <파일명>` 또는 `<해시> *<파일명>` 을 한 줄에 하나씩 적는다.
형식이 틀린 줄은 버려지고, 그 파일의 목록 응답 `sha256` 이 `null` 이 된다.

## 보존 기간

LGPL 대응 소스는 **마지막 배포 후 3년간** 지우지 않는다. 자동 삭제 작업이 이 폴더에
닿지 않아야 한다(요청서 R3).

## 운영

반입 파일은 `/var/lib/manufacturing-ai-platform/distribution` 에 두고
`DISTRIBUTION_ROOT` 로 가리킨다. 복사 후 **Git 에 있는 `SHA256SUMS.txt` 와 대조**한다.
절차는 [docs/08_DEPLOYMENT.md](../docs/08_DEPLOYMENT.md).
```

- [ ] **Step 7: 기존 테스트가 깨지지 않았는지 본다**

Run: `python manage.py test tests --settings=configurations.test_settings`
Expected: PASS (설정 2줄 추가라 영향이 없어야 한다)

- [ ] **Step 8: 커밋**

```bash
git add .gitignore configurations/settings.py .env.example distribution/README.md distribution/client/SHA256SUMS.txt distribution/licenses/SHA256SUMS.txt
git status --short   # 배포물(zip·tar.xz)이 스테이징되지 않았는지 눈으로 확인한다
git commit -m "$(printf 'chore: 배포물을 static 트리 밖 distribution/ 으로 옮긴다\n\napp/static/ 아래 두면 collectstatic 이 1.07GB 를 STATIC_ROOT 로 복사하고\nwhitenoise 가 /static/distribution/... 으로 같은 파일을 두 번째 경로로\n내보낸다. DISTRIBUTION_ROOT 설정으로 위치를 바꿀 수 있게 한다.\n\n.gitignore 는 distribution/ 한 줄로 막지 않는다 — SHA256SUMS.txt 와 README\n까지 사라진다. 확장자(zip·tar.xz)로 제외한다.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 6: 배포물 목록 Endpoint 2개 (R6 앞쪽)

**Files:**
- Modify: `app/views/api_v1.py` (`distribution_files`, `_recorded_checksums`, 목록 뷰 3개)
- Modify: `configurations/urls.py` (catch-all **앞**)
- Test: `tests/test_client_api.py` (`DistributionListTest` 신규)

**Interfaces:**
- Consumes: `settings.DISTRIBUTION_ROOT` (Task 5), `ClientApiView.require_auth`·`use_tenant` (Task 1), `data()` 헬퍼
- Produces: `distribution_files(folder: str) -> list[dict]` — 각 항목은 `{'name': str, 'path': Path, 'size_bytes': int, 'sha256': str | None}`. Task 7 의 다운로드 뷰가 같은 함수로 파일을 찾는다. `CHECKSUM_FILENAME: str`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`shutil`·`tempfile`·`Path` 는 Task 2 에서 이미 더했다.

```python
class DistributionTestCase(TestCase):
    """배포물 Endpoint 는 인증도 테넌트도 쓰지 않는다. 가짜 폴더만 필요하다.

    1GB 실파일은 쓰지 않는다 — 수십 바이트로 목록·Range 동작이 다 드러난다.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='dist-test-'))
        (self.root / 'licenses').mkdir()
        (self.root / 'licenses' / 'fake-src.tar.xz').write_bytes(b'0123456789')
        (self.root / 'licenses' / 'SHA256SUMS.txt').write_text(
            '{}  fake-src.tar.xz\n'.format('a' * 64), encoding='utf-8')
        (self.root / 'client').mkdir()
        # client/ 에는 SHA256SUMS.txt 를 두지 않는다 — sha256 이 null 로 나와야 한다.
        (self.root / 'client' / 'Client-0.1.4.zip').write_bytes(b'zipzipzip')

        self.override = override_settings(DISTRIBUTION_ROOT=self.root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.http = Client()


class DistributionListTest(DistributionTestCase):
    def test_licenses_목록은_인증없이_200(self):
        response = self.http.get('/api/v1/licenses/sources')
        self.assertEqual(response.status_code, 200)
        rows = response.json()['data']
        # 이름순. 'SHA256SUMS.txt' < 'fake-src.tar.xz'
        self.assertEqual([row['filename'] for row in rows],
                         ['SHA256SUMS.txt', 'fake-src.tar.xz'])

    def test_목록_항목은_4개_필드를_낸다(self):
        rows = self.http.get('/api/v1/licenses/sources').json()['data']
        archive = next(row for row in rows if row['filename'] == 'fake-src.tar.xz')
        self.assertEqual(archive['size_bytes'], 10)
        self.assertEqual(archive['sha256'], 'a' * 64)
        self.assertEqual(archive['download_url'],
                         '/api/v1/licenses/sources/fake-src.tar.xz')

    def test_SHA256SUMS_에_없는_파일은_sha256_이_null(self):
        rows = self.http.get('/api/v1/client-packages').json()['data']
        self.assertEqual(rows[0]['filename'], 'Client-0.1.4.zip')
        self.assertIsNone(rows[0]['sha256'])
        self.assertEqual(rows[0]['download_url'],
                         '/api/v1/client-packages/Client-0.1.4.zip')

    def test_SHA256SUMS_자신도_목록에_나온다(self):
        rows = self.http.get('/api/v1/licenses/sources').json()['data']
        checksum = next(row for row in rows if row['filename'] == 'SHA256SUMS.txt')
        self.assertIsNone(checksum['sha256'])

    def test_폴더가_없으면_빈_목록이다(self):
        empty = Path(tempfile.mkdtemp(prefix='dist-empty-'))
        self.addCleanup(shutil.rmtree, empty, True)
        with override_settings(DISTRIBUTION_ROOT=empty):
            response = self.http.get('/api/v1/licenses/sources')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], [])

    def test_형식이_틀린_SHA256SUMS_줄은_버린다(self):
        (self.root / 'licenses' / 'SHA256SUMS.txt').write_text(
            'deadbeef  fake-src.tar.xz\n', encoding='utf-8')   # 64자가 아니다
        rows = self.http.get('/api/v1/licenses/sources').json()['data']
        archive = next(row for row in rows if row['filename'] == 'fake-src.tar.xz')
        self.assertIsNone(archive['sha256'])
```

`EnvelopeTest.test_client_packages_는_범용_api_라우트에_먹히지_않는다` 를 아래로 **교체**한다(이제 목록이 나온다).

```python
    def test_client_packages_는_범용_api_라우트에_먹히지_않는다(self):
        # 범용 api/<task>/<view> 가 먼저 받으면 로그인 세션을 요구해 401 HTML 이 된다.
        response = self.http.get('/api/v1/client-packages')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'].split(';')[0], 'application/json')
        self.assertIn('data', response.json())
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python manage.py test tests.test_client_api.DistributionListTest --settings=configurations.test_settings -v2`
Expected: FAIL — `NOT_FOUND`(catch-all)가 돌아온다

- [ ] **Step 3: 폴더 읽기와 목록 뷰를 더한다**

`serialize_inspection` 위, `V1NotFoundView` 앞에 넣는다.

```python
CHECKSUM_FILENAME = 'SHA256SUMS.txt'
_SHA256_HEX_LENGTH = 64


def distribution_files(folder):
    """`DISTRIBUTION_ROOT/<folder>` **바로 아래** 파일 목록. 하위 폴더는 공개 대상이 아니다.

    `sha256` 은 서버가 계산한 값이 아니라 같은 폴더 `SHA256SUMS.txt` 에 적힌 값이다 —
    1GB 아카이브를 요청마다 해싱하면 목록 조회가 수 초씩 걸린다.

    설정은 **요청 시점에** 읽는다. 모듈 상수로 굳히면 테스트의 `override_settings` 가
    듣지 않아 실제 1GB 파일을 보게 된다.
    """
    root = Path(settings.DISTRIBUTION_ROOT) / folder
    if not root.is_dir():
        return []
    recorded = _recorded_checksums(root)
    return [{'name': path.name, 'path': path, 'size_bytes': path.stat().st_size,
             'sha256': recorded.get(path.name)}
            for path in sorted(root.iterdir(), key=lambda p: p.name) if path.is_file()]


def _recorded_checksums(root):
    """`<해시>  <파일명>`(텍스트)과 `<해시> *<파일명>`(바이너리) 줄을 읽는다."""
    checksum_file = root / CHECKSUM_FILENAME
    if not checksum_file.is_file():
        return {}
    recorded = {}
    for line in checksum_file.read_text(encoding='utf-8', errors='ignore').splitlines():
        parts = line.split()
        # 파일명이 없거나 해시 길이가 다른 줄은 어느 파일의 것인지 알 수 없으므로 버린다.
        if len(parts) == 2 and len(parts[0]) == _SHA256_HEX_LENGTH:
            recorded[parts[1].removeprefix('*')] = parts[0].lower()
    return recorded


class DistributionListView(ClientApiView):
    """배포물 목록(R6).

    **인증을 걸지 않는다.** LGPL 대응 소스를 받을 권리는 바이너리를 받은 사람 전부에게
    있어 API Key 를 요구하면 그 자체가 의무 이행에 조건을 다는 셈이고, 설치 전 검사 PC
    에는 Key 가 없다. 내부망 한정은 방화벽이 지킨다.
    """

    require_auth = False
    use_tenant = False
    http_method_names = ['get']
    folder = None
    url_prefix = None

    def get(self, request):
        return data([{'filename': found['name'],
                      'size_bytes': found['size_bytes'],
                      'sha256': found['sha256'],
                      'download_url': '{}/{}'.format(self.url_prefix, found['name'])}
                     for found in distribution_files(self.folder)])


class LicenseSourceListView(DistributionListView):
    folder = 'licenses'
    url_prefix = '/api/v1/licenses/sources'


class ClientPackageListView(DistributionListView):
    folder = 'client'
    url_prefix = '/api/v1/client-packages'
```

- [ ] **Step 4: 라우트를 더한다**

`configurations/urls.py` — import 에 `ClientPackageListView`, `LicenseSourceListView` 를 더하고 **catch-all 앞**에 넣는다.

```python
    # 배포·라이선스. 인증 없이 제공한다(R6). LGPL 고지문에 주소가 박혀 있어 바꾸지 않는다.
    path('api/v1/licenses/sources', LicenseSourceListView.as_view(), name='v1-license-sources'),
    path('api/v1/client-packages', ClientPackageListView.as_view(), name='v1-client-packages'),
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python manage.py test tests.test_client_api --settings=configurations.test_settings`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add app/views/api_v1.py configurations/urls.py tests/test_client_api.py
git commit -m "$(printf 'feat: 배포·라이선스 파일 목록 Endpoint 2개 추가\n\nlicenses/sources 는 라우트가 없어 404 HTML, client-packages 는 범용\napi/<task>/<view> 에 먹혀 401 HTML 이었다(R6). 인증 없이 목록을 낸다.\n\nsha256 은 서버가 계산하지 않고 같은 폴더 SHA256SUMS.txt 에 적힌 값을 읽는다 —\n1GB 아카이브를 요청마다 해싱하면 목록 조회가 수 초씩 걸린다.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 7: 배포물 다운로드와 HTTP Range (R6 뒤쪽)

**Files:**
- Modify: `app/views/api_v1.py` (`_parse_range`, `_file_chunks`, 다운로드 뷰 3개, 상단 import)
- Modify: `configurations/urls.py` (catch-all **앞**)
- Test: `tests/test_client_api.py` (`DistributionDownloadTest` 신규)

**Interfaces:**
- Consumes: `distribution_files()` (Task 6)
- Produces: `_parse_range(header: str | None, size: int) -> tuple[int, int] | str | None` — `(start, length)` / `'invalid'`(416) / `None`(전체 전송). `DOWNLOAD_CHUNK_BYTES: int`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
class DistributionDownloadTest(DistributionTestCase):
    URL = '/api/v1/licenses/sources/fake-src.tar.xz'

    @staticmethod
    def _body(response):
        return b''.join(response.streaming_content) if response.streaming \
            else response.content

    def test_인증없이_전체를_받는다(self):
        response = self.http.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._body(response), b'0123456789')
        self.assertEqual(response['Accept-Ranges'], 'bytes')
        self.assertIn('attachment', response['Content-Disposition'])

    def test_Range_로_이어받는다(self):
        response = self.http.get(self.URL, HTTP_RANGE='bytes=5-')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self._body(response), b'56789')
        self.assertEqual(response['Content-Range'], 'bytes 5-9/10')
        self.assertEqual(response['Content-Length'], '5')

    def test_닫힌_구간_Range(self):
        response = self.http.get(self.URL, HTTP_RANGE='bytes=2-4')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self._body(response), b'234')
        self.assertEqual(response['Content-Range'], 'bytes 2-4/10')

    def test_끝에서부터_세는_Range(self):
        response = self.http.get(self.URL, HTTP_RANGE='bytes=-3')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self._body(response), b'789')

    def test_파일_밖_Range_는_416(self):
        response = self.http.get(self.URL, HTTP_RANGE='bytes=999-')
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response['Content-Range'], 'bytes */10')
        self.assertEqual(response.json()['error']['code'], 'RANGE_NOT_SATISFIABLE')

    def test_다중_Range_는_전체를_보낸다(self):
        # multipart/byteranges 를 만들지 않는다. curl -C - 는 단일 범위만 쓴다.
        response = self.http.get(self.URL, HTTP_RANGE='bytes=0-1,5-6')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._body(response), b'0123456789')

    def test_해석할_수_없는_Range_는_전체를_보낸다(self):
        response = self.http.get(self.URL, HTTP_RANGE='items=0-1')
        self.assertEqual(response.status_code, 200)

    def test_없는_파일은_SOURCE_ARCHIVE_NOT_FOUND(self):
        response = self.http.get('/api/v1/licenses/sources/nope.tar.xz')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'SOURCE_ARCHIVE_NOT_FOUND')

    def test_없는_Client_배포본은_CLIENT_PACKAGE_NOT_FOUND(self):
        response = self.http.get('/api/v1/client-packages/nope.zip')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'CLIENT_PACKAGE_NOT_FOUND')

    def test_Client_배포본을_받는다(self):
        response = self.http.get('/api/v1/client-packages/Client-0.1.4.zip')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._body(response), b'zipzipzip')

    def test_경로_이탈은_내려주지_않는다(self):
        # 이름을 경로로 조립하지 않고 목록에서 찾으므로 폴더 밖으로 나갈 수 없다.
        secret = self.root / 'secret.txt'
        secret.write_bytes(b'do-not-serve')
        for path in ('/api/v1/licenses/sources/..',
                     '/api/v1/licenses/sources/../secret.txt',
                     '/api/v1/licenses/sources/..%2Fsecret.txt'):
            with self.subTest(path=path):
                response = self.http.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b'do-not-serve', self._body(response))
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python manage.py test tests.test_client_api.DistributionDownloadTest --settings=configurations.test_settings -v2`
Expected: FAIL — `NOT_FOUND`(catch-all)가 돌아온다

- [ ] **Step 3: Range 파서와 다운로드 뷰를 더한다**

상단 import 의 `from django.http import JsonResponse` 를 아래로 바꾼다(`OverlayImageView` 안의 지역 `FileResponse` import 는 건드리지 않는다).

```python
from django.http import FileResponse, JsonResponse, StreamingHttpResponse
```

Task 6 의 목록 뷰 아래에 넣는다.

```python
DOWNLOAD_CHUNK_BYTES = 64 * 1024


def _parse_range(header, size):
    """`Range` 헤더를 `(start, length)` 로 바꾼다.

    `(start, length)` — 부분 전송(206)
    `'invalid'` — 파일 밖 요청(416)
    `None` — 전체 전송(200). 헤더가 없거나 해석할 수 없거나 **다중 범위**인 경우다.

    단일 범위만 본다. 다중 범위(`bytes=0-1,5-6`)는 multipart/byteranges 를 만들어야
    하는데 쓰는 Client 가 없다 — `curl -C -` 도 브라우저 이어받기도 단일 범위다.
    Django 5.0.4 에는 Range 처리가 없어 여기서 직접 한다.
    """
    if not header or not header.startswith('bytes=') or ',' in header:
        return None
    spec = header[len('bytes='):].strip()
    try:
        if spec.startswith('-'):
            # 뒤에서 N 바이트. 파일보다 크게 요청하면 전체를 준다(RFC 9110).
            length = int(spec[1:])
            if length <= 0:
                return 'invalid'
            start = max(size - length, 0)
            return start, size - start
        first, separator, last = spec.partition('-')
        if not separator:
            return None
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return 'invalid'
    return start, min(end, size - 1) - start + 1


def _file_chunks(path, start, length):
    """파일의 일부를 조각내 흘려보낸다. 1GB 를 메모리에 올리지 않는다."""
    with path.open('rb') as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            block = handle.read(min(DOWNLOAD_CHUNK_BYTES, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


class DistributionDownloadView(ClientApiView):
    """배포물 다운로드(R6). 인증을 걸지 않는다 — `DistributionListView` 와 같은 이유다."""

    require_auth = False
    use_tenant = False
    http_method_names = ['get']
    folder = None
    not_found_code = None

    def get(self, request, filename):
        # 이름을 경로로 조립하지 않는다. 목록에서 이름이 같은 파일을 찾으므로
        # `../` 가 섞인 이름은 목록에 있을 수 없고, 폴더 밖으로 나갈 방법이 구조적으로 없다.
        found = next((f for f in distribution_files(self.folder) if f['name'] == filename), None)
        if found is None:
            return error(self.not_found_code, '보관 중인 파일이 아니다.', 404)

        size = found['size_bytes']
        requested = _parse_range(request.headers.get('Range'), size)

        if requested == 'invalid':
            response = error('RANGE_NOT_SATISFIABLE', '요청한 범위가 파일 밖이다.', 416)
            response['Content-Range'] = 'bytes */{}'.format(size)
            response['Accept-Ranges'] = 'bytes'
            return response

        if requested is None:
            response = FileResponse(found['path'].open('rb'), as_attachment=True,
                                    filename=found['name'])
            response['Accept-Ranges'] = 'bytes'
            return response

        start, length = requested
        response = StreamingHttpResponse(_file_chunks(found['path'], start, length),
                                         status=206, content_type='application/octet-stream')
        response['Content-Range'] = 'bytes {}-{}/{}'.format(start, start + length - 1, size)
        response['Content-Length'] = str(length)
        response['Accept-Ranges'] = 'bytes'
        response['Content-Disposition'] = 'attachment; filename="{}"'.format(found['name'])
        return response


class LicenseSourceDownloadView(DistributionDownloadView):
    folder = 'licenses'
    not_found_code = 'SOURCE_ARCHIVE_NOT_FOUND'


class ClientPackageDownloadView(DistributionDownloadView):
    folder = 'client'
    not_found_code = 'CLIENT_PACKAGE_NOT_FOUND'
```

- [ ] **Step 4: 라우트를 더한다**

`configurations/urls.py` — import 에 두 뷰를 더하고 목록 라우트 **뒤**, catch-all **앞**에 넣는다.

```python
    path('api/v1/licenses/sources/<str:filename>', LicenseSourceDownloadView.as_view(),
         name='v1-license-source-download'),
    path('api/v1/client-packages/<str:filename>', ClientPackageDownloadView.as_view(),
         name='v1-client-package-download'),
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python manage.py test tests.test_client_api --settings=configurations.test_settings`
Expected: PASS

- [ ] **Step 6: 실제 파일로 인수 확인 — 서버가 필요하므로 사용자에게 넘긴다**

아래 명령을 사용자에게 전달하고 **직접 돌리지 않는다**(1GB 전송이라 시간을 묶을 수 없다).

```bash
python manage.py runserver 127.0.0.1:8123        # 별도 터미널
curl -s http://127.0.0.1:8123/api/v1/licenses/sources | head -40
cd /tmp && curl --max-time 20 -OJ http://127.0.0.1:8123/api/v1/licenses/sources/qt-everywhere-src-6.11.2.tar.xz   # 중간에 끊긴다
curl -C - -OJ http://127.0.0.1:8123/api/v1/licenses/sources/qt-everywhere-src-6.11.2.tar.xz   # 이어받기
curl -OJ http://127.0.0.1:8123/api/v1/licenses/sources/SHA256SUMS.txt
sha256sum -c --ignore-missing SHA256SUMS.txt
```

Expected: 마지막 줄이 `qt-everywhere-src-6.11.2.tar.xz: OK`

- [ ] **Step 7: 커밋**

```bash
git add app/views/api_v1.py configurations/urls.py tests/test_client_api.py
git commit -m "$(printf 'feat: 배포물 다운로드와 HTTP Range 이어받기 추가\n\nQt 소스 1GB·Client zip 85MB 를 끊긴 지점부터 이어받을 수 있어야 한다(R6).\nDjango 5.0.4 에는 Range 처리가 없어 직접 구현한다 — 단일 범위만 보고,\n다중 범위는 multipart/byteranges 대신 전체를 보낸다.\n\n경로 이탈은 이름을 경로로 조립하지 않고 목록에서 찾는 방식으로 막는다.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 8: Client 회신문 `docs/client/SERVER_RESPONSES.md`

**Files:**
- Create: `docs/client/SERVER_RESPONSES.md`

**Interfaces:**
- Consumes: Task 1~7 의 실제 동작. **구현을 끝낸 뒤에 쓴다** — 추측으로 쓰면 Client 가 그 문서로 계약을 갱신해 버린다

- [ ] **Step 1: 실제 응답을 떠서 문서에 넣을 값을 확보한다**

```bash
python manage.py test tests.test_client_api --settings=configurations.test_settings
python - <<'PY'
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'configurations.test_settings'
django.setup()
from django.test.utils import setup_test_environment, teardown_test_environment
from django.test.runner import DiscoverRunner
setup_test_environment()
runner = DiscoverRunner(verbosity=0)
old = runner.setup_databases()
from django.test import Client
http = Client()
print('health:', http.get('/api/v1/health').json())
print('404:', http.get('/api/v1/nope').json())
runner.teardown_databases(old)
teardown_test_environment()
PY
```

Expected: health 가 최상위 4키, 404 가 `NOT_FOUND` 봉투. **이 출력을 문서의 예시로 쓴다**

- [ ] **Step 2: 회신문을 쓴다**

요청서의 "회신 방법"대로 항목 번호별 **처리 결과 / 결정 사항 / 바뀐 API 규격**을 적는다. 아래 결론을 그대로 쓴다.

| 항목 | 회신 내용 |
|---|---|
| R1 | **별건으로 분리.** 이 서버(`:8123`)는 개발 서버로 남기고 TLS 는 별도 운영 인스턴스에서 적용한다. 되돌려 보낼 질문: 인증서 방식 A/B/C(**B·C 면 CA PEM 전달 + Client 코드 변경**), 최종 주소·컷오버 일정, Key 전량 재발급 일정과 전달 경로, 인증 실패 rate limit·CORS·노출 범위. **`licenses/sources` 주소는 0.1.4 고지문에 박혀 있어 바꾸면 재빌드다 — 바꾸기 전에 알린다** |
| R2 | **확정.** `retryable: true` 로 나가는 응답은 **`500 INTERNAL_ERROR` 하나**다. 429 는 미구현(R5 참고), 503·504 는 서버가 내지 않는다 — 앞단에 nginx 를 두면 봉투 없는 5xx 로 올 수 있다. `RECEIVED` 구분: **GPU 미연결이라 모델이 매핑된 검사항목도 영구히 `RECEIVED`** 다. 폴링해도 바뀌지 않으므로 재조회를 끄는 편이 낫다. GPU 연결 시 구분 수단을 함께 정한다 |
| R3 | **보관은 유지.** 파일은 `DISTRIBUTION_ROOT`(운영 `/var/lib/manufacturing-ai-platform/distribution`)에 두고 이미지 보존 정책과 **무관**하다 — 이미지 삭제 작업은 `ImageAsset` 만 본다. 되돌려 보낼 질문: 3년 보존을 백업·보존 정책에 넣을 주체, 사외(고객사) 접근 허용 여부 |
| R4 | **제공하지 않음으로 확정.** `meta.count`·`CLIENT_VERSION_UNSUPPORTED` 둘 다. 계약 문서에서 삭제해 달라. `client_version` 은 계속 저장만 한다 |
| R5 | **수정 완료.** `AUTH_REQUIRED`(두 헤더 중 하나라도 없음)와 `AUTH_INVALID`(없는 `client_id`·키 불일치·비활성)를 구분한다. 헤더 이름은 `X-Client-ID`·`X-API-Key` 그대로다. **자격증명은 재발급이 필요하다** — 구 서버(`:8005`)의 `CLIENT-001` 키는 이 서버에 등록돼 있지 않다. 발급 값은 담당자에게 직접 전달한다 |
| R6 | **추가 완료.** 4개 Endpoint 모두 인증 없음. 목록 형식·`sha256`(`SHA256SUMS.txt` 기록값, 없으면 `null`)·Range 이어받기·404 코드 전부 요청대로다. **파일 3개 반입 완료**(Qt 1,019,661,552 / PySide 18,053,248 / Client zip 85,246,226 bytes, 해시 대조됨). 416 응답은 `RANGE_NOT_SATISFIABLE` 봉투 + `Content-Range: bytes */<size>` 다(계약에 없던 코드라 알린다) |
| R7 | **라우트 추가 완료, 이미지는 아직 없음.** `GET /api/v1/inspections/{id}/heatmap` 이 소유 확인을 하고 404 `INSPECTION_NOT_FOUND`/`HEATMAP_NOT_FOUND` 봉투를 낸다. **GPU 추론이 미연결이라 ANOMALY 모델이 매핑돼 있지 않고 `heatmap_url` 이 응답에 나오지 않는다**(R7-3 의 답). 필드가 없으면 호출하지 않는 지금 동작을 유지해 달라 |
| R8 | **계약 형식으로 맞췄다.** Client 변경 없음. 실패 시 503 + `status:"degraded"` + 실패 항목만 `"error"`, 이 503 만 봉투가 아니다 |
| R9 | ①**수정 완료** — `/api/v1` 아래 미지 경로는 404 `NOT_FOUND` 봉투다. ②**수정 완료** — `Content-Length` 없는 요청은 인증보다 먼저 411 `LENGTH_REQUIRED`, 상한 초과는 413 `IMAGE_TOO_LARGE`. **본문 상한은 33MiB(이미지 32MiB + multipart 여유)로 계약(21MiB)보다 넓다.** ③DEBUG 는 운영 인스턴스에서 끈다(R1 과 함께). ④`/openapi.json`·`/docs` 는 **제공하지 않는다** — 이 서버는 Django 이고 Schema 를 생성하지 않는다. `docs/client/SERVER_API_CONTRACT.md` 와 이 회신문이 정본이다 |

이어서 **"Client 가 맞춰야 하는 차이"** 절을 둔다. 서버 현 구조를 정본으로 두기로 했으므로(DEC-C2) spec §6 의 9행 표를 그대로 옮기고, 각 행에 실제 응답 JSON 예시를 붙인다. `data.id`(≠ `inspection_id`)와 overlay `data.image`(≠ `image_url`, `updated_at` 없음)를 가장 앞에 둔다.

마지막에 **바뀐 Endpoint 의 요청·응답 예시와 오류 코드 표**를 싣는다(요청서가 요구한 형식).

- [ ] **Step 3: 커밋**

```bash
git add docs/client/SERVER_RESPONSES.md
git commit -m "$(printf 'docs: Client 작업 요청 R1~R9 회신문 작성\n\n항목별 처리 결과와 바뀐 API 규격, 서버 현 구조를 정본으로 둔 차이 9건을\n적었다. R1(TLS)·R3(보존 정책)은 운영 결정이 필요한 질문으로 돌려보낸다.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

### Task 9: 프로젝트 문서 갱신과 전체 검증

**Files:**
- Modify: `docs/08_DEPLOYMENT.md`, `docs/USER_DECISIONS.md`, `docs/IMPLEMENTATION_STATUS.md`

- [ ] **Step 1: 배포 문서에 배포물 반입 절차를 더한다**

먼저 `docs/08_DEPLOYMENT.md` 를 읽어 기존 절 구조를 확인하고, 같은 형식으로 아래 내용을 넣는다.

- `DISTRIBUTION_ROOT=/var/lib/manufacturing-ai-platform/distribution` 를 `.env` 에 넣는다
- `licenses/`·`client/` 를 만들고 배포물을 복사한 뒤 **Git 의 `SHA256SUMS.txt` 와 `sha256sum -c` 로 대조**한다
- 이 폴더는 **인증 없이 공개**된다. 내부망 한정은 방화벽이 지킨다
- LGPL 대응 소스는 **마지막 배포 후 3년** 보존한다. 자동 삭제가 닿지 않게 한다
- 운영 인스턴스는 `DEBUG=False` + `ALLOWED_HOSTS` 실제 호스트명. 개발 서버(`:8123`)는 `DEBUG=True` 를 유지한다

- [ ] **Step 2: 결정을 기록한다**

`docs/USER_DECISIONS.md` §1.6 의 기존 행 형식을 읽고 같은 형식으로 10건을 더한다 — spec 의 DEC-C1~C10 표를 옮긴다. `docs/IMPLEMENTATION_STATUS.md` 에는 `/api/v1` Endpoint 가 7개에서 **13개**로 늘었고(health·catalog·catalog/version·inspections·by-request·heatmap·overlay 2개·배포물 4개 + catch-all), heatmap 은 라우트만임을 적는다.

- [ ] **Step 3: 전체 검증을 돌린다**

```bash
python manage.py test tests --settings=configurations.test_settings
python scripts/verify_permission_map.py
python scripts/verify_menu.py
node scripts/verify_screen_js.js
```

Expected: 네 개 모두 통과. 화면·템플릿을 건드리지 않았으므로 `verify_tokens.py`·`verify_modals.py`·`capture_ui.py` 는 돌리지 않는다

- [ ] **Step 4: 남은 검증 명령을 사용자에게 넘긴다**

서버가 필요한 것들이다. 돌리지 않고 전달한다.

```bash
python -m pytest tests/e2e -q
python scripts/capture_ui.py /tmp/ui-after
```

- [ ] **Step 5: 커밋**

```bash
git add docs/08_DEPLOYMENT.md docs/USER_DECISIONS.md docs/IMPLEMENTATION_STATUS.md
git commit -m "$(printf 'docs: 배포물 반입 절차와 결정 10건(DEC-C1~C10) 기록\n\n/api/v1 Endpoint 가 7개에서 13개로 늘었다. 배포물은 인증 없이 공개되고\nLGPL 대응 소스는 3년 보존이 필요하므로 자동 삭제가 닿지 않게 한다.\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

---

## 전체 작업 후 상태

| Endpoint | 인증 | 상태 |
|---|---|---|
| `GET /api/v1/health` | 없음 | 계약 형식 + 503 degraded |
| `GET /api/v1/catalog`, `catalog/version` | 필요 | 변경 없음 |
| `POST /api/v1/inspections` | 필요 | 411·413 선검사 추가 |
| `GET /api/v1/inspections/by-request/<request_id>` | 필요 | 변경 없음 |
| `GET /api/v1/inspections/<id>/heatmap` | 필요 | **신규** — 항상 404 봉투 |
| `GET /api/v1/overlays/<id>`, `<id>/image` | 필요 | 변경 없음 |
| `GET /api/v1/licenses/sources`, `/<filename>` | 없음 | **신규** — Range 지원 |
| `GET /api/v1/client-packages`, `/<filename>` | 없음 | **신규** — Range 지원 |
| `/api/v1/<그 외>` | 없음 | **신규** — 404 `NOT_FOUND` 봉투 |
