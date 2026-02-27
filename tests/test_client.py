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
    assert hasattr(client, "get_pull_request_statuses")
    assert hasattr(client, "get_pull_request_diffstat")
    assert hasattr(client, "get_commit_statuses")

    # Check they are callable
    assert callable(getattr(client, "get_pull_request_statuses"))
    assert callable(getattr(client, "get_pull_request_diffstat"))
    assert callable(getattr(client, "get_commit_statuses"))


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
