"""데이터 관리 서비스.

통합 구조 기준으로 새로 쓴 테스트다.
"""
import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from domain.models.data import (
    Dataset,
    ImageAsset,
    InspectionItem,
    LabelClass,
    LabelingTask,
)
from domain.services.account import user_is_platform_admin
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.services.data.item_access import ItemAccessService
from domain.services.data.labeling_task import LabelingTaskService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic


def make_image(name='a.png', size=(64, 48), color=(200, 30, 30)):
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class DataServiceTestCase(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        self.manager = User.objects.create_user('manager', password='x')
        self.worker = User.objects.create_user('worker', password='x')
        self.outsider = User.objects.create_user('outsider', password='x')
        with tenant_atomic(self.tenant):
            self.item = InspectionItem.objects.create(
                tenant=self.tenant, code='SCRATCH', name='스크래치 검사',
                task_type=InspectionItem.TaskType.OBJECT_DETECTION)


class UploadChannelTest(DataServiceTestCase):
    def test_경로와_등록자를_남긴다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('f.png')], actor=self.worker)
            ImageService.upload_images(self.item, [make_image('c.png', color=(1, 2, 3))], actor=self.worker,
                                       channel=ImageAsset.Channel.CAMERA)
            rows = dict(ImageAsset.objects.for_tenant(self.tenant).values_list('original_name', 'channel'))
            who = set(ImageAsset.objects.for_tenant(self.tenant).values_list('uploaded_by_id', flat=True))
        self.assertEqual(rows, {'f.png': 'FILE', 'c.png': 'CAMERA'})
        self.assertEqual(who, {self.worker.id})


class UploadDatasetTest(DataServiceTestCase):
    def test_검사항목당_업로드_데이터셋이_하나_자동_생성된다(self):
        with tenant_atomic(self.tenant):
            first = ItemService.get_or_create_upload_dataset(self.item)
            second = ItemService.get_or_create_upload_dataset(self.item)
        self.assertEqual(first.id, second.id)
        self.assertEqual(Dataset.objects.for_tenant(self.tenant).filter(item=self.item).count(), 1)

    def test_업로드하면_UPLOADED_UNLABELED_로_들어온다(self):
        with tenant_atomic(self.tenant):
            result = ImageService.upload_images(self.item, [make_image()], actor=self.worker)
        self.assertEqual(len(result['uploaded']), 1)
        asset = ImageAsset.objects.for_tenant(self.tenant).get()
        self.assertEqual(asset.status, ImageAsset.Status.UPLOADED)
        self.assertEqual(asset.label_status, ImageAsset.LabelStatus.UNLABELED)
        self.assertEqual(asset.width, 64)
        self.assertEqual(asset.height, 48)
        self.assertTrue(asset.thumbnail)

    def test_화면_업로드는_같은_이미지를_거부한다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image()], actor=self.worker)
            result = ImageService.upload_images(self.item, [make_image()], actor=self.worker)
        self.assertEqual(len(result['uploaded']), 0)
        self.assertEqual(len(result['rejected']), 1)


class ItemAccessTest(DataServiceTestCase):
    def test_배정_없이_모든_비전검사항목이_보인다(self):
        """비전검사항목 배정은 없앴다 — 무엇을 할 수 있는지는 메뉴 권한이 정한다(사용자 결정 2026-10-21)."""
        with tenant_atomic(self.tenant):
            for user in (self.manager, self.worker, self.outsider):
                self.assertEqual(ItemAccessService.visible_items(user=user, tenant=self.tenant).count(), 1, user.username)

    def test_쓰기_판단은_그_메뉴의_W_다(self):
        from domain.models.user import UserGroup, UserGroupMenu
        from domain.services.data.item_access import REVIEW_MENU
        group = UserGroup.objects.create(Code='reviewers', Name='검수')
        UserGroupMenu.objects.create(UserGroup=group, MenuCode=REVIEW_MENU, AuthCode='RW')
        self.worker.userprofile.UserGroup = group
        self.worker.userprofile.save()
        self.assertTrue(ItemAccessService.can_write(self.worker, REVIEW_MENU))
        self.assertFalse(ItemAccessService.can_write(self.worker, 'wm_data_snapshot'))
        self.assertFalse(ItemAccessService.can_write(self.manager, REVIEW_MENU))      # 그룹 없음
        UserGroupMenu.objects.filter(UserGroup=group).update(AuthCode='R')
        self.assertFalse(ItemAccessService.can_write(self.worker, REVIEW_MENU))

    def test_삭제_대기_검사항목은_목록에서_빠진다(self):
        with tenant_atomic(self.tenant):
            self.item.status = InspectionItem.Status.DELETION_PENDING
            self.item.save()
            self.assertEqual(
                ItemAccessService.visible_items(user=self.worker, tenant=self.tenant).count(), 0)

    def test_플랫폼_관리자는_배정_없이도_전부_보인다(self):
        admin = User.objects.create_user('root', password='x', is_superuser=True)
        self.assertTrue(user_is_platform_admin(admin))
        with tenant_atomic(self.tenant):
            self.assertEqual(
                ItemAccessService.visible_items(user=admin, tenant=self.tenant).count(), 1)


