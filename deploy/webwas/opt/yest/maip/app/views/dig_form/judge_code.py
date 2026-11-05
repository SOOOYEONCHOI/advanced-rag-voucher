from django.core.exceptions import PermissionDenied
from django.db import transaction

from domain.models.system import UserCode
from domain.services import judge_code as judge_service
from domain.services.common import CommonUtil

# MES 계열 API 는 HTTP 메서드로 R/W 를 가른다. 쓰기 action 을 GET 으로 부르면 읽기 권한만으로 통과하므로 막는다.
WRITE_ACTIONS = frozenset({'save', 'delete'})


def judge_code(context):
    '''
    /api/dig_form/judge_code
    검사양식 코드 관리 — 판정 칸 선택지(사용자코드). 묶음 아래 그룹·결과 코드 2단계 + 판정 의미·순서
    등록은 화면의 그룹·결과 코드 등록 모달, 수정·삭제는 상세에서 한다(공통 CRUD).
    그룹 코드·결과 코드는 양식 칸(CodeGroup)·작성 결과(ComboResult)가 가리키므로 쓰는 중이면 코드를 바꾸거나 지우지 않는다.
    '''
    items = []
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action', 'read')
    if action in WRITE_ACTIONS and context.request.method != 'POST':
        raise PermissionDenied   # ApiModuleView 가 403 으로 바꾼다

    try:
        root = judge_service.root()
        if root is None:
            raise ValueError('항목결과 코드의 기본 데이터가 없습니다. 관리자에게 기본 데이터 반영(seed_initial)을 요청해 주세요.')

        if action == 'read':
            # 한 목록(트리) — 그룹(parent_id 없음)을 순서대로, 그룹 바로 아래에 그 결과 코드(parent_id = 그룹 id)
            groups = list(UserCode.objects.filter(Parent=root))
            row = lambda c, parent_id: {
                'id': c.id, 'parent_id': parent_id, 'code': c.Code, 'name': c.Value,
                'meaning': c.Type if parent_id else None, 'sort_order': c._order, 'description': c.Description}
            order = lambda c: (c._order or 0, c.id)
            options = {}
            for o in UserCode.objects.filter(Parent__in=groups):
                options.setdefault(o.Parent_id, []).append(o)
            items = []
            for g in sorted(groups, key=order):
                items.append(row(g, None))
                items.extend(row(o, g.id) for o in sorted(options.get(g.id, []), key=order))

        elif action == 'save':
            user = context.request.user
            code_id = CommonUtil.try_int(posparam.get('id'))
            parent_id = CommonUtil.try_int(posparam.get('parent_id'))
            code_value = (posparam.get('code') or '').strip()
            name = (posparam.get('name') or '').strip()
            meaning = posparam.get('meaning') or None
            if not code_value or not name:
                raise ValueError('필수 항목을 입력해 주세요.')
            if len(code_value) > 30:
                raise ValueError('코드는 30자까지 입력할 수 있습니다.')
            if len(name) > 100:
                raise ValueError('코드명은 100자까지 입력할 수 있습니다.')

            parent = find_code(root, parent_id) if parent_id else root
            is_group = parent.id == root.id
            if not is_group and parent.Parent_id != root.id:
                raise ValueError('결과 코드는 그룹 아래에만 추가할 수 있습니다.')
            if not is_group and meaning not in judge_service.MEANINGS:
                raise ValueError('판정 의미를 선택하세요.')

            with transaction.atomic():
                if UserCode.objects.filter(Parent=parent, Code=code_value).exclude(id=code_id).exists():
                    raise ValueError('같은 코드가 이미 있습니다.')
                if code_id:
                    code = find_code(root, code_id)
                    if code.Parent_id != parent.id:
                        raise ValueError('소속 그룹은 바꿀 수 없습니다.')
                    # 코드가 바뀌면 양식 칸(CodeGroup)·작성 결과(ComboResult)와 연결이 끊긴다 — 쓰는 중이면 거부
                    used = judge_service.group_used(code.Code) if is_group else judge_service.option_used(parent.Code, code.Code)
                    if code.Code != code_value and used:
                        raise ValueError('사용 중인 코드는 코드값을 바꿀 수 없습니다.')
                else:
                    code = UserCode(Parent=parent)
                code.Code = code_value
                code.Value = name
                code.Type = None if is_group else meaning
                code._order = CommonUtil.try_int(posparam.get('sort_order')) or 0
                code.Description = (posparam.get('description') or '').strip() or None
                code.set_audit(user)
                code.save()
            items = {'success': True, 'message': '', 'id': code.id}

        elif action == 'delete':
            code = find_code(root, posparam.get('id'))
            if code.Parent_id == root.id:
                if judge_service.group_used(code.Code):
                    raise ValueError('양식에서 쓰는 그룹은 삭제할 수 없습니다.')
                if UserCode.objects.filter(Parent=code).exists():
                    raise ValueError('하위 결과 코드를 먼저 삭제하세요.')
            elif judge_service.option_used(code.Parent.Code, code.Code):
                raise ValueError('작성 결과에 쓰인 결과 코드는 삭제할 수 없습니다.')
            code.delete()
            items = {'success': True, 'message': ''}

    except ValueError as ex:
        # 사용자 문구는 ValueError 로 던진다. 그 밖의 예외는 ApiModuleView 가 로그를 남기고 500 일반 문구로 답한다.
        return {'success': False, 'message': str(ex)}

    return items


def find_code(root, code_id):
    """항목결과 코드(그룹 또는 결과 코드) 한 행. 묶음 밖의 사용자코드는 찾지 않는다."""
    code = UserCode.objects.filter(id=CommonUtil.try_int(code_id)).select_related('Parent').first()
    if code is None or not (code.Parent_id == root.id or (code.Parent is not None and code.Parent.Parent_id == root.id)):
        raise ValueError('항목결과 코드를 찾을 수 없습니다.')
    return code
