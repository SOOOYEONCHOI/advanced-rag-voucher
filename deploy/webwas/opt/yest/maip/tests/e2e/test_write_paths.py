"""화면의 쓰기 동작을 실제로 눌러 본다(G).

`capture_ui.py` 는 화면을 열기만 하고 `verify_links.py` 는 경로를 정적으로 본다.
F 단계에서 찾은 결함 6건(검사항목 추가 404, 관리자 승격 400, 권한 거부가
브라우저에 닿지 않음, 사용자 삭제 실패 …)은 전부 **눌러야 드러나는** 것이었다.

실제 DB 를 쓴다. 각 테스트는 `E2E-` 로 시작하는 자기 데이터만 만들고 끝에
지운다. seed 데이터는 바꾸지 않거나, 바꾸면 같은 테스트 안에서 되돌린다.
"""
import os
import re
import subprocess
import sys
import time

import pytest

from tests.e2e.conftest import ROOT, login, manage_shell
from tests.e2e import test_crud
from tests.e2e.test_crud import mes


def send(page, action, method='POST'):
    """`action()` 이 보내는 쓰기 요청의 응답을 기다려 성공인지 본다.

    알림 문구를 기다리면 직전 동작의 알림을 읽고 넘어갈 수 있다 — 응답을 기다린다.
    """
    with page.expect_response(lambda r: r.request.method == method and '/api/' in r.url,
                              timeout=15000) as info:
        action()
    response = info.value
    assert response.status < 400, (response.status, response.text()[:300])
    return response


def mes_get(page, url):
    """MES 화면 안에서 `/api/item/...` 조회를 부른다(로그인 쿠키를 화면 것으로 쓴다)."""
    return page.evaluate("""url => fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}})
        .then(r => r.json())""", url)


def run_worker_once():
    """스냅샷 Export 는 워커가 처리한다. 대기 작업을 한 번 비운다."""
    env = dict(os.environ, DB_CONN_MAX_AGE='0')
    done = subprocess.run([sys.executable, 'manage.py', 'run_worker', '--once'], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-1000:]


def detail(page, item_id):
    return test_crud.TestItemDeletionReview.detail(page, item_id)


def open_row(page, name):
    """비전검사항목 관리 트리에서 행을 누르고 상세 응답까지 기다린다.

    등록 직후 화면이 이미 그 행을 보이고 있어 이름만 기다리면, 늦게 온 상세 응답이 [수정] 모드를 풀었다.
    트리가 길어 화면 밖 행은 글자로 못 누르므로 행 데이터로 고른다(test_crud.select_item).
    """
    with page.expect_response(lambda r: '/api/item/item_admin' in r.url and 'action=detail' in r.url):
        test_crud.select_item(page, name)


def home_detail(page, item_id):
    """검사항목 홈 상세(라벨 클래스·설명). 화면 안에서 부른다."""
    return mes(page, f'/api/item/item_home?action=detail&item_id={item_id}')


@pytest.fixture
def item(page, base_url, admin_password):
    """화면에서 검사항목을 하나 만들고, 테스트가 끝나면 승인 삭제로 지운다.

    만든 뒤의 단언이 실패해도 지운다 — 실패한 실행이 실제 DB 에 흔적을 남기지 않게.
    """
    yield from created_item(page, base_url, admin_password)


@pytest.fixture
def measurement_item(page, base_url, admin_password):
    """등록 창에서 작업 유형을 치수 측정으로 골라 만든 검사항목. 지우는 것은 `item` 과 같다."""
    yield from created_item(page, base_url, admin_password, task_type='MEASUREMENT')


@pytest.fixture
def tablet_item(page, base_url, admin_password):
    """등록 창에서 촬영 방식을 태블릿으로 골라 만든 검사항목."""
    yield from created_item(page, base_url, admin_password, capture_method='TABLET')


def created_item(page, base_url, admin_password, task_type=None, capture_method=None):
    name = f'E2E-쓰기경로-{int(time.time() * 1000)}'
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_data_item/', wait_until='networkidle')
    page.click('#btnNew')
    page.wait_for_selector('#itemCreateModal.show')
    page.fill('#itemCreateName', name)
    if task_type:
        page.select_option('#itemCreateTaskType', task_type)
    if capture_method:
        page.select_option('#itemCreateCaptureMethod', capture_method)
    page.click('#btnCreateItem')
    page.wait_for_timeout(1500)
    rows = mes(page, '/api/item/item_admin?action=list&q=' + name)['rows']
    assert [r['name'] for r in rows] == [name]
    item_id = rows[0]['id']
    try:
        # 추가하고 나면 창이 닫혀야 목록을 누를 수 있다.
        assert page.locator('#itemCreateModal.show').count() == 0
        yield {'id': item_id, 'name': name}
    finally:
        page.goto(f'{base_url}/gui/wm_data_item/', wait_until='networkidle')
        test_crud.TestItemDeletionReview()._cleanup(page, item_id)
        assert detail(page, item_id) is None


