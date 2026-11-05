from configurations import settings

from domain.services.logging import LogWriter
from domain.services.date import DateUtil
from domain.services.sql import DbUtil

from app.views.system.loginlog import log_page
from domain.services.system import SystemService


def systemlog(context):
    '''
    api/system/systemlog
    '''
    systemService = SystemService()
    items = []
    gparam = context.gparam
    action = gparam.get('action', 'read')
    if action=='read':
        start = gparam.get('srchStartDt', None) + ' 00:00:00'
        end = gparam.get('srchEndDt', None) + ' 23:59:59'
        type = gparam.get('srchType', None)
        source = gparam.get('srchSource', None)

        items = systemService.get_systemlog_list(start, end, type, source, *log_page(gparam))
    elif action=='detail':
        log_id = context.gparam.get('log_id')
        items = systemService.get_systemlog_detail(log_id)

    elif action=='test':
        id = systemService.test_system_log()
        items ={'success': True, 'id': id}
 
    return items


