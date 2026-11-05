"""Wezard 업로드 형식 `wezard-dataset/v1` Export.

Wezard 는 이 zip 을 변환 없이 데이터셋 생성에 넘긴다. 최소 조건(train ≥ 10 등)은 만들 때 미리 검사한다.
"""
import io
import json
import tempfile
import zipfile

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from app.views.item.snapshot import _latest_exports
from domain.models.data import ExportJob, ImageAsset, InspectionItem, LabelClass
from domain.services.data.annotation import AnnotationService
from domain.services.data.export import ExportService, registry
from domain.services.data.export.wezard import WezardExporter
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.services.data.version import DatasetVersionService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from tests.test_data_services import make_image

T = InspectionItem.TaskType


class WezardExportTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        self.user = User.objects.create_superuser('wezard-export', password='x')
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)

    def snapshot(self, task_type, annotate, count):
        """count 장(64×48, 서로 다른 색)을 올려 annotate(순번, 라벨 id) 로 주석을 달고 승인 → 스냅샷."""
        with tenant_atomic(self.tenant):
            item = InspectionItem.objects.create(tenant=self.tenant, code='WZ-ITEM', name='Wezard 시험', task_type=task_type)
            label = LabelClass.objects.create(tenant=self.tenant, item=item, name='dent', display_name_ko='찍힘', is_defect=True)
            dataset = ItemService.get_or_create_upload_dataset(item)
            ImageService.upload_images(item, [make_image(f'{i}.png', color=(i, 100, 200)) for i in range(count)], actor=self.user)
            images = sorted(ImageAsset.objects.for_tenant(self.tenant).filter(dataset=dataset), key=lambda image: int(image.original_name.split('.')[0]))
            for index, image in enumerate(images):
                AnnotationService.replace_annotations(image, annotate(index, label.id), actor=self.user)
            ImageAsset.objects.for_tenant(self.tenant).filter(dataset=dataset).update(label_status=ImageAsset.LabelStatus.APPROVED)
            version, _ = DatasetVersionService.create_snapshot(dataset, self.user)
        return version, images

    def wezard_export(self, version):
        with tenant_atomic(self.tenant):
            job = ExportJob.objects.for_tenant(self.tenant).get(dataset_version=version, format=ExportJob.Format.WEZARD)
            ExportService.run(job)
            job.refresh_from_db()
        return job

    def dataset_json(self, job):
        self.assertEqual(job.status, ExportJob.Status.COMPLETED, job.error_message)
        archive = zipfile.ZipFile(io.BytesIO(job.file.read()))
        self.addCleanup(archive.close)
        return archive, json.loads(archive.read('dataset.json'))

    # ---- 등록 ----

    def test_스냅샷을_등록하면_Wezard_형식도_함께_적재하고_화면은_고정_형식만_본다(self):
        version, _ = self.snapshot(T.OBJECT_DETECTION, self.bbox, 1)
        with tenant_atomic(self.tenant):
            formats = sorted(ExportJob.objects.for_tenant(self.tenant).filter(dataset_version=version).values_list('format', flat=True))
            self.assertEqual(formats, ['COCO', 'WEZARD'])
            self.assertEqual(_latest_exports(self.tenant, [version.id])[version.id].format, 'COCO')
            self.assertEqual(_latest_exports(self.tenant, [version.id], wezard=True)[version.id].format, 'WEZARD')

    def test_Wezard_형식은_라벨링하는_모든_유형에서_쓴다(self):
        for task_type in set(T.values) - {T.MEASUREMENT}:
            self.assertIsNotNone(registry.get_exporter_class(task_type, ExportJob.Format.WEZARD))
        # 치수 측정은 라벨링·스냅샷을 하지 않아 Export 형식이 없다(설계 2026-10-20)
        with self.assertRaises(ValueError):
            registry.get_exporter_class(T.MEASUREMENT, ExportJob.Format.WEZARD)

    # ---- 객체 탐지 ----

    def bbox(self, index, label_id):
        if index == 0:  # 오른쪽 끝이 이미지 폭(64px)과 같다 — Wezard 는 x2 ≤ W 를 허용한다
            return [{'geometry_type': 'BBOX', 'label_class_id': label_id, 'x': 34, 'y': 8, 'width': 30, 'height': 16}]
        return [{'geometry_type': 'BBOX', 'label_class_id': label_id, 'x': 10, 'y': 8, 'width': 20, 'height': 16}]

    def test_객체_탐지는_xyxy_박스로_바꾼다(self):
        version, images = self.snapshot(T.OBJECT_DETECTION, self.bbox, 14)
        archive, manifest = self.dataset_json(self.wezard_export(version))
        self.assertEqual((manifest['format'], manifest['task_type'], manifest['classes']),
                         ('wezard-dataset/v1', 'detection', ['dent']))
        items = {item['file']: item for item in manifest['items']}
        first = f'images/{images[0].sha256}.png'
        self.assertEqual(items[first], {'file': first, 'boxes': [{'label': 'dent', 'bbox': [34, 8, 64, 24]}]})
        self.assertEqual(items[f'images/{images[1].sha256}.png']['boxes'][0]['bbox'], [10, 8, 30, 24])
        self.assertTrue(all('split' not in item and 'label' not in item for item in manifest['items']))
        for name in items:
            self.assertIn(name, archive.namelist())
        meta = manifest['meta']
        self.assertEqual((meta['source'], meta['external_ref']), ('maip', f'maip:WZ-ITEM:v1.0#{version.id}'))
        self.assertEqual(meta['maip']['image_ids'][first], images[0].id)
        self.assertEqual(meta['maip']['item']['code'], 'WZ-ITEM')

    def test_학습용이_10장보다_적으면_만들지_않는다(self):
        version, _ = self.snapshot(T.OBJECT_DETECTION, self.bbox, 5)
        job = self.wezard_export(version)
        self.assertEqual(job.status, ExportJob.Status.FAILED)
        self.assertIn('학습용', job.error_message)

    # ---- 이상 탐지: 앞의 2장은 이상(찍힘 Polygon), 나머지는 영역이 없어 정상(DEC-032) ----

    def anomaly(self, index, label_id):
        if index >= 2:
            return []
        return [{'geometry_type': 'POLYGON', 'label_class_id': label_id, 'segmentation': [[10, 10], [40, 10], [40, 30], [10, 30]]}]

    def test_이상_결함이_여러_종류면_anomaly_types_는_combined_다(self):
        def mixed(index, label_id):
            if index != 0:
                return self.anomaly(index, label_id)
            other = LabelClass.objects.create(tenant=self.tenant, item=LabelClass.objects.get(pk=label_id).item,
                                              name='scratch', display_name_ko='긁힘', is_defect=True)
            return self.anomaly(index, label_id) + [
                {'geometry_type': 'POLYGON', 'label_class_id': other.id, 'segmentation': [[1, 1], [8, 1], [8, 8]]}]
        version, images = self.snapshot(T.ANOMALY_DETECTION, mixed, 16)
        _, manifest = self.dataset_json(self.wezard_export(version))
        self.assertEqual(manifest['meta']['maip']['anomaly_types'],
                         {f'images/{images[0].sha256}.png': 'combined', f'images/{images[1].sha256}.png': 'dent'})

    def test_이상_탐지는_good_defect_와_마스크로_바꾼다(self):
        version, images = self.snapshot(T.ANOMALY_DETECTION, self.anomaly, 16)
        archive, manifest = self.dataset_json(self.wezard_export(version))
        self.assertEqual((manifest['task_type'], manifest['classes']), ('anomaly', ['good', 'defect']))
        items = {item['file']: item for item in manifest['items']}
        defect = items[f'images/{images[0].sha256}.png']
        self.assertEqual((defect['label'], defect['mask']), ('defect', f'masks/{images[0].sha256}.png'))
        mask = Image.open(io.BytesIO(archive.read(defect['mask'])))
        self.assertEqual((mask.size, mask.getpixel((25, 20)), mask.getpixel((2, 2))), ((64, 48), 255, 0))
        self.assertEqual(items[f'images/{images[5].sha256}.png'], {'file': f'images/{images[5].sha256}.png', 'label': 'good'})
        self.assertEqual(manifest['meta']['maip']['anomaly_types'], {f'images/{images[0].sha256}.png': 'dent', f'images/{images[1].sha256}.png': 'dent'})

    def test_이상_이미지가_1장이면_검증용이_없어_만들지_않는다(self):
        def one_defect(index, label_id):
            return self.anomaly(index + 1, label_id)
        version, _ = self.snapshot(T.ANOMALY_DETECTION, one_defect, 16)
        job = self.wezard_export(version)
        self.assertEqual(job.status, ExportJob.Status.FAILED)
        self.assertIn('이상', job.error_message)

    # ---- 분류 ----

    def test_분류는_첫_라벨을_label_로_쓴다(self):
        version, images = self.snapshot(T.CLASSIFICATION, lambda index, label_id: [{'geometry_type': 'CLASSIFICATION', 'label_class_id': label_id}], 14)
        _, manifest = self.dataset_json(self.wezard_export(version))
        self.assertEqual((manifest['task_type'], manifest['classes']), ('classification', ['dent']))
        self.assertEqual(manifest['items'][0]['label'], 'dent')


