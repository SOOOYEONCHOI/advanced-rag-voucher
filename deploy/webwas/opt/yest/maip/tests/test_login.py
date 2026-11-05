"""로그인 하드닝 (Task 1.2)."""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase

from domain.models.system import LoginLog, SystemOption
from domain.models.user import UserGroup
from domain.services import login_throttle

PASSWORD = 'correct-horse-battery-staple'


class LoginTest(TestCase):
    def setUp(self):
        cache.clear()
        SystemOption.objects.create(Code='LOGO_TITLE', Value='테스트')
        group = UserGroup.objects.create(Code='user', Name='일반')
        self.user = User.objects.create_user('tester', password=PASSWORD)
        self.user.userprofile.UserGroup = group
        self.user.userprofile.save()
        self.client = Client()

    def _post(self, username='tester', password=PASSWORD, **extra):
        return self.client.post('/login/', {'username': username, 'password': password},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest', **extra)

    def test_정상_로그인(self):
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['loginResult'], 'OK')
        self.assertTrue(LoginLog.objects.filter(Type='login', User=self.user).exists())

    def test_비밀번호_틀리면_실패가_기록된다(self):
        response = self._post(password='wrong')
        self.assertEqual(response.json()['loginResult'], 'ETC')
        self.assertEqual(response.json()['loginResultMsg'], '아이디 또는 비밀번호가 맞지 않습니다.')
        log = LoginLog.objects.get(Type='fail')
        self.assertEqual(log.Username, 'tester')
        self.assertIsNone(log.User)
        self.assertIn('불일치', log.FailReason)

    def test_없는_계정도_시도한_아이디가_남는다(self):
        self._post(username='ghost', password='x')
        self.assertTrue(LoginLog.objects.filter(Type='fail', Username='ghost').exists())

    def test_실패_5회면_잠기고_이후_올바른_비밀번호도_거부(self):
        for _ in range(login_throttle.MAX_FAILURES - 1):
            self.assertEqual(self._post(password='wrong').json()['loginResult'], 'ETC')

        locked = self._post(password='wrong').json()
        self.assertEqual(locked['loginResult'], 'LOCKED')
        self.assertEqual(locked['loginResultMsg'], '로그인 시도가 많아 잠겼습니다. 5분 뒤에 다시 시도해 주세요.')
        # 잠긴 뒤에는 올바른 비밀번호도 통과하지 못한다.
        self.assertEqual(self._post().json()['loginResult'], 'LOCKED')

    def test_잠금_문구는_남은_시간을_분으로_올려_말한다(self):
        from unittest.mock import patch
        with patch('app.views.account.login_throttle.seconds_locked', return_value=61):
            message = self._post().json()['loginResultMsg']
        self.assertEqual(message, '로그인 시도가 많아 잠겼습니다. 2분 뒤에 다시 시도해 주세요.')

    def test_잠금이_풀리면_다시_로그인된다(self):
        for _ in range(login_throttle.MAX_FAILURES):
            self._post(password='wrong')
        self.assertEqual(self._post().json()['loginResult'], 'LOCKED')

        cache.clear()  # 잠금 시간 경과와 같은 효과
        self.assertEqual(self._post().json()['loginResult'], 'OK')

    def test_다른_IP는_따로_센다(self):
        for _ in range(login_throttle.MAX_FAILURES):
            self._post(password='wrong', REMOTE_ADDR='10.0.0.1')
        self.assertEqual(self._post(REMOTE_ADDR='10.0.0.1').json()['loginResult'], 'LOCKED')
        # 아이디만으로 잠그면 누구나 남의 로그인을 막을 수 있다. 주소가 다르면 통과해야 한다.
        self.assertEqual(self._post(REMOTE_ADDR='10.0.0.2').json()['loginResult'], 'OK')

    def test_프록시가_아닌_곳에서_온_주소_헤더는_믿지_않는다(self):
        # X-Forwarded-For 첫 값을 믿어 값만 바꾸면 무한 대입이 됐다.
        for i in range(login_throttle.MAX_FAILURES):
            self._post(password='wrong', REMOTE_ADDR='10.0.0.9',
                       HTTP_X_FORWARDED_FOR=f'10.9.9.{i}', HTTP_X_REAL_IP=f'10.8.8.{i}')
        self.assertEqual(self._post(REMOTE_ADDR='10.0.0.9').json()['loginResult'], 'LOCKED')

    def test_같은_호스트의_nginx_뒤에서는_X_Real_IP_로_센다(self):
        for i in range(login_throttle.MAX_FAILURES):
            self._post(password='wrong', REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP='10.0.0.1',
                       HTTP_X_FORWARDED_FOR=f'10.9.9.{i}')       # XFF 를 바꿔도 같은 주소다
        self.assertEqual(self._post(REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP='10.0.0.1')
                         .json()['loginResult'], 'LOCKED')
        self.assertEqual(self._post(REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP='10.0.0.2')
                         .json()['loginResult'], 'OK')

    def test_운영_캐시는_워커끼리_공유된다(self):
        # LocMemCache 는 프로세스별이라 gunicorn 워커 수만큼 실패 횟수가 늘어난다.
        from configurations import settings as base
        self.assertNotIn('locmem', base.CACHES['default']['BACKEND'].lower())

    def test_로그인_기록이_실패해도_로그아웃된다(self):
        from unittest.mock import patch
        self._post()
        self.assertIn('_auth_user_id', self.client.session)
        with patch('app.views.account.LoginLog.objects.create', side_effect=RuntimeError('db down')):
            self.client.get('/logout/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_세션은_8시간_쓰지_않으면_끝난다(self):
        from django.conf import settings
        self.assertEqual(settings.SESSION_COOKIE_AGE, 8 * 3600)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)   # 요청마다 만료를 미룬다 = 유휴 만료

    def test_비활성_계정은_거부된다(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self._post().json()['loginResult'], 'INACTIVE')

    def test_로그인_후_비활성화되면_기존_세션도_막힌다(self):
        self.assertEqual(self._post().json()['loginResult'], 'OK')
        self.user.is_active = False
        self.user.save()
        response = self.client.get('/api/system/myinfo?action=detail',
                                   HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 401)

    def test_미인증_API_호출은_401(self):
        response = Client().get('/api/system/user?action=list',
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 401)


