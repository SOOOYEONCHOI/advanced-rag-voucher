from domain.models.system import Depart
from domain.models.user import UserProfile
from domain.services.logging import LogWriter


def depart(context):
    '''
    api/system/depart

    부서 정보 — 공통 CRUD 화면. 코드는 등록 때만 받는다. 사용자에게 연결된 부서는 지우지 않는다
    '''
    items = []
    posparam = context.posparam
    gparam = context.gparam
    action = gparam.get('action', 'read')

    try:
        if action == 'read':
            items = [{'id': d.id, 'code': d.Code, 'name': d.Name, 'type': d.Type, 'description': d.Description}
                     for d in Depart.objects.order_by('Code', 'Name')]

        elif action == 'save':
            # 등록 모달은 코드·부서명·부서유형·비고, 상세 수정은 부서명·부서유형·비고를 보낸다
            id = posparam.get('id')
            code = (posparam.get('code') or '').strip()
            name = (posparam.get('name') or '').strip()
            dept_type = (posparam.get('type') or '').strip() or None
            description = posparam.get('description') or None

            if id:
                dept = Depart.objects.get(id=id)    # 코드는 바꾸지 않는다
                if not name:
                    return {'success': False, 'message': '부서명을 입력해 주세요.'}
            else:
                if not code or not name:
                    return {'success': False, 'message': '코드와 부서명을 입력해 주세요.'}
                if ' ' in code:
                    return {'success': False, 'message': '코드에는 공백을 넣을 수 없습니다.'}
                if Depart.objects.filter(Code=code).exists():
                    return {'success': False, 'message': '같은 코드의 부서가 이미 있습니다.'}
                dept = Depart(Code=code)
            if Depart.objects.filter(Name=name).exclude(id=dept.id).exists():
                return {'success': False, 'message': '같은 이름의 부서가 이미 있습니다.'}
            dept.Name = name
            dept.Type = dept_type
            dept.Description = description
            dept.save()
            items = {'success': True, 'id': dept.id}

        elif action == 'delete':
            id = posparam.get('id')
            # user_profile 이 DO_NOTHING 외래키로 가리킨다 — 지우면 DB 오류라 먼저 막는다
            count = UserProfile.objects.filter(Depart_id=id).count()
            if count:
                return {'success': False,
                        'message': '사용 중인 부서입니다. 이 부서의 사용자 {}명을 다른 부서로 옮긴 뒤 삭제해 주세요.'.format(count)}
            Depart.objects.filter(id=id).delete()
            items = {'success': True}

        else:
            raise Exception("action : " + action)

    except Exception as ex:
        source = 'depart : action-{}'.format(action)
        LogWriter.add_dblog('error', source, ex)
        if action == 'delete':
            return {'success': False, 'message': LogWriter.delete_err_message(ex)}
        # 예외 원문(SQL·영문)은 DB 로그에만 남긴다
        return {'success': False, 'message': '처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'}

    return items
