"""비전검사 Overlay 관리 (`wm_vis_overlay`).

Client 화면에 겹쳐 보여 줄 기준 이미지다. 교체하면 `version` 이 오른다 —
Client 가 그 값으로 캐시를 무효화한다.
"""
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.urls import reverse

from domain.models.data import InspectionItem
from domain.models.vision import VisionOverlay
from domain.services.logging import LogWriter
from domain.tenancy import tenant_atomic

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_MIME = {'image/png', 'image/jpeg'}


def overlay(context):
    """api/vision/overlay"""
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action', 'list')

    try:
        with tenant_atomic():
            if action == 'list':
                return _list()
            # 지우지 않는다 — 숨기려면 "표시"(visible)를 해제해 저장한다(행이 곧 검사항목).
            if action == 'save':
                return _save(context, posparam)
        raise ValueError('action: ' + str(action))
    except Exception as ex:
        LogWriter.add_dblog('error', 'vision/overlay : action-{}'.format(action), ex)
        return {'success': False, 'message': '처리 중 오류가 발생했습니다.'}


def _list():
    """매핑과 같은 이유로 Overlay 가 없는 검사항목도 함께 돌려준다."""
    rows = []
    for item in InspectionItem.objects.select_related('overlay').order_by('display_order', 'code'):
        row = getattr(item, 'overlay', None)
        rows.append({
            'item_id': item.id,
            'item_code': item.code,
            'item_name': item.name,
            'has_overlay': row is not None,
            'version': row.version if row else None,
            'visible': row.visible if row else False,
            'opacity': row.opacity if row else None,
            # 교체하면 version 이 오른다. 쿼리에 실어 브라우저가 옛 이미지를 다시 쓰지 않게 한다.
            'image_url': (reverse('private-overlay', args=[item.id]) + f'?v={row.version}') if row else '',
            'updated_at': row.updated_at.strftime('%Y-%m-%d %H:%M') if row else '',
        })
    return rows


def _save(context, posparam):
    item = InspectionItem.objects.filter(id=posparam.get('item_id')).first()
    if item is None:
        return {'success': False, 'message': '비전검사항목을 찾을 수 없습니다.'}

    opacity = posparam.get('opacity')
    try:
        opacity = float(opacity) if opacity not in (None, '') else 0.7
    except (TypeError, ValueError):
        return {'success': False, 'message': '불투명도는 숫자로 입력해 주세요.'}
    if not 0.0 <= opacity <= 1.0:
        return {'success': False, 'message': '불투명도는 0.0~1.0 사이로 입력해 주세요.'}

    uploaded = context.request.FILES.get('image')
    row = VisionOverlay.objects.filter(item=item).first()

    if uploaded is not None:
        if not isinstance(uploaded, UploadedFile) or uploaded.content_type not in ALLOWED_MIME:
            return {'success': False, 'message': 'PNG 또는 JPEG 만 올릴 수 있습니다.'}
        if uploaded.size > MAX_IMAGE_BYTES:
            return {'success': False, 'message': '10MB 이하만 올릴 수 있습니다.'}
    elif row is None:
        return {'success': False, 'message': 'Overlay 이미지를 선택해 주세요.'}

    if row is None:
        row = VisionOverlay(item=item, version=1)
    elif uploaded is not None:
        # 이미지를 바꿀 때만 버전을 올린다. Client 가 이 값으로 캐시를 지운다.
        row.version += 1

    row.opacity = opacity
    if posparam.get('visible') not in (None, ''):
        row.visible = posparam.get('visible') not in ('0', 'false', 'False')
    if uploaded is not None:
        # 파일 제공 뷰는 현재 이미지만 내준다. 버전마다 경로가 달라 옛 파일은 남으면 고아다.
        if row.image:
            _delete_file_on_commit(row.image)
        row.image = uploaded
    row.save()
    return {'success': True, 'version': row.version}


def _delete_file_on_commit(field_file):
    """행 변경이 커밋된 뒤에 지운다. 롤백되면 행이 살아나는데 파일만 사라지면 안 된다."""
    storage, name = field_file.storage, field_file.name
    transaction.on_commit(lambda: storage.delete(name))
