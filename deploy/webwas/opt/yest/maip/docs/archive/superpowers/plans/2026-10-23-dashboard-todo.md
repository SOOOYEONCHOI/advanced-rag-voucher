# 대시보드 내 할 일·현황 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로그인 첫 화면 대시보드를 "위: 메뉴 W 기준 내 할 일 / 아래: 메뉴 R 기준 현황" 의 실제 데이터 화면으로 바꾼다.

**Architecture:** 대시보드 자기 API `/api/vision/dashboard?action=summary` 하나가 `{todo, status}` 를 준다 — 칸마다 그 메뉴 권한을 확인하고 없으면 `null`. 화면(`vision/dashboard.html`)은 `null` 칸을 감춘다. 라벨링·검수는 비전검사항목 탭의 내부 탭이라, `data/item.html` 이 `?screen=<메뉴코드>` 로 처음 열 내부 탭을 받는다.

**Tech Stack:** Django 5.2(USE_TZ=False), jQuery, Bootstrap 5, Chart.js(저장소 vendor), Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-23-dashboard-todo-design.md`

## Global Constraints

- 마이그레이션·모델 변경 없음. `domain/gui.py` 매핑 변경 없음(경로 `vision/dashboard` 그대로)
- 다른 메뉴의 API 를 화면에서 부르지 않는다 — 값은 모두 `/api/vision/dashboard`
- todo 칸은 그 메뉴 **W**, status 칸은 그 메뉴 **R**(`AccountService.check_user_auth(user, menu)` 가 주는 문자열에 `'W'`/`'R'` 포함). 없으면 `null`
- RLS 테이블(`ImageAsset`·`LabelingTask`·`InspectionItem`·`VisionInspection` 조인)은 `tenant_atomic(current_tenant())` 안에서 읽는다 — 밖이면 조용히 0건
- 화면 값은 `.text()` / `$('<td>').text()` 로 넣는다. 문자열을 이어 `.html()` 하지 않는다
- 사용자 문구는 `~합니다` 체. 새 버튼 클래스를 만들지 않는다(보조 버튼 `.btn-input`)
- 기간 7일(오늘 포함), 상위 10건, 3일 초과 = 대기 경고 — 상수 `DAYS = 7`, `TOP = 10`, `OVERDUE_DAYS = 3`
- 테스트는 `--settings=configurations.test_settings`. 전체 단위·전체 e2e 는 돌리지 않는다
- e2e 데이터는 `E2E-` 접두사, 픽스처에서 지운다
- e2e 는 **워크트리 코드로 띄운 별도 서버**에 돌린다 — 8123 은 팀이 쓰는 main 작업 트리 서버다. 워크트리에 `.env` 가 없으면 `ln -s ../../.env .env`(커밋하지 않는다), `python manage.py runserver 127.0.0.1:8124` 를 백그라운드로 띄우고 `E2E_BASE_URL=http://127.0.0.1:8124 python -m pytest …` 로 돌린다. 끝나면 서버를 끈다
- 커밋: Conventional Commits, type 영문·설명 한국어, AI 표시 금지

## 파일 구조

| 파일 | 책임 | 작업 |
|---|---|---|
| `app/views/vision/dashboard.py` | 대시보드 API — 칸마다 권한 확인 → 값 | Task 1·2·3 |
| `tests/test_dashboard_api.py` | API 단위 테스트 | Task 1·2·3 |
| `app/templates/data/item.html` | `?screen=` 으로 처음 열 내부 탭 | Task 4 |
| `tests/e2e/test_data_screens.py` | `?screen=` e2e | Task 4 |
| `app/templates/vision/dashboard.html` | 화면 전체 다시 쓰기 | Task 5 |
| `tests/e2e/test_dashboard.py`(새) · `tests/e2e/test_data_register.py` | 대시보드 e2e | Task 5 |
| `docs/FEATURES.md` §10 · `docs/STATUS.md` · `docs/DECISIONS.md` | 문서 | Task 6 |

Task 1~3 동안 화면은 옛 응답 모양(`res.register`)을 읽어 등록 카드가 비어 보인다 — Task 5 에서 화면을 바꾼다(브랜치 안에서만, 병합 전).

---

### Task 1: API 틀 `{todo, status}` + 검사 작업 할 일

**Files:**
- Modify: `app/views/vision/dashboard.py` (전체 다시 쓰기)
- Modify: `tests/test_dashboard_api.py`

**Interfaces:**
- Produces: `dashboard(context)` → `{'todo': {'incoming', 'outgoing', 'working', 'labeling', 'review', 'items'}, 'status': {'inspection', 'register', 'vision'}}`. 이 Task 에서 `labeling`·`review`·`items`·`inspection`·`vision` 은 항상 `None`, `register` 는 지금 모양(`days`·`total`·`by_channel`·`by_item`) 그대로 `status` 아래로 옮긴다.
- 모듈 상수·헬퍼(뒤 Task 가 쓴다): `DAYS`, `TOP`, `OVERDUE_DAYS`, 메뉴 코드 상수, `_days()`.

- [ ] **Step 1: 실패하는 테스트 쓰기** — `tests/test_dashboard_api.py` 를 아래로 바꾼다(기존 두 테스트는 `status.register` 로 옮기고 todo·status 가 비는지도 본다).

