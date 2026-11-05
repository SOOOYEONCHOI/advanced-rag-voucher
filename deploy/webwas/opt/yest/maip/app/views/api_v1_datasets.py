"""학습 플랫폼(Wezard)용 스냅샷 API — `/api/v1/datasets/...`.

정본은 `docs/Wezard/maip-api.md` 다. 응답 모양·오류 코드·경로를 바꾸면 그 문서를 함께 고친다.
인증 헤더·봉투·시각 형식은 `/api/v1` 과 같고 키 테이블만 다르다(IntegrationClient, DECISIONS DEC-029).
기준 Export 는 스냅샷마다 가장 최근 **`WEZARD` 형식** ExportJob 이다. 화면은 고정 형식을 본다.
"""
import hashlib
import json
import logging
from pathlib import Path

from django.db.models import OuterRef, Subquery
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from app.views.api_v1 import (
    ClientApiView,
    _parse_range,
    data,
    error,
    parse_utc,
    ranged_file_response,
    to_utc_z,
)
from app.views.item.snapshot import _analyze_manifest, _latest_exports
from domain.models.data import DatasetVersion, ExportJob, InspectionItem
from domain.models.vision import IntegrationClient
from domain.services.data.audit import AuditService
from domain.services.data.export import ExportService
from domain.tenancy import current_tenant

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class DatasetApiView(ClientApiView):
    client_model = IntegrationClient
    client_attr = 'integration_client'
    http_method_names = ['get']

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        """오류 본문 최상위에 `request_id`(RequestIdMiddleware 가 정한 값)를 더한다.

        인증 실패처럼 상위 dispatch 가 만든 오류에도 붙도록 여기서 한 번에 넣는다. 응답 헤더는 미들웨어가 붙인다.
        """
        response = super().dispatch(request, *args, **kwargs)
        if response.status_code >= 400 and response.get('Content-Type', '').startswith('application/json'):
            body = json.loads(response.content)
            body['request_id'] = request.request_id
            response.content = json.dumps(body, ensure_ascii=False)
        return response

    @classmethod
    def _authenticate(cls, request):
        """`X-API-Key` 하나. 키의 해시로 연동처를 찾는다(`X-Client-ID` 는 보지 않는다).

        해시를 조회 키로 쓰므로 비교 시각으로 키를 알아낼 수 없다. 키는 어떤 형태로도 로그에 남기지 않는다.
        """
        api_key = request.headers.get('X-API-Key', '')
        if not api_key:
            return None, 'AUTH_REQUIRED'
        digest = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        client = IntegrationClient.objects.filter(api_key_hash=digest, active=True).first()
        if client is None:
            logger.info('/api/v1/datasets 인증 실패(없거나 폐기된 키)')
            return None, 'AUTH_INVALID'
        IntegrationClient.objects.filter(pk=client.pk).update(last_seen_at=timezone.now())
        return client, None


def invalid(message):
    return error('INVALID_PARAMETER', message, 400)


def _snapshots():
    latest = (ExportJob.objects.filter(dataset_version=OuterRef('pk'), format=ExportJob.Format.WEZARD)
              .order_by('-created_at', '-id'))
    return (DatasetVersion.objects.for_tenant(current_tenant())
            .select_related('dataset__item')
            .annotate(export_status=Subquery(latest.values('status')[:1]))
            .order_by('-created_at', '-id'))


def _find(snapshot_id):
    version = _snapshots().filter(pk=snapshot_id).first()
    if version is None:
        return None, None
    return version, _latest_exports(current_tenant(), [version.id], wezard=True).get(version.id)


def _serialize(version, job):
    item = version.dataset.item
    completed = job is not None and job.status == ExportJob.Status.COMPLETED
    return {
        'id': version.id,
        'version_tag': version.version_tag,
        'created_at': to_utc_z(version.created_at),
        'item': {'id': item.id, 'code': item.code, 'name': item.name, 'task_type': item.task_type},
        'image_count': (version.manifest or {}).get('image_count', 0),
        'export': None if job is None else {
            'status': job.status,
            'format': job.format,
            'format_label': job.get_format_display(),
            'size_bytes': job.file_size,
            'sha256': job.file_sha256 or None,
            'completed_at': to_utc_z(job.completed_at),
            'download_url': f'/api/v1/datasets/snapshots/{version.id}/download' if completed else None,
        },
    }


