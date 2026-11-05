"""디지털 양식(CheckList) — 모델·API·참고사진·seed·가져오기.

PostgreSQL 전용(양식코드 시퀀스·raw SQL)은 tests/pg/test_dig_form.py 에 있다.
"""
import datetime
import io
import json
import shutil
import tempfile
from unittest import mock
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from PIL import Image

from domain.gui import DIG_FORM_EDIT_MENU, DIG_FORM_MENU_CODES, GUIConfiguration
from domain.models.data import ImageAsset, InspectionCategory, InspectionItem
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from domain.management.commands.export_dig_form import code_list, export_forms, latest_forms
from domain.models.system import AttachFile, MenuFolder, MenuItem, SystemCode, UserCode
from domain.models.user import UserGroup, UserGroupMenu
from domain.services import judge_code
from domain.services.dig_form_image import image_path, image_url, save_upload, sync_editor_images

from domain.management.commands.seed_dig_form import FIXTURE
from domain.models.dig_form import (DigForm, DigFormItem, DigFormItemResult, DigFormResult,
                                    DigFormSection, DigFormWorkClass)


def make_form(code='DF-T1', input_types=('N',), version=1):
    """양식 1개 + 점검항목 섹션 1개 + 입력칸(ResultType 별 1칸씩)."""
    form = DigForm.objects.create(Code=code, Version=version, Title='시험 양식', LayoutType='SECTION')
    section = DigFormSection.objects.create(DigForm=form, SectionType='INSPECTION', Title='점검')
    items = [DigFormItem.objects.create(DigFormSection=section, RowType='D', RowIndex=2, ColumnIndex=i + 1,
                                        ResultType=t, InputYN='Y', LowerLimit=1, UpperLimit=9)
             for i, t in enumerate(input_types)]
    return form, section, items


