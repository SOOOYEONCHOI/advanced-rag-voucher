"""sample_inspection: 표본 zip 에서 결함·정상을 나눠 뽑아 `/api/v1/inspections` 로 보내고 검사 기록을 남긴다."""
import io
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from PIL import Image

from domain.management.commands import sample_inspection
from domain.management.commands.seed_demo import SAMPLE_DEFECT_FILES, SAMPLE_IMAGE_FILES
from domain.models.data import InspectionItem, LabelClass
from domain.models.vision import VisionClient, VisionInspection, VisionItemModelMapping, VisionModel
from domain.services.vision.gateway import InferenceResult, WezardError
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic

FIXED_KEY = 'fixed-key-for-test-0000000000000000000000'


class AnomalyGateway:
    """결함 표본만 이상으로 판정한다 — 요청에 파일 이름이 없어 이미지 밝기로 가른다."""

    def infer(self, *, image_bytes, **kwargs):
        shade = Image.open(io.BytesIO(image_bytes)).getpixel((0, 0))[0]
        return InferenceResult(abnormal=shade >= 200, model_name='fan-panel', model_version='3',
                               anomaly_score=float(shade), threshold=200.0, inference_ms=12.0)


class ClassifyGateway:
    def infer(self, *, image_bytes, **kwargs):
        shade = Image.open(io.BytesIO(image_bytes)).getpixel((0, 0))[0]
        return InferenceResult(abnormal=False, model_name='fan-panel-cls', model_version='1', inference_ms=9.0,
                               classification={'label': 'defect' if shade >= 200 else 'normal', 'score': 0.9})


class FailingGateway:
    def infer(self, **kwargs):
        raise WezardError('TIMEOUT', None)


class SampleInspectionTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        zip_path = Path(tempfile.mkdtemp()) / 'fan_panel.zip'
        with zipfile.ZipFile(zip_path, 'w') as archive:
            for index, name in enumerate(SAMPLE_IMAGE_FILES):
                buffer = io.BytesIO()
                shade = 250 if name in SAMPLE_DEFECT_FILES else index
                Image.new('RGB', (8, 8), (shade, shade, shade)).save(buffer, format='PNG')
                archive.writestr(name, buffer.getvalue())
        for target, value in (('SAMPLE_ZIP', zip_path), ('secrets', mock.Mock(token_urlsafe=lambda n: FIXED_KEY))):
            patcher = mock.patch.object(sample_inspection, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with tenant_atomic():
            self.item = InspectionItem.objects.create(tenant=current_tenant(), code='FAN-PANEL', name='팬',
                                                      task_type=InspectionItem.TaskType.ANOMALY_DETECTION)
            model = VisionModel.objects.create(name='fan-panel', version='latest', artifact_path='', runtime='wezard',
                                               inspection_type=VisionModel.InspectionType.ANOMALY)
            VisionItemModelMapping.objects.create(item=self.item, model=model)

    def run_command(self, gateway, **options):
        out = io.StringIO()
        with mock.patch('domain.services.vision.inspection.get_inference_gateway', return_value=gateway):
            call_command('sample_inspection', stdout=out, **options)
        return out.getvalue()

    def inspections(self):
        with tenant_atomic():
            return list(VisionInspection.objects.filter(client__client_id='PIPELINE-TEST'))

    def test_결함과_정상을_나눠_뽑아_검사_기록을_남긴다(self):
        out = self.run_command(AnomalyGateway(), defect=2, normal=3, seed=7)
        rows = [line.split()[0] for line in out.splitlines() if line.split() and line.split()[0] in SAMPLE_IMAGE_FILES]
        self.assertEqual(len([n for n in rows if n in SAMPLE_DEFECT_FILES]), 2, out)
        self.assertEqual(len([n for n in rows if n not in SAMPLE_DEFECT_FILES]), 3, out)
        records = self.inspections()
        self.assertEqual(len(records), 5)
        self.assertTrue(all(r.status == VisionInspection.Status.SUCCESS and r.item_id == self.item.id for r in records))
        self.assertEqual(sorted(r.abnormal for r in records), [False, False, False, True, True])
        self.assertIn('seed=7', out)
        self.assertIn('결함 2장 중 2장', out)
        self.assertIn('정상 3장 중 3장', out)

    def test_같은_seed_는_같은_표본을_뽑는다(self):
        first = self.run_command(AnomalyGateway(), seed=3)
        second = self.run_command(AnomalyGateway(), seed=3)
        names = lambda out: [line.split()[0] for line in out.splitlines() if line.split()[:1] and line.split()[0] in SAMPLE_IMAGE_FILES]
        self.assertEqual(names(first), names(second))
        # 다시 돌려도 시험 클라이언트는 하나다
        self.assertEqual(VisionClient.objects.filter(client_id='PIPELINE-TEST').count(), 1)

    def test_SUCCESS_가_아니면_실패로_끝나고_사유를_보인다(self):
        out = io.StringIO()
        with mock.patch('domain.services.vision.inspection.get_inference_gateway', return_value=FailingGateway()):
            with self.assertRaises(CommandError):
                call_command('sample_inspection', stdout=out)
        self.assertIn('FAILED', out.getvalue())
        self.assertEqual(len(self.inspections()), 4)

    def test_API_Key_는_출력하지_않는다(self):
        out = self.run_command(AnomalyGateway())
        self.assertNotIn(FIXED_KEY, out)

    def test_분류_검사항목은_분류_결과를_찍는다(self):
        with tenant_atomic():
            item = InspectionItem.objects.create(tenant=current_tenant(), code='FAN-PANEL-CLS', name='분류',
                                                 task_type=InspectionItem.TaskType.CLASSIFICATION)
            for name, ko, defect in (('normal', '정상', False), ('defect', '불량', True)):
                LabelClass.objects.create(tenant=current_tenant(), item=item, name=name, display_name_ko=ko, is_defect=defect)
            model = VisionModel.objects.create(name='fan-panel-cls', version='latest', artifact_path='', runtime='wezard',
                                               inspection_type=VisionModel.InspectionType.CLASSIFICATION)
            VisionItemModelMapping.objects.create(item=item, model=model)
        out = self.run_command(ClassifyGateway(), item='FAN-PANEL-CLS', seed=1)
        self.assertIn('분류 불량 0.90', out)
        self.assertIn('분류 정상 0.90', out)
        self.assertIn('결함 2장 중 2장', out)

    def test_없는_검사항목은_거절한다(self):
        with self.assertRaises(CommandError):
            self.run_command(AnomalyGateway(), item='NO-SUCH')
