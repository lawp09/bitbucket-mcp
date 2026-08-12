"""Tests for get_pipeline_step_logs (issue #74).

Covers the two root-cause fixes — the ``Accept: */*`` override that unblocks the
406, and following the 307 to long-term storage — plus the size-bounding, range
handling and service-container support built on top of them.
"""

import httpx
import pytest
import respx
from unittest.mock import AsyncMock, patch

from src import client as client_module
from src.client import (
    BitbucketClient,
    DEFAULT_MAX_LOG_BYTES,
    _build_log_range,
    _parse_content_range,
)

WORKSPACE = "test_workspace"
REPO = "test-repo"
PIPELINE_UUID = "{adab6a1f-1111-2222-3333-444455556666}"
STEP_UUID = "{84fc6465-7777-8888-9999-aaaabbbbcccc}"

LOG_URL = (
    f"https://api.bitbucket.org/2.0/repositories/{WORKSPACE}/{REPO}"
    f"/pipelines/{PIPELINE_UUID}/steps/{STEP_UUID}/log"
)
STORAGE_URL = "https://bitbucket-pipelines-logs.s3.amazonaws.com/presigned-log"


@pytest.fixture
def bb_client():
    """A client whose async transport is safe to close between tests."""
    return BitbucketClient("test@example.com", "token", WORKSPACE)


async def _get_logs(bb_client, **kwargs):
    return await bb_client.get_pipeline_step_logs(REPO, PIPELINE_UUID, STEP_UUID, **kwargs)


# ========== Root cause 1: the 406 ==========


@pytest.mark.asyncio
async def test_sends_accept_wildcard_not_json(bb_client):
    """The log endpoint produces octet-stream; Accept: application/json 406s."""
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"build ok"))
        result = await _get_logs(bb_client)

    assert route.call_count == 1
    assert route.calls[0].request.headers["Accept"] == "*/*"
    assert result["content"] == "build ok"


@pytest.mark.asyncio
async def test_json_accept_default_untouched_for_other_calls(bb_client):
    """The override is per-request: every other endpoint still asks for JSON."""
    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"x"))
        await _get_logs(bb_client)

        repo_url = f"https://api.bitbucket.org/2.0/repositories/{WORKSPACE}/{REPO}"
        route = respx.get(repo_url).mock(return_value=httpx.Response(200, json={"slug": REPO}))
        await bb_client.get_repository(REPO)

    assert route.calls[0].request.headers["Accept"] == "application/json"
    assert bb_client.client.headers["Accept"] == "application/json"


# ========== Root cause 2: the 307 to long-term storage ==========


@pytest.mark.asyncio
async def test_follows_307_redirect_to_storage(bb_client):
    """Completed steps 307 to long-term storage; the redirect must be followed."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(307, headers={"Location": STORAGE_URL})
        )
        respx.get(STORAGE_URL).mock(
            return_value=httpx.Response(200, content=b"archived log body")
        )
        result = await _get_logs(bb_client)

    assert result["content"] == "archived log body"
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_credentials_not_forwarded_to_storage_host(bb_client):
    """The redirect target is pre-signed: Bitbucket credentials must not leak to it."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(307, headers={"Location": STORAGE_URL})
        )
        storage = respx.get(STORAGE_URL).mock(
            return_value=httpx.Response(200, content=b"body")
        )
        await _get_logs(bb_client)

    assert "Authorization" not in storage.calls[0].request.headers


# ========== Size bounding ==========


@pytest.mark.asyncio
async def test_default_requests_suffix_range(bb_client):
    """Default call asks for the trailing 100 KiB rather than the whole log."""
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"tail"))
        await _get_logs(bb_client)

    assert route.calls[0].request.headers["Range"] == f"bytes=-{DEFAULT_MAX_LOG_BYTES}"


