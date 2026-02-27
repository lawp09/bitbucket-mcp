# Bitbucket MCP Server (Python)

<!-- mcp-name: io.github.lawp09/bitbucket-mcp -->

[![PyPI](https://img.shields.io/pypi/v/bitbucket-mcp-py)](https://pypi.org/project/bitbucket-mcp-py/)
[![Python](https://img.shields.io/pypi/pyversions/bitbucket-mcp-py)](https://pypi.org/project/bitbucket-mcp-py/)
[![CI](https://github.com/lawp09/bitbucket-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/lawp09/bitbucket-mcp/actions/workflows/ci.yml)
[![CodeQL](https://github.com/lawp09/bitbucket-mcp/actions/workflows/codeql.yml/badge.svg)](https://github.com/lawp09/bitbucket-mcp/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Connect **Claude Code**, **VS Code (GitHub Copilot)**, **Cursor**, and any MCP-compatible AI assistant to your Bitbucket Cloud repositories. Review pull requests, monitor pipelines, and manage your code — all through natural language.

## Features

- **45 MCP tools** — repositories, pull requests, comments, tasks, diffs, pipelines, build statuses, reviewers, draft PRs, batch review
- **Slim responses** — stripped API noise for lower LLM token usage
- **Configurable** — enable/disable tools via `configs/tools.json`
- **Secure credentials** — environment variables or system keychain

## Quick Start

### 1. Install

The recommended way to run the server is via **uvx** (zero install, isolated environment):

```bash
# Always latest version
uvx --from bitbucket-mcp-py bitbucket-mcp

# Pin a specific version
uvx --from bitbucket-mcp-py==1.8.1 bitbucket-mcp
```

> **Why `--from`?** The PyPI package is `bitbucket-mcp-py` but the command entry point is `bitbucket-mcp`. The `--from` flag tells uvx which package to install.

<details>
<summary>Alternative install methods</summary>

| Mode | Command | Best for |
|------|---------|----------|
| **pip global** | `pip install bitbucket-mcp-py` | Simple, persistent install |
| **Local dev** | `pip install -e .` in project dir | Contributing to the project |
| **Docker** | See [Docker section](#docker-alternative) | Container-based workflows |

</details>

### 2. Configure credentials

Set the following environment variables (or use a `.env` file — see [Credentials](#credentials)):

| Variable | Description |
|----------|-------------|
| `BITBUCKET_USERNAME` | Your Bitbucket email |
| `BITBUCKET_TOKEN` | Your Bitbucket API token |
| `BITBUCKET_WORKSPACE` | Your workspace slug |

> **Get your API token** at: https://id.atlassian.com/manage-profile/security/api-tokens
>
> ⚠️ **Use a scoped token, not a global one.** When creating the token, select specific scopes (e.g. `Repositories: Read`, `Pull requests: Read/Write`). Global tokens without explicit scopes do not work with this MCP server.

### 3. Configure your AI assistant

#### Claude Code (recommended)

**Option A — CLI (fastest):**

```bash
claude mcp add bitbucket-mcp \
  -e BITBUCKET_USERNAME=your-email@example.com \
  -e BITBUCKET_TOKEN=your-api-token \
  -e BITBUCKET_WORKSPACE=your-workspace \
  -- uvx --from bitbucket-mcp-py bitbucket-mcp
```

**Option B — JSON config** (`~/.claude.json` or project `.mcp.json`):

```json
{
  "mcpServers": {
    "bitbucket-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "bitbucket-mcp-py", "bitbucket-mcp"],
      "env": {
        "BITBUCKET_USERNAME": "your-email@example.com",
        "BITBUCKET_TOKEN": "your-api-token",
        "BITBUCKET_WORKSPACE": "your-workspace"
      }
    }
  }
}
```

#### VS Code (GitHub Copilot)

Add to `.vscode/mcp.json` (workspace) or `~/Library/Application Support/Code/User/mcp.json` (global, macOS):

```json
{
  "servers": {
    "bitbucket-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "bitbucket-mcp-py", "bitbucket-mcp"],
      "env": {
        "BITBUCKET_USERNAME": "your-email@example.com",
        "BITBUCKET_TOKEN": "your-api-token",
        "BITBUCKET_WORKSPACE": "your-workspace"
      }
    }
  }
}
```

#### Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "bitbucket-mcp": {
      "command": "uvx",
      "args": ["--from", "bitbucket-mcp-py", "bitbucket-mcp"],
      "env": {
        "BITBUCKET_USERNAME": "your-email@example.com",
        "BITBUCKET_TOKEN": "your-api-token",
        "BITBUCKET_WORKSPACE": "your-workspace"
      }
    }
  }
}
```

## Available Tools

| Category | Tools |
|----------|-------|
| **Repositories** | `list_repositories`, `get_repository` |
| **Pull Requests** | `get_pull_requests`, `get_pull_request`, `create_pull_request`, `update_pull_request`, `approve_pull_request`, `unapprove_pull_request`, `request_changes_pull_request`, `unrequest_changes_pull_request`, `decline_pull_request`, `merge_pull_request` |
| **Comments** | `get_pull_request_comments`, `add_pull_request_comment`, `get_pull_request_comment`, `update_pull_request_comment`, `delete_pull_request_comment`, `resolve_pull_request_comment`, `reopen_pull_request_comment`, `get_pull_request_activity` |
| **Tasks PR** | `get_pull_request_tasks`, `get_pull_request_task`, `create_pull_request_task`, `update_pull_request_task`, `delete_pull_request_task` |
| **Diff / Review** | `get_pull_request_diff`, `get_pull_request_patch`, `get_pull_request_diffstat`, `get_pull_request_commits` |
| **PR Discovery** | `get_pull_requests_pending_review` |
| **Build / CI** | `get_pull_request_statuses`, `get_commit_statuses` |
| **Pipelines** | `list_pipeline_runs`, `get_pipeline_run`, `get_pipeline_steps`, `get_pipeline_step_logs`, `run_pipeline`, `stop_pipeline` |
| **Reviewers** | `get_effective_default_reviewers`, `suggest_pull_request_reviewers` |
| **Draft PR** | `create_draft_pull_request`, `publish_draft_pull_request`, `convert_pull_request_to_draft` |
| **Batch Review** | `submit_pull_request_batch_review` |
| **Review Summary** | `get_pull_request_review_summary` |

> Disabled by default: `merge_pull_request` (safety), `stop_pipeline` (safety), `get_pull_request_patch` (git am format — not useful for AI review), `convert_pull_request_to_draft` (not supported by Bitbucket API). Enable in `configs/tools.json`.

> **Token tip** — `get_pull_request_diff` accepts an optional `path` parameter to filter the diff to a single file, reducing token usage by ~95% on large PRs:
> ```
> get_pull_request_diff(repo_slug, pull_request_id, path="src/services/myService.ts")
> ```

## Credentials

### Option 1: `.env` file (recommended)

```bash
cp .env.example .env
# Edit .env with your credentials
```

### Option 2: System keychain (most secure)

```bash
pip install 'bitbucket-mcp-py[keyring]'
python3 -c "import keyring; keyring.set_password('bitbucket-mcp', 'bitbucket_token', 'YOUR_TOKEN')"
```

## Docker (Alternative)

If you prefer running the server in a container:

```bash
docker build -t bitbucket-mcp-py .
docker run -d --name bitbucket-mcp --env-file .env bitbucket-mcp-py
```

Then configure your AI assistant to use `docker exec`:

```json
{
  "mcpServers": {
    "bitbucket-mcp": {
      "command": "docker",
      "args": ["exec", "-i", "bitbucket-mcp", "python", "-m", "src.main", "--transport", "stdio"]
    }
  }
}
```

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests
uv run pytest tests/ -v

# Run specific test
uv run pytest tests/test_client.py -v
```

## Requirements

- Python 3.12+
- Bitbucket API token

## License

MIT

## References

- [MCP Registry](https://registry.modelcontextprotocol.io/) — Official MCP server registry
- [PyPI Package](https://pypi.org/project/bitbucket-mcp-py/) — Python package
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Bitbucket API 2.0](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/)
- [FastMCP Framework](https://gofastmcp.com/)
