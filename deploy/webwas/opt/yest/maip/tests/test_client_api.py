"""비전검사 클라이언트용 `/api/v1` 계약.

여기서 깨지면 현장 검사가 멈춘다. 검증 기준은 계약 정본인
`docs/client/SERVER_API_CONTRACT.md` 다 — 서버가 관리하고 클라이언트가 맞춘다.
"""
import hashlib
import io
import json
import secrets
import shutil
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.utils import OperationalError
from django.test import Client, TestCase, override_settings
from PIL import Image

from domain.models.data import ImageAsset, InspectionItem, LabelClass, MeasurementPoint
from domain.models.vision import (
    VisionClient,
    VisionInspection,
    VisionItemModelMapping,
    VisionModel,
    VisionOverlay,
)
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic


def jpeg_bytes(size=(64, 48)):
    buffer = io.BytesIO()
    Image.new('RGB', size, (10, 120, 200)).save(buffer, format='JPEG')
    return buffer.getvalue()


def png_bytes(size=(40, 30)):
    buffer = io.BytesIO()
    Image.new('RGB', size, (200, 30, 30)).save(buffer, format='PNG')
    return buffer.getvalue()


def bomb_png(width=20000, height=20000):
    """헤더만 거대한 작은 PNG(1비트 0 행). Pillow 가 열 때 DecompressionBombError 를 낸다."""
    import struct
    import zlib

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    row = b'\x00' * (1 + (width + 7) // 8)
    packer = zlib.compressobj(9)
    data = b''.join(packer.compress(row) for _ in range(height)) + packer.flush()
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 1, 0, 0, 0, 0))
            + chunk(b'IDAT', data) + chunk(b'IEND', b''))


class ClientApiTestCase(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        self.api_key = secrets.token_urlsafe(24)
        account = User.objects.create_user('svc-test', password='x')
        with tenant_atomic(self.tenant):
            self.vision_client = VisionClient.objects.create(
                client_id='CLIENT-TEST', name='테스트 Client',
                api_key_hash=hashlib.sha256(self.api_key.encode()).hexdigest(),
                service_account=account)
            self.item = InspectionItem.objects.create(
                tenant=self.tenant, code='SCRATCH', name='스크래치',
                task_type=InspectionItem.TaskType.OBJECT_DETECTION)
            self.classification_item = InspectionItem.objects.create(
                tenant=self.tenant, code='SORT', name='분류 검사',
                task_type=InspectionItem.TaskType.CLASSIFICATION)
        self.http = Client()

    def _headers(self, **override):
        return {'HTTP_X_CLIENT_ID': 'CLIENT-TEST', 'HTTP_X_API_KEY': self.api_key, **override}

    def _submit(self, request_id=None, item_id=None):
        return self.http.post('/api/v1/inspections', {
            'image': io.BytesIO(jpeg_bytes()),
            'metadata': json.dumps({
                'request_id': request_id or str(uuid.uuid4()),
                'client_id': 'CLIENT-TEST',
                'process_id': 1, 'product_id': 1,
                'inspection_item_id': item_id or self.item.id,
                'capture_timestamp': '2026-09-30T09:12:00+09:00',
                'client_version': '1.0.0',
                'camera': {'vendor': 'basler', 'serial_number': 'SN-1'},
            }),
        }, **self._headers())


class HealthTest(ClientApiTestCase):
    def test_인증없이_계약_형식으로_나온다(self):
        response = self.http.get('/api/v1/health')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        # Client 는 최상위 status·components·version 을 읽는다. 봉투로 싸면 못 읽는다.
        self.assertNotIn('data', body)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['components'], {'database': 'ok', 'storage': 'ok'})
        self.assertEqual(body['version'], settings.APP_VERSION)
        self.assertTrue(body['timestamp'].endswith('Z'))

    def test_DB_가_죽으면_503_degraded(self):
        with patch('django.db.connection.cursor', side_effect=OperationalError('down')):
            response = self.http.get('/api/v1/health')
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body['status'], 'degraded')
        self.assertEqual(body['components']['database'], 'error')
        self.assertEqual(body['components']['storage'], 'ok')
        # 이 503 은 오류 봉투가 아니다. Health 본문을 그대로 낸다.
        self.assertNotIn('error', body)

    def test_Storage_에_쓸_수_없으면_503_degraded(self):
        # 평범한 파일을 부모로 지목한다 — mkdir 이 NotADirectoryError 로 실패한다.
        # 권한으로 막는 경로(/proc 등)를 쓰면 root 로 돌릴 때 통과해 버린다.
        blocker = Path(tempfile.mkdtemp(prefix='health-test-')) / 'not-a-dir'
        blocker.write_bytes(b'x')
        self.addCleanup(shutil.rmtree, blocker.parent, True)
        with override_settings(STORAGE_ROOT=blocker / 'storage'):
            response = self.http.get('/api/v1/health')
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body['components']['storage'], 'error')
        self.assertEqual(body['components']['database'], 'ok')


class AuthTest(ClientApiTestCase):
    def test_헤더가_없으면_AUTH_REQUIRED(self):
        response = self.http.get('/api/v1/catalog')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_REQUIRED')
        self.assertFalse(response.json()['error']['retryable'])

    def test_헤더가_하나만_있어도_AUTH_REQUIRED(self):
        response = self.http.get('/api/v1/catalog', HTTP_X_CLIENT_ID='CLIENT-TEST')
        self.assertEqual(response.json()['error']['code'], 'AUTH_REQUIRED')

    def test_잘못된_키는_AUTH_INVALID(self):
        response = self.http.get('/api/v1/catalog',
                                 **self._headers(HTTP_X_API_KEY='wrong'))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_INVALID')

    def test_없는_Client_ID_는_AUTH_INVALID(self):
        response = self.http.get('/api/v1/catalog',
                                 **self._headers(HTTP_X_CLIENT_ID='CLIENT-NOPE'))
        self.assertEqual(response.json()['error']['code'], 'AUTH_INVALID')

    def test_비활성_Client는_AUTH_INVALID(self):
        VisionClient.objects.filter(pk=self.vision_client.pk).update(active=False)
        response = self.http.get('/api/v1/catalog', **self._headers())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_INVALID')



