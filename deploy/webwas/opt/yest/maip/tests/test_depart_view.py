"""부서 정보 API(`/api/system/depart`)와 사용자 소속 부서 — 코드는 등록 때만 받고, 사용자가 있는 부서는 지우지 않는다(사용자 결정 2026-10-26)."""
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from app.views.system.depart import depart
from app.views.system.user import user
from domain.gui import GUIConfiguration
from domain.models.system import Depart
from domain.models.user import UserGroup


class DepartViewTest(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user('admin1', password='x')

    def _call(self, view, action, **posparam):
        request = RequestFactory().post('/api/system/depart')
        request.user = self.admin
        return view(SimpleNamespace(request=request, gparam={'action': action}, posparam=posparam))

    def test_시스템_관리_화면이고_자기_메뉴_권한으로_부른다(self):
        self.assertEqual(GUIConfiguration.get_gui_info('wm_depart')['name'], '부서 정보')
        self.assertEqual(GUIConfiguration.get_menu_code_by_taskview('system', 'depart'), ['wm_depart'])
        self.assertIsNone(GUIConfiguration.get_menu_code_by_taskview('definition', 'depart'))

    def test_등록하면_코드순_목록에_나온다(self):
        self.assertTrue(self._call(depart, 'save', code='D20', name='품질팀', type='', description='')['success'])
        self.assertTrue(self._call(depart, 'save', code='D10', name='생산팀', type='현장', description='1공장')['success'])
        self.assertEqual([{k: r[k] for k in ('code', 'name', 'type', 'description')} for r in self._call(depart, 'read')], [
            {'code': 'D10', 'name': '생산팀', 'type': '현장', 'description': '1공장'},
            {'code': 'D20', 'name': '품질팀', 'type': None, 'description': None}])

    def test_코드와_부서명은_필수이고_코드에_공백을_넣지_않는다(self):
        need = {'success': False, 'message': '코드와 부서명을 입력해 주세요.'}
        self.assertEqual(self._call(depart, 'save', code=' ', name='생산팀'), need)
        self.assertEqual(self._call(depart, 'save', code='D10', name=''), need)
        self.assertEqual(self._call(depart, 'save', code='D 10', name='생산팀'),
                         {'success': False, 'message': '코드에는 공백을 넣을 수 없습니다.'})
        self.assertFalse(Depart.objects.exists())

    def test_같은_코드나_이름은_다시_만들지_않는다(self):
        Depart.objects.create(Code='D10', Name='생산팀')
        self.assertEqual(self._call(depart, 'save', code='D10', name='다른 팀'),
                         {'success': False, 'message': '같은 코드의 부서가 이미 있습니다.'})
        self.assertEqual(self._call(depart, 'save', code='D20', name='생산팀'),
                         {'success': False, 'message': '같은 이름의 부서가 이미 있습니다.'})
        self.assertEqual(Depart.objects.count(), 1)

    def test_고칠_때는_코드를_바꾸지_않는다(self):
        dept = Depart.objects.create(Code='D10', Name='생산팀')
        Depart.objects.create(Code='D20', Name='품질팀')
        self.assertEqual(self._call(depart, 'save', id=dept.id, name='품질팀'),
                         {'success': False, 'message': '같은 이름의 부서가 이미 있습니다.'})
        self.assertTrue(self._call(depart, 'save', id=dept.id, code='HACK', name='생산1팀', type='현장', description='')['success'])
        dept.refresh_from_db()
        self.assertEqual((dept.Code, dept.Name, dept.Type, dept.Description), ('D10', '생산1팀', '현장', None))

    def test_사용자가_있는_부서는_지우지_않는다(self):
        dept = Depart.objects.create(Code='D10', Name='생산팀')
        worker = User.objects.create_user('worker1', password='x')
        worker.userprofile.Depart = dept
        worker.userprofile.save()
        self.assertEqual(self._call(depart, 'delete', id=dept.id), {
            'success': False, 'message': '사용 중인 부서입니다. 이 부서의 사용자 1명을 다른 부서로 옮긴 뒤 삭제해 주세요.'})
        self.assertTrue(Depart.objects.filter(id=dept.id).exists())

        worker.userprofile.Depart = None
        worker.userprofile.save()
        self.assertEqual(self._call(depart, 'delete', id=dept.id), {'success': True})
        self.assertFalse(Depart.objects.exists())

    def test_사용자에_부서를_저장하고_비우면_소속이_없다(self):
        # 목록·상세의 부서명(raw SQL)은 tests/pg/test_user_sql.py 가 본다
        group = UserGroup.objects.create(Code='user', Name='일반사용자')
        dept = Depart.objects.create(Code='D10', Name='생산팀')
        worker = User.objects.create_user('worker1', password='x')
        data = {'id': worker.id, 'login_id': 'worker1', 'Name': '작업자', 'UserGroup_id': group.id, 'is_active': 'on'}
        self.assertTrue(self._call(user, 'save', Depart_id=dept.id, **data)['success'])
        self.assertEqual(User.objects.get(id=worker.id).userprofile.Depart_id, dept.id)

        self.assertTrue(self._call(user, 'save', Depart_id='', **data)['success'])
        self.assertIsNone(User.objects.get(id=worker.id).userprofile.Depart_id)

    def test_없는_부서는_사용자에_저장하지_않는다(self):
        group = UserGroup.objects.create(Code='user', Name='일반사용자')
        res = self._call(user, 'save', login_id='worker1', Name='작업자', UserGroup_id=group.id, Depart_id=999999)
        self.assertEqual(res, {'success': False, 'message': '부서를 찾을 수 없습니다. 목록을 다시 열어 주세요.'})
        self.assertFalse(User.objects.filter(username='worker1').exists())