@pytest.mark.asyncio
async def test_partial_content_parses_total_and_flags_truncation(bb_client):
    """206 honoured: Content-Range gives the real total."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(
                206,
                content=b"last ten!!",
                headers={"Content-Range": "bytes 990-999/1000"},
            )
        )
        result = await _get_logs(bb_client, max_bytes=10)

    assert result == {
        "content": "last ten!!",
        "truncated": True,
        "returned_bytes": 10,
        "total_bytes": 1000,
    }


@pytest.mark.asyncio
async def test_tail_reconstructed_when_server_ignores_range(bb_client):
    """200 with the whole body: the tail is carved out client-side."""
    body = b"".join(f"{i:04d}".encode() for i in range(512))  # 2048 bytes
    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=body))
        result = await _get_logs(bb_client, max_bytes=64)

    # The *tail*, not merely 64 bytes from somewhere.
    assert result["content"] == body[-64:].decode()
    assert result["returned_bytes"] == 64
    assert result["truncated"] is True
    assert result["total_bytes"] == 2048


@pytest.mark.asyncio
async def test_small_body_is_not_truncated(bb_client):
    """A log shorter than the cap comes back whole."""
    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"short log"))
        result = await _get_logs(bb_client)

    assert result == {
        "content": "short log",
        "truncated": False,
        "returned_bytes": 9,
        "total_bytes": 9,
    }


@pytest.mark.asyncio
async def test_explicit_window_honoured_when_server_ignores_range(bb_client):
    """The regression this guards: an ignored Range must not yield the tail."""
    body = b"".join(f"{i:04d}".encode() for i in range(100))  # 400 bytes
    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=body))
        result = await _get_logs(bb_client, start=40, end=59)

    assert result["content"] == body[40:60].decode()
    assert result["returned_bytes"] == 20
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_open_ended_window_reads_to_end(bb_client):
    """start without end: everything from that offset onwards."""
    body = b"0123456789"
    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=body))
        result = await _get_logs(bb_client, start=6)

    assert result["content"] == "6789"
    assert result["truncated"] is True
    assert result["total_bytes"] == 10


@pytest.mark.asyncio
async def test_explicit_window_covering_whole_log_is_not_truncated(bb_client):
    """A window that happens to span the log is reported as complete."""
    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"abcdef"))
        result = await _get_logs(bb_client, start=0, end=99)

    assert result["content"] == "abcdef"
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_ceiling_message_when_no_range_was_requested(bb_client, monkeypatch):
    """max_bytes=None sends no Range at all — the message must not imply one."""
    monkeypatch.setattr(client_module, "MAX_LOG_STREAM_BYTES", 1024)
    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"z" * 4096))
        with pytest.raises(ValueError, match="no range was requested"):
            await _get_logs(bb_client, max_bytes=None)


@pytest.mark.asyncio
async def test_max_bytes_none_returns_whole_log_without_range(bb_client):
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"all of it"))
        result = await _get_logs(bb_client, max_bytes=None)

    assert "Range" not in route.calls[0].request.headers
    assert result["content"] == "all of it"
    assert result["truncated"] is False


# ========== Multi-chunk streaming ==========
#
# respx delivers a bytes `content=` as a single chunk, which would leave the
# per-chunk offset arithmetic — the whole point of streaming — untested. These
# tests feed the body as an async iterator so it really arrives in several chunks.


async def _chunks(*parts: bytes):
    for part in parts:
        yield part


CHUNKED_BODY = (b"0123456789", b"abcdefghij", b"KLMNOPQRST")  # 30 bytes total
CHUNKED_FLAT = b"".join(CHUNKED_BODY)


@pytest.mark.asyncio
async def test_carve_spans_chunk_boundaries(bb_client):
    """A window straddling three chunks is reassembled byte-exactly."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(200, content=_chunks(*CHUNKED_BODY))
        )
        result = await _get_logs(bb_client, start=8, end=21)

    assert result["content"] == CHUNKED_FLAT[8:22].decode()  # "89abcdefghijKL"
    assert result["returned_bytes"] == 14


@pytest.mark.asyncio
async def test_carve_stops_early_once_window_is_complete(bb_client):
    """Window opens in chunk 0, closes in chunk 1, chunk 2 is never read.

    Because bytes are left unread, the total size is honestly unknown.
    """
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(200, content=_chunks(*CHUNKED_BODY))
        )
        result = await _get_logs(bb_client, start=8, end=13)

    assert result["content"] == CHUNKED_FLAT[8:14].decode()  # "89abcd"
    assert result["truncated"] is True
    assert result["total_bytes"] is None