class EnvelopeTest(ClientApiTestCase):
    def test_없는_v1_경로는_404_봉투다(self):
        response = self.http.get('/api/v1/nope')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response['Content-Type'].split(';')[0], 'application/json')
        self.assertEqual(response.json()['error']['code'], 'NOT_FOUND')
        self.assertFalse(response.json()['error']['retryable'])
        self.assertNotIn('request_id', response.json())  # 클라이언트 계약의 오류 봉투에는 없다(§2-1)

    def test_client_packages_는_범용_api_라우트에_먹히지_않는다(self):
        # 범용 api/<task>/<view> 가 먼저 받으면 로그인 세션을 요구해 401 HTML 이 된다.
        response = self.http.get('/api/v1/client-packages')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'].split(';')[0], 'application/json')
        self.assertIn('data', response.json())

    def test_Content_Length_가_없으면_인증보다_먼저_411(self):
        # 인증 헤더를 일부러 보내지 않는다 — 411 이 인증보다 앞인지 보는 테스트다.
        response = self.http.post('/api/v1/inspections', {'metadata': '{}'},
                                  CONTENT_LENGTH='')
        self.assertEqual(response.status_code, 411)
        self.assertEqual(response.json()['error']['code'], 'LENGTH_REQUIRED')

    def test_본문이_상한을_넘으면_인증보다_먼저_413(self):
        response = self.http.post('/api/v1/inspections', {'metadata': '{}'},
                                  CONTENT_LENGTH=str(64 * 1024 * 1024))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['error']['code'], 'IMAGE_TOO_LARGE')

    def test_GET_은_Content_Length_를_요구하지_않는다(self):
        self.assertEqual(self.http.get('/api/v1/health').status_code, 200)

    def test_허용하지_않는_메서드도_봉투다(self):
        # Client 0.1.6 은 봉투 없는 4xx 를 재시도하지 않고 "서버 응답 오류"로 멈춘다.
        for method, path in (('get', '/api/v1/inspections'), ('delete', '/api/v1/overlays/1'),
                             ('options', '/api/v1/catalog'), ('put', '/api/v1/health')):
            # 본문이 있는 메서드는 Content-Length 가 없으면 411 이 먼저다. 본문을 싣는다.
            response = self.http.generic(method.upper(), path, b'x', 'text/plain',
                                         **self._headers())
            self.assertEqual(response.status_code, 405, (method, path))
            self.assertEqual(response.json()['error']['code'], 'METHOD_NOT_ALLOWED', (method, path))
            self.assertIs(response.json()['error']['retryable'], False)
            self.assertIn('Allow', response)

    def test_본문이_있는_다른_메서드도_인증_뒤_405_봉투다(self):
        response = self.http.post('/api/v1/catalog', {'x': '1'}, **self._headers())
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()['error']['code'], 'METHOD_NOT_ALLOWED')

    def test_v1_루트도_404_봉투다(self):
        for path in ('/api/v1', '/api/v1/'):
            response = self.http.get(path)
            self.assertEqual(response.status_code, 404, path)
            self.assertEqual(response.json()['error']['code'], 'NOT_FOUND', path)

    def test_오류_메시지는_계약_문서와_같은_경어체다(self):
        # 계약 문서(SERVER_API_CONTRACT.md)가 이 문장을 그대로 인용한다. 바꾸면 문서도 고친다.
        self.assertEqual(self.http.get('/api/v1/nope').json()['error']['message'], '없는 경로입니다.')
        self.assertEqual(self.http.get('/api/v1/catalog').json()['error']['message'],
                         '인증에 실패했습니다.')


class CatalogTest(ClientApiTestCase):
    def test_Client_파서가_요구하는_중첩_구조를_지킨다(self):
        payload = self.http.get('/api/v1/catalog', **self._headers()).json()['data']
        # server_client.py:283 이 이 키들을 KeyError 없이 훑는다.
        self.assertIn('version', payload)
        process = payload['processes'][0]
        for key in ('id', 'code', 'name', 'display_order'):
            self.assertIn(key, process)
        product = process['products'][0]
        for key in ('id', 'code', 'name'):
            self.assertIn(key, product)
        item = product['inspection_items'][0]
        for key in ('id', 'code', 'name', 'display_order', 'inspection_type', 'overlay'):
            self.assertIn(key, item)

    def test_합성_공정과_제품은_항상_한_건씩이다(self):
        payload = self.http.get('/api/v1/catalog', **self._headers()).json()['data']
        self.assertEqual(len(payload['processes']), 1)
        self.assertEqual(len(payload['processes'][0]['products']), 1)

    def test_분류_검사항목은_요청하지_않으면_카탈로그에_나오지_않는다(self):
        payload = self.http.get('/api/v1/catalog', **self._headers()).json()['data']
        codes = {i['code'] for i in payload['processes'][0]['products'][0]['inspection_items']}
        self.assertIn('SCRATCH', codes)
        # 0.1.6 이하 Client InspectionType enum 은 2종뿐이라 내보내면 파싱이 깨진다(O-14).
        self.assertNotIn('SORT', codes)

    def test_include_classification_이면_분류도_CLASSIFICATION_으로_나온다(self):
        url = '/api/v1/catalog?include=classification'
        payload = self.http.get(url, **self._headers()).json()['data']
        types = {i['code']: i['inspection_type'] for i in payload['processes'][0]['products'][0]['inspection_items']}
        self.assertEqual(types, {'SCRATCH': 'DETECTION', 'SORT': 'CLASSIFICATION'})
        # 지문은 내보낸 목록 기준이다. 버전 경로도 같은 파라미터를 받는다.
        plain = self.http.get('/api/v1/catalog/version', **self._headers()).json()['data']['version']
        with_cls = self.http.get('/api/v1/catalog/version?include=classification', **self._headers()).json()['data']['version']
        self.assertEqual(with_cls, payload['version'])
        self.assertNotEqual(plain, with_cls)

    def test_태블릿_촬영_검사항목은_어떤_include_로도_나오지_않는다(self):
        # 태블릿 항목은 디지털 양식 사진 넣기로만 쓴다 — 거치대 Client 목록에 없어야 한다(R22 §5-2)
        with tenant_atomic(self.tenant):
            InspectionItem.objects.create(tenant=self.tenant, code='TAB-X', name='태블릿',
                                          capture_method=InspectionItem.CaptureMethod.TABLET)
        for query in ('', '?include=classification,measurement'):
            payload = self.http.get('/api/v1/catalog' + query, **self._headers()).json()['data']
            codes = {i['code'] for i in payload['processes'][0]['products'][0]['inspection_items']}
            self.assertIn('SCRATCH', codes)
            self.assertNotIn('TAB-X', codes, query)

    def test_중지된_검사항목은_빠진다(self):
        with tenant_atomic(self.tenant):
            self.item.status = InspectionItem.Status.PAUSED
            self.item.save()
        payload = self.http.get('/api/v1/catalog', **self._headers()).json()['data']
        codes = {i['code'] for i in payload['processes'][0]['products'][0]['inspection_items']}
        self.assertNotIn('SCRATCH', codes)

    def test_버전_지문은_내용이_바뀔_때만_달라진다(self):
        first = self.http.get('/api/v1/catalog', **self._headers()).json()['data']['version']
        again = self.http.get('/api/v1/catalog', **self._headers()).json()['data']['version']
        self.assertEqual(first, again)
        with tenant_atomic(self.tenant):
            self.item.name = '스크래치(변경)'
            self.item.save()
        changed = self.http.get('/api/v1/catalog', **self._headers()).json()['data']['version']
        self.assertNotEqual(first, changed)


