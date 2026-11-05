"""학습 플랫폼(Wezard)용 스냅샷 API — `/api/v1/datasets/...`.

정본은 `docs/Wezard/maip-api.md` 다. 키는 IntegrationClient 로 대조한다(DECISIONS DEC-029).
"""
import hashlib
import secrets
import tempfile

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from domain.models.data import ActivityLog, ExportJob, ImageAsset, InspectionItem, LabelClass
from domain.models.vision import IntegrationClient, VisionClient
from domain.services.data.annotation import AnnotationService
from domain.services.data.export import ExportService
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.services.data.version import DatasetVersionService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from tests.test_data_services import make_image


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


class DatasetApiTestCase(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_superuser('dataset-api-admin', password='x')
        self.api_key = 'maip_' + secrets.token_urlsafe(32)
        IntegrationClient.objects.create(client_id='WEZARD-TEST', name='Wezard',
                                         api_key_hash=sha256(self.api_key.encode()))
        with tenant_atomic(self.tenant):
            self.item = InspectionItem.objects.create(
                tenant=self.tenant, code='API-DET', name='검출',
                task_type=InspectionItem.TaskType.OBJECT_DETECTION)
            # COCO 는 결함 라벨 클래스가 있어야 만들어진다(CocoExporter.validate).
            LabelClass.objects.create(tenant=self.tenant, item=self.item, name='dent',
                                      display_name_ko='찍힘', is_defect=True)
        self.http = Client()

    def snapshot(self, item=None, run=True, count=14):
        """승인 이미지 count 장으로 스냅샷을 만들고 **Wezard 형식** Export 를 돌려준다.

        Wezard 최소 조건(학습용 10장)을 넘기려고 14장이고, 객체 탐지면 장마다 결함 박스를 하나 단다.
        run=False 면 Export 는 QUEUED 로 남는다.
        """
        item = item or self.item
        self.batch = getattr(self, 'batch', 0) + 1  # 같은 데이터셋에 같은 파일은 다시 올라가지 않는다
        with tenant_atomic(self.tenant):
            dataset = ItemService.get_or_create_upload_dataset(item)
            ImageService.upload_images(item, [make_image(f'{self.batch}-{i}.png', color=(i, self.batch, 50))
                                              for i in range(count)], actor=self.user)
            new = ImageAsset.objects.for_tenant(self.tenant).filter(dataset=dataset).exclude(
                label_status=ImageAsset.LabelStatus.APPROVED)
            label = LabelClass.objects.for_tenant(self.tenant).filter(item=item).first()
            if label and item.task_type == InspectionItem.TaskType.OBJECT_DETECTION:
                for image in new:
                    AnnotationService.replace_annotations(image, [{
                        'geometry_type': 'BBOX', 'label_class_id': label.id,
                        'x': 10, 'y': 8, 'width': 20, 'height': 16}], actor=self.user)
            new.update(label_status=ImageAsset.LabelStatus.APPROVED)
            version, _ = DatasetVersionService.create_snapshot(dataset, self.user)
            export = ExportJob.objects.for_tenant(self.tenant).get(dataset_version=version, format=ExportJob.Format.WEZARD)
            if run:
                ExportService.run(export)
                export.refresh_from_db()
                self.assertEqual(export.status, ExportJob.Status.COMPLETED, export.error_message)
        return version, export

    def get(self, path, **extra):
        # 키 하나가 연동처를 나타낸다. X-Client-ID 는 보내지 않는다.
        return self.http.get(path, HTTP_X_API_KEY=self.api_key, **extra)


class ChecksumTest(DatasetApiTestCase):
    def test_Export_하면_zip_크기와_SHA256_을_저장한다(self):
        _, export = self.snapshot()
        raw = export.file.read()
        self.assertEqual((export.file_size, export.file_sha256), (len(raw), sha256(raw)))

    def test_비어_있으면_처음_부를_때_계산해_저장한다(self):
        _, export = self.snapshot()
        raw = export.file.read()
        with tenant_atomic(self.tenant):
            ExportJob.objects.for_tenant(self.tenant).filter(pk=export.pk).update(file_size=None, file_sha256='')
            export.refresh_from_db()
            ExportService.ensure_checksum(export)
            export.refresh_from_db()
        self.assertEqual((export.file_size, export.file_sha256), (len(raw), sha256(raw)))


LIST = '/api/v1/datasets/snapshots'


class AuthTest(DatasetApiTestCase):
    def test_키가_없으면_401_AUTH_REQUIRED(self):
        response = self.http.get(LIST)
        self.assertEqual((response.status_code, response.json()['error']['code']), (401, 'AUTH_REQUIRED'))

    def test_검사_클라이언트_키로는_받을_수_없다(self):
        key = secrets.token_urlsafe(24)
        VisionClient.objects.create(client_id='FIELD-PC', name='현장', api_key_hash=sha256(key.encode()))
        response = self.http.get(LIST, HTTP_X_CLIENT_ID='FIELD-PC', HTTP_X_API_KEY=key)
        self.assertEqual((response.status_code, response.json()['error']['code']), (401, 'AUTH_INVALID'))

    def test_X_Client_ID_만으로는_401_AUTH_REQUIRED(self):
        response = self.http.get(LIST, HTTP_X_CLIENT_ID='WEZARD-TEST')
        self.assertEqual((response.status_code, response.json()['error']['code']), (401, 'AUTH_REQUIRED'))

    def test_연동_키로는_검사_API_를_부를_수_없다(self):
        # 연동 키에는 X-Client-ID 가 없어 검사 API 는 헤더 부족(AUTH_REQUIRED)으로, 있어도 다른 테이블이라 막는다.
        self.assertEqual(self.get('/api/v1/catalog').status_code, 401)
        response = self.get('/api/v1/catalog', HTTP_X_CLIENT_ID='WEZARD-TEST')
        self.assertEqual((response.status_code, response.json()['error']['code']), (401, 'AUTH_INVALID'))

    def test_사용을_끈_키는_401(self):
        IntegrationClient.objects.update(active=False)
        self.assertEqual(self.get(LIST).status_code, 401)

    def test_인증하면_최근_접속을_남긴다(self):
        self.get(LIST)
        self.assertIsNotNone(IntegrationClient.objects.get().last_seen_at)


class SnapshotListTest(DatasetApiTestCase):
    def setUp(self):
        super().setUp()
        self.done, self.done_export = self.snapshot()
        with tenant_atomic(self.tenant):
            self.other = InspectionItem.objects.create(
                tenant=self.tenant, code='API-CLS', name='분류',
                task_type=InspectionItem.TaskType.CLASSIFICATION)
        self.queued, _ = self.snapshot(self.other, run=False)

    def test_최신순으로_검사항목과_Export_를_함께_준다(self):
        body = self.get(LIST).json()['data']
        self.assertEqual((body['total'], body['limit'], body['offset']), (2, 50, 0))
        first, second = body['items']
        self.assertEqual((first['id'], second['id']), (self.queued.id, self.done.id))
        self.assertEqual(second['item'], {'id': self.item.id, 'code': 'API-DET', 'name': '검출',
                                          'task_type': 'OBJECT_DETECTION'})
        self.assertEqual(second['image_count'], 14)
        self.assertTrue(second['created_at'].endswith('Z'))
        export = second['export']
        self.assertEqual((export['status'], export['format'], export['format_label']),
                         ('COMPLETED', 'WEZARD', 'Wezard 학습 데이터셋'))
        self.assertEqual((export['size_bytes'], export['sha256']),
                         (self.done_export.file_size, self.done_export.file_sha256))
        self.assertEqual(export['download_url'], f'/api/v1/datasets/snapshots/{self.done.id}/download')
        self.assertIsNone(first['export']['download_url'])  # 아직 대기 중

    def test_검사항목_유형_상태로_거른다(self):
        def ids(query):
            return [row['id'] for row in self.get(LIST + query).json()['data']['items']]
        self.assertEqual(ids('?item_code=API-DET'), [self.done.id])
        self.assertEqual(ids('?task_type=CLASSIFICATION'), [self.queued.id])
        self.assertEqual(ids('?status=COMPLETED'), [self.done.id])
        self.assertEqual(ids('?status=QUEUED'), [self.queued.id])
        self.assertEqual(ids('?created_after=2999-01-01T00:00:00Z'), [])

    def test_페이지를_나눈다(self):
        body = self.get(LIST + '?limit=1&offset=1').json()['data']
        self.assertEqual(([row['id'] for row in body['items']], body['total']), ([self.done.id], 2))

    def test_잘못된_쿼리는_400_INVALID_PARAMETER(self):
        for query in ('?offset=-1', '?offset=x', '?limit=0', '?limit=201', '?status=DONE',
                      '?task_type=SEGMENT', '?task_type=MEASUREMENT', '?created_after=어제'):
            response = self.get(LIST + query)
            self.assertEqual((response.status_code, response.json()['error']['code']),
                             (400, 'INVALID_PARAMETER'), query)


class SnapshotDetailTest(DatasetApiTestCase):
    def test_목록_행에_통계와_제외_이미지_수를_더한다(self):
        version, export = self.snapshot()
        body = self.get(f'{LIST}/{version.id}').json()['data']
        self.assertEqual(body['export']['sha256'], export.file_sha256)
        self.assertEqual(body['excluded_image_count'], 0)
        self.assertEqual(body['statistics']['image_count'], 14)
        self.assertIsNone(body['export']['error_message'])

    def test_예전_zip_은_정보를_볼_때_SHA256_을_채운다(self):
        version, export = self.snapshot()
        expected = export.file_sha256
        with tenant_atomic(self.tenant):
            ExportJob.objects.for_tenant(self.tenant).filter(pk=export.pk).update(file_size=None, file_sha256='')
        self.assertEqual(self.get(f'{LIST}/{version.id}').json()['data']['export']['sha256'], expected)

    def test_없는_스냅샷은_404_SNAPSHOT_NOT_FOUND(self):
        response = self.get(f'{LIST}/999999')
        self.assertEqual((response.status_code, response.json()['error']['code']), (404, 'SNAPSHOT_NOT_FOUND'))


class SnapshotDownloadTest(DatasetApiTestCase):
    def url(self, version):
        return f'{LIST}/{version.id}/download'

    def body(self, response):
        return b''.join(response.streaming_content)

    def downloads(self):
        with tenant_atomic(self.tenant):
            return ActivityLog.objects.for_tenant(self.tenant).filter(event_type='SNAPSHOT_DOWNLOADED').count()

    def test_전체를_받으면_SHA256_이_정보와_같다(self):
        version, export = self.snapshot()
        response = self.get(self.url(version))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sha256(self.body(response)), export.file_sha256)
        self.assertIn(f'snapshot-{version.id}-{version.version_tag}-wezard.zip', response['Content-Disposition'])
        self.assertEqual(response['Accept-Ranges'], 'bytes')

    def test_Range_로_이어받는다(self):
        version, export = self.snapshot()
        raw = export.file.read()
        response = self.get(self.url(version), HTTP_RANGE='bytes=10-')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self.body(response), raw[10:])
        self.assertEqual(response['Content-Range'], f'bytes 10-{len(raw) - 1}/{len(raw)}')

    def test_파일_밖_범위는_416(self):
        version, export = self.snapshot()
        response = self.get(self.url(version), HTTP_RANGE=f'bytes={export.file_size + 5}-')
        self.assertEqual((response.status_code, response.json()['error']['code']),
                         (416, 'RANGE_NOT_SATISFIABLE'))

    def test_받기_시작만_감사_로그에_남긴다(self):
        version, _ = self.snapshot()
        self.body(self.get(self.url(version)))
        self.body(self.get(self.url(version), HTTP_RANGE='bytes=10-'))
        self.assertEqual(self.downloads(), 1)

    def test_대기_중이면_409_EXPORT_NOT_READY_재시도_가능(self):
        version, _ = self.snapshot(run=False)
        response = self.get(self.url(version))
        error = response.json()['error']
        self.assertEqual((response.status_code, error['code'], error['retryable']), (409, 'EXPORT_NOT_READY', True))

    def test_실패했으면_409_EXPORT_FAILED(self):
        version, export = self.snapshot(run=False)
        with tenant_atomic(self.tenant):
            ExportJob.objects.for_tenant(self.tenant).filter(pk=export.pk).update(status=ExportJob.Status.FAILED)
        response = self.get(self.url(version))
        self.assertEqual((response.status_code, response.json()['error']['code']), (409, 'EXPORT_FAILED'))

    def test_파일이_사라졌으면_404_EXPORT_FILE_NOT_FOUND(self):
        version, export = self.snapshot()
        export.file.storage.delete(export.file.name)
        response = self.get(self.url(version))
        self.assertEqual((response.status_code, response.json()['error']['code']), (404, 'EXPORT_FILE_NOT_FOUND'))

    def test_없는_스냅샷은_404(self):
        self.assertEqual(self.get(f'{LIST}/999999/download').json()['error']['code'], 'SNAPSHOT_NOT_FOUND')