@pytest.mark.asyncio
async def test_window_ending_exactly_at_eof_is_not_reported_truncated(bb_client):
    """`end` on the very last byte is a complete read, not a truncated one."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(200, content=_chunks(*CHUNKED_BODY))
        )
        result = await _get_logs(bb_client, start=0, end=len(CHUNKED_FLAT) - 1)

    assert result["content"] == CHUNKED_FLAT.decode()
    assert result["total_bytes"] == 30
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_empty_chunk_between_data_chunks_does_not_end_the_read(bb_client):
    """An empty chunk mid-stream must not be mistaken for end-of-log.

    httpx drops zero-length chunks before `aiter_bytes()` yields them, so the
    `if extra:` guard in `_read_capped_stream` is belt-and-braces for transports
    that don't; what this pins is the observable outcome.
    """
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(
                200, content=_chunks(b"0123456789", b"", b"abcdefghij")
            )
        )
        result = await _get_logs(bb_client, start=2, end=5)

    assert result["content"] == "2345"
    # Real data followed, so the read is genuinely incomplete.
    assert result["truncated"] is True
    assert result["total_bytes"] is None


@pytest.mark.asyncio
async def test_trailing_empty_chunk_still_counts_as_eof(bb_client):
    """A stream ending on an empty chunk is still a complete read."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(200, content=_chunks(b"0123456789", b""))
        )
        result = await _get_logs(bb_client, start=0, end=9)

    assert result["content"] == "0123456789"
    assert result["truncated"] is False
    assert result["total_bytes"] == 10


@pytest.mark.asyncio
async def test_tail_trimming_across_chunk_boundaries(bb_client):
    """The rolling buffer keeps the true tail, not the tail of one chunk."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(200, content=_chunks(*CHUNKED_BODY))
        )
        result = await _get_logs(bb_client, max_bytes=7)

    assert result["content"] == CHUNKED_FLAT[-7:].decode()  # "NOPQRST"
    assert result["total_bytes"] == 30
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_open_ended_carve_reads_every_remaining_chunk(bb_client):
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(200, content=_chunks(*CHUNKED_BODY))
        )
        result = await _get_logs(bb_client, start=15)

    assert result["content"] == CHUNKED_FLAT[15:].decode()
    assert result["total_bytes"] == 30


# ========== Range header construction & validation ==========


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"start": 10, "end": 20}, "bytes=10-20"),
        ({"start": 10}, "bytes=10-"),
        ({"end": 20}, "bytes=0-20"),  # end alone => absolute window from byte 0
        ({"max_bytes": 512}, "bytes=-512"),
    ],
)
@pytest.mark.asyncio
async def test_range_header_variants(bb_client, kwargs, expected):
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"x"))
        await _get_logs(bb_client, **kwargs)

    assert route.calls[0].request.headers["Range"] == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start": -1},
        {"end": -5},
        {"start": 100, "end": 50},
        {"max_bytes": 0},
        {"max_bytes": -10},
        {"start": "10"},
        {"start": True},
    ],
)
@pytest.mark.asyncio
async def test_invalid_range_raises_before_any_request(bb_client, kwargs):
    """Bad input fails locally with a clear message, not as an opaque 400/416."""
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"x"))
        with pytest.raises(ValueError):
            await _get_logs(bb_client, **kwargs)

    assert route.call_count == 0


# ========== 416 & defensive Content-Range parsing ==========


@pytest.mark.asyncio
async def test_416_raises_value_error_with_size_hint(bb_client):
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(416, headers={"Content-Range": "bytes */2048"})
        )
        with pytest.raises(ValueError, match="2048 bytes"):
            await _get_logs(bb_client, start=9000, end=9100)


@pytest.mark.asyncio
async def test_416_without_usable_content_range_still_raises_cleanly(bb_client):
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(416, headers={"Content-Range": "bytes */*"})
        )
        with pytest.raises(ValueError, match="not satisfiable"):
            await _get_logs(bb_client, start=9000)


@pytest.mark.asyncio
async def test_206_with_unknown_total_reports_none(bb_client):
    """`bytes 0-9/*` is legal: the total is unknown, not zero."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(
                206, content=b"0123456789", headers={"Content-Range": "bytes 0-9/*"}
            )
        )
        result = await _get_logs(bb_client, max_bytes=10)

    assert result["total_bytes"] is None
    assert result["truncated"] is True


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, (None, None, None)),
        ("", (None, None, None)),
        ("garbage", (None, None, None)),
        ("bytes 0-99/2048", (0, 99, 2048)),
        ("bytes 0-99/*", (0, 99, None)),
        ("bytes */2048", (None, None, 2048)),
        ("bytes */*", (None, None, None)),
        ("bytes abc-def/2048", (None, None, None)),
    ],
)
def test_parse_content_range(header, expected):
    assert _parse_content_range(header) == expected


def test_build_log_range_returns_no_header_for_unbounded_request():
    assert _build_log_range(None, None, None) == (None, None, None)


# ========== Errors & streaming ceiling ==========


@pytest.mark.asyncio
async def test_404_bubbles_up_as_http_error(bb_client):
    """No silent failure when the pipeline/step/log does not exist."""
    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(404, json={"error": "nope"}))
        with pytest.raises(httpx.HTTPStatusError):
            await _get_logs(bb_client)


