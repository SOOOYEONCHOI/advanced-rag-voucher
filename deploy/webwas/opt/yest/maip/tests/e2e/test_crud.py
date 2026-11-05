"""화면 CRUD 동작 검증.

동기 Ajax 를 콜백으로 바꾸면 "조회 → 그리드 표시 → 행 선택 → 상세 표시 →
저장 → 목록 갱신" 순서가 깨질 수 있다. 동기 호출은 순서를 코드가 보장했지만
콜백은 그렇지 않다. 화면을 실제로 조작해 확인한다.
"""
import time

from tests.e2e.conftest import login, manage_shell

# MES 공통 확인 모달(Alert.confirm)의 버튼. 저장·삭제가 이 모달을 거친다.
CONFIRM_OK = '#commonConfirmModalOk'


def open_screen(page, base_url, admin_password, gui_code):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/gui/{gui_code}/', wait_until='networkidle')
    page.wait_for_timeout(1200)


def confirm(page):
    """확인 모달의 '확인'을 누른다."""
    page.wait_for_selector(CONFIRM_OK, state='visible', timeout=8000)
    page.click(CONFIRM_OK)
    page.wait_for_timeout(1500)


class TestUnitCrud:
    """단위정보 — 가장 단순한 MES CRUD 화면."""

    def test_등록_조회_수정_삭제가_이어서_동작한다(self, page, base_url, admin_password):
        open_screen(page, base_url, admin_password, 'wm_unit')
        name = f'E2E-{int(time.time()) % 100000}'

        page.click('#btnNew')
        page.fill('#name', name)
        page.fill('#description', '동기 Ajax 전환 확인')
        page.click('#btnSave')
        confirm(page)

        # 저장 뒤 목록이 자동으로 다시 조회돼야 한다(콜백 순서 확인).
        assert name in page.content(), '저장한 단위가 목록에 없다'

        # 행을 눌러 상세가 채워지는지 — 상세 조회도 콜백이다.
        page.get_by_text(name, exact=True).first.click()
        page.wait_for_timeout(1200)
        assert page.input_value('#name') == name, '상세가 채워지지 않았다'

        page.fill('#description', '수정됨')
        page.click('#btnSave')
        confirm(page)

        page.get_by_text(name, exact=True).first.click()
        page.wait_for_timeout(1200)
        assert page.input_value('#description') == '수정됨', '수정이 반영되지 않았다'

        page.click('#btnDel')
        confirm(page)
        assert name not in page.content(), '삭제한 단위가 목록에 남아 있다'


class TestSearchFlow:
    """조회 조건 → 목록 갱신."""

    def test_사용자_화면_조회가_동작하고_콤보가_채워진다(self, page, base_url, admin_password):
        open_screen(page, base_url, admin_password, 'wm_user')

        # 콤보는 비동기로 채워진다. 옵션이 들어왔는지 본다.
        assert page.locator('#cboUserGroup option').count() >= 2, '사용자그룹 콤보가 비었다'
        # 상세 폼 콤보도 같은 응답으로 채운다(호출 1회 → 콤보 2개).
        assert page.locator('#UserGroup_id option').count() >= 1, '상세 콤보가 비었다'

        page.click('#btnSearch')
        page.wait_for_timeout(1500)
        assert 'admin' in page.content(), '사용자 목록이 조회되지 않았다'

    def test_로그_화면_조회가_동작한다(self, page, base_url, admin_password):
        open_screen(page, base_url, admin_password, 'wm_login_log')
        page.click('#btnSearch')
        page.wait_for_timeout(1500)
        assert 'admin' in page.content(), '로그인 로그가 조회되지 않았다'


class TestComboChain:
    """콤보 → 종속 콤보 → 목록으로 이어지는 비동기 연쇄."""

    def test_메뉴로그_화면의_콤보가_모두_채워진다(self, page, base_url, admin_password):
        open_screen(page, base_url, admin_password, 'wm_menu_log')
        page.wait_for_timeout(1500)
        assert page.locator('#cboMenu option').count() >= 2, '메뉴 콤보가 비었다'
        assert page.locator('#cboUser option').count() >= 2, '사용자 콤보가 비었다'

    def test_다국어_화면의_메뉴폴더_콤보가_채워진다(self, page, base_url, admin_password):
        open_screen(page, base_url, admin_password, 'wm_multi_language')
        page.wait_for_timeout(1500)
        assert page.locator('#cboMenuFolder option').count() >= 2, '메뉴폴더 콤보가 비었다'