class InspectionSubmitTest(ClientApiTestCase):
    def test_촬영_전송이_데이터관리_이미지로_저장된다(self):
        response = self._submit()
        self.assertEqual(response.status_code, 201, response.content[:300])
        payload = response.json()['data']
        self.assertEqual(payload['status'], 'RECEIVED')

        inspection = VisionInspection.objects.get(pk=payload['id'])
        self.assertIsNotNone(inspection.image_asset, '검사 이미지가 데이터관리로 들어가지 않았다')

        asset = inspection.image_asset
        self.assertEqual(asset.dataset.item_id, self.item.id)
        self.assertEqual(asset.status, ImageAsset.Status.UPLOADED)
        self.assertEqual(asset.label_status, ImageAsset.LabelStatus.UNLABELED)
        self.assertEqual(asset.source_inspection_id, inspection.id)
        self.assertEqual(asset.channel, ImageAsset.Channel.CLIENT)

    def test_같은_request_id_재전송은_새로_저장하지_않는다(self):
        request_id = str(uuid.uuid4())
        first = self._submit(request_id=request_id)
        second = self._submit(request_id=request_id)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['data']['id'], second.json()['data']['id'])
        self.assertEqual(VisionInspection.objects.count(), 1)
        self.assertEqual(ImageAsset.objects.for_tenant(self.tenant).count(), 1)

    def test_같은_사진을_다시_찍어_보내도_저장된다(self):
        # 화면 업로드는 sha256 중복을 막지만 Client 경로는 허용한다.
        self._submit()
        self._submit()
        self.assertEqual(VisionInspection.objects.count(), 2)
        self.assertEqual(ImageAsset.objects.for_tenant(self.tenant).count(), 2)

    def test_없는_검사항목은_404(self):
        self.assertEqual(self._submit(item_id=999999).status_code, 404)

    def test_metadata_가_없으면_422(self):
        response = self.http.post('/api/v1/inspections',
                                  {'image': io.BytesIO(jpeg_bytes())}, **self._headers())
        self.assertEqual(response.status_code, 422)

    def _submit_raw(self, metadata, image=True):
        """metadata 를 문자열 그대로 보낸다 — JSON 이 아닌 경우까지 보려는 것이다."""
        payload = {'metadata': metadata}
        if image:
            payload['image'] = io.BytesIO(jpeg_bytes())
        return self.http.post('/api/v1/inspections', payload, **self._headers())

    def _metadata(self, **override):
        return json.dumps({'request_id': str(uuid.uuid4()),
                           'inspection_item_id': self.item.id, **override})

    def test_metadata_가_JSON_객체가_아니면_422(self):
        # json.loads 는 배열·숫자·문자열도 통과시킨다. 그대로 두면 .get() 에서
        # AttributeError 가 나 500 retryable=true 로 나가고 Client 가 재시도한다.
        for raw in ('[1, 2, 3]', '"문자열"', '42', 'null'):
            response = self._submit_raw(raw)
            self.assertEqual(response.status_code, 422, raw)
            self.assertEqual(response.json()['error']['code'], 'METADATA_INVALID', raw)
            self.assertIs(response.json()['error']['retryable'], False, raw)

    def test_길이_상한을_넘는_필드는_422_이고_아무것도_저장하지_않는다(self):
        # SQLite 는 varchar 길이를 강제하지 않아 고치기 전에는 201 로 통과한다.
        # 운영 PostgreSQL 에서는 DataError → 500 retryable=true 였다.
        cases = (
            ('client_version', {'client_version': 'v' * 51}),
            ('camera.vendor', {'camera': {'vendor': 'v' * 101, 'serial_number': 'S'}}),
            ('camera.serial_number', {'camera': {'vendor': 'basler', 'serial_number': 'S' * 101}}),
            ('request_id', {'request_id': 'x' * 37}),
        )
        for label, override in cases:
            response = self._submit_raw(self._metadata(**override))
            self.assertEqual(response.status_code, 422, label)
            self.assertEqual(response.json()['error']['code'], 'METADATA_INVALID', label)
            # 검증이 파일을 쓰기 전에 끝나야 한다. 뒤에서 거절하면 이미지 파일만
            # 남는다 — 파일 쓰기는 트랜잭션 롤백 대상이 아니다.
            self.assertEqual(VisionInspection.objects.count(), 0, f'{label}: 검사가 남았다')
            self.assertEqual(ImageAsset.objects.for_tenant(self.tenant).count(), 0,
                             f'{label}: 이미지가 저장됐다')

    def test_request_id_를_자르지_않고_거절한다(self):
        # 자르면 Client 가 보낸 id 로 재조회할 수 없는 기록이 생긴다(201 뒤 404).
        long_id = 'a' * 40
        self.assertEqual(self._submit_raw(self._metadata(request_id=long_id)).status_code, 422)
        self.assertFalse(VisionInspection.objects.filter(request_id=long_id[:36]).exists())

    def test_해상도만_거대한_압축_폭탄은_재시도하지_않는_IMAGE_INVALID(self):
        response = self.http.post('/api/v1/inspections', {
            'image': io.BytesIO(bomb_png()), 'metadata': self._metadata()}, **self._headers())
        self.assertEqual(response.status_code, 422, response.content[:200])
        body = response.json()['error']
        self.assertEqual((body['code'], body['retryable']), ('IMAGE_INVALID', False))
        self.assertEqual(VisionInspection.objects.count(), 0)

    def test_capture_timestamp_가_시각이_아니면_METADATA_INVALID(self):
        response = self._submit_raw(self._metadata(capture_timestamp='어제'))
        self.assertEqual(response.status_code, 422)
        # 이미지 문제가 아니다. IMAGE_INVALID 로 답하면 작업자가 카메라를 본다.
        self.assertEqual(response.json()['error']['code'], 'METADATA_INVALID')

    def test_inspection_item_id_가_정수가_아니면_METADATA_INVALID(self):
        response = self._submit_raw(self._metadata(inspection_item_id='abc'))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'METADATA_INVALID')

    def test_inspection_item_id_가_실수나_참거짓이면_METADATA_INVALID(self):
        # int() 는 12.7 → 12, True → 1 로 읽어 다른 비전검사항목으로 검사를 받는다
        for value in (self.item.id + 0.7, True):
            response = self._submit_raw(self._metadata(inspection_item_id=value))
            self.assertEqual(response.status_code, 422, value)
            self.assertEqual(response.json()['error']['code'], 'METADATA_INVALID', value)
        self.assertEqual(VisionInspection.objects.count(), 0)

    def test_camera_가_객체가_아니면_빈_값이어도_METADATA_INVALID(self):
        for value in ([], '', 0, False, 'basler'):
            response = self._submit_raw(self._metadata(camera=value))
            self.assertEqual(response.status_code, 422, value)
            self.assertEqual(response.json()['error']['code'], 'METADATA_INVALID', value)

    def test_camera_가_null_이거나_없으면_받는다(self):
        self.assertEqual(self._submit_raw(self._metadata(camera=None)).status_code, 201)
        self.assertEqual(self._submit_raw(self._metadata()).status_code, 201)

    def test_multipart_형식이_깨지면_재시도하지_않는_422(self):
        # 그대로 두면 request.POST 에서 MultiPartParserError → 500 retryable=true 로 나가 Client 가 같은 요청을 다시 보낸다
        response = self.http.post('/api/v1/inspections', data=b'--x\r\nbroken', content_type='multipart/form-data',
                                  **self._headers())
        self.assertEqual(response.status_code, 422)
        body = response.json()['error']
        self.assertEqual((body['code'], body['retryable']), ('METADATA_INVALID', False))

    def test_오류_메시지에_파이썬_예외_원문을_싣지_않는다(self):
        for metadata in (self._metadata(capture_timestamp='어제'),
                         self._metadata(inspection_item_id='abc')):
            message = self._submit_raw(metadata).json()['error']['message']
            for leak in ('isoformat', 'literal for int', 'Traceback', 'Error'):
                self.assertNotIn(leak, message, message)

    def test_정상_metadata_는_상한까지_그대로_201(self):
        response = self._submit_raw(self._metadata(
            client_version='v' * 50,
            camera={'vendor': 'v' * 100, 'serial_number': 'S' * 100},
            capture_timestamp='2026-10-06T09:00:00+09:00'))
        self.assertEqual(response.status_code, 201, response.content[:300])

    def test_남의_request_id_로는_결과를_볼_수_없다(self):
        request_id = str(uuid.uuid4())
        self._submit(request_id=request_id)

        other_key = secrets.token_urlsafe(24)
        with tenant_atomic(self.tenant):
            VisionClient.objects.create(
                client_id='CLIENT-OTHER', name='다른 Client',
                api_key_hash=hashlib.sha256(other_key.encode()).hexdigest())
        response = self.http.get(f'/api/v1/inspections/by-request/{request_id}',
                                 HTTP_X_CLIENT_ID='CLIENT-OTHER', HTTP_X_API_KEY=other_key)
        self.assertEqual(response.status_code, 404)

    def test_모델이_매핑돼_있어도_GPU가_없으면_RECEIVED_다(self):
        with tenant_atomic(self.tenant):
            model = VisionModel.objects.create(
                name='detector', inspection_type=VisionModel.InspectionType.DETECTION,
                version='1.0.0', artifact_path='/x.pt', runtime='torchvision', threshold=0.5)
            VisionItemModelMapping.objects.create(item=self.item, model=model)

        payload = self._submit().json()['data']
        self.assertEqual(payload['status'], 'RECEIVED')

        inspection = VisionInspection.objects.get(pk=payload['id'])
        # 매핑 없음과 구분할 수 있어야 한다 — 검사 결과 화면이 이걸로 판단한다.
        self.assertEqual(inspection.error_message, 'GPU_INFERENCE_NOT_CONFIGURED')
        self.assertTrue(inspection.inference_skipped)
        self.assertEqual(inspection.model_name, 'detector')

    def test_추론_결과의_bbox_는_x1y1x2y2_객체로_나간다(self):
        from domain.services.vision.gateway import Defect, InferenceResult

        with tenant_atomic(self.tenant):
            model = VisionModel.objects.create(
                name='detector', inspection_type=VisionModel.InspectionType.DETECTION,
                version='1.0.0', artifact_path='/x.pt', runtime='torchvision', threshold=0.5)
            VisionItemModelMapping.objects.create(item=self.item, model=model)

        class FakeGateway:
            def infer(self, **kwargs):
                return InferenceResult(
                    abnormal=True, model_name='detector', model_version='1.0.0',
                    defects=[Defect(class_name='scratch', confidence=0.93,
                                    bbox={'x1': 120, 'y1': 40, 'x2': 210, 'y2': 95})],
                    inference_ms=84.5)

        with patch('domain.services.vision.inspection.get_inference_gateway',
                   return_value=FakeGateway()):
            payload = self._submit().json()['data']

        self.assertEqual(payload['status'], 'SUCCESS')
        self.assertEqual(payload['defects'][0]['bbox'],
                         {'x1': 120, 'y1': 40, 'x2': 210, 'y2': 95})

    def test_탐지_결과에_라벨_표시_이름을_싣는다(self):
        from domain.services.vision.gateway import Defect, InferenceResult

        self._map_detector()
        with tenant_atomic(self.tenant):
            LabelClass.objects.create(tenant=self.tenant, item=self.item, name='scratch', display_name_ko='스크래치')

        class DetectGateway:
            def infer(self, **kwargs):
                box = {'x1': 1, 'y1': 1, 'x2': 5, 'y2': 5}
                return InferenceResult(abnormal=True, model_name='detector', model_version='4', inference_ms=9,
                                       defects=[Defect(class_name='scratch', confidence=0.98, bbox=box),
                                                Defect(class_name='dent', confidence=0.91, bbox=box)])

        with patch('domain.services.vision.inspection.get_inference_gateway', return_value=DetectGateway()):
            payload = self._submit().json()['data']
        # 검사항목에 없는 라벨은 코드를 그대로 이름으로 쓴다 — 분류와 같다.
        self.assertEqual([(d['class_name'], d['name']) for d in payload['defects']],
                         [('scratch', '스크래치'), ('dent', 'dent')])
        by_request = self.http.get(f'/api/v1/inspections/by-request/{payload["request_id"]}', **self._headers()).json()['data']
        self.assertEqual(by_request['defects'], payload['defects'])

    def _map_detector(self):
        with tenant_atomic(self.tenant):
            model = VisionModel.objects.create(
                name='detector', inspection_type=VisionModel.InspectionType.DETECTION,
                version='latest', artifact_path='', runtime='wezard')
            VisionItemModelMapping.objects.create(item=self.item, model=model)

    def _submit_with(self, error):
        class FailingGateway:
            def infer(self, **kwargs):
                raise error

        with patch('domain.services.vision.inspection.get_inference_gateway', return_value=FailingGateway()):
            return self._submit().json()['data']

    def test_배포된_모델이_없으면_RECEIVED_와_사유를_남긴다(self):
        from app.views.vision.inspection import _row
        from domain.services.vision.gateway import ModelNotDeployedError

        self._map_detector()
        payload = self._submit_with(ModelNotDeployedError())
        self.assertEqual(payload['status'], 'RECEIVED')
        inspection = VisionInspection.objects.get(pk=payload['id'])
        self.assertEqual(inspection.error_message, 'WEZARD_MODEL_NOT_DEPLOYED')
        self.assertEqual(_row(inspection)['status_label'], '접수됨 (추론 미실행 · 배포 모델 없음)')

    def test_Wezard_오류는_FAILED_이고_사유는_화면에만_남는다(self):
        from domain.services.vision.gateway import WezardError

        self._map_detector()
        payload = self._submit_with(WezardError('UPSTREAM_TIMEOUT', 504))
        self.assertEqual(payload['status'], 'FAILED')
        self.assertNotIn('UPSTREAM_TIMEOUT', json.dumps(payload))
        inspection = VisionInspection.objects.get(pk=payload['id'])
        self.assertEqual(inspection.error_message, 'WezardError: UPSTREAM_TIMEOUT (HTTP 504)')

    def test_성공하면_실제로_쓴_모델_버전을_기록한다(self):
        from domain.services.vision.gateway import InferenceResult

        self._map_detector()

        class LatestGateway:
            def infer(self, **kwargs):
                return InferenceResult(abnormal=False, model_name='detector', model_version='3', inference_ms=5)

        with patch('domain.services.vision.inspection.get_inference_gateway', return_value=LatestGateway()):
            payload = self._submit().json()['data']
        self.assertEqual(payload['model'], {'name': 'detector', 'version': '3'})

    def test_Wezard_미설정은_화면에_미설정으로_보인다(self):
        from app.views.vision.inspection import _row

        self._map_detector()
        inspection = VisionInspection.objects.get(pk=self._submit().json()['data']['id'])
        self.assertEqual(_row(inspection)['status_label'], '접수됨 (추론 미실행 · Wezard 미설정)')

    def _map_classifier(self):
        with tenant_atomic(self.tenant):
            for order, (name, ko, defect) in enumerate((('normal', '정상', False), ('defect', '불량', True))):
                LabelClass.objects.create(tenant=self.tenant, item=self.classification_item, name=name,
                                          display_name_ko=ko, is_defect=defect, sort_order=order)
            model = VisionModel.objects.create(
                name='sorter', inspection_type=VisionModel.InspectionType.CLASSIFICATION,
                version='latest', artifact_path='', runtime='wezard')
            VisionItemModelMapping.objects.create(item=self.classification_item, model=model)

    def _classify(self, label, score=0.97):
        from domain.services.vision.gateway import InferenceResult

        class ClassifyGateway:
            def infer(self, **kwargs):
                return InferenceResult(abnormal=False, model_name='sorter', model_version='1', inference_ms=7,
                                       classification={'label': label, 'score': score})

        with patch('domain.services.vision.inspection.get_inference_gateway', return_value=ClassifyGateway()):
            return self._submit(item_id=self.classification_item.id).json()['data']

    def test_분류는_1순위_클래스가_불량이면_이상이다(self):
        self._map_classifier()
        payload = self._classify('defect')
        self.assertEqual((payload['status'], payload['inspection_type'], payload['abnormal']),
                         ('SUCCESS', 'CLASSIFICATION', True))
        self.assertEqual(payload['classification'], {'label': 'defect', 'name': '불량', 'score': 0.97})
        self.assertEqual((payload['defects'], payload['anomaly_score'], payload['threshold']), ([], None, None))
        normal = self._classify('normal', 0.88)
        self.assertEqual((normal['abnormal'], normal['classification']['name']), (False, '정상'))

    def test_검사항목에_없는_라벨은_이상으로_본다(self):
        self._map_classifier()
        payload = self._classify('crack')
        self.assertEqual((payload['abnormal'], payload['classification']),
                         (True, {'label': 'crack', 'name': 'crack', 'score': 0.97}))

    def test_분류가_아니면_classification_은_null_이고_상세에는_분류_결과가_있다(self):
        from app.views.vision.inspection import _detail

        self.assertIsNone(self._submit().json()['data']['classification'])
        self._map_classifier()
        payload = self._classify('defect')
        with tenant_atomic(self.tenant):
            self.assertEqual(_detail(payload['id'])['classification'], '불량 (0.97)')

    def test_bbox_모양이_틀리면_Defect_생성에서_막는다(self):
        from domain.services.vision.gateway import Defect

        # GPU Server 응답이 그대로 Client 로 나가는 자리다. 틀린 좌표가 나가면
        # 작업자가 엉뚱한 위치를 불량으로 본다.
        for wrong in ([120, 40, 210, 95], {'x': 1, 'y': 2, 'w': 3, 'h': 4}, {}):
            with self.assertRaises(ValueError, msg=repr(wrong)):
                Defect(class_name='scratch', confidence=0.93, bbox=wrong)


