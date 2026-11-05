"""Overlay 이미지는 쓰지 않게 되면 저장소에서도 지운다.

파일 제공 뷰(`files/vision_overlay`)는 현재 이미지만 내준다. 그런데 교체는 버전마다 새 경로(`v2.png`)에
쓰면서 옛 파일을 그대로 뒀다. Overlay 는 지우지 않고 "표시"를 해제해 숨긴다.
"""
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from PIL import Image

from app.views.vision.overlay import overlay
from domain.models.data import InspectionItem
from domain.models.vision import VisionOverlay
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic


def png():
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8)).save(buffer, format='PNG')
    return SimpleUploadedFile('o.png', buffer.getvalue(), content_type='image/png')


class OverlayFileCleanupTest(TestCase):

    def setUp(self):
        reset_tenant_cache()
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.admin = User.objects.create_superuser('root', password='x')
        with tenant_atomic():
            self.item = InspectionItem.objects.create(tenant=current_tenant(), name='Overlay')

    def _call(self, action, data, files=None):
        request = RequestFactory().post('/api/vision/overlay', data={**data, **(files or {})})
        request.user = self.admin
        # 파일은 커밋 뒤에 지운다. TestCase 는 커밋하지 않으므로 콜백을 직접 돌린다.
        with self.captureOnCommitCallbacks(execute=True):
            return overlay(SimpleNamespace(request=request, gparam={'action': action}, posparam=data))

    def _files(self):
        return sorted(p.name for p in Path(self.media.name).rglob('*') if p.is_file())

    def test_교체하면_옛_이미지를_지운다(self):
        self._call('save', {'item_id': self.item.id}, {'image': png()})
        result = self._call('save', {'item_id': self.item.id}, {'image': png()})

        self.assertTrue(result['success'], result)
        self.assertEqual(self._files(), ['v2.png'])

    def test_저장할_때_표시_여부를_받는다(self):
        """상세 영역의 "표시" 필드. Overlay 는 지우지 않고 표시를 해제해 숨긴다."""
        self._call('save', {'item_id': self.item.id, 'visible': '0'}, {'image': png()})
        self.assertFalse(VisionOverlay.objects.get(item=self.item).visible)
        result = self._call('save', {'item_id': self.item.id, 'visible': '1'})
        self.assertTrue(result['success'], result)
        self.assertTrue(VisionOverlay.objects.get(item=self.item).visible)
        self.assertEqual(VisionOverlay.objects.get(item=self.item).version, 1, '이미지를 안 바꾸면 버전은 그대로다')

    def test_삭제와_표시_전환_기능은_따로_없다(self):
        self._call('save', {'item_id': self.item.id}, {'image': png()})
        for action in ('delete', 'toggle_visible'):
            # 내부 문자열(`action: delete`)을 화면에 보이지 않는다
            self.assertEqual(self._call(action, {'item_id': self.item.id}),
                             {'success': False, 'message': '처리 중 오류가 발생했습니다.'})
        self.assertTrue(VisionOverlay.objects.filter(item=self.item).exists())

    def test_목록의_수정일은_분까지다(self):
        self._call('save', {'item_id': self.item.id}, {'image': png()})
        row = next(r for r in self._call('list', {}) if r['item_id'] == self.item.id)
        self.assertRegex(row['updated_at'], r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')

    def test_관리_화면의_미리보기_주소로_이미지를_받는다(self):
        # 목록이 주는 image_url 을 받을 경로가 없어 미리보기가 늘 비어 있었다.
        from django.test import Client

        self._call('save', {'item_id': self.item.id}, {'image': png()})
        row = next(r for r in self._call('list', {}) if r['item_id'] == self.item.id)

        http = Client()
        self.assertEqual(http.get(row['image_url']).status_code, 404, '로그인 없이 받으면 안 된다')
        http.force_login(self.admin)
        response = http.get(row['image_url'])
        self.assertEqual(response.status_code, 200, row['image_url'])
        self.assertTrue(response['Content-Type'].startswith('image/'))
