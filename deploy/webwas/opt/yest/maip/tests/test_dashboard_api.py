"""대시보드 자기 API — 할 일은 메뉴 W, 현황은 메뉴 R 만큼 칸을 준다(설계 2026-10-23, 화면 보완 2026-10-23)."""
import uuid
from datetime import date, datetime, time, timedelta

from django.test import override_settings

from domain.models.basic import Product, ProductForm, Receipt
from domain.models.data import ImageAsset, InspectionItem
from domain.models.dig_form import DigForm, DigFormItem, DigFormItemResult, DigFormResult, DigFormSection
from domain.models.user import UserGroupMenu
from domain.models.vision import VisionClient, VisionInspection
from domain.services import judge_code
from domain.services.data.image import ImageService
from domain.tenancy import tenant_atomic
from tests.test_data_services import make_image
from tests.test_item_api import AJAX, ItemApiTestCase


def at(day, hour=10):
    return datetime.combine(day, time(hour))


class DashboardTestCase(ItemApiTestCase):
    def summary(self, user):
        response = self.http(user).get('/api/vision/dashboard', {'action': 'summary'}, **AJAX)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def done_at(self, result, when):
        # _modified 는 auto_now 라 만든 뒤 바꾼다 — 완료 시각·마지막 저장
        DigFormResult.objects.filter(pk=result.pk).update(_modified=when)


@override_settings(API_AUTHZ_MODE='enforce')
class DashboardSummaryTest(DashboardTestCase):
    menus = {'wm_dashboard': 'RW', 'wm_data_register': 'R'}

    def test_등록_메뉴_R_이면_최근_7일_등록을_경로별_날짜별로_준다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('a.png'), make_image('b.png', color=(1, 1, 1))], actor=self.manager)
        register = self.summary(self.manager)['status']['register']
        self.assertEqual(register['days'][-1], date.today().strftime('%m/%d'))
        self.assertEqual(register['total'], 2)
        self.assertEqual(register['series'], [{'code': 'FILE', 'label': '파일 업로드', 'counts': [0, 0, 0, 0, 0, 0, 2]}])   # 색은 경로 코드를 따른다

    def test_이번_달_수집은_합계와_검수_완료_처리_나머지_미처리다_치수_측정은_미처리가_아니다(self):
        S = ImageAsset.LabelStatus
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image(f'{n}.png', color=(n, n, n)) for n in range(3)], actor=self.manager)
            measure = InspectionItem.objects.create(tenant=self.tenant, code='MEAS', name='치수',
                                                    task_type=InspectionItem.TaskType.MEASUREMENT)
            ImageService.upload_images(measure, [make_image('m.png', color=(9, 9, 9))], actor=self.manager)
            images = ImageAsset.objects.for_tenant(self.tenant).filter(dataset__item=self.item).order_by('id')
            ImageAsset.objects.for_tenant(self.tenant).filter(pk=images[0].pk).update(label_status=S.APPROVED)
            # 지난달 등록 — 세지 않는다
            last_month = at(date.today().replace(day=1) - timedelta(days=1))
            ImageAsset.objects.for_tenant(self.tenant).filter(pk=images[2].pk).update(created_at=last_month)
        self.assertEqual(self.summary(self.manager)['status']['month_images'], {'total': 3, 'pending': 1, 'done': 1})

    def test_등록_메뉴_권한이_없으면_등록_칸이_없다(self):
        UserGroupMenu.objects.filter(MenuCode='wm_data_register').delete()
        status = self.summary(self.worker)['status']
        self.assertIsNone(status['register'])
        self.assertIsNone(status['month_images'])

    def test_다른_메뉴_권한이_없으면_할_일과_다른_현황_칸은_모두_null_이다(self):
        body = self.summary(self.manager)
        self.assertEqual(set(body['todo']), {'inspection', 'jobs', 'vision', 'images'})
        self.assertTrue(all(v is None for v in body['todo'].values()))
        self.assertEqual(set(body['status']), {'month_done', 'month_images', 'inspection', 'register', 'vision'})
        for key in ('month_done', 'inspection', 'vision'):
            self.assertIsNone(body['status'][key])


