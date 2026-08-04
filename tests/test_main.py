"""Tests for the CLI entry point — transport selection (issue #62) and stateless mode (#71).

These tests validate the *selection* of the transport and the settings derived from the
CLI/environment; the server coroutines are mocked, so they do not exercise a real HTTP
round-trip, which is FastMCP's responsibility.
"""

import asyncio
import os
import signal
from unittest.mock import AsyncMock, patch

import pytest

import src.main
import src.server
from src.main import main
from src.server import mcp
from src.utils import pagination


@pytest.fixture(autouse=True)
def restore_mcp_settings():
    """Save/restore the global mcp.settings so HTTP tests don't leak state into the
    shared FastMCP singleton used by other test modules."""
    saved = {
        name: getattr(mcp.settings, name)
        for name in ("host", "port", "stateless_http", "json_response", "transport_security")
    }
    yield
    for name, value in saved.items():
        setattr(mcp.settings, name, value)


@pytest.fixture(autouse=True)
def clean_env():
    """main() reads BITBUCKET_* settings from the environment — keep tests isolated."""
    keys = (
        "BITBUCKET_ALLOWED_HOSTS",
        "BITBUCKET_ALLOWED_ORIGINS",
        "BITBUCKET_MAX_PAGES_HARD_CAP",
    )
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# get_credentials is imported INSIDE main() (`from .utils.credentials import ...`),
# so the patch target is the source module, NOT `src.main.get_credentials`
# (that name does not exist at module scope in src.main).
CREDS_TARGET = "src.utils.credentials.get_credentials"


def _patch_transports():
    """Patch the three FastMCP transport coroutines main() dispatches to.

    Returns a dict of {name: AsyncMock} plus the contextmanagers to enter.
    """
    return {
        name: patch.object(mcp, name, new_callable=AsyncMock)
        for name in ("run_stdio_async", "run_sse_async", "run_streamable_http_async")
    }


class _Transports:
    """Context manager exposing the three mocked transport coroutines."""

    def __enter__(self):
        self._patches = _patch_transports()
        self.mocks = {name: p.start() for name, p in self._patches.items()}
        return self.mocks

    def __exit__(self, *exc):
        for p in self._patches.values():
            p.stop()
        return False


def test_default_transport_is_stdio():
    with _Transports() as t, patch(CREDS_TARGET):
        main([])
    t["run_stdio_async"].assert_awaited_once()
    t["run_streamable_http_async"].assert_not_awaited()


def test_http_transport_uses_streamable_http():
    with _Transports() as t, patch(CREDS_TARGET):
        main(["--transport", "http"])
    t["run_streamable_http_async"].assert_awaited_once()
    t["run_stdio_async"].assert_not_awaited()


@pytest.mark.filterwarnings("always::DeprecationWarning")
def test_sse_transport_warns_deprecation():
    with _Transports() as t, patch(CREDS_TARGET):
        with pytest.warns(DeprecationWarning, match="deprecated"):
            main(["--transport", "sse"])
    t["run_sse_async"].assert_awaited_once()


@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_http_family_sets_host_and_port(transport):
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", transport, "--host", "1.2.3.4", "--port", "9000"])
    assert mcp.settings.host == "1.2.3.4"
    assert mcp.settings.port == 9000


def test_stdio_does_not_touch_host_port():
    # The autouse fixture saved the originals; confirm stdio leaves them unchanged.
    host_before = mcp.settings.host
    port_before = mcp.settings.port
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", "stdio"])
    assert mcp.settings.host == host_before
    assert mcp.settings.port == port_before


def test_missing_credentials_exits():
    with _Transports(), patch(CREDS_TARGET, side_effect=ValueError("no creds")):
        with pytest.raises(SystemExit) as exc:
            main(["--transport", "stdio"])
    assert exc.value.code == 1


def test_server_crash_exits_with_code_1():
    with patch.object(mcp, "run_stdio_async", new_callable=AsyncMock) as run, \
            patch(CREDS_TARGET):
        run.side_effect = RuntimeError("boom")
        with pytest.raises(SystemExit) as exc:
            main(["--transport", "stdio"])
    assert exc.value.code == 1


# ========== Stateless mode (issue #71) ==========


def test_stateless_http_enables_stateless_and_json_response():
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", "http", "--stateless"])
    assert mcp.settings.stateless_http is True
    assert mcp.settings.json_response is True


def test_http_without_stateless_keeps_sessions():
    """Non-regression: plain HTTP must behave exactly as before."""
    mcp.settings.stateless_http = False
    mcp.settings.json_response = False
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", "http"])
    assert mcp.settings.stateless_http is False
    assert mcp.settings.json_response is False