```python
"""대시보드 자기 API — 위 할 일은 메뉴 W, 아래 현황은 메뉴 R 만큼 칸을 준다(설계 2026-10-23)."""
from datetime import date, timedelta

from django.test import override_settings

from domain.models.basic import Product, ProductForm, Receipt
from domain.models.dig_form import DigForm, DigFormResult
from domain.models.user import UserGroupMenu
from domain.services.data.image import ImageService
from domain.tenancy import tenant_atomic
from tests.test_data_services import make_image
from tests.test_item_api import AJAX, ItemApiTestCase


class DashboardTestCase(ItemApiTestCase):
    def summary(self, user):
        response = self.http(user).get('/api/vision/dashboard', {'action': 'summary'}, **AJAX)
        self.assertEqual(response.status_code, 200)
        return response.json()


@override_settings(API_AUTHZ_MODE='enforce')
class DashboardSummaryTest(DashboardTestCase):
    menus = {'wm_dashboard': 'RW', 'wm_data_register': 'R'}

    def test_등록_메뉴_R_이면_최근_7일_등록_요약을_준다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('a.png'), make_image('b.png', color=(1, 1, 1))], actor=self.manager)
        register = self.summary(self.manager)['status']['register']
        self.assertEqual((register['days'], register['total']), (7, 2))
        self.assertEqual(register['by_channel'], [{'label': '파일 업로드', 'count': 2}])

    def test_등록_메뉴_권한이_없으면_카드가_없다(self):
        UserGroupMenu.objects.filter(MenuCode='wm_data_register').delete()
        self.assertIsNone(self.summary(self.worker)['status']['register'])

    def test_다른_메뉴_권한이_없으면_할_일과_다른_현황_칸은_모두_null_이다(self):
        body = self.summary(self.manager)
        self.assertEqual(set(body['todo']), {'incoming', 'outgoing', 'working', 'labeling', 'review', 'items'})
        self.assertTrue(all(v is None for v in body['todo'].values()))
        self.assertIsNone(body['status']['inspection'])
        self.assertIsNone(body['status']['vision'])


@override_settings(API_AUTHZ_MODE='enforce')
class DashboardIncomingTodoTest(DashboardTestCase):
    menus = {'wm_dashboard': 'RW', 'wm_dig_form_incoming_write': 'RW', 'wm_dig_form_outgoing_write': 'R'}

    def test_수입검사_W_면_대기_3일_초과_작성_중_내_것을_센다(self):
        product = Product.objects.create(Code='MEC1.A', PartNo='MEC1', Revision='A', Name='브래킷')
        form = DigForm.objects.create(Code='DF-D1', Version=1, Title='가공품 성적서', FormType='INCOMING')
        ProductForm.objects.create(PartNo='MEC1', FormCode='DF-D1')
        today = date.today()
        for seq, days_ago in ((1, 5), (2, 1), (3, 0)):
            Receipt.objects.create(ReceiptNo=f'R1-{seq}', ReqNo='R1', ReqSeq=seq, Product=product, ItemCode=product.Code,
                                   ItemName=product.Name, Qty=1, ReceiptDate=today - timedelta(days=days_ago))
        DigFormResult.objects.create(DigForm=form, WriteDate=today, WorkOrderNumber='R1-3', _creater_id=self.manager.id)
        DigFormResult.objects.create(DigForm=form, WriteDate=today, WorkOrderNumber='MANUAL-1', _creater_id=self.worker.id)

        todo = self.summary(self.manager)['todo']
        incoming = todo['incoming']
        self.assertEqual({k: incoming[k] for k in ('waiting', 'overdue', 'working', 'mine')},
                         {'waiting': 2, 'overdue': 1, 'working': 2, 'mine': 1})
        # 대기 표는 입고일 오래된 순
        self.assertEqual([(j['receipt_no'], j['wait_days'], j['form_title']) for j in incoming['jobs']],
                         [('R1-1', 5, '가공품 성적서'), ('R1-2', 1, '가공품 성적서')])
        self.assertIsNone(todo['outgoing'])          # 품질검사 작성은 R 뿐
        # 작성 중 표는 내 것 먼저, 수입만(품질 W 없음)
        self.assertEqual([(w['kind_label'], w['work_order_number'], w['is_mine']) for w in todo['working']],
                         [('수입', 'R1-3', True), ('수입', 'MANUAL-1', False)])
        self.assertEqual(todo['working'][0]['menu'], 'wm_dig_form_incoming_write')


@override_settings(API_AUTHZ_MODE='enforce')
class DashboardOutgoingTodoTest(DashboardTestCase):
    menus = {'wm_dashboard': 'RW', 'wm_dig_form_outgoing_write': 'RW'}

    def test_품질검사_W_면_작성_중과_내_것을_세고_수입_칸은_없다(self):
        form = DigForm.objects.create(Code='DF-D2', Version=1, Title='Rotor 성적서', FormType='OUTGOING')
        incoming = DigForm.objects.create(Code='DF-D3', Version=1, Title='수입 양식', FormType='INCOMING')
        today = date.today()
        DigFormResult.objects.create(DigForm=form, WriteDate=today, WorkOrderNumber='WO-1', _creater_id=self.manager.id)
        DigFormResult.objects.create(DigForm=form, WriteDate=today, WorkOrderNumber='WO-2', State='done', _creater_id=self.manager.id)
        DigFormResult.objects.create(DigForm=incoming, WriteDate=today, WorkOrderNumber='R9-1', _creater_id=self.manager.id)

        todo = self.summary(self.manager)['todo']
        self.assertIsNone(todo['incoming'])
        self.assertEqual(todo['outgoing'], {'working': 1, 'mine': 1})
        self.assertEqual([(w['kind_label'], w['work_order_number'], w['menu']) for w in todo['working']],
                         [('품질', 'WO-1', 'wm_dig_form_outgoing_write')])
```

- [ ] **Step 2: 실패 확인**

Run: `python manage.py test tests.test_dashboard_api --settings=configurations.test_settings`
Expected: FAIL — `KeyError: 'status'` / `'todo'`

- [ ] **Step 3: 구현** — `app/views/vision/dashboard.py` 를 아래로 바꾼다.

```python
"""대시보드(`wm_dashboard`) 자기 API — 요청자의 메뉴 권한만큼 칸을 준다(다른 메뉴 API 를 부르면 그 권한이 없는 그룹에서 403).

위 "내 할 일"(todo)은 그 메뉴 W, 아래 "현황"(status)은 그 메뉴 R 이 있을 때 값이 있고 없으면 null 이다(설계 2026-10-23).
"""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.db.models import Count

from domain.models.data import ImageAsset
from domain.models.dig_form import DigFormItem, DigFormItemResult, DigFormResult
from domain.services import receipt as receipts
from domain.services.account import AccountService, user_display_name
from domain.tenancy import current_tenant, tenant_atomic

DAYS = 7
TOP = 10
OVERDUE_DAYS = 3

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
    return {
        'todo': {
            'incoming': _incoming(user) if 'INCOMING' in write_kinds else None,
            'outgoing': _outgoing(user) if 'OUTGOING' in write_kinds else None,
            'working': _working(user, write_kinds) if write_kinds else None,
            'labeling': None, 'review': None, 'items': None,
        },
        'status': {
            'inspection': None,
            'register': _register() if can(REGISTER_MENU, 'R') else None,
            'vision': None,
        },
    }


def _days():
    """오늘을 포함한 최근 DAYS 일 — 오래된 날부터."""
    today = date.today()
    return [today - timedelta(days=DAYS - 1 - i) for i in range(DAYS)]


def _incoming(user):
    """수입검사 작성 목록(receipts.jobs)과 같은 수 — 대기·3일 초과·작성 중·그중 내 것, 대기 상위 TOP(입고일 오래된 순)."""
    rows = receipts.jobs(user_id=user.id)
    today = date.today()
    waiting = [r for r in rows if r['kind'] == 'WAITING']
    working = [r for r in rows if r['kind'] == 'WORKING']

    def wait_days(row):
        return (today - date.fromisoformat(row['receipt_date'])).days if row['receipt_date'] else None

    oldest = sorted(waiting, key=lambda r: r['receipt_date'] or '9999-12-31')[:TOP]   # 입고일 없는 것은 뒤
    return {
        'waiting': len(waiting),
        'overdue': sum(1 for r in waiting if (wait_days(r) or 0) > OVERDUE_DAYS),
        'working': len(working),
        'mine': sum(1 for r in working if r['is_mine']),
        'jobs': [{'receipt_no': r['receipt_no'], 'receipt_date': r['receipt_date'], 'wait_days': wait_days(r),
                  'item_code': r['item_code'], 'item_name': r['item_name'], 'form_title': r['form_title']} for r in oldest],
    }


def _outgoing(user):
    rows = DigFormResult.objects.filter(DigForm__FormType='OUTGOING', State='working')
    return {'working': rows.count(), 'mine': rows.filter(_creater_id=user.id).count()}


def _working(user, kinds):
    """작성 중인 검사 상위 TOP — 내 것 먼저, 그다음 마지막 저장 최근 순. W 가 있는 구분만."""
    # ponytail: 작성 중 전부를 읽어 정렬한다 — 작성 중이 수천 건이면 SQL order by (작성자=나) 로
    rows = list(DigFormResult.objects.filter(DigForm__FormType__in=kinds, State='working')
                .select_related('DigForm').order_by('-_modified', '-id'))
    rows = sorted(rows, key=lambda r: r._creater_id != user.id)[:TOP]      # 안정 정렬 — 최근 순이 남는다
    inputs = dict(DigFormItem.objects.filter(DigFormSection__DigForm_id__in={r.DigForm_id for r in rows}, InputYN='Y')
                  .values_list('DigFormSection__DigForm_id').annotate(n=Count('id')))
    values = dict(DigFormItemResult.objects.filter(DigFormResult__in=rows)
                  .values_list('DigFormResult_id').annotate(n=Count('id')))
    names = {u.id: user_display_name(u) for u in User.objects.select_related('userprofile')
             .filter(id__in={r._modifier_id or r._creater_id for r in rows})}
    return [{
        'kind_label': KIND_LABELS[r.DigForm.FormType], 'menu': WRITE_MENUS[r.DigForm.FormType],
        'form_title': r.DigForm.Title, 'work_order_number': r.WorkOrderNumber or '',
        'writer_name': names.get(r._modifier_id or r._creater_id, ''),
        'value_count': values.get(r.id, 0), 'input_count': inputs.get(r.DigForm_id, 0),
        'saved': r._modified.strftime('%m-%d %H:%M') if r._modified else '', 'is_mine': r._creater_id == user.id,
    } for r in rows]


def _register():
    """최근 DAYS 일 비전 데이터 등록 — 합계·등록 경로별·비전검사항목 상위 5."""
    since = _days()[0]
    tenant = current_tenant()
    with tenant_atomic(tenant):
        images = ImageAsset.objects.for_tenant(tenant).filter(created_at__date__gte=since)
        labels = dict(ImageAsset.Channel.choices)
        by_channel = [{'label': labels[r['channel']], 'count': r['n']}
                      for r in images.values('channel').annotate(n=Count('id')).order_by('-n', 'channel')]
        by_item = [{'id': r['dataset__item_id'], 'code': r['dataset__item__code'], 'name': r['dataset__item__name'], 'count': r['n']}
                   for r in images.values('dataset__item_id', 'dataset__item__code', 'dataset__item__name')
                   .annotate(n=Count('id')).order_by('-n', 'dataset__item__code')[:5]]
        return {'days': DAYS, 'total': images.count(), 'by_channel': by_channel, 'by_item': by_item}
```

