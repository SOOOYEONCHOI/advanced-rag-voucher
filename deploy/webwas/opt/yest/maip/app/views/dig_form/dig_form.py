import datetime
import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max

from domain.gui import DIG_FORM_EDIT_MENU, DIG_FORM_TYPES, dig_form_menu_code
from domain.services import judge_code
from domain.gui import DIG_FORM_TYPES, dig_form_menu_code
from domain.services import dig_form_fields, judge_code
from domain.services import receipt as receipts
from domain.services.account import AccountService
from domain.services.dig_form_image import (CAPTURE_SESSION_KEY, CAPTURE_SESSION_MAX, CELL_ATTACH, CELL_TABLE,
                                            capture_image, find_cell_asset, find_cell_image, link_cell_image,
                                            rig_result_asset, rig_results, rig_summaries, save_upload, vision_links)
from domain.services.sql import DbUtil
from domain.models.data import InspectionItem
from domain.models.dig_form import DigForm, DigFormItem, DigFormResult, DigFormItemResult, DigFormSection
from domain.models.system import AttachFile
from domain.tenancy import current_tenant, tenant_atomic

# MES 계열 API 는 HTTP 메서드로 R/W 를 가른다. 쓰기 action 을 GET 으로 부르면 읽기 권한만으로 통과하므로 막는다.
# 칸 설정 저장(save_item)은 양식 구조를 바꾸므로 양식 편집 API(system/form_edit)에 있다.
WRITE_ACTIONS = frozenset({'save', 'complete', 'delete', 'upload_image', 'capture', 'use_rig_result'})


def require_write(user, form_types, kind='write'):
    """메뉴 W — 작성·완료·삭제는 양식 구분의 검사작성(write), 양식 편집·칸 설정은 구분과 상관없이 검사양식 관리(form).
    인가 훅은 매핑된 메뉴 아무 W 로 쓰기를 통과시키므로 여기서 좁힌다."""
    codes = [DIG_FORM_EDIT_MENU] if kind == 'form' else [dig_form_menu_code(t, kind) for t in form_types]
    if not any('W' in (AccountService.check_user_auth(user, code) or '') for code in codes):
        raise PermissionDenied   # ApiModuleView 가 403 으로 바꾼다


EXTRA_PREFIX = dig_form_fields.EXTRA_PREFIX   # 머리글 직접 입력 칸의 bind — 양식 편집기(form_edit.html FORM_EDIT_EXTRA_PREFIX)가 만든다
HEADER_VALUE_MAX = 200


HEADER_SECTION = 'HEADER'        # 머리글 섹션 — 섹션 Content 에 맨 위 머리글(FixedTopContent)과 같은 칸 목록 JSON


def header_keys(form):
    """양식 머리글(FixedTopContent)과 머리글 섹션의 입력 항목 키 — 작성건 HeaderValues 의 키가 된다.
    직접 입력은 <키>, 목록 항목(품목·품번 등)은 field.<키> 와 목록에서 고른 코드 field.<키>@code"""
    lists = [form.FixedTopContent] + list(DigFormSection.objects.filter(DigForm_id=form.id, SectionType=HEADER_SECTION)
                                          .values_list('Content', flat=True))
    keys = set()
    for content in lists:
        for c in json.loads(content or '[]'):
            bind = str(c.get('bind') or '')
            if not c.get('input'):
                continue
            if bind.startswith(EXTRA_PREFIX):
                keys.add(bind[len(EXTRA_PREFIX):])
            elif bind.startswith(dig_form_fields.FIELD_PREFIX):
                key = dig_form_fields.value_key(bind)
                keys.update((key, key + dig_form_fields.CODE_SUFFIX))
    return keys


def with_header_cells(sections, type_key):
    """머리글 섹션의 Content(JSON 문자열) → cells(칸 목록)."""
    for s in sections:
        if s[type_key] == HEADER_SECTION:
            s['cells'] = json.loads(s.pop('content') or '[]')
    return sections


