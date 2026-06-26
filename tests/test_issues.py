"""Tests for the Bitbucket Issue Tracker tools (client, server, transformers, BBQL)."""

import json

import httpx
import pytest
import respx
from unittest.mock import AsyncMock, patch

from src.client import (
    BitbucketClient,
    IssueTrackerDisabledError,
    _bbql_quote,
    _build_issue_query,
)
from src.utils.transformers import (
    slim_issue,
    slim_issue_list,
    slim_issue_comment,
    slim_issue_comment_list,
)


# ========== Fixtures ==========

SAMPLE_LINKS = {
    "self": {"href": "https://api.bitbucket.org/2.0/some/url"},
    "html": {"href": "https://bitbucket.org/some/url"},
    "avatar": {"href": "https://bytebucket.org/ravatar/xyz"},
}

SAMPLE_USER = {
    "display_name": "Philippe LAWSON",
    "links": SAMPLE_LINKS,
    "type": "user",
    "uuid": "{e7ae358e-abb2-4b2e-8e00-3976fa551c45}",
    "account_id": "5db9be213a09190c2ad5c484",
    "nickname": "Phil",
    "username": "plawson",
}

SAMPLE_ISSUE = {
    "type": "issue",
    "id": 17,
    "title": "Crash on save",
    "content": {
        "raw": "Steps to reproduce...",
        "html": "<p>Steps to reproduce...</p>",
        "markup": "markdown",
    },
    "state": "open",
    "kind": "bug",
    "priority": "major",
    "reporter": SAMPLE_USER,
    "assignee": SAMPLE_USER,
    "component": {"name": "backend", "links": SAMPLE_LINKS},
    "milestone": {"name": "v2.0", "links": SAMPLE_LINKS},
    "votes": 3,
    "watches": 5,
    "created_on": "2026-06-01T10:00:00+00:00",
    "updated_on": "2026-06-10T12:00:00+00:00",
    "links": SAMPLE_LINKS,
    "repository": {"links": SAMPLE_LINKS, "full_name": "workspace/my-repo"},
}

SAMPLE_ISSUE_COMMENT = {
    "type": "issue_comment",
    "id": 901,
    "content": {
        "raw": "I can reproduce this.",
        "html": "<p>I can reproduce this.</p>",
        "markup": "markdown",
    },
    "user": SAMPLE_USER,
    "created_on": "2026-06-02T08:00:00+00:00",
    "updated_on": "2026-06-02T08:30:00+00:00",
    "links": SAMPLE_LINKS,
    "issue": {"id": 17, "links": SAMPLE_LINKS},
}

SAMPLE_TRACKER_DISABLED_404 = {
    "type": "error",
    "error": {"message": "Repository has no issue tracker."},
}

SAMPLE_ISSUE_NOT_FOUND_404 = {
    "type": "error",
    "error": {"message": "No Issue matching the query."},
}

ISSUES_URL = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo/issues"


# ========== BBQL builder ==========

class TestBuildIssueQuery:
    def test_no_filter_returns_none(self):
        assert _build_issue_query() is None

    def test_single_state(self):
        assert _build_issue_query(state="open") == 'state = "open"'

    def test_combines_all_with_and(self):
        result = _build_issue_query(
            state="open", kind="bug", priority="major", assignee="{uuid-1}"
        )
        assert result == (
            'state = "open" AND kind = "bug" AND priority = "major" '
            'AND assignee.uuid = "{uuid-1}"'
        )

    def test_raw_query_is_parenthesized(self):
        assert _build_issue_query(q="created_on > 2024-01-01") == "(created_on > 2024-01-01)"

    def test_dedicated_filters_and_raw_query_combined(self):
        result = _build_issue_query(state="open", q="votes > 2")
        assert result == 'state = "open" AND (votes > 2)'

    def test_quoting_escapes_quotes_and_backslashes(self):
        assert _bbql_quote('a"b\\c') == '"a\\"b\\\\c"'


# ========== Transformers ==========

