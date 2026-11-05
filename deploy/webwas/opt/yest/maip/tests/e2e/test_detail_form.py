"""상세 영역 — [등록]·[수정]·[삭제], 행을 고르면 읽기 전용, [수정]을 누르면 [저장]·[취소].

비전검사 클라이언트 화면으로 본다. 테스트가 만든 `E2E-DF-` 클라이언트만 고치고 끝나면 지운다.
"""
import json
import time

import pytest

from tests.e2e.conftest import login
from tests.e2e.test_crud import mes
from tests.e2e.test_write_paths import CONFIRM_OK, confirm_ok, mes_get, open_gui, send_mes

VISIBLE = "(s) => [...document.querySelectorAll(s)].filter(e => e.offsetParent).map(e => e.id)"
BUTTONS = '#btnNew, #btnEdit, #btnDelete, #btnSave, #btnCancel, #btnReissue'


def shown(page):
    return page.evaluate(VISIBLE, BUTTONS)


def client_ids(page):
    return {row['client_id']: row['id'] for row in mes(page, '/api/vision/client?action=list&keyword=E2E-DF-')}


@pytest.fixture
def clients(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_vis_client')
    stamp = int(time.time() * 1000)
    names = [f'E2E-DF-{stamp}-A', f'E2E-DF-{stamp}-B']
    for name in names:
        assert mes(page, '/api/vision/client?action=save', {'client_id': name, 'name': name}).get('success')
    open_gui(page, base_url, 'wm_vis_client')
    try:
        yield names
    finally:
        for row_id in client_ids(page).values():
            mes(page, '/api/vision/client?action=delete', {'id': row_id})
        assert client_ids(page) == {}


def pick(page, name):
    page.locator('#main-grid').get_by_text(name, exact=True).first.click()
    page.wait_for_timeout(300)


def alert_text(page):
    page.wait_for_selector('#commonAlertModal.show', timeout=5000)
    text = page.inner_text('#commonAlertModalBody')
    page.click('#commonAlertModalOk')
    page.wait_for_selector('#commonAlertModal', state='hidden')
    return text


def test_고르면_읽기_전용이고_수정하면_저장_취소만_보인다(page, clients):
    assert sorted(shown(page)) == ['btnDelete', 'btnEdit', 'btnNew']
    # 고른 행 없이 [수정]·[삭제] → 안내만
    page.click('#btnEdit')
    assert '목록에서 항목을 선택해 주세요' in alert_text(page)
    assert sorted(shown(page)) == ['btnDelete', 'btnEdit', 'btnNew']

    pick(page, clients[0])
    assert page.is_disabled('#name') and page.is_disabled('#active') and page.is_disabled('#client_id')
    page.click('#btnEdit')
    assert sorted(shown(page)) == ['btnCancel', 'btnReissue', 'btnSave']
    assert page.is_enabled('#name') and page.is_enabled('#active') and page.is_disabled('#client_id')

    # [취소]는 원래 값으로 되돌린다
    page.fill('#name', '바꾸는 중')
    page.click('#btnCancel')
    assert page.input_value('#name') == clients[0] and page.is_disabled('#name')
    assert sorted(shown(page)) == ['btnDelete', 'btnEdit', 'btnNew']


def test_수정_중에_다른_행을_누르면_확인한다(page, clients):
    pick(page, clients[0])
    page.click('#btnEdit')
    page.fill('#name', '바꾸는 중')
    pick(page, clients[1])
    page.wait_for_selector('#commonConfirmModal.show')
    assert '수정 중인 내용' in page.inner_text('#commonConfirmModalBody')
    page.click('#commonConfirmModalCancel')
    page.wait_for_selector('#commonConfirmModal', state='hidden')
    assert page.input_value('#name') == '바꾸는 중' and page.is_enabled('#name')
    assert page.evaluate('() => page.grid.getSelectedItems().map(i => i.client_id)') == [clients[0]]
    # 확인하면 버리고 옮긴다
    pick(page, clients[1])
    confirm_ok(page)
    page.wait_for_timeout(300)
    assert page.input_value('#name') == clients[1] and page.is_disabled('#name')


def test_수정하고_저장하면_반영되고_읽기_전용으로_돌아간다(page, clients):
    pick(page, clients[0])
    page.click('#btnEdit')
    page.fill('#name', 'E2E-DF-바뀐-이름')
    page.uncheck('#active')
    body = send_mes(page, lambda: page.click('#btnSave'), 'client?action=save')
    assert body['success']
    page.wait_for_timeout(500)
    row = next(r for r in mes(page, '/api/vision/client?action=list&keyword=E2E-DF-') if r['client_id'] == clients[0])
    assert (row['name'], row['active']) == ('E2E-DF-바뀐-이름', False)
    assert page.is_disabled('#name') and page.input_value('#name') == 'E2E-DF-바뀐-이름'
    assert sorted(shown(page)) == ['btnDelete', 'btnEdit', 'btnNew']


def test_등록은_필수_값을_검사하고_삭제는_확인을_거친다(page, clients):
    page.click('#btnNew')
    page.wait_for_selector('#clientCreateModal.show')
    page.click('#btnCreateClient')
    assert '필수 항목을 입력해 주세요' in alert_text(page)
    assert page.evaluate("() => $('#clientCreateModal .is-invalid').length") == 2

    name = clients[0] + '-C'
    page.fill('#createClientId', name)
    page.fill('#createName', name)
    send_mes(page, lambda: page.click('#btnCreateClient'), 'client?action=save')
    page.wait_for_selector('#apiKeyModal.show')
    page.click('#apiKeyModal .btn-close')
    page.wait_for_timeout(500)

    pick(page, name)
    page.click('#btnDelete')
    send_mes(page, lambda: confirm_ok(page), 'client?action=delete')
    page.wait_for_timeout(500)
    assert name not in client_ids(page)


def test_검사_기록이_있어_삭제를_거절하면_사유를_보인다(page, clients):
    refused = {'success': False, 'message': '검사 기록이 있어 삭제할 수 없습니다. 사용을 해제해 주세요.'}
    pattern = '**/api/vision/client?action=delete'
    page.route(pattern, lambda route: route.fulfill(status=200, content_type='application/json', body=json.dumps(refused)))
    try:
        pick(page, clients[0])
        page.click('#btnDelete')
        page.wait_for_selector(CONFIRM_OK, state='visible')
        page.click(CONFIRM_OK)
        assert refused['message'] in alert_text(page)
    finally:
        page.unroute(pattern)   # 픽스처가 지울 때는 실제 요청이 나가야 한다


# ---- 비전 검사 화면 보완(2026-10-07): 토글·이미지 중심 상세·조회 버튼 위치·매핑 목록

RIGHT_GAP_JS = """(s) => { const b = document.querySelector(s); const box = b.closest('.card-body');
    const style = getComputedStyle(box);
    return Math.round(box.getBoundingClientRect().right - parseFloat(style.paddingRight) - b.getBoundingClientRect().right); }"""
HEIGHTS_JS = """([a, b]) => [document.querySelector(a).getBoundingClientRect().height,
                              document.querySelector(b).getBoundingClientRect().height].map(Math.round)"""


@pytest.mark.parametrize('screen', ['wm_vis_overlay', 'wm_data_review/?inspection_item={ano}',
                                    'wm_data_snapshot/?inspection_item={ano}'])
def test_검색_칸이_없으면_조회_버튼은_오른쪽_끝이다(page, base_url, admin_password, demo, screen):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/{screen.format(**demo) if "/" in screen else screen + "/"}', wait_until='networkidle')
    assert abs(page.evaluate(RIGHT_GAP_JS, '#btnSearch')) <= 2


def test_검사_이력_상세는_이미지와_표가_같은_높이다(page, base_url, admin_password, inspection):
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_vis_inspection')
    assert '상세 정보' in page.inner_text('#inspDetailTitle')
    page.locator('#insp-grid').get_by_text(inspection['client_id'], exact=True).first.click()
    page.wait_for_timeout(1200)
    image, table = page.evaluate(HEIGHTS_JS, ['#inspImageBox', '#inspDetail'])
    assert table > 100 and abs(image - table) <= 2, (image, table)


@pytest.mark.parametrize('abnormal, text, red', [(True, '이상', True), (False, '정상', False)])
def test_검사_이력_상세의_이상_판정은_굵게_이상이면_붉게_보인다(page, base_url, admin_password, abnormal, text, red):
    """상세 응답은 `page.route` 로 바꿔 넣는다 — 서버 데이터는 건드리지 않는다."""
    login(page, base_url, 'admin', admin_password)
    page.route('**/api/vision/inspection?action=detail*', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps({
            'id': 'e2e', 'request_id': 'e2e', 'item_code': 'X', 'item_name': 'X', 'client_id': 'X', 'client_version': '1',
            'status_label': '성공', 'model': 'm', 'abnormal': abnormal, 'anomaly_score': None, 'threshold': None,
            'inference_ms': None, 'capture_timestamp': '', 'camera': '', 'error_message': '', 'image_id': None})))
    try:
        open_gui(page, base_url, 'wm_vis_inspection')
        page.evaluate("() => page.showDetail('e2e')")
        cell = page.locator('#inspDetail tr', has_text='이상 판정').locator('td')
        cell.wait_for()
        assert cell.inner_text() == text
        assert page.evaluate("e => getComputedStyle(e).fontWeight", cell.element_handle()) == '700'
        classes = cell.get_attribute('class') or ''
        assert ('text-danger' in classes) == red, classes
    finally:
        page.unroute('**/api/vision/inspection?action=detail*')


