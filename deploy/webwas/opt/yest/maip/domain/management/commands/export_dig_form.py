"""이 서버 DB(공유 개발 DB)의 고객 양식을 seed_dig_form 데이터 파일로 뽑는다. 담당자가 돌린다.

    python manage.py export_dig_form domain/management/samples/dig_form_forms.json

- DB 는 읽기만 한다. 뽑은 파일과 참고사진 폴더(`dig_form_images/`, 파일 옆)를 커밋하면 seed_dig_form 이 운영에 넣는다
- 고르는 양식은 **검사 분류(중분류)에 매핑된 양식과 `--codes`(기본 DF0012~DF0026, 완성된 고객 양식)의 최신 버전**이다
  (사용자 결정 2026-10-22·2026-10-23). 양식 정의(섹션·칸·작업분류)만 뽑고 id·작성자·작성 결과는 뺀다
- 이미지 칸의 비전검사항목 연결은 항목 코드로, 매핑한 중분류는 이름으로 뽑는다 — id 는 환경마다 다르다
- 참고사진·고정 이미지 칸 그림은 파일을 함께 뽑는다(seed_dig_form 이 새 첨부로 잇는다). 파일이 이 서버에 없는 그림은 빼고 알린다.
  머리글에 사진이 든 양식은 거절한다
"""
import json
import re
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from domain.models.data import InspectionCategory, InspectionItem
from domain.models.dig_form import DigForm, DigFormItem, DigFormSection, DigFormWorkClass
from domain.models.system import AttachFile
from domain.services.dig_form_image import IMAGE_ATTACH, IMAGE_TABLE, IMG_TAG, REF_ATTACH, REF_TABLE, image_path
from domain.tenancy import current_tenant, tenant_atomic

DROP = {'id', '_status', '_created', '_modified', '_creater_id', '_modifier_id'}
IMAGE_FOLDER = 'dig_form_images'
# 완성된 고객 양식 — 빠진 번호 없이 모두 기본 데이터다(사용자 결정 2026-10-23)
DEFAULT_CODES = 'DF0012-DF0026'
IMG_WITH_URL = re.compile(r'<img\b[^>]*/media/dig-form-image/(\d+)/[^>]*>', re.IGNORECASE)


def image_token(name):
    """본문의 참고사진 자리 — seed_dig_form 이 새 첨부 주소로 바꾼다"""
    return '{{dig_form_image:%s}}' % name


def read():
    """양식 표 4개와 참고사진 첨부·비전검사항목 코드·중분류 매핑을 읽는다 — 양식 표의 키는 칼럼 이름(외래키는 `<필드>_id`)이다."""
    data = {model._meta.db_table: list(model.objects.order_by('id').values())
            for model in (DigForm, DigFormWorkClass, DigFormSection, DigFormItem)}
    def files(table, attach):
        return [{'id': a.id, 'FileName': a.FileName, 'ExtName': a.ExtName, 'path': str(image_path(a))}
                for a in AttachFile.objects.filter(TableName=table, AttachName=attach)]
    data['attach_file'] = files(IMAGE_TABLE, IMAGE_ATTACH)
    data['ref_file'] = files(REF_TABLE, REF_ATTACH)
    tenant = current_tenant()
    with tenant_atomic(tenant):
        data['vision_codes'] = dict(InspectionItem.objects.for_tenant(tenant).values_list('id', 'code'))
        data['categories'] = dict(InspectionCategory.objects.for_tenant(tenant).exclude(form_code='')
                                  .values_list('form_code', 'name'))
    return data


def code_list(text):
    """'DF0012-DF0025,DF0030' → 양식코드 목록. 범위는 같은 접두어의 번호를 자릿수 그대로 잇는다"""
    codes = []
    for part in filter(None, (p.strip() for p in text.split(','))):
        start, _, end = part.partition('-')
        if not end:
            codes.append(start)
            continue
        prefix = start.rstrip('0123456789')
        width = len(start) - len(prefix)
        codes += [f'{prefix}{n:0{width}d}' for n in range(int(start[len(prefix):]), int(end[len(prefix):]) + 1)]
    return codes


def latest_forms(data, codes):
    """중분류에 매핑된 양식과 고른 코드마다 가장 높은 버전 [(코드, 버전)]"""
    wanted = set(data['categories']) | set(codes)
    latest = {}
    for form in data['dig_form']:
        if form['Code'] in wanted:
            latest[form['Code']] = max(latest.get(form['Code'], 0), form['Version'])
    missing = wanted - set(latest)
    if missing:
        raise CommandError('DB 에 없는 양식: ' + ', '.join(sorted(missing)))
    return sorted(latest.items())


def _strip(row, *more):
    return {k: v for k, v in row.items() if k not in DROP and k not in more}


