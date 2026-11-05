"""좌측 메뉴 트리의 폴더 정리와 비전 데이터 관리의 분류 트리.

메뉴 트리 SQL 은 PostgreSQL 전용이라 단위 테스트가 닿지 않는다(AGENTS [6]).
SQL 뒤의 폴더 정리와 비전검사항목 노드만 떼어 시험한다.
"""
import io

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from app.views.system.menus import _item_nodes, drop_empty_folders, top_level_leaves
from domain.gui import ITEM_CHILD_MENU_CODES
from domain.models.data import InspectionCategory, InspectionItem
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic


class DropEmptyFoldersTest(SimpleTestCase):
    def test_하위가_없는_폴더는_내보내지_않는다(self):
        tree = [{'objId': 'f1', 'nodes': []},
                {'objId': 'f2', 'nodes': [{'objId': 'wm_user', 'nodes': []}]}]
        self.assertEqual([f['objId'] for f in drop_empty_folders(tree)], ['f2'])


class TopLevelLeafTest(SimpleTestCase):
    def test_대시보드_폴더는_폴더_없이_1단계_링크로_보인다(self):
        dashboard = {'objId': 'wm_dashboard', 'objNm': '대시보드', 'objUrl': '/gui/wm_dashboard', 'nodes': []}
        tree = [{'objId': 'f9', 'objNm': '대시보드', 'menuIconCls': 'uil-chart-line', 'nodes': [dashboard]},
                {'objId': 'f2', 'nodes': [{'objId': 'wm_user', 'nodes': []}]}]
        folders = top_level_leaves(tree)
        self.assertEqual(folders[0]['leaf'], dashboard)
        self.assertNotIn('leaf', folders[1])


class SeedMenuTreeTest(TestCase):
    """좌측 메뉴 — 업무 흐름 기준으로 다시 묶고 이름·띄어쓰기를 맞췄다(사용자 결정 2026-10-21). 코드는 그대로다."""

    def test_폴더와_메뉴의_이름과_순서(self):
        from domain.models.system import MenuFolder, MenuItem
        call_command('seed_initial', stdout=io.StringIO())
        tree = [(f.FolderName, f.IconCSS, list(MenuItem.objects.filter(MenuFolder=f).order_by('_order')
                                              .values_list('MenuCode', 'MenuName')))
                for f in MenuFolder.objects.order_by('_order')]
        self.assertEqual(tree, [
            ('대시보드', 'uil-chart-line', [('wm_dashboard', '대시보드')]),
            ('검사 작업', 'uil-clipboard-alt', [
                ('wm_dig_form_incoming_write', '수입검사 작성'), ('wm_dig_form_incoming_result', '수입검사 결과'),
                ('wm_dig_form_outgoing_write', '품질검사 작성'), ('wm_dig_form_outgoing_result', '품질검사 결과'),
                ('wm_vis_inspection', '비전 검사 이력')]),
            ('검사 관리', 'uil-layer-group', [
                ('wm_dig_form_incoming_form', '검사양식 관리'), ('wm_dig_form_judge_code', '검사양식 코드 관리'),
                ('wm_product_form', '수입검사 품목 지정'), ('wm_data_item', '비전검사항목 관리'),
                ('wm_vis_overlay', '비전검사 Overlay 관리'), ('wm_vis_client', '비전검사 클라이언트 관리')]),
            ('비전 데이터 관리', 'uil-database', [
                ('wm_data_register', '비전 데이터 등록'), ('wm_data_item_detail', '비전검사항목 홈'), ('wm_data_image', '데이터 목록'), ('wm_data_labeling', '라벨링 작업'),
                ('wm_data_review', '검수 작업'), ('wm_data_snapshot', '스냅샷 관리')]),
            ('기준정보', 'uil-box', [('wm_product_bom', '품목·BOM 조회'), ('wm_receipt', '입고 내역')]),
            ('시스템 관리', 'uil-cog', [
                ('wm_interface_log', '인터페이스 이력'), ('wm_depart', '부서 정보'), ('wm_user', '사용자'), ('wm_user_group', '사용자 그룹'), ('wm_user_group_menu', '메뉴 권한'),
                ('wm_menu_language', '메뉴명 설정'), ('wm_login_log', '로그인 로그'), ('wm_menu_log', '메뉴 로그'),
                ('wm_system_log', '시스템 로그')]),
        ])

    def test_작업지시_관리는_품질검사_작성에_합쳤다(self):
        """작업지시 관리 화면은 지우고 품질검사 작성의 검사 작업 목록(대기·작성 중)으로 합쳤다(사용자 결정 2026-10-21)."""
        from domain.gui import GUIConfiguration
        self.assertIsNone(GUIConfiguration.get_gui_info('wm_work_order'))

    def test_AI_모델_매핑_화면은_지웠다(self):
        from domain.gui import GUIConfiguration
        self.assertIsNone(GUIConfiguration.get_gui_info('wm_vis_model_mapping'))
        self.assertIsNone(GUIConfiguration.get_menu_code_by_taskview('vision', 'model_mapping'))

    def test_화면_이름이_메뉴_이름과_같다(self):
        from domain.gui import GUIConfiguration
        from domain.models.system import MenuItem
        call_command('seed_initial', stdout=io.StringIO())
        for code, name in MenuItem.objects.values_list('MenuCode', 'MenuName'):
            self.assertEqual(GUIConfiguration.get_gui_info(code)['name'], name, code)


    def test_대시보드는_모든_그룹이_읽고_쓴다(self):
        """로그인 첫 화면이라 일반사용자 그룹도 기본으로 RW 다(사용자 결정 2026-10-21). 시드 뒤에 만든 그룹도 다시 돌리면 받는다."""
        from domain.models.user import UserGroup, UserGroupMenu
        call_command('seed_initial', stdout=io.StringIO())
        UserGroup.objects.create(Code='e2e-line', Name='라인 작업자')
        call_command('seed_initial', stdout=io.StringIO())
        self.assertEqual(dict(UserGroupMenu.objects.filter(MenuCode='wm_dashboard').values_list('UserGroup__Code', 'AuthCode')),
                         {'admin': 'RW', 'user': 'RW', 'e2e-line': 'RW'})
        self.assertFalse(UserGroupMenu.objects.filter(UserGroup__Code='user').exclude(MenuCode='wm_dashboard').exists())

