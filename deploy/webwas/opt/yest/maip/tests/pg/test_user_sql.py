"""사용자 화면의 raw SQL(PostgreSQL 전용 `to_char`)이 소속 부서 이름을 준다."""
from django.contrib.auth.models import User
from django.test import TestCase

from domain.models.system import Depart
from domain.services.account import AccountService


class UserDepartSqlTest(TestCase):
    def setUp(self):
        self.dept = Depart.objects.create(Code='PG-D10', Name='pg-생산팀')
        self.worker = User.objects.create_user('pg-worker', password='x')
        self.worker.userprofile.Depart = self.dept
        self.worker.userprofile.save()
        self.nobody = User.objects.create_user('pg-nobody', password='x')

    def test_목록과_상세에_부서가_나온다(self):
        rows = {r['login_id']: r for r in AccountService().get_user_list(True, '', '')}
        self.assertEqual((rows['pg-worker']['Depart_id'], rows['pg-worker']['depart_name']), (self.dept.id, 'pg-생산팀'))
        self.assertEqual((rows['pg-nobody']['Depart_id'], rows['pg-nobody']['depart_name']), (None, None))
        self.assertEqual(AccountService().get_user_detail(self.worker.id)['depart_name'], 'pg-생산팀')
