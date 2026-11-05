from domain.services.logging import LogWriter
from domain.services.date import DateUtil

from domain.services.system import SystemService
from domain.services.combo import ComboService

from domain.models.system import Bookmark

def combo(context):
    gparam = context.gparam
    combo_type = gparam.get('combo_type')
    cond1 = gparam.get('cond1', '')
    cond2 = gparam.get('cond2', '')
    cond3 = gparam.get('cond3', '')
    #lang_code = gparam.get('lang_code','ko-KR')

    items = ComboService.get_combo_list(combo_type, cond1, cond2, cond3)
    return items

