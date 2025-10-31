#!/bin/bash
# Run the Bitbucket MCP container in background

set -e

# Check required environment variables
if [ -z "$BITBUCKET_USERNAME" ] || [ -z "$BITBUCKET_TOKEN" ] || [ -z "$BITBUCKET_WORKSPACE" ]; then
    echo "Error: Missing required environment variables"
    echo ""
    echo "Please set:"
    echo "  export BITBUCKET_USERNAME='your-email@example.com'"
    echo "  export BITBUCKET_TOKEN='your-192-char-token'"
    echo "  export BITBUCKET_WORKSPACE='your-workspace'"
    exit 1
fi

# Stop and remove existing container if it exists
if podman ps -a --format '{{.Names}}' | grep -q '^bitbucket-mcp$'; then
    echo "Stopping existing container..."
    podman stop bitbucket-mcp 2>/dev/null || true
    podman rm bitbucket-mcp 2>/dev/null || true
fi

echo "Starting Bitbucket MCP container..."
podman run -d \
  --name bitbucket-mcp \
  -e BITBUCKET_USERNAME="${BITBUCKET_USERNAME}" \
  -e BITBUCKET_TOKEN="${BITBUCKET_TOKEN}" \
  -e BITBUCKET_WORKSPACE="${BITBUCKET_WORKSPACE}" \
  bitbucket-mcp-py:latest

echo ""
echo "Container started successfully!"
echo "Container name: bitbucket-mcp"
echo ""
echo "To execute MCP server:"
echo "  ./scripts/exec-mcp.sh"
echo ""
echo "To view logs:"
echo "  podman logs -f bitbucket-mcp"
echo ""
echo "To stop container:"
echo "  podman stop bitbucket-mcp"
echo ""
