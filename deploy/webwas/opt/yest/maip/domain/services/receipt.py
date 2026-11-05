"""입고 — ERP 구매요청 현황(= 입고의뢰) 수신건을 입고(`mst_receipt`)에 반영하고, 입고의 수입검사 상태를 센다.

- 구매요청 한 줄 = 입고 한 줄. 입고번호(요청번호-요청순번)가 수입검사 작성건의 `WorkOrderNumber` 다
- 수량·입고일·거래처는 발주 값이 있으면 발주, 없으면 품의(입고일은 그것도 없으면 요청납기일) 값이다
- 품목 마스터에 없는 품목은 구매요청의 이름·규격으로 만든다. 있는 품목은 고치지 않는다(PLM 이 정본이다)
- 파일에 없는 기존 입고는 건드리지 않는다. 검증이 하나라도 틀리면 아무것도 반영하지 않는다
- 검사 대상 = 품번에 수입검사 양식(`mst_product_form`, N:M)이 매핑된 입고. 검사 작업은 저장하지 않고 작성건으로 센다
(DECISIONS 사용자 결정 2026-10-19·2026-10-21)
"""
import datetime
import json
from collections import Counter
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.contrib.auth.models import User
from django.db.models import Count, Exists, F, OuterRef, Q

from domain.models.basic import Product, ProductForm, Receipt
from domain.models.dig_form import DigForm, DigFormItem, DigFormItemResult, DigFormResult
from domain.services.account import user_display_name
from domain.services.logging import LogWriter

RESULT_LABELS = {'receipt_added': '입고 추가', 'receipt_updated': '입고 변경', 'product_added': '품목 추가'}
INCOMING = 'INCOMING'


# 입고일 — 앞 칸부터 값이 있는 것을 쓴다
DATE_COLUMNS = ('PlanReceiptDatePo', 'PlanReceiptDateAppr', 'ReqDueDate')


def _date(row, column):
    value = getattr(row, column)
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError(f'{row.RowNo}행: {column} 이 날짜 형식이 아닙니다({value}).')


def _values(row):
    """원본 행 하나를 검증하고 (입고번호, 품번, 리비전, 입고 값) 으로 바꾼다."""
    if not row.ReqNo:
        raise ValueError(f'{row.RowNo}행: 요청번호가 비었습니다.')
    try:
        seq = int(row.ReqSeq)
    except (TypeError, ValueError):
        seq = 0
    if seq < 1:
        raise ValueError(f'{row.RowNo}행: 요청순번 {row.ReqSeq} 이 1 이상의 숫자가 아닙니다.')
    part_no, _dot, revision = (row.Item or '').rpartition('.')
    if not part_no or not revision or not row.ItemName:
        raise ValueError(f'{row.RowNo}행: 품목 {row.Item} 이 품번.리비전 모양이 아니거나 품목명이 비었습니다.')
    raw_qty = row.PoQty or row.ApprQty or row.ReqQty
    try:
        qty = Decimal(raw_qty)
    except (InvalidOperation, TypeError):
        qty = None
    if qty is None or not qty.is_finite() or qty <= 0:
        raise ValueError(f'{row.RowNo}행: 수량 {raw_qty} 은 0보다 큰 숫자여야 합니다.')
    dates = [_date(row, column) for column in DATE_COLUMNS]   # 쓰지 않는 칸도 형식을 본다
    values = {
        'ReqNo': row.ReqNo, 'ReqSeq': seq, 'ItemCode': row.Item, 'ItemName': row.ItemName, 'Spec': row.Spec,
        'Category': row.Category, 'Unit': row.Unit, 'Qty': qty,
        'ReceiptDate': next((d for d in dates if d), None),
        'VendorName': row.VendorPo or row.VendorAppr, 'ProjectNo': row.ProjectNo, 'ProjectName': row.ProjectName,
        'RequesterName': row.RequesterName, 'EoNo': row.EoNo,
    }
    return f'{row.ReqNo}-{seq}', part_no, revision, values


