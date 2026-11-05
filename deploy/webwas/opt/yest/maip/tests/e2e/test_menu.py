"""좌측 메뉴 구조 검증.

메뉴는 DB(`menu_item`) 와 동적 검사항목이 섞인 트리다. 서버 쪽 단위 테스트로는
"폴더가 하나만 열리는가", "하위 메뉴가 그 검사항목으로 열리는가" 를 확인할 수
없다. Bootstrap collapse 와 iframe 탭이 관여하기 때문이다.
"""
from tests.e2e.conftest import login

# 폴더 순서(업무 흐름 기준, 사용자 결정 2026-10-21·2026-10-22, seed_initial.MENU_TREE). 대시보드는 폴더 없는 1단계 링크다.
EXPECTED_FOLDERS = ['대시보드', '검사 작업', '검사 관리', '비전 데이터 관리', '기준정보', '시스템 관리']


# 더 이상 메뉴에 없어야 하는 것들. 남의 화면을 가리키던 중복과 MES 기준정보다.
REMOVED_MENUS = ['데이터 품질 점검', 'Export', '데이터 통계/활동이력', '검사 현황',
                 '코드정보', '단위정보', '업체정보',
                 'AI 모델', '작업 대기열', '다국어 설정', '프라퍼티마스터',
                 '양식 편집', '디지털 양식 조회',   # 2026-10-16 검사양식으로 합침
                 '비전검사항목 모델 매핑', 'AI 모델 매핑',   # 2026-10-21 비전검사항목 관리 상세로 합침
                 '작업지시 관리']   # 2026-10-21 품질검사 작성의 검사 작업 목록으로 합침

TREE_JS = """() => Array.from(
    document.querySelectorAll('#sideNavAll > .side-nav-item[level="0"]')).map(li => ({
        folder: li.querySelector(':scope > a > span').textContent.trim(),
        fid: (li.querySelector(':scope > .collapse') || {}).id || null,     // 1단계 링크(대시보드)는 펼침이 없다
        items: Array.from(li.querySelectorAll(':scope > .collapse > ul > li')).map(x => {
            let sub = x.querySelector(':scope > .collapse');
            let leaf = x.querySelector(':scope > a.menu-leaf-link');
            return {
                name: x.querySelector(':scope > a').textContent.trim(),
                url: leaf ? leaf.dataset.url : null,
                subId: sub ? sub.id : null,
                children: sub ? Array.from(sub.querySelectorAll('a.menu-leaf-link'))
                    .map(a => ({name: a.textContent.trim(), url: a.dataset.url})) : []
            };
        })
    }))"""


def tree(page):
    page.wait_for_selector('#sideNavAll .side-nav-item', timeout=15000)
    page.wait_for_timeout(1200)
    return page.evaluate(TREE_JS)


def folder(nodes, name):
    return next(f for f in nodes if f['folder'] == name)


def expand(page, collapse_id):
    """접혀 있을 때만 누른다.

    로그인 직후 활성 메뉴가 속한 폴더는 이미 펼쳐져 있다. 무조건 누르면 오히려
    접혀서 하위 링크를 누를 수 없다. 토글 앵커는 `data-bs-target` 으로 찾는다.
    """
    shown = ("() => { let d = document.querySelector('#%s');"
             " return !!d && d.classList.contains('show'); }" % collapse_id)
    if not page.evaluate(shown):
        page.click(f'#sideNavAll a[data-bs-target="#{collapse_id}"]')
    page.wait_for_selector('#%s.show' % collapse_id, timeout=8000)
    page.wait_for_timeout(500)


class TestFirstScreen:
    """로그인하면 메뉴 맨 위 대시보드가 닫을 수 없는 첫 탭으로 열린다(사용자 결정 2026-10-21, 지금은 데모).

    메뉴는 비동기로 그려진다. 첫 탭을 메뉴가 그려지기 전에 찾으면 아무 탭도 열리지 않는다.
    """

    def test_첫_화면은_맨_위_대시보드다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        page.wait_for_timeout(2500)
        frame = next((f for f in page.frames if '/gui/wm_dashboard' in f.url), None)
        assert frame is not None, [f.url for f in page.frames]
        assert frame.locator('#summaryCards .band-cell').count() >= 1
        top = page.locator('#sideNavAll > .side-nav-item[level="0"]').first
        assert top.locator(':scope > a.menu-leaf-link').get_attribute('data-mid') == 'wm_dashboard'
        assert top.locator(':scope > a i.uil-chart-line').count() == 1 and top.locator('.collapse').count() == 0
        assert 'active' in top.locator(':scope > a').get_attribute('class')
        assert page.locator('.mnb-list li a .mnb-tab-title').first.inner_text().strip() == '대시보드'


