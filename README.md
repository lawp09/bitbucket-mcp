# Bitbucket MCP Server (Python)

A Python-based Model Context Protocol (MCP) server for Bitbucket API, optimized for container execution with Podman.

## Features

- **Basic Authentication**: Uses correct `Basic base64(email:token)` authentication
- **Container-Optimized**: Designed for single-instance container execution with `podman exec`
- **Stderr Logging**: All logs go to stderr for container compatibility
- **Comprehensive API Coverage**: Pull requests, comments, repositories, pipelines, build statuses
- **FastMCP Framework**: Built on the official FastMCP Python framework
- **Async/Await**: Fully asynchronous for high performance

## Requirements

- Python 3.12+
- Podman or Docker
- Bitbucket account with app password

## Quick Start

### 1. Set Environment Variables

```bash
export BITBUCKET_USERNAME="your-email@example.com"
export BITBUCKET_TOKEN="your-192-char-app-password"
export BITBUCKET_WORKSPACE="your-workspace"
```

### 2. Build Container

```bash
./scripts/build.sh
```

### 3. Run Container

```bash
./scripts/run.sh
```

### 4. Execute MCP Server

```bash
./scripts/exec-mcp.sh
```

## Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "podman",
      "args": [
        "exec",
        "-i",
        "bitbucket-mcp",
        "python",
        "-m",
        "src.main",
        "--transport",
        "stdio",
        "--loggers",
        "stderr"
      ],
      "env": {
        "BITBUCKET_USERNAME": "your-email@example.com",
        "BITBUCKET_TOKEN": "your-192-char-token",
        "BITBUCKET_WORKSPACE": "your-workspace"
      }
    }
  }
}
```

## Available MCP Tools

### Repository Tools
- `list_repositories` - List repositories in workspace
- `get_repository` - Get repository details

### Pull Request Tools
- `get_pull_requests` - List pull requests for a repository
- `get_pull_request` - Get detailed PR information
- `create_pull_request` - Create a new pull request
- `update_pull_request` - Update PR title/description
- `approve_pull_request` - Approve a pull request
- `unapprove_pull_request` - Remove approval
- `decline_pull_request` - Decline a pull request
- `merge_pull_request` - Merge a pull request

### Comment Tools
- `get_pull_request_comments` - List all PR comments
- `add_pull_request_comment` - Add general or inline comment
- `get_pull_request_diff` - Get unified diff
- `get_pull_request_activity` - Get activity log
- `get_pull_request_commits` - Get PR commits

### Build Status Tools
- `get_pull_request_statuses` - Get CI/CD build statuses
- `get_pull_request_diffstat` - Get file modification statistics

### Pipeline Tools
- `list_pipeline_runs` - List pipeline executions
- `get_pipeline_run` - Get pipeline details
- `get_pipeline_steps` - List pipeline steps
- `get_pipeline_step_logs` - Get step logs

## Development

### Install Dependencies

```bash
pip install uv
uv pip install -r requirements.txt
```

### Run Tests

```bash
./scripts/test.sh
```

Or manually:

```bash
pytest tests/ -v --cov=src
```

### Run Integration Tests

Integration tests require valid Bitbucket credentials:

```bash
export BITBUCKET_USERNAME="..."
export BITBUCKET_TOKEN="..."
export BITBUCKET_WORKSPACE="..."

pytest tests/test_integration.py -v -m integration
```

## Architecture

```
src/
├── main.py          # Entry point with CLI args
├── server.py        # MCP server with tool registration
├── client.py        # Bitbucket API client (async)
├── tools/           # MCP tools organized by domain
└── utils/           # Utility functions
```

## Authentication

This server uses **Basic Authentication** with the format:

```
Authorization: Basic base64(email:token)
```

This is the correct method for Bitbucket API 2.0. The previous TypeScript implementation incorrectly used `Bearer` tokens.

### Getting Your App Password

1. Go to Bitbucket Settings → App passwords
2. Create new app password with required scopes:
   - Repositories: Read, Write
   - Pull requests: Read, Write
   - Pipelines: Read
3. Copy the 192-character token
4. Use it as `BITBUCKET_TOKEN`

## Container Architecture

The container stays alive with `tail -f /dev/null`, allowing you to execute the MCP server on-demand:

```bash
# Container runs continuously
podman run -d --name bitbucket-mcp ...

# Execute MCP server when needed
podman exec -i bitbucket-mcp python -m src.main --transport stdio
```

This approach:
- Keeps container lightweight
- Avoids premature server startup
- Allows multiple execution attempts
- Perfect for Claude Desktop integration

## Troubleshooting

### Authentication Errors

If you get 401 Unauthorized:

1. Verify email is correct
2. Verify app password is valid (192 chars)
3. Check workspace name is correct
4. Test authentication:

```bash
python -c "
import asyncio
from src.client import BitbucketClient

async def test():
    client = BitbucketClient('EMAIL', 'TOKEN', 'WORKSPACE')
    print(await client.get_user())
    await client.close()

asyncio.run(test())
"
```

### Container Not Running

```bash
# Check container status
podman ps -a | grep bitbucket-mcp

# View logs
podman logs bitbucket-mcp

# Restart container
podman restart bitbucket-mcp
```

### MCP Server Not Responding

```bash
# Test manually
podman exec -i bitbucket-mcp python -m src.main --transport stdio

# Check environment variables
podman exec bitbucket-mcp env | grep BITBUCKET
```

## Comparison with TypeScript Version

| Feature | TypeScript | Python |
|---------|-----------|--------|
| Authentication | ❌ Bearer (incorrect) | ✅ Basic Auth |
| Container Support | ❌ Auto-starts | ✅ Exec on-demand |
| Logging | ❌ File-based | ✅ Stderr |
| Performance | ✅ Fast | ✅ Async/Fast |
| Dependencies | Medium | Minimal |

## License

MIT

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Ensure tests pass
5. Submit pull request

## References

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Bitbucket API 2.0](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/)
- [FastMCP Framework](https://gofastmcp.com/)
