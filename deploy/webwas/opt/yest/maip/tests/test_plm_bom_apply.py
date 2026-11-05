"""PLM 수신건을 품목(product)·BOM(bom) 마스터에 반영한다.

부모 단위로 직속 자식 목록을 파일과 맞춘다 — 파일에 나오지 않은 조립품(다른 장비)은 건드리지 않는다.
검증이 하나라도 틀리면 아무것도 반영하지 않는다.
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from domain.models.basic import Bom, Product
from domain.models.interface import IfBatch, IfPlmPartBom
from domain.services.interface import INTERFACES, apply
from domain.services.plm_bom import apply_plm_part_bom


def plm_batch(*rows):
    """rows: (depth, code, qty, {원본 칼럼 덮어쓰기}) — 품번·버전은 코드에서 만든다."""
    batch = IfBatch.objects.create(Kind=IfBatch.Kinds.PLM_PART_BOM, SourceRef='t.xlsx', RowCount=len(rows))
    for no, (depth, code, qty, *more) in enumerate(rows, 1):
        part_no, rev = code.split('.')
        values = dict(No=f'{no:03}', Depth=str(depth), PartErp=code, PartNo=part_no, PartVer=f'{rev}.1',
                      PartName=f'NAME {part_no}', PartType='기구', Qty=qty, PartCreated='2026-01-02',
                      PartVerCreated='2026-03-04', Model3dType='prt', Model3dNo=part_no, Model3dVer=f'{rev}.1',
                      Model3dModified='2026-03-04 15:13:38')
        values.update(more[0] if more else {})
        IfPlmPartBom.objects.create(Batch=batch, RowNo=no, **values)
    return batch


def edges():
    return sorted((b.Parent.Code, b.Child.Code, b.Qty, b.Seq) for b in Bom.objects.select_related('Parent', 'Child'))


class PlmBomApplyTest(TestCase):

    def test_수신건을_반영하면_품목과_BOM_이_생긴다(self):
        batch = plm_batch((1, 'R.A', '1'), (2, 'A.B', '2'), (3, 'X.C', '3', {'PostProcess': 'PAINTING[WHITE]'}), (2, 'B.A', '1'))

        call_command('apply_interface', str(batch.id))

        self.assertEqual(edges(), [('A.B', 'X.C', Decimal('3'), 1), ('R.A', 'A.B', Decimal('2'), 1), ('R.A', 'B.A', Decimal('1'), 2)])
        x = Product.objects.get(Code='X.C')
        self.assertEqual((x.PartNo, x.Revision, x.Version, x.Name, x.PostProcess, x.PlmCreatedDate, x.Model3dModified),
                         ('X', 'C', 'C.1', 'NAME X', 'PAINTING[WHITE]', datetime.date(2026, 1, 2),
                          datetime.datetime(2026, 3, 4, 15, 13, 38)))

    def test_두_곳에_쓰인_하위조립품은_한_번만_저장한다(self):
        batch = plm_batch((1, 'R.A', '1'), (2, 'A.A', '1'), (3, 'X.A', '2'), (2, 'C.A', '1'), (3, 'A.A', '1'), (4, 'X.A', '2'))

        result = apply_plm_part_bom(batch)

        self.assertEqual(result['bom_added'], 4)
        self.assertEqual(Bom.objects.filter(Parent__Code='A.A').count(), 1)

    def test_다시_반영하면_자식을_맞추고_다른_장비는_건드리지_않는다(self):
        apply_plm_part_bom(plm_batch((1, 'R.A', '1'), (2, 'A.A', '1'), (3, 'X.A', '1'), (3, 'Y.A', '1'), (1, 'Q.A', '1'), (2, 'Z.A', '1')))
        changed = plm_batch((1, 'R.A', '1'), (2, 'A.A', '1', {'PartName': 'NEW NAME'}), (3, 'X.A', '5'), (3, 'W.A', '1'))

        result = apply_plm_part_bom(changed)

        self.assertEqual(edges(), [('A.A', 'W.A', Decimal('1'), 2), ('A.A', 'X.A', Decimal('5'), 1),
                                   ('Q.A', 'Z.A', Decimal('1'), 1), ('R.A', 'A.A', Decimal('1'), 1)])
        self.assertEqual({k: result[k] for k in ('product_added', 'product_updated', 'bom_added', 'bom_updated', 'bom_deleted')},
                         {'product_added': 1, 'product_updated': 1, 'bom_added': 1, 'bom_updated': 1, 'bom_deleted': 1})
        self.assertTrue(Product.objects.filter(Code='Y.A').exists())    # BOM 에서 빠져도 품목은 남는다
        again = apply_plm_part_bom(changed)
        self.assertEqual(sum(again[k] for k in ('product_added', 'product_updated', 'bom_added', 'bom_updated', 'bom_deleted')), 0)

    def test_하위_없이_나온_품목은_6단계까지만_자식을_비운다(self):
        chain = [(d, f'P{d}.A', '1') for d in range(1, 8)]                   # 1~7단계
        apply_plm_part_bom(plm_batch(*chain, (8, 'K.A', '1'), (2, 'L.A', '1'), (3, 'M.A', '1')))
        # 다시 받은 파일은 7단계 아래가 잘렸고(내보내기 한도), L 은 실제로 하위가 없어졌다
        apply_plm_part_bom(plm_batch(*chain, (2, 'L.A', '1')))

        self.assertTrue(Bom.objects.filter(Parent__Code='P7.A', Child__Code='K.A').exists())
        self.assertFalse(Bom.objects.filter(Parent__Code='L.A').exists())

    def test_검증이_틀리면_아무것도_반영하지_않는다(self):
        cases = {
            'Depth': [(1, 'R.A', '1'), (3, 'X.A', '1')],
            'Part(ERP)': [(1, 'R.A', '1'), (2, 'X.A', '1', {'PartVer': 'B.1'})],
            'Qty': [(1, 'R.A', '1'), (2, 'X.A', '0')],
            '속성': [(1, 'R.A', '1'), (2, 'X.A', '1'), (2, 'Y.A', '1'), (3, 'X.A', '1', {'Spec': 'OTHER'})],
            '두 번': [(1, 'R.A', '1'), (2, 'X.A', '1'), (2, 'X.A', '1')],
            '순환': [(1, 'R.A', '1'), (2, 'X.A', '1'), (3, 'R.A', '1')],
            '날짜': [(1, 'R.A', '1', {'PartCreated': '2026/01/02'})],
        }
        for word, rows in cases.items():
            with self.subTest(word):
                with self.assertRaisesMessage(ValueError, word):
                    apply_plm_part_bom(plm_batch(*rows))
                self.assertFalse(Product.objects.exists())

    def test_DB_의_다른_장비와_엮여_순환이_생기면_되돌린다(self):
        apply_plm_part_bom(plm_batch((1, 'X.A', '1'), (2, 'R.A', '1')))

        # X 를 7단계(내보내기 한도)에 둬야 X→R 이 남는다 — 더 얕으면 하위 없는 X 의 자식을 비워 순환이 사라진다
        chain = [(d, f'P{d}.A', '1') for d in range(1, 6)]
        with self.assertRaisesMessage(ValueError, '순환'):
            apply_plm_part_bom(plm_batch(*chain, (6, 'R.A', '1'), (7, 'X.A', '1', {'PartName': 'CHANGED'})))

        self.assertEqual(edges(), [('X.A', 'R.A', Decimal('1'), 1)])
        self.assertEqual(Product.objects.get(Code='X.A').Name, 'NAME X')

    def test_수신에_실패한_건은_명령으로도_반영하지_않는다(self):
        batch = IfBatch.objects.create(Kind=IfBatch.Kinds.PLM_PART_BOM, SourceRef='b.xlsx', RowCount=0,
                                       Status=IfBatch.Statuses.RECEIVE_FAILED)

        with self.assertRaisesMessage(CommandError, '수신에 실패'):
            call_command('apply_interface', str(batch.id))


class ApplyStatusTest(TestCase):
    """반영 결과는 수신건에 남는다 — 마지막 한 번만(DECISIONS 사용자 결정 2026-10-19)."""

    def test_반영하면_상태와_건수가_남는다(self):
        batch = plm_batch((1, 'R.A', '1'), (2, 'X.A', '1'))

        apply(batch)

        batch.refresh_from_db()
        self.assertEqual((batch.Status, batch.Message, batch.ApplyResult['product_added'], batch.ApplyResult['bom_added']),
                         (IfBatch.Statuses.APPLIED, None, 2, 1))
        self.assertIsNotNone(batch.AppliedAt)

    def test_검증이_틀리면_반영_실패와_사유가_남고_마스터는_그대로다(self):
        batch = plm_batch((1, 'R.A', '1'), (2, 'X.A', '0'))

        with self.assertRaisesMessage(ValueError, 'Qty'):
            apply(batch)

        batch.refresh_from_db()
        self.assertEqual((batch.Status, batch.ApplyResult), (IfBatch.Statuses.APPLY_FAILED, None))
        self.assertIn('Qty', batch.Message)
        self.assertFalse(Product.objects.exists())

    def test_반영_규칙이_없거나_수신에_실패한_건은_반영하지_않는다(self):
        erp = IfBatch.objects.create(Kind=IfBatch.Kinds.ERP_PURCHASE_REQ, SourceRef='e.xlsx', RowCount=0)
        failed = IfBatch.objects.create(Kind=IfBatch.Kinds.PLM_PART_BOM, SourceRef='b.xlsx', RowCount=0,
                                        Status=IfBatch.Statuses.RECEIVE_FAILED)
        # 반영 함수 없이 먼저 받는 종류 — 지금은 없어 등록부를 잠시 바꿔 본다
        no_rule = INTERFACES[IfBatch.Kinds.ERP_PURCHASE_REQ]._replace(apply=None)
        with mock.patch.dict(INTERFACES, {IfBatch.Kinds.ERP_PURCHASE_REQ: no_rule}):
            for batch, word in ((erp, '반영 규칙'), (failed, '수신에 실패')):
                with self.subTest(word):
                    with self.assertRaisesMessage(ValueError, word):
                        apply(batch)
                    batch.refresh_from_db()
                    self.assertNotEqual(batch.Status, IfBatch.Statuses.APPLIED)

