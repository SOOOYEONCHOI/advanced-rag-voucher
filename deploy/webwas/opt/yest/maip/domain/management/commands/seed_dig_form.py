"""고객 양식(디지털 양식) 기본 데이터를 넣는다. 운영 서버에서도 돈다. 멱등이다. `seed_vision_items` 다음에 돌린다.

    python manage.py seed_dig_form

데이터는 `samples/dig_form_forms.json` 과 그림 `samples/dig_form_images/`(`export_dig_form` 으로 뽑는다)다 —
검사 분류에 매핑된 양식과 완성된 고객 양식 DF0012~DF0026 의 최신 버전(사용자 결정 2026-10-22·2026-10-23).
참고사진(섹션 본문)과 고정 이미지 칸 그림은 파일을 MEDIA_ROOT 로 복사해 새 첨부로 잇는다.
같은 (양식코드, 버전)이 이미 있으면 건너뛴다 — 운영에서 고친 양식을 덮지 않는다.
작업분류(dig_form_work_class)는 대·중·소 분류명이 같으면 있는 것을 쓴다.
이미지 칸의 비전검사항목은 코드로 잇고, 양식을 매핑할 중분류는 이름으로 찾는다(그 구분의 대분류 아래, 매핑이 비어 있을 때만).
둘 다 `seed_vision_items` 가 만든다 — 없으면 잇지 않고 알린다.
"""
import json
import re
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from domain.models.data import InspectionCategory, InspectionItem
from domain.models.dig_form import DigForm, DigFormItem, DigFormSection, DigFormWorkClass
from domain.models.system import AttachFile
from domain.services.data import category as categories
from domain.services.dig_form_image import FOLDERS, IMAGE_ATTACH, IMAGE_TABLE, REF_ATTACH, REF_TABLE, image_url
from domain.tenancy import current_tenant, tenant_atomic

FIXTURE = Path(__file__).resolve().parents[1] / 'samples' / 'dig_form_forms.json'
IMAGES = FIXTURE.parent / 'dig_form_images'
IMAGE_TOKEN = re.compile(r'\{\{dig_form_image:([^}]+)\}\}')


def attach_copy(name, meta, table, attach_name, data_pk):
    """그림 파일 하나를 MEDIA_ROOT 로 복사하고 그 첨부 행을 만든다"""
    folder_name = FOLDERS[(table, attach_name)]
    folder = Path(settings.MEDIA_ROOT) / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    physic = f"{uuid.uuid4().hex}.{meta['ExtName']}"
    shutil.copyfile(IMAGES / name, folder / physic)
    return AttachFile.objects.create(
        TableName=table, DataPk=data_pk, AttachName=attach_name, FileIndex=0, FileName=meta['FileName'],
        PhysicFileName=physic, ExtName=meta['ExtName'], FilePath=folder_name, FileSize=(folder / physic).stat().st_size)


def add_photos(section, data):
    """본문의 참고사진 자리를 이 섹션의 첨부로 만들고 주소를 넣는다"""
    def photo(match):
        attach = attach_copy(match.group(1), data['images'][match.group(1)], IMAGE_TABLE, IMAGE_ATTACH, section.id)
        return image_url(attach.id)

    section.Content = IMAGE_TOKEN.sub(photo, section.Content)
    section.save(update_fields=['Content'])


def add_ref_images(cells, data):
    """고정 이미지 칸의 그림 자리를 이 칸의 첨부로 만들고 칸 값을 그 첨부 id 로 바꾼다(dig_form_image.link_ref_images 와 같은 모양)"""
    for cell in cells:
        match = IMAGE_TOKEN.fullmatch(cell.Content or '') if cell.ResultType == 'R' else None
        if match:
            attach = attach_copy(match.group(1), data['ref_images'][match.group(1)], REF_TABLE, REF_ATTACH, cell.id)
            cell.Content = str(attach.id)
            cell.save(update_fields=['Content'])


