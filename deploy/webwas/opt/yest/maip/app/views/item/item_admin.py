"""검사항목 관리 화면(`wm_data_item`, 시스템 관리) — `/api/item/item_admin`.

플랫폼 관리자 전용이다. 메뉴 권한이 있어도 플랫폼 관리자가 아니면 403 이다.
검사항목 추가·상태 전환·삭제 요청 승인/반려를 한다(비전검사항목 배정은 없앴다, 사용자 결정 2026-10-21).

| action        | 메서드 | 입력                                  |
|---------------|--------|---------------------------------------|
| list          | GET    | q, status (전부 — 화면이 나눈다)        |
| detail        | GET    | item_id                               |
| models        | GET    | item_id — Wezard 배포 모델(그 유형). [수정]을 누를 때만 부른다 |
| create        | POST   | name, description, task_type, capture_method, category_id(중분류, 빈 값 = 미분류) |
| update        | POST   | item_id, description, active(Y/N), (capture_method), (category_id), (model_name) — 상세 [수정] |
| toggle_status | POST   | item_id — 사용 ↔ 중지                  |
| approve_delete| POST   | deletion_id                           |
| reject_delete | POST   | deletion_id                           |
"""
import uuid

from django.core.exceptions import PermissionDenied
from django.http import Http404

from app.views.item import ItemApiError, param, whole
from domain.models.data import Dataset, InspectionItem, ItemDeletionRequest
from domain.services.account import user_is_platform_admin
from domain.services.data import category as categories
from domain.services.data.audit import AuditService
from domain.services.data.item_deletion import ItemDeletionService
from domain.services.data.item_platform import ItemPlatformService
from domain.services.vision import model_mapping as model_mappings

READ_ACTIONS = frozenset({'list', 'detail', 'models'})


def item_admin(context):
    """api/item/item_admin"""
    if not user_is_platform_admin(context.request.user):
        raise PermissionDenied('플랫폼 관리자만 사용할 수 있습니다.')
    handler = {
        'list': _list, 'detail': _detail, 'models': _models, 'create': _create, 'update': _update,
        'toggle_status': _toggle_status, 'approve_delete': _review_deletion, 'reject_delete': _review_deletion,
    }.get(context.gparam.get('action', 'list'))
    if handler is None:
        raise ItemApiError('지원하지 않는 기능입니다.')
    return handler(context)