def merge_header_values(form, saved, posted):
    """보낸 키만 바꾼다(빈 값은 지운다). 반환: (저장할 JSON 또는 None, 바뀐 키 수)."""
    values = json.loads(saved or '{}')
    if not isinstance(posted, dict):
        raise ValueError('머리글 입력값 형식이 올바르지 않습니다.')
    allowed = header_keys(form)
    changed = 0
    for key, value in posted.items():
        if key not in allowed:
            raise ValueError('양식에 없는 머리글 입력 항목입니다: {}'.format(key))
        value = '' if value is None else str(value).strip()
        if len(value) > HEADER_VALUE_MAX:
            raise ValueError('머리글 입력값은 {}자까지 넣을 수 있습니다.'.format(HEADER_VALUE_MAX))
        if values.get(key, '') == value:
            continue
        if value:
            values[key] = value
        else:
            values.pop(key, None)
        changed += 1
    return (json.dumps(values, ensure_ascii=False) if values else None), changed


def with_header_values(rows):
    """작성건 행의 header_values(JSON 문자열) → dict."""
    for row in rows:
        row['header_values'] = json.loads(row.get('header_values') or '{}')
    return rows


def working_result(user, result_id):
    """완료·삭제할 작성건 — 잠그고, 양식 구분의 작성 권한을 본다. 없으면 None."""
    form_result = DigFormResult.objects.select_for_update().select_related('DigForm').filter(id=result_id).first()
    if form_result is not None:
        require_write(user, [form_result.DigForm.FormType])
    return form_result


def rig_cell(item_id):
    """거치대 비전검사항목이 연결된 이미지 칸. 아니면 화면에 보일 오류 dict."""
    item_id = str(item_id or '')
    cell = DigFormItem.objects.select_related('DigFormSection__DigForm').filter(
        id=int(item_id), ResultType='I', InputYN='Y').exclude(VisionItem=None).first() if item_id.isdigit() else None
    if cell is None:
        return {'success': False, 'message': '비전검사항목이 연결된 이미지 칸이 아닙니다.'}
    with tenant_atomic():
        rig = InspectionItem.objects.for_tenant(current_tenant()).filter(
            pk=cell.VisionItem_id, capture_method=InspectionItem.CaptureMethod.RIG).exists()
    if not rig:
        return {'success': False, 'message': '거치대 비전검사항목이 연결된 칸이 아닙니다.'}
    return cell


