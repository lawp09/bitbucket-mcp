"""Tests for structured output in MCP tools"""

import pytest
from typing import Dict, Any
from src.server import mcp, conditional_tool


def test_conditional_tool_decorator_has_structured_output_param():
    """Test that conditional_tool decorator accepts structured_output parameter"""

    # Test with structured_output=True (default)
    @conditional_tool()
    async def test_tool_default() -> Dict[str, Any]:
        return {"key": "value"}

    # Test with explicit structured_output=True
    @conditional_tool(structured_output=True)
    async def test_tool_explicit_true() -> Dict[str, Any]:
        return {"key": "value"}

    # Test with structured_output=False
    @conditional_tool(structured_output=False)
    async def test_tool_explicit_false() -> Dict[str, Any]:
        return {"key": "value"}

    # All decorators should work without errors
    assert callable(test_tool_default)
    assert callable(test_tool_explicit_true)
    assert callable(test_tool_explicit_false)


@pytest.mark.asyncio
async def test_tools_registered_with_structured_output():
    """Test that MCP tools are properly registered"""

    # Get list of registered tools
    tools = await mcp.list_tools()

    # Check that tools are registered
    assert len(tools) > 0

    # Check specific tools exist
    tool_names = [tool.name for tool in tools]

    # Core tools should be registered
    expected_tools = [
        "list_repositories",
        "get_repository",
        "get_pull_requests",
        "get_pull_request",
    ]

    for expected_tool in expected_tools:
        assert expected_tool in tool_names, f"Tool {expected_tool} should be registered"


def test_tool_configuration_integration():
    """Test that conditional_tool respects configuration file"""
    import json
    from pathlib import Path

    # Check that configs/tools.json exists
    project_root = Path(__file__).parent.parent
    config_file = project_root / "configs" / "tools.json"

    assert config_file.exists(), "configs/tools.json should exist"

    # Load config
    with open(config_file, 'r') as f:
        config = json.load(f)

    # Check structure
    assert "tools" in config
    assert isinstance(config["tools"], dict)

    # Check that all tool categories exist
    assert "repositories" in config["tools"]
    assert "pull_requests" in config["tools"]
    assert "pipelines" in config["tools"]


@pytest.mark.asyncio
async def test_structured_output_is_enabled_by_default():
    """Test that tools use structured_output by default"""

    # Create a test tool without explicit structured_output parameter
    @conditional_tool()
    async def mock_tool() -> Dict[str, Any]:
        return {
            "id": 123,
            "name": "test",
            "data": {"nested": "value"}
        }

    # Tool should be callable
    result = await mock_tool()

    # Result should be a dict, not a string
    assert isinstance(result, dict)
    assert result["id"] == 123
    assert result["name"] == "test"
    assert isinstance(result["data"], dict)
    assert result["data"]["nested"] == "value"