- [ ] **Step 4: 통과 확인**

Run: `python manage.py test tests.test_dashboard_api tests.test_receipt_jobs --settings=configurations.test_settings`
Expected: PASS (전부)

- [ ] **Step 5: 커밋**

```bash
git add app/views/vision/dashboard.py tests/test_dashboard_api.py
git commit -m "feat: 대시보드 API 를 할 일·현황으로 나누고 수입·품질검사 할 일을 메뉴 W 만큼 준다"
```

---

### Task 2: 비전 데이터 할 일(라벨링·검수·항목별 표)

**Files:**
- Modify: `app/views/vision/dashboard.py`
- Modify: `tests/test_dashboard_api.py`

**Interfaces:**
- Consumes: Task 1 의 `dashboard`, 메뉴 상수 `LABELING_MENU`, `REVIEW_MENU`.
- Produces: `todo.labeling = {'queue', 'rework', 'mine'} | None`, `todo.review = {'waiting'} | None`, `todo.items = [{'id','code','name', ('queue','rework','mine' — 라벨링 W 일 때), ('review' — 검수 W 일 때)}] | None` — Task 5 화면이 읽는다.

- [ ] **Step 1: 실패하는 테스트 추가** — `tests/test_dashboard_api.py` 끝에 붙이고, import 에 `from domain.models.data import ImageAsset, InspectionItem, LabelingTask` 를 더한다.

```python
@override_settings(API_AUTHZ_MODE='enforce')
class DashboardVisionDataTodoTest(DashboardTestCase):
    # 작업자 그룹은 검수 작업을 R 만 받는다(ItemApiTestCase.WRITER_ONLY)
    menus = {'wm_dashboard': 'RW', 'wm_data_labeling': 'RW', 'wm_data_review': 'RW'}

    def setUp(self):
        super().setUp()
        S = ImageAsset.LabelStatus
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image(f'{n}.png', color=(n, n, n)) for n in range(4)], actor=self.manager)
            images = list(ImageAsset.objects.for_tenant(self.tenant).filter(dataset__item=self.item).order_by('id'))
            for image, status in zip(images, (S.UNLABELED, S.REWORK, S.SUBMITTED, S.APPROVED)):
                ImageAsset.objects.for_tenant(self.tenant).filter(pk=image.pk).update(label_status=status)
            LabelingTask.objects.create(tenant=self.tenant, item=self.item, image=images[0], assignee=self.manager,
                                        status=LabelingTask.Status.IN_PROGRESS)
            # 치수 측정 항목은 라벨링을 하지 않는다 — 표에 나오지 않는다
            measure = InspectionItem.objects.create(tenant=self.tenant, code='MEAS', name='치수',
                                                    task_type=InspectionItem.TaskType.MEASUREMENT)
            ImageService.upload_images(measure, [make_image('m.png', color=(9, 9, 9))], actor=self.manager)

    def test_라벨링_검수_W_면_합계와_항목별_할_일을_준다(self):
        todo = self.summary(self.manager)['todo']
        self.assertEqual(todo['labeling'], {'queue': 2, 'rework': 1, 'mine': 1})
        self.assertEqual(todo['review'], {'waiting': 1})
        self.assertEqual(todo['items'], [{'id': self.item.id, 'code': 'API', 'name': 'API 검사',
                                          'queue': 2, 'rework': 1, 'mine': 1, 'review': 1}])

    def test_검수_W_가_없으면_검수_칸과_항목별_검수_열이_없다(self):
        todo = self.summary(self.worker)['todo']
        self.assertIsNone(todo['review'])
        self.assertEqual(todo['labeling'], {'queue': 2, 'rework': 1, 'mine': 0})   # 작업은 manager 가 잡았다
        self.assertNotIn('review', todo['items'][0])
```

- [ ] **Step 2: 실패 확인**

Run: `python manage.py test tests.test_dashboard_api.DashboardVisionDataTodoTest --settings=configurations.test_settings`
Expected: FAIL — `todo['labeling']` 이 `None`

- [ ] **Step 3: 구현** — `dashboard.py` 에 import 와 함수를 더하고 `dashboard()` 의 todo 를 바꾼다.

import 에 더한다:

```python
from django.db.models import Count, Q

from app.views.item.labeling import WORK_STATUSES
from domain.models.data import ImageAsset, InspectionItem, LabelingTask
from domain.services.data.image import ACTIVE_TASK_STATUSES
from domain.services.data.item_access import ItemAccessService
```

`dashboard()` 안 — `write_kinds` 아래에:

```python
    labeling_w, review_w = can(LABELING_MENU, 'W'), can(REVIEW_MENU, 'W')
    labeling = review = items = None
    if labeling_w or review_w:
        labeling, review, items = _vision_data(user, labeling_w, review_w)
```

그리고 todo 의 `'labeling': None, 'review': None, 'items': None,` 을 `'labeling': labeling, 'review': review, 'items': items,` 로 바꾼다.

함수:

```python
def _vision_data(user, labeling, review):
    """라벨링·검수 할 일 — (라벨링 합계 | None, 검수 합계 | None, 항목별 행). 치수 측정 항목은 라벨링이 없어 뺀다.

    라벨링 대기는 라벨링 화면 대기열과 같은 상태(WORK_STATUSES), 내 작업은 내가 잡은 진행 중 작업, 검수 대기는 제출됨이다.
    """
    S = ImageAsset.LabelStatus
    tenant = current_tenant()
    with tenant_atomic(tenant):
        items = list(ItemAccessService.visible_items(user=user, tenant=tenant)
                     .exclude(task_type=InspectionItem.TaskType.MEASUREMENT).order_by('display_order', 'code'))
        ids = [i.id for i in items]
        stats = {r.pop('dataset__item_id'): r for r in ImageAsset.objects.for_tenant(tenant)
                 .filter(dataset__item_id__in=ids).values('dataset__item_id').order_by().annotate(
                     queue=Count('id', filter=Q(label_status__in=WORK_STATUSES)),
                     rework=Count('id', filter=Q(label_status=S.REWORK)),
                     review=Count('id', filter=Q(label_status=S.SUBMITTED)))}
        mine = dict(LabelingTask.objects.for_tenant(tenant).filter(assignee=user, status__in=ACTIVE_TASK_STATUSES, item_id__in=ids)
                    .values_list('item_id').order_by().annotate(n=Count('id')))
    rows = []
    for item in items:
        s = stats.get(item.id, {})
        row = {'id': item.id, 'code': item.code, 'name': item.name}
        if labeling:
            row.update(queue=s.get('queue', 0), rework=s.get('rework', 0), mine=mine.get(item.id, 0))
        if review:
            row['review'] = s.get('review', 0)
        if row.get('queue') or row.get('mine') or row.get('review'):
            rows.append(row)
    rows.sort(key=lambda r: -(r.get('queue', 0) + r.get('review', 0)))     # 할 일 많은 순(같으면 메뉴 순서)

    def total(key):
        return sum(r.get(key, 0) for r in rows)
    return ({'queue': total('queue'), 'rework': total('rework'), 'mine': total('mine')} if labeling else None,
            {'waiting': total('review')} if review else None,
            rows)
```

- [ ] **Step 4: 통과 확인**

