from configurations import settings
from domain.services.logging import LogWriter
from domain.models import UserCode

def code_info(context):
    '''
    /api/definition/code_info
    '''
    items=[]
    posparam = context.posparam
    gparam = context.gparam
    action = gparam.get('action', 'read')
    request = context.request
    user = request.user

    try:
        if action == 'read_parent':  # 부모 코드 read

            codeName = gparam.get('codeName','')
            
            q = UserCode.objects.filter(Parent__isnull=True, Value__contains=codeName).order_by('-id') ## order by

            items = []
            for row in q:
                dc = {}
                dc['id'] = row.id
                dc['code'] = row.Code
                dc['value'] = row.Value
                dc['description'] = row.Description

                items.append(dc)

        elif action == 'read_child':

            parent_id = gparam.get('parent_id')

            if parent_id:
                q = UserCode.objects.filter(Parent=parent_id).order_by('_order')
                
                for row in q:
                    dc = {}
                    dc['id'] = row.id
                    dc['code'] = row.Code
                    dc['value'] = row.Value
                    dc['description'] = row.Description
                    dc['parent_id'] = row.Parent.id
                    dc['order'] = row._order

                    items.append(dc)

        elif action == 'save_parent':

            lists = posparam.get('Q')   #

            for item in lists:
                code = item.get('code')
                value = item.get('value')
                description = item.get('description')
                id = item.get('id')

                check = UserCode.objects.filter(Code=code) 
                check = check.filter(Parent__isnull=True)

                if id:
                    check = check.exclude(id=id)

                if check:
                    return {'success' : False , 'message': '이미 존재하는 코드입니다.' }

                if not id:
                    uc = UserCode()
                else:
                    uc = UserCode.objects.get(id=id)

                uc.Code = code
                uc.Value = value
                uc.Description = description
                uc.set_audit(user)
                uc.save()

            items = {'success': True}
        
        elif action == 'save_child':

            Q = posparam.get('Q')
            parent_id = posparam.get('parent_id')
            Parent = UserCode.objects.get(id=parent_id)
            children = UserCode.objects.filter(Parent=parent_id)

            for index in range(0, len(Q)):
                list = Q[index]

                code = list.get('code')
                value = list.get('value')
                description = list.get('description')
                id = list.get('id')

                check = children
                check = check.filter(Code=code)

                if id:
                    check = check.exclude(id=id)

                if check:
                    return {'success' : False , 'message': '이미 존재하는 코드입니다.' }

                if not id:
                    uc = UserCode()
                    uc.Parent = Parent
                else:
                    uc = UserCode.objects.get(id=id)

                uc.Code = code
                uc.Value = value
                uc.Description = description
                uc._order = index
                uc.set_audit(user)
                uc.save()

            items = {'success': True}

        elif action == 'delete_parent':

            id = posparam.get('id')
            child = UserCode.objects.filter(Parent=id)
            first = child.first()
            if first:
                child.delete()

            q = UserCode.objects.filter(id=id)
            q.delete()

            items = {'success': True}

        elif action == 'delete_child':

            id = posparam.get('id')
            q = UserCode.objects.filter(id=id)
            q.delete()

            items = {'success': True}

        
        elif action == 'basic_user_code_insert': # basic_haccp_insert
            ''' 사용자코드 기본데이터 등록
            '''
            # Parent 기본 코드값 세팅
            code_grp_list = [
                { 
                    'Code': 'air_filter_class', 'Value': '에어필터종류',
                    'Code_List' : [
                        { 'Code': '레큘레이터', 'Value': '레큘레이터', },
                        { 'Code': '무정전', 'Value': '무정전',  },
                        { 'Code': '미디움', 'Value': '미디움', },
                        { 'Code': '셀렉', 'Value': '셀렉', },
                        { 'Code': '프리', 'Value': '프리', },
                     ],
                },
                {
                    'Code': 'calib_inst_class', 'Value': '검교정기기종류',
                    'Code_List' : [
                        { 'Code': '습도계', 'Value': '습도계', },
                        { 'Code': 'thermometer', 'Value': 'thermometer',  },
                        { 'Code': 'timer', 'Value': '타이머', },
                     ],
                },
                {
                    'Code': 'haccp_add_ethanol_devi_action', 'Value': 'CCP주정첨가 이탈사항',
                    'Code_List' : [
                        { 'Code': 'haccp_add_ethanol_f01', 'Value': '조치사항1', },
                        { 'Code': 'haccp_add_ethanol_f02', 'Value': '조치사항2',  },
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': 'haccp_bake_devi_action', 'Value': 'HACCP가열(굽기)이탈사항',
                    'Code_List' : [
                        { 'Code': 'haccp_da_01', 'Value': '조치사항1', },
                        { 'Code': 'haccp_da_02', 'Value': '조치사항2',  },
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': 'haccp_cream_devi_action', 'Value': 'CCP크림/무스 이탈사항',
                    'Code_List' : [
                        { 'Code': 'haccp_cream_f01', 'Value': '조치사항1', },
                        { 'Code': 'haccp_cream_f02', 'Value': '조치사항2',  },
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': 'haccp_fry_devi_action', 'Value': 'HACCP가열(유탕)일지이탈사항',
                    'Code_List' : [
                        { 'Code': 'haccp_da_f01', 'Value': '조치사항1', },
                        { 'Code': 'haccp_da_f02', 'Value': '조치사항2',  },
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': 'haccp_fsd_devi_action', 'Value': 'HACCP이물검출일지',
                    'Code_List' : [
                        { 'Code': 'haccp_fsd_01', 'Value': '이물검출조치1', },
                        { 'Code': 'haccp_fsd_02', 'Value': '이물검출조치2',  },
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': 'haccp_rapid_freeze_devi_action', 'Value': 'CCP급속동결 이탈사항',
                    'Code_List' : [
                        { 'Code': 'haccp_rapid_freeze_f01', 'Value': '조치사항1', },
                        { 'Code': 'haccp_rapid_freeze_f02', 'Value': '조치사항2',  },
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': 'hand_over_reason', 'Value': '인수인계사유',
                    'Code_List' : [
                        { 'Code': '기타', 'Value': '기타', },
                        { 'Code': '병가', 'Value': '병가',  },
                        { 'Code': '연차', 'Value': '연차', },
                        { 'Code': '휴가', 'Value': '휴가', },
                     ],
                },
                {
                    'Code': 'illum_zone_class', 'Value': '조도구역구분',
                    'Code_List' : [
                        { 'Code': '창고', 'Value': '창고', },
                        { 'Code': '작업장', 'Value': '작업장',  },
                        { 'Code': '검사구역', 'Value': '검사구역', },
                     ],
                },
                {
                    'Code': 'pest_trap_class', 'Value': '트랩구분',
                    'Code_List' : [
                        { 'Code': 'flypaper', 'Value': '쥐끈끈이(글루보드)', },
                        { 'Code': 'repell_lamp', 'Value': '포충등',  },
                     ],
                },
                {
                    'Code': '개인위생일지조치', 'Value': '개인위생일지조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': '공조필터점검조치', 'Value': '공조필터점검조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                        { 'Code': '설정값재설정', 'Value': '설정값재설정',  },
                        { 'Code': '기기고장(수리)', 'Value': '기기고장(수리)', },
                        { 'Code': '확인시 이상없음', 'Value': '확인시 이상없음', },
                     ],
                },
                {
                    'Code': '공중낙하세균검사조치', 'Value': '공중낙하세균검사조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                        { 'Code': '조치사항1', 'Value': '조치사항1',  },
                        { 'Code': '조치사항2', 'Value': '조치사항2', },
                     ],
                },
                {
                    'Code': '방충방서개선조치항목', 'Value': '방충방서개선조치항목',
                    'Code_List' : [
                        { 'Code': '이탈사항 보완 조치', 'Value': '이탈사항 보완 조치', },
                        { 'Code': '청결유지', 'Value': '청결유지',  },
                     ],
                },
                {
                    'Code': '설비관리점검조치', 'Value': '설비관리점검조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                        { 'Code': '설정값재설정', 'Value': '설정값재설정',  },
                        { 'Code': '기기고장(수리)', 'Value': '기기고장(수리)', },
                        { 'Code': '확인시 이상없음', 'Value': '확인시 이상없음', },
                     ],
                },
                {
                    'Code': '에어컴프레샤조치', 'Value': '에어컴프레샤조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                        { 'Code': '조치사항1', 'Value': '조치사항1',  },
                        { 'Code': '조치사항2', 'Value': '조치사항2', },
                     ],
                },
                {
                    'Code': '온습도관리조치', 'Value': '온습도관리조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                        { 'Code': '설정값재설정', 'Value': '설정값재설정',  },
                        { 'Code': '기기고장(수리)', 'Value': '기기고장(수리)', },
                        { 'Code': '확인시 이상없음', 'Value': '확인시 이상없음', },
                     ],
                },
                {
                    'Code': '위생관리점검조치', 'Value': '위생관리점검조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                        { 'Code': '설정값재설정', 'Value': '설정값재설정',  },
                        { 'Code': '기기고장(수리)', 'Value': '기기고장(수리)', },
                        { 'Code': '확인시 이상없음', 'Value': '확인시 이상없음', },
                        { 'Code': '제품폐기', 'Value': '제품폐기', },
                     ],
                },
                {
                    'Code': '입출고및재고점검조치', 'Value': '입출고및재고점검조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                        { 'Code': '설정값재설정', 'Value': '설정값재설정',  },
                        { 'Code': '확인시 이상없음', 'Value': '확인시 이상없음', },
                     ],
                },
                {
                    'Code': '작업장주변환경점검조치', 'Value': '작업장주변환경점검조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': '저수조청소', 'Value': '저수조청소',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                        { 'Code': '설정값재설정', 'Value': '설정값재설정',  },
                        { 'Code': '기기고장(수리)', 'Value': '기기고장(수리)', },
                        { 'Code': '확인시 이상없음', 'Value': '확인시 이상없음', },
                     ],
                },
                {
                    'Code': '조도이탈사유', 'Value': '조도이탈사유',
                    'Code_List' : [
                        { 'Code': '조도기준이탈', 'Value': '조도기준이탈', },
                        { 'Code': '형광등 점멸', 'Value': '형광등 점멸',  },
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': '조도이탈조치', 'Value': '조도이탈조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': '층', 'Value': '층',
                    'Code_List' : [
                        { 'Code': '1층', 'Value': '1층', },
                        { 'Code': '2층', 'Value': '2층', },
                        { 'Code': '3층', 'Value': '3층', },
                        { 'Code': '4층', 'Value': '4층', },
                        { 'Code': '5층', 'Value': '5층', },
                        { 'Code': '지하', 'Value': '지하',  },
                        { 'Code': '옥상', 'Value': '옥상', },
                     ],
                },
                {
                    'Code': '표면오염도검사조치', 'Value': '표면오염도검사조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                        { 'Code': '조치내역1', 'Value': '조치내역1',  },
                        { 'Code': '조치내역2', 'Value': '조치내역2', },
                     ],
                },
                {
                    'Code': '현품처리', 'Value': '현품처리',
                    'Code_List' : [
                        { 'Code': '선별', 'Value': '선별', },
                        { 'Code': '그대로사용', 'Value': '그대로사용',  },
                     ],
                },
                {
                    'Code': 'judge_code', 'Value': '판정코드',
                    'Code_List' : [
                        { 'Code': 'pass', 'Value': '합격', },
                        { 'Code': 'fail', 'Value': '불합격',  },
                     ],
                },
                {
                    'Code': 'mat_manage_level', 'Value': '자재관리등급',
                    'Code_List' : [
                        { 'Code': 'A', 'Value': 'A', },
                        { 'Code': 'B', 'Value': 'B',  },
                        { 'Code': 'C', 'Value': 'C', },
                     ],
                },
                {
                    'Code': '용수검사조치', 'Value': '용수검사조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': '차량관리대장조치', 'Value': '차량관리대장조치',
                    'Code_List' : [
                        { 'Code': '직접입력', 'Value': '직접입력', },
                     ],
                },
                {
                    'Code': 'inter_exter_type', 'Value': '검교정구분',
                    'Code_List' : [
                        { 'Code': '사내', 'Value': '사내', },
                        { 'Code': '사외', 'Value': '사외',  },
                     ],
                },

            ]
            
            for code_grp in code_grp_list:
                GrpCode = code_grp['Code']
                q = UserCode.objects.filter(Code=GrpCode)
                #q = q.filter(Parent=None)
                q = q.filter(Parent_id__isnull=True)
                cg = q.first()
                if not cg:
                    cg = UserCode()
                    cg.Code = GrpCode
                cg.Value = code_grp['Value']
                
                # cg.Description = description
                cg.set_audit(user)
                cg.save()

                code_list = code_grp['Code_List']

                for index, item in enumerate(code_list, start=1):
                    Code = item['Code']
                    q = UserCode.objects.filter(Code=Code)
                    q = q.filter(Parent_id=cg.id)
                    uc = q.first()
                    if not uc:
                        uc = UserCode()
                        uc.Code = Code
                        uc.Parent_id = cg.id
                    uc.Value = item['Value']
                    #uc.Description = description
                    uc._order = index
                    uc.set_audit(user)
                    uc.save()

    except Exception as ex:
        source = 'definition/code_info : action-{}'.format(action)
        LogWriter.add_dblog('error', source , ex)
        raise ex

    return items
