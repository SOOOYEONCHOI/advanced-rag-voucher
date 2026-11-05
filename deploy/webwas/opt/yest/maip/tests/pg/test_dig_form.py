"""디지털 양식 — SQLite 로 볼 수 없는 PostgreSQL 전용 부분(양식코드 시퀀스·raw SQL)."""
from types import SimpleNamespace

from django.test import TestCase

from domain.services.sql import DbUtil


class DigFormCodeSequenceTest(TestCase):
    def test_양식코드_시퀀스가_있다(self):
        code = DbUtil.get_row("select 'DF' || lpad(nextval('dig_form_code_seq')::text, 4, '0') as code")['code']
        self.assertRegex(code, r'^DF\d{4}$')


class SeedDigFormCodeSequenceTest(TestCase):
    def test_새_양식코드는_기본_양식_다음_번호부터다(self):
        from django.core.management import call_command
        import io

        call_command('seed_dig_form', stdout=io.StringIO())
        self.assertEqual(DbUtil.get_row("select nextval('dig_form_code_seq') as n")['n'], 21)   # 기본 양식 마지막 DF0020 다음


class FormEditListTest(TestCase):
    def test_불러오기_목록은_섹션_양식만_고를_수_있다(self):
        from app.views.system.form_edit import form_edit
        from domain.models.dig_form import DigForm

        DigForm.objects.create(Code='DF-S1', Title='섹션', LayoutType='SECTION')
        DigForm.objects.create(Code='DF-G1', Title='칸 단위', LayoutType='GRID')

        class Context:
            gparam = {'action': 'read', 'layout_type': 'SECTION', 'keyword': 'DF-'}
            posparam = {}

        self.assertEqual([r['code'] for r in form_edit(Context())], ['DF-S1'])


class DigFormResultSearchTest(TestCase):
    """검사작성의 작성 중 목록·검사결과의 완료 목록·이어쓰기 찾기 — to_char 가 있어 PostgreSQL 에서만 돈다."""

    def setUp(self):
        from django.contrib.auth.models import User
        from domain.models.dig_form import DigForm, DigFormResult

        self.user = User.objects.create_user('writer', password='x')
        outgoing = DigForm.objects.create(Code='DF-Q1', Title='품질')
        incoming = DigForm.objects.create(Code='DF-I1', Title='수입', FormType='INCOMING')
        self.done = DigFormResult.objects.create(DigForm=outgoing, WriteDate='2026-10-16', WorkOrderNumber='WO-1', State='done')
        self.working = DigFormResult.objects.create(DigForm=outgoing, WriteDate='2026-10-16', WorkOrderNumber='WO-1', Round=2,
                                                    _creater_id=self.user.id)
        DigFormResult.objects.create(DigForm=incoming, WriteDate='2026-10-16')
        self.form = outgoing

    def call(self, **gparam):
        from app.views.dig_form.dig_form import dig_form

        class Context:
            posparam = {}
            request = SimpleNamespace(user=SimpleNamespace(id=None))
        Context.request.user.id = gparam.pop('user_id', None)
        Context.gparam = gparam
        return dig_form(Context())

    def test_작성_중_목록은_구분의_작성_중인_건만_기간_없이_준다(self):
        rows = self.call(action='result_search', form_type='OUTGOING', state='working')
        self.assertEqual([r['id'] for r in rows], [self.working.id])

    def test_결과_목록은_구분의_완료된_건만_준다(self):
        rows = self.call(action='result_search', form_type='OUTGOING', state='done',
                         date_from='2026-10-01', date_to='2026-10-31')
        self.assertEqual([r['id'] for r in rows], [self.done.id])

    def test_이어쓰기는_작성_중인_건만_찾는다(self):
        found = self.call(action='find_result', form_id=self.form.id, work_order_number='WO-1')
        self.assertEqual(found['id'], self.working.id)

    def test_목록과_이어쓰기는_머리글_입력값을_dict_로_준다(self):
        self.working.HeaderValues = '{"k1": "2026-10-19"}'
        self.working.save()
        rows = self.call(action='result_search', form_type='OUTGOING', state='working')
        self.assertEqual(rows[0]['header_values'], {'k1': '2026-10-19'})
        found = self.call(action='find_result', form_id=self.form.id, work_order_number='WO-1')
        self.assertEqual(found['header_values'], {'k1': '2026-10-19'})
        rows = self.call(action='result_search', form_type='OUTGOING', state='done',
                         date_from='2026-10-01', date_to='2026-10-31')
        self.assertEqual(rows[0]['header_values'], {})

    def test_작성자면_is_mine_이다(self):
        rows = self.call(action='result_search', form_type='OUTGOING', state='working', user_id=self.user.id)
        self.assertEqual([r['is_mine'] for r in rows], [True])
        found = self.call(action='find_result', form_id=self.form.id, work_order_number='WO-1', user_id=self.user.id + 1)
        self.assertFalse(found['is_mine'])


class FormEditFormTypeTest(TestCase):
    """검사양식 목록의 구분 필터와 새 양식의 구분 — 양식코드 시퀀스·to_char 가 있어 PostgreSQL 에서만 돈다."""

    def test_목록은_구분으로_거른다(self):
        from app.views.system.form_edit import form_edit
        from domain.models.dig_form import DigForm

        DigForm.objects.create(Code='DF-Q1', Title='품질')
        DigForm.objects.create(Code='DF-I1', Title='수입', FormType='INCOMING')

        class Context:
            gparam = {'action': 'read', 'form_type': 'INCOMING', 'keyword': 'DF-'}
            posparam = {}

        self.assertEqual([r['code'] for r in form_edit(Context())], ['DF-I1'])

    def test_새_양식은_고른_구분으로_저장한다(self):
        from django.contrib.auth.models import User
        from app.views.system.form_edit import save_form
        from domain.models.dig_form import DigForm

        user = User.objects.create_superuser('pg-editor', password='x')
        body = save_form({'title': '수입 양식', 'form_type': 'INCOMING', 'top_cells': [{'bind': 'result.WriteDate'}],
                          'sections': []}, user)
        self.assertTrue(body['success'])
        self.assertEqual(DigForm.objects.get(Code=body['code']).FormType, 'INCOMING')

    def test_머리글_섹션은_상세에서_칸_목록으로_읽는다(self):
        import json
        from django.contrib.auth.models import User
        from app.views.dig_form.dig_form import dig_form
        from app.views.system.form_edit import save_form, get_detail
        from domain.models.dig_form import DigForm

        user = User.objects.create_superuser('pg-header', password='x')
        cells = [{'row': 1, 'col': 1, 'content': '확인자'}]
        body = save_form({'title': '머리글 섹션 양식', 'form_type': 'OUTGOING', 'top_cells': [],
                          'sections': [{'type': 'HEADER', 'title': '확인', 'width': 12, 'cells': cells}]}, user)
        form_id = DigForm.objects.get(Code=body['code']).id
        section = get_detail(form_id)['sections'][0]
        self.assertEqual((section['type'], section['cells'], 'content' in section), ('HEADER', cells, False))

        class Context:
            gparam = {'action': 'detail', 'form_id': form_id}
            posparam = {}
            request = SimpleNamespace(user=user)

        section = dig_form(Context())['sections'][0]
        self.assertEqual((section['section_type'], section['cells']), ('HEADER', cells))