Run: `python manage.py test tests.test_dashboard_api --settings=configurations.test_settings`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/views/vision/dashboard.py tests/test_dashboard_api.py
git commit -m "feat: 대시보드 할 일에 비전 데이터 라벨링·검수 합계와 비전검사항목별 할 일을 메뉴 W 만큼 준다"
```

---

### Task 3: 현황 — 검사 완료·부적합 7일, 등록 7일 경로별, 최근 비전 검사

**Files:**
- Modify: `app/views/vision/dashboard.py`
- Modify: `tests/test_dashboard_api.py`

**Interfaces:**
- Consumes: Task 1 의 `_days()`, `DAYS`, `TOP`, 메뉴 상수.
- Produces(Task 5 화면이 읽는다):
  - `status.inspection = {'days': ['MM/DD'×7], 'incoming': [int×7] | None, 'outgoing': [int×7] | None, 'ng': [int×7]} | None`
  - `status.register = {'days': ['MM/DD'×7], 'total': int, 'series': [{'label': str, 'counts': [int×7]}]} | None` — **모양이 바뀐다**(`by_channel`·`by_item` 없음)
  - `status.vision = [inspection._row(row) …] | None` — 키 `created_at`·`item_name`·`client_id`·`status_label`·`abnormal` 를 화면이 쓴다

- [ ] **Step 1: 실패하는 테스트 쓰기**

`DashboardSummaryTest.test_등록_메뉴_R_이면_최근_7일_등록_요약을_준다` 를 아래로 바꾸고, `test_다른_메뉴_권한이_없으면…` 은 그대로 둔다:

```python
    def test_등록_메뉴_R_이면_최근_7일_등록을_경로별_날짜별로_준다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('a.png'), make_image('b.png', color=(1, 1, 1))], actor=self.manager)
        register = self.summary(self.manager)['status']['register']
        self.assertEqual(register['days'][-1], date.today().strftime('%m/%d'))
        self.assertEqual(register['total'], 2)
        self.assertEqual(register['series'], [{'label': '파일 업로드', 'counts': [0, 0, 0, 0, 0, 0, 2]}])
```

파일 끝에 붙인다(import 에 `import uuid`, `from datetime import datetime`, `from domain.models.dig_form import DigFormItem, DigFormItemResult, DigFormSection`, `from domain.models.vision import VisionClient, VisionInspection`, `from domain.services import judge_code` 를 더한다):

```python
@override_settings(API_AUTHZ_MODE='enforce')
class DashboardStatusTest(DashboardTestCase):
    menus = {'wm_dashboard': 'RW', 'wm_dig_form_incoming_result': 'R', 'wm_vis_inspection': 'R'}

    def done(self, form, days_ago, combo=None, item=None, state='done'):
        result = DigFormResult.objects.create(DigForm=form, WriteDate=date.today(), State=state)
        if combo:
            DigFormItemResult.objects.create(DigFormResult=result, DigFormItem=item, ComboResult=combo)
        # _modified 는 auto_now 라 만든 뒤 바꾼다 — 완료 시각
        DigFormResult.objects.filter(pk=result.pk).update(
            _modified=datetime.combine(date.today() - timedelta(days=days_ago), datetime.min.time().replace(hour=10)))

    def test_검사결과_R_구분만_7일_완료와_부적합_항목을_센다(self):
        judge_code.ensure_defaults()
        incoming = DigForm.objects.create(Code='DF-S1', Version=1, Title='수입', FormType='INCOMING', LayoutType='SECTION')
        outgoing = DigForm.objects.create(Code='DF-S2', Version=1, Title='품질', FormType='OUTGOING', LayoutType='SECTION')
        cells = {}
        for form in (incoming, outgoing):
            section = DigFormSection.objects.create(DigForm=form, SectionType='INSPECTION', Title='점검')
            cells[form.id] = DigFormItem.objects.create(DigFormSection=section, RowType='D', RowIndex=2, ColumnIndex=1,
                                                        ResultType='S', InputYN='Y', CodeGroup='dig_form_okng')
        self.done(incoming, 0, 'N', cells[incoming.id])          # 오늘 완료 · 부적합 1
        self.done(incoming, 2, 'Y', cells[incoming.id])          # 2일 전 완료 · 적합
        self.done(incoming, 0, state='working')                  # 작성 중 — 세지 않는다
        self.done(outgoing, 0, 'N', cells[outgoing.id])          # 품질 결과 R 없음 — 세지 않는다
        inspection = self.summary(self.manager)['status']['inspection']
        self.assertEqual(inspection['incoming'], [0, 0, 0, 0, 1, 0, 1])
        self.assertIsNone(inspection['outgoing'])
        self.assertEqual(inspection['ng'], [0, 0, 0, 0, 0, 0, 1])

    def test_비전_검사_이력_R_이면_최근_검사를_준다(self):
        with tenant_atomic(self.tenant):
            client = VisionClient.objects.create(client_id='CLIENT-D', name='라인 1', api_key_hash='x' * 64)
            key = str(uuid.uuid4())
            VisionInspection.objects.create(id=key, request_id=key, client=client, item=self.item,
                                            status=VisionInspection.Status.SUCCESS, abnormal=True)
        vision = self.summary(self.manager)['status']['vision']
        self.assertEqual([(v['item_name'], v['client_id'], v['abnormal']) for v in vision], [('API 검사', 'CLIENT-D', True)])
        self.assertIsNone(self.summary(self.manager)['status']['register'])     # 등록 메뉴 R 없음
```

`ResultType='S'` 가 판정(콤보) 칸이 아니면 `domain/models/dig_form.py:78` 주석(T/N/S/B)과 `tests/test_dig_form.py` 의 판정 칸 만드는 곳을 보고 판정 칸 타입으로 맞춘다 — 집계는 타입을 보지 않고 `CodeGroup`·`ComboResult` 만 본다.

- [ ] **Step 2: 실패 확인**

Run: `python manage.py test tests.test_dashboard_api --settings=configurations.test_settings`
Expected: FAIL — `register['series']` KeyError, `inspection`·`vision` 이 `None`

- [ ] **Step 3: 구현**

import 에 더한다:

```python
from collections import Counter
from datetime import date, datetime, time, timedelta

from app.views.vision.inspection import _row as inspection_row
from domain.models.vision import VisionInspection
from domain.services import judge_code
from domain.services.sql import DbUtil
```

`dashboard()` 안 — `return` 앞에:

```python
    read_kinds = [kind for kind, menu in (('INCOMING', INCOMING_RESULT), ('OUTGOING', OUTGOING_RESULT)) if can(menu, 'R')]
```

status 를 바꾼다:

```python
        'status': {
            'inspection': _inspection(read_kinds) if read_kinds else None,
            'register': _register() if can(REGISTER_MENU, 'R') else None,
            'vision': _vision() if can(VISION_MENU, 'R') else None,
        },
```

`_register()` 를 바꾸고 두 함수를 더한다:

```python
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
            'series': [{'label': label, 'counts': [counts[(channel, d)] for d in days]}
                       for channel, label in ImageAsset.Channel.choices if channel in used]}


def _vision():
    """최근 비전 검사 TOP 건 — 비전 검사 이력 목록과 같은 행 모양."""
    with tenant_atomic(current_tenant()):
        return [inspection_row(r) for r in VisionInspection.objects.select_related('item', 'client').order_by('-created_at')[:TOP]]
```

Task 1 의 `from datetime import date, timedelta` 는 위 import 로 바꾼다. 쓰지 않게 된 import 는 지운다.

- [ ] **Step 4: 통과 확인**

Run: `python manage.py test tests.test_dashboard_api tests.test_vision_inspection_filters --settings=configurations.test_settings`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/views/vision/dashboard.py tests/test_dashboard_api.py
git commit -m "feat: 대시보드 현황에 7일 검사 완료·부적합, 7일 등록 경로별, 최근 비전 검사를 메뉴 R 만큼 준다"
```

---

### Task 4: 비전검사항목 탭이 `?screen=` 으로 처음 열 내부 탭을 받는다

