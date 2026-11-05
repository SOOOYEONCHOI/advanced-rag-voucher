"""개발·검증용 표본 데이터.

검사항목·라벨 클래스·비전검사 클라이언트를 만든다. 멱등이다. 작업자 계정은 만들지 않는다 — 사용자 화면에서 만든다
(표본 라벨러·검수자 계정은 비전검사항목 배정을 없애며 뺐다, 사용자 결정 2026-10-21).

    python manage.py seed_demo

운영 DB 에서는 실행하지 않는다 — `--force` 없이는 이미 검사 데이터가 있으면 멈춘다.
표본 zip(`domain/management/samples/fan_panel.zip`)이 있으면 그 이미지까지 넣는다.

    python manage.py seed_demo --samples [zip 또는 폴더]

`--samples` 는 위 표본을 만든 뒤에 돌린다. 냉각팬 패널 검사항목 3종(분류·이상탐지·객체탐지)을 맞추고
표본(경로를 빼면 위 zip)의 이미지로 3종 모두에 대표 이미지·Overlay·이미지 20장을 넣는다(업로더는 첫 superuser).
Client API Key 는 건드리지 않는다. 다시 돌려도 늘지 않는다. 검사 데이터가 있는 DB 에서는 `--force` 가 필요하다.
"""
import hashlib
import secrets
import zipfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from domain.models.data import (
    InspectionItem,
    LabelClass,
    TenantMembership,
)
from domain.models.user import UserGroup, UserProfile
from domain.models.vision import VisionClient, VisionInspection, VisionOverlay
from domain.services.data.image import ImageService
from domain.tenancy import current_tenant, tenant_atomic

# 냉각팬 패널 단면(표본 zip) 하나를 검사 유형 3가지로 시험한다. FAN-PANEL 코드는 Wezard 연동
# (external_ref `maip:FAN-PANEL:…`, model_name `fan-panel`)에 묶여 있어 바꾸지 않는다.
DEFECT_CLASSES = [('scratch', '스크래치', '#E4572E', True), ('missing_screw', '나사 누락', '#D7263D', True),
                  ('grill_deform', '팬 그릴 변형', '#F3A712', True), ('hole_misplaced', '홀 위치 불량', '#1B998B', True)]
ITEMS = [
    ('FAN-PANEL-CLS', '냉각팬 패널 단면(분류)', InspectionItem.TaskType.CLASSIFICATION,
     [('normal', '정상', '#2E86AB', False), ('defect', '불량', '#D7263D', True)]),
    ('FAN-PANEL', '냉각팬 패널 단면(이상탐지)', InspectionItem.TaskType.ANOMALY_DETECTION, DEFECT_CLASSES),
    ('FAN-PANEL-DET', '냉각팬 패널 단면(객체탐지)', InspectionItem.TaskType.OBJECT_DETECTION, DEFECT_CLASSES),
]

# --samples 표본. 원본 PNG 를 그대로 묶었다 — 다시 인코딩하면 sha256 이 바뀌어 이미 올린 이미지와 중복 판정이 어긋난다.
SAMPLE_ZIP = Path(__file__).resolve().parents[1] / 'samples' / 'fan_panel.zip'
SAMPLE_COVER = '산업용 금속 패널과 팬 그릴.png'
SAMPLE_OVERLAY = '산업용 금속 패널과 팬 그릴_outline_transparent.png'
SAMPLE_IMAGE_FILES = [f'{n}.png' for n in range(1, 21)]
# 결함이 보이는 이미지는 라벨링 대상, 나머지는 정상(라벨링 불필요 → 검수 대기)으로 올린다.
SAMPLE_DEFECT_FILES = ['2.png', '3.png', '12.png', '13.png', '14.png']

# 비전검사 클라이언트 표본의 표시 이름. 바꾸면 재실행으로 기존 표본에도 반영된다.
CLIENT_NAME = '1호기 비전검사 클라이언트'

