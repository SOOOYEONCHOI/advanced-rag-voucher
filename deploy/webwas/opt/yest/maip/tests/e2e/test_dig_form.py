"""디지털 전환(디지털 양식) 화면 — 수입·품질 × 검사양식·검사작성·검사결과.

개발 DB 에 seed_dig_form 의 고객 양식이 있어야 한다.
쓰기 흐름은 `E2E-DF-` 입고번호/WO 로 자기 검사만 만들고 finally 에서 지운다(완료된 검사는 화면·API 로 지울 수 없다).
"""
import json
import textwrap
import time

import pytest

from scripts.dev.send_inspections import defect_jpeg
from tests.e2e.conftest import login, manage_shell
from tests.e2e.test_write_paths import confirm_ok, mes_get, send_mes

# 검사양식 관리(wm_dig_form_incoming_form)는 수입·품질을 한 화면에서 다룬다(사용자 결정 2026-10-21)
SCREENS = ['wm_dig_form_incoming_form', 'wm_dig_form_incoming_write', 'wm_dig_form_incoming_result',
           'wm_dig_form_outgoing_write', 'wm_dig_form_outgoing_result']
API = '/api/dig_form/dig_form'


def is_dig_form_api(response):
    return API in response.url or '/api/system/form_edit' in response.url


@pytest.mark.parametrize('gui_code', SCREENS)
def test_디지털_양식_화면이_오류_없이_열린다(page, base_url, admin_password, gui_code):
    errors = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    login(page, base_url, 'admin', admin_password)
    with page.expect_response(is_dig_form_api) as response:
        page.goto(f'{base_url}/gui/{gui_code}/', wait_until='networkidle')
    assert response.value.status == 200
    assert errors == []


def test_판정_코드_관리_화면이_그룹과_결과_코드를_트리로_보인다(page, base_url, admin_password):
    errors = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    login(page, base_url, 'admin', admin_password)
    with page.expect_response(lambda r: '/api/dig_form/judge_code' in r.url and 'action=read' in r.url) as response:
        page.goto(f'{base_url}/gui/wm_dig_form_judge_code/', wait_until='networkidle')
    assert response.value.status == 200
    codes = [row['code'] for row in response.value.json()]
    assert 'dig_form_okng' in codes and 'dig_form_pass_na' in codes
    assert errors == []


def test_수입_품질_메뉴는_탭_이름에_구분을_붙인다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    titles = page.evaluate("""() => Object.fromEntries(Array.from(
        document.querySelectorAll('.menu-leaf-link[data-mid^="wm_dig_form_"]'))
        .map(a => [a.getAttribute('data-mid'), a.getAttribute('data-tab-title')]))""")
    assert titles['wm_dig_form_incoming_write'] == '수입검사 작성'
    assert 'wm_dig_form_outgoing_form' not in titles          # 검사양식 관리 하나로 합쳤다


def test_검사양식_관리는_수입_품질_양식을_한_목록에_구분과_함께_보인다(page, base_url, admin_password):
    def is_read(response):
        return '/api/system/form_edit' in response.url and 'action=read' in response.url

    login(page, base_url, 'admin', admin_password)
    with page.expect_response(is_read) as response:
        page.goto(f'{base_url}/gui/wm_dig_form_incoming_form/', wait_until='networkidle')
    assert {row['form_type_label'] for row in response.value.json()} == {'수입검사', '품질검사'}
    assert page.locator('#form-grid').get_by_text('구분', exact=True).count() >= 1
    page.select_option('#cboFormType', 'OUTGOING')
    with page.expect_response(is_read) as response:
        page.click('#btnSearch')
    assert {row['form_type'] for row in response.value.json()} == {'OUTGOING'}
    page.click('#btnNew')                                     # 새 양식은 거른 구분이 기본값이고 고를 수 있다
    page.wait_for_selector('#title', state='visible')
    assert page.input_value('#form_type') == 'OUTGOING' and page.is_enabled('#form_type')


def test_양식_상세_조회_모달에_수정과_검사_작성이_있다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)    # superuser 는 검사양식 관리 RW
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_form/', wait_until='networkidle')
    page.locator('#form-grid button', has_text='조회').first.click()
    page.wait_for_selector('#previewInfo', state='visible')
    assert page.locator('#btnEdit').is_visible()
    assert page.locator('#btnWrite').is_visible()


@pytest.fixture
def outgoing_form(page, base_url, admin_password):
    """품질 검사양식 중 숫자 입력칸이 있는 양식 하나(고객 양식 DF0008). 로그인한 page 를 함께 쓴다."""
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/', wait_until='networkidle')
    forms = mes_get(page, f'{API}?action=form_list&form_type=OUTGOING&latest_only=Y')
    form = next((f for f in forms if f['code'] == 'DF0008'), None)
    if form is None:
        pytest.skip('DF0008 양식이 없다. 공유 개발 DB 의 옛 고객 양식이다(지금 seed_dig_form 에는 없다).')
    return form['id']


def remove_results(tag):
    manage_shell(
        'from domain.models.dig_form import DigFormItemResult, DigFormResult\n'
        f'ids = list(DigFormResult.objects.filter(WorkOrderNumber={tag!r}).values_list("id", flat=True))\n'
        'DigFormItemResult.objects.filter(DigFormResult_id__in=ids).delete()\n'
        'DigFormResult.objects.filter(id__in=ids).delete()')


def start_new(page, base_url, form_id, tag):
    """검사양식 [검사 작성]처럼 form_id 로 열면 작성 모달이 입력 상태로 열린다 — 숫자 칸 하나를 채워 저장한다(저장 뒤 보기 상태)."""
    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/?form_id={form_id}', wait_until='networkidle')
    page.wait_for_selector('#work_order_number')
    page.fill('#work_order_number', tag)
    page.locator('#digFormTable .dig-form-num').first.fill('1')
    send_mes(page, lambda: (page.click('#btnSave'), confirm_ok(page)), 'action=save')


