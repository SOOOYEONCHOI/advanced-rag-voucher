"""인터페이스 이력 화면(`wm_interface_log`) — 수신건 검색, 요약(상태·사유), 원본 데이터(종류마다 다른 열).

화면은 조회 전용이다. 자기 수신건(출처 `E2E-`)을 manage.py 로 만들고 지운다. 반영하지 않으므로 마스터(mst_*)는 건드리지 않는다.
"""
import pytest

from tests.e2e.conftest import login, manage_shell

CLEAN = ("from domain.models.interface import IfBatch\n"
         "IfBatch.objects.filter(SourceRef__startswith='E2E-').delete()")
MAKE = CLEAN + (
    "\nfrom domain.services.interface import receive\n"
    "receive('PLM_PART_BOM', [dict(Depth='1', PartErp='E2E-R.A', PartNo='E2E-R', PartVer='A.1', PartName='E2E 장비', Qty='1')],"
    " 'FILE', 'E2E-bom.xlsx')\n"
    "receive('ERP_PURCHASE_REQ', [dict(ReqNo='E2E-PRQ', ReqSeq='1')], 'FILE', 'E2E-prq.xlsx')\n"
    "IfBatch.objects.create(Kind='PLM_PART_BOM', SourceRef='E2E-broken.xlsx', RowCount=0, Status='RECEIVE_FAILED',"
    " Message='머리글이 PLM 품목·BOM 양식과 다릅니다.')")


@pytest.fixture
def e2e_batches():
    manage_shell(MAKE)
    yield
    manage_shell(CLEAN)


def rows_of(page, grid):
    return [' '.join(t.split()) for t in page.locator(f'{grid} .wzg-row').all_inner_texts()]


def pick(page, source):
    with page.expect_response(lambda r: 'action=detail' in r.url):
        page.locator('#main-grid').get_by_text(source, exact=True).click()
    page.wait_for_timeout(300)


def test_수신건을_검색해_요약과_원본_데이터를_본다(page, base_url, admin_password, e2e_batches):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_interface_log/', wait_until='domcontentloaded')
    page.wait_for_selector('#main-grid .wzg-container')

    page.fill('#source', 'E2E-')
    with page.expect_response(lambda r: 'action=list' in r.url):
        page.click('#btnSearch')
    page.wait_for_timeout(300)
    listed = rows_of(page, '#main-grid')
    assert len(listed) == 3, listed
    assert any('E2E-broken.xlsx' in r and '수신 실패' in r for r in listed), listed
    assert any('E2E-prq.xlsx' in r and '반영 대기' in r for r in listed), listed

    pick(page, 'E2E-broken.xlsx')
    assert page.locator('#summaryTable').get_by_text('머리글이 PLM 품목·BOM 양식과 다릅니다.', exact=True).count() == 1

    pick(page, 'E2E-bom.xlsx')
    assert page.locator('#summaryTable').get_by_text('반영 대기', exact=True).count() == 1
    page.click('a[href="#tabRows"]')
    page.wait_for_timeout(800)
    assert page.locator('#rows-grid').get_by_text('Part(ERP)', exact=True).count() == 1
    assert any('E2E-R.A' in r for r in rows_of(page, '#rows-grid'))

    # 종류가 바뀌면 원본 데이터 열도 그 종류의 원본 머리글로 바뀐다
    with page.expect_response(lambda r: 'action=rows' in r.url):
        pick(page, 'E2E-prq.xlsx')
    page.wait_for_timeout(500)
    assert page.locator('#rows-grid').get_by_text('요청번호', exact=True).count() == 1
    assert page.locator('#rows-grid').get_by_text('Part(ERP)', exact=True).count() == 0
    assert any('E2E-PRQ' in r for r in rows_of(page, '#rows-grid'))

    assert not page.console_errors, page.console_errors


def test_상세_정보의_버튼은_수신건_종류의_화면_탭을_연다(page, base_url, admin_password, e2e_batches):
    """상세 정보 머리 오른쪽 — PLM 품목·BOM 은 [품목·BOM 조회], ERP 구매요청 현황은 [입고 내역]만 보이고,
    누르면 그 메뉴 탭을 열고 그리로 옮긴다(사용자 결정 2026-10-22)."""
    login(page, base_url, 'admin', admin_password)
    page.wait_for_selector('#sideNavAll .menu-leaf-link[data-mid="wm_interface_log"]', state='attached', timeout=15000)
    open_log = "() => window.myMenu.openMenu('wm_interface_log', '인터페이스 이력', '/gui/wm_interface_log/default')"
    page.evaluate(open_log)
    log = page.frame_locator('#mnb_iframe_wm_interface_log')
    log.locator('#main-grid .wzg-container').wait_for(timeout=10000)
    buttons = {'wm_receipt': log.locator('[data-open-menu="wm_receipt"]'),
               'wm_product_bom': log.locator('[data-open-menu="wm_product_bom"]')}
    assert not any(b.is_visible() for b in buttons.values()), '수신건을 고르기 전에 버튼이 보인다'

    log.locator('#source').fill('E2E-')
    log.locator('#btnSearch').click()
    for source, mid, label in (('E2E-bom.xlsx', 'wm_product_bom', '품목·BOM 조회'), ('E2E-prq.xlsx', 'wm_receipt', '입고 내역')):
        with page.expect_response(lambda r: 'action=detail' in r.url):
            log.locator('#main-grid').get_by_text(source, exact=True).click()
        page.wait_for_timeout(300)
        assert [m for m, b in buttons.items() if b.is_visible()] == [mid], source
        buttons[mid].click()
        page.wait_for_selector(f'.mnb-tab-panel.active[data-mid="{mid}"] iframe', timeout=10000)
        assert page.frame_locator(f'#mnb_iframe_{mid}').locator('.header-title').inner_text().strip().startswith(label)
        page.evaluate(open_log)
    assert not page.console_errors, page.console_errors
