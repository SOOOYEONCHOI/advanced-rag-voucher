"""조직은 YEST 하나이고 모든 사용자가 거기 속한다(사용자 결정, 2026-10-06).

데이터 화면의 조직 접근 판정(`TenantAccessService`)은 조직 소속(`TenantMembership`)을 본다. 사용자 화면의
등록 경로가 소속을 만들지 않아 **사용자 화면에서 만든 사용자가 데이터 화면을 쓰지 못한** 적이 있다.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from app.views.system.user import user as user_api
from domain.models.data import InspectionItem, TenantMembership
from domain.models.user import UserGroup
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic


class SingleOrgTest(TestCase):

    def setUp(self):
        reset_tenant_cache()
        self.admin = User.objects.create_superuser('root', password='x')
        self.group = UserGroup.objects.create(Code='user', Name='일반사용자')

    def test_조직_이름은_YEST_다(self):
        self.assertEqual(current_tenant().name, 'YEST')

    def test_사용자_화면에서_만든_사용자는_배정_후보가_된다(self):
        request = RequestFactory().post('/api/system/user')
        request.user = self.admin
        context = SimpleNamespace(
            request=request, gparam={'action': 'save'},
            posparam={'login_id': 'newbie', 'Name': '신규', 'UserGroup_id': self.group.id,
                      'is_active': 'Y'})

        # MES 의 `DateUtil.get_current_datetime()` 은 시간대가 붙은 시각을 돌려준다.
        # 운영 PostgreSQL 은 받지만 테스트용 SQLite 는 USE_TZ=False 에서 거부한다.
        with patch('app.views.system.user.DateUtil.get_current_datetime',
                   return_value=datetime.now()):
            result = user_api(context)

        self.assertTrue(result.get('success'), result)
        newbie = User.objects.get(username='newbie')
        with tenant_atomic(current_tenant()):
            self.assertTrue(TenantMembership.objects.filter(user=newbie, is_active=True).exists())

    def test_seed_initial_은_조직명을_바꾸고_빠진_소속을_채운다(self):
        orphan = User.objects.create_user('orphan', password='x')
        tenant = current_tenant()
        with tenant_atomic(tenant):
            TenantMembership.objects.filter(user=orphan).delete()
        type(tenant).objects.filter(pk=tenant.pk).update(name='ManufacturingAIPlatform')

        call_command('seed_initial', stdout=open('/dev/null', 'w'))

        tenant.refresh_from_db()
        self.assertEqual(tenant.name, 'YEST')
        with tenant_atomic(tenant):
            self.assertTrue(TenantMembership.objects.filter(user=orphan).exists())


class ItemCreateWithoutOrgTest(TestCase):
    """검사항목 추가 창에 조직 선택이 없다. 서버가 현재 조직(YEST)으로 만든다."""

    def setUp(self):
        reset_tenant_cache()
        self.client.force_login(User.objects.create_superuser('root', password='x'))

    def test_조직을_보내지_않아도_YEST_에_만들어진다(self):
        response = self.client.post(
            '/api/item/item_admin?action=create',
            {'name': '조직 없이 추가', 'task_type': 'OBJECT_DETECTION'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200, response.content.decode())
        with tenant_atomic():
            item = InspectionItem.objects.get(name='조직 없이 추가')
        self.assertEqual(item.tenant_id, current_tenant().id)


class ServiceAccountNotAssignableTest(TestCase):
    """비전검사 클라이언트의 서비스 계정은 배정 후보가 아니다.

    클라이언트가 보낸 이미지의 업로더로만 쓰는 계정이라 로그인할 수 없다.
    조직 소속은 있으므로(업로드가 RLS 안에서 일어난다) 소속만으로 후보를 고르면
    사람처럼 끼어든다.
    """

    def setUp(self):
        reset_tenant_cache()


class DeleteLoggedInUserTest(TestCase):
    """한 번이라도 로그인한 사용자도 지울 수 있다.

    `login_log.User` 가 DO_NOTHING 이라 로그인 기록이 있는 사용자는 외래키에 걸려
    "다른 곳에서 사용되고 있어 삭제할 수 없다"가 됐다. 기록은 `Username` 으로 남긴다.
    """

    def setUp(self):
        reset_tenant_cache()
        self.admin = User.objects.create_superuser('root', password='x')

    def test_로그인_기록이_있어도_지워지고_기록은_남는다(self):
        from domain.models.system import LoginLog
        user = User.objects.create_user('leaver', password='x')
        LoginLog.objects.create(Type='login', User=user, Username='leaver')
        LoginLog.objects.create(Type='login', User=user)  # Username 이 생기기 전 기록
        request = RequestFactory().post('/api/system/user')
        request.user = self.admin
        context = SimpleNamespace(request=request, gparam={'action': 'delete'}, posparam={'id': user.id})

        result = user_api(context)

        self.assertTrue(result.get('success'), result)
        self.assertFalse(User.objects.filter(id=user.id).exists())
        logs = LoginLog.objects.filter(Username='leaver')
        self.assertEqual(logs.count(), 2)
        self.assertFalse(logs.exclude(User=None).exists())


class FixedTenantIdTypeTest(TestCase):
    """조직 행을 처음 만든 프로세스도 id 가 UUID 여야 한다.

    get_or_create 가 행을 만들면 넘긴 값을 그대로 id 로 둔다. 문자열을 넘기면
    `item.tenant_id(UUID) != tenant.id(str)` 이 되어 그 프로세스의 검사항목 접근이
    재시작 전까지 모두 거부됐다.
    """

    def test_처음_만든_조직의_id_도_UUID다(self):
        import uuid

        from domain.models.data import Tenant
        from domain.tenancy import FIXED_TENANT_ID, current_tenant, reset_tenant_cache

        Tenant.objects.filter(pk=FIXED_TENANT_ID).delete()
        reset_tenant_cache()
        self.addCleanup(reset_tenant_cache)

        self.assertIsInstance(current_tenant().id, uuid.UUID)


class TenantAccessMembershipTest(TestCase):
    """멤버십은 RLS 대상이다. 조직 컨텍스트 밖에서 읽으면 운영 DB 에서 0건이다.

    SQLite 테스트에는 RLS 가 없어 0건을 재현할 수 없으므로, 멤버십을 읽는 순간에
    조직 컨텍스트가 열려 있는지를 본다. 호출부가 컨텍스트 밖이어도 그래야 한다.
    """

    def test_멤버십만_있는_사용자도_컨텍스트_밖_호출에서_통과한다(self):
        from unittest.mock import patch

        from domain import tenancy
        from domain.models.data import TenantMembership
        from domain.services.data.tenant_access import TenantAccessService

        tenancy.reset_tenant_cache()
        self.addCleanup(tenancy.reset_tenant_cache)
        tenant = tenancy.current_tenant()
        user = User.objects.create_user('member-only', password='x')
        with tenancy.tenant_atomic(tenant):
            TenantMembership.objects.get_or_create(tenant=tenant, user=user)

        scopes = []
        real_filter = TenantMembership.objects.filter

        def spy(*args, **kwargs):
            scopes.append(tenancy._current_tenant.get())
            return real_filter(*args, **kwargs)

        with patch.object(TenantMembership.objects, 'filter', side_effect=spy):
            self.assertTrue(TenantAccessService.can_access(user, tenant))
        self.assertTrue(scopes, '멤버십을 읽지 않았다')
        self.assertTrue(all(scope is not None for scope in scopes), '조직 컨텍스트 밖에서 멤버십을 읽었다')
