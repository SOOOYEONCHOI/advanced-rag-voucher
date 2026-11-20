# 2026.10.30(sooyeon.choi) 추가 - 원본 문서 열기 경로 계산 검증
#   운영은 소스(/app)와 데이터(/data)가 따로 마운트되어 "페이지 이동"이 "원본 문서를 열 수 없습니다"로 실패했다.
#   저장(save)·삭제(delete)·원본 열기(GET /ingest/documents/{id}/file)가 같은 저장 폴더 기준을 쓰는지 본다.
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routes import ingest as ingest_routes
from app.services.ingest_service import FileStorageManager, get_original_file_storage

_ADMIN = {"user_id": "admin", "is_admin": True}


def _prod_like_storage(tmp_path):
    """운영 구조 재현: UPLOADED_FILES_BASE_DIR=<데이터>/data → 원본 저장 폴더 <데이터>/data (백엔드 소스 폴더 밖)."""
    data_root = tmp_path / "mnt_data"
    (data_root / "db").mkdir(parents=True)
    settings = SimpleNamespace(uploaded_files_base_dir=str(data_root / "data"))
    return settings, get_original_file_storage(settings)


def _save(storage, tmp_path, name="sample.pdf"):
    src = tmp_path / name
    src.write_bytes(b"%PDF-1.4 test")
    return asyncio.run(storage.save(str(src), name, "doc-1"))


def test_save_then_resolve_outside_backend_root(tmp_path):
    settings, storage = _prod_like_storage(tmp_path)
    _, source_path, _ = _save(storage, tmp_path)

    assert source_path.startswith("mnt_data/data/")   # 운영이면 data/data/… 로 기록된다
    assert "\\" not in source_path
    resolved = storage.resolve(source_path)
    assert resolved.is_file()
    assert resolved.parent.parent.parent == (tmp_path / "mnt_data" / "data").resolve()


def test_resolve_local_instance_format(tmp_path):
    """로컬 형식(instance/data/…) 기존 값도 그대로 풀린다."""
    storage = FileStorageManager(tmp_path / "adrag_backend" / "instance" / "data")
    target = tmp_path / "adrag_backend" / "instance" / "data" / "2026" / "10" / "x.xlsx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")

    assert storage.resolve("instance/data/2026/10/x.xlsx") == target.resolve()


@pytest.mark.parametrize("bad", ["../../etc/passwd", "instance/../../outside.pdf", ""])
def test_resolve_rejects_outside_storage(tmp_path, bad):
    storage = FileStorageManager(tmp_path / "adrag_backend" / "instance" / "data")
    with pytest.raises(ValueError):
        storage.resolve(bad)


def test_delete_ignores_outside_storage(tmp_path):
    storage = FileStorageManager(tmp_path / "adrag_backend" / "instance" / "data")
    outside = tmp_path / "adrag_backend" / "keep.txt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("keep")

    storage.delete("../keep.txt")   # 저장 폴더 밖 → 지우지 않는다
    assert outside.exists()


class _FakeDb:
    def __init__(self, source_path):
        self.source_path = source_path

    def execute_query(self, _sql, params):
        return [{
            "document_id": params[0], "source_path": self.source_path, "original_filename": "원본.pdf",
            "security_level": "public", "document_type": "manual", "source_collection": "documents",
        }]


def _open(monkeypatch, settings, source_path, principal=_ADMIN):
    monkeypatch.setattr(ingest_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(ingest_routes, "get_database_manager", lambda *_: _FakeDb(source_path))
    return asyncio.run(ingest_routes.open_original_document("doc-1", principal=principal))


def test_open_original_document_prod_layout(tmp_path, monkeypatch):
    """API-원본 열기: 소스 폴더 밖 저장 폴더의 파일을 정상 반환한다(수정 전에는 404)."""
    settings, storage = _prod_like_storage(tmp_path)
    _, source_path, _ = _save(storage, tmp_path)

    response = _open(monkeypatch, settings, source_path)
    assert response.path == str(storage.resolve(source_path))
    assert response.media_type == "application/pdf"


def test_open_original_document_errors(tmp_path, monkeypatch):
    settings, _ = _prod_like_storage(tmp_path)

    with pytest.raises(HTTPException) as escaped:
        _open(monkeypatch, settings, "../../etc/passwd")
    assert escaped.value.status_code == 400

    with pytest.raises(HTTPException) as missing:
        _open(monkeypatch, settings, "mnt_data/data/2026/10/none.pdf")
    assert missing.value.status_code == 404


def test_open_original_document_permission_unchanged(tmp_path, monkeypatch):
    """권한 판단은 그대로 — 접근 컬렉션이 없으면 경로 계산 전에 403(절대 규칙 8)."""
    settings, storage = _prod_like_storage(tmp_path)
    _, source_path, _ = _save(storage, tmp_path)
    monkeypatch.setattr(ingest_routes, "_get_user_accessible", lambda _p: (set(), set()))

    with pytest.raises(HTTPException) as denied:
        _open(monkeypatch, settings, source_path, principal={"user_id": "u1", "is_admin": False})
    assert denied.value.status_code == 403
