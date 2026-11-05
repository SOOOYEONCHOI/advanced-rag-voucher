"""검사 분류(대분류 › 중분류) 모델 제약과 품목 검사양식 N:M (설계 2026-10-21 §2)."""
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from domain.models.basic import ProductForm
from domain.models.data import InspectionCategory, InspectionItem
from domain.models.user import UserGroupMenu
from domain.services.data import category as categories
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from tests.test_item_api import AJAX, PASSWORD, ItemApiTestCase


class CategoryModelTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()

    def make(self, name, parent=None, **fields):
        with tenant_atomic():
            if parent is None:
                fields.setdefault('form_type', 'INCOMING')
            return InspectionCategory.objects.create(tenant=self.tenant, parent=parent, name=name, **fields)

    def assertIntegrity(self, fn):
        with self.assertRaises(IntegrityError), transaction.atomic():
            fn()

    def test_대분류_이름은_겹치지_않는다(self):
        self.make('수입검사')
        self.assertIntegrity(lambda: self.make('수입검사'))

    def test_중분류_이름은_같은_대분류_안에서만_겹치지_않는다(self):
        incoming, outgoing = self.make('수입검사'), self.make('출하검사', form_type='OUTGOING')
        self.make('성적서', incoming)
        self.make('성적서', outgoing)
        self.assertIntegrity(lambda: self.make('성적서', incoming))

    def test_양식_하나는_중분류_하나에만_매핑한다(self):
        major = self.make('수입검사')
        self.make('A', major, form_code='DF0015')
        self.make('B', major)
        self.make('C', major)
        self.assertIntegrity(lambda: self.make('D', major, form_code='DF0015'))

    def test_단계별_칸이_맞지_않으면_거절한다(self):
        self.assertIntegrity(lambda: self.make('대분류', form_code='DF0015'))
        major = self.make('수입검사')
        self.assertIntegrity(lambda: self.make('중분류', major, form_type='INCOMING'))

    def test_비전검사항목이_있는_중분류는_지우지_않는다(self):
        minor = self.make('성적서', self.make('수입검사'))
        with tenant_atomic():
            InspectionItem.objects.create(tenant=self.tenant, code='VIS-T', name='표면', category=minor)
            with self.assertRaises(ProtectedError):
                minor.delete()


class ProductFormManyToManyTest(TestCase):
    def test_품번_하나에_양식_여러_개(self):
        ProductForm.objects.create(PartNo='P1', FormCode='DF1')
        ProductForm.objects.create(PartNo='P1', FormCode='DF2')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductForm.objects.create(PartNo='P1', FormCode='DF1')


def make_dig_form(code, form_type='INCOMING', layout='SECTION', version=1, use='Y', title=None):
    from domain.models.dig_form import DigForm
    return DigForm.objects.create(Code=code, Version=version, Title=title or f'{code} 양식', FormType=form_type,
                                  LayoutType=layout, UseYN=use)


