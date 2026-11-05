"""SQLite 단위 테스트가 닿지 않는 것 — RLS 와 PostgreSQL 전용 raw SQL(메뉴 트리)."""
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase

from domain.models.data import ImageAsset, InspectionItem
from domain.models.user import UserGroup
from domain.services.data.image import ImageService
from domain.tenancy import current_tenant, tenant_atomic
from tests.test_data_services import make_image


class RlsOutsideTenantTest(TransactionTestCase):
    """요청처럼 tenant_atomic 이 가장 바깥 트랜잭션이어야 한다.

    `SET LOCAL app.tenant_id` 는 바깥 트랜잭션이 끝날 때 사라진다. TestCase 는 테스트 전체를 트랜잭션 하나로
    감싸 tenant_atomic 을 나와도 값이 남는다 — 그래서 이 테스트만 TransactionTestCase 다(끝나면 표를 비운다).
    """

    def test_테넌트_밖에서는_0건이고_안에서는_보인다(self):
        tenant = current_tenant()
        with tenant_atomic(tenant):
            item = InspectionItem.objects.create(tenant=tenant, code='PG-RLS', name='PG RLS',
                                                 task_type=InspectionItem.TaskType.OBJECT_DETECTION)
            user = User.objects.create_user('pg-rls', password='x')
            ImageService.upload_images(item, [make_image()], actor=user)
            inside = ImageAsset.objects.for_tenant(tenant).count()
        self.assertGreaterEqual(inside, 1)
        # tenant_atomic 을 나가면 테넌트 설정을 되돌린다 — 그 밖에서는 예외 없이 0건이다(AGENTS [4])
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM vision_data_imageasset')
            self.assertEqual(cursor.fetchone()[0], 0)


class RlsTest(TestCase):
    def test_FORCE_RLS_가_정책_테이블_14개에_걸려_있다(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_class WHERE relname IN (SELECT tablename FROM pg_policies) "
                           "AND relkind = 'r' AND relrowsecurity AND relforcerowsecurity")
            self.assertEqual(cursor.fetchone()[0], 14)  # 0001 의 18개 중 0009 가 쓰지 않는 5개를 지웠고 0017 이 측정점, 0019 가 검사 분류를 더했고 0020 이 배정을 지웠다


class MenuTreeSqlTest(TestCase):
    def test_메뉴_트리_재귀_SQL_이_돈다(self):
        from domain.services.system import SystemService
        call_command('seed_initial', verbosity=0)
        admin = User.objects.create_superuser('pg-admin', password='x')
        admin.userprofile.UserGroup = UserGroup.objects.get(Code='admin')
        admin.userprofile.save()
        menus = SystemService().get_web_menu_list(admin, 'ko-KR')   # v_menu_folder · with recursive
        self.assertTrue(menus)
        self.assertIn('menu_code', menus[0])
