"""디지털 양식 이미지 — 양식 편집 참고사진(에디터)과 CheckList 작성의 이미지 칸.

참고사진: 첨부 행은 기존 `attach_file`(TableName='dig_form_section', AttachName='editor', DataPk=섹션 id)이고,
파일은 `MEDIA_ROOT/dig_form_section/` 에 둔다.
이미지 칸: 점검항목 섹션의 이미지 열(ResultType='I') 칸마다 사진 1장. 첨부 행은
(TableName='dig_form_item_result', AttachName='cell', DataPk=칸 결과 id)이고 칸 결과 TextResult 에 첨부 id 를 둔다.
파일은 `MEDIA_ROOT/dig_form_result/` 에 둔다. 나중에 AI 가 이 사진을 읽어 같은 행의 다른 칸을 채운다.
고정 이미지 칸: 점검항목 섹션의 고정 이미지 열(ResultType='R') 칸에 양식이 박아 두는 그림 1장(작성자는 고치지 않는다). 첨부 행은
(TableName='dig_form_item', AttachName='ref', DataPk=칸 id)이고 칸 Content 에 첨부 id 를 둔다. 파일은 `MEDIA_ROOT/dig_form_item/` 에 둔다.
위 칸과 병합한 칸은 칸 하나(RowSpan)라 첨부도 하나다. 칸이 새 버전마다 새로 만들어지므로 `link_ref_images` 가 새 칸에 다시 연결한다.

비전검사항목이 연결된 이미지 칸(`dig_form_item.VisionItem`): 사진은 첨부가 아니라 그 항목의 비전 데이터 이미지(`ImageAsset`)
한 벌이고, 칸 결과 TextResult 에 그 이미지 id 를 둔다. 넣는 즉시(`capture_image`) 라벨링 대기열에 오르고, 칸에서 빼거나 검사를
지워도 데이터 관리의 사진은 남는다. 다음 단계의 AI 추론은 이 이미지를 가리키는 검사 기록으로 붙인다.

공개 경로가 없다 — `/media/dig-form-image/<id>/` 가 디지털 양식 메뉴 권한을 확인하고 내준다(DEC-019).

둘 다 고르는 즉시 업로드하므로 첨부는 DataPk=0 으로 생기고, 저장할 때 연결한다 — 참고사진은
`sync_editor_images`(팀원 MES `FileService.sync_editor_images` 와 같은 규칙), 이미지 칸은 `link_cell_image`.
"""
import datetime
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from PIL import Image, UnidentifiedImageError

from domain.models.data import ImageAsset, InspectionItem
from domain.models.dig_form import DigFormItem
from domain.models.system import AttachFile
from domain.models.vision import VisionInspection
from domain.services.vision.inspection import judgement_text, measured_rows
from domain.tenancy import current_tenant, tenant_atomic

IMAGE_TABLE = 'dig_form_section'
IMAGE_ATTACH = 'editor'
IMAGE_FOLDER = 'dig_form_section'
CELL_TABLE = 'dig_form_item_result'
CELL_ATTACH = 'cell'
CELL_FOLDER = 'dig_form_result'
REF_TABLE = 'dig_form_item'
REF_ATTACH = 'ref'
REF_FOLDER = 'dig_form_item'
# 첨부 구분(TableName, AttachName) → 저장 폴더. `/media/dig-form-image/` 는 이 구분의 첨부만 내준다
FOLDERS = {(IMAGE_TABLE, IMAGE_ATTACH): IMAGE_FOLDER, (CELL_TABLE, CELL_ATTACH): CELL_FOLDER,
           (REF_TABLE, REF_ATTACH): REF_FOLDER}
