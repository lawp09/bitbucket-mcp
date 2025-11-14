# Quick Start Guide - Bitbucket MCP Server

> **Recommended**: Use Docker Compose for the fastest setup. It handles container orchestration and configuration automatically.

## Quick Start with Docker Compose

### TL;DR - 5 Steps

```bash
# 1. Clone and navigate
cd /Users/ulawsph/app/ai/mcp/bitbucket-mcp-py

# 2. Set your credentials
export BITBUCKET_USERNAME="your-email@example.com"
export BITBUCKET_TOKEN="your-192-char-token"
export BITBUCKET_WORKSPACE="your-workspace"

# 3. Start with Docker Compose
docker-compose up -d

# 4. Verify it's running
docker-compose logs bitbucket-mcp

# 5. Configure Claude Desktop (see below)
```

That's it! Your Bitbucket MCP server is running.

For detailed Docker Compose setup including environment configuration options, networking, and troubleshooting, see [DOCKER_COMPOSE_GUIDE.md](docs/DOCKER_COMPOSE_GUIDE.md).

## Prerequisites

- Python 3.12+
- Podman, Docker, or Docker Compose installed
- Bitbucket account with app password

## Alternative: Manual Installation with Scripts

### 1. Get a Bitbucket App Password

1. Go to https://bitbucket.org/account/settings/app-passwords/
2. Click "Create app password"
3. Name: "Claude MCP Server"
4. Required permissions:
   - ✅ Repositories: Read, Write
   - ✅ Pull requests: Read, Write
   - ✅ Pipelines: Read
5. Copy the token (192 characters)

### 2. Configure Environment Variables

```bash
export BITBUCKET_USERNAME="your-email@example.com"
export BITBUCKET_TOKEN="your-192-char-token"
export BITBUCKET_WORKSPACE="your-workspace"
```

💡 **Tip**: Add these lines to your `~/.bashrc` or `~/.zshrc` to make them permanent.

### 3. Build the Container

```bash
cd /Users/ulawsph/app/ai/mcp/bitbucket-mcp-py
./scripts/build.sh
```

Expected output:
```
Building Bitbucket MCP container...
✓ Image built successfully
Image: bitbucket-mcp-py:latest
```

### 4. Start the Container

```bash
./scripts/run.sh
```

Expected output:
```
Container started successfully!
Container name: bitbucket-mcp
```

### 5. Test the MCP Server

```bash
# Simple test
podman exec -i bitbucket-mcp python -m src.main --transport stdio
```

You should see the server start with logs on stderr.

### 6. Configure Claude Desktop

Edit your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Linux**: `~/.config/Claude/claude_desktop_config.json`

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add this configuration:

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

> 💡 **Security Tip**: While Claude Desktop supports inline `env` configuration, it's more secure to set these as system environment variables (step 2) and omit the `env` section entirely. This prevents accidentally committing credentials if you share your configuration file.

### 7. Restart Claude Desktop

1. Completely quit Claude Desktop
2. Relaunch Claude Desktop
3. The Bitbucket MCP server should now be available

## Alternative: GitHub Copilot (VS Code) Configuration

If you're using GitHub Copilot in VS Code instead of Claude Desktop:

**Configuration file location:**
- **macOS**: `~/Library/Application Support/Code/User/mcp.json`
- **Windows**: `%APPDATA%\Code\User\mcp.json`
- **Linux**: `~/.config/Code/User/mcp.json`

Add this configuration:

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

> ⚠️ **Security Best Practice**: Do NOT include credentials in the JSON file. The server reads `BITBUCKET_USERNAME`, `BITBUCKET_TOKEN`, and `BITBUCKET_WORKSPACE` from environment variables (see step 2 above). This prevents accidentally committing credentials to version control.

**After configuration:**
1. Restart VS Code completely
2. The Bitbucket MCP server should now be available in GitHub Copilot

## Verification

Both Docker Compose and manual script-based installations work the same way. In Claude Desktop or GitHub Copilot, try:

```
Can you list the repositories in my Bitbucket workspace?
```

or

```
Show me the open pull requests on repo X
```

The MCP server is running and accessible regardless of which installation method you used.

## Useful Commands

### View container logs

```bash
podman logs -f bitbucket-mcp
```

### Stop the container

```bash
podman stop bitbucket-mcp
```

### Restart the container

```bash
podman restart bitbucket-mcp
```

### Rebuild after modifications

```bash
./scripts/build.sh
podman stop bitbucket-mcp
podman rm bitbucket-mcp
./scripts/run.sh
```

### Run tests

```bash
./scripts/test.sh
```

## Troubleshooting

### Error: "Container not running"

```bash
# Check status
podman ps -a | grep bitbucket-mcp

# Restart if necessary
./scripts/run.sh
```

### Error: "401 Unauthorized"

