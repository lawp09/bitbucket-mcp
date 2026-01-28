#!/bin/bash
# Run the Bitbucket MCP container in background
# NOTE: For easier setup, consider using Docker Compose instead. See: docker-compose up -d
# This script is maintained for manual/advanced usage. For most users, docker-compose is recommended.

set -e

# Handle --help flag
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    echo "run.sh - Run Bitbucket MCP container"
    echo ""
    echo "USAGE:"
    echo "  ./scripts/run.sh [OPTIONS]"
    echo ""
    echo "ENVIRONMENT VARIABLES:"
    echo "  BITBUCKET_USERNAME    Your Bitbucket email address (required)"
    echo "  BITBUCKET_TOKEN       Your Bitbucket API token (required)"
    echo "  BITBUCKET_WORKSPACE   Your Bitbucket workspace slug (required)"
    echo ""
    echo "OPTIONS:"
    echo "  --help, -h    Show this help message"
    echo ""
    echo "EXAMPLES:"
    echo "  export BITBUCKET_USERNAME='your-email@example.com'"
    echo "  export BITBUCKET_TOKEN='your-192-char-token'"
    echo "  export BITBUCKET_WORKSPACE='your-workspace'"
    echo "  ./scripts/run.sh"
    echo ""
    echo "ALTERNATIVES:"
    echo "  For easier setup with Docker Compose (RECOMMENDED):"
    echo "    Set environment variables in .env file"
    echo "    docker-compose up -d"
    echo ""
    exit 0
fi

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
