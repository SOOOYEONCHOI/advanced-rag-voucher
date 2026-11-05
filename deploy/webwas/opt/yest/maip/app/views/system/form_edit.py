import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction

from app.views.dig_form.dig_form import HEADER_SECTION, require_write, with_header_cells
from domain.gui import DIG_FORM_TYPE_LABELS, DIG_FORM_TYPES
from domain.services import dig_form_fields, judge_code
from domain.services.dig_form_image import (REF_ATTACH, REF_TABLE, check_ref_images, link_ref_images, save_upload,
                                            sync_editor_images, unlink_ref_images)
from domain.services.sql import DbUtil
from domain.models.data import InspectionCategory, InspectionItem
from domain.services.data.category import label_of
from domain.tenancy import current_tenant, tenant_atomic
from domain.models.dig_form import DigForm, DigFormSection, DigFormItem, DigFormResult

# MES 계열 API 는 HTTP 메서드로 R/W 를 가른다. 쓰기 action 을 GET 으로 부르면 읽기 권한만으로 통과하므로 막는다.
WRITE_ACTIONS = frozenset({'save', 'save_item', 'upload_image', 'delete'})

# 양식 편집으로 만든 양식(LayoutType=SECTION)의 점검항목은 기존 칸 구조(dig_form_item)로 저장한다
# 점검항목 세션마다 열 구성(열 제목·상위 머리줄·종류·폭)을 자유롭게 정한다 — 기존 양식 DF0001·DF0008·DF0009 참고
#   점검항목 섹션마다 표 하나 — 행 순번은 섹션마다 1부터, 표 설정(컬럼개수·머리줄행수·작업자표시여부)은 섹션마스터
#   섹션의 머리줄: RowType='H' 칸. 1~3행 — 상위 머리줄 행 + 중간 머리줄 행(있을 때만, 같은 값 연속 열 가로 병합) + 열 제목
#     묶음이 없는 열의 제목은 아래 머리줄까지 세로 병합
#     열 제목 칸(맨 아래 머리줄 칸)의 ResultType·CodeGroup = 그 열의 종류 표시 (입력칸 아님, InputYN='N')
#     글자 NULL · 입력 T · 판정 S(+코드그룹) · 체크 B · 이미지 I / 섹션 작업자표시여부=Y면 마지막 열은 작업자(렌더러가 본문 행에 자동 표시)
#   섹션의 본문: RowType='D' 칸. 글자 열은 "같은 값 병합"이면 연속 같은 값을 세로 병합(왼쪽 병합 열 묶음 안에서)
#     입력 열은 행마다 문자(T)/숫자(N, 하한·상한 → 같은 행 OK/NG 판정 자동) · 판정 열은 S · 체크 열은 B 입력칸
#     이미지 열은 I 입력칸 — 작성 시 행마다 사진 1장(domain/services/dig_form_image.py). 나중에 AI 가 사진을 읽어 같은 행 값을 채운다
#     행마다 지정 열(열 제목 칸 ResultType='M')은 칸마다 종류를 고른다 — 글자·입력·판정(칸마다 선택지 그룹)·체크·이미지·고정 이미지·비움.
#       입력·판정·체크·이미지 칸의 Content 는 앞뒤 글자(예: "부적합 건수 : {} EA" — {} 자리에 입력칸), 비움은 빈 글자 칸. 같은 값 병합은 없다.
#       고정 이미지 칸은 고정 이미지 열의 칸과 같고, [위 칸과 병합]은 바로 위 칸도 고정 이미지일 때만 된다
#     고정 이미지 열(ResultType='R')은 양식에 박아 두는 그림 — 입력칸이 아니고(InputYN='N') Content = 그림 첨부 id(비면 빈 칸).
#       편집기의 [위 칸과 병합]으로 묶은 행은 칸 하나(RowSpan)로 저장한다 — 아래 행에는 칸이 없다(글자 열 같은 값 병합과 같은 구조).
#       첨부는 dig_form_item/ref (domain/services/dig_form_image.py). 그림을 바꾸면 칸이 바뀌어 새 버전이다
#   섹션 이미지: 표 밖 칸 하나(RowType='S', 행 0·열 0, I 입력칸). 있으면 켜진 것 — 작성 시 섹션 제목 옆에 사진 1장,
#     나중에 AI 가 사진을 읽어 섹션 표 전체를 채운다. 행 순번 0 은 이 칸만 쓴다(본문·머리줄은 1부터)
SECTION_IMAGE_ROW = 0
COLUMN_KINDS = {'TEXT': None, 'INPUT': 'T', 'JUDGE': 'S', 'CHECK': 'B', 'IMAGE': 'I', 'MIXED': 'M', 'REF_IMAGE': 'R'}
MARKER_KINDS = {None: 'TEXT', 'T': 'INPUT', 'S': 'JUDGE', 'B': 'CHECK', 'I': 'IMAGE', 'M': 'MIXED', 'R': 'REF_IMAGE'}
# 행마다 지정 열의 칸 종류 — EMPTY(비움)는 빈 글자 칸으로 저장한다
CELL_KINDS = ('TEXT', 'INPUT', 'JUDGE', 'CHECK', 'IMAGE', 'REF_IMAGE', 'EMPTY')
# 입력 칸 종류 — 칸 하나를 input_cell 로 만들고 input_value 로 읽는다
INPUT_KINDS = ('INPUT', 'JUDGE', 'CHECK', 'IMAGE')
# 글자 열의 "같은 값 병합" 설정 — 열 제목 칸 CodeGroup에 표시 (본문에 실제 병합 칸이 없어도 설정이 복원되도록)
MERGE_MARKER = 'dig_form_merge'
WORKER_COLUMN = {'title': '작업자', 'kind': 'WORKER', 'width': 80}
MAX_COLUMNS = 30
SECTION_TYPES = ('PHOTO', 'INSPECTION', HEADER_SECTION)
# 머리글 칸의 작성 입력 — 작성일·작성자는 입력받지 않는다(작성일은 서버가 새 작성건을 만든 날, 사용자 결정 2026-10-20). 항목 목록이 정한다
AUTO_BINDS = dig_form_fields.AUTO_BINDS
WORK_ORDER_BIND = dig_form_fields.WORK_ORDER_BIND
# 양식명(제목) 칸 — 칸의 text 가 있으면 머리글에 그 글자, 없으면 양식명(Title)을 보인다. 길이는 양식명과 같다
TITLE_BIND = 'form.Title'
TITLE_TEXT_MAX = 200


