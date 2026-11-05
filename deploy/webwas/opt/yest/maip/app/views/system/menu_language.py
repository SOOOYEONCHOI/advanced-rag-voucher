from django.conf import settings

from domain.services.logging import LogWriter
from domain.services.date import DateUtil
from domain.services.system import SystemService
from domain.models.system import LabelCode, LabelCodeLanguage, MenuFolder, MenuItem



def menu_language(context):
    '''
    /api/system/menu_language
    '''
    gparam = context.gparam
    posparam = context.posparam
    user = context.request.user
    action = gparam.get('action', 'read')
    system_service = SystemService()    
    result = {}
    try:
        if action=='read':
            MenuFolder_id = gparam.get('MenuFolder_id')
            result = system_service.get_menu_list(MenuFolder_id)
        elif action =='menu_language_list':
            ModuleName = gparam.get('ModuleName') #common
            TemplateKey = gparam.get('TemplateKey') #menu
            label_code = gparam.get('LabelCode') #folder_name or menu_name
            lang_code = gparam.get('LangCode') or settings.LANGUAGE_CODE   # 화면은 한국어만 고친다

            # 조회는 쓰지 않는다. 없으면 빈 목록을 돌려주고, 행 생성은
            # 관리자가 실제로 저장할 때 labellang_save 가 한다(아래).
            # 여기서 만들면 화면을 훑기만 해도 label_code 가 늘어난다.
            labelcode = LabelCode.objects.filter(
                ModuleName=ModuleName, TemplateKey=TemplateKey, LabelCode=label_code).first()
            result = system_service.get_label_lang_list(labelcode.id, lang_code) if labelcode else []
        elif action=='labellang_detail':
            id = gparam.get('id')
            result = system_service.get_label_lang_detail(id)

        elif action=='labellang_save':
            id = posparam.get('id')
            ModuleName = posparam.get('ModuleName') 
            TemplateKey= posparam.get('TemplateKey')
            label_code = posparam.get('LabelCode')
            # 메뉴명 설정은 한국어 표시값만 고친다 — 언어를 보내지 않으면 기본 언어다
            LangCode = posparam.get('LangCode') or settings.LANGUAGE_CODE
            DispText = (posparam.get('DispText') or '').strip()
            if not DispText:
                return {'success': False, 'message': '표시값을 입력해 주세요.'}

            queryset = LabelCode.objects.filter(ModuleName=ModuleName, TemplateKey=TemplateKey, LabelCode=label_code)

            labelcode = None
            if queryset.count()>0:
                labelcode = queryset[0]
            else:
                labelcode = LabelCode(ModuleName=ModuleName, TemplateKey=TemplateKey, LabelCode=label_code)
                labelcode.set_audit(user)
                labelcode.save()

            labelCodelang = None
            if id:
                queryset = LabelCodeLanguage.objects.filter(id=id, LabelCode=labelcode, LangCode=LangCode)
                if queryset.count()==0:
                    labelCodelang = LabelCodeLanguage()
                else:
                    labelCodelang = queryset[0]
            else:
                labelCodelang = LabelCodeLanguage()

            labelCodelang.LabelCode = labelcode
            labelCodelang.LangCode = LangCode
            labelCodelang.DispText = DispText
            labelCodelang.set_audit(context.request.user)
            labelCodelang.save()
            result = {'success': True}
        elif action=='labellang_delete':
            id = posparam.get('id')
            row_effected = LabelCodeLanguage.objects.filter(id=id).first()
            row_effected.delete()
            result = { 'success' : True }
        else:
            raise Exception('action error : ' + action)


    except Exception as ex:
        source = '/api/system/menu_language, action:{}'.format(action)
        LogWriter.add_dblog('error', source, ex)
        if action == 'labellang_delete':
            err_msg = LogWriter.delete_err_message(ex)
            result = {'success':False, 'message': err_msg}
            return result
        else:
            # 예외 원문(SQL·영문)은 DB 로그에만 남긴다
            return {'success': False, 'message': '처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'}
        #raise ex



    return result


