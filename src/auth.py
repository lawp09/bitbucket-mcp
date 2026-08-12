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
from typing import Dict, Optional, Tuple

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from pydantic import Field

logger = logging.getLogger(__name__)

BITBUCKET_API_BASE = "https://api.bitbucket.org/2.0"

# Bitbucket's own OAuth authorization server. Used as the default ``issuer_url`` advertised
# in the protected-resource metadata; overridable for proxied/enterprise setups.
DEFAULT_ISSUER_URL = "https://bitbucket.org"

DEFAULT_TOKEN_CACHE_TTL = 300  # seconds
DEFAULT_TOKEN_CACHE_SIZE = 256
DEFAULT_CLIENT_CACHE_TTL = 900  # seconds
DEFAULT_CLIENT_CACHE_SIZE = 128


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
    issuer_url: str = DEFAULT_ISSUER_URL
    client_cache_size: int = DEFAULT_CLIENT_CACHE_SIZE
    client_cache_ttl: int = DEFAULT_CLIENT_CACHE_TTL
    token_cache_size: int = DEFAULT_TOKEN_CACHE_SIZE
    token_cache_ttl: int = DEFAULT_TOKEN_CACHE_TTL
    #: Allow tools flagged ``destructiveHint`` (merge, decline, stop_pipeline, delete_*).
    allow_destructive: bool = False
    #: Expose only tools flagged ``readOnlyHint`` — strictest posture.
    read_only: bool = False


def token_fingerprint(token: str) -> str:
    """Return a stable, non-reversible cache key for a token.

    The raw token is never used as a dict key, logged, or embedded in an error: a
    fingerprint is enough to recognise a token we already verified.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class BitbucketTokenVerifier:
    """Verify a bearer token against Bitbucket and derive the caller's identity.

    Implements the SDK's ``TokenVerifier`` protocol. Results are cached with a bounded
    LRU + TTL keyed by :func:`token_fingerprint`, and concurrent verifications of the same
    unseen token are de-duplicated so a burst of first-time requests issues a single pair
    of Bitbucket calls.

    The cache TTL is also the **revocation window**: a token revoked on Bitbucket's side
    keeps working until its cached verification expires. Set the TTL to 0 to verify on
    every request.
    """

    def __init__(
        self,
        *,
        cache_ttl: int = DEFAULT_TOKEN_CACHE_TTL,
        cache_size: int = DEFAULT_TOKEN_CACHE_SIZE,
        base_url: str = BITBUCKET_API_BASE,
        timeout: float = 10.0,
    ):
        self._cache_ttl = max(0, cache_ttl)
        self._cache_size = max(1, cache_size)
        self._base_url = base_url
        self._timeout = timeout
        # fingerprint -> (expires_at, BitbucketAccessToken). Insertion-ordered dict used
        # as an LRU: re-inserting on hit moves the entry to the end.
        self._cache: Dict[str, Tuple[float, BitbucketAccessToken]] = {}
        self._inflight: Dict[str, "asyncio.Future[Optional[BitbucketAccessToken]]"] = {}

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
                workspace = await self._resolve_default_workspace(client, headers)
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

    async def _resolve_default_workspace(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Optional[str]:
        """Resolve the caller's default workspace from their memberships.

        Exactly one membership -> that workspace becomes the caller's default, which is
        what makes ``workspace=None`` resolve to *their* workspace rather than the
        process one. Zero or several -> ``None``, and calls must name their workspace.
        """
        try:
            response = await client.get(
                "/user/permissions/workspaces", headers=headers, params={"pagelen": 100}
            )
            if response.status_code >= 400:
                return None
            values = response.json().get("values", []) or []
        except (httpx.HTTPError, ValueError):
            return None

        slugs = []
        for entry in values:
            slug = (entry.get("workspace") or {}).get("slug")
            if slug and slug not in slugs:
                slugs.append(slug)
        if len(slugs) == 1:
            return slugs[0]
        logger.info(
            "Caller has %d workspace memberships; no default workspace will be assumed",
            len(slugs),
        )
        return None
