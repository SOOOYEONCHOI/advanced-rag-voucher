"""메뉴명 설정의 조회가 데이터를 만들지 않는다.

`menu_language_list` 는 조회 액션인데 라벨 코드가 없으면 행을 insert 했다.
화면을 훑기만 해도 `label_code` 가 늘어 '다국어 설정' 그리드가 자라고,
레이아웃 회귀 비교의 기준선이 흔들렸다.

행 생성은 `labellang_save` 가 이미 한다 — 조회에서 만들 이유가 없다.

응답 **내용**은 여기서 보지 않는다. `get_label_lang_list` 는 PostgreSQL 의
`to_char`·`fn_code_name` 을 쓰는 raw SQL 이고 test_settings 는 SQLite 다
(AGENTS.md [7]). 이 테스트가 지키는 것은 "조회가 쓰지 않는다" 하나다.
"""
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from app.views.system.menu_language import menu_language
from domain.models.system import LabelCode


class MenuLanguageReadTest(TestCase):
    """조회는 읽기만 한다."""

    def setUp(self):
        self.user = User.objects.create_user('tester', password='x')
        self.factory = RequestFactory()

    def _context(self, **gparam):
        request = self.factory.get('/api/system/menu_language')
        request.user = self.user
        return SimpleNamespace(request=request, gparam=gparam, posparam={})

    def test_없는_라벨코드를_조회해도_행이_생기지_않는다(self):
        context = self._context(action='menu_language_list',
                                ModuleName='common', TemplateKey='menu',
                                LabelCode='없는메뉴이름', LangCode='ko-KR')

        menu_language(context)

        self.assertEqual(
            LabelCode.objects.filter(LabelCode='없는메뉴이름').count(), 0)


class MenuLanguageSaveTest(TestCase):
    """메뉴명 설정은 한국어 표시값만 고치는 수정 전용 화면이다 — 언어를 보내지 않으면 기본 언어(LANGUAGE_CODE)다."""

    def setUp(self):
        self.user = User.objects.create_user('tester', password='x')

    def _save(self, **posparam):
        request = RequestFactory().post('/api/system/menu_language')
        request.user = self.user
        data = dict({'ModuleName': 'common', 'TemplateKey': 'menu', 'LabelCode': '사용자'}, **posparam)
        return menu_language(SimpleNamespace(request=request, gparam={'action': 'labellang_save'}, posparam=data))

    def test_언어를_보내지_않으면_기본_언어로_저장하고_다시_저장하면_같은_행을_고친다(self):
        from domain.models.system import LabelCodeLanguage
        self.assertEqual(self._save(DispText='계정')['success'], True)
        row = LabelCodeLanguage.objects.get()
        self.assertEqual((row.LangCode, row.DispText), ('ko-KR', '계정'))
        self.assertEqual(self._save(id=row.id, DispText='사용자 계정')['success'], True)
        self.assertEqual(list(LabelCodeLanguage.objects.values_list('LangCode', 'DispText')), [('ko-KR', '사용자 계정')])

    def test_표시값이_비면_입력하라고_한다(self):
        from domain.models.system import LabelCodeLanguage
        self.assertEqual(self._save(DispText=' '), {'success': False, 'message': '표시값을 입력해 주세요.'})
        self.assertFalse(LabelCodeLanguage.objects.exists())
