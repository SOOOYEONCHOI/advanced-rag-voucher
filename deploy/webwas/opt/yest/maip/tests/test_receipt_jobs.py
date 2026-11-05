"""수입 검사 작업 — 매핑 (품번 × 양식코드) × 입고 중 그 양식코드·입고번호 작성건이 없는 것이 대기다(설계 2026-10-21 §6)."""
import datetime

from django.test import TestCase

from domain.models.basic import Product, ProductForm, Receipt
from domain.models.dig_form import DigForm, DigFormResult
from domain.services import receipt as receipts


class ReceiptJobsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.mec = Product.objects.create(Code='MEC1.A', PartNo='MEC1', Revision='A', Name='브래킷')
        cls.box = Product.objects.create(Code='BOX1.A', PartNo='BOX1', Revision='A', Name='전장 BOX')
        cls.free = Product.objects.create(Code='FREE.A', PartNo='FREE', Revision='A', Name='매핑 없음')
        cls.f1 = DigForm.objects.create(Code='DF-J1', Version=1, Title='가공품 성적서', FormType='INCOMING')
        cls.f1v2 = DigForm.objects.create(Code='DF-J1', Version=2, Title='가공품 성적서 v2', FormType='INCOMING')
        cls.f2 = DigForm.objects.create(Code='DF-J2', Version=1, Title='외관 시트', FormType='INCOMING')
        DigForm.objects.create(Code='DF-OFF', Version=1, Title='안 씀', FormType='INCOMING', UseYN='N')
        for part, code in (('MEC1', 'DF-J1'), ('MEC1', 'DF-J2'), ('BOX1', 'DF-J2'), ('BOX1', 'DF-OFF')):
            ProductForm.objects.create(PartNo=part, FormCode=code)

    def receipt(self, no, product, day):
        return Receipt.objects.create(ReceiptNo=no, ReqNo=no.split('-')[0], ReqSeq=int(no.split('-')[1]), Product=product,
                                      ItemCode=product.Code, ItemName=product.Name, Qty=1,
                                      ReceiptDate=datetime.date(2026, 10, day))

    def write(self, form, no, state='working'):
        return DigFormResult.objects.create(DigForm=form, WriteDate=datetime.date(2026, 10, 21), WorkOrderNumber=no, State=state)

    @staticmethod
    def pairs(jobs):
        return [(r.ReceiptNo, f.Code) for r, f in jobs]

    def test_품번_하나에_양식_둘이면_대기_작업이_둘이고_최신_입고가_먼저다(self):
        self.receipt('R1-1', self.mec, 1)
        self.receipt('R1-2', self.box, 5)
        self.receipt('R1-3', self.free, 9)
        jobs = receipts.waiting_jobs()
        self.assertEqual(self.pairs(jobs), [('R1-2', 'DF-J2'), ('R1-1', 'DF-J1'), ('R1-1', 'DF-J2')])
        self.assertEqual(dict((r.ReceiptNo + f.Code, f.Version) for r, f in jobs)['R1-1DF-J1'], 2)   # 사용 중인 최신 버전

    def test_작성건이_있으면_상태와_버전에_상관없이_대기가_아니다(self):
        self.receipt('R1-1', self.mec, 1)
        self.write(self.f1, 'R1-1')                    # 옛 버전으로 쓴 작성 중
        self.assertEqual(self.pairs(receipts.waiting_jobs()), [('R1-1', 'DF-J2')])
        self.write(self.f2, 'R1-1', state='done')
        self.assertEqual(receipts.waiting_jobs(), [])

    def test_검색어와_양식으로_거른다(self):
        self.receipt('R1-1', self.mec, 1)
        self.receipt('R2-1', self.box, 2)
        self.assertEqual(self.pairs(receipts.waiting_jobs(keyword='BOX')), [('R2-1', 'DF-J2')])
        self.assertEqual(self.pairs(receipts.waiting_jobs(keyword='R1-')), [('R1-1', 'DF-J1'), ('R1-1', 'DF-J2')])
        self.assertEqual(self.pairs(receipts.waiting_jobs(form_code='DF-J1')), [('R1-1', 'DF-J1')])

    def test_배지는_대기와_완료가_없는_작성_중을_센다(self):
        self.receipt('R1-1', self.mec, 1)
        self.receipt('R2-1', self.box, 2)
        self.write(self.f1v2, 'R1-1')                   # MEC1×DF-J1 작성 중
        self.write(self.f2, 'R2-1')                     # BOX1×DF-J2 작성 중이었다가
        self.write(self.f2, 'R2-1', state='done')       # 완료 — 세지 않는다
        self.write(self.f2, 'MANUAL-1')                 # 입고와 무관한 수기 — 세지 않는다
        self.assertEqual(receipts.job_counts(), {'waiting': 1, 'working': 1})   # 대기 R1-1×DF-J2

    def test_검사_작업_목록은_대기가_먼저이고_작성_중은_입고와_수기를_함께_준다(self):
        self.receipt('R1-1', self.mec, 1)
        working = self.write(self.f1v2, 'R1-1')
        self.write(self.f2, 'MANUAL-1')
        self.write(self.f2, 'DONE-1', state='done')
        rows = receipts.jobs()
        self.assertEqual([(r['kind'], r['kind_label'], r['receipt_no'], r['form_code']) for r in rows], [
            ('WAITING', '대기', 'R1-1', 'DF-J2'), ('WORKING', '작성 중', 'MANUAL-1', 'DF-J2'), ('WORKING', '작성 중', 'R1-1', 'DF-J1')])
        waiting, manual, mine = rows
        self.assertEqual((waiting['form_id'], waiting['result_id'], waiting['item_name']), (self.f2.id, None, '브래킷'))
        self.assertEqual((mine['result_id'], mine['form_version'], mine['item_code']), (working.id, 2, 'MEC1.A'))
        self.assertEqual((manual['item_code'], manual['receipt_date']), ('', ''))
        self.assertEqual((mine['write_date'], mine['header_values'], mine['is_mine']), ('2026-10-21', {}, False))
        self.assertEqual([r['kind'] for r in receipts.jobs(kind='WAITING')], ['WAITING'])
        self.assertEqual([r['receipt_no'] for r in receipts.jobs(kind='WORKING', keyword='브래킷')], ['R1-1'])
        self.assertEqual([r['receipt_no'] for r in receipts.jobs(form_code='DF-J1')], ['R1-1'])

