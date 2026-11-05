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



def system_code(context):
    '''
    /api/system/system_code
    '''

    result = []
    gparam = context.gparam
    action = gparam.get('action', 'read')
    system_service = SystemService()
    if action=='read':
        code_type = gparam.get('code_type')
        keyword = gparam.get('keyword')
        result = system_service.get_system_code_list(code_type, keyword)

    return result