class RequestIdTest(DatasetApiTestCase):
    """X-Request-ID 를 돌려주고 오류 본문·감사 로그에 남긴다."""

    def test_형식이_맞으면_그대로_돌려준다(self):
        response = self.get(LIST, HTTP_X_REQUEST_ID='wz-import.57_a')
        self.assertEqual(response['X-Request-ID'], 'wz-import.57_a')

    def test_없거나_형식이_틀리면_새로_만든다(self):
        for extra in ({}, {'HTTP_X_REQUEST_ID': 'x' * 65}, {'HTTP_X_REQUEST_ID': '한글'}):
            response = self.get(LIST, **extra)
            self.assertEqual(response.status_code, 200)
            self.assertRegex(response['X-Request-ID'], r'^[0-9a-f]{32}$')

    def test_오류_본문에_request_id_가_있다(self):
        response = self.http.get(LIST, HTTP_X_REQUEST_ID='req-401')
        self.assertEqual((response.status_code, response.json()['request_id'], response['X-Request-ID']),
                         (401, 'req-401', 'req-401'))
        response = self.get(f'{LIST}/999999', HTTP_X_REQUEST_ID='req-404')
        self.assertEqual(response.json()['request_id'], 'req-404')

    def test_없는_경로의_404_본문에도_request_id_가_있다(self):
        # 연동 규약 §4 — 받는 쪽은 오류 본문 request_id 로 돌려준다. 없는 경로는 catch-all 이 받는다.
        for path in ('/api/v1/datasets/xyz', f'{LIST}/abc'):
            response = self.http.get(path, HTTP_X_REQUEST_ID='req-nf')
            self.assertEqual((response.status_code, response.json()['error']['code'], response.json().get('request_id')),
                             (404, 'NOT_FOUND', 'req-nf'), path)

    def test_받기_감사_로그에_request_id_를_남긴다(self):
        version, _ = self.snapshot()
        b''.join(self.get(f'{LIST}/{version.id}/download', HTTP_X_REQUEST_ID='req-dl').streaming_content)
        with tenant_atomic(self.tenant):
            log = ActivityLog.objects.for_tenant(self.tenant).get(event_type='SNAPSHOT_DOWNLOADED')
        self.assertEqual((log.payload['request_id'], log.payload['client_id']), ('req-dl', 'WEZARD-TEST'))
