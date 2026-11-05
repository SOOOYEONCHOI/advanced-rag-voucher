"""Playwright E2E 공통 설정.

**실행 중인 서버에 붙는다.** Django 테스트 러너가 아니라 pytest 로 돌린다.

    python manage.py runserver 127.0.0.1:8123
    python manage.py seed_initial --admin-password <PW>
    python manage.py seed_demo
    pytest tests/e2e -q

주의: 실제 DB를 쓴다. 개발/검증 DB 에서만 돌려라.
"""
import json
import os
import pathlib
import subprocess
import sys
import textwrap
import time

import pytest
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get('E2E_BASE_URL', 'http://127.0.0.1:8123')
ROOT = pathlib.Path(__file__).resolve().parents[2]


def _secret(filename, env_key):
    value = os.environ.get(env_key)
    if value:
        return value
    path = ROOT / filename
    if path.exists():
        return path.read_text(encoding='utf-8').strip()
    pytest.skip(f'{filename} 이 없다. 비밀번호를 적어 둔다(DEVELOPMENT §1.4).')


@pytest.fixture(scope='session')
def base_url():
    return BASE_URL


@pytest.fixture(scope='session')
def admin_password():
    return _secret('.admin_pw', 'E2E_ADMIN_PASSWORD')


# 관리자가 아닌 사용자 — 테스트가 계정·그룹을 만들고 끝나면 지운다(표본 작업자 계정은 seed_demo 에서 뺐다).
# 데이터 화면만 받는다: 홈·데이터 목록·라벨링 W, 검수·스냅샷 R. 비전검사항목 관리·시스템 관리는 없다.
WORKER_MENUS = {'wm_dashboard': 'RW', 'wm_data_item_detail': 'RW', 'wm_data_image': 'RW', 'wm_data_labeling': 'RW',
                'wm_data_review': 'R', 'wm_data_snapshot': 'R'}
WORKER_CLEAN = textwrap.dedent("""
    from django.contrib.auth.models import User
    from domain.models.system import LoginLog
    from domain.models.user import UserGroup
    from domain.tenancy import tenant_atomic
    with tenant_atomic():
        for user in User.objects.filter(username='e2e-worker'):
            # 화면의 사용자 삭제와 같다 — 로그인 기록은 아이디로 남기고 연결만 끊는다(DO_NOTHING 외래키)
            LoginLog.objects.filter(User=user).update(Username=user.username, User=None)
            user.delete()
        UserGroup.objects.filter(Code='e2e-workers').delete()""")


@pytest.fixture(scope='session')
def worker():
    """{'username', 'password'} — 관리자가 아닌 작업자 계정."""
    import secrets
    password = secrets.token_urlsafe(12)
    manage_shell(WORKER_CLEAN + textwrap.dedent(f"""
        from domain.models.user import UserGroupMenu
        group = UserGroup.objects.create(Code='e2e-workers', Name='E2E 작업자')
        for code, auth in {WORKER_MENUS!r}.items():
            UserGroupMenu.objects.create(UserGroup=group, MenuCode=code, AuthCode=auth)
        user = User.objects.create_user('e2e-worker', password={password!r})
        user.userprofile.UserGroup = group
        user.userprofile.save()"""))
    try:
        yield {'username': 'e2e-worker', 'password': password}
    finally:
        manage_shell(WORKER_CLEAN)


@pytest.fixture(scope='session')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(
            headless=os.environ.get('E2E_HEADED') != '1')
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={'width': 1600, 'height': 1000},
                                  locale='ko-KR')
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
    page.console_errors = errors
    yield page
    context.close()


def login(page, base_url, username, password):
    """로그인하고 셸이 뜰 때까지 기다린다."""
    page.goto(f'{base_url}/login/', wait_until='domcontentloaded')
    page.fill('#loginId', username)
    page.fill('#loginPwd', password)
    page.click('#login')
    page.wait_for_url(f'{base_url}/', timeout=15000)
    # 좌측 메뉴는 폴더 아코디언이다. 권한이 없는 계정은 폴더가 하나도 없을 수
    # 있으므로 셸 컨테이너만 확인하고 렌더를 잠깐 기다린다.
    page.wait_for_selector('#sideNavAll', state='attached', timeout=15000)
    page.wait_for_timeout(900)


