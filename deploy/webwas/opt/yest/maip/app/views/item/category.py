"""비전검사항목 관리 화면(`wm_data_item`, 검사 관리)의 분류 API — `/api/item/category`.

분류는 메뉴 권한으로 다룬다(변경은 메뉴 W — 디스패치가 본다). 대분류는 고정이라 중분류만 등록·수정·삭제한다. 비전검사항목 등록·수정은 `/api/item/item_admin`(플랫폼 관리자).

| action     | 메서드 | 입력 |
|------------|--------|------|
| tree       | GET    | — 대분류 › 중분류 › 비전검사항목 평면 목록 |
| forms      | GET    | form_type — 매핑할 수 있는 양식 |
| save_minor | POST   | (category_id), parent_id, name, form_code, sort_order, description |
| delete     | POST   | category_id |
"""
from app.views.item import ItemApiError, param
from domain.services.account import user_is_platform_admin
from domain.services.data import category as categories

READ_ACTIONS = frozenset({'tree', 'forms'})


def category(context):
    """api/item/category"""
    action = context.gparam.get('action', 'tree')
    tenant = context.request.tenant
    try:
        if action == 'tree':
            return {'rows': categories.tree(tenant), 'can_manage_items': user_is_platform_admin(context.request.user)}
        if action == 'forms':
            forms = categories.mappable_forms(param(context, 'form_type', ''))
            return {'forms': [{'code': f.Code, 'title': f.Title, 'version': f.Version} for f in forms.values()]}
        fields = {key: param(context, key, '') for key in ('name', 'sort_order', 'description')}
        if action == 'save_minor':
            saved = categories.save_minor(tenant, category_id=param(context, 'category_id'),
                                          parent_id=param(context, 'parent_id'),
                                          form_code=param(context, 'form_code', ''), **fields)
        elif action == 'delete':
            categories.delete_category(tenant, param(context, 'category_id'))
            return {'success': True, 'message': ''}
        else:
            raise ItemApiError('지원하지 않는 기능입니다.')
    except ValueError as exc:
        raise ItemApiError(str(exc)) from exc
    return {'success': True, 'message': '', 'id': saved.id}