class TestGridColumnSetting:
    """그리드 컬럼 설정 — loadColumnData 체인이 비동기로 바뀐 곳."""

    def test_컬럼_설정_팝업이_열린다(self, page, base_url, admin_password):
        open_screen(page, base_url, admin_password, 'wm_unit')
        page.click('#btnGridSetting')
        page.wait_for_timeout(1800)
        assert page.locator('#cboLangCode').count() > 0, '컬럼 설정 팝업이 열리지 않았다'
        assert not [e for e in page.console_errors if 'favicon' not in e], \
            f'컬럼 설정에서 JS 오류: {page.console_errors[:3]}'


class TestUserLifecycle:
    """사용자 화면에서 만든 사용자 — 조직(YEST) 소속과 삭제.

    단위 테스트(SQLite)에는 RLS 가 없어 여기서만 드러난다. 소속 행은 RLS 로 보호되는데
    사용자 삭제가 조직 컨텍스트 밖에서 돌면 Django 가 그 행을 보지 못해 함께 지우지
    못하고, 외래키에 걸려 "다른 곳에서 사용되고 있어 삭제할 수 없다"가 된다.
    """

    POST = """([url, data]) => new Promise((ok, fail) =>
        AjaxUtil.postAsyncData(url, data, ok, (xhr) => fail(xhr && xhr.responseText)))"""
    GET = """(url) => fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}})
        .then(r => r.json())"""

    def test_만든_사용자는_지울_수_있다(self, page, base_url, admin_password):
        open_screen(page, base_url, admin_password, 'wm_user')
        login_id = f'e2e-user-{int(time.time()) % 100000}'

        groups = page.evaluate(self.GET, '/api/system/usergroup?action=read')
        group_id = next(g['id'] for g in groups if g['code'] == 'user')
        saved = page.evaluate(self.POST, ['/api/system/user?action=save', {
            'login_id': login_id, 'Name': 'E2E 사용자', 'UserGroup_id': group_id,
            'is_active': 'Y'}])
        assert saved.get('success'), saved

        deleted = page.evaluate(self.POST, ['/api/system/user?action=delete',
                                            {'id': saved['id']}])
        assert deleted.get('success'), deleted