def form_edit(context):
    '''
    /api/system/form_edit
    양식 편집 — 양식 목록, 상세(기본정보·머리글·섹션·점검항목), 저장·삭제
    점검항목이 바뀌면 같은 코드로 새 버전을 추가하고 원래 버전은 그대로 둔다 (사용자 결정 2026-10-16)
    다른 양식 복사는 등록 팝업이 그 양식의 머리글·섹션을 불러와(섹션 id 없이) 새 양식으로 저장하는 것이다 — 서버에 따로 복사 action 은 없다
    '''
    items = []
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action', 'read')
    if action in WRITE_ACTIONS and context.request.method != 'POST':
        raise PermissionDenied   # ApiModuleView 가 403 으로 바꾼다

    try:
        if action == 'read':
            dc = {
                'keyword': gparam.get('keyword') or None,
                'use_yn': gparam.get('use_yn') or None,
                'form_type': gparam.get('form_type') or None,
                'layout_type': gparam.get('layout_type') or None,
            }
            sql = '''
            select f.id
            , f."FormType" as form_type
            , f."Code" as code
            , f."Title" as title
            , f."Version" as version
            , f."LayoutType" as layout_type
            , f."ApplyModel" as apply_model
            , to_char(f."EstablishDate", 'yyyy-mm-dd') as establish_date
            , to_char(f."StartDate", 'yyyy-mm-dd') as start_date
            , to_char(f."EndDate", 'yyyy-mm-dd') as end_date
            , (select count(distinct (i."DigFormSection_id", i."RowIndex")) from dig_form_item i
               inner join dig_form_section s on s.id = i."DigFormSection_id"
               where s."DigForm_id" = f.id and i."InputYN" = 'Y' and i."RowIndex" <> 0) as item_count
            , (select count(*) from dig_form_result r where r."DigForm_id" = f.id) as result_count
            , f."UseYN" as use_yn
            , f."Description" as description
            , up."Name" as modifier
            , to_char(coalesce(f._modified, f._created), 'yyyy-mm-dd hh24:mi') as modified
            from dig_form f
            left join user_profile up on up."User_id" = coalesce(f._modifier_id, f._creater_id)
            where 1=1
            '''
            if dc['keyword']:
                sql += '''
                and (upper(f."Code") like concat('%%', upper(%(keyword)s), '%%')
                    or upper(f."Title") like concat('%%', upper(%(keyword)s), '%%'))
                '''
            if dc['use_yn']:
                sql += ''' and f."UseYN" = %(use_yn)s '''
            if dc['form_type']:
                sql += ''' and f."FormType" = %(form_type)s '''
            if dc['layout_type']:
                # 불러오기 팝업은 양식 편집으로 만든 양식(SECTION)만 고른다
                sql += ''' and f."LayoutType" = %(layout_type)s '''
            if gparam.get('latest_only') == 'Y':
                sql += ''' and f."Version" = (select max(f2."Version") from dig_form f2 where f2."Code" = f."Code") '''
            sql += ''' order by f."Code", f."Version" desc '''
            items = DbUtil.get_rows(sql, dc)
            # 검사양식 관리는 수입·품질 양식을 한 목록에 보인다(사용자 결정 2026-10-21)
            for row in items:
                row['form_type_label'] = DIG_FORM_TYPE_LABELS.get(row['form_type'], row['form_type'])

        elif action == 'detail':
            items = get_detail(gparam.get('id'))

        elif action == 'save':
            items = save_form(posparam.get('Q') or {}, context.request.user)

        elif action == 'delete':
            items = delete_form(posparam.get('id'), context.request.user)

        elif action == 'vision_items':
            # 이미지 열 행에 연결할 비전검사항목 — 편집기는 사용(ACTIVE) 항목만 새로 고르게 하고, 이미 연결된 중지 항목은 그대로 보인다.
            # 치수 측정 항목도 연결한다 — 작성 때 거치대 결과 불러오기로만 넣는다(설계 2026-10-21 §7, 2026-10-20 Q5 를 바꿈)
            # 검사 분류(대분류 › 중분류) 순서로 주고, 이 양식 코드에 매핑된 중분류를 함께 알린다(설계 2026-10-21 §5)
            items = vision_items(gparam.get('form_code') or '')

        elif action == 'judge_sets':
            # 판정 열에서 고를 선택지 그룹 — 항목결과 코드(사용자코드). 편집기를 열 때 한 번 읽어 둔다
            items = judge_code.groups()

        elif action == 'header_fields':
            # 머리글 "값" 선택지 — 그 양식 구분에서 쓰는 항목(domain/services/dig_form_fields.py). 편집기를 열 때 한 번 읽어 둔다
            items = dig_form_fields.fields_for(gparam.get('form_type') or '')

        elif action == 'upload_image':
            # 참고사진 에디터 이미지 — 연결되지 않은 첨부(DataPk=0)로 저장하고 save 때 섹션에 연결한다
            # target=ref 는 고정 이미지 칸 그림 — save 때 칸에 연결한다(link_ref_images)
            # 검사양식 관리의 W(구분과 상관없다)
            require_write(context.request.user, DIG_FORM_TYPES, 'form')
            uploaded = context.request.FILES.get('uploadfile')
            if gparam.get('target') == 'ref':
                items = save_upload(uploaded, context.request.user, table=REF_TABLE, attach_name=REF_ATTACH)
            else:
                items = save_upload(uploaded, context.request.user)

        # 디지털 양식 조회 화면의 입력칸 설정 — 팀원 MES 에서는 작성·조회 API(dig_form/dig_form)에 있었다
        elif action == 'save_item':
            # 입력칸 설정 — 본문 칸의 입력 여부·입력 방식·허용 범위 변경
            # 작성 결과가 있는 칸 단위 양식은 같은 코드의 새 버전으로 복사해 거기서 바꾼다 — 옛 버전과 완료된 결과의 입력 방식은 그대로(사용자 결정 2026-10-19)
            user = context.request.user
            item = DigFormItem.objects.select_related('DigFormSection__DigForm').filter(id=posparam.get('item_id')).first()
            if item is None:
                return {'success': False, 'message': '칸을 찾을 수 없습니다.'}
            form = item.DigFormSection.DigForm
            require_write(user, [form.FormType], 'form')
            revised = DigFormResult.objects.filter(DigForm_id=form.id).exists()
            if revised and form.LayoutType != 'GRID':
                return {'success': False, 'message': '작성된 결과가 있는 양식은 입력칸을 바꿀 수 없습니다.'}
            if item.RowIndex <= item.DigFormSection.HeaderRowCount or (item.InputYN != 'Y' and item.Content):
                return {'success': False, 'message': '머리줄이나 글자가 있는 칸은 입력칸으로 바꿀 수 없습니다.'}

            # 값이 틀리면 ValueError — 새 버전 복사까지 되돌린다
            with transaction.atomic():
                if revised:
                    form, copied = copy_new_version(form, user)
                    item = copied[item.id]
                if posparam.get('input_yn') == 'Y':
                    result_type = posparam.get('result_type')
                    if result_type not in ('N', 'T', 'S'):
                        raise ValueError('입력 방식을 선택하세요.')
                    # 판정은 항목결과 코드(dig_form_judge_code) 아래의 선택지 그룹 하나를 고른다
                    code_group = (posparam.get('code_group') or '').strip() or None
                    if result_type != 'S':
                        code_group = None
                    elif code_group not in judge_code.group_codes():
                        raise ValueError('판정 선택지를 골라 주세요.')
                    lower = posparam.get('lower_limit') or None
                    upper = posparam.get('upper_limit') or None
                    if result_type != 'N':
                        lower = upper = None
                    elif lower is not None and upper is not None and float(lower) > float(upper):
                        raise ValueError('하한값이 상한값보다 큽니다.')

                    # 같은 행 입력칸의 작업마스터 분류를 따름 (통계용, D11)
                    sibling = DigFormItem.objects.filter(DigFormSection_id=item.DigFormSection_id, RowIndex=item.RowIndex, InputYN='Y') \
                        .exclude(id=item.id).exclude(DigFormWorkClass=None).first()
                    item.RowType = 'D'
                    item.InputYN = 'Y'
                    item.ResultType = result_type
                    item.CodeGroup = code_group
                    item.LowerLimit = lower
                    item.UpperLimit = upper
                    item.DigFormWorkClass_id = sibling.DigFormWorkClass_id if sibling else item.DigFormWorkClass_id
                else:
                    item.RowType = 'H'
                    item.InputYN = 'N'
                    item.ResultType = None
                    item.CodeGroup = None
                    item.LowerLimit = None
                    item.UpperLimit = None
                    item.DigFormWorkClass = None
                item.set_audit(user)
                item.save()

            items = {'success': True, 'message': '', 'revised': revised, 'id': form.id, 'version': form.Version, 'item_id': item.id}


    except ValueError as ex:
        # 사용자 문구는 ValueError 로 던진다. 그 밖의 예외는 ApiModuleView 가 로그를 남기고 500 일반 문구로 답한다.
        return {'success': False, 'message': str(ex)}

    return items


