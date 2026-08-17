"""Bitbucket API Client with Basic Authentication"""

import base64
import logging
import re
import urllib.parse
from typing import Any, Dict, Optional, Protocol
import httpx

from .utils.pagination import PaginationConfig, aggregate_pages

logger = logging.getLogger(__name__)


# Default size ceiling for get_file_content (256 KiB). Larger files blow up the
# LLM token budget and are better fetched via git; callers can raise it explicitly.
# Public so the server layer reuses the same default instead of duplicating the literal.
DEFAULT_MAX_FILE_BYTES = 256 * 1024

# Trailing slice of a pipeline step log returned by default (100 KiB). Raw logs run
# to many MB on long steps and the tail is where failures live; callers wanting more
# pass an explicit start/end window or max_bytes=None.
DEFAULT_MAX_LOG_BYTES = 100 * 1024

# Hard ceiling on the number of bytes pulled off the wire for a single log request,
# whatever the Range outcome. Guards the case where the long-term-storage host
# ignores Range and streams a multi-GB log at us.
MAX_LOG_STREAM_BYTES = 50 * 1024 * 1024

# `bytes 0-99/2048`, `bytes 0-99/*` and the 416 form `bytes */2048`.
_CONTENT_RANGE_RE = re.compile(
    r"^\s*bytes\s+(?:(\d+)-(\d+)|\*)/(\d+|\*)\s*$", re.IGNORECASE
)

# Mimetypes refused by get_file_content: returning their bytes as text would yield
# mojibake and a huge useless payload. Kept deliberately narrow so source files
# with unusual mimetypes (or a null mimetype) are still served.
_BINARY_MIMETYPE_PREFIXES = ("image/", "audio/", "video/", "font/")
_BINARY_MIMETYPES = frozenset({
    "application/octet-stream",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/x-bzip2",
    "application/pdf",
    "application/java-archive",
    "application/x-executable",
    "application/x-sharedlib",
    "application/wasm",
})


def _is_binary_mimetype(mimetype: Optional[str]) -> bool:
    """Return True for mimetypes that should not be returned as text.

    A missing/empty mimetype returns False (Bitbucket reports null for many plain
    source files) so the size guard remains the primary protection.
    """
    if not mimetype:
        return False
    mt = mimetype.lower().split(";")[0].strip()
    return mt in _BINARY_MIMETYPES or mt.startswith(_BINARY_MIMETYPE_PREFIXES)