class TestDataConfirm:
    """데이터 화면의 확인 질문은 브라우저 기본 창이 아니라 제품 확인창으로 뜬다.

    `#confirmDialog` 가 어느 템플릿에도 없어 `DataUI.confirm` 이 `window.confirm`
    으로 떨어지고 있었다.
    """

    def test_스냅샷_등록_창은_Esc_로_닫히고_배경_클릭으로는_닫히지_않는다(self, page, base_url, admin_password, demo):
        native = []
        page.on('dialog', lambda d: (native.append(d.message), d.dismiss()))
        open_screen(page, base_url, admin_password, 'wm_data_snapshot')
        page.goto(f'{base_url}/gui/wm_data_snapshot/?inspection_item={demo["det"]}', wait_until='networkidle')
        page.wait_for_timeout(800)

        page.click('#btnNew')
        page.wait_for_selector('#snapshotCreateModal.show', timeout=5000)
        order = page.eval_on_selector_all('#snapshotCreateModal .modal-footer button',
                                          'bs => bs.map(b => b.id)')
        assert order == ['btnCancelSnapshot', 'btnCreateSnapshot']
        page.mouse.click(5, 5)                    # 배경
        page.wait_for_timeout(500)
        assert page.locator('#snapshotCreateModal.show').count() == 1
        page.keyboard.press('Escape')
        page.wait_for_selector('#snapshotCreateModal', state='hidden', timeout=3000)
        assert native == []

    def test_편집_창_안의_확인창은_그_위에_뜬다(self, page, base_url, admin_password, demo):
        open_screen(page, base_url, admin_password, 'wm_data_item_detail')
        # 상세 화면은 검사항목을 지정해야 편집 버튼이 보인다(seed_demo 의 검사항목).
        page.goto(f'{base_url}/gui/wm_data_item_detail/?inspection_item={demo["det"]}', wait_until='networkidle')
        page.click('#btnEdit')
        page.wait_for_selector('#itemEditModal.show', timeout=5000)

        # 편집 창 안의 '삭제 요청' 이 이 확인창을 띄운다. 그 버튼은 활성 검사항목에서
        # 비활성이고 누르면 데이터가 바뀌므로, 버튼이 부르는 함수를 직접 부른다.
        page.evaluate("() => Alert.confirm('', '비전검사항목 삭제 요청을 플랫폼 관리자에게 전달하시겠습니까?', () => {})")
        page.wait_for_selector('#commonConfirmModalCancel', state='visible', timeout=5000)
        page.wait_for_timeout(400)

        # 편집 창 위에 있어야 누를 수 있다.
        on_top = page.evaluate("""() => {
            const b = document.getElementById('commonConfirmModalCancel').getBoundingClientRect();
            return document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2).id;
        }""")
        assert on_top == 'commonConfirmModalCancel'
        page.click('#commonConfirmModalCancel')
        page.wait_for_timeout(500)
        assert page.locator('#itemEditModal.show').count() == 1


class TestDataDeleteConfirm:
    """라벨 삭제는 확인을 거친다. 취소하면 아무것도 보내지 않는다."""

    def _writes(self, page):
        """쓰기 요청을 기록하고 **서버에 닿기 전에 끊는다.**

        확인을 건너뛰는 회귀가 생기면 이 테스트가 실제로 지우게 된다 — 실제 DB 다.
        처음 RED 를 확인할 때 seed 의 라벨 1개와 배정 2건이 그렇게 지워졌다.
        """
        sent = []

        def block(route):
            if route.request.method == 'GET':
                route.continue_()
                return
            sent.append(route.request.method + ' ' + route.request.url)
            route.abort()

        page.route('**/api/**', block)
        return sent

    def _cancel(self, page):
        page.wait_for_selector('#commonConfirmModalCancel', state='visible', timeout=5000)
        page.click('#commonConfirmModalCancel')
        page.wait_for_timeout(800)

    def _edit_tab(self, page, base_url, admin_password, demo, tab):
        open_screen(page, base_url, admin_password, 'wm_data_item_detail')
        page.goto(f'{base_url}/gui/wm_data_item_detail/?inspection_item={demo["det"]}', wait_until='networkidle')
        page.click('#btnEdit')
        page.click(f'#itemEditModal button[data-bs-target="#{tab}"]')
        page.wait_for_timeout(500)

    def test_라벨_삭제는_확인을_거친다(self, page, base_url, admin_password, demo):
        self._edit_tab(page, base_url, admin_password, demo, 'tabLabels')
        sent = self._writes(page)
        page.locator('#editLabels tr.label-row .btn-dell').first.click()
        self._cancel(page)
        assert sent == []

CSRF_JS = """(document.querySelector('[name=csrfmiddlewaretoken]') || {}).value
    || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1]"""


def mes(page, url, data=None):
    """화면 안에서 MES API(`/api/item/...`)를 부른다. data 가 있으면 폼 POST, 없으면 GET."""
    return page.evaluate("""([url, data]) => {
        const init = {headers: {'X-Requested-With': 'XMLHttpRequest'}};
        if (data) {
            init.method = 'POST';
            init.body = new URLSearchParams(Object.assign({csrfmiddlewaretoken: %s}, data));
        }
        return fetch(url, init).then(r => r.json());
    }""" % CSRF_JS, [url, data])


