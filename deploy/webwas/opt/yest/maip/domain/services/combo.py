import datetime

from domain import init_once

from .logging import LogWriter
from .sql import DbUtil
from domain.models.basic import Company, Factory, Unit
from domain.models.system import DocumentForm, MenuFolder, MenuItem, SystemCode, UserCode, Depart
from domain.models.user import UserGroup, UserProfile


@init_once
class ComboService(object):
    """화면 콤보박스 데이터 제공.

    원본 MES의 74개 콤보 중 통합 플랫폼 범위(시스템관리·기준정보)에 해당하는
    것만 남겼다. 데이터관리·비전검사 콤보는 각 Phase에서 추가한다.
    """

    __dic_func__ = None
    __initialized__ = False

    @classmethod
    def __static_init__(cls):
        if cls.__initialized__:
            return

        cls.__dic_func__ = {
            'company': cls.company,
            'depart': cls.depart,
            'doc_form': cls.doc_form,
            'factory': cls.factory,
            'menu_code': cls.menu_code,
            'menu_folder': cls.menu_folder,
            'menu_item': cls.menu_item,
            'menu_template': cls.menu_template,
            'parent_code': cls.parent_code,
            'parent_user_code_id': cls.parent_user_code_id,
            'system_code': cls.system_code,
            'system_codetype': cls.system_codetype,
            'unit': cls.unit,
            'user_code': cls.user_code,
            'user_code_id': cls.user_code_id,
            'user_group': cls.user_group,
            'user_profile': cls.user_profile,
        }
        cls.__initialized__ = True


    @classmethod
    def get_combo_list(cls, combo_type, cond1, cond2, cond3):
        try:
            items = []

            if combo_type in cls.__dic_func__:
                items = cls.__dic_func__[combo_type](cond1, cond2, cond3)

                #items = cache.get(combo_type, None)
                #if not items:
                #    items = cls.__dic_func__[combo_type](cond1, cond2, cond3)
                #    cache.set(combo_type, items)

            else:
                print('combo_type : '+ combo_type)

            return items
        except Exception as ex:
            source = 'ComboService.get_combo_list, combo_type:{}'.format(combo_type)
            LogWriter.add_dblog('error', source , ex)
            raise ex

    @classmethod
    def company(cls, cond1, cond2, cond3):
        #if cond1:
        #    q = Company.objects.filter(CompanyType=cond1)
        #else:
        #    q = Company.objects.all()
        #q = q.values('id','Name').order_by('Name')
        #items = [ {'value': entry['id'], 'text':entry['Name']} for entry in q ]
        if cond1:
            sql = '''with A as (
		        select "DataPk"
		        from class_data
		        where "TableName" = 'company'
		        and "ClassName" = 'company_type'
		        and "Tag" = %(comp_type)s
	        )
	        select C.id as value, C."Name" as text
	        from A
	        inner join company C on C.id = A."DataPk"
            order by 2
            '''
        else:
            sql = '''select C.id as value, C."Name" as text
	        from company C
            order by 2
            '''
        dc = {}
        dc['comp_type'] = cond1
        items = DbUtil.get_rows(sql, dc)

        return items

    @classmethod
    def depart(cls, cond1, cond2, cond3):
        q = Depart.objects.all()
        if cond1:
            q = q.filter(Type=cond1)

        q = q.values('id', 'Name').order_by('Name')
        items = [ {'value': entry['id'], 'text':entry['Name']} for entry in q ]
        return items

    @classmethod
    def doc_form(cls, cond1, cond2, cond3):
        q = DocumentForm.objects.filter(FormType=cond1)
        q = q.values('id', 'FormName').order_by('FormName')
        items = [ {'value': entry['id'], 'text':entry['FormName']} for entry in q ]
        return items

    @classmethod
    def factory(cls, cond1, cond2, cond3):
        query = Factory.objects.values('id', 'Name').order_by('id')
        items = [ {'value': entry['id'], 'text':entry['Name']} for entry in query ]
        return items

    @classmethod
    def menu_code(cls, cond1, cond2, cond3):
        items = []
        if cond1:
            query = MenuItem.objects.filter(MenuFolder_id=cond1).values('MenuCode','MenuName')
            items = [ {'value' : entry['MenuCode'], 'text' : entry['MenuName'] } for entry in query ]
        return items

    @classmethod
    def menu_folder(cls, cond1, cond2, cond3):
        # 3depth 추가
        query = MenuFolder.objects
        if cond1 == 'null': #1 level
            query = query.filter(Parent_id__isnull=True)
        elif cond1:
            query = query.filter(Parent_id=cond1)

        query = MenuFolder.objects.values('id', 'FolderName').order_by('_order')
        items = [ {'value' : entry['id'], 'text' : entry['FolderName'] } for entry in query ]
        return items

    @classmethod
    def menu_item(cls, cond1, cond2, cond3):
        query = MenuItem.objects.values('MenuCode','MenuName','MenuFolder__FolderName')
        items = []
        for item in query:
            value = item['MenuCode']
            text = '{}({})'.format(item['MenuName'],item['MenuFolder__FolderName'])
            dic = { 'value': value, 'text':text }
            items.append(dic)

        return items

    @classmethod
    def menu_template(cls, cond1, cond2, cond3):
        from domain.gui import GUIConfiguration

        items = []
        if cond1:
            gui = GUIConfiguration.get_gui_info(cond1)
            dic_templates = gui['templates']
            for k, v in dic_templates.items():
                items.append({'value': k, 'text': k})
        return items

    @classmethod
    def parent_code(cls, cond1, cond2, cond3):
        query = UserCode.objects.filter(Parent_id__isnull=True).values('id', 'Value').order_by('Value')
        
        items = [ {'value': entry['id'], 'text':entry['Value']} for entry in query ]
        return items

    @classmethod
    def parent_user_code_id(cls, cond1, cond2, cond3):
        ''' parent_id is null. combo value=id
        '''
        query = UserCode.objects.filter(Parent__isnull=True).values('id', 'Code', 'Value').order_by('Value')
        
        items = [ {'value': entry['id'], 'text':entry['Value'], 'code': entry['Code']} for entry in query ]
        return items

    @classmethod
    def system_code(cls, cond1, cond2, cond3):
        if cond1 == 'export_yn':
            print('debug')
        q = SystemCode.objects.filter(CodeType=cond1)
        if cond2:
            if ',' in cond2:
                cond2 = cond2.replace(' ', '')
                cond_list = cond2.split(',')
                q = q.filter(Code__in=cond_list)
            else:
                q = q.filter(Code=cond2)
        #if cond3:
        #    q= q.filter(Q(Code=cond2)|Q(Code=cond3))
        #elif cond2:
        #    q = q.filter(Code=cond2)
        q = q.values('Code', 'Value').order_by('_ordering')
        #print(q.query)
        items = [ {'value': entry['Code'], 'text':entry['Value']} for entry in q ]
        return items

    @classmethod
    def system_codetype(cls, cond1, cond2, cond3):
        if settings.DBMS == 'MSSQL':
            sql = ''' select distinct "CodeType" as value,  "CodeType" as text
            from sys_code
            order by 1
            '''
            items = DbUtil.get_rows(sql)
        else:
            query = SystemCode.objects.order_by('CodeType').distinct('CodeType').values('CodeType')
            items = [ {'value': entry['CodeType'], 'text':entry['CodeType']} for entry in query ]
        return items

    @classmethod
    def unit(cls, cond1, cond2, cond3):
        queryset = Unit.objects.all().values('id','Name').order_by('Name')
        items = [ {'value': entry['id'], 'text':entry['Name']} for entry in queryset ]

        return items

    @classmethod
    def user_code(cls, cond1, cond2, cond3):
        query = UserCode.objects.filter(Parent__Code=cond1).values('Code', 'Value').order_by('Value').order_by('_order')
        #print(query.query)
        items = [ {'value': entry['Code'], 'text':entry['Value']} for entry in query ]
        return items

    @classmethod
    def user_code_id(cls, cond1, cond2, cond3):
        ''' combo value=id
        '''
        query = UserCode.objects.filter(Parent__Code=cond1).values('id', 'Code', 'Value').order_by('Value')
        items = [ {'value': entry['id'], 'text':entry['Value'], 'code': entry['Code']} for entry in query ]
        return items

    @classmethod
    def user_group(cls, cond1, cond2, cond3):
        query = UserGroup.objects.values('id', 'Name').order_by('Name')
        items = [ {'value': entry['id'], 'text':entry['Name']} for entry in query ]
        return items

    @classmethod
    def user_profile(cls, cond1, cond2, cond3):
        query = UserProfile.objects.values('User_id', 'Name').order_by('Name')
        items = [ {'value': entry['User_id'], 'text':entry['Name']} for entry in query ]

        return items