class TestMeasurementItem:
    """치수 측정 비전검사항목 — 라벨 클래스 대신 측정점, 하위 메뉴는 홈·데이터 목록만(설계 2026-10-20)."""

    def test_좌측_메뉴는_홈이고_홈의_화면_버튼은_데이터_목록만이다(self, page, base_url, measurement_item):
        page.goto(f'{base_url}/', wait_until='networkidle')
        prefix = f"item{measurement_item['id']}_"
        page.wait_for_selector(f'#sideNavAll .menu-leaf-link[data-mid^="{prefix}"]', state='attached')
        mids = page.eval_on_selector_all(f'#sideNavAll .menu-leaf-link[data-mid^="{prefix}"]',
                                         'els => els.map(e => e.dataset.mid)')
        assert mids == [prefix + 'wm_data_item_detail']          # 비전검사항목은 홈 하나만(설계 2026-10-21 §4)
        screens = home_detail(page, measurement_item['id'])['screens']
        assert [s['code'] for s in screens] == ['wm_data_image']

    def test_홈에서_측정점을_추가_수정_삭제한다(self, page, base_url, measurement_item):
        item_id = measurement_item['id']
        page.goto(f'{base_url}/gui/wm_data_item_detail/?inspection_item={item_id}', wait_until='networkidle')
        assert page.inner_text('#labelTitle') == '측정점'
        assert page.locator('#summaryCards > div').count() == 1
        page.click('#btnEdit')
        page.wait_for_selector('#itemEditModal.show')
        page.click('#labelTab')
        assert page.inner_text('#labelTab') == '측정점'
        new = page.locator('#editLabels tr.point-new')
        for name, value in (('code', 'A'), ('name', 'E2E 치수 A'), ('nominal', '540'), ('lower', '539'), ('upper', '541')):
            new.locator(f'input[name="{name}"]').fill(value)
        assert new.locator('input[name="unit"]').input_value() == 'mm'
        send(page, lambda: new.get_by_role('button', name='추가').click())
        page.wait_for_selector('#editLabels tr.point-row')
        assert [(p['code'], p['upper']) for p in home_detail(page, item_id)['points']] == [('A', '541.000')]

        row = page.locator('#editLabels tr.point-row').first
        row.locator('input[name="upper"]').fill('541.5')
        send(page, lambda: row.get_by_role('button', name='저장').click())
        page.wait_for_function("() => document.querySelector('#labelBody').innerText.includes('541.500')")

        row = page.locator('#editLabels tr.point-row').first
        row.get_by_role('button', name='삭제').click()
        send(page, lambda: confirm_ok(page))
        page.wait_for_selector('#editLabels tr.point-row', state='detached')
        assert home_detail(page, item_id)['points'] == []

    def test_범위가_틀리면_저장하지_않고_알린다(self, page, base_url, measurement_item):
        item_id = measurement_item['id']
        page.goto(f'{base_url}/gui/wm_data_item_detail/?inspection_item={item_id}', wait_until='networkidle')
        page.click('#btnEdit')
        page.wait_for_selector('#itemEditModal.show')
        page.click('#labelTab')
        new = page.locator('#editLabels tr.point-new')
        for name, value in (('code', 'A'), ('name', '치수 A'), ('nominal', '540'), ('lower', '541'), ('upper', '539')):
            new.locator(f'input[name="{name}"]').fill(value)
        with page.expect_response(lambda r: 'point_create' in r.url) as info:
            new.get_by_role('button', name='추가').click()
        assert info.value.status == 400
        assert home_detail(page, item_id)['points'] == []


