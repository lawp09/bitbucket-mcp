# Pagination

All list-returning tools support pagination parameters.

## Configuration

- **`page_size` / `limit`**: Items per page (default: 10-30, tool-specific)
- **`max_pages`**: Maximum number of pages to fetch (default: 1, `None` for unlimited)
- **`max_items`**: Maximum total number of items (default: None)

## Warnings

Warnings are logged if:
- `max_pages > 10` — large page counts may indicate a missing filter
- `max_items > 300` — very large result sets can exceed token limits

## Stateless Mode (HTTP Serverless)

In stateless HTTP mode (`--stateless`), a hard cap applies:

**`BITBUCKET_MAX_PAGES_HARD_CAP`** (default: 10)

With `json_response=True`, nothing is emitted until the walk completes, so unbounded pagination can outlive proxy idle timeouts or edge function duration limits. Beyond the cap, the response carries `truncated: true` (distinct from `has_more`, which means "there is a next page").

**Never silent truncation** — the caller always knows if results were capped.