class MeasurementTestCase(ClientApiTestCase):
    """치수 측정 — 클라이언트가 잰 값을 서버가 측정점 규격으로 판정한다(설계 2026-10-20)."""

    def setUp(self):
        super().setUp()
        with tenant_atomic(self.tenant):
            self.dim = InspectionItem.objects.create(tenant=self.tenant, code='DIM', name='Rotor 치수',
                                                     task_type=InspectionItem.TaskType.MEASUREMENT)
            for order, (code, nominal) in enumerate((('A', '540'), ('C', '154'))):
                MeasurementPoint.objects.create(tenant=self.tenant, item=self.dim, code=code, name='치수 ' + code,
                                                nominal=Decimal(nominal), lower=Decimal(nominal) - 1,
                                                upper=Decimal(nominal) + 1, sort_order=order)

    def _measure(self, measurements, item_id=None, request_id=None, **extra):
        metadata = {'request_id': request_id or str(uuid.uuid4()), 'inspection_item_id': item_id or self.dim.id,
                    'measurements': measurements, **extra}
        return self.http.post('/api/v1/inspections', {'image': io.BytesIO(jpeg_bytes()),
                                                      'metadata': json.dumps(metadata)}, **self._headers())


class MeasurementCatalogTest(MeasurementTestCase):
    def items(self, query=''):
        payload = self.http.get('/api/v1/catalog' + query, **self._headers()).json()['data']
        return {i['code']: i for i in payload['processes'][0]['products'][0]['inspection_items']}

    def test_요청한_클라이언트에만_측정점과_함께_나간다(self):
        # 모르는 유형을 받으면 깨지는 Client(0.1.6)가 있다 — 분류와 같은 방식이다(DEC-031)
        self.assertNotIn('DIM', self.items())
        self.assertNotIn('DIM', self.items('?include=classification'))
        items = self.items('?include=measurement')
        self.assertNotIn('SORT', items)
        self.assertEqual(items['DIM']['inspection_type'], 'MEASUREMENT')
        self.assertEqual(items['DIM']['measurement_points'][0], {
            'code': 'A', 'name': '치수 A', 'nominal': 540.0, 'lower': 539.0, 'upper': 541.0, 'unit': 'mm',
            'description': None})
        self.assertNotIn('measurement_points', items['SCRATCH'])
        self.assertEqual(set(self.items('?include=classification,measurement')), {'SCRATCH', 'SORT', 'DIM'})

    def test_측정점이_바뀌면_지문이_바뀐다(self):
        url = '/api/v1/catalog/version?include=measurement'
        first = self.http.get(url, **self._headers()).json()['data']['version']
        with tenant_atomic(self.tenant):
            MeasurementPoint.objects.filter(item=self.dim, code='A').update(upper=Decimal('541.5'))
        self.assertNotEqual(first, self.http.get(url, **self._headers()).json()['data']['version'])


