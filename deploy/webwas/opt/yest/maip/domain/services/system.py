
from domain.models.system import MenuItem
from domain.services.sql import DbUtil
from domain.services.logging import LogWriter
from domain.models.user import UserGroup
from domain.models.basic import Factory
from configurations import settings
from domain.models.system import SystemOption

# 시스템 로그 구분(LogWriter.add_dblog 의 logtype)을 화면에 보일 말로
SYSLOG_TYPE_LABEL = '''case "Type" when 'error' then '오류' else "Type" end'''

class SystemService():

    def get_label_list(self, lang_code, gui_code, template_key):
        items = []
        
        sql = '''
        select
        lc."ModuleName" as gui_code
        , lc."TemplateKey" as template_key
        , lc."LabelCode" as label_code
        , lc."Description" as descr
        , lcl."DispText" as text
        from label_code lc 
        left join label_code_lang lcl on lc.id = lcl."LabelCode_id" 
        where lcl."LangCode" = %(lang_code)s 
        '''
        if gui_code:
            sql += ''' and lc."ModuleName" = %(gui_code)s 
            and lc."TemplateKey"=%(template_key)s
            '''
        sql += ''' 
        order by lc."ModuleName", lc."TemplateKey" 
        '''

        dc = {'lang_code':lang_code, 'gui_code':gui_code, 'template_key':template_key }

        items = DbUtil.get_rows(sql, dc)
        return items

    def get_labelcode_list(self, ModuleName):
        items = []
        
        if settings.DBMS =='MSSQL' :
            sql = ''' select lc.id
             , lc."ModuleName"
             , coalesce ((select "MenuName" from menu_item where "MenuCode"=lc."ModuleName" limit 1), 'Common') as menu_name
             , lc."TemplateKey"
             , lc."LabelCode"
             , lc."Description"
             , to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from label_code lc 
            
            where lc."ModuleName"=%(ModuleName)s 
            '''
        else :
            sql = ''' select lc.id
             , lc."ModuleName"
             , coalesce ((select "MenuName" from menu_item where "MenuCode"=lc."ModuleName" limit 1), 'Common') as menu_name
             , lc."TemplateKey"
             , lc."LabelCode"
             , lc."Description"
             , to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from label_code lc 
            
            where lc."ModuleName"=%(ModuleName)s 
            '''
        dc = {'ModuleName': ModuleName }
        items = DbUtil.get_rows(sql, dc)
        return items

    def get_labelcode_detail(self, id):
        items = []
        
        if settings.DBMS =='MSSQL' :
            sql = ''' select lc.id
             , lc."ModuleName"
             , coalesce ((select "MenuName" from menu_item where "MenuCode"=lc."ModuleName" limit 1), 'Common') as menu_name
             , (select "MenuFolder_id" from menu_item where "MenuCode"=lc."ModuleName" limit 1) as "MenuFolder_id"
             , lc."TemplateKey"
             , lc."LabelCode"
             , lc."Description"
             , to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from label_code lc 
            where lc.id=%(id)s 
            '''
        else :
            sql = ''' select lc.id
             , lc."ModuleName"
             , coalesce ((select "MenuName" from menu_item where "MenuCode"=lc."ModuleName" limit 1), 'Common') as menu_name
             , (select "MenuFolder_id" from menu_item where "MenuCode"=lc."ModuleName" limit 1) as "MenuFolder_id"
             , lc."TemplateKey"
             , lc."LabelCode"
             , lc."Description"
             , to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from label_code lc 
            where lc.id=%(id)s 
            '''
        dc = {'id': id }
        items = DbUtil.get_row(sql, dc)
        return items

    def get_labelcode_lang_detail(self, lang_code, gui_code, template_key, label_code):
        result = {}
        
        try:
            if settings.DBMS =='MSSQL' :
                sql ='''select lc.id as lable_code_id
                , lcl.id as label_lang_id
                , lc."ModuleName"
                , coalesce ((select "MenuName" from menu_item where "MenuCode"=lc."ModuleName" limit 1), 'Common') as menu_name
                , lc."TemplateKey"
                , lc."LabelCode"
                , lc."Description"
                , lcl."LangCode"
                , lcl."DispText"
                , to_char(lcl."_created" ,'yyyy-mm-dd hh24:mi:ss') as disp_created
                from label_code_lang lcl
                inner join label_code lc on lcl."LabelCode_id" = lc.id
                where lcl."LangCode" = %(lang_code)s
                and lc."ModuleName" = %(gui_code)s
                and lc."TemplateKey" = %(template_key)s
                and lc."LabelCode" = %(label_code)s
                '''
            else :
                sql ='''select lc.id as lable_code_id
                , lcl.id as label_lang_id
                , lc."ModuleName"
                , coalesce ((select "MenuName" from menu_item where "MenuCode"=lc."ModuleName" limit 1), 'Common') as menu_name
                , lc."TemplateKey"
                , lc."LabelCode"
                , lc."Description"
                , lcl."LangCode"
                , lcl."DispText"
                , to_char(lcl."_created" ,'yyyy-mm-dd hh24:mi:ss') as disp_created
                from label_code_lang lcl
                inner join label_code lc on lcl."LabelCode_id" = lc.id
                where lcl."LangCode" = %(lang_code)s
                and lc."ModuleName" = %(gui_code)s
                and lc."TemplateKey" = %(template_key)s
                and lc."LabelCode" = %(label_code)s
                '''
            dc = {
                'lang_code':lang_code, 
                'gui_code': gui_code,
                'template_key':template_key,
                'label_code':label_code
             }
            items = DbUtil.get_rows(sql, dc)
            if len(items)>0:
                result = items[0]
            else:
                menu_name = ''
                queryset = MenuItem.objects.filter(MenuCode=gui_code)
                if queryset.count()>0:
                    menu_name = queryset[0].MenuName
                result = {'menu_name': menu_name, 'ModuleName' : gui_code, 'LangCode': lang_code, 'TemplateKey':template_key, 'DispText': '', 'Description':'', 'lable_code_id': None, 'label_lang_id':None}
        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_labelcode_lang_detail', ex)
            raise ex

        return result


    def get_label_lang_detail(self, id):
        items = []
        
        try:
            if settings.DBMS =='MSSQL':
                sql =''' select lcl.id
                , lc."ModuleName"
                , lc."TemplateKey"
                , lcl."LangCode" 
                , lc."LabelCode" 
                , lcl."DispText" 
                , lcl."LabelCode_id"
                , to_char(lcl."_created" ,'yyyy-mm-dd hh24:mi:ss') as created
                from label_code_lang lcl 
                inner join label_code lc on lcl."LabelCode_id" = lc.id
                where lcl.id = %(id)s
                '''
            else :
                sql =''' select lcl.id
                , lc."ModuleName"
                , lc."TemplateKey"
                , lcl."LangCode" 
                , lc."LabelCode" 
                , lcl."DispText" 
                , lcl."LabelCode_id"
                , to_char(lcl."_created" ,'yyyy-mm-dd hh24:mi:ss') as created
                from label_code_lang lcl 
                inner join label_code lc on lcl."LabelCode_id" = lc.id
                where lcl.id = %(id)s
                '''
            dc = {'id':id}
            items = DbUtil.get_row(sql, dc)

        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_label_lang_list', ex)
            raise ex

        return items


    def get_label_lang_list(self, labelcode_id, lang_code):
        items = []
        
        try:
            if settings.DBMS =='MSSQL' :
                sql =''' select lcl.id
                , lc."ModuleName"
                , lc."TemplateKey"
                , lcl."LangCode" 
                , lc."LabelCode" 
                , lcl."DispText" 
                , lcl."LabelCode_id"
                , to_char(lcl."_created" ,'yyyy-mm-dd hh24:mi:ss') as created
                , fn_code_name('lang_code', lcl."LangCode") as lang_code_name
                from label_code_lang lcl 
                inner join label_code lc on lcl."LabelCode_id" = lc.id
                where lcl."LabelCode_id" = %(labelcode_id)s
                '''
            else :
                sql =''' select lcl.id
                , lc."ModuleName"
                , lc."TemplateKey"
                , lcl."LangCode" 
                , lc."LabelCode" 
                , lcl."DispText" 
                , lcl."LabelCode_id"
                , to_char(lcl."_created" ,'yyyy-mm-dd hh24:mi:ss') as created
                , fn_code_name('lang_code', lcl."LangCode") as lang_code_name
                from label_code_lang lcl 
                inner join label_code lc on lcl."LabelCode_id" = lc.id
                where lcl."LabelCode_id" = %(labelcode_id)s
                '''
            if lang_code:
                sql+=''' 
                and "LangCode" = %(lang_code)s
                '''
            dc = {'labelcode_id':labelcode_id, 'lang_code':lang_code}
            items = DbUtil.get_rows(sql, dc)

        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_label_lang_list', ex)
            raise ex

        return items

    def get_web_menu_list(self, user, lang_code):
        #message = 'get_web_menu_list group_id :{}, user_id : {}'.format(group_id, user_id)
        #print(message)
        try:
            items = []
            userGroup = user.userprofile.UserGroup
            if userGroup:
                user_group_code = userGroup.Code
                user_group_id = userGroup.id
            else:
                user_group_code = ''
                user_group_id = 0

            if settings.DBMS == 'MSSQL':
                sql = ''' with tree(id, menu_code, pid, name,depth, path, cycle, folder_order, _order, css, data_div, folder_id) as (  
                      select a.id
                          ,cast(a."FolderName" as nvarchar) as menu_code 
                          ,a."Parent_id" as pid
                          , cast(a."FolderName" as nvarchar) as name 
                          ,1 as depth
                          --,array[a.id] as path
					      , cast(dbo.lpad(a.id, 5, '0') as nvarchar) as path
                          ,0 as cycle
                          ,_order as folder_order
                          ,_order
                          ,a."IconCSS" as css
                          ,cast('folder' as nvarchar) as data_div
                          , a.id as folder_id
                          from menu_folder a 
                          where a."Parent_id" is null
                      union all 
                      select  null as id
                          , cast(mi."MenuCode" as nvarchar) as menu_code
                          ,mi."MenuFolder_id" as pid
                          , cast(coalesce(lcl.disptext, mi."MenuName") as nvarchar) as name 
                          ,tree.depth+1
                          --,array_append(tree.path, mi."MenuFolder_id") as path
					      , cast( tree.path + '-' + dbo.lpad( mi."MenuFolder_id", 5, '0') as nvarchar) as path
                          --,mi."MenuFolder_id" = any(tree.path) as cycle
					      , case when charindex(dbo.lpad( mi."MenuFolder_id", 5, '0'), tree.path) > 0 then 1 else 0 end as cycle
                          ,tree.folder_order
                          ,mi._order
                          ,null as css
                          ,cast('menu' as nvarchar) as data_div
                          ,mi."MenuFolder_id" as folder_id
                      from menu_item mi 
                      left join label_code lc on mi."MenuName" = lc."LabelCode" and lc."ModuleName" = 'common' and lc."TemplateKey" = 'menu'
                      left join label_code_lang lcl on lc.id = lcl."LabelCode_id" and lcl."LangCode" = %(lang_code)s
                      inner join tree on mi."MenuFolder_id" = tree.id 
                      where exists (
                        select 1 
                        where %(group_code)s = 'dev' 
                        union all
                        select 1 
                        where mi."MenuCode" in ('wm_user_group_menu', 'wm_user_group', 'wm_user')
                        and (%(super_user)s = 1 or %(group_code)s = 'admin' )
                        union all
                        select 1 
                        from user_group_menu gm 
                        where gm."MenuCode" = mi."MenuCode" 
                        and gm."UserGroup_id" = %(group_id)s 
                        and gm."AuthCode" like '%%R%%'
                        and ( %(group_code)s not in ('dev') or %(super_user)s = 0  )
					    )
                      and cycle = 0
                  ), M as 
                  (
                  select tree.id
                  ,tree.menu_code
                  ,tree.pid
                  ,tree.name
                  ,tree.depth
                  ,tree.folder_order
                  ,tree._order
                  ,coalesce(tree.css,'') as css
                  ,case when bk."MenuCode" is not null then 1 else 0 end as isbookmark
                  , data_div
                  , count(*) over (partition by tree.folder_id) as sub_count
                  , tree.path
                  from tree 
                  left join bookmark bk on bk."MenuCode" = tree.menu_code 
                  and bk."User_id" = %(user_id)s
                  where 1 = 1
                  )
                  select id, menu_code, pid, name, depth, folder_order, _order, css, isbookmark 
                  from M
                  where sub_count > 1
                  order by folder_order, path,_order
                '''
                # 3depth 추가
                sql = ''' with tree as (  
	                select a.folder_id as id
		                , cast(a.folder_name as nvarchar(50)) as menu_code 
		                , a.p_folder_id as pid
		                , cast(a.folder_name as nvarchar) as name 
		                , a._level as depth
		                , a.path
		                , a.folder_order
		                , 0 as _order
		                , a.icon as css
		                , cast('folder' as nvarchar) as data_div
		                , a.folder_id
	                from v_menu_folder a 
	                union all 
	                 select null as id
		                , cast(mi."MenuCode" as nvarchar(50)) as menu_code
		                , mi."MenuFolder_id" as pid
		                , cast(coalesce(lcl.disptext, mi."MenuName") as nvarchar) as name
		                , tree.depth + 1
		                , cast( tree.path + '-9' + dbo.lpad( mi._order, 3, '0') as nvarchar) as path
		                , tree.folder_order
		                , mi._order
		                , null as css
		                , cast('menu' as nvarchar) as data_div
		                , mi."MenuFolder_id" as folder_id
	                from menu_item mi 
                    left join label_code lc on mi."MenuName" = lc."LabelCode" and lc."ModuleName" = 'common' and lc."TemplateKey" = 'menu'
                    left join label_code_lang lcl on lc.id = lcl."LabelCode_id" and lcl."LangCode" = %(lang_code)s
	                inner join tree on mi."MenuFolder_id" = tree.id 
	                where exists (
		                select 1 
		                where %(group_code)s = 'dev' 
		                union all
		                 select 1 
			                where mi."MenuCode" in ('wm_user_group_menu', 'wm_user_group', 'wm_user')
			                and (%(super_user)s = 1 or %(group_code)s = 'admin' )
		                union all
		                 select 1 
			                from user_group_menu gm 
			                where gm."MenuCode" = mi."MenuCode" 
			                and gm."UserGroup_id" = %(group_id)s 
			                and gm."AuthCode" like '%%R%%'
			                and ( %(group_code)s not in ('dev') or %(super_user)s = 0  )
	                )
                ), M as 
                (
	                select tree.id
	                , tree.menu_code
	                , tree.pid
	                , tree.name
	                , tree.depth
	                , tree.folder_order
	                , tree._order
	                , coalesce(tree.css,'') as css
	                , case when bk."MenuCode" is not null then 1 else 0 end as isbookmark
	                , data_div
	                , count(*) over (partition by tree.folder_id) as sub_count
	                , tree.path
	                from tree 
	                left join bookmark bk on bk."MenuCode" = tree.menu_code 
	                and bk."User_id" = %(user_id)s
	                where 1 = 1
                )
                select M.id, M.menu_code, M.pid
                , M.name
                , M.depth, M.folder_order
                , M._order, M.css, M.isbookmark 
                from M
                where sub_count > 1
                order by path, folder_order, _order
                '''
                dc ={}
                dc['super_user'] = 1 if user.is_superuser else 0
                dc['group_code'] = user_group_code
                dc['group_id'] = user_group_id
                dc['user_id'] = user.id
                dc['lang_code'] = lang_code
            else:
                sql=''' 
                WITH RECURSIVE tree AS (
                SELECT a.folder_id AS id,
                       CAST(a.folder_name AS VARCHAR(50)) AS menu_code,
                       a.p_folder_id AS pid,
                       CAST(a.folder_name AS VARCHAR(255)) AS name,
                       a._level AS depth,
                       CAST(a.path AS VARCHAR(500)) AS path,
                       a.folder_order,
                       0 AS _order,
                       CAST(a.icon AS VARCHAR(50)) AS css,
                       CAST('folder' AS VARCHAR(50)) AS data_div,
                       a.folder_id
                FROM v_menu_folder a
                UNION ALL
                SELECT NULL AS id,
                       CAST(mi."MenuCode" AS VARCHAR(50)) AS menu_code,
                       mi."MenuFolder_id" AS pid,
                       CAST(COALESCE(lcl."DispText", mi."MenuName") AS VARCHAR(255)) AS name,
                       tree.depth + 1,
                       CAST(tree.path || '-9' || LPAD(mi._order::TEXT, 3, '0') AS VARCHAR(500)) AS path,
                       tree.folder_order,
                       mi._order,
                       CAST(NULL AS VARCHAR(50)) AS css,
                       CAST('menu' AS VARCHAR(50)) AS data_div,
                       mi."MenuFolder_id" AS folder_id
                FROM menu_item mi
                LEFT JOIN label_code lc ON mi."MenuName" = lc."LabelCode" 
                                        AND lc."ModuleName" = 'common' 
                                        AND lc."TemplateKey" = 'menu'
                LEFT JOIN label_code_lang lcl ON lc.id = lcl."LabelCode_id" 
                                              AND lcl."LangCode" = %(lang_code)s
                INNER JOIN tree ON mi."MenuFolder_id" = tree.id
                WHERE EXISTS (
                    SELECT 1
                    where %(group_code)s = 'dev' 
                    UNION ALL
                    SELECT 1
                    where mi."MenuCode" in ('wm_user_group_menu', 'wm_user_group', 'wm_user')
			                and (%(super_user)s = true or %(group_code)s = 'admin' )
                    UNION ALL
                    SELECT 1
                    FROM user_group_menu gm
                    WHERE gm."MenuCode" = mi."MenuCode"
                      and gm."UserGroup_id" = %(group_id)s 
                      AND gm."AuthCode" LIKE '%%R%%'
                      and ( %(group_code)s not in ('dev') or %(super_user)s = false  )
                )
            ), M AS (
                SELECT tree.id,
                       tree.menu_code,
                       tree.pid,
                       tree.name,
                       tree.depth,
                       tree.folder_order,
                       tree._order,
                       COALESCE(tree.css, '') AS css,
                       CASE WHEN bk."MenuCode" IS NOT NULL THEN 1 ELSE 0 END AS isbookmark,
                       data_div,
                       COUNT(*) OVER (PARTITION BY tree.folder_id) AS sub_count,
                       tree.path
                FROM tree
                LEFT JOIN bookmark bk ON bk."MenuCode" = tree.menu_code
                                      AND bk."User_id" = %(user_id)s
                WHERE 1 = 1
            )
            SELECT M.id, M.menu_code, M.pid,
                   M.name,
                   M.depth, M.folder_order,
                   M._order, M.css, M.isbookmark
            FROM M
            WHERE sub_count > 1
            ORDER BY folder_order, path, _order;
                '''
                dc ={}
                dc['super_user'] = user.is_superuser
                dc['group_code'] = user_group_code
                dc['group_id'] = user_group_id
                dc['lang_code'] = lang_code
                dc['user_id'] = user.id
           
            items = DbUtil.get_rows(sql, dc)

        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_web_menu_list', ex)
            raise ex

        return items


    def get_menu_list(self, folder_id):

        try:
            items = []
            dc ={'folder_id':folder_id}
            if settings.DBMS == 'MSSQL':
                sql='''
                    with tree as (  
                      select 
                        a.id
                      , a."Parent_id" as pid
                      , convert(nvarchar(255),'') as menu_code  -- 데이터 유형을 명확히 설정
                      , convert(nvarchar(255), a."FolderName") as folder_name
                      , convert(nvarchar(255),'') as menu_name
                      , 1 as depth
                      , convert(nvarchar(50),'folder') as data_div
                      , a.id as folder_id
                      , 1 as is_folder
                      , convert(varchar(50), concat(a.id,'0')) as ord
                      from menu_folder a   
                      where a."Parent_id" is null                 
                '''
                if folder_id:
                    sql+='''
                        and a.id = %(folder_id)s
                    '''
                sql+='''
                union all 
                select 
                null as id
              , mi."MenuFolder_id" as pid 
              , convert(nvarchar(255), mi."MenuCode") as menu_code  -- 일치하는 데이터 유형으로 변환
              , convert(nvarchar(255),'') as folder_name
              , convert(nvarchar(255), mi."MenuName") as menu_name
              , tree.depth + 1 as depth
              , convert(nvarchar(50), 'menu') as data_div
              , mi."MenuFolder_id" as folder_id
              , 0 as is_folder                
              , convert(varchar(50), concat(mi."MenuFolder_id",'c')) as ord
              from menu_item mi 
              inner join tree on mi."MenuFolder_id" = tree.id  
            )
            select 
              tree.pid
            , tree.id
            , tree.menu_code
            , tree.folder_name
            , tree.menu_name
            , tree.depth
            , tree.ord
            , tree.is_folder
            from tree
            order by tree.ord
                '''
            else:
                sql='''
                    with recursive tree as (  
                      select 
                        a.id
                      , a."Parent_id" as pid
                      , cast('' as varchar(255)) as menu_code
                      , cast(a."FolderName" as varchar(255)) as folder_name
                      , cast('' as varchar(255)) as menu_name
                      , 1 as depth
                      , cast('folder' as varchar(50)) as data_div
                      , a.id as folder_id
                      , 1 as is_folder
                      , cast(a.id::text || '0' as varchar(50)) as ord
                      from menu_folder a   
                      where a."Parent_id" is null                 
                '''
                if folder_id:
                    sql+='''
                        and a.id = %(folder_id)s
                    '''
                sql+='''
                union all 
                select 
                null as id
              , mi."MenuFolder_id" as pid 
              , cast(mi."MenuCode" as varchar(255)) as menu_code
              , cast('' as varchar(255)) as folder_name
              , cast(mi."MenuName" as varchar(255)) as menu_name
              , tree.depth + 1 as depth
              , cast('menu' as varchar(50)) as data_div
              , mi."MenuFolder_id" as folder_id
              , 0 as is_folder                
              , cast(mi."MenuFolder_id"::text || 'c' as varchar(50)) as ord
              from menu_item mi 
              inner join tree on mi."MenuFolder_id" = tree.id  
            )
            select 
              tree.pid
            , tree.id
            , tree.menu_code
            , tree.folder_name
            , tree.menu_name
            , tree.depth
            , tree.ord
            , tree.is_folder
            from tree
            order by tree.ord
                '''

            items = DbUtil.get_rows(sql, dc)
        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_menu_list', ex)
            raise ex

        return items



    def get_systemlog_list(self, start, end, type, source, page=1, size=None):
        if settings.DBMS == 'POSTGRESQL':
            sql = ''' select id
            , ''' + SYSLOG_TYPE_LABEL + ''' as type
            , "Source" as source
            ,"Message" as message
            , to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from sys_log sl
            where _created between %(start)s and %(end)s
            '''
            if type:
                # 화면에는 '오류' 로 보인다 — 보이는 말로도, 저장된 값으로도 찾는다
                sql += '''and (''' + SYSLOG_TYPE_LABEL + ''' ilike concat('%%',%(type)s,'%%')
                    or "Type" ilike concat('%%',%(type)s,'%%'))
                '''

            if source:
                sql += '''and "Source" ilike concat('%%', %(source)s, '%%')
                '''
            sql += ''' order by _created desc
                ''' 
        elif settings.DBMS == 'MSSQL':
            sql = ''' select id
            , "Type" as type
            , "Source" as source
            ,"Message" as message
            , to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from sys_log sl
            where _created between %(start)s and %(end)s
            '''
            if type:
                sql += '''and "Type" ilike concat('%%', %(type)s,'%%')
                '''

            if source:
                sql += '''and "Source" ilike concat('%%', %(source)s, '%%')
                '''

            sql += ''' order by _created desc
            '''
        items = []
        try:
            dc = {}
            dc['start'] = start
            dc['end'] = end
            dc['type'] = type
            dc['source'] = source
            items = DbUtil.get_page(sql, dc, page, size)
        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_systemlog_list', ex)
            raise ex

        return items


    def get_systemlog_detail(self, log_id):
        if settings.DBMS == 'POSTGRESQL':
            sql = ''' select id, ''' + SYSLOG_TYPE_LABEL + ''' as type, "Source" as source,"Message" as message
            , to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from sys_log sl
            where id = %(log_id)s
            '''
        elif settings.DBMS == 'MSSQL':
            sql = ''' select id, "Type" as type, "Source" as source,"Message" as message
            , to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from sys_log sl
            where id = %(log_id)s
            '''
        log = {}
        try:
            dc = {'log_id':log_id}
            items = DbUtil.get_row(sql, dc)
        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_systemlog_detail', ex)
            raise ex

        return items

    def test_system_log(self):
        
        #sql = '''
        #SET NOCOUNT ON;
        #insert into sys_log([type],[Source], Message, _created) values('test', '/api/system/system_log?action=test', 'return id test', getdate());
        #SELECT SCOPE_IDENTITY();
        #'''
        #connection = DbUtil.get_connection()
        #cursor = connection.cursor()
        #cursor.execute(sql)
        #id = cursor.fetchone()[0]
        #cursor.commit()
        #cursor.close()
        #print(id)
        #return id

        sql = '''
        insert into mat_inout (
            "Material_id", "StoreHouse_id" , "InOut" , "OutputType" , "InoutDate" , "InoutTime" , "OutputQty" 
	        , "State" , "SourceDataPk" , "SourceTableName"  , "_created" , "_status" 
        )
        select m.id, mc."StoreHouse_id", 'out', 'consumed_out', jr."ProductionDate", %(out_time)s , mc."ConsumedQty"
        , 'confirmed', mc.id, 'mat_consu', now(), 'a'
        from mat_consu mc
        inner join job_res jr on jr.id = mc."JobResponse_id"
        inner join material m on m.id = mc."Material_id"
        where jr.id = %(jr_pk)s
        '''
        #DbUtil.execute(sql, dic_param)
        #ret = sqlrun.execute(sql, dic_param)
        dic_param = {'out_time':'01:30', 'jr_pk':'16'}
        connection = DbUtil.get_connection()
        cursor = connection.cursor()
        DbUtil.execute_param(cursor, sql, dic_param)
        cursor.commit()
   


    def get_loginlog_list(self, start, end, keyword, page=1, size=None):

        if settings.DBMS == 'POSTGRESQL':
            # 실패 기록은 User 가 비어 있고(시도한 아이디만 Username 에 남는다), 삭제된 사용자의 기록은
            # 연결이 끊겨 있다. 아이디는 Username 으로 채우고, 아직 있는 계정이면 이름도 붙인다.
            sql = ''' select ll.id
            , case ll."Type" when 'login' then '로그인' when 'logout' then '로그아웃'
                when 'fail' then '실패' else ll."Type" end as type
            , ll."IPAddress" as addr
            , coalesce(au.username, ll."Username") as login_id
            , up."Name" as name
            , ll."FailReason" as fail_reason
            , to_char(ll."_created" ,'yyyy-mm-dd hh24:mi:ss') as created 
            from login_log ll 
            left join auth_user au ON au.id = ll."User_id"
                or (ll."User_id" is null and au.username = ll."Username")
            left join user_profile up on up."User_id" = au.id
            where ll._created between %(start)s and %(end)s
            '''

            if keyword:
                sql += ''' and (coalesce(au.username, ll."Username") ilike concat('%%', %(keyword)s, '%%')
                    or up."Name" ilike concat('%%', %(keyword)s, '%%')
                )
                '''

            sql += ''' order by ll._created desc
            '''
        elif settings.DBMS == 'MSSQL':
            sql = ''' select ll.id
            , ll."Type" as type
            , ll."IPAddress" as addr
            , au.username as login_id
            , up."Name" as name
            , to_char(ll."_created" ,'yyyy-mm-dd hh24:mi:ss') as created 
            from login_log ll 
            left join auth_user au ON au.id = ll."User_id" 
            left join user_profile up on up."User_id" = ll."User_id" 
            where ll._created between %(start)s and %(end)s
            '''

            if keyword:
                sql += ''' and (au.username ilike concat('%%', %(keyword)s, '%%')
                    or up."Name" ilike concat('%%', %(keyword)s, '%%')
                )
                '''
            sql += ''' order by ll._created desc
            '''
        items = []
        try:
            dc = {}
            dc['start'] = start
            dc['end'] = end
            dc['keyword'] = keyword
            items = DbUtil.get_page(sql, dc, page, size)
        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_loginlog_list', ex)
            raise ex

        return items

    def get_usergroup_list(self, superuser=False):
        if settings.DBMS == 'POSTGRESQL':
            sql = ''' select id, "Code" as code 
            , "Name" as name 
            , "Description" as description 
            , "Disabled" as disabled 
            , to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from user_group ug 
            where 1 = 1
            '''
            if not superuser:
                sql += ''' and "Code" <> 'dev' 
                '''
            sql += ''' order by "Name"
            '''
        elif settings.DBMS == 'MSSQL':
            sql = ''' select id, "Code" as code 
            , "Name" as name 
            , "Description" as description 
            , "Disabled" as disabled 
            , to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from user_group ug 
            where 1 = 1
            '''
            if not superuser:
                sql += ''' and "Code" <> 'dev' 
                '''
            sql += ''' order by "Name"
            '''
        items = []
        try:
            items = DbUtil.get_rows(sql)
        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_usergroup_list', ex)
            raise ex

        return items

    def get_usergroup_detail(self, group_id):

        if settings.DBMS == 'POSTGRESQL':
            sql = ''' select id, "Code" as code 
            , "Name" as name 
            ,"Description" as description 
            ,"Disabled" as disabled 
            ,to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from user_group 
            where id = %(group_id)s
            '''
        elif settings.DBMS == 'MSSQL':
            sql = ''' select id, "Code" as code 
            , "Name" as name 
            ,"Description" as description 
            ,"Disabled" as disabled 
            ,to_char("_created" ,'yyyy-mm-dd hh24:mi:ss') as created
            from user_group 
            where id = %(group_id)s
            '''
        group = {}
        try:
            dc={'group_id':group_id}
            items = DbUtil.get_row(sql, dc)

        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_usergroup_detail', ex)
            raise ex

        return items

    def get_usergroupmenu_list(self, group_id, folder_id=None):

        items = []
        if settings.DBMS == 'POSTGRESQL':
            sql = ''' with recursive tree as (  
                      select a.id
                          , a."Parent_id" as pid
                          , '' as menu_code
                          , a."FolderName" as name
                          , 1 as depth
                          , array[a.id] as path
                          , false as cycle
                          --, concat(a."Parent_id", a.id, a."_order") as ord
                          , a."_order" as ord
                          ,'folder' as data_div
                           , a.id as folder_id
                          , true as is_folder
                          from menu_folder a   
                          where a."Parent_id" is null
                      union all 
                      select null as id
                          , mi."MenuFolder_id" as pid              
                          , mi."MenuCode"::text as menu_code
                          , mi."MenuName"  as name          
                          , tree.depth+1
                          , array_append(tree.path, mi."MenuFolder_id") as path
                          , mi."MenuFolder_id" = any(tree.path) as cycle
                          --, concat(tree.ord, tree.pid, mi."_order") as ord
                          , mi._order as ord
                          ,'menu' as data_div
                          , mi."MenuFolder_id" as folder_id
                          , false as is_folder
                      from menu_item mi 
                      inner join tree on mi."MenuFolder_id" = tree.id  
                      where mi."MenuCode" not in ('wm_user_group', 'wm_user', 'wm_user_group_menu')
                  )
                  select tree.pid
                      , tree.id
                      , tree.menu_code
                      , tree.name
                      , tree.depth
                      , tree.ord
                      , ugm."UserGroup_id"
                      , ugm."AuthCode"
                      , case when tree.is_folder then null else coalesce(ugm."AuthCode" like '%%R%%', false) end  as r
                      , case when tree.is_folder then null else coalesce(ugm."AuthCode" like '%%W%%', false) end  as w
                      , case when tree.is_folder then null else coalesce(ugm."AuthCode" like '%%X%%', false) end  as x
                      , tree.is_folder
                  from tree 
                  left join user_group_menu ugm on ugm."MenuCode" = tree.menu_code 
                  and ugm."UserGroup_id" = %(group_id)s
                  order by path, tree.ord
                  '''        
        elif settings.DBMS == 'MSSQL':
            sql = ''' with tree as (  
                      select a.id
                          , a."Parent_id" as pid
                          , cast('' as nvarchar) as menu_code
                          , a."FolderName" as name
                          , 1 as depth
                          --, array[a.id] as path
					      , cast(dbo.lpad(a.id, 5, '0') as nvarchar) as path
                          , 0 as cycle
                          --, concat(a."Parent_id", a.id, a."_order") as ord
                          , a."_order" as ord2
                          ,cast('folder' as nvarchar) as data_div
                           , a.id as folder_id
                          , 1 as is_folder
                          from menu_folder a   
                          where a."Parent_id" is null
                      union all 
                      select null as id
                          , mi."MenuFolder_id" as pid              
                          , mi."MenuCode" as menu_code
                          , mi."MenuName"  as name          
                          , tree.depth+1
                          --, array_append(tree.path, mi."MenuFolder_id") as path
					      , cast( tree.path + '-' + dbo.lpad( mi."MenuFolder_id", 5, '0') as nvarchar) as path
                          --, mi."MenuFolder_id" = any(tree.path) as cycle
					      , case when charindex(dbo.lpad( mi."MenuFolder_id", 5, '0'), tree.path) > 0 then 1 else 0 end as cycle
                          --, concat(tree.ord, tree.pid, mi."_order") as ord
                          , mi._order as ord2
                          ,cast('menu' as nvarchar) as data_div
                          , mi."MenuFolder_id" as folder_id
                          , 0 as is_folder
                      from menu_item mi 
                      inner join tree on mi."MenuFolder_id" = tree.id  
                      where mi."MenuCode" not in ('wm_user_group', 'wm_user', 'wm_user_group_menu')
                  )
                  select tree.pid
                      ,tree.id
                      ,tree.menu_code
                      ,tree.name
                      ,tree.depth
                      ,tree.ord2
                      ,ugm."UserGroup_id"
                      ,ugm."AuthCode"
                      ,case when tree.is_folder = 0 and ugm."AuthCode" like '%%R%%' then 1 else 0 end  as r
				      ,case when tree.is_folder = 0 and ugm."AuthCode" like '%%W%%' then 1 else 0 end  as w
				      ,case when tree.is_folder = 0 and ugm."AuthCode" like '%%X%%' then 1 else 0 end  as x
                      , tree.is_folder
                  from tree 
                  left join user_group_menu ugm on ugm."MenuCode" = tree.menu_code 
                  and ugm."UserGroup_id" = %(group_id)s
                  order by path, tree.ord2
                  '''
            # 3depth 추가
            sql = ''' with tree as (  
	            select a.id
	                , a."Parent_id" as pid
	                , cast('' as nvarchar(50)) as menu_code
	                , a."FolderName" as name
	                , 1 as depth
		            , cast(dbo.lpad(a._order, 5, '0') as nvarchar) as path
	                , 0 as cycle
	                , a."_order" as ord2
	                ,cast('folder' as nvarchar) as data_div
	                , a.id as folder_id
	                , 1 as is_folder
	            from menu_folder a   
	            where 1=1
	            union all 
                select null as id
                    , mi."MenuFolder_id" as pid              
                    , cast(mi."MenuCode" as nvarchar(50)) as menu_code
                    , mi."MenuName"  as name          
                    , tree.depth+1
	                , cast( tree.path + '-' + dbo.lpad( mi._order, 5, '0') as nvarchar) as path
	                , case when charindex(dbo.lpad( mi."MenuFolder_id", 5, '0'), tree.path) > 0 then 1 else 0 end as cycle
                    , mi._order as ord2
                    ,cast('menu' as nvarchar) as data_div
                    , mi."MenuFolder_id" as folder_id
                    , 0 as is_folder
                from menu_item mi 
                inner join tree on mi."MenuFolder_id" = tree.id  
                where mi."MenuCode" not in ('wm_user_group', 'wm_user', 'wm_user_group_menu')
            )
            select tree.pid
	            , tree.id
	            , tree.menu_code
	            , tree.name
	            , tree.depth
	            , tree.ord2
	            , ugm."UserGroup_id"
	            , ugm."AuthCode"
	            , case when tree.is_folder = 0 and ugm."AuthCode" like '%%R%%' then 1 else 0 end  as r
	            , case when tree.is_folder = 0 and ugm."AuthCode" like '%%W%%' then 1 else 0 end  as w
	            , case when tree.is_folder = 0 and ugm."AuthCode" like '%%X%%' then 1 else 0 end  as x
	            , tree.is_folder
	            , ugm.id as ugm_id
            from tree 
            left join user_group_menu ugm on ugm."MenuCode" = tree.menu_code 
            and ugm."UserGroup_id" = %(group_id)s
            order by path, tree.ord2
            '''
        
        folder_filter = folder_id and str(folder_id).strip() not in ('', 'all')
        if folder_filter:
            if settings.DBMS == 'POSTGRESQL':
                sql = sql.replace('where a."Parent_id" is null', 'where a.id = %(folder_id)s')
            elif settings.DBMS == 'MSSQL':
                sql = sql.replace('where 1=1', 'where a.id = %(folder_id)s')

        items = []
        try:
            dc = {'group_id': group_id}
            if folder_filter:
                dc['folder_id'] = int(folder_id)
            items = DbUtil.get_rows(sql, dc)
        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_usergroupmenu_list', ex)
            raise ex

        return items


    def get_bookmark_list(self, user_id):
        
        sql = '''
        select mi."MenuName" as name 
        , mi."MenuCode" as code 
        , mi."Url" as url
        --, false as ismanual
        , 0 as ismanual
        from bookmark bm 
        inner join menu_item mi on bm."MenuCode" = mi."MenuCode" 
        where bm."User_id" = %(user_id)s
        order by 1
        '''
        items = []
        try:
            dc = {'user_id':user_id}
            items = DbUtil.get_rows(sql, dc)
        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_bookmakr_list', ex)
            raise ex

        return items

    #def get_code_list(self, txtCode):

    #    sql = '''
    #        select 
    #        "Parent_id" as parent_id, id,"Code" as code,
    #        "Value" as name,"Description" as description
    #        from user_code
    #        where 
    #        "Value" ilike '%%'''+txtCode+'''%%'
    #        order by "Value"
    #    '''
    #    items = []
    #    try:
    #        items = DbUtil.get_rows(sql)
    #    except Exception as ex:
    #        LogWriter.add_dblog('error', 'SystemService.get_cod_list', ex)
    #        raise ex

    #    return items

    #def get_code_detail(self, id):
    #    dic_param = {'id':id}
    #    sql = '''
    #        select 
    #        "Parent_id" as parent_id, id,"Code" as code,
    #        "Value" as name,"Description" as description
    #        from user_code
    #        where  id =%(id)s
    #    '''
    #    code = {}
    #    try:
    #        items = DbUtil.get_rows(sql, dic_param)
    #        if len(items)==1:
    #            code = items[0]
    #    except Exception as ex:
    #        LogWriter.add_dblog('error', 'SystemService.get_code_detail', ex)
    #        raise ex

    #    return code

    def get_storyboard_item_list(self):
        items = []
        if settings.DBMS == 'POSTGRESQL':
            sql = ''' select si.id
            , case when si."BoardType" ='menu' 
                then concat(mi."MenuName",'(', mf."FolderName",')')
               else df."FormName" end as name
              , si."BoardType"
              , fn_code_name('story_board_type', si."BoardType" ) as "BoardTypeName"
              , si."Duration"
              , si."Url"
              , up."Name" as writer
              , to_char(si."_created" ,'yyyy-mm-dd hh24:mi:ss') as created
              , si."ParameterData"
            from storyboard_item si 
            left join menu_item mi on mi."MenuCode" = si."MenuCode" 
            left join menu_folder mf on mf.id = mi."MenuFolder_id" 
            left join doc_form df on df.id = NULLIF(si."ParameterData", '')::int
            left join user_profile up on up."User_id" = si."_creater_id"
            order by id
            '''
        elif settings.DBMS == 'MSSQL':
            sql = ''' select si.id
            , case when si."BoardType" ='menu' 
                then concat(mi."MenuName",'(', mf."FolderName",')')
               else df."FormName" end as name
              , si."BoardType"
              , fn_code_name('story_board_type', si."BoardType" ) as "BoardTypeName"
              , si."Duration"
              , si."Url"
              , up."Name" as writer
              , to_char(si."_created" ,'yyyy-mm-dd hh24:mi:ss') as created
              , si."ParameterData"
            from storyboard_item si 
            left join menu_item mi on mi."MenuCode" = si."MenuCode" 
            left join menu_folder mf on mf.id = mi."MenuFolder_id" 
            left join doc_form df on df.id = NULLIF(si."ParameterData", '')::integer
            left join user_profile up on up."User_id" = si."_creater_id"
            order by id
            '''
        try:
            items = DbUtil.get_rows(sql)
        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_storyboard_item_list', ex)
            raise ex

        return items


    def get_system_code_list(self, code_type, keyword):

        
        sql = ''' 
        select
          id 
          ,"CodeType"  , "Code" , "Value" , "Description", "_ordering" 
        from sys_code sc 
        where 1=1
        '''

        if code_type:
            sql += ''' and "CodeType" = %(code_type)s '''

        if keyword:
            sql += ''' and "Value" = %(keyword)s '''

        sql+=''' order by "CodeType" , "_ordering" , "Value" 
            '''

        try:
            dc = {'code_type':code_type, 'keyword':keyword}
            items = DbUtil.get_rows(sql, dc)
        except Exception as ex:
            LogWriter.add_dblog('error', 'SystemService.get_system_code_list', ex)
            raise ex

        return items

    @classmethod
    def get_system_title(cls):
        q = SystemOption.objects.filter(Code='LOGO_TITLE').values('Value')
        option = q.first()
        if option:
            system_title = option.get('Value')
        else:
            system_title = 'Yullin MES21'

        return system_title
