"""검수 작업 화면(`wm_data_review`) — `/api/item/review`.

목록은 라벨링을 마치고 제출된(작업 완료) 이미지만 준다. 승인·재작업은 검수 작업 메뉴 W 가 있어야
한다(디스패치와 DatasetReviewService 가 확인, 아니면 403).

| action  | 메서드 | 입력                               |
|---------|--------|------------------------------------|
| list    | GET    | item_id (전부 — 화면이 나눈다)       |
| detail  | GET    | item_id, image_id                  |
| approve | POST   | item_id, image_id                  |
| rework  | POST   | item_id, image_id, reason(필수)     |
"""
from django.db.models import Prefetch
from django.http import Http404
from django.urls import reverse

from app.views.item import ItemApiError, load_item, param, whole
from domain.models.data import ImageAsset, LabelingTask
from domain.services.account import user_display_name
from domain.services.data.image_list import ImageListService, label_fields, label_result
from domain.services.data.review import DatasetReviewService
from domain.services.data.workflow import WorkflowStatus

READ_ACTIONS = frozenset({'list', 'detail'})


def review(context):
    """api/item/review"""
    handler = {'list': _list, 'detail': _detail, 'approve': _decide, 'rework': _decide}.get(
        context.gparam.get('action', 'list'))
    if handler is None:
        raise ItemApiError('지원하지 않는 기능입니다.')
    return handler(context)


def _submitted(context, item):
    return ImageListService.query(context.request.tenant, item, status=WorkflowStatus.COMPLETED)


def _image(context, item):
    try:
        return _submitted(context, item).get(pk=int(param(context, 'image_id')))
    except (ImageAsset.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404('검수할 데이터를 찾을 수 없습니다. 이미 처리됐을 수 있습니다.') from exc


def _assignee(image):
    task = next(iter(image.submitted_tasks), None)
    # 라벨 작업 없이 올라온 이미지는 제출한 작업이 없다.
    return user_display_name(task.assignee) if task and task.assignee else '-'


def _list(context):
    item = load_item(context, 'item.read')
    # 전부를 주므로 작업자를 행마다 따로 읽지 않는다
    images = _submitted(context, item).prefetch_related(Prefetch(
        'labeling_tasks', to_attr='submitted_tasks',
        queryset=LabelingTask.objects.filter(status=LabelingTask.Status.SUBMITTED)
        .select_related('assignee').order_by('id')))
    result = whole(images, lambda image: {
        'id': image.id, 'original_name': image.original_name,
        'thumbnail_url': reverse('private-image-thumbnail', args=[image.id]),
        'label_result': label_result(image, item.task_type), 'assignee_name': _assignee(image),
        'updated_at': image.updated_at.strftime('%Y-%m-%d %H:%M'),
    })
    result['item'] = {'id': item.id, 'name': item.name}
    return result


def _detail(context):
    item = load_item(context, 'item.read')
    image = _image(context, item)
    payload = ImageListService.detail_payload(image, context.request.user)
    payload.update(label_fields(image, item.task_type))
    return payload


def _decide(context):
    item = load_item(context, 'item.read')
    image = _image(context, item)
    try:
        if context.gparam.get('action') == 'approve':
            DatasetReviewService.approve(image, context.request.user)
            message = '검수 완료로 처리했습니다.'
        else:
            DatasetReviewService.request_rework(image, context.request.user, param(context, 'reason', ''))
            message = '재작업을 요청했습니다.'
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': message}
