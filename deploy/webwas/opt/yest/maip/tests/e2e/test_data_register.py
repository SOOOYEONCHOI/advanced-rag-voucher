"""비전 데이터 등록 화면 — 파일 등록 → 목록·상세 → 편집 → 삭제. 자기 항목(E2E-REG)만 만들고 지운다."""
import pytest

from tests.e2e.conftest import login, manage_shell
from tests.e2e.test_write_paths import confirm_ok

MAKE = ("from domain.tenancy import tenant_atomic, current_tenant\n"
        "from domain.models.data import InspectionItem\n"
        "t = current_tenant()\n"
        "with tenant_atomic(t):\n"
        "    item, _ = InspectionItem.objects.get_or_create(code='E2E-REG', defaults={'tenant': t, 'name': 'E2E 등록', 'task_type': 'OBJECT_DETECTION'})\n"
        "    print(item.id)")
CLEAN = ("from domain.tenancy import tenant_atomic\n"
         "from domain.models.data import InspectionItem\n"
         "from domain.services.data.item_platform import ItemPlatformService\n"
         "with tenant_atomic():\n"
         "    ids = list(InspectionItem.objects.filter(code='E2E-REG').values_list('id', flat=True))\n"
         "for item_id in ids: ItemPlatformService.delete_item(item_id)")


@pytest.fixture
def e2e_item():
    item_id = int(manage_shell(MAKE).strip().splitlines()[-1])
    yield item_id
    manage_shell(CLEAN)


def test_파일로_등록하고_상세에서_편집하고_삭제한다(page, base_url, admin_password, e2e_item, tmp_path):
    from PIL import Image
    png = tmp_path / 'e2e-reg.png'
    Image.new('RGB', (64, 48), (10, 120, 30)).save(png)
    login(page, base_url, 'admin', admin_password)
    # 자기 항목으로 거른 화면을 연다 — 공유 DB 에는 다른 PC 저장소에만 파일이 있는 이미지가 있어 전체 목록은 썸네일이 404 다
    page.goto(f'{base_url}/gui/wm_data_register/?inspection_item={e2e_item}', wait_until='networkidle')
    page.click('#btnRegister')
    page.select_option('#registerItem', label='E2E-REG · E2E 등록')
    page.check('#registerKindFile')
    page.set_input_files('#registerFiles', str(png))
    with page.expect_response(lambda r: 'action=upload' in r.url):
        page.click('#registerSubmit')
    page.click('#registerModal .modal-footer [data-bs-dismiss="modal"]')
    page.wait_for_selector('#registerModal', state='hidden')
    page.wait_for_selector('#detailTable td:has-text("E2E-REG")')
    assert page.locator('#detailTable').get_by_text('파일 업로드', exact=True).count() == 1
    page.click('#btnPreprocess')
    page.wait_for_selector('#preprocessModal.show')
    # 편집 창은 화면 안에 들어온다(preview.css 의 .preprocess-canvas 60vh — 빠지면 이미지 원본 크기로 길어진다)
    dialog = page.evaluate("() => document.querySelector('#preprocessModal .modal-dialog').getBoundingClientRect().height")
    assert dialog <= page.viewport_size['height'], (dialog, page.viewport_size)
    with page.expect_response(lambda r: 'action=preprocess' in r.url):
        page.click('#preprocessRotateRight')
    page.locator('#preprocessModal [data-bs-dismiss="modal"]').last.click()
    page.click('#btnDelete')
    with page.expect_response(lambda r: 'action=delete' in r.url):
        confirm_ok(page)
    assert not page.console_errors, page.console_errors


def test_대시보드_등록_카드를_누르면_등록_탭이_열린다(page, base_url, admin_password, e2e_item):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/', wait_until='networkidle')
    frame = page.frame_locator('iframe[id="mnb_iframe_wm_dashboard"]')
    frame.locator('#registerCard').wait_for(state='visible')
    frame.locator('#registerCard [data-menu]').click()
    page.wait_for_selector('.mnb-tab-panel.active[data-mid="wm_data_register"]')
    # 탭이 여는 전체 목록에는 다른 PC 저장소의 이미지가 섞일 수 있다 — 썸네일 404 는 보지 않는다
    errors = [e for e in page.console_errors if 'Failed to load resource' not in e]
    assert not errors, errors
