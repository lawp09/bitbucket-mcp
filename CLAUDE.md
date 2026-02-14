# CLAUDE.md - Bitbucket MCP Server

## Project Overview

**Name**: bitbucket-mcp-py
**Type**: MCP (Model Context Protocol) Server for Bitbucket API
**Version**: 1.4.1
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
    ├── pagination.py    # Pagination utilities (max_pages, max_items)
    └── transformers.py  # Slim response transformers (reduce LLM token usage)

configs/
└── tools.json           # Tool enable/disable configuration

.github/workflows/
└── ci.yml               # CI pipeline (tests + build)

tests/                   # pytest test suite
scripts/                 # Shell scripts (build.sh, run.sh)
server.json              # MCP Registry server manifest
```

## Credentials Configuration

**Option 1: `.env` File (Recommended)**
```bash
cp .env.example .env
# Edit .env with your credentials
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

**Fallback Chain**: `.env` file → System keychain

> **Security**: `.env` is in `.gitignore`. Never commit credentials.

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

### Slim Responses

All tool responses pass through transformers (`src/utils/transformers.py`) that strip unnecessary Bitbucket API fields (links, avatars, nested metadata) to reduce LLM token usage. Each entity type has a dedicated `slim_*` function.

## CI/CD

GitHub Actions workflow (`.github/workflows/ci.yml`):
- **Triggers**: push to `main`, PR targeting `main`
- **Steps**: Install deps, run pytest with coverage, build package
- Python 3.12, pip cache enabled

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
| `src/utils/transformers.py` | Slim response transformers (token reduction) |
| `Makefile` | Container management (podman/docker) |
| `.github/workflows/ci.yml` | GitHub Actions CI pipeline |
| `.env.example` | Template for credentials (copy to .env) |
| `server.json` | MCP Registry manifest (for `mcp-publisher`) |

## Publishing

### PyPI
```bash
python -m build
python -m twine upload dist/* -u __token__ -p <PYPI_TOKEN>
```
- Package: https://pypi.org/project/bitbucket-mcp-py/
- Install: `pip install bitbucket-mcp-py`

### MCP Registry
```bash
brew install mcp-publisher
mcp-publisher login github    # GitHub OAuth (device flow)
mcp-publisher publish         # Reads server.json
```
- Registry: https://registry.modelcontextprotocol.io/
- Server name: `io.github.lawp09/bitbucket-mcp`
- **Important**: README must contain `<!-- mcp-name: io.github.lawp09/bitbucket-mcp -->` for PyPI ownership validation

### Version Bump Checklist
1. `pyproject.toml` → `version`
2. `src/__init__.py` → `__version__`
3. `server.json` → `version` + `packages[0].version`
4. `CHANGELOG.md` → new entry

## Recent Changes

- Published to PyPI and MCP Registry
- Added GitHub Actions CI workflow (pytest + coverage + build)
- Added slim response transformers to reduce LLM token usage (`src/utils/transformers.py`)
- Configured hatch wheel build for `src/` layout
- Added `respx` to dev dependencies
- Added secure credentials management with keychain support (`src/utils/credentials.py`)
- Simplified Makefile (uses podman/docker directly, no docker-compose)
- Added `max_pages=None` support for unlimited pagination

## Conventions

- **Async-first**: All API calls use `async/await`
- **Type hints**: All functions have type annotations
- **Structured output**: Tools return `Dict[str, Any]`, not strings
- **Logging**: Use `logging` module, output to stderr
- **Tests**: pytest with pytest-asyncio, min coverage 80%
