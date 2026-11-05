"""WeZonGrid 화면 공통 동작 — 컬럼이 그리드 폭을 채운다, 쌓이는 목록은 서버 페이징이다.

컬럼 폭은 화면마다 고정 px 로 정의돼 있어 합이 그리드보다 작으면 오른쪽이 빈다.
`GridUtil.fitWidth` 가 남는 폭을 정의 폭 비율대로 나눈다(창 폭이 바뀌면 다시 맞춘다).
"""
from datetime import date, timedelta

import pytest

from tests.e2e.conftest import login, manage_shell

# 메뉴에 보이는 그리드 화면. 데이터 화면은 검사항목이 있어야 열린다.
SCREENS = ['wm_depart', 'wm_user', 'wm_user_group', 'wm_user_group_menu', 'wm_menu_language', 'wm_login_log',
           'wm_menu_log', 'wm_system_log', 'wm_data_item',
           'wm_vis_inspection', 'wm_vis_client', 'wm_vis_overlay',
           'wm_data_image/?inspection_item={ano}', 'wm_data_review/?inspection_item={ano}', 'wm_data_snapshot/?inspection_item={ano}']
# 메뉴에서 내렸지만 주소로는 열리는 화면(seed_initial RETIRED_FROM_MENU). 같은 구조를 지킨다.
RETIRED = ['wm_code', 'wm_unit', 'wm_company', 'wm_multi_language', 'wm_prop_master']

# 보이는 그리드마다 (마지막 헤더 셀 오른쪽 끝, 본문 오른쪽 끝 — 세로 스크롤 막대 제외)
GAPS_JS = """() => [...document.querySelectorAll('.wzg-container')].filter(c => c.offsetParent).map(c => {
    const body = c.querySelector('.wzg-body-scroll');
    const heads = [...c.querySelectorAll('th')].filter(th => th.offsetParent && th.getBoundingClientRect().width > 0);
    const right = Math.max(...heads.map(th => th.getBoundingClientRect().right));
    const bodyRect = body.getBoundingClientRect();
    return {id: c.parentElement.id, gap: Math.round(bodyRect.left + body.clientWidth - right),
            scroll: body.scrollWidth > body.clientWidth};
})"""


def filled(found):
    """오른쪽이 비지 않았다 — 폭이 맞거나, 컬럼 합이 그리드보다 넓어 가로 스크롤이다(fitWidth 는 정의 폭을 둔다)."""
    return all(abs(g['gap']) <= 2 or (g['gap'] < 0 and g['scroll']) for g in found)


def gaps(page):
    return page.evaluate(GAPS_JS)


@pytest.mark.parametrize('screen', SCREENS + RETIRED)
def test_컬럼이_그리드_폭을_채운다(page, base_url, admin_password, demo, screen):
    login(page, base_url, 'admin', admin_password)
    path = screen.format(**demo) if '/' in screen else screen + '/'
    page.goto(f'{base_url}/gui/{path}', wait_until='networkidle')
    page.wait_for_timeout(800)
    found = gaps(page)
    assert found, '보이는 그리드가 없다'
    assert filled(found), found
    # 창 폭이 바뀌면 다시 맞춘다
    page.set_viewport_size({'width': 1500, 'height': 911})
    page.wait_for_timeout(600)
    found = gaps(page)
    assert filled(found), found


def test_숨은_탭의_그리드도_보일_때_폭을_채운다(page, base_url, admin_password):
    """메뉴로그의 목록 탭은 처음에 숨어 있고, 탭을 열 때 화면이 grid.resize() 를 부른다(폭을 정의 폭으로 되돌린다)."""
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_menu_log/', wait_until='networkidle')
    page.wait_for_timeout(800)
    tabs = page.locator('.nav-link')
    for index in range(tabs.count()):
        if tabs.nth(index).is_visible():
            tabs.nth(index).click()
            page.wait_for_timeout(700)
            found = gaps(page)
            assert found and all(abs(g['gap']) <= 2 for g in found), (index, found)