def export_forms(data, keys):
    """고르는 양식의 정의를 id·작성자·결과 없이 뽑는다. 반환: (파일 내용, {사진 이름: 원본 경로}, [뺀 사진 설명])."""
    sections, items = {}, {}
    for row in data['dig_form_section']:
        sections.setdefault(row['DigForm_id'], []).append(row)
    for row in data['dig_form_item']:
        items.setdefault(row['DigFormSection_id'], []).append(row)
    attaches = {a['id']: a for a in data.get('attach_file', [])}
    refs = {a['id']: a for a in data.get('ref_file', [])}
    vision_codes, categories = data.get('vision_codes', {}), data.get('categories', {})
    forms, used, images, ref_images, files, dropped = [], set(), {}, {}, {}, []
    for form in data['dig_form']:
        if (form['Code'], form['Version']) not in keys:
            continue
        label = f"{form['Code']} v{form['Version']}"
        if any('<img' in (form.get(k) or '').lower() for k in ('Content', 'FixedTopContent')):
            raise CommandError(f'{label} 의 머리글에 사진이 있어 기본 데이터로 뽑지 않습니다.')

        def photo(match):
            attach = attaches.get(int(match.group(1)))
            if attach is None or not Path(attach['path']).is_file():
                dropped.append(f'{label} 참고사진 {match.group(1)}')
                return ''
            name = f"{form['Code']}-v{form['Version']}-{attach['id']}.{attach['ExtName']}"
            images[name], files[name] = {'FileName': attach['FileName'], 'ExtName': attach['ExtName']}, attach['path']
            return match.group(0).replace(f"/media/dig-form-image/{attach['id']}/", image_token(name))

        def ref_picture(content):
            """고정 이미지 칸 값(첨부 id) → 그림 자리. 글자 칸('사진' 같은 머리)은 그대로"""
            if not (content or '').isdigit():
                return content
            attach = refs.get(int(content))
            if attach is None or not Path(attach['path']).is_file():
                dropped.append(f'{label} 고정 이미지 {content}')
                return ''
            name = f"{form['Code']}-v{form['Version']}-ref-{attach['id']}.{attach['ExtName']}"
            ref_images[name], files[name] = {'FileName': attach['FileName'], 'ExtName': attach['ExtName']}, attach['path']
            return image_token(name)

        out = _strip(form)
        out['category'] = categories.get(form['Code'], '')
        out['sections'] = []
        for section in sorted(sections.get(form['id'], []), key=lambda r: (r['SortOrder'], r['id'])):
            sec = _strip(section, 'DigForm_id')
            if sec.get('Content'):
                sec['Content'] = IMG_WITH_URL.sub(photo, sec['Content'])
            if any('dig_form_image:' not in tag for tag in IMG_TAG.findall(sec.get('Content') or '')):
                raise CommandError(f'{label} 에 이 서버 첨부가 아닌 사진이 있어 뽑지 않습니다.')
            sec['items'] = []
            for item in sorted(items.get(section['id'], []), key=lambda r: (r['RowIndex'], r['ColumnIndex'])):
                cell = _strip(item, 'DigFormSection_id', 'DigFormWorkClass_id', 'VisionItem_id')
                cell['work_class'] = item.get('DigFormWorkClass_id')
                cell['vision_item'] = vision_codes.get(item.get('VisionItem_id'))
                if item['ResultType'] == 'R':
                    cell['Content'] = ref_picture(item.get('Content'))
                used.add(cell['work_class'])
                sec['items'].append(cell)
            out['sections'].append(sec)
        forms.append(out)
    missing = set(keys) - {(f['Code'], f['Version']) for f in forms}
    if missing:
        raise CommandError('DB 에 없는 양식: ' + ', '.join(f'{c} v{v}' for c, v in sorted(missing)))
    classes = {str(r['id']): _strip(r) for r in data['dig_form_work_class'] if r['id'] in used}
    return ({'format': 'dig-form-forms/v3', 'work_classes': classes, 'images': images, 'ref_images': ref_images,
             'forms': forms}, files, dropped)


class Command(BaseCommand):
    help = '이 서버 DB 에서 검사 분류에 매핑된 양식과 --codes 양식(최신 버전)을 seed_dig_form 데이터 파일(JSON)과 참고사진 폴더로 뽑습니다.'

    def add_arguments(self, parser):
        parser.add_argument('output', type=Path, help='뽑을 파일(예: domain/management/samples/dig_form_forms.json)')
        parser.add_argument('--codes', default=DEFAULT_CODES,
                            help=f'매핑과 함께 뽑을 양식코드. 쉼표와 범위(DF0012-DF0025)를 쓴다. 기본 {DEFAULT_CODES}')

    def handle(self, *args, **options):
        data = read()
        out, files, dropped = export_forms(data, latest_forms(data, code_list(options['codes'])))
        output = options['output']
        folder = output.parent / IMAGE_FOLDER
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        for name, source in files.items():
            shutil.copyfile(source, folder / name)
        output.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str) + '\n', encoding='utf-8')
        for line in dropped:
            self.stdout.write(self.style.WARNING(f'{line} — 파일이 이 서버에 없어 뺐습니다'))
        self.stdout.write(self.style.SUCCESS(
            f"양식 {len(out['forms'])}개·참고사진 {len(out['images'])}장·고정 이미지 {len(out['ref_images'])}장을 뽑았습니다 — {output}, {folder}"))
