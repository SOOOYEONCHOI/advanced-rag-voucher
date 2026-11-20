"""파일 저장 폴더 계산.

전에는 SQLite 시절 설정 SQLITE_DB_PATH(<데이터>/db/x.db)의 위치에서 폴더를 정했다. 이제 원본 보관 폴더
UPLOADED_FILES_BASE_DIR(<데이터>/data)를 기준으로 정하며, 결과 경로는 전과 같다.

    원본 보관 = UPLOADED_FILES_BASE_DIR                         (예: /data/data)
    청크 결과 = CHUNK_OUTPUT_DIR 또는 <상위 폴더>/chunk          (예: /data/chunk)
    적재 대기 = INGEST_QUEUE_DIR 또는 <상위 폴더>/db/ingest_jobs (예: /data/db/ingest_jobs)

테스트가 ``app.core.config`` 모듈을 가짜로 바꿔 끼우는 경우가 있어서 config에 두지 않고 따로 둔다.
"""

from pathlib import Path


def get_file_storage_dir(settings) -> Path:
    """원본 업로드 파일 보관 폴더."""
    return Path(settings.uploaded_files_base_dir)


def _data_root(settings) -> Path:
    return get_file_storage_dir(settings).parent


def get_chunk_output_dir(settings) -> Path:
    """청크 결과 저장 폴더."""
    value = getattr(settings, "chunk_output_dir", "") or ""
    return Path(value) if value.strip() else _data_root(settings) / "chunk"


def get_ingest_queue_dir(settings) -> Path:
    """업로드 파일을 잠시 두는 적재 대기 폴더."""
    value = getattr(settings, "ingest_queue_dir", "") or ""
    return Path(value) if value.strip() else _data_root(settings) / "db" / "ingest_jobs"