def test_남는_폭을_정의_폭_비율대로_나눈다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_vis_inspection/', wait_until='networkidle')
    page.wait_for_timeout(800)
    widths = page.evaluate("""() => Object.fromEntries(page.grid._columnManager.getVisibleColumns()
        .map(c => [c.dataField, c.width]))""")
    # 정의: created_at 150, item_name 200, status_label 200
    assert abs(widths['item_name'] / widths['created_at'] - 200 / 150) <= 0.02 * 200 / 150, widths
    assert abs(widths['status_label'] / widths['created_at'] - 200 / 150) <= 0.02 * 200 / 150, widths
    assert widths['created_at'] > 150, widths


def test_검사_이력은_오늘을_포함한_최근_7일을_서버에서_20건씩_받는다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    with page.expect_response(lambda r: '/api/vision/inspection?action=list' in r.url) as listed:
        page.goto(f'{base_url}/gui/wm_vis_inspection/')
    response = listed.value
    week_ago = (date.today() - timedelta(days=6)).isoformat()   # 오늘 포함 7일(요약 카드와 같다)
    assert 'page_size=20' in response.url and f'date_from={week_ago}' in response.url, response.url
    body = response.json()
    assert len(body['rows']) <= 20 and 'totalRows' in body, body
    page.wait_for_timeout(500)
    assert page.input_value('#dateFrom') == week_ago
    pager = page.locator('#insp-grid .wzg-pager-info').inner_text()
    assert pager.endswith(f'/ 총 {body["totalRows"]:,}건'), pager


# (화면, 목록 API 조각, 그리드). 로그는 쌓이기만 하므로 50건씩 서버에서 받는다.
LOG_SCREENS = [('wm_menu_log', '/api/system/menulog?action=log_list', '#log-grid'),
               ('wm_login_log', '/api/system/loginlog', '#login-log-grid'),
               ('wm_system_log', '/api/system/systemlog', '#log-grid')]


@pytest.mark.parametrize('screen,api,grid', LOG_SCREENS)
def test_로그는_서버에서_50건씩_받는다(page, base_url, admin_password, screen, api, grid):
    login(page, base_url, 'admin', admin_password)
    listed = []
    page.on('response', lambda r: listed.append(r) if api in r.url else None)
    page.goto(f'{base_url}/gui/{screen}/', wait_until='networkidle')
    page.wait_for_timeout(500)
    assert len(listed) == 1, [r.url for r in listed]   # 열 때 한 번만 받는다
    assert 'page_size=50' in listed[0].url, listed[0].url
    body = listed[0].json()
    assert len(body['rows']) <= 50 and 'totalRows' in body, body
    assert page.locator(f'{grid} .wzg-pager-size-select').input_value() == '50'


@pytest.mark.parametrize('screen', ['wm_user', 'wm_user_group', 'wm_login_log', 'wm_menu_log', 'wm_system_log'])
def test_시스템_화면_목록_머리에_엑셀과_컬럼_설정_버튼이_없다(page, base_url, admin_password, screen):
    """공통 CRUD 화면 규칙(사용자 결정 2026-10-19). 서버의 엑셀 받기(export=1)는 남긴다."""
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/{screen}/', wait_until='networkidle')
    assert page.locator('#btnExcel, [id^="btnGridSetting"]').count() == 0


def test_메뉴로그_2페이지는_다음_50건이다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_menu_log/', wait_until='networkidle')
    page.click('a[href="#tab_log"]')
    first = page.locator('#log-grid .wzg-pager-info').inner_text()
    with page.expect_response(lambda r: 'action=log_list' in r.url and 'page=2' in r.url) as listed:
        page.locator('#log-grid .wzg-pager-btn', has_text='2').first.click()
    body = listed.value.json()
    assert first.startswith('1 ~ 50 /'), first
    assert len(body['rows']) == min(50, body['totalRows'] - 50)
    assert page.locator('#log-grid .wzg-pager-info').inner_text().startswith('51 ~ ')


# 검수·스냅샷은 조건에 맞는 전부를 받고 그리드가 20건씩 나눈다(화면 안 페이징). 비전검사항목 관리는 트리라 나누지 않는다.
WHOLE_SCREENS = [('wm_data_review/?inspection_item={ano}', '/api/item/review'),
                 ('wm_data_snapshot/?inspection_item={ano}', '/api/item/snapshot')]


