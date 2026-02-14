"""Tests for comment reply functionality"""

import json

import pytest
import respx
from httpx import Response
from src.client import BitbucketClient
from src.utils.transformers import slim_comment


@pytest.mark.asyncio
@respx.mock
async def test_client_reply_payload_includes_parent():
    """Test that reply comment includes parent field in payload"""
    email = "test@example.com"
    token = "test_token"
    workspace = "test_workspace"
    repo_slug = "test-repo"
    pr_id = "1"
    content = "reply text"
    parent_id = 123

    client = BitbucketClient(email, token, workspace)

    # Mock the POST request
    mock_response = {
        "id": 456,
        "content": {"raw": content},
        "parent": {"id": parent_id},
        "user": {"display_name": "Test User"},
        "created_on": "2025-01-01T00:00:00Z",
        "updated_on": "2025-01-01T00:00:00Z"
    }

    route = respx.post(
        f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/comments"
    ).mock(return_value=Response(200, json=mock_response))

    # Call the method with parent_id
    await client.add_pull_request_comment(
        repo_slug=repo_slug,
        pull_request_id=pr_id,
        content=content,
        parent_id=parent_id
    )

    # Verify the request was made
    assert route.called
    request = route.calls.last.request

    # Verify the payload contains parent field
    payload = json.loads(request.content)
    assert "parent" in payload
    assert payload["parent"]["id"] == parent_id
    assert payload["content"]["raw"] == content

    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_client_comment_payload_excludes_parent_when_none():
    """Test that comment without parent_id excludes parent field from payload"""
    email = "test@example.com"
    token = "test_token"
    workspace = "test_workspace"
    repo_slug = "test-repo"
    pr_id = "1"
    content = "regular comment"

    client = BitbucketClient(email, token, workspace)

    # Mock the POST request
    mock_response = {
        "id": 789,
        "content": {"raw": content},
        "user": {"display_name": "Test User"},
        "created_on": "2025-01-01T00:00:00Z",
        "updated_on": "2025-01-01T00:00:00Z"
    }

    route = respx.post(
        f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/comments"
    ).mock(return_value=Response(200, json=mock_response))

    # Call the method without parent_id
    await client.add_pull_request_comment(
        repo_slug=repo_slug,
        pull_request_id=pr_id,
        content=content
    )

    # Verify the request was made
    assert route.called
    request = route.calls.last.request

    # Verify the payload does NOT contain parent field
    payload = json.loads(request.content)
    assert "parent" not in payload
    assert payload["content"]["raw"] == content

    await client.close()


def test_slim_comment_includes_parent_id():
    """Test that slim_comment includes parent_id when parent is present"""
    raw_comment = {
        "id": 1,
        "content": {"raw": "text"},
        "parent": {"id": 123},
        "user": {"display_name": "Test User"},
        "created_on": "2025-01-01T00:00:00Z",
        "updated_on": "2025-01-01T00:00:00Z"
    }

    result = slim_comment(raw_comment)

    assert "parent_id" in result
    assert result["parent_id"] == 123
    assert result["id"] == 1
    assert result["content"] == "text"
    assert result["author"]["display_name"] == "Test User"


def test_slim_comment_excludes_parent_id_when_no_parent():
    """Test that slim_comment excludes parent_id when parent is not present"""
    raw_comment = {
        "id": 1,
        "content": {"raw": "text"},
        "user": {"display_name": "Test User"},
        "created_on": "2025-01-01T00:00:00Z",
        "updated_on": "2025-01-01T00:00:00Z"
    }

    result = slim_comment(raw_comment)

    assert "parent_id" not in result
    assert result["id"] == 1
    assert result["content"] == "text"
    assert result["author"]["display_name"] == "Test User"