class MeasurementSubmitTest(MeasurementTestCase):
    def test_범위_안이면_추론_없이_바로_SUCCESS_정상이다(self):
        response = self._measure([{'code': 'C', 'value': 155}, {'code': 'A', 'value': 539}])
        self.assertEqual(response.status_code, 201, response.content[:300])
        payload = response.json()['data']
        self.assertEqual((payload['status'], payload['abnormal'], payload['model']), ('SUCCESS', False, None))
        self.assertEqual(payload['inspection_type'], 'MEASUREMENT')
        # 경계값(하한·상한)은 합격이다. 순서는 측정점 순서다
        self.assertEqual(payload['measurements'], [
            {'code': 'A', 'name': '치수 A', 'value': 539, 'lower': 539.0, 'upper': 541.0, 'unit': 'mm', 'ok': True},
            {'code': 'C', 'name': '치수 C', 'value': 155, 'lower': 153.0, 'upper': 155.0, 'unit': 'mm', 'ok': True}])
        inspection = VisionInspection.objects.get(pk=payload['id'])
        self.assertEqual(inspection.measurements, payload['measurements'])
        self.assertIsNotNone(inspection.image_asset, '측정 사진도 증빙으로 남는다')

    def test_하나라도_벗어나면_이상이다(self):
        payload = self._measure([{'code': 'A', 'value': 541.001}, {'code': 'C', 'value': 154}]).json()['data']
        self.assertTrue(payload['abnormal'])
        self.assertEqual([m['ok'] for m in payload['measurements']], [False, True])

    def test_측정값이_계약을_벗어나면_422_이고_아무것도_저장하지_않는다(self):
        cases = {
            '없음': None, '빠진 점': [{'code': 'A', 'value': 540}],
            '모르는 코드': [{'code': 'A', 'value': 540}, {'code': 'C', 'value': 154}, {'code': 'Z', 'value': 1}],
            '중복': [{'code': 'A', 'value': 540}, {'code': 'A', 'value': 540}, {'code': 'C', 'value': 154}],
            '문자열': [{'code': 'A', 'value': '540'}, {'code': 'C', 'value': 154}],
            'bool': [{'code': 'A', 'value': True}, {'code': 'C', 'value': 154}],
            '객체 아님': ['A', {'code': 'C', 'value': 154}], '배열 아님': {'A': 540},
        }
        for label, measurements in cases.items():
            response = self._measure(measurements)
            self.assertEqual(response.status_code, 422, label)
            self.assertEqual(response.json()['error']['code'], 'MEASUREMENT_INVALID', label)
            self.assertFalse(response.json()['error']['retryable'], label)
        self.assertEqual(VisionInspection.objects.count(), 0)
        self.assertEqual(ImageAsset.objects.for_tenant(self.tenant).count(), 0)

    def test_NaN_무한대는_422(self):
        for raw in ('NaN', 'Infinity'):
            metadata = ('{"request_id": "%s", "inspection_item_id": %d, "measurements": '
                        '[{"code": "A", "value": %s}, {"code": "C", "value": 154}]}' % (uuid.uuid4(), self.dim.id, raw))
            response = self.http.post('/api/v1/inspections', {'image': io.BytesIO(jpeg_bytes()), 'metadata': metadata},
                                      **self._headers())
            self.assertEqual(response.json()['error']['code'], 'MEASUREMENT_INVALID', raw)

    def test_다른_유형에_보낸_측정값은_무시한다(self):
        payload = self._measure([{'code': 'A', 'value': 'x'}], item_id=self.item.id).json()['data']
        self.assertEqual(payload['status'], 'RECEIVED')
        self.assertIsNone(payload['measurements'])

    def test_배율_정보를_남기고_객체가_아니면_METADATA_INVALID(self):
        ok = [{'code': 'A', 'value': 540}, {'code': 'C', 'value': 154}]
        calibration = {'method': 'REFERENCE', 'mm_per_px': 0.2831, 'reference': 'CAL-100'}
        payload = self._measure(ok, calibration=calibration).json()['data']
        self.assertEqual(VisionInspection.objects.get(pk=payload['id']).calibration, calibration)
        for wrong in ('REFERENCE', [1], {'method': 'R' * 51}):
            response = self._measure(ok, calibration=wrong)
            self.assertEqual(response.json()['error']['code'], 'METADATA_INVALID', repr(wrong))

    def test_같은_request_id_재전송은_처음_결과를_준다(self):
        request_id = str(uuid.uuid4())
        first = self._measure([{'code': 'A', 'value': 540}, {'code': 'C', 'value': 154}], request_id=request_id)
        again = self._measure([{'code': 'A', 'value': 999}, {'code': 'C', 'value': 154}], request_id=request_id)
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertFalse(again.json()['data']['abnormal'])


