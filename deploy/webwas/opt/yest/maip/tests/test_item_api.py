"""`/api/item/*` — 데이터 관리 화면의 MES API.

`item` task 는 dispatch 가 테넌트 컨텍스트·POST 강제·업무 오류 응답을 맡는다
(app/views/item/__init__.py). 화면마다 모듈 하나다.
"""
import json
import tempfile
import time

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from domain.models.data import DatasetVersion, ImageAsset, InspectionCategory, InspectionItem
from domain.models.system import SystemOption
from domain.models.user import UserGroup, UserGroupMenu
from domain.services.data.image import ImageService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from tests.test_data_services import make_image

PASSWORD = 'correct-horse-battery-staple'
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@override_settings(API_AUTHZ_MODE='enforce')
class ItemApiTestCase(TestCase):
    """무엇을 할 수 있는지는 메뉴 권한만 정한다(비전검사항목 배정은 없앴다, 사용자 결정 2026-10-21).

    관리자 그룹은 `menus` 그대로, 작업자 그룹은 같은 메뉴를 받되 홈 설정·검수·스냅샷 등록 메뉴는 R 만 받는다.
    """

    menus = {'wm_data_snapshot': 'RW'}
    WRITER_ONLY = frozenset({'wm_data_item_detail', 'wm_data_review', 'wm_data_snapshot'})

    def setUp(self):
        cache.clear()
        reset_tenant_cache()
        self.tenant = current_tenant()
        SystemOption.objects.get_or_create(Code='LOGO_TITLE', defaults={'Value': '테스트'})
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        managers = UserGroup.objects.create(Code='item-manager', Name='관리')
        workers = UserGroup.objects.create(Code='worker', Name='작업자')
        for code, auth in self.menus.items():
            UserGroupMenu.objects.create(UserGroup=managers, MenuCode=code, AuthCode=auth)
            UserGroupMenu.objects.create(UserGroup=workers, MenuCode=code,
                                         AuthCode=auth.replace('W', '') if code in self.WRITER_ONLY else auth)
        self.manager = self._user('item-manager', managers)
        self.worker = self._user('item-worker', workers)
        with tenant_atomic(self.tenant):
            self.item = InspectionItem.objects.create(tenant=self.tenant, code='API', name='API 검사',
                                                      task_type=InspectionItem.TaskType.OBJECT_DETECTION)

    def _user(self, name, group=None):
        user = User.objects.create_user(name, password=PASSWORD)
        if group is not None:
            user.userprofile.UserGroup = group
            user.userprofile.save()
        return user

    def http(self, user):
        client = Client()
        self.assertTrue(client.login(username=user.username, password=PASSWORD))
        return client

    def approve_one(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image()], actor=self.manager)
            ImageAsset.objects.for_tenant(self.tenant).update(label_status=ImageAsset.LabelStatus.APPROVED)


class ItemDispatchTest(ItemApiTestCase):
    def test_변경_action_은_GET_으로_부르면_405_이고_아무것도_만들지_않는다(self):
        self.approve_one()
        response = self.http(self.manager).get('/api/item/snapshot',
                                               {'action': 'create', 'item_id': self.item.id}, **AJAX)
        self.assertEqual(response.status_code, 405)
        with tenant_atomic(self.tenant):
            self.assertFalse(DatasetVersion.objects.for_tenant(self.tenant).exists())

    def test_조회는_테넌트_컨텍스트_안에서_돈다(self):
        self.approve_one()
        created = self.http(self.manager).post('/api/item/snapshot?action=create',
                                               {'item_id': self.item.id}, **AJAX)
        self.assertEqual(created.status_code, 200, created.content.decode()[:200])
        body = self.http(self.manager).get('/api/item/snapshot',
                                           {'action': 'list', 'item_id': self.item.id}, **AJAX).json()
        self.assertEqual(body['totalRows'], 1)   # RLS 밖에서 읽으면 0 이다

    def test_업무_오류는_400_과_문구이고_롤백한다(self):
        response = self.http(self.manager).post('/api/item/snapshot?action=create',
                                                {'item_id': self.item.id}, **AJAX)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {'success': False,
                                           'message': '검수 완료된 이미지가 없어 스냅샷을 만들 수 없습니다.'})

    def test_없는_검사항목은_404(self):
        response = self.http(self.manager).get('/api/item/snapshot',
                                               {'action': 'list', 'item_id': 999999}, **AJAX)
        self.assertEqual(response.status_code, 404)

    def test_메뉴_권한이_없으면_403(self):
        response = self.http(self._user('no-menu')).get(
            '/api/item/snapshot', {'action': 'list', 'item_id': self.item.id}, **AJAX)
        self.assertEqual(response.status_code, 403)

    def test_배정_없이_메뉴_권한만으로_모든_비전검사항목을_다룬다(self):
        """비전검사항목 배정은 없앴다 — 메뉴 R 이 있으면 어느 항목이든 본다(사용자 결정 2026-10-21)."""
        with tenant_atomic(self.tenant):
            other = InspectionItem.objects.create(tenant=self.tenant, code='OTHER', name='다른 검사',
                                                  task_type=InspectionItem.TaskType.OBJECT_DETECTION)
        response = self.http(self.worker).get('/api/item/snapshot',
                                              {'action': 'list', 'item_id': other.id}, **AJAX)
        self.assertEqual(response.status_code, 200)

    def test_모르는_action_은_400(self):
        response = self.http(self.manager).post('/api/item/snapshot?action=nope',
                                                {'item_id': self.item.id}, **AJAX)
        self.assertEqual(response.status_code, 400)


