"""데이터 목록 화면(`wm_data_image`) — `/api/item/image`.

| action     | 메서드 | 입력                                                            | 권한           |
|------------|--------|-----------------------------------------------------------------|----------------|
| list       | GET    | item_id, q, status, label, date_from, date_to, page, page_size  | item.read      |
| detail     | GET    | item_id, image_id — 수집 경로(source: 클라이언트·파일 업로드·카메라 촬영·양식 사진 넣기)를 함께 준다 | item.read      |
| upload     | POST   | item_id, files(여러 개, 20개까지), requires_labeling(파일마다 1·0) | dataset.upload |
| delete     | POST   | item_id, image_id                                               | dataset.upload |
| preprocess | POST   | item_id, image_id, Q={"operations": [...]} — 원본 기준 연산 전체   | image.preprocess |
"""
from django.http import Http404
from django.urls import reverse

from app.views.item import ItemApiError, load_item, paged, param
from domain.models.data import ImageAsset, LabelClass
from domain.models.vision import VisionInspection
from domain.services.data.image import ImageService
from domain.services.data.image_list import ImageListService, label_fields, label_result
from domain.services.data.preprocess import ImagePreprocessService, PreprocessLocked
from domain.services.data.workflow import WorkflowStatus, workflow_status, workflow_status_label

READ_ACTIONS = frozenset({'list', 'detail'})


def image(context):
    """api/item/image"""
    handler = {'list': _list, 'detail': _detail, 'upload': _upload, 'delete': _delete,
               'preprocess': _preprocess}.get(context.gparam.get('action', 'list'))
    if handler is None:
        raise ItemApiError('지원하지 않는 기능입니다.')
    return handler(context)


def _image(context, item):
    try:
        return (ImageAsset.objects.for_tenant(context.request.tenant).select_related('dataset')
                .get(pk=int(param(context, 'image_id')), dataset__item=item))
    except (ImageAsset.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404('데이터를 찾을 수 없습니다.') from exc


def _list(context):
    item = load_item(context, 'item.read')
    g = context.gparam
    images = ImageListService.query(context.request.tenant, item, q=(g.get('q') or '').strip(),
                                    status=(g.get('status') or '').strip(), label=(g.get('label') or '').strip(),
                                    date_from=g.get('date_from') or '', date_to=g.get('date_to') or '')
    # 검색 조건이 등록일이라 목록도 등록일 최신순으로 보인다(나중에 편집해도 자리가 바뀌지 않는다).
    images = images.order_by('-created_at', '-id')
    result = paged(images, g, lambda image: {
        'id': image.id, 'original_name': image.original_name,
        'thumbnail_url': reverse('private-image-thumbnail', args=[image.id]),
        'workflow_status_label': workflow_status_label(workflow_status(image)),
        'label_result': label_result(image, item.task_type),
        'source': image.get_channel_display(),
        'created_at': image.created_at.strftime('%Y-%m-%d %H:%M'),
    })
    result['item'] = {
        'id': item.id, 'name': item.name, 'task_type': item.task_type,
        'cover_url': reverse('private-item-cover', args=[item.id]) if item.cover_image else '',
        'skip_labeling_available': ImageService.skip_labeling_available(item),
    }
    result['labels'] = list(LabelClass.objects.for_tenant(context.request.tenant).filter(item=item)
                            .values('id', 'display_name_ko'))
    result['statuses'] = [{'value': s, 'label': workflow_status_label(s)} for s in
                          (WorkflowStatus.UPLOAD, WorkflowStatus.WAITING, WorkflowStatus.IN_PROGRESS,
                           WorkflowStatus.COMPLETED, WorkflowStatus.REVIEWED)]
    return result


def _detail(context):
    item = load_item(context, 'item.read')
    image = _image(context, item)
    listed = ImageListService.query(context.request.tenant, item).get(pk=image.pk)
    image.annotation_count = listed.annotation_count
    payload = ImageListService.detail_payload(image, context.request.user)
    payload['source'] = _source(image)
    payload.update(label_fields(listed, item.task_type))
    return payload


def _source(image):
    """어디서 들어온 이미지인지. Client 전송이면 보낸 Client 와 촬영 시각."""
    if image.channel != ImageAsset.Channel.CLIENT:
        return {'kind': image.channel, 'label': image.get_channel_display()}
    inspection = VisionInspection.objects.select_related('client').filter(pk=image.source_inspection_id).first()
    if inspection is None:  # 검사 기록이 지워졌다
        return {'kind': 'CLIENT', 'label': image.get_channel_display(), 'client_id': '', 'inspection_id': image.source_inspection_id, 'captured_at': ''}
    return {'kind': 'CLIENT', 'label': image.get_channel_display(), 'client_id': inspection.client.client_id, 'inspection_id': inspection.id,
            'captured_at': inspection.capture_timestamp.strftime('%Y-%m-%d %H:%M') if inspection.capture_timestamp else ''}


def _upload(context):
    item = load_item(context, 'dataset.upload')
    files = context.request.FILES.getlist('files')
    if not files:
        raise ItemApiError('업로드할 이미지 파일을 선택해 주세요.')
    flags = context.request.POST.getlist('requires_labeling')
    result = ImageService.upload_images(item=item, files=files, actor=context.request.user,
                                        requires_labeling_flags=[value != '0' for value in flags] if flags else None)
    return {'success': True, 'message': f"{len(result['uploaded'])}개를 올렸습니다.",
            'uploaded': result['uploaded'], 'rejected': result['rejected']}


def _delete(context):
    item = load_item(context, 'dataset.upload')
    image = _image(context, item)
    try:
        ImageService.delete_image(image, context.request.user)
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '데이터를 삭제했습니다.'}


def _preprocess(context):
    item = load_item(context, 'image.preprocess')
    image = _image(context, item)
    body = context.posparam.get('Q')
    if not isinstance(body, dict):
        raise ItemApiError('편집 내용을 확인해 주세요.')
    try:
        edited = ImagePreprocessService.apply(image, body.get('operations'), actor=context.request.user)
    except (PreprocessLocked, ValueError) as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '이미지를 편집했습니다.',
            'image': ImageListService.detail_payload(edited, context.request.user)}
