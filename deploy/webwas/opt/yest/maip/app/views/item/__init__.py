"""데이터 관리 화면의 MES API — `/api/item/<view>?action=...` (DECISIONS DEC-028).

화면 하나에 모듈 하나다. 메뉴 권한은 `domain/gui.py` `taskview_menu_code_map()` 의
`item/<view>` 매핑을 dispatch 가 보고, 그 조직의 비전검사항목인지는 모듈이 `load_item` 으로 본다.

`ApiModuleView._execute_tenant_task` 가 이 task 를 따로 다룬다.
- 요청 전체를 `tenant_atomic()` 으로 감싼다(RLS — 밖에서 읽으면 예외 없이 0건).
- 모듈의 `READ_ACTIONS` 에 없는 action 은 POST 로만 받는다(아니면 405).
- `ItemApiError` 는 400 `{"success": false, "message"}` 로 바꾸고 롤백한다.

응답 규약
- 조회는 dict. 목록은 `{"rows": [...], "totalRows": n}` — 데이터 목록은 서버 페이징(`paged`,
  WeZonGrid `dataMode:'server'` 가 그대로 받는다), 나머지는 전부를 주고 화면이 나눈다(`whole`).
- 변경은 `{"success": true, "message": "..."}`.
- 사용자에게 보일 업무 오류는 `ItemApiError("~합니다")`. 서비스가 사용자 문구로 던진
  ValueError 만 바꿔 던진다 — 다른 예외 문구는 내보내지 않는다.
"""
from django.http import Http404
from django.urls import reverse

from domain.models.data import InspectionItem
from domain.services.data.authorization import AuthorizationService
from domain.services.data.item import ItemService


class ItemApiError(Exception):
    """화면에 그대로 보일 업무 오류. 문구는 ~합니다 체."""


def param(context, key, default=None):
    """POST 본문을 먼저, 없으면 쿼리 문자열을 본다. action 은 쿼리, 값은 본문으로 오는 MES 관례."""
    value = context.posparam.get(key)
    if value in (None, ''):
        value = context.gparam.get(key)
    return default if value in (None, '') else value


# 라벨이 있어야 쓰는 화면. 치수 측정 항목은 라벨링을 하지 않는다 — 메뉴만 감추지 않고 여기서 거절한다.
LABELED_VIEWS = frozenset({'labeling', 'review', 'snapshot'})


def load_item(context, action):
    """`item_id` 의 검사항목을 읽고 그 검사항목에 대한 `action` 권한을 확인한다."""
    try:
        item = ItemService.get_item(context.request.tenant, int(param(context, 'item_id')))
    except (InspectionItem.DoesNotExist, ValueError, TypeError) as exc:
        raise Http404('비전검사항목을 찾을 수 없습니다.') from exc
    AuthorizationService.require(context.request, action, item=item)
    if item.task_type == InspectionItem.TaskType.MEASUREMENT and context.kwargs.get('view_name') in LABELED_VIEWS:
        raise ItemApiError('치수 측정 비전검사항목은 라벨링·검수·스냅샷을 쓰지 않습니다.')
    return item


def cover_url(item):
    """대표 이미지 주소. 주소가 늘 같으면 새 이미지로 바꿔도 브라우저가 옛 그림을 보인다 — 수정 시각을 붙인다."""
    if not item.cover_image:
        return ''
    return f"{reverse('private-item-cover', args=[item.id])}?v={int(item.updated_at.timestamp())}"


def page_params(gparam, default_size=20, max_size=100):
    """(page, page_size). 1 부터 센다. 크기는 max_size 를 넘지 않는다."""
    try:
        page = max(int(gparam.get('page') or 1), 1)
        size = min(max(int(gparam.get('page_size') or default_size), 1), max_size)
    except (TypeError, ValueError):
        page, size = 1, default_size
    return page, size


def whole(rows, serialize):
    """화면 안 페이징 목록 — 조건에 맞는 전부를 `{rows, totalRows}` 로 준다. 그리드가 나눈다."""
    rows = [serialize(row) for row in rows]
    return {'rows': rows, 'totalRows': len(rows)}


def paged(queryset, gparam, serialize, default_size=20):
    """QuerySet 또는 이미 만든 list 를 한 페이지로 자른다."""
    page, size = page_params(gparam, default_size)
    start = (page - 1) * size
    total = len(queryset) if isinstance(queryset, list) else queryset.count()
    return {'rows': [serialize(row) for row in queryset[start:start + size]], 'totalRows': total}