def vision_items(form_code):
    """{items: [{id, code, name, task_type, status, status_display, category_id, group}], mapped: {id, label} | None}.

    항목 순서는 대분류 순서 › 중분류 순서 › 표시 순서 › 코드, 소속이 없는 항목(미분류)은 끝이다.
    """
    with tenant_atomic():
        tenant = current_tenant()
        categories = {c.id: c for c in InspectionCategory.objects.for_tenant(tenant).select_related('parent')}
        rows = list(InspectionItem.objects.for_tenant(tenant))

    def minor_of(item):
        category = categories.get(item.category_id)
        return category if category is not None and category.parent_id else None

    def order(item):
        minor = minor_of(item)
        if minor is None:
            return (1, 0, '', 0, '', item.display_order, item.code)
        return (0, minor.parent.sort_order, minor.parent.name, minor.sort_order, minor.name, item.display_order, item.code)

    mapped = next((c for c in categories.values() if c.parent_id and form_code and c.form_code == form_code), None)
    return {
        'items': [{'id': i.id, 'code': i.code, 'name': i.name, 'task_type': i.get_task_type_display(),
                   'status': i.status, 'status_display': i.get_status_display(),
                   'category_id': minor_of(i).id if minor_of(i) else None, 'group': label_of(minor_of(i))}
                  for i in sorted(rows, key=order)],
        'mapped': {'id': mapped.id, 'label': label_of(mapped)} if mapped else None,
    }


def get_detail(form_id):
    dc = {'form_id': form_id}
    sql = '''
    select f.id
    , f."FormType" as form_type
    , f."Code" as code
    , f."Title" as title
    , f."Version" as version
    , f."LayoutType" as layout_type
    , f."ApplyModel" as apply_model
    , f."UseYN" as use_yn
    , to_char(f."EstablishDate", 'yyyy-mm-dd') as establish_date
    , to_char(f."StartDate", 'yyyy-mm-dd') as start_date
    , to_char(f."EndDate", 'yyyy-mm-dd') as end_date
    , f."Description" as description
    , f."FixedTopContent" as fixed_top_content
    , (select count(*) from dig_form_result r where r."DigForm_id" = f.id) as result_count
    from dig_form f
    where f.id = %(form_id)s
    '''
    form = DbUtil.get_row(sql, dc)
    if not form:
        return {'success': False, 'message': '양식을 찾을 수 없습니다.'}
    form['top_cells'] = json.loads(form.pop('fixed_top_content') or '[]')

    sql = '''
    select s.id
    , s."SectionType" as type
    , s."Title" as title
    , s."Content" as content
    , s."Width" as width
    , s."Height" as height
    , s."HeaderRowCount" as header_row_count
    , s."WorkerColumnYN" as worker_column_yn
    from dig_form_section s
    where s."DigForm_id" = %(form_id)s
    order by s."SortOrder", s.id
    '''
    sections = with_header_cells(DbUtil.get_rows(sql, dc), 'type')

    rows = {}
    for item in DigFormItem.objects.filter(DigFormSection__DigForm_id=form_id).order_by('RowIndex', 'ColumnIndex'):
        rows.setdefault(item.DigFormSection_id, {}).setdefault(item.RowIndex, {})[item.ColumnIndex] = item
    for s in sections:
        if s['type'] == 'INSPECTION':
            section_rows = rows.get(s['id'], {})
            s['section_image_yn'] = 'Y' if section_rows.pop(SECTION_IMAGE_ROW, None) else 'N'
            s['columns'], s['rows'] = parse_inspection(section_rows, s['header_row_count'], s['worker_column_yn'] == 'Y')
    form['sections'] = sections
    return form


