"""비전검사 클라이언트 — 상세 영역의 "사용" 필드와 [삭제].

삭제는 검사 기록이 없을 때만 된다(검사 기록은 클라이언트를 PROTECT 로 가리킨다).
지울 때 서비스 계정(`svc-<id>`, 업로더 기록용)도 함께 지운다.
"""
import uuid
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import TestCase

from app.views.vision.client import client
from domain.models.data import InspectionItem
from domain.models.vision import VisionClient, VisionInspection
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic


def call(action, **posparam):
    return client(SimpleNamespace(gparam={'action': action}, posparam=posparam))


class VisionClientTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.created = call('save', client_id='CL-1', name='현장 1')
        self.row = VisionClient.objects.get(client_id='CL-1')

    def test_등록할_때_사용_여부를_받는다(self):
        call('save', client_id='CL-2', name='현장 2', active='0')
        self.assertFalse(VisionClient.objects.get(client_id='CL-2').active)

    def test_수정할_때_이름과_사용_여부를_바꾼다(self):
        result = call('save', id=self.row.id, client_id='CL-1', name='바뀐 이름', active='0')
        self.assertTrue(result['success'], result)
        self.row.refresh_from_db()
        self.assertEqual((self.row.name, self.row.active), ('바뀐 이름', False))

    def test_검사_기록이_없으면_서비스_계정과_함께_지운다(self):
        result = call('delete', id=self.row.id)
        self.assertTrue(result['success'], result)
        self.assertFalse(VisionClient.objects.filter(client_id='CL-1').exists())
        self.assertFalse(User.objects.filter(username='svc-cl-1').exists())

    def test_검사_기록이_있으면_지우지_않는다(self):
        with tenant_atomic():
            item = InspectionItem.objects.create(tenant=current_tenant(), name='검사')
            key = str(uuid.uuid4())
            VisionInspection.objects.create(id=key, request_id=key, client=self.row, item=item)
        result = call('delete', id=self.row.id)
        self.assertEqual(result, {'success': False,
                                  'message': '검사 기록이 있어 삭제할 수 없습니다. 사용을 해제해 주세요.'})
        self.assertTrue(VisionClient.objects.filter(client_id='CL-1').exists())
        self.assertTrue(User.objects.filter(username='svc-cl-1').exists())


class VisionClientDetailTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.key = call('save', client_id='CL-D', name='상세')['api_key']
        self.row = VisionClient.objects.get(client_id='CL-D')

    def test_상세는_키_해시를_내주지_않는다(self):
        detail = client(SimpleNamespace(gparam={'action': 'detail', 'id': self.row.id}, posparam={}))
        self.assertEqual(detail, {'id': self.row.id, 'client_id': 'CL-D', 'name': '상세', 'active': True})

    def test_재발급하면_새_키만_통하고_원문은_응답에만_있다(self):
        import hashlib
        result = call('reissue_key', id=self.row.id)
        self.assertTrue(result['success'], result)
        self.assertNotEqual(result['api_key'], self.key)
        self.row.refresh_from_db()
        self.assertEqual(self.row.api_key_hash, hashlib.sha256(result['api_key'].encode()).hexdigest())

    def test_없는_클라이언트는_상세_재발급_모두_실패한다(self):
        detail = client(SimpleNamespace(gparam={'action': 'detail', 'id': 0}, posparam={}))
        self.assertFalse(detail['success'])
        self.assertFalse(call('reissue_key', id=0)['success'])


class VisionClientScreenTextTest(TestCase):
    """목록 날짜 형식과 예상하지 못한 오류 문구(화면 표시)."""

    def setUp(self):
        reset_tenant_cache()
        call('save', client_id='CL-T', name='표시')

    def test_등록일은_분까지_최근_접속은_초까지다(self):
        from django.utils import timezone
        VisionClient.objects.filter(client_id='CL-T').update(last_seen_at=timezone.now())
        [row] = [r for r in call('list') if r['client_id'] == 'CL-T']
        self.assertRegex(row['created_at'], r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')
        self.assertRegex(row['last_seen_at'], r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')

    def test_예상하지_못한_오류는_내부_문자열_대신_고정_문구로_알린다(self):
        self.assertEqual(call('no-such-action'), {'success': False, 'message': '처리 중 오류가 발생했습니다.'})
