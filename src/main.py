#!/usr/bin/env python3
"""Main entry point for Bitbucket MCP Server"""

import argparse
import asyncio
import os
import signal
import sys
import warnings

from mcp.server.transport_security import TransportSecuritySettings

from .server import close_clients, mcp
from .utils.pagination import set_page_hard_cap

# Default ceiling on pages fetched per tool call in stateless mode (see
# src/utils/pagination.py). Overridable with BITBUCKET_MAX_PAGES_HARD_CAP.
DEFAULT_STATELESS_PAGE_HARD_CAP = 10


def _env_list(name):
    """Parse a comma-separated environment variable into a list, or None if unset/empty."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or None


def _page_hard_cap_from_env():
    """Read the stateless page hard cap from the environment.

    Falls back to the default on an unset, malformed or non-positive value rather than
    failing the boot: a bad cap must not take the server down.
    """
    raw = os.environ.get("BITBUCKET_MAX_PAGES_HARD_CAP", "").strip()
    if not raw:
        return DEFAULT_STATELESS_PAGE_HARD_CAP
    try:
        cap = int(raw)
    except ValueError:
        print(
            f"Warning: BITBUCKET_MAX_PAGES_HARD_CAP={raw!r} is not an integer, "
            f"using {DEFAULT_STATELESS_PAGE_HARD_CAP}",
            file=sys.stderr,
        )
        return DEFAULT_STATELESS_PAGE_HARD_CAP
    if cap < 1:
        print(
            f"Warning: BITBUCKET_MAX_PAGES_HARD_CAP={cap} must be >= 1, "
            f"using {DEFAULT_STATELESS_PAGE_HARD_CAP}",
            file=sys.stderr,
        )
        return DEFAULT_STATELESS_PAGE_HARD_CAP
    return cap


def _build_transport_security():
    """Build transport security settings from the environment.

    Returns None (no DNS-rebinding protection) when neither BITBUCKET_ALLOWED_HOSTS nor
    BITBUCKET_ALLOWED_ORIGINS is set.

    Setting this explicitly matters: FastMCP auto-enables DNS-rebinding protection when
    built with a loopback host (its constructor default), and src/server.py builds the
    server before --host is known. Left alone, an HTTP deployment reached through a real
    hostname is rejected (421/403) even though --host 0.0.0.0 was requested.

    Both allowlists are required together — see _validate_allowlists.
    """
    hosts = _env_list("BITBUCKET_ALLOWED_HOSTS")
    origins = _env_list("BITBUCKET_ALLOWED_ORIGINS")
    if hosts is None and origins is None:
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts or [],
        allowed_origins=origins or [],
    )


def _validate_allowlists(parser):
    """Reject a half-configured allowlist, which would lock the server out.

    The SDK's checks have no "unset means skip" branch: an empty allowed_hosts rejects
    *every* request with 421 (verified live), and an empty allowed_origins rejects every
    request carrying an Origin header — i.e. every browser-based client. Setting one
    variable alone therefore bricks the server silently, so require both together.
    """
    hosts = _env_list("BITBUCKET_ALLOWED_HOSTS")
    origins = _env_list("BITBUCKET_ALLOWED_ORIGINS")
    if (hosts is None) != (origins is None):
        missing = "BITBUCKET_ALLOWED_HOSTS" if hosts is None else "BITBUCKET_ALLOWED_ORIGINS"
        parser.error(
            f"{missing} must be set too: BITBUCKET_ALLOWED_HOSTS and "
            f"BITBUCKET_ALLOWED_ORIGINS are enforced as a pair, and leaving one empty "
            f"rejects every request (421/403)."
        )


def _install_stdio_signal_handlers():
    """Turn SIGINT/SIGTERM into a cancellation of the current task, for stdio only.

    Without this, a Ctrl-C under stdio raises KeyboardInterrupt from the loop's internal
    poll — outside the serving coroutine's frame — so _serve()'s finally never runs and
    the clients are left to the OS. Cancelling the task instead resumes the coroutine at
    its await point, which does run the finally.

    stdio only: the HTTP transports run under uvicorn, which installs its own signal
    handling and shuts down gracefully (its serve() returns normally, reaching the
    finally). Overriding that would fight uvicorn for the same signals.

    Returns the signals it managed to install, for _remove_signal_handlers.
    """
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    installed = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, task.cancel)
            installed.append(sig)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - platform-specific
            # Not supported on this platform (e.g. Windows proactor loop); fall back to
            # the default behaviour rather than failing to start.
            pass
    return installed


def _remove_signal_handlers(signals):
    """Restore the default handlers for `signals`."""
    loop = asyncio.get_running_loop()
    for sig in signals:
        try:
            loop.remove_signal_handler(sig)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - platform-specific
            pass


async def _serve(transport):
    """Run the server for `transport`, closing the Bitbucket clients on the way out.

    Mirrors the body of FastMCP.run(), which dispatches to these same public coroutines
    via anyio.run(). Driving them ourselves is what makes a clean shutdown possible:
    anyio.run()/FastMCP.run() close their event loop before returning, so anything we did
    in a finally around mcp.run() would run on a fresh loop and find nothing to close.
    Here the finally still runs inside the loop that served the requests.
    """
    installed_signals = []
    try:
        if transport == "stdio":
            installed_signals = _install_stdio_signal_handlers()
            await mcp.run_stdio_async()
        elif transport == "sse":
            await mcp.run_sse_async()
        else:
            await mcp.run_streamable_http_async()
    except asyncio.CancelledError:
        # Signal-driven shutdown: a normal exit, not an error. Swallowed here so it does
        # not surface as a crash, after the finally below has closed the clients.
        print("\nServer stopped by user", file=sys.stderr)
    finally:
        # Restore the default handlers first: an impatient second Ctrl-C must not cancel
        # us again *inside* this cleanup. That second CancelledError would be raised in
        # the finally itself — past the guard above, and a BaseException that neither
        # close_clients() nor main() catches — turning a clean shutdown into a traceback.
        # With the defaults restored it surfaces as KeyboardInterrupt, which main()
        # already handles.
        _remove_signal_handlers(installed_signals)
        try:
            await close_clients()
        except asyncio.CancelledError:
            pass


def main(argv=None):
    """Main entry point with CLI argument parsing.

    Args:
        argv: Optional list of CLI args (defaults to sys.argv[1:] when None).
              Exposed for testability — the packaged entry point calls main().
    """
    parser = argparse.ArgumentParser(
        description="Bitbucket MCP Server - Container optimized",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with stdio transport (default for MCP)
  python -m src.main --transport stdio --loggers stderr

  # Run with Streamable HTTP transport on port 8080
  python -m src.main --transport http --port 8080

  # Stateless Streamable HTTP (horizontal scaling / serverless, single-tenant)
  python -m src.main --transport http --port 8080 --stateless

Environment variables required:
  BITBUCKET_USERNAME      - Your Bitbucket account email
  BITBUCKET_TOKEN      - Your Bitbucket API token
  BITBUCKET_WORKSPACE  - Your Bitbucket workspace name

Optional (HTTP transport):
  BITBUCKET_ALLOWED_HOSTS       - Comma-separated Host allowlist (DNS-rebinding protection)
  BITBUCKET_ALLOWED_ORIGINS     - Comma-separated Origin allowlist
  BITBUCKET_MAX_PAGES_HARD_CAP  - Max pages per tool call in stateless mode (default: 10)
"""
    )

    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default="stdio",
        help=(
            "Transport protocol (default: stdio). 'stdio' for local clients; "
            "'http' uses Streamable HTTP (MCP spec 2025-03-26); "
            "'sse' is the legacy Server-Sent Events transport (deprecated)."
        )
    )

    parser.add_argument(
        "--loggers",
        choices=["stderr", "file"],
        default="stderr",
        help="Logger output destination (default: stderr)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000)"
    )

    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host for HTTP transport (default: 0.0.0.0)"
    )

    parser.add_argument(
        "--stateless",
        action="store_true",
        help=(
            "Run the Streamable HTTP transport in stateless mode: no Mcp-Session-Id, a "
            "fresh session per request. Enables horizontal scaling / serverless "
            "deployment. Requires --transport http."
        )
    )

    args = parser.parse_args(argv)

    # Reject rather than ignore: a silently dropped --stateless is a production footgun.
    # stdio has no sessions to begin with, and the legacy SSE app never reads
    # stateless_http/json_response — the flag would be inert on both.
    if args.stateless and args.transport != "http":
        parser.error("--stateless requires --transport http")

    if args.transport != "stdio":
        _validate_allowlists(parser)

    # Validate credentials (env vars → keychain fallback)
    from .utils.credentials import get_credentials
    try:
        get_credentials()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Map the CLI choice to the FastMCP transport name once, so every log message
    # uses the real transport ('http' -> 'streamable-http'; 'sse' -> legacy alias).
    transport = {
        "stdio": "stdio",
        "http": "streamable-http",
        "sse": "sse",
    }[args.transport]

    # Emit the deprecation warning OUTSIDE the try/except below: DeprecationWarning is
    # an Exception subclass, so under PYTHONWARNINGS=error it would be caught by the
    # generic `except Exception` and reported as a misleading "Error starting server".
    if args.transport == "sse":
        warnings.warn(
            "Transport 'sse' is deprecated (MCP spec 2025-03-26); "
            "use '--transport http' (Streamable HTTP) instead.",
            DeprecationWarning,
        )

    try:
        print(f"Starting Bitbucket MCP Server ({transport} transport)...", file=sys.stderr)

        if transport == "stdio":
            # Run with stdio transport (standard MCP)
            asyncio.run(_serve("stdio"))
        else:
            # FastMCP.run() does not accept host/port kwargs — they are configured
            # on the server settings before run() is called. Every setting below is read
            # lazily when the ASGI app is built, so assigning them here is effective.
            mcp.settings.host = args.host
            mcp.settings.port = args.port
            mcp.settings.transport_security = _build_transport_security()

            mode = transport
            if args.stateless:
                mcp.settings.stateless_http = True
                # Single JSON response instead of an SSE stream — required by edge and
                # serverless runtimes that cannot hold a streaming response open.
                mcp.settings.json_response = True
                set_page_hard_cap(_page_hard_cap_from_env())
                mode = f"{transport}, stateless"

            print(
                f"Server running on http://{args.host}:{args.port} ({mode})",
                file=sys.stderr,
            )
            asyncio.run(_serve(transport))

    except KeyboardInterrupt:
        print("\nServer stopped by user", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"Error starting server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
