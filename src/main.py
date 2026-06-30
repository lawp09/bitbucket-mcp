#!/usr/bin/env python3
"""Main entry point for Bitbucket MCP Server"""

import argparse
import sys
import warnings
from .server import mcp


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

Environment variables required:
  BITBUCKET_USERNAME      - Your Bitbucket account email
  BITBUCKET_TOKEN      - Your Bitbucket API token
  BITBUCKET_WORKSPACE  - Your Bitbucket workspace name
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

    args = parser.parse_args(argv)

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
            mcp.run(transport="stdio")
        else:
            # FastMCP.run() does not accept host/port kwargs — they are configured
            # on the server settings before run() is called.
            mcp.settings.host = args.host
            mcp.settings.port = args.port
            print(
                f"Server running on http://{args.host}:{args.port} ({transport})",
                file=sys.stderr,
            )
            mcp.run(transport=transport)

    except KeyboardInterrupt:
        print("\nServer stopped by user", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"Error starting server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