class SnapshotApiTest(ItemApiTestCase):
    def _create(self, user, **extra):
        return self.http(user).post('/api/item/snapshot?action=create',
                                    {'item_id': self.item.id, **extra}, **AJAX)

    def _list(self):
        return self.http(self.manager).get('/api/item/snapshot',
                                           {'action': 'list', 'item_id': self.item.id}, **AJAX).json()

    def test_작업자는_스냅샷을_등록할_수_없다(self):
        self.approve_one()
        self.assertEqual(self._create(self.worker).status_code, 403)

    def test_목록은_버전마다_Export_상태를_준다(self):
        self.approve_one()
        self._create(self.manager)
        body = self._list()
        row = body['rows'][0]
        self.assertEqual((row['export']['format'], row['export']['status']), ('COCO', 'QUEUED'))
        self.assertEqual(row['export']['file_url'], '')
        self.assertNotIn('readiness', row)
        self.assertTrue(body['can_create'])
        self.assertNotIn('export_format', body)

    def test_목록은_페이지를_나누지_않고_전부를_준다(self):
        self.approve_one()
        self.assertEqual(self._create(self.manager).status_code, 200)
        with tenant_atomic(self.tenant):  # 데이터가 같으면 두 번째 스냅샷을 만들지 않는다 — 다른 이미지를 더한다
            ImageService.upload_images(self.item, [make_image('b.png', color=(1, 2, 3))], actor=self.manager)
            ImageAsset.objects.for_tenant(self.tenant).update(label_status=ImageAsset.LabelStatus.APPROVED)
        self.assertEqual(self._create(self.manager).status_code, 200)
        body = self.http(self.manager).get('/api/item/snapshot', {
            'action': 'list', 'item_id': self.item.id, 'page': 1, 'page_size': 1}, **AJAX).json()
        self.assertEqual((len(body['rows']), body['totalRows']), (2, 2))

    def test_작업자_목록에는_등록_권한이_없다고_나온다(self):
        body = self.http(self.worker).get('/api/item/snapshot',
                                          {'action': 'list', 'item_id': self.item.id}, **AJAX).json()
        self.assertFalse(body['can_create'])

    def test_상세는_분포_분석을_준다(self):
        self.approve_one()
        version_id = self._create(self.manager).json()['version_id']
        body = self.http(self.manager).get('/api/item/snapshot', {
            'action': 'detail', 'item_id': self.item.id, 'version_id': version_id}, **AJAX).json()
        self.assertEqual(body['version']['id'], version_id)
        self.assertEqual(body['analysis']['image_count'], 1)

    def test_다시_만들기는_고정_형식_Export_를_하나_더_적재한다(self):
        # 형식을 고르던 때 YOLO 로 만든 스냅샷도 다시 만들면 고정 형식(COCO)이다.
        from domain.models.data import ExportJob
        self.approve_one()
        version_id = self._create(self.manager).json()['version_id']
        with tenant_atomic(self.tenant):
            ExportJob.objects.for_tenant(self.tenant).filter(dataset_version_id=version_id).exclude(
                format='WEZARD').update(format='YOLO')
        response = self.http(self.manager).post('/api/item/snapshot?action=rebuild',
                                                {'item_id': self.item.id, 'version_id': version_id}, **AJAX)
        self.assertEqual(response.status_code, 200)
        with tenant_atomic(self.tenant):
            formats = list(ExportJob.objects.for_tenant(self.tenant)
                           .filter(dataset_version_id=version_id).values_list('format', flat=True))
        # Wezard 전송용은 대기 중이라 다시 적재하지 않는다.
        self.assertEqual(sorted(formats), ['COCO', 'WEZARD', 'YOLO'])

    def _version_detail(self, version_id):
        return self.http(self.manager).get('/api/item/snapshot', {
            'action': 'detail', 'item_id': self.item.id, 'version_id': version_id}, **AJAX).json()

    def test_화면_상세의_분포는_라벨_클래스_표시_이름이다(self):
        # Wezard statistics(/api/v1/datasets)는 같은 분석을 내부 이름으로 준다 — 화면 응답만 바꾼다.
        from domain.models.data import DatasetVersion, LabelClass
        self.approve_one()
        version_id = self._create(self.manager).json()['version_id']
        box = {'geometry_type': 'BBOX', 'bbox': [1, 1, 2, 2]}
        with tenant_atomic(self.tenant):
            LabelClass.objects.create(tenant=self.tenant, item=self.item, name='scratch', display_name_ko='긁힘')
            DatasetVersion.objects.filter(pk=version_id).update(manifest={'image_count': 2, 'images': [
                {'annotations': [dict(box, label='scratch'), dict(box, label='scratch'), dict(box, label='gone')]},
                {'annotations': []}]})
        analysis = self._version_detail(version_id)['analysis']
        self.assertEqual(analysis['class_distribution'], [['긁힘', 2], ['gone', 1]])

    def test_이상_탐지_화면_분포는_여러_결함과_표시_이름이고_예전_정상_판정은_빠진다(self):
        from domain.models.data import DatasetVersion, LabelClass
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(task_type=InspectionItem.TaskType.ANOMALY_DETECTION)
        self.approve_one()
        version_id = self._create(self.manager).json()['version_id']
        polygon = {'geometry_type': 'POLYGON', 'segmentation': [[1, 1], [5, 1], [5, 5]]}
        with tenant_atomic(self.tenant):
            LabelClass.objects.create(tenant=self.tenant, item=self.item, name='scratch', display_name_ko='긁힘')
            DatasetVersion.objects.filter(pk=version_id).update(manifest={'image_count': 3, 'images': [
                {'annotations': [dict(polygon, label='scratch')]},
                {'annotations': [dict(polygon, label='scratch'), dict(polygon, label='dent')]},
                {'annotations': [{'geometry_type': 'NONE', 'is_anomaly': False, 'label': None}]}]})
        analysis = self._version_detail(version_id)['analysis']
        self.assertEqual(sorted(analysis['anomaly_type_distribution']), [['긁힘', 1], ['여러 결함', 1]])
        self.assertEqual(sorted(analysis['class_distribution']), [['dent', 1], ['긁힘', 2]])

    def test_멈춘_작업의_실패_사유는_화면_문구로_보인다(self):
        from domain.models.data import ExportJob
        from domain.services.data.job import STALE_MESSAGE
        self.approve_one()
        version_id = self._create(self.manager).json()['version_id']
        with tenant_atomic(self.tenant):
            ExportJob.objects.for_tenant(self.tenant).filter(dataset_version_id=version_id).update(
                status=ExportJob.Status.FAILED, error_message=STALE_MESSAGE)
        body = self._version_detail(version_id)
        self.assertEqual(body['version']['export']['error_message'],
                         '파일을 만드는 중 중단되었습니다. 다시 만들기를 눌러 주세요.')
        self.assertEqual(body['wezard_export']['error_message'],
                         '파일을 만드는 중 중단되었습니다. 다시 만들기를 눌러 주세요.')

    def test_다시_만들_것이_없으면_파일이_없다고_한다(self):
        from domain.models.data import ExportJob
        self.approve_one()
        version_id = self._create(self.manager).json()['version_id']
        with tenant_atomic(self.tenant):
            ExportJob.objects.for_tenant(self.tenant).filter(dataset_version_id=version_id).update(
                status=ExportJob.Status.COMPLETED)
        response = self.http(self.manager).post('/api/item/snapshot?action=rebuild',
                                                {'item_id': self.item.id, 'version_id': version_id}, **AJAX)
        self.assertEqual((response.status_code, response.json()['message']), (400, '다시 만들 파일이 없습니다.'))

    def test_다시_만들기는_없는_Wezard_전송용_zip_을_채운다(self):
        # Wezard 전송용이 생기기 전 스냅샷: 고정 형식은 완료, WEZARD 는 없다.
        from domain.models.data import ExportJob
        self.approve_one()
        version_id = self._create(self.manager).json()['version_id']
        with tenant_atomic(self.tenant):
            jobs = ExportJob.objects.for_tenant(self.tenant).filter(dataset_version_id=version_id)
            jobs.filter(format='WEZARD').delete()
            jobs.update(status=ExportJob.Status.COMPLETED)
        response = self.http(self.manager).post('/api/item/snapshot?action=rebuild',
                                                {'item_id': self.item.id, 'version_id': version_id}, **AJAX)
        self.assertEqual(response.status_code, 200)
        with tenant_atomic(self.tenant):
            formats = list(ExportJob.objects.for_tenant(self.tenant)
                           .filter(dataset_version_id=version_id).values_list('format', flat=True))
        self.assertEqual(sorted(formats), ['COCO', 'WEZARD'])


class SnapshotAnalysisTest(TestCase):
    def test_이상_탐지_분석은_결함_영역으로_정상_이상을_센다(self):
        from app.views.item.snapshot import _analyze_manifest
        polygon = {'geometry_type': 'POLYGON', 'segmentation': [[1, 1], [5, 1], [5, 5]]}
        manifest = {'images': [
            {'annotations': []},
            {'annotations': [dict(polygon, label='scratch')]},
            {'annotations': [dict(polygon, label='scratch'), dict(polygon, label='dent')]},
            {'annotations': [{'geometry_type': 'NONE', 'is_anomaly': False, 'label': None}]},   # 예전 판정 라벨
        ]}
        stats = _analyze_manifest(manifest, 'ANOMALY_DETECTION')
        self.assertEqual((stats['normal_image_count'], stats['anomaly_image_count']), (2, 2))
        self.assertEqual(sorted(stats['anomaly_type_distribution']), [('combined', 1), ('scratch', 1)])


