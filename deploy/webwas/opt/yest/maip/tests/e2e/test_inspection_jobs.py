"""입고 → 수입검사 흐름 — 양식 기준 품목 매핑, 입고 내역, 수입검사 작성의 검사 작업 목록(대기·작성 중), 자재입고 검색, 메뉴 검사 대기 배지
(설계 2026-10-21 §6).

자기 데이터(`E2E-` 양식·품목·입고·매핑·작성건)를 manage.py 로 만들고 지운다.
E2E-P 는 양식이 매핑된 품번(검사 대상), E2E-Q 는 매핑이 없는 품번이다.
"""
import json
import textwrap
import time

import pytest

from tests.e2e.conftest import login, manage_shell

CLEAN = textwrap.dedent("""
    from domain.models.basic import Product, ProductForm, Receipt
    from domain.models.dig_form import DigForm, DigFormItem, DigFormItemResult, DigFormResult, DigFormSection
    results = DigFormResult.objects.filter(WorkOrderNumber__startswith='E2E-PRQ')
    DigFormItemResult.objects.filter(DigFormResult__in=results).delete()
    results.delete()
    forms = DigForm.objects.filter(Code__startswith='E2E-I')
    DigFormResult.objects.filter(DigForm__in=forms).delete()
    DigFormItem.objects.filter(DigFormSection__DigForm__in=forms).delete()
    DigFormSection.objects.filter(DigForm__in=forms).delete()
    forms.delete()
    ProductForm.objects.filter(PartNo__startswith='E2E-').delete()
    Receipt.objects.filter(ReceiptNo__startswith='E2E-').delete()
    Product.objects.filter(Code__startswith='E2E-').delete()""")


@pytest.fixture
def receipt_flow():
    code = f'E2E-I{int(time.time()) % 10_000_000}'
    out = manage_shell(CLEAN + textwrap.dedent(f"""
        import datetime, json
        form = DigForm.objects.create(Code={code!r}, Title='E2E 수입 양식', LayoutType='GRID', FormType='INCOMING')
        section = DigFormSection.objects.create(DigForm=form, SectionType='INSPECTION', SortOrder=1, Width=12,
                                                ColumnCount=2, HeaderRowCount=1, WorkerColumnYN='N')
        DigFormItem.objects.create(DigFormSection=section, RowType='H', RowIndex=1, ColumnIndex=1, Content='항목', MinColumnWidth=100)
        DigFormItem.objects.create(DigFormSection=section, RowType='H', RowIndex=1, ColumnIndex=2, Content='값', MinColumnWidth=100)
        today = datetime.date.today()
        for seq, part in ((1, 'E2E-P'), (2, 'E2E-Q')):
            product = Product.objects.create(Code=part + '.A', PartNo=part, Revision='A', Name='E2E 품목 ' + part)
            Receipt.objects.create(ReceiptNo=f'E2E-PRQ-{{seq}}', ReqNo='E2E-PRQ', ReqSeq=seq, Product=product,
                                   ItemCode=product.Code, ItemName=product.Name, Qty=1, ReceiptDate=today)
        ProductForm.objects.create(PartNo='E2E-P', FormCode={code!r})
        print(json.dumps({{'code': form.Code, 'form_id': form.id}}))"""))
    created = json.loads(out.strip().splitlines()[-1])
    try:
        yield created
    finally:
        manage_shell(CLEAN)


def test_양식을_고르고_수정에서_품목을_추가하고_빼서_저장한다(page, base_url, admin_password, receipt_flow):
    """수입검사 품목 지정은 공통 CRUD 구조다 — 위 양식 목록, 아래 상세. [수정] 중 [품목 추가]·행 [삭제]는 [저장]에서 반영하고
    [취소]하면 되돌린다(설계 2026-10-21 §6, DESIGN §5.5)."""
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_product_form/', wait_until='networkidle')
    page.locator('#form-grid').get_by_text(receipt_flow['code'], exact=True).click()
    page.wait_for_function("() => page.itemGrid.getData().some(r => r.part_no === 'E2E-P')")
    assert page.input_value('#code') == receipt_flow['code']
    assert page.locator('#btnAddProduct').is_hidden()
    assert page.locator('#item-grid').get_by_role('button', name='삭제').count() == 0    # 읽기 전용

    def add(part_no):
        page.click('#btnAddProduct')
        page.wait_for_selector('#productAddModal.show')
        page.fill('#productKeyword', part_no)
        with page.expect_response(lambda r: 'action=products' in r.url):
            page.click('#btnProductSearch')
        page.wait_for_timeout(300)
        page.locator('#product-grid .wzg-row', has_text=part_no).locator('input[type=checkbox]').check()
        page.click('#btnAddChecked')
        page.wait_for_function(f"() => page.itemGrid.getData().some(r => r.part_no === {part_no!r})")

    def mapped():
        out = manage_shell(textwrap.dedent(f"""
            from domain.models.basic import ProductForm
            print(sorted(ProductForm.objects.filter(FormCode={receipt_flow['code']!r}).values_list('PartNo', flat=True)))"""))
        return out.strip().splitlines()[-1]

    # [취소]하면 더한 품목이 빠지고 저장되지 않는다
    page.click('#btnEdit')
    add('E2E-Q')
    page.click('#btnCancel')
    page.wait_for_function("() => !page.itemGrid.getData().some(r => r.part_no === 'E2E-Q')")
    assert mapped() == "['E2E-P']"

    # [저장]하면 더하고 뺀 것이 한 번에 반영된다
    page.click('#btnEdit')
    add('E2E-Q')
    page.locator('#item-grid .wzg-row', has_text='E2E-P').get_by_role('button', name='삭제').click()
    page.wait_for_function("() => !page.itemGrid.getData().some(r => r.part_no === 'E2E-P')")
    with page.expect_response(lambda r: 'action=save' in r.url):
        page.click('#btnSave')
    page.wait_for_selector('#btnEdit', state='visible')     # 저장 뒤 다시 읽어 읽기 전용으로 돌아온다
    page.wait_for_function("() => page.itemGrid.getData().map(r => r.part_no).join() === 'E2E-Q'")
    assert mapped() == "['E2E-Q']"
    assert not page.console_errors, page.console_errors