class CategoryApiTest(ItemApiTestCase):
    """검사 분류 관리(`wm_data_item`) — 분류는 메뉴 권한(W), 비전검사항목은 플랫폼 관리자."""

    menus = {'wm_data_item': 'RW'}

    def setUp(self):
        super().setUp()
        make_dig_form('DF-IN')
        make_dig_form('DF-IN2')
        make_dig_form('DF-OUT', form_type='OUTGOING')
        make_dig_form('DF-GRID', layout='GRID')
        make_dig_form('DF-OLD')
        make_dig_form('DF-OLD', version=2, use='N')

    def post(self, action, user=None, **data):
        return self.http(user or self.manager).post(f'/api/item/category?action={action}', data, **AJAX)

    def get(self, action, user=None, **params):
        return self.http(user or self.manager).get('/api/item/category', {'action': action, **params}, **AJAX)

    def major(self, name='수입검사'):
        """고정 대분류(수입검사·품질검사·미분류)의 id — 대분류는 만들지 않는다(사용자 결정 2026-10-21)."""
        with tenant_atomic(self.tenant):
            categories.ensure_fixed_majors(self.tenant)
            return InspectionCategory.objects.get(tenant=self.tenant, parent=None, name=name).id

    def minor(self, parent_id, name='성적서', **extra):
        response = self.post('save_minor', parent_id=parent_id, name=name, **extra)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['id']

    def test_트리는_고정_대분류_순서이고_소속_없는_항목은_미분류_대분류_아래다(self):
        incoming, quality, none = self.major('수입검사'), self.major('품질검사'), self.major('미분류')
        minor = self.minor(incoming, '성적서', form_code='DF-IN')
        with tenant_atomic(self.tenant):
            InspectionItem.objects.create(tenant=self.tenant, code='VIS-A', name='표면', category_id=minor)
        rows = self.get('tree').json()['rows']
        self.assertEqual([(r['id'], r['parent_id'], r['kind']) for r in rows], [
            (f'cat{incoming}', None, 'major'), (f'cat{minor}', f'cat{incoming}', 'minor'),
            (f'item{InspectionItem.objects.get(code="VIS-A").id}', f'cat{minor}', 'item'),
            (f'cat{quality}', None, 'major'), (f'cat{none}', None, 'major'), (f'item{self.item.id}', f'cat{none}', 'item')])
        minor_row = rows[1]
        self.assertEqual((minor_row['form_code'], minor_row['form_title']), ('DF-IN', 'DF-IN 양식'))
        self.assertEqual([r['form_type_label'] for r in rows if r['kind'] == 'major'], ['수입', '품질', ''])
        self.assertEqual(rows[-1]['category_label'], '미분류')
        self.assertFalse(self.get('tree').json()['can_manage_items'])

    def test_비전검사항목_행은_지금_AI_모델_이름을_준다(self):
        """목록 "매핑" 열 — 중분류는 양식, 비전검사항목은 AI 모델이다(사용자 결정 2026-10-21). 치수 측정은 모델이 없다."""
        from domain.models.vision import VisionItemModelMapping, VisionModel
        model = VisionModel.objects.create(name='wz-det', version='latest', inspection_type='DETECTION', artifact_path='',
                                           runtime='wezard')
        VisionItemModelMapping.objects.create(item=self.item, model=model, model_code='wz-det', model_version='latest',
                                              active=False)
        rows = {r['id']: r for r in self.get('tree').json()['rows']}
        self.assertEqual(rows[f'item{self.item.id}']['model_name'], '')       # 비활성 매핑(이력)은 보이지 않는다
        VisionItemModelMapping.objects.create(item=self.item, model=model, model_code='wz-det', model_version='latest',
                                              active=True)
        rows = {r['id']: r for r in self.get('tree').json()['rows']}
        self.assertEqual(rows[f'item{self.item.id}']['model_name'], 'wz-det')

    def test_대분류는_만들거나_고치거나_지우지_않는다(self):
        major = self.major()
        self.assertEqual(self.post('save_major', name='조립검사', form_type='OUTGOING').status_code, 400)
        self.assertEqual(self.post('delete', category_id=major).json()['message'], '대분류는 고정이라 지울 수 없습니다.')
        with tenant_atomic(self.tenant):
            self.assertEqual(InspectionCategory.objects.filter(parent=None).count(), 3)

    def test_중분류는_같은_구분의_사용_중인_최신_섹션_양식만_매핑한다(self):
        major = self.major()
        for code in ('DF-OUT', 'DF-GRID', 'DF-OLD', 'DF-NONE'):
            response = self.post('save_minor', parent_id=major, name='X', form_code=code)
            self.assertEqual(response.json()['message'], '같은 구분의 사용 중인 섹션 양식을 골라 주세요.', code)
        first = self.minor(major, 'A', form_code='DF-IN')
        self.assertEqual(self.post('save_minor', parent_id=major, name='B', form_code='DF-IN').json()['message'],
                         'A에 이미 매핑된 양식입니다.')
        self.post('save_minor', category_id=first, parent_id=major, name='A', form_code='')   # 매핑 풀기
        self.minor(major, 'B', form_code='DF-IN')
        self.minor(self.major('품질검사'), 'C', form_code='DF-OUT')

    def test_미분류_중분류는_양식을_매핑하지_않는다(self):
        none = self.major('미분류')
        self.assertEqual(self.post('save_minor', parent_id=none, name='X', form_code='DF-IN').json()['message'],
                         '미분류에는 양식을 매핑하지 않습니다.')
        self.minor(none, '기타')

    def test_중분류의_상위는_대분류여야_한다(self):
        minor = self.minor(self.major())
        self.assertEqual(self.post('save_minor', parent_id=minor, name='손자').json()['message'], '대분류를 골라 주세요.')

    def test_비전검사항목이_없어야_중분류를_지운다(self):
        minor = self.minor(self.major())
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(category_id=minor)
        self.assertEqual(self.post('delete', category_id=minor).json()['message'],
                         '비전검사항목이 있는 중분류는 지울 수 없습니다.')
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(category_id=None)
        self.assertTrue(self.post('delete', category_id=minor).json()['success'])

    def test_양식_목록은_같은_구분의_사용_중인_최신_섹션_양식이다(self):
        forms = self.get('forms', form_type='INCOMING').json()['forms']
        self.assertEqual([f['code'] for f in forms], ['DF-IN', 'DF-IN2'])

    def test_메뉴_R_만이면_조회만_한다(self):
        UserGroupMenu.objects.filter(MenuCode='wm_data_item').update(AuthCode='R')
        self.assertEqual(self.get('tree').status_code, 200)
        self.assertEqual(self.post('save_minor', parent_id=self.major(), name='성적서').status_code, 403)

    def test_플랫폼_관리자는_비전검사항목을_다룰_수_있다고_알린다(self):
        admin = User.objects.create_superuser('platform-root', password=PASSWORD)
        self.assertTrue(self.get('tree', user=admin).json()['can_manage_items'])


