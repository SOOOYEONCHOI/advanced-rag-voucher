"""품목·BOM 조회 화면(`wm_product_bom`) — 검색, 상세, 하위 BOM 트리(소요량), 사용처 트리.

품목·BOM 은 인터페이스 반영으로만 들어와 화면에 등록 기능이 없다. 자기 품목(`E2E-`)을 manage.py 로 만들고 지운다.
"""
import pytest

from tests.e2e.conftest import login, manage_shell

CLEAN = ("from domain.models.basic import Bom, Product\n"
         "Bom.objects.filter(Parent__Code__startswith='E2E-').delete()\n"
         "Product.objects.filter(Code__startswith='E2E-').delete()")
# E2E-R ─ E2E-A(2) ─ E2E-X(3)
MAKE = CLEAN + ("\np = {c: Product.objects.create(Code=c, PartNo=c.split('.')[0], Revision='A', Name='NAME ' + c, PartType=t)"
                " for c, t in (('E2E-R.A', 'FSC'), ('E2E-A.A', '기구'), ('E2E-X.A', '구매품'))}\n"
                "Bom.objects.create(Parent=p['E2E-R.A'], Child=p['E2E-A.A'], Qty=2, Seq=1)\n"
                "Bom.objects.create(Parent=p['E2E-A.A'], Child=p['E2E-X.A'], Qty=3, Seq=1)")


@pytest.fixture
def e2e_bom():
    manage_shell(MAKE)
    yield
    manage_shell(CLEAN)


def search(page, keyword, root_only=False):
    page.fill('#keyword', keyword)
    page.set_checked('#rootOnly', root_only)
    with page.expect_response(lambda r: 'action=list' in r.url):
        page.click('#btnSearch')
    page.wait_for_timeout(300)
    return page.locator('#main-grid .wzg-row').all_inner_texts()


def tree_rows(page, grid):
    """트리 행 글자. 펼침 아이콘(▼·▶)은 뺀다."""
    return [' '.join(t.replace('▼', ' ').replace('▶', ' ').split()) for t in page.locator(f'{grid} .wzg-row').all_inner_texts()]


def test_품목을_검색해_상세_하위_BOM_사용처를_본다(page, base_url, admin_password, e2e_bom):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_product_bom/', wait_until='domcontentloaded')
    page.wait_for_selector('#main-grid .wzg-container')

    assert len(search(page, 'E2E-')) == 3
    rows = search(page, 'E2E-', root_only=True)
    assert len(rows) == 1 and 'E2E-R.A' in rows[0]

    with page.expect_response(lambda r: 'action=tree' in r.url):
        page.locator('#main-grid').get_by_text('E2E-R.A', exact=True).click()
    page.wait_for_selector('#infoTables:not(.d-none)')
    assert page.locator('#infoPart').get_by_text('NAME E2E-R.A', exact=True).count() == 1

    page.click('a[href="#tabTree"]')
    page.wait_for_timeout(500)
    # 품목코드·품목명·유형·수량·소요량 — X 는 2 × 3 = 6 개가 든다
    assert any(r.startswith('E2E-X.A NAME E2E-X.A 구매품 3 6') for r in tree_rows(page, '#tree-grid')), tree_rows(page, '#tree-grid')

    search(page, 'E2E-X')
    with page.expect_response(lambda r: 'action=where_used' in r.url):
        page.locator('#main-grid').get_by_text('E2E-X.A', exact=True).click()
    page.click('a[href="#tabUsed"]')
    page.wait_for_timeout(500)
    used = tree_rows(page, '#used-grid')
    assert [r.split()[0] for r in used] == ['E2E-X.A', 'E2E-A.A', 'E2E-R.A'], used

    assert not page.console_errors, page.console_errors
