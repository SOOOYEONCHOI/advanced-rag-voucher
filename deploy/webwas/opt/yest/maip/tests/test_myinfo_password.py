"""내 정보의 비밀번호 변경도 비밀번호 정책을 거친다.

관리자 경로(`system/user` 의 `pass_setting`)는 `validate_password` 를 부르지만
내 정보(`system/myinfo`)는 부르지 않아, 화면 검사만 건너뛰면 정책보다 약한
비밀번호로 바꿀 수 있었다.
"""
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from app.views.system.myinfo import myinfo


class MyinfoPasswordPolicyTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('worker1', password='Original-pass-91')

    def _change(self, password, confirm=None, login_id='worker1'):
        request = RequestFactory().post('/api/system/myinfo')
        request.user = self.user
        context = SimpleNamespace(
            request=request, gparam={'action': 'password_change'},
            posparam={'login_id': login_id, 'name': '작업자',
                      'loginPwd': password, 'loginPwd2': password if confirm is None else confirm})
        return myinfo(context)

    def test_확인_비밀번호가_다르면_실패_응답이다(self):
        # 예외를 던지면 500 이 되어 화면에는 일반 오류 문구만 보였다.
        self.assertEqual(self._change('Another-pass-73', confirm='Other-pass-73'),
                         {'success': False, 'message': '비밀번호가 일치하지 않습니다.'})

    def test_다른_사람의_아이디는_실패_응답이다(self):
        self.assertEqual(self._change('Another-pass-73', login_id='someone'),
                         {'success': False, 'message': '본인의 정보만 수정할 수 있습니다.'})

    def test_정책에_어긋나는_비밀번호는_거부한다(self):
        result = self._change('1234')

        self.assertFalse(result.get('success'), result)
        self.assertTrue(result.get('message'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Original-pass-91'))

    def test_정책을_지키면_바뀐다(self):
        result = self._change('Another-pass-73')

        self.assertTrue(result.get('success'), result)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Another-pass-73'))
