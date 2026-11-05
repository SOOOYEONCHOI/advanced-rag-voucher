"""입고 내역 (`wm_receipt`, 기준정보) — 조회 전용. 입고는 ERP 구매요청 현황(= 입고의뢰) 반영(`apply_interface`)으로만 들어온다.

검사 정보(양식·상태)는 주지 않는다 — 수입 검사는 수입검사 작성의 검사 작업 목록이 다룬다(설계 2026-10-21 §6).
수입검사 작성의 자재입고 검색 팝업도 이 API 를 부른다(`target_only=Y` — 품목 검사양식이 매핑된 품번의 입고만).
그래서 매핑이 입고 내역·수입검사 작성 두 메뉴다(gui.py).
"""
from datetime import datetime

from django.db.models import F, Q

from app.views.item import paged
from domain.models.basic import Receipt
from domain.services import receipt as receipts
from domain.services.logging import LogWriter


def receipt(context):
    """api/definition/receipt"""
    gparam = context.gparam
    action = gparam.get('action', 'list')
    try:
        if action == 'list':
            return _list(gparam)
        raise ValueError('action: ' + str(action))
    except Exception as ex:
        LogWriter.add_dblog('error', 'definition/receipt : action-{}'.format(action), ex)
        return {'success': False, 'message': '입고 정보를 불러오지 못했습니다.'}


def _list(gparam):
    queryset = receipts.with_target(Receipt.objects.all()).order_by(
        F('ReceiptDate').desc(nulls_last=True), 'ReqNo', 'ReqSeq')
    keyword = (gparam.get('keyword') or '').strip()
    if keyword:
        queryset = queryset.filter(Q(ReceiptNo__icontains=keyword) | Q(ItemCode__icontains=keyword) | Q(ItemName__icontains=keyword))
    project = (gparam.get('project') or '').strip()
    if project:
        queryset = queryset.filter(Q(ProjectNo__icontains=project) | Q(ProjectName__icontains=project))
    if gparam.get('date_from'):
        queryset = queryset.filter(ReceiptDate__gte=datetime.fromisoformat(gparam['date_from']).date())
    if gparam.get('date_to'):
        queryset = queryset.filter(ReceiptDate__lte=datetime.fromisoformat(gparam['date_to']).date())
    if gparam.get('target_only') == 'Y':
        queryset = queryset.filter(is_target=True)
    return paged(queryset, gparam, _row, default_size=50)


def _row(r):
    return {
        'id': r.id, 'receipt_no': r.ReceiptNo, 'receipt_date': r.ReceiptDate.isoformat() if r.ReceiptDate else '',
        'item_code': r.ItemCode, 'item_name': r.ItemName, 'spec': r.Spec, 'category': r.Category, 'unit': r.Unit,
        'qty': format(r.Qty.normalize(), 'f'), 'vendor_name': r.VendorName, 'project_no': r.ProjectNo,
        'project_name': r.ProjectName, 'eo_no': r.EoNo,
    }
