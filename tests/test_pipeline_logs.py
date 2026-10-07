"""Tests for get_pipeline_step_logs (issues #74 and #80).

Covers the root-cause fixes — the ``Accept: */*`` override that unblocks the 406,
following the 307 to long-term storage, and dropping the suffix ``Range`` the
endpoint's inline serving mode answers 503 to — plus the size-bounding, range
handling and service-container support built on top of them.

A default (tail) call makes **two** requests: a one-byte size probe, then the tail
as an absolute range. Both are GETs on the same URL, so one ``respx`` route serves
both legs; ``calls[0]`` is the probe and ``calls[-1]`` the fetch.
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
    _tail_window,
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

    assert route.call_count == 2  # size probe, then the tail fetch
    assert all(call.request.headers["Accept"] == "*/*" for call in route.calls)
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
async def test_never_sends_a_suffix_range(bb_client):
    """Regression for #80: the suffix form 503s on the inline serving mode.

    The one form this client must never put on the wire, whatever the path taken.
    """
    body = b"x" * 5000
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=body))
        await _get_logs(bb_client, max_bytes=100)

    sent = [call.request.headers.get("Range") for call in route.calls]
    assert not any(r and r.startswith("bytes=-") for r in sent), sent


@pytest.mark.asyncio
async def test_default_probes_size_then_fetches_an_absolute_tail(bb_client):
    """The tail is expressed as an absolute range derived from a one-byte probe."""
    body = b"x" * 5000
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=body))
        result = await _get_logs(bb_client, max_bytes=100)

    assert route.calls[0].request.headers["Range"] == "bytes=0-0"
    assert route.calls[-1].request.headers["Range"] == "bytes=4900-"
    assert result["returned_bytes"] == 100
    assert result["total_bytes"] == 5000


@pytest.mark.asyncio
async def test_probe_reads_the_total_from_content_range_on_a_206(bb_client):
    """A server honouring `bytes=0-0` reports the total in Content-Range."""
    with respx.mock:
        route = respx.get(LOG_URL).mock(
            side_effect=[
                httpx.Response(
                    206, content=b"0", headers={"Content-Range": "bytes 0-0/900"}
                ),
                httpx.Response(
                    206,
                    content=b"tail bytes",
                    headers={"Content-Range": "bytes 890-899/900"},
                ),
            ]
        )
        result = await _get_logs(bb_client, max_bytes=10)

    assert route.calls[-1].request.headers["Range"] == "bytes=890-"
    assert result["content"] == "tail bytes"
    assert result["total_bytes"] == 900
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_probe_ignores_content_length_on_a_206(bb_client):
    """On a 206, Content-Length measures the one-byte part, not the whole log.

    Reading it as the total would derive a window from the number 1.
    """
    with respx.mock:
        route = respx.get(LOG_URL).mock(
            side_effect=[
                httpx.Response(
                    206, content=b"0", headers={"Content-Range": "bytes 0-0/4096"}
                ),
                httpx.Response(200, content=b"y" * 4096),
            ]
        )
        await _get_logs(bb_client, max_bytes=64)

    assert route.calls[-1].request.headers["Range"] == "bytes=4032-"


@pytest.mark.asyncio
async def test_tail_overshoot_is_trimmed_when_the_log_grows(bb_client):
    """The window is open-ended, so a growing log can overshoot `max_bytes`.

    What comes back must still be the *current* tail, and still be bounded.
    """
    with respx.mock:
        respx.get(LOG_URL).mock(
            side_effect=[
                httpx.Response(
                    206, content=b"0", headers={"Content-Range": "bytes 0-0/100"}
                ),
                # By fetch time the step has written 60 more bytes.
                httpx.Response(
                    206,
                    content=b"A" * 20 + b"B" * 60,
                    headers={"Content-Range": "bytes 80-159/160"},
                ),
            ]
        )
        result = await _get_logs(bb_client, max_bytes=20)

    assert result["content"] == "B" * 20  # the newest bytes, not the stale ones
    assert result["returned_bytes"] == 20
    assert result["total_bytes"] == 160
    assert result["truncated"] is True


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
    ],
)
@pytest.mark.asyncio
async def test_range_header_variants(bb_client, kwargs, expected):
    """Explicit windows only — a tail has no header of its own (see the tail tests)."""
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"x"))
        await _get_logs(bb_client, **kwargs)

    assert route.call_count == 1  # an explicit window never probes
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

    assert route.call_count == 2  # the probe targets the service-container URL too
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

    assert route.call_count == 2  # probe + fetch, both on the overridden workspace


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


# ========== Bearer (multi-tenant) clients on the streaming path (#72) ==========
#
# get_pipeline_step_logs is the only method combining a bearer client's 401/403 response
# hook with `client.stream(...)` and `follow_redirects=True`. The hook runs once per
# response leg, inside _send_handling_redirects, before stream() yields — so it must not
# disturb the 307 follow, the streamed body, or the expected 416.


@pytest.fixture
def bearer_client():
    """A multi-tenant client: bearer auth + the 401/403 -> AuthorizationError hook."""
    return BitbucketClient.from_bearer("bearer-token-abc", WORKSPACE, account_id="account-a")


@pytest.mark.asyncio
async def test_bearer_client_follows_the_307_and_streams(bearer_client):
    """The auth hook must not break the redirect or the streamed body."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(307, headers={"Location": STORAGE_URL})
        )
        respx.get(STORAGE_URL).mock(
            return_value=httpx.Response(200, content=b"archived log body")
        )
        result = await _get_logs(bearer_client)

    assert result["content"] == "archived log body"
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_bearer_client_maps_403_on_the_log_endpoint(bearer_client):
    """A 403 on the streaming path surfaces as AuthorizationError, without the token."""
    from src.client import AuthorizationError

    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(403, json={}))
        with pytest.raises(AuthorizationError) as exc:
            await _get_logs(bearer_client)

    assert exc.value.status_code == 403
    assert "bearer-token-abc" not in str(exc.value)


