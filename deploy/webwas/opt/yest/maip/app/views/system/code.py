from configurations import settings
from domain.services.common import CommonUtil
from domain.services.sql import DbUtil
from domain.services.logging import LogWriter

from domain.models.system import UserCode

def code(context):
    '''
    작성명 : 코드정보
    작성자 : 이인호
    작성일 : 2020-12-29
    비고 :

    -수정사항-
    수정일             작업자     수정내용
    2020-01-01     홍길동      테스트수정내용
    '''
    items = []
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action', 'read')
        
    try:
        if action=='read':
            parentId =gparam.get('parentId', '')
            txtCode =gparam.get('txtCode', '')
            if settings.DBMS == 'MSSQL' : 
                sql = '''  select id
                , "Parent_id" as parent_id, "Code" as code
                , "Value" as name,"Description" as description
                from user_code
                where 1=1  
                '''
                if parentId:
                    sql += ''' and "Parent_id" = %(parentId)s
                    '''
                if txtCode :
                    sql += ''' and "Value" like concat('%%',%(name)s,'%%')
                    '''
            else :
                sql = '''  select id
                , "Parent_id" as parent_id, "Code" as code
                , "Value" as name,"Description" as description
                from user_code
                where "Value" ilike concat('%%',%(name)s,'%%')
                '''
                if parentId:
                    sql += ''' and "Parent_id" = %(parentId)s
                    '''
            sql += '''
            order by "Value"
            '''
            dc = {}
            dc['parentId'] = parentId
            dc['name'] = txtCode
            items = DbUtil.get_rows(sql, dc)
        elif action=='detail':
            id = gparam.get('id')
            
            sql = ''' select C.id
            , C."Parent_id" as parent_id
            , P."Value" as parent_name
            , C."Code" as code
            , C."Value" as name, C."Description" as description
            from user_code C
            left join user_code P on P.id = C."Parent_id"
            where C.id = %(id)s
            '''
            dc = {}
            dc['id'] = id
            items = DbUtil.get_row(sql, dc)
        elif action=='save':
            parent_id = posparam.get('parent_id')
            id = posparam.get('id')
            code = posparam.get('code')
            name = posparam.get('name')
            description = posparam.get('description')

            check = UserCode.objects.filter(Code=code)
            

            if id:
                check = check.exclude(id = id)
            if check :
                return {'success' : False , 'message': '이미 존재하는 코드입니다.' }
            if id:
                user_code = UserCode.objects.get(id=id)
            else:
                user_code = UserCode()
            user_code.Code = code
            user_code.Value = name
            user_code.Parent_id = CommonUtil.try_int( parent_id )
            user_code.Description = description
            user_code.save()
            items = { 'success': True ,'id' : user_code.id }

        elif action=='delete':
            id = posparam.get('id')
            user_code = UserCode.objects.get(id=id)
            user_code.delete()
            items = { 'success': True}
    except Exception as ex:
        source = 'code : action-{}'.format(action)
        LogWriter.add_dblog('error', source , ex)
        if action == 'delete':
            err_msg = LogWriter.delete_err_message(ex)
            items = {'success':False, 'message': err_msg}
            return items
        else:
            items = {}
            items['success'] = False
            if not items.get('message'):
                items['message'] = str(ex)
            return items

    return items
