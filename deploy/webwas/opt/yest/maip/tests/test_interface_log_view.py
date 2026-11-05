"""인터페이스 이력 API(`/api/definition/interface_log`) — 조회 전용.

수신건 목록(종류·경로·상태·수신일·출처 검색, 서버 페이징)과 상세(마지막 반영 결과·실패 사유), 원본 행(서버 페이징)을 준다.
원본 행의 열은 종류 등록부에서 받는다 — 종류가 늘어도 화면을 고치지 않는다.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from app.views.definition.interface_log import interface_log
from domain.gui import GUIConfiguration
from domain.models.interface import IfBatch
from domain.services.interface import INTERFACES, apply, receive


def call(**gparam):
    return interface_log(SimpleNamespace(request=None, gparam=gparam, posparam={}))


def plm_row(depth, code):
    part_no, rev = code.split('.')
    return dict(Depth=str(depth), PartErp=code, PartNo=part_no, PartVer=rev + '.1', PartName='NAME ' + part_no, Qty='1')


class InterfaceLogViewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.plm = receive(IfBatch.Kinds.PLM_PART_BOM, [plm_row(1, 'R.A'), plm_row(2, 'X.A')], IfBatch.Channels.FILE, 'bom.xlsx')
        apply(cls.plm)
        cls.erp = receive(IfBatch.Kinds.ERP_PURCHASE_REQ, [{'ReqNo': 'PRQ1', 'ReqSeq': '1'}], IfBatch.Channels.FILE, 'prq.xlsx')
        cls.failed = IfBatch.objects.create(Kind=IfBatch.Kinds.PLM_PART_BOM, SourceRef='broken.xlsx', RowCount=0,
                                            Status=IfBatch.Statuses.RECEIVE_FAILED, Message='머리글이 다릅니다.')

    def test_목록은_최신순이고_조건으로_거른다(self):
        self.assertEqual([r['source_ref'] for r in call(action='list')['rows']], ['broken.xlsx', 'prq.xlsx', 'bom.xlsx'])
        self.assertEqual([r['id'] for r in call(action='list', kind='PLM_PART_BOM')['rows']], [self.failed.id, self.plm.id])
        self.assertEqual([r['id'] for r in call(action='list', status='APPLIED')['rows']], [self.plm.id])
        self.assertEqual([r['id'] for r in call(action='list', source='prq')['rows']], [self.erp.id])
        self.assertEqual(call(action='list', channel='API')['totalRows'], 0)
        self.assertEqual(call(action='list', date_from='2000-01-01', date_to='2000-01-02')['totalRows'], 0)
        page = call(action='list', page='2', page_size='2')
        self.assertEqual((page['totalRows'], [r['id'] for r in page['rows']]), (3, [self.plm.id]))

    def test_목록_행은_화면_이름으로_준다(self):
        rows = {r['id']: r for r in call(action='list')['rows']}
        self.assertEqual((rows[self.plm.id]['kind_label'], rows[self.plm.id]['channel_label'],
                          rows[self.plm.id]['status_label'], rows[self.plm.id]['receiver']),
                         ('PLM 품목·BOM', '파일', '반영 완료', '명령'))
        self.assertEqual(rows[self.erp.id]['status_label'], '반영 대기')
        self.assertTrue(rows[self.plm.id]['applied_at'])
        # 반영 함수 없이 먼저 받는 종류의 반영 대기는 "반영 규칙 없음"이다 — 지금은 없어 등록부를 잠시 바꿔 본다
        no_rule = INTERFACES[IfBatch.Kinds.ERP_PURCHASE_REQ]._replace(apply=None)
        with mock.patch.dict(INTERFACES, {IfBatch.Kinds.ERP_PURCHASE_REQ: no_rule}):
            rows = {r['id']: r for r in call(action='list')['rows']}
        self.assertEqual(rows[self.erp.id]['status_label'], '반영 규칙 없음')

    def test_검색_선택지는_종류_경로_상태다(self):
        filters = call(action='filters')
        self.assertIn({'value': 'PLM_PART_BOM', 'label': 'PLM 품목·BOM'}, filters['kinds'])
        self.assertEqual([c['value'] for c in filters['channels']], ['FILE', 'API', 'DB'])
        self.assertEqual(len(filters['statuses']), 4)

    def test_상세는_반영_건수와_원본_열을_준다(self):
        detail = call(action='detail', id=str(self.plm.id))
        self.assertIn(['품목 추가', 2], detail['result'])
        self.assertEqual(detail['columns'][4], {'field': 'PartErp', 'header': 'Part(ERP)'})
        self.assertEqual(len(detail['columns']), 39)
        failed = call(action='detail', id=str(self.failed.id))
        self.assertEqual((failed['status_label'], failed['message'], failed['result']), ('수신 실패', '머리글이 다릅니다.', []))

    def test_원본_행은_파일_순서대로_서버_페이징한다(self):
        rows = call(action='rows', batch_id=str(self.plm.id), page_size='1', page='2')
        self.assertEqual((rows['totalRows'], rows['rows'][0]['RowNo'], rows['rows'][0]['PartErp']), (2, 2, 'X.A'))

    def test_이력_API_는_인터페이스_이력_메뉴_권한으로_연다(self):
        self.assertEqual(GUIConfiguration.get_menu_code_by_taskview('definition', 'interface_log'), ['wm_interface_log'])
        self.assertEqual(GUIConfiguration.get_gui_info('wm_interface_log')['templates']['default'], 'definition/interface_log.html')