@transaction.atomic
def apply_purchase_req(batch):
    """수신건을 입고에 반영하고 건수 {RESULT_LABELS: n} 를 돌려준다. 틀리면 ValueError 이고 아무것도 바뀌지 않는다."""
    parsed = {}
    for row in batch.erp_rows.order_by('RowNo'):
        receipt_no, part_no, revision, values = _values(row)
        if receipt_no in parsed:
            raise ValueError(f'{row.RowNo}행: 입고번호 {receipt_no} 가 파일에 두 번 나옵니다.')
        parsed[receipt_no] = (part_no, revision, values)
    result = Counter({key: 0 for key in RESULT_LABELS})

    codes = {values['ItemCode'] for _part, _rev, values in parsed.values()}
    products = {p.Code: p for p in Product.objects.filter(Code__in=codes)}
    for part_no, revision, values in parsed.values():
        if values['ItemCode'] not in products:
            products[values['ItemCode']] = Product.objects.create(
                Code=values['ItemCode'], PartNo=part_no, Revision=revision, Name=values['ItemName'], Spec=values['Spec'])
            result['product_added'] += 1

    existing = {r.ReceiptNo: r for r in Receipt.objects.filter(ReceiptNo__in=parsed)}
    for receipt_no, (_part, _rev, values) in parsed.items():
        values = dict(values, Product_id=products[values['ItemCode']].id)
        receipt = existing.get(receipt_no)
        if receipt is None:
            Receipt.objects.create(ReceiptNo=receipt_no, Batch=batch, **values)
            result['receipt_added'] += 1
        elif any(getattr(receipt, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(receipt, k, v)
            receipt.Batch = batch
            receipt.save()
            result['receipt_updated'] += 1

    LogWriter.add_dblog('info', 'interface/apply_purchase_req', '수신건 {} 반영 — {}'.format(
        batch.id, ', '.join(f'{k} {result[k]}' for k in RESULT_LABELS)))
    return dict(result)


def with_target(queryset):
    """입고에 검사 대상(is_target — 품번에 수입검사 양식이 매핑됨)을 붙인다. 자재입고 검색 팝업이 거른다."""
    return queryset.annotate(is_target=Exists(ProductForm.objects.filter(PartNo=OuterRef('Product__PartNo'))))


def latest_forms(codes):
    """양식코드 → 사용 중인 최신 버전 {code: DigForm}. 가장 높은 버전이 사용 중(UseYN Y)이 아니면 없다(검사작성 양식 고르기와 같다)."""
    latest = {}
    for form in DigForm.objects.filter(Code__in=set(codes), FormType=INCOMING).order_by('Code', '-Version'):
        latest.setdefault(form.Code, form)
    return {code: form for code, form in latest.items() if form.UseYN == 'Y'}


def _mapped(keyword='', form_code=''):
    """매핑된 입고 — (입고 목록(최신순), {품번: [양식코드]}). 검색어는 입고번호·품목코드·품목명."""
    pairs = ProductForm.objects.all()
    if form_code:
        pairs = pairs.filter(FormCode=form_code)
    by_part = {}
    for part_no, code in pairs.order_by('FormCode').values_list('PartNo', 'FormCode'):
        by_part.setdefault(part_no, []).append(code)
    queryset = Receipt.objects.filter(Product__PartNo__in=by_part).select_related('Product')
    keyword = (keyword or '').strip()
    if keyword:
        queryset = queryset.filter(Q(ReceiptNo__icontains=keyword) | Q(ItemCode__icontains=keyword) | Q(ItemName__icontains=keyword))
    return list(queryset.order_by(F('ReceiptDate').desc(nulls_last=True), 'ReqNo', 'ReqSeq')), by_part


def _written(receipts):
    """{(양식코드, 입고번호): {작성 상태}} — 버전과 상관없이 그 코드로 쓴 수입검사 작성건."""
    written = {}
    rows = DigFormResult.objects.filter(DigForm__FormType=INCOMING, WorkOrderNumber__in=[r.ReceiptNo for r in receipts])
    for code, number, state in rows.values_list('DigForm__Code', 'WorkOrderNumber', 'State'):
        written.setdefault((code, number), set()).add(state)
    return written


def waiting_jobs(keyword='', form_code=''):
    """대기 작업 [(입고, 양식)] — 매핑 (품번, 양식코드) 의 입고 중 그 양식코드·입고번호로 쓴 작성건(상태 무관)이 없는 것.

    양식은 그 코드의 사용 중인 최신 버전(latest_forms) — 없으면 나오지 않는다. 입고일 최신순(설계 2026-10-21 §6).
    """
    # ponytail: 매핑된 입고 전부를 메모리에서 맞춘다 — 입고가 수만 건이면 (품번, 양식코드) 조인 SQL 로
    receipts, by_part = _mapped(keyword, form_code)
    forms = latest_forms({code for codes in by_part.values() for code in codes})
    written = _written(receipts)
    return [(r, forms[code]) for r in receipts for code in by_part[r.Product.PartNo]
            if code in forms and (code, r.ReceiptNo) not in written]


def job_counts():
    """검사 대기 배지 — {'waiting': 대기 작업 수, 'working': 매핑된 (입고, 양식코드) 중 작성 중이고 완료가 없는 수}."""
    receipts, by_part = _mapped()
    forms = latest_forms({code for codes in by_part.values() for code in codes})
    written = _written(receipts)
    waiting = working = 0
    for r in receipts:
        for code in by_part[r.Product.PartNo]:
            states = written.get((code, r.ReceiptNo))
            if states is None:
                waiting += code in forms
            elif 'working' in states and 'done' not in states:
                working += 1
    return {'waiting': waiting, 'working': working}


JOB_KIND_LABELS = {'WAITING': '대기', 'WORKING': '작성 중'}


def jobs(keyword='', form_code='', kind='', user_id=None):
    """수입검사 작성 목록 — 대기(입고일 최신순) 다음 작성 중(작성일 최신순, 입고와 무관한 수기 작성 포함).

    kind: '' 전체 · 'WAITING' · 'WORKING'. 검색어는 입고번호·품목코드·품목명(설계 2026-10-21 §6).
    작성 중 행은 작성 모달이 머리로 쓰는 값(write_date·header_values·is_mine — user_id 가 작성자인지)도 준다.
    """
    waiting = waiting_jobs(keyword, form_code) if kind in ('', 'WAITING') else []
    working = []
    if kind in ('', 'WORKING'):
        results = DigFormResult.objects.filter(DigForm__FormType=INCOMING, State='working').select_related('DigForm')
        if form_code:
            results = results.filter(DigForm__Code=form_code)
        working = list(results.order_by('-WriteDate', '-id'))
    found = {r.ReceiptNo: r for r in Receipt.objects.filter(ReceiptNo__in=[w.WorkOrderNumber for w in working if w.WorkOrderNumber])}
    word = (keyword or '').strip().casefold()
    if word:
        def hit(w):
            r = found.get(w.WorkOrderNumber)
            return any(word in (v or '').casefold() for v in (w.WorkOrderNumber, r and r.ItemCode, r and r.ItemName))
        working = [w for w in working if hit(w)]

    form_ids = {f.id for _r, f in waiting} | {w.DigForm_id for w in working}
    inputs = dict(DigFormItem.objects.filter(DigFormSection__DigForm_id__in=form_ids, InputYN='Y')
                  .values_list('DigFormSection__DigForm_id').annotate(n=Count('id')))
    values = dict(DigFormItemResult.objects.filter(DigFormResult__in=working)
                  .values_list('DigFormResult_id').annotate(n=Count('id')))
    users = {u.id: user_display_name(u) for u in User.objects.select_related('userprofile')
             .filter(id__in={w._modifier_id or w._creater_id for w in working})}
    rows = [_job('WAITING', receipt, form, inputs) for receipt, form in waiting]
    for w in working:
        row = _job('WORKING', found.get(w.WorkOrderNumber), w.DigForm, inputs)
        row.update({'receipt_no': w.WorkOrderNumber or '', 'result_id': w.id, 'round': w.Round,
                    'write_date': w.WriteDate.isoformat() if w.WriteDate else '',
                    'header_values': json.loads(w.HeaderValues or '{}'), 'is_mine': user_id is not None and w._creater_id == user_id,
                    'value_count': values.get(w.id, 0), 'writer_name': users.get(w._modifier_id or w._creater_id, ''),
                    'created': w._created.strftime('%Y-%m-%d %H:%M') if w._created else ''})
        rows.append(row)
    return rows


def _job(kind, receipt, form, inputs):
    return {
        'kind': kind, 'kind_label': JOB_KIND_LABELS[kind],
        'receipt_no': receipt.ReceiptNo if receipt else '',
        'receipt_date': receipt.ReceiptDate.isoformat() if receipt and receipt.ReceiptDate else '',
        'item_code': receipt.ItemCode if receipt else '', 'item_name': receipt.ItemName if receipt else '',
        'qty': format(receipt.Qty.normalize(), 'f') if receipt else '', 'vendor_name': (receipt.VendorName or '') if receipt else '',
        'form_id': form.id, 'form_code': form.Code, 'form_title': form.Title, 'form_version': form.Version,
        'result_id': None, 'round': None, 'value_count': 0, 'input_count': inputs.get(form.id, 0),
        'writer_name': '', 'created': '',
    }