def dig_form(context):
    '''
    /api/dig_form/dig_form
    디지털 양식 조회·작성(PoC) — 양식 정의와 작성 결과를 표로 그리기 위한 데이터, 신규 작성 저장
    '''
    items = []
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action', 'form_list')
    if action in WRITE_ACTIONS and context.request.method != 'POST':
        raise PermissionDenied   # ApiModuleView 가 403 으로 바꾼다

    try:
        if action == 'form_list':
            sql = '''
            select f.id
            , f."Code" as code
            , f."Version" as version
            , f."Title" as title
            , f."UseYN" as use_yn
            from dig_form f
            where 1=1
            '''
            # 구분(form_type)이 없으면 전부(양식 편집의 머리글 불러오기). 검사결과는 그 구분의 모든 버전(완료된 검사가 옛 버전에 달린다),
            # 검사작성의 새 작성은 latest_only=Y 로 사용 중인 최신 버전만
            form_type = gparam.get('form_type') or None
            if form_type:
                sql += ''' and f."FormType" = %(form_type)s '''
            if gparam.get('latest_only') == 'Y':
                sql += ''' and f."UseYN" = 'Y'
                and f."Version" = (select max(f2."Version") from dig_form f2 where f2."Code" = f."Code") '''
            sql += ''' order by f."Code", f."Version" desc '''
            items = DbUtil.get_rows(sql, {'form_type': form_type})

        elif action == 'judge_sets':
            # 판정 선택지 그룹 목록 [{code, name, options: [{code, value, meaning}]}]. 양식 편집기는 자기 API(system/form_edit)의 같은 action 을 쓴다
            items = judge_code.groups()

        elif action == 'header_lookup':
            # 머리글 목록 항목(품목·품번·입고번호) 검색 — 기준정보 메뉴 권한 없이 디지털 양식 메뉴 R 로 읽는다
            items = dig_form_fields.lookup(gparam.get('bind') or '', gparam.get('q'))

        elif action == 'wo_list':
            # WO 검색 팝업 — 임시 데이터 출처: 이미 작성된 작성건의 WO
            # (작업지시 엑셀 업로드 테이블이 생기면 이 쿼리만 그 테이블로 교체)
            dc = {
                'date_from': gparam.get('date_from'),
                'date_to': gparam.get('date_to'),
                'keyword': (gparam.get('keyword') or '').strip() or None,
            }
            sql = '''
            select r."WorkOrderNumber" as work_order_number
            , to_char(max(r."WriteDate"), 'yyyy-mm-dd') as last_write_date
            , count(*) as result_count
            , string_agg(distinct f."Title", ', ') as form_titles
            from dig_form_result r
            inner join dig_form f on f.id = r."DigForm_id"
            where coalesce(r."WorkOrderNumber", '') <> ''
            and r."WriteDate" between %(date_from)s and %(date_to)s
            '''
            if dc['keyword']:
                sql += ''' and r."WorkOrderNumber" ilike concat('%%', %(keyword)s, '%%')'''
            sql += ''' group by r."WorkOrderNumber" order by max(r."WriteDate") desc, r."WorkOrderNumber"'''
            items = DbUtil.get_rows(sql, dc)

        elif action == 'detail':
            form_id = gparam.get('form_id')
            dc = {'form_id': form_id}

            sql = '''
            select f.id
            , f."Code" as code
            , f."Version" as version
            , f."Title" as title
            , to_char(f."EstablishDate", 'yyyy-mm-dd') as establish_date
            , f."ApplyModel" as apply_model
            , f."UseYN" as use_yn
            , f."FixedTopContent" as fixed_top_content
            , f."LayoutType" as layout_type
            from dig_form f
            where f.id = %(form_id)s
            '''
            form = DbUtil.get_row(sql, dc)
            # 상단 영역 칸 목록(JSON) — 모양은 문서헤더, 값은 문서헤더(form.*)·문서헤더결과(result.*)·결재(appr.N)
            form['top_cells'] = json.loads(form.pop('fixed_top_content') or '[]')

            # 섹션 — 참고사진(PHOTO, 에디터 HTML)·점검항목(INSPECTION, 섹션마다 표 하나 — 머리줄행수·작업자 열은 섹션 설정)·머리글(HEADER, 칸 목록)
            sql = '''
            select s.id
            , s."SectionType" as section_type
            , s."Title" as title
            , s."Content" as content
            , s."SortOrder" as sort_order
            , s."Width" as width
            , s."ColumnCount" as column_count
            , s."HeaderRowCount" as header_row_count
            , s."WorkerColumnYN" as worker_column_yn
            from dig_form_section s
            where s."DigForm_id" = %(form_id)s
            order by s."SortOrder", s.id
            '''
            sections = with_header_cells(DbUtil.get_rows(sql, dc), 'section_type')

            # 칸 — 행 순번은 섹션마다 1부터
            sql = '''
            select i.id
            , i."DigFormSection_id" as section_id
            , i."RowIndex" as row_index
            , i."ColumnIndex" as column_index
            , i."RowType" as row_type
            , i."RowSpan" as row_span
            , i."ColSpan" as col_span
            , i."Content" as content
            , i."InputYN" as input_yn
            , i."ResultType" as result_type
            , i."CodeGroup" as code_group
            , i."LowerLimit" as lower_limit
            , i."UpperLimit" as upper_limit
            , i."MinColumnWidth" as min_column_width
            from dig_form_item i
            inner join dig_form_section s on s.id = i."DigFormSection_id"
            where s."DigForm_id" = %(form_id)s
            order by s."SortOrder", s.id, i."RowIndex", i."ColumnIndex"
            '''
            cells = DbUtil.get_rows(sql, dc)
            # 비전검사항목이 연결된 이미지 칸 — 사진 넣기 팝업(코드·이름·Overlay)과 `비전: <코드>` 표시
            links = vision_links([c['id'] for c in cells])
            for c in cells:
                c['vision_item'] = links.get(c['id'])

            # 판정 칸 선택지 (코드그룹별) — 항목결과 코드(사용자코드). meaning = 판정 의미 Y/N/X
            sql = judge_code.OPTION_SQL + '''
            where s."Code" in (
                select distinct i."CodeGroup" from dig_form_item i
                inner join dig_form_section ds on ds.id = i."DigFormSection_id"
                where ds."DigForm_id" = %(form_id)s and i."CodeGroup" is not null
            )
            order by s."Code", o._order, o.id
            '''
            codes = {}
            for row in DbUtil.get_rows(sql, dc):
                codes.setdefault(row['code_group'], []).append(
                    {'code': row['code'], 'value': row['value'], 'meaning': row['meaning']})
            items = {'form': form, 'sections': sections, 'cells': cells, 'codes': codes}

        elif action == 'result_list':
            form_id = gparam.get('form_id')
            sql = '''
            select r.id
            , to_char(r."WriteDate", 'yyyy-mm-dd') as write_date
            , r."WorkOrderNumber" as work_order_number
            from dig_form_result r
            where r."DigForm_id" = %(form_id)s
            order by r."WriteDate" desc, r.id desc
            '''
            items = DbUtil.get_rows(sql, {'form_id': form_id})

        elif action == 'job_list':
            # 수입검사 작성 목록 — 대기(매핑된 입고 × 양식) + 작성 중(설계 2026-10-21 §6)
            if gparam.get('form_type') != receipts.INCOMING:
                return {'success': False, 'message': '검사 작업 목록은 수입검사만 있습니다.'}
            items = receipts.jobs(gparam.get('keyword') or '', gparam.get('form_code') or '', gparam.get('kind') or '',
                                  user_id=context.request.user.id)

        elif action == 'job_count':
            # 좌측 메뉴 "수입검사 작성" 옆 검사 대기 배지
            counts = receipts.job_counts()
            items = {'count': counts['waiting'] + counts['working']}

        elif action == 'result_search':
            # 작성건 검색: 검사결과는 완료(state=done)를 작성일 기간·양식·WO로, 검사작성은 작성 중(state=working)을 기간 없이
            dc = {
                'date_from': gparam.get('date_from') or None,
                'date_to': gparam.get('date_to') or None,
                'form_id': gparam.get('form_id') or None,
                'work_order_number': gparam.get('work_order_number') or None,
                'form_type': gparam.get('form_type') or None,
                'state': gparam.get('state') or None,
                'user_id': context.request.user.id,
            }
            sql = '''
            select r.id
            , r."DigForm_id" as form_id
            , f."Code" as form_code
            , f."Version" as form_version
            , f."Title" as form_title
            , to_char(r."WriteDate", 'yyyy-mm-dd') as write_date
            , r."WorkOrderNumber" as work_order_number
            , r."Round" as round
            , r."State" as state
            , r."HeaderValues" as header_values
            , (select count(*) from dig_form_item_result ir where ir."DigFormResult_id" = r.id) as value_count
            , (select count(*) from dig_form_item i inner join dig_form_section s on s.id = i."DigFormSection_id"
               where s."DigForm_id" = r."DigForm_id" and i."InputYN" = 'Y') as input_count
            -- 삭제 버튼은 작성자에게만(서버 delete 도 확인한다)
            , (r._creater_id = %(user_id)s) as is_mine
            , up."Name" as creater_name
            -- 머리글 작성자(자동) — 마지막으로 저장(이어쓰기·완료 포함)한 사람
            , wp."Name" as writer_name
            , to_char(r._created, 'yyyy-mm-dd hh24:mi') as created
            from dig_form_result r
            inner join dig_form f on f.id = r."DigForm_id"
            left join user_profile up on up."User_id" = r._creater_id
            left join user_profile wp on wp."User_id" = coalesce(r._modifier_id, r._creater_id)
            where 1=1
            '''
            if dc['date_from'] and dc['date_to']:
                sql += ''' and r."WriteDate" between %(date_from)s and %(date_to)s'''
            if dc['form_type']:
                sql += ''' and f."FormType" = %(form_type)s'''
            if dc['state']:
                sql += ''' and r."State" = %(state)s'''
            if dc['form_id']:
                sql += ''' and r."DigForm_id" = %(form_id)s'''
            if dc['work_order_number']:
                sql += ''' and r."WorkOrderNumber" ilike concat('%%', %(work_order_number)s, '%%')'''
            sql += ''' order by r."WriteDate" desc, r.id desc'''
            items = with_header_values(DbUtil.get_rows(sql, dc))

        elif action == 'result_values':
            result_id = gparam.get('result_id')
            sql = '''
            select ir."DigFormItem_id" as item_id
            , i."DigFormSection_id" as section_id
            , i."RowIndex" as row_index
            , ir."TextResult" as text_result
            , ir."NumberResult" as number_result
            , ir."ComboResult" as combo_result
            , jo.value as combo_value
            , jo.meaning as combo_meaning
            , ir."CheckResultYN" as check_result_yn
            , up."Name" as worker_name
            from dig_form_item_result ir
            inner join dig_form_item i on i.id = ir."DigFormItem_id"
            left join (''' + judge_code.OPTION_SQL + ''') jo on jo.code_group = i."CodeGroup" and jo.code = ir."ComboResult"
            -- 작업자 = 수정자 있으면 수정자, 없으면 생성자 (피드백 F8·F13, D25)
            left join user_profile up on up."User_id" = coalesce(ir._modifier_id, ir._creater_id)
            where ir."DigFormResult_id" = %(result_id)s
            -- 저장한 순서 — 화면의 행 작업자는 그 행에서 가장 나중에 저장한 사람이다(렌더러가 행마다 마지막 값을 쓴다)
            order by coalesce(ir._modified, ir._created), ir.id
            '''
            items = DbUtil.get_rows(sql, {'result_id': result_id})
            # 비전 연결 칸의 값이 거치대 검사 이미지면 그 판정을 붙인다(설계 2026-10-21 §7)
            linked = set(DigFormItem.objects.filter(id__in=[r['item_id'] for r in items]).exclude(VisionItem=None)
                         .values_list('id', flat=True))
            values = {r['item_id']: int(r['text_result']) for r in items
                      if r['item_id'] in linked and str(r['text_result'] or '').isdigit()}
            summaries = rig_summaries(values.values())
            for row in items:
                row['vision_result'] = summaries.get(values.get(row['item_id']))

        elif action == 'find_result':
            # 이어쓰기: 같은 양식(버전)에서 같은 WO로 작성 중인 작성건 — 최신 차수. 완료된 건은 이어 쓰지 않는다
            sql = '''
            select r.id
            , to_char(r."WriteDate", 'yyyy-mm-dd') as write_date
            , r."WorkOrderNumber" as work_order_number
            , r."Round" as round
            , r."State" as state
            , r."HeaderValues" as header_values
            , (r._creater_id = %(user_id)s) as is_mine
            , wp."Name" as writer_name
            from dig_form_result r
            left join user_profile wp on wp."User_id" = coalesce(r._modifier_id, r._creater_id)
            where r."DigForm_id" = %(form_id)s
            and r."WorkOrderNumber" = %(work_order_number)s
            and r."State" = 'working'
            order by r."Round" desc, r.id desc
            limit 1
            '''
            items = DbUtil.get_row(sql, {'form_id': gparam.get('form_id'), 'work_order_number': (gparam.get('work_order_number') or '').strip(),
                                         'user_id': context.request.user.id})
            if items:
                with_header_values([items])

        elif action == 'upload_image':
            # 이미지 칸(ResultType='I') 사진 — 연결되지 않은 첨부(DataPk=0)로 저장하고 save 때 칸 결과에 연결한다
            # 어느 양식에 붙을지 아직 모르므로 두 검사작성 메뉴 중 하나의 W
            require_write(context.request.user, DIG_FORM_TYPES)
            items = save_upload(context.request.FILES.get('uploadfile'), context.request.user, CELL_TABLE, CELL_ATTACH)

        elif action == 'capture':
            # 비전검사항목이 연결된 이미지 칸의 사진 — 넣는 즉시 그 항목의 비전 데이터 이미지가 된다. 항목은 요청이 아니라 칸에서 정한다
            # item_id 가 숫자가 아니면 filter 가 ValueError 원문을 던지므로 먼저 거른다
            user = context.request.user
            item_id = str(posparam.get('item_id') or '')
            cell = DigFormItem.objects.select_related('DigFormSection__DigForm').filter(
                id=int(item_id), ResultType='I', InputYN='Y').exclude(VisionItem=None).first() if item_id.isdigit() else None
            if cell is None:
                return {'success': False, 'message': '비전검사항목이 연결된 이미지 칸이 아닙니다.'}
            require_write(user, [cell.DigFormSection.DigForm.FormType])
            asset_id = capture_image(cell.VisionItem_id, context.request.FILES.get('uploadfile'), user)
            session = context.request.session
            session[CAPTURE_SESSION_KEY] = (session.get(CAPTURE_SESSION_KEY, []) + [asset_id])[-CAPTURE_SESSION_MAX:]
            items = {'success': True, 'message': '', 'asset_id': asset_id}

        elif action in ('rig_results', 'use_rig_result'):
            # 거치대 결과 불러오기 — 거치대 비전검사항목 칸에 그 항목의 최근 검사 결과(이미지)를 고른다(설계 2026-10-21 §7).
            # 고른 이미지는 capture 처럼 세션 목록에 넣는다 — 저장 검증(find_cell_asset)·사진 제공이 그대로 받는다
            cell = rig_cell(posparam.get('item_id') or gparam.get('item_id'))
            if isinstance(cell, dict):
                return cell
            if action == 'rig_results':
                items = {'rows': rig_results(cell.VisionItem_id)}
            else:
                require_write(context.request.user, [cell.DigFormSection.DigForm.FormType])
                asset_id = rig_result_asset(cell.VisionItem_id, posparam.get('inspection_id'))
                session = context.request.session
                session[CAPTURE_SESSION_KEY] = (session.get(CAPTURE_SESSION_KEY, []) + [asset_id])[-CAPTURE_SESSION_MAX:]
                items = {'success': True, 'message': '', 'asset_id': asset_id}

        elif action == 'save':
            # 저장 — result_id 없으면 새 작성건, 있으면 그 작성건에 이어쓰기(빈 칸 추가·바뀐 칸 수정, 그대로인 칸은 건드리지 않음)
            # 작업자 = 칸을 마지막으로 저장한 사람(_modifier_id, set_audit) — 바뀐 칸만 저장해야 다른 작업자 칸이 덮어써지지 않음
            # 작성일은 입력받지 않는다 — 새 작성건을 만든 날(서버 오늘)이고 이어쓰기에서 바꾸지 않는다(사용자 결정 2026-10-20)
            user = context.request.user
            form_id = posparam.get('form_id')
            result_id = posparam.get('result_id') or None
            work_order_number = (posparam.get('work_order_number') or '').strip() or None
            values = posparam.get('Q') or []
            # 머리글 입력 항목 {키: 값}(JSON 문자열) — 바뀐 키만 온다(빈 값 = 지움)
            try:
                header_values = json.loads(posparam.get('header_values') or '{}')
            except ValueError:
                return {'success': False, 'message': '머리글 입력값 형식이 올바르지 않습니다.'}

            form = DigForm.objects.filter(id=form_id).first()
            if form is None:
                return {'success': False, 'message': '양식을 찾을 수 없습니다.'}
            require_write(user, [form.FormType])

            # 입력칸만, 같은 양식 소속만 허용 (R1·R2)
            input_items = {i.id: i for i in DigFormItem.objects.filter(DigFormSection__DigForm_id=form.id, InputYN='Y')}

            with transaction.atomic():
                if result_id:
                    form_result = DigFormResult.objects.filter(id=result_id, DigForm_id=form.id).first()
                    if form_result is None:
                        return {'success': False, 'message': '작성건을 찾을 수 없습니다.'}
                    if form_result.State == 'done':
                        return {'success': False, 'message': '완료된 검사는 고칠 수 없습니다.'}
                else:
                    # WO가 있으면 같은 양식·WO의 작성 중인 건은 하나(이어쓰기) — 새로 만들지 않고 불러오도록 안내
                    # 완료된 건만 있으면 새 검사를 쓰고 차수를 올린다(사용자 결정 2026-10-16)
                    # 검사 작업은 양식 코드 단위다 — 옛 버전으로 작성 중이어도 같은 작업이다(설계 2026-10-21 §6)
                    same_wo = DigFormResult.objects.filter(DigForm__Code=form.Code, WorkOrderNumber=work_order_number) if work_order_number else None
                    if same_wo is not None and same_wo.filter(State='working').exists():
                        return {'success': False, 'message': 'WO {}로 작성 중인 검사가 있습니다.\n작성 중 목록에서 불러와 이어 써 주세요.'.format(work_order_number)}
                    form_result = DigFormResult()
                    form_result.DigForm = form
                    form_result.WriteDate = datetime.date.today()
                    form_result.WorkOrderNumber = work_order_number
                    form_result.Round = ((same_wo.aggregate(n=Max('Round'))['n'] if same_wo is not None else None) or 0) + 1
                form_result.HeaderValues, changed = merge_header_values(form, form_result.HeaderValues, header_values)
                form_result.set_audit(user)
                form_result.save()

                saved = {ir.DigFormItem_id: ir for ir in DigFormItemResult.objects.filter(DigFormResult_id=form_result.id)}
                for v in values:
                    item = input_items.get(int(v.get('item_id')))
                    if item is None:
                        raise ValueError('양식에 없는 입력칸입니다: {}'.format(v.get('item_id')))
                    value = v.get('value')
                    value = None if value is None or str(value).strip() == '' else str(value).strip()
                    item_result = saved.get(item.id)
                    if item_result is None:
                        if value is None:
                            continue
                        item_result = DigFormItemResult()
                        item_result.DigFormResult = form_result
                        item_result.DigFormItem = item
                    # 칸 유형별 값 — 비우면 값만 지움(행은 유지)
                    text = number = combo = check = None
                    image = None
                    if value is not None:
                        if item.ResultType == 'I' and item.VisionItem_id:
                            # 비전검사항목이 연결된 칸 — 값은 ImageAsset id. 이번 세션에 올렸거나 이미 저장된 그 항목의 이미지만
                            text = str(find_cell_asset(value, item.VisionItem_id, item_result.TextResult if item_result.id else None,
                                                       set(context.request.session.get(CAPTURE_SESSION_KEY, []))))
                        elif item.ResultType == 'I':
                            # 이미지 칸 — 값은 첨부 id. 저장 뒤 칸 결과에 연결한다
                            image = find_cell_image(value, item_result.id, user)
                            text = str(image.id)
                        elif item.ResultType == 'N':
                            try:
                                number = Decimal(value)
                            except InvalidOperation:
                                raise ValueError('숫자 칸에 숫자가 아닌 값이 있습니다: {}'.format(value))
                        elif item.ResultType == 'S':
                            combo = value
                        elif item.ResultType == 'B':
                            check = value
                        else:
                            text = value
                    if item_result.id and (item_result.TextResult, item_result.NumberResult, item_result.ComboResult, item_result.CheckResultYN) == (text, number, combo, check):
                        continue
                    item_result.TextResult, item_result.NumberResult, item_result.ComboResult, item_result.CheckResultYN = text, number, combo, check
                    item_result.set_audit(user)
                    item_result.save()
                    if item.ResultType == 'I' and not item.VisionItem_id:
                        link_cell_image(image, item_result.id, user)
                    changed += 1

            items = {'success': True, 'message': '', 'result_id': form_result.id, 'changed': changed, 'round': form_result.Round,
                     'write_date': str(form_result.WriteDate), 'writer_name': user.userprofile.Name,
                     'header_values': json.loads(form_result.HeaderValues or '{}')}

        elif action == 'complete':
            # 완료 — 되돌리지 않는다(사용자 결정 2026-10-16). 빈 칸이 있어도 완료한다
            with transaction.atomic():
                form_result = working_result(context.request.user, posparam.get('result_id'))
                if form_result is None:
                    return {'success': False, 'message': '검사를 찾을 수 없습니다.'}
                if form_result.State == 'done':
                    return {'success': False, 'message': '이미 완료된 검사입니다.'}
                form_result.State = 'done'
                form_result.set_audit(context.request.user)
                form_result.save()
            items = {'success': True, 'message': ''}

        elif action == 'delete':
            # 작성 중인 검사만, 작성한 사람만 지운다. 이미지 칸 첨부 행도 지우고 파일은 남긴다(link_cell_image 와 같은 규칙)
            with transaction.atomic():
                form_result = working_result(context.request.user, posparam.get('result_id'))
                if form_result is None:
                    return {'success': False, 'message': '검사를 찾을 수 없습니다.'}
                if form_result.State != 'working':
                    return {'success': False, 'message': '작성 중인 검사만 지울 수 있습니다.'}
                if form_result._creater_id != context.request.user.id:
                    return {'success': False, 'message': '작성한 사람만 지울 수 있습니다.'}
                item_results = DigFormItemResult.objects.filter(DigFormResult=form_result)
                AttachFile.objects.filter(TableName=CELL_TABLE, AttachName=CELL_ATTACH,
                                          DataPk__in=list(item_results.values_list('id', flat=True))).delete()
                item_results.delete()
                form_result.delete()
            items = {'success': True, 'message': ''}

    except ValueError as ex:
        # 사용자 문구는 ValueError 로 던진다. 그 밖의 예외는 ApiModuleView 가 로그를 남기고 500 일반 문구로 답한다.
        return {'success': False, 'message': str(ex)}

    return items
