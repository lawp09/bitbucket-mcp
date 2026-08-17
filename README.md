# Bitbucket MCP Server (Python)

<!-- mcp-name: io.github.lawp09/bitbucket-mcp -->

[![PyPI](https://img.shields.io/pypi/v/bitbucket-mcp-py)](https://pypi.org/project/bitbucket-mcp-py/)
[![Python](https://img.shields.io/pypi/pyversions/bitbucket-mcp-py)](https://pypi.org/project/bitbucket-mcp-py/)
[![CI](https://github.com/lawp09/bitbucket-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/lawp09/bitbucket-mcp/actions/workflows/ci.yml)
[![CodeQL](https://github.com/lawp09/bitbucket-mcp/actions/workflows/codeql.yml/badge.svg)](https://github.com/lawp09/bitbucket-mcp/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Connect **Claude Code**, **OpenAI Codex**, **Cursor**, **VS Code (GitHub Copilot)**, and any MCP-compatible AI assistant to your Bitbucket Cloud repositories. Review pull requests, monitor pipelines, and manage your code — all through natural language.

## Features

- **60+ MCP tools** — repositories, pull requests, comments, tasks, diffs, pipelines (runtime + config), build statuses, reviewers, draft PRs, batch review, issue tracker, commits, source/file browsing
- **MCP 2025 tool annotations** — every tool advertises `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint` + a human-readable title, so clients (Claude Code, Cursor) auto-include read-only tools and warn before destructive operations
- **Slim responses** — stripped API noise for lower LLM token usage
- **Configurable** — enable/disable tools via `configs/tools.json` or `BITBUCKET_TOOLS_CONFIG` env var
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

#### OpenAI Codex

**Option A — CLI (fastest):**

```bash
codex mcp add bitbucket-mcp \
  --env BITBUCKET_USERNAME=your-email@example.com \
  --env BITBUCKET_TOKEN=your-api-token \
  --env BITBUCKET_WORKSPACE=your-workspace \
  -- uvx --from bitbucket-mcp-py bitbucket-mcp
```

**Option B — TOML config** (`~/.codex/config.toml`):

```toml
[mcp_servers.bitbucket-mcp]
command = "uvx"
args = ["--from", "bitbucket-mcp-py", "bitbucket-mcp"]
env = { BITBUCKET_USERNAME = "your-email@example.com", BITBUCKET_TOKEN = "your-api-token", BITBUCKET_WORKSPACE = "your-workspace" }
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

## Available Tools

| Category | Tools |
|----------|-------|
| **Repositories** | `list_repositories`, `get_repository`, `get_repository_tags` |
| **Pull Requests** | `get_pull_requests`, `get_pull_request`, `create_pull_request`, `update_pull_request`, `approve_pull_request`, `unapprove_pull_request`, `request_changes_pull_request`, `unrequest_changes_pull_request`, `decline_pull_request`, `merge_pull_request` |
| **Comments** | `get_pull_request_comments`, `add_pull_request_comment`, `get_pull_request_comment`, `update_pull_request_comment`, `delete_pull_request_comment`, `resolve_pull_request_comment`, `reopen_pull_request_comment`, `get_pull_request_activity` |
| **Tasks PR** | `get_pull_request_tasks`, `get_pull_request_task`, `create_pull_request_task`, `update_pull_request_task`, `delete_pull_request_task` |
| **Diff / Review** | `get_pull_request_diff`, `get_pull_request_patch`, `get_pull_request_diffstat`, `get_pull_request_commits` |
| **PR Discovery** | `get_pull_requests_pending_review` |
| **Build / CI** | `get_pull_request_statuses`, `get_commit_statuses` |
| **Pipelines** | `list_pipeline_runs`, `get_pipeline_run`, `get_pipeline_steps`, `get_pipeline_step_logs`, `run_pipeline`, `stop_pipeline` |
| **Pipelines Config** | `get_pipeline_config`, `list_pipeline_variables`, `get_pipeline_variable`, `create_pipeline_variable`, `update_pipeline_variable`, `delete_pipeline_variable`, `list_pipeline_schedules`, `get_pipeline_schedule`, `list_pipeline_schedule_executions`, `create_pipeline_schedule`, `update_pipeline_schedule`, `delete_pipeline_schedule`, `list_pipeline_caches`, `delete_pipeline_cache` |
| **Reviewers** | `get_effective_default_reviewers`, `suggest_pull_request_reviewers` |
| **Draft PR** | `create_draft_pull_request`, `publish_draft_pull_request`, `convert_pull_request_to_draft` |
| **Batch Review** | `submit_pull_request_batch_review` |
| **Review Summary** | `get_pull_request_review_summary` |
| **Issues** | `list_issues`, `get_issue`, `create_issue`, `update_issue`, `delete_issue`, `get_issue_comments`, `get_issue_comment`, `add_issue_comment`, `update_issue_comment`, `delete_issue_comment` |
| **Commits** | `list_commits`, `get_commit`, `get_commit_comments`, `get_commit_comment`, `add_commit_comment` |
| **Source** | `get_file_content`, `list_directory` |
| **Deployments** | `list_environments`, `get_environment`, `create_environment`, `delete_environment`, `list_deployments`, `get_deployment`, `list_deployment_variables`, `create_deployment_variable`, `update_deployment_variable`, `delete_deployment_variable` |
| **Branch Restrictions** | `list_branch_restrictions`, `get_branch_restriction`, `create_branch_restriction`, `update_branch_restriction`, `delete_branch_restriction` |
| **Workspace** | `list_workspace_members`, `get_workspace_member`, `list_workspace_permissions`, `list_repository_permissions` |

> Disabled by default: `merge_pull_request` (safety), `stop_pipeline` (safety), `get_pull_request_patch` (git am format — not useful for AI review), `convert_pull_request_to_draft` (not supported by Bitbucket API), `delete_issue` (safety), `delete_issue_comment` (safety), `add_commit_comment` (write op), `create_pipeline_variable` / `update_pipeline_variable` / `delete_pipeline_variable` (write ops), `create_pipeline_schedule` / `update_pipeline_schedule` / `delete_pipeline_schedule` (write ops), `delete_pipeline_cache` (safety), `create_environment` / `delete_environment` / `create_deployment_variable` / `update_deployment_variable` / `delete_deployment_variable` (write ops), `create_branch_restriction` / `update_branch_restriction` / `delete_branch_restriction` (write ops). Enable in `configs/tools.json`.

> **Governance scopes** — Branch restriction read tools need the `repository` scope (`repository:admin` may be required depending on repo config); the write tools need `repository:admin`. Workspace member/permission tools need the `account` scope. The `/members` endpoint lists users **without** a per-user permission (use `list_workspace_permissions` for roles).

> **Deployments scopes** — the read tools (`list_environments`, `get_environment`, `list_deployments`, `get_deployment`, `list_deployment_variables`) need the `deployment` scope; the write tools need `deployment:write`. Bitbucket has no server-side filter for deployments by environment ([BCLOUD-18729](https://jira.atlassian.com/browse/BCLOUD-18729)) — filter on the `environment` field of `list_deployments` instead. There is no `update_environment` tool: Bitbucket exposes no `PUT` for environments (only `POST .../changes` for locking).

### Custom tool configuration

By default the server reads `configs/tools.json` bundled with the package. You can point to a custom file at runtime without rebuilding:

```bash
export BITBUCKET_TOOLS_CONFIG=/path/to/my-tools.json
```

**Fallback chain** (first match wins):

1. `BITBUCKET_TOOLS_CONFIG` environment variable
2. Built-in `configs/tools.json`

> **Fail-safe behaviour** — If `BITBUCKET_TOOLS_CONFIG` is set but the file is missing or contains invalid JSON, the server raises an error on startup (explicit failure rather than silently ignoring the override). If the built-in default is missing, all tools are enabled.

> **Token tip** — `get_pull_request_diff` accepts an optional `path` parameter to filter the diff to a single file, reducing token usage by ~95% on large PRs:
> ```
> get_pull_request_diff(repo_slug, pull_request_id, path="src/services/myService.ts")
> ```
>
> **Token tip** — `get_pipeline_step_logs` returns only the trailing 100 KiB of a step log by
> default (raw logs run to several MB on long steps). The response carries a `truncated` flag;
> widen the window with the absolute byte range `start` / `end`, or pass `max_bytes=null` for
> the whole log. Pass a service container UUID as `log_uuid` to read that service's log
> instead of the build container's. This endpoint needs a real pipeline **UUID** — resolve it
> via `get_pipeline_run` if you only have a build number.
> ```
> get_pipeline_step_logs(repo_slug, pipeline_uuid="{adab6a1f-...}", step_uuid="{84fc6465-...}")
> ```

## MCP Prompts

The server also exposes **MCP Prompts** — parameterised templates that compatible clients (Claude Code, Cursor, ...) surface as slash commands. Instead of remembering tool names, you invoke a prompt and the assistant orchestrates the right tools for you. They appear in the client's prompt picker (`prompts/list`).

| Prompt | Arguments | What it does |
|--------|-----------|--------------|
| `review_pull_request` | `repo_slug`, `pull_request_id` | Full AI review: metadata → diffstat → diff → comments → tasks, then Summary / Risk / Quality / Security / Recommendation |
| `debug_pipeline_failure` | `repo_slug`, `pipeline_uuid` | Diagnose a failed pipeline: run → steps → failed-step logs, then Root cause / Failed step / Error / Fix |
| `summarize_repository` | `repo_slug` | Repo overview: info → recent commits → open PRs → CI → issues, then Purpose / Activity / Health / Contributors |
| `onboard_reviewer` | `repo_slug`, `pull_request_id` | Help a new reviewer: PR context → commits → diff → review history, then Context / Changes / Review-so-far / Focus |

Prompts are enabled/disabled in `configs/tools.json` under the top-level `prompts` key (separate from `tools`).

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

### Transports

The server speaks **stdio** by default (the standard transport for local MCP clients). For a network deployment it also supports **Streamable HTTP** (MCP spec 2025-03-26):

```bash
# Streamable HTTP on 0.0.0.0:8080
python -m src.main --transport http --host 0.0.0.0 --port 8080
```

> Clients connect to `http://<host>:<port>/mcp` (e.g. `http://localhost:8080/mcp`).

> `--transport sse` (legacy Server-Sent Events) is still accepted but **deprecated** — it emits a `DeprecationWarning`. Prefer `--transport http`.

#### Stateless HTTP (horizontal scaling / serverless)

`--stateless` runs the Streamable HTTP transport without server-side sessions: no `Mcp-Session-Id`, a fresh transport per HTTP request. Any instance behind a load balancer can serve any request — **no sticky sessions required**.

```bash
python -m src.main --transport http --host 0.0.0.0 --port 8080 --stateless
```

> ⚠️ **Single-tenant by default.** Without `--multi-tenant` the server serves *its own* process-wide Bitbucket token to every caller. Deploy it on a private network or behind an authenticated reverse proxy — or use [multi-tenant mode](#multi-tenant-http-per-request-credentials), where each caller brings their own credentials.

`--stateless` requires `--transport http` (it is rejected on `stdio` and on the legacy `sse`, whose app ignores the setting). It also forces a **single JSON response** instead of an SSE stream, because edge/serverless runtimes cannot hold a streaming response open — there is currently no way to combine stateless with streaming.

A liveness endpoint is exposed on both HTTP transports for load balancers:

```bash
curl http://localhost:8080/healthz    # {"status": "ok"}
```

**In a container** — the image's default `CMD` keeps it idle for `exec`-based stdio usage, so server mode is started by overriding the command:

```bash
podman run -d --name bitbucket-mcp-http -p 8000:8000 --env-file .env bitbucket-mcp-py \
  python -m src.main --transport http --host 0.0.0.0 --port 8000 --stateless
```

> Works identically with `docker run`. The image exposes port 8000.

| Environment variable | Default | Purpose |
|---|---|---|
| `BITBUCKET_ALLOWED_HOSTS` | *(unset)* | Comma-separated `Host` allowlist. Enables DNS-rebinding protection when set. |
| `BITBUCKET_ALLOWED_ORIGINS` | *(unset)* | Comma-separated `Origin` allowlist. |
| `BITBUCKET_MAX_PAGES_HARD_CAP` | `10` | Max pages a single tool call may fetch **in stateless mode**. Beyond it the response carries `truncated: true` — never a silent cut. |

> The two allowlists must be **set together**: an empty `Host` allowlist rejects every request (`421`), and an empty `Origin` allowlist rejects every browser client (`403`). Setting only one is refused at startup rather than silently locking the server out.

```bash
export BITBUCKET_ALLOWED_HOSTS="mcp.example.com"
export BITBUCKET_ALLOWED_ORIGINS="https://app.example.com"
```

> With neither allowlist set, no DNS-rebinding protection is applied — appropriate for a server reached through a private network or a trusted proxy. Set them as soon as the server is exposed on a real hostname.

#### Multi-tenant HTTP (per-request credentials)

By default an HTTP deployment is **single-tenant**: every caller acts with the process-wide Bitbucket token. `--multi-tenant` changes that — each request carries the **caller's own Bitbucket OAuth access token** as `Authorization: Bearer`, and runs under that identity. The server holds no Bitbucket credential of its own.

```bash
BITBUCKET_RESOURCE_SERVER_URL=https://mcp.example.com \
  python -m src.main --transport http --host 0.0.0.0 --port 8080 --stateless --multi-tenant
```

The token is verified against `GET /2.0/user`, which yields the caller's `account_id` and default workspace; the same token is then reused for the downstream API calls, so no credential is ever stored or mapped. Unauthenticated requests get a `401` with a `WWW-Authenticate` challenge pointing at `/.well-known/oauth-protected-resource`.

What this buys you:

- **Isolation** — one Bitbucket client per `(identity, workspace)`; two callers never share one, and there is no process token to fall back on.
- **`workspace=None` means *your* workspace** — resolved from the caller's memberships, never from `BITBUCKET_WORKSPACE`. With zero or several memberships there is no default and calls must name their workspace.
- **Audit trail** — every call is logged to the `bitbucket_mcp.audit` logger with the tool, the `account_id` and the workspace. Never credentials.
- **Tighter defaults** — tools flagged `destructiveHint` are refused unless explicitly enabled.

| Environment variable | Default | Purpose |
|---|---|---|
| `BITBUCKET_RESOURCE_SERVER_URL` | *(required)* | This server's public URL — the OAuth resource identifier |
| `BITBUCKET_OAUTH_ISSUER_URL` | `https://bitbucket.org` | Advertised authorization server |
| `BITBUCKET_CLIENT_CACHE_SIZE` / `_TTL` | `128` / `900` | Bound on the per-identity client cache (LRU + TTL, seconds). TTL `0` builds a fresh client per request |
| `BITBUCKET_TOKEN_CACHE_SIZE` / `_TTL` | `256` / `300` | Bound on cached token verifications. The TTL is the **revocation window** — set it to `0` to verify every request |
| `BITBUCKET_MULTITENANT_ALLOW_DESTRUCTIVE` | *(off)* | Allow `merge`, `decline`, `delete_*`, `stop_pipeline` |
| `BITBUCKET_MULTITENANT_READ_ONLY` | *(off)* | Expose read-only tools only |

> **Not supported in this mode**: Bitbucket Repository/Workspace Access Tokens — they are not bound to a user account, so no identity can be derived. Use single-tenant HTTP for that. Bearer tokens require TLS: terminate HTTPS in front of the server.

**stdio is unaffected** — it stays single-user with environment variables, exactly as documented above.

See **[docs/deployment-modes.md](docs/deployment-modes.md)** for the full matrix of the three deployment modes and the threat model of each.

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