def select_item(page, name):
    """비전검사항목 관리 트리에서 비전검사항목 행을 이름으로 고른다. 트리가 길어 화면 밖 행은 글자로 못 누른다."""
    page.wait_for_function("() => typeof page !== 'undefined' && page.rows && page.rows.length > 0")   # let page — window 속성이 아니다
    found = page.evaluate("""name => {
        const row = page.rows.find(r => r.kind === 'item' && r.item_name === name);
        if (!row) return false;
        page.grid.setSelectionByRowId(row.id);
        page.show(row);
        return true;
    }""", name)
    assert found, name
    page.wait_for_timeout(1000)


class TestItemDeletionReview:
    """검사항목 관리자의 삭제 요청을 플랫폼 관리자가 목록 화면에서 승인·반려한다.

    승인·반려 API 는 있었지만 부르는 화면이 없어, 삭제를 요청한 검사항목은
    `DELETION_PENDING` 에 영구히 묶였다(상태 전환도 400).
    자기 검사항목을 만들고, 끝나면 지운다.
    """

    def _pending_item(self, page, name):
        item_id = mes(page, '/api/item/item_admin?action=create', {'name': name})['item_id']
        mes(page, '/api/item/item_admin?action=toggle_status', {'item_id': item_id})
        result = mes(page, '/api/item/item_home?action=request_delete', {'item_id': item_id})
        assert result.get('success'), result
        return item_id

    def _select(self, page, base_url, name):
        page.goto(f'{base_url}/gui/wm_data_item/', wait_until='networkidle')
        select_item(page, name)

    @staticmethod
    def detail(page, item_id):
        """검사항목 상세. 없으면(삭제됨) None."""
        body = mes(page, f'/api/item/item_admin?action=detail&item_id={item_id}')
        return body if 'id' in body else None

    def _cleanup(self, page, item_id):
        detail = self.detail(page, item_id)
        if not detail:
            return
        if detail['status'] != 'DELETION_PENDING':
            if detail['status'] == 'ACTIVE':
                mes(page, '/api/item/item_admin?action=toggle_status', {'item_id': item_id})
            mes(page, '/api/item/item_home?action=request_delete', {'item_id': item_id})
            detail = self.detail(page, item_id)
        mes(page, '/api/item/item_admin?action=approve_delete',
            {'deletion_id': detail['deletion_request']['id']})
        self.forget(detail['name'])

    @staticmethod
    def forget(name):
        """승인한 요청은 삭제 기록으로, 스냅샷 zip 을 만든 워커 작업은 작업 이력으로 남는다.
        테스트가 만든 기록(반려한 것 포함)은 지운다."""
        assert name.startswith('E2E-'), name
        manage_shell('from domain.models.data import BackgroundJob, ItemDeletionRequest\nfrom domain.tenancy import tenant_atomic\n'
                     'with tenant_atomic():\n'
                     f'    ItemDeletionRequest.objects.filter(item_name={name!r}).delete()\n'
                     f'    BackgroundJob.objects.filter(payload__item_name={name!r}).delete()')

    def test_반려하면_일시_중지로_돌아간다(self, page, base_url, admin_password):
        name = f'E2E-삭제반려-{int(time.time())}'
        open_screen(page, base_url, admin_password, 'wm_data_item')
        item_id = self._pending_item(page, name)
        try:
            self._select(page, base_url, name)
            page.get_by_role('button', name='삭제 요청 반려', exact=True).click()
            page.wait_for_timeout(1200)
            detail = self.detail(page, item_id)
            assert detail['status'] == 'PAUSED'
            assert detail['deletion_request'] is None
        finally:
            self._cleanup(page, item_id)

    def test_승인하면_확인을_거쳐_삭제된다(self, page, base_url, admin_password):
        name = f'E2E-삭제승인-{int(time.time())}'
        open_screen(page, base_url, admin_password, 'wm_data_item')
        item_id = self._pending_item(page, name)
        try:
            self._select(page, base_url, name)
            page.get_by_role('button', name='삭제 승인', exact=True).click()
            confirm(page)
            page.wait_for_timeout(800)
            assert page.evaluate('name => page.rows.some(r => r.item_name === name)', name) is False
            assert self.detail(page, item_id) is None
        finally:
            self._cleanup(page, item_id)
            self.forget(name)