def _parse_content_range(
    header: Optional[str],
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Parse a ``Content-Range`` header into ``(start, end, total)``.

    Every component degrades to ``None`` rather than raising: RFC 7233 allows an
    unknown total (``bytes 0-99/*``) and a redirected storage host may omit or
    malform the header entirely. A crash here would break the very call this
    parsing is meant to make usable.
    """
    if not header:
        return None, None, None
    match = _CONTENT_RANGE_RE.match(header)
    if not match:
        return None, None, None
    raw_start, raw_end, raw_total = match.groups()
    return (
        int(raw_start) if raw_start is not None else None,
        int(raw_end) if raw_end is not None else None,
        int(raw_total) if raw_total != "*" else None,
    )


def _build_log_range(
    start: Optional[int], end: Optional[int], max_bytes: Optional[int]
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """Validate the log window and build its ``Range`` header.

    Returns ``(header, effective_start, effective_end)``. ``header`` is None when
    the caller asked for the whole log (no window, no cap).

    Raises:
        ValueError: On a non-integer or negative bound, an inverted window, or a
            non-positive ``max_bytes`` — caught locally so the caller gets a clear
            message instead of an opaque 400/416 from Bitbucket.
    """
    for name, value in (("start", start), ("end", end), ("max_bytes", max_bytes)):
        # bool is an int subclass; True/False as a byte offset is always a mistake.
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError(f"{name} must be an integer or None, got {value!r}")
        if name != "max_bytes" and value is not None and value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")
    if max_bytes is not None and max_bytes <= 0:
        raise ValueError(f"max_bytes must be a positive integer or None, got {max_bytes}")

    if start is not None or end is not None:
        eff_start = start if start is not None else 0
        if end is not None and end < eff_start:
            raise ValueError(f"end ({end}) must be >= start ({eff_start}).")
        header = f"bytes={eff_start}-{end}" if end is not None else f"bytes={eff_start}-"
        return header, eff_start, end
    if max_bytes is not None:
        return f"bytes=-{max_bytes}", None, None
    return None, None, None


async def _read_capped_stream(
    response: httpx.Response,
    *,
    reconstruct: Optional[str],
    ranged: bool,
    start: Optional[int],
    end: Optional[int],
    tail_bytes: Optional[int],
) -> tuple[bytes, int, bool]:
    """Read a streamed body without ever holding more than the wanted window.

    ``reconstruct`` is truthy only when a ``Range`` was requested and the server
    answered 200 anyway — the window then has to be carved out of the full stream
    client-side. Otherwise the body already *is* the window and is passed through.
    ``ranged`` says whether a ``Range`` header was sent at all; it only shapes the
    ceiling error message.

    Returns ``(payload, bytes_consumed, read_to_eof)``. ``read_to_eof`` is False
    only when bytes were left unread — a window whose ``end`` falls exactly on the
    last byte still counts as a complete read, so the caller does not report a
    truncation that did not happen.

    Raises:
        ValueError: If more than ``MAX_LOG_STREAM_BYTES`` come off the wire.
    """
    # An explicit window is carved out by offset; otherwise keep a rolling tail.
    carve = bool(reconstruct) and (start is not None or end is not None)
    tail_limit = tail_bytes if (reconstruct and not carve) else None
    buffer = bytearray()
    consumed = 0
    read_to_eof = True

    stream = response.aiter_bytes()
    async for chunk in stream:
        chunk_offset = consumed
        consumed += len(chunk)
        if consumed > MAX_LOG_STREAM_BYTES:
            # Blame the right party: the caller's window is only at fault when the
            # server actually served the range it was given.
            if reconstruct:
                cause = "and the server did not honour the requested range"
            elif ranged:
                cause = "for the range that was served"
            else:
                cause = "and no range was requested"
            raise ValueError(
                f"Log exceeds the {MAX_LOG_STREAM_BYTES}-byte streaming ceiling "
                f"{cause}; narrow the window with the start/end parameters."
            )
        if carve:
            lo = max(0, (start if start is not None else 0) - chunk_offset)
            hi = len(chunk) if end is None else min(len(chunk), end + 1 - chunk_offset)
            if hi > lo:
                buffer += chunk[lo:hi]
            if end is not None and consumed > end:
                # Window complete: stop pulling. Exiting the `async with` in the
                # caller releases the connection instead of leaking it.
                # Peek one chunk first, so an `end` landing exactly on the last
                # byte reads as a complete log rather than a spurious "there's more".
                async for extra in stream:
                    if extra:
                        # Deliberately exempt from the ceiling: this is a single
                        # transport read past a window we already hold in full, and
                        # aborting here would discard a correct result.
                        consumed += len(extra)
                        read_to_eof = False
                        break
                break
        else:
            buffer += chunk
            if tail_limit is not None and len(buffer) > tail_limit:
                del buffer[: len(buffer) - tail_limit]

    return bytes(buffer), consumed, read_to_eof


class AuthorizationError(Exception):
    """Raised when a call cannot be authorized for the current caller.

    Covers three distinct situations, all of which must surface to the MCP layer as a
    clear, structured error rather than a raw HTTP failure:

    - multi-tenant mode is active but the request carries no verified Bitbucket identity;
    - the caller's identity resolves to no default workspace and none was passed;
    - Bitbucket answered 401/403 for a bearer-authenticated (multi-tenant) call.

    The message never contains a token: only the account id, the workspace and the HTTP
    status. Mirrors the ``IssueTrackerDisabledError`` convention (typed exception ->
    structured response) already used by the server layer.
    """

    def __init__(
        self,
        message: str,
        *,
        account_id: Optional[str] = None,
        workspace: Optional[str] = None,
        status_code: Optional[int] = None,
    ):
        self.account_id = account_id
        self.workspace = workspace
        self.status_code = status_code
        super().__init__(message)


async def _raise_authorization_error(response: httpx.Response) -> None:
    """httpx response hook: turn a 401/403 into a typed :class:`AuthorizationError`.

    Installed on bearer (multi-tenant) clients only. The message carries the method, the
    path and the status — never the ``Authorization`` header, and never the token.
    """
    if response.status_code not in (401, 403):
        return
    request = response.request
    raise AuthorizationError(
        f"Bitbucket refused the request ({response.status_code}) for "
        f"{request.method} {request.url.path}. The caller's token is missing the "
        f"required scope, or is expired or revoked.",
        status_code=response.status_code,
    )


class IssueTrackerDisabledError(Exception):
    """Raised when an issue endpoint returns 404 because the repository's issue
    tracker is disabled.

    The Bitbucket issue tracker is opt-in per repository; calls to issue endpoints
    on a repository without one return a 404. This typed exception lets the server
    layer surface a clear, structured error instead of a raw HTTP failure.
    """

    def __init__(self, workspace: str, repo_slug: str):
        self.workspace = workspace
        self.repo_slug = repo_slug
        super().__init__(
            f"Issue tracker is disabled for repository '{workspace}/{repo_slug}'."
        )


# Observed disabled-tracker body: {"error": {"message": "Repository has no issue tracker."}}.
# Substring match keeps it resilient to minor wording changes around "no issue tracker".
_TRACKER_DISABLED_MARKER = "no issue tracker"


def _is_tracker_disabled_response(response: httpx.Response) -> bool:
    """Return True if a 404 response indicates the issue tracker is disabled.

    Distinguishes a "tracker disabled" 404 (e.g. "Repository has no issue tracker.")
    from a regular "issue not found" 404 by inspecting the error message in the body.
    A not-found 404 is left to propagate as a normal HTTP error.
    """
    if response.status_code != 404:
        return False
    try:
        message = response.json().get("error", {}).get("message", "")
    except Exception:
        message = response.text
    return _TRACKER_DISABLED_MARKER in (message or "").lower()


def _raise_if_tracker_disabled(
    response: httpx.Response, workspace: str, repo_slug: str
) -> None:
    """Raise IssueTrackerDisabledError if the response is a tracker-disabled 404.

    Shared guard for the direct (non-paginated) issue endpoints so the detection
    stays in one place and cannot be forgotten on a new method.
    """
    if _is_tracker_disabled_response(response):
        raise IssueTrackerDisabledError(workspace, repo_slug)


def _bbql_quote(value: str) -> str:
    """Escape and wrap a string value for a BBQL query."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_issue_query(
    state: Optional[str] = None,
    kind: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    q: Optional[str] = None,
) -> Optional[str]:
    """Combine dedicated filters and a raw BBQL query into a single BBQL string.

    Dedicated filters and the raw query are joined with AND; the raw query is
    wrapped in parentheses to preserve operator precedence.

    Example:
        _build_issue_query(state="open", kind="bug")
        -> 'state = "open" AND kind = "bug"'

    Returns:
        The combined BBQL query string, or None when no filter is provided.
    """
    clauses = []
    if state:
        clauses.append(f"state = {_bbql_quote(state)}")
    if kind:
        clauses.append(f"kind = {_bbql_quote(kind)}")
    if priority:
        clauses.append(f"priority = {_bbql_quote(priority)}")
    if assignee:
        clauses.append(f"assignee.uuid = {_bbql_quote(assignee)}")
    if q:
        clauses.append(f"({q})")
    return " AND ".join(clauses) if clauses else None


class AuthStrategy(Protocol):
    """How a client authenticates against the Bitbucket API.

    Injectable so the same client serves the single-user Basic-Auth deployment and the
    multi-tenant bearer deployment (issue #72) without either knowing about the other.
    """

    scheme: str

    def header(self) -> str:
        """Return the full value of the ``Authorization`` header."""
        ...  # pragma: no cover - Protocol stub


class BasicAuthStrategy:
    """``Authorization: Basic base64(email:token)`` — the historical scheme.

    Uses an Atlassian API token bound to the process, resolved once at startup from the
    environment or the system keychain.
    """

    scheme = "Basic"

    def __init__(self, email: str, token: str):
        self._email = email
        self._token = token

    def header(self) -> str:
        auth_b64 = base64.b64encode(f"{self._email}:{self._token}".encode("utf-8")).decode("utf-8")
        return f"Basic {auth_b64}"

    def __repr__(self) -> str:
        """Never render the credentials — this object is reachable from tracebacks."""
        return "BasicAuthStrategy(email=<redacted>, token=<redacted>)"


class BearerAuthStrategy:
    """``Authorization: Bearer <token>`` — a Bitbucket OAuth 2.0 access token.

    Used in multi-tenant HTTP mode: the token presented by the MCP client *is* the
    caller's Bitbucket credential, reused as-is so the server never stores or maps
    credentials of its own.
    """

    scheme = "Bearer"

    def __init__(self, token: str):
        self._token = token

    def header(self) -> str:
        return f"Bearer {self._token}"

    def __repr__(self) -> str:
        """Never render the token — this object is reachable from tracebacks."""
        return "BearerAuthStrategy(token=<redacted>)"


class BitbucketClient:
    """Async HTTP client for Bitbucket API 2.0.

    Authenticates through an injectable :class:`AuthStrategy`: Basic Auth by default
    (single-user deployments), Bearer via :meth:`from_bearer` (multi-tenant HTTP).
    """

    def __init__(self, email: str, token: str, workspace: str):
        """
        Initialize Bitbucket client with Basic Auth.

        Public constructor, kept signature-compatible on purpose: it is part of the
        package's public surface and is used throughout ``tests/``.

        Args:
            email: Bitbucket account email
            token: Bitbucket API token
            workspace: Bitbucket workspace name
        """
        self._init_common(BasicAuthStrategy(email, token), workspace)

    @classmethod
    def from_bearer(
        cls,
        token: str,
        workspace: Optional[str],
        *,
        account_id: Optional[str] = None,
    ) -> "BitbucketClient":
        """Build a client authenticating with a Bitbucket OAuth bearer token.

        Args:
            token: Bitbucket access token, used as-is as the bearer credential.
            workspace: Default workspace for this identity. May be ``None`` when the
                identity has zero or several workspace memberships — every call must
                then pass ``workspace`` explicitly (see :meth:`_resolve_workspace`).
            account_id: Bitbucket account id of the caller, for logs and errors. Never
                a credential.

        Returns:
            A client whose 401/403 responses surface as :class:`AuthorizationError`.
        """
        client = cls.__new__(cls)
        client._init_common(BearerAuthStrategy(token), workspace, account_id=account_id)
        return client

    def _init_common(
        self,
        auth: AuthStrategy,
        workspace: Optional[str],
        *,
        account_id: Optional[str] = None,
    ) -> None:
        """Shared construction path for both auth schemes."""
        self.workspace = workspace
        self.account_id = account_id
        self.auth_scheme = auth.scheme
        self.base_url = "https://api.bitbucket.org/2.0"

        # Lifecycle bookkeeping used by the server's bounded per-identity client cache
        # (issue #72): a client evicted from the LRU while a request is still using it
        # must not be closed under that request's feet.
        self._inflight = 0
        self._retired = False
        self._closed = False

        # 401/403 -> AuthorizationError, but only for bearer clients: in single-user
        # Basic-Auth mode a 403 is a legitimate, documented outcome for some endpoints
        # (e.g. get_pipeline_config without admin:repository) and callers already handle
        # it as an httpx.HTTPStatusError. Multi-tenant mode has no such history.
        event_hooks = {"response": [_raise_authorization_error]} if auth.scheme == "Bearer" else {}

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": auth.header(),
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            timeout=30.0,
            trust_env=False,  # Disable proxy from environment for testing
            event_hooks=event_hooks,
        )

        logger.info(
            f"Bitbucket client initialized for workspace: {workspace} "
            f"(auth={auth.scheme})"
        )

    def _resolve_workspace(self, workspace: Optional[str]) -> str:
        """Resolve the workspace for a call: explicit argument, else this client's default.

        In multi-tenant mode ``self.workspace`` is the *caller's* workspace, never the
        process one — the per-identity client is what makes ``workspace=None`` safe. When
        the identity resolves to no default workspace (zero or several memberships), fail
        loudly here rather than building a ``/repositories/None/...`` URL.
        """
        ws = workspace or self.workspace
        if not ws:
            raise AuthorizationError(
                "No default workspace for this identity: pass `workspace` explicitly.",
                account_id=self.account_id,
            )
        return ws

    async def close(self):
        """Close the HTTP client. Idempotent — safe to call from several cleanup paths."""
        if self._closed:
            return
        self._closed = True
        await self.client.aclose()

    def __repr__(self) -> str:
        """Protected repr to avoid credential leaks in logs/debug."""
        return (
            f"BitbucketClient(workspace={self.workspace!r}, auth={self.auth_scheme!r}, "
            f"account_id={self.account_id!r})"
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        _ = exc_type, exc_val, exc_tb  # Unused but required for protocol
        await self.close()

    # ========== Authentication Test ==========

    async def get_user(self) -> Dict[str, Any]:
        """
        Get authenticated user details (test authentication).

        Returns:
            User information dictionary

        Raises:
            httpx.HTTPStatusError: If authentication fails
        """
        response = await self.client.get("/user")
        response.raise_for_status()
        return response.json()

    # ========== Repositories ==========

    async def list_repositories(
        self,
        workspace: Optional[str] = None,
        name: Optional[str] = None,
        limit: int = 30,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        List repositories in workspace with pagination support.

        Args:
            workspace: Workspace name (defaults to self.workspace)
            name: Filter by repository name (partial match)
            limit: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of repositories with aggregated values
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=limit, max_pages=max_pages)
        params = {}
        if name:
            params["q"] = f'name~"{name}"'

        return await aggregate_pages(self.client, f"/repositories/{ws}", params, config)

    async def get_repository(
        self,
        repo_slug: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get repository details.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Repository information
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(f"/repositories/{ws}/{repo_slug}")
        response.raise_for_status()
        return response.json()

    async def get_repository_tags(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        List repository tags ordered by most recent target date.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of repository tags with aggregated values
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        params = {"sort": "-target.date"}

        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/refs/tags",
            params,
            config
        )

    # ========== Pull Requests ==========

    async def get_pull_requests(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        state: str = "OPEN",
        limit: int = 30,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        List pull requests for a repository with pagination support.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            state: PR state (OPEN, MERGED, DECLINED, SUPERSEDED)
            limit: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of pull requests with aggregated values
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=limit, max_pages=max_pages)
        params = {"state": state}

        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests",
            params,
            config
        )

    async def get_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get detailed information about a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Pull request details
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}"
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _normalize_reviewers(reviewers: list) -> list:
        """Normalize reviewers to [{"uuid": "..."}] format, accepting both strings and dicts."""
        return [r if isinstance(r, dict) else {"uuid": r} for r in reviewers]

    async def create_pull_request(
        self,
        repo_slug: str,
        title: str,
        description: str,
        source_branch: str,
        target_branch: str,
        workspace: Optional[str] = None,
        reviewers: Optional[list] = None,
        draft: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new pull request.

        Args:
            repo_slug: Repository slug
            title: PR title
            description: PR description
            source_branch: Source branch name
            target_branch: Target branch name
            workspace: Workspace name (defaults to self.workspace)
            reviewers: List of reviewer usernames
            draft: Whether to create as draft PR

        Returns:
            Created pull request details
        """
        ws = self._resolve_workspace(workspace)

        payload: Dict[str, Any] = {
            "title": title,
            "description": description,
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": target_branch}}
        }

        if reviewers is not None:
            payload["reviewers"] = self._normalize_reviewers(reviewers)

        if draft:
            payload["draft"] = True

        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def update_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        reviewers: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Update a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            title: New title
            description: New description
            reviewers: List of reviewer UUIDs (optional)

        Returns:
            Updated pull request details
        """
        ws = self._resolve_workspace(workspace)

        payload = {}
        if title:
            payload["title"] = title
        if description:
            payload["description"] = description
        if reviewers is not None:
            payload["reviewers"] = self._normalize_reviewers(reviewers)

        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def approve_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Approve a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Approval details
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/approve",
            json={}  # Body vide requis par l'API Bitbucket
        )
        response.raise_for_status()
        return response.json()

    async def unapprove_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Remove approval from a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/approve"
        )
        response.raise_for_status()

    async def request_changes_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Request changes on a pull request (sets status to 'needs work').

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Participant details with updated state
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/request-changes",
            json={}
        )
        response.raise_for_status()
        return response.json()

    async def unrequest_changes_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Remove 'request changes' status from a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/request-changes"
        )
        response.raise_for_status()

    async def decline_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Decline a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            message: Optional reason for declining

        Returns:
            Updated pull request details
        """
        ws = self._resolve_workspace(workspace)

        payload = {}
        if message:
            payload["message"] = message

        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/decline",
            json=payload if payload else None
        )
        response.raise_for_status()
        return response.json()

    async def merge_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        message: Optional[str] = None,
        strategy: str = "merge_commit"
    ) -> Dict[str, Any]:
        """
        Merge a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            message: Merge commit message
            strategy: Merge strategy (merge_commit, squash, fast_forward)

        Returns:
            Merged pull request details
        """
        ws = self._resolve_workspace(workspace)

        payload = {"merge_strategy": strategy}
        if message:
            payload["message"] = message

        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/merge",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    # ========== PR Comments ==========

    async def get_pull_request_comments(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1,
        unresolved_only: bool = False
    ) -> Dict[str, Any]:
        """
        Get all comments on a pull request with pagination support.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)
            unresolved_only: Kept for backward compatibility (filtering is done client-side)

        Returns:
            Comments with aggregated values, including resolution field
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        params = {}

        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments",
            params,
            config
        )

    async def add_pull_request_comment(
        self,
        repo_slug: str,
        pull_request_id: str,
        content: str,
        workspace: Optional[str] = None,
        inline_path: Optional[str] = None,
        inline_from: Optional[int] = None,
        inline_to: Optional[int] = None,
        pending: bool = False,
        parent_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Add a comment to a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            content: Comment content (markdown)
            workspace: Workspace name (defaults to self.workspace)
            inline_path: File path for inline comment
            inline_from: Line number in old version (for deleted/modified lines)
            inline_to: Line number in new version (for added/modified lines)
            pending: Whether to create as pending comment (draft)
            parent_id: Comment ID to reply to (creates a threaded reply)

        Returns:
            Created comment details
        """
        ws = self._resolve_workspace(workspace)

        payload: Dict[str, Any] = {
            "content": {"raw": content}
        }

        if inline_path:
            inline_data: Dict[str, Any] = {"path": inline_path}
            if inline_from:
                inline_data["from"] = inline_from
            if inline_to:
                inline_data["to"] = inline_to
            payload["inline"] = inline_data

        if pending:
            payload["pending"] = True

        if parent_id is not None:
            payload["parent"] = {"id": parent_id}

        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def get_pull_request_comment(
        self,
        repo_slug: str,
        pull_request_id: str,
        comment_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get a specific comment on a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            comment_id: Comment ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Comment details
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments/{comment_id}"
        )
        response.raise_for_status()
        return response.json()

    async def update_pull_request_comment(
        self,
        repo_slug: str,
        pull_request_id: str,
        comment_id: str,
        content: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update a comment on a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            comment_id: Comment ID
            content: New comment content (markdown)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated comment details
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments/{comment_id}",
            json={"content": {"raw": content}}
        )
        response.raise_for_status()
        return response.json()

    async def delete_pull_request_comment(
        self,
        repo_slug: str,
        pull_request_id: str,
        comment_id: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Delete a comment on a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            comment_id: Comment ID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments/{comment_id}"
        )
        response.raise_for_status()

    async def resolve_pull_request_comment(
        self,
        repo_slug: str,
        pull_request_id: str,
        comment_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Resolve a comment on a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            comment_id: Comment ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Resolution details
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments/{comment_id}/resolve",
            json={}
        )
        response.raise_for_status()
        return response.json()

    async def reopen_pull_request_comment(
        self,
        repo_slug: str,
        pull_request_id: str,
        comment_id: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Reopen (unresolve) a comment on a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            comment_id: Comment ID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments/{comment_id}/resolve"
        )
        response.raise_for_status()

    # ========== PR Tasks ==========

    async def get_pull_request_tasks(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get tasks on a pull request with pagination support.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of tasks
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/tasks",
            {},
            config
        )

    async def get_pull_request_task(
        self,
        repo_slug: str,
        pull_request_id: str,
        task_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get a specific pull request task.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            task_id: Task ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Task object from Bitbucket API
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/tasks/{task_id}"
        )
        response.raise_for_status()
        return response.json()

    async def create_pull_request_task(
        self,
        repo_slug: str,
        pull_request_id: str,
        content: str,
        comment_id: Optional[int] = None,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a task on a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            content: Task content (markdown)
            comment_id: Optional comment ID to link the task to a specific comment
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Created task object
        """
        ws = self._resolve_workspace(workspace)
        payload = {
            "content": {"raw": content},
            "state": "UNRESOLVED"
        }
        if comment_id is not None:
            payload["comment"] = {"id": comment_id}
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/tasks",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def update_pull_request_task(
        self,
        repo_slug: str,
        pull_request_id: str,
        task_id: str,
        content: Optional[str] = None,
        state: Optional[str] = None,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update a pull request task.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            task_id: Task ID
            content: New task content (markdown)
            state: New task state (UNRESOLVED or RESOLVED)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated task object
        """
        ws = self._resolve_workspace(workspace)
        payload: Dict[str, Any] = {}
        if content is not None:
            payload["content"] = {"raw": content}
        if state is not None:
            payload["state"] = state
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/tasks/{task_id}",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def delete_pull_request_task(
        self,
        repo_slug: str,
        pull_request_id: str,
        task_id: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Delete a pull request task.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            task_id: Task ID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/tasks/{task_id}"
        )
        response.raise_for_status()

    # ========== PR Patch ==========

    async def get_pull_request_patch(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get the patch for a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Dictionary with patch content as string
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/patch",
            follow_redirects=True
        )
        response.raise_for_status()
        return {"patch": response.text}

    # ========== PR Discovery ==========

    async def get_pull_requests_pending_review(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 30,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get open pull requests where the current user is a reviewer.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of pull requests pending review
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        params = {"state": "OPEN", "role": "REVIEWER"}
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests",
            params,
            config
        )

    async def get_pull_request_diff(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        path: Optional[str] = None
    ) -> str:
        """
        Get the unified diff for a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            path: Filter diff to a specific file path (optional)

        Returns:
            Unified diff as string
        """
        ws = self._resolve_workspace(workspace)
        params = {}
        if path:
            params["path"] = path
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/diff",
            params=params,
            follow_redirects=True
        )
        response.raise_for_status()
        return response.text

    async def get_pull_request_activity(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get activity log for a pull request with pagination support.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Activity log with aggregated values. Comment objects include the resolution field
            showing resolution status (null for unresolved comments, or resolution object with user and timestamp).
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/activity",
            {},
            config
        )

    async def get_pull_request_comment_stats(
        self,
        workspace: str,
        repo_slug: str,
        pull_request_id: int
    ) -> Dict[str, Any]:
        """
        Get comment statistics for a pull request.

        Args:
            workspace: Workspace name
            repo_slug: Repository slug
            pull_request_id: Pull request ID

        Returns:
            Dictionary with comment statistics:
            - total: Total number of comments
            - resolved: Number of resolved comments
            - unresolved: Number of unresolved comments
        """
        comments_response = await self.get_pull_request_comments(
            repo_slug=repo_slug,
            pull_request_id=str(pull_request_id),
            workspace=workspace,
            page_size=50,
            max_pages=None
        )

        comments = comments_response.get("values", [])
        total = len(comments)
        resolved = sum(1 for comment in comments if comment.get("resolution") is not None)
        unresolved = total - resolved

        return {
            "total": total,
            "resolved": resolved,
            "unresolved": unresolved
        }

    async def get_pull_request_commits(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get commits on a pull request with pagination support.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Commits with aggregated values
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/commits",
            {},
            config
        )

    # ========== Pipelines ==========

    async def list_pipeline_runs(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        status: Optional[str] = None,
        target_branch: Optional[str] = None,
        limit: int = 30,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        List pipeline runs for a repository with pagination support.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            status: Filter by status (PENDING, IN_PROGRESS, SUCCESSFUL, FAILED, etc.)
            target_branch: Filter by target branch
            limit: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            List of pipeline runs with aggregated values
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=limit, max_pages=max_pages)
        params = {}

        if status:
            params["status"] = status
        if target_branch:
            params["target.branch"] = target_branch

        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pipelines/",
            params,
            config
        )

    async def get_pipeline_run(
        self,
        repo_slug: str,
        pipeline_uuid: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get details for a specific pipeline run.

        Args:
            repo_slug: Repository slug
            pipeline_uuid: Pipeline UUID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Pipeline run details
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pipelines/{pipeline_uuid}"
        )
        response.raise_for_status()
        return response.json()

    async def get_pipeline_steps(
        self,
        repo_slug: str,
        pipeline_uuid: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        List steps for a pipeline run with pagination support.

        Args:
            repo_slug: Repository slug
            pipeline_uuid: Pipeline UUID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Pipeline steps with aggregated values
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pipelines/{pipeline_uuid}/steps/",
            {},
            config
        )

    async def get_pipeline_step_logs(
        self,
        repo_slug: str,
        pipeline_uuid: str,
        step_uuid: str,
        workspace: Optional[str] = None,
        log_uuid: Optional[str] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        max_bytes: Optional[int] = DEFAULT_MAX_LOG_BYTES,
    ) -> Dict[str, Any]:
        """
        Get logs for a specific pipeline step.

        This is the only Bitbucket endpoint in this client that does NOT return
        JSON: it declares ``produces: [application/octet-stream]``, so the
        client-wide ``Accept: application/json`` header must be overridden per
        request (it answers 406 otherwise). It also answers 307 once the step is
        complete — the log is moved to long-term storage — hence
        ``follow_redirects=True``. httpx strips the ``Authorization`` header on
        that cross-origin hop by itself, which is what we want: the redirect
        target is pre-signed and must not receive Bitbucket credentials.

        Raw logs are routinely multi-MB, so the response is bounded: by default
        only the last ``max_bytes`` are returned (HTTP suffix ``Range``). The body
        is streamed and never buffered whole, so an unbounded log cannot exhaust
        memory even when the storage host ignores ``Range`` and replies 200.

        Args:
            repo_slug: Repository slug
            pipeline_uuid: Pipeline UUID, e.g. ``{adab6a1f-...}``. Unlike
                ``get_pipeline_run``, this endpoint is not documented to accept a
                build number — resolve the UUID first if you only have a number.
            step_uuid: Step UUID
            workspace: Workspace name (defaults to self.workspace)
            log_uuid: Optional log UUID. Omit for the main build container; pass a
                service container UUID to read that service's log instead.
            start: First byte to return (absolute, inclusive)
            end: Last byte to return (absolute, inclusive). ``start``/``end`` are an
                absolute byte window, NOT a "last N bytes" convention; ``end`` alone
                means "from byte 0". An explicit window is honoured verbatim and is
                never additionally trimmed by ``max_bytes``.
            max_bytes: Size of the trailing slice returned when no explicit
                ``start``/``end`` is given (default: 100 KiB). ``None`` returns the
                whole log, subject to the streaming ceiling.

        Returns:
            Dict with ``content`` (str), ``truncated`` (bool — the content is not
            the whole log), ``returned_bytes`` and ``total_bytes`` (None when the
            server did not disclose it and the body was not read to the end).

        Raises:
            ValueError: On an invalid range, on 416 (requested range not
                satisfiable), or when the log exceeds the streaming ceiling.
        """
        ws = self._resolve_workspace(workspace)
        range_header, eff_start, eff_end = _build_log_range(start, end, max_bytes)

        path = f"/repositories/{ws}/{repo_slug}/pipelines/{pipeline_uuid}/steps/{step_uuid}"
        path += f"/logs/{log_uuid}" if log_uuid else "/log"

        # Accept: */* is the actual fix for the 406; Range rides along in the same
        # per-request dict, leaving the client-wide JSON default untouched.
        headers = {"Accept": "*/*"}
        if range_header:
            headers["Range"] = range_header

        async with self.client.stream(
            "GET", path, headers=headers, follow_redirects=True
        ) as response:
            if response.status_code == httpx.codes.REQUESTED_RANGE_NOT_SATISFIABLE:
                _, _, total = _parse_content_range(response.headers.get("Content-Range"))
                size_hint = f" (log is {total} bytes)" if total is not None else ""
                raise ValueError(
                    f"Requested range {range_header} is not satisfiable{size_hint}."
                )
            if response.status_code >= 400:
                # Read the (small) error body so raise_for_status reports something useful.
                await response.aread()
            response.raise_for_status()

            # 304 is documented by this endpoint but unreachable here: we never send
            # If-None-Match (no caller-side etag store). Were one added, an empty
            # 304 body would need distinguishing from a genuinely empty log.
            cr_start, _, cr_total = _parse_content_range(
                response.headers.get("Content-Range")
            )
            partial = response.status_code == httpx.codes.PARTIAL_CONTENT
            # A 200 means the server ignored our Range: the window has to be
            # reconstructed from the full stream instead of trusted as-is.
            reconstruct = None if partial else range_header
            raw, consumed, read_to_eof = await _read_capped_stream(
                response,
                reconstruct=reconstruct,
                ranged=bool(range_header),
                start=eff_start,
                end=eff_end,
                tail_bytes=max_bytes,
            )

        if cr_total is not None:
            total_bytes = cr_total
        elif partial or not read_to_eof:
            # 206 without a numeric total, or a stream we cut short: the full size
            # is genuinely unknown — do not pass off the bytes read as the total.
            total_bytes = None
        else:
            total_bytes = consumed

        # A 206 whose range starts past byte 0 is partial even if its length
        # happens to match the total (defensive: servers do disagree here).
        truncated = (
            total_bytes is None or len(raw) < total_bytes or bool(cr_start)
        )
        return {
            "content": raw.decode(response.encoding or "utf-8", errors="replace"),
            "truncated": truncated,
            "returned_bytes": len(raw),
            "total_bytes": total_bytes,
        }

    # ========== Pull Request Build Statuses ==========

    async def get_pull_request_statuses(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get build/CI statuses for a pull request with pagination support.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Build statuses with aggregated values
            Each status contains:
            - state: SUCCESSFUL, FAILED, INPROGRESS, STOPPED
            - key: Unique identifier for the build
            - name: Build name/description
            - url: Link to the build details
            - created_on: Timestamp of the status
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/statuses",
            {},
            config
        )

    # ========== Commit Build Statuses ==========

    async def get_commit_statuses(
        self,
        repo_slug: str,
        commit_hash: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get build/CI statuses for a specific commit with pagination support.

        Args:
            repo_slug: Repository slug
            commit_hash: Commit hash (full or short)
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Build statuses with aggregated values
            Each status contains:
            - state: SUCCESSFUL, FAILED, INPROGRESS, STOPPED
            - key: Unique identifier for the build
            - name: Build name/description
            - url: Link to the build details
            - created_on: Timestamp of the status
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/commit/{commit_hash}/statuses",
            {},
            config
        )

    async def run_pipeline(
        self,
        repo_slug: str,
        branch: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Trigger a new pipeline run on a branch.

        Args:
            repo_slug: Repository slug
            branch: Branch name to run the pipeline on
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Created pipeline run details
        """
        ws = self._resolve_workspace(workspace)
        payload = {
            "target": {
                "ref_type": "branch",
                "type": "pipeline_ref_target",
                "ref_name": branch
            }
        }
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pipelines/",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def stop_pipeline(
        self,
        repo_slug: str,
        pipeline_uuid: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Stop a running pipeline.

        Args:
            repo_slug: Repository slug
            pipeline_uuid: Pipeline UUID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pipelines/{pipeline_uuid}/stopPipeline",
            json={}
        )
        response.raise_for_status()

    # ========== Pipelines Config (variables, schedules, caches) ==========
    #
    # NOTE on paths: variables and schedules live under "pipelines_config"
    # (underscore), but caches live under "pipelines-config" (HYPHEN). This API
    # inconsistency is confirmed against the live API (the underscore caches path
    # returns 404 "no API hosted at this URL").

    async def get_pipeline_config(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get the repository pipelines configuration (enabled flag, build number).

        Note: this endpoint requires the ``admin:repository`` scope. A token with
        only read scopes receives a 403 whose body lists the missing privilege.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Pipelines configuration object
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pipelines_config"
        )
        response.raise_for_status()
        return response.json()

    async def list_pipeline_variables(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 20,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List repository-level pipeline variables with pagination support.

        Secured variables never include their value in the response.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 20)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of pipeline variables
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pipelines_config/variables",
            {},
            config,
        )

    async def get_pipeline_variable(
        self,
        repo_slug: str,
        variable_uuid: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a single repository-level pipeline variable.

        Args:
            repo_slug: Repository slug
            variable_uuid: Variable UUID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Pipeline variable (no value if secured)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pipelines_config/variables/{variable_uuid}"
        )
        response.raise_for_status()
        return response.json()

    async def create_pipeline_variable(
        self,
        repo_slug: str,
        key: str,
        value: str,
        secured: bool = False,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a repository-level pipeline variable.

        Args:
            repo_slug: Repository slug
            key: Variable name
            value: Variable value
            secured: Whether the value is secured/masked (default: False)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Created variable
        """
        ws = self._resolve_workspace(workspace)
        payload = {"key": key, "value": value, "secured": secured}
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pipelines_config/variables",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def update_pipeline_variable(
        self,
        repo_slug: str,
        variable_uuid: str,
        key: Optional[str] = None,
        value: Optional[str] = None,
        secured: Optional[bool] = None,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update a repository-level pipeline variable (partial update).

        Args:
            repo_slug: Repository slug
            variable_uuid: Variable UUID
            key: New variable name (optional)
            value: New variable value (optional)
            secured: New secured flag (optional)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated variable
        """
        ws = self._resolve_workspace(workspace)
        payload: Dict[str, Any] = {}
        if key is not None:
            payload["key"] = key
        if value is not None:
            payload["value"] = value
        if secured is not None:
            payload["secured"] = secured
        if not payload:
            raise ValueError(
                "update_pipeline_variable requires at least one of key/value/secured."
            )
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/pipelines_config/variables/{variable_uuid}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def delete_pipeline_variable(
        self,
        repo_slug: str,
        variable_uuid: str,
        workspace: Optional[str] = None,
    ) -> None:
        """
        Delete a repository-level pipeline variable.

        Args:
            repo_slug: Repository slug
            variable_uuid: Variable UUID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pipelines_config/variables/{variable_uuid}"
        )
        response.raise_for_status()

    async def list_pipeline_schedules(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 20,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List pipeline schedules with pagination support.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 20)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of pipeline schedules
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pipelines_config/schedules",
            {},
            config,
        )

    async def get_pipeline_schedule(
        self,
        repo_slug: str,
        schedule_uuid: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a single pipeline schedule.

        Args:
            repo_slug: Repository slug
            schedule_uuid: Schedule UUID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Pipeline schedule
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pipelines_config/schedules/{schedule_uuid}"
        )
        response.raise_for_status()
        return response.json()

    async def list_pipeline_schedule_executions(
        self,
        repo_slug: str,
        schedule_uuid: str,
        workspace: Optional[str] = None,
        page_size: int = 20,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List the executions of a pipeline schedule with pagination support.

        Args:
            repo_slug: Repository slug
            schedule_uuid: Schedule UUID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 20)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of schedule executions
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pipelines_config/schedules/{schedule_uuid}/executions",
            {},
            config,
        )

    async def create_pipeline_schedule(
        self,
        repo_slug: str,
        branch: str,
        cron_pattern: str,
        workspace: Optional[str] = None,
        enabled: bool = True,
        selector_pattern: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a pipeline schedule on a branch.

        Args:
            repo_slug: Repository slug
            branch: Branch the scheduled pipeline runs on
            cron_pattern: Cron expression (Bitbucket 7-field format, e.g. "0 0 6 * * ? *")
            workspace: Workspace name (defaults to self.workspace)
            enabled: Whether the schedule is enabled (default: True)
            selector_pattern: Pipeline selector pattern (defaults to the branch name)

        Returns:
            Created schedule
        """
        ws = self._resolve_workspace(workspace)
        payload = {
            "type": "pipeline_schedule",
            "enabled": enabled,
            "target": {
                "type": "pipeline_ref_target",
                "ref_type": "branch",
                "ref_name": branch,
                "selector": {
                    "type": "branches",
                    "pattern": selector_pattern if selector_pattern is not None else branch,
                },
            },
            "cron_pattern": cron_pattern,
        }
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pipelines_config/schedules",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def update_pipeline_schedule(
        self,
        repo_slug: str,
        schedule_uuid: str,
        enabled: Optional[bool] = None,
        cron_pattern: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update a pipeline schedule (partial update).

        Args:
            repo_slug: Repository slug
            schedule_uuid: Schedule UUID
            enabled: New enabled flag (optional)
            cron_pattern: New cron expression (optional)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated schedule
        """
        ws = self._resolve_workspace(workspace)
        payload: Dict[str, Any] = {}
        if enabled is not None:
            payload["enabled"] = enabled
        if cron_pattern is not None:
            payload["cron_pattern"] = cron_pattern
        if not payload:
            raise ValueError(
                "update_pipeline_schedule requires at least one of enabled/cron_pattern."
            )
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/pipelines_config/schedules/{schedule_uuid}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def delete_pipeline_schedule(
        self,
        repo_slug: str,
        schedule_uuid: str,
        workspace: Optional[str] = None,
    ) -> None:
        """
        Delete a pipeline schedule.

        Args:
            repo_slug: Repository slug
            schedule_uuid: Schedule UUID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pipelines_config/schedules/{schedule_uuid}"
        )
        response.raise_for_status()

    async def list_pipeline_caches(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 20,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List pipeline caches with pagination support.

        Uses the ``pipelines-config`` (hyphen) path — see the section note.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 20)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of pipeline caches
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pipelines-config/caches",
            {},
            config,
        )

    async def delete_pipeline_cache(
        self,
        repo_slug: str,
        cache_uuid: str,
        workspace: Optional[str] = None,
    ) -> None:
        """
        Delete a pipeline cache.

        Uses the ``pipelines-config`` (hyphen) path — see the section note.

        Args:
            repo_slug: Repository slug
            cache_uuid: Cache UUID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pipelines-config/caches/{cache_uuid}"
        )
        response.raise_for_status()

    # ========== Default Reviewers ==========

    async def get_effective_default_reviewers(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 30,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get effective default reviewers for a repository.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of default reviewers
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/effective-default-reviewers",
            {},
            config
        )

    async def get_pull_request_diffstat(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1,
        pr_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get file modification statistics for a pull request with pagination support.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)
            pr_data: Pre-fetched PR data to extract diffstat URL from links,
                     avoiding a redundant API call (optional)

        Returns:
            Statistics with lines added/removed per file
            Each file entry contains:
            - status: modified, added, removed, renamed
            - lines_added: Number of lines added
            - lines_removed: Number of lines removed
            - new.path: File path after changes
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)

        # Use provided pr_data or fetch it
        if pr_data is None:
            pr_response = await self.client.get(
                f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}"
            )
            pr_response.raise_for_status()
            pr_data = pr_response.json()

        # Get the diffstat URL from the PR links
        if 'links' in pr_data and 'diffstat' in pr_data['links']:
            diffstat_url = pr_data['links']['diffstat']['href']
            # Remove base URL if present
            if diffstat_url.startswith(self.base_url):
                diffstat_url = diffstat_url[len(self.base_url):]

            return await aggregate_pages(self.client, diffstat_url, {}, config)
        else:
            # Fallback to direct URL if links not available
            return await aggregate_pages(
                self.client,
                f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/diffstat",
                {},
                config
            )

    async def publish_draft_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Publish a draft pull request (convert DRAFT to OPEN).

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated pull request details
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}",
            json={"draft": False}
        )
        response.raise_for_status()
        return response.json()

    # ========== Issues ==========

    async def list_issues(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        state: Optional[str] = None,
        kind: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        q: Optional[str] = None,
        sort: str = "-created_on",
        page_size: int = 20,
        max_pages: Optional[int] = 1,
        max_items: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        List issues in a repository's issue tracker with filtering and pagination.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            state: Filter by state (new, open, resolved, on hold, invalid, duplicate, wontfix, closed)
            kind: Filter by kind (bug, enhancement, proposal, task)
            priority: Filter by priority (trivial, minor, major, critical, blocker)
            assignee: Filter by assignee uuid
            q: Raw BBQL query, combined with the other filters using AND. Passed
               through verbatim (NOT escaped) — unlike the dedicated filters.
            sort: Sort field (default: -created_on for most recent first)
            page_size: Items per page (default: 20)
            max_pages: Maximum pages to fetch (default: 1)
            max_items: Maximum total items to fetch (default: None)

        Returns:
            Paginated list of issues with aggregated values

        Raises:
            IssueTrackerDisabledError: If the repository has no issue tracker enabled
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(
            page_size=page_size, max_pages=max_pages, max_items=max_items
        )
        params: Dict[str, Any] = {"sort": sort}
        query = _build_issue_query(state, kind, priority, assignee, q)
        if query:
            params["q"] = query
        try:
            return await aggregate_pages(
                self.client,
                f"/repositories/{ws}/{repo_slug}/issues",
                params,
                config,
            )
        except httpx.HTTPStatusError as exc:
            if _is_tracker_disabled_response(exc.response):
                raise IssueTrackerDisabledError(ws, repo_slug) from exc
            raise

    async def get_issue(
        self,
        repo_slug: str,
        issue_id: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get details for a specific issue.

        Args:
            repo_slug: Repository slug
            issue_id: Issue ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Issue details

        Raises:
            IssueTrackerDisabledError: If the repository has no issue tracker enabled
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/issues/{issue_id}"
        )
        _raise_if_tracker_disabled(response, ws, repo_slug)
        response.raise_for_status()
        return response.json()

    async def create_issue(
        self,
        repo_slug: str,
        title: str,
        content: Optional[str] = None,
        kind: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        state: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new issue.

        Args:
            repo_slug: Repository slug
            title: Issue title
            content: Issue description in markdown (optional)
            kind: Issue kind (bug, enhancement, proposal, task) (optional)
            priority: Issue priority (trivial, minor, major, critical, blocker) (optional)
            assignee: Assignee uuid (optional)
            state: Initial state (optional)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Created issue details

        Raises:
            IssueTrackerDisabledError: If the repository has no issue tracker enabled
        """
        ws = self._resolve_workspace(workspace)
        payload: Dict[str, Any] = {"title": title}
        if content is not None:
            payload["content"] = {"raw": content}
        if kind is not None:
            payload["kind"] = kind
        if priority is not None:
            payload["priority"] = priority
        if assignee is not None:
            payload["assignee"] = {"uuid": assignee}
        if state is not None:
            payload["state"] = state
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/issues",
            json=payload,
        )
        _raise_if_tracker_disabled(response, ws, repo_slug)
        response.raise_for_status()
        return response.json()

    async def update_issue(
        self,
        repo_slug: str,
        issue_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        state: Optional[str] = None,
        kind: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update an issue (partial update — only provided fields are changed).

        Args:
            repo_slug: Repository slug
            issue_id: Issue ID
            title: New title (optional)
            content: New description in markdown (optional)
            state: New state (optional)
            kind: New kind (optional)
            priority: New priority (optional)
            assignee: New assignee uuid (optional)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated issue details

        Raises:
            IssueTrackerDisabledError: If the repository has no issue tracker enabled
        """
        ws = self._resolve_workspace(workspace)
        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if content is not None:
            payload["content"] = {"raw": content}
        if state is not None:
            payload["state"] = state
        if kind is not None:
            payload["kind"] = kind
        if priority is not None:
            payload["priority"] = priority
        if assignee is not None:
            payload["assignee"] = {"uuid": assignee}
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/issues/{issue_id}",
            json=payload,
        )
        _raise_if_tracker_disabled(response, ws, repo_slug)
        response.raise_for_status()
        return response.json()

    async def delete_issue(
        self,
        repo_slug: str,
        issue_id: str,
        workspace: Optional[str] = None,
    ) -> None:
        """
        Delete an issue.

        Args:
            repo_slug: Repository slug
            issue_id: Issue ID
            workspace: Workspace name (defaults to self.workspace)

        Raises:
            IssueTrackerDisabledError: If the repository has no issue tracker enabled
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/issues/{issue_id}"
        )
        _raise_if_tracker_disabled(response, ws, repo_slug)
        response.raise_for_status()

    async def get_issue_comments(
        self,
        repo_slug: str,
        issue_id: str,
        workspace: Optional[str] = None,
        page_size: int = 20,
        max_pages: Optional[int] = 1,
        max_items: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        List comments on an issue with pagination support.

        Args:
            repo_slug: Repository slug
            issue_id: Issue ID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 20)
            max_pages: Maximum pages to fetch (default: 1)
            max_items: Maximum total items to fetch (default: None)

        Returns:
            Paginated list of issue comments with aggregated values

        Raises:
            IssueTrackerDisabledError: If the repository has no issue tracker enabled
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(
            page_size=page_size, max_pages=max_pages, max_items=max_items
        )
        try:
            return await aggregate_pages(
                self.client,
                f"/repositories/{ws}/{repo_slug}/issues/{issue_id}/comments",
                {},
                config,
            )
        except httpx.HTTPStatusError as exc:
            if _is_tracker_disabled_response(exc.response):
                raise IssueTrackerDisabledError(ws, repo_slug) from exc
            raise

    async def get_issue_comment(
        self,
        repo_slug: str,
        issue_id: str,
        comment_id: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a specific comment on an issue.

        Args:
            repo_slug: Repository slug
            issue_id: Issue ID
            comment_id: Comment ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Issue comment details

        Raises:
            IssueTrackerDisabledError: If the repository has no issue tracker enabled
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/issues/{issue_id}/comments/{comment_id}"
        )
        _raise_if_tracker_disabled(response, ws, repo_slug)
        response.raise_for_status()
        return response.json()

    async def add_issue_comment(
        self,
        repo_slug: str,
        issue_id: str,
        content: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add a comment to an issue.

        Args:
            repo_slug: Repository slug
            issue_id: Issue ID
            content: Comment content in markdown
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Created issue comment details

        Raises:
            IssueTrackerDisabledError: If the repository has no issue tracker enabled
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/issues/{issue_id}/comments",
            json={"content": {"raw": content}},
        )
        _raise_if_tracker_disabled(response, ws, repo_slug)
        response.raise_for_status()
        return response.json()

    async def update_issue_comment(
        self,
        repo_slug: str,
        issue_id: str,
        comment_id: str,
        content: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update a comment on an issue.

        Args:
            repo_slug: Repository slug
            issue_id: Issue ID
            comment_id: Comment ID
            content: New comment content in markdown
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated issue comment details

        Raises:
            IssueTrackerDisabledError: If the repository has no issue tracker enabled
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/issues/{issue_id}/comments/{comment_id}",
            json={"content": {"raw": content}},
        )
        _raise_if_tracker_disabled(response, ws, repo_slug)
        response.raise_for_status()
        return response.json()

    async def delete_issue_comment(
        self,
        repo_slug: str,
        issue_id: str,
        comment_id: str,
        workspace: Optional[str] = None,
    ) -> None:
        """
        Delete a comment on an issue.

        Args:
            repo_slug: Repository slug
            issue_id: Issue ID
            comment_id: Comment ID
            workspace: Workspace name (defaults to self.workspace)

        Raises:
            IssueTrackerDisabledError: If the repository has no issue tracker enabled
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/issues/{issue_id}/comments/{comment_id}"
        )
        _raise_if_tracker_disabled(response, ws, repo_slug)
        response.raise_for_status()

    # ========== Commits & Source ==========

    async def list_commits(
        self,
        repo_slug: str,
        revision: Optional[str] = None,
        workspace: Optional[str] = None,
        path: Optional[str] = None,
        include: Optional[str] = None,
        exclude: Optional[str] = None,
        page_size: int = 30,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List commits for a repository, optionally scoped to a revision/branch.

        Args:
            repo_slug: Repository slug
            revision: Branch, tag or commit hash to start from (optional; defaults to
                all branches). A branch name containing '/' (e.g. ``feature/x``) is
                ambiguous on this endpoint — resolve it to a hash first if needed.
            workspace: Workspace name (defaults to self.workspace)
            path: Restrict history to commits touching this file/directory path
            include: Only commits reachable from this ref (query filter)
            exclude: Exclude commits reachable from this ref (query filter)
            page_size: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of commits with aggregated values
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        if revision:
            url = f"/repositories/{ws}/{repo_slug}/commits/{revision}"
        else:
            url = f"/repositories/{ws}/{repo_slug}/commits"
        params: Dict[str, Any] = {}
        if path:
            params["path"] = path
        if include:
            params["include"] = include
        if exclude:
            params["exclude"] = exclude
        return await aggregate_pages(self.client, url, params, config)

    async def get_commit(
        self,
        repo_slug: str,
        commit: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get details for a single commit.

        Args:
            repo_slug: Repository slug
            commit: Commit hash (a simple branch/tag name also works)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Commit details
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/commit/{commit}"
        )
        response.raise_for_status()
        return response.json()

    async def get_commit_comments(
        self,
        repo_slug: str,
        commit: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List comments on a commit with pagination support.

        Args:
            repo_slug: Repository slug
            commit: Commit hash
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Comments with aggregated values
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/commit/{commit}/comments",
            {},
            config,
        )

    async def get_commit_comment(
        self,
        repo_slug: str,
        commit: str,
        comment_id: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a specific comment on a commit.

        Args:
            repo_slug: Repository slug
            commit: Commit hash
            comment_id: Comment ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Comment details
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/commit/{commit}/comments/{comment_id}"
        )
        response.raise_for_status()
        return response.json()

    async def add_commit_comment(
        self,
        repo_slug: str,
        commit: str,
        content: str,
        workspace: Optional[str] = None,
        inline_path: Optional[str] = None,
        inline_from: Optional[int] = None,
        inline_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Add a comment to a commit (general or inline).

        Args:
            repo_slug: Repository slug
            commit: Commit hash
            content: Comment content (markdown)
            workspace: Workspace name (defaults to self.workspace)
            inline_path: File path for an inline comment
            inline_from: Line number in the old version (deleted/modified lines)
            inline_to: Line number in the new version (added/modified lines)

        Returns:
            Created comment details
        """
        ws = self._resolve_workspace(workspace)
        if not inline_path and (inline_from is not None or inline_to is not None):
            raise ValueError(
                "inline_path is required when inline_from/inline_to is provided."
            )
        payload: Dict[str, Any] = {"content": {"raw": content}}
        if inline_path:
            inline_data: Dict[str, Any] = {"path": inline_path}
            if inline_from is not None:
                inline_data["from"] = inline_from
            if inline_to is not None:
                inline_data["to"] = inline_to
            payload["inline"] = inline_data
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/commit/{commit}/comments",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def _src_url(
        self,
        repo_slug: str,
        commit: str,
        path: str,
        workspace: Optional[str] = None,
    ) -> str:
        """Build a percent-encoded ``/src`` URL.

        The user-supplied ``path`` is URL-encoded (preserving '/') so file names
        containing '?', '#', '%' or spaces cannot break or inject into the request.
        Parent-directory segments ('..') are rejected: ``quote`` leaves dots intact,
        so an unchecked '..' could let the request escape the target ``repo_slug``.
        """
        ws = self._resolve_workspace(workspace)
        clean = (path or "").lstrip("/")
        if any(segment == ".." for segment in clean.split("/")):
            raise ValueError(
                f"Invalid path '{path}': parent-directory segments ('..') are not allowed."
            )
        encoded = urllib.parse.quote(clean, safe="/")
        base = f"/repositories/{ws}/{repo_slug}/src/{commit}"
        return f"{base}/{encoded}" if encoded else f"{base}/"

    async def _get_src_meta(
        self,
        repo_slug: str,
        commit: str,
        path: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch ``?format=meta`` metadata for a source path (file or directory)."""
        url = self._src_url(repo_slug, commit, path, workspace)
        response = await self.client.get(
            url, params={"format": "meta"}, follow_redirects=True
        )
        response.raise_for_status()
        return response.json()

    async def get_file_content(
        self,
        repo_slug: str,
        commit: str,
        path: str,
        workspace: Optional[str] = None,
        max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> str:
        """
        Get the raw text content of a file at a given commit/branch.

        A ``?format=meta`` pre-check guards the call: it rejects directories,
        oversized files (> ``max_bytes``) and binary mimetypes before downloading.
        The content is then fetched from the exact commit hash resolved by the
        pre-check (not the original ref), so a concurrent push cannot swap in a
        different file between the two requests. A final byte-length check catches
        files whose metadata reported no size.

        Args:
            repo_slug: Repository slug
            commit: Commit hash (a simple branch/tag name also works; a branch name
                containing '/' is ambiguous on ``/src`` — resolve it to a hash first)
            path: File path within the repository
            workspace: Workspace name (defaults to self.workspace)
            max_bytes: Maximum file size to return (default: 256 KiB)

        Returns:
            File content as text

        Raises:
            ValueError: If the path is a directory, exceeds ``max_bytes``, or is binary
        """
        meta = await self._get_src_meta(repo_slug, commit, path, workspace)
        if meta.get("type") == "commit_directory":
            raise ValueError(
                f"'{path}' is a directory, not a file; use list_directory instead."
            )
        size = meta.get("size")
        if isinstance(size, int) and size > max_bytes:
            raise ValueError(
                f"File '{path}' is {size} bytes, exceeding the {max_bytes}-byte limit; "
                "fetch it via git or request a narrower path."
            )
        mimetype = meta.get("mimetype")
        if _is_binary_mimetype(mimetype):
            raise ValueError(
                f"File '{path}' has a binary mimetype ({mimetype}); "
                "refusing to return raw bytes as text."
            )
        # Pin the content fetch to the commit the metadata resolved to (closes the
        # TOCTOU window when ``commit`` is a moving branch ref).
        pinned = (meta.get("commit") or {}).get("hash") or commit
        url = self._src_url(repo_slug, pinned, path, workspace)
        response = await self.client.get(url, follow_redirects=True)
        response.raise_for_status()
        # Safety net for files whose metadata reported size=None: enforce the cap
        # on the actual payload so an oversized blob is never returned as text.
        raw = response.content
        if len(raw) > max_bytes:
            raise ValueError(
                f"File '{path}' is {len(raw)} bytes, exceeding the "
                f"{max_bytes}-byte limit; fetch it via git or request a narrower path."
            )
        # Decode tolerantly: a text file in a non-UTF-8 charset without a declared
        # encoding must not crash the call (binary files are already rejected above).
        return raw.decode(response.encoding or "utf-8", errors="replace")

    async def list_directory(
        self,
        repo_slug: str,
        commit: str,
        path: str = "",
        workspace: Optional[str] = None,
        page_size: int = 50,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List the entries of a directory at a given commit/branch.

        A ``?format=meta`` pre-check gives a clear error when the path is a file
        (instead of a JSON decode failure on the raw content).

        Args:
            repo_slug: Repository slug
            commit: Commit hash (a simple branch/tag name also works)
            path: Directory path within the repository (empty = repository root)
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 50)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated directory listing with aggregated values

        Raises:
            ValueError: If the path points to a file
        """
        meta = await self._get_src_meta(repo_slug, commit, path, workspace)
        if meta.get("type") == "commit_file":
            raise ValueError(
                f"'{path}' is a file, not a directory; use get_file_content instead."
            )
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        # Pin to the resolved commit hash for a consistent listing (see get_file_content).
        pinned = (meta.get("commit") or {}).get("hash") or commit
        url = self._src_url(repo_slug, pinned, path, workspace)
        return await aggregate_pages(
            self.client, url, {}, config, follow_redirects=True
        )

    # ========== Deployments & Environments ==========
    #
    # API quirks verified against the docs (developer.atlassian.com deployments group):
    #   * The runtime collection endpoints REQUIRE a trailing slash:
    #     ``/environments/`` returns 404 without it (BitbucketPHP/Client#65). The same
    #     trailing slash is applied to ``/deployments/`` for consistency within the group.
    #   * The deployment-variables endpoints live under ``deployments_config`` (UNDERSCORE),
    #     mirroring ``pipelines_config`` for variables (NOT the hyphenated caches path).
    #   * There is no ``PUT /environments/{uuid}`` (modification is only possible via
    #     ``POST .../changes``), so no ``update_environment`` is exposed.
    #   * ``/deployments`` cannot be server-side filtered by environment (BCLOUD-18729);
    #     consumers filter on the slimmed ``environment`` field instead.

    async def list_environments(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 20,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List deployment environments for a repository.

        Note: the collection path requires a trailing slash (``/environments/``);
        without it the API returns 404.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 20)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of environments
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/environments/",
            {},
            config,
        )

    async def get_environment(
        self,
        repo_slug: str,
        environment_uuid: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a single deployment environment.

        Args:
            repo_slug: Repository slug
            environment_uuid: Environment UUID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Environment object
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/environments/{environment_uuid}"
        )
        response.raise_for_status()
        return response.json()

    async def create_environment(
        self,
        repo_slug: str,
        name: str,
        environment_type: str = "Test",
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a deployment environment.

        Args:
            repo_slug: Repository slug
            name: Environment name
            environment_type: One of "Test", "Staging", "Production" (default: "Test")
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Created environment
        """
        ws = self._resolve_workspace(workspace)
        payload = {"name": name, "environment_type": {"name": environment_type}}
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/environments/",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def delete_environment(
        self,
        repo_slug: str,
        environment_uuid: str,
        workspace: Optional[str] = None,
    ) -> None:
        """
        Delete a deployment environment.

        Args:
            repo_slug: Repository slug
            environment_uuid: Environment UUID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/environments/{environment_uuid}"
        )
        response.raise_for_status()

    async def list_deployments(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 20,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List deployments for a repository (most recent first).

        The API does not support server-side filtering by environment
        (BCLOUD-18729); filter on the ``environment`` field of the result instead.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 20)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of deployments
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/deployments/",
            {},
            config,
        )

    async def get_deployment(
        self,
        repo_slug: str,
        deployment_uuid: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a single deployment (state, environment, deployed commit).

        Args:
            repo_slug: Repository slug
            deployment_uuid: Deployment UUID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Deployment object
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/deployments/{deployment_uuid}"
        )
        response.raise_for_status()
        return response.json()

    async def list_deployment_variables(
        self,
        repo_slug: str,
        environment_uuid: str,
        workspace: Optional[str] = None,
        page_size: int = 20,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List the variables of a deployment environment (secured values masked).

        Path note: uses ``deployments_config`` (underscore), like pipeline variables.

        Args:
            repo_slug: Repository slug
            environment_uuid: Environment UUID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 20)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of deployment variables
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/deployments_config/environments/{environment_uuid}/variables",
            {},
            config,
        )

    async def create_deployment_variable(
        self,
        repo_slug: str,
        environment_uuid: str,
        key: str,
        value: str,
        secured: bool = False,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a deployment environment variable.

        Args:
            repo_slug: Repository slug
            environment_uuid: Environment UUID
            key: Variable name
            value: Variable value
            secured: Whether the value is secured/masked (default: False)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Created variable (no value if secured)
        """
        ws = self._resolve_workspace(workspace)
        payload = {"key": key, "value": value, "secured": secured}
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/deployments_config/environments/{environment_uuid}/variables",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def update_deployment_variable(
        self,
        repo_slug: str,
        environment_uuid: str,
        variable_uuid: str,
        key: Optional[str] = None,
        value: Optional[str] = None,
        secured: Optional[bool] = None,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update a deployment environment variable (partial update).

        Args:
            repo_slug: Repository slug
            environment_uuid: Environment UUID
            variable_uuid: Variable UUID
            key: New variable name (optional)
            value: New variable value (optional)
            secured: New secured flag (optional)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated variable (no value if secured)
        """
        ws = self._resolve_workspace(workspace)
        payload: Dict[str, Any] = {}
        if key is not None:
            payload["key"] = key
        if value is not None:
            payload["value"] = value
        if secured is not None:
            payload["secured"] = secured
        if not payload:
            raise ValueError(
                "update_deployment_variable requires at least one of key/value/secured."
            )
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/deployments_config/environments/{environment_uuid}/variables/{variable_uuid}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def delete_deployment_variable(
        self,
        repo_slug: str,
        environment_uuid: str,
        variable_uuid: str,
        workspace: Optional[str] = None,
    ) -> None:
        """
        Delete a deployment environment variable.

        Args:
            repo_slug: Repository slug
            environment_uuid: Environment UUID
            variable_uuid: Variable UUID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/deployments_config/environments/{environment_uuid}/variables/{variable_uuid}"
        )
        response.raise_for_status()

    # ========== Branch Restrictions & Workspace Governance ==========
    #
    # API quirks verified against the docs (branch-restrictions / workspaces groups):
    #   * The ``branch-restrictions`` COLLECTION endpoint requires a trailing slash
    #     (404 otherwise, BCLOUD-17211); the individual ``/{id}`` resource does not.
    #   * Workspace endpoints (``/workspaces/{ws}/members`` & ``/permissions``) are
    #     standard — NO trailing slash.
    #   * ``/members`` returns ``workspace_membership`` objects WITHOUT a ``permission``
    #     field; per-user roles live on the separate ``/permissions`` endpoint.
    #   * Member identifiers are an ``account_id`` or a brace-wrapped ``uuid`` (usernames
    #     were removed from API URLs in 2019 for GDPR).

    async def list_branch_restrictions(
        self,
        repo_slug: str,
        kind: Optional[str] = None,
        workspace: Optional[str] = None,
        page_size: int = 30,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List branch restrictions (branch protection rules) for a repository.

        Note: the collection path requires a trailing slash (``/branch-restrictions/``).

        Args:
            repo_slug: Repository slug
            kind: Optional filter by restriction type (e.g. ``push``,
                ``require_approvals_to_merge``)
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of branch restrictions
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        params = {"kind": kind} if kind else {}
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/branch-restrictions/",
            params,
            config,
        )

    async def get_branch_restriction(
        self,
        repo_slug: str,
        restriction_id: int,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a single branch restriction.

        Args:
            repo_slug: Repository slug
            restriction_id: Numeric restriction id
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Branch restriction object
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/branch-restrictions/{restriction_id}"
        )
        response.raise_for_status()
        return response.json()

    async def create_branch_restriction(
        self,
        repo_slug: str,
        kind: str,
        pattern: str,
        value: Optional[int] = None,
        users: Optional[list] = None,
        groups: Optional[list] = None,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a branch restriction.

        Args:
            repo_slug: Repository slug
            kind: Restriction type (``push``, ``force``, ``delete``,
                ``require_approvals_to_merge``, ...)
            pattern: Branch name pattern the restriction applies to
            value: Numeric value where applicable (e.g. min approvals)
            users: Optional list of account_ids exempted/targeted
            groups: Optional list of group slugs exempted/targeted
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Created branch restriction
        """
        ws = self._resolve_workspace(workspace)
        payload: Dict[str, Any] = {"kind": kind, "pattern": pattern}
        if value is not None:
            payload["value"] = value
        if users is not None:
            payload["users"] = [{"account_id": u} for u in users]
        if groups is not None:
            payload["groups"] = [{"slug": g} for g in groups]
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/branch-restrictions/",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def update_branch_restriction(
        self,
        repo_slug: str,
        restriction_id: int,
        kind: Optional[str] = None,
        pattern: Optional[str] = None,
        value: Optional[int] = None,
        users: Optional[list] = None,
        groups: Optional[list] = None,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update a branch restriction.

        Note: the Bitbucket ``PUT`` endpoint requires ``kind`` in the body (it is the
        restriction's identity and cannot be changed), so pass the existing ``kind``
        along with the field(s) you want to change.

        Args:
            repo_slug: Repository slug
            restriction_id: Numeric restriction id
            kind: Restriction type — required by the API on update
            pattern: New branch pattern (optional)
            value: New numeric value (optional)
            users: New list of account_ids (optional)
            groups: New list of group slugs (optional)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated branch restriction
        """
        # The Bitbucket PUT endpoint rejects a body without ``kind`` (400). Fail fast
        # with a clear message instead of letting a silent 400 bubble up.
        if kind is None:
            raise ValueError(
                "update_branch_restriction requires 'kind' (the Bitbucket PUT API mandates it)."
            )
        ws = self._resolve_workspace(workspace)
        payload: Dict[str, Any] = {"kind": kind}
        if pattern is not None:
            payload["pattern"] = pattern
        if value is not None:
            payload["value"] = value
        if users is not None:
            payload["users"] = [{"account_id": u} for u in users]
        if groups is not None:
            payload["groups"] = [{"slug": g} for g in groups]
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/branch-restrictions/{restriction_id}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def delete_branch_restriction(
        self,
        repo_slug: str,
        restriction_id: int,
        workspace: Optional[str] = None,
    ) -> None:
        """
        Delete a branch restriction.

        Args:
            repo_slug: Repository slug
            restriction_id: Numeric restriction id
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/branch-restrictions/{restriction_id}"
        )
        response.raise_for_status()

    async def list_workspace_members(
        self,
        workspace: Optional[str] = None,
        page_size: int = 30,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List the members of a workspace.

        The members endpoint returns ``workspace_membership`` objects (user + workspace)
        WITHOUT a per-user permission; use ``list_workspace_permissions`` for roles.

        Args:
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of workspace memberships
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/workspaces/{ws}/members",
            {},
            config,
        )

    async def get_workspace_member(
        self,
        member_id: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a single workspace member.

        Args:
            member_id: Member account_id or brace-wrapped uuid (not a username)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Workspace membership object
        """
        ws = self._resolve_workspace(workspace)
        response = await self.client.get(
            f"/workspaces/{ws}/members/{member_id}"
        )
        response.raise_for_status()
        return response.json()

    async def list_workspace_permissions(
        self,
        workspace: Optional[str] = None,
        page_size: int = 30,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List the user permissions (roles) of a workspace.

        Args:
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of workspace permissions (permission + user)
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/workspaces/{ws}/permissions",
            {},
            config,
        )

    async def list_repository_permissions(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 30,
        max_pages: Optional[int] = 1,
    ) -> Dict[str, Any]:
        """
        List the user permissions for a specific repository in the workspace.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of repository permissions (permission + user)
        """
        ws = self._resolve_workspace(workspace)
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/workspaces/{ws}/permissions/repositories/{repo_slug}",
            {},
            config,
        )
