# Bitbucket MCP Server (Python)

<!-- mcp-name: io.github.lawp09/bitbucket-mcp -->

[![PyPI](https://img.shields.io/pypi/v/bitbucket-mcp-py)](https://pypi.org/project/bitbucket-mcp-py/)
[![Python](https://img.shields.io/pypi/pyversions/bitbucket-mcp-py)](https://pypi.org/project/bitbucket-mcp-py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Model Context Protocol (MCP) server for Bitbucket API, optimized for container execution.

## Install

```bash
pip install bitbucket-mcp-py
```

## Features

- Basic Auth (`base64(email:token)`)
- Container-ready (Podman/Docker)
- 22 MCP tools (repositories, PRs, comments, pipelines)
- Configurable tools via `configs/tools.json`
- Optional keychain support for secure credentials

## Quick Start

### 1. Configure Credentials

```bash
cp .env.example .env
# Edit .env with your credentials
```

> Get your API token at: https://id.atlassian.com/manage-profile/security/api-tokens

### 2. Build & Run

```bash
make build
make up
make verify  # Test authentication
```

### 3. Configure Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "podman",
      "args": ["exec", "-i", "bitbucket-mcp", "python", "-m", "src.main", "--transport", "stdio"]
    }
  }
}
```

### 4. Configure VS Code (GitHub Copilot)

Add to `~/Library/Application Support/Code/User/mcp.json`:

```json
{
  "mcpServers": {
    "bitbucket-mcp": {
      "command": "podman",
      "args": ["exec", "-i", "bitbucket-mcp", "python", "-m", "src.main", "--transport", "stdio"]
    }
  }
}
```

## Available Tools

| Category | Tools |
|----------|-------|
| **Repositories** | `list_repositories`, `get_repository` |
| **Pull Requests** | `get_pull_requests`, `get_pull_request`, `create_pull_request`, `update_pull_request`, `approve_pull_request`, `unapprove_pull_request`, `decline_pull_request` |
| **Comments** | `get_pull_request_comments`, `add_pull_request_comment`, `get_pull_request_activity`, `get_pull_request_diff`, `get_pull_request_commits` |
| **Build Status** | `get_pull_request_statuses`, `get_pull_request_diffstat` |
| **Pipelines** | `list_pipeline_runs`, `get_pipeline_run`, `get_pipeline_steps`, `get_pipeline_step_logs` |

## Make Commands

```bash
make build    # Build container
make up       # Start container
make down     # Stop container
make test     # Run tests
make verify   # Test Bitbucket auth
make logs     # View logs
make clean    # Remove container/image
```

## Secure Credentials (Optional)

For enhanced security, use system keychain instead of environment variables:

```bash
# Install keyring support
pip install 'bitbucket-mcp-py[keyring]'

# Store in macOS Keychain
python3 -c "import keyring; keyring.set_password('bitbucket-mcp', 'bitbucket_token', 'YOUR_TOKEN')"
```

## Development

```bash
# Run tests
make test

# Run specific test
pytest tests/test_client.py -v
```

## Requirements

- Python 3.12+
- Podman or Docker
- Bitbucket API token

## License

MIT

## References

- [MCP Registry](https://registry.modelcontextprotocol.io/) - Official MCP server registry
- [PyPI Package](https://pypi.org/project/bitbucket-mcp-py/) - Python package
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Bitbucket API 2.0](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/)
- [FastMCP Framework](https://gofastmcp.com/)
