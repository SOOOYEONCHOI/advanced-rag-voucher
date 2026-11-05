"""대시보드(`wm_dashboard`) 자기 API — 요청자의 메뉴 권한만큼 칸을 준다(다른 메뉴 API 를 부르면 그 권한이 없는 그룹에서 403).

할 일(todo)은 그 메뉴 W, 현황(status)은 그 메뉴 R 이 있을 때 값이 있고 없으면 null 이다(설계 2026-10-23, 화면 보완 2026-10-23).
"""
from collections import Counter
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q
from django.urls import reverse

from app.views.item.labeling import WORK_STATUSES
from app.views.vision.inspection import _row as inspection_row
from domain.models.data import ImageAsset, InspectionItem
from domain.models.dig_form import DigFormItemResult, DigFormResult
from domain.models.vision import VisionInspection
from domain.services import judge_code, receipt as receipts
from domain.services.account import AccountService
from domain.services.data.item_access import ItemAccessService
from domain.services.sql import DbUtil
from domain.tenancy import current_tenant, tenant_atomic

DAYS = 7
ROWS = 5

INCOMING_WRITE, OUTGOING_WRITE = 'wm_dig_form_incoming_write', 'wm_dig_form_outgoing_write'
INCOMING_RESULT, OUTGOING_RESULT = 'wm_dig_form_incoming_result', 'wm_dig_form_outgoing_result'
LABELING_MENU, REVIEW_MENU = 'wm_data_labeling', 'wm_data_review'
REGISTER_MENU, VISION_MENU = 'wm_data_register', 'wm_vis_inspection'
WRITE_MENUS = {'INCOMING': INCOMING_WRITE, 'OUTGOING': OUTGOING_WRITE}
KIND_LABELS = {'INCOMING': '수입', 'OUTGOING': '품질'}


def dashboard(context):
    """api/vision/dashboard"""
    if context.gparam.get('action', 'summary') != 'summary':
        return {'success': False, 'message': '지원하지 않는 기능입니다.'}
    user = context.request.user

    def can(menu, mode):
        return mode in (AccountService.check_user_auth(user, menu) or '')

    write_kinds = [kind for kind, menu in WRITE_MENUS.items() if can(menu, 'W')]
    read_kinds = [kind for kind, menu in (('INCOMING', INCOMING_RESULT), ('OUTGOING', OUTGOING_RESULT)) if can(menu, 'R')]
    inspection = jobs = vision = images = None
    if write_kinds:
        inspection, jobs = _inspection_work(write_kinds)
    labeling_w, review_w = can(LABELING_MENU, 'W'), can(REVIEW_MENU, 'W')
    if labeling_w or review_w:
        vision, images = _vision_data(user, labeling_w, review_w)
    return {
        'todo': {'inspection': inspection, 'jobs': jobs, 'vision': vision, 'images': images},
        'status': {
            'month_done': _month_done(read_kinds) if read_kinds else None,
            'month_images': _month_images() if can(REGISTER_MENU, 'R') else None,
            'inspection': _inspection(read_kinds) if read_kinds else None,
            'register': _register() if can(REGISTER_MENU, 'R') else None,
            'vision': _vision() if can(VISION_MENU, 'R') else None,
        },
    }


def _days():
    """오늘을 포함한 최근 DAYS 일 — 오래된 날부터."""
    today = date.today()
    return [today - timedelta(days=DAYS - 1 - i) for i in range(DAYS)]


def _month_start():
    return datetime.combine(date.today().replace(day=1), time())


def _inspection_work(kinds):
    """검사 작업 — 구분별 할 일 수({수입: 대기+작성 중, 품질: 작성 중}, W 없는 구분은 None)와 대기·작성 중 최근 ROWS 행.

    대기는 수입검사 작성 목록과 같은 계산(receipts.waiting_jobs)이고 입고일로, 작성 중은 마지막 저장으로 최근 순을 정한다.
    """
    waiting = receipts.waiting_jobs() if 'INCOMING' in kinds else []
    working = list(DigFormResult.objects.filter(DigForm__FormType__in=kinds, State='working').select_related('DigForm'))
    counts = Counter(r.DigForm.FormType for r in working)
    rows = [(datetime.combine(receipt.ReceiptDate, time()) if receipt.ReceiptDate else datetime.min, {
        'state_label': '대기', 'kind_label': KIND_LABELS['INCOMING'], 'menu': INCOMING_WRITE, 'number': receipt.ReceiptNo,
        'title': form.Title, 'when': receipt.ReceiptDate.isoformat() if receipt.ReceiptDate else '',
    }) for receipt, form in waiting]
    rows += [(r._modified or r._created, {
        'state_label': '작성 중', 'kind_label': KIND_LABELS[r.DigForm.FormType], 'menu': WRITE_MENUS[r.DigForm.FormType],
        'number': r.WorkOrderNumber or '', 'title': r.DigForm.Title,
        'when': (r._modified or r._created).strftime('%Y-%m-%d %H:%M'),
    }) for r in working]
    rows.sort(key=lambda pair: pair[0], reverse=True)
    return ({'incoming': len(waiting) + counts['INCOMING'] if 'INCOMING' in kinds else None,
             'outgoing': counts['OUTGOING'] if 'OUTGOING' in kinds else None},
            [row for _when, row in rows[:ROWS]])