def parse_inspection(section_rows, header_rows, worker):
    '''섹션의 칸 → (열 구성, 행 값 목록). 1~머리줄행수 행이 머리줄, 세로 병합된 글자 칸은 아래 행이 위 값을 이어받는다'''
    ordered = sorted(section_rows.items())
    header = [(r, cells) for r, cells in ordered if r <= header_rows]
    body = [(r, cells) for r, cells in ordered if r > header_rows]
    if not header:
        return [], []
    top, last = header[0][0], header[-1][0]

    # 맨 아래 머리줄까지 내려오는 1칸짜리 = 열 제목, 나머지 = 묶음 머리줄 (위에서 첫 줄 = 상위, 둘째 줄 = 중간)
    leaves, groups = {}, {}
    for row_index, cells in header:
        for col, c in cells.items():
            if c.ColSpan == 1 and row_index + c.RowSpan - 1 == last:
                leaves[col] = c
            else:
                for k in range(col, col + c.ColSpan):
                    groups.setdefault(k, {})[row_index - top] = c.Content or ''
    cols = sorted(leaves)
    if worker:
        cols = cols[:-1]  # 마지막 열 = 작업자

    columns = []
    for col in cols:
        c = leaves[col]
        kind = MARKER_KINDS.get(c.ResultType, 'TEXT')
        # 표시가 없는 이전 저장분은 실제 병합된 칸이 있는지로 판단
        merge = kind == 'TEXT' and (c.CodeGroup == MERGE_MARKER
                                    or any(cells.get(col) is not None and cells[col].RowSpan > 1 for _, cells in body))
        path = groups.get(col, {})
        columns.append({
            'title': c.Content or '', 'group': path.get(0, ''), 'sub': path.get(1, ''), 'kind': kind,
            'code_group': c.CodeGroup if kind == 'JUDGE' else '', 'merge': merge, 'width': c.MinColumnWidth,
        })

    values, active = [], {}
    for row_index, cells in body:
        row = []
        for col, column in zip(cols, columns):
            c = cells.get(col)
            if column['kind'] == 'TEXT':
                if c is not None:
                    active[col] = (c.Content or '', row_index + c.RowSpan - 1)
                    row.append(c.Content or '')
                else:
                    a = active.get(col)
                    row.append(a[0] if a and a[1] >= row_index else '')
            elif column['kind'] == 'INPUT':
                row.append(input_value(c, 'INPUT'))
            elif column['kind'] == 'IMAGE':
                row.append(input_value(c, 'IMAGE') if c is not None and c.VisionItem_id else None)
            elif column['kind'] == 'MIXED':
                # 칸이 없는 행 = 위 고정 이미지 칸에 병합된 행
                if c is not None:
                    active[col] = (None, row_index + c.RowSpan - 1)
                    row.append(mixed_value(c))
                else:
                    a = active.get(col)
                    row.append({'kind': 'REF_IMAGE', 'merge': True} if a and a[1] >= row_index else mixed_value(None))
            elif column['kind'] == 'REF_IMAGE':
                # 칸이 없는 행 = 위 칸에 병합된 행
                if c is not None:
                    active[col] = (None, row_index + c.RowSpan - 1)
                    row.append({'file': int(c.Content)} if (c.Content or '').isdigit() else None)
                else:
                    a = active.get(col)
                    row.append({'merge': True} if a and a[1] >= row_index else None)
            else:
                row.append(None)
        values.append(row)
    return columns, values


def input_value(c, kind):
    '''입력 칸의 설정 → 편집기 행 값(앞뒤 글자 제외) — 입력: 문자/숫자·상하한, 판정: 선택지 그룹, 이미지: 비전검사항목. 칸이 없으면 기본값.
    build 의 input_cell 과 짝이다'''
    if kind == 'INPUT':
        return {'type': 'N' if c is not None and c.ResultType == 'N' else 'T',
                'lower_limit': number_text(c.LowerLimit) if c is not None else '',
                'upper_limit': number_text(c.UpperLimit) if c is not None else ''}
    if kind == 'JUDGE':
        return {'code_group': c.CodeGroup}
    if kind == 'IMAGE':
        return {'vision_item': c.VisionItem_id}
    return {}


def mixed_value(c):
    '''행마다 지정 열의 칸 → 편집기 행 값 {kind, label, ...}'''
    if c is not None and c.ResultType == 'R':
        return {'kind': 'REF_IMAGE', 'file': int(c.Content)} if (c.Content or '').isdigit() else {'kind': 'REF_IMAGE'}
    if c is None or c.InputYN != 'Y':
        text = c.Content if c is not None else None
        return {'kind': 'TEXT', 'text': text} if text else {'kind': 'EMPTY'}
    kind = MARKER_KINDS.get('T' if c.ResultType == 'N' else c.ResultType, 'TEXT')
    return {'kind': kind, 'label': c.Content or '', **input_value(c, kind)}


def cell_kind(column, v):
    '''열과 행 값 → 그 칸의 종류. 행마다 지정 열은 행 값의 kind(없으면 비움)'''
    if column.get('kind') != 'MIXED':
        return column.get('kind')
    return v.get('kind') if isinstance(v, dict) else 'EMPTY'


def number_text(v):
    return '' if v is None else format(v.normalize(), 'f')


def to_decimal(v, label):
    v = '' if v is None else str(v).strip()
    if v == '':
        return None
    try:
        return Decimal(v)
    except InvalidOperation:
        raise ValueError('{}에 숫자가 아닌 값이 있습니다: {}'.format(label, v))


def text_or_none(v, max_length):
    v = (v or '').strip()
    return v[:max_length] if v else None


