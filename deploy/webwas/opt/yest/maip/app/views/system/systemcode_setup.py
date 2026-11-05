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



def systemcode_setup(context):
    '''
    /api/system/systemcode_setup
    '''

    sevice = SystemSetupService()
    success = sevice.setup_systemcode()
    result = {'success': success}
    return result