1. Verify your email is correct
2. Verify your token is valid (192 characters)
3. Verify the workspace exists
4. Test authentication:

```bash
podman exec -i bitbucket-mcp python -c "
import asyncio
from src.client import BitbucketClient
import os

async def test():
    client = BitbucketClient(
        os.getenv('BITBUCKET_USERNAME'),
        os.getenv('BITBUCKET_TOKEN'),
        os.getenv('BITBUCKET_WORKSPACE')
    )
    try:
        user = await client.get_user()
        print('✓ Authentication successful!')
        print(f'  User: {user[\"display_name\"]}')
    except Exception as e:
        print(f'✗ Authentication failed: {e}')
    finally:
        await client.close()

asyncio.run(test())
"
```

### Error: "Missing environment variables"

Check that variables are defined in the container:

```bash
podman exec bitbucket-mcp env | grep BITBUCKET
```

If they're not there, restart with the correct variables:

```bash
podman stop bitbucket-mcp
podman rm bitbucket-mcp
./scripts/run.sh
```

### Claude Desktop doesn't see the server

1. Check the config file path
2. Verify JSON syntax
3. Completely restart Claude Desktop
4. Check Claude Desktop logs

**macOS**:
```bash
tail -f ~/Library/Logs/Claude/mcp*.log
```

## Available MCP Tools

Once configured, you'll have access to these tools in Claude:

**Repositories**
- `list_repositories` - List repos
- `get_repository` - Get repo details

**Pull Requests**
- `get_pull_requests` - List PRs
- `get_pull_request` - Get PR details
- `create_pull_request` - Create a PR
- `approve_pull_request` - Approve a PR
- `merge_pull_request` - Merge a PR

**Comments**
- `get_pull_request_comments` - List comments
- `add_pull_request_comment` - Add a comment
- `get_pull_request_diff` - View diff

**Pipelines**
- `list_pipeline_runs` - List executions
- `get_pipeline_step_logs` - View logs

## Working with Pagination

### Basic Pagination

By default, all list-returning tools fetch only the first page (10-30 items depending on the tool):

```python
# Fetch first page only (default)
comments = await client.get_pull_request_comments(
    repo_slug="my-repo",
    pull_request_id=42
)
# Returns: Up to 10 comments
```

### Fetching Multiple Pages

Use the `max_pages` parameter to fetch more data:

```python
# Fetch up to 3 pages
comments = await client.get_pull_request_comments(
    repo_slug="my-repo",
    pull_request_id=42,
    page_size=20,      # 20 items per page
    max_pages=3        # Fetch up to 3 pages
)
# Returns: Up to 60 comments (20 × 3)
```

### Fetching All Available Data

Set `max_pages` to a high value to fetch all available pages:

```python
# Fetch all repositories
repos = await client.list_repositories(
    workspace="my-workspace",
    max_pages=100  # High enough to get all data
)
# Returns: All repositories in the workspace
```

### Via MCP Protocol

When using the MCP server via Claude or other MCP clients:

**Example 1: Default single page**
```json
{
  "tool": "get_pull_request_commits",
  "arguments": {
    "repo_slug": "my-repo",
    "pull_request_id": 123
  }
}
```

**Example 2: Multiple pages**
```json
{
  "tool": "get_pull_request_commits",
  "arguments": {
    "repo_slug": "my-repo",
    "pull_request_id": 123,
    "page_size": 50,
    "max_pages": 5
  }
}
```

### Best Practices

1. **Start with defaults**: Default 1-page fetching is fast and safe
2. **Use max_pages for known bounds**: If you know data size, set appropriate limit
3. **Monitor warnings**: Fetching >10 pages or >300 items triggers warnings
4. **Consider performance**: Each page requires an API call
5. **Check `next` in response**: Indicates if more data is available

### Response Structure

All paginated responses include:
- `values`: Array of items (aggregated from all fetched pages)
- `pagelen`: Items per page
- `size`: Total items available (from Bitbucket API)
- `next`: URL to next page (if more data exists but wasn't fetched)

## Usage Examples in Claude

### List open PRs

```
Show me all open pull requests on the "my-project" repo
```

### Approve a PR

```
Approve pull request #42 on the "my-project" repo
```

### Add a comment

```
Add a comment on PR #42: "LGTM! Excellent work on this feature."
```

### View PR diff

```
Show me the diff of pull request #42 on "my-project"
```

## Going Further

- Check [README.md](README.md) for complete documentation
- Read [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) for technical details
- Review [PLAN.md](PLAN.md) to understand the architecture

## Support

If you encounter problems:

1. Check logs: `podman logs bitbucket-mcp`
2. Test authentication (see Troubleshooting section)
3. Verify the container is running
4. Consult Bitbucket API documentation

---

**Estimated setup time**: 5-10 minutes

**Prerequisites**: Bitbucket account + Podman installed

**Status**: ✅ Production-ready
