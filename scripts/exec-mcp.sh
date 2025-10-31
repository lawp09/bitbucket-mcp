#!/bin/bash
# Execute the MCP server inside the running container
# This is meant to be called by Claude Desktop via podman exec

set -e

# Check if container is running
if ! podman ps --format '{{.Names}}' | grep -q '^bitbucket-mcp$'; then
    echo "Error: Container 'bitbucket-mcp' is not running" >&2
    echo "Start it with: ./scripts/run.sh" >&2
    exit 1
fi

# Execute MCP server with stdio transport
podman exec -i bitbucket-mcp \
  python -m src.main --transport stdio --loggers stderr