class TestSlimIssue:
    def test_keeps_essential_fields(self):
        result = slim_issue(SAMPLE_ISSUE)
        assert result["id"] == 17
        assert result["title"] == "Crash on save"
        assert result["content"] == "Steps to reproduce..."
        assert result["state"] == "open"
        assert result["kind"] == "bug"
        assert result["priority"] == "major"
        assert result["component"] == "backend"
        assert result["milestone"] == "v2.0"
        assert result["votes"] == 3
        assert result["watches"] == 5

    def test_reporter_and_assignee_are_slimmed(self):
        result = slim_issue(SAMPLE_ISSUE)
        assert result["reporter"]["display_name"] == "Philippe LAWSON"
        assert "links" not in result["reporter"]
        assert result["assignee"]["display_name"] == "Philippe LAWSON"
        # uuid is kept (issues identify assignees by uuid) so it can be reused
        assert result["assignee"]["uuid"] == SAMPLE_USER["uuid"]
        assert result["reporter"]["uuid"] == SAMPLE_USER["uuid"]

    def test_strips_links_html_and_repository(self):
        result = slim_issue(SAMPLE_ISSUE)
        assert "links" not in result
        assert "repository" not in result
        assert "html" not in str(result.get("content"))

    def test_handles_missing_optional_fields(self):
        issue = {
            "id": 1,
            "title": "Minimal",
            "content": None,
            "assignee": None,
            "component": None,
            "milestone": None,
        }
        result = slim_issue(issue)
        assert result["content"] is None
        assert result["assignee"] is None
        assert result["component"] is None
        assert result["milestone"] is None

    def test_issue_list_aggregates_and_flags_has_more(self):
        data = {
            "values": [SAMPLE_ISSUE, SAMPLE_ISSUE],
            "page": 1,
            "next": f"{ISSUES_URL}?page=2",
        }
        result = slim_issue_list(data)
        assert result["count"] == 2
        assert result["has_more"] is True
        assert result["values"][0]["id"] == 17


class TestSlimIssueComment:
    def test_keeps_essential_fields(self):
        result = slim_issue_comment(SAMPLE_ISSUE_COMMENT)
        assert result["id"] == 901
        assert result["content"] == "I can reproduce this."
        assert result["author"]["display_name"] == "Philippe LAWSON"
        assert "links" not in result

    def test_comment_list(self):
        data = {"values": [SAMPLE_ISSUE_COMMENT], "page": 1}
        result = slim_issue_comment_list(data)
        assert result["count"] == 1
        assert result["values"][0]["id"] == 901


# ========== Client (respx) ==========

@pytest.mark.asyncio
async def test_list_issues_endpoint_sort_and_query():
    response = {"pagelen": 20, "size": 1, "page": 1, "values": [SAMPLE_ISSUE]}
    with respx.mock:
        route = respx.get(ISSUES_URL).mock(return_value=httpx.Response(200, json=response))
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            result = await client.list_issues(
                "my-repo", state="open", kind="bug", page_size=20
            )
        assert result["values"][0]["id"] == 17
        params = route.calls.last.request.url.params
        assert params["sort"] == "-created_on"
        assert params["pagelen"] == "20"
        assert 'state = "open"' in params["q"]
        assert 'kind = "bug"' in params["q"]


@pytest.mark.asyncio
async def test_list_issues_aggregates_multiple_pages():
    page1 = {
        "pagelen": 20, "size": 2, "page": 1,
        "values": [{"id": 1, "title": "a"}],
        "next": f"{ISSUES_URL}?page=2",
    }
    page2 = {
        "pagelen": 20, "size": 2, "page": 2,
        "values": [{"id": 2, "title": "b"}],
    }

    def handler(request):
        if "page=2" in str(request.url):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    with respx.mock:
        respx.get(url__regex=r".*/issues").mock(side_effect=handler)
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            result = await client.list_issues("my-repo", page_size=20, max_pages=2)
        assert len(result["values"]) == 2
        assert result["values"][0]["id"] == 1
        assert result["values"][-1]["id"] == 2


@pytest.mark.asyncio
async def test_get_issue():
    url = f"{ISSUES_URL}/17"
    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, json=SAMPLE_ISSUE))
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            result = await client.get_issue("my-repo", "17")
        assert result["id"] == 17


