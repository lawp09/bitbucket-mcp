# Changelog - Bitbucket MCP Server Python

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
