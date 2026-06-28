# Changelog - Bitbucket MCP Server Python

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
