"""검사항목 관리 화면의 명령(추가·상태 전환) — `/api/item/item_admin`.

REST 시절 화면이 보내던 주소에 라우트가 없어 추가·상태 전환이 404·500 이었다.
MES API 로 옮긴 뒤에도 같은 두 동작이 되는지 지킨다.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from domain.models.data import InspectionItem
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic


class ItemAdminCommandRouteTest(TestCase):

    def setUp(self):
        reset_tenant_cache()
        self.client.force_login(User.objects.create_superuser('root', password='x'))
        with tenant_atomic():
            self.item = InspectionItem.objects.create(tenant=current_tenant(), name='경로 확인')

    def test_화면이_쓰는_주소로_상태를_바꿀_수_있다(self):
        before = self.item.status

        response = self.client.post(
            '/api/item/item_admin?action=toggle_status', {'item_id': self.item.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200, response.content.decode()[:200])
        with tenant_atomic():
            self.item.refresh_from_db()
        self.assertNotEqual(self.item.status, before)

    def test_검사항목을_연달아_추가할_수_있다(self):
        # 추가 창은 코드를 받지 않는다. 코드가 unique 인데 빈 값으로 저장하면
        # 두 번째 추가부터 unique 위반이 난다.
        for name in ('첫째', '둘째'):
            response = self.client.post(
                '/api/item/item_admin?action=create', {'name': name},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 200, response.content.decode()[:200])
        with tenant_atomic():
            codes = list(InspectionItem.objects.filter(name__in=('첫째', '둘째')).values_list('code', flat=True))
        self.assertEqual(len(set(codes)), 2)
        self.assertNotIn('', codes)