**Files:**
- Modify: `app/templates/data/item.html` (`render(item)` 끝)
- Modify: `tests/e2e/test_data_screens.py`

**Interfaces:**
- Produces: `/gui/wm_data_item_detail/?inspection_item=<id>&screen=<메뉴코드>` — 권한 있는 내부 탭이면 처음 그릴 때 그 탭을 연다. 이미 열린 탭은 `page.showScreen(code)`(있는 메서드)로 바꾼다 — Task 5 가 쓴다.

- [ ] **Step 1: 실패하는 e2e 쓰기** — `tests/e2e/test_data_screens.py` 의 `test_최근_데이터와_전체_보기는_내부_탭으로_연다` 바로 아래에:

```python
def test_주소의_screen_으로_처음_열_내부_탭을_고른다(admin, base_url, demo):
    """대시보드의 [라벨링]·[검수]가 그 항목 탭의 내부 탭을 바로 연다(설계 2026-10-23)."""
    page = admin
    mid = f"item{demo['det']}_wm_data_item_detail"
    page.wait_for_timeout(1500)
    page.evaluate(f"() => window.myMenu.openMenu('{mid}', '비전검사항목', "
                  f"'/gui/wm_data_item_detail/?inspection_item={demo['det']}&screen=wm_data_labeling')")
    home = page.frame_locator(f'.mnb-tab-panel[data-mid="{mid}"] iframe')
    home.locator('#itemFrames .item-frame[data-screen="wm_data_labeling"]').wait_for(state='visible', timeout=5000)
    assert home.locator('#itemTabs .nav-link.active').inner_text() == '라벨링 작업'
    assert home.locator('#paneHome').is_hidden()
```

- [ ] **Step 2: 실패 확인** (워크트리 서버 8124 — Global Constraints)

Run: `E2E_BASE_URL=http://127.0.0.1:8124 python -m pytest tests/e2e/test_data_screens.py -q -k "screen"`
Expected: FAIL — 라벨링 프레임이 보이지 않는다(timeout)

- [ ] **Step 3: 구현** — `item.html` 의 `render(item)` 맨 끝(`$('#imageLink').toggleClass(...)` 줄 아래)에:

```js
            // 대시보드가 ?screen=<메뉴코드> 로 연 내부 탭 — 처음 그릴 때 한 번, 권한 있는 탭만(없으면 홈)
            if (!this.screenOpened) {
                this.screenOpened = true;
                const first = new URLSearchParams(location.search).get('screen');
                if (first && granted.indexOf(first) >= 0) { this.showScreen(first); }
            }
```

- [ ] **Step 4: 통과 확인**

Run: `E2E_BASE_URL=http://127.0.0.1:8124 python -m pytest tests/e2e/test_data_screens.py -q`
Expected: PASS (파일 전체 — 같은 화면의 다른 테스트가 깨지지 않았는지)

- [ ] **Step 5: 커밋**

```bash
git add app/templates/data/item.html tests/e2e/test_data_screens.py
git commit -m "feat: 비전검사항목 탭이 주소의 screen 으로 처음 열 내부 탭을 고른다"
```

---

### Task 5: 대시보드 화면 다시 쓰기

**Files:**
- Modify: `app/templates/vision/dashboard.html` (전체 다시 쓰기)
- Create: `tests/e2e/test_dashboard.py`
- Modify: `tests/e2e/test_data_register.py` (`test_대시보드_등록_카드를_누르면_등록_탭이_열린다`)

**Interfaces:**
- Consumes: Task 1~3 응답 모양, Task 4 의 `?screen=`·`page.showScreen(code)`, 셸 `window.parent.myMenu`(`$leftSideNavi`, `openMenu(id, title, url)`, `leafTitle($link)`).
- 요소 id(e2e 가 쓴다): `#todoSection`, `#todoIncoming`, `#todoOutgoing`, `#todoLabeling`, `#todoReview`, `#jobsBody`, `#workingBody`, `#itemsCard`, `#todoItems`, `#statusSection`, `#inspectionCard`, `#registerCard`, `#visionCard`, `#nothing`. 메뉴를 여는 요소는 `[data-menu="<메뉴코드>"]`, 항목 버튼은 `button[data-item][data-screen]`.

- [ ] **Step 1: 실패하는 e2e 쓰기** — `tests/e2e/test_dashboard.py`:

```python
"""대시보드 — 할 일 카드·항목 버튼이 그 메뉴 탭을 연다. 자기 항목(E2E-DASH)만 만들고 지운다."""
import pytest

from tests.e2e.conftest import login, manage_shell

MAKE = ("import io\n"
        "from PIL import Image\n"
        "from django.core.files.uploadedfile import SimpleUploadedFile\n"
        "from domain.tenancy import tenant_atomic, current_tenant\n"
        "from domain.models.data import InspectionItem\n"
        "from domain.services.data.image import ImageService\n"
        "buf = io.BytesIO(); Image.new('RGB', (64, 48), (11, 22, 33)).save(buf, format='PNG')\n"
        "t = current_tenant()\n"
        "with tenant_atomic(t):\n"
        "    item = InspectionItem.objects.create(tenant=t, code='E2E-DASH', name='E2E 대시보드', task_type='OBJECT_DETECTION', status='ACTIVE')\n"
        "    ImageService.upload_images(item, [SimpleUploadedFile('e2e-dash.png', buf.getvalue(), content_type='image/png')])\n"
        "    print(item.id)")
CLEAN = ("from domain.tenancy import tenant_atomic\n"
         "from domain.models.data import InspectionItem\n"
         "from domain.services.data.item_platform import ItemPlatformService\n"
         "with tenant_atomic():\n"
         "    ids = list(InspectionItem.objects.filter(code='E2E-DASH').values_list('id', flat=True))\n"
         "for item_id in ids: ItemPlatformService.delete_item(item_id)")


@pytest.fixture
def e2e_item():
    manage_shell(CLEAN)            # 지난 실행이 남긴 것
    item_id = int(manage_shell(MAKE).strip().splitlines()[-1])
    yield item_id
    manage_shell(CLEAN)


def dashboard(page, base_url, admin_password):
    login(page, base_url, 'admin', admin_password)
    page.goto(f'{base_url}/', wait_until='networkidle')
    frame = page.frame_locator('iframe[id="mnb_iframe_wm_dashboard"]')
    frame.locator('#todoSection').wait_for(state='visible')
    return frame


def test_수입검사_카드를_누르면_수입검사_작성_탭이_열린다(page, base_url, admin_password):
    frame = dashboard(page, base_url, admin_password)
    frame.locator('#todoIncoming').click()
    page.wait_for_selector('.mnb-tab-panel.active[data-mid="wm_dig_form_incoming_write"]')
    errors = [e for e in page.console_errors if 'Failed to load resource' not in e]
    assert not errors, errors


def test_항목의_라벨링_버튼은_그_항목_탭의_라벨링_내부_탭을_연다(page, base_url, admin_password, e2e_item):
    frame = dashboard(page, base_url, admin_password)
    frame.locator('#todoItems tr', has_text='E2E-DASH').locator('button[data-screen="wm_data_labeling"]').click()
    mid = f'item{e2e_item}_wm_data_item_detail'
    page.wait_for_selector(f'.mnb-tab-panel.active[data-mid="{mid}"]')
    home = page.frame_locator(f'.mnb-tab-panel[data-mid="{mid}"] iframe')
    home.locator('#itemFrames .item-frame[data-screen="wm_data_labeling"]').wait_for(state='visible', timeout=5000)
    assert home.locator('#itemTabs .nav-link.active').inner_text() == '라벨링 작업'
    # 탭 화면(전체 목록)에는 다른 PC 저장소의 이미지가 섞일 수 있다 — 썸네일 404 는 보지 않는다
    errors = [e for e in page.console_errors if 'Failed to load resource' not in e]
    assert not errors, errors
```

`tests/e2e/test_data_register.py` 의 `test_대시보드_등록_카드를_누르면_등록_탭이_열린다` 에서
`frame.locator('#registerCard .dashboard-stat').click()` 을 `frame.locator('#registerCard [data-menu]').click()` 로 바꾼다(나머지 그대로).