def search(page, state):
    rows = mes_get(page, f'{API}?action=result_search&form_type=OUTGOING&state={state}')
    return [r['work_order_number'] for r in rows]


def test_검사를_완료하면_작성_중_목록에서_검사결과로_옮겨_간다(page, base_url, outgoing_form):
    tag = f'E2E-DF-{int(time.time() * 1000)}'
    try:
        start_new(page, base_url, outgoing_form, tag)
        assert tag in search(page, 'working')
        send_mes(page, lambda: (page.click('#btnComplete'), confirm_ok(page)), 'action=complete')
        assert tag not in search(page, 'working')
        assert tag in search(page, 'done')
    finally:
        remove_results(tag)


def test_작성자는_작성_중인_검사를_지운다(page, base_url, outgoing_form):
    tag = f'E2E-DF-{int(time.time() * 1000)}'
    try:
        start_new(page, base_url, outgoing_form, tag)
        page.wait_for_selector('#btnDelete', state='visible')
        send_mes(page, lambda: (page.click('#btnDelete'), confirm_ok(page)), 'action=delete')
        assert tag not in search(page, 'working')
    finally:
        remove_results(tag)


def search_and_open(page, grid, label, tag):
    """조회 카드에 WO 를 넣어 [조회]하고 첫 행의 버튼으로 모달을 연다."""
    page.fill('#txtWorkOrder', tag)
    with page.expect_response(lambda r: 'action=result_search' in r.url):
        page.click('#btnSearch')
    page.locator(f'{grid} button', has_text=label).first.click()


def test_검사작성_목록의_열기는_보기로_열고_수정하면_저장이_생긴다(page, base_url, outgoing_form):
    tag = f'E2E-DF-{int(time.time() * 1000)}'
    try:
        start_new(page, base_url, outgoing_form, tag)
        page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/', wait_until='networkidle')
        search_and_open(page, '#workingGrid', '열기', tag)
        page.wait_for_selector('#btnEdit', state='visible')
        assert not page.locator('#btnSave').is_visible()
        assert page.locator('#digFormTable .dig-form-num').count() == 0     # 보기 상태는 입력칸이 없다
        page.click('#btnEdit')
        page.wait_for_selector('#btnSave', state='visible')
        assert page.locator('#digFormTable .dig-form-num').count() > 0
    finally:
        remove_results(tag)


def test_수정_취소는_저장하지_않고_보기_상태로_돌아간다(page, base_url, outgoing_form):
    tag = f'E2E-DF-{int(time.time() * 1000)}'
    saves = []
    try:
        start_new(page, base_url, outgoing_form, tag)     # 저장 뒤 보기 상태
        page.on('request', lambda r: saves.append(r.url) if 'action=save' in r.url else None)
        page.wait_for_selector('#btnEdit', state='visible')
        assert not page.locator('#btnCancelEdit').is_visible()
        page.click('#btnEdit')
        page.wait_for_selector('#btnCancelEdit', state='visible')
        page.locator('#digFormTable .dig-form-num').first.fill('7')
        page.click('#btnCancelEdit')
        confirm_ok(page)                                   # 바꾼 값이 있으면 묻는다
        page.wait_for_selector('#btnEdit', state='visible')
        assert page.locator('#digFormTable .dig-form-num').count() == 0
        assert not page.locator('#btnCancelEdit').is_visible()
        assert saves == []
    finally:
        remove_results(tag)


def test_수정_중_Esc_로_닫으면_저장하지_않은_내용을_묻는다(page, base_url, outgoing_form):
    tag = f'E2E-DF-{int(time.time() * 1000)}'
    saves = []
    try:
        start_new(page, base_url, outgoing_form, tag)
        page.on('request', lambda r: saves.append(r.url) if 'action=save' in r.url else None)
        page.wait_for_selector('#btnEdit', state='visible')
        page.click('#btnEdit')
        page.locator('#digFormTable .dig-form-num').first.fill('7')
        page.keyboard.press('Escape')
        page.wait_for_selector('#commonConfirmModal', state='visible')
        assert page.locator('#btnSave').is_visible()          # 묻는 동안 모달은 그대로다
        page.click('#commonConfirmModalCancel')
        page.wait_for_selector('#commonConfirmModal', state='hidden')
        assert page.locator('#btnSave').is_visible()          # 취소하면 계속 수정한다
        page.locator('#digFormTable .dig-form-num').first.focus()   # 확인창이 닫히면 포커스가 모달 밖이다 — 입력칸으로 돌아와 누른다
        page.keyboard.press('Escape')
        confirm_ok(page)
        page.wait_for_selector('#btnSave', state='detached')
        assert saves == []
    finally:
        remove_results(tag)