MAX_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 50_000_000
EXTENSIONS = {'PNG': 'png', 'JPEG': 'jpg', 'GIF': 'gif'}
CONTENT_TYPES = {'png': 'image/png', 'jpg': 'image/jpeg', 'gif': 'image/gif'}
# capture 로 이 사용자가 올린 ImageAsset id — save 는 이 목록이나 칸에 이미 저장된 값만 받는다(남의 이미지 id 끼워 넣기 차단)
CAPTURE_SESSION_KEY = 'dig_form_captures'
CAPTURE_SESSION_MAX = 200
# 거치대 결과 불러오기 — 그 항목의 최근 검사 결과(설계 2026-10-21 §7)
RIG_RESULT_DAYS = 30
RIG_RESULT_LIMIT = 50

IMG_TAG = re.compile(r'<img\b[^>]*>', re.IGNORECASE)
IMG_SRC = re.compile(r'''\bsrc\s*=\s*["']([^"']*)["']''', re.IGNORECASE)
IMG_URL = re.compile(r'^/media/dig-form-image/(\d+)/$')
IMG_URL_IN_HTML = re.compile(r'/media/dig-form-image/(\d+)/')


def image_url(file_id):
    return f'/media/dig-form-image/{file_id}/'


def image_path(attach):
    return Path(settings.MEDIA_ROOT) / FOLDERS[(attach.TableName, attach.AttachName)] / attach.PhysicFileName


def save_upload(uploaded, user, table=IMAGE_TABLE, attach_name=IMAGE_ATTACH):
    """이미지를 검사해 저장하고 연결되지 않은 첨부(DataPk=0)를 만든다. 기본은 참고사진, 이미지 칸은 CELL_TABLE·CELL_ATTACH."""
    folder_name = FOLDERS[(table, attach_name)]
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
    folder = Path(settings.MEDIA_ROOT) / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    uploaded.seek(0)
    with open(folder / name, 'wb') as out:
        for chunk in uploaded.chunks():
            out.write(chunk)
    attach = AttachFile(TableName=table, DataPk=0, AttachName=attach_name, FileIndex=0,
                        FileName=uploaded.name[:100], PhysicFileName=name, ExtName=ext,
                        FilePath=folder_name, FileSize=uploaded.size)
    attach.set_audit(user)
    attach.save()
    return {'success': True, 'fileId': attach.id, 'url': image_url(attach.id)}


def find_cell_image(value, item_result_id, user):
    """이미지 칸에 저장할 값(첨부 id 글자) → 첨부 행. 이 사용자가 올린 연결 전 첨부이거나 이 칸에 이미 연결된 첨부만 받는다.

    호출부 트랜잭션 안에서 부른다. 칸 결과가 아직 없으면 item_result_id 는 None 이다.
    """
    attach = None
    if str(value).isdigit():
        attach = AttachFile.objects.select_for_update().filter(
            pk=int(value), TableName=CELL_TABLE, AttachName=CELL_ATTACH).first()
    if attach is None or not ((attach.DataPk == 0 and attach._creater_id == user.id)
                              or (item_result_id and attach.DataPk == item_result_id)):
        raise ValueError('이미지 정보를 찾을 수 없습니다. 이미지를 다시 올려 주세요.')
    return attach


def link_cell_image(attach, item_result_id, user):
    """칸 결과에 이미지 첨부를 연결하고, 그 칸에 연결돼 있던 다른 첨부 행은 지운다(attach=None 이면 모두).

    파일은 지우지 않는다 — 참고사진과 같은 규칙. 호출부 트랜잭션 안에서, 칸 결과를 저장한 뒤 부른다.
    """
    linked = AttachFile.objects.filter(TableName=CELL_TABLE, AttachName=CELL_ATTACH, DataPk=item_result_id)
    if attach is not None:
        linked = linked.exclude(pk=attach.pk)
        if attach.DataPk != item_result_id:
            attach.DataPk = item_result_id
            attach.set_audit(user)
            attach.save()
    linked.delete()