- [ ] **Step 2: 실패 확인**

Run: `E2E_BASE_URL=http://127.0.0.1:8124 python -m pytest tests/e2e/test_dashboard.py -q`
Expected: FAIL — `#todoSection` 이 없다(timeout)

- [ ] **Step 3: 구현** — `app/templates/vision/dashboard.html` 을 아래로 바꾼다.

```html
{% extends "app/layout_page.html" %}
{% load static %}

{% block css %}
<style>
    /* 할 일 카드 — 숫자가 먼저 읽히게 크게, 설명은 작게. 0건은 흐리게 두고 자리는 그대로 */
    .dashboard-section { font-size: 14px; font-weight: 700; color: var(--brand-ink); margin: 4px 0 8px; }
    .dashboard-stat { padding: 12px 16px; }
    .dashboard-stat .stat-label { font-size: 12px; color: var(--brand-muted); }
    .dashboard-stat .stat-value { font-size: 26px; font-weight: 700; color: var(--brand-ink); line-height: 1.3; }
    .dashboard-stat .stat-note { font-size: 12px; color: var(--brand-muted); }
    .dashboard-stat.is-waiting .stat-value { color: var(--brand-warning-ink); }
    .dashboard-stat.is-empty .stat-value { color: var(--brand-muted); font-size: 16px; }
    [data-menu] { cursor: pointer; }
    [data-menu]:focus-visible { outline: 2px solid var(--brand-ink); outline-offset: 2px; }
    /* 차트는 칸 높이를 정해 두고 그 안에 맞춘다(Chart.js maintainAspectRatio:false) */
    .dashboard-chart { position: relative; height: 240px; }
    .dashboard-table td, .dashboard-table th { white-space: nowrap; }
    .dashboard-overdue { color: var(--brand-warning-ink); font-weight: 700; }
    .dashboard-mine td { font-weight: 700; }
</style>
{% endblock %}

{% block content %}
<!-- 대시보드 — 로그인 첫 화면. 위는 그 메뉴 W 가 있는 할 일, 아래는 그 메뉴 R 이 있는 현황(설계 2026-10-23).
     값은 대시보드 자기 API 가 메뉴 권한만큼 준다(null 인 칸은 감춘 그대로) — 다른 메뉴 API 를 부르면 권한 없는 그룹에서 403 -->
<div class="card">
    <div class="d-flex card-header justify-content-between align-items-center">
        <h4 class="header-title">
            <span data-labelCd="{{ gui.gui_name }}">{{ gui.gui_name }}</span>
            <a href="javascript:void(0);"><i class="uil uil-favorite favorite-off"></i></a>
        </h4>
    </div>
    <div class="card-body py-2">
        <p class="text-muted mb-0" id="screenDescription">처리할 일과 현황입니다. 메뉴 권한이 있는 것만 보입니다.</p>
    </div>
</div>

<section class="d-none" id="todoSection">
    <div class="dashboard-section">내 할 일</div>
    <div class="row g-2 mb-2">
        <div class="col-6 col-lg d-none"><div class="card mb-0 h-100 dashboard-stat" id="todoIncoming" data-menu="wm_dig_form_incoming_write" role="button" tabindex="0">
            <div class="stat-label">검사 작업 · 수입검사</div><div class="stat-value"></div><div class="stat-note"></div></div></div>
        <div class="col-6 col-lg d-none"><div class="card mb-0 h-100 dashboard-stat" id="todoOutgoing" data-menu="wm_dig_form_outgoing_write" role="button" tabindex="0">
            <div class="stat-label">검사 작업 · 품질검사</div><div class="stat-value"></div><div class="stat-note"></div></div></div>
        <div class="col-6 col-lg d-none"><div class="card mb-0 h-100 dashboard-stat" id="todoLabeling">
            <div class="stat-label">비전 데이터 · 라벨링</div><div class="stat-value"></div><div class="stat-note"></div></div></div>
        <div class="col-6 col-lg d-none"><div class="card mb-0 h-100 dashboard-stat" id="todoReview">
            <div class="stat-label">비전 데이터 · 검수</div><div class="stat-value"></div><div class="stat-note"></div></div></div>
    </div>
    <div class="row g-2 mb-2">
        <div class="col-12 col-xl-6 d-none" id="jobsCard">
            <div class="card mb-0 p-15 h-100">
                <div class="sub-tit mb-2">새로 작업할 수입검사</div>
                <table class="table table-bordered table-sm align-middle mb-0 dashboard-table">
                    <thead><tr><th>입고번호</th><th>입고일</th><th>품목</th><th>양식</th><th class="text-end">대기</th></tr></thead>
                    <tbody id="jobsBody"></tbody>
                </table>
            </div>
        </div>
        <div class="col-12 col-xl-6 d-none" id="workingCard">
            <div class="card mb-0 p-15 h-100">
                <div class="sub-tit mb-2">작성 중인 검사</div>
                <table class="table table-bordered table-sm align-middle mb-0 dashboard-table">
                    <thead><tr><th>구분</th><th>양식</th><th>입고번호/WO</th><th>작성자</th><th>진행</th><th>마지막 저장</th></tr></thead>
                    <tbody id="workingBody"></tbody>
                </table>
            </div>
        </div>
    </div>
    <div class="card mb-2 p-15 d-none" id="itemsCard">
        <div class="sub-tit mb-2">라벨링·검수할 비전검사항목</div>
        <table class="table table-bordered table-sm align-middle mb-0 dashboard-table">
            <thead><tr><th>비전검사항목</th>
                <th class="text-end col-labeling">라벨링 대기</th><th class="text-end col-labeling">재작업</th><th class="text-end col-labeling">내 작업</th>
                <th class="text-end col-review">검수 대기</th><th>열기</th></tr></thead>
            <tbody id="todoItems"></tbody>
        </table>
    </div>
</section>

<section class="d-none" id="statusSection">
    <div class="dashboard-section">현황</div>
    <div class="card mb-2 p-15 d-none" id="inspectionCard">
        <div class="sub-tit mb-2">최근 7일 검사 완료 · 부적합</div>
        <div class="dashboard-chart"><canvas id="chartInspection" aria-label="최근 7일 검사 완료 막대 차트" role="img"></canvas></div>
    </div>
    <div class="row g-2 mb-2">
        <div class="col-12 col-xl-6 d-none" id="registerCard">
            <div class="card mb-0 p-15 h-100">
                <div class="sub-tit mb-2" data-menu="wm_data_register" role="button" tabindex="0">최근 7일 비전 데이터 등록 <span id="registerTotal"></span></div>
                <div class="dashboard-chart"><canvas id="chartRegister" aria-label="최근 7일 비전 데이터 등록 막대 차트" role="img"></canvas></div>
            </div>
        </div>
        <div class="col-12 col-xl-6 d-none" id="visionCard">
            <div class="card mb-0 p-15 h-100">
                <div class="sub-tit mb-2" data-menu="wm_vis_inspection" role="button" tabindex="0">최근 비전 검사 이력</div>
                <table class="table table-bordered table-sm align-middle mb-0 dashboard-table">
                    <thead><tr><th>검사 시각</th><th>비전검사항목</th><th>판정</th><th>클라이언트</th></tr></thead>
                    <tbody id="visionBody"></tbody>
                </table>
            </div>
        </div>
    </div>
</section>

<p class="text-muted d-none" id="nothing">볼 수 있는 할 일과 현황이 없습니다. 메뉴 권한이 필요하면 관리자에게 요청합니다.</p>
{% endblock %}

{% block scripts %}
<script src="{% static 'assets/vendor/chart.js/chart.umd.js' %}"></script>
<script type="text/javascript">
    // 색은 토큰에서 읽는다(DESIGN §2.1) — 회색 단계 + 대기(주황)·이상(오류 빨강) 신호만 쓴다
    class DashboardPage {
        init() {
            const _this = this;
            $(document).on('click', '[data-menu]', function () { _this.openMenu($(this).attr('data-menu')); });
            $(document).on('keydown', '[data-menu]', function (e) {
                if (e.target === this && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); _this.openMenu($(this).attr('data-menu')); }
            });
            $('#todoItems').on('click', 'button[data-screen]', function () {
                _this.openItem($(this).attr('data-item'), $(this).attr('data-screen'));
            });
            this.setupChart();
            AjaxUtil.getAsyncData('/api/vision/dashboard', { action: 'summary' }, function (res) {
                if (!res || !res.todo) { return; }
                const shown = function (o) { return Object.keys(o).some(function (k) { return o[k] !== null; }); };
                $('#todoSection').toggleClass('d-none', !shown(res.todo));
                $('#statusSection').toggleClass('d-none', !shown(res.status));
                $('#nothing').toggleClass('d-none', shown(res.todo) || shown(res.status));
                _this.renderTodo(res.todo);
                _this.renderStatus(res.status);
            });
        }

        // 셸 좌측 메뉴의 그 메뉴 탭을 연다. 메뉴에 없으면(권한 없음) 열지 않는다
        openMenu(menuCode) {
            const shell = window.parent !== window && window.parent.myMenu;
            if (!shell) { return; }
            const $link = shell.$leftSideNavi.find('.menu-leaf-link[data-mid="' + menuCode + '"]');
            if (!$link.length) { return; }
            shell.openMenu(menuCode, shell.leafTitle($link), $link.attr('data-url'));
        }

        // 비전검사항목 탭의 내부 탭(라벨링·검수). 좌측 메뉴의 그 항목 링크로 탭을 열고, 링크가 항목 홈이면 ?screen= 을 붙인다.
        // 이미 열린 탭이면 그 화면의 내부 탭만 바꾼다. 홈 권한이 없어 링크가 다른 하위 화면이면 그 링크를 그대로 연다
        openItem(itemId, screen) {
            const shell = window.parent !== window && window.parent.myMenu;
            if (!shell) { return; }
            const $link = shell.$leftSideNavi.find('.menu-leaf-link[data-mid^="item' + itemId + '_"]').first();
            if (!$link.length) { return; }
            const mid = $link.attr('data-mid');
            const home = mid === 'item' + itemId + '_wm_data_item_detail';
            const url = $link.attr('data-url') + (home ? '&screen=' + encodeURIComponent(screen) : '');
            const frame = window.parent.document.getElementById('mnb_iframe_' + mid);
            shell.openMenu(mid, shell.leafTitle($link), url);
            if (home && frame && frame.contentWindow.page) { frame.contentWindow.page.showScreen(screen); }
        }

        // 할 일 카드 하나. 권한이 있으면(값이 null 이 아니면) 보이고, 0건이면 흐리게 "할 일 없음"
        card(id, count, value, note, warn) {
            const $card = $('#' + id);
            $card.parent().removeClass('d-none');
            $card.toggleClass('is-empty', !count).toggleClass('is-waiting', !!count && !!warn);
            $card.find('.stat-value').text(count ? value : '할 일 없음');
            $card.find('.stat-note').text(count ? note : '');
        }

        emptyRow(cols, message) {
            return $('<tr>').append($('<td>', { colspan: cols, 'class': 'text-muted text-center' }).text(message));
        }

        renderTodo(t) {
            if (t.incoming) {
                const i = t.incoming;
                this.card('todoIncoming', i.waiting + i.working, '대기 ' + i.waiting + '건',
                          '3일 넘게 ' + i.overdue + '건 · 작성 중 ' + i.working + '건(내 것 ' + i.mine + '건)', i.overdue > 0);
                $('#jobsCard').removeClass('d-none');
                $('#jobsBody').empty().append(i.jobs.length ? i.jobs.map(function (j) {
                    const days = j.wait_days === null ? '-' : (j.wait_days === 0 ? '오늘' : j.wait_days + '일');
                    return $('<tr>', { 'data-menu': 'wm_dig_form_incoming_write', tabindex: 0 }).append(
                        $('<td>').text(j.receipt_no), $('<td>').text(j.receipt_date || '-'),
                        $('<td>').text(j.item_code + ' · ' + j.item_name), $('<td>').text(j.form_title),
                        $('<td>', { 'class': 'text-end' + (j.wait_days > 3 ? ' dashboard-overdue' : '') }).text(days));
                }) : this.emptyRow(5, '새로 작업할 수입검사가 없습니다.'));
            }
            if (t.outgoing) {
                this.card('todoOutgoing', t.outgoing.working, '작성 중 ' + t.outgoing.working + '건', '내 것 ' + t.outgoing.mine + '건');
            }
            if (t.working) {
                $('#workingCard').removeClass('d-none');
                $('#workingBody').empty().append(t.working.length ? t.working.map(function (w) {
                    return $('<tr>', { 'data-menu': w.menu, tabindex: 0, 'class': w.is_mine ? 'dashboard-mine' : '' }).append(
                        $('<td>').text(w.kind_label), $('<td>').text(w.form_title), $('<td>').text(w.work_order_number || '-'),
                        $('<td>').text(w.writer_name || '-'), $('<td>').text(w.value_count + '/' + w.input_count + ' 칸'),
                        $('<td>').text(w.saved));
                }) : this.emptyRow(6, '작성 중인 검사가 없습니다.'));
            }
            if (t.labeling) {
                const l = t.labeling;
                this.card('todoLabeling', l.queue + l.mine, '대기 ' + l.queue + '건', '재작업 ' + l.rework + '건 · 내 작업 ' + l.mine + '건', l.rework > 0);
            }
            if (t.review) {
                this.card('todoReview', t.review.waiting, '검수 대기 ' + t.review.waiting + '건', '');
            }
            if (t.items) {
                const labeling = !!t.labeling, review = !!t.review;
                $('#itemsCard').removeClass('d-none');
                $('#itemsCard .col-labeling').toggleClass('d-none', !labeling);
                $('#itemsCard .col-review').toggleClass('d-none', !review);
                const cols = 2 + (labeling ? 3 : 0) + (review ? 1 : 0);
                $('#todoItems').empty().append(t.items.length ? t.items.map(function (r) {
                    const button = function (screen, text) {
                        return $('<button>', { type: 'button', 'class': 'btn btn-input me-1', 'data-item': r.id, 'data-screen': screen }).text(text);
                    };
                    return $('<tr>').append(
                        $('<td>').text(r.code + ' · ' + r.name),
                        labeling ? [$('<td>', { 'class': 'text-end' }).text(r.queue), $('<td>', { 'class': 'text-end' }).text(r.rework),
                                    $('<td>', { 'class': 'text-end' }).text(r.mine)] : null,
                        review ? $('<td>', { 'class': 'text-end' }).text(r.review) : null,
                        $('<td>').append(labeling ? button('wm_data_labeling', '라벨링') : null, review ? button('wm_data_review', '검수') : null));
                }) : this.emptyRow(cols, '라벨링·검수할 비전검사항목이 없습니다.'));
            }
        }

        renderStatus(s) {
            const c = this.colors;
            const sum = function (list) { return list.reduce(function (a, b) { return a + b; }, 0); };
            if (s.inspection) {
                const i = s.inspection;
                $('#inspectionCard').removeClass('d-none');
                const bars = [['수입검사 완료', i.incoming, c.ink], ['품질검사 완료', i.outgoing, c.lineStrong]].filter(function (b) { return b[1]; });
                if (!sum(bars.map(function (b) { return sum(b[1]); }))) {
                    this.noData('#inspectionCard');
                } else {
                    new Chart(document.getElementById('chartInspection'), {
                        data: {
                            labels: i.days,
                            // order 가 작을수록 위에 그린다 — 부적합 선을 막대 위에
                            datasets: [{ type: 'line', label: '부적합 항목', data: i.ng, borderColor: c.danger, backgroundColor: c.danger,
                                         tension: 0.3, pointRadius: 3, yAxisID: 'y1', order: 0 }].concat(bars.map(function (b) {
                                return { type: 'bar', label: b[0], data: b[1], backgroundColor: b[2], stack: 'done', maxBarThickness: 36, order: 1 };
                            }))
                        },
                        options: {
                            interaction: { mode: 'index', intersect: false },
                            scales: {
                                x: { stacked: true, grid: { display: false } },
                                y: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: '완료(건)' } },
                                y1: { position: 'right', beginAtZero: true, suggestedMax: 5, ticks: { precision: 0 }, grid: { display: false },
                                      title: { display: true, text: '부적합(건)' } }
                            },
                            plugins: { legend: { position: 'top', align: 'end' } }
                        }
                    });
                }
            }
            if (s.register) {
                $('#registerCard').removeClass('d-none');
                $('#registerTotal').text('· ' + s.register.total.toLocaleString() + '장');
                if (!s.register.total) {
                    this.noData('#registerCard');
                } else {
                    const palette = [c.ink, c.muted, c.lineStrong, c.line];
                    new Chart(document.getElementById('chartRegister'), {
                        type: 'bar',
                        data: { labels: s.register.days, datasets: s.register.series.map(function (x, n) {
                            return { label: x.label, data: x.counts, backgroundColor: palette[n % palette.length], stack: 'image', maxBarThickness: 36 };
                        }) },
                        options: {
                            scales: { x: { stacked: true, grid: { display: false } },
                                      y: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: '등록(장)' } } },
                            plugins: { legend: { position: 'top', align: 'end' } }
                        }
                    });
                }
            }
            if (s.vision) {
                $('#visionCard').removeClass('d-none');
                $('#visionBody').empty().append(s.vision.length ? s.vision.map(function (v) {
                    const judgement = v.abnormal === true ? '이상' : (v.abnormal === false ? '정상' : v.status_label);
                    return $('<tr>').append($('<td>').text(v.created_at), $('<td>').text(v.item_name),
                        $('<td>', { 'class': v.abnormal === true ? 'text-danger fw-bold' : '' }).text(judgement), $('<td>').text(v.client_id));
                }) : this.emptyRow(4, '비전 검사 기록이 없습니다.'));
            }
        }

        // 기록이 없는 차트는 빈 축 대신 한 줄 안내
        noData(selector) {
            $(selector).find('.dashboard-chart').replaceWith($('<p>', { 'class': 'text-muted mb-0' }).text('최근 7일 기록이 없습니다.'));
        }

        setupChart() {
            const css = getComputedStyle(document.documentElement);
            const token = function (name) { return css.getPropertyValue(name).trim(); };
            this.colors = {
                ink: token('--brand-ink'), muted: token('--brand-muted'), lineStrong: token('--brand-line-strong'),
                line: token('--brand-line'), danger: token('--brand-danger')
            };
            Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
            Chart.defaults.color = this.colors.muted;
            Chart.defaults.borderColor = this.colors.line;
            Chart.defaults.maintainAspectRatio = false;
            Chart.defaults.plugins.legend.labels.boxWidth = 12;
        }
    }

    let page = new DashboardPage();
    $(document).ready(function () { page.init(); });
</script>
{% endblock %}
```

