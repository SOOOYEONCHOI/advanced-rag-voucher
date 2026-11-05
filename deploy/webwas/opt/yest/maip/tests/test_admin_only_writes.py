"""모든 사용자가 공유하는 설정은 관리자만 바꾼다(사용자 결정, 2026-10-06).

그리드 컬럼 설정(`system/grid_setting`)과 라벨 문구(`common/labels`)는 권한
매핑이 `[]`(로그인만 요구)라, 화면에서 버튼을 관리자에게만 보여도 서버는 누구의
요청이든 받았다. 조회는 모든 화면이 쓰므로 그대로 둔다.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from domain.models.system import GridColumn, LabelCode
from domain.models.user import UserGroup

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
COLUMNS = {'module_name': 'wm_user', 'grid_name': 'grid', 'lang_code': 'ko-KR',
           'Q': '[{"dataField": "login_id", "headerText": "사원번호", "width": 100}]'}
LABEL = {'ModuleName': 'wm_user', 'TemplateKey': 'default', 'LabelCode': 'x.title',
         'Description': '', 'LangCode': 'ko-KR', 'DispText': '제목'}


class AdminOnlySharedSettingTest(TestCase):

    def setUp(self):
        worker = User.objects.create_user('worker1', password='x')
        worker.userprofile.UserGroup = UserGroup.objects.create(Code='user', Name='일반사용자')
        worker.userprofile.save()
        self.worker = worker
        self.admin = User.objects.create_user('admin1', password='x')
        self.admin.userprofile.UserGroup = UserGroup.objects.create(Code='admin', Name='관리자')
        self.admin.userprofile.save()

    def _post(self, user, url, data):
        self.client.force_login(user)
        return self.client.post(url, data, **AJAX)

    def test_일반_사용자는_그리드_컬럼을_저장할_수_없다(self):
        response = self._post(self.worker, '/api/system/grid_setting?action=save_columns', COLUMNS)

        self.assertEqual(response.status_code, 403, response.content.decode()[:200])
        self.assertFalse(GridColumn.objects.exists())

    def test_일반_사용자는_그리드_컬럼을_초기화할_수_없다(self):
        response = self._post(self.worker, '/api/system/grid_setting?action=delete', COLUMNS)

        self.assertEqual(response.status_code, 403)

    def test_일반_사용자는_라벨_문구를_저장할_수_없다(self):
        response = self._post(self.worker, '/api/common/labels?action=save_labelcode_lang', LABEL)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(LabelCode.objects.exists())

    def test_관리자는_그리드_컬럼을_저장할_수_있다(self):
        response = self._post(self.admin, '/api/system/grid_setting?action=save_columns', COLUMNS)

        self.assertEqual(response.status_code, 200, response.content.decode()[:200])
        self.assertTrue(GridColumn.objects.filter(DataField='login_id').exists())
