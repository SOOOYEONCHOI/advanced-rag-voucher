"""로그 화면의 raw SQL(PostgreSQL 전용 `to_char`·`ilike`)이 사람이 읽는 값을 준다."""
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import TestCase

from app.views.system.menulog import menulog
from domain.models.system import LoginLog, MenuFolder, MenuItem, MenuUseLog
from domain.services.system import SystemService

DAY = ('2000-01-01 00:00:00', '2999-12-31 23:59:59')


class LoginLogSqlTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('pg-worker', password='x')
        self.user.userprofile.Name = '작업자'
        self.user.userprofile.save()
        LoginLog.objects.create(Type='login', User=self.user, Username='pg-worker', IPAddress='10.0.0.1')
        # 실패는 User 가 비어 있다(account.py) — 시도한 아이디만 남는다
        LoginLog.objects.create(Type='fail', Username='pg-worker', IPAddress='10.0.0.1',
                                FailReason='아이디 또는 비밀번호 불일치')
        LoginLog.objects.create(Type='fail', Username='pg-ghost', IPAddress='10.0.0.2',
                                FailReason='아이디 또는 비밀번호 불일치')

    def _rows(self, keyword=None):
        return SystemService().get_loginlog_list(*DAY, keyword)['rows']

    def test_실패_기록도_아이디와_사유가_보인다(self):
        rows = {(r['type'], r['login_id']): r for r in self._rows()}
        self.assertEqual(rows[('실패', 'pg-ghost')]['fail_reason'], '아이디 또는 비밀번호 불일치')
        self.assertEqual(rows[('실패', 'pg-worker')]['name'], '작업자')
        self.assertEqual(rows[('로그인', 'pg-worker')]['name'], '작업자')

    def test_검색은_시도한_아이디도_찾는다(self):
        self.assertEqual([r['login_id'] for r in self._rows('ghost')], ['pg-ghost'])


class MenuLogSqlTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('pg-viewer', password='x')
        self.user.userprofile.Name = '열람자'
        self.user.userprofile.save()
        folder = MenuFolder.objects.create(FolderName='PG 폴더')
        MenuItem.objects.create(MenuCode='pg_menu', MenuName='PG 메뉴', MenuFolder=folder)
        for _ in range(3):
            MenuUseLog.objects.create(MenuCode='pg_menu', User=self.user)
        # 메뉴에서 내린 화면의 기록 — menu_item 에 없다
        MenuUseLog.objects.create(MenuCode='wm_code', User=self.user)

    def _call(self, **gparam):
        params = {'date_from': '2000-01-01', 'date_to': '2999-12-31'}
        params.update(gparam)
        return menulog(SimpleNamespace(gparam=params, posparam={}, request=None))

    def test_건수는_많은_순이고_내린_메뉴도_이름이_있다(self):
        rows = self._call(action='log_count', cboUser=self.user.id)
        self.assertEqual([(r['menu_name'], r['use_count']) for r in rows], [('PG 메뉴', 3), ('코드정보', 1)])
        self.assertEqual(rows[1]['folder_name'], '메뉴에서 내림')

    def test_기록에도_내린_메뉴_이름이_있다(self):
        rows = self._call(action='log_list', cboUser=self.user.id)['rows']
        self.assertIn('코드정보', [r['menu_name'] for r in rows])

    def test_사용자_콤보는_이름과_아이디다(self):
        texts = [r['text'] for r in self._call(action='user_list')]
        self.assertIn('열람자(pg-viewer)', texts)
