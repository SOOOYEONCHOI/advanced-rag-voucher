"""PLM 품목·BOM 수신건(`if_plm_part_bom`)을 품목(`mst_product`)·BOM(`mst_bom`) 마스터에 반영한다.

- 파일은 장비 한 대의 BOM 을 위에서 아래로 펼친 것이다. 부모는 바로 위쪽의 `Depth` 가 하나 작은 행이다
- 품목은 코드(Part(ERP))로 찾아 없으면 만들고 달라졌으면 고친다. 지우지 않는다
- BOM 은 부모 단위로 직속 자식 목록을 파일과 맞춘다(추가·수량/순서 변경·삭제). 파일에 나오지 않은 조립품은 건드리지 않는다
- 하위 없이 나온 품목은 `MAX_EXPORT_DEPTH` 보다 얕을 때만 자식을 비운다 — 그 깊이에서는 내보내기가 잘랐을 수 있다
- 검증이 하나라도 틀리면 아무것도 반영하지 않는다(DECISIONS 사용자 결정 2026-10-19, DATA_MODEL §2)
"""
import datetime
from collections import Counter
from decimal import Decimal, InvalidOperation

from django.db import transaction

from domain.models.basic import Bom, Product
from domain.services.logging import LogWriter

# 원본 머리글 `Line No ( 7 Depth )` — PLM 내보내기가 7단계까지다
MAX_EXPORT_DEPTH = 7
TEXT = {'PartNo': 'PartNo', 'Version': 'PartVer', 'Name': 'PartName', 'PartType': 'PartType', 'Spec': 'Spec',
        'MaterialGroup': 'MaterialGroup', 'Material': 'Material', 'PostProcess': 'PostProcess', 'PartState': 'PartState',
        'Model3dType': 'Model3dType', 'Model3dNo': 'Model3dNo', 'Model3dVersion': 'Model3dVer', 'Model3dState': 'Model3dState',
        'Drawing2dNo': 'Drawing2dNo', 'Drawing2dVersion': 'Drawing2dVer', 'Drawing2dState': 'Drawing2dState'}
DATE = {'PlmCreatedDate': 'PartCreated', 'PlmVersionDate': 'PartVerCreated'}
DATETIME = {'Model3dModified': 'Model3dModified', 'Drawing2dModified': 'Drawing2dModified'}
# 반영 건수 키 → 화면 이름(인터페이스 이력)
RESULT_LABELS = {'product_added': '품목 추가', 'product_updated': '품목 변경',
                 'bom_added': 'BOM 추가', 'bom_updated': 'BOM 변경', 'bom_deleted': 'BOM 삭제'}
COUNTS = tuple(RESULT_LABELS)


def _when(row, column, fmt, kind):
    value = getattr(row, column)
    if value is None:
        return None
    try:
        parsed = datetime.datetime.strptime(value, fmt)
    except ValueError:
        raise ValueError(f'{row.RowNo}행: {column} 이 {kind} 형식이 아닙니다({value}).')
    return parsed.date() if kind == '날짜' else parsed


def _product(row):
    """원본 행 하나를 검증하고 (코드, 수량, 품목 값) 으로 바꾼다."""
    code, part_no, ver = row.PartErp, row.PartNo, row.PartVer or ''
    revision = ver.split('.')[0]
    if not code or not part_no or code != f'{part_no}.{revision}':
        raise ValueError(f'{row.RowNo}행: Part(ERP) {code} 가 Part No {part_no}·Part Ver {ver} 와 맞지 않습니다.')
    if not row.PartName:
        raise ValueError(f'{row.RowNo}행: Part Name 이 비었습니다.')
    try:
        qty = Decimal(row.Qty)
    except (InvalidOperation, TypeError):
        qty = None
    if qty is None or not qty.is_finite() or qty <= 0:
        raise ValueError(f'{row.RowNo}행: Qty {row.Qty} 는 0보다 큰 숫자여야 합니다.')
    values = {field: getattr(row, column) for field, column in TEXT.items()}
    values['Revision'] = revision
    values.update({field: _when(row, column, '%Y-%m-%d', '날짜') for field, column in DATE.items()})
    values.update({field: _when(row, column, '%Y-%m-%d %H:%M:%S', '일시') for field, column in DATETIME.items()})
    return code, qty, values