class DigFormModelTest(TestCase):
    def test_한_섹션에서_칸_위치는_겹치지_않는다(self):
        _form, section, _items = make_form()
        with self.assertRaises(IntegrityError), transaction.atomic():
            DigFormItem.objects.create(DigFormSection=section, RowType='D', RowIndex=2, ColumnIndex=1)

    def test_입력칸은_판정타입이_있어야_한다(self):
        _form, section, _items = make_form()
        with self.assertRaises(IntegrityError), transaction.atomic():
            DigFormItem.objects.create(DigFormSection=section, RowType='D', RowIndex=3, ColumnIndex=1, InputYN='Y')

    def test_작성건마다_칸_결과는_하나다(self):
        form, _section, (item,) = make_form()
        result = DigFormResult.objects.create(DigForm=form, WriteDate='2026-10-14')
        DigFormItemResult.objects.create(DigFormResult=result, DigFormItem=item, NumberResult=3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DigFormItemResult.objects.create(DigFormResult=result, DigFormItem=item, NumberResult=4)

    def test_양식_구분의_기본값은_품질이다(self):
        form = DigForm.objects.create(Code='DF-T9', Title='구분 없는 양식')
        self.assertEqual(form.FormType, 'OUTGOING')


def png_bytes(size=(8, 8)):
    buffer = io.BytesIO()
    Image.new('RGB', size, 'white').save(buffer, format='PNG')
    return buffer.getvalue()


class DigFormImageTest(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user('editor', password='x')

    def upload(self, data=None, name='a.png'):
        return save_upload(SimpleUploadedFile(name, data or png_bytes(), content_type='image/png'), self.user)

    def test_업로드는_MEDIA_ROOT_에_저장하고_연결되지_않은_첨부로_남긴다(self):
        res = self.upload()
        attach = AttachFile.objects.get(pk=res['fileId'])
        self.assertEqual((attach.TableName, attach.AttachName, attach.DataPk), ('dig_form_section', 'editor', 0))
        self.assertEqual(res['url'], image_url(attach.id))
        self.assertTrue((Path(self.media) / 'dig_form_section' / attach.PhysicFileName).is_file())

    def test_이미지가_아니면_거절한다(self):
        with self.assertRaisesMessage(ValueError, '읽을 수 없는 이미지 파일입니다.'):
            self.upload(b'not an image', name='a.png')

    def test_본문_이미지를_섹션에_연결하고_빠진_이미지는_연결을_끊는다(self):
        first, second = self.upload()['fileId'], self.upload()['fileId']
        html = f'<p><img src="{image_url(first)}"><img src="{image_url(second)}"></p>'
        sync_editor_images(html, 7, self.user)
        self.assertEqual(set(AttachFile.objects.filter(DataPk=7).values_list('id', flat=True)), {first, second})
        sync_editor_images(f'<img src="{image_url(first)}">', 7, self.user)
        self.assertEqual(list(AttachFile.objects.filter(DataPk=7).values_list('id', flat=True)), [first])

    def test_다른_섹션의_이미지는_복사해_새_주소로_바꾼다(self):
        file_id = self.upload()['fileId']
        sync_editor_images(f'<img src="{image_url(file_id)}">', 7, self.user)
        html = sync_editor_images(f'<img src="{image_url(file_id)}">', 8, self.user)
        copied = AttachFile.objects.get(DataPk=8)
        self.assertNotEqual(copied.id, file_id)
        self.assertEqual(html, f'<img src="{image_url(copied.id)}">')

    def test_외부_주소나_base64_이미지는_거절한다(self):
        with self.assertRaises(ValueError):
            sync_editor_images('<img src="data:image/png;base64,AAAA">', 7, self.user)
        with self.assertRaises(ValueError):
            sync_editor_images('<img src="https://example.com/a.png">', 7, self.user)

    def test_이미지는_디지털_양식_메뉴_권한이_있어야_받는다(self):
        file_id = self.upload()['fileId']
        url = image_url(file_id)
        self.assertEqual(self.client.get(url).status_code, 404)          # 익명
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 404)          # 메뉴 권한 없음
        group = UserGroup.objects.create(Code='qc', Name='품질')
        self.user.userprofile.UserGroup = group
        self.user.userprofile.save()
        UserGroupMenu.objects.create(UserGroup=group, MenuCode='wm_dig_form_outgoing_result', AuthCode='R')
        response = self.client.get(url)
        self.assertEqual((response.status_code, response['Content-Type']), (200, 'image/png'))


class DigFormApiTest(TestCase):
    def setUp(self):
        self.form, self.section, (self.number_item,) = make_form()
        self.group = UserGroup.objects.create(Code='qc', Name='품질')
        self.user = User.objects.create_user('writer', password='x')
        self.user.userprofile.UserGroup = self.group
        self.user.userprofile.save()
        self.client.force_login(self.user)

    def grant(self, code, auth):
        UserGroupMenu.objects.create(UserGroup=self.group, MenuCode=code, AuthCode=auth)

    def save(self, method='post', **extra):
        data = {'form_id': self.form.id,
                'Q': json.dumps([{'item_id': self.number_item.id, 'value': '5'}]), **extra}
        if method == 'get':   # GET 은 data 가 쿼리를 덮어쓴다 — action 도 data 로 보낸다
            return self.client.get('/api/dig_form/dig_form', {**data, 'action': 'save'})
        return self.client.post('/api/dig_form/dig_form?action=save', data)

    def test_저장하면_저장한_사람이_작성자고_이어쓰면_이어쓴_사람이_작성자다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        self.user.userprofile.Name = '작성자갑'
        self.user.userprofile.save()
        body = self.save().json()
        self.assertEqual(body['writer_name'], '작성자갑')
        other = User.objects.create_user('second', password='x')
        other.userprofile.UserGroup = self.group
        other.userprofile.Name = '작성자을'
        other.userprofile.save()
        self.client.force_login(other)
        body = self.save(result_id=body['result_id'], Q=json.dumps([{'item_id': self.number_item.id, 'value': '6'}])).json()
        self.assertEqual(body['writer_name'], '작성자을')

    def test_행_작업자는_그_행에서_가장_나중에_저장한_사람이다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        judge_code.ensure_defaults()
        second = DigFormItem.objects.create(DigFormSection=self.section, RowType='D', RowIndex=2, ColumnIndex=2,
                                            InputYN='Y', ResultType='T')
        self.user.userprofile.Name = '첫째'
        self.user.userprofile.save()
        result_id = self.save(Q=json.dumps([{'item_id': self.number_item.id, 'value': '5'},
                                            {'item_id': second.id, 'value': 'a'}])).json()['result_id']
        other = User.objects.create_user('second', password='x')
        other.userprofile.UserGroup = self.group
        other.userprofile.Name = '둘째'
        other.userprofile.save()
        self.client.force_login(other)
        self.save(result_id=result_id, Q=json.dumps([{'item_id': second.id, 'value': 'b'}]))   # 같은 행 두 번째 칸만 고친다
        self.grant('wm_dig_form_outgoing_result', 'R')
        rows = self.client.get('/api/dig_form/dig_form', {'action': 'result_values', 'result_id': result_id}).json()
        # 화면은 행마다 마지막 이름을 쓴다 — 그 행에서 가장 나중에 저장한 사람이 마지막에 온다
        self.assertEqual([r['worker_name'] for r in rows if r['row_index'] == 2][-1], '둘째')
        self.assertEqual({r['item_id']: r['worker_name'] for r in rows}, {self.number_item.id: '첫째', second.id: '둘째'})

    def test_작성_권한이_있으면_결과를_저장한다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        body = self.save().json()
        self.assertTrue(body['success'])
        self.assertEqual(DigFormItemResult.objects.get().NumberResult, 5)

    def test_저장은_GET_으로_부르면_막는다(self):
        self.grant('wm_dig_form_outgoing_result', 'R')
        self.assertEqual(self.save(method='get').status_code, 403)
        self.assertFalse(DigFormResult.objects.exists())

    def test_조회_권한만으로는_저장할_수_없다(self):
        self.grant('wm_dig_form_outgoing_result', 'R')
        self.assertEqual(self.save().status_code, 403)

    def test_다른_양식의_칸은_저장하지_않는다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        _other, _section, (foreign,) = make_form(code='DF-T2')
        body = self.save(Q=json.dumps([{'item_id': foreign.id, 'value': '5'}])).json()
        self.assertEqual(body, {'success': False, 'message': f'양식에 없는 입력칸입니다: {foreign.id}'})
        self.assertFalse(DigFormResult.objects.exists())

    def test_예상하지_못한_오류의_원문은_응답에_싣지_않는다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        response = self.save(Q=json.dumps([{'value': '5'}]))      # item_id 없음 → int(None) TypeError
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('NoneType', response.content.decode())

    def test_양식_목록은_어느_디지털_양식_메뉴로도_읽는다(self):
        self.grant('wm_dig_form_incoming_result', 'R')
        rows = self.client.get('/api/dig_form/dig_form', {'action': 'form_list'}).json()
        self.assertEqual([r['code'] for r in rows], ['DF-T1'])

    def post(self, action, **data):
        return self.client.post('/api/dig_form/dig_form?action=' + action, data)

    def test_양식_목록은_구분으로_거르고_사용_중인_최신_버전만도_고른다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        DigForm.objects.create(Code='DF-T1', Version=2, Title='시험 양식 2판')
        DigForm.objects.create(Code='DF-N1', Title='사용 안 함', UseYN='N')
        DigForm.objects.create(Code='DF-I1', Title='수입 양식', FormType='INCOMING')
        rows = self.client.get('/api/dig_form/dig_form', {'action': 'form_list', 'form_type': 'OUTGOING', 'latest_only': 'Y'}).json()
        self.assertEqual([(r['code'], r['version']) for r in rows], [('DF-T1', 2)])
        # 검사결과의 양식 고르기는 완료된 검사가 달린 옛 버전·미사용 양식도 고른다
        rows = self.client.get('/api/dig_form/dig_form', {'action': 'form_list', 'form_type': 'OUTGOING'}).json()
        self.assertEqual([(r['code'], r['version']) for r in rows], [('DF-N1', 1), ('DF-T1', 2), ('DF-T1', 1)])

    def test_완료하면_상태가_done_이다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        result_id = self.save().json()['result_id']
        self.assertTrue(self.post('complete', result_id=result_id).json()['success'])
        self.assertEqual(DigFormResult.objects.get(id=result_id).State, 'done')

    def test_완료된_검사는_저장하지_않는다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        result_id = self.save().json()['result_id']
        self.post('complete', result_id=result_id)
        body = self.save(result_id=result_id, Q=json.dumps([{'item_id': self.number_item.id, 'value': '7'}])).json()
        self.assertEqual(body, {'success': False, 'message': '완료된 검사는 고칠 수 없습니다.'})
        self.assertEqual(DigFormItemResult.objects.get().NumberResult, 5)

    def test_완료된_검사는_다시_완료하지_않는다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        result_id = self.save().json()['result_id']
        self.post('complete', result_id=result_id)
        self.assertEqual(self.post('complete', result_id=result_id).json(),
                         {'success': False, 'message': '이미 완료된 검사입니다.'})

    def test_작성_중인_같은_양식_WO_가_있으면_새로_쓰지_않는다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        self.assertTrue(self.save(work_order_number='WO-1').json()['success'])
        self.assertFalse(self.save(work_order_number='WO-1').json()['success'])
        self.assertEqual(DigFormResult.objects.count(), 1)

    def test_옛_버전으로_작성_중이면_같은_코드의_새_버전으로도_같은_WO_를_새로_쓰지_않는다(self):
        # 검사 작업은 양식 코드 단위다(설계 2026-10-21 §6)
        self.grant('wm_dig_form_outgoing_write', 'RW')
        self.assertTrue(self.save(work_order_number='WO-1').json()['success'])
        newer, _section, (item,) = make_form(code=self.form.Code, version=2)
        body = self.client.post('/api/dig_form/dig_form?action=save', {
            'form_id': newer.id, 'work_order_number': 'WO-1', 'Q': json.dumps([{'item_id': item.id, 'value': '5'}])}).json()
        self.assertFalse(body['success'])

    def test_수입_검사_작업_목록과_대기_건수(self):
        from domain.models.basic import Product, ProductForm, Receipt
        self.grant('wm_dig_form_incoming_write', 'R')
        DigForm.objects.filter(id=self.form.id).update(FormType='INCOMING')
        product = Product.objects.create(Code='P1.A', PartNo='P1', Revision='A', Name='품목')
        Receipt.objects.create(ReceiptNo='R-1', ReqNo='R', ReqSeq=1, Product=product, ItemCode='P1.A', ItemName='품목', Qty=1)
        ProductForm.objects.create(PartNo='P1', FormCode=self.form.Code)
        rows = self.client.get('/api/dig_form/dig_form', {'action': 'job_list', 'form_type': 'INCOMING'}).json()
        self.assertEqual([(r['kind'], r['receipt_no'], r['form_id']) for r in rows], [('WAITING', 'R-1', self.form.id)])
        self.assertEqual(self.client.get('/api/dig_form/dig_form', {'action': 'job_count'}).json(), {'count': 1})
        self.assertEqual(self.client.get('/api/dig_form/dig_form', {'action': 'job_list', 'form_type': 'OUTGOING'}).json(),
                         {'success': False, 'message': '검사 작업 목록은 수입검사만 있습니다.'})

    def test_완료된_검사와_같은_양식_WO_로_새_검사를_쓰면_차수가_오른다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        first = self.save(work_order_number='WO-1').json()['result_id']
        self.post('complete', result_id=first)
        second = self.save(work_order_number='WO-1').json()['result_id']
        self.assertEqual([(r.id, r.Round, r.State) for r in DigFormResult.objects.order_by('id')],
                         [(first, 1, 'done'), (second, 2, 'working')])

    def test_저장_응답에_차수가_있다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        first = self.save(work_order_number='WO-1').json()
        self.assertEqual(first['round'], 1)
        self.post('complete', result_id=first['result_id'])
        self.assertEqual(self.save(work_order_number='WO-1').json()['round'], 2)

    def with_header_inputs(self):
        """머리글에 입력 항목 둘(라벨 연결, result.extra.<키>)과 입력이 아닌 칸 하나."""
        self.form.FixedTopContent = json.dumps([
            {'row': 1, 'col': 1, 'content': '중간검사일', 'input_key': 'k1'},
            {'row': 1, 'col': 2, 'bind': 'result.extra.k1', 'input': True, 'name': '중간검사일'},
            {'row': 1, 'col': 3, 'content': '비고', 'input_key': 'k2'},
            {'row': 1, 'col': 4, 'bind': 'result.extra.k2', 'input': True, 'name': '비고'},
            {'row': 2, 'col': 1, 'bind': 'result.extra.k3'},
        ])
        self.form.save()

    def test_머리글_입력_항목을_저장하고_응답에_돌려준다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        self.with_header_inputs()
        body = self.save(header_values=json.dumps({'k1': '2026-10-19', 'k2': ' 메모 '})).json()
        self.assertEqual((body['success'], body['header_values']), (True, {'k1': '2026-10-19', 'k2': '메모'}))
        self.assertEqual(json.loads(DigFormResult.objects.get().HeaderValues), {'k1': '2026-10-19', 'k2': '메모'})
        self.assertEqual(DigFormItemResult.objects.get().NumberResult, 5)

    def test_이어쓰기는_보낸_머리글_키만_바꾸고_빈_값은_지운다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        self.with_header_inputs()
        result_id = self.save(header_values=json.dumps({'k1': '2026-10-19', 'k2': '메모'})).json()['result_id']
        body = self.save(result_id=result_id, Q='[]', header_values=json.dumps({'k2': ''})).json()
        self.assertEqual((body['changed'], body['header_values']), (1, {'k1': '2026-10-19'}))
        body = self.save(result_id=result_id, Q='[]', header_values=json.dumps({'k1': ''})).json()
        self.assertEqual(body['header_values'], {})
        self.assertIsNone(DigFormResult.objects.get().HeaderValues)

    def test_머리글_값을_보내지_않으면_그대로_둔다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        self.with_header_inputs()
        result_id = self.save(header_values=json.dumps({'k1': '2026-10-19'})).json()['result_id']
        body = self.save(result_id=result_id, Q=json.dumps([{'item_id': self.number_item.id, 'value': '7'}])).json()
        self.assertEqual(body['header_values'], {'k1': '2026-10-19'})
        self.assertEqual(DigFormItemResult.objects.get().NumberResult, 7)

    def test_양식에_없거나_입력이_아닌_머리글_키는_저장하지_않는다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        self.with_header_inputs()
        for key in ('nope', 'k3'):
            self.assertEqual(self.save(header_values=json.dumps({key: 'x'})).json(),
                             {'success': False, 'message': f'양식에 없는 머리글 입력 항목입니다: {key}'})
        self.assertFalse(DigFormResult.objects.exists())   # 칸 값도 함께 되돌린다
        self.assertFalse(DigFormItemResult.objects.exists())

    def test_머리글_목록_항목은_글자와_목록에서_고른_코드를_저장한다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        self.form.FixedTopContent = json.dumps([
            {'row': 1, 'col': 1, 'bind': 'result.field.product', 'input': True},
            {'row': 1, 'col': 2, 'bind': 'result.field.part_no', 'input': True},
        ])
        self.form.save()
        posted = {'field.product': '브래킷', 'field.product@code': 'P-001', 'field.part_no': '목록에 없는 품번'}
        body = self.save(header_values=json.dumps(posted)).json()
        self.assertEqual((body['success'], body['header_values']), (True, posted))
        self.assertEqual(self.save(header_values=json.dumps({'field.receipt_no': 'x'})).json()['message'],
                         '양식에 없는 머리글 입력 항목입니다: field.receipt_no')

    def test_머리글_목록_검색은_디지털_양식_조회_권한으로_읽는다(self):
        from domain.models.basic import Product
        Product.objects.create(Code='P-001', PartNo='BRK-10', Revision='A', Name='브래킷')
        self.assertEqual(self.client.get('/api/dig_form/dig_form', {'action': 'header_lookup', 'bind': 'result.field.product', 'q': '브래'}).status_code, 403)
        self.grant('wm_dig_form_outgoing_result', 'R')
        rows = self.client.get('/api/dig_form/dig_form', {'action': 'header_lookup', 'bind': 'result.field.part_no', 'q': '브래'}).json()
        self.assertEqual([(r['text'], r['code']) for r in rows], [('BRK-10', 'P-001')])
        body = self.client.get('/api/dig_form/dig_form', {'action': 'header_lookup', 'bind': 'result.extra.k1', 'q': ''}).json()
        self.assertEqual(body, {'success': False, 'message': '목록에서 고르는 입력값이 아닙니다.'})

    def test_머리글_입력값_형식과_길이를_확인한다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        self.with_header_inputs()
        bad = {'success': False, 'message': '머리글 입력값 형식이 올바르지 않습니다.'}
        self.assertEqual(self.save(header_values='{').json(), bad)
        self.assertEqual(self.save(header_values='["k1"]').json(), bad)
        self.assertEqual(self.save(header_values=json.dumps({'k2': 'x' * 201})).json(),
                         {'success': False, 'message': '머리글 입력값은 200자까지 넣을 수 있습니다.'})
        self.assertFalse(DigFormResult.objects.exists())

    def test_작성일은_입력받지_않고_새_작성건을_만든_날이다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        body = self.save(write_date='2000-01-01').json()
        today = datetime.date.today()
        self.assertEqual((body['success'], body['write_date']), (True, str(today)))
        self.assertEqual(DigFormResult.objects.get().WriteDate, today)

    def test_이어쓰기는_작성일을_바꾸지_않는다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        result_id = self.save().json()['result_id']
        DigFormResult.objects.filter(id=result_id).update(WriteDate='2026-10-01')
        body = self.save(result_id=result_id, Q=json.dumps([{'item_id': self.number_item.id, 'value': '7'}])).json()
        self.assertEqual(body['write_date'], '2026-10-01')
        self.assertEqual(str(DigFormResult.objects.get().WriteDate), '2026-10-01')

    def test_머리글_섹션의_입력_항목도_저장한다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        self.with_header_inputs()
        DigFormSection.objects.create(DigForm=self.form, SectionType='HEADER', SortOrder=9, Content=json.dumps([
            {'row': 1, 'col': 1, 'content': '확인자', 'input_key': 'k9'},
            {'row': 1, 'col': 2, 'bind': 'result.extra.k9', 'input': True, 'name': '확인자'},
        ]))
        body = self.save(header_values=json.dumps({'k1': '2026-10-19', 'k9': '홍길동'})).json()
        self.assertEqual((body['success'], body['header_values']), (True, {'k1': '2026-10-19', 'k9': '홍길동'}))

    def test_작성자는_작성_중인_검사를_지운다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        result_id = self.save().json()['result_id']
        self.assertTrue(self.post('delete', result_id=result_id).json()['success'])
        self.assertFalse(DigFormResult.objects.exists())
        self.assertFalse(DigFormItemResult.objects.exists())

    def test_작성자가_아니면_지우지_않는다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        result_id = self.save().json()['result_id']
        other = User.objects.create_user('other', password='x')
        other.userprofile.UserGroup = self.group
        other.userprofile.save()
        self.client.force_login(other)
        self.assertEqual(self.post('delete', result_id=result_id).json(),
                         {'success': False, 'message': '작성한 사람만 지울 수 있습니다.'})
        self.assertTrue(DigFormResult.objects.filter(id=result_id).exists())

    def test_완료된_검사는_지우지_않는다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        result_id = self.save().json()['result_id']
        self.post('complete', result_id=result_id)
        self.assertEqual(self.post('delete', result_id=result_id).json(),
                         {'success': False, 'message': '작성 중인 검사만 지울 수 있습니다.'})

    def test_품질_양식은_수입검사작성_쓰기_권한으로_저장하지_않는다(self):
        self.grant('wm_dig_form_incoming_write', 'RW')
        self.assertEqual(self.save().status_code, 403)
        self.assertFalse(DigFormResult.objects.exists())

    def test_품질_검사는_수입검사작성_쓰기_권한으로_완료하거나_지우지_않는다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        result_id = self.save().json()['result_id']
        UserGroupMenu.objects.filter(MenuCode='wm_dig_form_outgoing_write').update(MenuCode='wm_dig_form_incoming_write')
        self.assertEqual(self.post('complete', result_id=result_id).status_code, 403)
        self.assertEqual(self.post('delete', result_id=result_id).status_code, 403)
        self.assertEqual(DigFormResult.objects.get().State, 'working')

    def test_칸_설정은_양식_편집_쓰기_권한이_있어야_한다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        _form, section, _items = make_form(code='DF-T3', input_types=())
        cell = DigFormItem.objects.create(DigFormSection=section, RowType='D', RowIndex=3, ColumnIndex=1)
        data = {'item_id': cell.id, 'input_yn': 'Y', 'result_type': 'N', 'lower_limit': '1', 'upper_limit': '9'}
        self.client.post('/api/dig_form/dig_form?action=save_item', data)   # 작성 API 에는 이 action 이 없다
        cell.refresh_from_db()
        self.assertEqual(cell.InputYN, 'N')
        self.assertEqual(self.client.post('/api/system/form_edit?action=save_item', data).status_code, 403)
        self.grant('wm_dig_form_incoming_form', 'RW')
        body = self.client.post('/api/system/form_edit?action=save_item', data).json()
        self.assertEqual((body['success'], body['revised'], body['item_id']), (True, False, cell.id))
        cell.refresh_from_db()
        self.assertEqual((cell.InputYN, cell.ResultType), ('Y', 'N'))

    def test_칸_설정의_판정은_항목결과_코드의_그룹을_골라_저장한다(self):
        self.grant('wm_dig_form_incoming_form', 'RW')
        judge_code.ensure_defaults()
        cell = DigFormItem.objects.create(DigFormSection=self.section, RowType='D', RowIndex=3, ColumnIndex=1)
        save = lambda **data: self.client.post('/api/system/form_edit?action=save_item',
                                               {'item_id': cell.id, 'input_yn': 'Y', **data}).json()
        self.assertTrue(save(result_type='S', code_group='dig_form_pass_na')['success'])
        cell.refresh_from_db()
        self.assertEqual((cell.ResultType, cell.CodeGroup), ('S', 'dig_form_pass_na'))   # OK/NG 로 덮어쓰지 않는다
        self.assertEqual(save(result_type='S', code_group='dig_form_nothing'),
                         {'success': False, 'message': '판정 선택지를 골라 주세요.'})
        self.assertEqual(save(result_type='S'), {'success': False, 'message': '판정 선택지를 골라 주세요.'})
        self.assertTrue(save(result_type='T', code_group='dig_form_okng')['success'])     # 판정이 아니면 그룹을 두지 않는다
        cell.refresh_from_db()
        self.assertEqual((cell.ResultType, cell.CodeGroup), ('T', None))

    def test_작성_결과가_있는_칸_단위_양식은_새_버전에서_입력칸을_바꾼다(self):
        self.grant('wm_dig_form_incoming_form', 'RW')
        DigForm.objects.filter(id=self.form.id).update(LayoutType='GRID', FixedTopContent='[]')
        cell = DigFormItem.objects.create(DigFormSection=self.section, RowType='D', RowIndex=3, ColumnIndex=1, Content=None)
        DigFormResult.objects.create(DigForm=self.form, WriteDate='2026-10-19')
        data = {'item_id': cell.id, 'input_yn': 'Y', 'result_type': 'N', 'lower_limit': '1', 'upper_limit': '9'}
        body = self.client.post('/api/system/form_edit?action=save_item', data).json()
        self.assertEqual((body['success'], body['revised'], body['version']), (True, True, 2))
        new = DigForm.objects.get(id=body['id'])
        self.assertEqual((new.Code, new.LayoutType, new.FixedTopContent, new.Title), (self.form.Code, 'GRID', '[]', self.form.Title))
        old_cells = DigFormItem.objects.filter(DigFormSection__DigForm=self.form)
        new_cells = DigFormItem.objects.filter(DigFormSection__DigForm=new)
        self.assertEqual(new_cells.count(), old_cells.count())
        self.assertEqual(DigFormSection.objects.filter(DigForm=new).count(), 1)
        changed = new_cells.get(id=body['item_id'])
        self.assertEqual((changed.RowIndex, changed.ColumnIndex, changed.InputYN, changed.ResultType), (3, 1, 'Y', 'N'))
        cell.refresh_from_db()
        self.assertEqual(cell.InputYN, 'N')     # 옛 버전과 그 결과는 그대로
        self.assertEqual(DigFormResult.objects.filter(DigForm=new).count(), 0)
        # 새 버전은 결과가 없으므로 다음 칸은 그 버전을 고친다
        other = new_cells.exclude(id=changed.id).first()
        body = self.client.post('/api/system/form_edit?action=save_item', {'item_id': other.id, 'input_yn': 'N'}).json()
        self.assertEqual((body['success'], body['revised'], body['id']), (True, False, new.id))

    def test_새_버전_입력칸_값이_틀리면_새_버전을_만들지_않는다(self):
        self.grant('wm_dig_form_incoming_form', 'RW')
        DigForm.objects.filter(id=self.form.id).update(LayoutType='GRID')
        cell = DigFormItem.objects.create(DigFormSection=self.section, RowType='D', RowIndex=3, ColumnIndex=1)
        DigFormResult.objects.create(DigForm=self.form, WriteDate='2026-10-19')
        data = {'item_id': cell.id, 'input_yn': 'Y', 'result_type': 'N', 'lower_limit': '9', 'upper_limit': '1'}
        self.assertEqual(self.client.post('/api/system/form_edit?action=save_item', data).json(),
                         {'success': False, 'message': '하한값이 상한값보다 큽니다.'})
        self.assertEqual(DigForm.objects.filter(Code=self.form.Code).count(), 1)

    def test_작성_결과가_있는_섹션_양식은_입력칸을_바꾸지_않는다(self):
        self.grant('wm_dig_form_incoming_form', 'RW')
        cell = DigFormItem.objects.create(DigFormSection=self.section, RowType='D', RowIndex=3, ColumnIndex=1)
        DigFormResult.objects.create(DigForm=self.form, WriteDate='2026-10-19')
        data = {'item_id': cell.id, 'input_yn': 'Y', 'result_type': 'N'}
        self.assertEqual(self.client.post('/api/system/form_edit?action=save_item', data).json(),
                         {'success': False, 'message': '작성된 결과가 있는 양식은 입력칸을 바꿀 수 없습니다.'})
        cell.refresh_from_db()
        self.assertEqual(cell.InputYN, 'N')

    def test_참고사진_업로드는_양식_편집_쓰기_권한이_있어야_한다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')

        def upload():
            return self.client.post('/api/system/form_edit?action=upload_image',
                                    {'uploadfile': SimpleUploadedFile('a.png', png_bytes(), 'image/png')})

        self.assertEqual(upload().status_code, 403)
        self.grant('wm_dig_form_incoming_form', 'RW')
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        with override_settings(MEDIA_ROOT=media):
            body = upload().json()
        self.assertTrue(body['success'])


class DigFormCellImageTest(TestCase):
    """점검항목 섹션의 이미지 열(ResultType='I') — 작성 시 칸마다 사진 1장."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.form, _section, (self.item,) = make_form(input_types=('I',))
        self.group = UserGroup.objects.create(Code='qc', Name='품질')
        UserGroupMenu.objects.create(UserGroup=self.group, MenuCode='wm_dig_form_outgoing_write', AuthCode='RW')
        self.user = self.member('writer')
        self.client.force_login(self.user)

    def member(self, name):
        user = User.objects.create_user(name, password='x')
        user.userprofile.UserGroup = self.group
        user.userprofile.save()
        return user

    def upload(self):
        return self.client.post('/api/dig_form/dig_form?action=upload_image',
                                {'uploadfile': SimpleUploadedFile('a.png', png_bytes(), 'image/png')}).json()

    def save(self, value, result_id=''):
        return self.client.post('/api/dig_form/dig_form?action=save', {
            'form_id': self.form.id, 'result_id': result_id,
            'Q': json.dumps([{'item_id': self.item.id, 'value': value}])}).json()

    def test_작성_화면_업로드는_결과_폴더에_연결되지_않은_첨부로_남긴다(self):
        body = self.upload()
        attach = AttachFile.objects.get(pk=body['fileId'])
        self.assertEqual((attach.TableName, attach.AttachName, attach.DataPk), ('dig_form_item_result', 'cell', 0))
        self.assertTrue((Path(self.media) / 'dig_form_result' / attach.PhysicFileName).is_file())
        response = self.client.get(body['url'])
        self.assertEqual((response.status_code, response['Content-Type']), (200, 'image/png'))

    def test_저장하면_칸_결과에_연결하고_값은_첨부_id_다(self):
        file_id = self.upload()['fileId']
        self.assertTrue(self.save(str(file_id))['success'])
        result = DigFormItemResult.objects.get()
        self.assertEqual(result.TextResult, str(file_id))
        self.assertEqual(AttachFile.objects.get(pk=file_id).DataPk, result.id)

    def test_검사를_지우면_이미지_칸_첨부_연결도_지운다(self):
        file_id = self.upload()['fileId']
        result_id = self.save(str(file_id))['result_id']
        body = self.client.post('/api/dig_form/dig_form?action=delete', {'result_id': result_id}).json()
        self.assertTrue(body['success'])
        self.assertFalse(AttachFile.objects.filter(pk=file_id).exists())

    def test_사진을_바꾸거나_빼면_이전_연결을_지운다(self):
        first = self.upload()['fileId']
        result_id = self.save(str(first))['result_id']
        second = self.upload()['fileId']
        self.assertTrue(self.save(str(second), result_id)['success'])
        self.assertFalse(AttachFile.objects.filter(pk=first).exists())
        self.assertTrue(self.save('', result_id)['success'])
        self.assertIsNone(DigFormItemResult.objects.get().TextResult)
        self.assertFalse(AttachFile.objects.filter(TableName='dig_form_item_result').exclude(DataPk=0).exists())

    def test_다른_사용자가_올린_사진이나_참고사진_id_는_받지_않는다(self):
        others = self.upload()['fileId']
        editor = save_upload(SimpleUploadedFile('b.png', png_bytes(), content_type='image/png'), self.user)['fileId']
        self.client.force_login(self.member('other'))
        message = '이미지 정보를 찾을 수 없습니다. 이미지를 다시 올려 주세요.'
        self.assertEqual(self.save(str(others)), {'success': False, 'message': message})
        self.assertEqual(self.save(str(editor)), {'success': False, 'message': message})
        self.assertFalse(DigFormResult.objects.exists())

    def test_작성_화면_업로드는_작성_쓰기_권한이_있어야_한다(self):
        self.client.force_login(User.objects.create_user('nobody', password='x'))
        response = self.client.post('/api/dig_form/dig_form?action=upload_image',
                                    {'uploadfile': SimpleUploadedFile('a.png', png_bytes(), 'image/png')})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AttachFile.objects.exists())


class FormEditImageColumnTest(TestCase):
    def test_이미지_열은_행마다_I_입력칸이고_다시_읽으면_이미지_열이다(self):
        from app.views.system.form_edit import build_inspection, parse_inspection
        section = DigFormSection(SectionType='INSPECTION', WorkerColumnYN='N')
        columns = [{'title': '항목', 'kind': 'TEXT', 'width': 100}, {'title': '사진', 'kind': 'IMAGE', 'width': 80}]
        items, header_rows = build_inspection(section, columns, [['A', None], ['B', None]])
        cells = [i for i in items if i.InputYN == 'Y']
        self.assertEqual([(i.RowIndex, i.ColumnIndex, i.ResultType) for i in cells], [(2, 2, 'I'), (3, 2, 'I')])
        rows = {}
        for i in items:
            rows.setdefault(i.RowIndex, {})[i.ColumnIndex] = i
        parsed, values = parse_inspection(rows, header_rows, False)
        self.assertEqual([c['kind'] for c in parsed], ['TEXT', 'IMAGE'])
        self.assertEqual(values, [['A', None], ['B', None]])

    def test_이미지_열_행은_비전검사항목을_연결하고_다시_읽으면_연결이_보인다(self):
        from app.views.system.form_edit import build_inspection, parse_inspection
        section = DigFormSection(SectionType='INSPECTION', WorkerColumnYN='N')
        columns = [{'title': '항목', 'kind': 'TEXT', 'width': 100}, {'title': '사진', 'kind': 'IMAGE', 'width': 80}]
        items, header_rows = build_inspection(section, columns, [['A', {'vision_item': 7}], ['B', None]])
        self.assertEqual([i.VisionItem_id for i in items if i.InputYN == 'Y'], [7, None])
        rows = {}
        for i in items:
            rows.setdefault(i.RowIndex, {})[i.ColumnIndex] = i
        _parsed, values = parse_inspection(rows, header_rows, False)
        self.assertEqual(values, [['A', {'vision_item': 7}], ['B', None]])

    def test_비전검사항목_값이_숫자가_아니면_거절한다(self):
        from app.views.system.form_edit import build_inspection
        section = DigFormSection(SectionType='INSPECTION', WorkerColumnYN='N')
        with self.assertRaisesMessage(ValueError, '비전검사항목 값이 올바르지 않습니다.'):
            build_inspection(section, [{'title': '사진', 'kind': 'IMAGE'}], [[{'vision_item': 'x'}]])

    def test_섹션_이미지를_켜면_표_밖_행_0_칸을_하나_더한다(self):
        from app.views.system.form_edit import build_inspection
        section = DigFormSection(SectionType='INSPECTION', WorkerColumnYN='N')
        columns = [{'title': '항목', 'kind': 'TEXT', 'width': 100}]
        plain, _ = build_inspection(section, columns, [['A']])
        self.assertFalse([i for i in plain if i.RowIndex == 0])
        items, _ = build_inspection(section, columns, [['A']], section_image=True)
        (cell,) = [i for i in items if i.RowIndex == 0]
        self.assertEqual((cell.RowType, cell.ColumnIndex, cell.InputYN, cell.ResultType), ('S', 0, 'Y', 'I'))


class DigFormHeaderFieldTest(TestCase):
    '''머리글 입력값 항목 — domain/services/dig_form_fields.py'''

    def test_품질_양식은_입고번호를_따로_고르고_수입_양식은_WO_칸이_입고번호다(self):
        from domain.services.dig_form_fields import fields_for
        outgoing = {f['bind']: f['name'] for f in fields_for('OUTGOING')}
        incoming = {f['bind']: f['name'] for f in fields_for('INCOMING')}
        self.assertEqual((outgoing['result.WorkOrderNumber'], outgoing['result.field.receipt_no']), ('WO', '입고번호'))
        self.assertEqual(incoming['result.WorkOrderNumber'], '입고번호')
        self.assertNotIn('result.field.receipt_no', incoming)
        # 구분을 정하기 전의 새 양식(검사양식 관리는 수입·품질 한 화면) — 모든 항목, 저장할 때 구분으로 막는다
        self.assertIn('result.field.receipt_no', {f['bind'] for f in fields_for('')})

    def test_작성일_작성자는_표시만_하고_WO_는_이어쓰기_키다(self):
        from domain.services.dig_form_fields import AUTO_BINDS, WORK_ORDER_BIND, fields_for
        self.assertEqual(AUTO_BINDS, ('result.WriteDate', 'result.Writer'))
        self.assertEqual(WORK_ORDER_BIND, 'result.WorkOrderNumber')
        self.assertEqual({f['bind'] for f in fields_for('OUTGOING') if f['input'] == 'auto'}, set(AUTO_BINDS))

    def test_머리글_입력값은_등록된_항목이나_직접_입력만_받는다(self):
        from app.views.system.form_edit import check_header_binds
        cells = [{'row': 1, 'col': 1, 'bind': 'result.field.product', 'input': True},
                 {'row': 1, 'col': 2, 'bind': 'result.extra.f1', 'input': True, 'name': '확인자'},
                 {'row': 1, 'col': 3, 'bind': 'appr.2'}, {'row': 1, 'col': 4, 'content': '라벨'}]
        self.assertIsNone(check_header_binds([cells], 'INCOMING'))
        self.assertEqual(check_header_binds([[{'bind': 'result.field.receipt_no', 'input': True}]], 'INCOMING'),
                         '입고번호 입력값은 이 양식 구분에서 쓸 수 없습니다.')
        self.assertEqual(check_header_binds([cells, [{'bind': 'result.Nope'}]], 'OUTGOING'),
                         '머리글에 알 수 없는 입력값이 있습니다: result.Nope')

    def test_품목이나_품번을_검색하면_함께_채울_값을_준다(self):
        from domain.models.basic import Product, Receipt
        from domain.services.dig_form_fields import lookup
        bracket = Product.objects.create(Code='P-001', PartNo='BRK-10', Revision='A', Name='브래킷')
        Product.objects.create(Code='P-002', PartNo='CVR-20', Revision='A', Name='커버')
        both = {'result.field.product': '브래킷', 'result.field.part_no': 'BRK-10'}
        self.assertEqual(lookup('result.field.product', '브래'),
                         [{'code': 'P-001', 'label': 'BRK-10 · 브래킷', 'values': both, 'text': '브래킷'}])
        self.assertEqual([r['text'] for r in lookup('result.field.part_no', '')], ['BRK-10', 'CVR-20'])
        Receipt.objects.create(ReceiptNo='R-1-1', ReqNo='R-1', ReqSeq=1, Product=bracket, ItemCode='P-001', ItemName='브래킷', Qty=3)
        self.assertEqual([(r['text'], r['label']) for r in lookup('result.field.receipt_no', 'R-1')], [('R-1-1', 'R-1-1 · 브래킷')])
        with self.assertRaisesMessage(ValueError, '목록에서 고르는 입력값이 아닙니다.'):
            lookup('result.WorkOrderNumber', '')


class FormEditSaveTest(TestCase):
    '''양식 편집 저장(form_edit.save_form) — 칸이 그대로인 수정. 새 양식코드는 PostgreSQL 시퀀스라 tests/pg 에서 본다'''
    COLUMNS = [{'title': '항목', 'kind': 'TEXT', 'width': 100}, {'title': '판정', 'kind': 'MIXED', 'width': 90}]
    ROWS = [['외관', {'kind': 'JUDGE', 'code_group': 'dig_form_okng'}]]

    def setUp(self):
        from app.views.system.form_edit import build_inspection
        group = UserGroup.objects.create(Code='qc', Name='품질')
        UserGroupMenu.objects.create(UserGroup=group, MenuCode=DIG_FORM_EDIT_MENU, AuthCode='RW')   # 검사양식 관리(수입·품질 한 화면)
        self.user = User.objects.create_user('editor', password='x')
        self.user.userprofile.UserGroup = group
        self.user.userprofile.save()
        judge_code.ensure_defaults()
        self.form = DigForm.objects.create(Code='DF-S1', Title='수정 전', LayoutType='SECTION', FormType='OUTGOING')
        self.section = DigFormSection.objects.create(DigForm=self.form, SectionType='INSPECTION', Title='점검', SortOrder=1, WorkerColumnYN='N')
        items, header_rows = build_inspection(self.section, self.COLUMNS, self.ROWS)
        DigFormItem.objects.bulk_create(items)
        self.section.HeaderRowCount = header_rows
        self.section.save()

    def save(self, **inspection):
        from app.views.system.form_edit import save_form
        s = {'id': self.section.id, 'type': 'INSPECTION', 'title': '점검', 'width': 12, 'worker_column_yn': 'N',
             'columns': self.COLUMNS, 'rows': self.ROWS, **inspection}
        header = {'type': 'HEADER', 'title': '확인', 'width': 6, 'cells': [{'row': 1, 'col': 1, 'content': '확인자'}]}
        return save_form({'id': self.form.id, 'title': '수정 후', 'top_cells': [], 'sections': [s, header]}, self.user)

    def test_칸이_그대로면_그_버전에서_제목_크기_열_폭만_고치고_작업자_열은_그대로다(self):
        columns = [dict(self.COLUMNS[0], width=150), self.COLUMNS[1]]
        body = self.save(title='점검(수정)', width=6, height='300', columns=columns, worker_column_yn='Y')
        self.assertEqual((body['success'], body['revised']), (True, True))   # 작업자 열을 켜면 칸이 바뀐다 — 새 버전, 이 버전은 그대로
        self.assertNotEqual(body['id'], self.form.id)
        body = self.save(title='점검(수정)', width=6, height='300', columns=columns)
        self.assertEqual((body['success'], body['revised'], body['id']), (True, False, self.form.id))
        self.section.refresh_from_db()
        self.assertEqual((self.section.Title, self.section.Width, self.section.Height, self.section.WorkerColumnYN), ('점검(수정)', 6, 300, 'N'))
        self.assertEqual(DigFormItem.objects.get(DigFormSection=self.section, RowType='H', ColumnIndex=1).MinColumnWidth, 150)
        header = DigFormSection.objects.get(DigForm=self.form, SectionType='HEADER')
        self.assertEqual((header.SortOrder, header.Width, json.loads(header.Content)), (2, 6, [{'row': 1, 'col': 1, 'content': '확인자'}]))
        self.form.refresh_from_db()
        self.assertEqual(self.form.Title, '수정 후')


class FormEditMixedColumnTest(TestCase):
    '''행마다 지정 열 — 칸마다 종류·판정 선택지·앞뒤 글자'''
    COLUMNS = [{'title': '항목', 'kind': 'TEXT', 'width': 100}, {'title': '판정', 'kind': 'MIXED', 'width': 90},
               {'title': '건수', 'kind': 'MIXED', 'width': 90}]
    ROWS = [
        ['① 도장품', {'kind': 'JUDGE', 'code_group': 'dig_form_okng'},
         {'kind': 'INPUT', 'type': 'N', 'lower_limit': '', 'upper_limit': '3', 'label': '부적합 건수 : {} EA'}],
        ['③ 구매품', {'kind': 'JUDGE', 'code_group': 'dig_form_pass_na'}, {'kind': 'TEXT', 'text': '해당 없음'}],
        ['ERP', {'kind': 'EMPTY'}, {'kind': 'CHECK', 'label': ''}],
    ]

    def build(self, rows=None):
        from app.views.system.form_edit import build_inspection
        section = DigFormSection(SectionType='INSPECTION', WorkerColumnYN='N')
        return build_inspection(section, self.COLUMNS, rows or self.ROWS)

    def test_칸마다_고른_종류로_저장한다(self):
        items, _ = self.build()
        head = {i.ColumnIndex: i for i in items if i.RowType == 'H'}
        self.assertEqual([head[k].ResultType for k in (1, 2, 3)], [None, 'M', 'M'])
        body = {(i.RowIndex, i.ColumnIndex): i for i in items if i.RowType == 'D'}
        self.assertEqual((body[2, 2].ResultType, body[2, 2].CodeGroup), ('S', 'dig_form_okng'))
        self.assertEqual((body[3, 2].ResultType, body[3, 2].CodeGroup), ('S', 'dig_form_pass_na'))
        self.assertEqual((body[2, 3].ResultType, body[2, 3].UpperLimit, body[2, 3].Content), ('N', 3, '부적합 건수 : {} EA'))
        self.assertEqual((body[3, 3].InputYN, body[3, 3].Content), ('N', '해당 없음'))
        self.assertEqual((body[4, 2].InputYN, body[4, 2].Content), ('N', None))  # 비움 = 빈 글자 칸
        self.assertEqual((body[4, 3].ResultType, body[4, 3].Content), ('B', None))

    def test_다시_읽으면_행마다_지정_열과_칸_값이_보인다(self):
        from app.views.system.form_edit import parse_inspection
        items, header_rows = self.build()
        rows = {}
        for i in items:
            rows.setdefault(i.RowIndex, {})[i.ColumnIndex] = i
        parsed, values = parse_inspection(rows, header_rows, False)
        self.assertEqual([c['kind'] for c in parsed], ['TEXT', 'MIXED', 'MIXED'])
        self.assertEqual(values, [
            ['① 도장품', {'kind': 'JUDGE', 'label': '', 'code_group': 'dig_form_okng'},
             {'kind': 'INPUT', 'label': '부적합 건수 : {} EA', 'type': 'N', 'lower_limit': '', 'upper_limit': '3'}],
            ['③ 구매품', {'kind': 'JUDGE', 'label': '', 'code_group': 'dig_form_pass_na'}, {'kind': 'TEXT', 'text': '해당 없음'}],
            ['ERP', {'kind': 'EMPTY'}, {'kind': 'CHECK', 'label': ''}],
        ])

    def test_칸_종류와_판정_선택지와_상하한을_확인한다(self):
        from app.views.system.form_edit import validate_inspection
        groups = {'dig_form_okng', 'dig_form_pass_na'}
        section = {'title': '점검', 'columns': self.COLUMNS}
        self.assertIsNone(validate_inspection(dict(section, rows=self.ROWS), groups))
        bad_kind = [['A', {'kind': 'X'}, {'kind': 'EMPTY'}]]
        self.assertEqual(validate_inspection(dict(section, rows=bad_kind), groups), '[점검] 1번째 행 판정의 칸 종류를 선택하세요.')
        bad_group = [['A', {'kind': 'JUDGE', 'code_group': 'none'}, {'kind': 'EMPTY'}]]
        self.assertEqual(validate_inspection(dict(section, rows=bad_group), groups), '[점검] 1번째 행 판정의 판정 선택지를 선택하세요.')
        bad_limit = [['A', {'kind': 'EMPTY'}, {'kind': 'INPUT', 'type': 'N', 'lower_limit': '5', 'upper_limit': '1'}]]
        self.assertEqual(validate_inspection(dict(section, rows=bad_limit), groups), '[점검] 1번째 행 건수의 하한이 상한보다 큽니다.')

    def test_칸의_선택지나_앞뒤_글자를_바꾸면_칸이_바뀐_것이다(self):
        from app.views.system.form_edit import item_signature
        before = {item_signature(i) for i in self.build()[0]}
        rows = [list(r) for r in self.ROWS]
        rows[1][1] = {'kind': 'JUDGE', 'code_group': 'dig_form_okng'}
        self.assertNotEqual({item_signature(i) for i in self.build(rows)[0]}, before)
        rows = [list(r) for r in self.ROWS]
        rows[0][2] = dict(rows[0][2], label='미입고 건수 : {} EA')
        self.assertNotEqual({item_signature(i) for i in self.build(rows)[0]}, before)


class DigFormSectionImageTest(DigFormCellImageTest):
    """섹션 이미지 칸(행 0)도 이미지 칸과 같은 방식으로 저장한다 — 이미지 칸 시험을 그대로 돌린다."""

    def setUp(self):
        super().setUp()
        self.item.RowType, self.item.RowIndex, self.item.ColumnIndex = 'S', 0, 0
        self.item.save()


def jpeg_bytes(size=(16, 12), color='gray'):
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, format='JPEG')
    return buffer.getvalue()


class DigFormVisionCaptureTest(TestCase):
    """비전검사항목이 연결된 이미지 칸 — 넣는 즉시 비전 데이터 관리 이미지가 되고, 칸 값은 그 이미지 id 다."""

    def setUp(self):
        reset_tenant_cache()
        with tenant_atomic():
            self.vision = InspectionItem.objects.create(tenant=current_tenant(), code='VIS-1', name='외관')
            self.other_vision = InspectionItem.objects.create(tenant=current_tenant(), code='VIS-2', name='치수')
        self.form, _section, (self.cell,) = make_form(input_types=('I',))
        DigFormItem.objects.filter(id=self.cell.id).update(VisionItem=self.vision)
        self.group = UserGroup.objects.create(Code='qc', Name='품질')
        UserGroupMenu.objects.create(UserGroup=self.group, MenuCode='wm_dig_form_outgoing_write', AuthCode='RW')
        self.user = self.member('writer')
        self.client.force_login(self.user)

    def member(self, name):
        user = User.objects.create_user(name, password='x')
        user.userprofile.UserGroup = self.group
        user.userprofile.save()
        return user

    def capture(self, cell_id=None, data=None, name='shot.jpg', content_type='image/jpeg'):
        return self.client.post('/api/dig_form/dig_form?action=capture', {
            'item_id': cell_id or self.cell.id,
            'uploadfile': SimpleUploadedFile(name, data or jpeg_bytes(), content_type)})

    def save(self, value, result_id=''):
        return self.client.post('/api/dig_form/dig_form?action=save', {
            'form_id': self.form.id, 'result_id': result_id,
            'Q': json.dumps([{'item_id': self.cell.id, 'value': value}])}).json()

    def assets(self, item):
        with tenant_atomic():
            return list(ImageAsset.objects.for_tenant(current_tenant()).filter(dataset__item=item)
                        .values_list('id', 'label_status'))

    def test_사진을_넣으면_연결된_비전검사항목의_라벨링_대기_이미지가_된다(self):
        body = self.capture().json()
        self.assertTrue(body['success'])
        self.assertEqual(self.assets(self.vision), [(body['asset_id'], 'UNLABELED')])
        self.assertEqual(self.client.session['dig_form_captures'], [body['asset_id']])
        with tenant_atomic():
            asset = ImageAsset.objects.get(pk=body['asset_id'])
        self.assertEqual((asset.channel, asset.uploaded_by_id), ('FORM', self.user.id))

    def test_치수_측정_항목에는_사진을_넣지_않는다(self):
        # 측정값은 고정 거치대 클라이언트만 낸다 — 사진만 쌓이지 않게 한다(설계 Q5)
        with tenant_atomic():
            InspectionItem.objects.filter(pk=self.vision.pk).update(task_type='MEASUREMENT')
        body = self.capture().json()
        self.assertEqual(body, {'success': False, 'message': '치수 측정 비전검사항목에는 사진을 넣을 수 없습니다.'})
        self.assertEqual(self.assets(self.vision), [])

    def test_같은_사진을_다시_넣어도_받는다(self):
        self.capture()
        self.assertTrue(self.capture().json()['success'])
        self.assertEqual(len(self.assets(self.vision)), 2)

    def test_비전검사항목_배정이_없어도_검사작성_쓰기면_넣고_업로드_기록은_작성자다(self):
        from domain.models.data import ActivityLog
        self.capture()   # ItemAssignment 를 하나도 만들지 않았다
        with tenant_atomic():
            log = ActivityLog.objects.for_tenant(current_tenant()).get(event_type='IMAGE_UPLOADED')
        self.assertEqual(log.actor_id, self.user.id)

    def test_검사작성_쓰기_권한이_없으면_넣지_않는다(self):
        UserGroupMenu.objects.filter(UserGroup=self.group).update(AuthCode='R')
        self.assertEqual(self.capture().status_code, 403)
        self.assertEqual(self.assets(self.vision), [])

    def test_수입검사작성_쓰기로는_품질_양식_칸에_넣지_않는다(self):
        UserGroupMenu.objects.filter(UserGroup=self.group).update(MenuCode='wm_dig_form_incoming_write')
        self.assertEqual(self.capture().status_code, 403)

    def test_연결_안_된_칸에는_넣지_않는다(self):
        DigFormItem.objects.filter(id=self.cell.id).update(VisionItem=None)
        self.assertEqual(self.capture().json(), {'success': False, 'message': '비전검사항목이 연결된 이미지 칸이 아닙니다.'})

    def test_중지된_비전검사항목에는_넣지_않는다(self):
        with tenant_atomic():
            InspectionItem.objects.filter(id=self.vision.id).update(status='PAUSED')
        self.assertEqual(self.capture().json(), {'success': False, 'message': '중지된 비전검사항목이라 사진을 넣을 수 없습니다.'})

    def test_JPG_PNG_가_아니면_거절한다(self):
        body = self.capture(name='shot.gif', content_type='image/gif').json()
        self.assertEqual(body, {'success': False, 'message': 'PNG 또는 JPG/JPEG 파일만 업로드할 수 있습니다.'})

    def test_capture_는_GET_으로_부르면_막는다(self):
        self.assertEqual(self.client.get('/api/dig_form/dig_form', {'action': 'capture', 'item_id': self.cell.id}).status_code, 403)

    def test_저장하면_칸_값은_이미지_id_이고_첨부는_만들지_않는다(self):
        asset_id = self.capture().json()['asset_id']
        self.assertTrue(self.save(str(asset_id))['success'])
        self.assertEqual(DigFormItemResult.objects.get().TextResult, str(asset_id))
        self.assertFalse(AttachFile.objects.exists())

    def test_이번_세션에_올리지_않은_이미지_id_는_저장하지_않는다(self):
        asset_id = self.capture().json()['asset_id']
        self.client.force_login(self.member('other'))
        self.assertEqual(self.save(str(asset_id)), {'success': False, 'message': '이미지 정보를 찾을 수 없습니다. 이미지를 다시 올려 주세요.'})

    def test_다른_비전검사항목_이미지는_저장하지_않는다(self):
        other = DigFormItem.objects.create(DigFormSection=self.cell.DigFormSection, RowType='D', RowIndex=3, ColumnIndex=1,
                                           ResultType='I', InputYN='Y', VisionItem=self.other_vision)
        asset_id = self.capture(cell_id=other.id).json()['asset_id']
        self.assertFalse(self.save(str(asset_id))['success'])

    def test_이미_저장된_값은_세션이_바뀌어도_그대로_저장한다(self):
        asset_id = self.capture().json()['asset_id']
        result_id = self.save(str(asset_id))['result_id']
        self.client.force_login(self.member('other'))
        self.assertTrue(self.save(str(asset_id), result_id)['success'])

    def test_칸_사진은_올린_세션이거나_저장된_연결_칸이_가리킬_때만_받는다(self):
        asset_id = self.capture().json()['asset_id']
        unsaved_id = self.capture().json()['asset_id']
        url = f'/media/dig-form-asset/{asset_id}/'
        self.assertEqual(self.client.get(url).status_code, 200)                 # 이번 세션에 올림
        self.assertTrue(self.save(str(asset_id))['success'])
        self.client.force_login(self.member('reader'))                         # 다른 사용자 — 세션도 새로 생긴다
        self.assertEqual(self.client.get(url).status_code, 200)                 # 저장된 연결 칸이 가리킴
        self.assertEqual(self.client.get(f'/media/dig-form-asset/{unsaved_id}/').status_code, 404)   # 저장 전, 남의 세션
        self.client.force_login(User.objects.create_user('nobody', password='x'))
        self.assertEqual(self.client.get(url).status_code, 404)                 # 디지털 양식 메뉴 권한 없음

    def test_Overlay_는_표시_중일_때만_칸으로_받는다(self):
        from django.core.files.base import ContentFile
        from domain.models.vision import VisionOverlay
        url = f'/media/dig-form-overlay/{self.cell.id}/'
        self.assertEqual(self.client.get(url).status_code, 404)                 # Overlay 없음
        overlay = VisionOverlay(item=self.vision, opacity=0.5)
        overlay.image.save('o.png', ContentFile(png_bytes()), save=True)
        self.assertEqual(self.client.get(url).status_code, 200)
        overlay.visible = False
        overlay.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_양식_상세의_칸에_연결된_비전검사항목이_실린다(self):
        from domain.services.dig_form_image import vision_links
        self.assertEqual(vision_links([self.cell.id]), {self.cell.id: {
            'id': self.vision.id, 'code': 'VIS-1', 'name': '외관', 'status': 'ACTIVE', 'overlay_opacity': None,
            'task_type': 'OBJECT_DETECTION', 'capture_method': 'RIG'}})


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='maip-rig-'))
class DigFormRigResultTest(TestCase):
    """거치대 비전검사항목 칸에 그 항목의 최근 검사 결과를 골라 넣는다(설계 2026-10-21 §7)."""

    def setUp(self):
        import uuid
        from domain.models.vision import VisionClient
        from domain.services.data.image import ImageService
        from tests.test_data_services import make_image
        self.uuid = uuid
        reset_tenant_cache()
        with tenant_atomic():
            tenant = current_tenant()
            self.rig = InspectionItem.objects.create(tenant=tenant, code='VIS-R', name='거치대')
            self.dim = InspectionItem.objects.create(tenant=tenant, code='VIS-D', name='치수', task_type='MEASUREMENT')
            self.tab = InspectionItem.objects.create(tenant=tenant, code='TAB-T', name='태블릿', capture_method='TABLET')

            def asset(item, name):
                return ImageService.upload_images(item, [make_image(name)], requires_labeling=True,
                                                  allow_duplicate=True)['uploaded'][0]['id']
            self.asset = asset
        self.client_row = VisionClient.objects.create(client_id='CLIENT-R', name='1호기', api_key_hash='x' * 64)
        self.form, _section, (self.cell, self.cell2, self.dim_cell, self.tab_cell, self.plain_cell) = make_form(
            input_types=('I', 'I', 'I', 'I', 'I'))
        for cell, item in ((self.cell, self.rig), (self.cell2, self.rig), (self.dim_cell, self.dim), (self.tab_cell, self.tab)):
            DigFormItem.objects.filter(id=cell.id).update(VisionItem=item)
        self.group = UserGroup.objects.create(Code='qc', Name='품질')
        self.menu = UserGroupMenu.objects.create(UserGroup=self.group, MenuCode='wm_dig_form_outgoing_write', AuthCode='RW')
        self.user = User.objects.create_user('writer', password='x')
        self.user.userprofile.UserGroup = self.group
        self.user.userprofile.save()
        self.client.force_login(self.user)

    def inspection(self, item, days_ago=0, image=True, **fields):
        from domain.models.vision import VisionInspection
        key = str(self.uuid.uuid4())
        with tenant_atomic():
            asset_id = self.asset(item, key[:8] + '.png') if image else None
            VisionInspection.objects.create(id=key, request_id=key, client=self.client_row, item=item, status='SUCCESS',
                                            image_asset_id=asset_id, **fields)
            if days_ago:
                VisionInspection.objects.filter(pk=key).update(
                    created_at=datetime.datetime.now() - datetime.timedelta(days=days_ago))
        return key, asset_id

    def results(self, cell):
        return self.client.get('/api/dig_form/dig_form', {'action': 'rig_results', 'item_id': cell.id}).json()

    def use(self, cell, inspection_id):
        return self.client.post('/api/dig_form/dig_form?action=use_rig_result', {'item_id': cell.id, 'inspection_id': inspection_id})

    def test_목록은_그_항목의_최근_30일_이미지_있는_결과를_최신순으로_준다(self):
        old, _ = self.inspection(self.rig, abnormal=False)
        new, new_asset = self.inspection(self.rig, abnormal=True)
        self.inspection(self.rig, days_ago=31, abnormal=False)
        self.inspection(self.rig, image=False, abnormal=False)
        self.inspection(self.dim, abnormal=False)
        rows = self.results(self.cell)['rows']
        self.assertEqual([(r['id'], r['judgement'], r['client_name']) for r in rows], [(new, '이상', '1호기'), (old, '정상', '1호기')])
        self.assertEqual(rows[0]['asset_id'], new_asset)

    def test_치수_측정_결과는_측정점_줄을_준다(self):
        self.inspection(self.dim, abnormal=False, measurements=[
            {'code': 'A', 'name': '치수 A', 'value': 540.32, 'lower': 539.0, 'upper': 541.0, 'unit': 'mm', 'ok': True}])
        self.assertEqual(self.results(self.dim_cell)['rows'][0]['measured'],
                         [{'label': '치수 A (A)', 'text': '540.32 mm (539~541) 합격', 'ok': True}])

    def test_태블릿_칸과_연결_없는_칸은_불러오지_않는다(self):
        self.assertEqual(self.results(self.tab_cell), {'success': False, 'message': '거치대 비전검사항목이 연결된 칸이 아닙니다.'})
        self.assertEqual(self.results(self.plain_cell), {'success': False, 'message': '비전검사항목이 연결된 이미지 칸이 아닙니다.'})

    def test_고르면_세션에_들어가_그_값으로_저장하고_두_칸에_넣어도_된다(self):
        key, asset_id = self.inspection(self.rig, abnormal=False)
        self.assertEqual(self.use(self.cell, key).json(), {'success': True, 'message': '', 'asset_id': asset_id})
        self.assertTrue(self.use(self.cell2, key).json()['success'])
        body = self.client.post('/api/dig_form/dig_form?action=save', {'form_id': self.form.id, 'Q': json.dumps([
            {'item_id': self.cell.id, 'value': str(asset_id)}, {'item_id': self.cell2.id, 'value': str(asset_id)}])}).json()
        self.assertTrue(body['success'], body)
        self.assertEqual(sorted(DigFormItemResult.objects.values_list('TextResult', flat=True)), [str(asset_id)] * 2)
        # 결과 보기 값에 판정이 붙는다
        rows = self.client.get('/api/dig_form/dig_form', {'action': 'result_values', 'result_id': body['result_id']}).json()
        self.assertEqual({r['vision_result']['judgement'] for r in rows}, {'정상'})

    def test_다른_항목_결과는_넣지_않는다(self):
        key, _ = self.inspection(self.dim, abnormal=False)
        self.assertEqual(self.use(self.cell, key).json(), {'success': False, 'message': '불러올 검사 결과를 찾을 수 없습니다.'})

    def test_쓰기_권한이_없거나_GET_이면_403(self):
        key, _ = self.inspection(self.rig, abnormal=False)
        self.assertEqual(self.client.get('/api/dig_form/dig_form', {'action': 'use_rig_result', 'item_id': self.cell.id,
                                                                    'inspection_id': key}).status_code, 403)
        self.menu.AuthCode = 'R'
        self.menu.save()
        self.assertEqual(self.use(self.cell, key).status_code, 403)


class FormEditRefImageTest(TestCase):
    '''고정 이미지 열 — 양식에 넣어 두는 그림. [위 칸과 병합]한 행은 칸 하나(RowSpan), 첨부는 칸마다 하나'''
    COLUMNS = [{'title': '작업', 'kind': 'TEXT', 'width': 100}, {'title': '사진', 'kind': 'REF_IMAGE', 'width': 120}]

    def setUp(self):
        from app.views.system.form_edit import build_inspection
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        self.enterContext(override_settings(MEDIA_ROOT=media))
        group = UserGroup.objects.create(Code='qc', Name='품질')
        UserGroupMenu.objects.create(UserGroup=group, MenuCode=DIG_FORM_EDIT_MENU, AuthCode='RW')
        self.user = User.objects.create_user('editor', password='x')
        self.user.userprofile.UserGroup = group
        self.user.userprofile.save()
        self.client.force_login(self.user)
        self.form = DigForm.objects.create(Code='DF-R1', Title='그림 양식', LayoutType='SECTION', FormType='INCOMING')
        self.section = DigFormSection.objects.create(DigForm=self.form, SectionType='INSPECTION', Title='점검', WorkerColumnYN='N')
        items, header_rows = build_inspection(self.section, self.COLUMNS, [['A', None], ['B', None], ['C', None]])
        DigFormItem.objects.bulk_create(items)
        self.section.HeaderRowCount = header_rows
        self.section.save()

    def upload(self, user=None):
        if user is not None:
            return save_upload(SimpleUploadedFile('a.png', png_bytes(), 'image/png'), user,
                               table='dig_form_item', attach_name='ref')['fileId']
        body = self.client.post('/api/system/form_edit?action=upload_image&target=ref',
                                {'uploadfile': SimpleUploadedFile('a.png', png_bytes(), 'image/png')}).json()
        self.assertTrue(body['success'], body)
        return body['fileId']

    def build(self, rows):
        from app.views.system.form_edit import build_inspection
        return build_inspection(DigFormSection(SectionType='INSPECTION', WorkerColumnYN='N'), self.COLUMNS, rows)

    def save(self, form, rows):
        section = DigFormSection.objects.get(DigForm=form, SectionType='INSPECTION')
        data = {'id': form.id, 'title': form.Title, 'top_cells': [], 'sections': [
            {'id': section.id, 'type': 'INSPECTION', 'title': '점검', 'width': 12, 'worker_column_yn': 'N',
             'section_image_yn': 'N', 'columns': self.COLUMNS, 'rows': rows}]}
        return self.client.post('/api/system/form_edit?action=save', {'Q': json.dumps(data)}).json()

    def ref_cells(self, form_id):
        return list(DigFormItem.objects.filter(DigFormSection__DigForm_id=form_id, RowType='D', ResultType='R').order_by('RowIndex'))

    def test_위_칸과_병합한_행은_칸_하나로_저장하고_입력칸이_아니다(self):
        items, _ = self.build([['A', {'file': 11}], ['B', {'merge': True}], ['C', None]])
        head = [i for i in items if i.RowType == 'H' and i.ColumnIndex == 2][0]
        self.assertEqual(head.ResultType, 'R')
        cells = sorted((i for i in items if i.RowType == 'D' and i.ColumnIndex == 2), key=lambda i: i.RowIndex)
        self.assertEqual([(i.RowIndex, i.RowSpan, i.Content, i.ResultType, i.InputYN) for i in cells],
                         [(2, 2, '11', 'R', 'N'), (4, 1, None, 'R', 'N')])

    def test_다시_읽으면_병합한_행은_위_칸과_병합으로_보인다(self):
        from app.views.system.form_edit import parse_inspection
        items, header_rows = self.build([['A', {'file': 11}], ['B', {'merge': True}], ['C', None]])
        rows = {}
        for i in items:
            rows.setdefault(i.RowIndex, {})[i.ColumnIndex] = i
        columns, values = parse_inspection(rows, header_rows, False)
        self.assertEqual(columns[1]['kind'], 'REF_IMAGE')
        self.assertEqual(values, [['A', {'file': 11}], ['B', {'merge': True}], ['C', None]])

    def test_위_칸에_이미지가_없으면_병합하지_않는다(self):
        from app.views.system.form_edit import validate_inspection
        section = {'title': '점검', 'columns': self.COLUMNS}
        self.assertEqual(validate_inspection(dict(section, rows=[['A', {'merge': True}]]), set()),
                         '[점검] 1번째 행 사진: 위 칸에 이미지가 없어 병합할 수 없습니다.')
        self.assertEqual(validate_inspection(dict(section, rows=[['A', None], ['B', {'merge': True}]]), set()),
                         '[점검] 2번째 행 사진: 위 칸에 이미지가 없어 병합할 수 없습니다.')
        rows = [['A', {'file': 1}], ['B', {'merge': True}], ['C', {'merge': True}]]
        self.assertIsNone(validate_inspection(dict(section, rows=rows), set()))

    def test_그림을_넣으면_새_버전의_칸에_첨부가_연결된다(self):
        first, second = self.upload(), self.upload()
        body = self.save(self.form, [['A', {'file': first}], ['B', {'merge': True}], ['C', {'file': second}]])
        self.assertEqual((body['success'], body['revised']), (True, True), body)
        cells = self.ref_cells(body['id'])
        self.assertEqual([(c.RowSpan, c.Content) for c in cells], [(2, str(first)), (1, str(second))])
        for cell in cells:
            attach = AttachFile.objects.get(id=int(cell.Content))
            self.assertEqual((attach.TableName, attach.AttachName, attach.DataPk), ('dig_form_item', 'ref', cell.id))
        self.assertEqual(self.client.get(image_url(first)).status_code, 200)

    def test_그림이_그대로면_그_버전을_고치고_바꾸면_새_버전에_첨부를_복제한다(self):
        first, second = self.upload(), self.upload()
        rows = [['A', {'file': first}], ['B', {'merge': True}], ['C', {'file': second}]]
        v2 = self.save(self.form, rows)['id']
        self.assertEqual((self.save(DigForm.objects.get(id=v2), rows)['revised']), False)

        third = self.upload()
        body = self.save(DigForm.objects.get(id=v2), [['A', {'file': first}], ['B', {'merge': True}], ['C', {'file': third}]])
        self.assertEqual((body['success'], body['revised']), (True, True), body)
        old, new = self.ref_cells(v2), self.ref_cells(body['id'])
        # 이전 버전 칸과 첨부는 그대로, 새 버전은 같은 파일의 첨부 행을 따로 갖는다
        self.assertEqual([c.Content for c in old], [str(first), str(second)])
        self.assertEqual(new[1].Content, str(third))
        copied = AttachFile.objects.get(id=int(new[0].Content))
        self.assertNotEqual(copied.id, first)
        self.assertEqual((copied.DataPk, copied.PhysicFileName), (new[0].id, AttachFile.objects.get(id=first).PhysicFileName))
        self.assertEqual(AttachFile.objects.get(id=first).DataPk, old[0].id)

    def test_다른_사람이_올리고_연결하지_않은_그림은_받지_않는다(self):
        other = User.objects.create_user('other', password='x')
        body = self.save(self.form, [['A', {'file': self.upload(other)}], ['B', None], ['C', None]])
        self.assertEqual(body, {'success': False, 'message': '고정 이미지 정보를 찾을 수 없습니다. 이미지를 다시 넣어 주세요.'})

    def test_양식을_지우면_고정_이미지_첨부_행도_지운다(self):
        v2 = self.save(self.form, [['A', {'file': self.upload()}], ['B', None], ['C', None]])['id']
        body = self.client.post('/api/system/form_edit?action=delete', {'id': v2}).json()
        self.assertTrue(body['success'], body)
        self.assertFalse(AttachFile.objects.filter(TableName='dig_form_item', AttachName='ref').exclude(DataPk=0).exists())

    def test_행마다_지정_열의_고정_이미지는_위_칸이_고정_이미지일_때만_병합한다(self):
        from app.views.system.form_edit import build_inspection, parse_inspection, validate_inspection
        columns = [{'title': '작업', 'kind': 'TEXT', 'width': 100}, {'title': '그림·설명', 'kind': 'MIXED', 'width': 160}]
        rows = [['A', {'kind': 'REF_IMAGE', 'file': 11}], ['B', {'kind': 'REF_IMAGE', 'merge': True}],
                ['C', {'kind': 'TEXT', 'text': '볼트 체결 순서 주의'}]]
        items, header_rows = build_inspection(DigFormSection(SectionType='INSPECTION', WorkerColumnYN='N'), columns, rows)
        cells = sorted((i for i in items if i.RowType == 'D' and i.ColumnIndex == 2), key=lambda i: i.RowIndex)
        self.assertEqual([(i.RowIndex, i.RowSpan, i.ResultType, i.InputYN, i.Content) for i in cells],
                         [(2, 2, 'R', 'N', '11'), (4, 1, None, 'N', '볼트 체결 순서 주의')])
        by_row = {}
        for i in items:
            by_row.setdefault(i.RowIndex, {})[i.ColumnIndex] = i
        self.assertEqual(parse_inspection(by_row, header_rows, False)[1], rows)

        section = {'title': '점검', 'columns': columns}
        self.assertIsNone(validate_inspection(dict(section, rows=rows), set()))
        below_text = [['A', {'kind': 'TEXT', 'text': '설명'}], ['B', {'kind': 'REF_IMAGE', 'merge': True}]]
        self.assertEqual(validate_inspection(dict(section, rows=below_text), set()),
                         '[점검] 2번째 행 그림·설명: 위 칸에 이미지가 없어 병합할 수 없습니다.')

    def test_행마다_지정_열의_고정_이미지도_칸에_첨부가_연결된다(self):
        from app.views.system.form_edit import build_inspection
        self.COLUMNS = [{'title': '작업', 'kind': 'TEXT', 'width': 100}, {'title': '그림·설명', 'kind': 'MIXED', 'width': 160}]
        DigFormItem.objects.filter(DigFormSection=self.section).delete()
        items, header_rows = build_inspection(self.section, self.COLUMNS, [['A', {'kind': 'EMPTY'}], ['B', {'kind': 'EMPTY'}]])
        DigFormItem.objects.bulk_create(items)
        file_id = self.upload()
        body = self.save(self.form, [['A', {'kind': 'REF_IMAGE', 'file': file_id}], ['B', {'kind': 'REF_IMAGE', 'merge': True}]])
        self.assertEqual((body['success'], body['revised']), (True, True), body)
        [cell] = self.ref_cells(body['id'])
        self.assertEqual((cell.RowSpan, cell.Content), (2, str(file_id)))
        self.assertEqual(AttachFile.objects.get(id=file_id).DataPk, cell.id)

    def test_고정_이미지_칸_그림은_파일과_함께_뽑는다(self):
        from domain.management.commands.export_dig_form import read
        v2 = self.save(self.form, [['A', {'file': self.upload()}], ['B', None], ['C', None]])['id']
        form = DigForm.objects.get(id=v2)
        [cell] = [c for c in self.ref_cells(v2) if (c.Content or '').isdigit()]
        out, files, dropped = export_forms(read(), [(form.Code, form.Version)])
        name = f'{form.Code}-v{form.Version}-ref-{cell.Content}.png'
        contents = [i['Content'] for s in out['forms'][0]['sections'] for i in s['items'] if i['ResultType'] == 'R']
        self.assertIn('{{dig_form_image:%s}}' % name, contents)
        self.assertEqual((list(out['ref_images']), list(files), dropped), ([name], [name], []))


class FormEditVersionTest(TestCase):
    """양식 편집 저장·복사·삭제 — 점검항목(칸)이 바뀌거나 복사하면 같은 코드의 새 버전, 그대로면 그 버전을 고친다."""
    COLUMNS = [{'title': '항목', 'kind': 'TEXT', 'width': 100}, {'title': '값', 'kind': 'INPUT', 'width': 80}]
    ROWS = [['A', {'type': 'N', 'lower_limit': '1', 'upper_limit': '9'}]]

    def setUp(self):
        from app.views.system.form_edit import build_inspection
        group = UserGroup.objects.create(Code='qc', Name='품질')
        UserGroupMenu.objects.create(UserGroup=group, MenuCode='wm_dig_form_incoming_form', AuthCode='RW')   # 검사양식 관리
        self.user = User.objects.create_user('editor', password='x')
        self.user.userprofile.UserGroup = group
        self.user.userprofile.save()
        self.client.force_login(self.user)
        self.form = DigForm.objects.create(Code='DF-T9', Title='시험 양식', LayoutType='SECTION')
        self.section = DigFormSection.objects.create(DigForm=self.form, SectionType='INSPECTION', Title='점검',
                                                     WorkerColumnYN='N')
        items, header_rows = build_inspection(self.section, self.COLUMNS, self.ROWS)
        DigFormItem.objects.bulk_create(items)
        self.section.HeaderRowCount = header_rows
        self.section.save()

    def payload(self, **section):
        s = {'id': self.section.id, 'type': 'INSPECTION', 'title': '점검', 'width': 12, 'height': None,
             'worker_column_yn': 'N', 'section_image_yn': 'N', 'columns': self.COLUMNS, 'rows': self.ROWS, **section}
        return {'id': self.form.id, 'title': '시험 양식', 'top_cells': [{'bind': 'result.WriteDate'}], 'sections': [s]}

    def save(self, data):
        return self.client.post('/api/system/form_edit?action=save', {'Q': json.dumps(data)}).json()

    def post(self, action, data):
        return self.client.post('/api/system/form_edit?action=' + action, data)

    def image_form(self, vision_item=None):
        from app.views.system.form_edit import build_inspection
        form = DigForm.objects.create(Code='DF-T8', Title='사진 양식', LayoutType='SECTION')
        section = DigFormSection.objects.create(DigForm=form, SectionType='INSPECTION', Title='점검', WorkerColumnYN='N')
        columns = [{'title': '항목', 'kind': 'TEXT', 'width': 100}, {'title': '사진', 'kind': 'IMAGE', 'width': 80}]
        items, header_rows = build_inspection(section, columns, [['A', {'vision_item': vision_item} if vision_item else None]])
        DigFormItem.objects.bulk_create(items)
        section.HeaderRowCount = header_rows
        section.save()
        payload = {'id': form.id, 'title': '사진 양식', 'top_cells': [{'bind': 'result.WriteDate'}], 'sections': [
            {'id': section.id, 'type': 'INSPECTION', 'title': '점검', 'width': 12, 'height': None, 'worker_column_yn': 'N',
             'section_image_yn': 'N', 'columns': columns, 'rows': [['A', None]]}]}
        return form, payload

    def vision_item(self, code='VIS-1', status='ACTIVE'):
        reset_tenant_cache()
        with tenant_atomic():
            return InspectionItem.objects.create(tenant=current_tenant(), code=code, name='외관', status=status)

    def judge_payload(self, code_group):
        columns = self.COLUMNS + [{'title': '판정', 'kind': 'JUDGE', 'code_group': code_group, 'width': 100}]
        return self.payload(columns=columns, rows=[row + [None] for row in self.ROWS])

    def test_판정_선택지_그룹은_양식_편집_API_로_항목결과_코드에서_읽는다(self):
        judge_code.ensure_defaults()
        sets = self.client.get('/api/system/form_edit', {'action': 'judge_sets'}).json()
        self.assertEqual([s['code'] for s in sets],
                         ['dig_form_okng', 'dig_form_pass_na', 'dig_form_fit', 'dig_form_usable', 'dig_form_receipt'])
        self.assertEqual(sets[2]['name'], '적합 / 부적합')

    def test_판정_열은_항목결과_코드에_있는_그룹이면_저장한다(self):
        judge_code.ensure_defaults()
        body = self.save(self.judge_payload('dig_form_fit'))
        self.assertTrue(body['success'], body)
        self.assertTrue(DigFormItem.objects.filter(CodeGroup='dig_form_fit', InputYN='Y', ResultType='S').exists())

    def test_판정_열이_없는_그룹이면_저장하지_않는다(self):
        judge_code.ensure_defaults()
        self.assertEqual(self.save(self.judge_payload('nope')),
                         {'success': False, 'message': '[점검] 3번째 열의 판정 선택지를 선택하세요.'})

    def test_이미지_칸_연결을_바꾸면_새_버전이고_원래_버전은_연결이_없다(self):
        item = self.vision_item()
        form, payload = self.image_form()
        payload['sections'][0]['rows'] = [['A', {'vision_item': item.id}]]
        body = self.save(payload)
        self.assertEqual((body['success'], body['revised']), (True, True))
        self.assertEqual(list(DigFormItem.objects.filter(DigFormSection__DigForm_id=body['id'], ResultType='I', InputYN='Y')
                              .values_list('VisionItem_id', flat=True)), [item.id])
        self.assertFalse(DigFormItem.objects.filter(DigFormSection__DigForm=form).exclude(VisionItem=None).exists())

    def test_연결이_그대로면_새_버전을_만들지_않는다(self):
        item = self.vision_item()
        _form, payload = self.image_form(vision_item=item.id)
        payload['sections'][0]['rows'] = [['A', {'vision_item': item.id}]]
        self.assertEqual(self.save(payload)['revised'], False)

    def test_없는_비전검사항목은_연결하지_않는다(self):
        _form, payload = self.image_form()
        payload['sections'][0]['rows'] = [['A', {'vision_item': 999999}]]
        self.assertEqual(self.save(payload), {'success': False, 'message': '연결할 비전검사항목을 찾을 수 없습니다. 목록을 다시 열어 골라 주세요.'})

    def test_중지된_항목이라도_이미_연결된_것은_그대로_저장한다(self):
        item = self.vision_item(status='PAUSED')
        _form, payload = self.image_form(vision_item=item.id)
        payload['sections'][0]['rows'] = [['A', {'vision_item': item.id}]]
        self.assertTrue(self.save(payload)['success'])

    def test_치수_측정_항목도_연결_목록에_있고_연결해_저장한다(self):
        # 치수 측정 항목은 거치대 결과 불러오기로만 넣는다(설계 2026-10-21 §7 — 2026-10-20 Q5 를 바꿈)
        item = self.vision_item()
        with tenant_atomic():
            dim = InspectionItem.objects.create(tenant=current_tenant(), code='VIS-DIM', name='치수', task_type='MEASUREMENT')
        rows = self.client.get('/api/system/form_edit', {'action': 'vision_items'}).json()['items']
        self.assertEqual([r['id'] for r in rows], [item.id, dim.id])
        _form, payload = self.image_form()
        payload['sections'][0]['rows'] = [['A', {'vision_item': dim.id}]]
        self.assertTrue(self.save(payload)['success'])

    def test_비전검사항목_목록은_검사양식_읽기로_받는다(self):
        item = self.vision_item()
        rows = self.client.get('/api/system/form_edit', {'action': 'vision_items'}).json()['items']
        self.assertEqual([(r['id'], r['code'], r['status']) for r in rows], [(item.id, 'VIS-1', 'ACTIVE')])
        self.assertEqual(rows[0]['task_type'], '객체 탐지')

    def test_비전검사항목_목록은_검사_분류로_묶고_이_양식에_매핑된_중분류를_알린다(self):
        reset_tenant_cache()
        with tenant_atomic():
            tenant = current_tenant()
            major = InspectionCategory.objects.create(tenant=tenant, name='출하검사', form_type='OUTGOING')
            mapped = InspectionCategory.objects.create(tenant=tenant, parent=major, name='출하검수', form_code='DF-T9')
            other = InspectionCategory.objects.create(tenant=tenant, parent=major, name='8계통', sort_order=-1)
            loose = InspectionItem.objects.create(tenant=tenant, code='VIS-0', name='미분류 항목')
            mine = InspectionItem.objects.create(tenant=tenant, code='VIS-2', name='라벨', category=mapped)
            theirs = InspectionItem.objects.create(tenant=tenant, code='VIS-1', name='체결', category=other)
        body = self.client.get('/api/system/form_edit', {'action': 'vision_items', 'form_code': 'DF-T9'}).json()
        self.assertEqual(body['mapped'], {'id': mapped.id, 'label': '출하검사 › 출하검수'})
        self.assertEqual([(r['id'], r['group'], r['category_id']) for r in body['items']], [
            (theirs.id, '출하검사 › 8계통', other.id), (mine.id, '출하검사 › 출하검수', mapped.id), (loose.id, '미분류', None)])
        self.assertIsNone(self.client.get('/api/system/form_edit', {'action': 'vision_items', 'form_code': 'DF-X'}).json()['mapped'])

    def test_조회_권한만으로는_양식을_고치거나_지우지_않는다(self):
        DigForm.objects.filter(id=self.form.id).update(FormType='INCOMING')
        self.assertTrue(self.save(self.payload())['success'])      # 수입 양식도 검사양식 관리 W 로 고친다
        UserGroupMenu.objects.update(AuthCode='R')
        self.assertEqual(self.post('save', {'Q': json.dumps(self.payload())}).status_code, 403)
        self.assertEqual(self.post('delete', {'id': self.form.id}).status_code, 403)
        self.assertTrue(DigForm.objects.filter(id=self.form.id).exists())

    def test_새_양식은_검사양식_관리_쓰기_권한이_있어야_한다(self):
        UserGroupMenu.objects.update(AuthCode='R')
        data = dict(self.payload(), id=None, form_type='INCOMING')
        self.assertEqual(self.post('save', {'Q': json.dumps(data)}).status_code, 403)

    def test_새_양식은_구분이_있어야_한다(self):
        data = dict(self.payload(), id=None, form_type='')
        self.assertEqual(self.save(data), {'success': False, 'message': '양식 구분이 올바르지 않습니다.'})

    def test_칸_설정은_검사양식_관리_쓰기_권한이면_구분과_상관없다(self):
        # 수입·품질 검사양식 관리를 하나로 합쳤다(사용자 결정 2026-10-21) — 품질 양식도 같은 W 로 고친다
        cell = DigFormItem.objects.filter(DigFormSection=self.section, InputYN='Y').first()
        response = self.post('save_item', {'item_id': cell.id, 'input_yn': 'Y', 'result_type': 'T'})
        self.assertTrue(response.json()['success'])
        UserGroupMenu.objects.update(AuthCode='R')
        self.assertEqual(self.post('save_item', {'item_id': cell.id, 'input_yn': 'Y', 'result_type': 'T'}).status_code, 403)

    def test_참고사진_업로드는_검사양식_관리_쓰기_권한이면_된다(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        with override_settings(MEDIA_ROOT=media):
            body = self.post('upload_image', {'uploadfile': SimpleUploadedFile('a.png', png_bytes(), 'image/png')}).json()
        self.assertTrue(body['success'])

    def item_ids(self, form):
        return set(DigFormItem.objects.filter(DigFormSection__DigForm=form).values_list('id', flat=True))

    def add_result(self, form):
        item = DigFormItem.objects.filter(DigFormSection__DigForm=form, InputYN='Y').first()
        result = DigFormResult.objects.create(DigForm=form, WriteDate='2026-10-16')
        DigFormItemResult.objects.create(DigFormResult=result, DigFormItem=item, NumberResult=5)

    def test_점검항목이_그대로면_작성_결과가_있어도_그_버전을_고친다(self):
        self.add_result(self.form)
        before = self.item_ids(self.form)
        data = self.payload(title='점검 1')
        data['title'] = '바뀐 양식명'
        body = self.save(data)
        self.assertEqual((body['success'], body['revised'], body['id'], body['version']), (True, False, self.form.id, 1))
        self.form.refresh_from_db()
        self.section.refresh_from_db()
        self.assertEqual((self.form.Title, self.section.Title), ('바뀐 양식명', '점검 1'))
        self.assertEqual(self.item_ids(self.form), before)

    def test_열_폭과_섹션_크기는_새_버전_없이_그_버전에서_고친다(self):
        self.add_result(self.form)
        before = self.item_ids(self.form)
        columns = [dict(self.COLUMNS[0], width=150), self.COLUMNS[1]]
        body = self.save(self.payload(columns=columns, width=6, height=300))
        self.assertEqual((body['success'], body['revised'], body['id']), (True, False, self.form.id))
        self.assertEqual(self.item_ids(self.form), before)
        self.section.refresh_from_db()
        self.assertEqual((self.section.Width, self.section.Height), (6, 300))
        self.assertTrue(DigFormItem.objects.filter(DigFormSection=self.section, RowType='H', Content='항목',
                                                   MinColumnWidth=150).exists())

    def test_점검항목을_바꾸면_작성_결과가_없어도_새_버전이다(self):
        before = self.item_ids(self.form)
        changes = [
            {'rows': self.ROWS + [['B', {'type': 'T'}]]},
            {'section_image_yn': 'Y'},
            {'worker_column_yn': 'Y'},
            {'rows': [['A', {'type': 'N', 'lower_limit': '1', 'upper_limit': '10'}]]},
        ]
        for version, change in enumerate(changes, start=2):
            with self.subTest(change=change):
                body = self.save(self.payload(**change))
                self.assertEqual((body['success'], body['revised'], body['version']), (True, True, version))
                new = DigForm.objects.get(id=body['id'])
                self.assertEqual(new.Code, 'DF-T9')
                self.assertNotEqual(DigFormSection.objects.get(DigForm=new).id, self.section.id)
        self.assertEqual(self.item_ids(self.form), before)   # 원래 버전은 그대로

    def test_점검항목_섹션을_빼거나_더하면_새_버전이다(self):
        data = self.payload()
        data['sections'] = []
        self.assertTrue(self.save(data)['revised'])
        data = self.payload()
        data['sections'].append(dict(data['sections'][0], id=''))
        self.assertTrue(self.save(data)['revised'])

    def test_다른_양식에서_불러온_섹션은_id_가_없어_칸이_같아도_새_버전이다(self):
        # 화면의 [기존 양식 불러오기]는 섹션 id 를 비워 보낸다 — 참고사진은 첨부 행을 복제해 새 섹션에 연결한다
        other = DigForm.objects.create(Code='DF-T8', Title='다른 양식', LayoutType='SECTION')
        photo = DigFormSection.objects.create(DigForm=other, SectionType='PHOTO')
        attach = AttachFile.objects.create(TableName='dig_form_section', DataPk=photo.id, AttachName='editor',
                                           FileIndex=0, FileName='a.png', PhysicFileName='a.png')
        before = self.item_ids(self.form)
        data = self.payload(id='')
        data['sections'].insert(0, {'id': '', 'type': 'PHOTO', 'title': '사진', 'width': 12,
                                    'content': '<p><img src="{}"></p>'.format(image_url(attach.id))})
        body = self.save(data)
        self.assertEqual((body['success'], body['revised'], body['version']), (True, True, 2))
        self.assertEqual(self.item_ids(self.form), before)
        new_photo = DigFormSection.objects.get(DigForm_id=body['id'], SectionType='PHOTO')
        self.assertTrue(AttachFile.objects.filter(DataPk=new_photo.id, TableName='dig_form_section').exists())
        self.assertTrue(AttachFile.objects.filter(id=attach.id, DataPk=photo.id).exists())   # 원본 첨부는 그대로

    def test_칸_단위_양식은_양식_편집에서_저장하지_않는다(self):
        DigForm.objects.filter(id=self.form.id).update(LayoutType='GRID')
        self.assertFalse(self.save(self.payload())['success'])

    def test_삭제는_고른_버전과_섹션_칸_참고사진_첨부를_지운다(self):
        photo = DigFormSection.objects.create(DigForm=self.form, SectionType='PHOTO')
        AttachFile.objects.create(TableName='dig_form_section', DataPk=photo.id, AttachName='editor', FileIndex=0,
                                  FileName='a.png', PhysicFileName='a.png')
        body = self.client.post('/api/system/form_edit?action=delete', {'id': self.form.id}).json()
        self.assertEqual((body['success'], body['code'], body['version']), (True, 'DF-T9', 1))
        self.assertFalse(DigForm.objects.filter(id=self.form.id).exists())
        self.assertFalse(DigFormSection.objects.filter(id__in=[self.section.id, photo.id]).exists())
        self.assertFalse(AttachFile.objects.filter(DataPk=photo.id, TableName='dig_form_section').exists())

    def test_칸_단위_양식도_작성_결과가_없으면_삭제한다(self):
        # 칸 단위 양식은 편집기를 열 수 없어 양식 상세 조회의 [삭제]가 같은 API 를 부른다
        DigForm.objects.filter(id=self.form.id).update(LayoutType='GRID')
        body = self.client.post('/api/system/form_edit?action=delete', {'id': self.form.id}).json()
        self.assertTrue(body['success'])
        self.assertFalse(DigForm.objects.filter(id=self.form.id).exists())
        self.assertFalse(DigFormItem.objects.filter(DigFormSection_id=self.section.id).exists())

    def test_작성_결과가_있으면_삭제하지_않는다(self):
        self.add_result(self.form)
        body = self.client.post('/api/system/form_edit?action=delete', {'id': self.form.id}).json()
        self.assertFalse(body['success'])
        self.assertTrue(DigForm.objects.filter(id=self.form.id).exists())

    def test_삭제는_GET_으로_부르면_막는다(self):
        response = self.client.get('/api/system/form_edit', {'action': 'delete', 'id': self.form.id})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(DigForm.objects.filter(id=self.form.id).exists())

    def test_글자_칸은_줄바꿈과_줄_앞_들여쓰기를_남기고_줄바꿈을_LF_로_맞춘다(self):
        text = ' 측정시 동심도 기준 충족\r\n1) 동심도   \r\n  > 샤프트 중심선 일치 여부\n'
        body = self.save(self.payload(rows=[[text, {'type': 'N', 'lower_limit': '1', 'upper_limit': '9'}]]))
        self.assertEqual((body['success'], body['revised']), (True, True))
        content = DigFormItem.objects.get(DigFormSection__DigForm_id=body['id'], RowType='D', ColumnIndex=1).Content
        self.assertEqual(content, '측정시 동심도 기준 충족\n1) 동심도\n  > 샤프트 중심선 일치 여부')

    def test_줄바꿈_표기만_다르면_새_버전이_아니다(self):
        from app.views.system.form_edit import build_inspection
        DigFormItem.objects.filter(DigFormSection=self.section).delete()
        rows = [['1) 동심도\n  > 샤프트', {'type': 'N', 'lower_limit': '1', 'upper_limit': '9'}]]
        items, _ = build_inspection(self.section, self.COLUMNS, rows)
        DigFormItem.objects.bulk_create(items)
        crlf = [['1) 동심도\r\n  > 샤프트  ', rows[0][1]]]
        self.assertEqual(self.save(self.payload(rows=crlf))['revised'], False)

    HEADER_CELLS = [{'row': 1, 'col': 1, 'content': '확인자', 'input_key': 'k9'},
                    {'row': 1, 'col': 2, 'bind': 'result.extra.k9', 'input': True, 'name': '확인자'}]

    def header_payload(self, cells=None, top_cells=None):
        data = self.payload()
        if top_cells is not None:
            data['top_cells'] = top_cells
        data['sections'].append({'id': None, 'type': 'HEADER', 'title': '확인', 'width': 12, 'height': None,
                                 'cells': self.HEADER_CELLS if cells is None else cells})
        return data

    def test_머리글에_작성일_칸이_없어도_저장한다(self):
        body = self.save(dict(self.payload(), top_cells=[]))
        self.assertEqual((body['success'], body['revised']), (True, False))

    def test_작성일_칸은_입력칸으로_저장하지_않는다(self):
        self.save(dict(self.payload(), top_cells=[{'row': 1, 'col': 1, 'bind': 'result.WriteDate', 'input': True}]))
        self.assertEqual(json.loads(DigForm.objects.get(id=self.form.id).FixedTopContent),
                         [{'row': 1, 'col': 1, 'bind': 'result.WriteDate'}])

    def test_작성자_칸도_입력칸으로_저장하지_않는다(self):
        self.save(dict(self.payload(), top_cells=[{'row': 1, 'col': 1, 'bind': 'result.Writer', 'input': True}]))
        self.assertEqual(json.loads(DigForm.objects.get(id=self.form.id).FixedTopContent),
                         [{'row': 1, 'col': 1, 'bind': 'result.Writer'}])

    def test_머리글_섹션은_칸_목록을_섹션_내용으로_저장하고_새_버전이_아니다(self):
        body = self.save(self.header_payload())
        self.assertEqual((body['success'], body['revised']), (True, False))
        section = DigFormSection.objects.get(DigForm_id=self.form.id, SectionType='HEADER')
        self.assertEqual((section.SortOrder, json.loads(section.Content)), (2, self.HEADER_CELLS))
        self.assertFalse(DigFormItem.objects.filter(DigFormSection=section).exists())

    def test_WO_입력칸은_머리글과_머리글_섹션을_통틀어_하나다(self):
        wo = {'row': 1, 'col': 1, 'bind': 'result.WorkOrderNumber', 'input': True}
        body = self.save(self.header_payload(cells=[dict(wo)], top_cells=[dict(wo)]))
        self.assertEqual(body, {'success': False, 'message': '머리글에 입고번호/WO 입력칸이 여러 개 있습니다. 하나만 남겨 주세요.'})
        self.assertFalse(DigFormSection.objects.filter(SectionType='HEADER').exists())

    def test_머리글_섹션_칸이_목록이_아니면_저장하지_않는다(self):
        body = self.save(self.header_payload(cells={'row': 1}))
        self.assertEqual(body, {'success': False, 'message': '머리글 형식이 올바르지 않습니다.'})

    def test_양식명_칸의_표시_글자는_앞뒤_공백을_지워_저장하고_다른_칸에서는_버린다(self):
        cells = [{'row': 1, 'col': 1, 'bind': 'form.Title', 'style': 'title', 'text': '  수입검사 성적서 '},
                 {'row': 1, 'col': 2, 'bind': 'form.Code', 'text': '코드'},
                 {'row': 1, 'col': 3, 'bind': 'form.Title', 'style': 'title', 'text': '  '}]
        body = self.save(self.header_payload(cells=[dict(c) for c in cells], top_cells=[dict(c) for c in cells]))
        self.assertTrue(body['success'])
        expected = [{'row': 1, 'col': 1, 'bind': 'form.Title', 'style': 'title', 'text': '수입검사 성적서'},
                    {'row': 1, 'col': 2, 'bind': 'form.Code'},
                    {'row': 1, 'col': 3, 'bind': 'form.Title', 'style': 'title'}]
        self.assertEqual(json.loads(DigForm.objects.get(id=self.form.id).FixedTopContent), expected)
        section = DigFormSection.objects.get(DigForm_id=self.form.id, SectionType='HEADER')
        self.assertEqual(json.loads(section.Content), expected)

    def test_양식명_칸의_표시_글자가_200자를_넘으면_저장하지_않는다(self):
        body = self.save(dict(self.payload(), top_cells=[{'row': 1, 'col': 1, 'bind': 'form.Title', 'text': '가' * 201}]))
        self.assertEqual(body, {'success': False, 'message': '머리글 제목은 200자 이하로 입력해 주세요.'})

    def test_양식명_칸의_표시_글자가_글자가_아니면_저장하지_않는다(self):
        body = self.save(dict(self.payload(), top_cells=[{'row': 1, 'col': 1, 'bind': 'form.Title', 'text': 12}]))
        self.assertEqual(body, {'success': False, 'message': '머리글 제목 형식이 올바르지 않습니다.'})


class SeedInitialDigFormTest(TestCase):
    def test_품질_검사양식_권한은_검사양식_관리로_옮기고_높은_권한을_남긴다(self):
        both = UserGroup.objects.create(Code='qc2', Name='품질2')
        UserGroupMenu.objects.create(UserGroup=both, MenuCode='wm_dig_form_outgoing_form', AuthCode='RW')
        UserGroupMenu.objects.create(UserGroup=both, MenuCode='wm_dig_form_incoming_form', AuthCode='R')
        only = UserGroup.objects.create(Code='qc3', Name='품질3')
        UserGroupMenu.objects.create(UserGroup=only, MenuCode='wm_dig_form_outgoing_form', AuthCode='R')
        call_command('seed_initial', stdout=io.StringIO())
        auth = dict(UserGroupMenu.objects.filter(MenuCode='wm_dig_form_incoming_form', UserGroup__in=[both, only])
                    .values_list('UserGroup__Code', 'AuthCode'))
        self.assertEqual(auth, {'qc2': 'RW', 'qc3': 'R'})
        self.assertFalse(UserGroupMenu.objects.filter(MenuCode='wm_dig_form_outgoing_form').exists())

    def test_디지털_양식_메뉴와_판정_코드를_등록한다(self):
        call_command('seed_initial', stdout=io.StringIO())
        call_command('seed_initial', stdout=io.StringIO())   # 멱등
        menus = {m.MenuCode: (m.MenuFolder.FolderName, m.MenuName)
                 for m in MenuItem.objects.filter(MenuCode__in=DIG_FORM_MENU_CODES).select_related('MenuFolder')}
        self.assertEqual(menus, {
            'wm_dig_form_incoming_form': ('검사 관리', '검사양식 관리'),
            'wm_dig_form_incoming_write': ('검사 작업', '수입검사 작성'),
            'wm_dig_form_incoming_result': ('검사 작업', '수입검사 결과'),
            'wm_dig_form_outgoing_write': ('검사 작업', '품질검사 작성'),
            'wm_dig_form_outgoing_result': ('검사 작업', '품질검사 결과'),
        })
        # 체크리스트양식관리 폴더는 검사양식으로 합쳐 내렸다(사용자 결정 2026-10-16)
        self.assertFalse(MenuItem.objects.filter(MenuCode__in=['wm_form_edit', 'wm_dig_form_view']).exists())
        self.assertFalse(MenuFolder.objects.filter(FolderName='체크리스트양식관리').exists())
        codes = list(SystemCode.objects.filter(CodeType__startswith='dig_form')
                     .order_by('CodeType', '_ordering').values_list('CodeType', 'Code', 'Value'))
        self.assertEqual(codes, [('dig_form_okng', 'Y', 'OK'), ('dig_form_okng', 'N', 'NG'),
                                 ('dig_form_pass_na', 'Y', '합격'), ('dig_form_pass_na', 'N', '불합격'),
                                 ('dig_form_pass_na', 'X', 'N/A')])
        self.assertEqual(UserGroupMenu.objects.filter(UserGroup__Code='admin', MenuCode='wm_dig_form_incoming_form')
                         .values_list('AuthCode', flat=True).get(), 'RW')
        judge = MenuItem.objects.select_related('MenuFolder').get(MenuCode='wm_dig_form_judge_code')
        self.assertEqual((judge.MenuFolder.FolderName, judge.MenuName), ('검사 관리', '검사양식 코드 관리'))
        # 입고 조회는 기준정보 > 입고 내역으로 내렸다 — 코드는 그대로(설계 2026-10-21 §6)
        receipt = MenuItem.objects.select_related('MenuFolder').get(MenuCode='wm_receipt')
        self.assertEqual((receipt.MenuFolder.FolderName, receipt.MenuName), ('기준정보', '입고 내역'))
        # 전체 폴더·메뉴 순서는 tests.test_menu_tree.SeedMenuTreeTest 가 본다
        # 수입검사·품질검사 폴더는 검사 작업·검사 관리로 나눠 내렸다(사용자 결정 2026-10-19)
        self.assertFalse(MenuFolder.objects.filter(FolderName__in=['수입검사', '품질검사']).exists())


def judge_options():
    """(그룹 코드, 결과 코드, 이름, 판정 의미) — 그룹·결과 코드 순서대로."""
    return [(o.Parent.Code, o.Code, o.Value, o.Type)
            for o in UserCode.objects.filter(Parent__Parent__Code=judge_code.ROOT_CODE)
            .select_related('Parent').order_by('Parent___order', '_order')]


class JudgeCodeSeedTest(TestCase):
    def test_항목결과_코드를_넣고_다시_돌려도_늘지_않는다(self):
        call_command('seed_initial', stdout=io.StringIO())
        call_command('seed_initial', stdout=io.StringIO())
        self.assertEqual(UserCode.objects.filter(Code=judge_code.ROOT_CODE, Parent=None).count(), 1)
        self.assertEqual(judge_options(), [
            ('dig_form_okng', 'Y', 'OK', 'Y'), ('dig_form_okng', 'N', 'NG', 'N'),
            ('dig_form_pass_na', 'Y', '합격', 'Y'), ('dig_form_pass_na', 'N', '불합격', 'N'),
            ('dig_form_pass_na', 'X', 'N/A', 'X'),
            ('dig_form_fit', 'Y', '적합', 'Y'), ('dig_form_fit', 'N', '부적합', 'N'),
            ('dig_form_usable', 'Y', '사용 가능', 'Y'), ('dig_form_usable', 'N', '사용 불가', 'N'),
            ('dig_form_receipt', 'Y', '입고 완료', 'Y'), ('dig_form_receipt', 'N', '미입고', 'N'),
        ])

    def test_화면에서_고친_이름과_의미는_다시_돌려도_덮지_않는다(self):
        judge_code.ensure_defaults()
        UserCode.objects.filter(Parent__Code='dig_form_okng', Code='Y').update(Value='양호', Type='X')
        self.assertEqual(judge_code.ensure_defaults(), 0)
        self.assertEqual(UserCode.objects.filter(Parent__Code='dig_form_okng', Code='Y')
                         .values_list('Value', 'Type').get(), ('양호', 'X'))


class JudgeCodeApiTest(TestCase):
    URL = '/api/dig_form/judge_code'

    def setUp(self):
        judge_code.ensure_defaults()
        self.root = judge_code.root()
        self.okng = UserCode.objects.get(Parent=self.root, Code='dig_form_okng')
        self.group = UserGroup.objects.create(Code='qc', Name='품질')
        self.user = User.objects.create_user('coder', password='x')
        self.user.userprofile.UserGroup = self.group
        self.user.userprofile.save()
        self.client.force_login(self.user)

    def grant(self, code, auth):
        UserGroupMenu.objects.create(UserGroup=self.group, MenuCode=code, AuthCode=auth)

    def post(self, action, **data):
        return self.client.post(f'{self.URL}?action={action}', data)

    def test_트리는_그룹_순서대로_그룹_바로_아래에_결과_코드를_둔다(self):
        self.grant('wm_dig_form_judge_code', 'R')
        UserCode.objects.filter(Parent=self.okng, Code='N').update(_order=0)   # 순서를 바꾸면 그대로 따른다
        rows = self.client.get(self.URL, {'action': 'read'}).json()
        self.assertEqual([(r['parent_id'] is None, r['code'], r['name'], r['meaning']) for r in rows[:6]], [
            (True, 'dig_form_okng', 'OK / NG', None), (False, 'N', 'NG', 'N'), (False, 'Y', 'OK', 'Y'),
            (True, 'dig_form_pass_na', '합격 / 불합격 / N/A', None), (False, 'Y', '합격', 'Y'), (False, 'N', '불합격', 'N')])
        self.assertEqual({r['parent_id'] for r in rows[1:3]}, {self.okng.id})
        self.assertEqual(len(rows), 16)   # 그룹 5 + 결과 코드 11

    def test_결과_코드를_추가하려면_판정_의미가_있어야_한다(self):
        self.grant('wm_dig_form_judge_code', 'RW')
        body = self.post('save', parent_id=self.okng.id, code='G', name='양호').json()
        self.assertEqual(body, {'success': False, 'message': '판정 의미를 선택하세요.'})
        body = self.post('save', parent_id=self.okng.id, code='G', name='양호', meaning='Y', sort_order='3').json()
        self.assertTrue(body['success'])
        self.assertEqual(UserCode.objects.filter(id=body['id']).values_list('Parent_id', 'Type', '_order').get(),
                         (self.okng.id, 'Y', 3))

    def test_저장은_GET_이나_조회_권한으로는_막는다(self):
        self.grant('wm_dig_form_judge_code', 'R')
        get = self.client.get(self.URL, {'action': 'save', 'code': 'dig_form_x', 'name': 'X'})
        self.assertEqual((get.status_code, self.post('save', code='dig_form_x', name='X').status_code), (403, 403))
        self.assertFalse(UserCode.objects.filter(Code='dig_form_x').exists())

    def test_양식이_쓰는_그룹은_코드를_바꾸거나_지울_수_없다(self):
        self.grant('wm_dig_form_judge_code', 'RW')
        _form, section, _items = make_form(input_types=())
        DigFormItem.objects.create(DigFormSection=section, RowType='D', RowIndex=3, ColumnIndex=1,
                                   InputYN='Y', ResultType='S', CodeGroup='dig_form_okng')
        body = self.post('save', id=self.okng.id, code='dig_form_ok', name='OK / NG').json()
        self.assertEqual(body['message'], '사용 중인 코드는 코드값을 바꿀 수 없습니다.')
        self.assertEqual(self.post('delete', id=self.okng.id).json()['message'], '양식에서 쓰는 그룹은 삭제할 수 없습니다.')
        self.assertTrue(self.post('save', id=self.okng.id, code='dig_form_okng', name='합 / 불').json()['success'])

    def test_작성_결과가_쓴_결과_코드는_지울_수_없다(self):
        self.grant('wm_dig_form_judge_code', 'RW')
        form, section, _items = make_form(input_types=())
        cell = DigFormItem.objects.create(DigFormSection=section, RowType='D', RowIndex=3, ColumnIndex=1,
                                          InputYN='Y', ResultType='S', CodeGroup='dig_form_okng')
        result = DigFormResult.objects.create(DigForm=form, WriteDate='2026-10-16')
        DigFormItemResult.objects.create(DigFormResult=result, DigFormItem=cell, ComboResult='N')
        ng = UserCode.objects.get(Parent=self.okng, Code='N')
        self.assertEqual(self.post('delete', id=ng.id).json()['message'], '작성 결과에 쓰인 결과 코드는 삭제할 수 없습니다.')
        self.assertTrue(self.post('delete', id=UserCode.objects.get(Parent=self.okng, Code='Y').id).json()['success'])

    def test_묶음_밖의_사용자코드는_다루지_않는다(self):
        self.grant('wm_dig_form_judge_code', 'RW')
        other = UserCode.objects.create(Code='other', Value='다른 코드')
        self.assertEqual(self.post('delete', id=other.id).json()['message'], '항목결과 코드를 찾을 수 없습니다.')
        self.assertTrue(UserCode.objects.filter(id=other.id).exists())

    def test_이_메뉴_권한만으로는_양식_조회가_열리지_않는다(self):
        self.grant('wm_dig_form_judge_code', 'RW')
        self.assertEqual(self.client.get('/api/dig_form/dig_form', {'action': 'form_list'}).status_code, 403)


class DigFormJudgeMeaningTest(TestCase):
    """작성·조회 API 가 판정 선택지를 항목결과 코드(사용자코드)에서 판정 의미와 함께 읽는다."""

    def setUp(self):
        judge_code.ensure_defaults()
        group = UserGroup.objects.create(Code='qc', Name='품질')
        UserGroupMenu.objects.create(UserGroup=group, MenuCode='wm_dig_form_outgoing_result', AuthCode='R')
        user = User.objects.create_user('reader', password='x')
        user.userprofile.UserGroup = group
        user.userprofile.save()
        self.client.force_login(user)

    def test_작성_결과_값에_선택지_이름과_판정_의미가_붙는다(self):
        form, section, _items = make_form(input_types=())
        cell = DigFormItem.objects.create(DigFormSection=section, RowType='D', RowIndex=3, ColumnIndex=1,
                                          InputYN='Y', ResultType='S', CodeGroup='dig_form_pass_na')
        result = DigFormResult.objects.create(DigForm=form, WriteDate='2026-10-16')
        DigFormItemResult.objects.create(DigFormResult=result, DigFormItem=cell, ComboResult='X')
        rows = self.client.get('/api/dig_form/dig_form', {'action': 'result_values', 'result_id': result.id}).json()
        self.assertEqual([(r['combo_result'], r['combo_value'], r['combo_meaning']) for r in rows], [('X', 'N/A', 'X')])

    def test_판정_선택지_그룹_목록(self):
        sets = self.client.get('/api/dig_form/dig_form', {'action': 'judge_sets'}).json()
        self.assertEqual([s['code'] for s in sets],
                         ['dig_form_okng', 'dig_form_pass_na', 'dig_form_fit', 'dig_form_usable', 'dig_form_receipt'])
        self.assertEqual(sets[0]['options'], [{'code': 'Y', 'value': 'OK', 'meaning': 'Y'},
                                              {'code': 'N', 'value': 'NG', 'meaning': 'N'}])

    def test_수입_품질_메뉴는_같은_화면을_구분만_바꿔_쓰고_이름에_구분을_붙인다(self):   # 수입검사 작성·품질검사 결과
        # 검사양식 관리는 구분 없이 하나다(사용자 결정 2026-10-21) — 코드는 수입 검사양식 관리 시절 그대로
        gui = GUIConfiguration.get_gui_info('wm_dig_form_incoming_form')
        self.assertEqual((gui['name'], gui['templates']['default'], gui['params']), ('검사양식 관리', 'system/form_edit.html', {}))
        self.assertIsNone(GUIConfiguration.get_gui_info('wm_dig_form_outgoing_form'))
        for form_type, prefix in (('INCOMING', '수입'), ('OUTGOING', '품질')):
            for kind, name, template in (('write', '작성', 'dig_form/dig_form_write.html'),
                                         ('result', '결과', 'dig_form/dig_form_result.html')):
                gui = GUIConfiguration.get_gui_info('wm_dig_form_{}_{}'.format(form_type.lower(), kind))
                self.assertEqual((gui['name'], gui['templates']['default'], gui['params'], gui['tab_title']),
                                 (prefix + '검사 ' + name, template, {'form_type': form_type}, prefix + '검사 ' + name))
        self.assertIsNone(GUIConfiguration.get_gui_info('wm_form_edit'))
        self.assertIsNone(GUIConfiguration.get_gui_info('wm_dig_form_view'))


class UserGroupDisabledCheckboxTest(TestCase):
    def test_사용자그룹_화면에_사용_토글이_있고_저장은_disabled_를_보낸다(self):
        """저장 때 disabled 가 빠지면 usergroup.py 가 Disabled=True(미사용)로 저장한다 — 화면이 사용 토글로 값을 만들어 보낸다."""
        admin = User.objects.create_user('root', password='x', is_superuser=True)
        self.client.force_login(admin)
        html = self.client.get('/gui/wm_user_group/').content.decode()
        self.assertIn('id="active"', html)
        self.assertIn('id="createActive"', html)
        self.assertEqual(html.count("disabled: $('#active').is(':checked')"), 1)
        self.assertEqual(html.count("data.disabled = $('#createActive').is(':checked')"), 1)


class DigFormCaptureRenderTest(TestCase):
    def test_작성_화면에_공용_CameraCapture_와_DigFormCapture_가_한_번씩_들어간다(self):
        admin = User.objects.create_user('root', password='x', is_superuser=True)
        self.client.force_login(admin)
        response = self.client.get('/gui/wm_dig_form_incoming_write/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertEqual(html.count('class CameraCapture'), 1)
        self.assertEqual(html.count('class DigFormCapture'), 1)


class PreprocessEditorRenderTest(TestCase):
    def test_데이터_목록에_공용_PreprocessEditor_와_편집_창이_한_번씩_들어간다(self):
        admin = User.objects.create_user('root', password='x', is_superuser=True)
        self.client.force_login(admin)
        response = self.client.get('/gui/wm_data_image/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertEqual(html.count('class PreprocessEditor'), 1)
        self.assertEqual(html.count('id="preprocessModal"'), 1)


class DataRegisterRenderTest(TestCase):
    def test_비전_데이터_등록_화면에_등록_모달과_상세와_공용_부품이_들어간다(self):
        admin = User.objects.create_user('root', password='x', is_superuser=True)
        self.client.force_login(admin)
        response = self.client.get('/gui/wm_data_register/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for element_id in ('btnRegister', 'registerModal', 'registerItem', 'registerKindCamera', 'registerKindFile',
                           'registerFiles', 'registerSubmit', 'detailTable', 'btnPreprocess', 'btnDelete'):
            self.assertIn(f'id="{element_id}"', html)
        self.assertEqual(html.count('class CameraCapture'), 1)
        self.assertEqual(html.count('class PreprocessEditor'), 1)
        # 이미지 편집 창의 크기(.preprocess-*)는 preview.css 에 있다 — 빠지면 이미지가 원본 크기로 나와 창이 세로로 길어진다
        self.assertRegex(html, r'<link rel="stylesheet" href="[^"]*data/preview[^"]*\.css">')


class ExportDigFormTest(TestCase):
    def source(self):
        return export_source()

    def test_고객_양식은_id_결과_작성자_없이_섹션_칸_구조로_뽑는다(self):
        data = self.source()
        data['dig_form_section'][0].update(SectionType='INSPECTION', Content=None)
        data['dig_form_item'][0]['DigFormWorkClass_id'] = 3
        data['dig_form_work_class'] = [{'id': 3, 'Class1Name': '조립', 'Class2Name': None, 'Class3Name': None,
                                        'Description': None, '_status': None, '_created': None, '_modified': None,
                                        '_creater_id': None, '_modifier_id': None}]
        out, files, dropped = export_forms(data, [('DF0011', 1)])
        form = out['forms'][0]
        self.assertEqual((out['format'], form['Code'], form['Title']), ('dig-form-forms/v3', 'DF0011', 'FLOW'))
        self.assertNotIn('id', form)
        self.assertNotIn('_creater_id', form)
        item = form['sections'][0]['items'][0]
        self.assertEqual((item['RowIndex'], item['work_class']), (2, 3))
        self.assertNotIn('DigFormSection_id', item)
        self.assertEqual(out['work_classes'], {'3': {'Class1Name': '조립', 'Class2Name': None,
                                                     'Class3Name': None, 'Description': None}})
        self.assertEqual((files, dropped), ({}, []))

    def test_비전검사항목은_코드로_매핑한_중분류는_이름으로_뽑는다(self):
        # id 는 환경마다 다르다 — seed_dig_form 이 코드·이름으로 다시 찾는다(사용자 결정 2026-10-22)
        data = self.source()
        data['dig_form_section'][0].update(SectionType='INSPECTION', Content=None)
        data['dig_form_item'][0]['VisionItem_id'] = 7
        data.update(vision_codes={7: 'TAB-IMK'}, categories={'DF0011': 'Module Check Sheet'})
        form = export_forms(data, [('DF0011', 1)])[0]['forms'][0]
        item = form['sections'][0]['items'][0]
        self.assertEqual((item['vision_item'], form['category']), ('TAB-IMK', 'Module Check Sheet'))
        self.assertNotIn('VisionItem_id', item)

    def test_참고사진은_파일과_함께_뽑고_파일이_없으면_뺀다(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        photo = Path(folder) / 'a.png'
        photo.write_bytes(b'png')
        data = self.source()
        data['attach_file'] = [{'id': 11, 'FileName': 'a.png', 'ExtName': 'png', 'path': str(photo)}]
        out, files, dropped = export_forms(data, [('DF0011', 1)])
        self.assertEqual(out['forms'][0]['sections'][0]['Content'], '<p><img src="{{dig_form_image:DF0011-v1-11.png}}"></p>')
        self.assertEqual((out['images'], files, dropped),
                         ({'DF0011-v1-11.png': {'FileName': 'a.png', 'ExtName': 'png'}}, {'DF0011-v1-11.png': str(photo)}, []))
        photo.unlink()
        out, files, dropped = export_forms(data, [('DF0011', 1)])
        self.assertEqual((out['forms'][0]['sections'][0]['Content'], files, dropped), ('<p></p>', {}, ['DF0011 v1 참고사진 11']))

    def test_고정_이미지_칸은_그림을_뽑고_파일이_없으면_빼며_글자_칸은_그대로다(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        picture = Path(folder) / 'r.jpg'
        picture.write_bytes(b'jpg')
        data = self.source()
        data['dig_form_section'][0].update(SectionType='INSPECTION', Content=None)
        data['dig_form_item'][0].update(ResultType='R', Content='5')
        data['dig_form_item'].append(dict(data['dig_form_item'][0], id=501, ColumnIndex=2, Content='사진'))
        data['ref_file'] = [{'id': 5, 'FileName': 'r.jpg', 'ExtName': 'jpg', 'path': str(picture)}]
        out, files, dropped = export_forms(data, [('DF0011', 1)])
        cells = [i['Content'] for i in out['forms'][0]['sections'][0]['items']]
        self.assertEqual(cells, ['{{dig_form_image:DF0011-v1-ref-5.jpg}}', '사진'])
        self.assertEqual((out['ref_images'], files, dropped),
                         ({'DF0011-v1-ref-5.jpg': {'FileName': 'r.jpg', 'ExtName': 'jpg'}}, {'DF0011-v1-ref-5.jpg': str(picture)}, []))
        picture.unlink()
        out, files, dropped = export_forms(data, [('DF0011', 1)])
        self.assertEqual(([i['Content'] for i in out['forms'][0]['sections'][0]['items']], dropped),
                         (['', '사진'], ['DF0011 v1 고정 이미지 5']))

    def test_없는_양식은_뽑지_않는다(self):
        with self.assertRaisesMessage(CommandError, 'DF0099'):
            export_forms(self.source(), [('DF0099', 1)])

    def test_중분류에_매핑된_양식과_고른_코드의_최신_버전을_고른다(self):
        data = self.source()
        data['dig_form'].append(dict(data['dig_form'][0], id=32, Version=2))
        data['dig_form'].append(dict(data['dig_form'][0], id=33, Code='DF0012', Version=3))
        data['categories'] = {'DF0011': 'Module Check Sheet'}
        self.assertEqual(latest_forms(data, []), [('DF0011', 2)])
        self.assertEqual(latest_forms(data, ['DF0012']), [('DF0011', 2), ('DF0012', 3)])
        with self.assertRaisesMessage(CommandError, 'DF0013'):
            latest_forms(data, ['DF0012', 'DF0013'])
        data['categories']['DF0098'] = '8계통 Check Sheet'
        with self.assertRaisesMessage(CommandError, 'DF0098'):
            latest_forms(data, [])

    def test_양식코드_범위를_펼친다(self):
        self.assertEqual(code_list('DF0012-DF0014, DF0020'), ['DF0012', 'DF0013', 'DF0014', 'DF0020'])
        self.assertEqual(code_list(''), [])

    def test_명령은_seed_한_양식을_같은_데이터로_다시_뽑는다(self):
        reset_tenant_cache()
        call_command('seed_vision_items', stdout=io.StringIO())
        call_command('seed_dig_form', stdout=io.StringIO())
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        out = Path(folder) / 'forms.json'
        call_command('export_dig_form', str(out), stdout=io.StringIO())
        exported = json.loads(out.read_text(encoding='utf-8'))
        fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))

        def shape(data):
            return sorted((f['Code'], f['Version'], f['category'], [len(s['items']) for s in f['sections']],
                           sorted(i['vision_item'] or '' for s in f['sections'] for i in s['items']))
                          for f in data['forms'])
        self.assertEqual(shape(exported), shape(fixture))
        self.assertEqual(len(exported['images']), len(fixture['images']))
        for name in exported['images']:
            self.assertTrue((Path(folder) / 'dig_form_images' / name).is_file(), name)


def export_source():
    """export_forms 가 받는 모양의 작은 원본 — 양식 1·사진 섹션 1·칸 1."""
    audit = {'_status': None, '_created': '2026-10-12T10:00:00+09:00', '_modified': None,
             '_creater_id': 1, '_modifier_id': 1}
    return {
        'dig_form': [{'id': 31, 'Code': 'DF0011', 'Version': 1, 'Title': 'FLOW', 'LayoutType': 'SECTION',
                      'UseYN': 'Y', **audit}],
        'dig_form_work_class': [],
        'dig_form_section': [{'id': 93, 'DigForm_id': 31, 'SectionType': 'PHOTO', 'SortOrder': 0,
                              'HeaderRowCount': 1, 'WorkerColumnYN': 'Y',
                              'Content': '<p><img src="/media/dig-form-image/11/"></p>', **audit}],
        'dig_form_item': [{'id': 500, 'DigFormSection_id': 93, 'RowType': 'D', 'RowIndex': 2, 'ColumnIndex': 1,
                           'RowSpan': 1, 'ColSpan': 1, 'InputYN': 'Y', 'ResultType': 'T', **audit}],
    }


class SeedDigFormTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def test_고객_양식을_넣고_다시_돌려도_늘지_않는다(self):
        call_command('seed_vision_items', stdout=io.StringIO())
        call_command('seed_dig_form', stdout=io.StringIO())
        call_command('seed_dig_form', stdout=io.StringIO())
        self.assertEqual(sorted(DigForm.objects.values_list('Code', 'Version')),
                         sorted((f['Code'], f['Version']) for f in self.fixture['forms']))
        expected = sum(len(s['items']) for f in self.fixture['forms'] for s in f['sections'])
        self.assertEqual(DigFormItem.objects.count(), expected)
        self.assertEqual(AttachFile.objects.filter(TableName='dig_form_section').count(), len(self.fixture['images']))
        # 고정 이미지 칸은 새 첨부(dig_form_item/ref)로 잇고 칸 값이 그 첨부 id 다
        refs = AttachFile.objects.filter(TableName='dig_form_item', AttachName='ref')
        self.assertEqual(refs.count(), len(self.fixture['ref_images']))
        for ref in refs:
            self.assertEqual(DigFormItem.objects.get(id=ref.DataPk).Content, str(ref.id))
        self.assertFalse(DigFormResult.objects.exists())

    def test_비전검사항목을_코드로_잇고_중분류에_매핑하고_참고사진을_넣는다(self):
        call_command('seed_vision_items', stdout=io.StringIO())
        call_command('seed_dig_form', stdout=io.StringIO())
        with tenant_atomic():
            codes = dict(InspectionItem.objects.values_list('id', 'code'))
            mapping = dict(InspectionCategory.objects.exclude(form_code='').values_list('name', 'form_code'))
        linked = sorted(codes[i] for i in DigFormItem.objects.exclude(VisionItem=None).values_list('VisionItem_id', flat=True))
        self.assertEqual(linked, sorted(i['vision_item'] for f in self.fixture['forms'] for s in f['sections']
                                        for i in s['items'] if i['vision_item']))
        # 매핑이 없는 양식(category '')은 중분류에 잇지 않는다
        self.assertEqual(mapping, {f['category']: f['Code'] for f in self.fixture['forms'] if f['category']})
        for section in DigFormSection.objects.exclude(Content=None).exclude(Content=''):
            self.assertNotIn('dig_form_image:', section.Content)
        for attach in AttachFile.objects.filter(TableName='dig_form_section'):
            self.assertIn(image_url(attach.id), DigFormSection.objects.get(id=attach.DataPk).Content)
            self.assertTrue(image_path(attach).is_file())

    def test_비전검사항목이_없으면_잇지_않고_알린다(self):
        out = io.StringIO()
        call_command('seed_dig_form', stdout=out)
        self.assertIn('seed_vision_items 를 먼저', out.getvalue())
        self.assertFalse(DigFormItem.objects.exclude(VisionItem=None).exists())

    def test_작업분류는_같은_이름이면_다시_만들지_않는다(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        fixture = Path(folder) / 'forms.json'
        fixture.write_text(json.dumps({
            'work_classes': {'3': {'Class1Name': '조립', 'Class2Name': None, 'Class3Name': None, 'Description': None}},
            'images': {},
            'forms': [{'Code': 'DF0900', 'Version': 1, 'Title': '작업분류', 'LayoutType': 'SECTION', 'FormType': 'OUTGOING',
                       'UseYN': 'Y', 'category': '', 'sections': [
                           {'SectionType': 'INSPECTION', 'SortOrder': 1, 'HeaderRowCount': 1, 'WorkerColumnYN': 'Y', 'items': [
                               {'RowType': 'D', 'RowIndex': 2, 'ColumnIndex': 1, 'RowSpan': 1, 'ColSpan': 1, 'InputYN': 'N',
                                'work_class': 3, 'vision_item': None}]}]}]}), encoding='utf-8')
        with mock.patch('domain.management.commands.seed_dig_form.FIXTURE', fixture):
            call_command('seed_dig_form', stdout=io.StringIO())
            # 외래키가 PROTECT 라 지우지 않고 코드를 바꿔 같은 양식을 다시 넣게 한다
            DigForm.objects.filter(Code='DF0900').update(Code='DF0900X')
            call_command('seed_dig_form', stdout=io.StringIO())
        self.assertTrue(DigForm.objects.filter(Code='DF0900').exists())
        self.assertEqual(DigFormWorkClass.objects.count(), 1)
