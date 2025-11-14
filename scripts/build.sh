#!/bin/bash
# Build the Bitbucket MCP container
# NOTE: For easier setup, consider using Docker Compose instead. See: docker-compose up -d
# This script is maintained for manual/advanced usage. For most users, docker-compose is recommended.

set -e

# Handle --help flag
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    echo "build.sh - Build Bitbucket MCP container"
    echo ""
    echo "USAGE:"
    echo "  ./scripts/build.sh [OPTIONS]"
    echo ""
    echo "OPTIONS:"
    echo "  --help, -h    Show this help message"
    echo ""
    echo "ALTERNATIVES:"
    echo "  For easier setup with Docker Compose (RECOMMENDED):"
    echo "    docker-compose up -d"
    echo ""
    echo "  For manual build and run:"
    echo "    ./scripts/build.sh"
    echo "    ./scripts/run.sh"
    echo ""
    exit 0
fi

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