class TestFolders:
    def test_폴더가_지정한_순서로_나온다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        assert [f['folder'] for f in tree(page)] == EXPECTED_FOLDERS

    def test_폴더_DOM_id가_서로_다르다(self, page, base_url, admin_password):
        """같은 id 면 Bootstrap collapse 가 여러 폴더를 함께 토글한다.

        한글 폴더명을 `[^\\w-]`→`_` 치환해 쓰던 때 '데이터 관리'·'시스템 관리' 가
        모두 `fld_______` 가 되어 둘이 함께 열렸다.
        """
        login(page, base_url, 'admin', admin_password)
        fids = [f['fid'] for f in tree(page) if f['fid']]
        assert len(set(fids)) == len(fids), f'폴더 id 가 겹친다: {fids}'

    def test_폴더를_누르면_하나만_열린다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        tree(page)
        links = page.locator('#sideNavAll > .side-nav-item[level="0"] > a')
        for index in range(links.count()):
            links.nth(index).click()
            page.wait_for_timeout(700)
            shown = page.evaluate(
                """() => Array.from(document.querySelectorAll(
                    '#sideNavAll > .side-nav-item[level="0"] > .collapse'))
                    .filter(d => d.classList.contains('show')).map(d => d.id)""")
            assert len(shown) <= 1, f'폴더 {index} 클릭에 {shown} 가 함께 열렸다'

    def test_내린_메뉴가_보이지_않는다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        names = [it['name'] for f in tree(page) for it in f['items']]
        for gone in REMOVED_MENUS:
            assert gone not in names, f'내린 메뉴가 아직 있다: {gone}'


class TestItemSubtree:
    """비전 데이터 관리 > 대분류 › 중분류 › 비전검사항목(끝 메뉴 = 그 항목의 탭). 나머지 화면은 그 안의 내부 탭이다(사용자 결정 2026-10-21)."""

    def leaves(self, page):
        data = folder(tree(page), '비전 데이터 관리')
        leaves = [c for node in data['items'] for c in node['children']]
        assert leaves, '비전검사항목 끝 메뉴가 없다'
        return data, leaves

    def open_leaf(self, page, data, leaf):
        """끝 메뉴의 조상 펼침(대분류·중분류)을 바깥부터 차례로 열고 누른다."""
        expand(page, data['fid'])
        ids = page.evaluate("""url => { const ids = []; let el = document.querySelector(`#sideNavAll a.menu-leaf-link[data-url="${url}"]`);
            while (el && el.id !== 'sideNavAll') { if (el.classList && el.classList.contains('collapse') && el.id.startsWith('sub_')) ids.unshift(el.id);
                el = el.parentElement; } return ids; }""", leaf['url'])
        for collapse_id in ids:
            expand(page, collapse_id)
        page.click(f'#sideNavAll a.menu-leaf-link[data-url="{leaf["url"]}"]')
        page.wait_for_timeout(3000)

    def test_분류_아래_비전검사항목은_홈을_여는_끝_메뉴다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        data, leaves = self.leaves(page)
        assert data['items'][0]['name'] == '비전 데이터 등록' and data['items'][0]['url'], '첫 메뉴가 비전 데이터 등록이 아니다'
        assert all(not node['url'] for node in data['items'][1:]), '대분류 자리에 잎 메뉴가 있다'
        for leaf in leaves:
            assert leaf['url'].startswith('/gui/wm_data_item_detail/?inspection_item='), leaf
        ids = [leaf['url'].split('=')[1] for leaf in leaves]
        assert len(set(ids)) == len(ids), f'비전검사항목이 두 번 나온다: {ids}'

    def test_비전검사항목을_누르면_탭_하나가_열리고_내부_탭으로_라벨링을_연다(self, page, base_url, admin_password):
        """하위 화면은 셸 탭이 아니라 비전검사항목 탭 안의 내부 탭이다(사용자 결정 2026-10-21)."""
        login(page, base_url, 'admin', admin_password)
        data, leaves = self.leaves(page)
        leaf = leaves[0]
        item_id = leaf['url'].split('=')[1]
        self.open_leaf(page, data, leaf)
        home = next((f for f in page.frames if 'wm_data_item_detail' in f.url), None)
        assert home is not None and f'inspection_item={item_id}' in home.url
        home.wait_for_selector('#itemTabs [data-screen="wm_data_labeling"]', timeout=8000)
        assert home.eval_on_selector_all('#itemTabs .nav-link', 'els => els.map(e => e.textContent)') == [
            '홈', '데이터 목록', '라벨링 작업', '검수 작업', '스냅샷 관리']
        assert home.locator('#itemDescCollapse').evaluate('el => el.classList.contains("show")') is False   # 설명은 접혀 있다
        home.click('#itemTabs [data-screen="wm_data_labeling"]')
        page.wait_for_timeout(3000)
        frame = next((f for f in page.frames if 'wm_data_labeling' in f.url), None)
        assert frame is not None, '라벨링 화면이 열리지 않았다'
        assert frame.parent_frame == home, '라벨링이 비전검사항목 탭 안에 열려야 한다'
        assert frame.evaluate("() => document.querySelector('.labeling-layout').dataset.inspectionItemId") == item_id
        assert not frame.locator('.header-title').first.is_visible()            # 이름은 바깥 머리·탭이 보인다
        assert home.evaluate("() => { const w = document.querySelector('.ifram-wrapper'); return w.scrollHeight - w.clientHeight; }") <= 0
        titles = page.eval_on_selector_all('.mnb-list li a .mnb-tab-title', 'els => els.map(e => e.textContent.trim())')
        assert titles.count(leaf['name']) == 1 and not any('라벨링 작업' in t for t in titles), titles
        home.click('#itemTabs [data-screen="home"]')                            # 홈으로 돌아와도 라벨링은 그대로 남는다
        assert home.locator('#paneHome').is_visible() and frame.evaluate('() => !!document.querySelector(".labeling-layout")')

    def test_검사항목이_다르면_탭이_따로_열린다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        data, leaves = self.leaves(page)
        if len(leaves) < 2:
            import pytest
            pytest.skip('비전검사항목이 2개 미만이다')
        for leaf in leaves[:2]:
            self.open_leaf(page, data, leaf)
        titles = page.eval_on_selector_all('.mnb-list li a .mnb-tab-title', 'els => els.map(e => e.textContent.trim())')
        assert len(set(titles)) == len(titles), f'탭 이름이 겹친다: {titles}'
        for leaf in leaves[:2]:
            assert leaf['name'] in titles, titles

    def test_접힌_사이드바에서도_분류를_펼쳐_연다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        data, leaves = self.leaves(page)
        page.evaluate("() => document.documentElement.setAttribute('data-sidenav-size', 'condensed')")
        page.wait_for_timeout(500)
        page.hover(f'#sideNavAll a[data-bs-target="#{data["fid"]}"]')    # 폴더 → 펼침 메뉴
        page.wait_for_timeout(600)
        leaf = leaves[0]
        ids = page.evaluate("""url => { const ids = []; let el = document.querySelector(`#sideNavAll a.menu-leaf-link[data-url="${url}"]`);
            while (el && el.id !== 'sideNavAll') { if (el.classList && el.classList.contains('collapse') && el.id.startsWith('sub_')) ids.unshift(el.id);
                el = el.parentElement; } return ids; }""", leaf['url'])
        page.hover(f'#sideNavAll a[data-bs-target="#{ids[0]}"]')       # 대분류 → 펼침 메뉴
        page.wait_for_timeout(600)
        for collapse_id in ids[1:]:                                     # 중분류는 펼침 메뉴 안에서 아래로
            page.click(f'#sideNavAll a[data-bs-target="#{collapse_id}"]')
            page.wait_for_timeout(600)
        page.click(f'#sideNavAll a.menu-leaf-link[data-url="{leaf["url"]}"]')
        page.wait_for_timeout(3000)
        assert any('wm_data_item_detail' in f.url and leaf['url'].split('=')[1] in f.url for f in page.frames)