class LabelingTaskTest(DataServiceTestCase):
    def setUp(self):
        super().setUp()
        with tenant_atomic(self.tenant):
            LabelClass.objects.create(tenant=self.tenant, item=self.item, name='scratch',
                                      display_name_ko='긁힘')
            ImageService.upload_images(self.item, [make_image()], actor=self.worker)
            self.asset = ImageAsset.objects.for_tenant(self.tenant).get()

    def test_한_이미지를_두_명이_동시에_잡을_수_없다(self):
        from django.core.exceptions import PermissionDenied

        with tenant_atomic(self.tenant):
            task = LabelingTaskService.claim(image=self.asset, actor=self.worker)
            self.assertIsNotNone(task)
            # 임대가 살아 있는 동안 다른 사람이 잡으려 하면 거부된다.
            with self.assertRaises(PermissionDenied):
                LabelingTaskService.claim(image=self.asset, actor=self.manager)

    def test_작업중_이미지에는_활성_작업이_하나뿐이다(self):
        with tenant_atomic(self.tenant):
            LabelingTaskService.claim(image=self.asset, actor=self.worker)
            active = LabelingTask.objects.for_tenant(self.tenant).filter(
                image=self.asset, status__in=['CLAIMED', 'IN_PROGRESS']).count()
        self.assertEqual(active, 1)


