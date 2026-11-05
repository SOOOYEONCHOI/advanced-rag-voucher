"""Export 형식 8종의 zip 내용 — 이미지가 원본 형식의 확장자로 들어가고 라벨 파일이 그 이름을 가리킨다.

Client 가 보내는 이미지는 JPEG 다. 확장자와 내용이 다르면 학습 도구가 읽다 실패한다.
"""
import io
import json
import tempfile
import zipfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from domain.models.data import ExportJob, ImageAsset, InspectionItem, LabelClass
from domain.services.data.annotation import AnnotationService
from domain.services.data.export import ExportService
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.services.data.version import DatasetVersionService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic

JPEG, PNG = b'\xff\xd8', b'\x89PNG'


def upload(name, image_format, content_type):
    buffer = io.BytesIO()
    Image.new('RGB', (64, 48), (120, 120, 120)).save(buffer, format=image_format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


class ExportFormatTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        self.user = User.objects.create_superuser('export-admin', password='x')
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)

    def export_zip(self, task_type, export_format, annotate):
        """JPEG·PNG 한 장씩 올려 annotate(이미지, 라벨) 로 주석을 달고 승인 → 스냅샷 → Export."""
        with tenant_atomic(self.tenant):
            item = InspectionItem.objects.create(tenant=self.tenant, code=f'EXP-{export_format}', name=export_format, task_type=task_type)
            label = LabelClass.objects.create(tenant=self.tenant, item=item, name='dent', display_name_ko='찍힘')
            dataset = ItemService.get_or_create_upload_dataset(item)
            ImageService.upload_images(item, [upload('a.jpg', 'JPEG', 'image/jpeg'), upload('b.png', 'PNG', 'image/png')], actor=self.user)
            images = {image.original_name: image for image in ImageAsset.objects.for_tenant(self.tenant).filter(dataset=dataset)}
            for name, image in images.items():
                AnnotationService.replace_annotations(image, annotate(name, label.id), actor=self.user)
            ImageAsset.objects.for_tenant(self.tenant).filter(dataset=dataset).update(label_status=ImageAsset.LabelStatus.APPROVED)
            _, export = DatasetVersionService.create_snapshot(dataset, self.user, export_format)
            ExportService.run(export)
            export.refresh_from_db()
            self.assertEqual(export.status, ExportJob.Status.COMPLETED, export.error_message)
            archive = zipfile.ZipFile(io.BytesIO(export.file.read()))
            self.addCleanup(archive.close)
            return archive, {name: image.sha256 for name, image in images.items()}

    def assert_images(self, archive, expected):
        """expected: zip 안 이미지 이름 → 첫 바이트(JPEG·PNG)."""
        for name, magic in expected.items():
            self.assertIn(name, archive.namelist())
            self.assertEqual(archive.read(name)[:len(magic)], magic, name)

    def test_검사_유형마다_Export_형식은_하나로_고정이다(self):
        from domain.services.data.export import registry
        self.assertEqual(registry.ITEM_EXPORT_FORMAT, {
            InspectionItem.TaskType.CLASSIFICATION: ExportJob.Format.IMAGEFOLDER,
            InspectionItem.TaskType.OBJECT_DETECTION: ExportJob.Format.COCO,
            InspectionItem.TaskType.ANOMALY_DETECTION: ExportJob.Format.MVTEC,
        })

    # ---- 객체 검출 ----

    def bbox(self, name, label_id):
        return [{'geometry_type': 'BBOX', 'label_class_id': label_id, 'x': 10, 'y': 8, 'width': 20, 'height': 16}]

    def test_Export_는_zip_을_메모리에_모으지_않는다(self):
        # BytesIO 에 zip 전체를 만든 뒤 getvalue() 로 또 복사해 zip 크기의 2배를 메모리에 올렸다.
        from unittest.mock import patch
        with patch('domain.services.data.export.zipfile.ZipFile', wraps=zipfile.ZipFile) as opened:
            self.export_zip(InspectionItem.TaskType.OBJECT_DETECTION, 'COCO', self.bbox)
        targets = [call.args[0] for call in opened.call_args_list if len(call.args) > 1 and call.args[1] == 'w']
        self.assertTrue(targets)
        self.assertFalse([t for t in targets if isinstance(t, io.BytesIO)], targets)

    def test_COCO(self):
        archive, sha = self.export_zip(InspectionItem.TaskType.OBJECT_DETECTION, 'COCO', self.bbox)
        self.assert_images(archive, {f"images/{sha['a.jpg']}.jpg": JPEG, f"images/{sha['b.png']}.png": PNG})
        instances = json.loads(archive.read('annotations/instances.json'))
        self.assertEqual(sorted(i['file_name'] for i in instances['images']), sorted([f"{sha['a.jpg']}.jpg", f"{sha['b.png']}.png"]))
        self.assertEqual(len(instances['annotations']), 2)

    # ---- 분류 ----

    def classify(self, name, label_id):
        return [{'geometry_type': 'CLASSIFICATION', 'label_class_id': label_id}]

    def test_IMAGEFOLDER(self):
        archive, sha = self.export_zip(InspectionItem.TaskType.CLASSIFICATION, 'IMAGEFOLDER', self.classify)
        self.assert_images(archive, {f"dent/{sha['a.jpg']}.jpg": JPEG, f"dent/{sha['b.png']}.png": PNG})

    # ---- 이상 탐지: JPEG 는 이상(찍힘 Polygon), PNG 는 영역이 없어 정상(DEC-032) ----

    def anomaly(self, name, label_id):
        if name == 'b.png':
            return []
        return [{'geometry_type': 'POLYGON', 'label_class_id': label_id, 'segmentation': [[10, 10], [40, 10], [40, 30], [10, 30]]}]

    def assert_mask(self, archive, name):
        mask = Image.open(io.BytesIO(archive.read(name)))
        self.assertEqual(mask.format, 'PNG')
        self.assertEqual(mask.getpixel((25, 20)), 255)
        self.assertEqual(mask.getpixel((2, 2)), 0)


    def test_MVTEC_은_폴더_구조에_metadata_json_을_더한다(self):
        archive, sha = self.export_zip(InspectionItem.TaskType.ANOMALY_DETECTION, 'MVTEC', self.anomaly)
        self.assert_images(archive, {f"test/dent/{sha['a.jpg']}.jpg": JPEG, f"train/good/{sha['b.png']}.png": PNG})
        self.assert_mask(archive, f"ground_truth/dent/{sha['a.jpg']}_mask.png")
        entries = {e['image_id']: e for e in json.loads(archive.read('metadata.json'))['images']}
        for entry in entries.values():
            self.assertIn(entry['file_name'], archive.namelist())
            if entry['mask_available']:
                self.assert_mask(archive, entry['mask_file'])
        self.assertEqual(sum(e['mask_available'] for e in entries.values()), 1)

    def test_MVTEC_은_결함이_여러_종류면_combined_다(self):
        def mixed(name, label_id):
            if name == 'b.png':
                return []
            other = LabelClass.objects.create(tenant=self.tenant, item=LabelClass.objects.get(pk=label_id).item,
                                              name='scratch', display_name_ko='긁힘')
            return [{'geometry_type': 'POLYGON', 'label_class_id': label_id, 'segmentation': [[10, 10], [40, 10], [40, 30], [10, 30]]},
                    {'geometry_type': 'POLYGON', 'label_class_id': other.id, 'segmentation': [[1, 1], [8, 1], [8, 8]]}]
        archive, sha = self.export_zip(InspectionItem.TaskType.ANOMALY_DETECTION, 'MVTEC', mixed)
        self.assert_images(archive, {f"test/combined/{sha['a.jpg']}.jpg": JPEG, f"train/good/{sha['b.png']}.png": PNG})
