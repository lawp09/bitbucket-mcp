"""Tests for the Commits & Source tools (client, server, transformers, /src guards)."""

import httpx
import pytest
import respx
from unittest.mock import AsyncMock, patch

from src.client import BitbucketClient, _is_binary_mimetype
from src.utils.transformers import (
    slim_commit,
    slim_commit_list,
    slim_commit_comment,
    slim_commit_comment_list,
    slim_source_entry,
    slim_source_list,
)

# ========== Fixtures ==========

SAMPLE_LINKS = {
    "self": {"href": "https://api.bitbucket.org/2.0/some/url"},
    "html": {"href": "https://bitbucket.org/some/url"},
}

SAMPLE_USER = {
    "display_name": "Philippe LAWSON",
    "links": SAMPLE_LINKS,
    "nickname": "Phil",
    "username": "plawson",
}

SAMPLE_COMMIT = {
    "type": "commit",
    "hash": "abcdef1234567890abcdef1234567890abcdef12",
    "message": "feat: add endpoint\n\nDetails",
    "date": "2026-06-01T10:00:00+00:00",
    "author": {"raw": "Philippe LAWSON <phil@example.com>", "user": SAMPLE_USER},
    "parents": [{"hash": "0011223344556677889900112233445566778899"}],
    "links": SAMPLE_LINKS,
}

SAMPLE_COMMIT_COMMENT = {
    "type": "commit_comment",
    "id": 555,
    "content": {"raw": "Nice change.", "html": "<p>Nice change.</p>"},
    "user": SAMPLE_USER,
    "created_on": "2026-06-02T08:00:00+00:00",
    "updated_on": "2026-06-02T08:30:00+00:00",
    "links": SAMPLE_LINKS,
}

SAMPLE_DIR_LISTING = {
    "pagelen": 50,
    "page": 1,
    "size": 2,
    "values": [
        {
            "path": "src/app.py",
            "type": "commit_file",
            "size": 1024,
            "mimetype": "text/x-python",
            "commit": {"hash": "abcdef1234567890abcdef1234567890abcdef12"},
            "links": SAMPLE_LINKS,
        },
        {
            "path": "src/utils",
            "type": "commit_directory",
            "links": SAMPLE_LINKS,
        },
    ],
}

REPO_URL = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo"
COMMIT_HASH = "abcdef1234567890"


# ========== Transformers ==========

class TestSlimSourceEntry:
    def test_keeps_essential_fields(self):
        result = slim_source_entry(SAMPLE_DIR_LISTING["values"][0])
        assert result["path"] == "src/app.py"
        assert result["type"] == "commit_file"
        assert result["size"] == 1024
        assert result["mimetype"] == "text/x-python"
        assert "links" not in result
        # commit is hoisted to the list level, not repeated per entry
        assert "commit" not in result

    def test_directory_entry_has_no_size(self):
        result = slim_source_entry(SAMPLE_DIR_LISTING["values"][1])
        assert result["type"] == "commit_directory"
        assert result["size"] is None

    def test_source_list_aggregates_and_hoists_commit(self):
        result = slim_source_list(SAMPLE_DIR_LISTING)
        assert result["count"] == 2
        assert result["values"][0]["path"] == "src/app.py"
        # single top-level commit (12 chars) instead of one per entry
        assert result["commit"] == "abcdef123456"
        assert all("commit" not in e for e in result["values"])

    def test_source_list_commit_none_when_absent(self):
        result = slim_source_list({"values": [{"path": "x", "type": "commit_file"}], "page": 1})
        assert result["commit"] is None


class TestSlimCommitReuse:
    """slim_commit is reused as-is; confirm it stays lean (no parents leak)."""

    def test_commit_is_slim(self):
        result = slim_commit(SAMPLE_COMMIT)
        assert result["hash"] == "abcdef123456"
        assert result["author"] == "Philippe LAWSON"
        assert "parents" not in result
        assert "links" not in result

    def test_commit_list(self):
        data = {"values": [SAMPLE_COMMIT], "page": 1}
        result = slim_commit_list(data)
        assert result["count"] == 1


