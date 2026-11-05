"""라벨링 워크플로우 전체 — 이미지 수집부터 데이터셋 zip 받기까지 화면을 눌러 본다.

수집은 두 경로다. 비전검사 클라이언트가 `/api/v1/inspections` 로 보낸 JPEG 와, 사람이 데이터 목록
[데이터 추가]로 올린 파일. 둘 다 데이터 목록 확인·편집 → 라벨링(BBOX·Polygon) → 검수(재작업·완료)
→ 스냅샷 → 화면의 [받기] 로 이어지고, 받은 zip 의 내용까지 본다.

실제 DB 를 쓴다. `E2E-WF-` Client 자격증명과 `E2E-` 검사항목을 만들고 `finally` 에서 지운다.
Client 자격증명·검사 기록은 화면에 삭제 기능이 없어 `manage_shell` 로 지운다. 워커는 `run_worker_once` 로 돌린다.
"""
import io
import json
import time
import zipfile
from types import SimpleNamespace

import pytest
from PIL import Image

from scripts.dev.send_inspections import defect_jpeg, metadata
from tests.e2e.conftest import login, manage_shell
from tests.e2e import test_crud
from tests.e2e.test_crud import mes
from tests.e2e.test_image_fit import assert_fit
from tests.e2e.test_write_paths import CONFIRM_OK, mes_get, run_worker_once, send

REWORK_REASON = 'E2E 경계를 넓혀 주세요'


@pytest.fixture
def workflow(page, base_url, admin_password, tmp_path):
    """임시 Client 자격증명 하나와, 테스트가 만드는 검사항목들. 끝나면 검사 기록 → 검사항목 → Client 순으로 지운다
    (검사 기록이 있으면 검사항목을 지울 수 없고, Client 서비스 계정은 이미지의 업로더다)."""
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_data_item/', wait_until='networkidle')
    client_id = f'E2E-WF-{int(time.time() * 1000)}'
    saved = mes(page, '/api/vision/client?action=save', {'client_id': client_id, 'name': 'E2E 워크플로우'})
    assert saved.get('success'), saved
    state = SimpleNamespace(base_url=base_url, client_id=client_id, api_key=saved['api_key'], items=[], tmp_path=tmp_path)
    try:
        yield state
    finally:
        manage_shell(f'from domain.models.vision import VisionInspection\n'
                     f'VisionInspection.objects.filter(client__client_id={client_id!r}).delete()')
        page.goto(f'{base_url}/gui/wm_data_item/', wait_until='networkidle')
        for item_id in state.items:
            test_crud.TestItemDeletionReview()._cleanup(page, item_id)
        manage_shell(f'from django.contrib.auth.models import User\n'
                     f'from domain.models.vision import VisionClient\n'
                     f'from domain.tenancy import tenant_atomic\n'
                     f'VisionClient.objects.filter(client_id={client_id!r}).delete()\n'
                     f'with tenant_atomic():\n'
                     f'    User.objects.filter(username={"svc-" + client_id.lower()!r}).delete()')
        for item_id in state.items:
            assert test_crud.TestItemDeletionReview.detail(page, item_id) is None


def create_item(page, state, task_type, label, display_name, shape):
    """검사항목과 라벨 클래스 하나. 라벨 도형은 BBOX 만 새로 만들 수 있다 — 이상 탐지는 라벨링 화면이 Polygon 으로 그린다."""
    created = mes(page, '/api/item/item_admin?action=create', {'name': f'E2E-워크플로우-{int(time.time() * 1000)}', 'task_type': task_type})
    assert created.get('success'), created
    state.items.append(created['item_id'])
    label_created = mes(page, '/api/item/item_home?action=label_create',
                        {'item_id': created['item_id'], 'name': label, 'display_name_ko': display_name,
                         'color': '#E4572E', 'is_defect': 'true', 'annotation_shape': shape})
    assert label_created.get('success'), label_created
    return created['item_id']