class ItemAdminApiTest(ItemApiTestCase):
    """검사항목 관리(`wm_data_item`, 시스템 관리) — 플랫폼 관리자 전용."""

    menus = {'wm_data_item': 'RW'}

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('platform-root', password=PASSWORD)

    def _post(self, user, action, **data):
        return self.http(user).post(f'/api/item/item_admin?action={action}', data, **AJAX)

    def _get(self, user, action, **params):
        return self.http(user).get('/api/item/item_admin', {'action': action, **params}, **AJAX)

    def test_목록은_페이지를_나누지_않고_코드를_준다(self):
        """화면 안 페이징이다 — page·page_size 를 보내도 조건에 맞는 전부를 준다."""
        self._post(self.admin, 'create', name='둘째 검사', task_type='ANOMALY_DETECTION')
        body = self._get(self.admin, 'list', page=1, page_size=1).json()
        self.assertEqual((len(body['rows']), body['totalRows']), (2, 2))
        self.assertIn('API', [row['code'] for row in body['rows']])
        self.assertIn('status_choices', body)

    def test_목록_쿼리_수는_검사항목_수와_무관하다(self):
        # 검사항목마다 집계 쿼리(이미지 상태·라벨·데이터셋·스냅샷)를 따로 냈다.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        client = self.http(self.admin)

        def queries():
            with CaptureQueriesContext(connection) as captured:
                response = client.get('/api/item/item_admin', {'action': 'list'}, **AJAX)
            self.assertEqual(response.status_code, 200)
            return len(captured.captured_queries), response.json()['rows']

        one, _ = queries()
        with tenant_atomic(self.tenant):
            for index in range(3):
                InspectionItem.objects.create(tenant=self.tenant, code=f'N{index}', name=f'N{index}',
                                              task_type=InspectionItem.TaskType.OBJECT_DETECTION)
        many, rows = queries()
        self.assertEqual(many, one)
        api = next(row for row in rows if row['code'] == 'API')
        self.assertEqual(api['image_count'], 0)               # 집계 값은 그대로다

    def test_메뉴_권한이_있어도_플랫폼_관리자가_아니면_403(self):
        self.assertEqual(self._get(self.manager, 'list').status_code, 403)

    def test_추가하면_코드는_ITEM_id_다(self):
        item_id = self._post(self.admin, 'create', name='새 검사', task_type='ANOMALY_DETECTION').json()['item_id']
        with tenant_atomic(self.tenant):
            item = InspectionItem.objects.get(pk=item_id)
        self.assertEqual((item.code, item.task_type), (f'ITEM-{item_id}', 'ANOMALY_DETECTION'))

    def test_이름이_없으면_400(self):
        self.assertEqual(self._post(self.admin, 'create', name=' ').status_code, 400)

    def test_상세는_삭제_요청을_주고_배정_인원은_없다(self):
        body = self._get(self.admin, 'detail', item_id=self.item.id).json()
        self.assertNotIn('members', body)
        self.assertIsNone(body['deletion_request'])

    def test_배정_action_은_없다(self):
        for action in ('assign', 'remove_member'):
            self.assertEqual(self._post(self.admin, action, item_id=self.item.id, user_id=self.worker.id).status_code, 400)

    def test_삭제_요청_반려(self):
        from domain.models.data import ItemDeletionRequest
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(status='DELETION_PENDING')
            deletion = ItemDeletionRequest.objects.create(tenant=self.tenant, item=self.item,
                                                          requested_by=self.manager, reason='E2E')
        response = self._post(self.admin, 'reject_delete', deletion_id=deletion.id)
        self.assertEqual(response.status_code, 200, response.content.decode()[:200])
        with tenant_atomic(self.tenant):
            deletion.refresh_from_db()
        self.assertEqual(deletion.status, ItemDeletionRequest.Status.REJECTED)

    def test_상태_전환은_GET_으로_안_된다(self):
        self.assertEqual(self._get(self.admin, 'toggle_status', item_id=self.item.id).status_code, 405)

    def test_상태_전환_문구는_상태_이름을_쓴다(self):
        self.assertEqual(self._post(self.admin, 'toggle_status', item_id=self.item.id).json()['message'],
                         '비전검사항목을 중지했습니다.')
        self.assertEqual(self._post(self.admin, 'toggle_status', item_id=self.item.id).json()['message'],
                         '비전검사항목을 다시 사용합니다.')

    def test_등록_문구는_창_이름과_같다(self):
        self.assertEqual(self._post(self.admin, 'create', name='문구 확인').json()['message'], '비전검사항목을 등록했습니다.')

    def test_상세_수정은_설명과_사용_여부를_저장한다(self):
        self.assertEqual(self._get(self.admin, 'update', item_id=self.item.id, description='x').status_code, 405)
        body = self._post(self.admin, 'update', item_id=self.item.id, description=' 첫 줄\n둘째 줄 ', active='N').json()
        self.assertEqual(body['message'], '비전검사항목을 저장했습니다.')
        with tenant_atomic(self.tenant):
            self.item.refresh_from_db()
        self.assertEqual((self.item.description, self.item.status), ('첫 줄\n둘째 줄', 'PAUSED'))
        self._post(self.admin, 'update', item_id=self.item.id, description='', active='Y')
        with tenant_atomic(self.tenant):
            self.item.refresh_from_db()
        self.assertEqual((self.item.description, self.item.status), ('', 'ACTIVE'))

    def test_촬영_방식은_등록_때_고르고_상세_수정에서_바꾼다(self):
        item_id = self._post(self.admin, 'create', name='태블릿 검사', capture_method='TABLET').json()['item_id']
        detail = self._get(self.admin, 'detail', item_id=item_id).json()
        self.assertEqual((detail['capture_method'], detail['capture_method_label']), ('TABLET', '태블릿'))
        rows = {r['id']: r for r in self._get(self.admin, 'list').json()['rows']}
        self.assertEqual(rows[item_id]['capture_method_label'], '태블릿')
        self._post(self.admin, 'update', item_id=item_id, description='', active='Y', capture_method='RIG')
        self.assertEqual(self._get(self.admin, 'detail', item_id=item_id).json()['capture_method'], 'RIG')
        # 보내지 않으면 그대로, 모르는 값은 거절
        self._post(self.admin, 'update', item_id=item_id, description='', active='Y')
        self.assertEqual(self._get(self.admin, 'detail', item_id=item_id).json()['capture_method'], 'RIG')
        response = self._post(self.admin, 'update', item_id=item_id, description='', active='Y', capture_method='DRONE')
        self.assertEqual(response.json()['message'], '촬영 방식을 확인해 주세요.')

    def test_소속_중분류는_등록_때_고르고_상세_수정에서_옮긴다(self):
        with tenant_atomic(self.tenant):
            major = InspectionCategory.objects.create(tenant=self.tenant, name='수입검사', form_type='INCOMING')
            minor = InspectionCategory.objects.create(tenant=self.tenant, parent=major, name='성적서')
            other = InspectionCategory.objects.create(tenant=self.tenant, parent=major, name='전장')
        item_id = self._post(self.admin, 'create', name='분류 검사', category_id=minor.id).json()['item_id']
        detail = self._get(self.admin, 'detail', item_id=item_id).json()
        self.assertEqual((detail['category_id'], detail['category_label']), (minor.id, '수입검사 › 성적서'))
        rows = {r['id']: r for r in self._get(self.admin, 'list').json()['rows']}
        self.assertEqual((rows[item_id]['category_id'], rows[item_id]['category_label']), (minor.id, '수입검사 › 성적서'))
        self.assertEqual(rows[self.item.id]['category_label'], '미분류')
        self._post(self.admin, 'update', item_id=item_id, description='', active='Y', category_id=other.id)
        self.assertEqual(self._get(self.admin, 'detail', item_id=item_id).json()['category_id'], other.id)
        # 보내지 않으면 그대로, 빈 값이면 미분류, 대분류는 거절
        self._post(self.admin, 'update', item_id=item_id, description='', active='Y')
        self.assertEqual(self._get(self.admin, 'detail', item_id=item_id).json()['category_id'], other.id)
        response = self._post(self.admin, 'update', item_id=item_id, description='', active='Y', category_id=major.id)
        self.assertEqual(response.json()['message'], '중분류를 골라 주세요.')
        self.assertEqual(self._post(self.admin, 'create', name='X', category_id=major.id).status_code, 400)
        self._post(self.admin, 'update', item_id=item_id, description='', active='Y', category_id='')
        self.assertIsNone(self._get(self.admin, 'detail', item_id=item_id).json()['category_id'])

    def test_삭제_승인_대기는_사용_여부를_바꿀_수_없고_설명은_저장한다(self):
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(status='DELETION_PENDING')
        response = self._post(self.admin, 'update', item_id=self.item.id, description='사유 메모', active='Y')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'], '삭제 승인 대기 중에는 사용 여부를 바꿀 수 없습니다.')
        self.assertEqual(self._post(self.admin, 'update', item_id=self.item.id, description='사유 메모',
                                    active='N').status_code, 200)
        with tenant_atomic(self.tenant):
            self.item.refresh_from_db()
        self.assertEqual((self.item.description, self.item.status), ('사유 메모', 'DELETION_PENDING'))