def check_ref_images(file_ids, user):
    """고정 이미지 칸에 넣을 첨부 id 가 쓸 수 있는 것인지 — 이 사용자가 올린 연결 전 첨부이거나, 이미 어느 칸에 연결된 고정 이미지
    (같은 양식의 이전 버전·불러온 양식)다. 아니면 ValueError."""
    ids = set(file_ids)
    if not ids:
        return
    files = {f.id: f for f in AttachFile.objects.filter(id__in=ids, TableName=REF_TABLE, AttachName=REF_ATTACH)}
    for file_id in ids:
        attach = files.get(file_id)
        if attach is None or (attach.DataPk == 0 and attach._creater_id != user.id):
            raise ValueError('고정 이미지 정보를 찾을 수 없습니다. 이미지를 다시 넣어 주세요.')


def link_ref_images(items, user):
    """저장한 고정 이미지 칸(ResultType='R', Content=첨부 id)에 첨부를 연결한다. 호출부 트랜잭션 안에서, 칸을 저장한 뒤 부른다.

    - 연결 전 첨부(DataPk=0) → 이 칸에 연결
    - 다른 칸(이전 버전·불러온 양식)에 연결된 첨부 → 같은 파일로 첨부 행을 복제해 이 칸에 연결하고 칸 Content 를 새 id 로 바꾼다
    이전 버전의 칸과 첨부는 그대로 둔다 — 완료된 결과는 옛 그림을 그대로 보인다.
    """
    cells = [i for i in items if i.ResultType == 'R' and (i.Content or '').isdigit()]
    if not cells:
        return
    files = {f.id: f for f in AttachFile.objects.select_for_update().filter(
        id__in={int(i.Content) for i in cells}, TableName=REF_TABLE, AttachName=REF_ATTACH)}
    for item in cells:
        attach = files.get(int(item.Content))
        if attach is None:
            raise ValueError('고정 이미지 정보를 찾을 수 없습니다. 이미지를 다시 넣어 주세요.')
        if attach.DataPk == 0:
            attach.DataPk = item.id
            attach.set_audit(user)
            attach.save()
            continue
        if attach.DataPk == item.id:
            continue
        copied = AttachFile(TableName=REF_TABLE, DataPk=item.id, AttachName=REF_ATTACH, FileIndex=attach.FileIndex,
                            FileName=attach.FileName, PhysicFileName=attach.PhysicFileName, ExtName=attach.ExtName,
                            FilePath=attach.FilePath, FileSize=attach.FileSize)
        copied.set_audit(user)
        copied.save()
        item.Content = str(copied.id)
        item.save(update_fields=['Content'])


def unlink_ref_images(item_ids):
    """지우는 칸의 고정 이미지 첨부 행을 지운다(파일은 다른 행이 쓸 수 있어 남긴다)."""
    AttachFile.objects.filter(TableName=REF_TABLE, AttachName=REF_ATTACH, DataPk__in=list(item_ids)).delete()


def vision_links(cell_ids):
    """칸 id 목록 → {칸 id: 연결된 비전검사항목}. 사진 넣기 팝업의 머리·Overlay 와 `비전: <코드>` 표시에 쓴다."""
    links = dict(DigFormItem.objects.filter(id__in=cell_ids).exclude(VisionItem=None).values_list('id', 'VisionItem_id'))
    if not links:
        return {}
    with tenant_atomic():
        items = {i.id: i for i in InspectionItem.objects.for_tenant(current_tenant())
                 .filter(id__in=set(links.values())).select_related('overlay')}
    out = {}
    for cell_id, item_id in links.items():
        item = items.get(item_id)
        if item is None:
            continue
        overlay = getattr(item, 'overlay', None)
        # 유형·촬영 방식 — 화면이 칸의 버튼을 정한다(거치대면 [거치대 결과 불러오기], 치수 측정은 그것만)
        out[cell_id] = {'id': item.id, 'code': item.code, 'name': item.name, 'status': item.status,
                        'overlay_opacity': overlay.opacity if overlay is not None and overlay.visible else None,
                        'task_type': item.task_type, 'capture_method': item.capture_method}
    return out