def send_capture(page, state, item_id, content):
    """Client 처럼 보낸다. 데이터 목록의 파일명은 `<검사 id>.jpg` 다."""
    response = page.request.post(f'{state.base_url}/api/v1/inspections',
                                 headers={'X-Client-ID': state.client_id, 'X-API-Key': state.api_key},
                                 multipart={'image': {'name': 'capture.jpg', 'mimeType': 'image/jpeg', 'buffer': content},
                                            'metadata': json.dumps(metadata(state.client_id, item_id))})
    assert response.status == 201, response.text()[:300]
    return f"{response.json()['data']['id']}.jpg"


def upload_on_screen(page, state, item_id, files):
    """데이터 목록 [데이터 추가]로 올린다. files: {파일명: 바이트}."""
    paths = []
    for name, content in files.items():
        path = state.tmp_path / name
        path.write_bytes(content)
        paths.append(str(path))
    page.goto(f'{state.base_url}/gui/wm_data_image/?inspection_item={item_id}', wait_until='networkidle')
    page.get_by_role('button', name='데이터 추가').click()
    page.set_input_files('#imageFiles', paths)
    send(page, lambda: page.click('#startUpload'))
    page.wait_for_selector('#uploadModal', state='hidden', timeout=15000)


def as_png(content):
    buffer = io.BytesIO()
    Image.open(io.BytesIO(content)).save(buffer, format='PNG')
    return buffer.getvalue()


def image_ids(page, item_id):
    rows = mes(page, f'/api/item/image?action=list&item_id={item_id}&page=1&page_size=50')['rows']
    return {row['original_name']: row['id'] for row in rows}


