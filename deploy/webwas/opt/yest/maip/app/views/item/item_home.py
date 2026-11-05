"""검사항목 홈 화면(`wm_data_item_detail`) — `/api/item/item_home`.

보기는 이 메뉴 R, 설정은 이 메뉴 W 다(디스패치가 본다 — 비전검사항목 배정은 없앴다, 사용자 결정 2026-10-21).

| action                                 | 메서드 | 입력                                          |
|----------------------------------------|--------|-----------------------------------------------|
| detail                                 | GET    | item_id                                       |
| update                                 | POST   | name, description, cover_image(파일)          |
| label_create · label_update            | POST   | (label_id), name, display_name_ko, color, is_defect, annotation_shape |
| label_delete                           | POST   | label_id                                      |
| point_create · point_update            | POST   | (point_id), code, name, nominal, lower, upper, unit, description — 치수 측정 항목만 |
| point_delete                           | POST   | point_id                                      |
| toggle_status · request_delete         | POST   | (reason)                                      |
"""
from django.http import Http404
from django.urls import reverse

from app.forms.item import ItemSettingsForm, LabelClassForm, MeasurementPointForm
from app.views.item import ItemApiError, cover_url, load_item, param
from app.views.system.menus import MEASUREMENT_CHILD_MENU_CODES
from domain.gui import ITEM_CHILD_MENUS
from domain.models.data import ActivityLog, InspectionItem, LabelClass, MeasurementPoint
from domain.services.account import AccountService
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.services.data.item_access import ITEM_MENU, ItemAccessService
from domain.services.data.item_deletion import ItemDeletionService
from domain.services.data.item_platform import ItemPlatformService

READ_ACTIONS = frozenset({'detail'})


def item_home(context):
    """api/item/item_home"""
    action = context.gparam.get('action', 'detail')
    if action == 'detail':
        return _detail(context)
    handler = {
        'update': _update, 'label_create': _label_save,
        'label_update': _label_save, 'label_delete': _label_delete, 'toggle_status': _toggle_status,
        'request_delete': _request_delete,
        'point_create': _point_save, 'point_update': _point_save, 'point_delete': _point_delete,
    }.get(action)
    if handler is None:
        raise ItemApiError('지원하지 않는 기능입니다.')
    item = load_item(context, 'item.manage')
    measurement = item.task_type == InspectionItem.TaskType.MEASUREMENT
    if action.startswith('label_') and measurement:
        raise ItemApiError('치수 측정 비전검사항목은 라벨 클래스 대신 측정점을 씁니다.')
    if action.startswith('point_') and not measurement:
        raise ItemApiError('측정점은 치수 측정 비전검사항목에만 둡니다.')
    return handler(context, item)


def _detail(context):
    item = load_item(context, 'item.read')
    tenant = context.request.tenant
    detail = ItemPlatformService.detail_for(item, tenant)
    return {
        'id': item.id, 'code': item.code, 'name': item.name, 'description': item.description,
        'task_type': item.task_type, 'task_type_label': item.get_task_type_display(),
        'status': item.status, 'status_label': item.get_status_display(),
        'cover_url': cover_url(item),
        'can_manage': ItemAccessService.can_write(context.request.user, ITEM_MENU),
        'screens': _screens(context.request.user, item),
        'image_count': detail['image_count'], 'submitted_count': detail['submitted_count'],
        'reviewed_count': detail['reviewed_count'], 'waiting_count': detail['waiting_count'],
        'in_progress_count': detail['in_progress_count'],
        'labels': [{'id': l['id'], 'name': l['name'], 'display_name_ko': l['display_name_ko'],
                    'color': l['color'], 'is_defect': l['is_defect']} for l in detail['labels']],
        'points': [{'id': p.id, 'code': p.code, 'name': p.name, 'nominal': str(p.nominal), 'lower': str(p.lower),
                    'upper': str(p.upper), 'unit': p.unit, 'description': p.description}
                   for p in MeasurementPoint.objects.for_tenant(tenant).filter(item=item)],
        'snapshots': [{
            'version_tag': s['version_tag'], 'created_at': s['created_at'].strftime('%Y-%m-%d %H:%M'),
            'export_status': s['export_status'], 'export_status_label': s['export_status_label'],
            'file_url': reverse('private-export', args=[s['export_id']]) if s['export_has_file'] else '',
        } for s in detail['snapshots'][:5]],
        'recent_images': [{'id': i['id'], 'original_name': i['original_name'],
                           'thumbnail_url': reverse('private-image-thumbnail', args=[i['id']])}
                          for i in detail['recent_images'][:8]],
    }


