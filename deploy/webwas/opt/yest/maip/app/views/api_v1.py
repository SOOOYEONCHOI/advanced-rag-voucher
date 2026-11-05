"""비전검사 클라이언트용 `/api/v1` 계층.

호출자는 **비전검사 클라이언트**다 — 별도 프로젝트이고 배포물 이름은
`VisionInspectionClient` 다. 현장에 배포된 것은 `base_url` 만 이 서버로
바꾸면 동작해야 한다(DEC-007).

요청·응답 형태의 **정본은 `docs/client/SERVER_API_CONTRACT.md` 다**(DEC-C2).
서버가 그 문서를 관리하고 클라이언트가 맞춘다 — 응답 모양을 바꾸면 문서를
먼저 갱신해 전달한다.

- 응답 봉투: 성공 `{"data": ...}` / 실패 `{"error": {"code","message","retryable"}}`
- 시각: **UTC `Z`**. 서버는 `USE_TZ=False`(naive local)이므로 이 경계에서만 변환한다.
- 인증: `X-Client-ID` + `X-API-Key`(SHA-256 해시 대조)
- idempotency: `request_id` UNIQUE

**합성 공정·제품**: DB 에 공정·제품이 없지만 Client 가
`processes[].products[].inspection_items[]` 중첩을 강제하므로 응답 생성 시점에
고정값 1건씩을 만들어 끼운다. 테이블로 만들지 않는다.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.db import connection, models
from django.http import JsonResponse, StreamingHttpResponse
from django.http.multipartparser import MultiPartParserError
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from app.views.files import sendfile
from domain.models.data import InspectionItem
from domain.models.vision import VisionClient, VisionInspection, VisionOverlay
from domain.services.vision.inspection import (
    InspectionItemNotFound,
    InspectionService,
    MeasurementInvalid,
    RequestIdConflict,
)
from domain.tenancy import current_tenant, tenant_atomic

logger = logging.getLogger(__name__)

# Client 가 강제하는 계층. DB 에는 없고 응답에만 있다.
SYNTHETIC_PROCESS = {'id': 1, 'code': 'ALL', 'name': '전체', 'display_order': 0, 'active': True}
# 카탈로그 `include` 로 요청해야 내보내는 유형.
OPT_IN_TYPES = {'CLASSIFICATION', 'MEASUREMENT'}
SYNTHETIC_PRODUCT = {'id': 1, 'process_id': 1, 'code': 'ALL', 'name': '전체',
                     'description': None, 'active': True}

MAX_IMAGE_BYTES = 32 * 1024 * 1024  # Client `_MAX_IMAGE_BYTES` 와 같아야 한다
# multipart 경계 문자열과 다른 폼 필드가 차지하는 여유분.
MULTIPART_SLACK_BYTES = 1024 * 1024
_BODY_METHODS = {'POST', 'PUT', 'PATCH'}

# (receive_capture 인자명, 계약 필드명, 상한). 상한은 domain/models/vision.py 의
# 컬럼 길이와 **같아야 한다**. 넘으면 PostgreSQL 이 DataError 를 내는데 그것은
# IntegrityError 가 아니어서 500 retryable=true 로 나가고, Client 는 같은 결과가
# 날 요청을 재시도 한도까지 다시 보낸다.
METADATA_LIMITS = (
    ('request_id', 'request_id', 36),
    ('client_version', 'client_version', 50),
    ('camera_vendor', 'camera.vendor', 100),
    ('camera_serial', 'camera.serial_number', 100),
)
# metadata.calibration 의 글자 값 상한. 객체째 JSON 컬럼에 남으므로 크기를 묶어 둔다.
CALIBRATION_TEXT_LIMIT = 50


class MetadataError(Exception):
    """metadata 가 계약을 벗어났다. 전부 422 `METADATA_INVALID` 다.

    메시지는 우리가 쓴 문장이다. 파이썬 예외 원문을 넣지 않는다 — 내부 구현이
    Client 로 나간다.
    """


def parse_metadata(raw):
    """`metadata` 문자열 → `receive_capture` 에 그대로 넘길 dict.

    검증은 **이미지 파일을 쓰기 전에** 끝난다. 뒤로 미루면 거절된 요청이
    저장소에 파일만 남긴다 — 파일 쓰기는 트랜잭션 롤백 대상이 아니다.
    """
    if not raw:
        raise MetadataError('metadata 가 없습니다.')
    try:
        metadata = json.loads(raw)
    except json.JSONDecodeError:
        raise MetadataError('metadata 형식이 올바르지 않습니다.')
    if not isinstance(metadata, dict):
        raise MetadataError('metadata 는 JSON 객체여야 합니다.')

    # 없거나 null 이면 빈 객체. [] · "" · 0 · false 도 객체가 아니므로 거절한다
    camera = metadata.get('camera')
    if camera is None:
        camera = {}
    if not isinstance(camera, dict):
        raise MetadataError('camera 는 JSON 객체여야 합니다.')

    request_id = str(metadata.get('request_id') or '')
    item_id = metadata.get('inspection_item_id')
    if not request_id or item_id is None:
        raise MetadataError('request_id 와 inspection_item_id 가 필요합니다.')
    # int() 는 12.7 → 12, True → 1 로 읽어 다른 비전검사항목이 된다 — 정수로 읽히는 값만 받는다
    if isinstance(item_id, bool) or (isinstance(item_id, float) and not item_id.is_integer()):
        raise MetadataError('inspection_item_id 는 정수여야 합니다.')
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        raise MetadataError('inspection_item_id 는 정수여야 합니다.')
    try:
        capture_timestamp = parse_utc(metadata.get('capture_timestamp'))
    except (TypeError, ValueError):
        raise MetadataError('capture_timestamp 는 ISO 8601 시각이어야 합니다.')

    # 없거나 null 이면 없음. 치수 측정 항목에서 기준물로 정한 배율이다(선택, 설계 Q3).
    calibration = metadata.get('calibration')
    if calibration is not None:
        if not isinstance(calibration, dict):
            raise MetadataError('calibration 은 JSON 객체여야 합니다.')
        if any(isinstance(v, str) and len(v) > CALIBRATION_TEXT_LIMIT for v in calibration.values()):
            raise MetadataError(f'calibration 의 글자 값은 {CALIBRATION_TEXT_LIMIT}자 이하여야 합니다.')

    fields = {
        'request_id': request_id,
        'inspection_item_id': item_id,
        'capture_timestamp': capture_timestamp,
        'client_version': metadata.get('client_version') or None,
        'camera_vendor': camera.get('vendor') or None,
        'camera_serial': camera.get('serial_number') or None,
        # 측정점과 맞는지는 비전검사항목을 알아야 본다 — InspectionService 가 이미지를 쓰기 전에 검증한다.
        'measurements': metadata.get('measurements'),
        'calibration': calibration,
    }
    for key, label, limit in METADATA_LIMITS:
        value = fields[key]
        # 자르지 않는다. request_id 를 자르면 Client 가 보낸 id 로 재조회할 수 없는
        # 기록이 생긴다.
        if value is not None and len(str(value)) > limit:
            raise MetadataError(f'{label} 은 {limit}자 이하여야 합니다.')
    return fields


def to_utc_z(value):
    """naive local datetime → UTC `Z` 문자열.

    `USE_TZ=False` 라 DB 값은 서버 지역시각 naive 다. Client 계약은 UTC `Z` 이므로
    여기서만 변환한다 — 다른 곳에서 변환하면 두 번 바뀐다.
    """
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.astimezone(dt_timezone.utc).isoformat().replace('+00:00', 'Z')


def parse_utc(value):
    """Client 가 보낸 ISO 시각 → 서버 지역시각 naive."""
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        return parsed
    return timezone.make_naive(parsed, timezone.get_current_timezone())


def error(code, message, status, retryable=False):
    return JsonResponse(
        {'error': {'code': code, 'message': message, 'retryable': retryable}},
        status=status, json_dumps_params={'ensure_ascii': False})


def data(payload, status=200):
    return JsonResponse({'data': payload}, status=status,
                        json_dumps_params={'ensure_ascii': False})


class ClientApiView(View):
    """`X-Client-ID` + `X-API-Key` 로 인증한다.

    세션이 아니라 API Key 인증이므로 조직 컨텍스트를 미들웨어가 채우지 않는다.
    여기서 `tenant_atomic()` 을 연다 — RLS 가 걸려 있어 밖에서는 0행이다.
    """

    require_auth = True
    # health 와 배포물 Endpoint 는 테넌트 데이터를 읽지 않는다. 이 플래그가 없으면
    # health 가 DB 장애 때 tenant_atomic() 진입에서 먼저 터져 503 이 아니라 500 이 된다.
    use_tenant = True
    # 키를 대조할 테이블과 인증된 행을 실을 request 속성. 학습 플랫폼 API 는 IntegrationClient 를 본다
    # (app/views/api_v1_datasets.py). 테이블이 달라 한쪽 키로 다른 쪽 API 를 부를 수 없다.
    client_model = VisionClient
    client_attr = 'vision_client'

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        rejection = self._precheck(request)
        if rejection is not None:
            return rejection
        if self.require_auth:
            client, failure = self._authenticate(request)
            if client is None:
                return error(failure, '인증에 실패했습니다.', 401)
            setattr(request, self.client_attr, client)
        try:
            if not self.use_tenant:
                return super().dispatch(request, *args, **kwargs)
            with tenant_atomic():
                return super().dispatch(request, *args, **kwargs)
        except Exception:
            logger.exception('/api/v1 처리 실패: %s', request.path)
            return error('INTERNAL_ERROR', '서버 오류가 발생했습니다.', 500, retryable=True)

    def http_method_not_allowed(self, request, *args, **kwargs):
        # Django 기본은 본문 없는 405 HTML 이다. Client 0.1.6 은 봉투 없는 4xx 를
        # 재시도하지 않고 "서버 응답 오류"로 멈추므로 여기도 봉투로 답한다.
        response = error('METHOD_NOT_ALLOWED', '허용하지 않는 메서드입니다.', 405)
        response['Allow'] = ', '.join(self._allowed_methods())
        return response

    @staticmethod
    def _precheck(request):
        """인증보다 **먼저** 거절해야 하는 것.

        본문을 읽지 않고 선언된 길이로만 판단한다. 인증을 통과하지 못할 요청이
        수십 MB 를 먼저 쓰게 하지 않으려는 것이다. 상한을 따로 적지 않고
        MAX_IMAGE_BYTES 에서 계산하는 것은, 상수를 올렸을 때 이 가드가 먼저 막아
        원인을 찾기 어려워지는 일을 막으려는 것이다.
        """
        if request.method not in _BODY_METHODS:
            return None
        declared = request.META.get('CONTENT_LENGTH')
        if not declared:
            return error('LENGTH_REQUIRED', '요청 본문 길이(Content-Length)가 필요합니다.', 411)
        try:
            length = int(declared)
        except (TypeError, ValueError):
            return error('LENGTH_REQUIRED', '요청 본문 길이가 올바르지 않습니다.', 411)
        if length > MAX_IMAGE_BYTES + MULTIPART_SLACK_BYTES:
            return error('IMAGE_TOO_LARGE', '요청 본문이 상한을 넘었습니다.', 413)
        return None

    @classmethod
    def _authenticate(cls, request):
        """`(client, 실패코드)`. 성공하면 `(client, None)`.

        "헤더가 안 갔다"(`AUTH_REQUIRED`)와 "키가 틀렸다"(`AUTH_INVALID`)를 가른다 —
        Client 는 둘을 같은 방식으로 처리하지만 현장 장애 진단에 필요하다(R5).
        없는 Client 와 비활성 Client 는 구분하지 않는다. 존재 여부를 알려 주지 않는다.
        """
        client_id = request.headers.get('X-Client-ID', '')
        api_key = request.headers.get('X-API-Key', '')
        if not client_id or not api_key:
            return None, 'AUTH_REQUIRED'
        client = cls.client_model.objects.filter(client_id=client_id, active=True).first()
        if client is None:
            # API Key 는 어떤 형태로도 남기지 않는다. client_id 만 남긴다.
            logger.info('/api/v1 인증 실패(없거나 비활성): client_id=%s', client_id)
            return None, 'AUTH_INVALID'
        digest = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        # 타이밍 공격을 피하려 상수 시간 비교를 쓴다.
        if not hmac.compare_digest(digest, client.api_key_hash):
            logger.info('/api/v1 인증 실패(키 불일치): client_id=%s', client_id)
            return None, 'AUTH_INVALID'
        cls.client_model.objects.filter(pk=client.pk).update(last_seen_at=timezone.now())
        return client, None


class HealthView(ClientApiView):
    """`GET /api/v1/health` — 인증 없이 호출한다(Client 연결 확인).

    DB `SELECT 1` 과 Storage 쓰기/삭제를 **실제로 수행**한 뒤 응답한다. 하나라도
    실패하면 503 이고, 이 503 은 `/api/v1` 에서 오류 봉투가 아닌 유일한 응답이다 —
    Client 가 본문의 `components` 를 읽어 무엇이 죽었는지 보여 준다.
    """

    require_auth = False
    # DB 가 죽은 상황을 보고하는 뷰다. tenant_atomic() 안에서 돌면 진입 자체가
    # 먼저 터져 dispatch 의 except 가 500 INTERNAL_ERROR 로 바꿔 버린다.
    use_tenant = False
    http_method_names = ['get']

    def get(self, request):
        components = {'database': self._check_database(), 'storage': self._check_storage()}
        healthy = all(value == 'ok' for value in components.values())
        payload = {
            'status': 'ok' if healthy else 'degraded',
            'components': components,
            'version': settings.APP_VERSION,
            'timestamp': to_utc_z(timezone.now()),
        }
        return JsonResponse(payload, status=200 if healthy else 503,
                            json_dumps_params={'ensure_ascii': False})

    @staticmethod
    def _check_database():
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception:
            logger.exception('health: DB 점검 실패')
            return 'error'
        return 'ok'

    @staticmethod
    def _check_storage():
        probe = Path(settings.STORAGE_ROOT) / '.healthcheck'
        try:
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(b'ok')
            probe.unlink()
        except OSError:
            logger.exception('health: Storage 점검 실패')
            return 'error'
        return 'ok'


class CatalogView(ClientApiView):
    """`GET /api/v1/catalog` — 공정→제품→검사항목 중첩."""

    http_method_names = ['get']

    def get(self, request):
        return data(self.build(request))

    @staticmethod
    def build(request):
        # 0.1.6 이하 Client 는 CLASSIFICATION 을 모른다 — 분류·치수 측정은 `include` 로 요청한 Client 에만
        # 내보낸다(DEC-031). `include=classification,measurement` 처럼 쉼표로 함께 준다.
        included = set(request.GET.get('include', '').split(','))
        items = []
        # 태블릿 촬영 항목은 디지털 양식 사진 넣기로만 쓴다 — 거치대 Client 에는 내보내지 않는다(R22 §5-2)
        queryset = (InspectionItem.objects.for_tenant(current_tenant())
                    .filter(status=InspectionItem.Status.ACTIVE, capture_method=InspectionItem.CaptureMethod.RIG)
                    .select_related('overlay').prefetch_related('measurement_points')
                    .order_by('display_order', 'id'))
        for item in queryset:
            inspection_type = item.client_inspection_type
            if inspection_type in OPT_IN_TYPES and inspection_type.lower() not in included:
                continue
            overlay = getattr(item, 'overlay', None)
            entry = {
                'id': item.id,
                'product_id': SYNTHETIC_PRODUCT['id'],
                'code': item.code,
                'name': item.name,
                'description': item.description or None,
                'inspection_type': inspection_type,
                'display_order': item.display_order,
                'active': True,
                # 숨긴 Overlay 는 없는 것과 같은 모양이다. version 만 나가면 Client 의
                # 캐시 키가 보이지 않는 Overlay 를 가리킨다.
                'overlay': ({'available': True, 'version': overlay.version}
                            if overlay and overlay.visible
                            else {'available': False, 'version': None}),
            }
            if inspection_type == 'MEASUREMENT':
                # 치수 측정 항목에만 키가 있다. 측정점 규격이 바뀌면 지문도 바뀐다.
                entry['measurement_points'] = [
                    {'code': p.code, 'name': p.name, 'nominal': float(p.nominal), 'lower': float(p.lower),
                     'upper': float(p.upper), 'unit': p.unit, 'description': p.description or None}
                    for p in item.measurement_points.all()]
            items.append(entry)

        product = dict(SYNTHETIC_PRODUCT, inspection_items=items)
        process = dict(SYNTHETIC_PROCESS, products=[product])
        return {'version': CatalogView.fingerprint(items), 'processes': [process]}

    @staticmethod
    def fingerprint(items):
        """카탈로그 지문. 내용이 바뀔 때만 달라져야 한다 — Client 캐시 무효화 기준."""
        payload = json.dumps(items, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


class CatalogVersionView(CatalogView):
    """`GET /api/v1/catalog/version` — 지문만. Client 가 폴링한다."""

    def get(self, request):
        snapshot = self.build(request)
        return data({'version': snapshot['version'], 'updated_at': to_utc_z(timezone.now())})


class InspectionCreateView(ClientApiView):
    """`POST /api/v1/inspections` — 검사 요청.

    `multipart/form-data`: `image`(파일) + `metadata`(JSON 문자열).
    `process_id`·`product_id` 는 **받되 검증하지 않는다**.
    """

    http_method_names = ['post']

    def post(self, request):
        try:
            fields = parse_metadata(request.POST.get('metadata'))
        except MetadataError as exc:
            return error('METADATA_INVALID', str(exc), 422)
        except MultiPartParserError:
            # 깨진 multipart 는 다시 보내도 같다 — 500 retryable 로 내보내면 Client 가 재시도한다
            return error('METADATA_INVALID', '요청 본문 형식이 올바르지 않습니다.', 422)

        upload = request.FILES.get('image')
        if upload is None:
            return error('IMAGE_REQUIRED', '이미지가 없습니다.', 422)
        if upload.size > MAX_IMAGE_BYTES:
            return error('IMAGE_TOO_LARGE', '이미지가 너무 큽니다.', 413)

        try:
            inspection, created = InspectionService().receive_capture(
                client=request.vision_client, image_bytes=upload.read(), **fields)
        except InspectionItemNotFound as exc:
            return error('INSPECTION_ITEM_NOT_FOUND', str(exc), 404)
        except RequestIdConflict as exc:
            return error('REQUEST_ID_CONFLICT', str(exc), 409)
        except MeasurementInvalid as exc:
            return error('MEASUREMENT_INVALID', str(exc), 422)
        except ValueError as exc:
            # 여기 남는 ValueError 는 이미지 판정과 저장 거절뿐이다. metadata 쪽은
            # parse_metadata 가 위에서 걷어 갔다.
            return error('IMAGE_INVALID', str(exc), 422)

        return data(serialize_inspection(inspection), status=201 if created else 200)


class InspectionByRequestView(ClientApiView):
    """`GET /api/v1/inspections/by-request/<request_id>` — 재조회."""

    http_method_names = ['get']

    def get(self, request, request_id):
        inspection = VisionInspection.objects.filter(request_id=str(request_id)).first()
        if inspection is None:
            return error('INSPECTION_NOT_FOUND', '검사를 찾을 수 없습니다.', 404)
        if inspection.client_id != request.vision_client.id:
            # 남의 request_id 로 결과를 가져갈 수 없다.
            return error('INSPECTION_NOT_FOUND', '검사를 찾을 수 없습니다.', 404)
        return data(serialize_inspection(inspection))


class InspectionHeatmapView(ClientApiView):
    """`GET /api/v1/inspections/<id>/heatmap`.

    이상 탐지 SUCCESS 때 저장한 Heatmap(원본 위에 색 지도를 겹친 원본 크기 JPEG)을 내준다.
    없으면 `HEATMAP_NOT_FOUND` — 그런 검사는 응답에 `heatmap_url` 이 없어 Client 가 부르지 않는다.
    """

    http_method_names = ['get']

    def get(self, request, inspection_id):
        inspection = VisionInspection.objects.filter(pk=str(inspection_id)).first()
        if inspection is None or inspection.client_id != request.vision_client.id:
            # 존재 여부를 노출하지 않으려 둘을 같은 코드로 답한다.
            return error('INSPECTION_NOT_FOUND', '검사를 찾을 수 없습니다.', 404)
        if inspection.heatmap:
            try:
                return sendfile(inspection.heatmap.path, content_type='image/jpeg')
            except FileNotFoundError:
                logger.warning('Heatmap 파일이 없다: inspection=%s', inspection.id)
        return error('HEATMAP_NOT_FOUND', 'Heatmap 이 없습니다.', 404)


class OverlayView(ClientApiView):
    """`GET /api/v1/overlays/<inspection_item_id>`."""

    http_method_names = ['get']

    def get(self, request, inspection_item_id):
        overlay = VisionOverlay.objects.filter(item_id=inspection_item_id).first()
        if overlay is None or not overlay.visible:
            return error('OVERLAY_NOT_FOUND', 'Overlay 가 없습니다.', 404)
        return data({
            'inspection_item_id': overlay.item_id,
            'version': overlay.version,
            'visible': overlay.visible,
            'opacity': overlay.opacity,
            # Client 는 `/api/v1` 아래 상대 경로만 받는다(server_client.py:152).
            'image': f'/api/v1/overlays/{overlay.item_id}/image',
        })


class OverlayImageView(ClientApiView):
    """`GET /api/v1/overlays/<inspection_item_id>/image`."""

    http_method_names = ['get']

    def get(self, request, inspection_item_id):
        from django.http import FileResponse

        overlay = VisionOverlay.objects.filter(item_id=inspection_item_id).first()
        # visible 을 여기서도 본다. /overlays/{id} 만 404 를 내면 숨긴 가이드가
        # 이미지 경로로 그대로 나간다.
        if overlay is None or not overlay.visible or not overlay.image:
            return error('OVERLAY_NOT_FOUND', 'Overlay 이미지가 없습니다.', 404)
        try:
            return FileResponse(overlay.image.open('rb'))
        except FileNotFoundError:
            return error('OVERLAY_NOT_FOUND', 'Overlay 이미지가 없습니다.', 404)


CHECKSUM_FILENAME = 'SHA256SUMS.txt'
_SHA256_HEX_LENGTH = 64


def distribution_files(folder):
    """`DISTRIBUTION_ROOT/<folder>` **바로 아래** 파일 목록. 하위 폴더는 공개 대상이 아니다.

    `sha256` 은 서버가 계산한 값이 아니라 같은 폴더 `SHA256SUMS.txt` 에 적힌 값이다 —
    1GB 아카이브를 요청마다 해싱하면 목록 조회가 수 초씩 걸린다.

    설정은 **요청 시점에** 읽는다. 모듈 상수로 굳히면 테스트의 `override_settings` 가
    듣지 않아 실제 1GB 파일을 보게 된다.
    """
    root = Path(settings.DISTRIBUTION_ROOT) / folder
    if not root.is_dir():
        return []
    recorded = _recorded_checksums(root)
    return [{'name': path.name, 'path': path, 'size_bytes': path.stat().st_size,
             'sha256': recorded.get(path.name)}
            for path in sorted(root.iterdir(), key=lambda p: p.name) if path.is_file()]


def _recorded_checksums(root):
    """`<해시>  <파일명>`(텍스트)과 `<해시> *<파일명>`(바이너리) 줄을 읽는다."""
    checksum_file = root / CHECKSUM_FILENAME
    if not checksum_file.is_file():
        return {}
    recorded = {}
    for line in checksum_file.read_text(encoding='utf-8', errors='ignore').splitlines():
        parts = line.split()
        # 파일명이 없거나 해시 길이가 다른 줄은 어느 파일의 것인지 알 수 없으므로 버린다.
        if len(parts) == 2 and len(parts[0]) == _SHA256_HEX_LENGTH:
            recorded[parts[1].removeprefix('*')] = parts[0].lower()
    return recorded


class DistributionListView(ClientApiView):
    """배포물 목록.

    **인증을 걸지 않는다.** LGPL 대응 소스를 받을 권리는 바이너리를 받은 사람
    전부에게 있어 API Key 를 요구하면 그 자체가 의무 이행에 조건을 다는 셈이고,
    설치 전 검사 PC 에는 Key 가 없다. 내부망 한정은 방화벽이 지킨다.
    """

    require_auth = False
    use_tenant = False
    http_method_names = ['get']
    folder = None
    url_prefix = None

    def get(self, request):
        return data([{'filename': found['name'],
                      'size_bytes': found['size_bytes'],
                      'sha256': found['sha256'],
                      'download_url': '{}/{}'.format(self.url_prefix, found['name'])}
                     for found in distribution_files(self.folder)])


class LicenseSourceListView(DistributionListView):
    folder = 'licenses'
    url_prefix = '/api/v1/licenses/sources'


class ClientPackageListView(DistributionListView):
    folder = 'client'
    url_prefix = '/api/v1/client-packages'


DOWNLOAD_CHUNK_BYTES = 64 * 1024


def _parse_range(header, size):
    """`Range` 헤더를 `(start, length)` 로 바꾼다.

    `(start, length)` — 부분 전송(206)
    `'invalid'` — 파일 밖 요청(416)
    `None` — 전체 전송(200). 헤더가 없거나 해석할 수 없거나 **다중 범위**인 경우다.

    단일 범위만 본다. 다중 범위(`bytes=0-1,5-6`)는 multipart/byteranges 를 만들어야
    하는데 쓰는 Client 가 없다 — `curl -C -` 도 브라우저 이어받기도 단일 범위다.
    Django 에는 Range 처리가 없어 여기서 직접 한다.
    """
    if not header or not header.startswith('bytes=') or ',' in header:
        return None
    spec = header[len('bytes='):].strip()
    try:
        if spec.startswith('-'):
            # 뒤에서 N 바이트. 파일보다 크게 요청하면 전체를 준다(RFC 9110).
            length = int(spec[1:])
            if length <= 0:
                return 'invalid'
            start = max(size - length, 0)
            return start, size - start
        first, separator, last = spec.partition('-')
        if not separator:
            return None
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return 'invalid'
    return start, min(end, size - 1) - start + 1


def _file_chunks(path, start, length):
    """파일의 일부를 조각내 흘려보낸다. 1GB 를 메모리에 올리지 않는다."""
    with path.open('rb') as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            block = handle.read(min(DOWNLOAD_CHUNK_BYTES, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def ranged_file_response(request, path, size, filename):
    """파일 전체(200) 또는 단일 Range(206). 범위가 파일 밖이면 416 봉투.

    배포물과 학습 플랫폼 스냅샷(app/views/api_v1_datasets.py)이 함께 쓴다.
    """
    requested = _parse_range(request.headers.get('Range'), size)

    if requested == 'invalid':
        response = error('RANGE_NOT_SATISFIABLE', '요청한 범위가 파일 밖입니다.', 416)
        response['Content-Range'] = 'bytes */{}'.format(size)
        response['Accept-Ranges'] = 'bytes'
        return response

    # 운영은 Range 까지 nginx 가 처리한다(sendfile). 범위가 파일 밖이면 위에서 계약대로 416 봉투.
    if requested is None or settings.FILE_ACCEL_REDIRECT:
        response = sendfile(path, as_attachment=True, filename=filename)
        response['Accept-Ranges'] = 'bytes'
        return response

    start, length = requested
    response = StreamingHttpResponse(_file_chunks(path, start, length),
                                     status=206,
                                     content_type='application/octet-stream')
    response['Content-Range'] = 'bytes {}-{}/{}'.format(start, start + length - 1, size)
    response['Content-Length'] = str(length)
    response['Accept-Ranges'] = 'bytes'
    response['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
    return response


class DistributionDownloadView(ClientApiView):
    """배포물 다운로드. 인증을 걸지 않는다 — 목록과 같은 이유다."""

    require_auth = False
    use_tenant = False
    http_method_names = ['get']
    folder = None
    not_found_code = None

    def get(self, request, filename):
        # 이름을 경로로 조립하지 않는다. 목록에서 이름이 같은 파일을 찾으므로
        # `../` 가 섞인 이름은 목록에 있을 수 없고 폴더 밖으로 나갈 방법이 없다.
        found = next((f for f in distribution_files(self.folder) if f['name'] == filename),
                     None)
        if found is None:
            return error(self.not_found_code, '보관 중인 파일이 아닙니다.', 404)

        return ranged_file_response(request, found['path'], found['size_bytes'], found['name'])


class LicenseSourceDownloadView(DistributionDownloadView):
    folder = 'licenses'
    not_found_code = 'SOURCE_ARCHIVE_NOT_FOUND'


class ClientPackageDownloadView(DistributionDownloadView):
    folder = 'client'
    not_found_code = 'CLIENT_PACKAGE_NOT_FOUND'


class V1NotFoundView(View):
    """`/api/v1` 아래 미지 경로.

    봉투 없이 나가면 Client 는 "서버 응답을 해석할 수 없음"으로 처리한다. 이것이
    없으면 2-segment 경로는 범용 `api/<task>/<view>` 에 먹혀 401 HTML, 그 밖은
    Django 기본 404 HTML(DEBUG 면 전체 URL 패턴이 인증 없이 보인다)로 나간다.

    `ClientApiView` 를 상속하지 않는다 — 없는 경로에 선검사가 먼저 걸려 411 이
    나가면 Client 가 길이 문제로 오해한다.

    `/api/v1/datasets` 아래는 Wezard 연동 규약 §4 를 따라 본문에도 `request_id` 를 넣는다
    (`DatasetApiView.dispatch` 와 같은 모양). 클라이언트 계약의 오류 봉투에는 넣지 않는다.
    """

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        response = error('NOT_FOUND', '없는 경로입니다.', 404)
        if request.path == '/api/v1/datasets' or request.path.startswith('/api/v1/datasets/'):
            body = json.loads(response.content)
            body['request_id'] = request.request_id
            response.content = json.dumps(body, ensure_ascii=False)
        return response


def serialize_inspection(inspection):
    """Client `_parse_inspection` 계약."""
    payload = {
        'id': inspection.id,
        'request_id': inspection.request_id,
        'inspection_item_id': inspection.item_id,
        'inspection_type': inspection.item.client_inspection_type,
        'status': inspection.status,
        'abnormal': inspection.abnormal,
        'defects': inspection.defects or [],
        'anomaly_score': inspection.anomaly_score,
        'threshold': inspection.threshold,
        'classification': inspection.classification,
        # 치수 측정의 측정점별 결과. 다른 유형은 null(키는 있다 — classification 과 같다)
        'measurements': inspection.measurements,
        'inference_ms': inspection.inference_ms,
        'model': ({'name': inspection.model_name, 'version': inspection.model_version}
                  if inspection.model_name else None),
        'created_at': to_utc_z(inspection.created_at),
    }
    if inspection.heatmap:
        # Heatmap 이 있을 때만 키를 둔다 — Client 는 키가 있으면 그 경로를 부른다(계약 §6-3).
        payload['heatmap_url'] = f'/api/v1/inspections/{inspection.id}/heatmap'
    return payload