class CategoryMenuTest(TestCase):
    """비전 데이터 관리 > 대분류 › 중분류 › 비전검사항목(끝 메뉴 = 홈). 설계 2026-10-21 §4."""

    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        self.user = User.objects.create_user('menu-user', password='x')

    def category(self, name, parent=None, order=0):
        with tenant_atomic():
            return InspectionCategory.objects.create(tenant=self.tenant, name=name, parent=parent, sort_order=order,
                                                     form_type='' if parent else 'INCOMING')

    def item(self, code, category=None, task_type='OBJECT_DETECTION'):
        with tenant_atomic():
            item = InspectionItem.objects.create(tenant=self.tenant, code=code, name=f'{code} 이름', task_type=task_type,
                                                 category=category)
        return item

    def nodes(self, granted=ITEM_CHILD_MENU_CODES):
        return _item_nodes(self.user, granted)

    @staticmethod
    def shape(nodes):
        return [(n['objNm'], n['menuDepth'], CategoryMenuTest.shape(n['nodes'])) if n['nodes'] else (n['objNm'], n['menuDepth'])
                for n in nodes]

    def test_대분류_중분류_비전검사항목_순서로_묶고_빈_분류는_감추며_미분류가_끝이다(self):
        shipping = self.category('출하검사', order=2)
        incoming = self.category('수입검사', order=1)
        self.category('조립검사', order=3)                       # 항목 없음 — 감춘다
        rotor = self.category('Rotor 성적서', incoming)
        self.category('빈 중분류', incoming)                     # 항목 없음 — 감춘다
        final = self.category('출하검수', shipping)
        self.item('B', rotor)
        self.item('A', rotor)
        self.item('C', final)
        self.item('D')
        with tenant_atomic():                                    # 삭제 승인 대기 — 플랫폼 관리자만 본다
            InspectionItem.objects.filter(pk=self.item('E', rotor).pk).update(status=InspectionItem.Status.DELETION_PENDING)
        self.assertEqual(self.shape(self.nodes()), [
            ('수입검사', 2, [('Rotor 성적서', 3, [('A 이름', 4), ('B 이름', 4)])]),
            ('출하검사', 2, [('출하검수', 3, [('C 이름', 4)])]),
            ('미분류', 2, [('D 이름', 4)]),
        ])

    def test_미분류_대분류가_있으면_소속_없는_항목은_그_아래_중분류_다음이다(self):
        """미분류는 실제 대분류다(사용자 결정 2026-10-21). 소속 없는 항목은 그 중분류 뒤에 바로 붙는다."""
        with tenant_atomic():
            none = InspectionCategory.objects.create(tenant=self.tenant, name='미분류', form_type='', sort_order=3)
        self.item('A', self.category('기타', none))
        self.item('D')
        self.assertEqual(self.shape(self.nodes()), [('미분류', 2, [('기타', 3, [('A 이름', 4)]), ('D 이름', 4)])])
        self.assertEqual(self.nodes()[0]['objId'], f'cat{none.id}')

    def test_비전검사항목은_홈을_여는_끝_메뉴다(self):
        item = self.item('A', self.category('중분류', self.category('대분류')))
        leaf = self.nodes()[0]['nodes'][0]['nodes'][0]
        self.assertEqual((leaf['objId'], leaf['objUrl'], leaf['nodes'], leaf['tabTitle']),
                         (f'item{item.id}_wm_data_item_detail', f'/gui/wm_data_item_detail/?inspection_item={item.id}', [], 'A 이름'))
        self.assertTrue(self.nodes()[0]['objId'].startswith('cat'))

    def test_홈_권한이_없으면_권한_있는_첫_화면을_연다(self):
        item = self.item('A')
        leaf = self.nodes({'wm_data_labeling', 'wm_data_image'})[0]['nodes'][0]
        self.assertEqual(leaf['objUrl'], f'/gui/wm_data_image/?inspection_item={item.id}')
        self.assertEqual(leaf['objId'], f'item{item.id}_wm_data_image')

    def test_치수_측정_항목은_홈과_데이터_목록만_연다(self):
        self.item('DET')
        self.item('DIM', task_type='MEASUREMENT')
        names = [n['objNm'] for n in self.nodes({'wm_data_labeling'})[0]['nodes']]
        self.assertEqual(names, ['DET 이름'])

    def test_하위_화면_권한이_없으면_노드가_없다(self):
        self.item('A')
        self.assertEqual(self.nodes(set()), [])