@pytest.mark.parametrize("transport", ["stdio", "sse"])
def test_stateless_rejected_outside_http(transport):
    """stdio has no sessions and the legacy SSE app ignores the setting — reject rather
    than silently accept a flag that does nothing."""
    with _Transports(), patch(CREDS_TARGET):
        with pytest.raises(SystemExit) as exc:
            main(["--transport", transport, "--stateless"])
    assert exc.value.code == 2


def test_stateless_flag_rejected_before_credentials_are_read():
    """An invalid flag combination must fail even with no credentials configured."""
    with _Transports(), patch(CREDS_TARGET, side_effect=ValueError("no creds")) as creds:
        with pytest.raises(SystemExit) as exc:
            main(["--transport", "stdio", "--stateless"])
    assert exc.value.code == 2
    creds.assert_not_called()


def test_stateless_sets_default_page_hard_cap():
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", "http", "--stateless"])
    assert pagination.get_page_hard_cap() == 10


def test_page_hard_cap_read_from_env():
    os.environ["BITBUCKET_MAX_PAGES_HARD_CAP"] = "3"
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", "http", "--stateless"])
    assert pagination.get_page_hard_cap() == 3


@pytest.mark.parametrize("raw", ["not-a-number", "0", "-5"])
def test_invalid_page_hard_cap_falls_back_to_default(raw):
    """A bad cap must not take the server down."""
    os.environ["BITBUCKET_MAX_PAGES_HARD_CAP"] = raw
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", "http", "--stateless"])
    assert pagination.get_page_hard_cap() == 10


def test_http_without_stateless_leaves_hard_cap_disabled():
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", "http"])
    assert pagination.get_page_hard_cap() is None


# ========== Transport security (issue #71) ==========


def test_transport_security_defaults_to_permissive():
    """FastMCP auto-enables DNS-rebinding protection when built on a loopback host
    (its constructor default), which rejects any real hostname with 421/403. main()
    must clear it when no allowlist is configured."""
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", "http", "--host", "0.0.0.0"])
    assert mcp.settings.transport_security is None


def test_transport_security_from_env():
    os.environ["BITBUCKET_ALLOWED_HOSTS"] = "mcp.example.com, mcp2.example.com"
    os.environ["BITBUCKET_ALLOWED_ORIGINS"] = "https://app.example.com"
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", "http"])

    security = mcp.settings.transport_security
    assert security is not None
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == ["mcp.example.com", "mcp2.example.com"]
    assert security.allowed_origins == ["https://app.example.com"]


def test_blank_env_allowlist_is_ignored():
    os.environ["BITBUCKET_ALLOWED_HOSTS"] = "  ,  "
    with _Transports(), patch(CREDS_TARGET):
        main(["--transport", "http"])
    assert mcp.settings.transport_security is None


# ========== Clean shutdown (issue #71) ==========


@pytest.mark.parametrize(
    "argv,coroutine",
    [
        (["--transport", "stdio"], "run_stdio_async"),
        (["--transport", "http"], "run_streamable_http_async"),
    ],
)
def test_clients_are_closed_on_shutdown(argv, coroutine):
    """close_clients() runs inside the server's own event loop, so the clients created
    while serving are actually reachable (a finally around FastMCP.run() would not be —
    it closes its loop before returning)."""
    async def serve():
        # Simulate a tool creating a client on the server loop.
        with patch("src.server.get_credentials"):
            src.server.get_client()
        assert len(src.server._clients) == 1

    with patch.object(mcp, coroutine, new_callable=AsyncMock) as run, patch(CREDS_TARGET):
        run.side_effect = serve
        main(argv)

    assert len(src.server._clients) == 0


def test_clients_are_closed_even_when_the_server_crashes():
    with patch.object(mcp, "run_stdio_async", new_callable=AsyncMock) as run, \
            patch(CREDS_TARGET), \
            patch("src.main.close_clients", new_callable=AsyncMock) as close:
        run.side_effect = RuntimeError("boom")
        with pytest.raises(SystemExit):
            main(["--transport", "stdio"])
    close.assert_awaited_once()


# ========== Signal-driven shutdown (issue #71) ==========


def test_stdio_wires_the_signal_handlers():
    """_serve() installs them for stdio..."""
    with patch.object(mcp, "run_stdio_async", new_callable=AsyncMock), \
            patch(CREDS_TARGET), \
            patch("src.main._install_stdio_signal_handlers") as install:
        main(["--transport", "stdio"])
    install.assert_called_once()


