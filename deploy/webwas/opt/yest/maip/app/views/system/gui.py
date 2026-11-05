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


def gui(context):
    '''
    /api/system/gui
    '''
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action', 'read')

    items = []    
    try:
        gui_items = GUIConfiguration.get_gui_list()
        if action=='read':
            for k,v in gui_items.items():
                gui_code = k
                name = v.get('name')
                templates= v.get('templates')
                obj_url = '/gui/{}/'.format(k)
                default_template =  templates.get('default')

                gui = {'id' : k, 'name':name, 'page_url': obj_url, 'default': default_template}
                items.append(gui)
        elif action=='combo_list':
            for k,v in gui_items.items():
                gui_code = k
                name = v.get('name')
                text = "{}({})".format(k, name)
                item = { 'value' : k, 'text' : text}
                items.append(item)
        elif action=='template_list':
            gui_code = gparam.get('gui_code')
            if gui_code:
                gui = GUIConfiguration.get_gui_info(gui_code)
                templates = gui.get('templates')
                for k,v in templates.items():
                    text = '{}({})'.format(k, v)
                    items.append({'text': text, 'value': k})

        else:
            print(action)
    except Exception as ex:
        LogWriter.add_dblog('error', 'setup/gui' , ex)
        raise ex


    return items


