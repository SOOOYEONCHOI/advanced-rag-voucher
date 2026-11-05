"""검사 결과 화면은 자기 메뉴 권한만으로 필터 목록을 받는다.

검사항목·클라이언트 콤보를 모델 매핑(`wm_vis_model_mapping`)과 클라이언트
(`wm_vis_client`) API 에서 받아, 그 메뉴 권한이 없는 그룹은 403 이 났다.
"""
import uuid
from datetime import date, datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from domain.models.data import InspectionItem, LabelClass
from domain.models.system import SystemOption
from domain.models.user import UserGroup, UserGroupMenu
from domain.models.vision import VisionClient, VisionInspection
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic

PASSWORD = 'correct-horse-battery-staple'


@override_settings(API_AUTHZ_MODE='enforce')
class InspectionFiltersTest(TestCase):
    def setUp(self):
        cache.clear()
        reset_tenant_cache()
        SystemOption.objects.create(Code='LOGO_TITLE', Value='테스트')
        group = UserGroup.objects.create(Code='viewer', Name='조회')
        UserGroupMenu.objects.create(UserGroup=group, MenuCode='wm_vis_inspection', AuthCode='R')
        user = User.objects.create_user('viewer1', password=PASSWORD)
        user.userprofile.UserGroup = group
        user.userprofile.save()
        with tenant_atomic():
            self.item = InspectionItem.objects.create(tenant=current_tenant(), code='SCR', name='스크래치')
            VisionClient.objects.create(client_id='CLIENT-9', name='현장', api_key_hash='x' * 64)
        self.http = Client()
        self.http.login(username='viewer1', password=PASSWORD)

    def test_검사_결과_메뉴_권한만으로_필터_목록을_받는다(self):
        response = self.http.get('/api/vision/inspection?action=filters',
                                 HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn({'id': self.item.id, 'code': 'SCR', 'name': '스크래치'}, body['items'])
        self.assertEqual([c['client_id'] for c in body['clients']], ['CLIENT-9'])
        # 콤보에 필요한 것만 준다. API Key 해시 같은 값은 나가지 않는다.
        self.assertEqual(set(body['clients'][0]), {'id', 'client_id'})


class InspectionListPagingTest(InspectionFiltersTest):
    """검사 목록은 서버 페이징이다. 날짜를 비우면 최근 7일, 날짜 조건은 하루 끝까지 넣는다."""

    def make(self, count, created_at):
        with tenant_atomic():
            client = VisionClient.objects.get(client_id='CLIENT-9')
            ids = []
            for _ in range(count):
                key = str(uuid.uuid4())
                VisionInspection.objects.create(id=key, request_id=key, client=client, item=self.item)
                ids.append(key)
            # created_at 은 auto_now_add 라 만든 뒤 바꾼다.
            VisionInspection.objects.filter(id__in=ids).update(created_at=created_at)

    def get(self, **params):
        response = self.http.get('/api/vision/inspection', dict(action='list', **params),
                                 HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_요청한_페이지만_주고_전체_건수를_함께_준다(self):
        self.make(25, datetime.now())
        body = self.get(page=2, page_size=20)
        self.assertEqual(body['totalRows'], 25)
        self.assertEqual(len(body['rows']), 5)

    def test_500건에서_자르지_않는다(self):
        self.make(501, datetime.now())
        self.assertEqual(self.get(page=6, page_size=100)['totalRows'], 501)

    def test_날짜를_비우면_오늘을_포함한_최근_7일만_준다(self):
        # 화면의 기본 기간(6일 전 ~ 오늘)과 요약 카드의 "최근 7일"과 같다.
        today = datetime.combine(date.today(), time())
        self.make(1, today - timedelta(days=6))
        self.make(1, today - timedelta(days=7))
        self.assertEqual(self.get()['totalRows'], 1)

    def test_끝_날짜는_그날_23시_59분까지_넣는다(self):
        self.make(1, datetime(2026, 3, 2, 23, 59, 59))
        self.make(1, datetime(2026, 3, 3, 0, 0, 0))
        self.make(1, datetime(2026, 2, 28, 23, 59, 59))
        self.assertEqual(self.get(date_from='2026-03-01', date_to='2026-03-02')['totalRows'], 1)


class InspectionDetailDashboardTest(TestCase):
    """검사 결과 상세와 최근 기간 요약(대시보드 카드)."""

    def setUp(self):
        reset_tenant_cache()
        with tenant_atomic():
            self.item = InspectionItem.objects.create(tenant=current_tenant(), code='DSH', name='요약')
            self.client_row = VisionClient.objects.create(client_id='CLIENT-D', name='현장', api_key_hash='x' * 64)

    def make(self, created_at=None, **fields):
        key = str(uuid.uuid4())
        with tenant_atomic():
            VisionInspection.objects.create(id=key, request_id=key, client=self.client_row, item=self.item, **fields)
            if created_at:
                VisionInspection.objects.filter(pk=key).update(created_at=created_at)
        return key

    def call(self, **gparam):
        from types import SimpleNamespace
        from app.views.vision.inspection import inspection
        return inspection(SimpleNamespace(gparam=gparam, posparam={}))

    def test_상세는_판정과_모델_분류_결과를_준다(self):
        key = self.make(status='SUCCESS', abnormal=True, model_name='fan-panel-cls', model_version='2',
                        classification={'label': 'defect', 'name': '불량', 'score': 0.912}, client_version='0.1.6')
        detail = self.call(action='detail', id=key)
        self.assertEqual((detail['status_label'], detail['model'], detail['abnormal'], detail['classification']),
                         ('판정 완료', 'fan-panel-cls v2', True, '불량 (0.91)'))
        self.assertEqual((detail['request_id'], detail['client_version'], detail['error_message']), (key, '0.1.6', ''))

    def test_검출_결함은_라벨_클래스_표시_이름과_신뢰도로_준다(self):
        with tenant_atomic():
            LabelClass.objects.create(tenant=current_tenant(), item=self.item, name='scratch', display_name_ko='스크래치')
        box = {'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1}
        key = self.make(status='SUCCESS', abnormal=True, defects=[
            {'class_name': 'scratch', 'confidence': 0.912, 'bbox': box},
            {'class_name': 'unknown_dent', 'confidence': 0.5, 'bbox': box}])
        self.assertEqual(self.call(action='detail', id=key)['detected'], '스크래치 (0.91), unknown_dent (0.50)')
        self.assertEqual(self.call(action='detail', id=self.make(status='SUCCESS', abnormal=False))['detected'], '')

    def test_치수_측정은_측정점마다_값_범위_합불을_준다(self):
        key = self.make(status='SUCCESS', abnormal=True, measurements=[
            {'code': 'A', 'name': '치수 A', 'value': 540.32, 'lower': 539.0, 'upper': 541.0, 'unit': 'mm', 'ok': True},
            {'code': 'C', 'name': '치수 C', 'value': 155.5, 'lower': 153.0, 'upper': 155.0, 'unit': 'mm', 'ok': False}])
        self.assertEqual(self.call(action='detail', id=key)['measured'], [
            {'label': '치수 A (A)', 'text': '540.32 mm (539~541) 합격', 'ok': True},
            {'label': '치수 C (C)', 'text': '155.5 mm (153~155) 불합격', 'ok': False}])
        self.assertEqual(self.call(action='detail', id=self.make(status='RECEIVED'))['measured'], [])

    def test_판정_문구는_상태_분류_이상_정상_순서로_정한다(self):
        # 디지털 양식 이미지 칸의 거치대 결과 표시도 같은 문구를 쓴다(설계 2026-10-21 §7)
        from domain.services.vision.inspection import judgement_text
        cases = [(dict(status='RECEIVED'), '접수됨'), (dict(status='FAILED'), '실패'),
                 (dict(status='SUCCESS', abnormal=True, classification={'label': 's3', 'name': '3단계', 'score': 0.876}), '3단계 (0.88)'),
                 (dict(status='SUCCESS', abnormal=True), '이상'), (dict(status='SUCCESS', abnormal=False), '정상'),
                 (dict(status='SUCCESS'), '-')]
        for fields, text in cases:
            with tenant_atomic():
                row = VisionInspection.objects.get(pk=self.make(**fields))
            self.assertEqual(judgement_text(row), text, fields)

    def test_처리하지_못한_요청은_예외_원문_대신_고정_문구를_준다(self):
        self.assertEqual(self.call(action='nope'), {'success': False, 'message': '검사 정보를 불러오지 못했습니다.'})

    def test_요약_기간은_오늘을_포함한_날짜_단위다(self):
        today = datetime.combine(date.today(), time())
        self.make(status='SUCCESS', created_at=today - timedelta(days=6))
        self.make(status='SUCCESS', created_at=today - timedelta(days=7) + timedelta(hours=23, minutes=59))
        self.assertEqual(self.call(action='dashboard', days='7')['totals']['total'], 1)

    def test_없는_검사는_찾을_수_없다고_한다(self):
        self.assertEqual(self.call(action='detail', id='nope'), {'success': False, 'message': '검사를 찾을 수 없습니다.'})

    def test_요약은_기간_안의_상태별_건수와_이상률을_센다(self):
        self.make(status='SUCCESS', abnormal=True)
        self.make(status='SUCCESS', abnormal=False)
        self.make(status='RECEIVED', error_message='GPU_INFERENCE_NOT_CONFIGURED')
        self.make(status='FAILED', error_message='WezardError: TIMEOUT')
        self.make(status='SUCCESS', abnormal=True, created_at=datetime.now() - timedelta(days=30))   # 기간 밖
        summary = self.call(action='dashboard', days='7')
        totals = summary['totals']
        self.assertEqual((totals['total'], totals['success'], totals['received'], totals['failed']), (4, 2, 1, 1))
        self.assertEqual((totals['abnormal'], totals['abnormal_rate'], totals['inference_skipped']), (1, 50.0, 1))
        self.assertEqual(summary['by_item'], [{'item__code': 'DSH', 'item__name': '요약', 'count': 4}])
        self.assertEqual([c['client_id'] for c in summary['clients']], ['CLIENT-D'])
