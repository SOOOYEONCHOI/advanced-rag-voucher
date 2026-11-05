from domain.services.system import SystemService
from domain.services.logging import LogWriter
from domain.models.user import UserGroupMenu



def usergroupmenu(context):
    items = []
    gparam = context.gparam
    posparam = context.posparam

    action = gparam.get('action')
    svc = SystemService()

    try:
        if action=='read':
            group_id = gparam.get('group_id', '')
            folder_id = gparam.get('folder_id', '')
            # 화면은 그룹 콤보가 채워지기 전에 한 번 조회한다. 빈 값을 그대로
            # 넘기면 PostgreSQL 이 integer = '' 를 거부해 500 이 된다.
            if not str(group_id).strip():
                return []
            items = svc.get_usergroupmenu_list(group_id, folder_id)

        elif action =='save':
            request = context.request
            item_list = posparam.get('Q')

            group_id = posparam.get('group_id', '')
            UserGroupMenu.objects.filter(UserGroup_id=group_id).delete()

            for row in item_list:
                AuthCode = ''
                menu_code = row.get('menu_code')

                r = row.get('r', False)
                w = row.get('w', False)

                if r:
                    AuthCode = "R"

                if w:
                    AuthCode += 'W'

                usergroupmenu = UserGroupMenu(MenuCode = menu_code, AuthCode = AuthCode, UserGroup_id=group_id)
                usergroupmenu._creater_id = request.user.id
                usergroupmenu.save()

            items = { 'success': True }




    except Exception as ex:
        source = 'usergroupmenu : action-{}'.format(action)
        LogWriter.add_dblog('error', source , ex)
        raise ex


    return items
