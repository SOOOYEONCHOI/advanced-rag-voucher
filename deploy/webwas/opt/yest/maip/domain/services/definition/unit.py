from domain.services.sql import DbUtil
from domain.services.logging import LogWriter

class UnitService():
    def __init__(self):
        pass

    def get_unit_list(self, unit_name):
        '''
        작성명 : 단위 리스트 조회
        작성자 : 이인호
        작성일 : 2020-12-23
        비고 :

        -수정사항-
        수정일             작업자     수정내용
        2020-01-01     홍길동      테스트수정내용
        '''
        
        sql = ''' select id, "Name" as name ,"Description" as description
        , "PieceYN" as piece_yn
        from unit  
        where 1 = 1
        '''
        if unit_name !='':
            sql += '''
            and upper("Name") like concat('%%',upper(%(unit_name)s),'%%')
            '''
        sql += '''
        order by "Name"
        '''

        items = []
        try:
            dc={}
            dc['unit_name'] = unit_name
            items = DbUtil.get_rows(sql, dc)
        except Exception as ex:
            LogWriter.add_dblog('error', 'DefinitionService.get_unit_list', ex)
            raise ex

        return items

    def get_unit_detail(self, unit_id):
        '''
        작성명 : 단위 상세 조회
        작성자 : 이인호
        작성일 : 2020-12-23
        비고 :

        -수정사항-
        수정일             작업자     수정내용
        2020-01-01     홍길동      테스트수정내용
        '''
        
        sql = ''' select id
        , "Name" as name 
        ,"Description" as description 
        , "PieceYN" as piece_yn
        from unit where id = %(unit_id)s
        '''
        unit = {}
        try:
            dc = {}
            dc['unit_id'] = unit_id
            unit = DbUtil.get_row(sql, dc)

        except Exception as ex:
            LogWriter.add_dblog('error', 'DefinitionService.get_unit_detail', ex)
            raise ex

        return unit

