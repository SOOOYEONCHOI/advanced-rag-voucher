"""디지털 양식 항목결과 코드 — 판정 칸의 선택지(사용자코드 user_code, 화면: 검사양식 코드 관리).

    묶음(ROOT_CODE) → 그룹(코드 = 칸 dig_form_item."CodeGroup") → 결과 코드(코드 = 작성 결과 "ComboResult")

결과 코드의 `Type` 이 판정 의미다 — Y 합격 / N 불합격 / X 해당없음. 자동 판정·결과 표시는 결과 코드가 아니라
이 의미를 본다(팀원 MES 설계 초안 D30). 그룹 코드는 양식 칸과 작성 결과가 문자열로 가리키므로, 쓰는 중이면 바꾸거나 지우지 않는다.
"""
from django.db import transaction

from domain.models.dig_form import DigFormItem, DigFormItemResult
from domain.models.system import UserCode
from domain.services.sql import DbUtil

ROOT_CODE = 'dig_form_judge_code'
MEANINGS = ('Y', 'N', 'X')   # 합격 / 불합격 / 해당없음

# 판정 선택지 행 — code_group·code·value·meaning. 호출부가 where·order by 를 붙인다.
OPTION_SQL = f'''
    select s."Code" as code_group
    , o."Code" as code
    , o."Value" as value
    , o."Type" as meaning
    from user_code o
    inner join user_code s on s.id = o."Parent_id"
    inner join user_code r on r.id = s."Parent_id" and r."Code" = '{ROOT_CODE}' and r."Parent_id" is null
'''

# 기본 데이터(seed_initial). 앞의 두 그룹은 옛 sys_code 판정 코드와 같은 코드라 기존 양식 칸·작성 결과가 그대로 이어진다.
# 뒤의 세 그룹은 고객 원본 양식(08~11 조립 체크 시트) 검토로 더했다 — 고객 확인 거리는 docs/STATUS.md.
DEFAULT_GROUPS = [
    ('dig_form_okng', 'OK / NG', [('Y', 'OK', 'Y'), ('N', 'NG', 'N')]),
    ('dig_form_pass_na', '합격 / 불합격 / N/A', [('Y', '합격', 'Y'), ('N', '불합격', 'N'), ('X', 'N/A', 'X')]),
    ('dig_form_fit', '적합 / 부적합', [('Y', '적합', 'Y'), ('N', '부적합', 'N')]),
    ('dig_form_usable', '사용 가능 / 불가', [('Y', '사용 가능', 'Y'), ('N', '사용 불가', 'N')]),
    ('dig_form_receipt', '입고 완료 / 미입고', [('Y', '입고 완료', 'Y'), ('N', '미입고', 'N')]),
]


def root():
    return UserCode.objects.filter(Code=ROOT_CODE, Parent=None).first()


def groups():
    """판정 선택지 그룹 목록 [{code, name, options: [{code, value, meaning}]}] — 화면 순서(_order) 대로."""
    sql = f'''
    select s."Code" as code, s."Value" as name
    from user_code s
    inner join user_code r on r.id = s."Parent_id" and r."Code" = '{ROOT_CODE}' and r."Parent_id" is null
    order by s._order, s.id
    '''
    rows = DbUtil.get_rows(sql)
    options = {}
    for row in DbUtil.get_rows(OPTION_SQL + ' order by o._order, o.id'):
        options.setdefault(row['code_group'], []).append({'code': row['code'], 'value': row['value'], 'meaning': row['meaning']})
    for row in rows:
        row['options'] = options.get(row['code'], [])
    return rows


def group_codes():
    """있는 그룹 코드 — 양식 편집이 판정 열의 그룹을 검사할 때 쓴다."""
    return set(UserCode.objects.filter(Parent__Code=ROOT_CODE, Parent__Parent=None).values_list('Code', flat=True))


@transaction.atomic
def ensure_defaults():
    """기본 묶음·그룹·결과 코드를 없을 때만 넣는다. 화면에서 고친 이름·순서·의미는 덮지 않는다. 넣은 행 수를 돌려준다."""
    created = 0
    top, made = UserCode.objects.get_or_create(
        Code=ROOT_CODE, Parent=None,
        defaults={'Value': '항목결과 코드', 'Description': '디지털 양식 항목결과 코드 그룹(검사양식 코드 관리 화면)', '_order': 0})
    created += made
    for group_order, (group_code, group_name, options) in enumerate(DEFAULT_GROUPS, start=1):
        group, made = UserCode.objects.get_or_create(
            Code=group_code, Parent=top, defaults={'Value': group_name, '_order': group_order})
        created += made
        for option_order, (code, value, meaning) in enumerate(options, start=1):
            _, made = UserCode.objects.get_or_create(
                Code=code, Parent=group, defaults={'Value': value, 'Type': meaning, '_order': option_order})
            created += made
    return created


def group_used(group_code):
    """양식 칸이 이 그룹을 쓰는가."""
    return DigFormItem.objects.filter(CodeGroup=group_code).exists()


def option_used(group_code, option_code):
    """작성 결과가 이 결과 코드를 쓰는가."""
    return DigFormItemResult.objects.filter(DigFormItem__CodeGroup=group_code, ComboResult=option_code).exists()