@override_settings(API_AUTHZ_MODE='enforce')
class DashboardInspectionTodoTest(DashboardTestCase):
    menus = {'wm_dashboard': 'RW', 'wm_dig_form_incoming_write': 'RW', 'wm_dig_form_outgoing_write': 'RW'}

    def setUp(self):
        super().setUp()
        product = Product.objects.create(Code='MEC1.A', PartNo='MEC1', Revision='A', Name='브래킷')
        self.incoming = DigForm.objects.create(Code='DF-D1', Version=1, Title='가공품 성적서', FormType='INCOMING')
        self.outgoing = DigForm.objects.create(Code='DF-D2', Version=1, Title='Rotor 성적서', FormType='OUTGOING')
        ProductForm.objects.create(PartNo='MEC1', FormCode='DF-D1')
        today = date.today()
        for seq, days_ago in ((1, 5), (2, 1), (3, 0)):
            Receipt.objects.create(ReceiptNo=f'R1-{seq}', ReqNo='R1', ReqSeq=seq, Product=product, ItemCode=product.Code,
                                   ItemName=product.Name, Qty=1, ReceiptDate=today - timedelta(days=days_ago))
        write = DigFormResult.objects.create
        self.done_at(write(DigForm=self.incoming, WriteDate=today, WorkOrderNumber='R1-3', _creater_id=self.manager.id),
                     at(today, 9))
        self.done_at(write(DigForm=self.outgoing, WriteDate=today, WorkOrderNumber='WO-1', _creater_id=self.worker.id),
                     at(today - timedelta(days=3)))
        write(DigForm=self.outgoing, WriteDate=today, WorkOrderNumber='WO-2', State='done')      # 완료 — 할 일이 아니다

    def test_수입은_대기와_작성_중_품질은_작성_중을_센다(self):
        # 수입 대기 R1-1·R1-2 + 작성 중 R1-3, 품질 작성 중 WO-1
        self.assertEqual(self.summary(self.manager)['todo']['inspection'], {'incoming': 3, 'outgoing': 1})

    def test_대기와_작성_중을_섞어_최근_순으로_5개까지_준다(self):
        jobs = self.summary(self.manager)['todo']['jobs']
        self.assertEqual([(j['state_label'], j['kind_label'], j['number']) for j in jobs],
                         [('작성 중', '수입', 'R1-3'), ('대기', '수입', 'R1-2'), ('작성 중', '품질', 'WO-1'), ('대기', '수입', 'R1-1')])
        self.assertNotIn('is_mine', jobs[0])
        self.assertEqual({j['menu'] for j in jobs}, {'wm_dig_form_incoming_write', 'wm_dig_form_outgoing_write'})
        self.assertEqual(jobs[1]['title'], '가공품 성적서')


@override_settings(API_AUTHZ_MODE='enforce')
class DashboardOutgoingOnlyTodoTest(DashboardTestCase):
    menus = {'wm_dashboard': 'RW', 'wm_dig_form_outgoing_write': 'RW', 'wm_dig_form_incoming_write': 'R'}

    def test_품질검사_W_만_있으면_수입_수는_null_이고_목록에_수입이_없다(self):
        incoming = DigForm.objects.create(Code='DF-D3', Version=1, Title='수입 양식', FormType='INCOMING')
        outgoing = DigForm.objects.create(Code='DF-D4', Version=1, Title='품질 양식', FormType='OUTGOING')
        DigFormResult.objects.create(DigForm=incoming, WriteDate=date.today(), WorkOrderNumber='R9-1')
        DigFormResult.objects.create(DigForm=outgoing, WriteDate=date.today(), WorkOrderNumber='WO-9')
        todo = self.summary(self.manager)['todo']
        self.assertEqual(todo['inspection'], {'incoming': None, 'outgoing': 1})
        self.assertEqual([j['number'] for j in todo['jobs']], ['WO-9'])


