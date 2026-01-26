# Bitbucket MCP Server (Python)

A Python-based Model Context Protocol (MCP) server for Bitbucket API, optimized for container execution with Podman.

## Features

- **Basic Authentication**: Uses correct `Basic base64(email:token)` authentication
- **Container-Optimized**: Designed for single-instance container execution with `podman exec`
- **Stderr Logging**: All logs go to stderr for container compatibility
- **Comprehensive API Coverage**: Pull requests, comments, repositories, pipelines, build statuses
- **FastMCP Framework**: Built on the official FastMCP Python framework
- **Async/Await**: Fully asynchronous for high performance
- **Configurable Tools**: Enable/disable individual tools via `configs/tools.json`
- **Structured Responses**: Returns proper JSON objects, not serialized strings

## Quick Start with Docker Compose (Recommended)

The easiest way to get started with the Bitbucket MCP Server is using Docker Compose. This approach handles container orchestration, environment management, and networking automatically.

### Three Simple Steps

1. **Copy environment file and add credentials**
   ```bash
   cp .env.example .env
   # Edit .env and fill in your Bitbucket credentials:
   # BITBUCKET_USERNAME=your-email@example.com
   # BITBUCKET_TOKEN=your-192-char-app-password
   # BITBUCKET_WORKSPACE=your-workspace
   ```

2. **Start the server**
   ```bash
   docker-compose up -d
   ```

3. **Configure Claude Desktop/Copilot**
   Use the configuration examples below with container name `bitbucket-mcp`

### Approach Comparison

| Feature | Docker Compose | Manual Scripts |
|---------|---|---|
| Setup Time | ~1 minute | ~5 minutes |
| Environment Management | Automatic (.env) | Manual exports |
| Container Lifecycle | Managed | Manual |
| Configuration | Single file | Multiple scripts |
| Debugging | `docker-compose logs` | `podman logs` |
| Networking | Built-in | Manual mapping |
| **Recommended for** | Most users | Advanced/CI scenarios |

For complete setup instructions and troubleshooting, see the [Quick Start Guide](QUICKSTART.md).

## Requirements

- Python 3.12+
- Podman or Docker
- Bitbucket account with app password

## Quick Start

### 1. Configure Credentials

**Option A: Environment Variables (Recommended)**

Add to your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
export BITBUCKET_USERNAME="your-email@example.com"
export BITBUCKET_TOKEN="your-192-char-app-password"
export BITBUCKET_WORKSPACE="your-workspace"
```

**Option B: System Keychain (More Secure)**

Install optional keyring support and store credentials securely:

```bash
# Install keyring support
pip install 'bitbucket-mcp-py[keyring]'