class TestItemAdminMenu:
    def test_검사_관리는_검사_기준과_비전_검사_설정이다(self, page, base_url, admin_password):
        login(page, base_url, 'admin', admin_password)
        nodes = tree(page)
        assert [it['name'] for it in folder(nodes, '검사 관리')['items']] == [
            '검사양식 관리', '검사양식 코드 관리', '수입검사 품목 지정',
            '비전검사항목 관리', '비전검사 Overlay 관리', '비전검사 클라이언트 관리']
        assert [it['name'] for it in folder(nodes, '검사 작업')['items']][-1] == '비전 검사 이력'


class TestWorkerScope:
    def test_작업자는_권한_있는_메뉴만_본다(self, page, base_url, worker):
        login(page, base_url, worker['username'], worker['password'])
        nodes = tree(page)
        assert '시스템 관리' not in [f['folder'] for f in nodes], \
            '작업자에게 시스템 관리가 보인다'

        data = folder(nodes, '비전 데이터 관리')
        leaves = [c for it in data['items'] for c in it['children']]
        assert leaves, '비전검사항목이 보이지 않는다'
        assert all(c['url'].startswith('/gui/wm_data_item_detail/?inspection_item=') for c in leaves), leaves

    def test_작업자에게_비전검사항목_관리는_보이지_않는다(self, page, base_url, worker):
        """작업자 그룹에는 그 메뉴 권한이 없다(conftest WORKER_MENUS). 메뉴 권한이 있으면 분류는 보고 고치고,
        비전검사항목 등록·수정은 플랫폼 관리자만 한다(설계 2026-10-21 §3)."""
        login(page, base_url, worker['username'], worker['password'])
        names = [it['name'] for f in tree(page) for it in f['items']]
        assert '비전검사항목 관리' not in names, '작업자에게 메뉴 권한 없는 화면이 보인다'


class TestDataScreenShell:
    def test_셸_주석이_화면에_출력되지_않는다(self, page, base_url, admin_password):
        """Django 의 `{# #}` 는 한 줄 전용이다. 여러 줄로 쓰면 본문으로 나온다."""
        login(page, base_url, 'admin', admin_password)
        for gui_code in ['wm_data_item', 'wm_data_image', 'wm_data_snapshot']:
            page.goto(f'{base_url}/gui/{gui_code}/', wait_until='networkidle')
            page.wait_for_timeout(600)
            body = page.inner_text('body')
            assert 'layout_page' not in body, f'{gui_code} 에 셸 주석이 보인다'
            assert 'main.css' not in body, f'{gui_code} 에 셸 주석이 보인다'
