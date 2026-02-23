# Bitbucket MCP Server (Python)

<!-- mcp-name: io.github.lawp09/bitbucket-mcp -->

[![PyPI](https://img.shields.io/pypi/v/bitbucket-mcp-py)](https://pypi.org/project/bitbucket-mcp-py/)
[![Python](https://img.shields.io/pypi/pyversions/bitbucket-mcp-py)](https://pypi.org/project/bitbucket-mcp-py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Connect **Claude Code**, **Cursor**, **VS Code (GitHub Copilot)**, and any MCP-compatible AI assistant to your Bitbucket Cloud repositories. Review pull requests, monitor pipelines, and manage your code — all through natural language.

## Features

- **21 MCP tools** — repositories, pull requests, comments, diffs, pipelines
- **Slim responses** — stripped API noise for lower LLM token usage
- **Configurable** — enable/disable tools via `configs/tools.json`
- **Secure credentials** — environment variables or system keychain

## Quick Start

### 1. Install

```bash
# Avec uv (recommandé)
uvx bitbucket-mcp-py

# Avec pip
pip install bitbucket-mcp-py
```

## Installation modes

| Mode | Command | Pour qui |
|------|---------|----------|
| **uvx** (recommended) | `uvx bitbucket-mcp-py` | Zero install, works anywhere with uv |
| **pip global** | `pip install bitbucket-mcp-py` | Simple, global dependencies |
| **Local dev** | `pip install -e .` in project dir | Contributing to the project |

### 2. Configure credentials

Set the following environment variables (or use a `.env` file — see [Credentials](#credentials)):

| Variable | Description |
|----------|-------------|
| `BITBUCKET_USERNAME` | Your Bitbucket email |
| `BITBUCKET_TOKEN` | Your Bitbucket API token |
| `BITBUCKET_WORKSPACE` | Your workspace slug |

> Get your API token at: https://id.atlassian.com/manage-profile/security/api-tokens

### 3. Configure your AI assistant

#### Claude Code

```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "uvx",
      "args": ["bitbucket-mcp-py"],
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
    "bitbucket": {
      "command": "uvx",
      "args": ["bitbucket-mcp-py"],
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

Add to `~/Library/Application Support/Code/User/mcp.json`:

```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "uvx",
      "args": ["bitbucket-mcp-py"],
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
| **Pull Requests** | `get_pull_requests`, `get_pull_request`, `create_pull_request`, `update_pull_request`, `approve_pull_request`, `unapprove_pull_request`, `decline_pull_request`, `merge_pull_request` |
| **Comments** | `get_pull_request_comments`, `add_pull_request_comment`, `get_pull_request_activity`, `get_pull_request_diff`, `get_pull_request_commits` |
| **Build Status** | `get_pull_request_statuses`, `get_pull_request_diffstat` |
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
    "bitbucket": {
      "command": "docker",
      "args": ["exec", "-i", "bitbucket-mcp", "python", "-m", "src.main", "--transport", "stdio"]
    }
  }
}
```

## Development

```bash
# Install dev dependencies
pip install -e '.[dev]'

# Run tests
pytest tests/ -v

# Run specific test
pytest tests/test_client.py -v
```

## Requirements

- Python 3.12+
- Bitbucket API token

## License

MIT

## References

- [MCP Registry](https://registry.modelcontextprotocol.io/) - Official MCP server registry
- [PyPI Package](https://pypi.org/project/bitbucket-mcp-py/) - Python package
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Bitbucket API 2.0](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/)
- [FastMCP Framework](https://gofastmcp.com/)
