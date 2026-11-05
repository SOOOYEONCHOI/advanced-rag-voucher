"""시스템 관리 화면이 받는 message 는 사용자가 읽는 문구다 — 예외 원문(SQL·영문)을 내보내지 않는다."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from app.views.system.menu_language import menu_language
from app.views.system.user import user
from app.views.system.usergroup import usergroup
from domain.models.user import UserGroup

FAILED = '처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'


class SystemViewMessageTest(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user('admin1', password='x')
        self.group = UserGroup.objects.create(Code='user', Name='일반사용자')

    def _call(self, view, gparam, posparam):
        request = RequestFactory().post('/api/system/x')
        request.user = self.admin
        return view(SimpleNamespace(request=request, gparam=gparam, posparam=posparam))

    def _save_user(self, **posparam):
        data = {'login_id': 'worker1', 'Name': '작업자', 'UserGroup_id': self.group.id, 'is_active': 'on'}
        data.update(posparam)
        return self._call(user, {'action': 'save'}, data)

    def test_아이디가_비면_입력하라고_한다(self):
        self.assertEqual(self._save_user(login_id=' '), {'success': False, 'message': '아이디를 입력해 주세요.'})

    def test_쓰고_있는_아이디면_그렇게_말한다(self):
        User.objects.create_user('worker1', password='x')
        self.assertEqual(self._save_user(), {'success': False, 'message': '이미 쓰고 있는 아이디입니다.'})

    def test_같은_사용자를_고쳐_저장하는_것은_중복이_아니다(self):
        # DateUtil 은 tz 가 붙은 시각을 준다 — SQLite(USE_TZ=False)가 받지 않아 naive 로 바꾼다
        with patch('app.views.system.user.DateUtil.get_current_datetime', return_value=datetime(2026, 1, 1)):
            created = self._save_user()
            self.assertTrue(self._save_user(id=created['id'], Name='작업자2')['success'], created)

    def test_이름이나_그룹이_비면_입력하라고_한다(self):
        self.assertEqual(self._save_user(Name=' '), {'success': False, 'message': '이름을 입력해 주세요.'})
        self.assertEqual(self._save_user(UserGroup_id=''), {'success': False, 'message': '사용자 그룹을 골라 주세요.'})
        self.assertFalse(User.objects.filter(username='worker1').exists())

    def test_고쳐_저장해도_생성일은_그대로다(self):
        with patch('app.views.system.user.DateUtil.get_current_datetime', return_value=datetime(2026, 1, 1)):
            created = self._save_user()
        with patch('app.views.system.user.DateUtil.get_current_datetime', return_value=datetime(2026, 5, 5)):
            self.assertTrue(self._save_user(id=created['id'], Name='작업자2')['success'])
        self.assertEqual(User.objects.get(id=created['id']).date_joined.date().isoformat(), '2026-01-01')

    def test_사용자_저장_오류는_원문을_내보내지_않는다(self):
        with patch('app.views.system.user.User.save', side_effect=Exception('relation "x" does not exist')):
            self.assertEqual(self._save_user(), {'success': False, 'message': FAILED})

    def test_비밀번호_정책_위반은_한_줄에_하나씩이다(self):
        target = User.objects.create_user('worker2', password='x')
        result = self._call(user, {'action': 'pass_setting'}, {'id': target.id, 'pass1': '1234', 'pass2': '1234'})
        self.assertFalse(result['success'])
        self.assertIn('\n', result['message'])

    def test_비밀번호가_다르면_비밀번호라고_부른다(self):
        target = User.objects.create_user('worker3', password='x')
        result = self._call(user, {'action': 'pass_setting'}, {'id': target.id, 'pass1': 'a', 'pass2': 'b'})
        self.assertEqual(result['message'], '비밀번호가 일치하지 않습니다.')

    def test_사용자그룹_저장_오류는_원문을_내보내지_않는다(self):
        with patch('app.views.system.usergroup.UserGroup.save', side_effect=Exception('duplicate key')):
            result = self._call(usergroup, {'action': 'save'}, {'code': 'g1', 'name': '그룹'})
        self.assertEqual(result, {'success': False, 'message': FAILED})

    def test_메뉴명_저장은_성공을_알린다(self):
        result = self._call(menu_language, {'action': 'labellang_save'},
                            {'ModuleName': 'common', 'TemplateKey': 'menu', 'LabelCode': '사용자',
                             'LangCode': 'ko-KR', 'DispText': '사용자'})
        self.assertEqual(result, {'success': True})

    def test_메뉴명_저장_오류는_원문을_내보내지_않는다(self):
        with patch('app.views.system.menu_language.LabelCodeLanguage.save', side_effect=Exception('boom')):
            result = self._call(menu_language, {'action': 'labellang_save'},
                                {'ModuleName': 'common', 'TemplateKey': 'menu', 'LabelCode': '사용자',
                                 'LangCode': 'ko-KR', 'DispText': '사용자'})
        self.assertEqual(result, {'success': False, 'message': FAILED})


class UserGroupSaveTest(TestCase):
    """사용자그룹 등록 모달·상세 수정이 부르는 저장 — 필수 값·중복 코드를 서버도 막고, 고칠 때 코드는 바꾸지 않는다."""

    def setUp(self):
        self.admin = User.objects.create_user('admin1', password='x')

    def _save(self, **posparam):
        request = RequestFactory().post('/api/system/usergroup')
        request.user = self.admin
        return usergroup(SimpleNamespace(request=request, gparam={'action': 'save'}, posparam=posparam))

    def test_코드나_그룹명이_비면_입력하라고_한다(self):
        self.assertEqual(self._save(code=' ', name='작업자'), {'success': False, 'message': '코드와 그룹명을 입력해 주세요.'})
        self.assertEqual(self._save(code='worker', name=''), {'success': False, 'message': '코드와 그룹명을 입력해 주세요.'})
        self.assertFalse(UserGroup.objects.exists())

    def test_같은_코드는_다시_만들지_않는다(self):
        UserGroup.objects.create(Code='worker', Name='작업자')
        self.assertEqual(self._save(code='worker', name='다른 이름'), {'success': False, 'message': '같은 코드의 그룹이 이미 있습니다.'})
        self.assertEqual(UserGroup.objects.count(), 1)

    def test_고칠_때는_코드를_바꾸지_않고_이름_사용_설명만_바꾼다(self):
        # 코드는 소스가 찾는 값이다(admin·user·dev)
        group = UserGroup.objects.create(Code='admin', Name='관리자')
        self.assertEqual(self._save(id=group.id, code='hacked', name='관리자2', description='설명', disabled='')['success'], True)
        group.refresh_from_db()
        self.assertEqual((group.Code, group.Name, group.Description, group.Disabled), ('admin', '관리자2', '설명', True))
