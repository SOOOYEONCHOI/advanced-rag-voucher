"""비전검사항목 관리(검사 관리 > `wm_data_item`) — 대분류(고정) › 중분류(양식 매핑) › 비전검사항목 트리(설계 2026-10-21 §3).

실제 DB 에 쓴다. 분류·양식·비전검사항목은 모두 `E2E-` 이름이고 끝나면 지운다.
"""
import time

import pytest

from tests.e2e.conftest import manage_shell
from tests.e2e import test_crud
from tests.e2e.test_crud import confirm, mes, open_screen, select_item   # 테스트 클래스를 가져오면 여기서도 한 번 더 돈다

FORM_CODE = 'E2E-CAT-F1'


@pytest.fixture
def section_form():
    """매핑할 수입 섹션 양식 하나(E2E). 끝나면 분류(E2E-)와 함께 지운다."""
    manage_shell('from domain.models.dig_form import DigForm\n'
                 f'DigForm.objects.get_or_create(Code={FORM_CODE!r}, Version=1, defaults=dict('
                 'Title="E2E 분류 매핑 양식", FormType="INCOMING", LayoutType="SECTION", UseYN="Y"))')
    try:
        yield FORM_CODE
    finally:
        manage_shell('from domain.models.data import InspectionCategory\n'
                     'from domain.models.dig_form import DigForm\n'
                     'from domain.tenancy import tenant_atomic\n'
                     'with tenant_atomic():\n'
                     '    InspectionCategory.objects.filter(name__startswith="E2E-", parent__isnull=False).delete()\n'
                     '    InspectionCategory.objects.filter(name__startswith="E2E-").delete()\n'
                     f'DigForm.objects.filter(Code={FORM_CODE!r}).delete()')


def row_of(page, name):
    return page.evaluate('name => page.rows.find(r => r.name === name) || null', name)


def choose(page, name):
    """트리 행을 이름으로 고른다(화면 밖 행도)."""
    page.evaluate("""name => { const row = page.rows.find(r => r.name === name);
        page.grid.setSelectionByRowId(row.id); page.leave(() => page.show(row)); }""", name)
    page.wait_for_timeout(800)


def register(page, button, modal, fields, submit):
    page.click(button)
    page.wait_for_selector(f'{modal}.show')
    for selector, value in fields:
        if selector.endswith('Parent') or selector.endswith('FormCode') or selector.endswith('FormType') \
                or selector.endswith('Category'):
            page.wait_for_timeout(500)
            page.select_option(selector, value)
        else:
            page.fill(selector, value)
    page.click(submit)
    page.wait_for_timeout(1200)


def test_대분류는_고정이고_중분류를_등록해_양식을_매핑하고_고치고_지운다(page, base_url, admin_password, section_form):
    """대분류는 수입검사·품질검사·미분류로 고정이다 — 등록 버튼이 없고 고른 대분류는 읽기만 한다(사용자 결정 2026-10-21)."""
    minor = f'E2E-중분류-{int(time.time())}'
    open_screen(page, base_url, admin_password, 'wm_data_item')
    assert page.locator('#btnNewMajor').count() == 0
    majors = page.evaluate("() => page.rows.filter(r => r.kind === 'major').map(r => r.name)")
    assert majors == ['수입검사', '품질검사', '미분류'], majors
    choose(page, '수입검사')
    assert page.locator('#categoryTitle').inner_text() == '대분류 상세'
    assert page.locator('#btnCatEdit').is_hidden() and page.locator('#btnCatDelete').is_hidden()
    major_row = row_of(page, '수입검사')

    register(page, '#btnNewMinor', '#minorCreateModal',
             [('#minorParent', str(major_row['category_id'])), ('#minorName', minor), ('#minorFormCode', section_form)],
             '#btnCreateMinor')
    minor_row = row_of(page, minor)
    assert minor_row['parent_id'] == major_row['id']
    assert minor_row['mapped_label'].startswith('양식 ' + section_form + ' · ')
    assert page.locator('#btnCatEdit').is_visible()

    # 수정 — 매핑을 풀고 이름을 바꾼다
    choose(page, minor)
    page.click('#btnCatEdit')
    page.fill('#cat_name', minor + '-수정')
    page.select_option('#cat_form_code', '')
    page.click('#btnCatSave')
    page.wait_for_timeout(1200)
    edited = row_of(page, minor + '-수정')
    assert edited and edited['form_code'] == ''

    choose(page, minor + '-수정')
    page.click('#btnCatDelete')
    confirm(page)
    assert row_of(page, minor + '-수정') is None
    assert not page.console_errors, page.console_errors


def test_비전검사항목을_중분류에_등록하면_그_중분류는_지우지_않는다(page, base_url, admin_password, section_form):
    stamp = int(time.time())
    minor, item = f'E2E-중분류-{stamp}', f'E2E-분류항목-{stamp}'
    open_screen(page, base_url, admin_password, 'wm_data_item')
    major_id = row_of(page, '수입검사')['category_id']
    minor_id = mes(page, '/api/item/category?action=save_minor', {'parent_id': major_id, 'name': minor})['id']
    page.evaluate('() => page.load()')
    page.wait_for_timeout(1000)
    choose(page, minor)
    register(page, '#btnNew', '#itemCreateModal', [('#itemCreateName', item)], '#btnCreateItem')
    item_row = page.evaluate('name => page.rows.find(r => r.kind === "item" && r.item_name === name)', item)
    try:
        assert item_row['category_id'] == minor_id            # 고른 중분류가 기본값
        assert page.locator('#itemCard').is_visible()
        choose(page, minor)
        page.click('#btnCatDelete')
        confirm(page)
        assert '비전검사항목이 있는 중분류는 지울 수 없습니다.' in page.locator('#commonAlertModal').inner_text()
    finally:
        test_crud.TestItemDeletionReview()._cleanup(page, item_row['item_id'])


def test_플랫폼_관리자가_아니면_비전검사항목_버튼이_없고_분류는_고친다(page, base_url, admin_password):
    def not_admin(route):
        response = route.fetch()
        body = response.json()
        body['can_manage_items'] = False
        route.fulfill(response=response, json=body)

    page.route('**/api/item/category?action=tree*', not_admin)
    open_screen(page, base_url, admin_password, 'wm_data_item')
    assert page.locator('#btnNew').count() == 0
    assert page.locator('#btnNewMinor').is_visible()
    assert page.locator('#memberCard').count() == 0