@pytest.mark.asyncio
async def test_bearer_client_still_reports_an_unsatisfiable_range(bearer_client):
    """416 is a legitimate outcome here and must not be swallowed by the auth hook."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(416, headers={"Content-Range": "bytes */120"})
        )
        with pytest.raises(ValueError, match="not satisfiable"):
            await _get_logs(bearer_client, start=500, end=900)


@pytest.mark.asyncio
async def test_bearer_client_sends_bearer_and_wildcard_accept(bearer_client):
    """Both the per-request Accept override and the bearer scheme reach the wire."""
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"log"))
        await _get_logs(bearer_client)

    request = route.calls[0].request
    assert request.headers["Accept"] == "*/*"
    assert request.headers["Authorization"] == "Bearer bearer-token-abc"


# ========== Size probe: failure modes (#80) ==========
#
# Every way the probe can decline to answer must land on the same fallback: fetch
# without a Range and keep the tail client-side. That reads far more than it
# returns, but it returns the right bytes.


def _probe_then(*responses: httpx.Response):
    """Mock the probe leg and the fetch leg of one default (tail) call."""
    return respx.get(LOG_URL).mock(side_effect=list(responses))


@pytest.mark.parametrize(
    "probe_response",
    [
        httpx.Response(405),  # method/range not allowed
        httpx.Response(500),  # storage hiccup
        httpx.Response(503),  # the very status #80 is about
    ],
    ids=["405", "500", "503"],
)
@pytest.mark.asyncio
async def test_probe_failure_falls_back_to_an_unranged_read(bb_client, probe_response):
    body = b"".join(f"{i:04d}".encode() for i in range(512))  # 2048 bytes
    with respx.mock:
        route = _probe_then(probe_response, httpx.Response(200, content=body))
        result = await _get_logs(bb_client, max_bytes=64)

    assert "Range" not in route.calls[-1].request.headers
    assert result["content"] == body[-64:].decode()
    assert result["total_bytes"] == 2048
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_probe_transport_error_falls_back(bb_client):
    """A probe that never reaches the server must not fail the call."""
    with respx.mock:
        route = _probe_then(
            httpx.ConnectError("no route to host"),
            httpx.Response(200, content=b"recovered log"),
        )
        result = await _get_logs(bb_client, max_bytes=64)

    assert route.call_count == 2
    assert result["content"] == "recovered log"
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_probe_without_content_length_falls_back(bb_client):
    """A chunked 200 discloses no size, so there is no window to derive."""
    with respx.mock:
        route = _probe_then(
            httpx.Response(200, content=_chunks(b"0123456789", b"abcdefghij")),
            httpx.Response(200, content=b"0123456789abcdefghij"),
        )
        result = await _get_logs(bb_client, max_bytes=5)

    assert "Content-Length" not in route.calls[0].response.headers
    assert "Range" not in route.calls[-1].request.headers
    assert result["content"] == "fghij"


@pytest.mark.asyncio
async def test_probe_with_unknown_total_in_content_range_falls_back(bb_client):
    """`bytes 0-0/*` is legal and says the total is unknown, not that it is zero."""
    with respx.mock:
        route = _probe_then(
            httpx.Response(206, content=b"0", headers={"Content-Range": "bytes 0-0/*"}),
            httpx.Response(200, content=b"abcdefghij"),
        )
        result = await _get_logs(bb_client, max_bytes=4)

    assert "Range" not in route.calls[-1].request.headers
    assert result["content"] == "ghij"


@pytest.mark.asyncio
async def test_probe_reporting_zero_is_treated_as_unknown(bb_client):
    """A zero would derive an empty window and cost the caller the whole tail."""
    with respx.mock:
        route = _probe_then(
            httpx.Response(206, content=b"", headers={"Content-Range": "bytes 0-0/0"}),
            httpx.Response(200, content=b"not actually empty"),
        )
        result = await _get_logs(bb_client, max_bytes=6)

    assert "Range" not in route.calls[-1].request.headers
    assert result["content"] == " empty"  # the tail of "not actually empty"
    assert result["total_bytes"] == 18


@pytest.mark.asyncio
async def test_genuinely_empty_log_is_not_reported_truncated(bb_client):
    with respx.mock:
        _probe_then(httpx.Response(200, content=b""), httpx.Response(200, content=b""))
        result = await _get_logs(bb_client)

    assert result == {
        "content": "",
        "truncated": False,
        "returned_bytes": 0,
        "total_bytes": 0,
    }


@pytest.mark.asyncio
async def test_ceiling_message_when_an_honoured_tail_window_overshoots(
    bb_client, monkeypatch
):
    """The tail window is open-ended, so a 206 can overrun with nobody at fault.

    Blaming the server for "not honouring" the range here would be backwards: it
    honoured exactly what it was sent, and what it was sent has no upper bound.
    """
    monkeypatch.setattr(client_module, "MAX_LOG_STREAM_BYTES", 1024)
    with respx.mock:
        _probe_then(
            httpx.Response(
                206, content=b"0", headers={"Content-Range": "bytes 0-0/999999"}
            ),
            httpx.Response(
                206,
                content=b"z" * 4096,
                headers={"Content-Range": "bytes 899999-999998/999999"},
            ),
        )
        with pytest.raises(ValueError, match="open-ended tail window that was served") as exc:
            await _get_logs(bb_client, max_bytes=100000)

    assert "did not honour" not in str(exc.value)


@pytest.mark.asyncio
async def test_ceiling_message_when_the_server_ignored_the_tail_window(
    bb_client, monkeypatch
):
    """The same mode, but a 200: here the server really did ignore the range."""
    monkeypatch.setattr(client_module, "MAX_LOG_STREAM_BYTES", 1024)
    with respx.mock:
        _probe_then(
            httpx.Response(206, content=b"0", headers={"Content-Range": "bytes 0-0/4096"}),
            httpx.Response(200, content=b"z" * 4096),
        )
        with pytest.raises(ValueError, match="did not honour the requested range"):
            await _get_logs(bb_client, max_bytes=64)


@pytest.mark.asyncio
async def test_ceiling_message_when_the_size_could_not_be_probed(bb_client, monkeypatch):
    """The fallback sends no Range, so neither the caller nor the server is to blame."""
    monkeypatch.setattr(client_module, "MAX_LOG_STREAM_BYTES", 1024)
    with respx.mock:
        _probe_then(httpx.Response(405), httpx.Response(200, content=b"x" * 4096))
        with pytest.raises(ValueError, match="could not be determined in advance"):
            await _get_logs(bb_client, max_bytes=64)


# ========== Size probe: when it must not run at all ==========


@pytest.mark.asyncio
async def test_explicit_window_skips_the_probe(bb_client):
    with respx.mock:
        route = respx.get(LOG_URL).mock(
            return_value=httpx.Response(200, content=b"0123456789")
        )
        await _get_logs(bb_client, start=2, end=5)

    assert route.call_count == 1
    assert route.calls[0].request.headers["Range"] == "bytes=2-5"


@pytest.mark.asyncio
async def test_max_bytes_none_skips_the_probe(bb_client):
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"all"))
        await _get_logs(bb_client, max_bytes=None)

    assert route.call_count == 1
    assert "Range" not in route.calls[0].request.headers


@pytest.mark.asyncio
async def test_invalid_input_raises_before_the_probe(bb_client):
    """Validation runs first, so a bad argument costs no request at all."""
    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(200, content=b"x"))
        with pytest.raises(ValueError):
            await _get_logs(bb_client, max_bytes=-1)

    assert route.call_count == 0


# ========== Probe across the 307 to storage ==========


@pytest.mark.asyncio
async def test_probe_follows_the_307_and_never_leaks_credentials(bb_client):
    """Both legs redirect; the pre-signed host must see no Bitbucket credentials."""
    with respx.mock:
        api = respx.get(LOG_URL).mock(
            return_value=httpx.Response(307, headers={"Location": STORAGE_URL})
        )
        storage = respx.get(STORAGE_URL).mock(
            side_effect=[
                httpx.Response(
                    206, content=b"a", headers={"Content-Range": "bytes 0-0/40"}
                ),
                httpx.Response(
                    206,
                    content=b"tail of the archived log",
                    headers={"Content-Range": "bytes 16-39/40"},
                ),
            ]
        )
        result = await _get_logs(bb_client, max_bytes=24)

    assert api.call_count == 2 and storage.call_count == 2
    assert all("Authorization" not in c.request.headers for c in storage.calls)
    assert storage.calls[-1].request.headers["Range"] == "bytes=16-"
    assert result["content"] == "tail of the archived log"
    assert result["total_bytes"] == 40


# ========== Races between the probe and the fetch ==========


@pytest.mark.asyncio
async def test_shrunk_log_reports_a_race_not_a_bad_window(bb_client):
    """A derived window that 416s is our staleness, never the caller's mistake."""
    with respx.mock:
        _probe_then(
            httpx.Response(206, content=b"0", headers={"Content-Range": "bytes 0-0/5000"}),
            httpx.Response(416, headers={"Content-Range": "bytes */100"}),
        )
        with pytest.raises(ValueError, match="changed size while it was being read"):
            await _get_logs(bb_client, max_bytes=64)