def _vision_data(user, labeling, review):
    """비전 데이터 할 일 — 수({라벨링: 대기열, 검수: 검수 대기}, W 없는 쪽은 None)와 라벨링 대기 이미지 최근 ROWS 장(라벨링 W).

    라벨링 대기열은 라벨링 화면과 같은 상태(WORK_STATUSES), 검수 대기는 제출됨이다. 치수 측정 항목은 라벨링이 없어 뺀다.
    """
    tenant = current_tenant()
    with tenant_atomic(tenant):
        items = ItemAccessService.visible_items(user=user, tenant=tenant).exclude(task_type=InspectionItem.TaskType.MEASUREMENT)
        images = ImageAsset.objects.for_tenant(tenant).filter(dataset__item__in=items)
        counts = images.aggregate(labeling=Count('id', filter=Q(label_status__in=WORK_STATUSES)),
                                  review=Count('id', filter=Q(label_status=ImageAsset.LabelStatus.SUBMITTED)))
        recent = list(images.filter(label_status__in=WORK_STATUSES).select_related('dataset__item')
                      .order_by('-created_at', '-id')[:ROWS]) if labeling else None
    rows = None if recent is None else [{
        'id': image.id, 'item_id': image.dataset.item_id, 'item_name': image.dataset.item.name,
        'status_label': image.get_label_status_display(), 'created_at': image.created_at.strftime('%Y-%m-%d %H:%M'),
        'thumbnail_url': _thumbnail_url(image),
    } for image in recent]
    return ({'labeling': counts['labeling'] if labeling else None, 'review': counts['review'] if review else None}, rows)


def _thumbnail_url(image):
    """썸네일 주소 — 파일이 이 서버에 없으면(공유 개발 DB 의 다른 PC 저장소 행 등) 빈 값이라 화면이 404 를 내지 않는다."""
    field = image.thumbnail or image.file
    return reverse('private-image-thumbnail', args=[image.id]) if field and field.storage.exists(field.name) else ''


def _month_done(kinds):
    """이번 달 완료 검사 수 — 구분별(R 없는 구분은 None). 완료 시각은 _inspection 과 같다."""
    counts = dict(DigFormResult.objects.filter(State='done', DigForm__FormType__in=kinds, _modified__gte=_month_start())
                  .values_list('DigForm__FormType').order_by().annotate(n=Count('id')))
    return {'incoming': counts.get('INCOMING', 0) if 'INCOMING' in kinds else None,
            'outgoing': counts.get('OUTGOING', 0) if 'OUTGOING' in kinds else None}


def _month_images():
    """이번 달 등록 이미지 — 합계, 처리(검수 완료), 미처리(라벨링하는 항목의 나머지 — 치수 측정은 라벨링이 없어 빼고 합계에만 든다)."""
    tenant = current_tenant()
    with tenant_atomic(tenant):
        approved = Q(label_status=ImageAsset.LabelStatus.APPROVED)
        counts = ImageAsset.objects.for_tenant(tenant).filter(created_at__gte=_month_start()).aggregate(
            total=Count('id'), done=Count('id', filter=approved),
            pending=Count('id', filter=~approved & ~Q(dataset__item__task_type=InspectionItem.TaskType.MEASUREMENT)))
    return counts


def _labels(days):
    return [d.strftime('%m/%d') for d in days]


def _inspection(kinds):
    """최근 DAYS 일 날짜별 완료 수(구분별, R 없는 구분은 None)·부적합 항목 수(R 있는 구분만).

    완료 시각은 완료 작성건의 마지막 저장(_modified) — 완료한 검사는 고칠 수 없다(dig_form save 가 막는다).
    부적합 = 항목결과 콤보 값의 판정 코드 의미가 N.
    """
    days = _days()
    done = DigFormResult.objects.filter(State='done', DigForm__FormType__in=kinds,
                                        _modified__gte=datetime.combine(days[0], time()))
    counts = Counter(done.values_list('DigForm__FormType', '_modified__date'))
    ng_codes = {(r['code_group'], r['code']) for r in DbUtil.get_rows(judge_code.OPTION_SQL + ''' where o."Type" = 'N' ''')}
    ng = Counter(day for day, group, code in DigFormItemResult.objects.filter(DigFormResult__in=done, ComboResult__isnull=False)
                 .values_list('DigFormResult___modified__date', 'DigFormItem__CodeGroup', 'ComboResult')
                 if (group, code) in ng_codes)

    def series(kind):
        return [counts[(kind, d)] for d in days] if kind in kinds else None
    return {'days': _labels(days), 'incoming': series('INCOMING'), 'outgoing': series('OUTGOING'), 'ng': [ng[d] for d in days]}


def _register():
    """최근 DAYS 일 비전 데이터 등록 — 날짜별·등록 경로별 장수(있는 경로만, Channel 순서)."""
    days = _days()
    tenant = current_tenant()
    with tenant_atomic(tenant):
        rows = list(ImageAsset.objects.for_tenant(tenant).filter(created_at__date__gte=days[0])
                    .values_list('channel', 'created_at__date'))
    counts = Counter(rows)
    used = {channel for channel, _day in rows}
    return {'days': _labels(days), 'total': len(rows),
            'series': [{'code': channel, 'label': label, 'counts': [counts[(channel, d)] for d in days]}
                       for channel, label in ImageAsset.Channel.choices if channel in used]}


def _vision():
    """최근 비전 검사 ROWS 건 — 비전 검사 이력 목록과 같은 행 모양 + 썸네일 주소(이미지가 없거나 파일이 없으면 빈 값)."""
    with tenant_atomic(current_tenant()):
        rows = VisionInspection.objects.select_related('item', 'client', 'image_asset').order_by('-created_at')[:ROWS]
        return [dict(inspection_row(r), thumbnail_url=_thumbnail_url(r.image_asset) if r.image_asset else '') for r in rows]