- [ ] **Step 4: 통과 확인**

Run:
```bash
E2E_BASE_URL=http://127.0.0.1:8124 python -m pytest tests/e2e/test_dashboard.py tests/e2e/test_data_register.py -q
node scripts/verify/verify_screen_js.js
python scripts/verify/verify_response_keys.py
python scripts/verify/verify_tokens.py
python scripts/verify/verify_korean_only.py
```
Expected: 모두 PASS. `verify_modals`·`verify_buttons` 는 주소가 8123 고정이라 워크트리에서는 main 코드를 본다 — 병합한 뒤 main 에서 돌린다(최종 단계). `verify_buttons` 가 항목 행 버튼 형태를 문제 삼으면 DESIGN §5.2 표에서 역할에 맞는 기존 클래스로 바꾼다(새 클래스 금지).

- [ ] **Step 5: 커밋**

```bash
git add app/templates/vision/dashboard.html tests/e2e/test_dashboard.py tests/e2e/test_data_register.py
git commit -m "feat: 대시보드 화면을 내 할 일·현황 실제 데이터로 바꾸고 예시 값을 지운다"
```

---

### Task 6: 문서

**Files:**
- Modify: `docs/FEATURES.md` (§1 메뉴 트리의 대시보드 줄 "지금은 예시 값만 보이는 데모(§10)", §10 전체)
- Modify: `docs/STATUS.md` (1번 표의 대시보드 줄 "등록 카드만 실제", 7-1 줄)
- Modify: `docs/DECISIONS.md` (사용자 결정 2026-10-23 줄 하나 추가 — 기존 2026-10-23 비전 데이터 등록 줄 ⑤ 바로 아래)