@pytest.mark.parametrize('screen,api', WHOLE_SCREENS)
def test_작은_데이터_목록은_화면_안에서_나눈다(page, base_url, admin_password, demo, screen, api):
    login(page, base_url, 'admin', admin_password)
    path = screen.format(**demo) if '/' in screen else screen + '/'
    with page.expect_response(lambda r: api in r.url and 'action=list' in r.url) as listed:
        page.goto(f'{base_url}/gui/{path}')
    assert 'page_size' not in listed.value.url, listed.value.url
    body = listed.value.json()
    assert len(body['rows']) == body['totalRows'], body
    page.wait_for_timeout(500)
    assert page.evaluate('() => page.grid._isServerMode()') is False
    pager = page.locator('#main-grid .wzg-pager-info').inner_text()
    assert pager.endswith(f'/ 총 {body["totalRows"]:,}건'), pager


@pytest.fixture
def many_items():
    """검사항목 21개(E2E-PG-) — 한 페이지(20건)를 넘긴다. 이미지가 없어 바로 지운다."""
    manage_shell('from domain.models.data import InspectionItem\n'
                 'from domain.tenancy import current_tenant, tenant_atomic\n'
                 'with tenant_atomic():\n'
                 '    for i in range(21):\n'
                 '        InspectionItem.objects.create(tenant=current_tenant(), code=f"E2E-PG-{i:02}", name=f"E2E-페이지-{i:02}")')
    try:
        yield
    finally:
        manage_shell('from domain.models.data import InspectionItem\n'
                     'from domain.tenancy import tenant_atomic\n'
                     'with tenant_atomic():\n'
                     '    InspectionItem.objects.filter(code__startswith="E2E-PG-").delete()')


def test_다시_읽어도_고른_행을_놓치지_않는다(page, base_url, admin_password, many_items):
    """비전검사항목 관리: 비전검사항목 행을 골라 [수정]에서 사용을 끄고 저장하면 트리를 다시 읽고, 그 행이 계속 선택돼 있다."""
    from tests.e2e.test_crud import select_item
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_data_item/', wait_until='networkidle')
    select_item(page, 'E2E-페이지-20')
    page.wait_for_function("() => document.getElementById('code').value === 'E2E-PG-20'")
    page.click('#btnEdit')
    page.click('#active')       # 사용 → 중지
    with page.expect_response(lambda r: 'action=tree' in r.url and '/api/item/category' in r.url):
        page.click('#btnSave')
    page.wait_for_timeout(800)
    selected = page.evaluate('() => page.grid.getSelectedItems().map(i => i.code)')
    assert selected == ['E2E-PG-20'], selected
    assert page.evaluate("() => document.getElementById('code').value") == 'E2E-PG-20'



@pytest.mark.parametrize('screen', ['wm_vis_client', 'wm_vis_overlay'])
def test_비전_작은_목록은_20건씩_나눈다(page, base_url, admin_password, screen):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/{screen}/', wait_until='networkidle')
    page.wait_for_timeout(500)
    assert page.locator('#main-grid .wzg-pager-size-select').input_value() == '20'
    assert ' / 총 ' in page.locator('#main-grid .wzg-pager-info').inner_text()



# 화면마다 싣던 SheetJS(0.9MB)는 엑셀을 누를 때만, 셸의 차트·지도 JS 는 싣지 않는다.
HEAVY = ('xlsx', 'apexcharts', 'jsvectormap')


def test_엑셀_라이브러리는_엑셀을_누를_때만_싣는다(page, base_url, admin_password):
    loaded = []
    page.on('request', lambda r: loaded.append(r.url) if any(k in r.url for k in HEAVY) else None)
    login(page, base_url, 'admin', admin_password)
    page.wait_for_timeout(1500)
    page.goto(f'{base_url}/gui/wm_user/', wait_until='networkidle')
    assert loaded == [], loaded
    with page.expect_download() as downloaded:
        page.evaluate("() => GridUtil.exportExcel(page.grid, { fileName: 'e2e-users.xlsx' })")
    assert downloaded.value.suggested_filename == 'e2e-users.xlsx'
    assert [url for url in loaded if 'xlsx' in url], loaded