def test_양식_편집기를_Esc_로_닫아도_바뀐_내용을_묻고_바꾸지_않은_모달은_바로_닫힌다(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_form/', wait_until='networkidle')
    page.click('#btnNew')
    page.wait_for_selector('#title', state='visible')
    page.wait_for_timeout(300)                                # 기준값은 열린 뒤 다음 틱에 잡는다
    page.fill('#title', 'E2E-ESC')
    page.keyboard.press('Escape')
    page.wait_for_selector('#commonConfirmModal', state='visible')
    assert page.locator('#title').is_visible()
    confirm_ok(page)
    page.wait_for_selector('#title', state='detached')
    # 닫기를 덮어쓰지 않은 모달(양식 상세 조회)은 Esc 로 바로 닫힌다
    page.locator('#form-grid button', has_text='조회').first.click()
    page.wait_for_selector('#previewInfo', state='visible')
    page.keyboard.press('Escape')
    page.wait_for_selector('#previewInfo', state='detached')
    assert not page.locator('#commonConfirmModal').is_visible()


@pytest.fixture
def grid_form():
    """작성 결과 1건이 달린 `E2E-G` 품질 칸 단위(GRID) 양식 — 머리줄 1행 + 본문 1행(글자 칸, 빈 칸). 새 버전까지 같은 코드로 지운다."""
    tag = f'E2E-G{int(time.time())}'
    out = manage_shell(textwrap.dedent(f"""
        import json
        from domain.models.dig_form import DigForm, DigFormItem, DigFormResult, DigFormSection
        form = DigForm.objects.create(Code={tag!r}, Title={tag!r}, LayoutType='GRID', FormType='OUTGOING')
        section = DigFormSection.objects.create(DigForm=form, SectionType='INSPECTION', SortOrder=1, Width=12,
                                                ColumnCount=2, HeaderRowCount=1, WorkerColumnYN='N')
        DigFormItem.objects.create(DigFormSection=section, RowType='H', RowIndex=1, ColumnIndex=1, Content='항목', MinColumnWidth=100)
        DigFormItem.objects.create(DigFormSection=section, RowType='H', RowIndex=1, ColumnIndex=2, Content='값', MinColumnWidth=100)
        DigFormItem.objects.create(DigFormSection=section, RowType='H', RowIndex=2, ColumnIndex=1, Content='길이')
        cell = DigFormItem.objects.create(DigFormSection=section, RowType='H', RowIndex=2, ColumnIndex=2)
        DigFormResult.objects.create(DigForm=form, WriteDate='2026-10-19', WorkOrderNumber={tag!r})
        print(json.dumps({{'form_id': form.id, 'cell_id': cell.id}}))"""))
    created = json.loads(out.strip().splitlines()[-1])
    try:
        yield {'tag': tag, **created}
    finally:
        manage_shell(textwrap.dedent(f"""
            from domain.models.dig_form import DigForm, DigFormItem, DigFormResult, DigFormSection
            forms = DigForm.objects.filter(Code={tag!r})
            DigFormResult.objects.filter(DigForm__in=forms).delete()
            DigFormItem.objects.filter(DigFormSection__DigForm__in=forms).delete()
            DigFormSection.objects.filter(DigForm__in=forms).delete()
            forms.delete()"""))


def test_작성_결과가_있는_칸_단위_양식은_입력칸을_새_버전에서_바꾼다(page, base_url, admin_password, grid_form):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_form/', wait_until='networkidle')
    page.evaluate('(id) => page.preview(id)', grid_form['form_id'])
    page.wait_for_selector('#btnEdit', state='visible')
    page.click('#btnEdit')
    confirm_ok(page)                                       # 새 버전으로 저장된다고 묻는다
    page.click(f'#digFormTable [data-item-id="{grid_form["cell_id"]}"]')
    page.check('#set_input_yn')
    page.select_option('#set_result_type', 'T')
    body = send_mes(page, lambda: page.click('#btnSettingApply'), 'action=save_item')
    assert (body['revised'], body['version']) == (True, 2)
    page.wait_for_function("() => document.querySelector('#previewInfo').textContent.includes('Rev.2')")
    # 다음 칸은 결과가 없는 새 버전을 고친다
    page.uncheck('#set_input_yn')
    body = send_mes(page, lambda: page.click('#btnSettingApply'), 'action=save_item')
    assert (body['revised'], body['id']) == (False, page.evaluate('() => page.previewId'))


def test_검사결과_목록의_조회는_결과_모달로_연다(page, base_url, outgoing_form):
    tag = f'E2E-DF-{int(time.time() * 1000)}'
    try:
        start_new(page, base_url, outgoing_form, tag)
        send_mes(page, lambda: (page.click('#btnComplete'), confirm_ok(page)), 'action=complete')
        page.goto(f'{base_url}/gui/wm_dig_form_outgoing_result/', wait_until='networkidle')
        search_and_open(page, '#resultGrid', '조회', tag)
        page.wait_for_selector('#digFormTable table')
        assert page.locator('#resultInfo').inner_text().startswith(tag)
    finally:
        remove_results(tag)


@pytest.fixture
def vision_form():
    """`E2E-V` 비전검사항목 하나 + 그 항목이 이미지 칸에 연결된 품질 양식(SECTION). 끝나면 작성건 → 양식 → 비전검사항목(이미지 포함) 순으로 지운다."""
    tag = f'E2E-V{int(time.time())}'     # 양식코드는 20자까지
    out = manage_shell(textwrap.dedent(f"""
        import json
        from app.views.system.form_edit import build_inspection
        from domain.models.data import InspectionItem
        from domain.models.dig_form import DigForm, DigFormItem, DigFormSection
        from domain.tenancy import tenant_atomic
        with tenant_atomic() as tenant:
            item = InspectionItem.objects.create(tenant=tenant, code={tag!r}, name={tag!r}, task_type='OBJECT_DETECTION', status='ACTIVE')
        top = [{{'row': 1, 'col': 1, 'content': 'WO'}}, {{'row': 1, 'col': 2, 'bind': 'result.WorkOrderNumber', 'input': True}},
               {{'row': 1, 'col': 3, 'content': '작성일'}}, {{'row': 1, 'col': 4, 'bind': 'result.WriteDate', 'input': True}}]
        form = DigForm.objects.create(Code={tag!r}, Title={tag!r}, LayoutType='SECTION', FormType='OUTGOING', FixedTopContent=json.dumps(top))
        section = DigFormSection.objects.create(DigForm=form, SectionType='INSPECTION', Title='점검', WorkerColumnYN='N')
        columns = [{{'title': '항목', 'kind': 'TEXT', 'width': 200}}, {{'title': '사진', 'kind': 'IMAGE', 'width': 100}}]
        items, header_rows = build_inspection(section, columns, [['외관', {{'vision_item': item.id}}]])
        DigFormItem.objects.bulk_create(items)
        section.HeaderRowCount, section.ColumnCount = header_rows, 2
        section.save()
        print(json.dumps({{'item_id': item.id, 'form_id': form.id}}))"""))
    created = json.loads(out.strip().splitlines()[-1])
    try:
        yield {'tag': tag, **created}
    finally:
        manage_shell(textwrap.dedent(f"""
            from domain.models.dig_form import DigForm, DigFormItem, DigFormItemResult, DigFormResult, DigFormSection
            from domain.services.data.item_platform import ItemPlatformService
            forms = DigForm.objects.filter(Code={tag!r})
            DigFormItemResult.objects.filter(DigFormResult__DigForm__in=forms).delete()
            DigFormResult.objects.filter(DigForm__in=forms).delete()
            DigFormItem.objects.filter(DigFormSection__DigForm__in=forms).delete()
            DigFormSection.objects.filter(DigForm__in=forms).delete()
            forms.delete()
            ItemPlatformService.delete_item({created['item_id']})"""))


def vision_state(vision_form):
    """(비전검사항목 이미지 id 목록, 그 양식 작성건의 칸 값 목록)"""
    out = manage_shell(textwrap.dedent(f"""
        import json
        from domain.models.data import ImageAsset
        from domain.models.dig_form import DigFormItemResult
        from domain.tenancy import tenant_atomic
        with tenant_atomic():
            ids = list(ImageAsset.objects.filter(dataset__item_id={vision_form['item_id']}).values_list('id', flat=True))
        values = list(DigFormItemResult.objects.filter(DigFormResult__DigForm_id={vision_form['form_id']}).values_list('TextResult', flat=True))
        print(json.dumps([ids, values]))"""))
    return json.loads(out.strip().splitlines()[-1])


def test_양식_편집기는_이미지_칸의_비전_연결을_보이고_바꾸면_새_버전이다(page, base_url, admin_password, vision_form):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_form/', wait_until='networkidle')
    page.evaluate('(id) => page.openEdit({ id: id, layout_type: "SECTION" })', vision_form['form_id'])
    select = page.locator('.it-vision').first
    select.wait_for()
    assert select.input_value() == str(vision_form['item_id'])
    select.select_option('')
    body = send_mes(page, lambda: (page.click('#btnSave'), confirm_ok(page)), 'action=save')
    assert body['revised'] is True


@pytest.fixture
def categorized_form(vision_form):
    """vision_form 의 양식을 E2E 중분류에 매핑하고 그 비전검사항목을 그 중분류에 넣는다. 끝나면 소속을 풀고 분류를 지운다."""
    tag = vision_form['tag']
    manage_shell(textwrap.dedent(f"""
        from domain.models.data import InspectionCategory, InspectionItem
        from domain.tenancy import tenant_atomic
        with tenant_atomic() as tenant:
            major = InspectionCategory.objects.create(tenant=tenant, name='E2E-출하-{tag}', form_type='OUTGOING')
            minor = InspectionCategory.objects.create(tenant=tenant, parent=major, name='E2E-시트-{tag}', form_code={tag!r})
            InspectionItem.objects.filter(pk={vision_form['item_id']}).update(category=minor)"""))
    try:
        yield {**vision_form, 'label': f'E2E-출하-{tag} › E2E-시트-{tag}'}
    finally:
        manage_shell(textwrap.dedent(f"""
            from domain.models.data import InspectionCategory, InspectionItem
            from domain.tenancy import tenant_atomic
            with tenant_atomic():
                InspectionItem.objects.filter(pk={vision_form['item_id']}).update(category=None)
                InspectionCategory.objects.filter(name__endswith='-{tag}', parent__isnull=False).delete()
                InspectionCategory.objects.filter(name__endswith='-{tag}').delete()"""))


def open_editor(page, base_url, admin_password, form_id):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_form/', wait_until='networkidle')
    page.evaluate('(id) => page.openEdit({ id: id, layout_type: "SECTION" })', form_id)
    page.locator('.it-vision').first.wait_for()


def test_매핑한_양식_편집기는_그_중분류_항목을_맨_위에_보인다(page, base_url, admin_password, categorized_form):
    open_editor(page, base_url, admin_password, categorized_form['form_id'])
    assert page.locator('.form-edit-vision-category').inner_text() == '검사 분류: ' + categorized_form['label']
    first_group = page.locator('.it-vision').first.locator('optgroup').first
    assert first_group.get_attribute('label') == '이 양식 분류 — ' + categorized_form['label']
    assert first_group.locator('option').first.get_attribute('value') == str(categorized_form['item_id'])


def test_이미지_칸_모두_연결과_미연결_경고(page, base_url, admin_password, vision_form):
    open_editor(page, base_url, admin_password, vision_form['form_id'])
    cell = page.locator('.item-table .it-vision').first
    cell.select_option('')
    page.locator('.vision-all').first.select_option(str(vision_form['item_id']))
    page.locator('.btn-vision-all').first.click()
    assert cell.input_value() == str(vision_form['item_id'])
    # 연결이 빠진 칸이 있으면 저장 확인창이 알린다 — 취소하면 보내지 않는다
    cell.select_option('')
    page.click('#btnSave')
    page.wait_for_selector('#commonConfirmModal', state='visible')
    assert '비전검사항목이 연결되지 않은 이미지 칸이 1개 있습니다.' in page.locator('#commonConfirmModal').inner_text()
    page.click('#commonConfirmModalCancel')


def test_연결된_칸에_파일을_고르면_비전_데이터에_들어가고_저장하면_칸에_남는다(page, base_url, admin_password, vision_form):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/?form_id={vision_form["form_id"]}', wait_until='networkidle')
    page.wait_for_selector('#work_order_number')
    assert page.locator('#digFormTable', has_text='비전: ' + vision_form['tag']).count() == 1
    page.fill('#work_order_number', vision_form['tag'])
    page.locator('#digFormTable .dig-form-image-upload').first.click()
    with page.expect_response(lambda r: 'action=capture' in r.url) as response:
        page.locator('.capture-file').set_input_files(
            {'name': 'e2e.jpg', 'mimeType': 'image/jpeg', 'buffer': defect_jpeg('scratch', seed=vision_form['tag'])})
    asset_id = response.value.json()['asset_id']
    send_mes(page, lambda: (page.click('#btnSave'), confirm_ok(page)), 'action=save')
    assert vision_state(vision_form) == [[asset_id], [str(asset_id)]]


def test_결과_모달의_PDF_저장은_모달_내용만_사진과_함께_인쇄_문서로_옮긴다(page, base_url, admin_password, vision_form):
    # 인쇄창은 띄우지 않는다 — printFrame 을 바꿔 인쇄할 문서만 받아 본다
    tag = vision_form['tag']
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/?form_id={vision_form["form_id"]}', wait_until='networkidle')
    page.wait_for_selector('#work_order_number')
    page.fill('#work_order_number', tag)
    page.locator('#digFormTable .dig-form-image-upload').first.click()
    with page.expect_response(lambda r: 'action=capture' in r.url):
        page.locator('.capture-file').set_input_files(
            {'name': 'e2e.jpg', 'mimeType': 'image/jpeg', 'buffer': defect_jpeg('scratch', seed=tag)})
    send_mes(page, lambda: (page.click('#btnSave'), confirm_ok(page)), 'action=save')
    send_mes(page, lambda: (page.click('#btnComplete'), confirm_ok(page)), 'action=complete')

    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_result/', wait_until='networkidle')
    search_and_open(page, '#resultGrid', '조회', tag)
    page.wait_for_selector('#digFormTable table')
    page.evaluate('() => { page.printFrame = function (frame) { window.e2ePrinted = frame.contentDocument; }; }')
    page.click('#btnPdf')
    page.wait_for_function('() => !!window.e2ePrinted')
    printed = page.evaluate('''() => {
        let d = window.e2ePrinted;
        return {
            title: d.title,
            info: d.querySelector('#resultInfo').textContent,
            others: d.querySelectorAll('#resultGrid, #searchForm, .modal-header').length,
            buttons: d.querySelectorAll('button').length,
            photos: Array.from(d.querySelectorAll('.dig-form-print-landscape img.dig-form-print-photo')).map(function (img) { return img.naturalWidth > 0; }),
            lines: ['landscape', 'portrait'].map(function (o) { return d.querySelectorAll('.dig-form-print-' + o + ' > .dig-form-print-line').length; }),
            compat: d.compatMode,
        };
    }''')
    assert printed['info'].startswith(tag)
    assert printed['others'] == 0 and printed['buttons'] == 0
    assert printed['photos'] == [True]
    # 섹션 배치는 가로용·세로용 두 벌이고 둘 다 줄 단위로 묶인다
    assert all(printed['lines'])
    assert printed['compat'] == 'CSS1Compat'
    assert printed['title'].startswith(tag + '_Rev') and printed['title'].endswith('_1차')


def test_셸_탭에서_가짜_카메라로_찍어_사용하면_칸에_사진이_들어간다(browser, base_url, admin_password, vision_form):
    # 셸 iframe 안에서 카메라가 열리는지까지 본다. 가짜 카메라·권한 자동 허용 플래그로 브라우저를 따로 띄운다(같은 Playwright)
    camera_browser = browser.browser_type.launch(args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'])
    try:
        page = camera_browser.new_page(viewport={'width': 1024, 'height': 768}, locale='ko-KR')
        login(page, base_url, 'admin', admin_password)
        url = f'/gui/wm_dig_form_outgoing_write/?form_id={vision_form["form_id"]}'
        with page.expect_event('framenavigated', predicate=lambda f: 'wm_dig_form_outgoing_write' in f.url):
            page.evaluate('(url) => window.myMenu.openMenu("wm_dig_form_outgoing_write", "품질검사 작성", url, { navigateExisting: true })', url)
        frame = next(f for f in page.frames if 'wm_dig_form_outgoing_write' in f.url)
        frame.locator('#digFormTable .dig-form-image-upload').first.click()
        frame.wait_for_function('() => { const v = document.querySelector(".capture-video"); return v && v.videoWidth > 0; }')
        frame.click('.capture-shoot')
        frame.wait_for_selector('.capture-use:not(.d-none)')
        with page.expect_response(lambda r: 'action=capture' in r.url) as response:
            frame.click('.capture-use')
        body = response.value.json()
        assert body['success'], body
        assert frame.locator('#digFormTable .dig-form-image-value').first.input_value() == str(body['asset_id'])
    finally:
        camera_browser.close()


def test_HTTP_접속이면_촬영이_기기_카메라를_열고_찍은_사진이_칸에_들어간다(page, base_url, admin_password, vision_form):
    # 127.0.0.1 은 보안 컨텍스트라 HTTP 사내 주소(10.x)와 같게 만들려고 isSecureContext 를 false 로 바꾼다
    page.add_init_script("Object.defineProperty(window, 'isSecureContext', { get: () => false })")
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/?form_id={vision_form["form_id"]}', wait_until='networkidle')
    page.locator('#digFormTable .dig-form-image-upload').first.click()
    page.wait_for_selector('.capture-message:has-text("기기 카메라")')
    assert page.is_enabled('.capture-shoot') and page.locator('.capture-video.d-none').count() == 1
    assert page.get_attribute('.capture-device', 'capture') == 'environment'
    with page.expect_file_chooser() as chooser:
        page.click('.capture-shoot')
    with page.expect_response(lambda r: 'action=capture' in r.url) as response:
        chooser.value.set_files({'name': 'camera.jpg', 'mimeType': 'image/jpeg',
                                 'buffer': defect_jpeg('scratch', seed=vision_form['tag'] + 'cam')})
    body = response.value.json()
    assert body['success'], body
    assert page.locator('#digFormTable .dig-form-image-value').first.input_value() == str(body['asset_id'])


@pytest.fixture
def header_form():
    """`E2E-H` 품질 섹션 양식 — 맨 위 머리글(WO 입력·작성일 표시)과 머리글 섹션(라벨 연결 입력 항목 하나)·숫자 입력칸 하나."""
    tag = f'E2E-H{int(time.time())}'
    out = manage_shell(textwrap.dedent(f"""
        import json
        from app.views.system.form_edit import build_inspection
        from domain.models.dig_form import DigForm, DigFormItem, DigFormSection
        top = [{{'row': 1, 'col': 1, 'content': 'WO'}}, {{'row': 1, 'col': 2, 'bind': 'result.WorkOrderNumber', 'input': True}},
               {{'row': 1, 'col': 3, 'content': '작성일'}}, {{'row': 1, 'col': 4, 'bind': 'result.WriteDate'}}]
        form = DigForm.objects.create(Code={tag!r}, Title={tag!r}, LayoutType='SECTION', FormType='OUTGOING', FixedTopContent=json.dumps(top))
        cells = [{{'row': 1, 'col': 1, 'content': '확인자', 'input_key': 'e2eh'}},
                 {{'row': 1, 'col': 2, 'bind': 'result.extra.e2eh', 'input': True, 'name': '확인자'}}]
        section = DigFormSection.objects.create(DigForm=form, SectionType='INSPECTION', Title='점검', SortOrder=1, WorkerColumnYN='N')
        DigFormSection.objects.create(DigForm=form, SectionType='HEADER', Title='확인', SortOrder=2, Width=12,
                                      Content=json.dumps(cells, ensure_ascii=False))
        columns = [{{'title': '항목', 'kind': 'TEXT', 'width': 200}}, {{'title': '값', 'kind': 'INPUT', 'width': 100}}]
        items, header_rows = build_inspection(section, columns, [['길이', {{'type': 'N', 'lower_limit': '', 'upper_limit': ''}}]])
        DigFormItem.objects.bulk_create(items)
        section.HeaderRowCount, section.ColumnCount = header_rows, 2
        section.save()
        print(json.dumps({{'form_id': form.id}}))"""))
    created = json.loads(out.strip().splitlines()[-1])
    try:
        yield {'tag': tag, **created}
    finally:
        manage_shell(textwrap.dedent(f"""
            from domain.models.dig_form import DigForm, DigFormItem, DigFormItemResult, DigFormResult, DigFormSection
            forms = DigForm.objects.filter(Code={tag!r})
            DigFormItemResult.objects.filter(DigFormResult__DigForm__in=forms).delete()
            DigFormResult.objects.filter(DigForm__in=forms).delete()
            DigFormItem.objects.filter(DigFormSection__DigForm__in=forms).delete()
            DigFormSection.objects.filter(DigForm__in=forms).delete()
            forms.delete()"""))


def test_머리글_섹션은_작성_모달에_표로_보이고_입력값을_저장하며_작성일은_입력받지_않는다(page, base_url, admin_password, header_form):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/?form_id={header_form["form_id"]}', wait_until='networkidle')
    page.wait_for_selector('#work_order_number')
    assert page.locator('#write_date').count() == 0                     # 작성일 입력칸이 없다(머리글·위쪽 입력줄 모두)
    today = page.evaluate('() => new Date().toLocaleDateString("sv-SE")')
    assert page.locator('#digFormTopTable td[data-col="4"]').inner_text() == today
    extra = page.locator('#digFormTable [data-section] .dig-form-extra[data-extra-key="e2eh"]')
    assert extra.count() == 1
    page.fill('#work_order_number', header_form['tag'])
    extra.fill('확인 E2E')
    page.locator('#digFormTable .dig-form-num').first.fill('3')
    body = send_mes(page, lambda: (page.click('#btnSave'), confirm_ok(page)), 'action=save')
    assert (body['success'], body['header_values'], body['write_date']) == (True, {'e2eh': '확인 E2E'}, today)
    # 보기 상태로 다시 그리면 머리글 섹션에 저장한 값이 글자로 보인다
    page.wait_for_selector('#btnEdit', state='visible')
    assert '확인 E2E' in page.locator('#digFormTable').inner_text()


def test_양식_편집기는_머리글_섹션을_타일로_불러오고_그대로_저장하면_새_버전이_아니다(page, base_url, admin_password, header_form):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_form/', wait_until='networkidle')
    page.evaluate('(id) => page.openEdit({ id: id, layout_type: "SECTION" })', header_form['form_id'])
    tile = page.locator('.form-edit-tile[data-type="HEADER"]')
    tile.wait_for()
    assert '확인자' in tile.locator('.header-preview').inner_text()
    assert page.locator('.header-warning:not(.d-none)').count() == 0
    body = send_mes(page, lambda: (page.click('#btnSave'), confirm_ok(page)), 'action=save')
    assert (body['success'], body['revised']) == (True, False)
    out = manage_shell(textwrap.dedent(f"""
        import json
        from domain.models.dig_form import DigFormSection
        s = DigFormSection.objects.get(DigForm_id={header_form['form_id']}, SectionType='HEADER')
        print(json.dumps(json.loads(s.Content)))"""))
    cells = json.loads(out.strip().splitlines()[-1])
    assert [c.get('bind') for c in cells] == [None, 'result.extra.e2eh']


def test_양식_편집기_글자_칸은_여러_줄로_쓰고_작성_화면에_들여쓰기까지_보인다(page, base_url, admin_password, header_form):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_form/', wait_until='networkidle')
    page.evaluate('(id) => page.openEdit({ id: id, layout_type: "SECTION" })', header_form['form_id'])
    cell = page.locator('.form-edit-tile[data-type="INSPECTION"] textarea.it-text').first
    cell.wait_for()
    height = cell.evaluate('el => el.offsetHeight')
    cell.fill('')
    cell.type('1) 동심도')
    cell.press('Enter')
    cell.type('  > 샤프트 중심선')
    assert cell.evaluate('el => el.offsetHeight') > height            # 줄이 늘면 칸도 늘어난다
    body = send_mes(page, lambda: (page.click('#btnSave'), confirm_ok(page)), 'action=save')
    assert (body['success'], body['revised']) == (True, True)        # 글자를 바꾸면 새 버전
    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/?form_id={body["id"]}', wait_until='networkidle')
    text = page.locator('#digFormTable td.dig-form-text').first
    text.wait_for()
    assert text.evaluate('el => el.textContent') == '1) 동심도\n  > 샤프트 중심선'
    assert text.evaluate('el => getComputedStyle(el).whiteSpace') == 'pre-wrap'


def test_행마다_지정_열은_칸마다_종류와_앞뒤_글자를_정하고_작성_화면에_한_줄로_보인다(page, base_url, admin_password, header_form):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_form/', wait_until='networkidle')
    page.evaluate('(id) => page.openEdit({ id: id, layout_type: "SECTION" })', header_form['form_id'])
    tile = page.locator('.form-edit-tile[data-type="INSPECTION"]')
    tile.locator('.btn-col-toggle').click()
    panel = page.locator('.form-edit-popup .col-table')
    panel.wait_for()
    panel.locator('tbody tr').nth(1).locator('.col-kind').select_option('MIXED')
    page.locator('.form-edit-popup button', has_text='적용').click()
    # 숫자 입력이던 값은 입력 칸으로 옮겨진다
    first = tile.locator('.item-table tbody tr').nth(0).locator('td[data-col]').nth(1)
    assert first.locator('.it-mkind').input_value() == 'INPUT'
    assert first.locator('.it-type').input_value() == 'N'
    first.locator('.it-label').fill('부적합 건수 : {} EA')
    # 새 행은 마지막 행의 종류·앞뒤 글자를 이어받고, 그 칸만 판정으로 바꾼다
    tile.locator('.btn-item-add').click()
    second = tile.locator('.item-table tbody tr').nth(1).locator('td[data-col]')
    second.nth(0).locator('textarea.it-text').fill('외관')
    assert second.nth(1).locator('.it-label').input_value() == '부적합 건수 : {} EA'
    second.nth(1).locator('.it-mkind').select_option('JUDGE')
    second.nth(1).locator('.it-label').fill('')
    body = send_mes(page, lambda: (page.click('#btnSave'), confirm_ok(page)), 'action=save')
    assert (body['success'], body['revised']) == (True, True)        # 칸 종류가 바뀌면 새 버전

    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/?form_id={body["id"]}', wait_until='networkidle')
    line = page.locator('#digFormTable .dig-form-inline').first
    line.wait_for()
    assert line.inner_text().replace('\n', ' ').split() == ['부적합', '건수', ':', 'EA']
    assert line.locator('.dig-form-slot input.dig-form-num').count() == 1
    assert page.locator('#digFormTable .dig-form-radio').count() == 1


def test_머리글_행_열_추가는_선택한_칸_아래_오른쪽에_넣고_선택이_없으면_끝에_붙인다(page, base_url, admin_password):
    """저장하지 않는다 — 새 양식 팝업의 기본 머리글(4행 6열)로 본다."""
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_incoming_form/', wait_until='networkidle')
    page.click('#btnNew')
    editor = page.locator('.header-editor')
    preview = editor.locator('.header-preview table')
    preview.wait_for()
    cell = lambda r, c: preview.locator(f'[data-row="{r}"][data-col="{c}"]')
    assert cell(3, 1).inner_text() == 'WO'
    cell(3, 1).click()                                        # WO 라벨
    editor.locator('.btn-header-add-col').click()
    assert cell(3, 2).inner_text() == ''                      # 라벨 오른쪽에 빈 칸
    assert 'WO' in cell(3, 3).inner_text()                    # 입력칸은 한 칸 밀린다
    assert cell(1, 1).get_attribute('colspan') == '4'         # 넣은 자리를 지나는 제목 병합은 늘어난다
    editor.locator('.btn-header-add-row').click()             # 같은 칸이 선택된 채 아래에 행
    assert cell(4, 1).inner_text() == '' and cell(5, 1).inner_text() == '제정일'
    page.keyboard.press('Escape')
    confirm_ok(page)                                          # 저장하지 않고 닫는다
    page.wait_for_selector('.header-editor', state='detached')


@pytest.fixture
def rig_form():
    """`E2E-R` 거치대 항목(이상 탐지)·치수 측정 항목·태블릿 항목과 각 항목의 검사 결과(이미지 포함), 세 항목을 이미지 칸에 연결한 품질 양식.

    끝나면 작성건 → 양식 → 검사 결과 → 비전검사항목(이미지 포함) → 클라이언트 순으로 지운다.
    """
    tag = f'E2E-R{int(time.time())}'
    out = manage_shell(textwrap.dedent(f"""
        import io, json, uuid
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from app.views.system.form_edit import build_inspection
        from domain.models.data import InspectionItem
        from domain.models.dig_form import DigForm, DigFormItem, DigFormSection
        from domain.models.vision import VisionClient, VisionInspection
        from domain.services.data.image import ImageService
        from domain.tenancy import tenant_atomic
        def png(name):
            buf = io.BytesIO(); Image.new('RGB', (64, 48), (120, 120, 120)).save(buf, format='PNG')
            return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')
        client = VisionClient.objects.create(client_id={tag!r}, name='E2E 거치대', api_key_hash='x' * 64)
        ids = {{}}
        with tenant_atomic() as tenant:
            rig = InspectionItem.objects.create(tenant=tenant, code={tag + '-A'!r}, name='E2E 거치대 표면', task_type='ANOMALY_DETECTION')
            dim = InspectionItem.objects.create(tenant=tenant, code={tag + '-D'!r}, name='E2E 거치대 치수', task_type='MEASUREMENT')
            tab = InspectionItem.objects.create(tenant=tenant, code={tag + '-T'!r}, name='E2E 태블릿', capture_method='TABLET')
            for item, extra in ((rig, {{'abnormal': True}}), (dim, {{'abnormal': False, 'measurements': [
                    {{'code': 'A', 'name': '치수 A', 'value': 540.32, 'lower': 539.0, 'upper': 541.0, 'unit': 'mm', 'ok': True}}]}})):
                asset = ImageService.upload_images(item, [png(item.code + '.png')], allow_duplicate=True)['uploaded'][0]['id']
                key = str(uuid.uuid4())
                VisionInspection.objects.create(id=key, request_id=key, client=client, item=item, status='SUCCESS', image_asset_id=asset, **extra)
            ids = {{'rig': rig.id, 'dim': dim.id, 'tab': tab.id}}
        form = DigForm.objects.create(Code={tag!r}, Title={tag!r}, LayoutType='SECTION', FormType='OUTGOING')
        section = DigFormSection.objects.create(DigForm=form, SectionType='INSPECTION', Title='점검', WorkerColumnYN='N')
        columns = [{{'title': '항목', 'kind': 'TEXT', 'width': 200}}, {{'title': '사진', 'kind': 'IMAGE', 'width': 160}}]
        rows = [['표면', {{'vision_item': ids['rig']}}], ['치수', {{'vision_item': ids['dim']}}], ['라벨', {{'vision_item': ids['tab']}}]]
        items, header_rows = build_inspection(section, columns, rows)
        DigFormItem.objects.bulk_create(items)
        section.HeaderRowCount, section.ColumnCount = header_rows, 2
        section.save()
        print(json.dumps(dict(ids, form_id=form.id)))"""))
    created = json.loads(out.strip().splitlines()[-1])
    try:
        yield {'tag': tag, **created}
    finally:
        manage_shell(textwrap.dedent(f"""
            from domain.models.dig_form import DigForm, DigFormItem, DigFormItemResult, DigFormResult, DigFormSection
            from domain.models.vision import VisionClient, VisionInspection
            from domain.services.data.item_platform import ItemPlatformService
            forms = DigForm.objects.filter(Code={tag!r})
            DigFormItemResult.objects.filter(DigFormResult__DigForm__in=forms).delete()
            DigFormResult.objects.filter(DigForm__in=forms).delete()
            DigFormItem.objects.filter(DigFormSection__DigForm__in=forms).delete()
            DigFormSection.objects.filter(DigForm__in=forms).delete()
            forms.delete()
            VisionInspection.objects.filter(client__client_id={tag!r}).delete()
            for item_id in ({created['rig']}, {created['dim']}, {created['tab']}):
                ItemPlatformService.delete_item(item_id)
            VisionClient.objects.filter(client_id={tag!r}).delete()"""))


def test_거치대_칸은_결과를_불러와_넣고_보기에서_판정을_보인다(page, base_url, admin_password, rig_form):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/?form_id={rig_form["form_id"]}', wait_until='networkidle')
    page.wait_for_selector('#work_order_number')
    page.fill('#work_order_number', rig_form['tag'])
    boxes = page.locator('#digFormTable .dig-form-image')
    rig_box, dim_box, tab_box = boxes.nth(0), boxes.nth(1), boxes.nth(2)
    assert rig_box.locator('.dig-form-rig-result').count() == 1 and rig_box.locator('.dig-form-image-upload').count() == 1
    assert dim_box.locator('.dig-form-rig-result').count() == 1 and dim_box.locator('.dig-form-image-upload').count() == 0
    assert tab_box.locator('.dig-form-rig-result').count() == 0

    for box in (rig_box, dim_box):
        box.locator('.dig-form-rig-result').click()
        page.wait_for_selector('.rig-use')
        with page.expect_response(lambda r: 'action=use_rig_result' in r.url):
            page.locator('.rig-use').first.click()
        page.wait_for_selector('.rig-use', state='detached')
        assert box.locator('.dig-form-image-value').input_value().isdigit()

    send_mes(page, lambda: (page.click('#btnSave'), confirm_ok(page)), 'action=save')
    page.wait_for_timeout(1500)                 # 저장하면 보기 상태로 다시 그린다
    results = page.locator('#digFormTable .dig-form-vision-result')
    assert results.count() == 2
    assert '거치대 판정: 이상' in results.nth(0).inner_text()
    assert '540.32 mm (539~541) 합격' in results.nth(1).inner_text()



def test_품질검사_작성은_작업지시를_합친_검사_작업_목록이다(page, base_url, admin_password):
    """작업지시 관리 화면을 지우고 품질검사 작성에 합쳤다(사용자 결정 2026-10-21). 대기(작업지시)는 데이터 출처가 없어
    비어 있고 [작업지시 등록]은 안내만 띄운다. 작성 중 행은 [열기]다. DB 에 쓰지 않는다."""
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/wm_dig_form_outgoing_write/', wait_until='networkidle')
    page.wait_for_timeout(500)
    assert '검사 작업 목록' in page.inner_text('.upper-wezongrid .sub-tit')
    assert page.locator('#waitingNotice').is_visible()
    rows = page.evaluate('() => page.grid.getData()')
    assert all(r['kind'] == 'WORKING' and r['action_label'] == '열기' for r in rows), rows

    page.select_option('#cboKind', 'WAITING')      # 대기는 서버에 묻지 않고 빈 목록이다
    page.wait_for_timeout(300)
    assert page.evaluate('() => page.grid.getData().length') == 0

    page.click('#btnNewWorkOrder')
    page.wait_for_selector('#commonAlertModal.show', timeout=5000)
    assert '준비 중입니다' in page.inner_text('#commonAlertModalBody')
    page.click('#commonAlertModalOk')
    assert not page.console_errors, page.console_errors
