"""ERP 구매요청 현황(= 입고의뢰) 수신건을 입고(mst_receipt)에 반영한다.

구매요청 한 줄 = 입고 한 줄이고 입고번호는 요청번호-요청순번이다. 품목 마스터에 없는 품목은 구매요청 값으로 만든다.
파일에 없는 기존 입고는 건드리지 않는다. 검증이 하나라도 틀리면 아무것도 반영하지 않는다.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from domain.models.basic import Product, Receipt
from domain.models.interface import IfBatch
from domain.services.interface import apply, receive


def line(seq, item='MEC15710.C', **more):
    values = dict(ReqNo='PRQ1', ReqSeq=str(seq), Item=item, ItemName='NAME ' + item, Spec='SPEC', Category='기구구매',
                  Unit='EA', ReqQty='2', ApprQty='2', ReqDueDate='2026-10-23', PlanReceiptDateAppr='2026-10-22',
                  VendorAppr='업체A', ProjectNo='W1', ProjectName='NEOCON', RequesterName='담당자')
    values.update(more)
    return values


def erp(*rows):
    return receive(IfBatch.Kinds.ERP_PURCHASE_REQ, list(rows), IfBatch.Channels.FILE, 'prq.xlsx')


class ReceiptApplyTest(TestCase):

    def test_구매요청_한_줄이_입고_한_줄이_되고_없는_품목은_만든다(self):
        Product.objects.create(Code='MEC15710.C', PartNo='MEC15710', Revision='C', Name='PLM 이름')

        result = apply(erp(line(1), line(2, 'S2804158.A', EoNo='EO1')))

        self.assertEqual(result, {'receipt_added': 2, 'receipt_updated': 0, 'product_added': 1})
        r = Receipt.objects.get(ReceiptNo='PRQ1-2')
        self.assertEqual((r.ReqNo, r.ReqSeq, r.Product.Code, r.Qty, r.ReceiptDate, r.VendorName, r.EoNo),
                         ('PRQ1', 2, 'S2804158.A', Decimal('2'), datetime.date(2026, 10, 22), '업체A', 'EO1'))
        made = Product.objects.get(Code='S2804158.A')
        self.assertEqual((made.PartNo, made.Revision, made.Name, made.Spec), ('S2804158', 'A', 'NAME S2804158.A', 'SPEC'))
        self.assertEqual(Product.objects.get(Code='MEC15710.C').Name, 'PLM 이름')   # 있는 품목은 PLM 값을 그대로 둔다

    def test_발주_값이_있으면_수량과_입고일은_발주_값이다(self):
        apply(erp(line(1, PoQty='5', PlanReceiptDatePo='2026-10-30', VendorPo='업체B'), line(2, PlanReceiptDateAppr=None)))

        po = Receipt.objects.get(ReceiptNo='PRQ1-1')
        self.assertEqual((po.Qty, po.ReceiptDate, po.VendorName), (Decimal('5'), datetime.date(2026, 10, 30), '업체B'))
        self.assertEqual(Receipt.objects.get(ReceiptNo='PRQ1-2').ReceiptDate, datetime.date(2026, 10, 23))  # 요청납기일

    def test_다시_받으면_바뀐_줄만_고치고_파일에_없는_입고는_그대로_둔다(self):
        first = erp(line(1), line(2))
        apply(first)
        second = erp(line(1, ApprQty='3', ReqQty='3'))

        result = apply(second)

        self.assertEqual(result, {'receipt_added': 0, 'receipt_updated': 1, 'product_added': 0})
        self.assertEqual(Receipt.objects.get(ReceiptNo='PRQ1-1').Qty, Decimal('3'))
        self.assertEqual(Receipt.objects.get(ReceiptNo='PRQ1-1').Batch_id, second.id)
        self.assertEqual(Receipt.objects.get(ReceiptNo='PRQ1-2').Batch_id, first.id)
        self.assertEqual(apply(second), {'receipt_added': 0, 'receipt_updated': 0, 'product_added': 0})

    def test_검증이_틀리면_아무것도_반영하지_않는다(self):
        cases = {
            '요청번호': [line(1, ReqNo=None)],
            '요청순번': [line('x')],
            '품목': [line(1, item='NODOT')],
            '수량': [line(1, ApprQty='0', ReqQty='0')],
            '날짜': [line(1, PlanReceiptDateAppr='2026/10/22')],
            '두 번': [line(1), line(1)],
        }
        for word, rows in cases.items():
            with self.subTest(word):
                batch = erp(*rows)
                with self.assertRaisesMessage(ValueError, word):
                    apply(batch)
                self.assertFalse(Receipt.objects.exists())
                self.assertFalse(Product.objects.exists())
                batch.refresh_from_db()
                self.assertEqual(batch.Status, IfBatch.Statuses.APPLY_FAILED)
