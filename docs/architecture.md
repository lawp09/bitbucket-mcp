# Architecture & Design

## Authentication

- **Method**: Basic Auth (`Authorization: Basic base64(email:token)`)
- **API Base**: `https://api.bitbucket.org/2.0`
- **Credentials**: Environment variables or system keychain (see [Credentials Configuration](../CLAUDE.md#credentials-configuration) in CLAUDE.md)

## Response Transformation

All tool responses pass through transformers (`src/utils/transformers.py`) that strip unnecessary Bitbucket API fields (links, avatars, nested metadata) to reduce LLM token usage. Each entity type has a dedicated `slim_*` function.

**Benefits**:
- Reduces token usage on typical API responses
- Consistent response shape across all tools
- Sensitive fields automatically masked (e.g., deployment variables)

## Pagination

All list-returning tools support flexible pagination:
- `page_size` / `limit`: Items per page (tool-specific defaults 10-30)
- `max_pages`: Max pages to fetch (default: 1)
- `max_items`: Max total items (default: None)

See [Pagination](./pagination.md) for details.

## Tool Configuration

Tools can be individually enabled or disabled via `configs/tools.json`. See [Tool Configuration](./tools-configuration.md) for details.

## Stateless HTTP Mode

For serverless / horizontal-scaling deployments, use `--stateless` with `--transport http`:
- No `Mcp-Session-Id` header
- One transport per request
- `json_response=True` (no streaming)
- Hard pagination cap to prevent timeout (default: 10 pages)

See [Pagination](./pagination.md) for the hard cap configuration.

## API Quirks & Gotchas

The client handles several Bitbucket API quirks automatically:

**Trailing slashes** (returns 404 if wrong):
- `/branch-restrictions/` — requires trailing slash
- `/environments/` — requires trailing slash
- `/deployments/` — requires trailing slash
- Most other endpoints — no trailing slash

**Field naming inconsistencies**:
- Caches: `pipelines-config` (hyphen)
- Variables/Schedules: `pipelines_config` (underscore)

**User identification**:
- User IDs are `account_id`/`uuid` (GDPR 2019, usernames removed from API URLs)
- Workspace membership endpoints return objects without `permission` field — roles live on the separate `/permissions` endpoint

**Log endpoint specifics**:
- Returns `application/octet-stream`, not JSON
- Completed logs `307` redirect to long-term storage
- Response is streamed with a 50 MiB ceiling
- `Range` header supported for size bounding (default: trailing 100 KiB)

## Transport Modes

- **`stdio`** (default): Best for direct Claude Code integration
- **`streamable-http`**: HTTP transport for server deployments (MCP spec 2025-03-26)
- **`sse`** (legacy): Deprecated in favour of `streamable-http`

See `--help` for transport options.