class Command(BaseCommand):
    help = '고객 양식(디지털 양식) 기본 데이터를 넣습니다(멱등). seed_vision_items 다음에 돌립니다.'

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads(FIXTURE.read_text(encoding='utf-8'))
        tenant = current_tenant()
        with tenant_atomic(tenant):
            items = dict(InspectionItem.objects.for_tenant(tenant).values_list('code', 'id'))
        classes = {}

        def work_class(key):
            if key is None:
                return None
            if key not in classes:
                row = data['work_classes'][str(key)]
                classes[key] = (DigFormWorkClass.objects.filter(
                    Class1Name=row['Class1Name'], Class2Name=row['Class2Name'], Class3Name=row['Class3Name']).first()
                    or DigFormWorkClass.objects.create(**row))
            return classes[key]

        created, skipped, unlinked = [], [], set()
        for form in data['forms']:
            form = dict(form)
            sections = form.pop('sections')
            form.pop('category', None)
            label = f"{form['Code']} v{form['Version']}"
            if DigForm.objects.filter(Code=form['Code'], Version=form['Version']).exists():
                skipped.append(label)
                continue
            digform = DigForm.objects.create(**form)
            for section in sections:
                section = dict(section)
                cells = [dict(i) for i in section.pop('items')]
                row = DigFormSection.objects.create(DigForm=digform, **section)
                if IMAGE_TOKEN.search(row.Content or ''):
                    add_photos(row, data)
                for cell in cells:
                    code = cell.pop('vision_item', None)
                    if code and code not in items:
                        unlinked.add(code)
                    cell['VisionItem_id'] = items.get(code)
                add_ref_images(DigFormItem.objects.bulk_create([
                    DigFormItem(DigFormSection=row, DigFormWorkClass=work_class(cell.pop('work_class')), **cell)
                    for cell in cells]), data)
            created.append(label)

        mapped, unmapped = self.map_categories(tenant, data['forms'])

        if connection.vendor == 'postgresql':
            # 양식 편집이 새로 매기는 코드(DF + 4자리)가 기본 양식 코드와 겹치지 않게 한다.
            top = max((int(f['Code'][2:]) for f in data['forms'] if re.fullmatch(r'DF\d{4}', f['Code'])), default=1)
            with connection.cursor() as cur:
                cur.execute("select setval('dig_form_code_seq', greatest(%s, "
                            "(select case when is_called then last_value else 0 end from dig_form_code_seq)))", [top])
        self.stdout.write(self.style.SUCCESS(
            f"고객 양식 {len(created)}개 추가, {len(skipped)}개는 이미 있음"
            + (f" ({', '.join(skipped)})" if skipped else '') + f' / 중분류 매핑 {mapped}건'))
        if unlinked or unmapped:
            self.stdout.write(self.style.WARNING(
                '비전검사항목·중분류가 없어 잇지 못했습니다 — seed_vision_items 를 먼저 돌립니다: '
                + ', '.join(sorted(unlinked) + sorted(unmapped))))

    @staticmethod
    def map_categories(tenant, forms):
        """양식마다 이름이 같은 중분류(그 구분의 대분류 아래)에 매핑한다. 이미 매핑된 중분류·양식은 그대로 둔다"""
        mapped, unmapped = 0, []
        with tenant_atomic(tenant):
            for form in forms:
                if not form.get('category'):
                    continue
                minor = InspectionCategory.objects.for_tenant(tenant).filter(
                    name=form['category'], parent__form_type=form['FormType']).first()
                if minor is None:
                    unmapped.append(form['category'])
                    continue
                taken = InspectionCategory.objects.for_tenant(tenant).filter(form_code=form['Code']).exists()
                if minor.form_code or taken:
                    continue
                try:
                    categories.save_minor(tenant, category_id=minor.id, parent_id=minor.parent_id, name=minor.name,
                                          form_code=form['Code'], sort_order=minor.sort_order, description=minor.description)
                    mapped += 1
                except ValueError:
                    unmapped.append(form['category'])
        return mapped, unmapped