def _screens(user, item):
    """내부 탭 — 메뉴 권한이 있는 하위 화면(홈 제외). 좌측 메뉴의 비전검사항목은 홈을 열고 나머지는 그 안의 탭이다(사용자 결정 2026-10-21)."""
    measurement = item.task_type == InspectionItem.TaskType.MEASUREMENT
    return [{'code': code, 'name': name} for code, name in ITEM_CHILD_MENUS[1:]
            if (not measurement or code in MEASUREMENT_CHILD_MENU_CODES) and AccountService.check_user_auth(user, code)]


def _form_errors(form):
    return ' '.join(str(error) for errors in form.errors.values() for error in errors)


def _update(context, item):
    form = ItemSettingsForm({'name': param(context, 'name', ''), 'description': param(context, 'description', '')})
    if not form.is_valid():
        raise ItemApiError('입력 내용을 확인해 주세요. ' + _form_errors(form))
    uploaded = context.request.FILES.get('cover_image')
    if uploaded:
        try:
            ImageService._validate(uploaded)
        except ValueError as exc:
            raise ItemApiError(str(exc)) from exc
    item = ItemService.update_item(tenant=context.request.tenant, actor=context.request.user, item=item,
                                   values=form.cleaned_data)
    if uploaded:
        if item.cover_image:
            item.cover_image.delete(save=False)
        item.cover_image = uploaded
        item.save(update_fields=['cover_image', 'updated_at'])
    return {'success': True, 'message': '변경사항을 저장했습니다.'}


def _label_save(context, item):
    form = LabelClassForm({key: param(context, key, '') for key in
                           ('name', 'display_name_ko', 'color', 'is_defect', 'annotation_shape')})
    if not form.is_valid():
        raise ItemApiError('라벨 클래스 입력을 확인해 주세요. ' + _form_errors(form))
    tenant, actor = context.request.tenant, context.request.user
    try:
        if context.gparam.get('action') == 'label_create':
            label = ItemService.create_label_class(tenant=tenant, actor=actor, item=item, values=form.cleaned_data)
        else:
            label = ItemService.update_label_class(tenant=tenant, actor=actor, item=item,
                                                   label_class=_label(context, item), values=form.cleaned_data)
    except (TypeError, ValueError) as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '라벨 클래스를 저장했습니다.',
            'label': {'id': label.id, 'name': label.name, 'display_name_ko': label.display_name_ko}}


def _label(context, item):
    try:
        return LabelClass.objects.for_tenant(context.request.tenant).get(pk=int(param(context, 'label_id')), item=item)
    except (LabelClass.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404('라벨 클래스를 찾을 수 없습니다.') from exc


def _label_delete(context, item):
    try:
        ItemService.delete_label_class(tenant=context.request.tenant, actor=context.request.user, item=item,
                                       label_class=_label(context, item))
    except (TypeError, ValueError) as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '라벨 클래스를 삭제했습니다.'}


def _point_save(context, item):
    form = MeasurementPointForm({key: param(context, key, '') for key in
                                 ('code', 'name', 'nominal', 'lower', 'upper', 'unit', 'description')})
    if not form.is_valid():
        raise ItemApiError('측정점 입력을 확인해 주세요. ' + _form_errors(form))
    point = _point(context, item) if context.gparam.get('action') == 'point_update' else None
    try:
        point = ItemService.save_measurement_point(tenant=context.request.tenant, actor=context.request.user, item=item,
                                                   values=form.cleaned_data, point=point)
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '측정점을 저장했습니다.', 'point': {'id': point.id, 'code': point.code}}


def _point(context, item):
    try:
        return MeasurementPoint.objects.for_tenant(context.request.tenant).get(pk=int(param(context, 'point_id')), item=item)
    except (MeasurementPoint.DoesNotExist, TypeError, ValueError) as exc:
        raise Http404('측정점을 찾을 수 없습니다.') from exc


def _point_delete(context, item):
    try:
        ItemService.delete_measurement_point(tenant=context.request.tenant, actor=context.request.user, item=item,
                                             point=_point(context, item))
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '측정점을 삭제했습니다.'}


def _toggle_status(context, item):
    if item.status == InspectionItem.Status.DELETION_PENDING:
        raise ItemApiError('삭제 승인 대기 중인 비전검사항목의 상태는 바꿀 수 없습니다.')
    item.status = InspectionItem.Status.PAUSED if item.status == InspectionItem.Status.ACTIVE else InspectionItem.Status.ACTIVE
    item.save(update_fields=['status', 'updated_at'])
    ActivityLog.objects.create(tenant=context.request.tenant, item=item, actor=context.request.user,
                               event_type='PROJECT_STATUS_CHANGED', payload={'status': item.status})
    paused = item.status == InspectionItem.Status.PAUSED
    return {'success': True, 'message': '비전검사항목을 중지했습니다.' if paused else '비전검사항목을 다시 사용합니다.'}


def _request_delete(context, item):
    try:
        ItemDeletionService.request(item=item, actor=context.request.user, reason=param(context, 'reason', ''))
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '비전검사항목 삭제 요청을 플랫폼 관리자에게 전달했습니다.'}