def test_검사_이력_상세는_치수_측정의_측정점마다_한_줄이고_불합격은_붉다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    page.route('**/api/vision/inspection?action=detail*', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps({
            'id': 'e2e', 'request_id': 'e2e', 'item_code': 'X', 'item_name': 'X', 'client_id': 'X', 'client_version': '1',
            'status_label': '판정 완료', 'model': '', 'abnormal': True, 'anomaly_score': None, 'threshold': None,
            'inference_ms': None, 'capture_timestamp': '', 'camera': '', 'error_message': '', 'image_id': None,
            'measured': [{'label': '치수 A (A)', 'text': '540.32 mm (539~541) 합격', 'ok': True},
                         {'label': '치수 B (B)', 'text': '541.18 mm (539~541) 불합격', 'ok': False}]})))
    try:
        open_gui(page, base_url, 'wm_vis_inspection')
        page.evaluate("() => page.showDetail('e2e')")
        bad = page.locator('#inspDetail tr', has_text='측정 치수 B (B)').locator('td')
        bad.wait_for()
        assert bad.inner_text() == '541.18 mm (539~541) 불합격'
        assert 'text-danger' in (bad.get_attribute('class') or '')
        assert 'text-danger' not in (page.locator('#inspDetail tr', has_text='측정 치수 A (A)').locator('td').get_attribute('class') or '')
        assert page.locator('#inspDetail tr', has_text='모델').count() == 0
    finally:
        page.unroute('**/api/vision/inspection?action=detail*')


