"""Tests for MCP server"""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, patch

import src.server
from src.client import BitbucketClient
from src.server import close_clients, get_client


ENV_VARS = {
    "BITBUCKET_USERNAME": "test@example.com",
    "BITBUCKET_TOKEN": "test_token",
    "BITBUCKET_WORKSPACE": "test_workspace",
}


@pytest.fixture(autouse=True)
def reset_client_registry():
    """Empty the loop-keyed client registry around every test.

    The registry is module-level state shared by the whole test session; without this,
    a client created by one test would be handed to the next.
    """
    src.server._clients.clear()
    src.server._no_loop_client = None
    yield
    src.server._clients.clear()
    src.server._no_loop_client = None


def test_get_client_missing_env_vars():
    """Test that get_client raises error when env vars missing and no keychain"""
    with patch.dict(os.environ, {}, clear=True):
        with patch("src.utils.credentials.KEYRING_AVAILABLE", False):
            with pytest.raises(ValueError) as exc_info:
                get_client()

    assert "Missing required credentials" in str(exc_info.value)


def test_get_client_with_env_vars():
    """Test that get_client creates client when env vars present"""
    with patch.dict(os.environ, ENV_VARS, clear=True):
        client = get_client()

        assert client is not None
        assert client.workspace == "test_workspace"


def test_get_client_singleton():
    """Test that get_client returns same instance (singleton pattern)"""
    with patch.dict(os.environ, ENV_VARS, clear=True):
        client1 = get_client()
        client2 = get_client()

        # Should be the same instance
        assert client1 is client2


# ========== Loop-aware client registry (issue #71) ==========


def test_get_client_same_instance_within_a_loop():
    """Within one event loop, the client (and its connection pool) is reused."""
    async def scenario():
        return get_client(), get_client()

    with patch.dict(os.environ, ENV_VARS, clear=True):
        first, second = asyncio.run(scenario())

    assert first is second
    assert first.workspace == "test_workspace"


def test_get_client_new_instance_per_loop():
    """A fresh event loop gets a fresh client — an httpx pool bound to a closed loop
    would raise 'Event loop is closed' on reuse (serverless / stateless deployments)."""
    async def scenario():
        client = get_client()
        # Exercise the pool on this loop so a stale one would actually be detected.
        await client.client.aclose()
        return client

    with patch.dict(os.environ, ENV_VARS, clear=True):
        first = asyncio.run(scenario())
        second = asyncio.run(scenario())

    assert first is not second


def test_get_client_outside_loop_is_process_wide():
    """Called with no running loop, get_client keeps the historical singleton behaviour."""
    with patch.dict(os.environ, ENV_VARS, clear=True):
        first = get_client()
        second = get_client()

    assert first is second
    assert src.server._no_loop_client is first
    assert len(src.server._clients) == 0


@pytest.mark.asyncio
async def test_close_clients_closes_and_empties_registry():
    """close_clients() closes every registered client and clears the registry."""
    # spec=BitbucketClient so the test fails if close() is ever renamed.
    mock_client = AsyncMock(spec=BitbucketClient)
    src.server._clients[asyncio.get_running_loop()] = mock_client
    src.server._no_loop_client = AsyncMock(spec=BitbucketClient)
    no_loop = src.server._no_loop_client

    await close_clients()

    mock_client.close.assert_awaited_once()
    no_loop.close.assert_awaited_once()
    assert len(src.server._clients) == 0
    assert src.server._no_loop_client is None


@pytest.mark.asyncio
async def test_close_clients_survives_a_failing_close():
    """A client bound to a dead loop can raise on close; shutdown must not crash."""
    failing = AsyncMock(spec=BitbucketClient)
    failing.close.side_effect = RuntimeError("Event loop is closed")
    src.server._clients[asyncio.get_running_loop()] = failing

    await close_clients()  # must not raise

    assert len(src.server._clients) == 0


@pytest.mark.asyncio
async def test_close_clients_is_a_noop_when_empty():
    """Shutdown with nothing registered is harmless."""
    await close_clients()

    assert len(src.server._clients) == 0
    assert src.server._no_loop_client is None


@pytest.mark.asyncio
async def test_healthz_route_registered():
    """The liveness probe is mounted on the HTTP apps."""
    from src.server import mcp

    paths = [route.path for route in mcp._custom_starlette_routes]
    assert "/healthz" in paths


@pytest.mark.asyncio
async def test_mcp_server_tools_registered():
    """Test that MCP server has tools registered"""
    from src.server import mcp

    # Get list of registered tools (async method)
    tools = await mcp.list_tools()

    # Verify essential tools are registered
    tool_names = [tool.name for tool in tools]

    assert "get_pull_request" in tool_names
    assert "get_pull_requests" in tool_names
    assert "list_repositories" in tool_names
    assert "get_repository_tags" in tool_names
    assert "add_pull_request_comment" in tool_names
    assert "approve_pull_request" in tool_names
    assert "request_changes_pull_request" in tool_names
    assert "unrequest_changes_pull_request" in tool_names
    # merge_pull_request is disabled by default in configs/tools.json
    assert "get_pull_request_statuses" in tool_names
    assert "get_pull_request_diffstat" in tool_names
    assert "get_commit_statuses" in tool_names
    # Comment CRUD and pipeline tools
    assert "get_pull_request_comment" in tool_names
    assert "update_pull_request_comment" in tool_names
    # delete_pull_request_comment is disabled by default in configs/tools.json
    assert "resolve_pull_request_comment" in tool_names
    assert "reopen_pull_request_comment" in tool_names
    assert "run_pipeline" in tool_names
    # stop_pipeline is disabled by default in configs/tools.json
    assert "get_effective_default_reviewers" in tool_names
    # Task tools
    assert "get_pull_request_tasks" in tool_names
    assert "get_pull_request_task" in tool_names
    assert "create_pull_request_task" in tool_names
    assert "update_pull_request_task" in tool_names
    assert "delete_pull_request_task" in tool_names
    assert "get_pull_request_patch" not in tool_names  # disabled by default (git am format)
    assert "get_pull_requests_pending_review" in tool_names
    # Draft PR and review tools
    assert "create_draft_pull_request" in tool_names
    assert "publish_draft_pull_request" in tool_names
    assert "convert_pull_request_to_draft" not in tool_names  # disabled (API not supported)
    assert "submit_pull_request_batch_review" in tool_names
    assert "get_pull_request_review_summary" in tool_names
    assert "suggest_pull_request_reviewers" in tool_names
    # Issue tracker tools
    assert "list_issues" in tool_names
    assert "get_issue" in tool_names
    assert "create_issue" in tool_names
    assert "update_issue" in tool_names
    assert "delete_issue" not in tool_names  # disabled by default for safety
    assert "get_issue_comments" in tool_names
    assert "get_issue_comment" in tool_names
    assert "add_issue_comment" in tool_names
    assert "update_issue_comment" in tool_names
    assert "delete_issue_comment" not in tool_names  # disabled by default for safety


@pytest.mark.asyncio
async def test_tool_descriptions():
    """Test that tools have proper descriptions"""
    from src.server import mcp

    tools = await mcp.list_tools()
    tool_dict = {tool.name: tool for tool in tools}

    # Verify key tools have descriptions
    assert tool_dict["get_pull_request"].description is not None
    assert "pull request" in tool_dict["get_pull_request"].description.lower()

    assert tool_dict["list_repositories"].description is not None
    assert "repositories" in tool_dict["list_repositories"].description.lower()

    assert tool_dict["get_repository_tags"].description is not None
    assert "tags" in tool_dict["get_repository_tags"].description.lower()
