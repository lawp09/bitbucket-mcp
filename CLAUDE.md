# CLAUDE.md - Bitbucket MCP Server

## Project Overview

**Name**: bitbucket-mcp-py
**Type**: MCP (Model Context Protocol) Server for Bitbucket API
**Version**: 1.23.0
**Python**: 3.12+
**Container Runtime**: Podman (preferred) or Docker

## Client Configuration (uvx — recommended)

**Claude Code CLI:**
```bash
claude mcp add bitbucket-mcp \
  -e BITBUCKET_USERNAME=your-email@example.com \
  -e BITBUCKET_TOKEN=your-api-token \
  -e BITBUCKET_WORKSPACE=your-workspace \
  -- uvx --from bitbucket-mcp-py bitbucket-mcp
```

**Claude Code / GitHub Copilot JSON config:**
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

**OpenAI Codex TOML config** (`~/.codex/config.toml`):
```toml
[mcp_servers.bitbucket-mcp]
command = "uvx"
args = ["--from", "bitbucket-mcp-py", "bitbucket-mcp"]
env = { BITBUCKET_USERNAME = "your-email@example.com", BITBUCKET_TOKEN = "your-api-token", BITBUCKET_WORKSPACE = "your-workspace" }
```

> **Note**: The PyPI package is `bitbucket-mcp-py` but the command entry point is `bitbucket-mcp`. The `--from` flag is required with `uvx`.

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
├── ci.yml               # CI pipeline (tests + build)
└── release.yml          # Release pipeline (PyPI + MCP Registry + GitHub Release)

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

### MCP Tools (60+ tools)

> **Tool Annotations (MCP 2025)** — every tool advertises behavioural hints
> (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) plus a
> human-readable `title`. Classification is centralised in `conditional_tool`
> (`src/server.py`) via a name-prefix rule + an override table (`_ANNOTATION_OVERRIDES`)
> — the decorator sites stay annotation-free. `openWorldHint=False` everywhere
> (closed domain: one known API).

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

**Disabled by default**: `merge_pull_request` (safety), `stop_pipeline` (safety), `get_pull_request_patch` (git am format — use `get_pull_request_diff` for AI review), `convert_pull_request_to_draft` (not supported by Bitbucket API), `delete_issue` (safety), `delete_issue_comment` (safety), `add_commit_comment` (write op), `create_pipeline_variable`/`update_pipeline_variable`/`delete_pipeline_variable` (write ops), `create_pipeline_schedule`/`update_pipeline_schedule`/`delete_pipeline_schedule` (write ops), `delete_pipeline_cache` (safety), `create_environment`/`delete_environment` (write/safety), `create_deployment_variable`/`update_deployment_variable`/`delete_deployment_variable` (write ops), `create_branch_restriction`/`update_branch_restriction`/`delete_branch_restriction` (write ops)

> **Token tip** — `get_pull_request_diff` accepts an optional `path` parameter to filter the diff to a single file, reducing token usage by ~95% on large PRs:
> ```python
> get_pull_request_diff(repo_slug="my-repo", pull_request_id="42", path="src/services/myService.ts")
> ```

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

**Runtime override via env var** — set `BITBUCKET_TOOLS_CONFIG` to point to a custom JSON file without modifying the bundled config:

```bash
export BITBUCKET_TOOLS_CONFIG=/path/to/my-tools.json
```

Fallback chain: `BITBUCKET_TOOLS_CONFIG` → `configs/tools.json` (built-in default). An explicit path that is missing or invalid raises a hard error at startup.

### Slim Responses

All tool responses pass through transformers (`src/utils/transformers.py`) that strip unnecessary Bitbucket API fields (links, avatars, nested metadata) to reduce LLM token usage. Each entity type has a dedicated `slim_*` function.

## CI/CD

**CI** (`.github/workflows/ci.yml`):
- **Triggers**: push to `main`, PR targeting `main`
- **Steps**: Install deps, run pytest with coverage, build package