class WezardSplitRuleTest(SimpleTestCase):
    """사전 검사는 Wezard 빌드 판정과 같아야 한다. 예시는 Wezard 가 실제 빌드로 판정해 보내 준 값이다(2026-10-13)."""

    def judge(self, task_type, groups):
        """groups: {Wezard item 라벨 필드(json): 장수} → validate() 오류 목록."""
        exporter = WezardExporter.__new__(WezardExporter)
        exporter.task_type = task_type
        exporter.items = [(None, json.loads(fields), None) for fields, count in groups.items() for _ in range(count)]
        exporter.classes = (sorted({f['label'] for _, f, _ in exporter.items}) if task_type == 'classification'
                            else ['good', 'defect'] if task_type == 'anomaly' else ['dent'])
        return exporter.validate()

    def classification(self, a, b):
        return self.judge('classification', {'{"label": "ng"}': a, '{"label": "ok"}': b})

    def test_분류는_클래스별_train_합이_10장_이상이어야_한다(self):
        self.assertEqual(self.classification(11, 1), [])
        self.assertEqual(self.classification(7, 7), [])
        self.assertIn('9장', self.classification(10, 2)[0])
        self.assertIn('8장', self.classification(6, 6)[0])

    def test_검출은_박스_없는_이미지를_한_그룹으로_나눈다(self):
        box = '{"boxes": [{"label": "dent", "bbox": [0, 0, 1, 1]}]}'
        self.assertEqual(self.judge('detection', {box: 2, '{"boxes": []}': 12}), [])
        self.assertIn('9장', self.judge('detection', {box: 2, '{"boxes": []}': 10})[0])

    def test_검출은_이미지_박스_중_가장_드문_클래스로_나눈다(self):
        """Wezard 2026-10-13 변경 — 1장뿐인 클래스는 train 에 남는다."""
        dent = '{"boxes": [{"label": "dent", "bbox": [0, 0, 1, 1]}]}'
        scratch = '{"boxes": [{"label": "scratch", "bbox": [0, 0, 1, 1]}]}'
        both = '{"boxes": [{"label": "scratch", "bbox": [0, 0, 1, 1]}, {"label": "dent", "bbox": [1, 1, 2, 2]}]}'
        # dent 1·scratch 1·없음 10 → 1장 그룹 둘은 train, 없음 8 → train 10
        self.assertEqual(self.judge('detection', {dent: 1, scratch: 1, '{"boxes": []}': 10}), [])
        # 둘 다 있는 이미지는 드문 dent 그룹(1장, train) → scratch 2(train 1) + 없음 9(train 7) = 9
        self.assertIn('9장', self.judge('detection', {both: 1, scratch: 2, '{"boxes": []}': 9})[0])

    def test_이상_탐지는_val_에_good_과_defect_가_모두_있어야_한다(self):
        self.assertEqual(self.judge('anomaly', {'{"label": "good"}': 12, '{"label": "defect"}': 2}), [])
        self.assertTrue(self.judge('anomaly', {'{"label": "good"}': 12, '{"label": "defect"}': 1}))
