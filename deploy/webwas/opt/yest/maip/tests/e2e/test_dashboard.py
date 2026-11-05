"""대시보드 — 요약 카드·목록 행이 그 메뉴 탭을 연다. 자기 항목(E2E-DASH)만 만들고 지운다."""
import pytest

from tests.e2e.conftest import login, manage_shell

MAKE = ("import io\n"
        "from PIL import Image\n"
        "from django.core.files.uploadedfile import SimpleUploadedFile\n"
        "from domain.tenancy import tenant_atomic, current_tenant\n"
        "from domain.models.data import InspectionItem\n"
        "from domain.services.data.image import ImageService\n"
        "buf = io.BytesIO(); Image.new('RGB', (64, 48), (11, 22, 33)).save(buf, format='PNG')\n"
        "t = current_tenant()\n"
        "with tenant_atomic(t):\n"
        "    item = InspectionItem.objects.create(tenant=t, code='E2E-DASH', name='E2E 대시보드', task_type='OBJECT_DETECTION', status='ACTIVE')\n"
        "    ImageService.upload_images(item, [SimpleUploadedFile('e2e-dash.png', buf.getvalue(), content_type='image/png')])\n"
        "    image = item.datasets.get().images.get()\n"
        "    print(item.id, image.id)")
CLEAN = ("from domain.tenancy import tenant_atomic\n"
         "from domain.models.data import InspectionItem\n"
         "from domain.services.data.item_platform import ItemPlatformService\n"
         "with tenant_atomic():\n"
         "    ids = list(InspectionItem.objects.filter(code='E2E-DASH').values_list('id', flat=True))\n"
         "for item_id in ids: ItemPlatformService.delete_item(item_id)")


@pytest.fixture
def e2e_item():
    manage_shell(CLEAN)            # 지난 실행이 남긴 것
    item_id, image_id = map(int, manage_shell(MAKE).strip().splitlines()[-1].split())
    yield item_id, image_id
    manage_shell(CLEAN)


def dashboard(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/', wait_until='networkidle')
    frame = page.frame_locator('iframe[id="mnb_iframe_wm_dashboard"]')
    frame.locator('#summaryCards').wait_for(state='visible')
    return frame


def test_요약_카드는_이동하지_않고_최근_비전_검사_행은_비전_검사_이력_탭에서_그_검사를_연다(page, base_url, admin_password):
    frame = dashboard(page, base_url, admin_password)
    assert frame.locator('#summaryCards [data-menu]').count() == 0
    assert frame.locator('.header-title').first.is_hidden()           # 머리 카드(이름·즐겨찾기·설명)는 감춘다
    assert frame.locator('#visionCard .panel-link').count() == 0      # 전체 조회 링크 대신 행을 누른다
    row = frame.locator('#visionBody tr[data-inspection]').first
    if not row.count():
        pytest.skip('개발 DB 에 비전 검사 기록이 없다')
    row.hover()                                                       # 누르면 열리는 행은 hover 바탕(--brand-surface-2)
    assert 'rgb(247, 248, 249)' in row.locator('td').first.evaluate('td => getComputedStyle(td).boxShadow')
    inspection_id = row.get_attribute('data-inspection')
    row.click()
    page.wait_for_selector('.mnb-tab-panel.active[data-mid="wm_vis_inspection"]')
    history = page.frame_locator('.mnb-tab-panel[data-mid="wm_vis_inspection"] iframe')
    history.locator('#inspDetail tbody tr', has_text='검사 ID').wait_for(timeout=5000)
    assert history.locator('#inspDetail tbody tr', has_text='검사 ID').locator('td').inner_text() == inspection_id
    errors = [e for e in page.console_errors if 'Failed to load resource' not in e]
    assert not errors, errors


def test_라벨링_대기_이미지_행은_그_항목_탭의_라벨링_내부_탭에서_그_이미지를_연다(page, base_url, admin_password, e2e_item):
    item_id, image_id = e2e_item
    frame = dashboard(page, base_url, admin_password)
    # 방금 등록한 이미지라 최근 5장 맨 위다
    frame.locator(f'#imagesBody tr[data-image="{image_id}"]').click()
    mid = f'item{item_id}_wm_data_item_detail'
    page.wait_for_selector(f'.mnb-tab-panel.active[data-mid="{mid}"]')
    home = page.frame_locator(f'.mnb-tab-panel[data-mid="{mid}"] iframe')
    labeling = home.locator('#itemFrames .item-frame[data-screen="wm_data_labeling"]')
    labeling.wait_for(state='visible', timeout=5000)
    assert home.locator('#itemTabs .nav-link.active').inner_text() == '라벨링 작업'
    assert f'image={image_id}' in labeling.get_attribute('src')
    # 탭 화면(전체 목록)에는 다른 PC 저장소의 이미지가 섞일 수 있다 — 썸네일 404 는 보지 않는다
    errors = [e for e in page.console_errors if 'Failed to load resource' not in e]
    assert not errors, errors
