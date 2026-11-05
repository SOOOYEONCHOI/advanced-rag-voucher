"""비전 검사 이력 (`wm_vis_inspection`) · 검사 현황 (`wm_vis_dashboard`)."""
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q

from app.views.item import paged
from domain.models.data import InspectionItem, LabelClass
from domain.models.vision import VisionClient, VisionInspection
from domain.services.logging import LogWriter
from domain.services.vision.inspection import measured_rows
from domain.tenancy import current_tenant, tenant_atomic

STATUS_LABEL = {
    'RECEIVED': '접수됨',
    'SUCCESS': '판정 완료',
    'FAILED': '실패',
}
# RECEIVED 인데 사유가 남은 검사(추론 미실행)의 사유 — domain/services/vision/gateway.py 의 예외 code.
SKIP_REASON = {
    'GPU_INFERENCE_NOT_CONFIGURED': 'Wezard 미설정',
    'WEZARD_MODEL_NOT_DEPLOYED': '배포 모델 없음',
}


def inspection(context):
    """api/vision/inspection"""
    gparam = context.gparam
    action = gparam.get('action', 'list')

    try:
        with tenant_atomic():
            if action == 'list':
                return _list(gparam)
            if action == 'detail':
                return _detail(gparam.get('id'))
            if action == 'dashboard':
                return _dashboard(gparam)
            if action == 'filters':
                return _filters()
        raise ValueError('action: ' + str(action))
    except Exception as ex:
        # 예외 원문은 로그에만 남긴다.
        LogWriter.add_dblog('error', 'vision/inspection : action-{}'.format(action), ex)
        return {'success': False, 'message': '검사 정보를 불러오지 못했습니다.'}


def _filters():
    """검색 콤보. 다른 메뉴(모델 매핑·클라이언트)의 API 를 부르면 그 권한이 없는 그룹은 403 이다."""
    items = (InspectionItem.objects.for_tenant(current_tenant())
             .order_by('display_order', 'id').values('id', 'code', 'name'))
    clients = VisionClient.objects.order_by('client_id').values('id', 'client_id')
    return {'items': list(items), 'clients': list(clients)}


def _list(gparam):
    queryset = (VisionInspection.objects
                .select_related('item', 'client', 'image_asset')
                .order_by('-created_at'))

    item_id = gparam.get('item_id')
    if item_id:
        queryset = queryset.filter(item_id=item_id)
    client_id = gparam.get('client_id')
    if client_id:
        queryset = queryset.filter(client_id=client_id)
    status = gparam.get('status')
    if status:
        queryset = queryset.filter(status=status)
    # 날짜를 비우면 오늘을 포함한 최근 7일(요약 카드·화면 기본 기간과 같다).
    # `created_at::date` 는 인덱스를 못 타므로 범위로 건다.
    date_from = gparam.get('date_from') or (date.today() - timedelta(days=6)).isoformat()
    queryset = queryset.filter(created_at__gte=datetime.fromisoformat(date_from))
    date_to = gparam.get('date_to')
    if date_to:
        queryset = queryset.filter(created_at__lt=datetime.fromisoformat(date_to) + timedelta(days=1))

    return paged(queryset, gparam, _row)


def _row(row):
    return {
        'id': row.id,
        'created_at': row.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'item_code': row.item.code,
        'item_name': row.item.name,
        'client_id': row.client.client_id,
        'status': row.status,
        # 매핑이 있는데 추론이 안 돈 검사를 "모델 없음"과 구분하고 사유를 보여 준다.
        'status_label': ('접수됨 (추론 미실행 · {})'.format(SKIP_REASON.get(row.error_message, row.error_message))
                         if row.inference_skipped else STATUS_LABEL.get(row.status, row.status)),
        'abnormal': row.abnormal,
        'model': f'{row.model_name} v{row.model_version}' if row.model_name else '',
        'anomaly_score': row.anomaly_score,
        'inference_ms': row.inference_ms,
        'image_id': row.image_asset_id,
        'camera': f'{row.camera_vendor or ""} {row.camera_serial or ""}'.strip(),
    }


def _detail(inspection_id):
    row = (VisionInspection.objects
           .select_related('item', 'client', 'image_asset').filter(id=inspection_id).first())
    if row is None:
        return {'success': False, 'message': '검사를 찾을 수 없습니다.'}
    detail = _row(row)
    detail.update({
        'request_id': row.request_id,
        'client_version': row.client_version,
        'capture_timestamp': row.capture_timestamp.strftime('%Y-%m-%d %H:%M:%S')
        if row.capture_timestamp else '',
        'defects': row.defects or [],
        'threshold': row.threshold,
        'classification': ('{} ({:.2f})'.format(row.classification['name'], row.classification['score'])
                           if row.classification else ''),
        'error_message': row.error_message or '',
        'detected': _detected(row),
        # 치수 측정: 측정점마다 한 줄. 불합격은 화면이 강조한다
        'measured': measured_rows(row),
    })
    return detail


def _detected(row):
    """객체 탐지의 검출 결함. 검사항목 라벨 클래스의 표시 이름으로 보이고, 모르는 라벨은 받은 이름 그대로다."""
    if not row.defects:
        return ''
    names = dict(LabelClass.objects.filter(item_id=row.item_id).values_list('name', 'display_name_ko'))
    return ', '.join('{} ({:.2f})'.format(names.get(d['class_name']) or d['class_name'], d['confidence'])
                     for d in row.defects)


def _dashboard(gparam):
    """기간별 검사 건수·이상률·상태 분포·Client 활동."""
    days = int(gparam.get('days') or 7)
    # 오늘을 포함한 날짜 단위 — 목록의 기본 기간과 같다.
    since = datetime.combine(date.today() - timedelta(days=days - 1), time())
    base = VisionInspection.objects.filter(created_at__gte=since)

    totals = base.aggregate(
        total=Count('id'),
        received=Count('id', filter=Q(status='RECEIVED')),
        success=Count('id', filter=Q(status='SUCCESS')),
        failed=Count('id', filter=Q(status='FAILED')),
        abnormal=Count('id', filter=Q(abnormal=True)),
        # 모델은 붙었는데 GPU 가 없어 판정이 보류된 건수
        inference_skipped=Count('id', filter=Q(status='RECEIVED') & ~Q(error_message=None)),
    )
    judged = totals['success'] or 0
    totals['abnormal_rate'] = round(totals['abnormal'] / judged * 100, 1) if judged else None

    by_item = list(base.values('item__code', 'item__name')
                   .annotate(count=Count('id')).order_by('-count')[:10])
    clients = [{
        'client_id': row.client_id,
        'name': row.name,
        'active': row.active,
        'last_seen_at': row.last_seen_at.strftime('%Y-%m-%d %H:%M:%S') if row.last_seen_at else '',
    } for row in VisionClient.objects.order_by('client_id')]

    return {'period_days': days, 'totals': totals, 'by_item': by_item, 'clients': clients}