class HomeDefaultMenuTest(TestCase):
    """로그인 뒤 첫 화면(고정 첫 탭)은 메뉴 맨 위의 대시보드다(사용자 결정 2026-10-21). 시스템 옵션 main_menu 로 바꿀 수 있다."""

    def setUp(self):
        SystemOption.objects.create(Code='LOGO_TITLE', Value='테스트')
        User.objects.create_user('tester', password=PASSWORD)
        self.client = Client()
        self.client.login(username='tester', password=PASSWORD)

    def test_옵션이_없으면_대시보드다(self):
        self.assertEqual(self.client.get('/').context['default_menu_code'], 'wm_dashboard')

    def test_옵션이_있으면_그_화면이다(self):
        SystemOption.objects.create(Code='main_menu', Value='wm_data_item')
        self.assertEqual(self.client.get('/').context['default_menu_code'], 'wm_data_item')


class HomeWeragLinkTest(TestCase):
    """상단 바 We.RAG 로고는 .env 의 WERAG_URL 로 새 탭을 연다. 비거나 http(s) 가 아니면 보이지 않는다."""

    def setUp(self):
        User.objects.create_user('tester', password=PASSWORD)
        self.client = Client()
        self.client.login(username='tester', password=PASSWORD)

    def test_주소가_있으면_새_탭_링크가_나온다(self):
        with self.settings(WERAG_URL='https://chatbot.example.com/'):
            response = self.client.get('/')
        self.assertContains(response, 'href="https://chatbot.example.com/" target="_blank" rel="noopener noreferrer"')
        self.assertContains(response, 'werag-logo.png')

    def test_주소가_비면_로고가_없다(self):
        with self.settings(WERAG_URL=''):
            response = self.client.get('/')
        self.assertNotContains(response, 'werag-logo.png')

    def test_http_가_아닌_주소는_링크로_넣지_않는다(self):
        with self.settings(WERAG_URL='javascript:alert(1)'):
            response = self.client.get('/')
        self.assertNotContains(response, 'werag-logo.png')
        self.assertNotContains(response, 'javascript:alert(1)')


class SettingsDefaultTest(TestCase):
    """.env 를 빠뜨린 운영이 DEBUG 로 뜨지 않는다."""

    def test_DEBUG_기본값은_False(self):
        import importlib
        import os
        from unittest.mock import patch

        from configurations import env as env_module
        import configurations.settings as base
        with patch.dict(os.environ, {'DEBUG': '', 'ALLOWED_HOSTS': 'x', 'SECRET_KEY': 'k' * 50}), \
             patch.object(env_module, 'load_dotenv', lambda *a, **k: None):
            reloaded = importlib.reload(base)
            debug = reloaded.DEBUG
        importlib.reload(base)   # 다른 테스트를 위해 원래 값으로
        self.assertFalse(debug)
