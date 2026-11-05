from domain.services.logging import LogWriter
from domain.services.date import DateUtil
from domain.services.system import SystemService
from domain.models.system import LabelCode, LabelCodeLanguage, MenuFolder, MenuItem

def  labelcode(context):
    '''
    /api/system/labelcode
    '''
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action', 'read')
    system_service = SystemService()    

    result = []
    try:
        if action =='labelcode_read':
            menu_code = gparam.get('menu_code')
            result = system_service.get_labelcode_list(menu_code)
        elif action=='labelcode_detail':
            id = gparam.get('id')
            result = system_service.get_labelcode_detail(id)
        elif action=='labelcode_save':

            id = posparam.get('id')
            ModuleName = posparam.get('ModuleName')
            TemplateKey = posparam.get('TemplateKey')
            Code = posparam.get('LabelCode')
            Description = posparam.get('Description')

            labelcode = None
            if id:
                labelcode = LabelCode.objects.get(id=id)
            else:
                labelcode = LabelCode()

            labelcode.ModuleName = ModuleName
            labelcode.TemplateKey = TemplateKey
            labelcode.LabelCode = Code
            labelcode.Description = Description

            labelcode.set_audit(context.request.user)
            labelcode.save()

            result = {'success': True}
        elif action=='labelcode_delete':
            id = posparam.get('id')
            LabelCode.objects.filter(id=id).delete()
            result = {'success': True}
        elif action=='label_language_list':
            labelcode_id = gparam.get('labelcode_id');
            lang_code = gparam.get('lang_code');
            result = system_service.get_label_lang_list(labelcode_id, lang_code)
        elif action=='labellang_save':
            id = posparam.get('id', None);
            LangCode = posparam.get('LangCode');

            labelCodelang = None
            if id:
                queryset = LabelCodeLanguage.objects.filter(id=id, LangCode=LangCode)
                if queryset.count()==0:
                    labelCodelang = LabelCodeLanguage()
                else:
                    labelCodelang = queryset[0]
            else:
                labelCodelang = LabelCodeLanguage()

            labelCodelang.LabelCode_id = posparam.get('LabelCode_id')
            labelCodelang.LangCode = posparam.get('LangCode')
            labelCodelang.DispText = posparam.get('DispText')
            labelCodelang.set_audit(context.request.user)
            labelCodelang.save()

            result = {'success': True}
        elif action =='labellang_detail':
            id = gparam.get('id')
            result = system_service.get_label_lang_detail(id)
        elif action=='labellang_delete':
            id = posparam.get('id')
            row_effected = LabelCodeLanguage.objects.filter(id=id).delete()
            result={'success': True, 'row_effected' : row_effected}
        else:
            raise Exception('action error : ' + action)

    except Exception as ex:
        source = '/api/system/labelcode, action:{}'.format(action)
        LogWriter.add_dblog('error', source, ex)
        if action == 'delete':
            err_msg = LogWriter.delete_err_message(ex)
            result = {'success':False, 'message': err_msg}
            return result
        else:
            result = {}
            result['success'] = False
            if not result.get('message'):
                result['message'] = str(ex)
            return result
        #raise ex

    return result





