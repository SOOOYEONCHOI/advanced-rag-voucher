"""스냅샷 등록 = 그 시점 manifest 고정 + Export 작업 적재."""
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from domain.models.data import BackgroundJob, DatasetVersion, ExportJob, ImageAsset, InspectionItem, LabelClass
from domain.services.data.annotation import AnnotationService
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.services.data.version import NO_APPROVED_MESSAGE, DatasetVersionService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from tests.test_data_services import make_image


class SnapshotJobTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        self.user = User.objects.create_superuser('snap-admin', password='x')
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        with tenant_atomic(self.tenant):
            self.item = InspectionItem.objects.create(tenant=self.tenant, code='SNAP', name='스냅샷',
                                                      task_type=InspectionItem.TaskType.OBJECT_DETECTION)
            self.dataset = ItemService.get_or_create_upload_dataset(self.item)

    def approve_one(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image()], actor=self.user)
            ImageAsset.objects.for_tenant(self.tenant).update(label_status=ImageAsset.LabelStatus.APPROVED)

    def test_등록하면_manifest_를_고정하고_Export_작업을_적재한다(self):
        self.approve_one()
        with tenant_atomic(self.tenant):
            version, export = DatasetVersionService.create_snapshot(self.dataset, self.user, 'COCO')
            self.assertEqual(version.manifest['image_count'], 1)
            self.assertEqual((export.format, export.status), ('COCO', ExportJob.Status.QUEUED))
            self.assertTrue(BackgroundJob.objects.for_tenant(self.tenant)
                            .filter(payload__export_job_id=export.id).exists())

    def test_형식을_비우면_유형의_고정_형식이다(self):
        self.approve_one()
        with tenant_atomic(self.tenant):
            _, export = DatasetVersionService.create_snapshot(self.dataset, self.user)
        self.assertEqual(export.format, 'COCO')

    def test_고정_형식이_아니면_만들지_않는다(self):
        self.approve_one()
        with tenant_atomic(self.tenant), self.assertRaises(ValueError):
            DatasetVersionService.create_snapshot(self.dataset, self.user, 'YOLO')

    def test_승인_이미지가_없으면_만들지_않는다(self):
        with tenant_atomic(self.tenant):
            with self.assertRaisesMessage(ValueError, NO_APPROVED_MESSAGE):
                DatasetVersionService.create_snapshot(self.dataset, self.user)
            self.assertFalse(DatasetVersion.objects.for_tenant(self.tenant).exists())

    def test_같은_내용의_이미지는_먼저_들어온_한_장만_넣는다(self):
        """Client 가 같은 장면을 다시 보내면 중복 이미지가 생긴다(Q4). Export 는 파일 이름을 sha256 으로 지어 겹친다."""
        with tenant_atomic(self.tenant):
            for _ in range(2):
                ImageService.upload_images(self.item, [make_image()], actor=self.user, allow_duplicate=True)
            images = list(ImageAsset.objects.for_tenant(self.tenant).order_by('id'))
            self.assertEqual(len({image.sha256 for image in images}), 1)
            ImageAsset.objects.for_tenant(self.tenant).update(label_status=ImageAsset.LabelStatus.APPROVED)
            version, _ = DatasetVersionService.create_snapshot(self.dataset, self.user)
        self.assertEqual([image['id'] for image in version.manifest['images']], [images[0].id])

    def test_지원하지_않는_형식은_거절한다(self):
        self.approve_one()
        with tenant_atomic(self.tenant), self.assertRaises(ValueError):
            DatasetVersionService.create_snapshot(self.dataset, self.user, 'MVTEC')

    def test_품질_점검_작업_유형은_없다(self):
        self.assertNotIn('QUALITY', BackgroundJob.JobType.values)

    def test_직전_스냅샷과_데이터가_같으면_만들지_않는다(self):
        self.approve_one()
        with tenant_atomic(self.tenant):
            first, _ = DatasetVersionService.create_snapshot(self.dataset, self.user)
            with self.assertRaisesMessage(ValueError, '직전 스냅샷 v1.0 과 데이터가 같아'):
                DatasetVersionService.create_snapshot(self.dataset, self.user)
            self.assertEqual(DatasetVersion.objects.for_tenant(self.tenant).count(), 1)

    def test_승인_이미지가_늘면_새로_만든다(self):
        self.approve_one()
        with tenant_atomic(self.tenant):
            DatasetVersionService.create_snapshot(self.dataset, self.user)
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('b.png', color=(1, 2, 3))], actor=self.user)
            ImageAsset.objects.for_tenant(self.tenant).update(label_status=ImageAsset.LabelStatus.APPROVED)
            version, _ = DatasetVersionService.create_snapshot(self.dataset, self.user)
        self.assertEqual((version.version_tag, version.manifest['image_count']), ('v2.0', 2))

    def test_이미지_수가_같아도_주석이_바뀌면_새로_만든다(self):
        self.approve_one()
        with tenant_atomic(self.tenant):
            DatasetVersionService.create_snapshot(self.dataset, self.user)
            image = ImageAsset.objects.for_tenant(self.tenant).get()
            label = LabelClass.objects.create(tenant=self.tenant, item=self.item, name='dent', is_defect=True)
            AnnotationService.replace_annotations(image, [{'geometry_type': 'BBOX', 'label_class_id': label.id,
                                                           'x': 1, 'y': 1, 'width': 10, 'height': 10}], actor=self.user)
            version, _ = DatasetVersionService.create_snapshot(self.dataset, self.user)
        self.assertEqual((version.version_tag, version.manifest['image_count']), ('v2.0', 1))