**Release** (`.github/workflows/release.yml`):
- **Triggers**: git tag push `v*`
- **Jobs**: `test` → `build` → `publish-pypi` → `publish-mcp-registry` → `github-release`
- PyPI via OIDC Trusted Publisher, MCP Registry via `MCP_GITHUB_TOKEN` secret

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
| `.github/workflows/release.yml` | Release pipeline (PyPI + MCP Registry + GitHub Release) |
| `.env.example` | Template for credentials (copy to .env) |
| `server.json` | MCP Registry manifest (for `mcp-publisher`) |

## Publishing

### PyPI

Handled automatically by GitHub Actions on `git tag`. No manual upload needed.

- Package: https://pypi.org/project/bitbucket-mcp-py/

### MCP Registry

Handled automatically by GitHub Actions on `git tag` (job `publish-mcp-registry`).

Manual fallback:
```bash
mcp-publisher login github    # GitHub OAuth (device flow)
mcp-publisher publish server.json
```
- Registry: https://registry.modelcontextprotocol.io/
- Server name: `io.github.lawp09/bitbucket-mcp`
- **Important**: README must contain `<!-- mcp-name: io.github.lawp09/bitbucket-mcp -->` for PyPI ownership validation
- **Secret**: `MCP_GITHUB_TOKEN` stored in GitHub Actions secrets

### Version Bump Checklist
> Version is now derived from git tags via `hatch-vcs`. Only 2 files to update manually:
1. `server.json` → `version` + `packages[0].version`
2. `CHANGELOG.md` → new entry under `## [X.Y.Z] - YYYY-MM-DD`

Then: `git tag vX.Y.Z && git push origin vX.Y.Z` → GitHub Actions handles the rest.

## Recent Changes