@pytest.mark.asyncio
async def test_caller_window_that_416s_still_blames_the_window(bb_client):
    """The caller chose this one, so the message must name it."""
    with respx.mock:
        respx.get(LOG_URL).mock(
            return_value=httpx.Response(416, headers={"Content-Range": "bytes */100"})
        )
        with pytest.raises(ValueError, match="bytes=9000-9100 is not satisfiable"):
            await _get_logs(bb_client, start=9000, end=9100)


# ========== Bearer (multi-tenant) clients on the probe leg (#72 x #80) ==========


@pytest.mark.asyncio
async def test_bearer_403_on_the_probe_surfaces_as_authorization_error(bearer_client):
    """The auth hook fires on the probe too; the error must not be swallowed there."""
    from src.client import AuthorizationError

    with respx.mock:
        route = respx.get(LOG_URL).mock(return_value=httpx.Response(403, json={}))
        with pytest.raises(AuthorizationError) as exc:
            await _get_logs(bearer_client)

    assert route.call_count == 1  # the probe fails; no pointless second round-trip
    assert exc.value.status_code == 403
    assert "bearer-token-abc" not in str(exc.value)


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.asyncio
async def test_bearer_storage_refusal_is_not_blamed_on_the_token(bearer_client, status):
    """A 401/403 from the pre-signed storage host is a storage failure (#81)."""
    from src.client import AuthorizationError

    with respx.mock:
        api = respx.get(LOG_URL).mock(
            return_value=httpx.Response(307, headers={"Location": STORAGE_URL})
        )
        storage = respx.get(STORAGE_URL).mock(return_value=httpx.Response(status))
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await _get_logs(bearer_client)

    assert not isinstance(exc.value, AuthorizationError)
    assert exc.value.response.status_code == status
    # The probe's refusal is an ordinary non-2xx: it falls back to the unranged read,
    # which is the leg whose raise_for_status surfaces the error.
    assert api.call_count == 2 and storage.call_count == 2
    assert "Range" not in api.calls[-1].request.headers
    assert all("Authorization" not in call.request.headers for call in storage.calls)


