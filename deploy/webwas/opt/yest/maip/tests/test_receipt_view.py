"""입고 내역 API(`/api/definition/receipt`, 기준정보) — 조회 전용이고 검사 정보는 주지 않는다(설계 2026-10-21 §6).

자재입고 검색 팝업(수입 검사작성)도 이 API 를 부른다 — 검사 대상만(`target_only`) = 품번에 수입검사 양식이 매핑된 입고.
"""
import datetime
from types import SimpleNamespace

from django.test import TestCase

from app.views.definition.receipt import receipt
from domain.gui import GUIConfiguration
from domain.models.basic import Product, ProductForm, Receipt
from domain.models.dig_form import DigForm, DigFormResult


def call(user=None, **gparam):
    return receipt(SimpleNamespace(request=SimpleNamespace(user=user), gparam=gparam, posparam={}))


class ReceiptViewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        mapped = Product.objects.create(Code='MEC1.A', PartNo='MEC1', Revision='A', Name='맵핑 품목')
        plain = Product.objects.create(Code='S2.A', PartNo='S2', Revision='A', Name='일반 품목')
        DigForm.objects.create(Code='DF9001', Version=1, Title='수입 양식', FormType='INCOMING')
        cls.latest = DigForm.objects.create(Code='DF9001', Version=2, Title='수입 양식', FormType='INCOMING')
        ProductForm.objects.create(PartNo='MEC1', FormCode='DF9001')
        for seq, product, day in ((1, mapped, 23), (2, mapped, 23), (3, plain, 22), (4, mapped, 21)):
            Receipt.objects.create(ReceiptNo=f'PRQ1-{seq}', ReqNo='PRQ1', ReqSeq=seq, Product=product, ItemCode=product.Code,
                                   ItemName=product.Name, Qty=2, ReceiptDate=datetime.date(2026, 10, day), ProjectNo='W1')
        DigFormResult.objects.create(DigForm=cls.latest, WriteDate='2026-10-19', WorkOrderNumber='PRQ1-2')
        DigFormResult.objects.create(DigForm=cls.latest, WriteDate='2026-10-19', WorkOrderNumber='PRQ1-4', State='done')

    def test_목록은_입고_정보만_준다(self):
        rows = call(action='list')['rows']
        self.assertEqual([r['receipt_no'] for r in rows], ['PRQ1-1', 'PRQ1-2', 'PRQ1-3', 'PRQ1-4'])
        self.assertEqual((rows[0]['receipt_date'], rows[0]['qty'], rows[0]['item_name']), ('2026-10-23', '2', '맵핑 품목'))
        for key in ('form_code', 'form_id', 'form_title', 'state', 'state_label'):
            self.assertNotIn(key, rows[0])

    def test_검색_조건으로_거른다(self):
        def nos(**gparam):
            return [r['receipt_no'] for r in call(action='list', **gparam)['rows']]
        self.assertEqual(nos(target_only='Y'), ['PRQ1-1', 'PRQ1-2', 'PRQ1-4'])     # 자재입고 검색 팝업
        self.assertEqual(nos(keyword='일반'), ['PRQ1-3'])
        self.assertEqual(nos(keyword='prq1-4'), ['PRQ1-4'])
        self.assertEqual(nos(date_from='2026-10-22', date_to='2026-10-22'), ['PRQ1-3'])
        self.assertEqual(nos(project='w1', page='2', page_size='3'), ['PRQ1-4'])

    def test_검사_대기_건수와_작성_권한은_이_API_가_아니다(self):
        for action in ('pending_count', 'can_write'):
            self.assertEqual(call(action=action), {'success': False, 'message': '입고 정보를 불러오지 못했습니다.'})

    def test_입고_API_는_입고_조회와_수입_검사작성_메뉴로_연다(self):
        self.assertEqual(GUIConfiguration.get_menu_code_by_taskview('definition', 'receipt'),
                         ['wm_receipt', 'wm_dig_form_incoming_write'])
        self.assertEqual(GUIConfiguration.get_gui_info('wm_receipt')['templates']['default'], 'definition/receipt.html')
