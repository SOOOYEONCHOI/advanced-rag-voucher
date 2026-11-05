"""업로드·파생 파일의 단일 저장 루트.

모든 파일은 `settings.STORAGE_ROOT` 아래에만 저장한다. 이 경로는 nginx가
직접 서비스하지 않으며, 반드시 권한을 확인하는 View를 거쳐 제공한다.
"""
from pathlib import Path, PurePath

from django.conf import settings


class UnsafePathError(ValueError):
    """STORAGE_ROOT 밖을 가리키는 경로."""


def storage_root() -> Path:
    return Path(settings.STORAGE_ROOT)


def resolve(*parts) -> Path:
    """STORAGE_ROOT 기준 경로를 만든다. 루트를 벗어나면 거부한다.

    `..` 를 포함한 사용자 입력이 섞여도 루트 밖으로 나갈 수 없다.
    """
    root = storage_root().resolve()
    target = root.joinpath(*[str(p) for p in parts]).resolve()
    if target != root and root not in target.parents:
        raise UnsafePathError(f'STORAGE_ROOT 밖의 경로다: {target}')
    return target




# --------------------------------------------------------------------------
# 데이터 관리 도메인 업로드 경로
#
# Django `FileField(upload_to=...)` 가 부르므로 MEDIA_ROOT 기준 **상대 경로**를
# 돌려준다. `resolve()` 는 쓰지 않는다.
# --------------------------------------------------------------------------

def item_image_upload_path(instance, filename):
    suffix = PurePath(filename).suffix.lower()
    return f'tenants/{instance.tenant_id}/items/{instance.dataset.item_id}/images/{instance.storage_key}{suffix}'


def item_image_thumbnail_upload_path(instance, filename):
    return f'tenants/{instance.tenant_id}/items/{instance.dataset.item_id}/thumbnails/{instance.storage_key}.webp'


# 표준 이미지 테이블은 0009 에서 지웠다. 0001_initial 이 이 함수를 참조해 남긴다.
def standard_image_upload_path(instance, filename):
    suffix = PurePath(filename).suffix.lower()
    return f'tenants/{instance.tenant_id}/items/{instance.item_id}/standards/{instance.storage_key}{suffix}'


def item_cover_upload_path(instance, filename):
    suffix = PurePath(filename).suffix.lower()
    return f'tenants/{instance.tenant_id}/items/{instance.id}/cover{suffix}'


def export_upload_path(instance, filename):
    return f'tenants/{instance.tenant_id}/exports/{instance.storage_key}/{filename}'
