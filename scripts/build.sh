#!/bin/bash
# Build the Bitbucket MCP container

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "Building Bitbucket MCP container..."
podman build --no-cache -t bitbucket-mcp-py:latest .

echo ""
echo "Build complete!"
echo "Image: bitbucket-mcp-py:latest"
echo ""
echo "Next steps:"
echo "  1. Set environment variables:"
echo "     export BITBUCKET_USERNAME='your-email@example.com'"
echo "     export BITBUCKET_TOKEN='your-192-char-token'"
echo "     export BITBUCKET_WORKSPACE='your-workspace'"
echo ""
echo "  2. Run the container:"
echo "     ./scripts/run.sh"
echo ""
