# 디지털 양식(CheckList) 병합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 팀원 MES 브랜치 `feature/dig-form`(`125089b`)의 디지털 양식 화면·API·테이블 6개를 제조AI플랫폼에 옮기고, 팀원 DB 의 양식·작성 결과를 개발 DB 로 가져오며, `seed_initial` 이 메뉴·공통코드를, `seed_dig_form` 이 고객 양식 4종을 운영 기본 데이터로 넣게 한다.

**Architecture:** 화면·API 는 우리 MES 계열 규약(`/gui/<메뉴코드>`, `/api/<task>/<view>`, `gui.py` 인가 매핑)에 그대로 얹는다. 테이블은 팀원의 SQL 파일 대신 Django 마이그레이션 `0006` 으로 만든다. 참고사진은 팀원의 `/api/files/upload`·`/api/files/image`(인가 없음·경로 조작 가능·Windows 경로) 대신 `MEDIA_ROOT` 저장 + 권한 확인 View(`sendfile`)로 다시 만든다. 팀원 DB 데이터는 개발 전용 관리 명령 `import_dig_form` 이 읽기 전용 연결로 가져온다.

**Tech Stack:** Django 5.2, PostgreSQL 16, psycopg 3(이미 의존성), Pillow, jQuery + Quill(이미 `app/static/assets/vendor/quill`)

**Spec:** `tmp/dig-form-merge-inventory.md`(사용자 작성 병합 목록, git 무시 폴더) · 원본 소스 `/tmp/mes-team-dig-form`(`feature/dig-form` `125089b`, 기준 `main` `3870aeb`)

## Global Constraints

- 작업 브랜치 `feat/dig-form`. main 에 직접 커밋하지 않는다. 커밋 메시지는 한국어, 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- 마이그레이션은 Django 로만(`makemigrations`). `migrate --fake`·`django_migrations` 수정 금지. 다음 번호는 `0006`
- 테스트는 `--settings=configurations.test_settings`. 고친 모듈의 테스트만 돌리고, 전체 단위·전체 e2e 는 사용자 승인 후
- 사용자·DB 값은 화면에 `.text()` 로 넣는다(`innerHTML`·`.html()` 에 문자열을 이어 넣지 않는다). 동기 Ajax 금지
- 사용자 문구는 `~합니다` 체(`~하세요`·`~해 주세요` 는 그대로 둔다). HTTP reason 에 한글 금지
- 색은 hex 대신 `DESIGN.md` §2.1 토큰. 판정 "이상"은 `text-danger fw-bold`, 정상은 색 없이
- 파일은 공개 경로로 내지 않는다 — 권한 확인 View + `sendfile()`(DEC-019). 저장은 `MEDIA_ROOT` 아래
- 비밀(팀원 DB 접속 정보 포함)은 소스·커밋·로그·출력에 넣지 않는다. 팀원 DB 는 **읽기 전용 세션**으로만 연다
- 디지털 양식 테이블은 MES 계열(조직 구분 없음)이다 — `TENANT_TABLES`·RLS 대상이 아니다
- 팀원 원본 저장소(`/tmp/mes-team-dig-form`)는 읽기만 한다. 그 안의 코드를 실행하지 않는다

## 범위 결정 (계획 승인 때 함께 확인)

