"""외부 인터페이스 엑셀을 수신 테이블(`if_*`)에 원본 그대로 넣는다.

머리글은 모델 칼럼의 verbose_name 으로 찾는다. 값은 글자로 담고 빈 칸은 NULL 이다.
머리글이 하나라도 다르면 한 행도 넣지 않는다 — 양식이 바뀐 파일을 조용히 받지 않는다.
실패한 수신도 수신건(수신 실패, 행 0)으로 남아 이력에서 보인다.
"""
import datetime
import shutil
import tempfile
from pathlib import Path

import openpyxl
from django.core.management import CommandError, call_command
from django.db.models import TextField
from django.test import TestCase

from domain.models.interface import IfBatch, IfErpPurchaseReq, IfPlmPartBom
from domain.services.interface import receive_xlsx


def headers(model):
    return [f.verbose_name for f in model._meta.fields if isinstance(f, TextField)]


class InterfaceReceiveTest(TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def _xlsx(self, name, rows):
        wb = openpyxl.Workbook()
        for row in rows:
            wb.active.append(row)
        path = self.dir / name
        wb.save(path)
        return path

    def _plm_row(self, **values):
        return [values.get(h, '') for h in headers(IfPlmPartBom)]

    def test_PLM_파일은_제목줄_아래_머리글을_찾아_원본_값을_넣는다(self):
        hdr = headers(IfPlmPartBom)
        path = self._xlsx('Part_Vertical_BOM.xlsx', [
            ['Part BOM 수직 구조'],
            ['bom', 'bom', None, 'product'],          # PM 이 적은 분류 초안 — 데이터가 아니다
            hdr,
            self._plm_row(**{'No.': '001', 'Depth': '1', 'Line No ( 7 Depth )': '└', 'Part(ERP)': 'KSES28082.A', 'Qty': '1'}),
            self._plm_row(**{'No.': '002', 'Depth': '2', 'Line No ( 7 Depth )': '　├', 'Part(ERP)': 'C101S25.B', 'Qty': '2'}),
            [None] * len(hdr),                         # 끝의 빈 줄은 넣지 않는다
        ])

        call_command('import_interface', 'plm_part_bom', str(path))

        batch = IfBatch.objects.get()
        self.assertEqual((batch.Kind, batch.Channel, batch.SourceRef, batch.RowCount, batch.Status),
                         (IfBatch.Kinds.PLM_PART_BOM, IfBatch.Channels.FILE, 'Part_Vertical_BOM.xlsx', 2, IfBatch.Statuses.RECEIVED))
        rows = list(IfPlmPartBom.objects.order_by('RowNo'))
        self.assertEqual([(r.RowNo, r.No, r.LineNo, r.PartErp, r.Qty) for r in rows],
                         [(1, '001', '└', 'KSES28082.A', '1'), (2, '002', '　├', 'C101S25.B', '2')])
        self.assertIsNone(rows[0].PostProcess)        # 빈 칸('')은 NULL

    def test_ERP_파일의_날짜와_숫자는_글자로_바꿔_넣는다(self):
        hdr = [h.replace('거래처(품의)', '거래처\n(품의)') for h in headers(IfErpPurchaseReq)]
        row = [None] * len(hdr)
        row[hdr.index('요청번호')] = 'PRQ2026090289'
        row[hdr.index('요청순번')] = 3
        row[hdr.index('요청납기일')] = datetime.datetime(2026, 10, 23)
        row[hdr.index('거래처\n(품의)')] = '주식회사 예스히팅테크닉스'
        path = self._xlsx('PUOPRQ00400.xlsx', [hdr, row])

        batch = receive_xlsx(IfBatch.Kinds.ERP_PURCHASE_REQ, path)

        saved = IfErpPurchaseReq.objects.get(Batch=batch)
        self.assertEqual((saved.ReqNo, saved.ReqSeq, saved.ReqDueDate, saved.VendorAppr, saved.PoNo),
                         ('PRQ2026090289', '3', '2026-10-23', '주식회사 예스히팅테크닉스', None))

    def test_머리글이_다르면_한_행도_넣지_않고_수신_실패로_남긴다(self):
        hdr = headers(IfErpPurchaseReq)[:-1]           # 마지막 열이 빠진 파일
        path = self._xlsx('broken.xlsx', [hdr, ['x'] * len(hdr)])

        with self.assertRaisesMessage(CommandError, '요청의견상세'):
            call_command('import_interface', 'erp_purchase_req', str(path))

        batch = IfBatch.objects.get()
        self.assertEqual((batch.Status, batch.RowCount, batch.SourceRef), (IfBatch.Statuses.RECEIVE_FAILED, 0, 'broken.xlsx'))
        self.assertIn('요청의견상세', batch.Message)
        self.assertFalse(IfErpPurchaseReq.objects.exists())

    def test_xlsx_가_아닌_파일도_수신_실패로_남긴다(self):
        path = self.dir / 'not.xlsx'
        path.write_text('엑셀 아님', encoding='utf-8')

        with self.assertRaises(ValueError):
            receive_xlsx(IfBatch.Kinds.PLM_PART_BOM, path)

        self.assertEqual(IfBatch.objects.get().Status, IfBatch.Statuses.RECEIVE_FAILED)