class TestItemAdmin:

    def test_배정_인원_카드와_추가_창이_없다(self, page, base_url, item):
        """비전검사항목 배정은 없앴다 — 메뉴 권한만 본다(사용자 결정 2026-10-21)."""
        open_row(page, item['name'])
        assert page.locator('#memberCard, #memberAddModal, #btnAddMember').count() == 0
        assert 'members' not in detail(page, item['id'])

    def test_수정에서_설명과_사용을_바꾸고_취소_저장_뒤에는_수정_버튼으로_돌아온다(self, page, base_url, item):
        # 상세 머리는 [수정]만 — 사용/중지는 버튼이 아니라 수정 모드의 토글이다(DESIGN §5.5)
        open_row(page, item['name'])
        page.wait_for_function(f"() => document.getElementById('name').value === {item['name']!r}")
        visible = "() => ['#btnEdit', '#btnCancel', '#btnSave'].filter(s => !document.querySelector(s).classList.contains('d-none'))"
        assert page.evaluate(visible) == ['#btnEdit'] and page.is_disabled('#description') and page.is_disabled('#active')
        assert page.get_by_role('button', name='중지', exact=True).count() == 0

        page.click('#btnEdit')
        assert page.evaluate(visible) == ['#btnCancel', '#btnSave'] and page.is_enabled('#description')
        page.fill('#description', '버릴 설명')
        page.click('#btnCancel')
        assert page.evaluate(visible) == ['#btnEdit'] and page.input_value('#description') == ''

        page.click('#btnEdit')
        page.fill('#description', '첫 줄\n둘째 줄')
        page.click('#active')       # 사용 → 중지
        send(page, lambda: page.click('#btnSave'))
        body = detail(page, item['id'])
        assert (body['status'], body['description']) == ('PAUSED', '첫 줄\n둘째 줄')
        page.wait_for_function("() => document.getElementById('status_label').value === '중지'")
        assert page.evaluate(visible) == ['#btnEdit'] and not page.is_checked('#active')

        page.click('#btnEdit')
        page.click('#active')
        send(page, lambda: page.click('#btnSave'))
        assert detail(page, item['id'])['status'] == 'ACTIVE'

    def test_촬영_방식은_등록_때_고르고_목록에_보이며_수정에서_바꾼다(self, page, base_url, tablet_item):
        label = "name => page.rows.find(r => r.kind === 'item' && r.item_name === name).capture_method_label"
        assert page.evaluate(label, tablet_item['name']) == '태블릿'      # 목록 행(트리가 길어 화면 밖일 수 있다)
        open_row(page, tablet_item['name'])
        page.wait_for_function(f"() => document.getElementById('name').value === {tablet_item['name']!r}")
        assert page.input_value('#capture_method') == 'TABLET' and page.is_disabled('#capture_method')
        page.click('#btnEdit')
        page.select_option('#capture_method', 'RIG')
        send(page, lambda: page.click('#btnSave'))
        assert detail(page, tablet_item['id'])['capture_method'] == 'RIG'
        page.wait_for_function(f"() => ({label})({tablet_item['name']!r}) === '고정 거치대'")

    def test_AI_모델은_수정을_누를_때_Wezard_배포_모델을_읽는다(self, page, base_url, item):
        """비전검사항목 모델 매핑 화면과 같은 매핑을 상세에서 고친다(사용자 결정 2026-10-21). 저장은 하지 않는다."""
        open_row(page, item['name'])
        page.wait_for_function(f"() => document.getElementById('name').value === {item['name']!r}")
        assert page.is_visible('#model_name') and page.is_disabled('#model_name')
        assert page.eval_on_selector_all('#model_name option', 'els => els.map(e => e.textContent)') == ['(매핑 없음)']
        with page.expect_response(lambda r: '/api/item/item_admin' in r.url and 'action=models' in r.url) as response:
            page.click('#btnEdit')
        body = response.value.json()
        page.wait_for_timeout(300)
        options = page.eval_on_selector_all('#model_name option', 'els => els.map(e => e.value)')
        assert options == [''] + [m['name'] for m in body['models']]
        assert page.is_enabled('#model_name')
        if body['message']:                                        # Wezard 설정이 없는 개발 서버 — 까닭을 칸 아래에 보인다
            assert page.inner_text('#modelHelp') == body['message']
        page.click('#btnCancel')
        assert page.eval_on_selector_all('#model_name option', 'els => els.map(e => e.textContent)') == ['(매핑 없음)']

    def test_여러_줄_설명은_줄바꿈을_그대로_보인다(self, page, base_url, item):
        # 설명은 여러 줄 입력칸이다. 글자로 넣으면 줄바꿈이 공백으로 합쳐져 한 줄로 보였다
        manage_shell('from domain.models.data import InspectionItem\nfrom domain.tenancy import tenant_atomic\n'
                     'with tenant_atomic():\n'
                     f"    InspectionItem.objects.filter(pk={item['id']}).update(description='첫 줄\\n둘째 줄')")
        page.goto(f'{base_url}/gui/wm_data_item/', wait_until='networkidle')
        open_row(page, item['name'])
        page.wait_for_function("() => document.getElementById('description').value.includes('둘째 줄')")
        assert page.input_value('#description') == '첫 줄\n둘째 줄'
        # 입력칸은 공용 CSS 가 32px 한 줄로 고정한다 — 설명 칸은 여러 줄 높이여야 둘째 줄이 보인다
        assert page.evaluate("() => document.getElementById('description').clientHeight") > 60
        page.goto(f"{base_url}/gui/wm_data_item_detail/?inspection_item={item['id']}", wait_until='networkidle')
        page.wait_for_function("() => document.getElementById('itemDescription').textContent.includes('둘째 줄')")
        assert not page.is_visible('#itemDescription')                      # 홈 설명은 접혀 있다(사용자 결정 2026-10-21)
        page.click('.item-desc-toggle')
        page.wait_for_selector('#itemDescCollapse.show')
        assert page.inner_text('#itemDescription') == '첫 줄\n둘째 줄'


class TestItemDetail:

    def _open_settings(self, page, base_url, item, tab=None):
        page.goto(f"{base_url}/gui/wm_data_item_detail/?inspection_item={item['id']}", wait_until='networkidle')
        page.click('#btnEdit')
        page.wait_for_selector('#itemEditModal.show')
        if tab:
            page.click(f'#itemEditModal button[data-bs-target="#{tab}"]')
            page.wait_for_timeout(400)

    def test_정보를_저장한다(self, page, base_url, item):
        self._open_settings(page, base_url, item)
        page.fill('#infoDescription', 'E2E 설명')
        send(page, lambda: page.click('#btnSaveInfo'))
        assert home_detail(page, item['id'])['description'] == 'E2E 설명'

    def test_라벨_클래스를_추가_수정_삭제한다(self, page, base_url, item):
        self._open_settings(page, base_url, item, 'tabLabels')
        create = page.locator('#editLabels tr.label-new')
        create.locator('input[name=name]').fill('e2e_dent')
        create.locator('input[name=display_name_ko]').fill('찍힘')
        send(page, lambda: create.get_by_role('button', name='추가').click())
        assert [l['name'] for l in home_detail(page, item['id'])['labels']] == ['e2e_dent']

        page.wait_for_timeout(600)
        row = page.locator('#editLabels tr.label-row').first
        row.locator('input[name=display_name_ko]').fill('찍힘(수정)')
        send(page, lambda: row.get_by_role('button', name='저장').click())
        assert home_detail(page, item['id'])['labels'][0]['display_name_ko'] == '찍힘(수정)'

        page.wait_for_timeout(600)
        page.locator('#editLabels tr.label-row').first.get_by_role('button', name='삭제').click()
        page.wait_for_selector(CONFIRM_OK, state='visible')
        send(page, lambda: page.click(CONFIRM_OK))
        assert home_detail(page, item['id'])['labels'] == []