- [ ] **Step 1: FEATURES §10 을 다시 쓴다** — 아래 내용만 담는다(같은 내용을 다른 곳에 쓰지 않는다):
  - 근거: DECISIONS 사용자 결정 2026-10-21·2026-10-23
  - 로그인 첫 화면. 위 **내 할 일**(그 메뉴 W), 아래 **현황**(그 메뉴 R). 값은 `/api/vision/dashboard`(`summary`) 하나가 메뉴 권한만큼 주고 없는 칸은 감춘다 — 다른 메뉴 API 를 부르면 권한 없는 그룹에서 403
  - 할 일 카드 4개(이름은 "메뉴 폴더 · 일")와 값 정의 — 수입검사 수는 수입검사 작성 목록과 같고 좌측 배지와 작성 중 수가 다를 수 있다(배지는 매핑 안 된 수기 작성을 뺀다). 0건 카드는 흐리게
  - 표 3개: 새로 작업할 수입검사(입고일 오래된 순 10건, 3일 초과 강조), 작성 중인 검사(내 것 먼저 10건), 라벨링·검수할 비전검사항목([라벨링]·[검수] → 그 항목 탭의 내부 탭, `?screen=`)
  - 현황 3개: 7일 검사 완료(수입·품질 누적 막대)·부적합 항목 선, 7일 비전 데이터 등록(경로별 누적 막대), 최근 비전 검사 10건. 완료 시각·부적합 정의
  - 카드·표 행·현황 제목을 누르면 그 메뉴 탭이 열린다(좌측 메뉴에 없으면 열지 않는다)
  - Chart.js 는 이 화면에서만, 색은 토큰
  - 아직 없는 것: 승인 대기(검사 승인 STATUS 6 ②), 품질검사 대기(작업지시 6 ①)
- [ ] **Step 2: STATUS** — 대시보드가 데모라는 문장을 "할 일·현황 실제 데이터"로 바꾸고, 7-1 은 남은 것(승인 대기·작업지시 대기 — 6 ①② 뒤)만 남긴다
- [ ] **Step 3: DECISIONS** — 한 줄: `| 사용자 결정(2026-10-23) | **대시보드를 내 할 일(메뉴 W)·현황(메뉴 R) 실제 데이터로 바꾼다** — ① 할 일은 담당자 배정이 없어 메뉴 W 기준 전체 대기 + 내 것 강조 ② 0건 카드는 흐리게 ③ 카드 이름은 "메뉴 폴더 · 일" ④ 라벨링·검수는 비전검사항목별 표에서 그 항목 탭의 내부 탭으로 간다(`?screen=`) ⑤ 현황은 7일 검사 완료·부적합, 7일 등록 경로별, 최근 비전 검사만 ⑥ 운영 할 일·삭제 승인·승인 대기·작업지시·도넛·이상률 등은 넣지 않는다 | 로그인하면 할 일을 먼저 본다. 예시 값 데모를 걷어 낸다 |`
- [ ] **Step 4: 검증**

Run: `python scripts/verify/verify_links.py && python scripts/verify/verify_naming.py && python scripts/verify/verify_korean_only.py`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add docs/FEATURES.md docs/STATUS.md docs/DECISIONS.md
git commit -m "docs: 대시보드 할 일·현황을 FEATURES·STATUS·DECISIONS 에 반영한다"
```

구현을 모두 마치고 병합 전에 설계·계획을 `docs/archive/superpowers/specs`·`plans` 로 옮기는 커밋을 따로 한다(`git mv`).