class HeatmapTest(ClientApiTestCase):
    def test_인증이_필요하다(self):
        inspection_id = self._submit().json()['data']['id']
        response = self.http.get(f'/api/v1/inspections/{inspection_id}/heatmap')
        self.assertEqual(response.status_code, 401)

    def test_없는_검사는_INSPECTION_NOT_FOUND(self):
        response = self.http.get('/api/v1/inspections/no-such-id/heatmap',
                                 **self._headers())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'INSPECTION_NOT_FOUND')

    def test_남의_검사는_INSPECTION_NOT_FOUND(self):
        inspection_id = self._submit().json()['data']['id']
        other_key = secrets.token_urlsafe(24)
        with tenant_atomic(self.tenant):
            VisionClient.objects.create(
                client_id='CLIENT-OTHER', name='다른 Client',
                api_key_hash=hashlib.sha256(other_key.encode()).hexdigest())
        response = self.http.get(f'/api/v1/inspections/{inspection_id}/heatmap',
                                 HTTP_X_CLIENT_ID='CLIENT-OTHER', HTTP_X_API_KEY=other_key)
        self.assertEqual(response.status_code, 404)
        # 남의 것인지 아예 없는지 구분해 주지 않는다.
        self.assertEqual(response.json()['error']['code'], 'INSPECTION_NOT_FOUND')

    def test_내_검사라도_heatmap_이_없으면_HEATMAP_NOT_FOUND(self):
        inspection_id = self._submit().json()['data']['id']
        response = self.http.get(f'/api/v1/inspections/{inspection_id}/heatmap',
                                 **self._headers())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'HEATMAP_NOT_FOUND')

    def test_응답에_heatmap_url_을_넣지_않는다(self):
        # 필드가 없으면 Client 는 이 Endpoint 를 호출하지 않는다 — Heatmap 이 없는 검사의 계약이다.
        self.assertNotIn('heatmap_url', self._submit().json()['data'])