def capture_image(vision_item_id, uploaded, user):
    """연결된 비전검사항목에 사진을 올리고 ImageAsset id 를 돌려준다. 업로드 권한은 호출부(검사작성 W)가 본다 — 배정은 보지 않는다.

    같은 장면을 다시 찍는 일이 있어 중복을 받는다(allow_duplicate). 라벨링 대기로 들어간다.
    """
    from domain.services.data.image import ImageService

    if uploaded is None:
        raise ValueError('이미지 파일이 없습니다.')
    with tenant_atomic():
        item = InspectionItem.objects.for_tenant(current_tenant()).filter(pk=vision_item_id).first()
        if item is None:
            raise ValueError('연결된 비전검사항목을 찾을 수 없습니다.')
        if item.status != InspectionItem.Status.ACTIVE:
            raise ValueError('중지된 비전검사항목이라 사진을 넣을 수 없습니다.')
        if item.task_type == InspectionItem.TaskType.MEASUREMENT:
            raise ValueError('치수 측정 비전검사항목에는 사진을 넣을 수 없습니다.')
        result = ImageService.upload_images(item, [uploaded], actor=user, requires_labeling=True, allow_duplicate=True,
                                     channel=ImageAsset.Channel.FORM)
    if result['rejected']:
        raise ValueError(result['rejected'][0]['reason'])
    return result['uploaded'][0]['id']


def find_cell_asset(value, vision_item_id, saved_value, captured_ids):
    """연결된 이미지 칸에 저장할 값(ImageAsset id 글자) → id. 칸에 이미 저장된 값이거나, 이 사용자가 이번 세션에
    capture 로 올린 그 비전검사항목의 이미지만 받는다. 이미 저장된 값은 다시 보지 않는다(항목이 지워져도 저장이 막히지 않게).
    """
    value = str(value)
    if value == saved_value:
        return int(value)
    if value.isdigit() and int(value) in captured_ids:
        with tenant_atomic():
            if ImageAsset.objects.for_tenant(current_tenant()).filter(pk=int(value), dataset__item_id=vision_item_id).exists():
                return int(value)
    raise ValueError('이미지 정보를 찾을 수 없습니다. 이미지를 다시 올려 주세요.')


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


def rig_results(vision_item_id):
    """그 항목의 최근 30일 검사 결과 중 이미지가 있는 것, 최신순 50건 — 거치대 결과 불러오기 팝업의 목록."""
    since = datetime.datetime.now() - datetime.timedelta(days=RIG_RESULT_DAYS)
    rows = (VisionInspection.objects.filter(item_id=vision_item_id, image_asset__isnull=False, created_at__gte=since)
            .select_related('client').order_by('-created_at')[:RIG_RESULT_LIMIT])
    return [{'id': r.id, 'created': r.created_at.strftime('%Y-%m-%d %H:%M:%S'), 'client_name': r.client.name,
             'status': r.status, 'abnormal': r.abnormal, 'judgement': judgement_text(r), 'measured': measured_rows(r),
             'asset_id': r.image_asset_id} for r in rows]


def rig_result_asset(vision_item_id, inspection_id):
    """그 항목의 검사 결과면 그 ImageAsset id. 기간은 보지 않는다(목록을 연 뒤 30일이 지나도 넣는다)."""
    row = VisionInspection.objects.filter(pk=str(inspection_id or ''), item_id=vision_item_id,
                                          image_asset__isnull=False).first()
    if row is None:
        raise ValueError('불러올 검사 결과를 찾을 수 없습니다.')
    return row.image_asset_id


def rig_summaries(asset_ids):
    """ImageAsset id → 그 이미지를 만든 검사 결과의 판정 {judgement, measured, created}. 거치대 검사가 아닌 이미지는 없다."""
    rows = VisionInspection.objects.filter(image_asset_id__in=set(asset_ids)).order_by('created_at')
    return {r.image_asset_id: {'judgement': judgement_text(r), 'measured': measured_rows(r),
                               'created': r.created_at.strftime('%Y-%m-%d %H:%M')} for r in rows}

