# CLAUDE.md - Bitbucket MCP Server

## Project Overview

**Name**: bitbucket-mcp-py
**Type**: MCP (Model Context Protocol) Server for Bitbucket API
**Version**: 1.25.0
**Python**: 3.12+
**Container Runtime**: Podman (preferred) or Docker

## Client Configuration

**Claude Code CLI (Recommended):**
```bash
claude mcp add bitbucket-mcp \
  -e BITBUCKET_USERNAME=your-email@example.com \
  -e BITBUCKET_TOKEN=your-api-token \
  -e BITBUCKET_WORKSPACE=your-workspace \
  -- uvx --from bitbucket-mcp-py bitbucket-mcp
```

See [`docs/client-setup.md`](docs/client-setup.md) for GitHub Copilot, Codex, and other client configurations.

**Note**: The PyPI package is `bitbucket-mcp-py` but the entry point is `bitbucket-mcp`. The `--from` flag is required with `uvx`.

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
├── prompts.py           # MCP Prompts templates
└── utils/
    ├── credentials.py   # Secure credentials (env vars + keychain)
    ├── pagination.py    # Pagination utilities
    └── transformers.py  # Slim response transformers (token reduction)

configs/
└── tools.json           # Tool enable/disable configuration

tests/                   # pytest test suite
.github/workflows/       # GitHub Actions (CI + Release)
Dockerfile               # Container image definition
server.json              # MCP Registry manifest
pyproject.toml           # Python project config (uv, dependencies)
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

**Fallback chain**: `.env` file → System keychain

> **Security**: `.env` is in `.gitignore`. Never commit credentials.

## Architecture

### Authentication
- **Method**: Basic Auth (`Authorization: Basic base64(email:token)`)
- **API Base**: `https://api.bitbucket.org/2.0`

### MCP Tools (96)

Tools are grouped by domain in `configs/tools.json`: Repositories, Pull Requests, Comments, Tasks, Pipelines, Issues, Commits, Deployments, Branch Restrictions, Workspace, and more.

See [`docs/tools-reference.md`](docs/tools-reference.md) for the complete catalog, annotations, and disabled-by-default list.

### Response Transformation

All responses pass through transformers (`src/utils/transformers.py`) that strip unnecessary fields (links, avatars, metadata) to reduce LLM token usage.

### Tool Configuration

Tools can be individually enabled or disabled via `configs/tools.json`. See [`docs/tools-configuration.md`](docs/tools-configuration.md) for configuration options.

### Pagination

All list-returning tools support `page_size`, `max_pages`, and `max_items` parameters. See [`docs/pagination.md`](docs/pagination.md) for details, including stateless mode hard caps.

## Development

### Running Tests
```bash
make test                              # All tests (via Makefile)
uv run pytest tests/ -v               # Verbose
uv run pytest tests/test_client.py    # Specific file
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
@conditional_tool()
async def get_pull_request(...) -> Dict[str, Any]:
    ...
```

> **Never pass annotations or a title to the decorator** — `conditional_tool()` only takes
> `structured_output`. The MCP annotations (`readOnlyHint`/`destructiveHint`/
> `idempotentHint`, `openWorldHint=False` everywhere) and the human-readable `title` are
> derived centrally in `src/server.py` from the tool's **name prefix** (`get_`/`list_` →
> read-only, `delete_` → destructive…), with `_ANNOTATION_OVERRIDES` / `_TITLE_OVERRIDES`
> for the atypical verbs. A new tool whose name matches no prefix must get an override — a
> test asserts every registered tool is covered.

### Error Handling
- Client methods use `response.raise_for_status()` — errors bubble up
- No silent failures — exceptions propagate to MCP layer

## Deployment & Release

For publishing to PyPI, MCP Registry, CI/CD pipelines, container deployment, and version bumping procedures, see [`docs/deployment.md`](docs/deployment.md).

For architecture decisions, API quirks, and design rationale, see [`docs/architecture.md`](docs/architecture.md).

For key files reference, see [`docs/key-files.md`](docs/key-files.md).

For the release history — what changed in each version, and why — see [`CHANGELOG.md`](CHANGELOG.md).

## Conventions

- **Async-first**: All API calls use `async/await`
- **Type hints**: All functions have type annotations
- **Structured output**: Tools return `Dict[str, Any]`, not strings
- **Logging**: Use `logging` module, output to stderr
- **Tests**: pytest with pytest-asyncio, min coverage 80%
