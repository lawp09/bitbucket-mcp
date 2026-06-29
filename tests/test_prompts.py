"""Tests for the MCP Prompts primitive (issue #60)."""

from unittest.mock import patch

import pytest

from src.prompts import (
    build_review_pull_request_prompt,
    build_debug_pipeline_failure_prompt,
    build_summarize_repository_prompt,
    build_onboard_reviewer_prompt,
)


# ========== Builders (pure functions) ==========

class TestReviewPullRequestBuilder:
    def test_interpolates_args(self):
        text = build_review_pull_request_prompt("my-repo", "42")
        assert "my-repo" in text
        assert "42" in text

    def test_lists_tools_in_order(self):
        text = build_review_pull_request_prompt("my-repo", "42")
        for tool in (
            "get_pull_request",
            "get_pull_request_diffstat",
            "get_pull_request_diff",
            "get_pull_request_comments",
            "get_pull_request_tasks",
        ):
            assert tool in text

    def test_has_structured_output_sections(self):
        text = build_review_pull_request_prompt("my-repo", "42")
        for section in ("Summary", "Risk", "Code quality", "Security", "Recommendation"):
            assert section in text


class TestDebugPipelineFailureBuilder:
    def test_interpolates_args(self):
        text = build_debug_pipeline_failure_prompt("my-repo", "{pipe-9}")
        assert "my-repo" in text
        assert "{pipe-9}" in text

    def test_lists_tools(self):
        text = build_debug_pipeline_failure_prompt("my-repo", "{pipe-9}")
        for tool in ("get_pipeline_run", "get_pipeline_steps", "get_pipeline_step_logs"):
            assert tool in text

    def test_sections(self):
        text = build_debug_pipeline_failure_prompt("my-repo", "{pipe-9}")
        for section in ("Root cause", "Failed step", "Error message", "Fix suggestion"):
            assert section in text


class TestSummarizeRepositoryBuilder:
    def test_single_arg(self):
        text = build_summarize_repository_prompt("my-repo")
        assert "my-repo" in text

    def test_lists_tools(self):
        text = build_summarize_repository_prompt("my-repo")
        for tool in (
            "get_repository",
            "list_commits",
            "get_pull_requests",
            "list_pipeline_runs",
            "list_issues",
        ):
            assert tool in text

    def test_sections(self):
        text = build_summarize_repository_prompt("my-repo")
        for section in ("Purpose", "Recent activity", "Health", "Key contributors"):
            assert section in text


class TestOnboardReviewerBuilder:
    def test_interpolates_args(self):
        text = build_onboard_reviewer_prompt("my-repo", "42")
        assert "my-repo" in text
        assert "42" in text

    def test_lists_tools(self):
        text = build_onboard_reviewer_prompt("my-repo", "42")
        for tool in (
            "get_pull_request",
            "get_pull_request_commits",
            "get_pull_request_diff",
            "get_pull_request_activity",
        ):
            assert tool in text


def test_special_chars_do_not_break_generation():
    """An arg with quotes/braces is just interpolated, never breaks the f-string."""
    text = build_review_pull_request_prompt('repo"with{weird}', '"; drop')
    assert 'repo"with{weird}' in text
    assert '"; drop' in text


# ========== Registration via FastMCP ==========

EXPECTED_PROMPTS = {
    "review_pull_request": ["repo_slug", "pull_request_id"],
    "debug_pipeline_failure": ["repo_slug", "pipeline_uuid"],
    "summarize_repository": ["repo_slug"],
    "onboard_reviewer": ["repo_slug", "pull_request_id"],
}


@pytest.mark.asyncio
async def test_all_prompts_registered():
    from src.server import mcp
    prompts = await mcp.list_prompts()
    names = {p.name for p in prompts}
    for expected in EXPECTED_PROMPTS:
        assert expected in names, f"{expected} not registered"


@pytest.mark.asyncio
async def test_prompt_arguments_are_required():
    from src.server import mcp
    by_name = {p.name: p for p in await mcp.list_prompts()}
    for name, expected_args in EXPECTED_PROMPTS.items():
        args = by_name[name].arguments or []
        arg_names = [a.name for a in args]
        assert arg_names == expected_args
        assert all(a.required for a in args), f"{name} args should be required"


@pytest.mark.asyncio
async def test_get_prompt_returns_user_message():
    from src.server import mcp
    result = await mcp.get_prompt(
        "review_pull_request", {"repo_slug": "my-repo", "pull_request_id": "42"}
    )
    msg = result.messages[0]
    assert msg.role == "user"
    assert msg.content.type == "text"
    assert "my-repo" in msg.content.text
    assert "42" in msg.content.text


@pytest.mark.asyncio
async def test_get_prompt_summarize_single_arg():
    from src.server import mcp
    result = await mcp.get_prompt("summarize_repository", {"repo_slug": "my-repo"})
    assert "my-repo" in result.messages[0].content.text


# ========== conditional_prompt enable/disable ==========

@pytest.mark.asyncio
async def test_conditional_prompt_registers_when_enabled():
    """An enabled prompt is registered on the FastMCP instance.

    Uses a local FastMCP patched onto src.server.mcp so the global production
    singleton (and its exhaustive-count tests) stays untouched.
    """
    from src import server
    from mcp.server.fastmcp import FastMCP
    test_mcp = FastMCP("test")
    with patch.object(server, "mcp", test_mcp), \
            patch.object(server, "is_tool_enabled", return_value=True):
        async def my_prompt(repo_slug: str) -> str:
            return repo_slug
        wrapped = server.conditional_prompt()(my_prompt)
        assert wrapped is my_prompt  # FastMCP returns the same callable
    names = {p.name for p in await test_mcp.list_prompts()}
    assert "my_prompt" in names


@pytest.mark.asyncio
async def test_conditional_prompt_skips_when_disabled():
    """A disabled prompt is NOT registered — the decorator returns the bare function."""
    from src import server
    from mcp.server.fastmcp import FastMCP
    test_mcp = FastMCP("test")
    with patch.object(server, "mcp", test_mcp), \
            patch.object(server, "is_tool_enabled", return_value=False):
        async def disabled_prompt(repo_slug: str) -> str:
            return repo_slug
        wrapped = server.conditional_prompt()(disabled_prompt)
        assert wrapped is disabled_prompt  # untouched, not registered
    names = {p.name for p in await test_mcp.list_prompts()}
    assert "disabled_prompt" not in names
