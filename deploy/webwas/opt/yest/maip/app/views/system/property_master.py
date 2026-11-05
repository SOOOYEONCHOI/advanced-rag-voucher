from domain.services.logging import LogWriter
from domain.services.sql import DbUtil
from domain.models.system import PropertyMaster


def property_master(context):
    items = []
    gparam = context.gparam
    posparam = context.posparam
    request = context.request
    action = gparam.get('action','read')
    try:
        if action == 'read':
            tb_name = gparam.get('tb_name',None)
            sql = ''' select pm.id
            , fn_code_name('prop_master', pm."TableName") as table_name
            , pm."Code" as table_code
            , fn_code_name('value_type', pm."Type") as val_type
            , pm."Description" as description
            from prop_master pm
            left join sys_code sc on pm."TableName" =sc."Value" 
            where 1=1 
            '''
            if tb_name:
                sql += '''
                and pm."TableName"  = %(tb_name)s
                '''

            dc = {}
            dc['tb_name'] = tb_name
            items = DbUtil.get_rows(sql,dc)

        elif action == 'detail':
            prop_master_id = context.gparam.get('id')
            sql = '''
            select pm.id
            , pm."TableName" as table_name
            , pm."Code" as table_code
            , pm."Type" as val_type
            , pm."Description" as description
            from prop_master pm 
            where pm.id = %(prop_master_id)s 
            '''
            dc = {}
            dc['prop_master_id'] = prop_master_id
            items = DbUtil.get_row(sql, dc)

        elif action == 'save':
            id = posparam.get('id')
            table_name = posparam.get('table_name')
            table_code = posparam.get('table_code')
            description = posparam.get('description')
            val_type = posparam.get('val_type') 
            new_data = posparam.get('new_data') 
            name_code = PropertyMaster.objects.filter(TableName = table_name, Code = table_code).first()

            if id:
                if new_data == 'Y' and name_code: #alert
                    return {'success' : False , 'message': '이미 존재하는 코드입니다.' }
                elif new_data == 'Y': #insert
                    prop_master = PropertyMaster( TableName = table_name, Code=table_code, Type = val_type, Description=description )
                    prop_master.save()
                    new_id = prop_master.id
                else: #update
                    prop_master = PropertyMaster.objects.get(id=id)
                    prop_master.TableName = table_name
                    prop_master.Code = table_code
                    prop_master.Type = val_type
                    prop_master.Description = description
                    prop_master.save()
                    new_id = id
            else: #new 
                if name_code:
                    return {'success' : False , 'message': '이미 존재하는 코드입니다.' }
                else:
                    prop_master = PropertyMaster( TableName = table_name, Code=table_code, Type = val_type, Description=description )
                    prop_master.save()
                    new_id = prop_master.id

            items = {'success':True, 'id':new_id, 'message':''}

        elif action == 'delete':
            id = posparam.get('id')
            PropertyMaster.objects.filter(id=id).delete()
            items = {'success':True}

    except Exception as ex:
        source = 'prop_master : action-{}'.format(action)
        LogWriter.add_dblog('error', source , ex)
        raise ex

    return items