class AnomalyHeatmapTest(ClientApiTestCase):
    """이상 탐지 SUCCESS 의 Heatmap — 원본 위에 겹친 원본 크기 JPEG 를 저장하고 §8 경로로 내준다."""

    def setUp(self):
        super().setUp()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        with tenant_atomic(self.tenant):
            self.anomaly_item = InspectionItem.objects.create(
                tenant=self.tenant, code='SURFACE', name='표면',
                task_type=InspectionItem.TaskType.ANOMALY_DETECTION)
            model = VisionModel.objects.create(
                name='fan-panel', inspection_type=VisionModel.InspectionType.ANOMALY,
                version='latest', artifact_path='', runtime='wezard')
            VisionItemModelMapping.objects.create(item=self.anomaly_item, model=model)

    def _submit_anomaly(self, heatmap_png):
        from domain.services.vision.gateway import InferenceResult

        class FakeGateway:
            def infer(self, **kwargs):
                return InferenceResult(abnormal=True, model_name='fan-panel', model_version='2', inference_ms=30,
                                       anomaly_score=50.0, threshold=41.1, heatmap_png=heatmap_png)

        with patch('domain.services.vision.inspection.get_inference_gateway', return_value=FakeGateway()):
            return self._submit(item_id=self.anomaly_item.id).json()['data']

    def _heatmap(self, data):
        response = self.http.get(data['heatmap_url'], **self._headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        return Image.open(io.BytesIO(b''.join(response.streaming_content)))

    def test_SUCCESS_응답과_by_request_에_heatmap_url_이_있다(self):
        data = self._submit_anomaly(png_bytes((64, 48)))
        self.assertEqual(data['status'], 'SUCCESS')
        self.assertEqual(data['heatmap_url'], f'/api/v1/inspections/{data["id"]}/heatmap')
        again = self.http.get(f'/api/v1/inspections/by-request/{data["request_id"]}', **self._headers()).json()['data']
        self.assertEqual(again['heatmap_url'], data['heatmap_url'])

    def test_Heatmap_은_원본_크기의_겹친_JPEG_다(self):
        image = self._heatmap(self._submit_anomaly(png_bytes((64, 48))))
        self.assertEqual((image.format, image.size), ('JPEG', (64, 48)))
        # 원본(파랑)과 색 지도(빨강)를 겹쳤으므로 어느 한쪽 색 그대로가 아니다.
        red, _, blue = image.convert('RGB').getpixel((32, 24))
        self.assertTrue(red > 60 and blue > 60, (red, blue))

    def test_색_지도_크기가_달라도_원본_크기로_맞춘다(self):
        self.assertEqual(self._heatmap(self._submit_anomaly(png_bytes((32, 24)))).size, (64, 48))

    def test_Heatmap_을_못_만들면_판정만_내고_heatmap_url_은_없다(self):
        data = self._submit_anomaly(b'not-a-png')
        self.assertEqual((data['status'], data['abnormal']), ('SUCCESS', True))
        self.assertNotIn('heatmap_url', data)
        response = self.http.get(f'/api/v1/inspections/{data["id"]}/heatmap', **self._headers())
        self.assertEqual(response.json()['error']['code'], 'HEATMAP_NOT_FOUND')

    def test_이미지를_지우면_Heatmap_파일도_지운다(self):
        from domain.services.data.image import ImageService

        data = self._submit_anomaly(png_bytes((64, 48)))
        with tenant_atomic(self.tenant):
            inspection = VisionInspection.objects.get(pk=data['id'])
            path = Path(inspection.heatmap.path)
            self.assertTrue(path.is_file())
            ImageService.delete_image(inspection.image_asset, actor=None)
            inspection.refresh_from_db()
        self.assertFalse(path.exists())
        self.assertFalse(inspection.heatmap)


class OverlayTest(ClientApiTestCase):
    """`visible` 은 세 곳에서 같은 뜻이어야 한다 — 카탈로그·Overlay·이미지."""

    def _overlay(self, visible=True):
        with tenant_atomic(self.tenant):
            return VisionOverlay.objects.create(
                item=self.item, version=3, visible=visible, opacity=0.7,
                image=SimpleUploadedFile('guide.png', png_bytes(), content_type='image/png'))

    def _catalog_overlay(self):
        payload = self.http.get('/api/v1/catalog', **self._headers()).json()['data']
        items = payload['processes'][0]['products'][0]['inspection_items']
        return next(row['overlay'] for row in items if row['id'] == self.item.id)

    def test_보이는_Overlay_는_image_상대경로와_이미지를_준다(self):
        self._overlay(visible=True)
        response = self.http.get(f'/api/v1/overlays/{self.item.id}', **self._headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['image'], f'/api/v1/overlays/{self.item.id}/image')
        image = self.http.get(f'/api/v1/overlays/{self.item.id}/image', **self._headers())
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image['Content-Type'].startswith('image/'))

    def test_숨긴_Overlay_는_이미지도_404(self):
        # /overlays/{id} 는 404 인데 /image 가 200 이면, 숨긴 가이드가 그대로 나간다.
        self._overlay(visible=False)
        self.assertEqual(
            self.http.get(f'/api/v1/overlays/{self.item.id}', **self._headers()).status_code, 404)
        response = self.http.get(f'/api/v1/overlays/{self.item.id}/image', **self._headers())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'OVERLAY_NOT_FOUND')

    def test_카탈로그는_보이는_Overlay_의_version_을_낸다(self):
        self._overlay(visible=True)
        self.assertEqual(self._catalog_overlay(), {'available': True, 'version': 3})

    def test_카탈로그는_숨긴_Overlay_를_없는_것과_같게_낸다(self):
        # available: false 와 version: 3 이 같이 나가면 모순이다. Client 의 Overlay
        # 캐시 키가 version 이라 보이지 않는 것을 가리키게 된다.
        self._overlay(visible=False)
        self.assertEqual(self._catalog_overlay(), {'available': False, 'version': None})

    def test_Overlay_가_없으면_available_false(self):
        self.assertEqual(self._catalog_overlay(), {'available': False, 'version': None})