def manage_shell(code):
    """`manage.py shell -c` 로 서버 쪽 정리를 한다. 화면에 삭제 기능이 없는 것(Client 자격증명·검사 기록)에 쓴다."""
    env = dict(os.environ, DB_CONN_MAX_AGE='0')
    done = subprocess.run([sys.executable, 'manage.py', 'shell', '-c', code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-1000:]
    return done.stdout


# seed_demo 의 냉각팬 패널 검사항목. id 는 DB 마다 달라 코드로 찾는다.
DEMO_CODES = {'ano': 'FAN-PANEL', 'cls': 'FAN-PANEL-CLS', 'det': 'FAN-PANEL-DET'}


@pytest.fixture(scope='session')
def demo():
    """{'ano': id, 'cls': id, 'det': id}. 경로의 `{det}`·`{ano}`·`{cls}` 를 `.format(**demo)` 로 채운다."""
    out = manage_shell('import json\nfrom domain.models.data import InspectionItem\nfrom domain.tenancy import tenant_atomic\n'
                       'with tenant_atomic():\n'
                       f'    print(json.dumps(dict(InspectionItem.objects.filter(code__in={list(DEMO_CODES.values())!r})'
                       '.values_list("code", "id"))))')
    ids = json.loads(out.strip().splitlines()[-1])
    missing = [code for code in DEMO_CODES.values() if code not in ids]
    if missing:
        pytest.skip(f'seed_demo 비전검사항목이 없다: {missing}. seed_demo 를 먼저 돌려라.')
    return {key: ids[code] for key, code in DEMO_CODES.items()}


@pytest.fixture
def inspection(base_url):
    """검사 기록 하나 — `E2E-INSP-` 클라이언트·검사항목으로 보낸다. 검사 이력 화면 테스트가 개발 DB 에
    남은 기록에 기대지 않게 한다. 끝나면 검사 기록 → 검사항목 → 클라이언트 순으로 지운다."""
    import requests
    from scripts.dev.send_inspections import defect_jpeg, metadata

    tag = f'E2E-INSP-{int(time.time() * 1000)}'
    out = manage_shell(textwrap.dedent(f"""
        import hashlib, json, secrets
        from app.views.vision.client import _create_service_account
        from domain.models.data import InspectionItem
        from domain.models.vision import VisionClient
        from domain.tenancy import tenant_atomic
        key = secrets.token_urlsafe(32)
        with tenant_atomic() as tenant:
            item = InspectionItem.objects.create(tenant=tenant, code={tag!r}, name={tag!r},
                                                 task_type='OBJECT_DETECTION', status='ACTIVE')
        VisionClient.objects.create(client_id={tag!r}, name={tag!r}, api_key_hash=hashlib.sha256(key.encode()).hexdigest(),
                                    service_account=_create_service_account({tag!r}, {tag!r}))
        print(json.dumps({{'item_id': item.id, 'api_key': key}}))"""))
    created = json.loads(out.strip().splitlines()[-1])
    try:
        response = requests.post(f'{base_url}/api/v1/inspections', timeout=30,
                                 headers={'X-Client-ID': tag, 'X-API-Key': created['api_key']},
                                 files={'image': ('capture.jpg', defect_jpeg('scratch', seed=tag), 'image/jpeg')},
                                 data={'metadata': json.dumps(metadata(tag, created['item_id']))})
        assert response.status_code == 201, response.text[:300]
        yield {'client_id': tag, 'item_name': tag}
    finally:
        manage_shell(textwrap.dedent(f"""
            from django.contrib.auth.models import User
            from domain.models.vision import VisionClient, VisionInspection
            from domain.services.data.item_platform import ItemPlatformService
            from domain.tenancy import tenant_atomic
            VisionInspection.objects.filter(client__client_id={tag!r}).delete()
            ItemPlatformService.delete_item({created['item_id']})
            VisionClient.objects.filter(client_id={tag!r}).delete()
            with tenant_atomic():
                User.objects.filter(username={'svc-' + tag.lower()!r}).delete()"""))
