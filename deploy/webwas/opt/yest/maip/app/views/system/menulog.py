from configurations import settings

from domain.services.logging import LogWriter
from domain.services.date import DateUtil
from domain.services.sql import DbUtil

from app.views.system.loginlog import log_page
from domain.services.system import SystemService
from domain.gui import GUIConfiguration




def _name_removed_menus(rows):
    """menu_item 에 없는 기록은 폴더·메뉴가 빈 칸이었다. 메뉴에서 내린 화면은 화면 이름으로,
    화면 자체가 없어졌으면 기록된 코드로 채운다."""
    for row in rows:
        if not row.get('menu_name'):
            info = GUIConfiguration.get_gui_info(row.get('menu_code'))
            row['menu_name'] = info['name'] if info else row.get('menu_code')
            row['folder_name'] = '메뉴에서 내림' if info else '없어진 화면'
    return rows


def menulog(context):
    '''
    api/system/menulog?
    '''
    try:
        gparam = context.gparam
        posparam = context.posparam
        request = context.request
        action = gparam.get('action')

        if action == 'log_list':
            date_from = gparam.get('date_from')
            date_to = gparam.get('date_to')
            menu_code = gparam.get('cboMenu')
            user_pk = gparam.get('cboUser')

            if settings.DBMS == 'MSSQL':    
                sql = ''' select g.id, mf."FolderName" as folder_name, g."MenuCode" as menu_code, m."MenuName" as menu_name
                , u.username
	            --, concat(u.last_name, u.first_name) as user_name
                , p."Name" as user_name
	            , Format(g._created, 'yyyy-MM-dd HH:mm:ss') as click_date
	            from menu_use_log g 
	            left join menu_item m on m."MenuCode" = g."MenuCode" 
	            left join menu_folder mf on mf.id = m."MenuFolder_id" 
	            left join auth_user u on u.id = g."User_id" 
                left join user_profile p on p."User_id" = g."User_id" 
	            where g._created between %(date_from)s and %(date_to)s
                '''
                if menu_code:
                    sql += ''' and g."MenuCode" = %(menu_code)s
                    '''
                if user_pk:
                    sql += ''' and g."User_id" = %(user_pk)s
                    '''
                sql += ''' order by g._created desc '''
            else:
                sql = ''' select g.id, mf."FolderName" as folder_name, g."MenuCode" as menu_code, m."MenuName" as menu_name
                , u.username
	            --, u.last_name ||u.first_name as user_name
                , p."Name" as user_name
	            , to_char(g._created, 'yyyy-mm-dd hh24:mi:ss') as click_date
	            from menu_use_log g 
	            left join menu_item m on m."MenuCode" = g."MenuCode" 
	            left join menu_folder mf on mf.id = m."MenuFolder_id" 
	            left join auth_user u on u.id = g."User_id" 
                left join user_profile p on p."User_id" = g."User_id" 
	            where g._created between %(date_from)s and %(date_to)s
                '''
                if menu_code:
                    sql += ''' and g."MenuCode" = %(menu_code)s
                    '''
                if user_pk:
                    sql += ''' and g."User_id" = %(user_pk)s
                    '''
                sql += ''' order by g._created desc '''
            dc = {}
            dc['date_from'] = date_from
            dc['date_to'] = date_to + ' 23:59:59'
            dc['menu_code'] = menu_code
            dc['user_pk'] = user_pk

            items = DbUtil.get_page(sql, dc, *log_page(gparam))
            _name_removed_menus(items['rows'])
        elif action == 'log_count':
            date_from = gparam.get('date_from')
            date_to = gparam.get('date_to')
            menu_code = gparam.get('cboMenu')
            user_pk = gparam.get('cboUser')

            sql = ''' select mf."FolderName" as folder_name
            , g."MenuCode" as menu_code, m."MenuName" as menu_name
	        , count(*) as use_count
	        from menu_use_log g 
	        left join menu_item m on m."MenuCode" = g."MenuCode" 
	        left join menu_folder mf on mf.id = m."MenuFolder_id" 
	        left join auth_user u on u.id = g."User_id" 
	        where g._created between %(date_from)s and %(date_to)s
            '''
            if menu_code:
                sql += ''' and g."MenuCode" = %(menu_code)s
                '''
            if user_pk:
                sql += ''' and g."User_id" = %(user_pk)s
                '''
            sql += ''' group by mf."FolderName", g."MenuCode",  m."MenuName"
            order by count(*) desc, g."MenuCode" '''
            dc = {}
            dc['date_from'] = date_from
            dc['date_to'] = date_to + ' 23:59:59'
            dc['menu_code'] = menu_code
            dc['user_pk'] = user_pk

            items = DbUtil.get_rows(sql, dc)
            _name_removed_menus(items)
        elif action == 'user_list':
            if settings.DBMS == 'MSSQL':
                sql = ''' select u.id as value
                , concat(u.username,'(',u.last_name,u.first_name,')') as text
	            from auth_user u 
	            inner join user_profile up on up."User_id" = u.id 
	            inner join user_group ug on ug.id = up."UserGroup_id" 
	            where u.is_active = 1
	            and u.is_superuser = 0
	            and  ug."Code" not in ('dev')
	            order by 2
                '''
            else:
                sql = ''' select u.id as value, coalesce(nullif(up."Name", ''), u.username)||'('||u.username||')' as text
	            from auth_user u 
	            inner join user_profile up on up."User_id" = u.id 
	            inner join user_group ug on ug.id = up."UserGroup_id" 
	            where u.is_active 
	            and not u.is_superuser 
	            and  ug."Code" not in ('dev')
	            order by 2
                '''
            dc = {}
            items = DbUtil.get_rows(sql, dc)

    except Exception as ex:
        source = 'menulog : action-{}'.format(action)
        LogWriter.add_dblog('error', source , ex)
        raise ex

    return items
