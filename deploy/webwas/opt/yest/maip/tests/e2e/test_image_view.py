"""이미지 상세 보기 — 편집 창 대표 이미지, 휠 확대·끌어 이동.

실제 DB 를 쓴다. `item` 픽스처가 `E2E-` 검사항목을 만들고 지운다.
"""
import time

import pytest

from tests.e2e import test_crud
from tests.e2e.conftest import login, manage_shell
from tests.e2e.test_crud import mes
from tests.e2e.test_write_paths import item, open_gui, send, send_mes  # noqa: F401 — item 은 픽스처다

LARGE = 'e2e-zoom-large.png'


@pytest.fixture
def large_png(tmp_path):
    from PIL import Image
    path = tmp_path / LARGE
    Image.new('RGB', (1600, 1200), (180, 90, 60)).save(path)
    return str(path)


def test_편집_창에_대표_이미지가_보인다(page, base_url, item, large_png):
    page.goto(f'{base_url}/gui/wm_data_item_detail/?inspection_item={item["id"]}', wait_until='networkidle')
    page.click('#btnEdit')
    page.wait_for_selector('#itemEditModal.show')
    assert page.is_visible('#infoCoverEmpty') and not page.is_visible('#infoCoverPreview')
    page.set_input_files('#infoCover', large_png)
    assert page.get_attribute('#infoCoverPreview', 'src').startswith('blob:')
    send(page, lambda: page.click('#btnSaveInfo'))
    page.wait_for_timeout(1200)
    src = page.get_attribute('#infoCoverPreview', 'src')
    assert '/media/item-cover/' in src and '?v=' in src, src
    assert page.evaluate("() => document.getElementById('infoCoverPreview').naturalWidth") == 1600


# 대상 요소(확대되는 것)의 화면 위 상자
BOX_JS = "s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }"


def upload(page, base_url, item_id, path):
    page.goto(f'{base_url}/gui/wm_data_image/?inspection_item={item_id}', wait_until='networkidle')
    page.get_by_role('button', name='데이터 추가').click()
    page.set_input_files('#imageFiles', [path])
    send(page, lambda: page.click('#startUpload'))
    page.wait_for_selector('#uploadModal', state='hidden', timeout=15000)


def assert_wheel_and_drag(page, viewport, target):
    """휠 → 커서 자리 기준 확대, 끌기 → 이동, 더블클릭 → 원래대로."""
    left, top, width, height = page.evaluate(BOX_JS, target)
    cx, cy = left + width * 0.25, top + height * 0.25
    page.mouse.move(cx, cy)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(200)
    l2, t2, w2, h2 = page.evaluate(BOX_JS, target)
    assert w2 > width * 1.5, (width, w2)
    # 커서 아래 점(대상의 왼쪽 위 1/4 지점)이 그 자리에 남는다
    assert abs((cx - l2) / w2 - 0.25) < 0.01 and abs((cy - t2) / h2 - 0.25) < 0.01, (cx, cy, l2, t2, w2, h2)
    page.mouse.down()
    page.mouse.move(cx + 80, cy + 40, steps=5)
    page.mouse.up()
    l3, t3, _, _ = page.evaluate(BOX_JS, target)
    assert abs((l3 - l2) - 80) <= 2 and abs((t3 - t2) - 40) <= 2, (l2, l3, t2, t3)
    page.dblclick(viewport)
    page.wait_for_timeout(100)
    assert abs(page.evaluate(BOX_JS, target)[2] - width) <= 1