| # | 결정 | 이유 |
|---|---|---|
| S1 | 옮길 수 있는 화면은 모두 옮긴다(사용자 결정 2026-10-14 — 개발 중이라 옮긴 뒤 확인). 메뉴는 6개 — 수입검사목록 작성·조회, 품질검사목록 작성·조회, 양식 편집, **디지털 양식 조회**(체크리스트양식관리 폴더) | GRID 양식(DF0001~DF0009)의 입력칸은 디지털 양식 조회의 "입력칸 설정"에서만 바꾼다(양식 편집은 GRID 양식을 막는다) |
| S2 | 칸 설정 저장 `save_item` 은 작성·조회 API 가 아니라 **양식 편집 API**(`/api/system/form_edit`)로 옮긴다 — `wm_form_edit` 의 W 가 있어야 한다. 동작(작성 결과가 있는 양식도 바로 수정 — 팀원 ASM-005)은 그대로 두고 STATUS 에 확인 거리로 남긴다 | 팀원 위치(`dig_form/dig_form`)에 두면 작성 권한만으로 양식 구조를 바꾼다 |
| S2-1 | 메뉴 없는 `wm_dig_form_write`·`wm_dig_form_result`(form_type 없는 CheckList 작성·조회)는 화면 정의만 옮긴다(메뉴 없음 — superuser 가 주소로 연다) | 팀원 gui.py 그대로 |
| S3 | `dig_form.sql`·양식 데이터 SQL 4개는 옮기지 않는다. 고객 양식 4종(DF0001 v1·v2, DF0008, DF0009)은 팀원 DB 에서 **지금 구조로 뽑은 데이터 파일**(`domain/management/samples/dig_form_forms.json`)과 새 명령 `seed_dig_form` 으로 운영 기본 데이터가 된다(사용자 결정 2026-10-14) | SQL 4개는 섹션 구조 이전에 만들어 `DigFormSection_id` 를 채우지 않는다 — 지금 구조에서 실행되지 않는다 |
| S4 | 참고사진 실제 파일은 팀원 PC(`c:\temp\mes21\dig_form_section\`)에만 있다 — DB 로 가져올 수 없다 | 본문이 쓰는 4개(attach id 10·11·13·15)를 팀원에게 받아 `--photos` 로 넣는다. 받기 전에 가져오면 그 이미지는 본문에서 빠진다 |
| S5 | 팀원 DB 의 사용자그룹 권한(`user_group_menu`)·작성자 id 는 옮기지 않는다 | 사용자·그룹이 다른 DB 다. 권한은 `seed_initial` 이 관리자 그룹에 RW 로 준다. 작성자(`_creater_id`·`_modifier_id`)는 비운다 |
| S6 | 팀원의 `usergroup.html` "사용" 체크박스 복원도 옮긴다 | 우리 화면에도 체크박스가 없어, 저장하면 `usergroup.py` 가 `Disabled=True` 로 저장한다(같은 결함) |

## File Structure

| 파일 | 할 일 | 책임 |
|---|---|---|
| `domain/models/dig_form.py` | 생성(팀원 파일 기반) | 테이블 6개 모델 |
| `domain/models/__init__.py` | 수정 | `from .dig_form import *` |
| `domain/migrations/0006_dig_form.py` | 생성(`makemigrations`) | 테이블 생성 |
| `domain/services/dig_form_image.py` | 생성 | 참고사진 업로드 저장·주소·본문 이미지 연결(`sync_editor_images`) |
| `app/views/files/media.py` · `configurations/urls.py` | 수정 | `/media/dig-form-image/<id>/` 권한 확인 후 `sendfile` |
| `domain/gui.py` | 수정 | 화면 5개, `DIG_FORM_MENU_CODES`, API 인가 매핑 |
| `app/views/dig_form/__init__.py` · `dig_form.py` | 생성(팀원 파일 기반) | 작성·조회 API |
| `app/views/system/form_edit.py` | 생성(팀원 파일 기반) | 양식 편집 API + 이미지 업로드 action |
| `app/templates/dig_form/` 6개 · `app/templates/system/form_edit.html` | 생성(팀원 파일 기반) | 화면 |
| `app/templates/system/usergroup.html` | 수정 | "사용" 체크박스 |
| `domain/management/commands/seed_initial.py` | 수정 | 메뉴 폴더 3개·메뉴 5개·공통코드 5행 |
| `domain/management/commands/import_dig_form.py` | 생성 | 팀원 DB → 개발 DB(개발 전용), 고객 양식 데이터 파일 뽑기(`--export-forms`) |
| `domain/management/samples/dig_form_forms.json` | 생성(뽑은 결과) | 고객 양식 4종 정의(결과·작성자 없음) |
| `domain/management/commands/seed_dig_form.py` | 생성 | 고객 양식 4종을 넣는다(멱등, 운영 포함) |
| `tests/test_dig_form.py` | 생성 | 모델·API·이미지·seed·가져오기 |
| `tests/e2e/test_dig_form.py` | 생성 | 화면 5개 열림·양식 목록 |
| `docs/FEATURES.md`·`DATA_MODEL.md`·`ARCHITECTURE.md`·`DECISIONS.md`·`STATUS.md`·`DEVELOPMENT.md`·`DEPLOYMENT.md` | 수정 | 메뉴·테이블·파일 경로·결정·가져오기 절차·운영 기본 데이터 |

---

### Task 1: 모델과 마이그레이션 0006

**Files:**
- Create: `domain/models/dig_form.py`
- Modify: `domain/models/__init__.py`
- Create: `domain/migrations/0006_dig_form.py` (makemigrations 가 만든다)
- Test: `tests/test_dig_form.py`

**Interfaces:**
- Produces: `DigForm`, `DigFormWorkClass`, `DigFormSection`, `DigFormItem`, `DigFormResult`, `DigFormItemResult`(`domain.models.dig_form`). 필드명·`db_table` 은 팀원 모델과 같다(Task 7 이 컬럼명으로 옮긴다)

- [ ] **Step 1: 브랜치를 만든다**

```bash
git checkout -b feat/dig-form
```

- [ ] **Step 2: 실패하는 테스트를 쓴다** — `tests/test_dig_form.py`

```python
"""디지털 양식(CheckList) — 모델·API·참고사진·seed·가져오기."""
from django.db import IntegrityError, transaction
from django.test import TestCase

from domain.models.dig_form import (DigForm, DigFormItem, DigFormItemResult, DigFormResult,
                                    DigFormSection)


def make_form(code='DF-T1', input_types=('N',)):
    """양식 1개 + 점검항목 섹션 1개 + 입력칸(ResultType 별 1칸씩)."""
    form = DigForm.objects.create(Code=code, Title='시험 양식', LayoutType='SECTION')
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

    def test_양식코드_시퀀스가_있다(self):
        from domain.services.sql import DbUtil
        code = DbUtil.get_row("select 'DF' || lpad(nextval('dig_form_code_seq')::text, 4, '0') as code")['code']
        self.assertRegex(code, r'^DF\d{4}$')

    def test_작성건마다_칸_결과는_하나다(self):
        form, _section, (item,) = make_form()
        result = DigFormResult.objects.create(DigForm=form, WriteDate='2026-10-14')
        DigFormItemResult.objects.create(DigFormResult=result, DigFormItem=item, NumberResult=3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DigFormItemResult.objects.create(DigFormResult=result, DigFormItem=item, NumberResult=4)
```

- [ ] **Step 3: 실패를 확인한다**

Run: `.venv/bin/python manage.py test tests.test_dig_form --settings=configurations.test_settings`
Expected: `ModuleNotFoundError: No module named 'domain.models.dig_form'`

- [ ] **Step 4: 모델을 옮긴다**

`/tmp/mes-team-dig-form/SF_MES/domain/models/dig_form.py` 를 `domain/models/dig_form.py` 로 복사하고 머리 주석 두 줄만 바꾼다.

```python
# 디지털 양식(CheckList) — 팀원 MES `feature/dig-form` 에서 옮겼다. 스키마는 마이그레이션 0006 이 만든다.
# 조직 구분이 없는 MES 계열 테이블이다(RLS 대상 아님). 참고사진은 attach_file(TableName='dig_form_section', AttachName='editor').
```

팀원 DB 에는 `dig_form.sql` 이 건 제약 3개가 있는데 모델에는 없다. `DigFormItem.Meta` 에 더한다(Q 는 `from django.db.models import Q`).

```python
        constraints = [
            models.UniqueConstraint(fields=['DigFormSection', 'RowIndex', 'ColumnIndex'], name='dig_form_item_pos_uq'),
            models.CheckConstraint(condition=Q(InputYN='N') | Q(ResultType__isnull=False), name='dig_form_item_input_ck'),
            models.CheckConstraint(condition=Q(RowSpan__gte=1, ColSpan__gte=1), name='dig_form_item_span_ck'),
        ]
```

`domain/models/__init__.py` 끝에 한 줄을 더한다.

```python
from .dig_form import *
```

- [ ] **Step 5: 마이그레이션을 만들고 내용을 본다**

```bash
.venv/bin/python manage.py makemigrations domain --name dig_form
```

Expected: `domain/migrations/0006_dig_form.py` — `CreateModel` 6개 + `AddConstraint` 3개. 다른 모델 변경이 섞여 있으면 멈추고 원인을 본다.

양식 편집이 새 양식코드(`DF0013` …)를 `nextval('dig_form_code_seq')` 로 매긴다(`form_edit.py` 256행). 시퀀스는 모델이
아니라 만들어지지 않으므로 `operations` 끝에 더한다.

```python
        migrations.RunSQL(
            'CREATE SEQUENCE IF NOT EXISTS dig_form_code_seq START 1;',
            reverse_sql='DROP SEQUENCE IF EXISTS dig_form_code_seq;',
        ),
```

- [ ] **Step 6: 테스트가 통과하는지 본다**

Run: `.venv/bin/python manage.py test tests.test_dig_form --settings=configurations.test_settings`
Expected: `OK`. 이어서 `.venv/bin/python manage.py makemigrations --check --dry-run` → `No changes detected`

- [ ] **Step 7: 개발 DB 에 적용한다**(scoped path — 계획 승인으로 확인받은 항목)

```bash
.venv/bin/python manage.py migrate domain 0006
```

- [ ] **Step 8: 커밋**

```bash
git add domain/models/dig_form.py domain/models/__init__.py domain/migrations/0006_dig_form.py tests/test_dig_form.py
git commit -m "feat: 디지털 양식 테이블 6개를 모델과 마이그레이션 0006 으로 추가한다"
```

---

### Task 2: 참고사진 저장·제공

팀원의 `/api/files/upload`·`/api/files/image` 를 옮기지 않고 다시 만든다. 팀원 구현은 `others` 파라미터로 저장 폴더를 정하고(경로 조작), `c:\temp` 경로를 쓰며, 이미지를 권한 확인 없이 내준다.

**Files:**
- Create: `domain/services/dig_form_image.py`
- Modify: `domain/gui.py`(`DIG_FORM_MENU_CODES` 만 — 화면 등록은 Task 3)
- Modify: `app/views/files/media.py`, `configurations/urls.py`
- Test: `tests/test_dig_form.py`

**Interfaces:**
- Produces:
  - `domain.services.dig_form_image.save_upload(uploaded: UploadedFile, user) -> dict` — `{'success': True, 'fileId': int, 'url': str}`, 잘못된 파일은 `ValueError(사용자 문구)`
  - `sync_editor_images(html: str, data_pk: int, user) -> str` — 본문 이미지와 첨부 행을 맞추고 정리된 html 을 돌려준다. 허용되지 않은 이미지는 `ValueError`
  - `image_url(file_id: int) -> str` — `'/media/dig-form-image/<id>/'`
  - `IMAGE_TABLE = 'dig_form_section'`, `IMAGE_ATTACH = 'editor'`, `IMAGE_FOLDER = 'dig_form_section'`
  - `domain.gui.DIG_FORM_MENU_CODES: tuple[str, ...]` — 메뉴 6개 코드
  - URL 이름 `private-dig-form-image`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/test_dig_form.py` 에 더한다

```python
import io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from domain.models.system import AttachFile
from domain.models.user import UserGroup, UserGroupMenu
from domain.services.dig_form_image import image_url, save_upload, sync_editor_images


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
```

맨 위 import 에 `from pathlib import Path` 를 더한다.

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python manage.py test tests.test_dig_form --settings=configurations.test_settings`
Expected: `ModuleNotFoundError: No module named 'domain.services.dig_form_image'`

- [ ] **Step 3: 서비스를 만든다** — `domain/services/dig_form_image.py`

```python
"""디지털 양식 참고사진 — 양식 편집 에디터(Quill)에 넣는 이미지.

첨부 행은 기존 `attach_file`(TableName='dig_form_section', AttachName='editor', DataPk=섹션 id)이고,
파일은 `MEDIA_ROOT/dig_form_section/` 에 둔다. 공개 경로가 없다 — `/media/dig-form-image/<id>/` 가
디지털 양식 메뉴 권한을 확인하고 내준다(DEC-019).

에디터는 삽입 즉시 업로드하므로 첨부는 DataPk=0 으로 생기고, 양식을 저장할 때 `sync_editor_images` 가
섹션에 연결한다(팀원 MES `FileService.sync_editor_images` 와 같은 규칙).
"""
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from PIL import Image, UnidentifiedImageError

from domain.models.system import AttachFile

IMAGE_TABLE = 'dig_form_section'
IMAGE_ATTACH = 'editor'
IMAGE_FOLDER = 'dig_form_section'
MAX_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 50_000_000
EXTENSIONS = {'PNG': 'png', 'JPEG': 'jpg', 'GIF': 'gif'}
CONTENT_TYPES = {'png': 'image/png', 'jpg': 'image/jpeg', 'gif': 'image/gif'}

IMG_TAG = re.compile(r'<img\b[^>]*>', re.IGNORECASE)
IMG_SRC = re.compile(r'''\bsrc\s*=\s*["']([^"']*)["']''', re.IGNORECASE)
IMG_URL = re.compile(r'^/media/dig-form-image/(\d+)/$')
IMG_URL_IN_HTML = re.compile(r'/media/dig-form-image/(\d+)/')


def image_url(file_id):
    return f'/media/dig-form-image/{file_id}/'


def image_path(attach):
    return Path(settings.MEDIA_ROOT) / IMAGE_FOLDER / attach.PhysicFileName


def save_upload(uploaded, user):
    """이미지를 검사해 저장하고 연결되지 않은 첨부(DataPk=0)를 만든다."""
    if uploaded is None:
        raise ValueError('이미지 파일이 없습니다.')
    if uploaded.size > MAX_BYTES:
        raise ValueError('이미지는 30MB 이하만 올릴 수 있습니다.')
    try:
        with Image.open(uploaded) as image:
            kind, (width, height) = image.format, image.size
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('읽을 수 없는 이미지 파일입니다.') from exc
    if kind not in EXTENSIONS:
        raise ValueError('PNG·JPG·GIF 이미지만 올릴 수 있습니다.')
    if width * height > MAX_PIXELS:
        raise ValueError('이미지 해상도가 허용 범위를 초과했습니다.')

    ext = EXTENSIONS[kind]
    name = f'{uuid.uuid4().hex}.{ext}'
    folder = Path(settings.MEDIA_ROOT) / IMAGE_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    uploaded.seek(0)
    with open(folder / name, 'wb') as out:
        for chunk in uploaded.chunks():
            out.write(chunk)
    attach = AttachFile(TableName=IMAGE_TABLE, DataPk=0, AttachName=IMAGE_ATTACH, FileIndex=0,
                        FileName=uploaded.name[:100], PhysicFileName=name, ExtName=ext,
                        FilePath=IMAGE_FOLDER, FileSize=uploaded.size)
    attach.set_audit(user)
    attach.save()
    return {'success': True, 'fileId': attach.id, 'url': image_url(attach.id)}


def sync_editor_images(html, data_pk, user):
    """본문(html)의 이미지와 이 섹션의 첨부 행을 본문 기준으로 맞추고, 정리된 html 을 돌려준다.

    - DataPk=0(이 사용자가 올린 것) → 이 섹션에 연결
    - 다른 섹션의 이미지(섹션 복사·개정) → 같은 파일로 첨부 행을 복제하고 본문 주소를 새 id 로 바꾼다
    - 이 섹션에 연결돼 있으나 본문에서 빠진 이미지 → 첨부 행만 지운다(파일은 다른 행이 쓸 수 있어 남긴다)
    호출부 트랜잭션 안에서, 섹션 id 가 정해진 뒤 부른다.
    """
    html = html or ''
    file_ids = []
    for tag in IMG_TAG.findall(html):
        src = IMG_SRC.search(tag)
        match = IMG_URL.match(src.group(1)) if src else None
        if not match:
            raise ValueError('허용되지 않은 이미지가 포함되어 있습니다. 이미지는 에디터의 이미지 추가로 넣어 주세요.')
        file_ids.append(int(match.group(1)))

    with transaction.atomic():
        files = {f.id: f for f in AttachFile.objects.select_for_update().filter(
            id__in=set(file_ids), TableName=IMAGE_TABLE, AttachName=IMAGE_ATTACH)}
        id_map = {}
        for file_id in set(file_ids):
            attach = files.get(file_id)
            if attach is None or (attach.DataPk == 0 and attach._creater_id != user.id):
                raise ValueError('이미지 정보를 찾을 수 없습니다. 이미지를 다시 추가해 주세요.')
            if attach.DataPk == 0:
                attach.DataPk = data_pk
                attach.set_audit(user)
                attach.save()
            elif attach.DataPk != data_pk:
                copied = AttachFile(TableName=attach.TableName, DataPk=data_pk, AttachName=attach.AttachName,
                                    FileIndex=attach.FileIndex, FileName=attach.FileName,
                                    PhysicFileName=attach.PhysicFileName, ExtName=attach.ExtName,
                                    FilePath=attach.FilePath, FileSize=attach.FileSize)
                copied.set_audit(user)
                copied.save()
                id_map[file_id] = copied.id
        if id_map:
            html = IMG_URL_IN_HTML.sub(lambda m: image_url(id_map.get(int(m.group(1)), int(m.group(1)))), html)
        linked = [id_map.get(i, i) for i in set(file_ids)]
        AttachFile.objects.filter(TableName=IMAGE_TABLE, AttachName=IMAGE_ATTACH, DataPk=data_pk) \
            .exclude(id__in=linked).delete()
    return html
```

- [ ] **Step 4: 메뉴코드 상수를 둔다** — `domain/gui.py` 의 `ITEM_CHILD_MENU_CODES` 아래

```python
# 디지털 양식(CheckList) 화면. 참고사진(`/media/dig-form-image/`)과 작성·조회 API 는
# 이 중 하나의 권한이면 된다.
DIG_FORM_MENU_CODES = (
    'wm_dig_form_incoming_write', 'wm_dig_form_incoming_result',
    'wm_dig_form_outgoing_write', 'wm_dig_form_outgoing_result',
    'wm_form_edit', 'wm_dig_form_view',
)
```

- [ ] **Step 5: 제공 View 를 만든다** — `app/views/files/media.py` 끝

```python
class DigFormImageView(View):
    """디지털 양식 참고사진. 디지털 양식 메뉴 중 하나라도 읽기 권한이 있어야 한다.

    권한이 없거나 없는 id 면 구분 없이 404 다 — 존재 여부를 흘리지 않는다.
    """

    http_method_names = ['get']

    def get(self, request, file_id):
        from app.views import authorize_menu_codes
        from domain.gui import DIG_FORM_MENU_CODES
        from domain.models.system import AttachFile
        from domain.services.dig_form_image import (CONTENT_TYPES, IMAGE_ATTACH, IMAGE_TABLE,
                                                    image_path)

        if request.user.is_anonymous or authorize_menu_codes(
                request, list(DIG_FORM_MENU_CODES), 'media/dig-form-image'):
            raise Http404
        attach = AttachFile.objects.filter(pk=file_id, TableName=IMAGE_TABLE, AttachName=IMAGE_ATTACH).first()
        if attach is None:
            raise Http404
        try:
            return sendfile(str(image_path(attach)), request=request,
                            content_type=CONTENT_TYPES.get(attach.ExtName))
        except FileNotFoundError as exc:
            raise Http404('파일을 찾을 수 없습니다.') from exc
```

`configurations/urls.py` — import 목록에 `DigFormImageView` 를 더하고 `private-overlay` 줄 아래에 둔다.

```python
    path('media/dig-form-image/<int:file_id>/', DigFormImageView.as_view(), name='private-dig-form-image'),
```

- [ ] **Step 6: 테스트가 통과하는지 본다**

Run: `.venv/bin/python manage.py test tests.test_dig_form --settings=configurations.test_settings`
Expected: `OK`. 권한 테스트가 403 이 아니라 404 를 기대하는 것은 `authorize_menu_codes` 가 사유 문자열을 돌려주면 View 가 404 로 바꾸기 때문이다.

- [ ] **Step 7: 커밋**

```bash
git add domain/services/dig_form_image.py domain/gui.py app/views/files/media.py configurations/urls.py tests/test_dig_form.py
git commit -m "feat: 디지털 양식 참고사진을 MEDIA_ROOT 에 저장하고 메뉴 권한을 확인해 내준다"
```

---

### Task 3: 작성·조회·양식 편집 API

**Files:**
- Create: `app/views/dig_form/__init__.py`(빈 파일), `app/views/dig_form/dig_form.py`, `app/views/system/form_edit.py`
- Modify: `domain/gui.py`(화면 5개·API 인가 매핑)
- Test: `tests/test_dig_form.py`

**Interfaces:**
- Consumes: Task 1 모델, Task 2 `save_upload`·`sync_editor_images`·`DIG_FORM_MENU_CODES`
- Produces: `/api/dig_form/dig_form?action=form_list|wo_list|detail|result_list|result_search|result_values|find_result|save`, `/api/system/form_edit?action=read|detail|save|save_item|upload_image`. `save`·`save_item`·`upload_image` 는 POST 만 받는다

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `tests/test_dig_form.py` 에 더한다

```python
import json


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
        data = {'form_id': self.form.id, 'write_date': '2026-10-14',
                'Q': json.dumps([{'item_id': self.number_item.id, 'value': '5'}]), **extra}
        return getattr(self.client, method)('/api/dig_form/dig_form?action=save', data)

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

    def test_칸_설정은_양식_편집_쓰기_권한이_있어야_한다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        _form, section, _items = make_form(code='DF-T3', input_types=())
        cell = DigFormItem.objects.create(DigFormSection=section, RowType='D', RowIndex=3, ColumnIndex=1)
        data = {'item_id': cell.id, 'input_yn': 'Y', 'result_type': 'N', 'lower_limit': '1', 'upper_limit': '9'}
        self.client.post('/api/dig_form/dig_form?action=save_item', data)   # 작성 API 에는 이 action 이 없다
        cell.refresh_from_db()
        self.assertEqual(cell.InputYN, 'N')
        self.assertEqual(self.client.post('/api/system/form_edit?action=save_item', data).status_code, 403)
        self.grant('wm_form_edit', 'RW')
        self.assertEqual(self.client.post('/api/system/form_edit?action=save_item', data).json(),
                         {'success': True, 'message': ''})
        cell.refresh_from_db()
        self.assertEqual((cell.InputYN, cell.ResultType), ('Y', 'N'))

    def test_참고사진_업로드는_양식_편집_쓰기_권한이_있어야_한다(self):
        self.grant('wm_dig_form_outgoing_write', 'RW')
        upload = lambda: self.client.post('/api/system/form_edit?action=upload_image',
                                          {'uploadfile': SimpleUploadedFile('a.png', png_bytes(), 'image/png')})
        self.assertEqual(upload().status_code, 403)
        self.grant('wm_form_edit', 'RW')
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            body = upload().json()
        self.assertTrue(body['success'])
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python manage.py test tests.test_dig_form.DigFormApiTest --settings=configurations.test_settings`
Expected: 403(매핑 없음) 또는 404 로 실패

- [ ] **Step 3: 화면과 인가 매핑을 등록한다** — `domain/gui.py`

`menu_init()` 의 비전 검사 블록 아래:

```python
        # 디지털 양식(CheckList) — 같은 화면을 양식구분(form_type)별 메뉴로 쓴다. params 는 gparam 으로 간다.
        for code, name, template, form_type in (
                ('wm_dig_form_incoming_write', '수입검사목록 작성', 'dig_form/dig_form_write.html', 'INCOMING'),
                ('wm_dig_form_incoming_result', '수입검사목록 조회', 'dig_form/dig_form_result.html', 'INCOMING'),
                ('wm_dig_form_outgoing_write', '품질검사목록 작성', 'dig_form/dig_form_write.html', 'OUTGOING'),
                ('wm_dig_form_outgoing_result', '품질검사목록 조회', 'dig_form/dig_form_result.html', 'OUTGOING')):
            gui_dc[code] = cls.gui_item(name, template)
            gui_dc[code]['params'] = {'form_type': form_type}
        gui_dc['wm_form_edit'] = cls.gui_item('양식 편집', 'system/form_edit.html')
        # 디지털 양식 조회 — 작성건 보기 + GRID 양식의 입력칸 설정(칸 설정 저장은 양식 편집 API)
        gui_dc['wm_dig_form_view'] = cls.gui_item('디지털 양식 조회', 'dig_form/dig_form_view.html')
        # 메뉴 없음 — form_type 없이 여는 CheckList 작성·조회(팀원 gui.py 그대로)
        gui_dc['wm_dig_form_write'] = cls.gui_item('CheckList 작성', 'dig_form/dig_form_write.html')
        gui_dc['wm_dig_form_result'] = cls.gui_item('CheckList 조회', 'dig_form/dig_form_result.html')
```

`taskview_menu_code_map()` 의 비전 검사 블록 아래:

```python
        # 디지털 양식 — 작성은 작성 메뉴의 W, 조회는 아무 디지털 양식 메뉴의 R. 양식 편집은 자기 메뉴만.
        m['dig_form/dig_form'] = list(DIG_FORM_MENU_CODES)
        m['system/form_edit'] = ['wm_form_edit']
```

`DIG_FORM_MENU_CODES` 는 모듈 아래쪽에 있으므로 `taskview_menu_code_map` 실행 시점(클래스 메서드 호출 시)에는 정의돼 있다.

- [ ] **Step 4: API 를 옮긴다**

`/tmp/mes-team-dig-form/SF_MES/app/views/dig_form/dig_form.py` → `app/views/dig_form/dig_form.py`, `/tmp/mes-team-dig-form/SF_MES/app/views/system/form_edit.py` → `app/views/system/form_edit.py` 로 복사하고 `app/views/dig_form/__init__.py` 를 빈 파일로 만든 뒤 아래를 바꾼다.

1. **쓰기 action 은 POST 만** — MES 계열 API 는 HTTP 메서드로 R/W 를 가른다. GET 으로 저장 action 을 부르면 읽기 권한만으로 통과한다. 두 파일의 `action = gparam.get(...)` 바로 아래에:

```python
    if action in WRITE_ACTIONS and context.request.method != 'POST':
        raise PermissionDenied   # ApiModuleView 가 403 으로 바꾼다
```

모듈 상단에 `from django.core.exceptions import PermissionDenied` 와 상수를 둔다.

```python
WRITE_ACTIONS = frozenset({'save'})                     # dig_form.py
WRITE_ACTIONS = frozenset({'save', 'save_item', 'upload_image'})     # form_edit.py
```

2. **예상하지 못한 오류의 원문을 응답에 싣지 않는다**(사용자 문구는 `ValueError` 로만 던진다 — Django 의 형 변환 오류도
   `ValueError` 라 그 문장은 그대로 나가지만 내부 경로·SQL 은 담지 않는다) — 두 파일 끝의

```python
    except Exception as ex:
        source = '... : action-{}'.format(action)
        LogWriter.add_dblog('error', source, ex)
        return {'success': False, 'message': str(ex)}
```

를 아래로 바꾼다. 사용자 문구는 이미 `ValueError` 로 던지고 있고, 그 밖의 예외는 `ApiModuleView` 가 로그를 남기고 500 일반 문구로 답한다.

```python
    except ValueError as ex:
        return {'success': False, 'message': str(ex)}
```

`LogWriter` import 가 쓰이지 않게 되면 지운다.

3. **`save_item` 을 양식 편집 API 로 옮긴다**(범위 결정 S2) — `dig_form.py` 의 `elif action == 'save_item':` 블록을
   잘라 `form_edit.py` 의 action 분기(`elif action == 'save':` 다음)에 그대로 붙인다. 블록 안 코드는 바꾸지 않는다.
   `form_edit.py` 에 `DigFormItem` import 가 없으면 `from domain.models.dig_form import ... DigFormItem` 에 더한다.
   `dig_form.py` 에 쓰이지 않게 된 import 는 지운다.

4. **참고사진** — `form_edit.py`:
   - `from domain.services.file import FileService` → `from domain.services.dig_form_image import save_upload, sync_editor_images`
   - `IMAGE_TABLE = 'dig_form_section'` 상수와 `file_service = FileService()` 줄을 지운다
   - `file_service.sync_editor_images(s.get('content'), IMAGE_TABLE, section.id, user)` → `sync_editor_images(s.get('content'), section.id, user)`
   - `file_service.sync_editor_images('', IMAGE_TABLE, section.id, user)` → `sync_editor_images('', section.id, user)`
   - action 분기에 더한다:

```python
        elif action == 'upload_image':
            items = save_upload(context.request.FILES.get('uploadfile'), context.request.user)
```

5. 문서 참조 주석(`DIG_FORM_DECISIONS.md D-2` 등 우리 저장소에 없는 문서)은 지우지 않고 그대로 둔다 — 팀원 결정 번호라 추적에 쓴다.

- [ ] **Step 5: 테스트가 통과하는지 본다**

Run: `.venv/bin/python manage.py test tests.test_dig_form tests.test_api_authz --settings=configurations.test_settings`
Expected: `OK`

- [ ] **Step 6: 인가 매핑 검사**

Run: `.venv/bin/python scripts/verify/verify_permission_map.py`
Expected: `PASS`(템플릿이 아직 없어 화면 경로 검사가 실패하면 Task 4 뒤에 다시 돌린다)

- [ ] **Step 7: 커밋**

```bash
git add app/views/dig_form app/views/system/form_edit.py domain/gui.py tests/test_dig_form.py
git commit -m "feat: 디지털 양식 작성·조회·양식 편집 API 를 옮기고 쓰기 action 을 POST 전용으로 막는다"
```

---

### Task 4: 화면

**Files:**
- Create: `app/templates/dig_form/dig_form_write.html`, `dig_form_result.html`, `dig_form_view.html`, `dig_form_renderer.html`, `dig_form_wo_popup.html`, `dig_form_mat_in_popup.html`, `app/templates/system/form_edit.html`
- Test: 정적 검증 스크립트, Task 8 e2e

**Interfaces:**
- Consumes: Task 3 API, Task 2 `/media/dig-form-image/<id>/`·`/api/system/form_edit?action=upload_image`(응답 `{success, fileId, url}`)

- [ ] **Step 1: 템플릿을 복사한다**

```bash
mkdir -p app/templates/dig_form
for f in dig_form_write dig_form_result dig_form_view dig_form_renderer dig_form_wo_popup dig_form_mat_in_popup; do
  cp /tmp/mes-team-dig-form/SF_MES/app/templates/dig_form/$f.html app/templates/dig_form/; done
cp /tmp/mes-team-dig-form/SF_MES/app/templates/system/form_edit.html app/templates/system/
```

- [ ] **Step 2: 참고사진 주소를 바꾼다** — `system/form_edit.html`

```javascript
    const FORM_EDIT_IMAGE_URL = /^\/media\/dig-form-image\/\d+\/$/;
```

`FORM_EDIT_IMAGE_TABLE`·`FORM_EDIT_IMAGE_ATTACH` 상수를 지우고 `uploadEditorImage` 를 바꾼다(테이블·폴더는 서버가 정한다).

```javascript
        uploadEditorImage(file) {
            let data = new FormData();
            data.append('uploadfile', file);
            return new Promise(function (resolve, reject) {
                AjaxUtil.postFileAsyncData('/api/system/form_edit?action=upload_image', data, function (res) {
                    if (res && res.success && res.url) resolve(res);
                    else reject(res);
                }, function (req, status, error) {
                    reject(error);
                });
            });
        }
```

`uploadEditorImages` 의 `'/api/files/image?id=' + res.fileId` → `res.url`. 실패 문구는 서버 `message` 가 있으면 그것을 보인다.

```javascript
                } catch (e) {
                    Alert.alert('', (e && e.message) || ('이미지 업로드에 실패했습니다. (' + file.name + ')'));
                }
```

칸 설정 저장 주소를 바꾼다 — `dig_form/dig_form_view.html` 의 `AjaxUtil.postAsyncData(_this.url + '?action=save_item', ...)` →
`AjaxUtil.postAsyncData('/api/system/form_edit?action=save_item', ...)`. 이 화면의 "입력칸 설정" 버튼(`y_write_auth`)은
자기 메뉴 W 로 보이지만 저장은 `wm_form_edit` 의 W 가 있어야 한다 — 권한이 없으면 403 문구가 뜬다(확인 거리로 STATUS 에 적는다).

- [ ] **Step 3: `innerHTML`·`.html(` 을 하나씩 본다**

```bash
grep -n "innerHTML\|\.html(" app/templates/dig_form/*.html app/templates/system/form_edit.html
```

각 줄에서 넣는 값이 무엇인지 확인한다.
- 사용자·DB 값(양식명·칸 내용·작성값·WO)을 문자열로 이어 넣으면 `.text()`/`textContent` 나 `$('<td>').text(...)` 로 바꾼다
- 참고사진 본문(Quill HTML)은 HTML 이 내용이다. 렌더러의 `safeHtml` 을 거치는지 확인하고, 거치지 않으면 넣기 전에 `<script>`·`on*=` 속성·`javascript:` 주소를 지우는 `safeHtml` 을 거치게 한다
- 고정 마크업(아이콘·빈 칸)은 그대로 둔다

- [ ] **Step 4: 색을 토큰으로 바꾼다**(61곳 — 렌더러 19, 양식 편집 42)

```bash
.venv/bin/python scripts/verify/verify_tokens.py
```

나오는 줄마다 `DESIGN.md` §2.1 토큰으로 바꾼다. 팀원이 쓴 색과 대응:

| 팀원 색 | 토큰 |
|---|---|
| `#ea1b1b` `#c81616`(강조·필수·선택) | `var(--brand-primary)` · `var(--brand-primary-hover)`. 오류·NG 상태면 `var(--brand-danger)` |
| `#fff` `#ffffff` | `var(--brand-surface-1)` |
| `#fafafa` `#f5f4f4` `#f5f7fa` `#f0f2f5` | `var(--brand-surface-2)` |
| `#e8e8e8` `#e7e7e7` `#dedede` `#d8d8d8` `#d0d0d0` | `var(--brand-line)` |
| `#d9e0e7` `#d6dbe0` `#c1c1c2` `#a0a0a1` | `var(--brand-line-strong)` |
| `#747474` `#999999` `#51606d` | `var(--brand-muted)` |
| `#2e2e31` | `var(--brand-ink-2)` |
| `#fde8e8` `#fdf0f0` / `#f5c2c2` | `var(--brand-danger-tint)` / `var(--brand-danger-line)` |
| `#fff0da` / `#ffd79a` / `#b46500` | `var(--brand-warning-tint)` / `var(--brand-warning-line)` / `var(--brand-warning-ink)` |
| `#e8f0fe`(선택 칸) | `var(--row-select-bg)` |
| `#eef8f0` `#c6e6cf` `#1d7f3f`(OK·합격 초록) | 지운다 — 정상은 색 없이(DESIGN §2.1). 판정 NG 는 `text-danger fw-bold` |

- [ ] **Step 5: 정적 검증을 모두 돌린다**(화면을 고쳤으므로 모달·버튼 포함, 서버 필요한 것은 `./scripts/maipctl.py status web` 확인 후)

```bash
node scripts/verify/verify_screen_js.js
for s in verify_menu verify_permission_map verify_tokens verify_korean_only verify_links verify_naming verify_modals verify_buttons; do
  .venv/bin/python scripts/verify/$s.py || echo "FAIL $s"; done
```

Expected: 모두 PASS. 실패는 `DESIGN.md` §5(골격·버튼·모달·문구)와 §9 체크리스트대로 고친다. 영문 표기(`CheckList`·`WO`·`OK/NG`·`N/A`)를 `verify_korean_only` 가 잡으면 허용 목록이 아니라 화면 문구를 한국어로 바꿀지 사용자에게 묻는다.

- [ ] **Step 6: 화면을 직접 연다**

관리자로 로그인해 `/gui/wm_form_edit/`, `/gui/wm_dig_form_outgoing_write/`, `/gui/wm_dig_form_incoming_write/`(입고번호·자재입고 검색이 보이는지), 두 조회 화면, `/gui/wm_dig_form_view/`, 메뉴 없는 `/gui/wm_dig_form_write/`·`/gui/wm_dig_form_result/` 를 열어 브라우저 콘솔 오류가 없는지 본다. 데이터가 없어 목록이 비는 것은 Task 7 뒤에 다시 본다.

- [ ] **Step 7: 커밋**

```bash
git add app/templates/dig_form app/templates/system/form_edit.html
git commit -m "feat: 디지털 양식 작성·조회·양식 편집 화면을 옮기고 색·글자 넣기·참고사진 주소를 우리 규칙에 맞춘다"
```

---

### Task 5: seed_initial — 메뉴·공통코드 초기 등록

**Files:**
- Modify: `domain/management/commands/seed_initial.py`
- Test: `tests/test_dig_form.py`

**Interfaces:**
- Consumes: Task 3 의 `gui.py` 화면 코드(없으면 `seed_initial` 이 `gui.py 에 없는 메뉴코드다` 로 멈춘다)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from django.core.management import call_command

from domain.models.system import MenuItem, SystemCode


class SeedInitialDigFormTest(TestCase):
    def test_디지털_양식_메뉴와_판정_코드를_등록한다(self):
        call_command('seed_initial', stdout=io.StringIO())
        call_command('seed_initial', stdout=io.StringIO())   # 멱등
        menus = {m.MenuCode: (m.MenuFolder.FolderName, m.MenuName)
                 for m in MenuItem.objects.filter(MenuCode__in=DIG_FORM_MENU_CODES).select_related('MenuFolder')}
        self.assertEqual(menus, {
            'wm_dig_form_incoming_write': ('수입검사', '수입검사목록 작성'),
            'wm_dig_form_incoming_result': ('수입검사', '수입검사목록 조회'),
            'wm_dig_form_outgoing_write': ('품질검사', '품질검사목록 작성'),
            'wm_dig_form_outgoing_result': ('품질검사', '품질검사목록 조회'),
            'wm_form_edit': ('체크리스트양식관리', '양식 편집'),
            'wm_dig_form_view': ('체크리스트양식관리', '디지털 양식 조회'),
        })
        codes = list(SystemCode.objects.filter(CodeType__startswith='dig_form')
                     .order_by('CodeType', '_ordering').values_list('CodeType', 'Code', 'Value'))
        self.assertEqual(codes, [('dig_form_okng', 'Y', 'OK'), ('dig_form_okng', 'N', 'NG'),
                                 ('dig_form_pass_na', 'Y', '합격'), ('dig_form_pass_na', 'N', '불합격'),
                                 ('dig_form_pass_na', 'X', 'N/A')])
        self.assertEqual(UserGroupMenu.objects.filter(UserGroup__Code='admin', MenuCode='wm_form_edit')
                         .values_list('AuthCode', flat=True).get(), 'RW')
```

맨 위 import 에 `from domain.gui import DIG_FORM_MENU_CODES` 를 더한다.

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python manage.py test tests.test_dig_form.SeedInitialDigFormTest --settings=configurations.test_settings`
Expected: 메뉴 dict 가 비어 실패

- [ ] **Step 3: 구현한다** — `seed_initial.py`

`MENU_TREE` 의 `'데이터 관리'` 와 `'시스템 관리'` 사이에(아이콘·순서는 팀원 DB 의 폴더 82~84 와 같다):

```python
    # 디지털 양식(CheckList). 작성·조회는 같은 화면을 양식구분(form_type)별로 쓴다(gui.py params).
    ('수입검사', 'uil-layer-group', [
        ('wm_dig_form_incoming_write', '수입검사목록 작성'),
        ('wm_dig_form_incoming_result', '수입검사목록 조회'),
    ]),
    ('품질검사', 'uil-bring-bottom', [
        ('wm_dig_form_outgoing_write', '품질검사목록 작성'),
        ('wm_dig_form_outgoing_result', '품질검사목록 조회'),
    ]),
    ('체크리스트양식관리', 'uil-pricetag-alt', [
        ('wm_form_edit', '양식 편집'),
        ('wm_dig_form_view', '디지털 양식 조회'),
    ]),
```

`USER_GROUPS` 위에:

```python
# 공통코드 — 디지털 양식 판정 선택지. 작성 화면과 양식 편집이 sys_code 에서 읽는다.
SYSTEM_CODES = [
    ('dig_form_okng', 'Y', 'OK', '디지털 양식 판정 OK', 1),
    ('dig_form_okng', 'N', 'NG', '디지털 양식 판정 NG', 2),
    ('dig_form_pass_na', 'Y', '합격', '디지털 양식 판정 합격', 1),
    ('dig_form_pass_na', 'N', '불합격', '디지털 양식 판정 불합격', 2),
    ('dig_form_pass_na', 'X', 'N/A', '디지털 양식 판정 해당 없음', 3),
]
```

`handle()` 의 `SystemOption` 줄 아래:

```python
        for code_type, code, value, description, order in SYSTEM_CODES:
            SystemCode.objects.update_or_create(
                CodeType=code_type, Code=code,
                defaults={'Value': value, 'Description': description, '_ordering': order})
```

import 를 `from domain.models.system import MenuFolder, MenuItem, SystemCode, SystemOption` 로 바꾼다.

- [ ] **Step 4: 테스트가 통과하는지 본다**

Run: `.venv/bin/python manage.py test tests.test_dig_form tests.test_single_org tests.test_menu_tree --settings=configurations.test_settings`
Expected: `OK`

- [ ] **Step 5: 개발 DB 에 반영하고 메뉴를 검사한다**

```bash
.venv/bin/python manage.py seed_initial
.venv/bin/python scripts/verify/verify_menu.py
```

Expected: `메뉴폴더 6개 / 메뉴 23개`, `verify_menu` PASS. 좌측 메뉴에 폴더 3개가 데이터 관리와 시스템 관리 사이에 보인다.

- [ ] **Step 6: 커밋**

```bash
git add domain/management/commands/seed_initial.py tests/test_dig_form.py
git commit -m "feat: seed_initial 이 디지털 양식 메뉴 6개와 판정 공통코드를 등록한다"
```

---

### Task 6: 사용자그룹 "사용" 체크박스

**Files:**
- Modify: `app/templates/system/usergroup.html`
- Test: `tests/test_dig_form.py`(화면 응답), e2e `tests/e2e/test_crud.py -k 사용자그룹`(있으면)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
class UserGroupDisabledCheckboxTest(TestCase):
    def test_사용자그룹_화면에_사용_체크박스가_있다(self):
        """없으면 저장 때 disabled 가 빠져 usergroup.py 가 Disabled=True 로 저장한다."""
        admin = User.objects.create_user('root', password='x', is_superuser=True)
        self.client.force_login(admin)
        html = self.client.get('/gui/wm_user_group/').content.decode()
        self.assertIn('name="disabled"', html)
```

- [ ] **Step 2: 실패를 확인한다** — Expected: `AssertionError`

- [ ] **Step 3: 팀원 변경 세 군데를 우리 파일에 적용한다**

`/tmp/mes-team-dig-form` 에서 `git diff origin/main...HEAD -- SF_MES/app/templates/system/usergroup.html` 의 세 hunk — ① 설명 칸 위에 `id="disabled" name="disabled"` 체크박스 블록, ② 상세 바인딩 뒤 `$('#disabled').prop('checked', result.disabled == false);`, ③ 신규 버튼에서 `$('#disabled').prop('checked', true);`. 우리 파일의 같은 자리(설명 `textarea` 블록 위, `$('#description').text(result.description);` 아래, 신규 처리의 `$('#description').text('');` 아래)에 넣는다. 라벨은 `data-labelCd="사용"` 그대로.

- [ ] **Step 4: 통과 확인** — `.venv/bin/python manage.py test tests.test_dig_form --settings=configurations.test_settings` → `OK`. `verify_modals`·`verify_buttons` PASS

- [ ] **Step 5: 커밋**

```bash
git add app/templates/system/usergroup.html tests/test_dig_form.py
git commit -m "fix: 사용자그룹 화면에 사용 체크박스를 되살려 저장 때 그룹이 비활성으로 바뀌지 않게 한다"
```

---

### Task 7: 팀원 DB 에서 테스트 데이터 가져오기(`import_dig_form`)

개발 전용 관리 명령이다. 팀원 작업이 계속되면 `--replace` 로 다시 가져온다.

**Files:**
- Create: `domain/management/commands/import_dig_form.py`
- Test: `tests/test_dig_form.py`

**Interfaces:**
- Consumes: Task 1 테이블, Task 2 `image_url`·`IMAGE_*`
- Produces: `python manage.py import_dig_form [--photos <폴더>] [--replace]`, `python manage.py import_dig_form --export-forms <파일>` — 원본 접속은 환경변수 `DIG_FORM_SOURCE_URL`(`postgresql://…`)만. 테스트용으로 분리한 함수:
  - `load(data: dict[str, list[dict]], photos: Path|None) -> dict`
  - `export_forms(data: dict, keys: list[tuple[str, int]]) -> dict` — 고객 양식 데이터 파일(`dig-form-forms/v1`) 내용. Task 8 이 읽는다
  - `CUSTOMER_FORMS = [('DF0001', 1), ('DF0001', 2), ('DF0008', 1), ('DF0009', 1)]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from django.core.management.base import CommandError

from domain.management.commands.import_dig_form import export_forms, load, rewrite_photo_html


class ImportDigFormTest(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.photos = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.photos, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def source(self):
        audit = {'_status': None, '_created': '2026-10-12T10:00:00+09:00', '_modified': None,
                 '_creater_id': 1, '_modifier_id': 1}
        return {
            'dig_form': [{'id': 31, 'Code': 'DF0011', 'Version': 1, 'Title': 'FLOW', 'LayoutType': 'SECTION',
                          'UseYN': 'Y', **audit}],
            'dig_form_work_class': [],
            'dig_form_section': [{'id': 93, 'DigForm_id': 31, 'SectionType': 'PHOTO', 'SortOrder': 0,
                                  'HeaderRowCount': 1, 'WorkerColumnYN': 'Y',
                                  'Content': '<p><img src="/api/files/image?id=11"><img src="/api/files/image?id=12"></p>',
                                  **audit}],
            'dig_form_item': [{'id': 500, 'DigFormSection_id': 93, 'RowType': 'D', 'RowIndex': 2, 'ColumnIndex': 1,
                               'RowSpan': 1, 'ColSpan': 1, 'InputYN': 'Y', 'ResultType': 'T', **audit}],
            'dig_form_result': [{'id': 29, 'DigForm_id': 31, 'WriteDate': '2026-10-13', 'State': 'working',
                                 'Round': 1, 'WorkOrderNumber': 'test2610131104', **audit}],
            'dig_form_item_result': [{'id': 900, 'DigFormResult_id': 29, 'DigFormItem_id': 500,
                                      'TextResult': '양호', **audit}],
            'code_seq': 12,
            'attach_file': [
                {'id': 11, 'DataPk': 93, 'FileName': 'image.png', 'PhysicFileName': 'aaa.png', 'ExtName': 'png', 'FileSize': 70},
                {'id': 12, 'DataPk': 93, 'FileName': 'gone.png', 'PhysicFileName': 'gone.png', 'ExtName': 'png', 'FileSize': 70},
            ],
        }

    def test_id_를_그대로_옮기고_작성자는_비운다(self):
        load(self.source(), None)
        result = DigFormItemResult.objects.get(pk=900)
        self.assertEqual((result.DigFormResult_id, result.DigFormItem_id, result.TextResult), (29, 500, '양호'))
        self.assertIsNone(DigForm.objects.get(pk=31)._creater_id)
        DigForm.objects.create(Code='DF-NEW', Title='새 양식')   # 시퀀스를 옮긴 id 뒤로 맞췄다
        from domain.services.sql import DbUtil
        self.assertEqual(DbUtil.get_row("select nextval('dig_form_code_seq') as n")['n'], 13)

    def test_받은_사진은_새_첨부로_만들고_못_받은_사진은_본문에서_뺀다(self):
        (self.photos / 'aaa.png').write_bytes(png_bytes())
        summary = load(self.source(), self.photos)
        attach = AttachFile.objects.get(TableName='dig_form_section', DataPk=93)
        self.assertEqual(DigFormSection.objects.get(pk=93).Content, f'<p><img src="{image_url(attach.id)}"></p>')
        self.assertTrue((Path(self.media) / 'dig_form_section' / attach.PhysicFileName).is_file())
        self.assertEqual(summary['missing_photos'], ['gone.png'])

    def test_고객_양식은_id_결과_작성자_없이_섹션_칸_구조로_뽑는다(self):
        data = self.source()
        data['dig_form_section'][0].update(SectionType='INSPECTION', Content=None)
        data['dig_form_item'][0]['DigFormWorkClass_id'] = 3
        data['dig_form_work_class'] = [{'id': 3, 'Class1Name': '조립', 'Class2Name': None, 'Class3Name': None,
                                        'Description': None, '_status': None, '_created': None, '_modified': None,
                                        '_creater_id': None, '_modifier_id': None}]
        out = export_forms(data, [('DF0011', 1)])
        form = out['forms'][0]
        self.assertEqual((out['format'], form['Code'], form['Title']), ('dig-form-forms/v1', 'DF0011', 'FLOW'))
        self.assertNotIn('id', form)
        self.assertNotIn('_creater_id', form)
        item = form['sections'][0]['items'][0]
        self.assertEqual((item['RowIndex'], item['work_class']), (2, 3))
        self.assertNotIn('DigFormSection_id', item)
        self.assertEqual(out['work_classes'], {'3': {'Class1Name': '조립', 'Class2Name': None,
                                                     'Class3Name': None, 'Description': None}})

    def test_사진이_있거나_없는_양식은_뽑지_않는다(self):
        with self.assertRaisesMessage(CommandError, '사진'):
            export_forms(self.source(), [('DF0011', 1)])            # PHOTO 섹션에 img 가 있다
        with self.assertRaisesMessage(CommandError, 'DF0099'):
            export_forms(self.source(), [('DF0099', 1)])

    def test_원본_이미지_주소만_바꾼다(self):
        html = '<img alt="x" src="/api/files/image?id=3" width="10"><img src="https://e.x/a.png">'
        self.assertEqual(rewrite_photo_html(html, {3: 40}),
                         f'<img alt="x" src="{image_url(40)}" width="10"><img src="https://e.x/a.png">')
```

- [ ] **Step 2: 실패를 확인한다** — Expected: `ModuleNotFoundError ... import_dig_form`

- [ ] **Step 3: 명령을 만든다** — `domain/management/commands/import_dig_form.py`

```python
"""팀원 MES DB 의 디지털 양식(양식·작성 결과·참고사진)을 개발 DB 로 가져온다. 개발 전용이다.

    DIG_FORM_SOURCE_URL='postgresql://<user>:<password>@<host>:5432/<db>' \\
        python manage.py import_dig_form [--photos <참고사진 폴더>] [--replace]

- 접속 정보는 환경변수로만 받는다. 소스·커밋·로그·출력에 남기지 않는다. 원본은 읽기 전용 세션으로 연다
- id 를 그대로 옮긴다 — 작성 결과·칸이 id 로 묶여 있다. 옮긴 뒤 시퀀스를 맞춘다
- 작성자(`_creater_id`·`_modifier_id`)는 원본 DB 의 사용자라 비운다
- 참고사진: 원본 `attach_file` 행에 파일은 없다(팀원 PC 의 `c:\\temp\\mes21\\dig_form_section\\`). 그 폴더를 받아
  `--photos` 로 주면 같은 이름 파일을 MEDIA_ROOT 로 복사해 새 첨부를 만든다. 없는 파일의 이미지는 본문에서 뺀다
- 대상에 디지털 양식이 이미 있으면 멈춘다. `--replace` 는 대상의 디지털 양식 데이터·참고사진 첨부를 지우고 다시 넣는다
"""
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from domain.models.dig_form import DigForm, DigFormItemResult
from domain.models.system import AttachFile
from domain.services.dig_form_image import IMAGE_ATTACH, IMAGE_FOLDER, IMAGE_TABLE, image_url

# 넣는 순서(외래키 순). 지울 때는 거꾸로.
TABLES = ['dig_form', 'dig_form_work_class', 'dig_form_section', 'dig_form_item',
          'dig_form_result', 'dig_form_item_result']
OLD_IMG = re.compile(r'''(<img\b[^>]*\bsrc\s*=\s*["'])/api/files/image\?id=(\d+)(["'][^>]*>)''', re.IGNORECASE)


def rewrite_photo_html(html, id_map):
    """원본 이미지 주소(`/api/files/image?id=`)를 새 주소로 바꾸고, 옮기지 못한 이미지는 태그째 뺀다."""
    def swap(match):
        new_id = id_map.get(int(match.group(2)))
        return f'{match.group(1)}{image_url(new_id)}{match.group(3)}' if new_id else ''
    return OLD_IMG.sub(swap, html or '')


def fetch(url):
    """원본에서 표 6개와 참고사진 첨부 행을 읽는다."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(url, connect_timeout=10, application_name='maip-import-dig-form') as conn:
        conn.read_only = True
        cur = conn.cursor(row_factory=dict_row)
        data = {}
        for table in TABLES:
            cur.execute(f'select * from {table} order by id')   # 표 이름은 위 상수뿐이다
            data[table] = cur.fetchall()
        cur.execute('select * from attach_file where "TableName" = %s and "AttachName" = %s and "DataPk" <> 0 '
                    'order by id', (IMAGE_TABLE, IMAGE_ATTACH))
        data['attach_file'] = cur.fetchall()
        cur.execute('select last_value from dig_form_code_seq')
        data['code_seq'] = cur.fetchone()['last_value']
    return data


def load(data, photos):
    """읽은 행을 대상 DB 에 넣는다. {'counts': {...}, 'missing_photos': [...]}."""
    with transaction.atomic(), connection.cursor() as cur:
        for table in TABLES:
            cur.execute('select column_name from information_schema.columns '
                        'where table_schema = current_schema() and table_name = %s', [table])
            columns = {row[0] for row in cur.fetchall()}
            for row in data[table]:
                row = {**row, '_creater_id': None, '_modifier_id': None}
                names = [name for name in row if name in columns]
                cur.execute('insert into {} ({}) values ({})'.format(
                    table, ', '.join(f'"{n}"' for n in names), ', '.join(['%s'] * len(names))),
                    [row[n] for n in names])
            cur.execute(f"select setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"coalesce((select max(id) from {table}), 0) + 1, false)")

        id_map, missing = {}, []
        folder = Path(settings.MEDIA_ROOT) / IMAGE_FOLDER
        for row in data['attach_file']:
            source = photos / row['PhysicFileName'] if photos else None
            if source is None or not source.is_file():
                missing.append(row['FileName'])
                continue
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex}.{row['ExtName']}"
            shutil.copyfile(source, folder / name)
            attach = AttachFile.objects.create(
                TableName=IMAGE_TABLE, DataPk=row['DataPk'], AttachName=IMAGE_ATTACH, FileIndex=0,
                FileName=row['FileName'], PhysicFileName=name, ExtName=row['ExtName'],
                FilePath=IMAGE_FOLDER, FileSize=row['FileSize'])
            id_map[row['id']] = attach.id
        # 다음 새 양식코드가 원본에서 쓴 번호와 겹치지 않게 한다(원본 12 → 다음 DF0013).
        cur.execute("select setval('dig_form_code_seq', %s)", [max(data.get('code_seq') or 1, 1)])
        for section in data['dig_form_section']:
            if section['SectionType'] == 'PHOTO' and section.get('Content'):
                cur.execute('update dig_form_section set "Content" = %s where id = %s',
                            [rewrite_photo_html(section['Content'], id_map), section['id']])
    return {'counts': {t: len(data[t]) for t in TABLES}, 'missing_photos': missing}


# 운영 기본 데이터로 쓰는 고객 양식(사용자 결정 2026-10-14). seed_dig_form 이 넣는다.
CUSTOMER_FORMS = [('DF0001', 1), ('DF0001', 2), ('DF0008', 1), ('DF0009', 1)]
DROP = {'id', '_status', '_created', '_modified', '_creater_id', '_modifier_id'}


def _strip(row, *more):
    return {k: v for k, v in row.items() if k not in DROP and k not in more}


def export_forms(data, keys):
    """고르는 양식의 정의(섹션·칸·작업분류)를 id·작성자·결과 없이 뽑는다. 사진이 든 양식은 거절한다."""
    sections, items = {}, {}
    for row in data['dig_form_section']:
        sections.setdefault(row['DigForm_id'], []).append(row)
    for row in data['dig_form_item']:
        items.setdefault(row['DigFormSection_id'], []).append(row)
    forms, used = [], set()
    for form in data['dig_form']:
        if (form['Code'], form['Version']) not in keys:
            continue
        if '<img' in ((form.get('Content') or '') + (form.get('FixedTopContent') or '')).lower():
            raise CommandError(f"{form['Code']} v{form['Version']} 에 사진이 있어 기본 데이터로 뽑지 않습니다.")
        out = _strip(form)
        out['sections'] = []
        for section in sorted(sections.get(form['id'], []), key=lambda r: (r['SortOrder'], r['id'])):
            if '<img' in (section.get('Content') or '').lower():
                raise CommandError(f"{form['Code']} v{form['Version']} 에 사진이 있어 기본 데이터로 뽑지 않습니다.")
            sec = _strip(section, 'DigForm_id')
            sec['items'] = []
            for item in sorted(items.get(section['id'], []), key=lambda r: (r['RowIndex'], r['ColumnIndex'])):
                cell = _strip(item, 'DigFormSection_id', 'DigFormWorkClass_id')
                cell['work_class'] = item.get('DigFormWorkClass_id')
                used.add(cell['work_class'])
                sec['items'].append(cell)
            out['sections'].append(sec)
        forms.append(out)
    missing = set(keys) - {(f['Code'], f['Version']) for f in forms}
    if missing:
        raise CommandError('원본에 없는 양식: ' + ', '.join(f'{c} v{v}' for c, v in sorted(missing)))
    classes = {str(r['id']): _strip(r) for r in data['dig_form_work_class'] if r['id'] in used}
    return {'format': 'dig-form-forms/v1', 'work_classes': classes, 'forms': forms}


def clear():
    """대상의 디지털 양식 데이터와 참고사진 첨부를 지운다(파일은 남긴다)."""
    with transaction.atomic(), connection.cursor() as cur:
        for table in reversed(TABLES):
            cur.execute(f'delete from {table}')
        AttachFile.objects.filter(TableName=IMAGE_TABLE, AttachName=IMAGE_ATTACH).delete()


class Command(BaseCommand):
    help = '팀원 MES DB 의 디지털 양식 데이터를 개발 DB 로 가져옵니다(개발 전용).'

    def add_arguments(self, parser):
        parser.add_argument('--photos', type=Path, help='팀원 PC 의 dig_form_section 폴더를 받아 둔 경로')
        parser.add_argument('--replace', action='store_true', help='대상의 디지털 양식 데이터를 지우고 다시 넣습니다.')
        parser.add_argument('--export-forms', type=Path,
                            help='대상 DB 에 넣지 않고 고객 양식 4종을 이 파일(JSON)로 뽑습니다(seed_dig_form 이 읽습니다).')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('개발 서버(DEBUG)에서만 실행합니다.')
        url = os.environ.get('DIG_FORM_SOURCE_URL')
        if not url:
            raise CommandError('환경변수 DIG_FORM_SOURCE_URL 에 원본 DB 주소를 넣어 주세요.')
        if options['export_forms']:
            out = export_forms(fetch(url), CUSTOMER_FORMS)
            options['export_forms'].write_text(
                json.dumps(out, ensure_ascii=False, indent=1, default=str) + '\n', encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f"양식 {len(out['forms'])}개를 뽑았습니다 — {options['export_forms']}"))
            return
        if DigForm.objects.exists() or DigFormItemResult.objects.exists():
            if not options['replace']:
                raise CommandError('대상에 디지털 양식이 이미 있습니다. 다시 가져오려면 --replace 를 줍니다.')
            clear()
        summary = load(fetch(url), options['photos'])
        counts = ', '.join(f'{t} {n}' for t, n in summary['counts'].items())
        self.stdout.write(self.style.SUCCESS(f'가져왔습니다 — {counts}'))
        if summary['missing_photos']:
            self.stdout.write(self.style.WARNING(
                '파일이 없어 본문에서 뺀 참고사진: ' + ', '.join(summary['missing_photos'])))
```

- [ ] **Step 4: 테스트가 통과하는지 본다**

Run: `.venv/bin/python manage.py test tests.test_dig_form --settings=configurations.test_settings`
Expected: `OK`

- [ ] **Step 5: 커밋**

```bash
git add domain/management/commands/import_dig_form.py tests/test_dig_form.py
git commit -m "feat: 팀원 MES DB 의 디지털 양식 데이터를 개발 DB 로 가져오는 import_dig_form 명령을 추가한다"
```

- [ ] **Step 6: 개발 DB 로 가져온다**

접속 주소는 팀원 소스 설정에서 만들어 **출력하지 않고** 환경변수로만 넘긴다(사용자가 자기 터미널에서 `DIG_FORM_SOURCE_URL` 을 넣어 직접 실행해도 된다).

```bash
PHOTOS=<참고사진 폴더, 없으면 비움> .venv/bin/python - <<'EOF'
import os, re, subprocess
from pathlib import Path
from urllib.parse import quote
s = Path('/tmp/mes-team-dig-form/SF_MES/configurations/settings.py').read_text()
get = lambda pattern: re.search(pattern, s).group(1)
url = 'postgresql://{}:{}@{}:5432/yest'.format(
    quote(get(r"'USER'\s*:\s*'([^']*)'"), safe=''), quote(get(r"'PASSWORD'\s*:\s*'([^']*)'"), safe=''),
    get(r"DBMS_HOST\s*=\s*'([^']*)'"))
args = (['--photos', os.environ['PHOTOS']] if os.environ.get('PHOTOS') else []) + \
    (['--replace'] if os.environ.get('REPLACE') else [])
subprocess.run(['.venv/bin/python', 'manage.py', 'import_dig_form', *args],
               env={**os.environ, 'DIG_FORM_SOURCE_URL': url}, check=True)
EOF
```

Expected: `dig_form 13, dig_form_work_class 34, dig_form_section 25, dig_form_item 1814, dig_form_result 7, dig_form_item_result 78`. 참고사진 폴더가 없으면 경고에 4개 파일명이 나온다 — 팀원에게 받은 뒤 `PHOTOS=<폴더> REPLACE=1` 로 다시 실행한다.

- [ ] **Step 7: 화면에서 데이터를 본다**

양식 편집 목록 13개(`DF0001`~`DF0012`), 품질검사목록 조회에 작성 결과 7건, `DF0011` 의 참고사진 섹션(사진을 받았으면 이미지 표시).

---

### Task 8: 고객 양식 4종 운영 기본 데이터(`seed_dig_form`)

고객 양식 4종(NEOCON 제조 중간 검수 성적서 v1·v2, 별첨1 전장 발열 온도 및 Torque 기준, 8계통 Check Sheet)을 팀원 DB 에서
지금 구조(섹션·칸)로 뽑아 저장소에 두고, 새 명령이 넣는다. 운영 서버에서도 돈다. 작성 결과·작성자·사진은 넣지 않는다.

**Files:**
- Create: `domain/management/samples/dig_form_forms.json`(Task 7 `--export-forms` 결과, 약 0.4 MB)
- Create: `domain/management/commands/seed_dig_form.py`
- Test: `tests/test_dig_form.py`

**Interfaces:**
- Consumes: Task 7 `export_forms` 형식(`dig-form-forms/v1`), Task 1 모델·`dig_form_code_seq`
- Produces: `python manage.py seed_dig_form` — 같은 (Code, Version) 이 있으면 건너뛴다(멱등)

- [ ] **Step 1: 데이터 파일을 뽑는다**(Task 7 Step 6 의 래퍼에서 `args` 만 바꾼다)

```python
args = ['--export-forms', 'domain/management/samples/dig_form_forms.json']
```

Expected: `양식 4개를 뽑았습니다`. 파일을 열어 `forms` 4개(DF0001 v1·v2, DF0008, DF0009), 칸 수 합 1,297, `id`·`_creater_id` 가 없는지,
`<img` 가 없는지 본다(`grep -c '<img' …` → 0). 고객 사내 정보(실명·연락처)가 칸 내용에 있는지 훑어본다 — 있으면 멈추고 사용자에게 묻는다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

```python
import json as _json

from domain.management.commands.seed_dig_form import FIXTURE


class SeedDigFormTest(TestCase):
    def test_고객_양식을_넣고_다시_돌려도_늘지_않는다(self):
        data = _json.loads(FIXTURE.read_text(encoding='utf-8'))
        call_command('seed_dig_form', stdout=io.StringIO())
        call_command('seed_dig_form', stdout=io.StringIO())
        self.assertEqual(sorted(DigForm.objects.values_list('Code', 'Version')),
                         [('DF0001', 1), ('DF0001', 2), ('DF0008', 1), ('DF0009', 1)])
        expected = sum(len(s['items']) for f in data['forms'] for s in f['sections'])
        self.assertEqual(DigFormItem.objects.count(), expected)
        self.assertFalse(DigFormResult.objects.exists())

    def test_새_양식코드는_기본_양식_다음_번호부터다(self):
        call_command('seed_dig_form', stdout=io.StringIO())
        from domain.services.sql import DbUtil
        self.assertEqual(DbUtil.get_row("select nextval('dig_form_code_seq') as n")['n'], 10)

    def test_작업분류는_같은_이름이면_다시_만들지_않는다(self):
        call_command('seed_dig_form', stdout=io.StringIO())
        before = DigFormWorkClass.objects.count()
        # 외래키가 PROTECT 라 지우지 않고 코드를 바꿔, DF0001 v2(작업분류를 쓰는 양식)를 다시 넣게 한다
        DigForm.objects.filter(Code='DF0001', Version=2).update(Code='DF0001X')
        call_command('seed_dig_form', stdout=io.StringIO())
        self.assertTrue(DigForm.objects.filter(Code='DF0001', Version=2).exists())
        self.assertEqual(DigFormWorkClass.objects.count(), before)
```

`DigFormWorkClass` 를 `domain.models.dig_form` import 에 더한다.

- [ ] **Step 3: 실패를 확인한다** — Expected: `ModuleNotFoundError ... seed_dig_form`

- [ ] **Step 4: 명령을 만든다** — `domain/management/commands/seed_dig_form.py`

```python
"""고객 양식(디지털 양식) 기본 데이터를 넣는다. 운영 서버에서도 돈다. 멱등이다.

    python manage.py seed_dig_form

데이터는 `samples/dig_form_forms.json`(팀원 MES DB 에서 `import_dig_form --export-forms` 로 뽑은 것)이다.
같은 (양식코드, 버전)이 이미 있으면 건너뛴다 — 운영에서 고친 양식을 덮지 않는다.
작업분류(dig_form_work_class)는 대·중·소 분류명이 같으면 있는 것을 쓴다.
"""
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from domain.models.dig_form import DigForm, DigFormItem, DigFormSection, DigFormWorkClass

FIXTURE = Path(__file__).resolve().parents[1] / 'samples' / 'dig_form_forms.json'


class Command(BaseCommand):
    help = '고객 양식(디지털 양식) 기본 데이터를 넣습니다(멱등).'

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads(FIXTURE.read_text(encoding='utf-8'))
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

        created, skipped = [], []
        for form in data['forms']:
            form = dict(form)
            sections = form.pop('sections')
            label = f"{form['Code']} v{form['Version']}"
            if DigForm.objects.filter(Code=form['Code'], Version=form['Version']).exists():
                skipped.append(label)
                continue
            digform = DigForm.objects.create(**form)
            for section in sections:
                section = dict(section)
                items = section.pop('items')
                row = DigFormSection.objects.create(DigForm=digform, **section)
                DigFormItem.objects.bulk_create([
                    DigFormItem(DigFormSection=row, DigFormWorkClass=work_class(item.pop('work_class')), **item)
                    for item in (dict(i) for i in items)])
            created.append(label)

        # 양식 편집이 새로 매기는 코드(DF + 4자리)가 기본 양식 코드와 겹치지 않게 한다.
        top = max((int(f['Code'][2:]) for f in data['forms'] if re.fullmatch(r'DF\d{4}', f['Code'])), default=0)
        with connection.cursor() as cur:
            cur.execute("select setval('dig_form_code_seq', greatest(%s, "
                        "(select case when is_called then last_value else 0 end from dig_form_code_seq)), true)",
                        [max(top, 1)])
        self.stdout.write(self.style.SUCCESS(
            f"고객 양식 {len(created)}개 추가, {len(skipped)}개는 이미 있음"
            + (f" ({', '.join(skipped)})" if skipped else '')))
```

- [ ] **Step 5: 테스트가 통과하는지 본다**

Run: `.venv/bin/python manage.py test tests.test_dig_form --settings=configurations.test_settings`
Expected: `OK`

- [ ] **Step 6: 개발 DB 에서 확인한다** — Task 7 로 같은 양식을 이미 가져왔으므로 `4개는 이미 있음` 이 나와야 한다.

```bash
.venv/bin/python manage.py seed_dig_form
```

- [ ] **Step 7: 커밋**(데이터 파일이 1 MB 를 넘으면 멈추고 사용자에게 말한다)

```bash
ls -l domain/management/samples/dig_form_forms.json
git add domain/management/samples/dig_form_forms.json domain/management/commands/seed_dig_form.py tests/test_dig_form.py
git commit -m "feat: 고객 양식 4종을 운영 기본 데이터로 넣는 seed_dig_form 명령과 데이터 파일을 추가한다"
```

---

### Task 9: e2e·문서·최종 검증

**Files:**
- Create: `tests/e2e/test_dig_form.py`
- Modify: `docs/FEATURES.md`, `docs/DATA_MODEL.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/STATUS.md`, `docs/DEVELOPMENT.md`

- [ ] **Step 1: e2e 를 쓴다** — `tests/e2e/test_dig_form.py`(데이터는 읽기만 한다 — Task 7 데이터가 있어야 한다)

```python
"""디지털 양식 화면 8개가 열리고 양식 목록을 불러오는지 본다. 쓰기 요청은 하지 않는다."""
import pytest

from tests.e2e.conftest import login

SCREENS = ['wm_dig_form_incoming_write', 'wm_dig_form_incoming_result',
           'wm_dig_form_outgoing_write', 'wm_dig_form_outgoing_result', 'wm_form_edit',
           'wm_dig_form_view', 'wm_dig_form_write', 'wm_dig_form_result']


@pytest.mark.parametrize('gui_code', SCREENS)
def test_디지털_양식_화면이_오류_없이_열린다(page, base_url, admin_password, gui_code):
    errors = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    login(page, base_url, 'admin', admin_password)
    with page.expect_response(lambda r: '/api/' in r.url and ('dig_form' in r.url or 'form_edit' in r.url)) as res:
        page.goto(f'{base_url}/gui/{gui_code}/', wait_until='networkidle')
    assert res.value.status == 200
    assert errors == []
```

Run: `.venv/bin/python -m pytest tests/e2e/test_dig_form.py -q`(서버가 떠 있어야 한다)
Expected: `8 passed`

- [ ] **Step 2: 문서를 고친다**

| 문서 | 내용 |
|---|---|
| `FEATURES.md` | 메뉴 표에 폴더 3개·메뉴 5개, 화면별 기능(양식 편집: 섹션·점검항목·참고사진, 작성: 양식 선택·WO/입고번호·이어쓰기, 조회), 수입검사 자재입고 검색은 화면 틀만 |
| `DATA_MODEL.md` | 테이블 6개 표(RLS 아님), 공통코드 `dig_form_okng`·`dig_form_pass_na`, 참고사진 `attach_file`(`dig_form_section`/`editor`) + `MEDIA_ROOT/dig_form_section/`, 마이그레이션 `0006` 행, "다음 변경은 0007_…" |
| `ARCHITECTURE.md` | 파일 제공 표에 `/media/dig-form-image/<id>/`(디지털 양식 메뉴 R), API 표에 `/api/dig_form/dig_form`·`/api/system/form_edit` |
| `DECISIONS.md` | 새 결정 행 — 디지털 양식을 MES 계열 테이블로 옮김(조직 구분 없음), 참고사진을 권한 확인 View 로 다시 만듦(팀원 `/api/files` 미이식), 쓰기 action POST 전용, 칸 설정 저장(`save_item`)은 양식 편집 API·권한, 고객 양식 4종은 `seed_dig_form` 기본 데이터(사용자 결정 2026-10-14) |
| `STATUS.md` | 확인 거리 — 수입검사 자재입고 검색(틀만), WO 검색이 작성건 WO 를 임시 출처로 씀, 참고사진 파일 수령 여부, 입력칸 설정이 작성 결과가 있는 양식도 바로 고침(팀원 ASM-005), 디지털 양식 조회의 "입력칸 설정" 버튼은 자기 메뉴 W 로 보이나 저장은 `wm_form_edit` W 필요, 메뉴 없는 CheckList 작성·조회 |
| `DEVELOPMENT.md` | `import_dig_form` 실행 절차(환경변수·`--photos`·`--replace`·`--export-forms`) — 팀원이 고객 양식을 고치면 `--export-forms` 로 데이터 파일을 다시 뽑는다 |
| `DEPLOYMENT.md` | 설치·업데이트 순서에 `seed_dig_form`(`seed_initial` 다음). 이미 있는 양식은 건너뛴다 |

- [ ] **Step 3: 검증 스크립트를 모두 돌린다**

```bash
node scripts/verify/verify_screen_js.js
for s in verify_menu verify_permission_map verify_response_keys verify_tokens verify_korean_only verify_links verify_naming verify_modals verify_buttons; do
  .venv/bin/python scripts/verify/$s.py || echo "FAIL $s"; done
.venv/bin/python manage.py makemigrations --check --dry-run
```

- [ ] **Step 4: 전체 단위 테스트는 사용자 승인 후**

마이그레이션·`gui.py` 인가·`seed_initial` 을 고쳐 영향 범위를 좁힐 수 없다. 승인받으면 `.venv/bin/python manage.py test tests --settings=configurations.test_settings`. CSS·레이아웃 공용 파일은 건드리지 않으므로 전체 e2e 는 제안하지 않는다.

- [ ] **Step 5: 커밋**

```bash
git add tests/e2e/test_dig_form.py docs/FEATURES.md docs/DATA_MODEL.md docs/ARCHITECTURE.md docs/DECISIONS.md docs/STATUS.md docs/DEVELOPMENT.md docs/DEPLOYMENT.md
git commit -m "docs: 디지털 양식 메뉴·테이블·참고사진 경로·가져오기 절차와 결정을 문서에 반영한다"
```