def open_labeling(page, state, item_id):
    page.goto(f'{state.base_url}/gui/wm_data_labeling/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(1000)


def select_image(page, image_id):
    page.locator(f'#imageQueue .image-item[data-image-id="{image_id}"]').click()
    page.wait_for_timeout(500)


def drag_bbox(page, start, end):
    box = page.locator('#annotationImage').bounding_box()
    page.mouse.move(box['x'] + box['width'] * start, box['y'] + box['height'] * start)
    page.mouse.down()
    page.mouse.move(box['x'] + box['width'] * end, box['y'] + box['height'] * end, steps=5)
    page.mouse.up()


def label_bbox(page, image_id, start, end):
    select_image(page, image_id)
    send(page, lambda: page.click('#startTask'))
    page.locator('#labelClassList .label-class').first.click()
    drag_bbox(page, start, end)
    send(page, lambda: page.click('#saveAnnotations'))
    send(page, lambda: page.click('#submitTask'))


def review(page, state, item_id, decisions):
    """decisions: {파일명: None(검수 완료) 또는 재작업 사유}."""
    page.goto(f'{state.base_url}/gui/wm_data_review/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(800)
    for name, reason in decisions.items():
        page.locator('#main-grid').get_by_text(name, exact=True).click()
        page.wait_for_timeout(900)
        assert_fit(page, '.image-detail-coordinate-surface > img', '.image-detail-preview', min_box_height=360)
        if reason:
            page.fill('#reworkReason', reason)
            send(page, lambda: page.click('#btnRework'))
        else:
            send(page, lambda: page.click('#btnApprove'))
        page.wait_for_timeout(900)


def download_snapshot(page, state, item_id):
    """스냅샷 등록 → 워커 → 화면의 [받기]를 눌러 받은 zip. 형식은 검사 유형마다 고정이라 화면에 보이지 않는다."""
    page.goto(f'{state.base_url}/gui/wm_data_snapshot/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(800)
    page.click('#btnNew')
    page.wait_for_selector('#snapshotCreateModal.show')
    send(page, lambda: page.click('#btnCreateSnapshot'))
    run_worker_once()
    page.click('#btnSearch')
    link = page.locator('#main-grid a', has_text='받기').first
    link.wait_for(timeout=8000)
    with page.expect_download() as info:
        link.click()
    return zipfile.ZipFile(info.value.path())


def test_객체검출_Client_전송과_화면_업로드에서_COCO_zip_까지(page, workflow):
    state = workflow
    item_id = create_item(page, state, 'OBJECT_DETECTION', 'e2e_scratch', '긁힘', 'BBOX')

    # 1. 수집: Client 3장(긁힘 2·정상 1) + 화면에서 파일 업로드 1장(긁힘, PNG)
    scratch1 = send_capture(page, state, item_id, defect_jpeg('scratch', seed=f'{state.client_id}-1'))
    scratch2 = send_capture(page, state, item_id, defect_jpeg('scratch', seed=f'{state.client_id}-2'))
    normal = send_capture(page, state, item_id, defect_jpeg('normal', seed=state.client_id))
    scratch3 = 'e2e-wf-scratch3.png'
    upload_on_screen(page, state, item_id, {scratch3: as_png(defect_jpeg('scratch', seed=f'{state.client_id}-3'))})
    ids = image_ids(page, item_id)
    assert set(ids) == {scratch1, scratch2, normal, scratch3}

    # 2. 데이터 목록: 수집 경로가 보이고, 상세 미리보기가 맞춤 크기다. 정상 이미지를 회전했다가 원본으로 되돌린다
    page.goto(f'{state.base_url}/gui/wm_data_image/?inspection_item={item_id}', wait_until='networkidle')
    page.wait_for_timeout(800)
    grid = page.locator('#main-grid')
    assert (grid.get_by_text('클라이언트', exact=True).count(), grid.get_by_text('파일 업로드', exact=True).count()) == (3, 1)
    grid.get_by_text(scratch1, exact=True).click()
    page.wait_for_timeout(900)
    assert_fit(page, '.image-detail-coordinate-surface > img', '.image-detail-preview', min_box_height=360)
    assert state.client_id in page.inner_text('#detailBody')
    grid.get_by_text(normal, exact=True).click()
    page.wait_for_timeout(900)
    page.get_by_role('button', name='이미지 편집').click()
    page.wait_for_selector('#preprocessModal.show')
    send(page, lambda: page.click('#preprocessRotateRight'))
    assert mes(page, f'/api/item/image?action=detail&item_id={item_id}&image_id={ids[normal]}')['width'] == 480
    send(page, lambda: page.click('#preprocessReset'))
    assert mes(page, f'/api/item/image?action=detail&item_id={item_id}&image_id={ids[normal]}')['width'] == 640
    page.keyboard.press('Escape')

    # 3. 라벨링: 긁힘 3장은 BBOX, 정상은 결함 없음으로 제출(확인을 거친다)
    open_labeling(page, state, item_id)
    for name in (scratch1, scratch2, scratch3):
        label_bbox(page, ids[name], 0.3, 0.6)
    select_image(page, ids[normal])
    send(page, lambda: page.click('#startTask'))
    page.click('#submitTask')
    page.wait_for_selector(CONFIRM_OK, state='visible')
    send(page, lambda: page.click(CONFIRM_OK))

    # 4. 검수: 긁힘 1 은 재작업, 나머지는 검수 완료
    review(page, state, item_id, {scratch1: REWORK_REASON, scratch2: None, scratch3: None, normal: None})

    # 5. 재작업: 사유가 보이고, 기존 영역을 지우고 더 넓게 다시 그린다
    open_labeling(page, state, item_id)
    select_image(page, ids[scratch1])
    assert REWORK_REASON in page.inner_text('#reworkReasonBanner')
    send(page, lambda: page.click('#startTask'))
    page.locator('#annotationList .annotation-delete').first.click()
    page.locator('#labelClassList .label-class').first.click()
    drag_bbox(page, 0.2, 0.7)
    send(page, lambda: page.click('#saveAnnotations'))
    send(page, lambda: page.click('#submitTask'))

    # 6. 검수 완료 → 검수 대기가 비었다
    review(page, state, item_id, {scratch1: None})
    assert mes_get(page, f'/api/item/review?action=list&item_id={item_id}&page=1&page_size=20')['totalRows'] == 0

    # 7·8. 스냅샷(COCO) → 받은 zip: JPEG 3·PNG 1, 주석 3, 긁힘 1 은 다시 그린 좌표다
    archive = download_snapshot(page, state, item_id)
    names = archive.namelist()
    jpgs = [n for n in names if n.startswith('images/') and n.endswith('.jpg')]
    pngs = [n for n in names if n.startswith('images/') and n.endswith('.png')]
    assert (len(jpgs), len(pngs)) == (3, 1), names
    assert all(archive.read(n)[:2] == b'\xff\xd8' for n in jpgs)
    assert archive.read(pngs[0])[:4] == b'\x89PNG'
    instances = json.loads(archive.read('annotations/instances.json'))
    assert len(instances['images']) == 4
    assert [c['name'] for c in instances['categories']] == ['e2e_scratch']
    assert len(instances['annotations']) == 3
    redrawn = next(a for a in instances['annotations'] if a['image_id'] == ids[scratch1])
    for value, expected, size in zip(redrawn['bbox'], (0.2 * 640, 0.2 * 480, 0.5 * 640, 0.5 * 480), (640, 480, 640, 480)):
        assert abs(value - expected) <= 0.03 * size, redrawn['bbox']


def test_이상탐지_Client_전송과_화면_업로드에서_MVTec_zip_까지(page, workflow):
    state = workflow
    item_id = create_item(page, state, 'ANOMALY_DETECTION', 'e2e_dent', '찍힘', 'BBOX')

    # 1. 수집: 찍힘은 Client, 정상은 화면에서 파일 업로드(JPEG)
    dent = send_capture(page, state, item_id, defect_jpeg('dent', seed=state.client_id))
    normal = 'e2e-wf-normal.jpg'
    upload_on_screen(page, state, item_id, {normal: defect_jpeg('normal', seed=state.client_id)})
    ids = image_ids(page, item_id)

    # 2. 라벨링: 찍힘은 결함 유형 → Polygon 4점 → Enter. 정상은 아무것도 그리지 않고 제출(확인을 거친다, DEC-032)
    open_labeling(page, state, item_id)
    select_image(page, ids[dent])
    send(page, lambda: page.click('#startTask'))
    page.locator('#labelClassList .label-class', has_text='찍힘').click()
    box = page.locator('#annotationImage').bounding_box()
    for x, y in ((0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)):
        page.mouse.click(box['x'] + box['width'] * x, box['y'] + box['height'] * y)
    page.keyboard.press('Enter')
    send(page, lambda: page.click('#saveAnnotations'))
    send(page, lambda: page.click('#submitTask'))
    select_image(page, ids[normal])
    send(page, lambda: page.click('#startTask'))
    assert page.locator('#labelClassList .label-class', has_text='정상').count() == 0
    page.click('#submitTask')
    page.wait_for_selector(CONFIRM_OK, state='visible')
    send(page, lambda: page.click(CONFIRM_OK))

    # 3. 검수 완료
    review(page, state, item_id, {dent: None, normal: None})

    # 4·5. 스냅샷(MVTec AD) → 받은 zip: 정상은 train/good, 찍힘은 test/e2e_dent, 마스크는 그린 Polygon 자리다
    archive = download_snapshot(page, state, item_id)
    names = archive.namelist()
    good = [n for n in names if n.startswith('train/good/')]
    defect = [n for n in names if n.startswith('test/e2e_dent/')]
    masks = [n for n in names if n.startswith('ground_truth/e2e_dent/')]
    assert (len(good), len(defect), len(masks)) == (1, 1, 1), names
    assert good[0].endswith('.jpg') and defect[0].endswith('.jpg')
    mask = Image.open(io.BytesIO(archive.read(masks[0]))).convert('L')
    assert mask.size == (640, 480)
    white = [(x, y) for y in range(0, 480, 4) for x in range(0, 640, 4) if mask.getpixel((x, y)) == 255]
    assert white
    center_x = sum(x for x, _ in white) / len(white)
    center_y = sum(y for _, y in white) / len(white)
    assert abs(center_x - 320) <= 0.05 * 640 and abs(center_y - 240) <= 0.05 * 480, (center_x, center_y)