class FixedMajorTest(TestCase):
    """대분류는 수입검사·품질검사·미분류 셋으로 고정이다(사용자 결정 2026-10-21). 그 밖의 대분류는 중분류를 같은 양식 구분의
    고정 대분류로 옮기고 지운다 — 조립검사·출하검사(품질 양식)는 품질검사 아래로 간다. seed_vision_items 가 부른다."""

    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()

    def make(self, name, parent=None, **fields):
        return InspectionCategory.objects.create(tenant=self.tenant, parent=parent, name=name, **fields)

    def test_고정_대분류를_만들고_다른_대분류의_중분류를_옮긴다(self):
        with tenant_atomic(self.tenant):
            quality = self.make('품질검사', form_type='OUTGOING', sort_order=3)
            self.make('8계통 Check Sheet', quality, sort_order=1)
            assembly = self.make('조립검사', form_type='OUTGOING', sort_order=2)
            module = self.make('Module Check Sheet', assembly, sort_order=1, form_code='DF-OUT')
            shipping = self.make('출하검사', form_type='OUTGOING', sort_order=4)
            ship_sheet = self.make('출하검수 Sheet', shipping, sort_order=1)
            self.make('8계통 Check Sheet', shipping, sort_order=2)        # 옮길 곳에 같은 이름이 있다
            item = InspectionItem.objects.create(tenant=self.tenant, code='VIS-X', name='X', category=module)
            loose = InspectionItem.objects.create(tenant=self.tenant, code='VIS-Y', name='Y', category=shipping)
            categories.ensure_fixed_majors(self.tenant)
            categories.ensure_fixed_majors(self.tenant)     # 멱등

            majors = list(InspectionCategory.objects.filter(parent=None).values_list('name', 'form_type'))
            self.assertEqual(majors, [('수입검사', 'INCOMING'), ('품질검사', 'OUTGOING'), ('미분류', '')])
            quality.refresh_from_db()
            # 옛 대분류 순서(조립 2 · 품질 3 · 출하 4) → 중분류 순서로 다시 매긴다 — 새로 시드한 DB 와 같은 업무 순서다
            self.assertEqual(list(quality.children.values_list('name', 'sort_order')), [
                ('Module Check Sheet', 1), ('8계통 Check Sheet', 2), ('출하검수 Sheet', 3), ('8계통 Check Sheet (출하검사)', 4)])
            item.refresh_from_db(); loose.refresh_from_db(); ship_sheet.refresh_from_db()
            self.assertEqual((item.category_id, ship_sheet.parent_id), (module.id, quality.id))
            self.assertEqual(InspectionCategory.objects.get(pk=module.pk).form_code, 'DF-OUT')   # 매핑은 그대로
            self.assertIsNone(loose.category_id)          # 대분류를 가리키던 항목은 미분류