def test_클라이언트_사용은_토글이고_상태를_글로_보인다(page, clients):
    pick(page, clients[0])
    assert 'true' not in page.locator('#main-grid .wzg-body-scroll').inner_text()
    assert page.evaluate("() => $('#active').closest('.form-switch').length") == 1
    assert page.inner_text('#activeLabel') == '활성화'
    page.click('#btnEdit')
    page.uncheck('#active')
    assert page.inner_text('#activeLabel') == '비활성화'
    page.click('#btnCancel')
    assert page.inner_text('#activeLabel') == '활성화'
    # 토글은 옆 입력칸과 같은 줄(세로 가운데)에 있고 입력칸 높이에 어울리는 크기다
    toggle, box = page.evaluate("""() => ['#active', '#name'].map(s => {
        const r = document.querySelector(s).getBoundingClientRect(); return [r.top + r.height / 2, r.height]; })""")
    assert abs(toggle[0] - box[0]) <= 2 and toggle[1] >= 20, (toggle, box)


def test_Overlay_상세는_이미지_중심이고_표시는_토글이다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_vis_overlay')
    page.locator('#main-grid .wzg-body-scroll [role=row], #main-grid .wzg-body-scroll tr').first.click()
    page.wait_for_timeout(800)
    assert page.evaluate("() => $('#visible').closest('.form-switch').length") == 1
    assert page.inner_text('#visibleLabel') in ('활성화', '비활성화')
    image, table = page.evaluate(HEIGHTS_JS, ['#overlayImageBox', '#overlayDetail'])
    assert table > 100 and abs(image - table) <= 2, (image, table)
    # 읽기 모드에서는 파일 칸 대신 등록 여부를 글로 보이고, [수정]에서만 파일 칸이 보인다
    assert not page.is_visible('#image') and page.inner_text('#imageView') in ('등록됨', '-')
    assert page.input_value('#item_label').endswith(')')
    page.click('#btnEdit')
    assert page.is_visible('#image') and not page.is_visible('#imageView')
    page.click('#btnCancel')
    assert not page.is_visible('#image') and page.is_visible('#imageView')
    # 목록의 참/거짓 값은 글로 보인다
    cells = page.locator('#main-grid .wzg-body-scroll').inner_text()
    assert 'true' not in cells and 'false' not in cells, cells


def test_재발급_버튼은_API_Key_칸과_위아래가_맞고_칸은_다른_칸보다_좁다(page, clients):
    pick(page, clients[0])
    page.click('#btnEdit')
    key, button, client_id = page.evaluate("""() => ['#apiKeyMask', '#btnReissue', '#client_id'].map(s => {
        const r = document.querySelector(s).getBoundingClientRect(); return [Math.round(r.top), Math.round(r.bottom), Math.round(r.width)]; })""")
    assert abs(key[0] - button[0]) <= 1 and abs(key[1] - button[1]) <= 1, (key, button)
    assert key[2] < client_id[2], (key, client_id)