@pytest.mark.asyncio
async def test_create_issue_sends_partial_payload():
    with respx.mock:
        route = respx.post(ISSUES_URL).mock(
            return_value=httpx.Response(201, json=SAMPLE_ISSUE)
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.create_issue(
                "my-repo", "New bug", content="Details", kind="bug", priority="major"
            )
        body = json.loads(route.calls.last.request.read())
        assert body["title"] == "New bug"
        assert body["content"] == {"raw": "Details"}
        assert body["kind"] == "bug"
        assert body["priority"] == "major"
        # Fields not provided must be absent
        assert "assignee" not in body
        assert "state" not in body


@pytest.mark.asyncio
async def test_create_issue_with_assignee_wraps_uuid():
    with respx.mock:
        route = respx.post(ISSUES_URL).mock(
            return_value=httpx.Response(201, json=SAMPLE_ISSUE)
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.create_issue("my-repo", "Bug", assignee="{uuid-123}")
        body = json.loads(route.calls.last.request.read())
        assert body["assignee"] == {"uuid": "{uuid-123}"}


@pytest.mark.asyncio
async def test_create_issue_full_payload():
    with respx.mock:
        route = respx.post(ISSUES_URL).mock(
            return_value=httpx.Response(201, json=SAMPLE_ISSUE)
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.create_issue(
                "my-repo", "Full", content="Body", kind="task",
                priority="minor", assignee="{uuid-1}", state="new",
            )
        body = json.loads(route.calls.last.request.read())
        assert body == {
            "title": "Full",
            "content": {"raw": "Body"},
            "kind": "task",
            "priority": "minor",
            "assignee": {"uuid": "{uuid-1}"},
            "state": "new",
        }


@pytest.mark.asyncio
async def test_update_issue_full_payload():
    url = f"{ISSUES_URL}/17"
    with respx.mock:
        route = respx.put(url).mock(return_value=httpx.Response(200, json=SAMPLE_ISSUE))
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.update_issue(
                "my-repo", "17", title="T", content="C", state="resolved",
                kind="enhancement", priority="critical", assignee="{uuid-2}",
            )
        body = json.loads(route.calls.last.request.read())
        assert body == {
            "title": "T",
            "content": {"raw": "C"},
            "state": "resolved",
            "kind": "enhancement",
            "priority": "critical",
            "assignee": {"uuid": "{uuid-2}"},
        }


@pytest.mark.asyncio
async def test_update_issue_sends_only_provided_fields():
    url = f"{ISSUES_URL}/17"
    with respx.mock:
        route = respx.put(url).mock(return_value=httpx.Response(200, json=SAMPLE_ISSUE))
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            await client.update_issue("my-repo", "17", state="resolved")
        body = json.loads(route.calls.last.request.read())
        assert body == {"state": "resolved"}


@pytest.mark.asyncio
async def test_delete_issue_returns_none_and_uses_delete():
    url = f"{ISSUES_URL}/17"
    with respx.mock:
        route = respx.delete(url).mock(return_value=httpx.Response(204))
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            result = await client.delete_issue("my-repo", "17")
        assert result is None
        assert route.calls.last.request.method == "DELETE"


@pytest.mark.asyncio
async def test_issue_comments_crud():
    base = f"{ISSUES_URL}/17/comments"
    with respx.mock:
        respx.get(base).mock(
            return_value=httpx.Response(200, json={"page": 1, "values": [SAMPLE_ISSUE_COMMENT]})
        )
        get_one = respx.get(f"{base}/901").mock(
            return_value=httpx.Response(200, json=SAMPLE_ISSUE_COMMENT)
        )
        add = respx.post(base).mock(return_value=httpx.Response(201, json=SAMPLE_ISSUE_COMMENT))
        upd = respx.put(f"{base}/901").mock(
            return_value=httpx.Response(200, json=SAMPLE_ISSUE_COMMENT)
        )
        delete = respx.delete(f"{base}/901").mock(return_value=httpx.Response(204))

        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            listing = await client.get_issue_comments("my-repo", "17")
            single = await client.get_issue_comment("my-repo", "17", "901")
            added = await client.add_issue_comment("my-repo", "17", "Hello")
            updated = await client.update_issue_comment("my-repo", "17", "901", "Edited")
            deleted = await client.delete_issue_comment("my-repo", "17", "901")

        assert listing["values"][0]["id"] == 901
        assert single["id"] == 901
        assert added["id"] == 901
        assert updated["id"] == 901
        assert deleted is None
        assert json.loads(add.calls.last.request.read()) == {"content": {"raw": "Hello"}}
        assert json.loads(upd.calls.last.request.read()) == {"content": {"raw": "Edited"}}
        assert get_one.called and delete.called


# ========== 404 handling: tracker disabled vs not found ==========

def test_is_tracker_disabled_response_handles_null_message():
    """A 404 body with a null message must not crash nor false-positive."""
    from src.client import _is_tracker_disabled_response

    resp = httpx.Response(404, json={"error": {"message": None}})
    assert _is_tracker_disabled_response(resp) is False


def test_is_tracker_disabled_response_true_on_marker():
    from src.client import _is_tracker_disabled_response

    resp = httpx.Response(404, json=SAMPLE_TRACKER_DISABLED_404)
    assert _is_tracker_disabled_response(resp) is True



@pytest.mark.asyncio
async def test_get_issue_tracker_disabled_raises_typed_error():
    url = f"{ISSUES_URL}/17"
    with respx.mock:
        respx.get(url).mock(
            return_value=httpx.Response(404, json=SAMPLE_TRACKER_DISABLED_404)
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            with pytest.raises(IssueTrackerDisabledError) as exc:
                await client.get_issue("my-repo", "17")
    assert exc.value.workspace == "workspace"
    assert exc.value.repo_slug == "my-repo"


@pytest.mark.asyncio
async def test_list_issues_tracker_disabled_raises_typed_error_paginated_path():
    with respx.mock:
        respx.get(ISSUES_URL).mock(
            return_value=httpx.Response(404, json=SAMPLE_TRACKER_DISABLED_404)
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            with pytest.raises(IssueTrackerDisabledError):
                await client.list_issues("my-repo")


@pytest.mark.asyncio
async def test_every_issue_method_raises_typed_error_when_tracker_disabled():
    """All issue endpoints (direct + paginated) surface IssueTrackerDisabledError on a
    tracker-disabled 404, covering every graceful-failure branch."""
    with respx.mock:
        respx.route(url__regex=r".*/issues.*").mock(
            return_value=httpx.Response(404, json=SAMPLE_TRACKER_DISABLED_404)
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            coros = [
                client.create_issue("my-repo", "title"),
                client.update_issue("my-repo", "17", state="open"),
                client.delete_issue("my-repo", "17"),
                client.get_issue_comments("my-repo", "17"),
                client.get_issue_comment("my-repo", "17", "901"),
                client.add_issue_comment("my-repo", "17", "x"),
                client.update_issue_comment("my-repo", "17", "901", "x"),
                client.delete_issue_comment("my-repo", "17", "901"),
            ]
            for coro in coros:
                with pytest.raises(IssueTrackerDisabledError):
                    await coro


@pytest.mark.asyncio
async def test_get_issue_not_found_propagates_http_error():
    url = f"{ISSUES_URL}/999"
    with respx.mock:
        respx.get(url).mock(
            return_value=httpx.Response(404, json=SAMPLE_ISSUE_NOT_FOUND_404)
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_issue("my-repo", "999")


@pytest.mark.asyncio
async def test_list_issues_not_found_propagates_http_error_paginated_path():
    with respx.mock:
        respx.get(ISSUES_URL).mock(
            return_value=httpx.Response(404, json=SAMPLE_ISSUE_NOT_FOUND_404)
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.list_issues("my-repo")


@pytest.mark.asyncio
async def test_get_issue_comments_not_found_propagates_http_error_paginated_path():
    url = f"{ISSUES_URL}/999/comments"
    with respx.mock:
        respx.get(url).mock(
            return_value=httpx.Response(404, json=SAMPLE_ISSUE_NOT_FOUND_404)
        )
        async with BitbucketClient("test@example.com", "token", "workspace") as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_issue_comments("my-repo", "999")


# ========== Server tools (AsyncMock) ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_issues_tool(mock_get_client):
    from src.server import list_issues

    mock_client = AsyncMock()
    mock_client.list_issues.return_value = {"page": 1, "values": [SAMPLE_ISSUE]}
    mock_get_client.return_value = mock_client

    result = await list_issues("my-repo", state="open", kind="bug")

    # Guard the positional argument order forwarded to the client (filtering is the
    # core of this tool): repo_slug, workspace, state, kind, priority, assignee, q,
    # sort, page_size, max_pages, max_items.
    mock_client.list_issues.assert_awaited_once_with(
        "my-repo", None, "open", "bug", None, None, None, "-created_on", 20, 1, None
    )
    assert result["values"][0]["id"] == 17
    assert result["count"] == 1


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_issue_tool(mock_get_client):
    from src.server import get_issue

    mock_client = AsyncMock()
    mock_client.get_issue.return_value = SAMPLE_ISSUE
    mock_get_client.return_value = mock_client

    result = await get_issue("my-repo", "17")

    mock_client.get_issue.assert_awaited_once_with("my-repo", "17", None)
    assert result["id"] == 17
    assert "links" not in result


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_create_issue_tool(mock_get_client):
    from src.server import create_issue

    mock_client = AsyncMock()
    mock_client.create_issue.return_value = {**SAMPLE_ISSUE, "id": 99, "title": "New"}
    mock_get_client.return_value = mock_client

    result = await create_issue("my-repo", "New", content="Body", kind="bug")

    mock_client.create_issue.assert_awaited_once()
    assert result["id"] == 99
    assert result["title"] == "New"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_update_issue_tool(mock_get_client):
    from src.server import update_issue

    mock_client = AsyncMock()
    mock_client.update_issue.return_value = {**SAMPLE_ISSUE, "state": "resolved"}
    mock_get_client.return_value = mock_client

    result = await update_issue("my-repo", "17", state="resolved")

    mock_client.update_issue.assert_awaited_once_with(
        "my-repo", "17", None, None, "resolved", None, None, None, None
    )
    assert result["state"] == "resolved"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_issue_comments_tool(mock_get_client):
    from src.server import get_issue_comments

    mock_client = AsyncMock()
    mock_client.get_issue_comments.return_value = {"page": 1, "values": [SAMPLE_ISSUE_COMMENT]}
    mock_get_client.return_value = mock_client

    result = await get_issue_comments("my-repo", "17")

    mock_client.get_issue_comments.assert_awaited_once_with("my-repo", "17", None, 20, 1, None)
    assert result["values"][0]["id"] == 901
    assert result["count"] == 1


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_issue_comment_tool(mock_get_client):
    from src.server import get_issue_comment

    mock_client = AsyncMock()
    mock_client.get_issue_comment.return_value = SAMPLE_ISSUE_COMMENT
    mock_get_client.return_value = mock_client

    result = await get_issue_comment("my-repo", "17", "901")

    mock_client.get_issue_comment.assert_awaited_once_with("my-repo", "17", "901", None)
    assert result["id"] == 901


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_update_issue_comment_tool(mock_get_client):
    from src.server import update_issue_comment

    mock_client = AsyncMock()
    mock_client.update_issue_comment.return_value = SAMPLE_ISSUE_COMMENT
    mock_get_client.return_value = mock_client

    result = await update_issue_comment("my-repo", "17", "901", "Edited")

    mock_client.update_issue_comment.assert_awaited_once_with(
        "my-repo", "17", "901", "Edited", None
    )
    assert result["id"] == 901


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_delete_issue_tool_returns_confirmation(mock_get_client):
    from src.server import delete_issue

    mock_client = AsyncMock()
    mock_client.delete_issue.return_value = None
    mock_get_client.return_value = mock_client

    result = await delete_issue("my-repo", "17")

    mock_client.delete_issue.assert_awaited_once_with("my-repo", "17", None)
    assert result == {"deleted": True, "issue_id": "17"}


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_add_issue_comment_tool(mock_get_client):
    from src.server import add_issue_comment

    mock_client = AsyncMock()
    mock_client.add_issue_comment.return_value = SAMPLE_ISSUE_COMMENT
    mock_get_client.return_value = mock_client

    result = await add_issue_comment("my-repo", "17", "Hello")

    mock_client.add_issue_comment.assert_awaited_once_with("my-repo", "17", "Hello", None)
    assert result["id"] == 901
    assert result["content"] == "I can reproduce this."


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_delete_issue_comment_tool_returns_confirmation(mock_get_client):
    from src.server import delete_issue_comment

    mock_client = AsyncMock()
    mock_client.delete_issue_comment.return_value = None
    mock_get_client.return_value = mock_client

    result = await delete_issue_comment("my-repo", "17", "901")

    assert result == {"deleted": True, "comment_id": "901"}


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_update_issue_tool_requires_at_least_one_field(mock_get_client):
    from src.server import update_issue

    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client

    with pytest.raises(ValueError):
        await update_issue("my-repo", "17")

    mock_client.update_issue.assert_not_awaited()


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_issue_tool_returns_structured_error_when_tracker_disabled(mock_get_client):
    from src.server import get_issue

    mock_client = AsyncMock()
    mock_client.get_issue.side_effect = IssueTrackerDisabledError("workspace", "my-repo")
    mock_get_client.return_value = mock_client

    result = await get_issue("my-repo", "17")

    assert result["error"] == "issue_tracker_disabled"
    assert result["workspace"] == "workspace"
    assert result["repo_slug"] == "my-repo"
    assert "disabled" in result["message"].lower()
