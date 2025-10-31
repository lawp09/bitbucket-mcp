#!/usr/bin/env python3
"""Main entry point for Bitbucket MCP Server"""

import argparse
import sys
from .server import mcp


def main():
    """Main entry point with CLI argument parsing"""
    parser = argparse.ArgumentParser(
        description="Bitbucket MCP Server - Container optimized",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with stdio transport (default for MCP)
  python -m src.main --transport stdio --loggers stderr

  # Run with HTTP transport on port 8080
  python -m src.main --transport http --port 8080

Environment variables required:
  BITBUCKET_USERNAME      - Your Bitbucket account email
  BITBUCKET_TOKEN      - Your Bitbucket app password (192 chars)
  BITBUCKET_WORKSPACE  - Your Bitbucket workspace name
"""
    )

    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport type (default: stdio)"
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

    args = parser.parse_args()

    # Validate environment variables
    import os
    required_vars = ["BITBUCKET_USERNAME", "BITBUCKET_TOKEN", "BITBUCKET_WORKSPACE"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        print(
            f"Error: Missing required environment variables: {', '.join(missing_vars)}",
            file=sys.stderr
        )
        print("\nPlease set the following environment variables:", file=sys.stderr)
        print("  export BITBUCKET_USERNAME='your-email@example.com'", file=sys.stderr)
        print("  export BITBUCKET_TOKEN='your-192-char-token'", file=sys.stderr)
        print("  export BITBUCKET_WORKSPACE='your-workspace'", file=sys.stderr)
        sys.exit(1)

    try:
        print(f"Starting Bitbucket MCP Server with {args.transport} transport...", file=sys.stderr)

        if args.transport == "stdio":
            # Run with stdio transport (standard MCP)
            mcp.run(transport="stdio")
        else:
            # Run with HTTP transport
            print(f"Server running on http://{args.host}:{args.port}", file=sys.stderr)
            mcp.run(transport="sse", host=args.host, port=args.port)

    except KeyboardInterrupt:
        print("\nServer stopped by user", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"Error starting server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