def save_form(data, user):
    title = (data.get('title') or '').strip()
    if not title:
        return {'success': False, 'message': '양식명을 입력하세요.'}
    top_cells = data.get('top_cells') or []
    sections = data.get('sections') or []
    if any(s.get('type') not in SECTION_TYPES for s in sections):
        return {'success': False, 'message': '섹션 구분이 올바르지 않습니다.'}
    message = validate_header_cells([top_cells] + [s.get('cells') or [] for s in sections if s['type'] == HEADER_SECTION])
    if message:
        return {'success': False, 'message': message}
    judge_groups = judge_code.group_codes()
    for s in sections:
        if s['type'] != 'INSPECTION':
            continue
        message = validate_inspection(s, judge_groups)
        if message:
            return {'success': False, 'message': message}

    # 이미지 칸에 연결할 비전검사항목이 있는지 — 새로 고르는 목록은 화면이 사용 중인 항목으로 좁힌다
    vision_ids = {vision_id(v) for s in sections if s['type'] == 'INSPECTION'
                  for row in s.get('rows') or [] for c, v in zip(s['columns'], row) if cell_kind(c, v) == 'IMAGE'} - {None}
    if vision_ids:
        with tenant_atomic():
            found = set(InspectionItem.objects.for_tenant(current_tenant()).filter(id__in=vision_ids).values_list('id', flat=True))
        if vision_ids - found:
            return {'success': False, 'message': '연결할 비전검사항목을 찾을 수 없습니다. 목록을 다시 열어 골라 주세요.'}
    check_ref_images([ref_image_id(v) for s in sections if s['type'] == 'INSPECTION'
                      for row in s.get('rows') or [] for c, v in zip(s['columns'], row) if cell_kind(c, v) == 'REF_IMAGE'
                      if ref_image_id(v)], user)

    with transaction.atomic():
        form_id = data.get('id') or None
        source = None
        if form_id:
            source = DigForm.objects.select_for_update().filter(id=form_id).first()
            if source is None:
                return {'success': False, 'message': '양식을 찾을 수 없습니다.'}
            if source.LayoutType != 'SECTION':
                return {'success': False, 'message': '칸 단위(GRID) 양식은 양식 편집에서 수정할 수 없습니다.'}
        # 양식 구분 — 새 양식은 편집기에서 고른 구분, 고치거나 새 버전이면 원래 구분을 잇는다. 양식코드 시퀀스보다 먼저 본다
        form_type = source.FormType if source is not None else data.get('form_type')
        if form_type not in DIG_FORM_TYPES:
            return {'success': False, 'message': '양식 구분이 올바르지 않습니다.'}
        require_write(user, [form_type], 'form')
        message = check_header_binds([top_cells] + [s.get('cells') or [] for s in sections if s['type'] == HEADER_SECTION], form_type)
        if message:
            return {'success': False, 'message': message}
        # 점검항목(칸)이 바뀌면 같은 코드로 새 버전을 추가한다 — 원래 버전과 그 작성 결과는 그대로
        # id 없는 점검항목 섹션(새로 더한 섹션)은 바뀐 것이다
        # 점검항목이 그대로면 작성 결과가 있어도 그 버전을 고친다(기본정보·머리글·참고사진·섹션 배치·크기·열 폭)
        revised = source is not None and inspection_changed(source, sections)
        if revised:
            last = DigForm.objects.select_for_update().filter(Code=source.Code).order_by('-Version').first()
            form = DigForm(Code=source.Code, Version=last.Version + 1)
        elif source is not None:
            form = source
        else:
            code = DbUtil.get_row('''select 'DF' || lpad(nextval('dig_form_code_seq')::text, 4, '0') as code''')['code']
            form = DigForm(Code=code, Version=1)

        form.Title = title[:200]
        form.ApplyModel = text_or_none(data.get('apply_model'), 100)
        form.UseYN = 'N' if data.get('use_yn') == 'N' else 'Y'
        form.EstablishDate = data.get('establish_date') or None
        form.StartDate = data.get('start_date') or None
        form.EndDate = data.get('end_date') or None
        form.Description = text_or_none(data.get('description'), 500)
        form.FixedTopContent = json.dumps(top_cells, ensure_ascii=False)
        form.LayoutType = 'SECTION'
        form.FormType = form_type
        form.set_audit(user)
        form.save()

        # 새 버전·새 양식은 섹션이 없다. 고치는 버전은 점검항목이 그대로이므로 점검항목 섹션의 칸은 건드리지 않는다
        existing = {s.id: s for s in DigFormSection.objects.filter(DigForm_id=form.id)}

        # 점검항목 섹션마다 표 하나: 머리줄 + 본문 행 (행 순번은 섹션마다 1부터)
        new_items = []

        kept = set()
        for order, s in enumerate(sections, start=1):
            section = existing.get(section_id(s))
            if section is None or section.SectionType != s['type']:
                section = DigFormSection(DigForm=form, SectionType=s['type'])
            # 칸이 그대로인 점검항목 섹션 — 제목·순서·크기·열 폭만 고친다(작업자 열은 칸이라 그대로 둔다)
            unchanged = section.id is not None and section.SectionType == 'INSPECTION'
            section.Title = text_or_none(s.get('title'), 200)
            section.SortOrder = order
            section.Width = int(s['width']) if s.get('width') else None
            section.Height = int(s['height']) if str(s.get('height') or '').isdigit() else None
            if not unchanged:
                section.WorkerColumnYN = 'N' if s.get('worker_column_yn') == 'N' else 'Y'
            section.set_audit(user)
            section.save()
            kept.add(section.id)
            if unchanged:
                update_column_widths(section, s, user)
                continue
            if section.SectionType == 'PHOTO':
                section.Content = sync_editor_images(s.get('content'), section.id, user)
                section.save()
                continue
            if section.SectionType == HEADER_SECTION:
                section.Content = json.dumps(s.get('cells') or [], ensure_ascii=False)
                section.save()
                continue

            items, header_rows = build_inspection(section, s['columns'], s.get('rows') or [],
                                                  section_image=s.get('section_image_yn') == 'Y')
            new_items.extend(items)
            section.HeaderRowCount = header_rows
            section.ColumnCount = len(s['columns']) + (1 if section.WorkerColumnYN == 'Y' else 0)
            section.save()

        for sid, section in existing.items():
            if sid in kept:
                continue
            if section.SectionType == 'PHOTO':
                sync_editor_images('', section.id, user)
            section.delete()

        for item in new_items:
            item.set_audit(user)
        DigFormItem.objects.bulk_create(new_items)
        link_ref_images(new_items, user)

    return {'success': True, 'message': '', 'id': form.id, 'code': form.Code, 'version': form.Version, 'revised': revised}