@pytest.fixture
def pngs(tmp_path):
    from PIL import Image
    paths = []
    for index, shade in enumerate((200, 120)):
        path = tmp_path / f'e2e-scratch-{index}.png'
        Image.new('RGB', (320, 240), (shade, shade, shade)).save(path)
        paths.append(str(path))
    return paths


class TestUploadBatches:
    """한 번에 고른 파일이 20개를 넘어도 20개씩 나눠 모두 올라간다(서버는 요청당 20개)."""

    def test_25장을_고르면_모두_올라간다(self, page, base_url, item, tmp_path):
        from PIL import Image
        paths = []
        for index in range(25):
            path = tmp_path / f'e2e-batch-{index:02d}.png'
            Image.new('RGB', (64, 48), (index * 9, 40, 200 - index * 5)).save(path)
            paths.append(str(path))
        page.goto(f"{base_url}/gui/wm_data_image/?inspection_item={item['id']}", wait_until='networkidle')
        page.get_by_role('button', name='데이터 추가').click()
        page.wait_for_selector('#uploadModal.show')
        page.set_input_files('#imageFiles', paths)
        uploads = []
        page.on('response', lambda r: uploads.append(r.status) if 'action=upload' in r.url else None)
        page.click('#startUpload')
        page.wait_for_selector('#uploadModal', state='hidden', timeout=30000)
        assert uploads == [200, 200], uploads
        body = mes(page, f"/api/item/image?action=list&item_id={item['id']}&page=1&page_size=50")
        assert body['totalRows'] == 25


class TestDataPipeline:
    """한 검사항목의 데이터가 업로드 → 편집 → 라벨링 → 검수 → 스냅샷 → Export 로
    흐르는지 화면을 눌러 본다. 단계가 앞 단계의 결과를 쓰므로 한 테스트다."""

    def test_업로드부터_Export_까지(self, page, base_url, item, pngs):
        item_id = item['id']
        created = mes(page, '/api/item/item_home?action=label_create',
                      {'item_id': item_id, 'name': 'e2e_scratch', 'display_name_ko': '긁힘',
                       'color': '#E4572E', 'is_defect': 'true', 'annotation_shape': 'BBOX'})
        assert created.get('success'), created

        # 업로드
        page.goto(f'{base_url}/gui/wm_data_image/?inspection_item={item_id}', wait_until='networkidle')
        page.get_by_role('button', name='데이터 추가').click()
        page.set_input_files('#imageFiles', pngs)
        send(page, lambda: page.click('#startUpload'))
        page.wait_for_timeout(1500)

        # 이미지 편집(회전)
        page.locator('#main-grid').get_by_text(re.compile(r'e2e-scratch-\d\.png')).first.click()
        page.wait_for_timeout(800)
        page.get_by_role('button', name='이미지 편집').click()
        page.wait_for_selector('#preprocessModal.show')
        send(page, lambda: page.click('#preprocessRotateRight'))
        page.keyboard.press('Escape')

        # 라벨링: 작업 시작 → 영역 하나 → 임시 저장 → 제출
        page.goto(f'{base_url}/gui/wm_data_labeling/?inspection_item={item_id}', wait_until='networkidle')
        page.wait_for_timeout(1000)
        send(page, lambda: page.click('#startTask'))
        page.locator('#labelClassList .label-class').first.click()
        box = page.locator('#annotationImage').bounding_box()
        page.mouse.move(box['x'] + box['width'] * 0.3, box['y'] + box['height'] * 0.3)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] * 0.6, box['y'] + box['height'] * 0.6, steps=5)
        page.mouse.up()
        assert page.inner_text('#annotationCount').strip().startswith('1')
        send(page, lambda: page.click('#saveAnnotations'))
        # MES 셸로 옮기며 작업대 높이 체인을 다시 잡았다. 화면에서 그린 위치(30%~60%)가
        # 원본 픽셀 좌표로 그대로 저장됐는지 본다(320x240 이미지 → x·y≈96·72, 폭·높이≈96·72).
        queue = mes_get(page, f'/api/item/labeling?action=queue&item_id={item_id}')
        boxes = [a for image in queue['images'] for a in image['annotations'] if a['geometry_type'] == 'BBOX']
        assert len(boxes) == 1, boxes
        image_size = next((i['width'], i['height']) for i in queue['images'] if i['annotations'])
        for key, ratio, size in (('x', 0.3, image_size[0]), ('y', 0.3, image_size[1]),
                                 ('width', 0.3, image_size[0]), ('height', 0.3, image_size[1])):
            assert abs(boxes[0][key] - ratio * size) <= 0.03 * size, (key, boxes[0], image_size)
        send(page, lambda: page.click('#submitTask'))

        # 두 번째 이미지는 아무 것도 표시하지 않고 '결함 없음'으로 제출한다(확인을 거친다)
        page.wait_for_timeout(800)
        send(page, lambda: page.click('#startTask'))
        page.click('#submitTask')
        page.wait_for_selector(CONFIRM_OK, state='visible')
        send(page, lambda: page.click(CONFIRM_OK))

        # 검수: 하나는 재작업 요청(사유 필수), 하나는 검수 완료
        page.goto(f'{base_url}/gui/wm_data_review/?inspection_item={item_id}', wait_until='networkidle')
        page.wait_for_timeout(800)
        rows = page.locator('#main-grid').get_by_text(re.compile(r'e2e-scratch-\d\.png'))
        assert rows.count() == 2
        rows.first.click()
        page.wait_for_timeout(800)
        page.fill('input[placeholder="재작업 사유"]', 'E2E 재작업 사유')
        send(page, lambda: page.get_by_role('button', name='재작업 요청', exact=True).click())
        # 처리하면 같은 페이지의 다음 행이 이어서 열린다.
        page.wait_for_timeout(1200)
        send(page, lambda: page.get_by_role('button', name='검수 완료', exact=True).click())

        # 스냅샷 등록 → 워커가 zip 생성 → 목록에 받기 링크
        page.goto(f'{base_url}/gui/wm_data_snapshot/?inspection_item={item_id}', wait_until='networkidle')
        page.wait_for_timeout(800)
        page.click('#btnNew')
        page.wait_for_selector('#snapshotCreateModal.show')
        send(page, lambda: page.click('#btnCreateSnapshot'))
        run_worker_once()
        rows = mes_get(page, f'/api/item/snapshot?action=list&item_id={item_id}')['rows']
        assert [r['export']['status'] for r in rows] == ['COMPLETED'], rows
        page.click('#btnSearch')
        link = page.locator('#main-grid a', has_text='받기').first
        link.wait_for(timeout=8000)
        href = link.get_attribute('href')
        assert href.startswith('/media/export/'), href
        download = page.request.get(base_url + href)
        assert download.status == 200
        assert download.headers['content-type'] == 'application/zip'


