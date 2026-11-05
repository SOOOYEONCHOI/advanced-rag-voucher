"""브라우저 워크플로우 검증.

실행 중인 서버를 실제 브라우저로 돌린다. 단위 테스트가 못 잡는 것을 본다:
템플릿이 실제로 렌더되는가, 화면 JS 가 오류 없이 도는가, iframe 셸에서
화면이 열리는가, API 응답을 화면이 읽어 그리는가.

    python manage.py runserver 127.0.0.1:8123
    pytest tests/e2e -q
"""
import pytest

from tests.e2e.conftest import login

DATA_SCREENS = [
    ('wm_data_item', '검사 분류'),
    ('wm_data_image', '데이터 관리'),
    ('wm_data_labeling', '라벨링'),
    ('wm_data_review', '검수'),
    ('wm_data_snapshot', '스냅샷'),
]
VISION_SCREENS = [
    ('wm_dashboard', '대시보드'),
    ('wm_vis_inspection', '비전 검사 이력'),
    ('wm_vis_client', '비전검사 클라이언트 관리'),
    ('wm_vis_overlay', 'Overlay'),
]
SYSTEM_SCREENS = [
    ('wm_depart', '부서 정보'),
    ('wm_user', '사용자'),
    ('wm_user_group', '사용자 그룹'),
    ('wm_code', '코드정보'),
    ('wm_unit', '단위정보'),
]


def blocking_errors(page):
    """화면 동작을 막는 콘솔 오류만 남긴다."""
    return [e for e in page.console_errors
            if 'favicon' not in e and 'Failed to load resource' not in e]


class TestLogin:
    def test_로그인하면_셸과_메뉴가_뜬다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        folders = page.locator('#sideNavAll .side-nav-item > a')
        assert folders.count() > 0, '좌측 메뉴가 비었다'
        assert folders.first.is_visible(), '좌측 메뉴가 보이지 않는다'

    def test_틀린_비밀번호는_로그인되지_않는다(self, page, base_url):
        page.goto(f'{base_url}/login/', wait_until='domcontentloaded')
        page.fill('#loginId', 'admin')
        page.fill('#loginPwd', 'definitely-wrong-password')
        page.click('#login')
        page.wait_for_timeout(1500)
        assert '/login' in page.url, '틀린 비밀번호로 로그인이 됐다'

    def test_미인증_상태로_화면에_직접_접근할_수_없다(self, page, base_url):
        response = page.goto(f'{base_url}/gui/wm_user/', wait_until='domcontentloaded')
        assert response.status in (401, 403), f'미인증 접근이 {response.status} 로 통과했다'


@pytest.mark.parametrize('gui_code,label', DATA_SCREENS + VISION_SCREENS + SYSTEM_SCREENS)
class TestScreens:
    def test_화면이_JS_오류_없이_열린다(self, page, base_url, admin_password, gui_code, label):
        login(page, base_url, 'admin', admin_password)
        response = page.goto(f'{base_url}/gui/{gui_code}/', wait_until='networkidle')
        assert response.status == 200, f'{label}: HTTP {response.status}'
        assert page.locator('body').count() == 1

        errors = blocking_errors(page)
        assert not errors, f'{label}: JS 오류 {errors[:3]}'

    def test_화면이_권한_오류를_내지_않는다(self, page, base_url, admin_password,
                                          gui_code, label):
        """화면 JS 가 부르는 API 경로가 권한 표에 빠져 있으면 여기서 잡힌다."""
        login(page, base_url, 'admin', admin_password)
        page.goto(f'{base_url}/gui/{gui_code}/', wait_until='networkidle')
        page.wait_for_timeout(1200)
        body = page.locator('body').inner_text()
        assert '권한 설정이 없는 기능' not in body, f'{label}: 매핑 없는 API 를 부른다'
        assert '권한이 없' not in body, f'{label}: 관리자인데 권한 거부가 났다'


