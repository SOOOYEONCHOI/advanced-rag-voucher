"""이미지가 화면 영역에 맞춰 보인다(데이터 목록 상세·라벨링·검수 상세).

"맞춤"은 비율을 지키며 가로·세로 중 먼저 닿는 쪽에 맞추는 것이다. 작은 이미지도 키운다.
아주 작은 이미지(64x48)와 큰 이미지(1600x1200)를 함께 본다.

실제 DB 를 쓴다. `item` 픽스처가 `E2E-` 검사항목을 만들고 지운다.
"""
import pytest

from tests.e2e.test_crud import mes
from tests.e2e.test_write_paths import item, send  # noqa: F401 — item 은 픽스처다

SIZES = {'e2e-fit-small.png': (64, 48), 'e2e-fit-large.png': (1600, 1200)}

# 상자에 맞았는지: 가로나 세로 한쪽이 상자와 같고(2px), 어느 쪽도 상자를 넘지 않는다.
FIT_JS = """([imageSelector, boxSelector, usePadding]) => {
    const image = document.querySelector(imageSelector).getBoundingClientRect();
    const box = document.querySelector(boxSelector);
    const style = getComputedStyle(box);
    const pad = usePadding ? [parseFloat(style.paddingLeft) + parseFloat(style.paddingRight),
                              parseFloat(style.paddingTop) + parseFloat(style.paddingBottom)] : [0, 0];
    return {image: [image.width, image.height], box: [box.clientWidth - pad[0], box.clientHeight - pad[1]]};
}"""


def assert_fit(page, image_selector, box_selector, use_padding=False, min_box_height=0):
    size = page.evaluate(FIT_JS, [image_selector, box_selector, use_padding])
    (width, height), (box_width, box_height) = size['image'], size['box']
    # 상자가 이미지 크기로 줄어들면 위 검사가 늘 맞는다 — 상자 자체가 영역을 차지하는지도 본다.
    assert box_height >= min_box_height, size
    assert width <= box_width + 1 and height <= box_height + 1, size
    assert abs(width - box_width) <= 2 or abs(height - box_height) <= 2, size
    return width, height


@pytest.fixture
def fit_images(tmp_path):
    from PIL import Image
    paths = []
    for name, size in SIZES.items():
        path = tmp_path / name
        Image.new('RGB', size, (180, 90, 60)).save(path)
        paths.append(str(path))
    return paths


def test_세_화면에서_이미지가_영역에_맞는다(page, base_url, item, fit_images):
    item_id = item['id']
    page.goto(f'{base_url}/gui/wm_data_image/?inspection_item={item_id}', wait_until='networkidle')
    page.get_by_role('button', name='데이터 추가').click()
    page.set_input_files('#imageFiles', fit_images)
    send(page, lambda: page.click('#startUpload'))
    page.wait_for_selector('#uploadModal', state='hidden', timeout=15000)

    # 데이터 목록 상세
    for name in SIZES:
        page.locator('#main-grid').get_by_text(name, exact=True).click()
        page.wait_for_timeout(900)
        assert_fit(page, '.image-detail-coordinate-surface > img', '.image-detail-preview', min_box_height=360)

    # 라벨링: 100% 는 캔버스 안쪽에 맞춘 크기, 150% 는 그 1.5배이고 캔버스가 스크롤된다
    page.goto(f'{base_url}/gui/wm_data_labeling/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(1000)
    for name in SIZES:
        page.locator('#imageQueue .image-item', has_text=name).click()
        page.wait_for_timeout(600)
        assert page.inner_text('#zoomValue') == '100%'
        width, height = assert_fit(page, '#annotationImage', '#canvasHolder', use_padding=True)
        page.click('#zoomIn')
        page.click('#zoomIn')
        assert page.inner_text('#zoomValue') == '150%'
        zoomed = page.locator('#annotationImage').bounding_box()
        assert abs(zoomed['width'] - width * 1.5) <= 3 and abs(zoomed['height'] - height * 1.5) <= 3, (zoomed, width, height)
        assert page.evaluate("""() => { const h = document.getElementById('canvasHolder');
            return h.scrollWidth > h.clientWidth || h.scrollHeight > h.clientHeight; }""")

    # 검수 상세: 두 장을 제출 상태로 만든 뒤 본다
    queue = mes(page, f'/api/item/labeling?action=queue&item_id={item_id}')
    for image in queue['images']:
        claimed = mes(page, '/api/item/labeling?action=claim', {'item_id': item_id, 'image_id': image['id']})
        task = claimed['task']
        submitted = mes(page, '/api/item/labeling?action=submit',
                        {'item_id': item_id, 'task_id': task['id'], 'lease_token': task['lease_token']})
        assert submitted.get('success') is not False, submitted
    page.goto(f'{base_url}/gui/wm_data_review/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(800)
    for name in SIZES:
        page.locator('#main-grid').get_by_text(name, exact=True).click()
        page.wait_for_timeout(900)
        assert_fit(page, '.image-detail-coordinate-surface > img', '.image-detail-preview', min_box_height=360)
