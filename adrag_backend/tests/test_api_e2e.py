"""Deployed API response smoke tests.

These tests call a running backend.  They are opt-in so the normal unit-test
suite never changes a developer or shared database by accident.

Required environment variables:
    RUN_API_E2E=1
    API_ADMIN_ID=admin
    API_ADMIN_PASSWORD=<password>

Optional:
    API_BASE_URL=http://localhost:8081/api
    API_TEST_MUTATIONS=1       Enable create/update/delete tests.
    API_TEST_FILE=/path/to/a/small.pdf

Department and user deletion APIs do not exist. Mutation tests therefore
deactivate the records they create, but the records remain in the database.
Run mutation tests only against a disposable test environment.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest


pytestmark = pytest.mark.e2e


def _enabled(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes"}


def _assert_response(response: httpx.Response, expected_status: int) -> dict:
    assert response.status_code == expected_status, (
        f"{response.request.method} {response.request.url} returned "
        f"{response.status_code}: {response.text}"
    )
    if not response.content:
        return {}
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type, response.headers
    return response.json()


@pytest.fixture(scope="session")
def api() -> httpx.Client:
    if not _enabled("RUN_API_E2E"):
        pytest.skip("set RUN_API_E2E=1 to run deployed API tests")

    admin_id = os.getenv("API_ADMIN_ID")
    admin_password = os.getenv("API_ADMIN_PASSWORD")
    if not admin_id or not admin_password:
        pytest.skip("API_ADMIN_ID and API_ADMIN_PASSWORD are required")

    base_url = os.getenv("API_BASE_URL", "http://localhost:8081/api").rstrip("/")
    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        response = client.post(
            "/auth/login",
            json={"user_id": admin_id, "password": admin_password},
        )
        body = _assert_response(response, 200)
        assert body["role"] == "admin"
        assert body["access_token"]
        client.headers["Authorization"] = f"Bearer {body['access_token']}"
        yield client


@pytest.fixture
def mutations_enabled() -> None:
    if not _enabled("API_TEST_MUTATIONS"):
        pytest.skip("set API_TEST_MUTATIONS=1 against a disposable environment")


def test_auth_login_response(api: httpx.Client) -> None:
    # The session fixture performed the real login and only exists after its
    # response contract (role and access_token) was validated.
    assert api.headers["Authorization"].startswith("Bearer ")


def test_auth_me_response(api: httpx.Client) -> None:
    body = _assert_response(api.get("/auth/me"), 200)
    assert body["user_id"] == os.environ["API_ADMIN_ID"]
    assert body["role"] == "admin"
    assert body["is_admin"] is True


def test_query_collections_response(api: httpx.Client) -> None:
    body = _assert_response(api.get("/query/collections"), 200)
    assert isinstance(body["collections"], list)
    assert "user_id" in body


@pytest.mark.parametrize("params", [{}, {"include_all": "true"}])
def test_collections_response(api: httpx.Client, params: dict[str, str]) -> None:
    body = _assert_response(api.get("/collections", params=params), 200)
    assert isinstance(body["collections"], list)
    assert body["total"] == len(body["collections"])


def test_ingest_documents_response(api: httpx.Client) -> None:
    body = _assert_response(api.get("/ingest/documents"), 200)
    assert isinstance(body["documents"], list)
    assert body["total"] == len(body["documents"])


def test_admin_summary_response(api: httpx.Client) -> None:
    summary = _assert_response(api.get("/admin/summary"), 200)
    assert {"total_users", "active_departments", "unassigned_users"} <= summary.keys()


def test_admin_departments_response(api: httpx.Client) -> None:
    departments = _assert_response(api.get("/admin/departments"), 200)
    assert isinstance(departments, list)


def test_admin_topics_response(api: httpx.Client) -> None:
    topics = _assert_response(api.get("/admin/topics"), 200)
    assert isinstance(topics["topics"], list)


def test_admin_users_response(api: httpx.Client) -> None:
    users = _assert_response(api.get("/admin/users"), 200)
    assert isinstance(users["items"], list)
    assert isinstance(users["total"], int)


def test_collection_crud_responses(
    api: httpx.Client,
    mutations_enabled: None,
) -> None:
    suffix = uuid4().hex[:10]
    created = _assert_response(
        api.post(
            "/collections",
            json={"name": f"pytest-{suffix}", "description": "pytest e2e"},
        ),
        201,
    )
    collection_id = created["collection_id"]

    try:
        assert created["collection_name"] == f"pytest-{suffix}"
        updated = _assert_response(
            api.put(
                f"/collections/{collection_id}",
                json={"description": "pytest e2e updated"},
            ),
            200,
        )
        assert updated["collection_desc"] == "pytest e2e updated"
    finally:
        _assert_response(api.delete(f"/collections/{collection_id}"), 200)


def test_admin_department_user_and_permissions_responses(
    api: httpx.Client,
    mutations_enabled: None,
) -> None:
    suffix = uuid4().hex[:10]
    department = _assert_response(
        api.post("/admin/departments", json={"name": f"pytest-{suffix}"}),
        201,
    )
    department_id = department["id"]

    user_id = f"pytest_{suffix}"
    user_created = False
    try:
        detail = _assert_response(
            api.get(f"/admin/departments/{department_id}"),
            200,
        )
        assert detail["name"] == f"pytest-{suffix}"

        updated_department = _assert_response(
            api.put(
                f"/admin/departments/{department_id}",
                json={"name": f"pytest-{suffix}-updated", "topic_names": []},
            ),
            200,
        )
        assert updated_department["name"] == f"pytest-{suffix}-updated"

        created_user = _assert_response(
            api.post(
                "/admin/users",
                json={
                    "login_id": user_id,
                    "name": "Pytest User",
                    "department_id": department_id,
                    "password": uuid4().hex,
                },
            ),
            201,
        )
        user_created = True
        assert created_user["id"] == user_id

        user = _assert_response(api.get(f"/admin/users/{user_id}"), 200)
        assert user["id"] == user_id

        updated_user = _assert_response(
            api.put(f"/admin/users/{user_id}", json={"name": "Pytest User Updated"}),
            200,
        )
        assert updated_user["name"] == "Pytest User Updated"

        permissions = _assert_response(
            api.get(f"/admin/users/{user_id}/permissions"),
            200,
        )
        assert isinstance(permissions["blocked_topics"], list)

        updated_permissions = _assert_response(
            api.put(
                f"/admin/users/{user_id}/permissions",
                json={"blocked_topics": []},
            ),
            200,
        )
        assert updated_permissions["blocked_topics"] == []
    finally:
        # There are no delete endpoints for these resources. Leave clearly
        # named, inactive records rather than active test accounts.
        if user_created:
            _assert_response(
                api.put(f"/admin/users/{user_id}", json={"is_active": False}),
                200,
            )
        _assert_response(
            api.put(
                f"/admin/departments/{department_id}",
                json={"is_active": False},
            ),
            200,
        )


def test_ingest_upload_file_and_delete_responses(
    api: httpx.Client,
    mutations_enabled: None,
) -> None:
    file_value = os.getenv("API_TEST_FILE")
    if not file_value:
        pytest.skip("set API_TEST_FILE to a small supported document")
    file_path = Path(file_value)
    if not file_path.is_file():
        pytest.skip(f"API_TEST_FILE does not exist: {file_path}")

    collections = _assert_response(
        api.get("/collections", params={"include_all": "true"}),
        200,
    )["collections"]
    if not collections:
        pytest.skip("at least one existing collection is required for upload")
    collection_name = collections[0]["qdrant_name"]

    with file_path.open("rb") as stream:
        uploaded = _assert_response(
            api.post(
                "/ingest/upload",
                data={"collection_name": collection_name, "parser_type": "docling"},
                files={"file": (file_path.name, stream, "application/octet-stream")},
                timeout=300.0,
            ),
            200,
        )
    document_id = uploaded["document_id"]

    try:
        documents = _assert_response(
            api.get("/ingest/documents", params={"collection_name": collection_name}),
            200,
        )
        assert document_id in {item["document_id"] for item in documents["documents"]}
        filtered_document = next(item for item in documents["documents"] if item["document_id"] == document_id)
        assert filtered_document["parser_type"] == "docling"

        file_response = api.get(f"/ingest/documents/{document_id}/file")
        assert file_response.status_code == 200, file_response.text
        assert file_response.content
    finally:
        deleted = _assert_response(
            api.delete(f"/ingest/documents/{document_id}"),
            200,
        )
        assert deleted["document_id"] == document_id


def test_auth_logout_response(api: httpx.Client) -> None:
    body = _assert_response(api.post("/auth/logout"), 200)
    assert "message" in body
