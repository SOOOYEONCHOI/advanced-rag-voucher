"""작업 큐(JobService) — 워커가 죽거나 작업이 실패했을 때의 상태."""
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from domain.models.data import (BackgroundJob, DatasetVersion, ExportJob, ImageAsset, InspectionItem,
                                LabelClass)
from domain.services.data.audit import AuditService
from domain.services.data.export import ExportService
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.services.data.job import JobService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from tests.test_data_services import make_image


@override_settings(WORKER_STALE_SECONDS=60)
class JobRecoveryTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        self.user = User.objects.create_user('job-user', password='x')
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        with tenant_atomic(self.tenant):
            item = InspectionItem.objects.create(tenant=self.tenant, code='JOB', name='작업',
                                                 task_type=InspectionItem.TaskType.OBJECT_DETECTION)
            # COCO 는 결함 라벨 클래스가 없으면 zip 을 만들지 않고 실패한다.
            LabelClass.objects.create(tenant=self.tenant, item=item, name='scratch', display_name_ko='스크래치')
            ImageService.upload_images(item, [make_image()], actor=self.user)
            ImageAsset.objects.for_tenant(self.tenant).update(label_status=ImageAsset.LabelStatus.APPROVED)
            image = ImageAsset.objects.for_tenant(self.tenant).get()
            dataset = ItemService.get_or_create_upload_dataset(item)
            version = DatasetVersion.objects.create(
                tenant=self.tenant, dataset=dataset, version_tag='v1.0',
                manifest={'images': [{'id': image.id, 'sha256': image.sha256, 'width': image.width,
                                      'height': image.height, 'annotations': []}], 'image_count': 1})
            self.job, self.export = JobService.enqueue_export(version, self.user)

    def _stale(self, attempts):
        with tenant_atomic(self.tenant):
            BackgroundJob.objects.filter(pk=self.job.pk).update(
                status=BackgroundJob.Status.RUNNING, attempt_count=attempts,
                started_at=timezone.now() - timedelta(seconds=120))

    def _reload(self):
        with tenant_atomic(self.tenant):
            return BackgroundJob.objects.get(pk=self.job.pk), ExportJob.objects.get(pk=self.export.pk)

    def test_오래된_RUNNING_은_다시_대기열로_간다(self):
        self._stale(attempts=0)
        with tenant_atomic(self.tenant):
            self.assertEqual(JobService.requeue_stale(self.tenant), 1)
        job, _ = self._reload()
        self.assertEqual((job.status, job.attempt_count), (BackgroundJob.Status.QUEUED, 1))

    def test_최근_RUNNING_은_건드리지_않는다(self):
        with tenant_atomic(self.tenant):
            BackgroundJob.objects.filter(pk=self.job.pk).update(
                status=BackgroundJob.Status.RUNNING, started_at=timezone.now())
            self.assertEqual(JobService.requeue_stale(self.tenant), 0)

    def test_세_번째_고착이면_실패로_끝내고_Export_도_실패다(self):
        self._stale(attempts=JobService.MAX_ATTEMPTS - 1)
        with tenant_atomic(self.tenant):
            JobService.requeue_stale(self.tenant)
        job, export = self._reload()
        self.assertEqual(job.status, BackgroundJob.Status.FAILED)
        self.assertEqual(export.status, ExportJob.Status.FAILED)
        self.assertIn('워커가 중단', export.error_message)

    def test_작업이_예외로_실패하면_Export_도_실패다(self):
        with patch.object(ExportService, 'run', side_effect=RuntimeError('디스크 가득')):
            JobService.run_pending(limit=1)
        job, export = self._reload()
        self.assertEqual((job.status, export.status), (BackgroundJob.Status.FAILED, ExportJob.Status.FAILED))

    def test_run_pending_은_고착_작업을_다시_집는다(self):
        self._stale(attempts=0)
        self.assertEqual([j.pk for j in JobService.run_pending(limit=5)], [self.job.pk])

    def test_정상_작업은_zip_을_남긴다(self):
        JobService.run_pending(limit=1)
        _, export = self._reload()
        self.assertEqual(export.status, ExportJob.Status.COMPLETED)
        self.assertEqual(len(list(Path(settings.MEDIA_ROOT).rglob('*.zip'))), 1)

    def test_zip_저장_뒤_실패하면_zip_을_지운다(self):
        with patch.object(AuditService, 'record', side_effect=RuntimeError('x')):
            JobService.run_pending(limit=1)
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob('*.zip')), [])