def test_데이터_목록과_검수_상세에서_휠로_확대하고_끌어_옮긴다(page, base_url, item, large_png):
    item_id = item['id']
    upload(page, base_url, item_id, large_png)
    page.locator('#main-grid').get_by_text(LARGE, exact=True).click()
    page.wait_for_timeout(900)
    assert_wheel_and_drag(page, '.image-detail-preview', '.image-detail-coordinate-surface')

    queue = mes(page, f'/api/item/labeling?action=queue&item_id={item_id}')
    task = mes(page, '/api/item/labeling?action=claim', {'item_id': item_id, 'image_id': queue['images'][0]['id']})['task']
    submitted = mes(page, '/api/item/labeling?action=submit',
                    {'item_id': item_id, 'task_id': task['id'], 'lease_token': task['lease_token']})
    assert submitted.get('success') is not False, submitted
    page.goto(f'{base_url}/gui/wm_data_review/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(800)
    page.locator('#main-grid').get_by_text(LARGE, exact=True).click()
    page.wait_for_timeout(900)
    assert_wheel_and_drag(page, '.image-detail-preview', '.image-detail-coordinate-surface')


def test_Overlay_상세에서_휠로_확대한다(page, base_url, item, large_png):
    open_gui(page, base_url, 'wm_vis_overlay')
    page.locator('#main-grid').get_by_text(item['name'], exact=True).first.click()
    page.wait_for_timeout(800)
    page.click('#btnEdit')
    page.set_input_files('#image', large_png)
    send_mes(page, lambda: page.click('#btnSave'), 'overlay?action=save')
    page.wait_for_timeout(1200)
    # #overlayPreview 는 칸 전체를 차지하고 object-fit: contain 으로 그림을 담는다 — 요소 상자가 커지는지로 본다
    assert_wheel_and_drag(page, '#overlayImageBox', '#overlayPreview')


def test_라벨링에서_휠은_커서_기준으로_키우고_끌면_스크롤한다(page, base_url, item, large_png):
    item_id = item['id']
    upload(page, base_url, item_id, large_png)
    page.goto(f'{base_url}/gui/wm_data_labeling/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(1000)
    page.locator('#imageQueue .image-item', has_text=LARGE).click()
    page.wait_for_timeout(600)
    left, top, width, height = page.evaluate(BOX_JS, '#annotationImage')
    cx, cy = left + width * 0.75, top + height * 0.75
    page.mouse.move(cx, cy)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(200)
    assert int(page.inner_text('#zoomValue').rstrip('%')) > 150
    l2, t2, w2, h2 = page.evaluate(BOX_JS, '#annotationImage')
    assert abs((cx - l2) / w2 - 0.75) < 0.02 and abs((cy - t2) / h2 - 0.75) < 0.02, (cx, l2, w2, cy, t2, h2)

    # 작업 전(그리기 없음)에는 왼쪽 버튼으로 끌면 스크롤이 옮겨진다
    scroll = "() => { const h = document.getElementById('canvasHolder'); return [h.scrollLeft, h.scrollTop]; }"
    before = page.evaluate(scroll)
    page.mouse.down()
    page.mouse.move(cx - 60, cy - 30, steps=5)
    page.mouse.up()
    after = page.evaluate(scroll)
    assert abs((after[0] - before[0]) - 60) <= 2 and abs((after[1] - before[1]) - 30) <= 2, (before, after)


@pytest.fixture
def anomaly_item(page, base_url, admin_password):
    """이상 탐지 검사항목(라벨링이 Polygon 으로 그린다)과 결함 유형 하나. 끝나면 승인 삭제로 지운다."""
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_data_item/', wait_until='networkidle')
    created = mes(page, '/api/item/item_admin?action=create',
                  {'name': f'E2E-상세보기-{int(time.time() * 1000)}', 'task_type': 'ANOMALY_DETECTION'})
    assert created.get('success'), created
    item_id = created['item_id']
    try:
        label = mes(page, '/api/item/item_home?action=label_create',
                    {'item_id': item_id, 'name': 'e2e_dent', 'display_name_ko': '찍힘', 'color': '#E4572E',
                     'is_defect': 'true', 'annotation_shape': 'BBOX'})
        assert label.get('success'), label
        yield {'id': item_id}
    finally:
        page.goto(f'{base_url}/gui/wm_data_item/', wait_until='networkidle')
        test_crud.TestItemDeletionReview()._cleanup(page, item_id)
        assert test_crud.TestItemDeletionReview.detail(page, item_id) is None


def test_라벨링에서_끌어_옮긴_뒤의_클릭도_Polygon_점이_된다(page, base_url, anomaly_item, large_png):
    """점 → 끌어 이동 → 점 두 개. 이동은 점이 되지 않고, 이동 뒤의 클릭은 버려지지 않는다.

    끌어 옮기면 Chrome 은 click 을 이미지가 아닌 캔버스 칸에 보낸다(포인터 캡처). 이동 표시(panMoved)는
    다음 pointerup 이 다시 정하므로 이어지는 클릭의 점을 막지 않는다.
    """
    item_id = anomaly_item['id']
    upload(page, base_url, item_id, large_png)
    page.goto(f'{base_url}/gui/wm_data_labeling/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(1000)
    page.locator('#imageQueue .image-item', has_text=LARGE).click()
    page.wait_for_timeout(600)
    send(page, lambda: page.click('#startTask'))
    page.locator('#labelClassList .label-class', has_text='찍힘').click()
    left, top, width, height = page.evaluate(BOX_JS, '#annotationImage')
    page.mouse.move(left + width / 2, top + height / 2)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(200)

    holder = page.evaluate(BOX_JS, '#canvasHolder')
    cx, cy = holder[0] + holder[2] / 2, holder[1] + holder[3] / 2
    page.mouse.click(cx, cy)
    scroll = "() => document.getElementById('canvasHolder').scrollLeft"
    before = page.evaluate(scroll)
    page.mouse.down()
    page.mouse.move(cx - 60, cy - 30, steps=5)
    page.mouse.up()
    assert page.evaluate(scroll) - before >= 55  # 점이 아니라 이동이었다
    page.mouse.click(cx + 40, cy)
    page.mouse.click(cx + 40, cy + 40)
    assert page.evaluate("() => page.drawing && page.drawing.points.length") == 3


def test_BBOX_를_그리는_중에_휠로_키워도_상자는_누른_점과_놓은_점이다(page, base_url, item, large_png):
    """그리는 점은 이미지 원래 픽셀로 저장된다 — 도중에 배율이 바뀌어도 시작점이 밀리지 않는다."""
    item_id = item['id']
    created = mes(page, '/api/item/item_home?action=label_create',
                  {'item_id': item_id, 'name': 'e2e_box', 'display_name_ko': '상자', 'color': '#E4572E',
                   'is_defect': 'true', 'annotation_shape': 'BBOX'})
    assert created.get('success'), created
    upload(page, base_url, item_id, large_png)
    page.goto(f'{base_url}/gui/wm_data_labeling/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(1000)
    page.locator('#imageQueue .image-item', has_text=LARGE).click()
    page.wait_for_timeout(600)
    send(page, lambda: page.click('#startTask'))
    page.locator('#labelClassList .label-class', has_text='상자').click()

    left, top, width, height = page.evaluate(BOX_JS, '#annotationImage')
    page.mouse.move(left + width * 0.25, top + height * 0.25)   # 원본 (400, 300)
    page.mouse.down()
    page.mouse.move(left + width * 0.4, top + height * 0.4, steps=3)
    page.mouse.wheel(0, -200)                                    # 그리는 중에 확대
    page.wait_for_timeout(200)
    l2, t2, w2, h2 = page.evaluate(BOX_JS, '#annotationImage')
    page.mouse.move(l2 + w2 * 0.5, t2 + h2 * 0.5, steps=3)       # 원본 (800, 600)
    page.mouse.up()
    box = page.evaluate("() => page.activeImage.annotations.filter(a => a.geometry_type === 'BBOX').map(a => [a.x, a.y, a.width, a.height])")
    assert len(box) == 1, box
    x, y, w, h = box[0]
    assert abs(x - 400) <= 3 and abs(y - 300) <= 3 and abs(x + w - 800) <= 3 and abs(y + h - 600) <= 3, box


def start_polygon(page, base_url, item_id, path):
    """이상 탐지 검사항목에 이미지를 올리고 라벨링을 시작해 결함 유형(찍힘)을 고른다."""
    upload(page, base_url, item_id, path)
    page.goto(f'{base_url}/gui/wm_data_labeling/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(1000)
    page.locator('#imageQueue .image-item', has_text=LARGE).click()
    page.wait_for_timeout(600)
    send(page, lambda: page.click('#startTask'))
    page.locator('#labelClassList .label-class', has_text='찍힘').click()


def zoom_to(page, percent):
    while int(page.inner_text('#zoomValue').rstrip('%')) < percent:
        page.click('#zoomIn')
    page.wait_for_timeout(200)


POINT_SIZES = "() => [...document.querySelectorAll('.polygon-draft-point')].map(p => Math.round(p.getBoundingClientRect().width))"


def test_확대해도_Polygon_점과_선의_화면_크기는_같다(page, base_url, anomaly_item, large_png):
    start_polygon(page, base_url, anomaly_item['id'], large_png)
    holder = page.evaluate(BOX_JS, '#canvasHolder')
    cx, cy = holder[0] + holder[2] / 2, holder[1] + holder[3] / 2
    page.mouse.click(cx, cy)
    page.mouse.click(cx + 60, cy)
    at_100 = page.evaluate(POINT_SIZES)
    zoom_to(page, 400)
    at_400 = page.evaluate(POINT_SIZES)
    assert len(at_100) == 2 and at_100 == at_400, (at_100, at_400)
    assert at_400[0] <= 12 and at_400[1] <= 8, at_400   # 첫 점 11px, 나머지 7px
    # 선은 확대와 무관한 두께다(그리는 선·저장된 외곽선)
    assert page.evaluate("() => getComputedStyle(document.querySelector('.polygon-draft')).vectorEffect") == 'non-scaling-stroke'


def test_최대로_확대해도_첫_점_근처를_누르면_Polygon_이_닫힌다(page, base_url, anomaly_item, large_png):
    start_polygon(page, base_url, anomaly_item['id'], large_png)
    zoom_to(page, 400)
    holder = page.evaluate(BOX_JS, '#canvasHolder')
    cx, cy = holder[0] + holder[2] / 2, holder[1] + holder[3] / 2
    for dx, dy in ((0, 0), (80, 0), (80, 80)):
        page.mouse.click(cx + dx, cy + dy)
    first = "() => document.querySelector('.polygon-draft-point.is-start').classList.contains('is-closable')"
    page.mouse.move(cx + 60, cy + 60)
    assert page.evaluate(first) is False
    page.mouse.move(cx + 6, cy + 5)        # 첫 점에서 약 8px — 닫힘 범위(10px) 안
    assert page.evaluate(first) is True
    page.mouse.click(cx + 6, cy + 5)
    assert page.evaluate("() => page.drawing") is None
    assert page.evaluate("() => page.activeImage.annotations.filter(a => a.geometry_type === 'POLYGON').length") == 1


def set_cover(page, base_url, item_id, path):
    page.goto(f'{base_url}/gui/wm_data_item_detail/?inspection_item={item_id}', wait_until='networkidle')
    page.click('#btnEdit')
    page.wait_for_selector('#itemEditModal.show')
    page.set_input_files('#infoCover', path)
    send(page, lambda: page.click('#btnSaveInfo'))


# 두 칸의 스크롤 위치(움직일 수 있는 범위에 대한 비율)
SCROLL_RATIO = """() => ['referenceHolder', 'canvasHolder'].map(id => { const h = document.getElementById(id);
    return [h.scrollLeft / Math.max(1, h.scrollWidth - h.clientWidth), h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight)]; })"""


def assert_same_view(page):
    ref, work = page.evaluate(BOX_JS, '#referenceImage'), page.evaluate(BOX_JS, '#annotationImage')
    assert abs(ref[2] - work[2]) <= 1 and abs(ref[3] - work[3]) <= 1, (ref, work)
    (rx, ry), (wx, wy) = page.evaluate(SCROLL_RATIO)
    assert abs(rx - wx) < 0.02 and abs(ry - wy) < 0.02, ((rx, ry), (wx, wy))


def test_라벨링에서_대표_이미지와_작업_이미지를_나란히_본다(page, base_url, anomaly_item, large_png):
    item_id = anomaly_item['id']
    # 대표 이미지가 없으면 버튼이 꺼져 있다
    page.goto(f'{base_url}/gui/wm_data_labeling/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(800)
    assert page.is_disabled('#referenceToggle')

    set_cover(page, base_url, item_id, large_png)
    start_polygon(page, base_url, item_id, large_png)
    # 도구줄 왼쪽 위에는 [대표 이미지] 버튼만 있다("지금 표시하는 이미지" 제목은 없다)
    assert page.evaluate(BOX_JS, '#referenceToggle')[0] - page.evaluate(BOX_JS, '.canvas-toolbar')[0] < 30
    assert '지금 표시하는 이미지' not in page.inner_text('.canvas-toolbar')
    assert not page.is_visible('#referencePane')
    full = page.evaluate(BOX_JS, '#canvasHolder')
    look = "() => { const s = getComputedStyle(document.getElementById('referenceToggle')); return [s.backgroundColor, s.color]; }"
    off_look = page.evaluate(look)
    assert page.get_attribute('#referenceToggle', 'aria-pressed') == 'false'

    page.click('#referenceToggle')
    # 켜짐은 꺼짐과 다르게 보인다(토글 상태가 눈에 보인다). 배경은 0.15초 전환 효과가 있어 끝난 뒤 읽는다
    assert page.get_attribute('#referenceToggle', 'aria-pressed') == 'true'
    page.wait_for_timeout(300)
    on_look = page.evaluate(look)
    assert on_look[0] != off_look[0] and on_look[1] != off_look[1], (off_look, on_look)
    page.wait_for_function("() => document.getElementById('referenceImage').complete && document.getElementById('referenceImage').naturalWidth > 0")
    page.wait_for_timeout(300)
    ref, work = page.evaluate(BOX_JS, '#referenceHolder'), page.evaluate(BOX_JS, '#canvasHolder')
    assert ref[0] < work[0] and abs(ref[2] - work[2]) <= 2 and work[2] < full[2] * 0.6, (ref, work, full)
    assert page.inner_text('#referencePaneTitle') == '대표 이미지'
    assert page.inner_text('#workPaneTitle') == f'작업 중인 이미지 · {LARGE}'
    assert_same_view(page)

    # 오른쪽에서 휠 → 왼쪽도 같은 크기·같은 자리
    page.mouse.move(work[0] + work[2] * 0.7, work[1] + work[3] * 0.7)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(300)
    zoom = int(page.inner_text('#zoomValue').rstrip('%'))
    assert zoom > 150
    assert_same_view(page)
    # 왼쪽에서 휠 → 함께 커진다
    page.mouse.move(ref[0] + ref[2] * 0.3, ref[1] + ref[3] * 0.3)
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(300)
    assert int(page.inner_text('#zoomValue').rstrip('%')) > zoom
    assert_same_view(page)
    # 왼쪽에서 끌기 → 양쪽이 함께 옮겨진다
    scroll = "() => ['referenceHolder', 'canvasHolder'].map(id => document.getElementById(id).scrollLeft)"
    before = page.evaluate(scroll)
    page.mouse.move(ref[0] + ref[2] / 2, ref[1] + ref[3] / 2)
    page.mouse.down()
    page.mouse.move(ref[0] + ref[2] / 2 - 60, ref[1] + ref[3] / 2, steps=5)
    page.mouse.up()
    page.wait_for_timeout(200)
    after = page.evaluate(scroll)
    assert after[0] - before[0] >= 55 and after[1] - before[1] >= 55, (before, after)
    assert_same_view(page)

    # 오른쪽 작업은 그대로 — Polygon 점이 찍힌다
    page.mouse.click(work[0] + work[2] / 2, work[1] + work[3] / 2)
    assert page.evaluate("() => page.drawing && page.drawing.points.length") == 1
    # 끄면 왼쪽 칸이 사라지고 작업 칸이 전체 폭으로 돌아온다
    page.click('#referenceToggle')
    assert not page.is_visible('#referencePane')
    page.wait_for_timeout(300)
    assert page.evaluate(look) == off_look
    assert abs(page.evaluate(BOX_JS, '#canvasHolder')[2] - full[2]) <= 2


def test_데이터_목록은_라벨_결과와_결함_내역을_보인다(page, base_url, admin_password, demo):
    """seed_demo FAN-PANEL(이상 탐지)을 읽기만 한다. 이상 이미지는 Polygon 영역이 있고 이름표가 붙는다."""
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_data_image/?inspection_item={demo["ano"]}', wait_until='networkidle')
    rows = mes(page, f'/api/item/image?action=list&item_id={demo["ano"]}&page=1&page_size=100')['rows']
    bad = next((r for r in rows if r['label_result'] == '이상'), None)
    assert bad, 'FAN-PANEL 에 이상으로 라벨링된 이미지가 있어야 한다(seed_demo)'
    assert '라벨 결과' in page.inner_text('#main-grid') and '라벨 영역' not in page.inner_text('#main-grid')
    page.locator('#main-grid').get_by_text(bad['original_name'], exact=True).first.click()
    page.wait_for_selector('#detailBody table')
    detail = page.inner_text('#detailBody table')
    assert '라벨 결과\t이상' in detail and '결함 내역' in detail, detail
    assert page.locator('#detailBody .label-summary-chip').count() >= 1
    tags = page.locator('#detailBody .image-detail-box.is-polygon span')
    assert tags.count() >= 1 and tags.first.inner_text().strip(), '영역에 결함 이름표가 붙어야 한다'


def _set_label_status(item_id, image_id, status):
    """seed 이미지 하나의 label_status 만 바꾼다. update() 라 updated_at 은 그대로다."""
    return manage_shell('from domain.models.data import ImageAsset\nfrom domain.tenancy import tenant_atomic\n'
                        'with tenant_atomic():\n'
                        f'    qs = ImageAsset.objects.filter(dataset__item_id={item_id}, annotations__isnull=False)\n'
                        f'    qs = qs.filter(pk={image_id}) if {image_id!r} else qs.filter(label_status="APPROVED").order_by("id")[:1]\n'
                        '    image = qs.first()\n'
                        f'    ImageAsset.objects.filter(pk=image.pk).update(label_status={status!r})\n'
                        '    print(image.pk)').strip().splitlines()[-1]


def test_검수_화면도_라벨_결과와_결함_내역을_보인다(page, base_url, admin_password, demo):
    """seed_demo FAN-PANEL-CLS(분류)의 라벨된 이미지 하나를 제출됨으로 잠깐 돌려 읽는다. 승인·재작업은 누르지 않고
    끝나면 승인으로 되돌린다 — 스냅샷을 만들면 제출된 이미지가 남지 않아 개발 DB 에 기대지 않는다."""
    image_id = _set_label_status(demo['cls'], None, 'SUBMITTED')
    try:
        login(page, base_url, 'admin', admin_password)
        page.goto(f'{base_url}/gui/wm_data_review/?inspection_item={demo["cls"]}', wait_until='networkidle')
        rows = mes(page, f'/api/item/review?action=list&item_id={demo["cls"]}')['rows']
        row = next(r for r in rows if str(r['id']) == image_id)
        grid = page.inner_text('#main-grid')
        assert '라벨 결과' in grid and '라벨 영역' not in grid
        page.locator('#main-grid').get_by_text(row['original_name'], exact=True).first.click()
        page.wait_for_selector('#detailBody table')
        detail = page.inner_text('#detailBody table')
        assert f"라벨 결과\t{row['label_result']}" in detail and '결함 내역' in detail, detail
        assert page.locator('#detailBody .label-summary-chip').count() == 1
    finally:
        _set_label_status(demo['cls'], image_id, 'APPROVED')