class ItemAdminModelMappingTest(ItemApiTestCase):
    """비전검사항목 관리 상세의 AI 모델 — Wezard 배포 모델 이름으로 매핑한다(domain.services.vision.model_mapping, 사용자 결정 2026-10-21)."""

    menus = {'wm_data_item': 'RW'}

    def setUp(self):
        from unittest.mock import patch
        from tests.test_vision_model_mapping import FakeWezard
        super().setUp()
        self.admin = User.objects.create_superuser('platform-root', password=PASSWORD)
        self.gateway = FakeWezard()
        patcher = patch('domain.services.vision.model_mapping.get_inference_gateway', side_effect=lambda: self.gateway)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, action, **data):
        return self.http(self.admin).post(f'/api/item/item_admin?action={action}', data, **AJAX)

    def _get(self, action, **params):
        return self.http(self.admin).get('/api/item/item_admin', {'action': action, **params}, **AJAX)

    def active(self):
        from domain.models.vision import VisionItemModelMapping
        with tenant_atomic(self.tenant):
            return list(VisionItemModelMapping.objects.filter(item=self.item, active=True).values_list('model_code', flat=True))

    def test_상세는_지금_모델과_매핑_대상인지를_준다(self):
        body = self._get('detail', item_id=self.item.id).json()
        self.assertEqual((body['model_name'], body['mappable']), ('', True))
        with tenant_atomic(self.tenant):
            point = InspectionItem.objects.create(tenant=self.tenant, code='DIM', name='치수',
                                                  task_type=InspectionItem.TaskType.MEASUREMENT)
        self.assertFalse(self._get('detail', item_id=point.id).json()['mappable'])   # 치수 측정은 모델이 없다

    def test_모델_목록은_그_유형의_Wezard_배포_모델이다(self):
        body = self._get('models', item_id=self.item.id).json()
        self.assertEqual([m['name'] for m in body['models']], ['other-det', 'wz-det'])
        self.assertEqual(body['message'], '')

    def test_수정에서_모델을_고르면_매핑하고_비우면_해제한다(self):
        body = self._post('update', item_id=self.item.id, description='', active='Y', model_name='wz-det').json()
        self.assertTrue(body['success'])
        self.assertEqual(self.active(), ['wz-det'])
        self.assertEqual(self._get('detail', item_id=self.item.id).json()['model_name'], 'wz-det')
        self._post('update', item_id=self.item.id, description='', active='Y', model_name='')
        self.assertEqual(self.active(), [])

    def test_모델을_보내지_않거나_그대로면_Wezard_를_부르지_않는다(self):
        self._post('update', item_id=self.item.id, description='', active='Y', model_name='wz-det')
        self.gateway = object()     # 이제 Wezard 를 부르면 AttributeError 로 실패한다
        self.assertEqual(self._post('update', item_id=self.item.id, description='a', active='Y').status_code, 200)
        self.assertEqual(self._post('update', item_id=self.item.id, description='b', active='Y',
                                    model_name='wz-det').status_code, 200)
        self.assertEqual(self.active(), ['wz-det'])

    def test_배포되지_않은_모델이면_아무것도_저장하지_않는다(self):
        response = self._post('update', item_id=self.item.id, description='바뀐 설명', active='Y', model_name='없는모델')
        self.assertEqual(response.status_code, 400)
        self.assertIn('없는모델', response.json()['message'])
        with tenant_atomic(self.tenant):
            self.item.refresh_from_db()
        self.assertEqual((self.item.description, self.active()), ('', []))


class ItemHomeApiTest(ItemApiTestCase):
    """검사항목 홈(`wm_data_item_detail`). 보기는 배정 인원 누구나, 설정은 검사항목 관리자."""

    menus = {'wm_data_item_detail': 'RW'}

    def _post(self, user, action, **data):
        return self.http(user).post(f'/api/item/item_home?action={action}', {'item_id': self.item.id, **data}, **AJAX)

    def _detail(self, user):
        return self.http(user).get('/api/item/item_home', {'action': 'detail', 'item_id': self.item.id}, **AJAX)

    def test_작업자도_상세를_본다(self):
        self.approve_one()
        body = self._detail(self.worker).json()
        self.assertEqual(body['name'], 'API 검사')
        self.assertFalse(body['can_manage'])                     # 홈 메뉴 R 만
        self.assertTrue(self._detail(self.manager).json()['can_manage'])   # 홈 메뉴 W
        self.assertNotIn('members', body)
        self.assertTrue(body['recent_images'][0]['thumbnail_url'].startswith('/media/image/'))

    def test_화면_버튼은_메뉴_권한이_있는_하위_화면이다(self):
        # 좌측 메뉴의 비전검사항목은 홈만 연다 — 나머지 화면은 홈 버튼으로(설계 2026-10-21 §4)
        group = self.worker.userprofile.UserGroup
        for code in ('wm_data_image', 'wm_data_review'):
            UserGroupMenu.objects.create(UserGroup=group, MenuCode=code, AuthCode='R')
        self.assertEqual(self._detail(self.worker).json()['screens'],
                         [{'code': 'wm_data_image', 'name': '데이터 목록'}, {'code': 'wm_data_review', 'name': '검수 작업'}])
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(task_type='MEASUREMENT')
        self.assertEqual([s['code'] for s in self._detail(self.worker).json()['screens']], ['wm_data_image'])

    def test_작업자는_설정을_바꿀_수_없다(self):
        self.assertEqual(self._post(self.worker, 'update', name='바꿈').status_code, 403)

    def test_관리자는_이름과_대표_이미지를_바꾼다(self):
        cover = make_image('cover.png')
        response = self.http(self.manager).post('/api/item/item_home?action=update', {
            'item_id': self.item.id, 'name': '새 이름', 'description': '설명', 'cover_image': cover}, **AJAX)
        self.assertEqual(response.status_code, 200, response.content.decode()[:200])
        body = self._detail(self.manager).json()
        self.assertEqual((body['name'], body['description']), ('새 이름', '설명'))
        self.assertTrue(body['cover_url'])

    def test_대표_이미지를_바꾸면_주소가_달라진다(self):
        def upload(name):
            response = self.http(self.manager).post('/api/item/item_home?action=update', {
                'item_id': self.item.id, 'name': 'API 검사', 'cover_image': make_image(name)}, **AJAX)
            self.assertEqual(response.status_code, 200, response.content.decode()[:200])
            return self._detail(self.manager).json()['cover_url']

        first = upload('a.png')
        time.sleep(1.1)  # ?v= 는 초 단위다
        second = upload('b.png')
        self.assertIn('?v=', first)
        self.assertNotEqual(first, second)

    def test_업로드_규칙은_없다(self):
        self.assertNotIn('upload_guideline', self._detail(self.manager).json())
        self.assertFalse(hasattr(self.item, 'upload_guideline'))

    def test_이름이_비면_400(self):
        self.assertEqual(self._post(self.manager, 'update', name='').status_code, 400)

    def test_라벨_클래스_추가_수정_삭제(self):
        created = self._post(self.manager, 'label_create', name='scratch', display_name_ko='스크래치',
                             color='#112233', is_defect='true', annotation_shape='BBOX')
        self.assertEqual(created.status_code, 200, created.content.decode()[:200])
        label_id = created.json()['label']['id']
        self._post(self.manager, 'label_update', label_id=label_id, name='scratch', display_name_ko='긁힘',
                   color='#112233', is_defect='false')
        labels = self._detail(self.manager).json()['labels']
        self.assertEqual([(l['display_name_ko'], l['is_defect']) for l in labels], [('긁힘', False)])
        self.assertEqual(self._post(self.manager, 'label_delete', label_id=label_id).status_code, 200)
        self.assertEqual(self._detail(self.manager).json()['labels'], [])

    def test_색상_형식이_틀리면_400(self):
        response = self._post(self.manager, 'label_create', name='x', display_name_ko='x', color='red')
        self.assertEqual(response.status_code, 400)

    def test_일시_중지_뒤_삭제_요청(self):
        self.assertEqual(self._post(self.manager, 'toggle_status').status_code, 200)
        self.assertEqual(self._post(self.manager, 'request_delete', reason='정리').status_code, 200)
        self.assertEqual(self._detail(self.manager).json()['status'], 'DELETION_PENDING')

    def test_사용_중에는_삭제를_요청할_수_없다(self):
        response = self._post(self.manager, 'request_delete')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'], '중지된 비전검사항목만 삭제를 요청할 수 있습니다.')

    def test_상태_전환_문구는_상태_이름을_쓴다(self):
        self.assertEqual(self._post(self.manager, 'toggle_status').json()['message'], '비전검사항목을 중지했습니다.')
        self.assertEqual(self._post(self.manager, 'toggle_status').json()['message'], '비전검사항목을 다시 사용합니다.')

    def test_상세는_작업_중_건수를_준다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image(), make_image('b.png', color=(10, 10, 10))], actor=self.manager)
            ImageAsset.objects.for_tenant(self.tenant).filter(
                pk=ImageAsset.objects.for_tenant(self.tenant).order_by('id').first().pk
            ).update(label_status=ImageAsset.LabelStatus.IN_PROGRESS)
        body = self._detail(self.worker).json()
        self.assertEqual((body['in_progress_count'], body['waiting_count']), (1, 1))

    def test_스냅샷_목록은_최근_Export_상태를_준다(self):
        self.approve_one()
        from domain.services.data.item import ItemService
        from domain.services.data.version import DatasetVersionService
        with tenant_atomic(self.tenant):
            DatasetVersionService.create_snapshot(ItemService.get_or_create_upload_dataset(self.item), self.manager)
        snapshots = self._detail(self.worker).json()['snapshots']
        self.assertEqual([(s['version_tag'], s['export_status']) for s in snapshots], [('v1.0', 'QUEUED')])