# Store credentials (macOS example)
security add-generic-password -s "bitbucket-mcp" -a "bitbucket_username" -w "your-email"
security add-generic-password -s "bitbucket-mcp" -a "bitbucket_token" -w "your-token"
security add-generic-password -s "bitbucket-mcp" -a "bitbucket_workspace" -w "your-workspace"
```

> **Security Note**: Avoid using `.env` files for credentials as they can be accidentally committed. Environment variables in your shell profile or system keychain are safer.

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

**Example file**: See `claude_desktop_config.example.json`

> 💡 **Security Tip**: While Claude Desktop supports inline `env` configuration, it's more secure to set these as system environment variables and omit the `env` section entirely. This prevents accidentally committing credentials if you share your configuration file.

## GitHub Copilot (VS Code) Configuration

Add to your VS Code MCP config file:

**macOS**: `~/Library/Application Support/Code/User/mcp.json`
**Windows**: `%APPDATA%\Code\User\mcp.json`
**Linux**: `~/.config/Code/User/mcp.json`

```json
{
  "mcpServers": {
    "bitbucket-mcp": {
      "command": "podman",
      "args": [
        "exec",
        "-i",
        "bitbucket-mcp",
        "python",
        "-m",
        "src.main",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

**Example file**: See `github_copilot_config.example.json`

> ⚠️ **Security Best Practice**: Do NOT include `BITBUCKET_USERNAME`, `BITBUCKET_TOKEN`, or `BITBUCKET_WORKSPACE` in the JSON configuration file. Instead, set them as environment variables in your shell (see below). This prevents accidentally committing credentials to version control.

### Setting Environment Variables (Required)

The Bitbucket MCP server reads credentials from environment variables that must be set in your shell:

**macOS/Linux** (add to `~/.bashrc` or `~/.zshrc`):
```bash
export BITBUCKET_USERNAME="your-email@example.com"
export BITBUCKET_TOKEN="your-192-char-app-password"
export BITBUCKET_WORKSPACE="your-workspace-name"
```

**Windows** (PowerShell):
```powershell
[Environment]::SetEnvironmentVariable("BITBUCKET_USERNAME", "your-email@example.com", "User")
[Environment]::SetEnvironmentVariable("BITBUCKET_TOKEN", "your-192-char-app-password", "User")
[Environment]::SetEnvironmentVariable("BITBUCKET_WORKSPACE", "your-workspace-name", "User")
```

After setting environment variables, restart VS Code for the changes to take effect.

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
- `get_pull_request_comments` - List all PR comments (supports filtering by resolution status)
- `add_pull_request_comment` - Add general or inline comment
- `get_pull_request_diff` - Get unified diff
- `get_pull_request_activity` - Get activity log with comment resolution data
- `get_pull_request_commits` - Get PR commits

### Build Status Tools
- `get_pull_request_statuses` - Get CI/CD build statuses
- `get_pull_request_diffstat` - Get file modification statistics

### Pipeline Tools
- `list_pipeline_runs` - List pipeline executions
- `get_pipeline_run` - Get pipeline details
- `get_pipeline_steps` - List pipeline steps
- `get_pipeline_step_logs` - Get step logs

## Pagination

All tools that return lists now support pagination parameters to control data fetching:

### Parameters

- **`page_size`** (default: 10): Number of items per page
  - Available on: `get_pull_request_comments`, `get_pull_request_activity`, `get_pull_request_commits`, `get_pull_request_statuses`, `get_pull_request_diffstat`, `get_pipeline_steps`

- **`limit`** (default: 30): Items per page for repository and PR lists
  - Available on: `list_repositories`, `get_pull_requests`, `list_pipeline_runs`

- **`max_pages`** (default: 1): Maximum number of pages to fetch
  - Available on: all list-returning tools
  - Set to higher value to fetch multiple pages automatically

### Recommended Limits

- **Default**: 1 page (safe, fast)
- **Maximum recommended**: 10 pages or 300 total items
- Exceeding recommendations triggers a warning log

### Examples

**Fetch single page (default)**:
```json
{
  "name": "get_pull_request_comments",
  "arguments": {
    "repo_slug": "my-repo",
    "pull_request_id": 42
  }
}
```
Returns: Up to 10 comments

**Fetch multiple pages**:
```json
{
  "name": "get_pull_request_comments",
  "arguments": {
    "repo_slug": "my-repo",
    "pull_request_id": 42,
    "page_size": 20,
    "max_pages": 5
  }
}
```
Returns: Up to 100 comments (20 per page × 5 pages)

**Fetch all available pages** (use cautiously):
```json
{
  "name": "list_repositories",
  "arguments": {
    "workspace": "my-workspace",
    "max_pages": 999
  }
}
```
Returns: All repositories (stops at API limit or when no more data)

### Response Format

Responses maintain Bitbucket's original format:
```json
{
  "values": [...],        // Aggregated items from all fetched pages
  "pagelen": 10,          // Items per page
  "size": 150,            // Total items available
  "page": 1,              // Page number
  "next": "https://..."   // URL to next page (if more data available but not fetched)
}
```

### Performance Notes

- Default behavior (1 page) ensures fast responses
- Multi-page fetching increases response time linearly
- Use `max_pages` wisely based on your use case
- Monitor warning logs for large fetches

## Comment Resolution

Pull request comments now support resolution tracking to manage comment threads and discussions.

### get_pull_request_comments

**New Parameter:**
- `unresolved_only` (boolean, optional) - Filter to show only unresolved comments

**New Response Fields** (for each comment):
- `is_resolved` (boolean) - Whether the comment is marked as resolved
- `resolved_by` (object) - User who resolved the comment (if resolved)
- `resolved_on` (string) - ISO 8601 timestamp when comment was resolved (if resolved)

**Example: Get only unresolved comments**:
```json
{
  "name": "get_pull_request_comments",
  "arguments": {
    "repo_slug": "my-repo",
    "pull_request_id": 42,
    "unresolved_only": true
  }
}
```

Returns: Only unresolved comments with their details

### get_pull_request_activity

**Enhanced Comment Data** - Comment events in activity log now include:
- `is_resolved` (boolean) - Resolution status
- `resolved_by` (object) - User who resolved the comment
- `resolved_on` (string) - Timestamp of resolution

### get_pull_request

**New Response Field:**
- `comment_stats` (object) - Comment statistics for the PR:
  - `total` (integer) - Total number of comments
  - `resolved` (integer) - Number of resolved comments
  - `unresolved` (integer) - Number of unresolved comments

**Example Response**:
```json
{
  "id": 42,
  "title": "feat: new feature",
  "comment_stats": {
    "total": 15,
    "resolved": 10,
    "unresolved": 5
  }
}
```

## Tool Configuration

You can enable or disable individual MCP tools by editing `configs/tools.json`. This allows you to customize which tools are available to MCP clients.

### Configuration File

```json
{
  "tools": {
    "repositories": {
      "list_repositories": {
        "enabled": true,
        "description": "List repositories in workspace"
      }
    },
    "pull_requests": {
      "update_pull_request": {
        "enabled": false,
        "description": "Update a pull request"
      }
    }
  }
}
```

### Enabling/Disabling Tools

1. Edit `configs/tools.json`
2. Set `"enabled": false` for tools you want to disable
3. Rebuild the container: `./scripts/build.sh`
4. Restart the container: `./scripts/run.sh`

**Note**: Disabled tools will not appear in the MCP tool list and cannot be called by clients.

## Response Format

All MCP tools return structured JSON responses via FastMCP's `structured_output` feature. The MCP protocol wraps responses in a `CallToolResult` with two formats:

- **`content`**: Human-readable text representation (for display)
- **`structuredContent`**: Machine-readable JSON object (for programmatic use)

### Example Response

When calling `get_pull_request`, the response includes:

```json
{
  "id": 31,
  "title": "feat: add new feature",
  "state": "OPEN",
  "author": {
    "display_name": "John Doe"
  }
}
```

**Benefits**:
- No need to parse JSON strings
- Direct access to nested objects
- Type-safe responses
- Better IDE autocomplete support

**Technical Details**: Return types use `Dict[str, Any]` from Python's `typing` module, which FastMCP converts to proper JSON Schema for structured output.

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
