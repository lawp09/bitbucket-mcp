"""Tests for MCP 2025 tool annotations (readOnlyHint, destructiveHint, idempotentHint,
openWorldHint) and human-readable titles.

Most assertions hit the pure classification helpers (`_classify` / `_tool_title`) so they
cover EVERY tool name — including the ones disabled by default in configs/tools.json
(merge_pull_request, stop_pipeline, delete_issue, ...) which never appear in
`mcp.list_tools()`. A final integration test guards the registered tools end-to-end.
"""

import json
from pathlib import Path

import pytest

from mcp.types import ToolAnnotations
from src.server import (
    mcp,
    _classify,
    _tool_title,
    _tool_annotations,
    _ANNOTATION_PREFIXES,
    _ANNOTATION_OVERRIDES,
    _TITLE_OVERRIDES,
)


def _all_tool_names() -> set:
    """Every tool name (enabled or disabled) — union of configs/tools.json and the
    live registry, so override keys can be checked even for disabled-by-default tools."""
    cfg = json.loads((Path(__file__).parent.parent / "configs" / "tools.json").read_text())
    names = set()
    for category in cfg["tools"].values():
        names.update(category.keys())
    return names


# (tool_name, (readOnlyHint, destructiveHint, idempotentHint))
# One representative per prefix category + every override (incl. disabled-by-default ones).
_CLASSIFICATION_CASES = [
    # get_/list_ → read-only, idempotent
    ("get_pull_request", (True, False, True)),
    ("list_repositories", (True, False, True)),
    ("get_repository_tags", (True, False, True)),
    ("list_pipeline_runs", (True, False, True)),
    ("get_file_content", (True, False, True)),
    ("list_environments", (True, False, True)),
    ("get_deployment", (True, False, True)),
    # create_/add_ → write, non-idempotent
    ("create_pull_request", (False, False, False)),
    ("add_pull_request_comment", (False, False, False)),
    ("create_issue", (False, False, False)),
    ("create_environment", (False, False, False)),         # disabled by default
    # update_ → write, idempotent
    ("update_pull_request", (False, False, True)),
    ("update_issue_comment", (False, False, True)),
    ("update_deployment_variable", (False, False, True)),  # disabled by default
    # delete_ → destructive, idempotent
    ("delete_pull_request_comment", (False, True, True)),
    ("delete_issue", (False, True, True)),            # disabled by default
    ("delete_pipeline_cache", (False, True, True)),   # disabled by default
    ("delete_environment", (False, True, True)),      # disabled by default
    # read-only despite write-sounding verb
    ("suggest_pull_request_reviewers", (True, False, True)),
    # update-like toggles → write, idempotent
    ("approve_pull_request", (False, False, True)),
    ("unapprove_pull_request", (False, False, True)),
    ("request_changes_pull_request", (False, False, True)),
    ("unrequest_changes_pull_request", (False, False, True)),
    ("resolve_pull_request_comment", (False, False, True)),
    ("reopen_pull_request_comment", (False, False, True)),
    ("publish_draft_pull_request", (False, False, True)),
    ("convert_pull_request_to_draft", (False, False, True)),  # disabled by default
    # create-like → write, non-idempotent
    ("run_pipeline", (False, False, False)),
    ("submit_pull_request_batch_review", (False, False, False)),
    # DANGER → destructive, non-idempotent
    ("decline_pull_request", (False, True, False)),
    ("merge_pull_request", (False, True, False)),     # disabled by default
    ("stop_pipeline", (False, True, False)),          # disabled by default
]


@pytest.mark.parametrize("tool_name,expected", _CLASSIFICATION_CASES)
def test_classify_matches_matrix(tool_name, expected):
    """Each tool name classifies to the expected (readOnly, destructive, idempotent)."""
    assert _classify(tool_name) == expected


def test_overrides_take_precedence_over_prefixes():
    """An override wins even when the name also matches a prefix."""
    # publish_draft_pull_request would otherwise fall through to the conservative
    # fallback (no prefix match); the override gives it idempotent=True.
    assert "publish_draft_pull_request" in _ANNOTATION_OVERRIDES
    assert _classify("publish_draft_pull_request") == (False, False, True)