class Command(BaseCommand):
    help = '개발·검증용 비전검사항목·클라이언트 표본을 만든다(멱등).'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='검사 데이터가 이미 있어도 진행한다.')
        parser.add_argument('--samples', nargs='?', const='', default=None,
                            help='표본 zip 또는 폴더. 경로를 빼면 저장소의 표본 zip. 냉각팬 패널 3종에 이미지를 넣는다.')

    @transaction.atomic
    def handle(self, *args, **options):
        if VisionInspection.objects.exists() and not options['force']:
            self.stderr.write(self.style.ERROR(
                '이미 검사 데이터가 있다. 운영 DB 가 아닌지 확인하고 --force 를 붙여라.'))
            return

        if options['samples'] is not None:
            self._seed_samples(Path(options['samples']) if options['samples'] else SAMPLE_ZIP)
            return

        tenant = current_tenant()
        user_group, _ = UserGroup.objects.get_or_create(Code='user', defaults={'Name': '일반사용자'})

        with tenant_atomic(tenant):
            _upsert_items(tenant)

            api_key = secrets.token_urlsafe(32)
            client, created = VisionClient.objects.get_or_create(
                client_id='CLIENT-001', defaults={'name': CLIENT_NAME})
            account = client.service_account
            if created or not account:
                account, _ = User.objects.get_or_create(
                    username='svc-client-001',
                    defaults={'is_active': True, 'first_name': CLIENT_NAME})
                # 이 계정으로는 웹에 로그인할 수 없다. 업로드 행위자로만 쓴다.
                account.set_unusable_password()
                account.save()
                TenantMembership.objects.get_or_create(tenant=tenant, user=account)
                client.service_account = account
            # 표시 이름은 재실행 때마다 맞춘다. `defaults` 는 생성 때만 쓰이므로
            # 여기 없으면 이름을 바꿔도 기존 표본은 옛 이름으로 남는다.
            UserProfile.objects.filter(User=account).update(
                Name=CLIENT_NAME, UserGroup=user_group)
            client.name = CLIENT_NAME
            client.api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
            client.active = True
            client.save()

        self.stdout.write(self.style.SUCCESS(
            f'비전검사항목 {len(ITEMS)}개 / 클라이언트 1개'))
        self.stdout.write(f'CLIENT-001 API Key: {api_key}')
        self.stdout.write(self.style.WARNING(
            'API Key 는 해시만 저장한다. 이 줄을 놓치면 재발급해야 한다.'))
        # 표본 zip 이 있으면 이미지까지 넣는다. 없으면 검사항목만 만든다.
        if SAMPLE_ZIP.is_file():
            self._seed_samples(SAMPLE_ZIP)

    def _seed_samples(self, source):
        names = [SAMPLE_COVER, SAMPLE_OVERLAY, *SAMPLE_IMAGE_FILES]
        files = _read_samples(source, names)
        missing = [name for name in names if name not in files]
        if missing:
            raise CommandError(f'{source} 에 표본 파일이 없다: {", ".join(missing)}')
        uploader = User.objects.filter(is_superuser=True, is_active=True).order_by('id').first()
        if uploader is None:
            raise CommandError('표본 이미지를 올릴 관리자 계정이 없다. 먼저 seed_initial --admin-password 를 돌려라.')

        tenant = current_tenant()
        with tenant_atomic(tenant):
            for item in _upsert_items(tenant):
                # 대표 이미지·Overlay 는 이미 있으면 그대로 둔다 — 다시 쓰면 파일만 쌓이고 Overlay 버전이 오른다.
                if not item.cover_image:
                    item.cover_image.save(SAMPLE_COVER, ContentFile(files[SAMPLE_COVER]), save=False)
                    item.save(update_fields=['cover_image'])
                if not VisionOverlay.objects.filter(item=item).exists():
                    overlay = VisionOverlay(item=item, version=1, visible=True, opacity=1.0)
                    overlay.image.save(SAMPLE_OVERLAY, ContentFile(files[SAMPLE_OVERLAY]), save=False)
                    overlay.save()
                # 같은 내용은 업로드가 거절하므로(sha256) 다시 돌려도 늘지 않는다.
                uploads = [SimpleUploadedFile(n, files[n], content_type='image/png') for n in SAMPLE_IMAGE_FILES]
                result = ImageService.upload_images(
                    item, uploads, actor=uploader,
                    requires_labeling_flags=[n in SAMPLE_DEFECT_FILES for n in SAMPLE_IMAGE_FILES])
                self.stdout.write(self.style.SUCCESS(
                    f'{item.code}(id={item.id}) / 이미지 새로 {len(result["uploaded"])}장, '
                    f'건너뜀 {len(result["rejected"])}장'))


def _read_samples(source, names):
    """{파일 이름: 바이트}. zip 이면 압축을 풀어 읽고, 폴더면 그대로 읽는다. 없는 이름은 빠진다."""
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            present = set(archive.namelist())
            return {name: archive.read(name) for name in names if name in present}
    return {name: (source / name).read_bytes() for name in names if (source / name).is_file()}


def _upsert_items(tenant):
    """ITEMS 의 검사항목·라벨 클래스를 맞춘다(멱등). 만든 검사항목 목록을 돌려준다."""
    items = []
    for order, (code, name, task_type, classes) in enumerate(ITEMS):
        item, _ = InspectionItem.objects.update_or_create(
            code=code,
            defaults={'tenant': tenant, 'name': name, 'task_type': task_type,
                      'display_order': order, 'status': InspectionItem.Status.ACTIVE})
        for sort_order, (cls_name, ko, color, is_defect) in enumerate(classes):
            LabelClass.objects.update_or_create(
                tenant=tenant, item=item, name=cls_name,
                defaults={'display_name_ko': ko, 'color': color,
                          'is_defect': is_defect, 'sort_order': sort_order})
        items.append(item)
    return items