def test_클라이언트_관리의_등록은_목록_오른쪽_위_흰_바탕이고_배포본_받기가_그_오른쪽이다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_vis_client')
    assert page.locator('#btnNew').count() == 1 and page.locator('.upper-wezongrid #btnNew').count() == 1   # 상세 영역이 아니라 목록 머리
    new, packages = page.evaluate("""() => ['#btnNew', '#btnPackages'].map(s => {
        const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.right, Math.round(r.top)]; })""")
    assert new[1] <= packages[0] and new[2] == packages[2], (new, packages)
    grid_right = page.evaluate("() => document.querySelector('#main-grid').getBoundingClientRect().right")
    assert abs(grid_right - packages[1]) <= 2, (grid_right, packages)
    for selector in ('#btnNew', '#btnPackages'):
        assert page.evaluate("(s) => getComputedStyle(document.querySelector(s)).backgroundColor", selector) == 'rgb(255, 255, 255)'


def test_클라이언트_관리는_검색_칸_없이_조회_버튼만_오른쪽_끝이다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_vis_client')
    assert page.locator('#keyword').count() == 0
    assert abs(page.evaluate(RIGHT_GAP_JS, '#btnSearch')) <= 2
    assert '비전검사 클라이언트 관리' in page.inner_text('.header-title')


def test_클라이언트_관리에서_배포본_zip_을_받는다(page, base_url, admin_password):
    """목록·파일은 /api/v1/client-packages 그대로다(현장 PC 와 같은 경로). 85MB 를 다 받지 않고 첫 바이트만 본다."""
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_vis_client')
    page.click('#btnPackages')
    page.wait_for_selector('#clientPackageModal.show')
    page.wait_for_selector('#clientPackageModal tbody tr')
    packages = mes_get(page, '/api/v1/client-packages')['data']
    zips = [p for p in packages if p['filename'].endswith('.zip')]
    assert zips, '개발 서버 distribution/client 에 배포본 zip 이 있어야 한다'
    text = page.inner_text('#clientPackageModal tbody')
    assert zips[0]['filename'] in text and zips[0]['sha256'] in text and 'SHA256SUMS' not in text
    href = page.get_attribute('#clientPackageModal tbody a', 'href')
    assert href == zips[0]['download_url'], href
    first = page.request.get(base_url + href, headers={'Range': 'bytes=0-0'})
    assert first.status == 206 and first.body() == b'P'   # zip 은 'PK' 로 시작한다
    page.click('#clientPackageModal .modal-footer .btn-input')
    page.wait_for_selector('#clientPackageModal', state='hidden')


def test_API_Key_창은_바깥을_눌러도_닫히지_않는다(page, base_url, admin_password):
    """키는 이 창에서만 볼 수 있다. 실수로 닫히면 재발급해야 하므로 닫기 버튼으로만 닫는다."""
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_vis_client')
    page.evaluate("() => page.showKey('sample-only')")
    page.wait_for_selector('#apiKeyModal.show')
    page.wait_for_timeout(500)   # 여는 전환 중의 클릭은 Bootstrap 이 무시한다
    page.mouse.click(5, 5)   # 대화상자 밖(백드롭)
    page.wait_for_timeout(500)
    assert page.locator('#apiKeyModal.show').count() == 1
    page.click('#apiKeyModal .btn-close')
    page.wait_for_selector('#apiKeyModal', state='hidden')
    page.wait_for_timeout(500)   # 닫는 전환이 끝나 백드롭이 빠질 때까지
    page.evaluate("() => page.showKey('sample-only')")   # 다시 열어도 백드롭이 하나다
    page.wait_for_selector('#apiKeyModal.show')
    page.wait_for_timeout(500)
    assert page.locator('.modal-backdrop').count() == 1


# ---- 2026-10-07 보완 2차: 조회 조건이 없는 화면은 타이틀 아래에 요약 설명을 둔다

@pytest.mark.parametrize('screen', ['wm_vis_client', 'wm_vis_overlay'])
def test_조회_조건이_없는_화면은_요약_설명을_보인다(page, base_url, admin_password, screen):
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, screen)
    text = page.inner_text('#screenDescription')
    assert text.endswith('합니다.'), text
    assert abs(page.evaluate(RIGHT_GAP_JS, '#btnSearch')) <= 2
    # 설명과 [조회]는 한 줄이다
    desc, button = page.evaluate(HEIGHTS_JS.replace('.height', '.top'), ['#screenDescription', '#btnSearch'])
    assert abs(desc - button) <= 12, (desc, button)
