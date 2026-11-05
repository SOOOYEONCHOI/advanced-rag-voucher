"""라벨링 작업 화면(`wm_data_labeling`) — `/api/item/labeling`.

흐름: claim(작업 시작) → draft(임시 저장, 여러 번) → submit(제출). 그동안 화면은 heartbeat 로
lease 를 연장한다(LabelingTaskService.LEASE_MINUTES). 작업자 확인·lease 토큰 검사는 서비스가 하고
어긋나면 PermissionDenied(403)다.

| action    | 메서드 | 입력                                                    |
|-----------|--------|---------------------------------------------------------|
| queue     | GET    | item_id, page, page_size(기본 50), image_id — 작업할 이미지 한 페이지·건수·라벨 |
| claim     | POST   | item_id, image_id                                       |
| heartbeat | POST   | item_id, task_id, lease_token                           |
| draft     | POST   | item_id, task_id, Q={"lease_token", "annotations": [...]} |
| submit    | POST   | item_id, task_id, lease_token                           |
"""
from django.db.models import Count, Q
from django.http import Http404

from app.views.item import ItemApiError, cover_url, load_item, param
from domain.models.data import ImageAsset, LabelClass, LabelingTask
from domain.services.data.image import ImageService, image_prefetches
from domain.services.data.image_list import ImageListService
from domain.services.data.item_access import REVIEW_MENU, ItemAccessService
from domain.services.data.labeling_task import LabelingTaskService

READ_ACTIONS = frozenset({'queue'})

QUEUE_PAGE_SIZE = 50
# 대기열에 보이는 "작업할 것"(화면 visibleImages 와 같다)과 진행률의 "끝난 것"
WORK_STATUSES = [ImageAsset.LabelStatus.UNLABELED, ImageAsset.LabelStatus.IN_PROGRESS, ImageAsset.LabelStatus.REWORK]
DONE_STATUSES = [ImageAsset.LabelStatus.SUBMITTED, ImageAsset.LabelStatus.APPROVED]


def _int(context, key, default, low, high):
    try:
        return min(max(int(param(context, key, default)), low), high)
    except (TypeError, ValueError):
        return default


def labeling(context):
    """api/item/labeling"""
    handler = {'queue': _queue, 'claim': _claim, 'heartbeat': _heartbeat, 'draft': _draft,
               'submit': _submit}.get(context.gparam.get('action', 'queue'))
    if handler is None:
        raise ItemApiError('지원하지 않는 기능입니다.')
    return handler(context)


def task_payload(task):
    """화면이 다음 요청에 쓸 작업 정보. lease_token 은 draft·heartbeat·submit 때 다시 보낸다."""
    return {
        'id': task.id, 'image_id': task.image_id, 'assignee_id': task.assignee_id, 'status': task.status,
        'lease_token': str(task.lease_token) if task.lease_token else None,
        'lease_expires_at': task.lease_expires_at.isoformat() if task.lease_expires_at else None,
        'last_saved_at': task.last_saved_at.isoformat() if task.last_saved_at else None,
    }


def _task(context, item):
    try:
        return LabelingTask.objects.for_tenant(context.request.tenant).get(
            pk=int(param(context, 'task_id')), image__dataset__item=item)
    except (LabelingTask.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404('작업을 찾을 수 없습니다.') from exc


def _queue(context):
    item = load_item(context, 'item.read')
    tenant, user = context.request.tenant, context.request.user
    page = _int(context, 'page', 1, 1, 10 ** 6)
    size = _int(context, 'page_size', QUEUE_PAGE_SIZE, 1, 200)
    snapshot_ids = {}

    can_manage = ItemAccessService.can_write(user, REVIEW_MENU)   # 승인된 데이터를 지울 수 있는지(검수 작업 W)

    def payload(image):
        if image.dataset_id not in snapshot_ids:
            snapshot_ids[image.dataset_id] = ImageService.snapshot_image_ids(image.dataset)
        return ImageListService.detail_payload(image, user, snapshot_ids=snapshot_ids[image.dataset_id],
                                               can_manage=can_manage)

    counts = (ImageAsset.objects.for_tenant(tenant).filter(dataset__item=item)
              .aggregate(total=Count('id'), complete=Count('id', filter=Q(label_status__in=DONE_STATUSES)),
                         remaining=Count('id', filter=Q(label_status__in=WORK_STATUSES))))

    def with_relations(images):
        # 장마다 다시 읽지 않도록 관계를 한 번에 붙여 읽는다 — 쿼리 수가 이미지 수와 무관하다.
        return images.select_related('dataset__item').prefetch_related(*image_prefetches())

    # 작업할 이미지만 먼저 들어온 순으로 한 페이지씩 준다. 최근 수정 순이면 작업을 시작·저장할 때마다
    # 이미지가 다른 페이지로 옮겨 다닌다.
    work = with_relations(ImageListService.query(tenant, item).filter(label_status__in=WORK_STATUSES).order_by('id'))
    rows = list(work[(page - 1) * size: page * size])
    # 주소의 ?image= 로 연 이미지가 이 페이지에 없으면(다른 페이지·이미 제출) 따로 준다.
    requested = None
    image_id = str(param(context, 'image_id', '') or '')
    if image_id.isdigit() and int(image_id) not in {row.id for row in rows}:
        found = with_relations(ImageListService.query(tenant, item).filter(id=int(image_id))).first()
        requested = payload(found) if found else None
    return {
        'item': {'id': item.id, 'name': item.name, 'task_type': item.task_type, 'cover_url': cover_url(item)},
        'actor_id': user.id,
        'labels': list(LabelClass.objects.for_tenant(tenant).filter(item=item)
                       .values('id', 'display_name_ko', 'color', 'annotation_shape')),
        'images': [payload(image) for image in rows],
        'page': page, 'page_size': size, 'totalRows': counts['remaining'], 'counts': counts,
        'requested': requested,
    }


def _claim(context):
    item = load_item(context, 'item.read')
    try:
        image = ImageAsset.objects.for_tenant(context.request.tenant).get(
            pk=int(param(context, 'image_id')), dataset__item=item)
    except (ImageAsset.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404('데이터를 찾을 수 없습니다.') from exc
    try:
        task = LabelingTaskService.claim(image=image, actor=context.request.user)
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '작업을 시작했습니다.', 'task': task_payload(task)}


def _heartbeat(context):
    task = LabelingTaskService.heartbeat(task=_task(context, load_item(context, 'item.read')),
                                         actor=context.request.user, lease_token=param(context, 'lease_token'))
    return {'success': True, 'message': '', 'task': task_payload(task)}


def _draft(context):
    task = _task(context, load_item(context, 'item.read'))
    body = context.posparam.get('Q')
    if not isinstance(body, dict):
        raise ItemApiError('저장할 라벨을 확인해 주세요.')
    try:
        count = LabelingTaskService.save_draft(task=task, actor=context.request.user,
                                               annotations=body.get('annotations', []),
                                               lease_token=body.get('lease_token'))
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    task.refresh_from_db()
    return {'success': True, 'message': '라벨을 저장했습니다.', 'task': task_payload(task), 'annotation_count': count}


def _submit(context):
    task = LabelingTaskService.submit(task=_task(context, load_item(context, 'item.read')),
                                      actor=context.request.user, lease_token=param(context, 'lease_token'))
    return {'success': True, 'message': '라벨링 작업을 제출했습니다.', 'task': task_payload(task)}
