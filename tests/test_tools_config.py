"""Tests for load_tools_config() — runtime path resolution via arg / env var / default."""

import json
import os
import pytest
from unittest.mock import patch

from src.server import load_tools_config


def test_load_default_config():
    """Load the real configs/tools.json without arguments."""
    result = load_tools_config()

    assert isinstance(result, dict)
    # merge_pull_request is disabled by default
    assert result.get("merge_pull_request") is False
    # get_pull_request must be enabled
    assert result.get("get_pull_request") is True


def test_load_config_from_param(tmp_path):
    """config_path argument takes a custom JSON file."""
    config = {
        "tools": {
            "custom_category": {
                "my_tool": {"enabled": True},
                "other_tool": {"enabled": False},
            }
        }
    }
    config_file = tmp_path / "my_tools.json"
    config_file.write_text(json.dumps(config))

    result = load_tools_config(config_path=str(config_file))

    assert result == {"my_tool": True, "other_tool": False}


def test_load_config_from_env_var(tmp_path):
    """BITBUCKET_TOOLS_CONFIG env var points to a valid JSON file."""
    config = {
        "tools": {
            "pr": {
                "get_pull_request": {"enabled": True},
            }
        }
    }
    config_file = tmp_path / "env_tools.json"
    config_file.write_text(json.dumps(config))

    with patch.dict(os.environ, {"BITBUCKET_TOOLS_CONFIG": str(config_file)}):
        result = load_tools_config()

    assert result == {"get_pull_request": True}


def test_param_overrides_env_var(tmp_path):
    """config_path argument wins over BITBUCKET_TOOLS_CONFIG env var."""
    file_a = tmp_path / "file_a.json"
    file_a.write_text(json.dumps({"tools": {"cat": {"tool_a": {"enabled": False}}}}))

    file_b = tmp_path / "file_b.json"
    file_b.write_text(json.dumps({"tools": {"cat": {"tool_b": {"enabled": True}}}}))

    with patch.dict(os.environ, {"BITBUCKET_TOOLS_CONFIG": str(file_a)}):
        result = load_tools_config(config_path=str(file_b))

    # file_b (param) must win — tool_b present, tool_a absent
    assert result == {"tool_b": True}
    assert "tool_a" not in result


def test_env_var_file_not_found_raises(tmp_path):
    """FileNotFoundError raised when BITBUCKET_TOOLS_CONFIG points to a missing file."""
    missing = str(tmp_path / "nonexistent.json")

    with patch.dict(os.environ, {"BITBUCKET_TOOLS_CONFIG": missing}):
        with pytest.raises(FileNotFoundError):
            load_tools_config()


def test_env_var_invalid_json_raises(tmp_path):
    """ValueError raised when BITBUCKET_TOOLS_CONFIG points to an invalid JSON file."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json")

    with patch.dict(os.environ, {"BITBUCKET_TOOLS_CONFIG": str(bad_file)}):
        with pytest.raises(ValueError):
            load_tools_config()


def test_default_missing_returns_empty(tmp_path):
    """When the default path is missing, return {} without raising an exception."""
    # Patch os.getenv so BITBUCKET_TOOLS_CONFIG is absent, and override the
    # default path by pointing __file__'s parent to a location with no tools.json.
    with patch.dict(os.environ, {}, clear=True):
        # Override the default path computation by patching Path inside server module.
        # We simulate "default file not found" by using a non-existent path as default.
        import src.server as server_module

        # Temporarily relocate __file__ so project_root / configs / tools.json doesn't exist
        with patch.object(server_module, "__file__", str(tmp_path / "src" / "server.py")):
            result = load_tools_config()

    assert result == {}
