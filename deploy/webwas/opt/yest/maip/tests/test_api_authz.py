"""`/api/<task>/<view>` 인가 훅 (Task 1.1).

원본 MES는 로그인만 하면 모든 업무 API를 호출할 수 있었다. `apiPermissionMap`은
정의만 되고 호출되지 않는 죽은 코드였다. 여기서 그 맵이 실제로 동작하는지 본다.
"""
from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, TestCase, override_settings

from app.views import authorize_menu_codes
from domain.gui import GUIConfiguration
from domain.models.user import UserGroup, UserGroupMenu


class AuthorizeMenuCodesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.factory = RequestFactory()
        cls.viewer_group = UserGroup.objects.create(Code='viewer', Name='조회전용')
        cls.other_group = UserGroup.objects.create(Code='other', Name='무권한')

        cls.viewer = User.objects.create_user('viewer', password='x')
        cls.viewer.userprofile.UserGroup = cls.viewer_group
        cls.viewer.userprofile.save()

        cls.stranger = User.objects.create_user('stranger', password='x')
        cls.stranger.userprofile.UserGroup = cls.other_group
        cls.stranger.userprofile.save()

        cls.orphan = User.objects.create_user('orphan', password='x')  # 그룹 없음

        cls.admin = User.objects.create_user('root', password='x', is_superuser=True)

        # 조회전용 그룹은 wm_user 를 읽기만 할 수 있다.
        UserGroupMenu.objects.create(UserGroup=cls.viewer_group, MenuCode='wm_user', AuthCode='R')

    def _request(self, user, method='GET'):
        request = getattr(self.factory, method.lower())('/api/system/user')
        request.user = user
        return request

    # --- 매핑이 있는 경로 -------------------------------------------------

    def test_읽기_권한이_있으면_GET_통과(self):
        self.assertIsNone(
            authorize_menu_codes(self._request(self.viewer), ['wm_user'], 'system/user'))

    def test_읽기_권한만_있으면_POST_거부(self):
        denied = authorize_menu_codes(
            self._request(self.viewer, 'POST'), ['wm_user'], 'system/user')
        self.assertIsNotNone(denied)
        # 내부 API 경로는 사용자에게 보이지 않는다. 로그에만 남는다(사용자 결정, 2026-10-06).
        self.assertNotIn('system/user', denied)

    def test_읽기_권한만_있으면_PUT_PATCH_DELETE_도_거부(self):
        # 데이터 API 는 이미지 삭제·전처리 저장·라벨 임시저장을 PUT·DELETE 로 한다.
        # POST 만 쓰기로 보던 때는 조회전용 그룹이 메뉴 검사를 통과했다.
        for method in ('PUT', 'PATCH', 'DELETE'):
            with self.subTest(method=method):
                self.assertIsNotNone(authorize_menu_codes(
                    self._request(self.viewer, method), ['wm_user'], 'system/user'))

    def test_권한이_없는_그룹은_거부(self):
        self.assertIsNotNone(
            authorize_menu_codes(self._request(self.stranger), ['wm_user'], 'system/user'))

    def test_여러_메뉴중_하나라도_권한이_있으면_통과(self):
        self.assertIsNone(authorize_menu_codes(
            self._request(self.viewer), ['wm_prop_master', 'wm_user'], 'system/user'))

    def test_superuser는_항상_통과(self):
        self.assertIsNone(authorize_menu_codes(
            self._request(self.admin, 'POST'), ['wm_user'], 'system/user'))

    def test_그룹_없는_계정은_거부되고_예외를_내지_않는다(self):
        self.assertIsNotNone(
            authorize_menu_codes(self._request(self.orphan), ['wm_user'], 'system/user'))

    # --- 빈 목록 / 미등록 -------------------------------------------------

    def test_빈_목록은_로그인만_요구(self):
        self.assertIsNone(
            authorize_menu_codes(self._request(self.stranger), [], 'system/combo'))

    @override_settings(API_AUTHZ_MODE='warn')
    def test_warn_모드에서_미등록_경로는_통과하고_경고를_남긴다(self):
        with self.assertLogs('app.views', level='WARNING') as captured:
            self.assertIsNone(
                authorize_menu_codes(self._request(self.stranger), None, 'system/unknown'))
        self.assertIn('system/unknown', ''.join(captured.output))

    @override_settings(API_AUTHZ_MODE='enforce')
    def test_enforce_모드에서_미등록_경로는_거부(self):
        self.assertIsNotNone(
            authorize_menu_codes(self._request(self.stranger), None, 'system/unknown'))

    @override_settings(API_AUTHZ_MODE='off')
    def test_off_모드는_검사하지_않는다(self):
        self.assertIsNone(
            authorize_menu_codes(self._request(self.stranger, 'POST'), ['wm_user'], 'system/user'))


class PermissionMapTest(TestCase):
    """맵 자체의 정합성. `scripts/verify/verify_permission_map.py` 와 같은 규칙이다."""

    def test_매핑이_가리키는_메뉴코드는_모두_실재한다(self):
        GUIConfiguration.__static_init__()
        gui_codes = set(GUIConfiguration.menu_init())
        for key, codes in GUIConfiguration.taskview_menu_code_map().items():
            for code in codes:
                self.assertIn(code, gui_codes, f'{key} 가 없는 화면을 가리킨다: {code}')

    def test_page_매핑도_같은_규칙을_따른다(self):
        from domain.gui import PAGE_PERMISSION_MAP

        GUIConfiguration.__static_init__()
        gui_codes = set(GUIConfiguration.menu_init())
        for key, codes in PAGE_PERMISSION_MAP.items():
            for code in codes:
                self.assertIn(code, gui_codes, f'{key} 가 없는 화면을 가리킨다: {code}')
