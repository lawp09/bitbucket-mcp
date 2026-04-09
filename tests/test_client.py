"""Tests for Bitbucket API client"""

import base64
import pytest
from src.client import BitbucketClient


def test_client_initialization():
    """Test that client initializes with correct auth header"""
    email = "test@example.com"
    token = "test_token_192_chars"
    workspace = "test_workspace"

    client = BitbucketClient(email, token, workspace)

    # Verify Basic Auth header is correct
    expected_auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    expected_header = f"Basic {expected_auth}"

    assert client.workspace == workspace
    assert client.client.headers["Authorization"] == expected_header
    assert client.client.headers["Content-Type"] == "application/json"
    assert client.client.headers["Accept"] == "application/json"


def test_base_url():
    """Test that base URL is set correctly"""
    client = BitbucketClient("test@example.com", "token", "workspace")
    assert client.base_url == "https://api.bitbucket.org/2.0"
    # httpx adds a trailing slash to base_url
    assert str(client.client.base_url) == "https://api.bitbucket.org/2.0/"


@pytest.mark.asyncio
async def test_client_context_manager():
    """Test client can be used as async context manager"""
    async with BitbucketClient("test@example.com", "token", "workspace") as client:
        assert client is not None
        assert client.client is not None

    # Client should be closed after context
    assert client.client.is_closed


@pytest.mark.asyncio
async def test_workspace_default():
    """Test that workspace defaults to configured workspace"""
    client = BitbucketClient("test@example.com", "token", "my_workspace")

    # Methods should use default workspace if not specified
    assert client.workspace == "my_workspace"


def test_auth_header_encoding():
    """Test that special characters in email/token are properly encoded"""
    email = "user+tag@example.com"
    token = "token_with_special_chars_!@#$%"
    workspace = "workspace"

    client = BitbucketClient(email, token, workspace)

    # Manually verify encoding
    expected_auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    expected_header = f"Basic {expected_auth}"

    assert client.client.headers["Authorization"] == expected_header

    # Verify it decodes back correctly
    auth_part = client.client.headers["Authorization"].replace("Basic ", "")
    decoded = base64.b64decode(auth_part).decode()
    assert decoded == f"{email}:{token}"


def test_new_methods_exist():
    """Test that new methods are present in the client"""
    client = BitbucketClient("test@example.com", "token", "workspace")

    # Check that the new methods exist
    assert hasattr(client, "get_repository_tags")
    assert hasattr(client, "get_pull_request_statuses")
    assert hasattr(client, "get_pull_request_diffstat")
    assert hasattr(client, "get_commit_statuses")

    # Check they are callable
    assert callable(getattr(client, "get_repository_tags"))
    assert callable(getattr(client, "get_pull_request_statuses"))
    assert callable(getattr(client, "get_pull_request_diffstat"))
    assert callable(getattr(client, "get_commit_statuses"))


@pytest.mark.asyncio
async def test_get_repository_tags_uses_refs_tags_endpoint_with_page_size_and_sort():
    """Test that get_repository_tags requests the tags endpoint with recent-first sorting."""
    tags_url = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo/refs/tags"
    response_payload = {
        "pagelen": 10,
        "size": 1,
        "page": 1,
        "values": [
            {
                "name": "v1.2.3",
                "target": {
                    "hash": "12185f94580331a0ec5c59bd9a004903a245818a",
                    "date": "2026-04-09T12:00:00+00:00",
                    "message": "release: ship 1.2.3"
                }
            }
        ]
    }

    with respx.mock:
        route = respx.get(tags_url).mock(return_value=httpx.Response(200, json=response_payload))
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            result = await client.get_repository_tags("my-repo", page_size=10)

        assert result["values"][0]["name"] == "v1.2.3"
        assert route.calls.last.request.url.params["sort"] == "-target.date"
        assert route.calls.last.request.url.params["pagelen"] == "10"


@pytest.mark.asyncio
async def test_get_repository_tags_accepts_limit_alias_for_backward_compatibility():
    """Test that get_repository_tags still accepts limit as an alias for page_size."""
    tags_url = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo/refs/tags"

    with respx.mock:
        route = respx.get(tags_url).mock(return_value=httpx.Response(200, json={"pagelen": 5, "size": 0, "page": 1, "values": []}))
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.get_repository_tags("my-repo", limit=5)

        assert route.calls.last.request.url.params["pagelen"] == "5"


def test_request_changes_methods_exist():
    """Test that request_changes and unrequest_changes methods are present in the client"""
    client = BitbucketClient("test@example.com", "token", "workspace")

    assert hasattr(client, "request_changes_pull_request")
    assert hasattr(client, "unrequest_changes_pull_request")
    assert callable(getattr(client, "request_changes_pull_request"))
    assert callable(getattr(client, "unrequest_changes_pull_request"))


def test_comment_pipeline_reviewer_methods_exist():
    """Test that comment CRUD, pipeline, and reviewer methods are present in the client"""
    client = BitbucketClient("test@example.com", "token", "workspace")

    methods = [
        "get_pull_request_comment",
        "update_pull_request_comment",
        "delete_pull_request_comment",
        "resolve_pull_request_comment",
        "reopen_pull_request_comment",
        "run_pipeline",
        "stop_pipeline",
        "get_effective_default_reviewers",
    ]

    for method in methods:
        assert hasattr(client, method), f"Missing method: {method}"
        assert callable(getattr(client, method)), f"Not callable: {method}"