def copy_new_version(form, user):
    '''작성 결과가 있는 칸 단위(GRID) 양식을 같은 코드의 새 버전으로 섹션·칸까지 복사한다 — 옛 버전과 그 결과는 그대로.
    (새 양식, 옛 칸 id → 새 칸) 을 돌려준다. 칸 단위 양식에는 참고사진 첨부가 없어 첨부는 복사하지 않는다'''
    last = DigForm.objects.select_for_update().filter(Code=form.Code).order_by('-Version').first()
    sections = list(DigFormSection.objects.filter(DigForm_id=form.id))
    cells = list(DigFormItem.objects.filter(DigFormSection__DigForm_id=form.id).order_by('id'))
    new = DigForm.objects.get(id=form.id)
    copy_row(new, user, Version=last.Version + 1)
    section_map = {}
    for section in sections:
        old_id = section.id
        section_map[old_id] = copy_row(section, user, DigForm=new)
    old_ids = [c.id for c in cells]
    for c in cells:
        c.pk = None
        c._creater_id = None
        c.DigFormSection = section_map[c.DigFormSection_id]
        c.set_audit(user)
    DigFormItem.objects.bulk_create(cells)
    return new, dict(zip(old_ids, cells))


def copy_row(row, user, **values):
    '''row 를 새 행으로 저장한다(작성자·작성일시는 새로)'''
    row.pk = None
    row._state.adding = True
    row._creater_id = None
    for name, value in values.items():
        setattr(row, name, value)
    row.set_audit(user)
    row.save()
    return row


def validate_header_cells(cell_lists):
    '''맨 위 머리글과 머리글 섹션의 칸 — 작성일·작성자 칸은 표시만 한다(input 을 지운다). 작성 입력칸은 모든 머리글을 통틀어 bind 마다 하나다
    (작성 화면의 입력 요소 id·HeaderValues 키가 하나다). 문제가 없으면 None'''
    seen = set()
    for cells in cell_lists:
        if not isinstance(cells, list) or not all(isinstance(c, dict) for c in cells):
            return '머리글 형식이 올바르지 않습니다.'
        for c in cells:
            if c.get('bind') in AUTO_BINDS:
                c.pop('input', None)
            # 양식명 칸의 표시 글자(text) — 비우면 양식명을 보인다. 다른 칸에는 두지 않는다
            text = c.pop('text', None)
            if c.get('bind') == TITLE_BIND and text is not None:
                if not isinstance(text, str):
                    return '머리글 제목 형식이 올바르지 않습니다.'
                text = text.strip()
                if len(text) > TITLE_TEXT_MAX:
                    return '머리글 제목은 {}자 이하로 입력해 주세요.'.format(TITLE_TEXT_MAX)
                if text:
                    c['text'] = text
            if not c.get('input') or not c.get('bind'):
                continue
            if c['bind'] in seen:
                name = '입고번호/WO' if c['bind'] == WORK_ORDER_BIND else (c.get('name') or c['bind'])
                return '머리글에 {} 입력칸이 여러 개 있습니다. 하나만 남겨 주세요.'.format(name)
            seen.add(c['bind'])
    return None


def check_header_binds(cell_lists, form_type):
    '''머리글 칸의 입력값이 등록된 항목(dig_form_fields — 그 양식 구분에서 쓰는 것)이거나 직접 입력인지. 문제가 없으면 None'''
    for cells in cell_lists:
        for c in cells:
            if c.get('bind'):
                message = dig_form_fields.check_bind(str(c['bind']), form_type)
                if message:
                    return message
    return None


def section_id(s):
    v = str(s.get('id') or '')
    return int(v) if v.isdigit() else None


def ref_image_id(v):
    """고정 이미지 열 행 값 {"file": 첨부 id} → 첨부 id. 비었거나 위 칸과 병합한 행이면 None"""
    value = v.get('file') if isinstance(v, dict) and not v.get('merge') else None
    if value in (None, ''):
        return None
    if not str(value).isdigit():
        raise ValueError('고정 이미지 값이 올바르지 않습니다.')
    return int(value)


def ref_merge_top(rows, ci, ridx, mixed):
    """[위 칸과 병합]한 행 ridx 가 붙는 고정 이미지 칸의 첨부 id — 바로 위부터 병합을 거슬러 올라간다.
    위 칸이 없거나(첫 행) 고정 이미지가 아니면(행마다 지정 열) None"""
    for r in range(ridx - 1, -1, -1):
        v = rows[r][ci] if isinstance(rows[r][ci], dict) else {}
        if mixed and v.get('kind') != 'REF_IMAGE':
            return None
        if not v.get('merge'):
            return ref_image_id(v)
    return None


def ref_image_runs(rows, ci):
    """고정 이미지 열 → [(시작 행 위치, 행 수, 첨부 id)] — [위 칸과 병합]한 행은 바로 위 칸에 붙는다"""
    runs = []
    for ri, r in enumerate(rows):
        v = r[ci] if isinstance(r[ci], dict) else {}
        if v.get('merge') and runs:
            runs[-1][1] += 1
        else:
            runs.append([ri, 1, ref_image_id(v)])
    return runs


def vision_id(v):
    '''이미지 열 행 값 {"vision_item": id} → 연결할 비전검사항목 id. 비었으면 None'''
    value = v.get('vision_item') if isinstance(v, dict) else None
    if value in (None, ''):
        return None
    if not str(value).isdigit():
        raise ValueError('비전검사항목 값이 올바르지 않습니다.')
    return int(value)


def item_signature(item):
    '''칸 비교용 — 열 폭(MinColumnWidth)을 뺀 칸 설정 값 전부(이미지 칸의 비전검사항목 연결 포함). 폭은 바뀌어도 새 버전을 만들지 않고 그 버전에서 고친다'''
    return (item.RowType, item.RowIndex, item.ColumnIndex, item.RowSpan, item.ColSpan, item.Content, item.ResultType,
            item.CodeGroup, item.InputYN, item.LowerLimit, item.UpperLimit, item.VisionItem_id)


def build_posted(s):
    '''보낸 점검항목 섹션으로 만들어질 칸 (저장하지 않음)'''
    probe = DigFormSection(SectionType='INSPECTION', WorkerColumnYN='N' if s.get('worker_column_yn') == 'N' else 'Y')
    items, _ = build_inspection(probe, s['columns'], s.get('rows') or [], section_image=s.get('section_image_yn') == 'Y')
    return items