# --- MES 계열 화면 --------------------------------------------------------
# MES API 는 실패해도 200 에 success:false 를 돌려준다. 상태와 success 를 함께 본다.

CONFIRM_OK = '#commonConfirmModalOk'


def send_mes(page, action, path):
    with page.expect_response(lambda r: r.request.method == 'POST' and path in r.url,
                              timeout=15000) as info:
        action()
    response = info.value
    assert response.status < 400, (response.status, response.text()[:300])
    body = response.json()
    assert not (isinstance(body, dict) and body.get('success') is False), body
    return body


def confirm_ok(page):
    page.wait_for_selector(CONFIRM_OK, state='visible', timeout=8000)
    page.click(CONFIRM_OK)


def open_gui(page, base_url, gui_code):
    page.goto(f'{base_url}/gui/{gui_code}/', wait_until='networkidle')
    page.wait_for_timeout(1200)


class TestUserGroup:
    """사용자 그룹을 등록 모달로 만들고, 그 그룹의 메뉴 권한을 저장하고, 상세에서 고치고, 지운다."""

    def test_그룹_등록_권한_저장_수정_삭제(self, page, base_url, admin_password):
        code = f'e2e_grp_{int(time.time()) % 100000}'
        login(page, base_url, 'admin', admin_password)
        open_gui(page, base_url, 'wm_user_group')
        assert page.locator('.upper-wezongrid #btnNew').count() == 1     # 목록 머리 오른쪽 위
        page.click('#btnNew')
        page.wait_for_selector('#groupCreateModal.show')
        page.click('#btnCreateGroup')                                     # 빈 채로 → 필수 안내
        page.wait_for_selector('#commonAlertModal.show')
        page.click('#commonAlertModalOk')
        assert page.evaluate("() => $('#groupCreateModal .is-invalid').length") == 2
        page.fill('#createCode', code)
        page.fill('#createName', code)
        send_mes(page, lambda: page.click('#btnCreateGroup'), 'usergroup?action=save')
        page.wait_for_selector('#groupCreateModal', state='hidden')
        try:
            open_gui(page, base_url, 'wm_user_group_menu')
            page.select_option('#cboUserGroup', label=code)
            page.wait_for_timeout(1500)
            page.locator('#usergroupmenu-grid input[type=checkbox]').first.check()
            page.click('#btnSave')
            send_mes(page, lambda: confirm_ok(page), 'usergroupmenu?action=save')

            open_gui(page, base_url, 'wm_user_group')
            page.get_by_text(code, exact=True).first.click()
            page.wait_for_timeout(500)
            assert page.is_disabled('#name') and page.is_disabled('#code')
            page.click('#btnEdit')
            assert page.is_enabled('#name') and page.is_disabled('#code')   # 코드는 고치지 않는다
            page.fill('#name', code + '-수정')
            send_mes(page, lambda: page.click('#btnSave'), 'usergroup?action=save')
            page.wait_for_selector('#name:disabled')                          # 다시 읽어 읽기 전용으로 돌아온다
            assert page.input_value('#name') == code + '-수정'
        finally:
            open_gui(page, base_url, 'wm_user_group')
            page.get_by_text(code, exact=True).first.click()
            page.wait_for_timeout(500)
            page.click('#btnDelete')
            send_mes(page, lambda: confirm_ok(page), 'usergroup?action=delete')
        page.wait_for_timeout(800)
        assert page.get_by_text(code, exact=True).count() == 0


