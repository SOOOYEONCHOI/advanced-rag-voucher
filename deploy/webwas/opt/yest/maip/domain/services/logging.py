import logging
import re, sys, time

from configurations import settings
from .date import DateUtil

from domain.models.system import SystemLog

from domain import init_once

system_logger = logging.getLogger('system')

@init_once
class LogWriter:
    dic_table = {}

    @classmethod
    def __static_init__(cls):
        cls.dic_table = cls.table_name_load()
        return


    @classmethod
    def table_name_load(cls):
        dc = {}
        dc['Area'] = '에어리어'
        dc['area'] = '에어리어'
        dc['BoardReply'] = '게시판댓글'
        dc['board_reply'] = '게시판댓글'
        dc['BOM'] = 'BOM'
        dc['bom'] = 'BOM'
        dc['BOMComponent'] = 'BOM구성'
        dc['bom_comp'] = 'BOM구성'
        dc['BOMProcessComponent'] = 'BOM공정구성'
        dc['bom_proc_comp'] = 'BOM공정구성'
        dc['Bookmark'] = '바로가기메뉴'
        dc['bookmark'] = '바로가기메뉴'
        dc['CustomerComplain'] = '고객불만'
        dc['cust_complain'] = '고객불만'
        dc['DASConfig'] = 'DAS설정'
        dc['das_config'] = 'DAS설정'
        dc['DocumentResult'] = '문서결과'
        dc['doc_result'] = '문서결과'
        dc['Equipment'] = '설비'
        dc['equ'] = '설비'
        dc['EquipmentMaint'] = '설비정비내역'
        dc['equip_maint'] = '설비정비내역'
        dc['EquipRun'] = '설비가동'
        dc['equ_run'] = '설비가동'

        dc['HaccpDiary'] = 'Haccp일지'
        dc['HaccpDiaryForeignDetect'] = 'Haccp일지이물질발생'
        dc['HaccpItem'] = 'Haccp항목'
        dc['HaccpItemLimit'] = 'Haccp항목기준'
        dc['HaccpItemResult'] = 'Haccp항목결과'
        dc['HaccpProcessItem'] = 'Haccp공정별항목'
        dc['HaccpTest'] = 'Haccp검사'

        dc['JobResponse'] = '작업지시결과'
        dc['job_res'] = '작업지시결과'
        dc['JobResponseDefect'] = '작업부적합내역'
        dc['job_res_defect'] = '작업부적합내역'

        dc['KpiYearTarget'] = 'KPI연목표'
        dc['KpiMonthResult'] = 'KPI월실적'

        dc['LoginLog'] = '로그인로그'
        dc['login_log'] = '로그인로그'
        dc['Material'] = '품목'
        dc['material'] = '품목'
        dc['MaterialCompanyUnitPrice'] = '품목거래처단가'
        dc['mat_comp_uprice'] = '품목거래처단가'
        dc['MaterialConsume'] = '품목소비'
        dc['mat_consu'] = '품목소비'
        dc['MaterialDayStock'] = '일재고마감'
        dc['mat_day_stock'] = '일재고마감'
        dc['MaterialDayHouseStock'] = '일창고재고마감'
        dc['mat_day_house_stock'] = '일창고재고마감'
        
        dc['MaterialInout'] = '품목입출고'
        dc['mat_inout'] = '품목입출고'
        dc['MaterialInHouse'] = '품목창고재고'
        dc['mat_in_house'] = '품목창고재고'
        dc['MaterialInoutHead'] = '자재입출고헤더'
        dc['mat_inout_head'] = '자재입출고헤더'
        dc['MaterialLot'] = '품목로트'
        dc['mat_lot'] = '품목로트'
        dc['MaterialLotConsume'] = '로트출고'
        dc['mat_lot_cons'] = '로트출고'
        dc['MaterialOrder'] = '자재발주'
        dc['mat_order'] = '자재발주'
        dc['MaterialProcessInput'] = '자재공정투입'
        dc['mat_proc_input_req'] = '자재공정투입'
        dc['MaterialProduce'] = '제품생산'
        dc['mat_produce'] = '제품생산'
        dc['MaterialRequirement'] = '품목필요량'
        dc['mat_requ'] = '품목필요량'
        dc['MenuFolder'] = '메뉴폴더'
        dc['menu_folder'] = '메뉴폴더'
        dc['MenuItem'] = '메뉴항목'
        dc['menu_item'] = '메뉴항목'

        dc['Mold'] = '금형'
        dc['MoldClassProd'] = '금형종류생산품'

        dc['Person'] = '작업자'
        dc['person'] = '작업자'
        dc['PersonCenterAssign'] = '작업자근무배치'
        dc['person_center_assign'] = '작업자근무배치'
        dc['PersonWorkDiary'] = '작업자출근내역'
        dc['person_work_diary'] = '작업자출근내역'
        dc['PersonWorkSchedule'] = '작업자교대조스케쥴'
        dc['person_work_schedule'] = '작업자교대조스케쥴'
        dc['Process'] = '공정'
        dc['process'] = '공정'
        dc['ProcessDefectType'] = '공정별부적합유형'
        dc['proc_defect_type'] = '공정별부적합유형'
        dc['ProcessStopCause'] = '공정별비가동유형'
        dc['proc_stop_cause'] = '공정별비가동유형'

        dc['ProductionProcessInfo'] = '제품공정정보'

        dc['Routing'] = '라우팅'
        dc['routing'] = '라우팅'
        dc['Shipment'] = '출하'
        dc['shipment'] = '출하'
        dc['ShipmentHead'] = '출하헤더'
        dc['shipment_head'] = '출하헤더'
        dc['StockTake'] = '재고실사'
        dc['stock_take'] = '재고실사'
        dc['StopCause'] = '비가동유형'
        dc['stop_cause'] = '비가동유형'
        dc['StoreHouse'] = '창고'
        dc['store_house'] = '창고'
        dc['Suju'] = '수주'
        dc['suju'] = '수주'
        dc['SujuHead'] = '수주(헤더)'
        dc['suju_head'] = '수주(헤더)'
        dc['SujuMoneyReceive'] = '수주수금'
        dc['suju_money_receive'] = '수주수금'

        dc['TestItem'] = '검사항목'
        dc['TestItemMaster'] = '검사항목마스터'
        dc['TestResultCode'] = '검사선택형결과코드'

        dc['TagMaster'] = '태그마스터'
        dc['tag'] = '태그마스터'

        dc['TagData'] = '태그데이터'
        dc['tag_dat'] = '태그데이터'

        dc['TestDefectResult'] = '검사부적합내역'
        dc['TestMasterMaterial'] = '검사마스터적용품목'
        dc['TestMaster'] = '검사마스터'
        dc['TestMethod'] = '검사방법'
        dc['TestResult'] = '검사결과'
        dc['TestItemResult'] = '검사항목결과'

        dc['UserCode'] = '사용자코드'
        dc['user_code'] = '사용자코드'
        dc['UserGroupMenu'] = '사용자그룹메뉴'
        dc['user_group_menu'] = '사용자그룹메뉴'
        dc['UserProfile'] = '사용자프로필'
        dc['user_profile'] = '사용자프로필'
        dc['WorkCenter'] = '워크센터'
        dc['work_center'] = '워크센터'

        #추가
        dc['Jig'] = '지그'
        dc['jig'] = '지그'
        dc['JigBox'] = '지그박스'
        dc['jigbox'] = '지그박스'
        #dc['JigBoxLoading'] = 'JigBoxLoading'
        dc['JigOrder'] = '지그발주'
        dc['jig_order'] = '지그발주'
        #dc['JigBoxAdjustQantity'] = 'JigBoxAdjustQantity'
        #dc['JigExtendUseApproval'] = 'JigExtendUseApproval'
        #dc['JigBoxUsingHistory'] = 'JigBoxUsingHistory'
        dc['JigReceiving'] = '지그입고'
        dc['jig_receiving'] = '지그입고'
        #dc['JigBoxLoadingHistory'] = 'JigBoxLoadingHistory'
        #dc['CustomerInjectionMold'] = 'CustomerInjectionMold'
        #dc['ProductionProcessInfo'] = 'ProductionProcessInfo'
        #dc['UvLamp'] = 'UV램프'
        #dc['jigsupplier'] = 'JIG공급업체'
        #dc['JigSupplier'] = 'JIG공급업체'

        dc['Company'] = '업체'
        dc['DeliveryPlace'] = '납품처'
        dc['delivery_place'] = '납품처'
        dc['Unit'] = '단위'
        dc['unit'] = '단위'
        dc['RoutingProcess'] = '표준라우팅공정'
        dc['routing_process'] = '표준라우팅공정'
        dc['LocationInStoreHouse'] = '창고내 위치'
        dc['location_in_storeHouse'] = '창고내 위치'

        dc['LabelCode'] = '라벨코드'
        dc['label_code'] = '라벨코드'
        dc['LabelCodeLanguage'] = '라벨다국어설정'
        dc['label_code_lang'] = '라벨다국어설정'
        dc['DocumentResult'] = '문서결과'
        dc['test_result_code'] = '검사선택형결과코드'
        dc['test_defect_result'] = '검사부적합내역'
        dc['test_result'] = '검사결과'
        dc['mold'] = '금형'
        return dc


    # 참조하는 쪽 표(모델) 이름. Django ProtectedError · PostgreSQL(영문) · PostgreSQL(한글) 순.
    FK_REFERRER = (re.compile(r"foreign keys?: '(\w+)\."),
                   re.compile(r'on table "(\w+)"'),
                   re.compile(r'"(\w+)" 테이블'))

    @classmethod
    def delete_err_message(cls, ex):
        """삭제가 외래키에 걸렸을 때 사용자에게 보일 문구. 참조하는 표를 알면 그 이름을 쓴다.

        PostgreSQL 메시지에는 표 이름이 둘 나온다(지우려던 표 → 참조하는 표). 마지막 것이다.
        """
        text = str(ex)
        for pattern in cls.FK_REFERRER:
            names = pattern.findall(text)
            if names:
                table_name = cls.dic_table.get(names[-1])
                if table_name:
                    return table_name + '에서 사용 중이라 삭제할 수 없습니다.'
                break
        return '다른 곳에서 사용 중인 데이터라 삭제할 수 없습니다.'


    @staticmethod
    def add_dblog(logtype, source, ex=None):
        if isinstance(ex, KeyError):
            message = 'KeyError:' + str(ex)
            #message = str(type(ex)) + ':' + str(ex)
        else:
            message = ex
        SystemLog.add_log(logtype, source, message)
        # 화면(시스템 로그)은 DB 를 읽고 한 줄만 남는다. 파일 로그에는 트레이스까지 남긴다.
        level = logging.ERROR if logtype == 'error' else logging.INFO
        exc_info = (type(ex), ex, ex.__traceback__) if isinstance(ex, BaseException) else None
        system_logger.log(level, '%s %s', source, message, exc_info=exc_info)
        return
