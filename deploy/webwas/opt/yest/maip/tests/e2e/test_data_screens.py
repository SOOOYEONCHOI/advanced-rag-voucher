"""데이터 관리 화면 보완(2026-10-07) — 검사항목 홈·데이터 목록·라벨링·스냅샷.

읽기만 하는 검사는 데모 검사항목 FAN-PANEL-DET(냉각팬 패널 객체탐지, seed_demo)을 연다.
id 는 DB 마다 달라 `demo` 픽스처로 찾는다. 이미지를 올려야 하는 검사는 `item` 픽스처의
`E2E-` 검사항목을 쓰고 끝나면 지운다.
"""
import pytest

from tests.e2e.conftest import login
from tests.e2e.test_image_fit import assert_fit
from tests.e2e.test_write_paths import item, send  # noqa: F401 — item 은 픽스처다

RECT_JS = """(s) => { const r = document.querySelector(s).getBoundingClientRect();
    return {left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height}; }"""


def goto(page, base_url, path):
    page.goto(f'{base_url}/gui/{path}', wait_until='networkidle')
    page.wait_for_timeout(1000)


@pytest.fixture
def admin(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    return page


# ---- 검사항목 홈

def test_라벨_칸을_눌러도_글자_수_표시가_붙지_않는다(admin, base_url, demo):
    page = admin
    goto(page, base_url, f'wm_data_item_detail/?inspection_item={demo["det"]}')
    page.click('#btnEdit')
    page.wait_for_selector('#itemEditModal.show')
    assert page.locator('#infoGuideline').count() == 0      # 업로드 규칙은 없앴다
    page.click('#itemEditModal button[data-bs-target="#tabLabels"]')
    page.wait_for_timeout(400)
    for row in ('tr.label-row', 'tr.label-new'):
        name = page.locator(f'#editLabels {row} input[name=name]').first
        name.click()
        assert name.get_attribute('maxlength') == '64'
        assert name.get_attribute('autocomplete') == 'off'
    page.wait_for_timeout(300)
    assert page.locator('.bootstrap-maxlength').count() == 0


def test_홈은_작업_중_카드와_결함_여부를_보이고_상태_버튼은_상태_이름이다(admin, base_url, demo):
    page = admin
    goto(page, base_url, f'wm_data_item_detail/?inspection_item={demo["det"]}')
    page.wait_for_timeout(800)
    assert '작업 중' in page.inner_text('#summaryCards')
    assert page.locator('#labelBody thead th').all_inner_texts() == ['표시 이름', '결함 여부']
    assert set(page.locator('#labelBody tbody td:nth-child(2)').all_inner_texts()) <= {'결함', '정상'}
    # 머리는 작업 유형만, 배정 인원 칸·탭은 없다. 라벨 클래스 옆이 최근 스냅샷이다(사용자 결정 2026-10-21)
    assert page.inner_text('#itemMeta') == '객체 탐지'
    assert page.locator('#memberBody').count() == 0
    label_box, snapshot_box = page.locator('#labelBody').bounding_box(), page.locator('#snapshotBody').bounding_box()
    assert abs(label_box['y'] - snapshot_box['y']) < 1 and snapshot_box['x'] > label_box['x']
    page.click('#btnEdit')
    page.wait_for_selector('#itemEditModal.show')
    assert page.inner_text('#btnToggleStatus') in ('중지', '사용')
    assert page.locator('#itemEditModal [data-bs-target="#tabMembers"]').count() == 0


def test_검사항목_등록_창은_검사항목명이_필수이고_유형은_목록과_같은_이름이다(admin, base_url):
    page = admin
    posted = []
    # 요청이 나가면 안 된다 — 쓰기 요청은 끊고 센다
    page.route('**/api/item/item_admin?action=create*', lambda route: (posted.append(1), route.abort()))
    try:
        goto(page, base_url, 'wm_data_item/')
        page.click('#btnNew')
        page.wait_for_selector('#itemCreateModal.show')
        assert '객체 탐지' in page.locator('#itemCreateTaskType option').all_inner_texts()
        assert '(필수)' in page.inner_text('label[for=itemCreateName]')
        page.click('#btnCreateItem')
        page.wait_for_selector('#commonAlertModal.show')
        assert '필수 항목을 입력해 주세요' in page.inner_text('#commonAlertModalBody')
        assert 'is-invalid' in page.get_attribute('#itemCreateName', 'class')
        assert posted == []
    finally:
        page.unroute('**/api/item/item_admin?action=create*')


def test_홈_영역_높이는_데이터_양과_무관하다(admin, base_url, demo, item):
    page = admin
    bodies = ['#labelBody', '#snapshotBody', '#imageBody']
    heights = {}
    full, empty = demo['det'], item['id']   # 시드 객체탐지는 라벨·이미지가 있고, E2E 검사항목은 이미지가 없다
    for item_id in (full, empty):
        goto(page, base_url, f'wm_data_item_detail/?inspection_item={item_id}')
        heights[item_id] = [round(page.evaluate(RECT_JS, s)['height']) for s in bodies]
        assert page.evaluate("() => { const b = document.querySelector('#imageBody'); return b.scrollWidth <= b.clientWidth; }")
    assert heights[full] == heights[empty], heights


def test_최근_데이터와_전체_보기는_내부_탭으로_연다(admin, base_url, demo):
    """하위 화면은 셸 새 탭이 아니라 비전검사항목 탭 안의 내부 탭이다(사용자 결정 2026-10-21)."""
    page = admin                    # 로그인하면 셸(/)이다
    mid = f"item{demo['det']}_wm_data_item_detail"
    page.wait_for_timeout(1500)
    page.evaluate(f"() => window.myMenu.openMenu('{mid}', '비전검사항목', '/gui/wm_data_item_detail/?inspection_item={demo['det']}')")
    home = page.frame_locator(f'.mnb-tab-panel[data-mid="{mid}"] iframe')
    home.locator('#imageBody a').first.click()
    image_frame = home.locator('#itemFrames .item-frame[data-screen="wm_data_image"]')
    image_frame.wait_for(state='visible', timeout=5000)
    src = image_frame.get_attribute('src')
    assert 'image_id=' in src and 'embed=1' in src
    assert home.locator('#itemTabs .nav-link.active').inner_text() == '데이터 목록'
    assert page.locator(f'.mnb-tab-panel[data-mid^="item{demo["det"]}_"]').count() == 1      # 셸 탭은 하나

    home.locator('#itemTabs [data-screen="home"]').click()
    home.locator('#snapshotLink').click()
    home.locator('#itemFrames .item-frame[data-screen="wm_data_snapshot"]').wait_for(state='visible', timeout=5000)
    assert home.locator('#paneHome').is_hidden()


def test_주소의_screen_으로_처음_열_내부_탭을_고른다(admin, base_url, demo):
    """대시보드의 [라벨링]·[검수]가 그 항목 탭의 내부 탭을 바로 연다(설계 2026-10-23)."""
    page = admin
    mid = f"item{demo['det']}_wm_data_item_detail"
    page.wait_for_timeout(1500)
    page.evaluate(f"() => window.myMenu.openMenu('{mid}', '비전검사항목', "
                  f"'/gui/wm_data_item_detail/?inspection_item={demo['det']}&screen=wm_data_labeling')")
    home = page.frame_locator(f'.mnb-tab-panel[data-mid="{mid}"] iframe')
    home.locator('#itemFrames .item-frame[data-screen="wm_data_labeling"]').wait_for(state='visible', timeout=5000)
    assert home.locator('#itemTabs .nav-link.active').inner_text() == '라벨링 작업'
    assert home.locator('#paneHome').is_hidden()


# ---- 데이터 목록

def test_데이터_목록_조회_조건은_라벨이_칸_위에_있다(admin, base_url, demo):
    page = admin
    goto(page, base_url, f'wm_data_image/?inspection_item={demo["det"]}')
    pairs = page.evaluate("""() => [...document.querySelectorAll('#searchForm .form-label')].map(l => {
        const c = l.parentElement.querySelector('select, input');
        return [l.textContent.trim(), l.getBoundingClientRect().bottom, c.getBoundingClientRect().top]; })""")
    assert [p[0] for p in pairs] == ['상태', '라벨', '등록일', '파일명'], pairs
    assert all(bottom <= top + 1 for _, bottom, top in pairs), pairs
    assert page.locator('.floder-close').count() == 0


def test_이미지_편집_창은_이미지가_왼쪽에_크다(page, base_url, item, tmp_path):
    from PIL import Image
    path = tmp_path / 'e2e-edit.png'
    Image.new('RGB', (64, 48), (90, 120, 160)).save(path)     # 작은 이미지도 칸에 맞춰 키운다
    goto(page, base_url, f"wm_data_image/?inspection_item={item['id']}")
    page.get_by_role('button', name='데이터 추가').click()
    page.wait_for_selector('#uploadModal.show')
    assert page.locator('#uploadGuideline').count() == 0   # 업로드 규칙 안내는 없앴다
    page.set_input_files('#imageFiles', [str(path)])
    send(page, lambda: page.click('#startUpload'))
    page.wait_for_selector('#uploadModal', state='hidden', timeout=15000)
    page.locator('#main-grid').get_by_text('e2e-edit.png', exact=True).click()
    page.wait_for_timeout(900)
    page.click('#btnPreprocess')
    page.wait_for_selector('#preprocessModal.show')
    page.wait_for_timeout(800)
    body = page.evaluate(RECT_JS, '#preprocessModal .modal-body')
    stage = page.evaluate(RECT_JS, '#preprocessImageCol')
    tools = page.evaluate(RECT_JS, '#preprocessTools')
    assert stage['width'] >= body['width'] * 0.65, (stage, body)
    assert tools['left'] >= stage['right'] - 1, (tools, stage)
    assert page.locator('#preprocessTools th').all_inner_texts() == ['회전', '영역', '크기']
    assert_fit(page, '#preprocessImage', '#preprocessModal .preprocess-canvas', min_box_height=300)


# ---- 라벨링

def test_Polygon_층은_이미지와_같은_크기다(admin, base_url, demo):
    page = admin
    goto(page, base_url, f'wm_data_labeling/?inspection_item={demo["det"]}')
    page.locator('#imageQueue .image-item').first.click()
    page.wait_for_timeout(1000)
    image = page.evaluate(RECT_JS, '#annotationImage')
    layer = page.evaluate(RECT_JS, '#polygonLayer')
    assert abs(image['width'] - layer['width']) <= 1 and abs(image['height'] - layer['height']) <= 1, (image, layer)


@pytest.mark.parametrize('kind', ['det', 'ano'])
def test_그리기_방식_버튼은_없다(admin, base_url, demo, kind):
    # 그리기 방식은 라벨 클래스를 고르면 정해진다(객체 검출은 라벨의 도형, 이상 탐지는 Polygon). 버튼은 눌러야 하는지 헷갈렸다.
    page = admin
    goto(page, base_url, f'wm_data_labeling/?inspection_item={demo[kind]}')
    page.wait_for_selector('#labelClassList .label-class')   # 검사항목이 실제로 열렸는지
    assert page.locator('#drawBbox, #drawPolygon').count() == 0


def test_라벨링_대기열은_페이지로_나누고_다음_작업이_다음_페이지로_넘어간다(page, base_url, item, tmp_path):
    # 결정 6 B(2026-10-07): 대기열을 서버가 50장씩 준다. 여기서는 한 페이지 2장으로 줄여 본다.
    from PIL import Image
    paths = []
    for index in range(3):
        path = tmp_path / f'e2e-q{index}.png'
        Image.new('RGB', (64, 48), (index * 60, 30, 30)).save(path)
        paths.append(str(path))
    goto(page, base_url, f"wm_data_image/?inspection_item={item['id']}")
    page.get_by_role('button', name='데이터 추가').click()
    page.wait_for_selector('#uploadModal.show')
    page.set_input_files('#imageFiles', paths)
    send(page, lambda: page.click('#startUpload'))
    page.wait_for_selector('#uploadModal', state='hidden', timeout=15000)
    goto(page, base_url, f"wm_data_labeling/?inspection_item={item['id']}")
    page.evaluate("() => { page.pageSize = 2; return page.loadQueue(1); }")
    page.wait_for_timeout(800)
    assert page.locator('#imageQueue .image-item').count() == 2
    assert page.inner_text('#queuePageInfo') == '1 / 2'
    assert page.inner_text('#imagePosition') == '1 / 3'
    page.locator('#imageQueue .image-item').nth(1).click()
    page.wait_for_timeout(500)
    page.click('#nextTask')                                  # 페이지 끝 → 다음 페이지 첫 장
    page.wait_for_timeout(1000)
    assert page.inner_text('#queuePageInfo') == '2 / 2'
    assert page.inner_text('#imagePosition') == '3 / 3'
    page.click('#queuePrev')                                 # 이전 페이지는 마지막 장을 연다
    page.wait_for_timeout(1000)
    assert page.inner_text('#imagePosition') == '2 / 3'