def test_task_and_diff_methods_exist():
    """Test that PR task and diff methods are present in the client"""
    client = BitbucketClient("test@example.com", "token", "workspace")

    methods = [
        "get_pull_request_tasks",
        "get_pull_request_task",
        "create_pull_request_task",
        "update_pull_request_task",
        "delete_pull_request_task",
        "get_pull_request_patch",
        "get_pull_requests_pending_review",
    ]

    for method in methods:
        assert hasattr(client, method), f"Missing method: {method}"
        assert callable(getattr(client, method)), f"Not callable: {method}"


def test_draft_pr_methods_exist():
    """Test that draft PR methods are present in the client"""
    client = BitbucketClient("test@example.com", "token", "workspace")
    methods = ["publish_draft_pull_request"]
    for method in methods:
        assert hasattr(client, method), f"Missing method: {method}"
        assert callable(getattr(client, method)), f"Not callable: {method}"


def test_create_pull_request_task_accepts_comment_id():
    import inspect
    client = BitbucketClient("test@example.com", "token", "workspace")
    sig = inspect.signature(client.create_pull_request_task)
    assert "comment_id" in sig.parameters
    param = sig.parameters["comment_id"]
    assert param.default is None


import httpx
import respx


@pytest.mark.asyncio
async def test_update_pull_request_with_reviewers():
    """Test that update_pull_request sends reviewers in payload."""
    pr_url = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo/pullrequests/42"
    with respx.mock:
        route = respx.put(pr_url).mock(
            return_value=httpx.Response(200, json={"id": 1, "title": "Test", "reviewers": []})
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.update_pull_request(
                "my-repo", "42",
                reviewers=["{uuid-1}", "{uuid-2}"]
            )
        payload = route.calls.last.request.read()
        import json
        body = json.loads(payload)
        assert body["reviewers"] == [{"uuid": "{uuid-1}"}, {"uuid": "{uuid-2}"}]
        assert "title" not in body
        assert "description" not in body


@pytest.mark.asyncio
async def test_update_pull_request_reviewers_none_not_in_payload():
    """Test that reviewers=None does not add reviewers to payload."""
    pr_url = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo/pullrequests/42"
    with respx.mock:
        route = respx.put(pr_url).mock(
            return_value=httpx.Response(200, json={"id": 1, "title": "New title"})
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.update_pull_request("my-repo", "42", title="New title")
        import json
        body = json.loads(route.calls.last.request.read())
        assert "reviewers" not in body
        assert body["title"] == "New title"


@pytest.mark.asyncio
async def test_update_pull_request_reviewers_empty_list():
    """Test that reviewers=[] sends empty reviewers list (clears reviewers)."""
    pr_url = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo/pullrequests/42"
    with respx.mock:
        route = respx.put(pr_url).mock(
            return_value=httpx.Response(200, json={"id": 1, "title": "Test", "reviewers": []})
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.update_pull_request("my-repo", "42", reviewers=[])
        import json
        body = json.loads(route.calls.last.request.read())
        assert body["reviewers"] == []


@pytest.mark.asyncio
async def test_update_pull_request_reviewers_already_dict():
    """Test that reviewers passed as dicts are not double-wrapped."""
    pr_url = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo/pullrequests/42"
    with respx.mock:
        route = respx.put(pr_url).mock(
            return_value=httpx.Response(200, json={"id": 1, "title": "Test", "reviewers": []})
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.update_pull_request(
                "my-repo", "42",
                reviewers=[{"uuid": "{a2b9e5bf-1234}"}]
            )
        import json
        body = json.loads(route.calls.last.request.read())
        assert body["reviewers"] == [{"uuid": "{a2b9e5bf-1234}"}]


@pytest.mark.asyncio
async def test_update_pull_request_reviewers_mixed_str_and_dict():
    """Test that a mix of string and dict reviewers is normalized correctly."""
    pr_url = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo/pullrequests/42"
    with respx.mock:
        route = respx.put(pr_url).mock(
            return_value=httpx.Response(200, json={"id": 1, "title": "Test", "reviewers": []})
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.update_pull_request(
                "my-repo", "42",
                reviewers=["{uuid-str}", {"uuid": "{uuid-dict}"}]
            )
        import json
        body = json.loads(route.calls.last.request.read())
        assert body["reviewers"] == [{"uuid": "{uuid-str}"}, {"uuid": "{uuid-dict}"}]


@pytest.mark.asyncio
async def test_create_pull_request_with_reviewers_as_dicts():
    """Test that create_pull_request handles dict reviewers without double-wrapping."""
    pr_url = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo/pullrequests"
    with respx.mock:
        route = respx.post(pr_url).mock(
            return_value=httpx.Response(201, json={"id": 1, "title": "New PR"})
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.create_pull_request(
                "my-repo", "New PR", "Description",
                "feature-branch", "main",
                reviewers=[{"uuid": "{a2b9e5bf-1234}"}]
            )
        import json
        body = json.loads(route.calls.last.request.read())
        assert body["reviewers"] == [{"uuid": "{a2b9e5bf-1234}"}]


@pytest.mark.asyncio
async def test_create_pull_request_with_reviewers_as_strings():
    """Test that create_pull_request wraps string reviewers correctly."""
    pr_url = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo/pullrequests"
    with respx.mock:
        route = respx.post(pr_url).mock(
            return_value=httpx.Response(201, json={"id": 1, "title": "New PR"})
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.create_pull_request(
                "my-repo", "New PR", "Description",
                "feature-branch", "main",
                reviewers=["{uuid-1}", "{uuid-2}"]
            )
        import json
        body = json.loads(route.calls.last.request.read())
        assert body["reviewers"] == [{"uuid": "{uuid-1}"}, {"uuid": "{uuid-2}"}]
