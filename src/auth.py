"""Per-request Bitbucket identity for multi-tenant HTTP deployments (issue #72).

Architecture decision (option A + native Bitbucket OAuth):

- the MCP client presents a **Bitbucket access token** as ``Authorization: Bearer``;
- the server **verifies it by use** — ``GET /2.0/user`` with that bearer — which yields a
  verified identity (``account_id``) without any credential store;
- the same token is then reused as-is for the downstream API calls.

No store, no new dependency, no new secret surface: the token presented *is* the caller's
Bitbucket credential, carrying exactly the caller's own rights.

Rejected alternatives, for the record:

- *header pass-through of a raw Bitbucket token* — no verified identity, and no OAuth
  discoverability (``/.well-known/oauth-protected-resource``);
- *identity -> stored credentials mapping* — a persistent store is a new attack surface
  for no gain here, since the presented token is already a valid Bitbucket credential.

**Not supported in this mode**: Bitbucket Repository/Workspace Access Tokens. They are not
bound to a user account, so ``GET /2.0/user`` rejects them and no identity can be derived.
Deployments that need them stay single-tenant (see ``docs/deployment-modes.md``).
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.shared.auth import OAuthMetadata
from pydantic import AnyHttpUrl, Field

logger = logging.getLogger(__name__)

# Who-did-what log of the multi-tenant mode. Defined once, used by the server (tool calls)
# and by the admission and scope gates (refusals).
AUDIT_LOGGER_NAME = "bitbucket_mcp.audit"
audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)

BITBUCKET_API_BASE = "https://api.bitbucket.org/2.0"

# Membership listing with a workspace allowlist: 5 pages of 100. Past that the list is
# treated as incomplete — admission still works, but no default workspace is assumed.
MAX_MEMBERSHIP_PAGES = 5
# A substantive admission refusal (no allowed membership) is remembered this long, so a
# refused account does not cost two Bitbucket calls per request. Never longer than the
# verification cache TTL, and off when that TTL is 0.
REFUSAL_CACHE_TTL = 60  # seconds

# Bitbucket's OAuth endpoints. Bitbucket publishes no RFC 8414 metadata for them, so this
# server advertises them under its own issuer (see build_authorization_server_metadata).
BITBUCKET_AUTHORIZE_URL = "https://bitbucket.org/site/oauth2/authorize"
BITBUCKET_TOKEN_URL = "https://bitbucket.org/site/oauth2/access_token"

_DEFAULT_PORTS = {"http": 80, "https": 443}

DEFAULT_TOKEN_CACHE_TTL = 300  # seconds
DEFAULT_TOKEN_CACHE_SIZE = 256
DEFAULT_CLIENT_CACHE_TTL = 900  # seconds
DEFAULT_CLIENT_CACHE_SIZE = 128

# Minimum delay between two "workspace endpoint is gone" errors (see
# BitbucketTokenVerifier._log_workspace_endpoint_gone).
WORKSPACE_GONE_LOG_INTERVAL = 3600  # seconds


@dataclass(frozen=True)
class BitbucketIdentity:
    """A verified Bitbucket caller.

    ``account_id`` is the stable, GDPR-era user identifier (usernames were removed from
    the API in 2019). ``workspace`` is the caller's *default* workspace, resolved from
    their memberships; it is ``None`` when they belong to zero or several workspaces, in
    which case every call must name its workspace explicitly.
    """

    account_id: str
    display_name: Optional[str] = None
    workspace: Optional[str] = None


class BitbucketAccessToken(AccessToken):
    """The SDK ``AccessToken`` carrying the resolved Bitbucket identity.

    Subclassing is explicitly sanctioned by the SDK (``mcp/server/auth/provider.py``:
    "FastMCP doesn't render any of these types in the user response, so it's OK to add
    fields to subclasses which should not be exposed externally").

    ``token`` is redeclared with ``repr=False``: the inherited pydantic repr would print
    the raw credential into any log line or traceback that renders this object.
    """

    token: str = Field(repr=False)
    identity: BitbucketIdentity


def current_identity() -> Optional[BitbucketAccessToken]:
    """Return the verified Bitbucket token for the request being served, if any.

    Reads the contextvar populated by the SDK's ``AuthContextMiddleware``. Synchronous on
    purpose: it is called from ``get_client()``, which stays sync so none of the ~98 tool
    call sites have to change.
    """
    token = get_access_token()
    return token if isinstance(token, BitbucketAccessToken) else None


@dataclass(frozen=True)
class MultiTenantConfig:
    """Runtime configuration of the multi-tenant HTTP mode."""

    resource_server_url: str
    #: Advertised authorization server. ``None`` means this server's own origin, which
    #: then serves the authorization-server metadata itself.
    issuer_url: Optional[str] = None
    client_cache_size: int = DEFAULT_CLIENT_CACHE_SIZE
    client_cache_ttl: int = DEFAULT_CLIENT_CACHE_TTL
    token_cache_size: int = DEFAULT_TOKEN_CACHE_SIZE
    token_cache_ttl: int = DEFAULT_TOKEN_CACHE_TTL
    #: Allow tools flagged ``destructiveHint`` (merge, decline, stop_pipeline, delete_*).
    allow_destructive: bool = False
    #: Expose only tools flagged ``readOnlyHint`` — strictest posture.
    read_only: bool = False
    #: Workspaces (normalized slugs) a caller must belong to and may act on. Empty means
    #: no restriction: any Bitbucket account is admitted (see docs/deployment-modes.md).
    allowed_workspaces: FrozenSet[str] = frozenset()

    @property
    def origin(self) -> str:
        """Scheme, host and non-default port of ``resource_server_url`` — no path, no userinfo."""
        url = AnyHttpUrl(self.resource_server_url)
        port = "" if url.port == _DEFAULT_PORTS.get(url.scheme) else f":{url.port}"
        return f"{url.scheme}://{url.host}{port}"

    @property
    def effective_issuer_url(self) -> str:
        """The issuer advertised in the protected-resource metadata."""
        return self.issuer_url or self.origin

    @property
    def serves_authorization_metadata(self) -> bool:
        """Whether ``/.well-known/oauth-authorization-server`` is answered by this server.

        Only when the issuer *is* this server's origin: that is the one URL a client
        derives that lands on this server's root ``/.well-known/``. An issuer elsewhere —
        or on this host but with a path — must publish its own metadata.
        """
        return AnyHttpUrl(self.effective_issuer_url) == AnyHttpUrl(self.origin)


def build_authorization_server_metadata(issuer_url: str) -> OAuthMetadata:
    """RFC 8414 metadata that points MCP clients at Bitbucket's OAuth endpoints.

    The client then runs the authorization-code flow against Bitbucket directly, with its
    own pre-registered (confidential) Bitbucket OAuth client. Bitbucket supports neither
    public clients nor dynamic registration, hence no ``registration_endpoint`` and no
    ``none`` auth method.

    ``S256`` is advertised because MCP clients must refuse an authorization server that
    does not, but Bitbucket accepts a wrong ``code_verifier``: protection of the code in
    transit rests on the client secret (see ``docs/deployment-modes.md``).
    """
    return OAuthMetadata(
        issuer=AnyHttpUrl(issuer_url),
        authorization_endpoint=AnyHttpUrl(BITBUCKET_AUTHORIZE_URL),
        token_endpoint=AnyHttpUrl(BITBUCKET_TOKEN_URL),
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["client_secret_basic", "client_secret_post"],
        code_challenge_methods_supported=["S256"],
    )


def token_fingerprint(token: str) -> str:
    """Return a stable, non-reversible cache key for a token.

    The raw token is never used as a dict key, logged, or embedded in an error: a
    fingerprint is enough to recognise a token we already verified.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_workspace(slug: str) -> str:
    """Canonical form of a workspace slug for comparisons: trimmed, lower-cased."""
    return slug.strip().lower()


def parse_allowed_workspaces(values: Iterable[str]) -> FrozenSet[str]:
    """Normalize an allowlist, dropping blanks. Empty result means no restriction."""
    return frozenset(slug for slug in map(normalize_workspace, values) if slug)


def is_workspace_allowed(workspace: Optional[str], allowed: FrozenSet[str]) -> bool:
    """The one rule both gates apply: admission (memberships) and scope (each request).

    An empty allowlist allows everything. Otherwise only a listed slug passes — a workspace
    UUID (``{…}``) never equals a slug, so it is refused rather than resolved.
    """
    if not allowed:
        return True
    return bool(workspace) and normalize_workspace(workspace) in allowed


def admit(
    memberships: Sequence[str], complete: bool, allowed: FrozenSet[str]
) -> Tuple[bool, Optional[str]]:
    """Decide admission and the default workspace from a caller's memberships.

    Returns ``(admitted, default_workspace)``. Without an allowlist every caller is
    admitted and a single membership becomes the default. With one, only callers holding
    an allowed membership are admitted, and the default is chosen among those — only when
    the listing is complete, since an unseen page could hold a second candidate.
    """
    if not allowed:
        return True, (memberships[0] if len(memberships) == 1 else None)
    eligible = [slug for slug in memberships if is_workspace_allowed(slug, allowed)]
    if not eligible:
        return False, None
    return True, (eligible[0] if complete and len(eligible) == 1 else None)


class BitbucketTokenVerifier:
    """Verify a bearer token against Bitbucket and derive the caller's identity.

    Implements the SDK's ``TokenVerifier`` protocol. Results are cached with a bounded
    LRU + TTL keyed by :func:`token_fingerprint`, and concurrent verifications of the same
    unseen token are de-duplicated so a burst of first-time requests issues a single pair
    of Bitbucket calls.

    The cache TTL is also the **revocation window**: a token revoked on Bitbucket's side
    keeps working until its cached verification expires. Set the TTL to 0 to verify on
    every request.

    With ``allowed_workspaces``, a caller is admitted only if they belong to one of those
    workspaces; a refusal is a ``None`` (hence a 401), never a cached identity.
    """

    def __init__(
        self,
        *,
        cache_ttl: int = DEFAULT_TOKEN_CACHE_TTL,
        cache_size: int = DEFAULT_TOKEN_CACHE_SIZE,
        base_url: str = BITBUCKET_API_BASE,
        timeout: float = 10.0,
        allowed_workspaces: FrozenSet[str] = frozenset(),
    ):
        self._cache_ttl = max(0, cache_ttl)
        self._cache_size = max(1, cache_size)
        self._base_url = base_url
        self._timeout = timeout
        self._allowed_workspaces = allowed_workspaces
        # fingerprint -> expires_at of a substantive admission refusal. Kept apart from the
        # identity cache: it holds no identity, and cache_size() must not count it.
        self._refused: Dict[str, float] = {}
        # fingerprint -> (expires_at, BitbucketAccessToken). Insertion-ordered dict used
        # as an LRU: re-inserting on hit moves the entry to the end.
        self._cache: Dict[str, Tuple[float, BitbucketAccessToken]] = {}
        self._inflight: Dict[str, "asyncio.Future[Optional[BitbucketAccessToken]]"] = {}
        # Last time the "workspace endpoint is gone" error was logged, for throttling.
        # None = never logged. See _resolve_default_workspace.
        self._workspace_gone_logged_at: Optional[float] = None

    # ----- cache -------------------------------------------------------------

    def _cache_get(self, fingerprint: str) -> Optional[BitbucketAccessToken]:
        entry = self._cache.get(fingerprint)
        if entry is None:
            return None
        expires_at, token = entry
        if expires_at <= time.monotonic():
            self._cache.pop(fingerprint, None)
            return None
        # Refresh recency.
        self._cache.pop(fingerprint)
        self._cache[fingerprint] = entry
        return token

    def _cache_put(self, fingerprint: str, token: BitbucketAccessToken) -> None:
        if self._cache_ttl == 0:
            return
        self._cache.pop(fingerprint, None)
        self._cache[fingerprint] = (time.monotonic() + self._cache_ttl, token)
        while len(self._cache) > self._cache_size:
            self._cache.pop(next(iter(self._cache)))

    def cache_size(self) -> int:
        """Number of cached verifications — exposed for tests and diagnostics."""
        return len(self._cache)

    def _is_refused(self, fingerprint: str) -> bool:
        expires_at = self._refused.get(fingerprint)
        if expires_at is None:
            return False
        if expires_at <= time.monotonic():
            self._refused.pop(fingerprint, None)
            return False
        return True

    def _remember_refusal(self, fingerprint: str) -> None:
        ttl = min(REFUSAL_CACHE_TTL, self._cache_ttl)
        if ttl <= 0:
            return
        self._refused.pop(fingerprint, None)
        self._refused[fingerprint] = time.monotonic() + ttl
        while len(self._refused) > self._cache_size:
            self._refused.pop(next(iter(self._refused)))

    # ----- verification ------------------------------------------------------

    async def verify_token(self, token: str) -> Optional[BitbucketAccessToken]:
        """Verify `token` with Bitbucket. Returns ``None`` for any invalid token.

        Returning ``None`` (rather than raising) is what the SDK's ``BearerAuthBackend``
        expects; it turns into a 401 with a ``WWW-Authenticate`` header.
        """
        fingerprint = token_fingerprint(token)

        cached = self._cache_get(fingerprint)
        if cached is not None:
            return cached
        if self._is_refused(fingerprint):
            return None

        # De-duplicate concurrent first-time verifications of the same token.
        pending = self._inflight.get(fingerprint)
        if pending is not None:
            return await asyncio.shield(pending)

        future: "asyncio.Future[Optional[BitbucketAccessToken]]" = (
            asyncio.get_running_loop().create_future()
        )
        self._inflight[fingerprint] = future
        try:
            result = await self._verify_uncached(token, fingerprint)
        except BaseException as exc:  # noqa: BLE001 - always release the waiters
            future.set_exception(exc)
            # Consume the exception on the future itself so a cancelled-and-never-awaited
            # future does not surface as "exception was never retrieved".
            future.exception()
            raise
        else:
            future.set_result(result)
            return result
        finally:
            self._inflight.pop(fingerprint, None)

    async def _verify_uncached(
        self, token: str, fingerprint: str
    ) -> Optional[BitbucketAccessToken]:
        """Call Bitbucket to identify the bearer, then cache the outcome.

        A fresh ``httpx.AsyncClient`` per verification is deliberate: a long-lived one
        would bind its connection pool to the event loop that created it, the exact
        failure mode fixed for the API clients in #71. Verifications only happen on a
        cache miss, so the cost is bounded.
        """
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, trust_env=False
            ) as client:
                response = await client.get("/user", headers=headers)
                if response.status_code in (401, 403):
                    logger.info(
                        "Bearer token rejected by Bitbucket (status=%s, token=%s...)",
                        response.status_code,
                        fingerprint[:12],
                    )
                    return None
                response.raise_for_status()
                user = response.json()
                listing = await self._list_workspaces(client, headers)
        # ValueError covers a non-JSON body behind a 200 (a proxy error page, say):
        # json.JSONDecodeError is a ValueError, not an httpx.HTTPError. Letting it escape
        # would surface as an unhandled exception in the SDK's BearerAuthBackend — which
        # does not guard this call — instead of the clean 401 a bad token must produce.
        except (httpx.HTTPError, ValueError) as exc:
            # Never log `exc` verbatim without care: httpx messages carry the URL, not the
            # headers, so no token leaks — but keep the fingerprint form for correlation.
            logger.warning(
                "Could not verify bearer token (token=%s...): %s", fingerprint[:12], type(exc).__name__
            )
            return None

        account_id = user.get("account_id") or user.get("uuid")
        if not account_id:
            logger.warning(
                "Bitbucket returned no account_id for token=%s...; rejecting", fingerprint[:12]
            )
            return None

        admitted, workspace = self._admit(str(account_id), fingerprint, listing)
        if not admitted:
            return None

        identity = BitbucketIdentity(
            account_id=str(account_id),
            display_name=user.get("display_name"),
            workspace=workspace,
        )
        access_token = BitbucketAccessToken(
            token=token,
            client_id=identity.account_id,
            scopes=[],
            subject=identity.account_id,
            claims={"iss": self._base_url},
            identity=identity,
        )
        self._cache_put(fingerprint, access_token)
        logger.info(
            "Verified Bitbucket identity account_id=%s workspace=%s",
            identity.account_id,
            identity.workspace,
        )
        return access_token

    def _admit(
        self,
        account_id: str,
        fingerprint: str,
        listing: Optional[Tuple[List[str], bool]],
    ) -> Tuple[bool, Optional[str]]:
        """Apply the workspace allowlist to a verified caller; audit every refusal.

        Only a verdict on the caller — a complete listing with no allowed membership — is
        remembered. A listing that failed or stopped short says nothing about them, so it
        is refused (fail closed while an allowlist is set) but verified again next time.
        """
        if listing is None and self._allowed_workspaces:
            audit_logger.warning(
                "admission refused account_id=%s reason=memberships could not be listed",
                account_id,
            )
            return False, None
        memberships, complete = listing if listing is not None else ([], True)
        admitted, workspace = admit(memberships, complete, self._allowed_workspaces)
        if not admitted:
            if complete:
                # Remembered before the in-flight future resolves, so concurrent waiters
                # share this one refusal and its single audit line.
                self._remember_refusal(fingerprint)
            audit_logger.warning(
                "admission refused account_id=%s reason=%s",
                account_id,
                "no membership in an allowed workspace"
                if complete
                else "no allowed workspace among the memberships listed",
            )
            return False, None
        if workspace is None and memberships:
            logger.info(
                "Caller has %d workspace memberships; no default workspace will be assumed",
                len(memberships),
            )
        return True, workspace

    def _log_workspace_endpoint_gone(self) -> None:
        """Report a 410 on the workspace listing, at most once an hour.

        A removed endpoint is *our* bug, not a caller permission problem, so it is logged
        apart from the generic ``>= 400`` fallback — otherwise it reads as "this identity
        simply has no membership" and nobody investigates.

        Throttled, not once-per-process: the verifier is a process singleton, so a "log
        once ever" flag would leave an operator with a single line for a degradation
        lasting weeks — and ``BitbucketClient._resolve_workspace`` does not log the
        resulting failures either. Throttled, not unbounded: this fires on every cache
        miss (per token, per TTL), so N tenants would otherwise flood the log at the exact
        moment the signal matters.
        """
        now = time.monotonic()
        last = self._workspace_gone_logged_at
        if last is not None and now - last < WORKSPACE_GONE_LOG_INTERVAL:
            return
        self._workspace_gone_logged_at = now
        consequence = (
            "Every caller is refused while the workspace allowlist is set."
            if self._allowed_workspaces
            else "Callers keep authenticating, but no default workspace can be resolved — "
            "every tool call must name its workspace."
        )
        logger.error(
            "Workspace listing endpoint returned 410 Gone: it has been retired "
            "(see Atlassian CHANGE-2770). %s",
            consequence,
        )

    async def _list_workspaces(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Optional[Tuple[List[str], bool]]:
        """List the caller's workspace memberships as ``(slugs, complete)``.

        ``None`` when they cannot be listed (410, any other error status, transport or
        JSON failure). One page of 100 without an allowlist — enough to tell "exactly one"
        from "several". With an allowlist, ``next`` links are followed up to
        ``MAX_MEMBERSHIP_PAGES`` so that a member is not refused for an unseen page; a
        ``next`` link to another host is never followed, since it would carry the token.

        Endpoint: ``/user/workspaces``. NOT ``/user/permissions/workspaces`` nor
        ``/workspaces``, both removed on 2026-04-14 (Atlassian CHANGE-2770, the
        cross-workspace API sunset) and answering 410 for every caller — verified live.
        The replacement returns the same ``values[].workspace.slug`` shape and honours
        ``pagelen`` identically, so only the path differs.
        """
        api = httpx.URL(self._base_url)
        max_pages = MAX_MEMBERSHIP_PAGES if self._allowed_workspaces else 1
        url: str = "/user/workspaces"
        params: Optional[Dict[str, int]] = {"pagelen": 100}
        slugs: List[str] = []
        try:
            for _ in range(max_pages):
                response = await client.get(url, headers=headers, params=params)
                if response.status_code == 410:
                    self._log_workspace_endpoint_gone()
                    return None
                if response.status_code >= 400:
                    return None
                body = response.json()
                for entry in body.get("values", []) or []:
                    slug = (entry.get("workspace") or {}).get("slug")
                    if slug and slug not in slugs:
                        slugs.append(slug)
                next_url = body.get("next")
                if not next_url:
                    return slugs, True
                link = httpx.URL(next_url)
                if (link.scheme, link.host, link.port) != (api.scheme, api.host, api.port):
                    return slugs, False
                url, params = next_url, None
        # InvalidURL is not an HTTPError, and a non-string `next` or an unexpected body
        # shape raises TypeError / AttributeError: all mean the listing cannot be trusted,
        # never an unhandled error in the auth backend.
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError, AttributeError):
            return None
        return slugs, False
