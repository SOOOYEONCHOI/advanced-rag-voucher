from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.crypto import get_random_string
from django.contrib.auth.models import User
from domain.models.system import Depart, LoginLog
from domain.models.user import UserGroup, UserProfile
from domain.services.logging import LogWriter
from domain.services.system import SystemService
from domain.services.account import AccountService
from domain.services.date import DateUtil
from domain.tenancy import tenant_atomic

def user(context):
    '''
    api/system/user

    현재 사용자가 관리자 그룹인지 체크 루틴 필요
    '''
    items = []
    gparam = context.gparam
    posparam = context.posparam
    request = context.request

    action = gparam.get('action', 'read')
    account_service = AccountService()

    try:
        if action=='read':
            group =  gparam.get('group', '')
            keyword =gparam.get('keyword', '')
            super_user = request.user.is_superuser
            if not super_user:
                super_user = request.user.userprofile.UserGroup.Code == 'dev'
            items = account_service.get_user_list(super_user, group, keyword)

        elif action=='detail':
            id = gparam.get('id')
            items = account_service.get_user_detail(id)
        elif action=='save':

            user = None
            id = posparam.get('id', '')
            login_id = (posparam.get('login_id') or '').strip()
            if not login_id:
                return {'success': False, 'message': '아이디를 입력해 주세요.'}
            if User.objects.filter(username=login_id).exclude(id=id or None).exists():
                return {'success': False, 'message': '이미 쓰고 있는 아이디입니다.'}
            Name = (posparam.get('Name') or '').strip()
            UserGroup_id = posparam.get('UserGroup_id')
            Depart_id = posparam.get('Depart_id') or None     # 부서는 고르지 않아도 된다
            if not Name:
                return {'success': False, 'message': '이름을 입력해 주세요.'}
            if not UserGroup_id:
                return {'success': False, 'message': '사용자 그룹을 골라 주세요.'}
            if Depart_id and not Depart.objects.filter(id=Depart_id).exists():
                return {'success': False, 'message': '부서를 찾을 수 없습니다. 목록을 다시 열어 주세요.'}
            if id:
                user = User.objects.get(id=id)
            temp_password = None
            if not id:
                user = User()
                # 초기 비밀번호를 '1'로 고정하던 것을 없앴다. 임시 비밀번호를 만들어
                # 응답에 1회만 실어 보내고 서버에는 평문으로 남기지 않는다.
                temp_password = get_random_string(
                    12, 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789')
                user.set_password(temp_password)
                user.date_joined = DateUtil.get_current_datetime()   # 생성일 — 고쳐 저장할 때는 그대로 둔다

            email = posparam.get('email', '')
            is_active = posparam.get('is_active', False) 
            if is_active:
                is_active = True


            user.username = login_id
            user.email = email
            user.is_active = is_active
            user.save()


            user.userprofile.Name = Name
            user.userprofile.UserGroup_id = UserGroup_id
            user.userprofile.Depart_id = Depart_id
            user.userprofile.save()

            items = {'success': True, 'id': user.id}
            if temp_password:
                # 관리자 화면에 1회 노출한다. 저장하지 않으므로 다시 볼 수 없다.
                items['temp_password'] = temp_password

        elif action=='delete':
            id = posparam.get('id', '')
            # 조직 소속(TenantMembership) 등 데이터 관리 테이블은 RLS 로 보호된다.
            # 조직 컨텍스트 밖에서 지우면 Django 가 그 행을 보지 못해 함께 지우지
            # 못하고 외래키에 걸린다 — 모든 사용자가 조직 소속이므로 아무도 못 지운다.
            with tenant_atomic():
                # 로그인 기록은 DO_NOTHING 이라 그대로 두면 외래키에 걸린다 — 한 번이라도
                # 로그인한 사용자는 못 지운다. 기록은 Username 으로 남기고 연결만 끊는다.
                logs = LoginLog.objects.filter(User_id=id)
                username = User.objects.filter(id=id).values_list('username', flat=True).first()
                logs.filter(Username__isnull=True).update(Username=username)  # Username 이 생기기 전 기록
                logs.update(User=None)
                User.objects.filter(id=id).delete()
            items = {'success':True}
        elif action=='pass_setting':
            pass1 = posparam.get('pass1')
            pass2 = posparam.get('pass2')
            id  = posparam.get('id')

            if pass1 != pass2:
                items = {'success': False, 'message': '비밀번호가 일치하지 않습니다.'}
            else:
                user = User.objects.get(id=id)
                try:
                    # settings.AUTH_PASSWORD_VALIDATORS 를 실제로 적용한다.
                    # 화면에서만 검사하면 API 직접 호출로 우회할 수 있다.
                    validate_password(pass1, user=user)
                except DjangoValidationError as ex:
                    items = {'success': False, 'message': '\n'.join(ex.messages)}
                else:
                    user.set_password(pass1)
                    user.save()
                    UserProfile.objects.filter(User=user).update(
                        password_changed=DateUtil.get_current_datetime())
                    items = {'success': True}

    except Exception as ex:
        source = 'user : action-{}'.format(action)
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
 

