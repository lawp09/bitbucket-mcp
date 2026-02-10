# CLAUDE.md - Bitbucket MCP Server

## Project Overview

**Name**: bitbucket-mcp-py
**Type**: MCP (Model Context Protocol) Server for Bitbucket API
**Version**: 1.4.0
**Python**: 3.12+
**Container Runtime**: Podman (preferred) or Docker

## Quick Commands

```bash
# Container management (uses podman or docker automatically)
make build          # Build container image
make up             # Start container
make down           # Stop container
make verify         # Test Bitbucket authentication
make test           # Run tests locally
make logs           # Show container logs
make clean          # Remove container and image

# Execute MCP server
podman exec -i bitbucket-mcp python -m src.main --transport stdio
```

## Project Structure

```
src/
├── main.py              # CLI entry point (stdio/HTTP transport)
├── server.py            # MCP server, tool registration
├── client.py            # BitbucketClient (async, Basic Auth)
└── utils/
    ├── credentials.py   # Secure credentials (env vars + keychain)
    └── pagination.py    # Pagination utilities (max_pages, max_items)

configs/
└── tools.json           # Tool enable/disable configuration

tests/                   # pytest test suite
scripts/                 # Shell scripts (build.sh, run.sh)
```

## Credentials Configuration

**Option 1: Environment Variables (Recommended)**
```bash
# Add to ~/.zshrc or ~/.bashrc
export BITBUCKET_USERNAME="email@example.com"
export BITBUCKET_TOKEN="your-api-token"
export BITBUCKET_WORKSPACE="your-workspace"
```

**Option 2: System Keychain (More Secure)**
```bash
# Install keyring support
pip install 'bitbucket-mcp-py[keyring]'

# macOS: Store in Keychain
security add-generic-password -s "bitbucket-mcp" -a "bitbucket_username" -w "email"
security add-generic-password -s "bitbucket-mcp" -a "bitbucket_token" -w "token"
security add-generic-password -s "bitbucket-mcp" -a "bitbucket_workspace" -w "workspace"
```

**Fallback Chain**: Environment variables → System keychain

> **Security**: Avoid `.env` files for credentials (risk of accidental commit). Use shell env vars or keychain.

## Architecture

### Authentication
- **Method**: Basic Auth (`Authorization: Basic base64(email:token)`)
- **API Base**: `https://api.bitbucket.org/2.0`

### MCP Tools (23 total)

| Category | Tools |
|----------|-------|
| **Repositories** | `list_repositories`, `get_repository` |
| **Pull Requests** | `get_pull_requests`, `get_pull_request`, `create_pull_request`, `update_pull_request`, `approve_pull_request`, `unapprove_pull_request`, `decline_pull_request` |
| **Comments** | `get_pull_request_comments`, `add_pull_request_comment`, `get_pull_request_activity` |
| **Diff/Status** | `get_pull_request_diff`, `get_pull_request_commits`, `get_pull_request_statuses`, `get_pull_request_diffstat` |
| **Pipelines** | `list_pipeline_runs`, `get_pipeline_run`, `get_pipeline_steps`, `get_pipeline_step_logs` |

**Disabled by default**: `merge_pull_request` (safety)

### Pagination

All list-returning tools support:
- `page_size` / `limit`: Items per page (default: 10-30)
- `max_pages`: Max pages to fetch (default: 1, `None` for unlimited)
- `max_items`: Max total items (default: None)

**Warnings logged** if `max_pages > 10` or `max_items > 300`.

### Tool Configuration

Edit `configs/tools.json` to enable/disable tools:
```json
{
  "tools": {
    "pull_requests": {
      "merge_pull_request": {
        "enabled": false,
        "description": "Merge a pull request"
      }
    }
  }
}
```

## Development

### Running Tests
```bash
make test                    # All tests
pytest tests/ -v             # Verbose
pytest tests/test_client.py  # Specific file
```

### Code Patterns

**Async client methods**:
```python
async def get_pull_request(self, repo_slug: str, pr_id: int) -> Dict[str, Any]:
    response = await self.client.get(f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}")
    response.raise_for_status()
    return response.json()
```

**Tool registration** (server.py):
```python
@conditional_tool("pull_requests", "get_pull_request")
async def get_pull_request(...) -> Dict[str, Any]:
    ...
```

### Error Handling
- Client methods use `response.raise_for_status()` - errors bubble up
- No silent failures - exceptions propagate to MCP layer

## Container

**Dockerfile**:
- Base: `python:3.12-slim`
- Package manager: `uv`
- User: `mcpuser` (non-root, UID 1000)
- Command: `tail -f /dev/null` (stays alive for exec)

**Makefile** detects runtime:
```makefile
RUNTIME := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
```

## Key Files

| File | Purpose |
|------|---------|
| `src/server.py` | MCP tool registration, client singleton |
| `src/client.py` | Bitbucket API client (async, Basic Auth) |
| `src/utils/credentials.py` | Secure credentials (env vars → keychain fallback) |
| `src/utils/pagination.py` | Pagination config and aggregation |
| `configs/tools.json` | Tool enable/disable settings |
| `Makefile` | Container management (podman/docker) |
| `.env.example` | Template for credentials (copy to .env) |

## Recent Changes

- Added secure credentials management with keychain support (`src/utils/credentials.py`)
- Added optional `keyring` dependency for system keychain integration
- Simplified Makefile (uses podman/docker directly, no docker-compose)
- Removed redundant docker-compose.dev.yml and docker-compose.prod.yml
- Fixed healthcheck to use correct env vars (USERNAME, TOKEN, WORKSPACE)
- Added `max_pages=None` support for unlimited pagination
- Removed excessive documentation (3000+ lines in docs/)

## Conventions

- **Async-first**: All API calls use `async/await`
- **Type hints**: All functions have type annotations
- **Structured output**: Tools return `Dict[str, Any]`, not strings
- **Logging**: Use `logging` module, output to stderr
- **Tests**: pytest with pytest-asyncio, min coverage 80%
