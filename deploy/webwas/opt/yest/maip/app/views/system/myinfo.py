from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from domain.models.user import UserGroup
from domain.services.logging import LogWriter
from domain.services.system import SystemService
from domain.services.account import AccountService
from domain.services.date import DateUtil



def myinfo(context):
    '''
    api/system/myinfo
    '''
    gparam = context.gparam
    action = gparam.get('action', 'read')

    request = context.request
    user = request.user
    login_id = user.username
    name = user.userprofile.Name

    data = {}
    if action =='read':
        data = { 'login_id':login_id, 'name':name }
    elif action =='password_change':
        posparam = context.posparam

        req_login_id = posparam.get('login_id')
        if req_login_id!=login_id:
            return {'success': False, 'message': '본인의 정보만 수정할 수 있습니다.'}

        loginPwd = posparam.get('loginPwd')
        loginPwd2 = posparam.get('loginPwd2')
        name = posparam.get('name')

        if loginPwd!=loginPwd2:
            return {'success': False, 'message': '비밀번호가 일치하지 않습니다.'}

        if loginPwd:
            # 관리자 경로(system/user pass_setting)와 같은 정책을 건다.
            # 화면에서만 검사하면 API 직접 호출로 우회할 수 있다.
            try:
                validate_password(loginPwd, user=user)
            except DjangoValidationError as ex:
                return {'success': False, 'message': '\n'.join(ex.messages)}
            user.set_password(loginPwd)
        user.userprofile.Name = name
        user.userprofile.save()
        user.save()
        data = {'success':True}


    return data;