def update_column_widths(section, s, user):
    '''칸이 그대로인 점검항목 섹션의 열 폭만 고친다 — 폭은 열 제목 칸(머리줄)에 있고 작성 결과가 매달리지 않는다'''
    widths = {(i.RowIndex, i.ColumnIndex): i.MinColumnWidth for i in build_posted(s)}
    for item in DigFormItem.objects.filter(DigFormSection=section):
        width = widths.get((item.RowIndex, item.ColumnIndex))
        if item.MinColumnWidth != width:
            item.MinColumnWidth = width
            item.set_audit(user)
            item.save(update_fields=['MinColumnWidth', '_modified', '_modifier_id'])


def inspection_changed(form, sections):
    '''보낸 점검항목 섹션의 칸이 저장된 것과 다른가 — 점검항목 섹션이 늘거나 줄거나, 같은 섹션에서 만들어질 칸이 하나라도 다르면 바뀐 것이다.
    섹션 순서·제목·크기와 열 폭은 보지 않는다(그 버전에서 고친다)'''
    saved = {s.id: set() for s in DigFormSection.objects.filter(DigForm_id=form.id, SectionType='INSPECTION')}
    posted = [s for s in sections if s['type'] == 'INSPECTION']
    ids = [section_id(s) for s in posted]
    if None in ids or sorted(ids) != sorted(saved):
        return True
    for item in DigFormItem.objects.filter(DigFormSection_id__in=list(saved)):
        saved[item.DigFormSection_id].add(item_signature(item))
    for s, sid in zip(posted, ids):
        if {item_signature(i) for i in build_posted(s)} != saved[sid]:
            return True
    return False


def delete_form(form_id, user):
    '''선택한 버전 하나를 지운다 — 작성 결과가 있으면 지우지 않는다. 참고사진 첨부 행도 지운다(파일은 남긴다)'''
    with transaction.atomic():
        form = DigForm.objects.select_for_update().filter(id=form_id).first()
        if form is None:
            return {'success': False, 'message': '양식을 찾을 수 없습니다.'}
        require_write(user, [form.FormType], 'form')
        if DigFormResult.objects.filter(DigForm_id=form.id).exists():
            return {'success': False, 'message': '작성된 결과가 있어 삭제할 수 없습니다. 쓰지 않으려면 사용여부를 미사용으로 바꿔 주세요.'}
        sections = list(DigFormSection.objects.filter(DigForm_id=form.id))
        for section in sections:
            sync_editor_images('', section.id, user)
        cells = DigFormItem.objects.filter(DigFormSection__DigForm_id=form.id)
        unlink_ref_images(cells.filter(ResultType='R').values_list('id', flat=True))
        cells.delete()
        DigFormSection.objects.filter(DigForm_id=form.id).delete()
        form.delete()
    return {'success': True, 'message': '', 'code': form.Code, 'version': form.Version}


def validate_inspection(s, judge_groups):
    '''judge_groups: 항목결과 코드에 있는 그룹 코드 — 판정 열은 그중 하나여야 한다'''
    title = s.get('title') or ''
    columns = s.get('columns') or []
    if not columns:
        return '[{}] 열을 하나 이상 추가하세요.'.format(title)
    if len(columns) > MAX_COLUMNS:
        return '[{}] 열은 {}개까지 추가할 수 있습니다.'.format(title, MAX_COLUMNS)
    for idx, c in enumerate(columns):
        label = '[{}] {}번째 열'.format(title, idx + 1)
        if not (c.get('title') or '').strip():
            return label + '의 제목을 입력하세요.'
        if c.get('kind') not in COLUMN_KINDS:
            return label + '의 종류를 선택하세요.'
        if c['kind'] == 'JUDGE' and c.get('code_group') not in judge_groups:
            return label + '의 판정 선택지를 선택하세요.'
    for ridx, row in enumerate(s.get('rows') or []):
        if len(row) != len(columns):
            return '[{}] {}번째 행의 값 개수가 열 개수와 다릅니다.'.format(title, ridx + 1)
        for c, v in zip(columns, row):
            label = '[{}] {}번째 행 {}'.format(title, ridx + 1, c['title'])
            kind = cell_kind(c, v)
            if kind == 'REF_IMAGE' and isinstance(v, dict) and v.get('merge'):
                if ref_merge_top(s['rows'], columns.index(c), ridx, c['kind'] == 'MIXED') is None:
                    return label + ': 위 칸에 이미지가 없어 병합할 수 없습니다.'
            if c['kind'] == 'MIXED':
                if kind not in CELL_KINDS:
                    return label + '의 칸 종류를 선택하세요.'
                if kind == 'JUDGE' and v.get('code_group') not in judge_groups:
                    return label + '의 판정 선택지를 선택하세요.'
            if kind != 'INPUT' or not isinstance(v, dict) or v.get('type') != 'N':
                continue
            lower = to_decimal(v.get('lower_limit'), label + ' 하한')
            upper = to_decimal(v.get('upper_limit'), label + ' 상한')
            if lower is not None and upper is not None and lower > upper:
                return label + '의 하한이 상한보다 큽니다.'
    return None