@pytest.mark.asyncio
async def test_streaming_ceiling_aborts_oversized_log(bb_client, monkeypatch):
    """Ceiling patched down so the suite does not allocate 50 MiB."""
    monkeypatch.setattr(client_module, "MAX_LOG_STREAM_BYTES", 1024)
    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"x" * 4096))
        with pytest.raises(ValueError, match="did not honour the requested range"):
            await _get_logs(bb_client, max_bytes=64)


@pytest.mark.asyncio
async def test_streaming_ceiling_applies_to_honoured_range_too(bb_client, monkeypatch):
    """A 206 can still be huge on an open-ended window — the cap is uniform.

    The message must not blame the server here: it *did* honour the range; the
    caller's own window is simply too wide.
    """
    monkeypatch.setattr(client_module, "MAX_LOG_STREAM_BYTES", 1024)
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(
                206,
                content=b"y" * 4096,
                headers={"Content-Range": "bytes 0-4095/999999"},
            )
        )
        with pytest.raises(ValueError, match="for the range that was served") as excinfo:
            await _get_logs(bb_client, start=0)

    assert "did not honour" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_non_utf8_bytes_decode_without_raising(bb_client):
    """Logs carry ANSI/control bytes; a decode error must not kill the call."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(200, content=b"ok \xff\xfe done")
        )
        result = await _get_logs(bb_client)

    assert result["content"].startswith("ok ")
    assert result["content"].endswith(" done")


# ========== Service container logs ==========


@pytest.mark.asyncio
async def test_log_uuid_targets_service_container_endpoint(bb_client):
    log_uuid = "{deadbeef-0000-1111-2222-333344445555}"
    logs_url = (
        f"https://api.bitbucket.org/2.0/repositories/{WORKSPACE}/{REPO}"
        f"/pipelines/{PIPELINE_UUID}/steps/{STEP_UUID}/logs/{log_uuid}"
    )
    with respx.mock:
        route = respx.get(logs_url).mock(
            return_value=httpx.Response(200, content=b"service log")
        )
        result = await _get_logs(bb_client, log_uuid=log_uuid)

    assert route.call_count == 1
    assert result["content"] == "service log"


@pytest.mark.asyncio
async def test_workspace_override(bb_client):
    other_url = (
        f"https://api.bitbucket.org/2.0/repositories/other-ws/{REPO}"
        f"/pipelines/{PIPELINE_UUID}/steps/{STEP_UUID}/log"
    )
    with respx.mock:
        route = respx.get(other_url).mock(return_value=httpx.Response(200, content=b"l"))
        await _get_logs(bb_client, workspace="other-ws")

    assert route.call_count == 1


# ========== Server layer ==========


@pytest.mark.asyncio
async def test_server_tool_forwards_every_parameter():
    from src.server import get_pipeline_step_logs

    payload = {
        "content": "log",
        "truncated": True,
        "returned_bytes": 3,
        "total_bytes": 900,
    }
    mock_client = AsyncMock()
    mock_client.get_pipeline_step_logs = AsyncMock(return_value=payload)

    with patch("src.server.get_client", return_value=mock_client):
        result = await get_pipeline_step_logs(
            repo_slug=REPO,
            pipeline_uuid=PIPELINE_UUID,
            step_uuid=STEP_UUID,
            workspace="ws",
            log_uuid="{log-uuid}",
            start=10,
            end=99,
            max_bytes=4096,
        )

    assert result == payload
    mock_client.get_pipeline_step_logs.assert_awaited_once_with(
        REPO,
        PIPELINE_UUID,
        STEP_UUID,
        "ws",
        log_uuid="{log-uuid}",
        start=10,
        end=99,
        max_bytes=4096,
    )


@pytest.mark.asyncio
async def test_server_tool_defaults_to_tail():
    from src.server import get_pipeline_step_logs

    mock_client = AsyncMock()
    mock_client.get_pipeline_step_logs = AsyncMock(return_value={"content": ""})

    with patch("src.server.get_client", return_value=mock_client):
        await get_pipeline_step_logs(
            repo_slug=REPO, pipeline_uuid=PIPELINE_UUID, step_uuid=STEP_UUID
        )

    kwargs = mock_client.get_pipeline_step_logs.await_args.kwargs
    assert kwargs["max_bytes"] == DEFAULT_MAX_LOG_BYTES
    assert kwargs["log_uuid"] is None
