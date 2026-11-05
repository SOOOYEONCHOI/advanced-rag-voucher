"""DB 로그 보존 — 시스템로그 90일, 로그인·메뉴 로그 365일(사용자 결정 2026-10-07, 점검 #19)."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone

from domain.models.system import LoginLog, MenuUseLog, SystemLog
from domain.services import log_retention


class LogRetentionTest(TestCase):
    def _aged(self, model, days, **fields):
        row = model.objects.create(**fields)
        model.objects.filter(pk=row.pk).update(_created=timezone.now() - timedelta(days=days))
        return row

    def test_보존_기간이_지난_로그만_지운다(self):
        user = User.objects.create_user('log-user', password='x')
        old_sys = self._aged(SystemLog, 91, Type='info', Source='test', Message='old')
        new_sys = self._aged(SystemLog, 89, Type='info', Source='test', Message='new')
        self._aged(LoginLog, 366, Type='fail', Username='x')
        new_login = self._aged(LoginLog, 364, Type='fail', Username='x')
        self._aged(MenuUseLog, 366, MenuCode='wm_user', User=user)
        new_menu = self._aged(MenuUseLog, 10, MenuCode='wm_user', User=user)

        self.assertEqual(log_retention.purge(), {'sys_log': 1, 'login_log': 1, 'menu_use_log': 1, 'django_session': 0})
        self.assertFalse(SystemLog.objects.filter(pk=old_sys.pk).exists())
        self.assertEqual({SystemLog.objects.get().pk, LoginLog.objects.get().pk, MenuUseLog.objects.get().pk},
                         {new_sys.pk, new_login.pk, new_menu.pk})

    def test_만료된_로그인_세션만_지운다(self):
        now = timezone.now()
        Session.objects.create(session_key='expired', session_data='', expire_date=now - timedelta(minutes=1))
        Session.objects.create(session_key='alive', session_data='', expire_date=now + timedelta(hours=1))

        self.assertEqual(log_retention.purge(now)['django_session'], 1)
        self.assertEqual(list(Session.objects.values_list('session_key', flat=True)), ['alive'])
