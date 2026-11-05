from configurations import settings

from domain.services.sql import DbUtil
from domain.services.logging import LogWriter
from domain.models.user import UserGroup, UserGroupMenu, UserProfile

class AccountService():
    def __init__(self):
        '''
        생성자 루틴
        '''
        return

    def get_user_session(self, user_id):

        dic_param = {'user_id':user_id}

        sql = '''
        '''


        return {}

    def get_user_list(self, super_user, group, keyword):
        if settings.DBMS == 'POSTGRESQL':
            sql = '''
            select au.id
              , up."Name"
              , au.username as login_id
              , up."UserGroup_id"
              , au.email
              , ug."Name" as group_name
              , up."Factory_id"
              , f."Name" as factory_name
              , up."Depart_id"
              , d."Name" as depart_name
              , up.lang_code
              , au.is_active
              , to_char(au.date_joined ,'yyyy-mm-dd hh24:mi') as date_joined
            from auth_user au 
            left join user_profile up on up."User_id" = au.id
            left join user_group ug on up."UserGroup_id" = ug.id 
            left join factory f on up."Factory_id" = f.id 
            left join depart d on up."Depart_id" = d.id 
            where is_superuser = false
            '''
            if not super_user:
                sql += ''' and ug."Code" <> 'dev'
            '''
            if group:
                sql+=''' and ug.id = %(group)s
                '''
            if keyword:
                sql +='''and up."Name" like concat('%%', %(keyword)s, '%%')
                '''
            sql +=''' order by ug."Name", up."Name"
            '''
        elif settings.DBMS == 'MSSQL':
            sql = ''' select au.id
              , up."Name"
              , au.username as login_id
              , up."UserGroup_id"
              , au.email
              , ug."Name" as group_name
              , up."Factory_id"
              , f."Name" as factory_name
              , up."Depart_id"
              , d."Name" as depart_name
              , up.lang_code
              , au.is_active
              , Format(au.date_joined ,'yyyy-MM-dd HH:mm') as date_joined
            from auth_user au 
            left join user_profile up on up."User_id" = au.id
            left join user_group ug on up."UserGroup_id" = ug.id 
            left join factory f on up."Factory_id" = f.id 
            left join depart d on up."Depart_id" = d.id 
            where is_superuser = 0
            '''
            if not super_user:
                sql += ''' and ug."Code" <> 'dev'
            '''
            if group:
                sql+=''' and ug.id = %(group)s
                '''
            if keyword:
                sql+=''' and up."Name" like concat('%%', %(keyword)s, '%%')
                '''
            sql +=''' order by ug."Name", up."Name"
            '''
        try:
            dc = {
                'group' : group, 
                'keyword':keyword
            }
            items = DbUtil.get_rows(sql, dc)
        except Exception as ex:
            LogWriter.add_dblog('error','AccountService.get_user_list', ex)
            raise ex

        return items

    def get_user_detail(self, id):

        dic_param = {'id' : id}
        items = {}
        if settings.DBMS == 'POSTGRESQL':
            sql = ''' select au.id
              , up."Name"
              , au.username as login_id
              , au.email
              , ug."Name" as group_name
              , up."UserGroup_id"
              , up."Factory_id"
              , f."Name" as factory_name
              , up."Depart_id"
              , d."Name" as depart_name
              , up.lang_code
              , au.is_active
              , to_char(au.date_joined ,'yyyy-mm-dd hh24:mi') as date_joined
            from auth_user au 
            left join user_profile up on up."User_id" = au.id
            left join user_group ug on up."UserGroup_id" = ug.id 
            left join factory f on up."Factory_id" = f.id 
            left join depart d on up."Depart_id" = d.id 
            where au.id = %(id)s
            '''
        elif settings.DBMS == 'MSSQL':
            sql = ''' select au.id
              , up."Name"
              , au.username as login_id
              , au.email
              , ug."Name" as group_name
              , up."UserGroup_id"
              , up."Factory_id"
              , f."Name" as factory_name
              , up."Depart_id"
              , d."Name" as depart_name
              , up.lang_code
              , au.is_active
              , Format(au.date_joined ,'yyyy-MM-dd HH:mm') as date_joined
            from auth_user au 
            left join user_profile up on up."User_id" = au.id
            left join user_group ug on up."UserGroup_id" = ug.id 
            left join factory f on up."Factory_id" = f.id 
            left join depart d on up."Depart_id" = d.id 
            where au.id = %(id)s
            '''
        try:
            items = DbUtil.get_row(sql, dic_param)
            #if len(rows)>0:
            #    items = rows[0]

        except Exception as ex:
            LogWriter.add_dblog('error','AccountService.get_user_detail', ex)
            raise ex

        return items

    @classmethod
    def check_user_auth(cls, user, gui_code):
        if user.is_superuser:
            return 'RW'

        # 프로필이나 그룹이 없는 계정이 있다. 인가 훅이 모든 요청에서 이 함수를
        # 부르므로 여기서 죽으면 전 API가 500이 된다. 권한 없음으로 처리한다.
        profile = getattr(user, 'userprofile', None)
        if profile is None or profile.UserGroup is None:
            return None

        group_code = profile.UserGroup.Code

        if group_code in ['dev']:
            return 'RW'

        if group_code in ['admin', 'dev'] and gui_code in ['wm_user_group', 'wm_user', 'wm_user_group_menu']:
            return 'RW'

        group_id = profile.UserGroup.id
        q = UserGroupMenu.objects.filter(UserGroup__id=group_id, MenuCode=gui_code).values('AuthCode')
        authcode = None
        foo = q.first()
        if foo:
            authcode = foo['AuthCode']

        return authcode