def test_unknown_name_uses_conservative_fallback():
    """A name with no prefix and no override is treated as a non-idempotent write."""
    assert _classify("frobnicate_widget") == (False, False, False)


def test_tool_annotations_shape_and_open_world():
    """_tool_annotations returns the four hints, openWorldHint always False, no title."""
    ann = _tool_annotations("get_pull_request")
    assert isinstance(ann, ToolAnnotations)
    assert ann.readOnlyHint is True
    assert ann.destructiveHint is False
    assert ann.idempotentHint is True
    assert ann.openWorldHint is False
    # title is carried top-level via mcp.tool(title=...), not inside annotations.
    assert ann.title is None


def test_tool_title_autogenerates_and_overrides():
    """Title is auto title-cased, with overrides for awkward names."""
    assert _tool_title("get_pull_request") == "Get Pull Request"
    assert _tool_title("list_directory") == "List Directory"
    # overrides
    assert _tool_title("submit_pull_request_batch_review") == "Submit Batch Review"
    assert _tool_title("get_effective_default_reviewers") == "Get Default Reviewers"


def test_no_dead_title_overrides():
    """No override may duplicate the auto title-case value (dead override smell)."""
    for name, title in _TITLE_OVERRIDES.items():
        assert title != name.replace("_", " ").title(), (
            f"Override for {name!r} equals the auto title-case — remove it"
        )


def test_override_keys_are_real_tool_names():
    """Guard against typos: every override key must be an actual tool name."""
    known = _all_tool_names()
    for name in _ANNOTATION_OVERRIDES:
        assert name in known, f"_ANNOTATION_OVERRIDES key {name!r} is not a real tool"
    for name in _TITLE_OVERRIDES:
        assert name in known, f"_TITLE_OVERRIDES key {name!r} is not a real tool"


@pytest.mark.asyncio
async def test_every_registered_tool_is_covered_and_annotated():
    """Guard-rail: every registered tool has a title + annotations and is explicitly
    covered by a prefix or an override (no silent fallback)."""
    tools = await mcp.list_tools()
    for tool in tools:
        # Skip phantom tools registered by other test modules on the global `mcp`.
        if tool.name.startswith(("test_", "mock_")):
            continue
        assert tool.title, f"{tool.name} has no title"
        assert tool.annotations is not None, f"{tool.name} has no annotations"
        assert tool.annotations.openWorldHint is False, f"{tool.name} openWorldHint != False"
        covered = (
            any(tool.name.startswith(p) for p in _ANNOTATION_PREFIXES)
            or tool.name in _ANNOTATION_OVERRIDES
        )
        assert covered, f"{tool.name} is not covered by a prefix or override (would fallback)"


@pytest.mark.asyncio
async def test_registered_override_tools_expose_expected_hints():
    """End-to-end: every registered tool listed in _ANNOTATION_OVERRIDES exposes exactly
    the override's hints — catches a corrupted value propagating through mcp.tool()."""
    tools = {t.name: t for t in await mcp.list_tools()}
    checked = 0
    for name, (read_only, destructive, idempotent) in _ANNOTATION_OVERRIDES.items():
        tool = tools.get(name)
        if tool is None:  # disabled by default → not registered
            continue
        ann = tool.annotations
        assert ann.readOnlyHint is read_only, f"{name} readOnlyHint"
        assert ann.destructiveHint is destructive, f"{name} destructiveHint"
        assert ann.idempotentHint is idempotent, f"{name} idempotentHint"
        checked += 1
    assert checked > 0, "expected at least one enabled override tool to be verified"


@pytest.mark.asyncio
async def test_read_tools_are_read_only():
    """Every registered get_/list_ tool is read-only and non-destructive."""
    tools = await mcp.list_tools()
    for tool in tools:
        if tool.name.startswith(("get_", "list_")):
            assert tool.annotations.readOnlyHint is True, f"{tool.name} not readOnly"
            assert tool.annotations.destructiveHint is False, f"{tool.name} marked destructive"
