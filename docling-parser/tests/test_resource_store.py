"""pull 방식 resource 보관/조회/정리 계약 테스트."""

# 2026.08.28(sooyeon.choi) 추가 - 백엔드가 파서에서 resource를 가져가는 경로
import hashlib

import pytest

from app.resources.store import ParserResourceStore


def _result(tmp_path, name="resource.png", content=b"image-bytes"):
    (tmp_path / name).write_bytes(content)
    return {"resources": [{
        "resource_id": "resource-1",
        "resource_type": "image",
        "relative_path": name,
        "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
        "mime_type": "image/png",
        "sheet_name": "부품",
    }]}


def test_retain_moves_file_and_exposes_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    store = ParserResourceStore()
    result = _result(tmp_path)

    retained = store.retain(result, parse_job_id="job-1")

    assert len(retained) == 1
    assert retained[0]["resource_id"] == "resource-1"
    assert retained[0]["file_size"] == len(b"image-bytes")
    # 원본은 job 디렉터리로 이동되어 원래 위치에는 남지 않는다
    assert not (tmp_path / "resource.png").exists()
    path = store.path_of("job-1", "resource-1")
    assert path is not None and path.read_bytes() == b"image-bytes"
    # 결과 문서에 parser 로컬 경로를 남기지 않는다
    assert "relative_path" not in result["resources"][0]
    assert "local_path" not in result["resources"][0]
    assert result["resources"][0]["status"] == "retained"


def test_list_and_path_are_scoped_per_job(monkeypatch, tmp_path):
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    store = ParserResourceStore()
    store.retain(_result(tmp_path), parse_job_id="job-1")

    assert store.list("job-1") is not None
    assert store.list("job-2") is None
    assert store.path_of("job-2", "resource-1") is None
    assert store.path_of("job-1", "unknown") is None


def test_discard_removes_files_and_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    store = ParserResourceStore()
    store.retain(_result(tmp_path), parse_job_id="job-1")
    path = store.path_of("job-1", "resource-1")

    store.discard("job-1")

    assert store.list("job-1") is None
    assert not path.exists()


def test_manifest_restores_resources_after_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    first = ParserResourceStore()
    first.retain(_result(tmp_path), parse_job_id="job-1")

    restored = ParserResourceStore()

    assert restored.list("job-1") is not None
    path = restored.path_of("job-1", "resource-1")
    assert path is not None and path.read_bytes() == b"image-bytes"


def test_restore_ignores_corrupt_manifest(monkeypatch, tmp_path):
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    job_dir = tmp_path / "jobs" / "broken-job"
    job_dir.mkdir(parents=True)
    (job_dir / "manifest.json").write_text("{broken", encoding="utf-8")

    store = ParserResourceStore()

    assert store.list("broken-job") is None


def test_purge_expired_only_removes_old_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    store = ParserResourceStore()
    store.retain(_result(tmp_path), parse_job_id="job-1")

    assert store.purge_expired(ttl_seconds=3600) == []
    assert store.list("job-1") is not None

    assert store.purge_expired(ttl_seconds=-1) == ["job-1"]
    assert store.list("job-1") is None


def test_retain_rejects_path_traversal(monkeypatch, tmp_path):
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"outside")
    store = ParserResourceStore()
    result = {"resources": [{
        "resource_id": "resource-1",
        "relative_path": "../outside.png",
        "mime_type": "image/png",
    }]}

    with pytest.raises(ValueError, match="path traversal"):
        store.retain(result, parse_job_id="job-1")
    assert outside.exists()


def test_retain_without_resources_is_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    store = ParserResourceStore()
    assert store.retain({"resources": []}, parse_job_id="job-1") == []
    assert store.list("job-1") is None