class TestSlimCommitComment:
    def test_keeps_essential_fields(self):
        result = slim_commit_comment(SAMPLE_COMMIT_COMMENT)
        assert result["id"] == 555
        assert result["content"] == "Nice change."
        assert result["author"]["display_name"] == "Philippe LAWSON"
        assert "links" not in result

    def test_omits_resolution_noise(self):
        """Commit comments have no resolution lifecycle — those fields must be absent."""
        result = slim_commit_comment(SAMPLE_COMMIT_COMMENT)
        for field in ("is_resolved", "resolved_by", "resolved_on", "pending"):
            assert field not in result

    def test_inline_and_parent(self):
        comment = {
            **SAMPLE_COMMIT_COMMENT,
            "inline": {"path": "a.py", "from": None, "to": 12},
            "parent": {"id": 7},
        }
        result = slim_commit_comment(comment)
        assert result["inline"] == {"path": "a.py", "from": None, "to": 12}
        assert result["parent_id"] == 7

    def test_list(self):
        data = {"values": [SAMPLE_COMMIT_COMMENT], "page": 1}
        result = slim_commit_comment_list(data)
        assert result["count"] == 1
        assert "is_resolved" not in result["values"][0]


class TestSrcUrl:
    def test_root_path_has_trailing_slash(self):
        client = BitbucketClient("e@x.com", "token", "workspace")
        assert client._src_url("my-repo", COMMIT_HASH, "") == (
            f"/repositories/workspace/my-repo/src/{COMMIT_HASH}/"
        )

    def test_strips_leading_slash_and_encodes(self):
        client = BitbucketClient("e@x.com", "token", "workspace")
        url = client._src_url("my-repo", COMMIT_HASH, "/C#/Foo bar.cs")
        assert url == (
            f"/repositories/workspace/my-repo/src/{COMMIT_HASH}/C%23/Foo%20bar.cs"
        )
        assert url.count("//") == 0  # no double slash from the stripped leading '/'

    def test_rejects_parent_dir_traversal(self):
        client = BitbucketClient("e@x.com", "token", "workspace")
        with pytest.raises(ValueError, match="parent-directory"):
            client._src_url("my-repo", COMMIT_HASH, "../../other/secret.py")

    def test_rejects_mid_path_traversal(self):
        client = BitbucketClient("e@x.com", "token", "workspace")
        with pytest.raises(ValueError, match="parent-directory"):
            client._src_url("my-repo", COMMIT_HASH, "foo/../bar")

    def test_allows_dotted_names(self):
        """Names that merely contain dots ('..foo', 'foo..bar') stay allowed."""
        client = BitbucketClient("e@x.com", "token", "workspace")
        url = client._src_url("my-repo", COMMIT_HASH, "dir/..foo/foo..bar.txt")
        assert url.endswith("/..foo/foo..bar.txt")


class TestIsBinaryMimetype:
    @pytest.mark.parametrize("mt", [
        "image/png", "audio/mpeg", "video/mp4", "font/woff2",
        "application/octet-stream", "application/zip", "application/pdf",
        "APPLICATION/ZIP", "application/octet-stream; charset=binary",
    ])
    def test_binary(self, mt):
        assert _is_binary_mimetype(mt) is True

    @pytest.mark.parametrize("mt", [
        None, "", "text/plain", "text/x-python",
        "application/json", "application/javascript",
    ])
    def test_text(self, mt):
        assert _is_binary_mimetype(mt) is False


# ========== Client: commits (respx) ==========