@pytest.mark.parametrize("transport,coroutine", [
    ("http", "run_streamable_http_async"),
    ("sse", "run_sse_async"),
])
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_http_transports_do_not_wire_signal_handlers(transport, coroutine):
    """...but not for the HTTP transports: uvicorn installs its own and shuts down
    gracefully — overriding them would fight uvicorn for the same signals."""
    with patch.object(mcp, coroutine, new_callable=AsyncMock), \
            patch(CREDS_TARGET), \
            patch("src.main._install_stdio_signal_handlers") as install:
        main(["--transport", transport])
    install.assert_not_called()


def test_install_stdio_signal_handlers_registers_sigint_and_sigterm():
    """The installer itself registers a cancelling handler on both signals."""
    registered = {}

    async def scenario():
        loop = asyncio.get_running_loop()
        with patch.object(loop, "add_signal_handler", registered.__setitem__):
            src.main._install_stdio_signal_handlers()

    asyncio.run(scenario())

    assert set(registered) == {signal.SIGINT, signal.SIGTERM}
    # The handler must cancel the serving task, which is what resumes the coroutine so
    # its finally (and close_clients) actually runs.
    assert all(callable(h) for h in registered.values())


def test_cancellation_closes_clients_and_exits_cleanly():
    """SIGINT/SIGTERM cancel the serving task: clients are closed, no crash exit."""
    async def serve():
        with patch("src.server.get_credentials"):
            src.server.get_client()
        raise asyncio.CancelledError()

    with patch.object(mcp, "run_stdio_async", new_callable=AsyncMock) as run, \
            patch(CREDS_TARGET):
        run.side_effect = serve
        main(["--transport", "stdio"])  # must not raise SystemExit

    assert len(src.server._clients) == 0


@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.parametrize("var", ["BITBUCKET_ALLOWED_HOSTS", "BITBUCKET_ALLOWED_ORIGINS"])
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_partial_allowlist_is_rejected(transport, var):
    """The SDK enforces both allowlists as a pair. Verified live: origins-only yields an
    empty allowed_hosts and its host check has no 'unset means skip' branch — every
    request gets 421; hosts-only rejects every browser client with 403. Fail fast instead
    of bricking the server. Both HTTP transports read transport_security."""
    os.environ[var] = "example.com"
    with _Transports(), patch(CREDS_TARGET):
        with pytest.raises(SystemExit) as exc:
            main(["--transport", transport])
    assert exc.value.code == 2


def test_partial_allowlist_ignored_on_stdio():
    """stdio has no HTTP surface — the allowlists are irrelevant there."""
    os.environ["BITBUCKET_ALLOWED_HOSTS"] = "mcp.example.com"
    with _Transports() as t, patch(CREDS_TARGET):
        main(["--transport", "stdio"])
    t["run_stdio_async"].assert_awaited_once()


def test_second_cancellation_during_cleanup_does_not_crash():
    """A second Ctrl-C while close_clients() is in flight must not escape as a raw
    CancelledError (a BaseException that neither close_clients nor main catches)."""
    async def serve():
        raise asyncio.CancelledError()

    async def cleanup_cancelled():
        raise asyncio.CancelledError()

    with patch.object(mcp, "run_stdio_async", new_callable=AsyncMock) as run, \
            patch(CREDS_TARGET), \
            patch("src.main.close_clients", side_effect=cleanup_cancelled):
        run.side_effect = serve
        main(["--transport", "stdio"])  # must not raise


def test_signal_handlers_are_removed_before_cleanup():
    """Handlers are restored to the default before cleanup runs, so a repeat signal
    surfaces as KeyboardInterrupt (handled by main) rather than re-cancelling us."""
    order = []

    async def serve():
        raise asyncio.CancelledError()

    with patch.object(mcp, "run_stdio_async", new_callable=AsyncMock) as run, \
            patch(CREDS_TARGET), \
            patch("src.main._install_stdio_signal_handlers",
                  return_value=[signal.SIGINT, signal.SIGTERM]), \
            patch("src.main._remove_signal_handlers",
                  side_effect=lambda sigs: order.append(("remove", tuple(sigs)))), \
            patch("src.main.close_clients", new_callable=AsyncMock) as close:
        close.side_effect = lambda: order.append(("close", ()))
        run.side_effect = serve
        main(["--transport", "stdio"])

    assert order == [
        ("remove", (signal.SIGINT, signal.SIGTERM)),
        ("close", ()),
    ]
