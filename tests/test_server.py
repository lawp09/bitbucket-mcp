"""Tests for MCP server"""

import os
import pytest
from unittest.mock import patch
from src.server import get_client, _bitbucket_client


def test_get_client_missing_env_vars():
    """Test that get_client raises error when env vars missing and no keychain"""
    import src.server
    src.server._bitbucket_client = None

    with patch.dict(os.environ, {}, clear=True):
        with patch("src.utils.credentials.KEYRING_AVAILABLE", False):
            with pytest.raises(ValueError) as exc_info:
                get_client()

    assert "Missing required credentials" in str(exc_info.value)


def test_get_client_with_env_vars():
    """Test that get_client creates client when env vars present"""
    # Clear any existing client
    import src.server
    src.server._bitbucket_client = None

    env_vars = {
        "BITBUCKET_USERNAME": "test@example.com",
        "BITBUCKET_TOKEN": "test_token",
        "BITBUCKET_WORKSPACE": "test_workspace"
    }

    with patch.dict(os.environ, env_vars, clear=True):
        client = get_client()

        assert client is not None
        assert client.workspace == "test_workspace"


def test_get_client_singleton():
    """Test that get_client returns same instance (singleton pattern)"""
    # Clear any existing client
    import src.server
    src.server._bitbucket_client = None

    env_vars = {
        "BITBUCKET_USERNAME": "test@example.com",
        "BITBUCKET_TOKEN": "test_token",
        "BITBUCKET_WORKSPACE": "test_workspace"
    }

    with patch.dict(os.environ, env_vars, clear=True):
        client1 = get_client()
        client2 = get_client()

        # Should be the same instance
        assert client1 is client2


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
    assert "add_pull_request_comment" in tool_names
    assert "approve_pull_request" in tool_names
    assert "request_changes_pull_request" in tool_names
    assert "unrequest_changes_pull_request" in tool_names
    # merge_pull_request is disabled by default in configs/tools.json
    assert "get_pull_request_statuses" in tool_names
    assert "get_pull_request_diffstat" in tool_names
    assert "get_commit_statuses" in tool_names


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
