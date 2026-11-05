import json as _json

from django.core.exceptions import PermissionDenied

from domain.services.sql import DbUtil
from domain.services.logging import LogWriter
from domain.services.account import user_is_platform_admin

from domain.models.system import GridColumn, GridColumnLanguage

def grid_setting(context):
    '''
    작성명 : 코드정보
    작성자 : 김태영
    작성일 : 2021-03-12
    비고 :

    -수정사항-
    수정일             작업자     수정내용
    2020-01-01     홍길동      테스트수정내용
    '''
    items = []
    gparam = context.gparam
    posparam = context.posparam
    request = context.request
    action = gparam.get('action', 'read')

    # 컬럼 설정은 모든 사용자가 공유한다. 바꾸는 것은 관리자만(사용자 결정, 2026-10-06).
    if action in ('save_columns', 'delete') and not user_is_platform_admin(request.user):
        raise PermissionDenied

    try:
        if action=='load_columns':
            module_name = gparam.get('module_name')
            template_name = gparam.get('template_name', 'default')
            grid_name = gparam.get('grid_name')
            lang_code = gparam.get('lang_code')

            sql = '''
                select
                    gc."Index"      as "index",
                    gc."DataField"  as "dataField",
                    gc."HeaderText" as src_header_text,
                    gc."Width"      as width,
                    gc."Visible"    as visible,
                    coalesce(cl."DispText", gc."HeaderText") as "headerText",
                    cl."DispText"   as text
                from grid_col gc
                left join grid_col_lang cl
                    on cl."GridColumn_id" = gc.id
                   and cl."LangCode" = %(lang_code)s
                where gc."ModuleName" = %(module_name)s
                  and gc."TemplateKey" = %(template_name)s
                  and gc."GridName"    = %(grid_name)s
                order by gc."Index"
            '''
            dc = {}
            dc['module_name'] = module_name
            dc['template_name'] = template_name
            dc['grid_name'] = grid_name
            dc['lang_code'] = lang_code
            items = DbUtil.get_rows(sql, dc)

        elif action=='save_columns':
            module_name = posparam.get('module_name')
            template_name = posparam.get('template_name', 'default')
            grid_name = posparam.get('grid_name')
            lang_code = posparam.get('lang_code')
            columns = posparam.get('Q')
            q = GridColumn.objects.filter(ModuleName=module_name)
            q = q.filter(TemplateKey=template_name)
            q = q.filter(GridName=grid_name)

            if isinstance(columns, str):
                columns = _json.loads(columns)

            for index, col in enumerate(columns):
                data_field = col.get('dataField')
                if not data_field:
                    continue
                q1 = q.filter(DataField=data_field)
                grid_col = q1.first()
                if not grid_col:
                    grid_col = GridColumn()
                    grid_col.ModuleName = module_name
                    grid_col.TemplateKey = template_name
                    grid_col.GridName = grid_name
                    grid_col.Key = data_field  # satisfy unique_together constraint (Key field still used)

                grid_col.Index = index
                grid_col.DataField = data_field
                grid_col.HeaderText = col.get('src_header_text') or col.get('headerText')
                grid_col.Width = col.get('width')
                visible = col.get('visible', True)
                grid_col.Visible = visible not in [False, 'false', 'False', '0', 0, '']
                grid_col.set_audit(request.user)
                grid_col.save()

                grid_col_pk = grid_col.id
                q2 = GridColumnLanguage.objects.filter(GridColumn_id=grid_col_pk)
                q2 = q2.filter(LangCode=lang_code)
                lang_obj = q2.first()
                if not lang_obj:
                    lang_obj = GridColumnLanguage()
                    lang_obj.GridColumn_id=grid_col_pk
                    lang_obj.LangCode=lang_code
                text = col.get('text')
                if not text:
                    text = col.get('headerText') or col.get('src_header_text')
                lang_obj.DispText = text
                lang_obj.set_audit(request.user)
                lang_obj.save()

            items = {'success': True }

        elif action=='delete':
            module_name = posparam.get('module_name')
            template_name = posparam.get('template_name', 'default')
            grid_name = posparam.get('grid_name')

            q = GridColumnLanguage.objects.filter(GridColumn__ModuleName=module_name)
            q = q.filter(GridColumn__TemplateKey=template_name)
            q = q.filter(GridColumn__GridName=grid_name)
            q.delete()

            q = GridColumn.objects.filter(ModuleName=module_name)
            q = q.filter(TemplateKey=template_name)
            q = q.filter(GridName=grid_name)
            q.delete()

            items = {'success': True }
    except Exception as ex:
        source = 'grid_setting : action-{}'.format(action)
        LogWriter.add_dblog('error', source , ex)
        raise ex

    return items
