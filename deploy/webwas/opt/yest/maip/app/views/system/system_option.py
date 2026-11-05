import json
from datetime import datetime
from django.shortcuts import render
from django.http import HttpRequest
from configurations import settings
from domain.services.setup import SystemSetupService
from domain.services.system import SystemService
from domain.gui import GUIConfiguration
from domain.models.system import MenuFolder, MenuItem, SystemOption
from domain.services.date import DateUtil
from domain.services.logging import LogWriter
from django.db.models import Max 



def system_option(context):
    '''
    /api/system/system_option
    '''
    result = []
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action', 'read')
    user = context.request.user
    if action =='read':
        queryset = SystemOption.objects.all()
        result = []
        for systm_option in queryset:
            dic = { 'id' : systm_option.id, 'code': systm_option.Code, 'value': systm_option.Value, 'description': systm_option.Description }
            result.append(dic)
    elif action=='detail':
        id = gparam.get('id')
        systm_option = SystemOption.objects.get(id=id)
        result = { 'id' : systm_option.id, 'code': systm_option.Code, 'value': systm_option.Value, 'description': systm_option.Description }

    elif action=='save':
        id = posparam.get('id')
        code = posparam.get('code')
        value = posparam.get('value')
        description = posparam.get('description')

        system_option = None
        
        #if id:
        #    system_option = SystemOption.objects.get(id=id)
        #else:
        #    system_option = SystemOption()
        system_option = SystemOption.objects.filter(Code=code).first()
        if not system_option:
            system_option = SystemOption()
            system_option.Code = code
        
        system_option.Value = value
        system_option.Description = description
        system_option.set_audit(user)
        system_option.save()
        result = {'success' : True, 'id' : system_option.id}

    elif action=='delete':
        id = posparam.get('id')
        effected_count = SystemOption.objects.filter(id=id).delete()
        result = {'success' : True, 'effected_count': effected_count}

    elif action=='setup':

        saved_count = 0
        count = SystemOption.objects.filter(Code='consume_from_house_option').count()
        if count==0:
            system_option = SystemOption()
            system_option.Code = 'consume_from_house_option'
            system_option.Description = '생산투입자재 자동출고처리. process(공정창고), master(품목마스터지정, 기본값)'
            system_option.Value='master'
            system_option.save()
            saved_count = saved_count + 1

        count = SystemOption.objects.filter(Code='product_move_to_option').count()
        if count==0:
            system_option = SystemOption()
            system_option.Code = 'product_move_to_option'
            system_option.Description = '생산완료시 제품창고 입고처리. potential_input(가입고), input(입고, 기본값)'
            system_option.Value='input'
            system_option.save()
            saved_count = saved_count + 1

        count = SystemOption.objects.filter(Code='LOGO_TITLE').count()
        if count==0:
            system_option = SystemOption()
            system_option.Code = 'LOGO_TITLE'
            system_option.Description = '왼쪽메뉴상단타이틀'
            system_option.Value='제조AI플랫폼'
            system_option.save()
            saved_count = saved_count + 1

        count = SystemOption.objects.filter(Code='main_menu').count()
        if count==0:
            system_option = SystemOption()
            system_option.Code = 'main_menu'
            system_option.Description = '메인메뉴, 고정메뉴. 디폴트:wm_vis_inspection'
            system_option.Value='wm_vis_inspection'
            system_option.save()
            saved_count = saved_count + 1

        result = {'success':True,'saved_count':saved_count}

    elif action == 'get_option_value':
        ''' 키를 조건으로 value 리턴
        '''
        Code = gparam.get('code')
        system_option = SystemOption.objects.filter(Code=Code).first()
        if system_option:
            return system_option.Value
        else:
            return 'N'

    return result