def test_입고_내역은_검사_정보_없이_입고를_찾는다(page, base_url, admin_password, receipt_flow):
    """기준정보 > 입고 내역 — 검사 상태·검사 대상만·[검사 작성]이 없다(설계 2026-10-21 §6)."""
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_receipt/', wait_until='networkidle')
    assert page.locator('#cboState, #targetOnly').count() == 0
    page.fill('#keyword', 'E2E-PRQ')
    with page.expect_response(lambda r: 'action=list' in r.url):
        page.click('#btnSearch')
    page.wait_for_timeout(300)
    rows = [' '.join(t.split()) for t in page.locator('#main-grid .wzg-row').all_inner_texts()]
    assert [r.split()[0] for r in rows] == ['E2E-PRQ-1', 'E2E-PRQ-2'], rows
    assert page.locator('#main-grid').get_by_role('button', name='검사 작성').count() == 0
    assert not page.console_errors, page.console_errors


def test_자재입고_검색은_검사_대상_입고를_골라_입고번호를_채운다(page, base_url, admin_password, receipt_flow):
    login(page, base_url, 'admin', admin_password)
    page.goto(f"{base_url}/gui/wm_dig_form_incoming_write/?form_id={receipt_flow['form_id']}", wait_until='networkidle')
    page.wait_for_selector('#work_order_number')
    with page.expect_response(lambda r: '/api/definition/receipt' in r.url):
        page.click('#btnFindWO')
    popup = page.locator('#digFormMatInSearchGrid')
    assert popup.get_by_text('E2E-PRQ-2', exact=True).count() == 0     # 검사 대상만
    popup.get_by_text('E2E-PRQ-1', exact=True).dblclick()
    page.wait_for_function("() => document.getElementById('work_order_number').value === 'E2E-PRQ-1'")


def set_result(form_id, state):
    manage_shell(textwrap.dedent(f"""
        from domain.models.dig_form import DigFormResult
        DigFormResult.objects.update_or_create(DigForm_id={form_id}, WorkOrderNumber='E2E-PRQ-1',
                                               defaults={{'WriteDate': '2026-10-21', 'State': {state!r}}})"""))


def job_rows(page):
    page.fill('#txtWorkOrder', 'E2E-PRQ')
    with page.expect_response(lambda r: 'action=job_list' in r.url):
        page.click('#btnSearch')
    page.wait_for_timeout(300)
    return [' '.join(t.split()) for t in page.locator('#workingGrid .wzg-row').all_inner_texts()]


def test_매핑한_입고는_대기로_나오고_작성하면_작성_중_완료하면_빠진다(page, base_url, admin_password, receipt_flow):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_write/', wait_until='networkidle')
    rows = job_rows(page)
    assert len(rows) == 1 and rows[0].startswith('작성 대기 E2E-PRQ-1'), rows        # 매핑 없는 E2E-PRQ-2 는 없다
    page.locator('#workingGrid .wzg-row', has_text='E2E-PRQ-1').get_by_role('button', name='작성').click()
    page.wait_for_selector('#work_order_number')
    page.wait_for_function("() => document.getElementById('work_order_number').value === 'E2E-PRQ-1'")

    set_result(receipt_flow['form_id'], 'working')
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_write/', wait_until='networkidle')
    assert job_rows(page)[0].startswith('열기 작성 중 E2E-PRQ-1')
    page.select_option('#cboKind', 'WAITING')
    page.wait_for_timeout(800)
    assert page.locator('#workingGrid .wzg-row', has_text='E2E-PRQ-1').count() == 0
    set_result(receipt_flow['form_id'], 'done')
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_write/', wait_until='networkidle')
    assert job_rows(page) == []
    assert not page.console_errors, page.console_errors


def test_좌측_메뉴의_수입_검사작성_작업에_검사_대기_건수_배지가_있다(page, base_url, admin_password, receipt_flow):
    login(page, base_url, 'admin', admin_password)
    selector = '#sideNavAll .menu-leaf-link[data-mid="wm_dig_form_incoming_write"]'
    page.wait_for_function("(s) => { const a = document.querySelector(s); return a && Number(a.getAttribute('data-badge')) >= 1; }",
                           arg=selector, timeout=10000)
    assert page.locator(selector).inner_text().strip() == '수입검사 작성'    # 배지는 메뉴 이름(글자)에 섞이지 않는다
    assert page.locator('#sideNavAll .menu-leaf-link[data-mid="wm_receipt"][data-badge]').count() == 0