class MeasurementPointApiTest(ItemApiTestCase):
    """치수 측정 항목의 측정점 — 홈에서 라벨 클래스 자리에 둔다(설계 2026-10-20 §6)."""

    menus = {'wm_data_item_detail': 'RW'}
    _post, _detail = ItemHomeApiTest._post, ItemHomeApiTest._detail
    A = {'code': 'A', 'name': '치수 A', 'nominal': '540', 'lower': '539', 'upper': '541', 'unit': 'mm', 'description': ''}

    def setUp(self):
        super().setUp()
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(task_type=InspectionItem.TaskType.MEASUREMENT)

    def test_등록_수정_삭제(self):
        created = self._post(self.manager, 'point_create', **self.A)
        self.assertEqual(created.status_code, 200, created.content.decode()[:200])
        point_id = created.json()['point']['id']
        self._post(self.manager, 'point_create', **dict(self.A, code='C', name='치수 C', nominal='154', lower='153', upper='155'))
        self._post(self.manager, 'point_update', point_id=point_id, **dict(self.A, name='카세트 가로', upper='541.5'))
        points = self._detail(self.worker).json()['points']
        self.assertEqual([(p['code'], p['name'], p['upper']) for p in points],
                         [('A', '카세트 가로', '541.500'), ('C', '치수 C', '155.000')])
        self.assertEqual(self._post(self.manager, 'point_delete', point_id=point_id).status_code, 200)
        self.assertEqual([p['code'] for p in self._detail(self.worker).json()['points']], ['C'])

    def test_범위가_틀리거나_코드가_겹치면_400(self):
        response = self._post(self.manager, 'point_create', **dict(self.A, lower='541', upper='539'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('하한 ≤ 기준값 ≤ 상한', response.json()['message'])
        self._post(self.manager, 'point_create', **self.A)
        response = self._post(self.manager, 'point_create', **self.A)
        self.assertEqual(response.json()['message'], '같은 비전검사항목에 같은 측정점 코드가 이미 있습니다.')

    def test_측정_결과가_있는_코드는_바꾸거나_지울_수_없다(self):
        from domain.models.vision import VisionClient, VisionInspection
        point_id = self._post(self.manager, 'point_create', **self.A).json()['point']['id']
        client = VisionClient.objects.create(client_id='C1', name='c', api_key_hash='x')
        VisionInspection.objects.create(id='i1', request_id='r1', client=client, item=self.item,
                                        measurements=[{'code': 'A', 'value': 540, 'ok': True}])
        response = self._post(self.manager, 'point_update', point_id=point_id, **dict(self.A, code='B'))
        self.assertEqual(response.json()['message'], '측정 결과가 있는 측정점은 코드를 바꾸거나 지울 수 없습니다.')
        self.assertEqual(self._post(self.manager, 'point_delete', point_id=point_id).status_code, 400)
        # 이름·규격은 고친다 — 지난 기록은 그때 규격을 따로 갖고 있다
        self.assertEqual(self._post(self.manager, 'point_update', point_id=point_id, **dict(self.A, upper='542')).status_code, 200)

    def test_유형에_맞지_않는_설정은_거절한다(self):
        response = self._post(self.manager, 'label_create', name='x', display_name_ko='x', color='#112233')
        self.assertEqual(response.json()['message'], '치수 측정 비전검사항목은 라벨 클래스 대신 측정점을 씁니다.')
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(task_type=InspectionItem.TaskType.OBJECT_DETECTION)
        response = self._post(self.manager, 'point_create', **self.A)
        self.assertEqual(response.json()['message'], '측정점은 치수 측정 비전검사항목에만 둡니다.')

    def test_작업자는_측정점을_바꿀_수_없다(self):
        self.assertEqual(self._post(self.worker, 'point_create', **self.A).status_code, 403)


class MeasurementLabelingBlockTest(ItemApiTestCase):
    """치수 측정 항목은 라벨링·검수·스냅샷을 쓰지 않는다 — 메뉴만 감추지 않고 API 가 거절한다(설계 2026-10-20 §4-4)."""

    menus = {'wm_data_labeling': 'RW', 'wm_data_review': 'RW', 'wm_data_snapshot': 'RW', 'wm_data_image': 'RW'}

    def test_라벨_계열_API_는_거절하고_데이터_목록은_연다(self):
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(task_type=InspectionItem.TaskType.MEASUREMENT)
        http = self.http(self.manager)
        for view, action in (('labeling', 'queue'), ('review', 'list'), ('snapshot', 'list')):
            response = http.get(f'/api/item/{view}', {'action': action, 'item_id': self.item.id}, **AJAX)
            self.assertEqual(response.status_code, 400, view)
            self.assertEqual(response.json()['message'], '치수 측정 비전검사항목은 라벨링·검수·스냅샷을 쓰지 않습니다.')
        response = http.post('/api/item/snapshot?action=create', {'item_id': self.item.id}, **AJAX)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(http.get('/api/item/image', {'action': 'list', 'item_id': self.item.id}, **AJAX).status_code, 200)


class ImageApiTest(ItemApiTestCase):
    """데이터 목록(`wm_data_image`) — 목록·상세·업로드·삭제·편집."""

    menus = {'wm_data_image': 'RW'}

    def _get(self, user, action, **params):
        return self.http(user).get('/api/item/image', {'action': action, 'item_id': self.item.id, **params}, **AJAX)

    def _post(self, user, action, **data):
        return self.http(user).post(f'/api/item/image?action={action}', {'item_id': self.item.id, **data}, **AJAX)

    def _upload(self, user, *names):
        return self._post(user, 'upload', files=[make_image(n, color=(i * 40, 10, 10)) for i, n in enumerate(names)])

    def test_업로드하고_목록에서_본다(self):
        response = self._upload(self.worker, 'a.png', 'b.png')
        self.assertEqual(response.status_code, 200, response.content.decode()[:200])
        self.assertEqual(len(response.json()['uploaded']), 2)
        body = self._get(self.worker, 'list', page=1, page_size=1).json()
        self.assertEqual(body['totalRows'], 2)
        self.assertEqual(len(body['rows']), 1)
        self.assertTrue(body['rows'][0]['thumbnail_url'].startswith('/media/image/'))
        self.assertIn('skip_labeling_available', body['item'])
        self.assertEqual(self._get(self.worker, 'list', q='a.png').json()['totalRows'], 1)

    def test_목록은_등록일_최신순이고_등록일을_준다(self):
        # 검색 조건(등록일)과 보이는 날짜·정렬이 같다. 나중에 수정한 이미지가 위로 올라가지 않는다.
        from datetime import datetime
        self._upload(self.worker, 'old.png', 'new.png')
        with tenant_atomic(self.tenant):
            images = ImageAsset.objects.for_tenant(self.tenant)
            images.filter(original_name='old.png').update(created_at=datetime(2026, 1, 1, 9, 0),
                                                          updated_at=datetime(2026, 2, 1, 9, 0))
            images.filter(original_name='new.png').update(created_at=datetime(2026, 1, 2, 9, 0),
                                                          updated_at=datetime(2026, 1, 2, 9, 0))
        rows = self._get(self.worker, 'list').json()['rows']
        self.assertEqual([(r['original_name'], r['created_at']) for r in rows],
                         [('new.png', '2026-01-02 09:00'), ('old.png', '2026-01-01 09:00')])

    def test_압축_폭탄은_거절_목록에_든다(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from tests.test_client_api import bomb_png
        bomb = SimpleUploadedFile('bomb.png', bomb_png(), content_type='image/png')
        response = self._post(self.worker, 'upload', files=[bomb])
        self.assertEqual(response.status_code, 200, response.content.decode()[:200])
        self.assertEqual(response.json()['uploaded'], [])
        self.assertEqual([r['name'] for r in response.json()['rejected']], ['bomb.png'])

    def _labeled(self, task_type, cases):
        """cases: [(파일명, label_status, [(라벨 이름 또는 None, geometry_type, attributes)])] → {파일명: 이미지}."""
        from domain.models.data import Annotation, LabelClass
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(task_type=task_type)
            self.item.refresh_from_db()
            classes = {name: LabelClass.objects.create(tenant=self.tenant, item=self.item, name=name, display_name_ko=ko,
                                                       color=color, is_defect=defect)
                       for name, ko, color, defect in (('normal', '정상', '#2E86AB', False), ('defect', '불량', '#D7263D', True),
                                                       ('scratch', '긁힘', '#E4572E', True), ('dent', '찍힘', '#F3A712', True))}
            ImageService.upload_images(self.item, [make_image(n, color=(i * 30, 7, 7)) for i, (n, _, _) in enumerate(cases)],
                                       actor=self.manager)
            images = {image.original_name: image for image in ImageAsset.objects.for_tenant(self.tenant)}
            geometry = {'BBOX': {'x': 1, 'y': 1, 'width': 4, 'height': 4}, 'POLYGON': {'points': [[1, 1], [6, 1], [6, 6]]}}
            for name, status, annotations in cases:
                ImageAsset.objects.filter(pk=images[name].pk).update(label_status=status)
                for label, kind, attributes in annotations:
                    Annotation.objects.create(tenant=self.tenant, image=images[name], geometry_type=kind,
                                              label_class=classes[label] if label else None,
                                              geometry=geometry.get(kind), attributes=attributes)
        return images

    def _results(self):
        return {row['original_name']: row['label_result'] for row in self._get(self.worker, 'list').json()['rows']}

    def test_라벨_결과는_영역이_있으면_이상이고_제출_전에는_비운다(self):
        S = ImageAsset.LabelStatus
        self._labeled('OBJECT_DETECTION', [
            ('none.png', S.UNLABELED, []), ('box.png', S.SUBMITTED, [('scratch', 'BBOX', {})]),
            ('empty.png', S.APPROVED, []), ('draft.png', S.IN_PROGRESS, [('scratch', 'BBOX', {})]),
            ('redo.png', S.REWORK, [('dent', 'POLYGON', {})])])
        self.assertEqual(self._results(), {'none.png': '', 'box.png': '이상', 'empty.png': '정상', 'draft.png': '', 'redo.png': '이상'})

    def test_이상_탐지도_영역으로_정한다(self):
        S = ImageAsset.LabelStatus
        self._labeled('ANOMALY_DETECTION', [
            ('good.png', S.SUBMITTED, []), ('bad.png', S.APPROVED, [('scratch', 'POLYGON', {})])])
        self.assertEqual(self._results(), {'good.png': '정상', 'bad.png': '이상'})

    def test_분류는_클래스의_불량_여부로_정한다(self):
        S = ImageAsset.LabelStatus
        self._labeled('CLASSIFICATION', [
            ('ok.png', S.SUBMITTED, [('normal', 'NONE', {})]), ('ng.png', S.APPROVED, [('defect', 'NONE', {})]),
            ('blank.png', S.SUBMITTED, [])])
        self.assertEqual(self._results(), {'ok.png': '정상', 'ng.png': '이상', 'blank.png': ''})

    def test_이상_탐지를_라벨_작업_없이_올리면_라벨_없이_정상이다(self):
        from domain.models.data import Annotation
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(task_type=InspectionItem.TaskType.ANOMALY_DETECTION)
            self.item.refresh_from_db()
            ImageService.upload_images(self.item, [make_image('ok.png')], actor=self.manager, requires_labeling=False)
            self.assertFalse(Annotation.objects.for_tenant(self.tenant).exists())
        self.assertEqual(self._results(), {'ok.png': '정상'})

    def test_상세는_라벨_결과와_결함별_영역_수를_준다(self):
        S = ImageAsset.LabelStatus
        images = self._labeled('OBJECT_DETECTION', [
            ('multi.png', S.SUBMITTED, [('scratch', 'BBOX', {}), ('dent', 'POLYGON', {}), ('scratch', 'POLYGON', {})]),
            ('empty.png', S.SUBMITTED, [])])
        detail = self._get(self.worker, 'detail', image_id=images['multi.png'].id).json()
        self.assertEqual(detail['label_result'], '이상')
        self.assertEqual(detail['label_summary'], [{'name': '긁힘', 'color': '#E4572E', 'count': 2},
                                                   {'name': '찍힘', 'color': '#F3A712', 'count': 1}])
        empty = self._get(self.worker, 'detail', image_id=images['empty.png'].id).json()
        self.assertEqual((empty['label_result'], empty['label_summary']), ('정상', []))

    def test_분류_상세의_결함_내역은_클래스_이름만이다(self):
        S = ImageAsset.LabelStatus
        images = self._labeled('CLASSIFICATION', [('ng.png', S.SUBMITTED, [('defect', 'NONE', {})])])
        detail = self._get(self.worker, 'detail', image_id=images['ng.png'].id).json()
        self.assertEqual((detail['label_result'], detail['label_summary']),
                         ('이상', [{'name': '불량', 'color': '#D7263D', 'count': None}]))

    def test_수집_경로로_Client_전송과_화면_업로드를_구분한다(self):
        import datetime
        import uuid
        from domain.models.vision import VisionClient, VisionInspection
        self._upload(self.worker, 'screen.png')
        inspection_id = str(uuid.uuid4())
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('cam.png', color=(1, 2, 3))],
                                       allow_duplicate=True, source_inspection_id=inspection_id)
            client = VisionClient.objects.create(client_id='CLIENT-TEST', name='테스트', api_key_hash='x' * 64)
            VisionInspection.objects.create(id=inspection_id, request_id=inspection_id, client=client, item=self.item,
                                            capture_timestamp=datetime.datetime(2026, 10, 7, 10, 0))
        rows = {r['original_name']: r for r in self._get(self.worker, 'list').json()['rows']}
        self.assertEqual((rows['screen.png']['source'], rows['cam.png']['source']), ('파일 업로드', '클라이언트'))
        self.assertEqual(self._get(self.worker, 'detail', image_id=rows['cam.png']['id']).json()['source'],
                         {'kind': 'CLIENT', 'label': '클라이언트', 'client_id': 'CLIENT-TEST', 'captured_at': '2026-10-07 10:00',
                          'inspection_id': inspection_id})
        self.assertEqual(self._get(self.worker, 'detail', image_id=rows['screen.png']['id']).json()['source'],
                         {'kind': 'FILE', 'label': '파일 업로드'})

    def test_상세는_삭제_편집_가능_여부를_준다(self):
        self._upload(self.worker, 'a.png')
        row = self._get(self.worker, 'list').json()['rows'][0]
        detail = self._get(self.worker, 'detail', image_id=row['id']).json()
        self.assertTrue(detail['can_delete'])
        self.assertTrue(detail['can_preprocess'])
        self.assertEqual([s['state'] for s in detail['stage_steps']][:2], ['done', 'active'])

    def test_삭제(self):
        self._upload(self.worker, 'a.png')
        image_id = self._get(self.worker, 'list').json()['rows'][0]['id']
        self.assertEqual(self._post(self.worker, 'delete', image_id=image_id).status_code, 200)
        self.assertEqual(self._get(self.worker, 'list').json()['totalRows'], 0)

    def test_편집은_연산_목록을_Q_로_받는다(self):
        import json as _json
        self._upload(self.worker, 'a.png')
        image_id = self._get(self.worker, 'list').json()['rows'][0]['id']
        response = self._post(self.worker, 'preprocess', image_id=image_id,
                              Q=_json.dumps({'operations': [{'op': 'rotate', 'degrees': 90}]}))
        self.assertEqual(response.status_code, 200, response.content.decode()[:200])
        self.assertEqual((response.json()['image']['width'], response.json()['image']['height']), (48, 64))
        bad = self._post(self.worker, 'preprocess', image_id=image_id,
                         Q=_json.dumps({'operations': [{'op': 'rotate', 'degrees': 45}]}))
        self.assertEqual(bad.status_code, 400)

    def test_다른_검사항목의_이미지는_404(self):
        self._upload(self.worker, 'a.png')
        image_id = self._get(self.worker, 'list').json()['rows'][0]['id']
        with tenant_atomic(self.tenant):
            other = InspectionItem.objects.create(tenant=self.tenant, code='OTHER2', name='다른',
                                                  task_type=InspectionItem.TaskType.OBJECT_DETECTION)
        response = self.http(self.worker).post('/api/item/image?action=delete',
                                               {'item_id': other.id, 'image_id': image_id}, **AJAX)
        self.assertEqual(response.status_code, 404)

    def test_업로드는_GET_으로_안_된다(self):
        self.assertEqual(self._get(self.worker, 'upload').status_code, 405)


class ReviewApiTest(ItemApiTestCase):
    """검수 작업(`wm_data_review`). 목록은 제출(작업 완료)된 이미지만, 처리는 검사항목 관리자."""

    menus = {'wm_data_review': 'RW'}

    def setUp(self):
        super().setUp()
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('s1.png', color=(1, 2, 3)), make_image('s2.png', color=(4, 5, 6)),
                                                   make_image('w.png', color=(7, 8, 9))], actor=self.worker)
            ImageAsset.objects.for_tenant(self.tenant).exclude(original_name='w.png').update(
                label_status=ImageAsset.LabelStatus.SUBMITTED)
            self.submitted = ImageAsset.objects.for_tenant(self.tenant).get(original_name='s1.png')

    def _post(self, user, action, **data):
        return self.http(user).post(f'/api/item/review?action={action}', {'item_id': self.item.id, **data}, **AJAX)

    def test_목록은_제출된_이미지만_준다(self):
        """화면 안 페이징이다 — page_size 를 보내도 전부를 준다."""
        body = self.http(self.worker).get('/api/item/review', {'action': 'list', 'item_id': self.item.id,
                                                               'page_size': 1}, **AJAX).json()
        self.assertEqual(sorted(r['original_name'] for r in body['rows']), ['s1.png', 's2.png'])
        self.assertEqual(body['totalRows'], 2)

    def test_상세는_주석과_작업자를_준다(self):
        body = self.http(self.manager).get('/api/item/review', {
            'action': 'detail', 'item_id': self.item.id, 'image_id': self.submitted.id}, **AJAX).json()
        self.assertEqual(body['original_name'], 's1.png')
        self.assertIn('annotations', body)
        self.assertIn('assignee_name', body)

    def test_목록과_상세는_라벨_결과와_결함_내역을_준다(self):
        from domain.models.data import Annotation, LabelClass
        with tenant_atomic(self.tenant):
            label = LabelClass.objects.create(tenant=self.tenant, item=self.item, name='scratch', display_name_ko='긁힘',
                                              color='#E4572E')
            Annotation.objects.create(tenant=self.tenant, image=self.submitted, label_class=label, geometry_type='BBOX',
                                      geometry={'x': 1, 'y': 1, 'width': 4, 'height': 4})
        rows = self.http(self.worker).get('/api/item/review', {'action': 'list', 'item_id': self.item.id}, **AJAX).json()['rows']
        self.assertEqual({r['original_name']: r['label_result'] for r in rows}, {'s1.png': '이상', 's2.png': '정상'})
        body = self.http(self.manager).get('/api/item/review', {
            'action': 'detail', 'item_id': self.item.id, 'image_id': self.submitted.id}, **AJAX).json()
        self.assertEqual((body['label_result'], body['label_summary']),
                         ('이상', [{'name': '긁힘', 'color': '#E4572E', 'count': 1}]))

    def test_라벨_작업_없이_올라온_이미지의_작업자는_빈_값이다(self):
        rows = self.http(self.worker).get('/api/item/review', {'action': 'list', 'item_id': self.item.id}, **AJAX).json()['rows']
        self.assertEqual({r['assignee_name'] for r in rows}, {'-'})
        body = self.http(self.manager).get('/api/item/review', {
            'action': 'detail', 'item_id': self.item.id, 'image_id': self.submitted.id}, **AJAX).json()
        self.assertEqual(body['assignee_name'], '-')

    def test_관리자는_승인한다(self):
        self.assertEqual(self._post(self.manager, 'approve', image_id=self.submitted.id).status_code, 200)
        with tenant_atomic(self.tenant):
            self.submitted.refresh_from_db()
        self.assertEqual(self.submitted.label_status, ImageAsset.LabelStatus.APPROVED)

    def test_작업자는_검수할_수_없다(self):
        self.assertEqual(self._post(self.worker, 'approve', image_id=self.submitted.id).status_code, 403)

    def test_재작업은_사유가_있어야_한다(self):
        self.assertEqual(self._post(self.manager, 'rework', image_id=self.submitted.id, reason='').status_code, 400)
        self.assertEqual(self._post(self.manager, 'rework', image_id=self.submitted.id, reason='경계 다시').status_code, 200)
        with tenant_atomic(self.tenant):
            self.submitted.refresh_from_db()
        self.assertEqual(self.submitted.label_status, ImageAsset.LabelStatus.REWORK)

    def test_승인은_GET_으로_안_된다(self):
        response = self.http(self.manager).get('/api/item/review', {
            'action': 'approve', 'item_id': self.item.id, 'image_id': self.submitted.id}, **AJAX)
        self.assertEqual(response.status_code, 405)


