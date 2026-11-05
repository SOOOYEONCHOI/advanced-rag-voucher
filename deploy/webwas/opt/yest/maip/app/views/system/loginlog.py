from configurations import settings

from domain.services.logging import LogWriter
from domain.services.date import DateUtil
from domain.services.sql import DbUtil

from app.views.item import page_params
from domain.services.system import SystemService





def loginlog(context):
    '''
    api/system/systemlog
    '''
    systemService = SystemService()
    gparam = context.gparam
    start = gparam.get('srchStartDt', None) + ' 00:00:00'
    end = gparam.get('srchEndDt', None) + ' 23:59:59'
    keyword = gparam.get('keyword', None)

    items = systemService.get_loginlog_list(start, end, keyword, *log_page(gparam))
    return items


def log_page(gparam):
    """로그 목록 (page, size). 50건씩, 200건까지. 엑셀(`export`)은 조건 전체다."""
    page, size = page_params(gparam, 50, max_size=200)
    return (1, None) if gparam.get('export') else (page, size)