@override_settings(API_AUTHZ_MODE='enforce')
class DashboardVisionDataTodoTest(DashboardTestCase):
    # 작업자 그룹은 검수 작업을 R 만 받는다(ItemApiTestCase.WRITER_ONLY)
    menus = {'wm_dashboard': 'RW', 'wm_data_labeling': 'RW', 'wm_data_review': 'RW'}

    def setUp(self):
        super().setUp()
        S = ImageAsset.LabelStatus
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image(f'{n}.png', color=(n, n, n)) for n in range(4)], actor=self.manager)
            self.images = list(ImageAsset.objects.for_tenant(self.tenant).filter(dataset__item=self.item).order_by('id'))
            for n, (image, status) in enumerate(zip(self.images, (S.UNLABELED, S.REWORK, S.SUBMITTED, S.APPROVED))):
                ImageAsset.objects.for_tenant(self.tenant).filter(pk=image.pk).update(
                    label_status=status, created_at=at(date.today(), 8 + n))
            # 치수 측정 항목은 라벨링을 하지 않는다 — 세지 않고 목록에도 없다
            measure = InspectionItem.objects.create(tenant=self.tenant, code='MEAS', name='치수',
                                                    task_type=InspectionItem.TaskType.MEASUREMENT)
            ImageService.upload_images(measure, [make_image('m.png', color=(9, 9, 9))], actor=self.manager)

    def test_라벨링_검수_W_면_수와_라벨링_대기_이미지를_최근_순으로_준다(self):
        todo = self.summary(self.manager)['todo']
        self.assertEqual(todo['vision'], {'labeling': 2, 'review': 1})
        self.assertEqual([(i['id'], i['item_id'], i['status_label']) for i in todo['images']],
                         [(self.images[1].id, self.item.id, '재작업 필요'), (self.images[0].id, self.item.id, '미작업')])
        self.assertEqual(todo['images'][0]['thumbnail_url'], f'/media/image/{self.images[1].id}/thumbnail/')
        self.assertEqual(todo['images'][0]['item_name'], 'API 검사')

    def test_파일이_없는_이미지는_썸네일_주소가_비어_있다(self):
        # 공유 개발 DB 에는 다른 PC 저장소에만 파일이 있는 행이 있다 — 로그인 첫 화면이 404 를 내지 않게 한다
        with tenant_atomic(self.tenant):
            image = ImageAsset.objects.for_tenant(self.tenant).get(pk=self.images[1].pk)
            for field in (image.thumbnail, image.file):
                if field:
                    field.storage.delete(field.name)
        urls = {i['id']: i['thumbnail_url'] for i in self.summary(self.manager)['todo']['images']}
        self.assertEqual(urls[self.images[1].id], '')
        self.assertTrue(urls[self.images[0].id])

    def test_검수_W_가_없으면_검수_수가_null_이다(self):
        self.assertEqual(self.summary(self.worker)['todo']['vision'], {'labeling': 2, 'review': None})


@override_settings(API_AUTHZ_MODE='enforce')
class DashboardStatusTest(DashboardTestCase):
    menus = {'wm_dashboard': 'RW', 'wm_dig_form_incoming_result': 'R', 'wm_vis_inspection': 'R'}

    def done(self, form, days_ago, combo=None, item=None, state='done'):
        result = DigFormResult.objects.create(DigForm=form, WriteDate=date.today(), State=state)
        if combo:
            DigFormItemResult.objects.create(DigFormResult=result, DigFormItem=item, ComboResult=combo)
        self.done_at(result, at(date.today() - timedelta(days=days_ago)))

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

    def test_이번_달_완료는_결과_R_구분만_이번_달_것을_센다(self):
        incoming = DigForm.objects.create(Code='DF-S3', Version=1, Title='수입', FormType='INCOMING')
        outgoing = DigForm.objects.create(Code='DF-S4', Version=1, Title='품질', FormType='OUTGOING')
        self.done(incoming, 0)
        self.done(incoming, 0, state='working')
        self.done(outgoing, 0)                                   # 품질 결과 R 없음
        last_month = DigFormResult.objects.create(DigForm=incoming, WriteDate=date.today(), State='done')
        self.done_at(last_month, at(date.today().replace(day=1) - timedelta(days=1)))
        self.assertEqual(self.summary(self.manager)['status']['month_done'], {'incoming': 1, 'outgoing': None})

    def test_비전_검사_이력_R_이면_최근_5건을_썸네일과_함께_준다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('v.png')], actor=self.manager)
            image = ImageAsset.objects.for_tenant(self.tenant).get(dataset__item=self.item)
            client = VisionClient.objects.create(client_id='CLIENT-D', name='라인 1', api_key_hash='x' * 64)
            for n in range(6):
                key = str(uuid.uuid4())
                VisionInspection.objects.create(id=key, request_id=key, client=client, item=self.item,
                                                status=VisionInspection.Status.SUCCESS, abnormal=n == 5,
                                                image_asset=image if n == 5 else None)
                VisionInspection.objects.filter(pk=key).update(created_at=at(date.today(), 8 + n))
        status = self.summary(self.manager)['status']
        vision = status['vision']
        self.assertEqual(len(vision), 5)
        self.assertEqual((vision[0]['item_name'], vision[0]['client_id'], vision[0]['abnormal']), ('API 검사', 'CLIENT-D', True))
        self.assertEqual(vision[0]['thumbnail_url'], f'/media/image/{image.id}/thumbnail/')
        self.assertEqual(vision[1]['thumbnail_url'], '')            # 이미지 없는 검사
        self.assertIsNone(status['register'])     # 등록 메뉴 R 없음
