# Client Setup

This page documents client configuration options beyond Claude Code CLI.

## Claude Code CLI (Recommended)

```bash
claude mcp add bitbucket-mcp \
  -e BITBUCKET_USERNAME=your-email@example.com \
  -e BITBUCKET_TOKEN=your-api-token \
  -e BITBUCKET_WORKSPACE=your-workspace \
  -- uvx --from bitbucket-mcp-py bitbucket-mcp
```

**Note**: The PyPI package is `bitbucket-mcp-py` but the command entry point is `bitbucket-mcp`. The `--from` flag is required with `uvx`.

## GitHub Copilot / JSON Configuration

Add to your MCP configuration:

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

## OpenAI Codex

Configure in `~/.codex/config.toml`:

```toml
[mcp_servers.bitbucket-mcp]
command = "uvx"
args = ["--from", "bitbucket-mcp-py", "bitbucket-mcp"]
env = { BITBUCKET_USERNAME = "your-email@example.com", BITBUCKET_TOKEN = "your-api-token", BITBUCKET_WORKSPACE = "your-workspace" }
```

**Client priority**: Claude Code → Codex → Cursor → VS Code (GitHub Copilot)
