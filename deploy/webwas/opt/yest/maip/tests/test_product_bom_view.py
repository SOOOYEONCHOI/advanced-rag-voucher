"""품목·BOM 조회 API(`/api/definition/product_bom`) — 조회 전용.

트리 행의 id 는 품목 id 가 아니라 위치 경로다 — 같은 하위 조립품이 두 곳에 나온다.
소요량은 위쪽 수량을 모두 곱한 값이다.
"""
import datetime
from types import SimpleNamespace

from django.test import TestCase

from app.views.definition.product_bom import product_bom
from domain.gui import GUIConfiguration
from domain.models.basic import Bom, Product


def call(**gparam):
    return product_bom(SimpleNamespace(request=None, gparam=gparam, posparam={}))


class ProductBomViewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        p = {code: Product.objects.create(Code=code, PartNo=code.split('.')[0], Revision='A', Name='NAME ' + code,
                                          PartType=kind, PlmCreatedDate=datetime.date(2026, 1, 2))
             for code, kind in (('R.A', 'FSC'), ('A.A', '기구'), ('C.A', '기구'), ('X.A', '구매품'), ('L.A', '구매품'))}
        # R ─ A(2) ─ X(3)
        #   └ C(1) ─ A(1) ─ X(3)      A 는 두 곳에 쓰인다. L 은 어디에도 없다
        for parent, child, qty, seq in (('R.A', 'A.A', 2, 1), ('R.A', 'C.A', 1, 2), ('C.A', 'A.A', 1, 1), ('A.A', 'X.A', 3, 1)):
            Bom.objects.create(Parent=p[parent], Child=p[child], Qty=qty, Seq=seq)
        cls.p = p

    def test_목록은_검색_조건과_서버_페이징을_따른다(self):
        self.assertEqual([r['code'] for r in call(action='list', root_only='Y')['rows']], ['R.A'])
        self.assertEqual([r['code'] for r in call(action='list', keyword='name x')['rows']], ['X.A'])
        self.assertEqual([r['code'] for r in call(action='list', part_type='구매품')['rows']], ['L.A', 'X.A'])
        page = call(action='list', page='2', page_size='2')
        self.assertEqual((page['totalRows'], [r['code'] for r in page['rows']]), (5, ['L.A', 'R.A']))

    def test_유형_선택지는_DB_에_있는_값이다(self):
        self.assertEqual(call(action='part_types'), ['FSC', '구매품', '기구'])

    def test_상세는_품목_한_건이다(self):
        row = call(action='detail', id=str(self.p['X.A'].id))
        self.assertEqual((row['code'], row['part_type'], row['plm_created_date']), ('X.A', '구매품', '2026-01-02'))

    def test_하위_BOM_은_위치_경로_id_와_소요량으로_펼친다(self):
        rows = call(action='tree', id=str(self.p['R.A'].id))

        self.assertEqual([(r['code'], r['qty'], r['total_qty']) for r in rows],
                         [('R.A', '', ''), ('A.A', '2', '2'), ('X.A', '3', '6'),
                          ('C.A', '1', '1'), ('A.A', '1', '1'), ('X.A', '3', '3')])
        ids = [r['tree_id'] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        by_id = {r['tree_id']: r for r in rows}
        self.assertEqual([by_id[r['tree_pid']]['code'] if r['tree_pid'] else None for r in rows],
                         [None, 'R.A', 'A.A', 'R.A', 'C.A', 'A.A'])

    def test_사용처는_최상위까지_거슬러_올라간다(self):
        rows = call(action='where_used', id=str(self.p['X.A'].id))

        self.assertEqual([(r['code'], r['qty']) for r in rows],
                         [('X.A', ''), ('A.A', '3'), ('C.A', '1'), ('R.A', '1'), ('R.A', '2')])

    def test_조회_API_는_품목_BOM_메뉴_권한으로_연다(self):
        self.assertEqual(GUIConfiguration.get_menu_code_by_taskview('definition', 'product_bom'), ['wm_product_bom'])
        self.assertEqual(GUIConfiguration.get_gui_info('wm_product_bom')['templates']['default'], 'definition/product_bom.html')