def parse(rows):
    """원본 행 → (품목 {코드: 값}, 맞출 자식 목록 {부모 코드: [(자식 코드, 수량)]}). 틀리면 ValueError."""
    products, nodes, stack = {}, [], []
    for row in rows:
        try:
            depth = int(row.Depth)
        except (TypeError, ValueError):
            depth = 0
        if depth < 1 or depth > len(stack) + 1:
            raise ValueError(f'{row.RowNo}행: Depth {row.Depth} 가 앞 행보다 2 이상 깊거나 잘못된 값입니다.')
        code, qty, values = _product(row)
        if products.setdefault(code, values) != values:
            diff = next(k for k in values if values[k] != products[code][k])
            raise ValueError(f'{row.RowNo}행: {code} 의 속성({diff})이 앞에 나온 같은 품목과 다릅니다.')
        del stack[depth - 1:]
        if any(node['code'] == code for node in stack):
            raise ValueError(f'{row.RowNo}행: {code} 가 자기 하위에 다시 나옵니다(순환).')
        node = {'row': row.RowNo, 'code': code, 'qty': qty, 'depth': depth, 'kids': []}
        if stack:
            stack[-1]['kids'].append(node)
        stack.append(node)
        nodes.append(node)

    children = {}
    for node in nodes:
        if not node['kids'] and node['depth'] >= MAX_EXPORT_DEPTH:
            continue  # 잘렸을 수 있다 — 모른다
        kids = [(kid['code'], kid['qty']) for kid in node['kids']]
        seen = set()
        for kid in node['kids']:
            if kid['code'] in seen:
                raise ValueError(f"{kid['row']}행: {node['code']} 아래에 {kid['code']} 가 두 번 나옵니다.")
            seen.add(kid['code'])
        if children.setdefault(node['code'], kids) != kids:
            raise ValueError(f"{node['row']}행: {node['code']} 를 펼친 곳마다 자식 목록이 다릅니다.")
    return products, children


def _check_cycles(start_ids):
    # ponytail: BOM 전체를 메모리에 올려 본다 — 수십만 행이 되면 재귀 CTE 로 바꾼다
    graph = {}
    for parent_id, child_id in Bom.objects.values_list('Parent_id', 'Child_id'):
        graph.setdefault(parent_id, []).append(child_id)
    for start in start_ids:
        todo, seen = list(graph.get(start, [])), set()
        while todo:
            current = todo.pop()
            if current == start:
                code = Product.objects.get(id=start).Code
                raise ValueError(f'{code} 가 다른 장비 BOM 과 엮여 자기 하위가 됩니다(순환).')
            if current not in seen:
                seen.add(current)
                todo.extend(graph.get(current, []))


@transaction.atomic
def apply_plm_part_bom(batch):
    """수신건을 마스터에 반영하고 건수 {COUNTS: n} 를 돌려준다. 틀리면 ValueError 이고 아무것도 바뀌지 않는다."""
    products, children = parse(batch.plm_rows.order_by('RowNo'))
    result = Counter({key: 0 for key in COUNTS})

    existing = {p.Code: p for p in Product.objects.filter(Code__in=products)}
    for code, values in products.items():
        product = existing.get(code)
        if product is None:
            existing[code] = Product.objects.create(Code=code, **values)
            result['product_added'] += 1
        elif any(getattr(product, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(product, k, v)
            product.save()
            result['product_updated'] += 1
    ids = {code: product.id for code, product in existing.items()}

    changed = set()
    for parent, kids in children.items():
        parent_id = ids[parent]
        current = {bom.Child_id: bom for bom in Bom.objects.filter(Parent_id=parent_id)}
        want = {ids[child]: (qty, seq) for seq, (child, qty) in enumerate(kids, 1)}
        gone = [bom.id for child_id, bom in current.items() if child_id not in want]
        if gone:
            Bom.objects.filter(id__in=gone).delete()
            result['bom_deleted'] += len(gone)
        for child_id, (qty, seq) in want.items():
            bom = current.get(child_id)
            if bom is None:
                Bom.objects.create(Parent_id=parent_id, Child_id=child_id, Qty=qty, Seq=seq)
                result['bom_added'] += 1
                changed.add(parent_id)
            elif (bom.Qty, bom.Seq) != (qty, seq):
                bom.Qty, bom.Seq = qty, seq
                bom.save(update_fields=['Qty', 'Seq', '_modified'])
                result['bom_updated'] += 1
    _check_cycles(changed)

    LogWriter.add_dblog('info', 'interface/apply_plm_part_bom', '수신건 {} 반영 — {}'.format(
        batch.id, ', '.join(f'{k} {result[k]}' for k in COUNTS)))
    return dict(result)