class DistributionTestCase(TestCase):
    """배포물 Endpoint 는 인증도 테넌트도 쓰지 않는다. 가짜 폴더만 필요하다.

    1GB 실파일은 쓰지 않는다 — 수십 바이트로 목록·Range 동작이 다 드러난다.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='dist-test-'))
        (self.root / 'licenses').mkdir()
        (self.root / 'licenses' / 'fake-src.tar.xz').write_bytes(b'0123456789')
        (self.root / 'licenses' / 'SHA256SUMS.txt').write_text(
            '{}  fake-src.tar.xz\n'.format('a' * 64), encoding='utf-8')
        (self.root / 'client').mkdir()
        # client/ 에는 SHA256SUMS.txt 를 두지 않는다 — sha256 이 null 로 나와야 한다.
        (self.root / 'client' / 'Client-0.1.4.zip').write_bytes(b'zipzipzip')

        self.override = override_settings(DISTRIBUTION_ROOT=self.root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.http = Client()


class DistributionListTest(DistributionTestCase):
    def test_licenses_목록은_인증없이_200(self):
        response = self.http.get('/api/v1/licenses/sources')
        self.assertEqual(response.status_code, 200)
        rows = response.json()['data']
        # 이름순. 'SHA256SUMS.txt' < 'fake-src.tar.xz'
        self.assertEqual([row['filename'] for row in rows],
                         ['SHA256SUMS.txt', 'fake-src.tar.xz'])

    def test_목록_항목은_4개_필드를_낸다(self):
        rows = self.http.get('/api/v1/licenses/sources').json()['data']
        archive = next(row for row in rows if row['filename'] == 'fake-src.tar.xz')
        self.assertEqual(archive['size_bytes'], 10)
        self.assertEqual(archive['sha256'], 'a' * 64)
        self.assertEqual(archive['download_url'],
                         '/api/v1/licenses/sources/fake-src.tar.xz')

    def test_SHA256SUMS_에_없는_파일은_sha256_이_null(self):
        rows = self.http.get('/api/v1/client-packages').json()['data']
        self.assertEqual(rows[0]['filename'], 'Client-0.1.4.zip')
        self.assertIsNone(rows[0]['sha256'])
        self.assertEqual(rows[0]['download_url'],
                         '/api/v1/client-packages/Client-0.1.4.zip')

    def test_SHA256SUMS_자신도_목록에_나온다(self):
        rows = self.http.get('/api/v1/licenses/sources').json()['data']
        checksum = next(row for row in rows if row['filename'] == 'SHA256SUMS.txt')
        self.assertIsNone(checksum['sha256'])

    def test_폴더가_없으면_빈_목록이다(self):
        empty = Path(tempfile.mkdtemp(prefix='dist-empty-'))
        self.addCleanup(shutil.rmtree, empty, True)
        with override_settings(DISTRIBUTION_ROOT=empty):
            response = self.http.get('/api/v1/licenses/sources')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], [])

    def test_형식이_틀린_SHA256SUMS_줄은_버린다(self):
        (self.root / 'licenses' / 'SHA256SUMS.txt').write_text(
            'deadbeef  fake-src.tar.xz\n', encoding='utf-8')   # 64자가 아니다
        rows = self.http.get('/api/v1/licenses/sources').json()['data']
        archive = next(row for row in rows if row['filename'] == 'fake-src.tar.xz')
        self.assertIsNone(archive['sha256'])


class DistributionDownloadTest(DistributionTestCase):
    URL = '/api/v1/licenses/sources/fake-src.tar.xz'

    @staticmethod
    def _body(response):
        if response.streaming:
            return b''.join(response.streaming_content)
        return response.content

    def test_인증없이_전체를_받는다(self):
        response = self.http.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._body(response), b'0123456789')
        self.assertEqual(response['Accept-Ranges'], 'bytes')
        self.assertIn('attachment', response['Content-Disposition'])

    def test_Range_로_이어받는다(self):
        response = self.http.get(self.URL, HTTP_RANGE='bytes=5-')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self._body(response), b'56789')
        self.assertEqual(response['Content-Range'], 'bytes 5-9/10')
        self.assertEqual(response['Content-Length'], '5')

    def test_닫힌_구간_Range(self):
        response = self.http.get(self.URL, HTTP_RANGE='bytes=2-4')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self._body(response), b'234')
        self.assertEqual(response['Content-Range'], 'bytes 2-4/10')

    def test_끝에서부터_세는_Range(self):
        response = self.http.get(self.URL, HTTP_RANGE='bytes=-3')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(self._body(response), b'789')

    def test_파일_밖_Range_는_416(self):
        response = self.http.get(self.URL, HTTP_RANGE='bytes=999-')
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response['Content-Range'], 'bytes */10')
        self.assertEqual(response.json()['error']['code'], 'RANGE_NOT_SATISFIABLE')

    def test_다중_Range_는_전체를_보낸다(self):
        # multipart/byteranges 를 만들지 않는다. curl -C - 는 단일 범위만 쓴다.
        response = self.http.get(self.URL, HTTP_RANGE='bytes=0-1,5-6')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._body(response), b'0123456789')

    def test_해석할_수_없는_Range_는_전체를_보낸다(self):
        response = self.http.get(self.URL, HTTP_RANGE='items=0-1')
        self.assertEqual(response.status_code, 200)

    @override_settings(FILE_ACCEL_REDIRECT=True)
    def test_운영에서는_전송을_nginx_에_넘긴다(self):
        # Django(sync 워커)가 1GB 를 흘려보내면 --timeout 을 넘겨 워커가 죽고 전송이 끊겼다.
        for range_header in ({}, {'HTTP_RANGE': 'bytes=5-'}):   # Range 도 nginx 가 처리한다
            response = self.http.get(self.URL, **range_header)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['X-Accel-Redirect'], '/_protected/distribution/licenses/fake-src.tar.xz')
            self.assertEqual(response.content, b'')
            self.assertIn('attachment', response['Content-Disposition'])

    @override_settings(FILE_ACCEL_REDIRECT=True)
    def test_운영에서도_파일_밖_Range_는_계약대로_416_봉투(self):
        response = self.http.get(self.URL, HTTP_RANGE='bytes=999-')
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response.json()['error']['code'], 'RANGE_NOT_SATISFIABLE')
        self.assertNotIn('X-Accel-Redirect', response)

    def test_없는_파일은_SOURCE_ARCHIVE_NOT_FOUND(self):
        response = self.http.get('/api/v1/licenses/sources/nope.tar.xz')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'SOURCE_ARCHIVE_NOT_FOUND')

    def test_없는_Client_배포본은_CLIENT_PACKAGE_NOT_FOUND(self):
        response = self.http.get('/api/v1/client-packages/nope.zip')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'CLIENT_PACKAGE_NOT_FOUND')

    def test_Client_배포본을_받는다(self):
        response = self.http.get('/api/v1/client-packages/Client-0.1.4.zip')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._body(response), b'zipzipzip')

    def test_경로_이탈은_내려주지_않는다(self):
        # 이름을 경로로 조립하지 않고 목록에서 찾으므로 폴더 밖으로 나갈 수 없다.
        secret = self.root / 'secret.txt'
        secret.write_bytes(b'do-not-serve')
        for path in ('/api/v1/licenses/sources/..',
                     '/api/v1/licenses/sources/../secret.txt',
                     '/api/v1/licenses/sources/..%2Fsecret.txt'):
            with self.subTest(path=path):
                response = self.http.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b'do-not-serve', self._body(response))


class ReceiveRollbackFilesTest(ClientApiTestCase):
    """접수가 중간에 실패하면 DB 행과 함께 이미지·썸네일 파일도 남지 않는다."""

    def setUp(self):
        super().setUp()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)

    def _files(self):
        return [p for p in Path(settings.MEDIA_ROOT).rglob('*') if p.is_file()]

    def test_검사_행_저장이_실패하면_파일을_지운다(self):
        from django.db import IntegrityError
        with patch.object(VisionInspection.objects, 'create', side_effect=IntegrityError('x')):
            response = self._submit()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self._files(), [])

    def test_Heatmap_을_쓴_뒤_저장이_실패해도_Heatmap_파일을_지운다(self):
        from domain.services.vision.gateway import InferenceResult

        with tenant_atomic(self.tenant):
            item = InspectionItem.objects.create(tenant=self.tenant, code='SURFACE', name='표면',
                                                 task_type=InspectionItem.TaskType.ANOMALY_DETECTION)
            model = VisionModel.objects.create(name='fan-panel', inspection_type=VisionModel.InspectionType.ANOMALY,
                                               version='latest', artifact_path='', runtime='wezard')
            VisionItemModelMapping.objects.create(item=item, model=model)

        class FakeGateway:
            def infer(self, **kwargs):
                return InferenceResult(abnormal=True, model_name='fan-panel', model_version='2',
                                       anomaly_score=50.0, threshold=41.1, heatmap_png=png_bytes((64, 48)))

        original_save = VisionInspection.save

        def save_fails_with_heatmap(inspection, *args, **kwargs):
            if inspection.heatmap:
                raise RuntimeError('x')
            return original_save(inspection, *args, **kwargs)

        with patch('domain.services.vision.inspection.get_inference_gateway', return_value=FakeGateway()), \
                patch.object(VisionInspection, 'save', save_fails_with_heatmap):
            response = self._submit(item_id=item.id)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self._files(), [])

    def test_추론_단계가_실패해도_파일을_지운다(self):
        from domain.services.vision.inspection import InspectionService
        with patch.object(InspectionService, '_run_inference', side_effect=RuntimeError('x')):
            response = self._submit()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self._files(), [])
