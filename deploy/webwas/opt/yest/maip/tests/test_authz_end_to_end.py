"""인가 훅이 실제 요청 경로에서 동작하는지 (Task 1.5 enforce).

단위 테스트(`test_api_authz.py`)는 헬퍼만 본다. 여기서는 URLConf → View →
dispatch 를 실제로 지나가는지 확인한다.
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from domain.models.system import SystemOption
from domain.models.user import UserGroup, UserGroupMenu

PASSWORD = 'correct-horse-battery-staple'


@override_settings(API_AUTHZ_MODE='enforce')
class ApiAuthzEndToEndTest(TestCase):
    def setUp(self):
        cache.clear()
        SystemOption.objects.create(Code='LOGO_TITLE', Value='테스트')
        self.group = UserGroup.objects.create(Code='worker', Name='작업자')
        self.user = User.objects.create_user('worker1', password=PASSWORD)
        self.user.userprofile.UserGroup = self.group
        self.user.userprofile.save()
        self.client = Client()
        self.client.login(username='worker1', password=PASSWORD)

    def _grant(self, menu_code, auth_code):
        UserGroupMenu.objects.update_or_create(
            UserGroup=self.group, MenuCode=menu_code, defaults={'AuthCode': auth_code})

    def _get(self, path):
        return self.client.get(path, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_권한이_없으면_403(self):
        self.assertEqual(self._get('/api/system/user?action=list').status_code, 403)

    def test_권한을_주면_통과하고_회수하면_다시_403(self):
        self._grant('wm_user', 'R')
        self.assertEqual(self._get('/api/system/user?action=list').status_code, 200)

        UserGroupMenu.objects.filter(UserGroup=self.group, MenuCode='wm_user').delete()
        self.assertEqual(self._get('/api/system/user?action=list').status_code, 403)

    def test_읽기_권한만으로는_저장이_막힌다(self):
        self._grant('wm_unit', 'R')
        self.assertEqual(self._get('/api/definition/unit?action=list').status_code, 200)
        response = self.client.post('/api/definition/unit?action=save',
                                    {'name': 'X', 'description': '', 'piece_yn': 'N'},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 403)

    def test_공통_조회_API는_메뉴_권한_없이도_된다(self):
        # /api/system/menus 는 PostgreSQL 전용 SQL(재귀 뷰·LPAD·::TEXT)이라
        # SQLite 테스트 설정에서는 돌릴 수 없다. 실서버 스모크로 확인한다.
        for path in ('/api/system/combo?combo_type=user_group',
                     '/api/system/myinfo?action=detail'):
            self.assertEqual(self._get(path).status_code, 200, path)

    def test_매핑에_없는_경로는_403(self):
        self.assertEqual(self._get('/api/system/nosuchview?action=list').status_code, 403)

    def test_화면도_권한을_확인한다(self):
        self.assertEqual(self.client.get('/gui/wm_user/').status_code, 403)
        self._grant('wm_user', 'R')
        self.assertEqual(self.client.get('/gui/wm_user/').status_code, 200)

    def test_레거시_첨부_경로는_로그인해도_쓸_수_없다(self):
        # 로그인만 확인하던 첨부 업로드·제공·목록·삭제 경로. 화면이 쓰지 않아 지웠다.
        # 작업자가 HTML 을 올려 같은 출처에서 열리게 할 수 있었다(저장형 XSS).
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload = SimpleUploadedFile('x.html', b'<script></script>', content_type='text/html')
        response = self.client.post('/api/files/upload?tableName=t&attachName=b&others=t&accepts=&fileSize=0&addfileext=',
                                    {'DataPk': '0', 'uploadfile': upload})
        self.assertIn(response.status_code, (403, 404), response.content[:200])
        for path in ('/api/files/download?file_id=1', '/api/files/image?id=1', '/api/files/excel_export',
                     '/api/common/attach_file?action=detailFiles&TableName=t&DataPk=0'):
            self.assertIn(self._get(path).status_code, (403, 404), path)
        response = self.client.post('/api/common/attach_file?action=deleteFile', {'fileId': '1'},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertIn(response.status_code, (403, 404))
