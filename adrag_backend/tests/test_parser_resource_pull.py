"""파서 보관본을 backend가 회수하는 pull 경로 테스트."""

# 2026.08.28(sooyeon.choi) 추가 - 백엔드가 사설망/루프백일 때의 resource 전달
import hashlib

import pytest

from app.services import parser_resource_puller as puller_module
from app.services.parser_resource_puller import ParserResourcePuller, pull_parser_resources


CONTENT = b"png-bytes"
DIGEST = "sha256:" + hashlib.sha256(CONTENT).hexdigest()


class FakePuller(ParserResourcePuller):
    def __init__(self, entries):
        self.host = "http://parser"
        self.entries = entries
        self.discarded = []
        self.downloaded = []

    def list_resources(self, parse_job_id):
        return self.entries

    def download(self, parse_job_id, resource_id):
        self.downloaded.append(resource_id)
        return CONTENT

    def discard(self, parse_job_id):
        self.discarded.append(parse_job_id)


class FakeService:
    def __init__(self):
        self.staged = []

    async def stage_upload(self, upload, *, parse_job_id, metadata):
        payload = await upload.read(-1)
        self.staged.append({
            "payload": payload,
            "content_type": upload.content_type,
            "parse_job_id": parse_job_id,
            "metadata": metadata,
        })
        return metadata


@pytest.mark.asyncio
async def test_pull_stages_each_resource_and_discards_parser_copy():
    entries = [{
        "resource_id": "resource-1",
        "resource_type": "image",
        "content_hash": DIGEST,
        "mime_type": "image/png",
        "sheet_name": "부품",
        "from_cell": "D2",
        "linked_record_ids": ["rec-1"],
    }]
    service = FakeService()
    fake = FakePuller(entries)

    stored = await pull_parser_resources(service, "job-1", "doc-1", puller=fake)

    assert stored == 1
    assert fake.downloaded == ["resource-1"]
    assert fake.discarded == ["job-1"]
    staged = service.staged[0]
    assert staged["payload"] == CONTENT
    assert staged["content_type"] == "image/png"
    assert staged["parse_job_id"] == "job-1"
    assert staged["metadata"]["document_id"] == "doc-1"
    assert staged["metadata"]["sheet_name"] == "부품"
    assert staged["metadata"]["linked_record_ids"] == ["rec-1"]


@pytest.mark.asyncio
async def test_pull_without_resources_does_not_touch_backend():
    service = FakeService()
    fake = FakePuller([])

    stored = await pull_parser_resources(service, "job-1", "doc-1", puller=fake)

    assert stored == 0
    assert service.staged == []
    # 가져올 게 없으면 파서 정리 요청도 보내지 않는다
    assert fake.discarded == []


@pytest.mark.asyncio
async def test_pull_normalizes_singular_linked_record_id():
    entries = [{
        "resource_id": "resource-1",
        "content_hash": DIGEST,
        "mime_type": "image/png",
        "linked_record_id": "rec-9",
    }]
    service = FakeService()

    await pull_parser_resources(service, "job-1", "doc-1", puller=FakePuller(entries))

    assert service.staged[0]["metadata"]["linked_record_ids"] == ["rec-9"]
    # resource_type 기본값
    assert service.staged[0]["metadata"]["resource_type"] == "image"


def test_list_resources_treats_404_as_empty(monkeypatch):
    class Response:
        status_code = 404
        text = "not found"

    monkeypatch.setattr(puller_module.requests, "get", lambda *a, **k: Response())
    assert ParserResourcePuller(host="http://parser").list_resources("job-1") == []


def test_list_resources_raises_with_body_on_error(monkeypatch):
    class Response:
        status_code = 500
        text = "boom"

    monkeypatch.setattr(puller_module.requests, "get", lambda *a, **k: Response())
    with pytest.raises(RuntimeError, match="목록 조회 실패"):
        ParserResourcePuller(host="http://parser").list_resources("job-1")


def test_download_sends_api_key_header(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        content = CONTENT

    def get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(puller_module.requests, "get", get)
    data = ParserResourcePuller(host="http://parser/", api_key="k").download("job-1", "r-1")

    assert data == CONTENT
    assert captured["url"] == "http://parser/api/job/job-1/resources/r-1"
    assert captured["headers"] == {"X-API-KEY": "k"}


@pytest.mark.asyncio
async def test_pull_is_skipped_when_parser_host_is_not_configured():
    """파서 호스트가 없으면 조용히 건너뛴다(push로 이미 저장됐거나 파서 미사용)."""
    class NoHostPuller(FakePuller):
        def __init__(self):
            super().__init__([{"resource_id": "r", "content_hash": DIGEST, "mime_type": "image/png"}])
            self.host = ""

    service = FakeService()
    fake = NoHostPuller()

    assert await pull_parser_resources(service, "job-1", "doc-1", puller=fake) == 0
    assert service.staged == []
    assert fake.downloaded == []
