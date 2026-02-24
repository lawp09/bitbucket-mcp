# Bitbucket MCP Server (Python)

<!-- mcp-name: io.github.lawp09/bitbucket-mcp -->

[![PyPI](https://img.shields.io/pypi/v/bitbucket-mcp-py)](https://pypi.org/project/bitbucket-mcp-py/)
[![Python](https://img.shields.io/pypi/pyversions/bitbucket-mcp-py)](https://pypi.org/project/bitbucket-mcp-py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Connect **Claude Code**, **VS Code (GitHub Copilot)**, **Cursor**, and any MCP-compatible AI assistant to your Bitbucket Cloud repositories. Review pull requests, monitor pipelines, and manage your code — all through natural language.

## Features

- **24 MCP tools** — repositories, pull requests, comments, diffs, pipelines, build statuses
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

> Get your API token at: https://id.atlassian.com/manage-profile/security/api-tokens

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
| **Comments** | `get_pull_request_comments`, `add_pull_request_comment`, `get_pull_request_activity` |
| **Diff / Review** | `get_pull_request_diff`, `get_pull_request_diffstat`, `get_pull_request_commits` |
| **Build / CI** | `get_pull_request_statuses`, `get_commit_statuses` |
| **Pipelines** | `list_pipeline_runs`, `get_pipeline_run`, `get_pipeline_steps`, `get_pipeline_step_logs` |

> `merge_pull_request` is disabled by default. Enable it in `configs/tools.json`.

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
