from django.contrib.auth.models import User
from domain.models.user import UserGroup
from domain.services.logging import LogWriter
from domain.services.system import SystemService
from domain.services.account import AccountService
from domain.services.date import DateUtil


 
def usergroup(context):
    '''
    api/system/usergroup
    '''
    items = []
    posparam = context.posparam
    gparam = context.gparam
    request = context.request
    action = context.gparam.get('action', 'read')
    system_service = SystemService()

    try:
        if action=='read':
            super_user = request.user.is_superuser
            if not super_user:
                super_user = request.user.userprofile.UserGroup.Code == 'dev'

            items = system_service.get_usergroup_list(super_user)
        elif action=='detail':
            group_id = context.gparam.get('id')
            items = system_service.get_usergroup_detail(group_id)
        elif action=='save':
            #id=&code=dummy&name=asdf&description=asdfasdf&disabled=on&created=asdfas
            # 등록 모달은 코드·그룹명·사용·설명, 상세 수정은 그룹명·사용·설명을 보낸다
            id = posparam.get('id')
            code = (posparam.get('code') or '').strip()
            name = (posparam.get('name') or '').strip()
            description = posparam.get('description')
            disabled = posparam.get('disabled', None)

            if disabled:
                disabled = False
            else:
                disabled = True

            if id:
                # 코드는 바꾸지 않는다 — 소스가 그룹을 코드로 찾는다(admin·user·dev)
                usergroup = UserGroup.objects.get(id=id)
                if not name:
                    return {'success': False, 'message': '그룹명을 입력해 주세요.'}
                usergroup.Name = name
                usergroup.Description = description
                usergroup.Disabled = disabled
                usergroup.save()
            else:
                if not code or not name:
                    return {'success': False, 'message': '코드와 그룹명을 입력해 주세요.'}
                if UserGroup.objects.filter(Code=code).exists():
                    return {'success': False, 'message': '같은 코드의 그룹이 이미 있습니다.'}
                usergroup = UserGroup(Code=code, Name=name, Description=description, Disabled=disabled)
                usergroup.save()

            items = {'success': True, 'id': usergroup.id}
        elif action == 'delete':
            id = posparam.get('id')

            if id:
                usergroup = UserGroup.objects.filter(id=id).first()
                usergroup.delete()
                items = {'success': True}
            
            
        else:
            raise Exception("action : " + action)

    except Exception as ex:
        source = 'usergroup : action-{}'.format(action)
        LogWriter.add_dblog('error', source , ex)
        if action == 'delete':
            err_msg = LogWriter.delete_err_message(ex)
            items = {'success':False, 'message': err_msg}
            return items
        else:
            # 예외 원문(SQL·영문)은 DB 로그에만 남긴다
            return {'success': False, 'message': '처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'}
        #raise ex

    return items