class LabelingApiTest(ItemApiTestCase):
    """라벨링 작업(`wm_data_labeling`) — 대기열·작업 시작·임시 저장·제출·lease 연장."""

    menus = {'wm_data_labeling': 'RW'}

    def setUp(self):
        super().setUp()
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('l.png')], actor=self.worker)
            self.image = ImageAsset.objects.for_tenant(self.tenant).get()
            from domain.models.data import LabelClass
            self.label = LabelClass.objects.create(tenant=self.tenant, item=self.item, name='scratch', display_name_ko='긁힘')

    def _post(self, action, **data):
        return self.http(self.worker).post(f'/api/item/labeling?action={action}', {'item_id': self.item.id, **data}, **AJAX)

    def test_대기열은_이미지와_라벨을_준다(self):
        body = self.http(self.worker).get('/api/item/labeling', {'action': 'queue', 'item_id': self.item.id}, **AJAX).json()
        self.assertEqual([i['id'] for i in body['images']], [self.image.id])
        self.assertEqual([l['display_name_ko'] for l in body['labels']], ['긁힘'])
        self.assertEqual(body['actor_id'], self.worker.id)
        self.assertEqual(body['item']['task_type'], 'OBJECT_DETECTION')

    def test_대기열은_대표_이미지_주소를_주고_작업자가_받을_수_있다(self):
        def queue():
            return self.http(self.worker).get('/api/item/labeling', {'action': 'queue', 'item_id': self.item.id}, **AJAX).json()

        self.assertEqual(queue()['item']['cover_url'], '')
        with tenant_atomic(self.tenant):
            self.item.cover_image = make_image('cover.png')
            self.item.save()
        url = queue()['item']['cover_url']
        self.assertTrue(url.startswith(f'/media/item-cover/{self.item.id}/?v='), url)
        self.assertEqual(self.http(self.worker).get(url).status_code, 200)

    def test_대기열_쿼리_수는_이미지_수와_무관하다(self):
        # 이미지마다 약 7쿼리(N+1). Client 검사 이미지가 자동으로 쌓여 금방 수천 장이 된다.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from domain.models.data import Annotation
        client = self.http(self.worker)

        def queries():
            with CaptureQueriesContext(connection) as captured:
                response = client.get('/api/item/labeling', {'action': 'queue', 'item_id': self.item.id}, **AJAX)
            self.assertEqual(response.status_code, 200)
            return len(captured.captured_queries)

        self._post('claim', image_id=self.image.id)
        one = queries()
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image(f'm{i}.png', color=(i * 30, 5, 5)) for i in range(5)],
                                       actor=self.worker)
            others = list(ImageAsset.objects.for_tenant(self.tenant).exclude(id=self.image.id).values_list('id', flat=True))
            ImageAsset.objects.for_tenant(self.tenant).filter(id__in=others[:2]).update(
                label_status=ImageAsset.LabelStatus.APPROVED)
            Annotation.objects.create(tenant=self.tenant, image_id=others[2], label_class=self.label,
                                      geometry_type='BBOX', geometry={'x': 1, 'y': 1, 'width': 4, 'height': 4})
        self.assertEqual(queries(), one)

    def _queue(self, **params):
        return self.http(self.worker).get('/api/item/labeling', {'action': 'queue', 'item_id': self.item.id, **params}, **AJAX).json()

    def test_대기열은_작업할_이미지만_페이지로_준다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image(f'q{i}.png', color=(i * 20, 9, 9)) for i in range(4)],
                                       actor=self.worker)
            done = ImageAsset.objects.for_tenant(self.tenant).order_by('id').last()
            ImageAsset.objects.for_tenant(self.tenant).filter(id=done.id).update(
                label_status=ImageAsset.LabelStatus.SUBMITTED)
        first = self._queue(page=1, page_size=2)
        self.assertEqual((first['page'], first['page_size'], first['totalRows']), (1, 2, 4))
        self.assertEqual(first['counts'], {'total': 5, 'complete': 1, 'remaining': 4})
        ids = [i['id'] for i in first['images']] + [i['id'] for i in self._queue(page=2, page_size=2)['images']]
        self.assertEqual(ids, sorted(ids))           # 먼저 들어온 순 — 작업해도 페이지를 옮겨 다니지 않는다
        self.assertNotIn(done.id, ids)
        self.assertEqual(len(ids), 4)

    def test_페이지_밖의_이미지를_요청하면_따로_준다(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image('r.png', color=(1, 99, 9))], actor=self.worker)
            last = ImageAsset.objects.for_tenant(self.tenant).order_by('id').last()
        body = self._queue(page=1, page_size=1, image_id=last.id)
        self.assertEqual([i['id'] for i in body['images']], [self.image.id])
        self.assertEqual(body['requested']['id'], last.id)
        self.assertIsNone(self._queue(page=1, page_size=1, image_id=self.image.id)['requested'])
        self.assertIsNone(self._queue(page=1, image_id='abc')['requested'])   # 숫자가 아니면 무시

    def test_시작_저장_연장_제출(self):
        import json as _json
        task = self._post('claim', image_id=self.image.id).json()['task']
        self.assertTrue(task['lease_token'])
        draft = self._post('draft', task_id=task['id'], Q=_json.dumps({
            'lease_token': task['lease_token'],
            'annotations': [{'label_class_id': self.label.id, 'geometry_type': 'BBOX', 'x': 1, 'y': 1, 'width': 10, 'height': 10}]}))
        self.assertEqual(draft.status_code, 200, draft.content.decode()[:200])
        self.assertEqual(draft.json()['annotation_count'], 1)
        self.assertEqual(self._post('heartbeat', task_id=task['id'], lease_token=task['lease_token']).status_code, 200)
        self.assertEqual(self._post('submit', task_id=task['id'], lease_token=task['lease_token']).status_code, 200)
        with tenant_atomic(self.tenant):
            self.image.refresh_from_db()
        self.assertEqual(self.image.label_status, ImageAsset.LabelStatus.SUBMITTED)

    def test_이상_탐지는_판정_라벨_없이_Polygon_만_저장하고_빈_제출은_정상이다(self):
        import json as _json
        with tenant_atomic(self.tenant):
            InspectionItem.objects.filter(pk=self.item.pk).update(task_type=InspectionItem.TaskType.ANOMALY_DETECTION)
        task = self._post('claim', image_id=self.image.id).json()['task']

        def draft(*annotations):
            return self._post('draft', task_id=task['id'], Q=_json.dumps({
                'lease_token': task['lease_token'], 'annotations': list(annotations)}))

        judgement = draft({'label_class_id': self.label.id, 'geometry_type': 'NONE', 'is_anomaly': True})
        self.assertEqual(judgement.status_code, 400, judgement.content.decode()[:200])   # 정상/이상 판정 라벨은 없다(DEC-032)
        self.assertEqual(draft({'label_class_id': self.label.id, 'geometry_type': 'POLYGON',
                                'segmentation': [[1, 1], [8, 1], [8, 8]]}).status_code, 200)
        self.assertEqual(draft().status_code, 200)   # 영역을 모두 지우고
        self.assertEqual(self._post('submit', task_id=task['id'], lease_token=task['lease_token']).status_code, 200)

    def test_lease_토큰이_틀리면_403(self):
        task = self._post('claim', image_id=self.image.id).json()['task']
        response = self._post('submit', task_id=task['id'], lease_token='00000000-0000-0000-0000-000000000000')
        self.assertEqual(response.status_code, 403)
        # 사용자 문구에 내부 용어(lease)를 쓰지 않는다
        self.assertEqual(json.loads(response.content)['message'], '작업 정보가 맞지 않습니다. 작업을 다시 시작해 주세요.')

    def test_작업_시간이_끝나면_다시_시작하라고_한다(self):
        from datetime import timedelta
        from django.utils import timezone
        from domain.models.data import LabelingTask
        task = self._post('claim', image_id=self.image.id).json()['task']
        with tenant_atomic(self.tenant):
            LabelingTask.objects.filter(pk=task['id']).update(lease_expires_at=timezone.now() - timedelta(minutes=1))
        response = self._post('submit', task_id=task['id'], lease_token=task['lease_token'])
        self.assertEqual((response.status_code, json.loads(response.content)['message']),
                         (403, '작업 시간이 끝났습니다. 작업을 다시 시작해 주세요.'))

    def test_다른_사람이_작업_중이면_시작할_수_없다(self):
        self._post('claim', image_id=self.image.id)
        other = self.http(self.manager).post('/api/item/labeling?action=claim',
                                             {'item_id': self.item.id, 'image_id': self.image.id}, **AJAX)
        self.assertIn(other.status_code, (400, 403))


