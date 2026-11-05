from configurations import settings
from domain.services.common import CommonUtil
from domain.services.sql import DbUtil
from domain.services.logging import LogWriter

from domain.models.system import UserCode

def user_code(context):
    '''
    api/system/user_code
    '''
    items = []
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action', 'read')
        
    try:
        if action=='read':
            parent_code =gparam.get('parent_code')
            type_class_code =gparam.get('type_class_code')
            type2_class_code =gparam.get('type2_class_code')
            type_class_table =gparam.get('type_class_table')
            type2_class_table =gparam.get('type2_class_table')
            base_date =gparam.get('base_date')
            type = gparam.get('type')
            if settings.DBMS == 'MSSQL' : 
                if type_class_table == 'user_code':
                    func_name = 'dbo.fn_user_code_name'
                else:
                    func_name = 'dbo.fn_code_name'
                if type2_class_table == 'user_code':
                    func_name2 = 'dbo.fn_user_code_name'
                else:
                    func_name2 = 'dbo.fn_code_name'
            else:
                if type_class_table == 'user_code':
                    func_name = 'fn_user_code_name'
                else:
                    func_name = 'fn_code_name'
                if type2_class_table == 'user_code':
                    func_name2 = 'fn_user_code_name'
                else:
                    func_name2 = 'fn_code_name'

            sql = '''  select c.id
            , c."Parent_id" as parent_id, c."Code" as code
            , c."Value" as name
            , c."Type" as code_type
            , c."Type2" as code_type2
            , c."Description" as description
            , c."StartDate" as start_date
            , c."EndDate" as end_date
            '''
            sql += ''', ''' + func_name + '''(%(type_class_code)s, c."Type") as code_type_name '''
            sql += ''', ''' + func_name2 + '''(%(type2_class_code)s, c."Type2") as code_type_name2 '''
            sql += ''' from user_code c
            inner join user_code pc on pc.id = c."Parent_id"
            where pc."Code" = %(parent_code)s
            and %(base_date)s between coalesce(c."StartDate",'2000-01-01') and coalesce(c."EndDate",'2100-12-31')
            '''
            if type:
                sql += ''' and c."Type" = %(type)s 
                '''
            sql += ''' order by c."Type", c._order
            '''

            dc = {}
            dc['parent_code'] = parent_code
            dc['type_class_code'] = type_class_code
            dc['type2_class_code'] = type2_class_code
            dc['base_date'] = base_date
            dc['type'] = type
            items = DbUtil.get_rows(sql, dc)
            pass
        elif action=='detail':
            id = gparam.get('id')
            
            sql = ''' select c.id
                , c."Parent_id"
                , c."Code"
                , c."Value"
                , c."Type"
                , c."Type2"
                , c."Description"
                , c."StartDate"
                , c."EndDate"
            from user_code C
            where C.id = %(id)s
            '''
            dc = {}
            dc['id'] = id
            items = DbUtil.get_row(sql, dc)
        elif action=='save':
            parent_code =posparam.get('parent_code')
            q = UserCode.objects.filter(Code=parent_code)
            q = q.filter(Parent__isnull=True)
            parent_id = q.first().id

            id = posparam.get('id')
            Code = posparam.get('Code')
            Value = posparam.get('Value')
            Type = posparam.get('Type')
            Type2 = posparam.get('Type2')
            Description = posparam.get('Description')
            StartDate = posparam.get('StartDate')
            EndDate = posparam.get('EndDate')

            check = UserCode.objects.filter(Code=Code)
            check = check.filter(Parent_id=parent_id)
            
            if id:
                check = check.exclude(id = id)
            if check :
                return {'success' : False , 'message': '이미 존재하는 코드입니다.' }

            if id:
                user_code = UserCode.objects.get(id=id)
            else:
                user_code = UserCode()
                user_code._order = 10000
            user_code.Code = Code
            user_code.Value = Value
            user_code.Type = Type
            user_code.Type2 = Type2
            user_code.Parent_id = CommonUtil.try_int(parent_id )
            user_code.Description = Description
            user_code.StartDate = StartDate
            user_code.EndDate = EndDate
            user_code.save()
            items = { 'success': True ,'id' : user_code.id }

        elif action =='delete':
            id = posparam.get('id')
            user_code = UserCode.objects.filter(id=id).first()
            user_code.delete()
            items = {'success': True}

        elif action == 'code_order_save':
            items = posparam.get('Q')
            order = 1
            for id in items:
                UserCode.objects.filter(id=id).update(_order=order)
                order += 1

    except Exception as ex:
        source = 'system/user_code : action-{}'.format(action)
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
        #raise ex

    return items
