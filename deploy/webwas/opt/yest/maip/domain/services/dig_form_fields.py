"""디지털 양식 머리글 입력값 항목 — 양식 편집기의 "값" 선택지, 작성 화면의 입력 방식, 저장 검증이 이 목록 하나를 본다.

칸 JSON 의 bind 값은 옛 양식과 같다(form.* 양식정보 · result.* 작성 정보·입력 · appr.N 결재).
- 목록 항목(result.field.<키>): 작성 화면에서 검색해 고르고(목록에 없는 값은 직접 쓴다) 작성건 HeaderValues 의 "field.<키>" 에 글자,
  목록에서 고른 값이면 "field.<키>@code" 에 그 코드를 함께 둔다
- 직접 입력(result.extra.<키>): 양식 편집기가 키를 만든다(라벨의 [입력 받기] 또는 입력값의 "직접 입력"). 여기에는 없다
새 항목은 FIELDS 한 줄과, 목록이면 SOURCES 의 검색 함수 하나를 더한다.
"""
from django.db.models import Q

from domain.models.basic import Product, Receipt

FIELD_PREFIX = 'result.field.'
EXTRA_PREFIX = 'result.extra.'
CODE_SUFFIX = '@code'
INCOMING, OUTGOING = 'INCOMING', 'OUTGOING'
BOTH = (INCOMING, OUTGOING)
LOOKUP_LIMIT = 30

# group: 편집기 묶음 · input: '' 표시만 / auto 작성 정보(표시만) / wo 이어쓰기 키(작성 화면의 WO·입고 검색) / lookup 목록
# names: 양식 구분마다 다른 이름. 고르면 함께 채울 항목(품목 ↔ 품번)은 검색 결과의 values 가 정한다
FIELDS = [
    {'bind': 'form.Title', 'name': '양식명(제목)', 'group': '양식정보', 'input': ''},
    {'bind': 'form.Code', 'name': '양식코드', 'group': '양식정보', 'input': ''},
    {'bind': 'form.Version', 'name': '버전', 'group': '양식정보', 'input': ''},
    {'bind': 'form.EstablishDate', 'name': '제정일', 'group': '양식정보', 'input': ''},
    {'bind': 'form.ApplyModel', 'name': '적용모델', 'group': '양식정보', 'input': ''},
    # 수입 검사는 입고번호가 곧 작성건의 WO(이어쓰기 키)다 — 별도 입고번호 항목은 품질 양식에만 둔다
    {'bind': 'result.WorkOrderNumber', 'name': 'WO', 'names': {INCOMING: '입고번호'}, 'group': '작성 시 입력', 'input': 'wo'},
    {'bind': FIELD_PREFIX + 'product', 'name': '품목', 'group': '작성 시 입력', 'input': 'lookup', 'source': 'product'},
    {'bind': FIELD_PREFIX + 'part_no', 'name': '품번', 'group': '작성 시 입력', 'input': 'lookup', 'source': 'product'},
    {'bind': FIELD_PREFIX + 'receipt_no', 'name': '입고번호', 'group': '작성 시 입력', 'input': 'lookup', 'source': 'receipt',
     'form_types': (OUTGOING,)},
    {'bind': 'result.WriteDate', 'name': '작성일', 'group': '작성 정보', 'input': 'auto'},
    {'bind': 'result.Writer', 'name': '작성자', 'group': '작성 정보', 'input': 'auto'},
] + [{'bind': 'appr.{}'.format(n), 'name': '결재 {}'.format(n), 'group': '결재', 'input': ''} for n in range(1, 5)]

BY_BIND = {f['bind']: f for f in FIELDS}
# 작성일·작성자 — 표시만 한다(입력받지 않는다). 작성건 WO(이어쓰기 키) — 머리글을 통틀어 하나
AUTO_BINDS = tuple(f['bind'] for f in FIELDS if f['input'] == 'auto')
WORK_ORDER_BIND = next(f['bind'] for f in FIELDS if f['input'] == 'wo')


def fields_for(form_type):
    '''양식 구분에서 고를 수 있는 항목 — 편집기 선택지. 이름은 구분에 맞춘다.
    구분이 없으면(검사양식 관리는 수입·품질을 한 화면에서 다룬다 — 구분을 정하기 전의 새 양식) 모든 항목, 저장할 때 구분으로 막는다'''
    return [{'bind': f['bind'], 'name': (f.get('names') or {}).get(form_type, f['name']), 'group': f['group'],
             'input': f['input']}
            for f in FIELDS if not form_type or form_type in f.get('form_types', BOTH)]


def check_bind(bind, form_type):
    '''머리글 칸 bind 확인 — 등록된 항목(그 양식 구분에서 쓰는 것)이거나 직접 입력이면 None, 아니면 오류 문구'''
    if bind.startswith(EXTRA_PREFIX) and len(bind) > len(EXTRA_PREFIX):
        return None
    f = BY_BIND.get(bind)
    if f is None:
        return '머리글에 알 수 없는 입력값이 있습니다: {}'.format(bind)
    if form_type not in f.get('form_types', BOTH):
        return '{} 입력값은 이 양식 구분에서 쓸 수 없습니다.'.format(f['name'])
    return None


def value_key(bind):
    '''목록 항목 bind → 작성건 HeaderValues 의 키'''
    return 'field.' + bind[len(FIELD_PREFIX):]


def search_products(term):
    rows = Product.objects.order_by('PartNo', 'Code')
    if term:
        rows = rows.filter(Q(PartNo__icontains=term) | Q(Name__icontains=term) | Q(Code__icontains=term))
    return [{'code': p.Code, 'label': '{} · {}'.format(p.PartNo, p.Name),
             'values': {FIELD_PREFIX + 'product': p.Name, FIELD_PREFIX + 'part_no': p.PartNo}}
            for p in rows[:LOOKUP_LIMIT]]


def search_receipts(term):
    rows = Receipt.objects.order_by('-ReceiptDate', '-id')
    if term:
        rows = rows.filter(Q(ReceiptNo__icontains=term) | Q(ItemName__icontains=term) | Q(ItemCode__icontains=term))
    return [{'code': r.ReceiptNo, 'label': '{} · {}'.format(r.ReceiptNo, r.ItemName),
             'values': {FIELD_PREFIX + 'receipt_no': r.ReceiptNo}}
            for r in rows[:LOOKUP_LIMIT]]


SOURCES = {'product': search_products, 'receipt': search_receipts}


def lookup(bind, term):
    '''작성 화면 검색 — [{code, label, text, values}]. text 는 그 칸에 넣을 글자, values 는 함께 채울 항목까지의 {bind: 글자}'''
    f = BY_BIND.get(bind)
    if f is None or f['input'] != 'lookup':
        raise ValueError('목록에서 고르는 입력값이 아닙니다.')
    items = SOURCES[f['source']]((term or '').strip()[:100])
    for item in items:
        item['text'] = item['values'][bind]
    return items