@pytest.mark.asyncio
async def test_list_commits_no_revision():
    response = {"pagelen": 30, "size": 1, "page": 1, "values": [SAMPLE_COMMIT]}
    with respx.mock:
        route = respx.get(f"{REPO_URL}/commits").mock(
            return_value=httpx.Response(200, json=response)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            result = await client.list_commits("my-repo")
        assert result["values"][0]["hash"].startswith("abcdef")
        assert route.called


@pytest.mark.asyncio
async def test_list_commits_with_revision_and_filters():
    response = {"pagelen": 30, "size": 1, "page": 1, "values": [SAMPLE_COMMIT]}
    with respx.mock:
        route = respx.get(f"{REPO_URL}/commits/main").mock(
            return_value=httpx.Response(200, json=response)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            await client.list_commits(
                "my-repo", revision="main", path="src/app.py",
                include="main", exclude="develop"
            )
        params = route.calls.last.request.url.params
        assert params["path"] == "src/app.py"
        assert params["include"] == "main"
        assert params["exclude"] == "develop"


@pytest.mark.asyncio
async def test_get_commit():
    with respx.mock:
        respx.get(f"{REPO_URL}/commit/{COMMIT_HASH}").mock(
            return_value=httpx.Response(200, json=SAMPLE_COMMIT)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            result = await client.get_commit("my-repo", COMMIT_HASH)
        assert result["hash"].startswith("abcdef")


@pytest.mark.asyncio
async def test_get_commit_comments():
    response = {"pagelen": 10, "size": 1, "page": 1, "values": [SAMPLE_COMMIT_COMMENT]}
    with respx.mock:
        respx.get(f"{REPO_URL}/commit/{COMMIT_HASH}/comments").mock(
            return_value=httpx.Response(200, json=response)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            result = await client.get_commit_comments("my-repo", COMMIT_HASH)
        assert result["values"][0]["id"] == 555


@pytest.mark.asyncio
async def test_get_commit_comment():
    url = f"{REPO_URL}/commit/{COMMIT_HASH}/comments/555"
    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, json=SAMPLE_COMMIT_COMMENT))
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            result = await client.get_commit_comment("my-repo", COMMIT_HASH, "555")
        assert result["id"] == 555


@pytest.mark.asyncio
async def test_add_commit_comment_general_payload():
    url = f"{REPO_URL}/commit/{COMMIT_HASH}/comments"
    with respx.mock:
        route = respx.post(url).mock(
            return_value=httpx.Response(201, json=SAMPLE_COMMIT_COMMENT)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            await client.add_commit_comment("my-repo", COMMIT_HASH, "Looks good")
        import json
        body = json.loads(route.calls.last.request.content)
        assert body == {"content": {"raw": "Looks good"}}


@pytest.mark.asyncio
async def test_add_commit_comment_inline_payload():
    url = f"{REPO_URL}/commit/{COMMIT_HASH}/comments"
    with respx.mock:
        route = respx.post(url).mock(
            return_value=httpx.Response(201, json=SAMPLE_COMMIT_COMMENT)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            await client.add_commit_comment(
                "my-repo", COMMIT_HASH, "Bug here",
                inline_path="src/app.py", inline_from=5, inline_to=10
            )
        import json
        body = json.loads(route.calls.last.request.content)
        assert body["inline"] == {"path": "src/app.py", "from": 5, "to": 10}


# ========== Client: source /src (respx) ==========

def _src_meta_router(meta, content, content_status=200):
    """Build a respx side_effect that branches on the ?format=meta query param."""
    def handler(request):
        if request.url.params.get("format") == "meta":
            return httpx.Response(200, json=meta)
        return httpx.Response(content_status, text=content)
    return handler


@pytest.mark.asyncio
async def test_get_file_content_happy_path():
    meta = {"path": "src/app.py", "type": "commit_file", "size": 14,
            "mimetype": "text/x-python"}
    with respx.mock:
        respx.get(url__regex=rf".*/src/{COMMIT_HASH}/src/app\.py").mock(
            side_effect=_src_meta_router(meta, "print('hi')\n")
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            result = await client.get_file_content("my-repo", COMMIT_HASH, "src/app.py")
        assert result == "print('hi')\n"


@pytest.mark.asyncio
async def test_get_file_content_rejects_directory():
    meta = {"path": "src", "type": "commit_directory"}
    with respx.mock:
        respx.get(url__regex=rf".*/src/{COMMIT_HASH}/src").mock(
            return_value=httpx.Response(200, json=meta)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            with pytest.raises(ValueError, match="directory"):
                await client.get_file_content("my-repo", COMMIT_HASH, "src")


@pytest.mark.asyncio
async def test_get_file_content_rejects_oversized():
    meta = {"path": "big.json", "type": "commit_file", "size": 10_000_000,
            "mimetype": "application/json"}
    with respx.mock:
        respx.get(url__regex=rf".*/src/{COMMIT_HASH}/big\.json").mock(
            return_value=httpx.Response(200, json=meta)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            with pytest.raises(ValueError, match="exceeding"):
                await client.get_file_content(
                    "my-repo", COMMIT_HASH, "big.json", max_bytes=1024
                )


@pytest.mark.asyncio
async def test_get_file_content_rejects_binary():
    meta = {"path": "logo.png", "type": "commit_file", "size": 2048,
            "mimetype": "image/png"}
    with respx.mock:
        respx.get(url__regex=rf".*/src/{COMMIT_HASH}/logo\.png").mock(
            return_value=httpx.Response(200, json=meta)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            with pytest.raises(ValueError, match="binary"):
                await client.get_file_content("my-repo", COMMIT_HASH, "logo.png")


@pytest.mark.asyncio
async def test_get_file_content_encodes_special_path():
    """A '#' in the path must be percent-encoded, not sent as a URL fragment."""
    meta = {"path": "C#/Foo.cs", "type": "commit_file", "size": 5,
            "mimetype": "text/plain"}
    captured = {}

    def handler(request):
        if request.url.params.get("format") == "meta":
            captured["meta_url"] = str(request.url)
            return httpx.Response(200, json=meta)
        return httpx.Response(200, text="code\n")

    with respx.mock:
        respx.get(url__regex=r".*/src/.*").mock(side_effect=handler)
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            result = await client.get_file_content("my-repo", COMMIT_HASH, "C#/Foo.cs")
        assert result == "code\n"
        # '#' encoded as %23, so the fragment is never split off
        assert "%23" in captured["meta_url"]
        assert "C#/Foo.cs" not in captured["meta_url"]


@pytest.mark.asyncio
async def test_get_file_content_null_size_caught_post_download():
    """size=None bypasses the meta guard, so the post-download byte check must catch it."""
    meta = {"path": "big.txt", "type": "commit_file", "size": None,
            "mimetype": "text/plain"}
    big = "x" * 5000
    with respx.mock:
        respx.get(url__regex=rf".*/src/{COMMIT_HASH}/big\.txt").mock(
            side_effect=_src_meta_router(meta, big)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            with pytest.raises(ValueError, match="exceeding"):
                await client.get_file_content(
                    "my-repo", COMMIT_HASH, "big.txt", max_bytes=1024
                )


@pytest.mark.asyncio
async def test_get_file_content_pins_to_resolved_commit():
    """When commit is a branch, the content fetch must use the hash resolved by meta."""
    resolved = "fedcba9876543210"
    meta = {"path": "app.py", "type": "commit_file", "size": 5,
            "mimetype": "text/x-python", "commit": {"hash": resolved}}
    seen = {}

    def handler(request):
        if request.url.params.get("format") == "meta":
            return httpx.Response(200, json=meta)
        seen["content_url"] = str(request.url)
        return httpx.Response(200, text="code\n")

    with respx.mock:
        respx.get(url__regex=r".*/src/.*").mock(side_effect=handler)
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            result = await client.get_file_content("my-repo", "main", "app.py")
        assert result == "code\n"
        # content fetched from the pinned hash, not the moving branch ref
        assert f"/src/{resolved}/app.py" in seen["content_url"]
        assert "/src/main/" not in seen["content_url"]


@pytest.mark.asyncio
async def test_add_commit_comment_inline_line_zero_kept():
    """inline_from/inline_to == 0 must be sent (0 is a valid line, not 'unset')."""
    url = f"{REPO_URL}/commit/{COMMIT_HASH}/comments"
    with respx.mock:
        route = respx.post(url).mock(
            return_value=httpx.Response(201, json=SAMPLE_COMMIT_COMMENT)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            await client.add_commit_comment(
                "my-repo", COMMIT_HASH, "edge",
                inline_path="a.py", inline_from=0, inline_to=0
            )
        import json
        body = json.loads(route.calls.last.request.content)
        assert body["inline"] == {"path": "a.py", "from": 0, "to": 0}


@pytest.mark.asyncio
async def test_get_file_content_rejects_traversal():
    """A '..' segment must be rejected before any HTTP request is made."""
    async with BitbucketClient("e@x.com", "token", "workspace") as client:
        with pytest.raises(ValueError, match="parent-directory"):
            await client.get_file_content("my-repo", COMMIT_HASH, "../../etc/passwd")


@pytest.mark.asyncio
async def test_get_file_content_non_utf8_is_replaced():
    """A non-UTF-8 text file must not crash; undecodable bytes are replaced."""
    meta = {"path": "latin.txt", "type": "commit_file", "size": 5,
            "mimetype": "text/plain"}

    def handler(request):
        if request.url.params.get("format") == "meta":
            return httpx.Response(200, json=meta)
        return httpx.Response(
            200, content=b"caf\xe9\n", headers={"Content-Type": "text/plain"}
        )

    with respx.mock:
        respx.get(url__regex=rf".*/src/{COMMIT_HASH}/latin\.txt").mock(
            side_effect=handler
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            result = await client.get_file_content("my-repo", COMMIT_HASH, "latin.txt")
        assert isinstance(result, str)
        assert result.startswith("caf")  # 0xe9 replaced with U+FFFD, no crash


@pytest.mark.asyncio
async def test_add_commit_comment_inline_without_path_raises():
    """inline_from/inline_to without inline_path is a usage error, not silent."""
    async with BitbucketClient("e@x.com", "token", "workspace") as client:
        with pytest.raises(ValueError, match="inline_path is required"):
            await client.add_commit_comment(
                "my-repo", COMMIT_HASH, "x", inline_to=5
            )


@pytest.mark.asyncio
async def test_list_directory_happy_path():
    meta = {"path": "src", "type": "commit_directory"}

    def handler(request):
        if request.url.params.get("format") == "meta":
            return httpx.Response(200, json=meta)
        return httpx.Response(200, json=SAMPLE_DIR_LISTING)

    with respx.mock:
        respx.get(url__regex=rf".*/src/{COMMIT_HASH}/src").mock(side_effect=handler)
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            result = await client.list_directory("my-repo", COMMIT_HASH, "src")
        assert len(result["values"]) == 2
        assert result["values"][0]["path"] == "src/app.py"


@pytest.mark.asyncio
async def test_list_directory_rejects_traversal():
    """list_directory must inherit the '..' guard before any HTTP request."""
    async with BitbucketClient("e@x.com", "token", "workspace") as client:
        with pytest.raises(ValueError, match="parent-directory"):
            await client.list_directory("my-repo", COMMIT_HASH, "../../etc")


@pytest.mark.asyncio
async def test_list_directory_rejects_file():
    meta = {"path": "src/app.py", "type": "commit_file", "size": 10}
    with respx.mock:
        respx.get(url__regex=rf".*/src/{COMMIT_HASH}/src/app\.py").mock(
            return_value=httpx.Response(200, json=meta)
        )
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            with pytest.raises(ValueError, match="file"):
                await client.list_directory("my-repo", COMMIT_HASH, "src/app.py")


@pytest.mark.asyncio
async def test_list_directory_follows_redirect():
    """The /src listing 302-redirects to a commit-pinned URL; it must be followed."""
    meta = {"path": "", "type": "commit_directory"}
    pinned = f"{REPO_URL}/src/{COMMIT_HASH}/"

    def handler(request):
        if request.url.params.get("format") == "meta":
            return httpx.Response(200, json=meta)
        # First hit on the branch URL redirects to the pinned hash URL
        if "/src/main/" in str(request.url):
            return httpx.Response(302, headers={"Location": pinned})
        return httpx.Response(200, json=SAMPLE_DIR_LISTING)

    with respx.mock:
        respx.get(url__regex=r".*/src/.*").mock(side_effect=handler)
        async with BitbucketClient("e@x.com", "token", "workspace") as client:
            result = await client.list_directory("my-repo", "main", "")
        assert len(result["values"]) == 2


# ========== Server tools (AsyncMock) ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_commits_tool(mock_get_client):
    from src.server import list_commits

    mock_client = AsyncMock()
    mock_client.list_commits.return_value = {"page": 1, "values": [SAMPLE_COMMIT]}
    mock_get_client.return_value = mock_client

    result = await list_commits("my-repo", revision="main")

    mock_client.list_commits.assert_awaited_once_with(
        "my-repo", "main", None, None, None, None, 30, 1
    )
    assert result["values"][0]["hash"] == "abcdef123456"
    assert result["count"] == 1


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_commit_tool(mock_get_client):
    from src.server import get_commit

    mock_client = AsyncMock()
    mock_client.get_commit.return_value = SAMPLE_COMMIT
    mock_get_client.return_value = mock_client

    result = await get_commit("my-repo", COMMIT_HASH)

    mock_client.get_commit.assert_awaited_once_with("my-repo", COMMIT_HASH, None)
    assert result["hash"] == "abcdef123456"
    assert "links" not in result


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_file_content_tool_returns_raw_text(mock_get_client):
    from src.server import get_file_content

    mock_client = AsyncMock()
    mock_client.get_file_content.return_value = "print('hi')\n"
    mock_get_client.return_value = mock_client

    result = await get_file_content("my-repo", COMMIT_HASH, "src/app.py")

    mock_client.get_file_content.assert_awaited_once_with(
        "my-repo", COMMIT_HASH, "src/app.py", None, 262144
    )
    assert result == "print('hi')\n"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_directory_tool(mock_get_client):
    from src.server import list_directory

    mock_client = AsyncMock()
    mock_client.list_directory.return_value = SAMPLE_DIR_LISTING
    mock_get_client.return_value = mock_client

    result = await list_directory("my-repo", COMMIT_HASH, "src")

    mock_client.list_directory.assert_awaited_once_with(
        "my-repo", COMMIT_HASH, "src", None, 50, 1
    )
    assert result["count"] == 2
    assert result["values"][0]["type"] == "commit_file"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_commit_comments_tool(mock_get_client):
    from src.server import get_commit_comments

    mock_client = AsyncMock()
    mock_client.get_commit_comments.return_value = {
        "page": 1, "values": [SAMPLE_COMMIT_COMMENT]
    }
    mock_get_client.return_value = mock_client

    result = await get_commit_comments("my-repo", COMMIT_HASH)

    mock_client.get_commit_comments.assert_awaited_once_with(
        "my-repo", COMMIT_HASH, None, 10, 1
    )
    assert result["values"][0]["id"] == 555
    assert result["count"] == 1
    # uses the dedicated commit-comment slim (no resolution noise)
    assert "is_resolved" not in result["values"][0]


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_commit_comment_tool(mock_get_client):
    from src.server import get_commit_comment

    mock_client = AsyncMock()
    mock_client.get_commit_comment.return_value = SAMPLE_COMMIT_COMMENT
    mock_get_client.return_value = mock_client

    result = await get_commit_comment("my-repo", COMMIT_HASH, "555")

    mock_client.get_commit_comment.assert_awaited_once_with(
        "my-repo", COMMIT_HASH, "555", None
    )
    assert result["id"] == 555
    assert "links" not in result
    assert "is_resolved" not in result


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_add_commit_comment_tool_disabled_but_callable(mock_get_client):
    """add_commit_comment is disabled in tools.json but remains a callable function."""
    from src.server import add_commit_comment

    mock_client = AsyncMock()
    mock_client.add_commit_comment.return_value = SAMPLE_COMMIT_COMMENT
    mock_get_client.return_value = mock_client

    result = await add_commit_comment("my-repo", COMMIT_HASH, "hi")

    assert result["id"] == 555
    # response is passed through the slim transformer
    assert result["content"] == "Nice change."
    assert "links" not in result