class DeleteItemFilesTest(DataServiceTestCase):
    """검사항목을 지우면 그 검사항목의 파일도 저장소에서 사라진다."""

    def setUp(self):
        # 다른 테스트가 같은 검사항목 번호 폴더에 남긴 파일과 섞이지 않게 저장소를 따로 쓴다.
        import tempfile

        from django.test import override_settings

        super().setUp()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)

    def test_편집_원본과_대표_이미지까지_지운다(self):
        from pathlib import Path

        from django.conf import settings

        from domain.services.data.item_platform import ItemPlatformService
        from domain.services.data.preprocess import ImagePreprocessService

        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image()], actor=self.worker)
            asset = ImageAsset.objects.for_tenant(self.tenant).get()
            # 편집하면 원본이 original_file 로 남고 file 은 새 경로가 된다.
            with self.captureOnCommitCallbacks(execute=True):  # 이전 썸네일은 커밋 뒤에 지운다
                ImagePreprocessService.apply(asset, [{'op': 'rotate', 'degrees': 90}], actor=self.manager)
            self.item.cover_image.save('cover.png', make_image(), save=True)

        folder = Path(settings.MEDIA_ROOT) / f'tenants/{self.tenant.id}/items/{self.item.id}'
        self.assertGreaterEqual(len([p for p in folder.rglob('*') if p.is_file()]), 4)

        ItemPlatformService.delete_item(self.item.id)

        self.assertEqual([str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()], [])

    def test_검사_기록이_있으면_삭제를_승인하지_않고_파일도_남긴다(self):
        # 검사 기록은 검사항목을 PROTECT 로 붙든다. 파일을 먼저 지운 뒤 DB 삭제가
        # 막혀 롤백되면 행은 남고 파일만 사라진다.
        import uuid
        from pathlib import Path

        from django.conf import settings

        from domain.models.vision import VisionClient, VisionInspection
        from domain.services.data.item_deletion import ItemDeletionService

        admin = User.objects.create_superuser('root', password='x')
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image()], actor=self.worker)
            client = VisionClient.objects.create(client_id='C-1', name='c', api_key_hash='x' * 64)
            VisionInspection.objects.create(id=str(uuid.uuid4()), request_id=str(uuid.uuid4()),
                                            client=client, item=self.item)
            self.item.status = InspectionItem.Status.PAUSED
            self.item.save(update_fields=['status'])
        deletion = ItemDeletionService.request(item=self.item, actor=admin)

        with self.assertRaisesMessage(ValueError, '비전 검사 기록이 있는 비전검사항목은 삭제할 수 없습니다. 삭제 요청을 반려해 주세요.'):
            ItemDeletionService.approve(deletion=deletion, reviewer=admin)

        folder = Path(settings.MEDIA_ROOT) / f'tenants/{self.tenant.id}/items/{self.item.id}'
        self.assertTrue(any(p.is_file() for p in folder.rglob('*')), '파일이 지워졌다')
        self.assertTrue(InspectionItem.objects.filter(pk=self.item.pk).exists())


    def test_삭제를_승인해도_무엇을_지웠는지_요청에_남는다(self):
        # 비전검사항목이 지워지면 요청의 item 은 끊긴다(SET_NULL). 코드·이름이 없으면 기록이 쓸모없다.
        from domain.services.data.item_deletion import ItemDeletionService

        admin = User.objects.create_superuser('root', password='x')
        code, name = self.item.code, self.item.name
        with tenant_atomic(self.tenant):
            self.item.status = InspectionItem.Status.PAUSED
            self.item.save(update_fields=['status'])
        deletion = ItemDeletionService.request(item=self.item, actor=admin)

        ItemDeletionService.approve(deletion=deletion, reviewer=admin)

        with tenant_atomic(self.tenant):
            deletion.refresh_from_db()
        self.assertIsNone(deletion.item_id)
        self.assertEqual((deletion.item_code, deletion.item_name, deletion.status), (code, name, 'APPROVED'))

    def test_삭제를_승인해도_워커_작업은_무엇을_만들었는지와_함께_남는다(self):
        # 워커 작업 행은 나중 워커 관리 화면의 이력이다. zip 작업이 지워져도 무엇을 만들었는지 읽혀야 한다.
        from domain.models.data import BackgroundJob, DatasetVersion
        from domain.services.data.item_deletion import ItemDeletionService
        from domain.services.data.job import JobService

        admin = User.objects.create_superuser('root', password='x')
        with tenant_atomic(self.tenant):
            dataset = ItemService.get_or_create_upload_dataset(self.item)
            version = DatasetVersion.objects.create(tenant=self.tenant, dataset=dataset, version_tag='v1.0',
                                                    manifest={'images': [], 'image_count': 0})
            job, export = JobService.enqueue_export(version, admin, export_format='WEZARD')
            self.item.status = InspectionItem.Status.PAUSED
            self.item.save(update_fields=['status'])
        deletion = ItemDeletionService.request(item=self.item, actor=admin)

        ItemDeletionService.approve(deletion=deletion, reviewer=admin)

        with tenant_atomic(self.tenant):
            payload = BackgroundJob.objects.get(pk=job.pk).payload
        self.assertEqual(payload, {'export_job_id': export.id, 'item_code': self.item.code, 'item_name': self.item.name,
                                   'version_tag': 'v1.0', 'format': 'WEZARD'})


class UploadRollbackFilesTest(DataServiceTestCase):
    """업로드 트랜잭션이 롤백되면 이미 쓴 이미지·썸네일 파일도 지운다."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        super().setUp()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)

    def test_업로드_트랜잭션이_실패하면_파일을_지운다(self):
        from pathlib import Path
        from unittest.mock import patch

        from django.conf import settings

        from domain.services.data.audit import AuditService

        with patch.object(AuditService, 'record', side_effect=RuntimeError('x')):
            with self.assertRaises(RuntimeError), tenant_atomic(self.tenant):
                ImageService.upload_images(self.item, [make_image()], actor=self.worker)
        self.assertEqual([p for p in Path(settings.MEDIA_ROOT).rglob('*') if p.is_file()], [])


class UploadLimitTest(DataServiceTestCase):
    """한 요청에 20개까지 처리한다. 넘는 파일은 말없이 버리지 않고 거절 목록에 넣는다."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        super().setUp()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)

    def test_21번째부터는_거절_목록에_들어간다(self):
        files = [make_image(f'{i}.png', color=(i, 0, 0)) for i in range(21)]
        with tenant_atomic(self.tenant):
            result = ImageService.upload_images(self.item, files, actor=self.worker)
        self.assertEqual(len(result['uploaded']), 20)
        self.assertEqual(result['rejected'], [{'name': '20.png', 'reason': '한 번에 20개까지 올릴 수 있습니다.'}])


class ImageChannelFieldTest(DataServiceTestCase):
    def test_등록_경로_기본값은_파일_업로드이고_등록자는_비어_있다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image()])
        image = ImageAsset.objects.for_tenant(self.tenant).get()
        self.assertEqual((image.channel, image.uploaded_by_id), (ImageAsset.Channel.FILE, None))
        self.assertEqual(image.get_channel_display(), '파일 업로드')