class SnapshotListView(DatasetApiView):
    def get(self, request):
        query = request.GET
        try:
            limit = int(query.get('limit', DEFAULT_LIMIT))
            offset = int(query.get('offset', 0))
            created_after = parse_utc(query.get('created_after'))
        except (TypeError, ValueError):
            return invalid('limit·offset 은 정수, created_after 는 ISO 8601 시각이어야 합니다.')
        if offset < 0 or not 1 <= limit <= MAX_LIMIT:
            return invalid(f'limit 는 1~{MAX_LIMIT}, offset 은 0 이상이어야 합니다.')
        task_type, status = query.get('task_type'), query.get('status')
        # 치수 측정은 스냅샷이 없다(라벨링을 하지 않는다) — 학습 데이터 유형이 아니다
        if task_type and (task_type not in InspectionItem.TaskType.values or task_type == InspectionItem.TaskType.MEASUREMENT):
            return invalid('task_type 값이 올바르지 않습니다.')
        if status and status not in ExportJob.Status.values:
            return invalid('status 값이 올바르지 않습니다.')

        queryset = _snapshots()
        if query.get('item_code'):
            queryset = queryset.filter(dataset__item__code=query['item_code'])
        if task_type:
            queryset = queryset.filter(dataset__item__task_type=task_type)
        if status:
            queryset = queryset.filter(export_status=status)
        if created_after:
            queryset = queryset.filter(created_at__gt=created_after)

        total = queryset.count()
        rows = list(queryset[offset:offset + limit])
        latest = _latest_exports(current_tenant(), [row.id for row in rows], wezard=True)
        return data({'items': [_serialize(row, latest.get(row.id)) for row in rows],
                     'total': total, 'limit': limit, 'offset': offset})


class SnapshotDetailView(DatasetApiView):
    def get(self, request, snapshot_id):
        version, job = _find(snapshot_id)
        if version is None:
            return error('SNAPSHOT_NOT_FOUND', '스냅샷을 찾을 수 없습니다.', 404)
        if job is not None and job.status == ExportJob.Status.COMPLETED:
            try:
                ExportService.ensure_checksum(job)
            except FileNotFoundError:
                pass  # 정보는 준다. 받기에서 EXPORT_FILE_NOT_FOUND 로 알린다.
        body = _serialize(version, job)
        if body['export'] is not None:
            body['export']['error_message'] = job.error_message or None
        manifest = version.manifest or {}
        body['excluded_image_count'] = manifest.get('excluded_image_count', 0)
        body['statistics'] = _analyze_manifest(manifest, version.dataset.item.task_type)
        return data(body)


class SnapshotDownloadView(DatasetApiView):
    def get(self, request, snapshot_id):
        version, job = _find(snapshot_id)
        if version is None:
            return error('SNAPSHOT_NOT_FOUND', '스냅샷을 찾을 수 없습니다.', 404)
        if job is None or job.status in (ExportJob.Status.QUEUED, ExportJob.Status.RUNNING):
            return error('EXPORT_NOT_READY', 'Export 를 만드는 중입니다. 잠시 뒤 다시 요청해 주세요.', 409,
                         retryable=True)
        if job.status == ExportJob.Status.FAILED:
            return error('EXPORT_FAILED', 'Export 를 만들지 못했습니다. 플랫폼에서 다시 만들어야 합니다.', 409)
        try:
            ExportService.ensure_checksum(job)
            path = Path(job.file.path)
            size = path.stat().st_size
        except (FileNotFoundError, ValueError):  # ValueError: 파일 필드가 빈 행
            return error('EXPORT_FILE_NOT_FOUND', '저장소에 zip 파일이 없습니다.', 404)

        # 이어받기 조각마다 남기지 않는다. 받기를 시작한 요청(전체 또는 0 바이트부터)만 남긴다.
        requested = _parse_range(request.headers.get('Range'), size)
        if requested is None or (requested != 'invalid' and requested[0] == 0):
            AuditService.record(
                tenant=current_tenant(), item=version.dataset.item, event_type='SNAPSHOT_DOWNLOADED',
                payload={'dataset_version_id': version.id, 'export_job_id': job.id,
                         'client_id': request.integration_client.client_id},
                request_id=request.request_id)
        filename = f'snapshot-{version.id}-{version.version_tag}-{job.format.lower()}.zip'
        return ranged_file_response(request, path, size, filename)
