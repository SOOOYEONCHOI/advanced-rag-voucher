"""seed_demo: 데모 검사항목은 냉각팬 패널 3종(분류·이상탐지·객체탐지)이고, 표본(zip 또는 폴더)을 3종 모두에 넣는다(멱등)."""
import io
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from PIL import Image

from domain.management.commands import seed_demo
from domain.management.commands.seed_demo import SAMPLE_COVER, SAMPLE_DEFECT_FILES, SAMPLE_IMAGE_FILES, SAMPLE_OVERLAY
from domain.models.data import Annotation, ImageAsset, InspectionItem
from domain.models.vision import VisionOverlay
from domain.tenancy import reset_tenant_cache, tenant_atomic

T = InspectionItem.TaskType
CODES = {'FAN-PANEL': ('냉각팬 패널 단면(이상탐지)', T.ANOMALY_DETECTION),
         'FAN-PANEL-CLS': ('냉각팬 패널 단면(분류)', T.CLASSIFICATION),
         'FAN-PANEL-DET': ('냉각팬 패널 단면(객체탐지)', T.OBJECT_DETECTION)}


def _png(path, shade):
    Image.new('RGB', (8, 8), (shade, shade, shade)).save(path)


def without_bundled_zip(test):
    """저장소의 표본 zip(37MB)을 읽지 않게 한다. 기본 실행은 zip 이 있으면 이미지까지 넣는다."""
    patcher = mock.patch.object(seed_demo, 'SAMPLE_ZIP', Path('/nonexistent/fan_panel.zip'))
    patcher.start()
    test.addCleanup(patcher.stop)


class SeedDemoItemsTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        without_bundled_zip(self)
        call_command('seed_demo', stdout=io.StringIO())

    def test_기본_실행은_냉각팬_3종만_이미지_없이_만든다(self):
        with tenant_atomic():
            items = {item.code: item for item in InspectionItem.objects.all()}
            self.assertEqual(set(items), set(CODES))
            for code, (name, task_type) in CODES.items():
                self.assertEqual((items[code].name, items[code].task_type), (name, task_type))
            self.assertFalse(ImageAsset.objects.exists())
            self.assertEqual(sorted(items['FAN-PANEL-CLS'].label_classes.values_list('name', 'is_defect')),
                             [('defect', True), ('normal', False)])
            self.assertEqual(sorted(items['FAN-PANEL-DET'].label_classes.values_list('display_name_ko', flat=True)),
                             sorted(['스크래치', '나사 누락', '팬 그릴 변형', '홀 위치 불량']))


class SeedDemoSamplesTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        without_bundled_zip(self)
        call_command('seed_demo', stdout=io.StringIO())
        User.objects.create_superuser('root', password='x')     # 표본 이미지 업로더(seed_initial 의 관리자)
        self.dir = Path(tempfile.mkdtemp())
        _png(self.dir / SAMPLE_COVER, 250)
        Image.new('RGBA', (8, 8), (0, 255, 0, 0)).save(self.dir / SAMPLE_OVERLAY)
        for shade, name in enumerate(SAMPLE_IMAGE_FILES):
            _png(self.dir / name, shade)

    def _seed(self):
        call_command('seed_demo', samples=str(self.dir), stdout=io.StringIO())

    def test_3종_모두에_대표_이미지_Overlay_이미지_20장을_넣는다(self):
        self._seed()
        with tenant_atomic():
            for code in CODES:
                item = InspectionItem.objects.get(code=code)
                self.assertTrue(item.cover_image, code)
                images = ImageAsset.objects.filter(dataset__item=item)
                self.assertEqual(images.count(), 20, code)
                unlabeled = set(images.filter(label_status=ImageAsset.LabelStatus.UNLABELED).values_list('original_name', flat=True))
                self.assertEqual(unlabeled, set(SAMPLE_DEFECT_FILES), code)
                overlay = VisionOverlay.objects.get(item=item)
                self.assertEqual((overlay.version, overlay.opacity, overlay.visible), (1, 1.0, True))
            normal = Annotation.objects.filter(image__dataset__item__code='FAN-PANEL-CLS')
            self.assertEqual(normal.count(), 15)
            self.assertEqual(set(normal.values_list('label_class__name', flat=True)), {'normal'})
            self.assertFalse(Annotation.objects.filter(image__dataset__item__code='FAN-PANEL-DET').exists())

    def test_다시_돌려도_늘지_않는다(self):
        self._seed()
        self._seed()
        with tenant_atomic():
            for code in CODES:
                self.assertEqual(ImageAsset.objects.filter(dataset__item__code=code).count(), 20)
                self.assertEqual(VisionOverlay.objects.get(item__code=code).version, 1)

    def _zip(self):
        path = self.dir / 'samples.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name in [SAMPLE_COVER, SAMPLE_OVERLAY, *SAMPLE_IMAGE_FILES]:
                archive.write(self.dir / name, name)
        return path

    def test_zip_도_받는다(self):
        call_command('seed_demo', samples=str(self._zip()), stdout=io.StringIO())
        with tenant_atomic():
            for code in CODES:
                self.assertEqual(ImageAsset.objects.filter(dataset__item__code=code).count(), 20)

    def test_기본_실행은_표본_zip_이_있으면_이미지까지_넣는다(self):
        with mock.patch.object(seed_demo, 'SAMPLE_ZIP', self._zip()):
            call_command('seed_demo', stdout=io.StringIO())
        with tenant_atomic():
            self.assertEqual(ImageAsset.objects.filter(dataset__item__code='FAN-PANEL-DET').count(), 20)

    def test_관리자_계정이_없으면_멈춘다(self):
        User.objects.filter(is_superuser=True).delete()
        with self.assertRaises(CommandError):
            self._seed()

    def test_계정은_만들지_않는다(self):
        """표본 라벨러·검수자 계정은 뺐다(사용자 결정 2026-10-21) — 사람 계정은 관리자뿐이다."""
        self.assertEqual(list(User.objects.filter(is_active=True).exclude(username='svc-client-001')
                              .values_list('username', flat=True)), ['root'])

    def test_파일이_빠지면_아무것도_넣지_않는다(self):
        (self.dir / SAMPLE_OVERLAY).unlink()
        with self.assertRaises(CommandError):
            self._seed()
        with tenant_atomic():
            self.assertFalse(ImageAsset.objects.exists())
            self.assertFalse(VisionOverlay.objects.exists())