- Added **multi-tenant HTTP mode** (`--multi-tenant`, requires `--transport http` + `BITBUCKET_RESOURCE_SERVER_URL`) — one process, N users, each under **their own Bitbucket identity**. **Architecture decision: bearer + native Bitbucket OAuth** — the caller's Bitbucket access token arrives as `Authorization: Bearer`, is verified *by use* (`GET /2.0/user` → `account_id` + default workspace from **`/user/workspaces`** — *not* `/user/permissions/workspaces`, retired 2026-04-14 by CHANGE-2770 and answering 410, see #77), then **reused as-is** downstream. No store, no mapping, no new dependency. New `src/auth.py` (`BitbucketTokenVerifier`, `BitbucketAccessToken`, `MultiTenantConfig`, `current_identity`). **`get_client()` stays sync**: the SDK's `auth_context_var` (posed by `AuthContextMiddleware`) is a contextvar, readable synchronously → 0 of ~98 call sites touched. **`_clients` (single-tenant) left strictly intact**; a *separate* `_tenant_clients: WeakKeyDictionary[loop, _TenantClientCache]` holds the LRU+TTL cache keyed `(account_id, workspace)` — loop-keying from #71 preserved. **Eviction never closes a live client**: retired → closed when `_inflight` hits 0 (`_client_scope()` per tool call). **Fail-closed everywhere**, incl. the historical no-loop path (which built a client from `BITBUCKET_TOKEN`). Blocker 4 solved structurally: all 90 sites now go through `BitbucketClient._resolve_workspace()`, so `workspace=None` = the caller's workspace (or a clear error when the identity has 0/N memberships). Audit log `bitbucket_mcp.audit`; destructive tools off by default (policy derived from `_classify()`, no second list). **SDK caveat**: `enable_multi_tenant()` assigns `mcp.settings.auth` + the private `mcp._token_verifier` post-construction (the constructor rejects one without the other, and the singleton is built at import) — guard test included. **RAT/WAT unsupported** (no `account_id`). Transport-level integration test pushes 2 bearer identities through the real ASGI stack — the only thing that proves the contextvar survives the SDK's 3 layers of anyio task spawns (v1.26.0, #72)
- Fixed `get_pipeline_step_logs`, which **always returned HTTP 406** — the log endpoint is the only one in this client that isn't JSON (`produces: [application/octet-stream]`), so the client-wide `Accept: application/json` made the API reject every request. Now overridden **per request** (`Accept: */*`), JSON default untouched elsewhere. **Second latent bug fixed**: completed steps `307` to long-term storage and the call lacked `follow_redirects=True` — so fixing only the 406 would have moved the failure to the redirect for exactly the case people read logs in. httpx strips `Authorization` on the cross-origin hop by itself (the storage URL is pre-signed) — covered by a regression test. **Response is now bounded**: trailing 100 KiB by default via the HTTP `Range` header (hence the endpoint's documented `416`), absolute-inclusive `start`/`end` window, `max_bytes=None` to opt out; the body is **streamed** with a rolling buffer + 50 MiB ceiling, and when the storage host **ignores `Range` and replies 200** the requested window is reconstructed client-side instead of silently returning the wrong slice. New `log_uuid` param exposes `.../steps/{uuid}/logs/{log_uuid}` (service containers). **Breaking**: returns `Dict` (`content`/`truncated`/`returned_bytes`/`total_bytes`) instead of `str` — safe, since the tool 406'd on every call. `304`/`If-None-Match` deliberately not exposed (no etag store). This endpoint needs a real **UUID**, not a build number (v1.25.0, #74)
- Added **stateless HTTP mode** (`--stateless`) for horizontal scaling / serverless — no `Mcp-Session-Id`, one transport per request, `json_response=True` (edge runtimes can't hold a stream open). Requires `--transport http` (`parser.error` on `stdio`/`sse` — the SSE app ignores the setting). **Single-tenant**: the process token is served to every caller (multi-tenant → #72). **Two latent bugs fixed**: (1) `FastMCP` auto-enables DNS-rebinding protection when built on a loopback host (constructor default) and `server.py` builds it before `--host` is parsed → every HTTP deployment on a real hostname was **already** rejected with 421; `main()` now sets `transport_security` explicitly (env `BITBUCKET_ALLOWED_HOSTS`/`_ORIGINS`, else `None`). (2) `BitbucketClient.close()` had no caller; `close_clients()` now runs **in the server's own loop** — which required driving `run_stdio_async`/`run_sse_async`/`run_streamable_http_async` directly instead of `mcp.run()`, since `run()` closes its loop before returning (a `finally` around it would find nothing). **FastMCP `lifespan=` is the wrong hook: it is per-session, per-request in stateless.** The client singleton became a `WeakKeyDictionary` keyed by event loop (pool bound to its loop → `Event loop is closed` in serverless); `get_client()` **stays sync** (`get_running_loop()` needs a running loop, not a coroutine caller) → 0 of ~100 call sites touched. Pagination hard cap in stateless (`BITBUCKET_MAX_PAGES_HARD_CAP`, default 10) with `truncated: true` propagated through `_slim_paginated`'s whitelist — distinct from `has_more`. `/healthz` via `mcp.custom_route` (v1.24.0, #71)
- Migrated the HTTP transport from the deprecated **SSE** to **Streamable HTTP** (MCP spec 2025-03-26). `src/main.py`: `--transport http` → `streamable-http`; `--transport sse` kept as a legacy alias emitting a `DeprecationWarning` (out of the `try/except` so warnings-as-errors doesn't mask it as a server crash); `stdio` (default) unchanged. **Also fixed a latent bug**: `mcp.run()` was called with `host`/`port` kwargs that `FastMCP.run(transport, mount_path)` does not accept (`TypeError`) — HTTP never started; host/port are now set on `mcp.settings` before `run()`. `main(argv=None)` is now testable (`parse_args(argv)`); new `tests/test_main.py` mocks `mcp.run` + patches `src.utils.credentials.get_credentials` (imported inside `main()`), with an autouse fixture restoring `mcp.settings`. Transport selection is unit-tested; a real HTTP round-trip stays FastMCP's responsibility (v1.23.0, #62)

- Added Branch Restrictions & Workspace governance tools — 9 tools (`list_branch_restrictions`, `get_branch_restriction` enabled + `create/update/delete_branch_restriction` disabled; `list_workspace_members`, `get_workspace_member`, `list_workspace_permissions`, `list_repository_permissions` enabled — **first `/workspaces/` workspace-level endpoints**). Slim responses `slim_branch_restriction`/`slim_workspace_membership`/`slim_workspace_permission`/`slim_repository_permission`. **API gotchas (verified via docs/community)**: `branch-restrictions` collection REQUIRES a trailing slash (404 otherwise, BCLOUD-17211) while `/{id}` does not; workspace endpoints are standard (no trailing slash); **`/members` returns `workspace_membership` WITHOUT a `permission` field** (roles live on `/permissions`) → distinct transformers; user ids are `account_id`/`uuid` (GDPR 2019, usernames removed) via a dedicated `_slim_workspace_user`; the `PUT` update requires `kind` in the body. Read tools need `repository`/`account` scopes, write tools `repository:admin` (v1.22.0, #63)
- Added MCP Prompts primitive — 4 slash-command templates (`review_pull_request`, `debug_pipeline_failure`, `summarize_repository`, `onboard_reviewer`) that orchestrate existing tools and ask for structured output. New `src/prompts.py` (pure template builders, unit-testable without FastMCP) + `conditional_prompt()` decorator mirroring `conditional_tool`. **Config**: prompts live under a NEW top-level `prompts` key in `configs/tools.json` (NOT under `tools`) so they share `is_tool_enabled` without polluting `_all_tool_names()` / the annotation guard-rails; `load_tools_config` reads both keys. Wrapper functions carry docstrings so FastMCP populates the prompt `description`. Prompts return a `str` → FastMCP wraps it as a user `PromptMessage` (v1.22.0, #60)
- Added Deployments & Environments tools — 10 tools (`list_environments`, `get_environment`, `list_deployments`, `get_deployment`, `list_deployment_variables` enabled; `create_environment`, `delete_environment`, `create_deployment_variable`, `update_deployment_variable`, `delete_deployment_variable` disabled). Slim responses `slim_environment`/`slim_deployment`/`slim_deployment_variable` (masks secured values at every exit point). **API gotchas (verified via docs/community, BCLOUD-18729)**: `/environments/` and `/deployments/` collections REQUIRE a trailing slash (404 otherwise); deployment variables use `deployments_config` (underscore) like pipeline variables; deployment state read via `state.status.name` (not `.result` like pipeline runs) + commit from `deployable.commit.hash`. **Deviations from #61**: no `update_environment` (Bitbucket has no `PUT` for environments — only `POST .../changes`); no env filter on `list_deployments` (API limitation BCLOUD-18729 — filter on the slimmed `environment` field). Read tools need the `deployment` scope, write tools `deployment:write` (v1.21.0, #61)
- Added MCP 2025 Tool Annotations + human-readable `title` on every tool — `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`, so clients auto-include read-only tools and warn before destructive ops. Classification centralised in `conditional_tool` (`src/server.py`) via a name-prefix rule + `_ANNOTATION_OVERRIDES` for atypical verbs (`suggest_*`=read-only; toggles=idempotent; `merge_`/`decline_`/`stop_pipeline`=destructive); `title` auto title-cased + `_TITLE_OVERRIDES`; `openWorldHint=False` everywhere. Purely additive metadata, backward compatible (v1.20.0, #59)
- Added Pipelines Config tools — 14 tools (`get_pipeline_config`, `list_pipeline_variables`, `get_pipeline_variable`, `list_pipeline_schedules`, `get_pipeline_schedule`, `list_pipeline_schedule_executions`, `list_pipeline_caches` enabled; `create/update/delete_pipeline_variable`, `create/update/delete_pipeline_schedule`, `delete_pipeline_cache` disabled). Slim responses `slim_pipeline_config`/`slim_pipeline_variable` (masks secured values)/`slim_pipeline_schedule`/`slim_pipeline_cache`. **API gotchas verified live**: caches use the `pipelines-config` (hyphen) path while variables/schedules use `pipelines_config` (underscore); `get_pipeline_config` requires the `admin:repository` scope (403 otherwise); pipeline list endpoints return 200-empty (not 404) when there are no items, so no `pipelines_disabled` wrapper is needed. Hardened `slim_pipeline_run`/`step` against null `state`/`result` (in-progress runs) (v1.19.0)
- Added Source & Commits tools — 7 tools (`list_commits`, `get_commit`, `get_commit_comments`, `get_commit_comment`, `add_commit_comment` [disabled], `get_file_content`, `list_directory`); read a file/tree at any commit without cloning, browse commit history. `/src` access is hardened: percent-encoded paths, `..` traversal rejected, `?format=meta` pre-check rejecting directories/oversized/binary files, TOCTOU-safe pinning to the resolved commit hash, tolerant decoding. New transformers `slim_commit_comment`/`slim_source_entry`; `aggregate_pages` gains `follow_redirects` (the `/src` endpoint 302-redirects) (v1.18.0)
- Added Bitbucket Issue Tracker support — 10 tools (`list_issues`, `get_issue`, `create_issue`, `update_issue`, `delete_issue` [disabled], `get_issue_comments`, `get_issue_comment`, `add_issue_comment`, `update_issue_comment`, `delete_issue_comment` [disabled]); `list_issues` filters via dedicated params + raw BBQL `q` + `sort`; graceful `issue_tracker_disabled` response when the opt-in tracker is off; slim responses `slim_issue`/`slim_issue_comment` (v1.17.0, #50)
- Documented OpenAI Codex as MCP client (CLI + `~/.codex/config.toml`); client priority Claude Code → Codex → Cursor → VS Code (GitHub Copilot); added `openai-codex` PyPI keyword (v1.16.1)
- Added `get_repository_tags` tool — list repository tags sorted by most recent target (commit) date, slim responses (`slim_tag`/`slim_tag_list`) + pagination; pagination aligned with `list_repositories` (v1.16.0, #49)
- Added 6 tools — `create_draft_pull_request`, `publish_draft_pull_request`, `convert_pull_request_to_draft` (disabled), `submit_pull_request_batch_review`, `get_pull_request_review_summary`, `suggest_pull_request_reviewers`; fix `create_pull_request` draft payload (`draft: true` vs `state: "DRAFT"`)
- Added 7 tools — Tasks PR CRUD, `get_pull_request_patch` (disabled by default), `get_pull_requests_pending_review`, `path` filter on `get_pull_request_diff` (v2.0.0)
- Added 8 Phase 1 Quick Wins tools — comment CRUD, run/stop pipeline, effective default reviewers (v1.9.0)
- Automated MCP Registry publish in release pipeline — `publish-mcp-registry` job (v1.8.1)
- Added `/release` Claude Code skill for orchestrating the full release workflow (v1.8.1)
- Added `request_changes_pull_request` and `unrequest_changes_pull_request` tools (v1.8.0)
- Added `get_commit_statuses` tool for Jenkins/CI polling without a PR (v1.7.0)
- Published to PyPI and MCP Registry
- Added GitHub Actions release pipeline (PyPI OIDC + MCP Registry + GitHub Release)
- Added slim response transformers to reduce LLM token usage (`src/utils/transformers.py`)
- Added secure credentials management with keychain support (`src/utils/credentials.py`)

## Conventions

- **Async-first**: All API calls use `async/await`
- **Type hints**: All functions have type annotations
- **Structured output**: Tools return `Dict[str, Any]`, not strings
- **Logging**: Use `logging` module, output to stderr
- **Tests**: pytest with pytest-asyncio, min coverage 80%