def build_inspection(section, columns, rows, section_image=False):
    '''점검항목 섹션 → 칸 목록. 반환: (칸 목록, 머리줄 행 수). section_image 면 섹션 이미지 칸을 더한다'''
    items = []
    leaves = list(columns) + ([WORKER_COLUMN] if section.WorkerColumnYN == 'Y' else [])
    paths = [header_path(c) for c in leaves]
    header_rows = 1 + max(len(p) for p in paths)
    top = 1

    # 묶음 머리줄: 줄마다 위쪽 경로가 같은 연속 열을 한 칸으로 가로 병합
    for level in range(header_rows - 1):
        i = 0
        while i < len(leaves):
            if len(paths[i]) <= level:
                i += 1
                continue
            j = i
            while j < len(leaves) and paths[j][:level + 1] == paths[i][:level + 1]:
                j += 1
            items.append(make_item(section, top + level, i + 1, 'H', content=paths[i][level], col_span=j - i))
            i = j
    # 열 제목: 묶음 머리줄 바로 아래부터 맨 아래 머리줄까지 세로 병합
    for i, c in enumerate(leaves):
        items.append(header_leaf(section, top + len(paths[i]), i + 1, c, header_rows - len(paths[i])))

    body_top = top + header_rows
    texts = {ci: texts_of(rows, ci) for ci, c in enumerate(columns) if c['kind'] == 'TEXT'}
    merge_cols = []
    for ci, c in enumerate(columns):
        if c['kind'] == 'TEXT':
            if c.get('merge'):
                # 왼쪽 병합 열 묶음 안에서만 병합 (예: 같은 작업 안의 같은 검사항목)
                merge_cols.append(ci)
                keys = [tuple(texts[k][ri] for k in merge_cols) for ri in range(len(rows))]
                for start, size in merge_runs(keys):
                    items.append(make_item(section, body_top + start, ci + 1, 'D', content=texts[ci][start], row_span=size))
            else:
                for ri, text in enumerate(texts[ci]):
                    items.append(make_item(section, body_top + ri, ci + 1, 'D', content=text))
        elif c['kind'] == 'REF_IMAGE':
            for start, size, file_id in ref_image_runs(rows, ci):
                item = make_item(section, body_top + start, ci + 1, 'D', content=str(file_id) if file_id else None, row_span=size)
                item.ResultType = 'R'
                items.append(item)
        for ri, r in enumerate(rows):
            if c['kind'] in INPUT_KINDS:
                # 열 하나에 종류 하나 — 판정 선택지는 열 설정, 앞뒤 글자는 없다
                v = {k: x for k, x in r[ci].items() if k != 'label'} if isinstance(r[ci], dict) else {}
                if c['kind'] == 'JUDGE':
                    v['code_group'] = c['code_group']
                items.append(input_cell(section, body_top + ri, ci + 1, c['kind'], v))
            elif c['kind'] == 'MIXED':
                v = r[ci] if isinstance(r[ci], dict) else {}
                above = items[-1] if ri > 0 and items and items[-1].ColumnIndex == ci + 1 else None
                if v.get('kind') == 'REF_IMAGE' and v.get('merge') and above is not None and above.ResultType == 'R':
                    # 위 고정 이미지 칸에 병합 — 칸을 만들지 않고 위 칸을 늘린다
                    above.RowSpan += 1
                else:
                    items.append(mixed_item(section, body_top + ri, ci + 1, r[ci]))
    if section_image:
        items.append(make_item(section, SECTION_IMAGE_ROW, 0, 'S', input_type='I'))
    return items, header_rows


def input_cell(section, row_index, col, kind, v):
    '''본문 입력 칸 하나(입력·판정·체크·이미지) — v: 입력 type·상하한, 판정 code_group, 이미지 vision_item, 앞뒤 글자 label(Content).
    parse 의 input_value 와 짝이다'''
    label = clean_text(v['label']) if isinstance(v.get('label'), str) else ''
    if kind == 'INPUT' and v.get('type') == 'N':
        return make_item(section, row_index, col, 'D', content=label, input_type='N',
                         lower=to_decimal(v.get('lower_limit'), '하한'), upper=to_decimal(v.get('upper_limit'), '상한'))
    item = make_item(section, row_index, col, 'D', content=label, input_type=COLUMN_KINDS[kind], code_group=v.get('code_group'))
    if kind == 'IMAGE':
        item.VisionItem_id = vision_id(v)
    return item


def mixed_item(section, row_index, col, v):
    '''행마다 지정 열의 칸 하나 — 입력·판정·체크·이미지는 input_cell, 글자·비움은 글자 칸'''
    v = v if isinstance(v, dict) else {}
    kind = v.get('kind')
    if kind in INPUT_KINDS:
        return input_cell(section, row_index, col, kind, v)
    if kind == 'REF_IMAGE':
        file_id = ref_image_id(v)
        item = make_item(section, row_index, col, 'D', content=str(file_id) if file_id else None)
        item.ResultType = 'R'
        return item
    text = clean_text(v.get('text')) if kind == 'TEXT' and isinstance(v.get('text'), str) else ''
    return make_item(section, row_index, col, 'D', content=text)


def header_path(c):
    '''열의 묶음 머리줄 경로 [상위, 중간] — 빈 값은 건너뛴다 (상위 없이 중간만 있으면 중간이 상위 자리)'''
    return [v for v in ((c.get('group') or '').strip(), (c.get('sub') or '').strip()) if v]


def texts_of(rows, ci):
    return [clean_text(r[ci]) if isinstance(r[ci], str) else '' for r in rows]


def clean_text(v):
    '''글자 칸 — 줄바꿈(CRLF·CR)은 LF 로 맞추고 줄 끝 공백과 앞뒤 공백만 지운다(가운데 줄바꿈·줄 앞 들여쓰기는 남긴다)'''
    lines = (v or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    return '\n'.join(line.rstrip() for line in lines).strip()


def header_leaf(section, row_index, col, c, row_span):
    '''열 제목 칸 — 열 종류를 ResultType·CodeGroup으로 표시 (입력칸 아님). 글자 열 "같은 값 병합"은 CodeGroup=MERGE_MARKER'''
    item = make_item(section, row_index, col, 'H', content=c.get('title'), row_span=row_span,
                     min_width=int(c['width']) if str(c.get('width') or '').isdigit() else None)
    item.ResultType = COLUMN_KINDS.get(c['kind'])
    if c['kind'] == 'JUDGE':
        item.CodeGroup = c.get('code_group')
    elif c['kind'] == 'TEXT' and c.get('merge'):
        item.CodeGroup = MERGE_MARKER
    else:
        item.CodeGroup = None
    return item


def merge_runs(values):
    '''연속으로 같은 값의 (시작 위치, 개수) 목록'''
    runs = []
    for idx, v in enumerate(values):
        if runs and values[runs[-1][0]] == v:
            runs[-1][1] += 1
        else:
            runs.append([idx, 1])
    return runs


def make_item(section, row_index, col, row_type, content=None, row_span=1, col_span=1, min_width=None,
              input_type=None, code_group=None, lower=None, upper=None):
    item = DigFormItem(DigFormSection=section, RowType=row_type, RowIndex=row_index, ColumnIndex=col,
                       RowSpan=row_span, ColSpan=col_span)
    item.Content = text_or_none(content, 1000)
    item.MinColumnWidth = min_width
    if input_type:
        item.InputYN = 'Y'
        item.ResultType = input_type
        item.CodeGroup = code_group if input_type == 'S' else None
        item.LowerLimit = lower if input_type == 'N' else None
        item.UpperLimit = upper if input_type == 'N' else None
    return item