class RegisterApiTest(ItemApiTestCase):
    """비전 데이터 등록(`wm_data_register`) — 모든 항목의 최근 데이터, 카메라·파일 등록, 편집·삭제."""

    menus = {'wm_data_register': 'RW'}

    def _get(self, user, action, **params):
        return self.http(user).get('/api/item/register', {'action': action, **params}, **AJAX)

    def _post(self, user, action, **data):
        return self.http(user).post(f'/api/item/register?action={action}', data, **AJAX)

    def test_파일과_카메라로_등록하고_목록에서_경로와_등록자를_본다(self):
        r = self._post(self.manager, 'upload', item_id=self.item.id, kind='FILE', files=[make_image('f.png')])
        self.assertEqual(len(r.json()['uploaded']), 1, r.content.decode()[:200])
        self._post(self.manager, 'upload', item_id=self.item.id, kind='CAMERA', files=[make_image('f.png')])  # 카메라는 같은 사진도 받는다
        again = self._post(self.manager, 'upload', item_id=self.item.id, kind='FILE', files=[make_image('f.png')])
        self.assertEqual(len(again.json()['rejected']), 1)                                                   # 파일은 거절
        rows = self._get(self.manager, 'list').json()['rows']
        self.assertEqual([(r['channel_label'], r['item_code'], r['uploaded_by']) for r in rows],
                         [('카메라 촬영', 'API', 'item-manager'), ('파일 업로드', 'API', 'item-manager')])
        self.assertEqual(self._get(self.manager, 'list', channel='CAMERA').json()['totalRows'], 1)

    def test_목록의_잘못된_항목_id와_날짜는_400(self):
        for params in ({'item_id': 'abc'}, {'date_from': '2026-13-01'}, {'date_to': 'x'}):
            self.assertEqual(self._get(self.manager, 'list', **params).status_code, 400, params)

    def test_R_이면_보기만_하고_W_가_없으면_등록이_403(self):
        UserGroupMenu.objects.filter(MenuCode='wm_data_register', UserGroup__Code='worker').update(AuthCode='R')
        self.assertEqual(self._get(self.worker, 'list').status_code, 200)
        r = self._post(self.worker, 'upload', item_id=self.item.id, kind='FILE', files=[make_image()])
        self.assertEqual(r.status_code, 403)

    def test_치수_측정_중지_항목은_대상이_아니다(self):
        with tenant_atomic(self.tenant):
            InspectionItem.objects.create(tenant=self.tenant, code='DIM', name='치수', task_type=InspectionItem.TaskType.MEASUREMENT)
            InspectionItem.objects.create(tenant=self.tenant, code='OFF', name='중지', task_type=InspectionItem.TaskType.OBJECT_DETECTION,
                                          status=InspectionItem.Status.PAUSED)
        codes = [i['code'] for i in self._get(self.manager, 'items').json()['items']]
        self.assertEqual(codes, ['API'])
        with tenant_atomic(self.tenant):
            dim = InspectionItem.objects.get(code='DIM')
        r = self._post(self.manager, 'upload', item_id=dim.id, kind='FILE', files=[make_image()])
        self.assertEqual(r.status_code, 400)

    def test_상세_편집_삭제(self):
        self._post(self.manager, 'upload', item_id=self.item.id, kind='FILE', files=[make_image()])
        image_id = self._get(self.manager, 'list').json()['rows'][0]['id']
        detail = self._get(self.manager, 'detail', image_id=image_id).json()
        self.assertEqual((detail['item']['code'], detail['channel_label'], detail['can_preprocess']), ('API', '파일 업로드', True))
        r = self._post(self.manager, 'preprocess', image_id=image_id, Q=json.dumps({'operations': [{'op': 'rotate', 'degrees': 90}]}))
        self.assertEqual(r.status_code, 200, r.content.decode()[:200])
        self.assertEqual((r.json()['image']['width'], r.json()['image']['height']), (48, 64))
        self.assertEqual(self._post(self.manager, 'delete', image_id=image_id).status_code, 200)
        self.assertEqual(self._get(self.manager, 'list').json()['totalRows'], 0)

    def test_검수_완료_삭제는_검수_작업_W_도_있어야_한다(self):
        self.approve_one()
        image_id = self._get(self.manager, 'list').json()['rows'][0]['id']
        self.assertEqual(self._post(self.manager, 'delete', image_id=image_id).status_code, 403)
