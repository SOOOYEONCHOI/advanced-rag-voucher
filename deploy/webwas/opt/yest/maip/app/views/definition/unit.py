from domain.services.logging import LogWriter
from domain.services.definition.unit import UnitService
from domain.models.basic import Unit

def unit(context):
    '''
    작성명 : 단위정보
    작성자 : 이인호
    작성일 : 2020-12-23
    비고 :

    -수정사항-
    수정일             작업자     수정내용
    2020-01-01     홍길동      테스트수정내용
    '''
    items=[]
    gparam = context.gparam
    posparam = context.posparam
    unit_name = gparam.get('unit_name', None)
    action = gparam.get('action', 'list')
    unit_service = UnitService()

    try:
        if action=='list':
            items = unit_service.get_unit_list(unit_name)
        elif action=='detail':
            unit_id = context.gparam.get('unit_id')
            items = unit_service.get_unit_detail(unit_id)
        elif action=='save':
            id = posparam.get('id')
            name = posparam.get('name')
            description = posparam.get('description')
            piece_yn = posparam.get('piece_yn')

            name_chk = Unit.objects.filter(Name=name)

            if id:
                name_chk = name_chk.exclude(id=id)
                if name_chk : 
                    return {'success':False, 'message':'중복된 단위명이 존재합니다.'}
                unit = Unit.objects.get(id=id)
            else:
                if name_chk : 
                    return {'success':False, 'message':'중복된 단위명이 존재합니다.'}
                unit = Unit()
            unit.Name = name
            unit.Description = description
            unit.PieceYN = piece_yn
            unit.save()
            items = {'success':True}
        elif action=='delete':
            id = posparam.get('id')
            if id:
                unit = Unit.objects.filter(id=id).first()
                unit.delete()
                items = {'success':True}
        else:
            raise Exception("action : " + action)

    except Exception as ex:
        source = 'unit : action-{}'.format(action)
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