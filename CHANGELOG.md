# Changelog - Bitbucket MCP Server Python

## [1.26.0] - 2026-08-12

### Added
- **Multi-tenant HTTP mode** (issue #72) — `--multi-tenant` lets one process serve several users, each acting under **their own Bitbucket identity**. Each request carries the caller's Bitbucket OAuth access token as `Authorization: Bearer`; the server verifies it by use (`GET /2.0/user`), derives the caller's `account_id` and default workspace, and reuses the same token for the downstream calls. **No credential store, no mapping, no new dependency** — the token presented *is* the caller's credential, carrying exactly the caller's rights. Rejected alternatives: a raw-token pass-through header (no verified identity, no OAuth discoverability) and an identity→stored-credentials mapping (a persistent store is a new attack surface for no gain here). Requires `--transport http` and `BITBUCKET_RESOURCE_SERVER_URL`; combines with `--stateless`.
- Injectable auth strategy on `BitbucketClient` — `BasicAuthStrategy` (unchanged default) and `BearerAuthStrategy`, behind the new `BitbucketClient.from_bearer()`. The public constructor `BitbucketClient(email, token, workspace)` is untouched; both strategies redact their credential in `repr()`.
- Bounded per-identity client cache, keyed `(account_id, workspace)` **inside** the existing loop-keyed registry from #71, so a connection pool still belongs to the loop that created it. LRU + TTL (`BITBUCKET_CLIENT_CACHE_SIZE`/`_TTL`, defaults 128/900 s) with `aclose()` on eviction — but a client evicted while a request is still using it is only retired, then closed once its last in-flight caller is gone, never mid-request. Each entry also records the fingerprint of the token it was built with, so a caller who rotates their OAuth token gets a rebuilt client (replacing their entry) instead of being served the stale credential.
- Bounded token-verification cache keyed by a SHA-256 **fingerprint**, never the token (`BITBUCKET_TOKEN_CACHE_SIZE`/`_TTL`, defaults 256/300 s). Concurrent first-time verifications of the same token are de-duplicated into a single pair of Bitbucket calls. The TTL is the **revocation window**; `BITBUCKET_TOKEN_CACHE_TTL=0` verifies on every request.
- Audit trail on the `bitbucket_mcp.audit` logger — tool name, `account_id`, workspace. Never credentials, never raw arguments. Emitted in multi-tenant mode only; stdio stays silent.
- Multi-tenant exposure policy derived from the MCP 2025 annotations already on every tool: `destructiveHint` tools are refused unless `BITBUCKET_MULTITENANT_ALLOW_DESTRUCTIVE=1`, and `BITBUCKET_MULTITENANT_READ_ONLY=1` narrows exposure to `readOnlyHint` tools. No second hand-maintained list.
- Typed `AuthorizationError`, following the `IssueTrackerDisabledError` convention: raised when a multi-tenant request carries no verified identity, when an identity resolves to no workspace and none was passed, or when Bitbucket answers 401/403 to a bearer call. The message carries the account id, workspace and status — **never a token**.
- `docs/deployment-modes.md` — the three deployment modes (stdio single-user / HTTP single-tenant / HTTP multi-tenant) with the threat model, mitigations and residual risks of each.

### Security
- **Fail-closed by construction.** In multi-tenant mode `get_client()` never falls back to the process credentials: no verified identity raises, and the historical "no running event loop" path — which built a client from `BITBUCKET_TOKEN` — is refused rather than silently running one caller's request under another principal.
- `workspace=None` now resolves to the **caller's** workspace, never the process one, because the per-identity client carries the caller's default. Where the caller has zero or several workspace memberships there is no default at all and the call fails with a clear error instead of building a `/repositories/None/...` URL. Routed through a single `BitbucketClient._resolve_workspace()` used by all 90 call sites, so the guard cannot be forgotten on a new method.
- The `token` field of the access token is declared `repr=False`: the inherited pydantic repr would otherwise print the raw credential into any log line or traceback rendering it.

### Changed
- Every tool is now wrapped once, from the single `conditional_tool` site, with the multi-tenant policy check, the audit line and a client-lifetime scope. `functools.wraps` keeps `__wrapped__` set so FastMCP still derives the input schema from the real signature — asserted by a test.
- Bearer (multi-tenant) clients map 401/403 to `AuthorizationError` via an httpx response hook. Basic-Auth clients are deliberately left alone: a 403 is a documented outcome for some endpoints (e.g. `get_pipeline_config` without `admin:repository`) and callers already handle it as an `httpx.HTTPStatusError`.
- `BitbucketClient.close()` is idempotent, so the several cleanup paths cannot double-close.
- In multi-tenant mode the startup credential check is skipped (there is nothing to check); a leftover `BITBUCKET_TOKEN` is reported as ignored rather than silently unused.

### Notes
- **Repository and Workspace Access Tokens are not supported** in multi-tenant mode: they are not bound to a user account, so `GET /2.0/user` rejects them and no identity can be derived. Use single-tenant HTTP for that case.
- The server enforces no scopes of its own — Bitbucket answers 401/403 per call, and the scope names are not readable from `/2.0/user`.
- Rate limiting is not implemented and largely moot here: Bitbucket quotas are per account, and each call consumes the *caller's* quota, so one tenant cannot drain another's. The stateless pagination hard cap from #71 still bounds per-call amplification.
- The Python SDK caps at MCP protocol `2025-11-25`; this mode uses the OAuth primitives available there. Full alignment with the `2026-07-28` authorization model waits on SDK support.
- `enable_multi_tenant()` assigns `mcp.settings.auth` and the SDK-private `mcp._token_verifier` after construction, because `FastMCP(...)` rejects one without the other and the singleton is built at import time, before the CLI is parsed — the same pattern already used for `host`/`port`/`transport_security`. A guard test fails loudly if the SDK renames either.

## [1.25.0] - 2026-08-12

### Fixed
- **`get_pipeline_step_logs` always failed with HTTP 406** (issue #74). The pipeline step log endpoint is the only one in this client that does not return JSON — the Bitbucket spec declares `produces: [application/octet-stream]` — so the client-wide `Accept: application/json` header made the API reject every single request. The log call now overrides `Accept: */*` per request; the JSON default is untouched for all other endpoints.
- **307 redirect was not followed** on the same endpoint. Once a step completes, its log is moved to long-term storage and the API answers `307`. `httpx.AsyncClient` defaults to `follow_redirects=False` and `raise_for_status()` raises on an unfollowed redirect — so with only the 406 fixed, every *completed* step (exactly the case where one wants to read logs) would have failed on the redirect instead. The call now passes `follow_redirects=True`. httpx strips the `Authorization` header on that cross-origin hop by itself, which is what we want: the storage URL is pre-signed and must not receive Bitbucket credentials. Covered by a regression test.

### Added
- Size bounding on `get_pipeline_step_logs`. Raw step logs routinely run to several MB (a 24-minute step in the issue's repro), and returning them wholesale blows up the MCP client's context. By default only the trailing 100 KiB are returned, requested via the HTTP `Range` header the endpoint documents (hence its documented `416`). New `start` / `end` parameters take an **absolute, inclusive** byte window, and `max_bytes=null` opts out entirely.
- `log_uuid` parameter on `get_pipeline_step_logs`, exposing `.../steps/{step_uuid}/logs/{log_uuid}` — the build container's log is the default, a service container UUID reads that service's log instead. Useful when a step fails inside a service container.
- The response body is now **streamed** with a rolling buffer and a 50 MiB ceiling, so an oversized log cannot exhaust memory even when the long-term-storage host ignores `Range` and replies `200` with the whole file. In that case the requested window is reconstructed client-side rather than silently returning the wrong slice.

### Changed
- **Breaking**: `get_pipeline_step_logs` returns a `Dict[str, Any]` — `content`, `truncated`, `returned_bytes`, `total_bytes` — instead of a bare `str`, aligning it with the project's structured-output convention and making the size bounding visible to the caller. No caller can have depended on the old shape: the tool returned `406` on every invocation.
- The tool description now states that this endpoint needs a real pipeline **UUID**. A build number happens to work on `get_pipeline_run`, but it is not documented for the log endpoint — resolve the UUID first.

### Notes
- `304` / `If-None-Match` caching is documented by the endpoint but deliberately not exposed: this client keeps no caller-side etag store.
- Derived from the official Bitbucket spec plus a community thread, and verified against mocks; a live `curl` against a completed step is still worth doing before relying on the `206` path, which Bitbucket's own documented response list omits.

---

## [1.24.0] - 2026-08-04

### Added
- **Stateless HTTP mode** (issue #71) — `--stateless` runs the Streamable HTTP transport with no server-side session: no `Mcp-Session-Id`, a fresh transport per request, so any instance behind a load balancer can serve any request without sticky sessions. Enables horizontal scaling and serverless deployment. Requires `--transport http` (rejected with exit code 2 on `stdio` and on the legacy `sse`, whose app ignores the setting — a silently inert flag is a production footgun). Implies a single JSON response instead of an SSE stream, as required by edge runtimes. **Single-tenant**: the process-wide Bitbucket token is served to every caller — deploy behind a private network or an authenticated proxy (per-request credentials tracked in #72).
- `/healthz` liveness endpoint on both HTTP transports, for load balancers and container health checks. Inert under stdio.
- Configurable transport security via `BITBUCKET_ALLOWED_HOSTS` / `BITBUCKET_ALLOWED_ORIGINS` (comma-separated): when set, DNS-rebinding protection is enabled with those allowlists. The two must be set **together** — the SDK's checks have no "unset means skip" branch, so an empty `Host` allowlist rejects every request (421, verified live) and an empty `Origin` allowlist rejects every browser client (403). Setting only one exits with code 2 and an explanatory message instead of silently locking the server out.
- Graceful shutdown on SIGINT/SIGTERM under stdio: the signals cancel the serving task so the cleanup path actually runs (a raw Ctrl-C raises `KeyboardInterrupt` from the loop's internal poll, outside the coroutine frame, skipping it). The handlers are restored to their defaults before cleanup, so a second Ctrl-C during shutdown surfaces as a `KeyboardInterrupt` main() already handles rather than an uncaught `CancelledError` traceback. The HTTP transports are left alone — uvicorn installs its own handling. `"Server stopped by user"` is still printed on the signal path.
- Pagination hard cap in stateless mode (`BITBUCKET_MAX_PAGES_HARD_CAP`, default 10). With `json_response=True` nothing is emitted until the walk completes, so an unbounded `max_pages=None` can outlive a proxy idle timeout or an edge duration limit. Beyond the cap the response carries `truncated: true` — distinct from `has_more` ("there is a next page") in that it means "the server capped this walk". Never a silent truncation. Inactive outside stateless mode.

### Fixed
- **HTTP transport rejected any real hostname (421)**. `FastMCP` auto-enables DNS-rebinding protection when constructed on a loopback host (its constructor default), and `src/server.py` builds the server before `--host` is parsed — so `--host 0.0.0.0` behind a reverse proxy or a domain name was refused with `421`/`403` unless the client literally used `localhost`. `main()` now sets `transport_security` explicitly (from the env allowlists, or `None`). Reproduced against v1.23.0 and verified fixed.
- **`httpx.AsyncClient` was never closed** — `BitbucketClient.close()` had no caller in either transport. `close_clients()` now runs in the server's own event loop on shutdown. This required driving the FastMCP transport coroutines directly (`run_stdio_async` / `run_sse_async` / `run_streamable_http_async`, exactly what `FastMCP.run()` dispatches to) instead of `mcp.run()`: `run()` closes its event loop before returning, so any cleanup wrapped around it would run on a fresh loop and find nothing to close. FastMCP's `lifespan=` is *not* the right hook here — it is per-session (per-request in stateless mode), so closing a shared pool there would cut it under a concurrent request.
- The `max_pages` recommended-limit warning now logs the effective value, after any clamping, instead of the requested one.

### Changed
- The Bitbucket client singleton became a registry keyed by event loop (`WeakKeyDictionary`). A connection pool is bound to the loop that created it; a process-wide singleton is fine under uvicorn (one loop for the whole process) but raises `RuntimeError: Event loop is closed` in serverless deployments where each invocation runs its own `asyncio.run()`. Within a loop the client is still reused, so keep-alive pooling is preserved — which matters because `aggregate_pages` chains N requests to `api.bitbucket.org` per tool call. `get_client()` stays a **sync** function: `asyncio.get_running_loop()` only needs a running loop, not a coroutine caller, so none of its ~100 call sites changed.
- `Dockerfile` declares `EXPOSE 8000`. The `CMD` is deliberately unchanged (`tail -f /dev/null`) — the Makefile's `up` + `exec` workflow depends on it; the README documents the `podman run`/`docker run` invocation that overrides it for server mode.

### Notes
- Verified against a live server, not only mocks: stateless mode returns no `Mcp-Session-Id` and serves a second request with no shared state; the default HTTP mode still issues a session id and an SSE stream; a foreign `Host` is rejected with 421 once an allowlist is set.
- Clients still connect to `http://<host>:<port>/mcp`.

---

## [1.23.0] - 2026-06-29

### Changed
- HTTP transport migrated from the deprecated **SSE** transport to **Streamable HTTP** (MCP spec 2025-03-26). `--transport http` now selects `streamable-http`; `--transport sse` is kept as a legacy alias that emits a `DeprecationWarning`. `--transport stdio` (the default) is unchanged.

### Fixed
- HTTP transport never actually started: `mcp.run()` was being called with `host`/`port` keyword arguments that `FastMCP.run()` does not accept (`TypeError`). Host/port are now set on `mcp.settings` before `run()`, so the HTTP server starts correctly.

### Notes
- `main()` now accepts an optional `argv` (defaults to `sys.argv`) for testability. Transport selection is unit-tested with `mcp.run` mocked; a real HTTP round-trip remains FastMCP's responsibility (validate manually with `python -m src.main --transport http`).
- README documents the Streamable HTTP endpoint path: clients connect to `http://<host>:<port>/mcp`.

---

## [1.22.0] - 2026-06-29

### Added
- Branch Restrictions & Workspace governance tools (issue #63) — 9 tools. Branch Restrictions (repo-level): `list_branch_restrictions`, `get_branch_restriction` (enabled); `create_branch_restriction`, `update_branch_restriction`, `delete_branch_restriction` (disabled). Workspace (workspace-level, first `/workspaces/` endpoints): `list_workspace_members`, `get_workspace_member`, `list_workspace_permissions`, `list_repository_permissions` (all enabled). Slim responses `slim_branch_restriction` / `slim_workspace_membership` / `slim_workspace_permission` / `slim_repository_permission`. Enterprise governance/compliance use cases, uncovered by any competitor Bitbucket MCP.
- **API specifics handled**: the `branch-restrictions` collection requires a trailing slash (404 otherwise, BCLOUD-17211) while the `/{id}` resource does not; workspace endpoints are standard (no trailing slash). The `/members` endpoint returns `workspace_membership` objects **without** a `permission` field — per-user roles live on the separate `/permissions` endpoint, so memberships and permissions use distinct transformers. User identifiers are `account_id`/`uuid` (usernames removed from API URLs in 2019 for GDPR), preserved by a dedicated `_slim_workspace_user`. The `PUT` update requires `kind` in the body.
- MCP Prompts primitive (issue #60) — 4 parameterised prompt templates surfaced as slash commands by compatible clients: `review_pull_request`, `debug_pipeline_failure`, `summarize_repository`, `onboard_reviewer`. Each orchestrates a sequence of existing tools and asks for a structured output. No competitor Bitbucket MCP exposes prompts.
- New `src/prompts.py` module holding pure template builders (unit-testable without FastMCP), and a `conditional_prompt()` decorator mirroring `conditional_tool`. Prompts are enabled/disabled in `configs/tools.json` under a new top-level `prompts` key (kept separate from `tools` so the annotation guard-rails are untouched). Prompt wrappers carry docstrings so the MCP `description` is populated.

### Notes
- Branch restriction read tools require the `repository` scope (`repository:admin` may be needed per repo config); write tools require `repository:admin`. Workspace tools require the `account` scope.
- Prompts are read-only orchestration templates — they reference tools by name and return a user message; they do not call the Bitbucket API themselves.

---

## [1.21.0] - 2026-06-28

### Added
- Deployments & Environments tools (issue #61) — 10 tools. Read (enabled): `list_environments`, `get_environment`, `list_deployments`, `get_deployment`, `list_deployment_variables`. Write (disabled by default): `create_environment`, `delete_environment`, `create_deployment_variable`, `update_deployment_variable`, `delete_deployment_variable`. Slim responses `slim_environment` / `slim_deployment` / `slim_deployment_variable` (the latter masks `secured` values to `null` at every exit point — list, get, create, update). No competitor Bitbucket MCP covers these endpoints.
- **API specifics handled**: the `/environments/` and `/deployments/` collection endpoints require a trailing slash (404 otherwise); deployment variables live under `deployments_config` (underscore, like pipeline variables, not the hyphenated caches path); deployment state is read via `state.status.name` (not `state.result.name` as for pipeline runs) and the deployed commit from `deployable.commit.hash`.

### Deviations from the issue
- **No `update_environment`** — Bitbucket exposes no `PUT /environments/{uuid}` (modification is only possible via `POST .../changes` for locking/restrictions, out of scope). 10 tools instead of the 11 listed.
- **No environment filter on `list_deployments`** — the API has no server-side filter for deployments by environment (BCLOUD-18729); consumers filter on the slimmed `environment` field.

### Notes
- Read tools require the `deployment` OAuth scope; write tools require `deployment:write`.

---

## [1.20.0] - 2026-06-28

### Added
- MCP 2025 Tool Annotations on every tool — `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`. Clients (Claude Code, Cursor) use them to auto-include read-only tools without confirmation and to warn before destructive operations (merge, delete, stop). Classification is centralised in `conditional_tool` via a name-prefix rule (`get_`/`list_`/`create_`/`add_`/`update_`/`delete_`) plus an explicit override table for atypical verbs (`suggest_*` is read-only; toggles like `approve_`/`resolve_` are idempotent writes; `merge_`/`decline_`/`stop_pipeline` are destructive non-idempotent). `openWorldHint` is `False` everywhere (closed domain — a single known API).
- Human-readable `title` (MCP 2025) on every tool — auto title-cased from the tool name, with a small override table for awkward labels.

### Notes
- Purely additive metadata — no tool signature or runtime behaviour changed, fully backward compatible. No new dependency (`ToolAnnotations` ships with `mcp`).

---

## [1.19.0] - 2026-06-27

### Added
- Pipelines Config tools — 14 new MCP tools. Read (enabled): `get_pipeline_config`, `list_pipeline_variables`, `get_pipeline_variable`, `list_pipeline_schedules`, `get_pipeline_schedule`, `list_pipeline_schedule_executions`, `list_pipeline_caches`. Write (disabled by default): `create_pipeline_variable`, `update_pipeline_variable`, `delete_pipeline_variable`, `create_pipeline_schedule`, `update_pipeline_schedule`, `delete_pipeline_schedule`, `delete_pipeline_cache`.
- Slim responses `slim_pipeline_config`, `slim_pipeline_variable` (secured variables never expose their value), `slim_pipeline_schedule`, `slim_pipeline_schedule_execution`, `slim_pipeline_cache`.

### Changed
- `list_directory` hoists the resolved commit hash to a single top-level `commit` field instead of repeating it on every entry (token saving on large directories — all entries of a listing are at the same commit).

### Fixed
- `slim_pipeline_run` / `slim_pipeline_step` no longer raise `AttributeError` when `state` or `state.result` is null (the case for in-progress runs).

### Notes (verified against the live API)
- Pipeline caches live under the `pipelines-config` (hyphen) path, while variables and schedules use `pipelines_config` (underscore).
- `get_pipeline_config` requires the `admin:repository` scope; a read-only token receives a 403 listing the missing privilege.
- Pipeline list endpoints return an empty `200` (not a `404`) when there are no items, so no special "pipelines disabled" handling is needed.

---

## [1.18.0] - 2026-06-27

### Added
- Source & Commits tools — 7 new MCP tools: `list_commits` (optionally scoped to a revision/path), `get_commit`, `get_commit_comments`, `get_commit_comment`, `add_commit_comment` (disabled by default — write op), `get_file_content`, `list_directory`. An agent can now read a file or browse the tree at any commit/branch and inspect commit history without cloning.
- Slim responses `slim_commit_comment` / `slim_source_entry` (the commit-comment slim deliberately drops the resolution fields that only apply to PR comments).

### Changed
- `aggregate_pages` / `paginate_bitbucket` gain an opt-in `follow_redirects` flag (default `False`, no change to existing endpoints) — required because the `/src` directory listing 302-redirects to a commit-pinned URL.

### Security
- `get_file_content` / `list_directory` harden `/src` access: the user `path` is percent-encoded (`?`, `#`, `%`, spaces), parent-directory (`..`) segments are rejected, a `?format=meta` pre-check refuses directories / oversized files (> 256 KiB) / binary mimetypes, the content fetch is pinned to the resolved commit hash (closes a TOCTOU window on moving branch refs), and decoding is tolerant (`errors="replace"`) to avoid crashes on non-UTF-8 files.

---

## [1.17.0] - 2026-06-26

### Added
- Bitbucket Issue Tracker support — 10 new MCP tools: `list_issues` (filter by `state`/`kind`/`priority`/`assignee` plus raw BBQL `q` and `sort`), `get_issue`, `create_issue`, `update_issue`, `delete_issue` (disabled by default), `get_issue_comments`, `get_issue_comment`, `add_issue_comment`, `update_issue_comment`, `delete_issue_comment` (disabled by default). Slim responses (`slim_issue` / `slim_issue_comment`) and pagination throughout. (#50)
- Graceful failure when a repository's issue tracker is disabled — issue tools return `{"error": "issue_tracker_disabled", ...}` instead of a raw 404 (the tracker is opt-in per repository)

---

## [1.16.1] - 2026-06-26

### Changed
- Documentation — add OpenAI Codex client setup (CLI `codex mcp add` + `~/.codex/config.toml`); client priority order: Claude Code → OpenAI Codex → Cursor → VS Code (GitHub Copilot)
- PyPI keywords — add `openai-codex`

---

## [1.16.0] - 2026-06-26

### Added
- `get_repository_tags` tool — list a repository's tags ordered by most recent target (commit) date, with slim responses (`slim_tag` / `slim_tag_list`) and pagination (`page_size` / `max_pages`). (#49)

### Fixed
- `get_repository_tags` — align pagination with `list_repositories`: remove the manual truncation that made `max_pages` silently ineffective, and drop the unused `limit` alias

---

## [1.15.1] - 2026-03-20

### Changed
- Upgrade `mcp` dependency from `>=1.1.1` to `>=1.26.0,<2` (upper bound `<2` guards against future breaking changes)

---

## [1.15.0] - 2026-03-18

### Fixed
- `get_pull_request_comments` — remove unsupported `q=resolution=null` API filter that caused 400 Bad Request on Bitbucket Cloud; unresolved filtering now done client-side in server.py
- `get_pull_request_comments` MCP tool — `unresolved_only=True` now correctly filters results client-side (param was previously a no-op after API filter removal)
- `pyproject.toml` — update development status classifier from Beta to Production/Stable

---

## [1.14.1] - 2026-03-13

### Fixed
- `get_pull_request_review_summary` — eliminate redundant PR API call in diffstat (5→4 HTTP requests per invocation)
- `get_pull_request_review_summary` — restore `unresolved_only=True` for API-side comment filtering
- `get_pull_request_review_summary` — compute `ci_failing`/`ci_pending` from slimmed data (single source of truth)
- `_enrich_comment_with_resolution` — return a copy instead of mutating the input dict
- Remove dead code checking `state=="DRAFT"` (Bitbucket Cloud uses `draft: true`)

### Added
- `get_pull_request_review_summary` — new `review_readiness` states: `ci_pending`, `merged`, `declined`
- `get_pull_request_diffstat` client method — optional `pr_data` parameter to skip redundant PR fetch
- 4 new tests: resolved comment filtering, `ci_pending`, `merged`, `declined` readiness states
- Call argument assertions in tests to lock optimizations against regressions

---

## [1.14.0] - 2026-03-11

### Added
- `BITBUCKET_TOOLS_CONFIG` environment variable — override the built-in `configs/tools.json` at runtime to restrict which MCP tools are registered
- Fallback chain: `config_path` argument > `BITBUCKET_TOOLS_CONFIG` env var > default path
- Fail-safe: explicit config paths that are missing or contain invalid JSON raise a hard error at startup
- 7 unit tests for `load_tools_config()` runtime path resolution

---

## [1.13.1] - 2026-03-09

### Fixed
- `create_pull_request` / `update_pull_request` — fix double-wrapping of reviewer dicts (e.g. `{"uuid": {"uuid": "..."}}`) when caller passes pre-formed `{"uuid": "..."}` objects; extract `_normalize_reviewers` helper
- `create_pull_request` — unify `if reviewers:` → `if reviewers is not None:` to match `update_pull_request` behavior
- `create_pull_request` — fix type hint from `List[str]` to `list` to accept both string and dict reviewers

---

## [1.13.0] - 2026-03-09

### Added
- `update_pull_request` — add `reviewers` parameter (list of UUIDs); supports adding, replacing, or clearing reviewers (`[]` clears all)
- `slim_pull_request` — expose `author_uuid`, `reviewers[].uuid`, and `participants[].uuid` to enable read-then-write reviewer workflows

### Fixed
- `slim_pull_request` — reviewers use flat user structure (`r.uuid`, `r.display_name`); participants use nested structure (`p.user.uuid`) — matches real Bitbucket API shapes
- `update_pull_request` — return full `slim_pull_request` response (instead of `slim_pull_request_created`) so caller can confirm reviewer changes
- `create_pull_request` docstring — correct `reviewers` param description from "usernames" to "UUIDs"
- `update_pull_request` docstring — warn that `reviewers` REPLACES the entire list; instruct LLM to call `get_pull_request` first to preserve existing reviewers

---

## [1.12.0] - 2026-02-27

### Changed
- `create_pull_request_task` — add optional `comment_id` parameter to link a task to a specific PR comment; backward compatible (defaults to `None`)

---

## [1.11.0] - 2026-02-26

### Added
- `create_draft_pull_request` — create a pull request in draft state (alias for `create_pull_request(draft=True)`)
- `publish_draft_pull_request` — publish a draft PR to open state (`PUT` with `{"draft": false}`)
- `convert_pull_request_to_draft` — disabled (not supported by Bitbucket Cloud API, returns descriptive error)
- `submit_pull_request_batch_review` — post N inline/top-level comments + approve or request_changes in one operation
- `get_pull_request_review_summary` — composite tool: PR + diffstat + unresolved comments + CI statuses via `asyncio.gather`, returns `review_readiness` assessment
- `suggest_pull_request_reviewers` — combine default reviewers with historical approver scoring to rank best reviewers

### Fixed
- `create_pull_request` — fix draft payload: use `{"draft": true}` instead of `{"state": "DRAFT"}` (Bitbucket API v2 convention)

---

## [1.10.1] - 2026-02-25

### Fixed
- Correct GitHub repository URLs in `pyproject.toml` project links (were pointing to `bitbucket-mcp-py` instead of `bitbucket-mcp`)

---

## [1.10.0] - 2026-02-25

### Added
- `get_pull_request_tasks` — list tasks on a pull request (paginated)
- `get_pull_request_task` — get a single task by ID
- `create_pull_request_task` — create a task on a pull request
- `update_pull_request_task` — update task content and/or state (UNRESOLVED/RESOLVED)
- `delete_pull_request_task` — delete a task from a pull request
- `get_pull_request_patch` — get git format-patch for a PR (disabled by default — use `get_pull_request_diff` for AI review)
- `get_pull_requests_pending_review` — list open PRs where the current user is a reviewer
- `workflow_dispatch` trigger added to CI workflow for manual runs

### Changed
- `get_pull_request_diff` — new optional `path` parameter to filter diff to a single file (~95% token reduction on large PRs)

### Fixed
- `get_pull_request_diff` — add `follow_redirects=True` to handle HTTP 302 redirects from Bitbucket CDN on large PRs

---

## [1.9.0] - 2026-02-25

### Added
- `get_pull_request_comment` — get a single PR comment by ID
- `update_pull_request_comment` — edit comment content
- `delete_pull_request_comment` — delete a PR comment
- `resolve_pull_request_comment` — mark a comment as resolved
- `reopen_pull_request_comment` — reopen a resolved comment
- `run_pipeline` — trigger a pipeline on a branch
- `stop_pipeline` — stop a running pipeline (disabled by default)
- `get_effective_default_reviewers` — list effective default reviewers for a repo

### Fixed
- `slim_reviewer` transformer now reads user fields from nested `user` object (API structure)
- `delete_pull_request_comment` tool enabled by default in `configs/tools.json`

---

## [1.8.1] - 2026-02-24

### Added
- Automated MCP Registry publish in release pipeline (job `publish-mcp-registry` in `release.yml`)
- New `/release` skill for Claude Code to orchestrate the complete release workflow

### Changed
- GitHub Actions release workflow now publishes to both PyPI and MCP Registry on git tag push
- `github-release` job waits for both `publish-pypi` and `publish-mcp-registry` to succeed

---

## [1.8.0] - 2026-02-24

### Added
- New MCP tool `request_changes_pull_request` — sets reviewer status to "needs work" via `POST .../request-changes`
- New MCP tool `unrequest_changes_pull_request` — removes "needs work" status via `DELETE .../request-changes`

---

## [1.7.0] - 2026-02-23

### Added
- New MCP tool `get_commit_statuses` — get Jenkins/CI build statuses for any branch commit without creating a PR
- Uses Bitbucket API v2 endpoint `GET /repositories/{workspace}/{repo}/commit/{hash}/statuses`
- Supports pagination (`page_size`, `max_pages`)
- Slim response via existing `slim_status_list` transformer (removes noise, reduces LLM token usage)

---

## [1.6.0] - 2026-02-23

### Added
- Automated PyPI release pipeline via GitHub Actions (triggered on git tags `v*`)
- PyPI Trusted Publisher (OIDC) — no API token stored in GitHub
- GitHub Release auto-created with CHANGELOG notes on each tag

### Changed
- Version now derived from git tags via `hatch-vcs` (no more manual version bump in code)
- `CLAUDE.md` version bump checklist updated (2 files instead of 4)

### Fixed
- `__version__` fallback chain: `importlib.metadata` → `_version.py` → `0.0.0-dev`
- Dockerfile: `SETUPTOOLS_SCM_PRETEND_VERSION` ARG for hatch-vcs compatibility

---

## [1.5.0] - 2026-02-23

### Added
- uvx support via `[project.scripts]` entry point (`bitbucket-mcp` command)
- `merge_pull_request` tool enabled in default configuration
- Cursor configuration section in README
- Three installation modes documented (uvx, pip, local dev)
- `uv.lock` for reproducible installs

### Changed
- README rewritten with uvx as primary install method
- All references to Claude Desktop replaced with Claude Code
- Tool count corrected to 21 in README

### Fixed
- PyPI project URLs corrected (bitbucket-mcp → bitbucket-mcp-py)
- PyPI keywords enriched (claude-code, cursor, github-copilot, etc.)

---

## [Unreleased]

### Added

- Threaded reply support for PR comments via `parent_id` parameter on `add_pull_request_comment`
- GitHub Actions CI workflow (tests + build on push/PR to main)
- MIT LICENSE file
- CONTRIBUTING.md with dev setup and PR guidelines
- CODE_OF_CONDUCT.md (Contributor Covenant v2.1)
- PyPI metadata: license, authors, keywords, classifiers, project URLs
- GitHub topics and repository description
- Published to PyPI (`pip install bitbucket-mcp-py`)
- Published to [MCP Registry](https://registry.modelcontextprotocol.io/) (`io.github.lawp09/bitbucket-mcp`)
- `server.json` manifest for MCP Registry publishing
- PyPI badges and install section in README

### Changed

- Version bump to 1.4.1 for MCP Registry publication
- README: recommend `.env` file instead of shell exports for credentials
- CLAUDE.md: add publishing workflow, version bump checklist

### Security

- Remove `email` and `token` attributes from `BitbucketClient` after auth header construction
- Add protected `__repr__` on `BitbucketClient` to prevent credential leaks in logs
- Use `get_credentials()` in `main.py` startup validation (enables keychain fallback)

---

## [1.4.0] - 2026-02-10

### Added

- Slim response transformers to reduce LLM token usage (PR #5)
- Secure credentials management with system keychain support (`src/utils/credentials.py`)
- Optional `keyring` dependency for keychain integration
- `.env.example` template file for credential configuration

### Changed

- Consolidated config examples into `examples/` folder (PR #4)
- Replace "app password" references with "API token" and update URLs to Atlassian ID (PR #3)
- Simplified README from 587 to 122 lines
- `max_pages` in `PaginationConfig` now accepts `None` for unlimited pagination
- Credentials now loaded via `get_credentials()` with env var → keychain fallback

### Fixed

- `docker-compose.yml`: removed obsolete `version` attribute, fixed healthcheck variables
- `Makefile`: fixed `verify` command env vars, `test` now runs locally

### Removed

- `QUICKSTART.md` (redundant with README.md)
- `env.example` (duplicate of `.env.example`)
- `docker-compose.dev.yml` and `docker-compose.prod.yml` (single file sufficient)
- `docs/DOCKER_COMPOSE_GUIDE.md`, `docs/MIGRATION_GUIDE.md`, `docs/PLATFORM_COMPATIBILITY.md`

---

## [1.3.0] - 2025-11-14

### Added

- Comment resolution status support for pull request comments
- New `unresolved_only` filter parameter for `get_pull_request_comments` tool
- Comment resolution statistics in `get_pull_request` tool via new `comment_stats` object
- Fields: `is_resolved`, `resolved_by`, `resolved_on` in comment objects for tracking resolution status and timestamps
- Enhanced `get_pull_request_activity` with comment resolution data

### Technical Details

**New comment response fields**:
```json
{
  "id": 123,
  "content": "Great improvement!",
  "is_resolved": true,
  "resolved_by": {"display_name": "Jane Reviewer"},
  "resolved_on": "2025-11-14T10:30:00.000000+00:00"
}
```

**New comment_stats in PR response**:
```json
{
  "comment_stats": {
    "total": 15,
    "resolved": 10,
    "unresolved": 5
  }
}
```

**Benefits**:
- Track comment thread resolution status
- Filter for unresolved comments to focus on actionable feedback
- Monitor PR review progress with comment statistics
- Improved comment management in code review workflows

---

## [1.2.0] - 2025-11-05

### 🎉 New Features

#### Tool Configuration System
- **`configs/tools.json`** - Centralized configuration file to enable/disable individual MCP tools
- **`conditional_tool()` decorator** - Smart decorator that respects tool configuration
- **Dynamic tool registration** - Tools are only registered if enabled in configuration
- **Category organization** - Tools grouped by domain (repositories, pull_requests, pipelines)

**Configuration example**:
```json
{
  "tools": {
    "pull_requests": {
      "update_pull_request": {
        "enabled": false,
        "description": "Update a pull request"
      }
    }
  }
}
```

**Benefits**:
- Customize available tools per deployment
- Reduce attack surface by disabling unused tools
- Easy maintenance and auditing
- No code changes required - just edit JSON file

#### Structured Output Format
- **`structured_output=True`** - Enabled by default in FastMCP tool decorator
- **`Dict[str, Any]` return types** - Proper type hints for structured responses
- **Dual response format** - Both human-readable text and machine-parseable JSON
- **Direct object access** - No need to parse JSON strings

**Response structure**:
```json
{
  "content": [{"type": "text", "text": "..."}],
  "structuredContent": {
    "result": {
      "id": 31,
      "title": "feat: new feature",
      "state": "OPEN"
    }
  }
}
```

**Benefits**:
- Better IDE autocomplete support
- Type-safe response handling
- Easier client integration
- Backward compatible with text format

### 🔧 Technical Changes

- Changed all tool return types from `dict` to `Dict[str, Any]`
- Added `configs/` directory to Dockerfile COPY instructions
- Implemented `load_tools_config()` function for configuration loading
- Added `is_tool_enabled()` helper function
- Enhanced `conditional_tool()` decorator with `structured_output` parameter

### 📚 Documentation

- Updated README with Tool Configuration section
- Added Response Format section with examples
- Updated features list in README
- Added comprehensive code examples

### 🧪 Testing

- New test file: `tests/test_structured_output.py` (4 tests)
- All tests passing: 15/15 unit tests
- Manual MCP server validation completed
- Response format verified with real Bitbucket API

### 📦 Container

- Container now includes `configs/` folder
- Configuration loaded at startup
- Logs show enabled/disabled tool count
- Backward compatible - all tools enabled by default if config missing

---

## [1.1.0] - 2025-10-31

### 🎉 New Features

#### API Client
- **`get_pull_request_statuses()`** - Retrieves CI/CD build statuses (Jenkins, tests)
- **`get_pull_request_diffstat()`** - Retrieves file modification statistics

#### MCP Tools
- **`get_pull_request_statuses`** - MCP tool to get build statuses
- **`get_pull_request_diffstat`** - MCP tool to get diff statistics

### 📊 Technical Details

#### get_pull_request_statuses
Retrieves build/CI statuses associated with a pull request.

**Endpoint**: `/repositories/{workspace}/{repo}/pullrequests/{id}/statuses`

**Returns**:
- `state`: SUCCESSFUL, FAILED, INPROGRESS, STOPPED
- `key`: Unique build identifier
- `name`: Build name/description
- `url`: Link to build details
- `created_on`: Status timestamp

**Response example**:
```json
{
  "values": [
    {
      "state": "SUCCESSFUL",
      "name": "Jenkins » my-api » feature/branch #5",
      "url": "https://jenkins...",
      "description": "This commit looks good."
    }
  ]
}
```

#### get_pull_request_diffstat
Retrieves modification statistics for each PR file.

**Endpoint**: Dynamically uses the URL from PR's `links.diffstat.href`

**Returns**:
- `status`: modified, added, removed, renamed
- `lines_added`: Number of lines added
- `lines_removed`: Number of lines removed
- `new.path`: File path after modifications

**Response example**:
```json
{
  "values": [
    {
      "status": "modified",
      "new": {"path": "src/repositories/users/userRepositoryV2Impl.ts"},
      "lines_added": 56,
      "lines_removed": 28
    }
  ]
}
```

### ✅ Tests

- Unit tests added to verify new methods presence
- Integration tests validated on real PR #873
- 11/11 tests passing successfully

### 📈 Validation on PR #873

**get_pull_request_statuses**:
- ✅ 1 Jenkins status found
- State: SUCCESSFUL
- Build #5 on feature branch

**get_pull_request_diffstat**:
- ✅ 5 files modified
- Total: +102 lines, -74 lines
- TypeScript files and tests affected

### 🔧 Changes

#### Modified files:
1. `src/client.py` - Added 2 new methods (+81 lines)
2. `src/server.py` - Added 2 new MCP tools (+54 lines)
3. `README.md` - Documentation of new features
4. `tests/test_client.py` - Methods presence test
5. `tests/test_server.py` - Tools registration test

### 📦 Deployment

Container rebuilt and redeployed successfully:
- Image: `bitbucket-mcp-py:latest`
- Build ID: `de10583516b7`
- Container: `f1cadb56342a`

---

## [1.0.0] - 2025-10-31

### Initial Version

- Correct Basic Auth authentication
- 20+ initial MCP tools
- Podman container support
- Complete unit tests
- Comprehensive documentation