@pytest.mark.asyncio
async def test_bearer_same_origin_redirect_then_403_is_still_the_token(bearer_client):
    """The token survives a same-origin hop, so a refusal there is still about it."""
    from src.client import AuthorizationError

    moved = "https://api.bitbucket.org/2.0/moved-log"
    with respx.mock:
        respx.get(LOG_URL).mock(return_value=httpx.Response(307, headers={"Location": moved}))
        target = respx.get(moved).mock(return_value=httpx.Response(403, json={}))
        with pytest.raises(AuthorizationError):
            await _get_logs(bearer_client)

    assert target.calls[0].request.headers["Authorization"] == "Bearer bearer-token-abc"


# ========== _tail_window ==========


@pytest.mark.parametrize(
    "total,max_bytes,expected",
    [
        (5000, 100, ("bytes=4900-", 4900, None)),
        (80, 100, ("bytes=0-", 0, None)),  # log shorter than the cap: whole log
        (100, 100, ("bytes=0-", 0, None)),  # exactly the cap
        (0, 100, (None, None, None)),  # unknown/empty: no window at all
        (-1, 100, (None, None, None)),
    ],
)
def test_tail_window(total, max_bytes, expected):
    assert _tail_window(total, max_bytes) == expected


def test_tail_window_never_produces_a_suffix_range():
    """The one output shape that would reintroduce #80."""
    for total in (1, 99, 100, 101, 10**6):
        header, _, _ = _tail_window(total, 100)
        assert header is None or not header.startswith("bytes=-")


def test_build_log_range_defers_the_tail_to_the_caller():
    """A tail is bounded but has no header here: it needs the log size first."""
    assert _build_log_range(None, None, DEFAULT_MAX_LOG_BYTES) == (None, None, None)
