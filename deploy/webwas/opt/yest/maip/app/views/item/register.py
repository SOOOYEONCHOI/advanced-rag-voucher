"""비전 데이터 등록 화면(`wm_data_register`) — `/api/item/register`.

모든 비전검사항목의 최근 데이터를 보고, 항목을 골라 카메라·파일로 등록하고, 한 장을 편집·삭제한다(사용자 결정 2026-10-23).
권한은 이 메뉴의 R(조회)·W(등록·편집·삭제)뿐이다 — 검수 완료 삭제만 검수 작업 W 도 본다(ImageService.delete_image).

| action     | 메서드 | 입력 |
|------------|--------|------|
| list       | GET    | item_id?, channel?, q, date_from, date_to, page, page_size |
| detail     | GET    | image_id |
| items      | GET    | — 등록 대상(사용 중·치수 측정 아님)과 Overlay |
| upload     | POST   | item_id, kind(FILE·CAMERA), files |
| preprocess | POST   | image_id, Q={"operations": [...]} |
| delete     | POST   | image_id |
"""
from datetime import date

from django.http import Http404
from django.urls import reverse

from app.views.item import ItemApiError, paged, param
from domain.models.data import ImageAsset, InspectionItem
from domain.models.vision import VisionInspection, VisionOverlay
from domain.services.account import user_display_name
from domain.services.data.image import ImageService
from domain.services.data.image_list import ImageListService
from domain.services.data.preprocess import ImagePreprocessService, PreprocessLocked
from domain.services.data.workflow import workflow_status, workflow_status_label

READ_ACTIONS = frozenset({'list', 'detail', 'items'})
KINDS = {'FILE': ImageAsset.Channel.FILE, 'CAMERA': ImageAsset.Channel.CAMERA}


def register(context):
    """api/item/register"""
    handler = {'list': _list, 'detail': _detail, 'items': _items, 'upload': _upload,
               'preprocess': _preprocess, 'delete': _delete}.get(context.gparam.get('action', 'list'))
    if handler is None:
        raise ItemApiError('지원하지 않는 기능입니다.')
    return handler(context)


def _images(context):
    return (ImageAsset.objects.for_tenant(context.request.tenant)
            .select_related('dataset__item', 'uploaded_by__userprofile'))


def _image(context):
    try:
        return _images(context).get(pk=int(param(context, 'image_id')))
    except (ImageAsset.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404('데이터를 찾을 수 없습니다.') from exc


def _list(context):
    g = context.gparam
    images = _images(context)
    try:
        if g.get('item_id'):
            images = images.filter(dataset__item_id=int(g['item_id']))
        if g.get('date_from'):
            images = images.filter(created_at__date__gte=date.fromisoformat(g['date_from']))
        if g.get('date_to'):
            images = images.filter(created_at__date__lte=date.fromisoformat(g['date_to']))
    except ValueError as exc:
        raise ItemApiError('비전검사항목이나 등록일을 확인해 주세요.') from exc
    if g.get('channel') in ImageAsset.Channel.values:
        images = images.filter(channel=g['channel'])
    if (g.get('q') or '').strip():
        images = images.filter(original_name__icontains=g['q'].strip())
    return paged(images.order_by('-created_at', '-id'), g, lambda image: {
        'id': image.id, 'thumbnail_url': reverse('private-image-thumbnail', args=[image.id]),
        'item_code': image.dataset.item.code, 'item_name': image.dataset.item.name,
        'channel_label': image.get_channel_display(), 'original_name': image.original_name,
        'workflow_status_label': workflow_status_label(workflow_status(image)),
        'uploaded_by': user_display_name(image.uploaded_by) if image.uploaded_by else '-',
        'created_at': image.created_at.strftime('%Y-%m-%d %H:%M'),
    }, default_size=50)


def _detail(context):
    image = _image(context)
    payload = ImageListService.detail_payload(image, context.request.user)
    item = image.dataset.item
    payload.update({
        'item': {'id': item.id, 'code': item.code, 'name': item.name},
        'channel': image.channel, 'channel_label': image.get_channel_display(),
        'uploaded_by': user_display_name(image.uploaded_by) if image.uploaded_by else '-',
        'created_at': image.created_at.strftime('%Y-%m-%d %H:%M'), 'file_size': image.file_size,
    })
    if image.source_inspection_id:
        inspection = VisionInspection.objects.select_related('client').filter(pk=image.source_inspection_id).first()
        payload['client'] = {'client_id': inspection.client.client_id if inspection else '',
                             'captured_at': inspection.capture_timestamp.strftime('%Y-%m-%d %H:%M')
                             if inspection and inspection.capture_timestamp else ''}
    return payload


def _targets(tenant):
    return (InspectionItem.objects.for_tenant(tenant).filter(status=InspectionItem.Status.ACTIVE)
            .exclude(task_type=InspectionItem.TaskType.MEASUREMENT).select_related('category__parent'))


def _items(context):
    overlays = {o.item_id: o for o in VisionOverlay.objects.filter(visible=True).exclude(image='')}
    rows = []
    for item in _targets(context.request.tenant).order_by('category__parent__sort_order', 'category__sort_order',
                                                          'display_order', 'code'):
        overlay = overlays.get(item.id)
        category = item.category
        rows.append({'id': item.id, 'code': item.code, 'name': item.name,
                     'category': ' › '.join(c.name for c in (category.parent, category) if c) if category else '미분류',
                     'overlay_url': f'/media/overlay/{item.id}/' if overlay else '',
                     'overlay_opacity': overlay.opacity if overlay else None})
    return {'items': rows}


def _upload(context):
    try:
        item = _targets(context.request.tenant).get(pk=int(param(context, 'item_id')))
    except (InspectionItem.DoesNotExist, TypeError, ValueError) as exc:
        raise ItemApiError('등록할 수 있는 비전검사항목이 아닙니다. 사용 중인 항목을 골라 주세요.') from exc
    kind = KINDS.get(param(context, 'kind'))
    if kind is None:
        raise ItemApiError('등록 유형을 골라 주세요.')
    files = context.request.FILES.getlist('files')
    if not files:
        raise ItemApiError('등록할 이미지를 골라 주세요.')
    result = ImageService.upload_images(item=item, files=files, actor=context.request.user, channel=kind,
                                        allow_duplicate=kind == ImageAsset.Channel.CAMERA)
    return {'success': True, 'message': f"{len(result['uploaded'])}개를 등록했습니다.",
            'uploaded': result['uploaded'], 'rejected': result['rejected']}


def _preprocess(context):
    image = _image(context)
    body = context.posparam.get('Q')
    if not isinstance(body, dict):
        raise ItemApiError('편집 내용을 확인해 주세요.')
    try:
        edited = ImagePreprocessService.apply(image, body.get('operations'), actor=context.request.user)
    except (PreprocessLocked, ValueError) as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '이미지를 편집했습니다.',
            'image': ImageListService.detail_payload(edited, context.request.user)}


def _delete(context):
    image = _image(context)
    try:
        ImageService.delete_image(image, context.request.user)
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '데이터를 삭제했습니다.'}
