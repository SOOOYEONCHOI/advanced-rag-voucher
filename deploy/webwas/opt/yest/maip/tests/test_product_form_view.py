"""품목 검사양식 API(`/api/system/product_form`) — 양식 기준으로 검사할 품번을 N:M 으로 맞춘다(설계 2026-10-21 §6).

양식은 수입검사 양식 중 사용 중인 최신 버전이 있는 코드만 고른다. 품번은 리비전과 상관없고 이름은 가장 나중 리비전의 것이다.
"""
import json
from types import SimpleNamespace

from django.core.exceptions import PermissionDenied
from django.test import TestCase

from app.views.system.product_form import product_form
from domain.gui import GUIConfiguration
from domain.models.basic import Product, ProductForm
from domain.models.dig_form import DigForm


def call(method='GET', **params):
    request = SimpleNamespace(method=method, user=None)
    gparam = {'action': params.pop('action')}
    return product_form(SimpleNamespace(request=request, gparam=gparam if method == 'POST' else dict(gparam, **params),
                                        posparam=params if method == 'POST' else {}))


class ProductFormViewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        Product.objects.create(Code='MEC1.A', PartNo='MEC1', Revision='A', Name='옛 이름')
        Product.objects.create(Code='MEC1.B', PartNo='MEC1', Revision='B', Name='새 이름', PartType='가공')
        Product.objects.create(Code='S2.A', PartNo='S2', Revision='A', Name='판금')
        Product.objects.create(Code='S3.A', PartNo='S3', Revision='A', Name='판금 커버')
        DigForm.objects.create(Code='DF9001', Version=1, Title='수입 양식', FormType='INCOMING')
        DigForm.objects.create(Code='DF9004', Version=1, Title='수입 양식 둘', FormType='INCOMING', LayoutType='SECTION')
        DigForm.objects.create(Code='DF9002', Version=1, Title='품질 양식', FormType='OUTGOING')
        DigForm.objects.create(Code='DF9003', Version=1, Title='중지 양식', FormType='INCOMING', UseYN='N')
        ProductForm.objects.create(PartNo='S2', FormCode='DF9001')
        ProductForm.objects.create(PartNo='S2', FormCode='DF9004')
        ProductForm.objects.create(PartNo='MEC1', FormCode='DF9001')

    def test_양식_목록은_사용_중인_수입검사_양식과_매핑_품목_수다(self):
        self.assertEqual(call(action='forms'), [
            {'code': 'DF9001', 'title': '수입 양식', 'version': 1, 'item_count': 2},
            {'code': 'DF9004', 'title': '수입 양식 둘', 'version': 1, 'item_count': 1}])

    def test_양식의_품목은_품번마다_한_줄이고_가장_나중_리비전_이름이다(self):
        self.assertEqual(call(action='items', form_code='DF9001'), [
            {'part_no': 'MEC1', 'name': '새 이름', 'part_type': '가공', 'spec': None},
            {'part_no': 'S2', 'name': '판금', 'part_type': None, 'spec': None}])

    def test_추가할_품목은_화면_목록에_아직_없는_품번이다(self):
        """[수정] 중에 더하고 뺀 것은 아직 저장 전이라 화면이 지금 목록을 exclude 로 보낸다."""
        self.assertEqual([r['part_no'] for r in call(action='products', exclude=json.dumps(['MEC1', 'S2']))], ['S3'])
        self.assertEqual([r['part_no'] for r in call(action='products', exclude=json.dumps(['MEC1']), keyword='판금')], ['S2', 'S3'])

    def test_저장하면_그_양식의_품목을_보낸_목록으로_맞춘다(self):
        body = call('POST', action='save', form_code='DF9001', part_nos=json.dumps(['S2', 'S3']))
        self.assertEqual(body, {'success': True, 'message': '', 'added': 1, 'removed': 1})
        self.assertEqual(set(ProductForm.objects.filter(FormCode='DF9001').values_list('PartNo', flat=True)), {'S2', 'S3'})
        self.assertEqual(ProductForm.objects.filter(PartNo='S2').count(), 2)    # 다른 양식 매핑은 그대로

    def test_빈_목록을_저장하면_그_양식의_매핑만_푼다(self):
        self.assertTrue(call('POST', action='save', form_code='DF9001', part_nos='[]')['success'])
        self.assertEqual(list(ProductForm.objects.values_list('FormCode', flat=True)), ['DF9004'])

    def test_고를_수_없는_양식이나_없는_품번은_거절한다(self):
        for code in ('DF9002', 'DF9003', 'NONE'):
            body = call('POST', action='save', form_code=code, part_nos=json.dumps(['S3']))
            self.assertEqual(body, {'success': False, 'message': '사용 중인 수입검사 양식을 골라 주세요.'}, code)
        body = call('POST', action='save', form_code='DF9001', part_nos=json.dumps(['S3', 'GONE']))
        self.assertEqual(body, {'success': False, 'message': '품번을 찾을 수 없습니다: GONE'})
        self.assertFalse(ProductForm.objects.filter(PartNo='S3').exists())
        self.assertEqual(ProductForm.objects.filter(FormCode='DF9001').count(), 2)

    def test_변경은_POST_로만_받는다(self):
        with self.assertRaises(PermissionDenied):
            call(action='save', form_code='DF9001', part_nos='[]')

    def test_API_는_품목_검사양식_메뉴_권한으로_연다(self):
        self.assertEqual(GUIConfiguration.get_menu_code_by_taskview('system', 'product_form'), ['wm_product_form'])
