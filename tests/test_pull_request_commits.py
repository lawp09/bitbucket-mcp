"""Tests for the full commit hashes returned by get_pull_request (issue #98)."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from src.client import AuthorizationError, BitbucketClient

REPO_URL = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo"

SOURCE_FULL = "abc123def456" + "0" * 28
DESTINATION_FULL = "789abc000111" + "f" * 28

SAMPLE_PR = {
    "id": 42,
    "title": "Test PR",
    "state": "OPEN",
    "draft": False,
    "author": {"display_name": "Dev", "uuid": "{author-uuid}"},
    "source": {
        "branch": {"name": "feat"},
        "commit": {"hash": SOURCE_FULL[:12]},
        "repository": {"full_name": "workspace/my-repo"},
    },
    "destination": {
        "branch": {"name": "main"},
        "commit": {"hash": DESTINATION_FULL[:12]},
        "repository": {"full_name": "workspace/my-repo"},
    },
    "reviewers": [],
    "participants": [
        {"user": {"display_name": "Bot", "uuid": "{bot}"}, "role": "REVIEWER",
         "approved": False, "state": "changes_requested"},
    ],
}

COMMENT_STATS = {"total": 0, "resolved": 0, "unresolved": 0}


# ========== Client: resolve_commit_hash ==========

@pytest.mark.asyncio
async def test_resolve_commit_hash_expands_short_hash():
    with respx.mock:
        respx.get(f"{REPO_URL}/commit/{SOURCE_FULL[:12]}").mock(
            return_value=httpx.Response(200, json={"hash": SOURCE_FULL})
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            assert await client.resolve_commit_hash("my-repo", SOURCE_FULL[:12]) == SOURCE_FULL


@pytest.mark.asyncio
async def test_resolve_commit_hash_full_hash_needs_no_request():
    with respx.mock:  # any request would fail: no route is registered
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            assert await client.resolve_commit_hash("my-repo", SOURCE_FULL) == SOURCE_FULL


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["main", "ABC123DEF456", "abc", "../x/y", "abc123def456" + "0" * 29])
async def test_resolve_commit_hash_rejects_non_hash(value):
    async with BitbucketClient("e@x.com", "token", "workspace") as client:
        with pytest.raises(ValueError, match="Not a commit hash"):
            await client.resolve_commit_hash("my-repo", value)


@pytest.mark.asyncio
async def test_resolve_commit_hash_rejects_unrelated_commit():
    """A branch or tag named like the hash resolves to another commit: refuse it."""
    with respx.mock:
        respx.get(f"{REPO_URL}/commit/{SOURCE_FULL[:12]}").mock(
            return_value=httpx.Response(200, json={"hash": DESTINATION_FULL})
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            with pytest.raises(ValueError, match="unrelated hash"):
                await client.resolve_commit_hash("my-repo", SOURCE_FULL[:12])


@pytest.mark.asyncio
async def test_resolve_commit_hash_propagates_http_error():
    with respx.mock:
        respx.get(f"{REPO_URL}/commit/{SOURCE_FULL[:12]}").mock(
            return_value=httpx.Response(404, json={"error": {"message": "not found"}})
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.resolve_commit_hash("my-repo", SOURCE_FULL[:12])


# ========== Tool: get_pull_request ==========

def _mock_client(resolve=None):
    client = AsyncMock()
    client.workspace = "workspace"
    client.allowed_workspaces = frozenset()
    client.get_pull_request.return_value = {
        **SAMPLE_PR,
        "source": dict(SAMPLE_PR["source"]),
        "destination": dict(SAMPLE_PR["destination"]),
    }
    client.get_pull_request_comment_stats.return_value = COMMENT_STATS
    client.resolve_commit_hash.side_effect = resolve or (
        lambda slug, short, ws: {SOURCE_FULL[:12]: SOURCE_FULL,
                                 DESTINATION_FULL[:12]: DESTINATION_FULL}[short]
    )
    return client


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_pull_request_returns_full_hashes_and_state(mock_get_client):
    from src.server import get_pull_request

    mock_get_client.return_value = _mock_client()
    result = await get_pull_request("my-repo", "42")

    assert result["source_commit"] == SOURCE_FULL
    assert result["destination_commit"] == DESTINATION_FULL
    assert result["participants"][0]["state"] == "changes_requested"
    assert result["comment_stats"] == COMMENT_STATS


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_pull_request_looks_up_fork_source_in_fork(mock_get_client):
    from src.server import get_pull_request

    client = _mock_client()
    client.get_pull_request.return_value["source"]["repository"] = {
        "full_name": "someone/my-fork"
    }
    mock_get_client.return_value = client
    await get_pull_request("my-repo", "42")

    client.resolve_commit_hash.assert_any_await("my-fork", SOURCE_FULL[:12], "someone")
    client.resolve_commit_hash.assert_any_await("my-repo", DESTINATION_FULL[:12], "workspace")


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_pull_request_without_repository_uses_pr_repo(mock_get_client):
    from src.server import get_pull_request

    client = _mock_client()
    del client.get_pull_request.return_value["source"]["repository"]
    mock_get_client.return_value = client
    await get_pull_request("my-repo", "42", workspace="other-ws")

    client.resolve_commit_hash.assert_any_await("my-repo", SOURCE_FULL[:12], "other-ws")


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    httpx.HTTPStatusError(
        "404", request=httpx.Request("GET", "https://x"), response=httpx.Response(404)
    ),
    httpx.ConnectError("down"),
    AuthorizationError("workspace 'someone' is not allowed"),
    ValueError("unrelated hash"),
])
@patch("src.server.get_client")
async def test_get_pull_request_unresolvable_commit_is_null(mock_get_client, error, caplog):
    from src.server import get_pull_request

    def resolve(slug, short, ws):
        if short == SOURCE_FULL[:12]:
            raise error
        return DESTINATION_FULL

    mock_get_client.return_value = _mock_client(resolve)
    result = await get_pull_request("my-repo", "42")

    assert result["source_commit"] is None
    assert result["destination_commit"] == DESTINATION_FULL
    assert result["id"] == 42
    assert "Could not resolve source commit" in caplog.text


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_pull_request_fork_outside_allowlist_is_null_without_request(
    mock_get_client, caplog
):
    """Real client with an allowlist: the fork lookup is skipped, nothing is audited."""
    from src.server import get_pull_request

    pr = {**SAMPLE_PR, "source": {**SAMPLE_PR["source"],
                                  "repository": {"full_name": "someone/my-fork"}}}
    client = BitbucketClient.from_bearer(
        "tok", "workspace", allowed_workspaces=frozenset({"workspace"})
    )
    mock_get_client.return_value = client
    with respx.mock:  # an unrouted request (e.g. to the fork) would raise
        respx.get(f"{REPO_URL}/pullrequests/42").mock(
            return_value=httpx.Response(200, json=pr)
        )
        respx.get(f"{REPO_URL}/commit/{DESTINATION_FULL[:12]}").mock(
            return_value=httpx.Response(200, json={"hash": DESTINATION_FULL})
        )
        with patch.object(
            BitbucketClient, "get_pull_request_comment_stats",
            AsyncMock(return_value=COMMENT_STATS),
        ):
            result = await get_pull_request("my-repo", "42")
    await client.close()

    assert result["source_commit"] is None
    assert result["destination_commit"] == DESTINATION_FULL
    assert "scope refused" not in caplog.text


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_pull_request_missing_commit_skips_lookup(mock_get_client):
    from src.server import get_pull_request

    client = _mock_client()
    client.get_pull_request.return_value["source"] = {"branch": {"name": "feat"}}
    mock_get_client.return_value = client
    result = await get_pull_request("my-repo", "42")

    assert result["source_commit"] is None
    assert client.resolve_commit_hash.await_count == 1


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_pull_request_comment_stats_failure_waits_for_lookups(mock_get_client):
    """The error surfaces only once the hash lookups are done, not while they run."""
    from src.server import get_pull_request

    finished = []

    async def slow_resolve(slug, short, ws):
        await asyncio.sleep(0.01)
        finished.append(short)
        return SOURCE_FULL if short == SOURCE_FULL[:12] else DESTINATION_FULL

    client = _mock_client(slow_resolve)
    client.get_pull_request_comment_stats.side_effect = RuntimeError("stats down")
    mock_get_client.return_value = client

    with pytest.raises(RuntimeError, match="stats down"):
        await get_pull_request("my-repo", "42")
    assert len(finished) == 2