class TestUserPassword:
    """사용자 화면의 비밀번호 설정 — 정책을 지키면 바뀐다."""

    def test_비밀번호_설정(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        open_gui(page, base_url, 'wm_user')
        login_id = f'e2e-pw-{int(time.time()) % 100000}'
        groups = page.evaluate(test_crud.TestUserLifecycle.GET, '/api/system/usergroup?action=read')
        group_id = next(g['id'] for g in groups if g['code'] == 'user')
        saved = page.evaluate(test_crud.TestUserLifecycle.POST, ['/api/system/user?action=save', {
            'login_id': login_id, 'Name': 'E2E 비밀번호', 'UserGroup_id': group_id, 'is_active': 'Y'}])
        assert saved.get('success'), saved
        try:
            page.click('#btnSearch')
            page.wait_for_timeout(1200)
            page.get_by_text(login_id, exact=True).first.click()
            page.wait_for_timeout(800)
            assert not page.is_visible('#btnPassSetting')     # 수정 모드 전용 버튼이다
            page.click('#btnEdit')
            page.click('#btnPassSetting')
            page.wait_for_selector('#pass1', state='visible')
            page.fill('#pass1', 'E2e-Strong-pass-81')
            page.fill('#pass2', 'E2e-Strong-pass-81')
            send_mes(page, lambda: page.click('#btnPassSave'), 'user?action=pass_setting')
        finally:
            deleted = page.evaluate(test_crud.TestUserLifecycle.POST,
                                    ['/api/system/user?action=delete', {'id': saved['id']}])
            assert deleted.get('success'), deleted


class TestVisionScreens:

    def test_클라이언트를_고쳐_저장해도_값이_그대로다(self, page, base_url, admin_password):
        """seed 클라이언트를 [수정] → [저장](값 그대로) 한다. 사용 여부 전환·삭제는 test_detail_form 이 E2E 클라이언트로 본다."""
        login(page, base_url, 'admin', admin_password)
        open_gui(page, base_url, 'wm_vis_client')
        page.locator('#main-grid').get_by_text('CLIENT-001', exact=True).first.click()
        page.wait_for_timeout(800)
        before = page.evaluate("() => [$('#detailForm #id').val(), $('#name').val(), $('#active').prop('checked')]")
        page.click('#btnEdit')
        send_mes(page, lambda: page.click('#btnSave'), 'client?action=save')
        page.wait_for_timeout(800)
        assert page.evaluate("() => [$('#detailForm #id').val(), $('#name').val(), $('#active').prop('checked')]") == before

    def test_검사_이력_상세에_깨진_이미지가_보이지_않는다(self, page, base_url, admin_password, inspection):
        """선택 전에는 안내 문구, 고른 뒤에는 불러온 이미지나 안내 문구다. 빈 src·404 의 깨진 아이콘이 보이면 안 된다."""
        broken = """() => { const img = document.getElementById('inspImage');
            const shown = img.offsetParent !== null;
            return {shown: shown, loaded: img.complete && img.naturalWidth > 0,
                    empty: document.getElementById('inspImageEmpty').offsetParent !== null}; }"""
        login(page, base_url, 'admin', admin_password)
        open_gui(page, base_url, 'wm_vis_inspection')
        page.wait_for_timeout(800)
        state = page.evaluate(broken)
        assert (state['shown'], state['empty']) == (False, True), state
        page.locator('#insp-grid').get_by_text(inspection['client_id'], exact=True).first.click()
        page.wait_for_timeout(1500)
        state = page.evaluate(broken)
        assert state['loaded'] if state['shown'] else state['empty'], state

    def test_오버레이_수정으로_등록하고_표시를_해제한다(self, page, base_url, item, pngs):
        """Overlay 는 행이 곧 검사항목이라 머리에 [수정]만 있다. 숨기려면 "표시"를 해제해 저장한다."""
        open_gui(page, base_url, 'wm_vis_overlay')
        assert page.evaluate("() => [...document.querySelectorAll('#btnNew, #btnDelete, #btnDel, #btnToggle')].length") == 0
        page.locator('#main-grid').get_by_text(item['name'], exact=True).first.click()
        page.wait_for_timeout(800)
        assert page.is_disabled('#opacity')
        page.click('#btnEdit')
        page.set_input_files('#image', pngs[0])
        body = send_mes(page, lambda: page.click('#btnSave'), 'overlay?action=save')
        assert body['version'] == 1
        page.wait_for_timeout(800)
        assert page.is_disabled('#opacity') and page.is_checked('#visible')
        page.click('#btnEdit')
        page.uncheck('#visible')
        body = send_mes(page, lambda: page.click('#btnSave'), 'overlay?action=save')
        assert body['version'] == 1
        page.wait_for_timeout(800)
        row = next(r for r in mes_get(page, '/api/vision/overlay?action=list') if r['item_id'] == item['id'])
        assert (row['visible'], row['version']) == (False, 1)


class TestCompanyScreen:
    """업체정보(메뉴에서 내린 화면, superuser 는 주소로 연다)의 목록 조회는 PostgreSQL raw SQL 이다.

    없는 MES 테이블(material)을 조인해 조회할 때마다 오류였다. SQLite 단위 테스트로는 잡히지 않는다.
    """

    def test_업체_목록_조회가_오류_없이_행_목록을_준다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        open_gui(page, base_url, 'wm_company')
        body = mes_get(page, '/api/definition/company?action=read')
        assert isinstance(body, list), body


SYNC_XHR_PROBE = """
window.__syncXhr = [];
const open = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function (method, url, async) {
    if (async === false) window.__syncXhr.push(method + ' ' + url);
    return open.apply(this, arguments);
};
"""


class TestSharedSettings:
    """모든 사용자가 공유하는 설정 — 관리자가 바꾸고 원래대로 되돌린다."""

    def test_그리드_컬럼_설정_저장과_초기화는_비동기다(self, page, base_url, admin_password):
        # 동기 Ajax 는 금지다(AGENTS.md [5]). 컬럼 설정만 postSyncData 를 쓰고 있었다.
        page.add_init_script(SYNC_XHR_PROBE)
        login(page, base_url, 'admin', admin_password)
        open_gui(page, base_url, 'wm_unit')     # 컬럼 설정 버튼이 남은 화면(메뉴에서 내린 단위정보)
        page.click('#btnGridSetting')
        page.wait_for_selector('#btnSettingSave', state='visible')
        send_mes(page, lambda: page.click('#btnSettingSave'), 'grid_setting?action=save_columns')
        page.wait_for_timeout(800)
        page.click('#btnGridSetting')
        page.wait_for_selector('#btnSettingDelete', state='visible')
        send_mes(page, lambda: page.click('#btnSettingDelete'), 'grid_setting?action=delete')
        assert page.evaluate('() => window.__syncXhr') == []

    def test_즐겨찾기를_켰다_끈다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        open_gui(page, base_url, 'wm_user')
        star = page.locator('.header-title a', has=page.locator('i.uil-favorite')).first
        was_on = 'favorite-on' in page.locator('.header-title i.uil-favorite').first.get_attribute('class')
        send_mes(page, lambda: star.click(), 'bookmark?action=save')
        page.wait_for_timeout(500)
        send_mes(page, lambda: star.click(), 'bookmark?action=save')
        page.wait_for_timeout(500)
        now_on = 'favorite-on' in page.locator('.header-title i.uil-favorite').first.get_attribute('class')
        assert now_on == was_on


class TestMyInfo:
    """내 정보의 비밀번호 변경. 서버 정책에 걸리면 사유를 보이고 바꾸지 않는다."""

    START = 'E2e-Start-pass-57'

    def _user(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        open_gui(page, base_url, 'wm_user')
        login_id = f'e2e-my-{int(time.time()) % 100000}'
        post, get = test_crud.TestUserLifecycle.POST, test_crud.TestUserLifecycle.GET
        group_id = next(g['id'] for g in page.evaluate(get, '/api/system/usergroup?action=read')
                        if g['code'] == 'user')
        saved = page.evaluate(post, ['/api/system/user?action=save', {
            'login_id': login_id, 'Name': 'E2E 내정보', 'UserGroup_id': group_id, 'is_active': 'Y'}])
        assert saved.get('success'), saved
        result = page.evaluate(post, ['/api/system/user?action=pass_setting',
                                      {'id': saved['id'], 'pass1': self.START, 'pass2': self.START}])
        assert result.get('success'), result
        return login_id, saved['id']

    def _delete(self, page, base_url, admin_password, user_id):
        page.context.clear_cookies()
        login(page, base_url, 'admin', admin_password)
        open_gui(page, base_url, 'wm_user')
        deleted = page.evaluate(test_crud.TestUserLifecycle.POST,
                                ['/api/system/user?action=delete', {'id': user_id}])
        assert deleted.get('success'), deleted

    def _change(self, page, base_url, login_id, password):
        page.context.clear_cookies()
        login(page, base_url, login_id, self.START)
        page.goto(f'{base_url}/page/account/myinfo', wait_until='networkidle')
        page.fill('#loginPwd', password)
        page.fill('#loginPwd2', password)
        with page.expect_response(lambda r: 'myinfo?action=password_change' in r.url) as info:
            page.click('#btn_save_user')
        return info.value.json()

    def test_정책에_걸리면_사유를_보이고_정책을_지키면_바뀐다(self, page, base_url, admin_password):
        login_id, user_id = self._user(page, base_url, admin_password)
        try:
            # 화면 규칙(대·소문자·숫자·특수문자·8자)은 지키지만 아이디와 너무 비슷하다.
            similar = login_id.capitalize() + '!'
            body = self._change(page, base_url, login_id, similar)
            assert body.get('success') is False, body
            page.wait_for_selector('#commonAlertModal.show', timeout=5000)
            assert body['message'] in page.inner_text('#commonAlertModalBody')

            body = self._change(page, base_url, login_id, 'E2e-Changed-pass-64')
            assert body.get('success') is True, body
        finally:
            self._delete(page, base_url, admin_password, user_id)


class TestFailureIsShown:
    """실패한 쓰기는 화면이 알린다. 조용히 목록만 다시 그리면 성공한 줄 안다."""

    def test_Overlay_가_없는데_이미지_없이_저장하면_막는다(self, page, base_url, item):
        saved = []
        page.on('request', lambda r: saved.append(r.url) if 'overlay?action=save' in r.url else None)
        open_gui(page, base_url, 'wm_vis_overlay')
        page.locator('#main-grid').get_by_text(item['name'], exact=True).first.click()
        page.wait_for_timeout(600)
        page.click('#btnEdit')
        page.click('#btnSave')
        page.wait_for_selector('#commonAlertModal.show', timeout=5000)
        assert '필수 항목을 입력해 주세요' in page.inner_text('#commonAlertModalBody')
        assert page.evaluate("() => $('#image').hasClass('is-invalid')") and saved == []

    def test_즐겨찾기_저장이_실패하면_별을_되돌리고_알린다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        open_gui(page, base_url, 'wm_user')
        page.route('**/api/system/bookmark?action=save', lambda route: route.abort())
        icon = page.locator('.header-title i.uil-favorite').first
        before = icon.get_attribute('class')
        page.locator('.header-title a', has=page.locator('i.uil-favorite')).first.click()
        page.wait_for_selector('#commonAlertModal.show', timeout=5000)
        assert icon.get_attribute('class') == before


def test_사용자를_등록하면_임시_비밀번호를_한_번_보여_준다(page, base_url, admin_password):
    """결정 8(2026-10-07): 서버가 만든 임시 비밀번호를 화면이 보여 주지 않아 관리자가 알 수 없었다."""
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_user')
    login_id = f'e2e-temp-{int(time.time()) % 100000}'
    user_id = None
    try:
        assert page.locator('.upper-wezongrid #btnNew').count() == 1     # 목록 머리 오른쪽 위
        page.click('#btnNew')
        page.wait_for_selector('#userCreateModal.show')
        page.click('#btnCreateUser')                                      # 빈 채로 → 필수 안내
        page.wait_for_selector('#commonAlertModal.show')
        page.click('#commonAlertModalOk')
        assert page.evaluate("() => $('#userCreateModal .is-invalid').length") == 4   # 그룹·아이디·이름·이메일
        page.select_option('#createGroup', index=1)
        page.fill('#createLoginId', login_id)
        page.fill('#createName', 'E2E 임시 비밀번호')
        page.fill('#createEmail', 'e2e@example.com')
        with page.expect_response(lambda r: 'user?action=save' in r.url) as saved:
            page.click('#btnCreateUser')
        user_id = saved.value.json()['id']
        page.wait_for_selector('#userCreateModal', state='hidden')
        page.wait_for_selector('#tempPasswordModal.show', timeout=8000)
        assert len(page.input_value('#tempPasswordValue')) == 12
        page.click('#tempPasswordModal .modal-footer .btn-input')
        page.wait_for_selector('#tempPasswordModal', state='hidden')
        # 닫으면 값을 지운다 — 다시 볼 수 없다(hidden 이벤트는 배경 페이드가 끝난 뒤 온다)
        page.wait_for_function("() => document.getElementById('tempPasswordValue').value === ''", timeout=3000)
        # 등록한 사용자가 상세에 들어와 있다 — [수정]으로 이름을 바꿔 저장하면 읽기 전용으로 돌아온다(아이디는 고치지 않는다)
        assert page.input_value('#login_id') == login_id
        page.click('#btnEdit')
        assert page.is_disabled('#login_id') and page.is_enabled('#Name')
        page.fill('#Name', 'E2E 임시 비밀번호 수정')
        send_mes(page, lambda: page.click('#btnSave'), 'user?action=save')
        page.wait_for_selector('#Name:disabled')
        assert page.input_value('#Name') == 'E2E 임시 비밀번호 수정'
    finally:
        if user_id:
            deleted = page.evaluate(test_crud.TestUserLifecycle.POST,
                                    ['/api/system/user?action=delete', {'id': user_id}])
            assert deleted.get('success'), deleted


def test_메뉴명_설정은_한국어_표시값만_고치는_수정_전용이다(page, base_url, admin_password):
    """등록·삭제·언어 고르기가 없다(사용자 결정 2026-10-19). seed 데이터라 원래 표시값으로 되돌린다."""
    from tests.e2e.test_crud import mes
    login(page, base_url, 'admin', admin_password)
    open_gui(page, base_url, 'wm_menu_language')
    assert page.locator('#btnNew, #btnDelete, #cboLanguage, #label-lang-grid').count() == 0
    label = '메뉴 로그'
    rows = mes(page, f'/api/system/menu_language?action=menu_language_list&ModuleName=common&TemplateKey=menu&LabelCode={label}')
    before = rows[0] if rows else None
    had_label = 'True' in manage_shell(LABEL_EXISTS.format(label=label))   # 저장이 라벨 코드 행도 만든다
    saved_id = None
    try:
        # 메뉴가 34개라 첫 쪽(20건)에 없을 수 있다 — 폴더로 좁힌다
        with page.expect_response(lambda r: 'action=read' in r.url):
            page.select_option('#cboMenuFolder', label='시스템 관리')
        page.wait_for_timeout(300)
        page.locator('#menu-grid').get_by_text(label, exact=True).first.click()
        page.wait_for_function("() => document.getElementById('LabelCode').value === '메뉴 로그'")
        assert page.is_disabled('#DispText')
        page.click('#btnEdit')
        page.fill('#DispText', 'E2E-메뉴 로그')
        body = send_mes(page, lambda: page.click('#btnSave'), 'labellang_save')
        assert body['success']
        page.wait_for_selector('#DispText:disabled')
        assert page.input_value('#DispText') == 'E2E-메뉴 로그'
        saved_id = mes(page, f'/api/system/menu_language?action=menu_language_list&ModuleName=common&TemplateKey=menu&LabelCode={label}')[0]['id']
    finally:
        if before:
            mes(page, '/api/system/menu_language?action=labellang_save', {
                'id': before['id'], 'ModuleName': 'common', 'TemplateKey': 'menu', 'LabelCode': label, 'DispText': before['DispText']})
        elif saved_id:
            mes(page, '/api/system/menu_language?action=labellang_delete', {'id': saved_id})
        if not had_label:
            manage_shell(LABEL_DELETE.format(label=label))


LABEL_EXISTS = ("from domain.models.system import LabelCode\n"
                "print(LabelCode.objects.filter(ModuleName='common', TemplateKey='menu', LabelCode={label!r}).exists())")
LABEL_DELETE = ("from domain.models.system import LabelCode, LabelCodeLanguage\n"
                "LabelCode.objects.filter(ModuleName='common', TemplateKey='menu', LabelCode={label!r})"
                ".exclude(id__in=LabelCodeLanguage.objects.values('LabelCode_id')).delete()")