class TestMenuNavigation:
    def test_폴더를_펼쳐_화면을_열_수_있다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)

        # 좌측 메뉴는 폴더 아코디언이다. 접힌 상태가 기본이라 먼저 펼친다.
        folder = page.locator('#sideNavAll .side-nav-item > a').first
        folder.wait_for(state='visible', timeout=10000)
        folder.click()

        leaf = page.locator('#sideNavAll .menu-leaf-link').first
        leaf.wait_for(state='visible', timeout=10000)
        title = leaf.inner_text().strip()
        mid = leaf.get_attribute('data-mid')
        leaf.click()

        # 첫 탭(대시보드) iframe 은 새 탭이 열리면 가려진다 — 연 메뉴의 iframe 을 본다
        assert page.wait_for_selector(f'#mnb_iframe_{mid}', timeout=10000), f'{title} 탭이 열리지 않았다'

    def test_메뉴_폴더가_권한만큼_보인다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        labels = ' '.join(page.locator('#sideNavAll .side-nav-item > a').all_inner_texts())
        for expected in ('대시보드', '검사 작업', '검사 관리', '비전 데이터 관리', '기준정보', '시스템 관리'):
            assert expected in labels, f'{expected} 폴더가 없다'


class TestDataWorkflow:
    """검사항목 → 이미지 → 라벨링 대기열 흐름."""

    def test_검사항목_화면에_시드_검사항목이_보인다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        page.goto(f'{base_url}/gui/wm_data_item/', wait_until='networkidle')
        page.wait_for_timeout(1500)
        # 트리가 길어 화면 밖 행은 그리지 않는다 — 목록 행 데이터로 본다
        codes = page.evaluate("() => page.rows.filter(r => r.kind === 'item').map(r => r.code)")
        assert 'FAN-PANEL-DET' in codes, '시드 비전검사항목이 화면에 없다'

    def test_데이터_관리_화면_골격이_뜬다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        page.goto(f'{base_url}/gui/wm_data_image/', wait_until='networkidle')
        page.wait_for_timeout(1500)
        assert page.locator('#main-grid').count() == 1

    def test_비전_검사_이력은_요약_카드_없이_목록이_바로_보인다(self, page, base_url, admin_password):
        """요약 카드를 지워 조회 조건 바로 아래가 검사 목록이다(사용자 결정 2026-10-21)."""
        login(page, base_url, 'admin', admin_password)
        page.goto(f'{base_url}/gui/wm_vis_inspection/', wait_until='networkidle')
        page.wait_for_timeout(1500)
        assert page.locator('#summaryCards').count() == 0
        assert page.locator('#insp-grid .wzg-container').count() == 1

    def test_Client_전송_검사가_검사_결과_목록에_나온다(self, page, base_url, admin_password, inspection):
        login(page, base_url, 'admin', admin_password)
        page.goto(f'{base_url}/gui/wm_vis_inspection/', wait_until='networkidle')
        page.wait_for_timeout(2000)
        content = page.content()
        assert inspection['client_id'] in content, 'Client 가 보낸 검사가 목록에 없다'


class TestPermission:
    def test_작업자는_사용자_관리_화면에_들어갈_수_없다(self, page, base_url, worker):
        login(page, base_url, worker['username'], worker['password'])
        response = page.goto(f'{base_url}/gui/wm_user/', wait_until='domcontentloaded')
        assert response.status == 403, f'권한 없는 화면이 {response.status} 로 열렸다'

    def test_작업자_메뉴에는_데이터_관리만_보인다(self, page, base_url, worker):
        login(page, base_url, worker['username'], worker['password'])
        labels = ' '.join(page.locator('#sideNavAll .side-nav-item > a').all_inner_texts())
        assert '비전 데이터 관리' in labels, '작업자에게 비전 데이터 관리 메뉴가 없다'
        assert '시스템 관리' not in labels, '권한 없는 메뉴가 보인다'

    def test_작업자도_라벨링_화면은_열_수_있다(self, page, base_url, worker):
        login(page, base_url, worker['username'], worker['password'])
        response = page.goto(f'{base_url}/gui/wm_data_labeling/', wait_until='domcontentloaded')
        assert response.status == 200, f'작업자가 라벨링 화면에 못 들어간다: {response.status}'
