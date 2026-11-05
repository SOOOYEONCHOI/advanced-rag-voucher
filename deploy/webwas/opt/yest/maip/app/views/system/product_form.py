"""수입검사 품목 지정 (`wm_product_form`) — 수입검사 양식마다 검사할 품번(리비전 무관)을 맞춘다. 품번 : 양식 = N : M.

매핑한 (품번, 양식) 의 입고가 수입검사 작성 목록의 대기 작업이 된다(설계 2026-10-21 §6).
검사할 때는 그 코드의 사용 중인 최신 버전을 연다.

| action   | 메서드 | 입력 |
|----------|--------|------|
| forms    | GET    | — 수입 양식(사용 중인 최신 버전)과 매핑 품목 수 |
| items    | GET    | form_code — 그 양식에 매핑한 품번 |
| products | GET    | exclude(JSON 배열), keyword — 화면 목록에 없는 품번(100건까지). [수정] 중 바꾼 것은 저장 전이라 화면이 보낸다 |
| save     | POST   | form_code, part_nos(JSON 배열) — 그 양식의 품목을 이 목록으로 맞춘다 |
"""
import json
from collections import Counter

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q

from domain.models.basic import Product, ProductForm
from domain.models.dig_form import DigForm
from domain.services import receipt as receipts
from domain.services.logging import LogWriter

WRITE_ACTIONS = frozenset({'save'})
PRODUCT_LIMIT = 100


def product_form(context):
    """api/system/product_form"""
    gparam = context.gparam
    action = gparam.get('action', 'forms')
    # MES 계열 API 는 HTTP 메서드로 R/W 를 가른다. 쓰기 action 을 GET 으로 부르면 읽기 권한만으로 통과하므로 막는다
    if action in WRITE_ACTIONS and context.request.method != 'POST':
        raise PermissionDenied
    try:
        if action == 'forms':
            return _forms()
        if action == 'items':
            parts = ProductForm.objects.filter(FormCode=gparam.get('form_code') or '').values_list('PartNo', flat=True)
            return [_row(p) for p in _latest(Product.objects.filter(PartNo__in=list(parts))).values()]
        if action == 'products':
            queryset = Product.objects.exclude(PartNo__in=json.loads(gparam.get('exclude') or '[]'))
            keyword = (gparam.get('keyword') or '').strip()
            if keyword:
                queryset = queryset.filter(Q(PartNo__icontains=keyword) | Q(Name__icontains=keyword))
            return [_row(p) for p in list(_latest(queryset).values())[:PRODUCT_LIMIT]]
        if action == 'save':
            return _save(context.posparam)
        raise ValueError('action: ' + str(action))
    except Exception as ex:
        LogWriter.add_dblog('error', 'system/product_form : action-{}'.format(action), ex)
        return {'success': False, 'message': '처리 중 오류가 발생했습니다.'}


def _forms():
    codes = DigForm.objects.filter(FormType=receipts.INCOMING).values_list('Code', flat=True)
    counts = Counter(ProductForm.objects.values_list('FormCode', flat=True))
    return [{'code': f.Code, 'title': f.Title, 'version': f.Version, 'item_count': counts[f.Code]}
            for f in sorted(receipts.latest_forms(codes).values(), key=lambda f: f.Code)]


def _latest(queryset):
    """품번 → 가장 나중에 만든 품목(리비전). 품번순."""
    # ponytail: 품번 전부를 메모리에서 고른다 — 품목이 수만 건이 되면 DISTINCT ON(PartNo) SQL 로
    latest = {}
    for product in queryset.order_by('PartNo', '-id'):
        latest.setdefault(product.PartNo, product)
    return latest


def _row(product):
    return {'part_no': product.PartNo, 'name': product.Name, 'part_type': product.PartType, 'spec': product.Spec}


def _save(posparam):
    code = (posparam.get('form_code') or '').strip()
    if code not in receipts.latest_forms([code]):
        return {'success': False, 'message': '사용 중인 수입검사 양식을 골라 주세요.'}
    part_nos = {str(p).strip() for p in json.loads(posparam.get('part_nos') or '[]')}
    known = set(Product.objects.filter(PartNo__in=part_nos).values_list('PartNo', flat=True))
    missing = sorted(part_nos - known)
    if missing:
        return {'success': False, 'message': '품번을 찾을 수 없습니다: ' + ', '.join(missing)}
    with transaction.atomic():
        removed, _ = ProductForm.objects.filter(FormCode=code).exclude(PartNo__in=part_nos).delete()
        mapped = set(ProductForm.objects.filter(FormCode=code).values_list('PartNo', flat=True))
        new = sorted(part_nos - mapped)
        ProductForm.objects.bulk_create([ProductForm(PartNo=p, FormCode=code) for p in new])
    return {'success': True, 'message': '', 'added': len(new), 'removed': removed}
