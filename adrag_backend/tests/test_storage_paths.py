import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.storage_paths import get_chunk_output_dir, get_file_storage_dir, get_ingest_queue_dir


def _old_paths(sqlite_db_path: str):
    """제거 전 계산식(ingest_service·routes/ingest)."""
    db_file = Path(sqlite_db_path)
    return db_file.parent.parent / "data", db_file.parent.parent / "chunk", db_file.parent / "ingest_jobs"


def _new_paths(settings):
    return get_file_storage_dir(settings), get_chunk_output_dir(settings), get_ingest_queue_dir(settings)


@pytest.mark.parametrize(
    "old_sqlite, uploaded",
    [
        ("/data/db/db_rag_metadata.db", "/data/data"),                 # 운영 .env 값
        ("./instance/db/db_rag_metadata.db", "instance/data"),         # 로컬·dev 기본값
    ],
)
def test_same_folders_as_before(old_sqlite, uploaded):
    settings = SimpleNamespace(uploaded_files_base_dir=uploaded, chunk_output_dir="", ingest_queue_dir="")
    assert _new_paths(settings) == _old_paths(old_sqlite)


def test_explicit_dirs_override_defaults(tmp_path):
    settings = SimpleNamespace(
        uploaded_files_base_dir=str(tmp_path / "data"),
        chunk_output_dir=str(tmp_path / "elsewhere" / "chunk"),
        ingest_queue_dir=str(tmp_path / "queue"),
    )
    assert get_chunk_output_dir(settings) == tmp_path / "elsewhere" / "chunk"
    assert get_ingest_queue_dir(settings) == tmp_path / "queue"


def test_settings_without_new_fields_use_defaults():
    """테스트용 가짜 settings처럼 새 항목이 없어도 기본 규칙으로 계산한다."""
    settings = SimpleNamespace(uploaded_files_base_dir="/data/data")
    assert get_chunk_output_dir(settings) == Path("/data/chunk")
    assert get_ingest_queue_dir(settings) == Path("/data/db/ingest_jobs")


def test_settings_field_removed():
    """config.py에 sqlite_db_path 필드가 없고 새 항목 기본값은 비어 있다.

    다른 테스트가 sys.modules의 app.core.config를 가짜로 바꿔 끼울 수 있어서 파일에서 직접 읽는다.
    """
    path = Path(__file__).resolve().parents[1] / "app" / "core" / "config.py"
    spec = importlib.util.spec_from_file_location("_config_for_storage_paths_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fields = module.Settings.model_fields
    assert "sqlite_db_path" not in fields
    assert fields["chunk_output_dir"].default == ""
    assert fields["ingest_queue_dir"].default == ""
    assert fields["uploaded_files_base_dir"].default == "instance/data"