def _item(context):
    try:
        return InspectionItem.objects.for_tenant(context.request.tenant).get(pk=int(param(context, 'item_id')))
    except (InspectionItem.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404('비전검사항목을 찾을 수 없습니다.') from exc


def _list(context):
    rows = ItemPlatformService.list_items(query=context.gparam.get('q', ''),
                                          status=context.gparam.get('status', ''))
    result = whole(rows, lambda row: {
        'id': row['id'], 'code': row['code'], 'name': row['name'],
        'task_type_label': row['task_type_label'], 'capture_method_label': row['capture_method_label'],
        'category_id': row['category_id'], 'category_label': row['category_label'], 'status': row['status'],
        'status_label': row['status_label'],
        'image_count': row['image_count'], 'progress': row['progress'],
        'updated_at': row['updated_at'].strftime('%Y-%m-%d %H:%M'),
    })
    result['status_choices'] = [{'value': value, 'label': label} for value, label in InspectionItem.Status.choices]
    return result


def _detail(context):
    item = _item(context)
    detail = ItemPlatformService.detail_for(item, context.request.tenant)
    deletion = detail.get('deletion_request')
    return {
        'id': item.id, 'code': item.code, 'name': item.name, 'description': item.description,
        'task_type_label': item.get_task_type_display(), 'status': item.status,
        'capture_method': item.capture_method, 'capture_method_label': item.get_capture_method_display(),
        'category_id': item.category_id, 'category_label': categories.label_of(item.category),
        # AI 모델 매핑(domain.services.vision.model_mapping). 치수 측정은 모델이 없다
        'mappable': _mappable(item), 'model_name': model_mappings.active_model_name(item) if _mappable(item) else '',
        'status_label': item.get_status_display(), 'image_count': detail['image_count'],
        'progress': detail['progress'], 'created_at': item.created_at.strftime('%Y-%m-%d %H:%M'),
        'deletion_request': {
            'id': deletion['id'], 'reason': deletion['reason'] or '',
            'requested_by': deletion['requested_by__username'] or '',
            'requested_at': deletion['requested_at'].strftime('%Y-%m-%d %H:%M') if deletion['requested_at'] else '',
        } if deletion else None,
    }


def _mappable(item):
    return item.task_type != InspectionItem.TaskType.MEASUREMENT


def _models(context):
    item = _item(context)
    if not _mappable(item):
        raise ItemApiError('치수 측정 비전검사항목은 AI 모델을 쓰지 않습니다.')
    models, message = model_mappings.deployed_models(item)
    return {'models': models, 'message': message}


def _create(context):
    tenant = context.request.tenant
    name = str(param(context, 'name', '')).strip()
    if not name:
        raise ItemApiError('비전검사항목명을 입력해 주세요.')
    task_type = param(context, 'task_type')
    if task_type not in InspectionItem.TaskType.values:
        task_type = InspectionItem.TaskType.OBJECT_DETECTION
    capture_method = param(context, 'capture_method')
    if capture_method not in InspectionItem.CaptureMethod.values:
        capture_method = InspectionItem.CaptureMethod.RIG
    category = _category(context, None)
    # code 가 unique 라 임시 값으로 만든 뒤 ITEM-<id> 로 바꾼다(클라이언트 카탈로그의 code).
    item = InspectionItem.objects.create(tenant=tenant, code=uuid.uuid4().hex, name=name,
                                         description=str(param(context, 'description', '')).strip(),
                                         task_type=task_type, capture_method=capture_method, category=category,
                                         created_by=context.request.user)
    item.code = f'ITEM-{item.id}'
    item.save(update_fields=['code'])
    dataset = Dataset.objects.create(tenant=tenant, item=item, name='일반 사용자 업로드', version='v0.1',
                                     status=Dataset.Status.RAW)
    AuditService.record(tenant=tenant, item=item, actor=context.request.user, event_type='PROJECT_CREATED',
                        payload={'task_type': task_type})
    AuditService.record(tenant=tenant, item=item, actor=context.request.user, event_type='DATASET_CREATED',
                        payload={'dataset_id': dataset.id, 'name': dataset.name})
    return {'success': True, 'message': '비전검사항목을 등록했습니다.', 'item_id': item.id}


def _update(context):
    """상세 [수정]의 [저장] — 설명·사용 여부(사용 ↔ 중지)·촬영 방식·소속 중분류·AI 모델. 삭제 승인 대기는 사용 여부를 바꾸지 않는다.

    AI 모델은 `model_name` 을 보냈고 지금과 다를 때만 Wezard 에 묻는다. 고를 수 없으면 아무것도 저장하지 않는다.
    """
    item = _item(context)
    category = _category(context, item.category)
    capture_method = param(context, 'capture_method', item.capture_method)
    if capture_method not in InspectionItem.CaptureMethod.values:
        raise ItemApiError('촬영 방식을 확인해 주세요.')
    status = InspectionItem.Status.ACTIVE if param(context, 'active') == 'Y' else InspectionItem.Status.PAUSED
    if item.status not in {InspectionItem.Status.ACTIVE, InspectionItem.Status.PAUSED}:
        if status == InspectionItem.Status.ACTIVE:
            raise ItemApiError('삭제 승인 대기 중에는 사용 여부를 바꿀 수 없습니다.')
        status = item.status
    item.description = str(param(context, 'description', '')).strip()
    item.status = status
    item.capture_method = capture_method
    item.category = category
    if 'model_name' in context.posparam and _mappable(item):
        name = str(context.posparam.get('model_name') or '').strip()
        if name != model_mappings.active_model_name(item):
            result = model_mappings.save_mapping({'item_id': item.id, 'model_name': name})
            if not result.get('success'):
                raise ItemApiError(result.get('message') or 'AI 모델을 저장하지 못했습니다.')
    item.save(update_fields=['description', 'status', 'capture_method', 'category', 'updated_at'])
    return {'success': True, 'message': '비전검사항목을 저장했습니다.'}


def _category(context, current):
    """소속 중분류. 키를 보내지 않으면 지금 값, 빈 값이면 미분류."""
    if 'category_id' not in context.posparam:
        return current
    try:
        return categories.minor_of(context.request.tenant, context.posparam.get('category_id'))
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc


def _toggle_status(context):
    item = _item(context)
    if item.status not in {InspectionItem.Status.ACTIVE, InspectionItem.Status.PAUSED}:
        raise ItemApiError('현재 상태에서는 비전검사항목 상태를 바꿀 수 없습니다.')
    item.status = InspectionItem.Status.PAUSED if item.status == InspectionItem.Status.ACTIVE else InspectionItem.Status.ACTIVE
    item.save(update_fields=['status', 'updated_at'])
    paused = item.status == InspectionItem.Status.PAUSED
    return {'success': True, 'message': '비전검사항목을 중지했습니다.' if paused else '비전검사항목을 다시 사용합니다.',
            'status': item.status}


def _review_deletion(context):
    deletion = ItemDeletionRequest.objects.for_tenant(context.request.tenant).filter(
        pk=param(context, 'deletion_id'), status=ItemDeletionRequest.Status.REQUESTED).first()
    if deletion is None:
        raise Http404('승인 대기 중인 삭제 요청을 찾을 수 없습니다.')
    approve = context.gparam.get('action') == 'approve_delete'
    try:
        if approve:
            ItemDeletionService.approve(deletion=deletion, reviewer=context.request.user,
                                        review_note=param(context, 'review_note', ''))
        else:
            ItemDeletionService.reject(deletion=deletion, reviewer=context.request.user,
                                       review_note=param(context, 'review_note', ''))
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '비전검사항목 삭제 요청을 승인하고 비전검사항목을 삭제했습니다.' if approve
            else '비전검사항목 삭제 요청을 반려했습니다.'}
