"""Parser resource의 backend multipart 전송 계약 테스트."""

# 2026.08.27(sooyeon.choi) 추가 - 단계 6 서로 다른 서버 전송 모사
import hashlib

import pytest

from app.resources import uploader as resource_uploader


def test_uploads_resource_with_internal_auth_and_removes_parser_copy(monkeypatch, tmp_path):
    content = b"parser-resource"
    local = tmp_path / "resource.png"
    local.write_bytes(content)
    captured = {}

    class Response:
        status_code = 201
        text = ""

        @staticmethod
        def json():
            return {"resource": {"resource_path": "staging/job-1/originals/resource-1.png", "status": "staging"}}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        assert kwargs["files"]["file"][1].read() == content
        kwargs["files"]["file"][1].seek(0)
        return Response()

    monkeypatch.setenv("BACKEND_INTERNAL_URL", "http://backend:8000")
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "secret")
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    monkeypatch.setattr(resource_uploader.requests, "post", post)
    result = {"resources": [{
        "resource_id": "resource-1",
        "resource_type": "image",
        "relative_path": "resource.png",
        "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
        "mime_type": "image/png",
        "sheet_id": "sheet-1",
        "sheet_name": "부품",
        "from_cell": "D2",
        "to_cell": "D2",
    }]}

    resource_uploader.BackendResourceUploader().upload_result_resources(
        result, parse_job_id="job-1", document_id="doc-1"
    )

    assert captured["headers"] == {"X-INTERNAL-API-KEY": "secret"}
    assert captured["data"]["document_id"] == "doc-1"
    assert result["resources"][0]["status"] == "staging"
    assert not local.exists()


def test_rejects_parser_resource_path_traversal(monkeypatch, tmp_path):
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"outside")
    monkeypatch.setenv("BACKEND_INTERNAL_URL", "http://backend:8000")
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "secret")
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    result = {"resources": [{
        "resource_id": "resource-1",
        "relative_path": "../outside.png",
        "content_hash": "sha256:" + hashlib.sha256(b"outside").hexdigest(),
        "mime_type": "image/png",
    }]}

    with pytest.raises(ValueError, match="path traversal"):
        resource_uploader.BackendResourceUploader().upload_result_resources(
            result, parse_job_id="job-1", document_id="doc-1"
        )


# 2026.08.28(sooyeon.choi) 추가 - 요청별 callback_url 계약
def test_resolve_backend_url_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("BACKEND_INTERNAL_URL", "http://backend:8000")
    monkeypatch.delenv("BACKEND_CALLBACK_ALLOWLIST", raising=False)
    assert resource_uploader.resolve_backend_url(None) == "http://backend:8000"
    assert resource_uploader.resolve_backend_url("") == "http://backend:8000"


def test_resolve_backend_url_accepts_allowlisted_callback(monkeypatch):
    monkeypatch.setenv("BACKEND_INTERNAL_URL", "http://10.10.10.109:8000")
    monkeypatch.setenv("BACKEND_CALLBACK_ALLOWLIST", "http://10.7.6.9:8000, http://other:8000")
    assert resource_uploader.resolve_backend_url("http://10.7.6.9:8000/") == "http://10.7.6.9:8000"
    # 환경변수 기본값 자체도 항상 허용된다
    assert resource_uploader.resolve_backend_url("http://10.10.10.109:8000") == "http://10.10.10.109:8000"


def test_resolve_backend_url_rejects_unlisted_and_malformed(monkeypatch):
    monkeypatch.setenv("BACKEND_INTERNAL_URL", "http://10.10.10.109:8000")
    monkeypatch.setenv("BACKEND_CALLBACK_ALLOWLIST", "http://10.7.6.9:8000")
    with pytest.raises(ValueError, match="not allowed"):
        resource_uploader.resolve_backend_url("http://evil.example.com")
    with pytest.raises(ValueError, match="Invalid callback URL"):
        resource_uploader.resolve_backend_url("ftp://10.7.6.9:8000")
    with pytest.raises(ValueError, match="Invalid callback URL"):
        resource_uploader.resolve_backend_url("not-a-url")


def test_uploader_prefers_injected_backend_url(monkeypatch, tmp_path):
    content = b"parser-resource"
    (tmp_path / "resource.png").write_bytes(content)
    captured = {}

    class Response:
        status_code = 201
        text = ""

        @staticmethod
        def json():
            return {"resource": {"resource_path": "staging/job-1/originals/resource-1.png", "status": "staging"}}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setenv("BACKEND_INTERNAL_URL", "http://10.10.10.109:8000")
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "secret")
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    monkeypatch.setattr(resource_uploader.requests, "post", post)
    result = {"resources": [{
        "resource_id": "resource-1",
        "resource_type": "image",
        "relative_path": "resource.png",
        "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
        "mime_type": "image/png",
    }]}

    resource_uploader.BackendResourceUploader("http://10.7.6.9:8000").upload_result_resources(
        result, parse_job_id="job-1", document_id="doc-1"
    )

    # 전역 환경변수가 아니라 주입된 요청자 주소로 회신해야 한다
    assert captured["url"] == "http://10.7.6.9:8000/internal/ingest-jobs/job-1/resources"


# 2026.08.28(sooyeon.choi) 추가 - backend가 아닌 곳(nginx/SPA)에 닿은 경우 진단 가능해야 한다
def test_non_json_upload_response_does_not_expose_url_or_body(monkeypatch, tmp_path):
    (tmp_path / "resource.png").write_bytes(b"x")

    class HtmlResponse:
        status_code = 200
        text = "<!DOCTYPE html>\n<html lang=\"ko\">"
        headers = {"Content-Type": "text/html"}

        @staticmethod
        def json():
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setenv("BACKEND_INTERNAL_URL", "http://10.10.10.109")
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "secret")
    monkeypatch.setenv("PARSER_RESOURCE_ROOT", str(tmp_path))
    monkeypatch.setattr(resource_uploader.requests, "post", lambda url, **kw: HtmlResponse())
    result = {"resources": [{
        "resource_id": "resource-1",
        "relative_path": "resource.png",
        "content_hash": "sha256:" + hashlib.sha256(b"x").hexdigest(),
        "mime_type": "image/png",
    }]}

    with pytest.raises(RuntimeError) as excinfo:
        resource_uploader.BackendResourceUploader().upload_result_resources(
            result, parse_job_id="job-1", document_id="doc-1"
        )
    message = str(excinfo.value)
    assert "non-JSON" in message
    assert "http_status=200" in message
    assert "10.10.10.109" not in message
    assert "text/html" not in message
    assert "DOCTYPE" not in message