# --------------------------------------------------------------------------
# 데이터 관리 도메인이 쓰는 사용자 함수 5개
#
# 데이터 관리 서비스는 자체 `UserProfile`/`UserGroup` 을 전제로 쓰였지만 이
# 플랫폼은 MES 것을 쓴다. 그래서 같은 이름·같은 계약을 MES 모델 위에서
# 구현해 둔다.
# --------------------------------------------------------------------------

PLATFORM_ADMIN_GROUPS = ('dev', 'admin')


def user_is_platform_admin(user):
    """플랫폼 관리자 여부.

    `is_staff`/`is_superuser` 를 판정 근거로 삼지 않는다 — 그 둘은 Django 관리
    화면 접근 권한이지 업무 권한이 아니다. 다만 MES 는 superuser 를 최상위로
    취급하므로 superuser 는 포함한다.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'userprofile', None)
    group = getattr(profile, 'UserGroup', None)
    return bool(group and group.Code in PLATFORM_ADMIN_GROUPS)


def platform_admin_q(prefix=''):
    """플랫폼 관리자를 고르는 Q 객체.

    `prefix` 는 관계를 타고 들어갈 때 쓴다. 예: `platform_admin_q('user__')`.
    """
    from django.db.models import Q

    return (Q(**{prefix + 'is_superuser': True})
            | Q(**{prefix + 'userprofile__UserGroup__Code__in': PLATFORM_ADMIN_GROUPS}))


def user_display_name(user):
    """화면에 보일 이름. 없으면 로그인 아이디."""
    if not user:
        return ''
    profile = getattr(user, 'userprofile', None)
    return (getattr(profile, 'Name', None) or user.username or '').strip()


def set_user_display_name(user, name):
    UserProfile.objects.filter(User=user).update(Name=(name or '').strip() or None)


def set_user_group(user, group):
    """`group` 은 UserGroup 인스턴스 또는 Code 문자열."""
    if isinstance(group, str):
        group = UserGroup.objects.filter(Code=group).first()
    UserProfile.objects.filter(User=user).update(UserGroup=group)

