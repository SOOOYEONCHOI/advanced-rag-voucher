"""API 오류 응답과 입력 가드.

500 본문에 예외 원문이 실리면 SQL 조각·컬럼명·접속정보가 클라이언트로 샌다
(AGENTS.md "비밀은 소스·커밋·로그·오류 메시지에 넣지 않는다").
"""
import json
from types import SimpleNamespace

from django.test import RequestFactory, TestCase, override_settings

from app.views import MESBaseView
from app.views.system.usergroupmenu import usergroupmenu


class Response500Test(TestCase):
    """500 응답은 호출자가 정한 문구만 내보낸다."""

    def setUp(self):
        self.factory = RequestFactory()
        self.ex = Exception('invalid input syntax for type integer: ""\n'
                            'LINE 47: and ugm."UserGroup_id" = \'\'')

    def _body(self, view, xhr=True):
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if xhr else {}
        request = self.factory.get('/api/system/usergroupmenu', **headers)
        response = view.response500(request, '처리 중 오류가 발생했다.', self.ex)
        return response

    @override_settings(DEBUG=False)
    def test_ApiModuleView_는_예외_원문을_내보내지_않는다(self):
        body = json.loads(self._body(MESBaseView()).content)
        self.assertNotIn('UserGroup_id', json.dumps(body))
        self.assertEqual(body['message'], '처리 중 오류가 발생했다.')

    @override_settings(DEBUG=True)
    def test_DEBUG_에서는_예외를_함께_준다(self):
        body = json.loads(self._body(MESBaseView()).content)
        self.assertIn('UserGroup_id', body['ex'])


class UserGroupMenuReadTest(TestCase):
    """메뉴권한 화면은 그룹을 고르기 전에도 한 번 조회한다."""

    def test_그룹을_고르지_않으면_빈_목록을_준다(self):
        context = SimpleNamespace(
            gparam={'action': 'read', 'group_id': '', 'folder_id': ''},
            posparam={},
            request=None,
        )
        self.assertEqual(usergroupmenu(context), [])


class ReasonPhraseTest(TestCase):
    """오류 응답의 HTTP 상태줄에 한글을 싣지 않는다.

    상태줄은 latin-1 만 쓸 수 있다(PEP 3333). 한글 사유를 `reason=` 으로 넘기면
    WSGI 서버가 응답 머리를 쓰다 `UnicodeEncodeError` 로 실패해, 브라우저는 403 대신
    응답을 받지 못하고 기다린다. 화면은 본문의 `message` 만 읽는다.
    """

    def setUp(self):
        from django.contrib.auth.models import User
        from domain.models.user import UserGroup
        group = UserGroup.objects.create(Code='worker', Name='작업자')
        self.user = User.objects.create_user('worker1', password='x')
        self.user.userprofile.UserGroup = group
        self.user.userprofile.save()

    def test_권한이_없으면_403_본문에만_사유가_실린다(self):
        self.client.force_login(self.user)

        response = self.client.get('/api/system/user?action=read',
                                   HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 403)
        response.reason_phrase.encode('latin-1')
        self.assertEqual(json.loads(response.content)['message'],
                         '이 기능을 사용할 권한이 없습니다.')

    def test_오류_응답_넷_모두_상태줄이_latin1_이다(self):
        request = RequestFactory().get('/api/x', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        view = MESBaseView()
        for response in (view.response401(request, '로그인이 필요합니다.'),
                         view.response403(request, '권한이 없습니다.'),
                         view.response404(request, '찾을 수 없습니다.'),
                         view.response500(request, '오류가 발생했습니다.', None)):
            with self.subTest(status=response.status_code):
                response.reason_phrase.encode('latin-1')


class UserFacingErrorTextTest(TestCase):
    """화면이 받는 공통 오류 문구는 한국어이고 내부 이름을 담지 않는다."""

    def test_로그인이_끝난_Ajax_요청은_한국어로_안내한다(self):
        response = self.client.get('/api/system/user', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(json.loads(response.content)['message'], '로그인이 만료되었습니다. 다시 로그인해 주세요.')

    def test_권한이_없는_화면은_한국어_오류_페이지를_보인다(self):
        from django.contrib.auth.models import User
        user = User.objects.create_user('no-menu-user', password='x')
        self.client.force_login(user)
        response = self.client.get('/gui/wm_user/')
        self.assertEqual(response.status_code, 403)
        body = response.content.decode()
        self.assertIn('이 화면을 볼 권한이 없습니다.', body)
        self.assertNotIn('No access allowed', body)
        self.assertNotIn('404 Error', body)
