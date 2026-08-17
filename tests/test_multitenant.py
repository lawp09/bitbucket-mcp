"""Tests for per-request Bitbucket credentials in multi-tenant HTTP mode (issue #72).

Organised by acceptance criterion:

- AC1 two distinct identities never share a Bitbucket client
- AC2 no token in logs, ``repr`` output, or error messages
- AC3 the client cache is bounded under a load of N distinct identities
- AC4 ``workspace=None`` resolves to the caller's workspace, never the process one
- AC5 stdio mode stays strictly unchanged
- AC6 the deployment/threat-model documentation exists

plus the SDK guard-rails, the token verifier, and a transport-level integration test that
pushes two bearer identities through the real ASGI stack.
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

import src.server
from src.auth import (
    BitbucketAccessToken,
    BitbucketIdentity,
    BitbucketTokenVerifier,
    MultiTenantConfig,
    current_identity,
    token_fingerprint,
)
from src.client import (
    AuthorizationError,
    BasicAuthStrategy,
    BearerAuthStrategy,
    BitbucketClient,
)
from src.server import close_clients, enable_multi_tenant, get_client, mcp

SECRET = "s3cr3t-bitbucket-oauth-token-do-not-leak"


# ========== Fixtures ==========


@pytest.fixture(autouse=True)
def reset_multi_tenant_state():
    """Restore every piece of module/SDK global state this feature touches."""
    saved_auth = mcp.settings.auth
    saved_verifier = getattr(mcp, "_token_verifier", None)
    yield
    src.server._multi_tenant = None
    src.server._tenant_clients.clear()
    src.server._clients.clear()
    src.server._no_loop_client = None
    mcp.settings.auth = saved_auth
    mcp._token_verifier = saved_verifier


@pytest.fixture
def multi_tenant():
    """Enable multi-tenant mode with a small, fast cache and return the config."""
    config = MultiTenantConfig(
        resource_server_url="https://mcp.example.com",
        client_cache_size=4,
        client_cache_ttl=900,
    )
    enable_multi_tenant(config)
    return config


def make_token(account_id, workspace="acme", token=SECRET):
    """Build a verified access token as the verifier would."""
    return BitbucketAccessToken(
        token=token,
        client_id=account_id,
        scopes=[],
        subject=account_id,
        identity=BitbucketIdentity(
            account_id=account_id, display_name="Test User", workspace=workspace
        ),
    )


def as_caller(access_token):
    """Install `access_token` in the SDK auth contextvar, as AuthContextMiddleware does."""
    return auth_context_var.set(AuthenticatedUser(access_token))


# ========== AC1 — two identities never share a client ==========


@pytest.mark.asyncio
async def test_distinct_identities_get_distinct_clients(multi_tenant):
    reset = as_caller(make_token("account-a", workspace="ws-a"))
    client_a = get_client()
    auth_context_var.reset(reset)

    reset = as_caller(make_token("account-b", workspace="ws-b", token="other-token"))
    client_b = get_client()
    auth_context_var.reset(reset)

    assert client_a is not client_b
    assert client_a.account_id == "account-a"
    assert client_b.account_id == "account-b"
    assert client_a.workspace == "ws-a"
    assert client_b.workspace == "ws-b"
    assert client_a.client.headers["Authorization"] != client_b.client.headers["Authorization"]


@pytest.mark.asyncio
async def test_same_identity_reuses_its_client(multi_tenant):
    reset = as_caller(make_token("account-a"))
    first = get_client()
    second = get_client()
    auth_context_var.reset(reset)

    assert first is second


@pytest.mark.asyncio
async def test_rotated_token_gets_a_fresh_client(multi_tenant):
    """A refreshed OAuth token must not keep being served by a client holding the old one.

    Keyed on the account alone, a cache hit would silently reuse the stale credential for
    up to the cache TTL — wrong scopes at best, spurious 401s once it expires.
    """
    reset = as_caller(make_token("account-a", token="token-v1"))
    first = get_client()
    auth_context_var.reset(reset)

    reset = as_caller(make_token("account-a", token="token-v2"))
    second = get_client()
    auth_context_var.reset(reset)

    assert second is not first
    assert second.client.headers["Authorization"] == "Bearer token-v2"
    assert first._retired is True
    # The rotation *replaces* the identity's entry — a caller refreshing their token must
    # not accumulate one cache slot (and one connection pool) per rotation.
    cache = src.server._tenant_clients[asyncio.get_running_loop()]
    assert len(cache) == 1


@pytest.mark.asyncio
async def test_scheduled_drain_closes_retired_clients(multi_tenant):
    """The public path must actually close retired clients, not just queue them.

    Exercises _schedule_drain -> loop.create_task, which the direct _drain_pending calls
    elsewhere bypass. The task is strongly referenced, so it cannot be collected first.
    """
    reset = as_caller(make_token("account-a", token="token-v1"))
    stale = get_client()
    auth_context_var.reset(reset)

    reset = as_caller(make_token("account-a", token="token-v2"))
    get_client()
    auth_context_var.reset(reset)

    assert stale._retired is True
    assert stale._closed is False
    # Let the scheduled drain task run. Poll rather than count turnarounds: how many await
    # points aclose() goes through is an httpx implementation detail.
    # The done callback that clears _drain_tasks is itself scheduled with call_soon, so
    # wait for both conditions rather than assuming they land on the same turn.
    for _ in range(50):
        if stale._closed and not src.server._drain_tasks:
            break
        await asyncio.sleep(0)
    assert stale._closed is True
    assert src.server._drain_tasks == set()


@pytest.mark.asyncio
async def test_client_cache_ttl_zero_rebuilds_every_time(multi_tenant):
    """ttl=0 means "no caching" on both caches — never "cache forever" on one of them."""
    src.server._tenant_clients.clear()
    src.server._multi_tenant = MultiTenantConfig(
        resource_server_url="https://mcp.example.com", client_cache_ttl=0
    )
    reset = as_caller(make_token("account-a"))
    first = get_client()
    second = get_client()
    auth_context_var.reset(reset)

    assert second is not first


@pytest.mark.asyncio
async def test_acquire_outside_a_scope_warns(multi_tenant, caplog):
    """A future call site bypassing _client_scope must fail loudly, not silently."""
    with caplog.at_level(logging.WARNING, logger="src.server"):
        reset = as_caller(make_token("account-a"))
        client = get_client()
        auth_context_var.reset(reset)

    assert client._inflight == 0
    assert "outside a tool scope" in caplog.text


@pytest.mark.asyncio
async def test_client_scope_releases_on_exception(multi_tenant):
    """An exploding tool body must still release its clients."""
    reset = as_caller(make_token("account-a"))
    try:
        with pytest.raises(RuntimeError):
            async with src.server._client_scope():
                client = get_client()
                assert client._inflight == 1
                raise RuntimeError("boom")
    finally:
        auth_context_var.reset(reset)
    assert client._inflight == 0


@pytest.mark.asyncio
async def test_concurrent_scopes_share_one_client_and_release_it(multi_tenant):
    """Two concurrent calls from one identity share a client; the count returns to zero."""
    seen = []
    started = asyncio.Event()

    async def call(hold):
        async with src.server._client_scope():
            reset = as_caller(make_token("account-a"))
            client = get_client()
            auth_context_var.reset(reset)
            seen.append(client)
            if hold:
                started.set()
                await asyncio.sleep(0.02)
            else:
                await started.wait()
            assert client._inflight >= 1

    await asyncio.gather(call(True), call(False))

    assert seen[0] is seen[1]
    assert seen[0]._inflight == 0


@pytest.mark.asyncio
async def test_bearer_client_uses_bearer_scheme(multi_tenant):
    reset = as_caller(make_token("account-a"))
    client = get_client()
    auth_context_var.reset(reset)

    assert client.auth_scheme == "Bearer"
    assert client.client.headers["Authorization"] == f"Bearer {SECRET}"


# ========== AC2 — no token in repr / logs / errors ==========


def test_no_token_in_client_repr():
    bearer = BitbucketClient.from_bearer(SECRET, "acme", account_id="account-a")
    assert SECRET not in repr(bearer)
    assert "acme" in repr(bearer)

    basic = BitbucketClient("user@example.com", SECRET, "acme")
    assert SECRET not in repr(basic)


def test_no_token_in_strategy_repr():
    assert SECRET not in repr(BearerAuthStrategy(SECRET))
    assert SECRET not in repr(BasicAuthStrategy("user@example.com", SECRET))


def test_no_token_in_access_token_repr():
    """The inherited pydantic repr would print `token`; the subclass hides it."""
    access = make_token("account-a")
    assert SECRET not in repr(access)
    assert SECRET not in str(access)
    assert "account-a" in repr(access)
    # The value is still readable programmatically — it is the downstream credential.
    assert access.token == SECRET


def test_no_token_in_authorization_error():
    error = AuthorizationError(
        "Bitbucket refused the request (403).", account_id="account-a", status_code=403
    )
    assert SECRET not in str(error)
    assert error.status_code == 403


@pytest.mark.asyncio
async def test_no_token_in_logs_on_client_creation(multi_tenant, caplog):
    with caplog.at_level(logging.DEBUG):
        reset = as_caller(make_token("account-a"))
        get_client()
        auth_context_var.reset(reset)
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_no_token_in_logs_when_verification_fails(caplog):
    verifier = BitbucketTokenVerifier()
    with caplog.at_level(logging.DEBUG):
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=httpx.Response(401))):
            assert await verifier.verify_token(SECRET) is None
    assert SECRET not in caplog.text


def test_cache_key_is_a_fingerprint_not_the_token():
    fingerprint = token_fingerprint(SECRET)
    assert SECRET not in fingerprint
    assert fingerprint == token_fingerprint(SECRET)
    assert fingerprint != token_fingerprint(SECRET + "x")


# ========== AC3 — the client cache is bounded ==========


@pytest.mark.asyncio
async def test_client_cache_is_bounded_and_closes_evicted(multi_tenant):
    """500 distinct identities must not grow the cache past its ceiling."""
    closed = []
    original_close = BitbucketClient.close

    async def tracking_close(self):
        closed.append(self.account_id)
        await original_close(self)

    with patch.object(BitbucketClient, "close", tracking_close):
        for index in range(500):
            reset = as_caller(make_token(f"account-{index}", token=f"token-{index}"))
            get_client()
            auth_context_var.reset(reset)

        loop = asyncio.get_running_loop()
        cache = src.server._tenant_clients[loop]
        assert len(cache) <= multi_tenant.client_cache_size

        # Drain the retirement queue the way the running loop would.
        await src.server._drain_pending(cache)

    assert len(closed) == 500 - multi_tenant.client_cache_size
    assert "account-0" in closed
    assert "account-499" not in closed


@pytest.mark.asyncio
async def test_expired_client_is_replaced_and_retired(multi_tenant):
    src.server._tenant_clients.clear()
    reset = as_caller(make_token("account-a"))
    first = get_client()
    auth_context_var.reset(reset)

    cache = src.server._tenant_clients[asyncio.get_running_loop()]
    cache.ttl = 1
    with patch.object(src.server.time, "monotonic", return_value=time.monotonic() + 3600):
        reset = as_caller(make_token("account-a"))
        second = get_client()
        auth_context_var.reset(reset)

    assert second is not first
    assert first._retired is True
    await src.server._drain_pending(cache)
    assert first._closed is True


@pytest.mark.asyncio
async def test_evicted_client_is_not_closed_while_in_flight(multi_tenant):
    """An LRU eviction must never close a client a live request is still using."""
    async with src.server._client_scope():
        reset = as_caller(make_token("victim"))
        victim = get_client()
        auth_context_var.reset(reset)
        assert victim._inflight == 1

        # Push the victim out of a 4-slot cache.
        for index in range(multi_tenant.client_cache_size + 1):
            reset = as_caller(make_token(f"filler-{index}", token=f"token-{index}"))
            get_client()
            auth_context_var.reset(reset)

        cache = src.server._tenant_clients[asyncio.get_running_loop()]
        assert victim._retired is True
        await src.server._drain_pending(cache)
        # Still in use -> still open, and still queued for closing.
        assert victim._closed is False
        assert victim in cache.pending

    # Leaving the scope releases the last user, which closes it.
    assert victim._inflight == 0
    assert victim._closed is True


@pytest.mark.asyncio
async def test_close_clients_drains_tenant_caches(multi_tenant):
    reset = as_caller(make_token("account-a"))
    client = get_client()
    auth_context_var.reset(reset)

    await close_clients()

    assert client._closed is True
    assert len(src.server._tenant_clients) == 0


# ========== AC4 — workspace=None is the caller's workspace ==========


@pytest.mark.asyncio
async def test_workspace_none_resolves_to_caller_workspace(multi_tenant):
    """The process workspace must never leak into a tenant's call."""
    with patch.dict(os.environ, {"BITBUCKET_WORKSPACE": "process-workspace"}):
        reset = as_caller(make_token("account-a", workspace="caller-workspace"))
        client = get_client()
        auth_context_var.reset(reset)

    assert client._resolve_workspace(None) == "caller-workspace"
    assert client._resolve_workspace("explicit") == "explicit"


@pytest.mark.asyncio
async def test_calls_target_the_caller_workspace(multi_tenant):
    """End-to-end on a real client method: the URL carries the caller's workspace."""
    reset = as_caller(make_token("account-a", workspace="caller-workspace"))
    client = get_client()
    auth_context_var.reset(reset)

    captured = {}

    async def fake_get(url, **kwargs):
        captured["url"] = url
        return httpx.Response(
            200,
            json={"values": [], "page": 1, "size": 0},
            request=httpx.Request("GET", url),
        )

    with patch.object(client.client, "get", fake_get):
        await client.get_pull_requests("my-repo")

    assert "caller-workspace" in captured["url"]


def test_unresolved_workspace_raises_instead_of_building_a_bad_url():
    """Zero or several memberships -> no default; a call without workspace must fail."""
    client = BitbucketClient.from_bearer(SECRET, None, account_id="account-a")
    with pytest.raises(AuthorizationError) as exc:
        client._resolve_workspace(None)
    assert "pass `workspace` explicitly" in str(exc.value)
    assert SECRET not in str(exc.value)
    # An explicit workspace still works.
    assert client._resolve_workspace("acme") == "acme"


# ========== AC5 — stdio / single-tenant unchanged ==========


def test_single_tenant_path_is_untouched():
    """Multi-tenant off: get_client keeps using the process credentials, Basic Auth."""
    assert src.server._multi_tenant is None
    env = {
        "BITBUCKET_USERNAME": "user@example.com",
        "BITBUCKET_TOKEN": "process-token",
        "BITBUCKET_WORKSPACE": "process-workspace",
    }
    with patch.dict(os.environ, env, clear=True):
        client = get_client()
    assert client.auth_scheme == "Basic"
    assert client.workspace == "process-workspace"
    assert client.account_id is None


def test_single_tenant_ignores_an_auth_context():
    """A stray auth context must not change the single-tenant behaviour."""
    env = {
        "BITBUCKET_USERNAME": "user@example.com",
        "BITBUCKET_TOKEN": "process-token",
        "BITBUCKET_WORKSPACE": "process-workspace",
    }
    reset = as_caller(make_token("account-a", workspace="caller-workspace"))
    try:
        with patch.dict(os.environ, env, clear=True):
            client = get_client()
    finally:
        auth_context_var.reset(reset)
    assert client.auth_scheme == "Basic"
    assert client.workspace == "process-workspace"


# ========== Fail-closed ==========


@pytest.mark.asyncio
async def test_no_identity_is_refused(multi_tenant):
    """No verified identity -> refuse; never fall back to process credentials."""
    env = {
        "BITBUCKET_USERNAME": "user@example.com",
        "BITBUCKET_TOKEN": "process-token",
        "BITBUCKET_WORKSPACE": "process-workspace",
    }
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(AuthorizationError) as exc:
            get_client()
    assert "multi-tenant" in str(exc.value)


def test_no_running_loop_is_refused(multi_tenant):
    """The historical no-loop path builds a process client — refuse it here."""
    reset = as_caller(make_token("account-a"))
    try:
        with pytest.raises(AuthorizationError) as exc:
            get_client()
    finally:
        auth_context_var.reset(reset)
    assert "event loop" in str(exc.value)
    assert src.server._no_loop_client is None


def test_current_identity_ignores_a_plain_access_token():
    """A non-Bitbucket AccessToken in the context must not be trusted as an identity."""
    from mcp.server.auth.provider import AccessToken

    reset = auth_context_var.set(
        AuthenticatedUser(AccessToken(token=SECRET, client_id="x", scopes=[]))
    )
    try:
        assert current_identity() is None
    finally:
        auth_context_var.reset(reset)


# ========== Exposure policy for write tools ==========


@pytest.mark.asyncio
async def test_destructive_tool_refused_by_default(multi_tenant):
    with pytest.raises(AuthorizationError) as exc:
        src.server._enforce_tenant_policy("merge_pull_request", multi_tenant)
    assert "destructive" in str(exc.value)


@pytest.mark.asyncio
async def test_destructive_tool_allowed_when_opted_in():
    config = MultiTenantConfig(
        resource_server_url="https://mcp.example.com", allow_destructive=True
    )
    src.server._enforce_tenant_policy("merge_pull_request", config)  # must not raise


def test_read_only_mode_refuses_writes():
    config = MultiTenantConfig(resource_server_url="https://mcp.example.com", read_only=True)
    src.server._enforce_tenant_policy("get_pull_request", config)  # must not raise
    with pytest.raises(AuthorizationError) as exc:
        src.server._enforce_tenant_policy("create_pull_request", config)
    assert "read-only" in str(exc.value)


def test_non_destructive_write_allowed_by_default(multi_tenant):
    src.server._enforce_tenant_policy("create_pull_request", multi_tenant)  # must not raise


@pytest.mark.asyncio
async def test_tool_wrapper_enforces_policy_and_audits(multi_tenant, caplog):
    calls = []

    async def merge_pull_request(repo_slug, workspace=None):
        calls.append(repo_slug)
        return {"ok": True}

    async def get_pull_request(repo_slug, workspace=None):
        calls.append(repo_slug)
        return {"ok": True}

    guarded = src.server._instrument_tool("merge_pull_request", merge_pull_request)
    allowed = src.server._instrument_tool("get_pull_request", get_pull_request)

    reset = as_caller(make_token("account-a", workspace="ws-a"))
    try:
        with pytest.raises(AuthorizationError):
            await guarded("repo")
        with caplog.at_level(logging.INFO, logger="bitbucket_mcp.audit"):
            assert await allowed("repo") == {"ok": True}
    finally:
        auth_context_var.reset(reset)

    assert calls == ["repo"]
    assert "tool=get_pull_request" in caplog.text
    assert "account_id=account-a" in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_tool_wrapper_is_inert_in_single_tenant_mode(caplog):
    async def merge_pull_request(repo_slug, workspace=None):
        return {"ok": True}

    wrapped = src.server._instrument_tool("merge_pull_request", merge_pull_request)
    with caplog.at_level(logging.INFO, logger="bitbucket_mcp.audit"):
        assert await wrapped("repo") == {"ok": True}
    assert caplog.text == ""


def test_tool_wrapper_preserves_the_signature():
    """FastMCP derives the input schema via inspect.signature — it must see the real one."""
    import inspect

    async def get_pull_request(repo_slug: str, workspace: str = None) -> dict:
        return {}

    wrapped = src.server._instrument_tool("get_pull_request", get_pull_request)
    assert list(inspect.signature(wrapped).parameters) == ["repo_slug", "workspace"]
    assert wrapped.__name__ == "get_pull_request"


# ========== Token verifier ==========


# httpx.Response.raise_for_status() needs the originating request attached; a bare
# Response() built in a test has none, so every helper below wires one in.
_FAKE_REQUEST = httpx.Request("GET", "https://api.bitbucket.org/2.0/user")


def _response(status, payload=None):
    return httpx.Response(status, json=payload or {}, request=_FAKE_REQUEST)


def _user_response(account_id="account-a"):
    return _response(200, {"account_id": account_id, "display_name": "Test User"})


def _workspaces_response(*slugs):
    return _response(200, {"values": [{"workspace": {"slug": slug}} for slug in slugs]})


def _is_workspaces_url(url):
    """Is this the workspace-listing leg of a verification (vs the /user leg)?

    Single source of truth on purpose: the same routing decision was duplicated in three
    mocks, and when the endpoint moved (CHANGE-2770, issue #77) they silently stopped
    matching — each one then served the /user payload for both legs, degrading the tests
    to the "no membership" branch without failing. One helper, one place to update.

    Matched on the exact suffix rather than a substring: "/user" is a prefix of
    "/user/workspaces" (a prefix test routes both legs to /user), and the client also
    calls workspace-scoped "/workspaces/{slug}/..." paths that must not match here.
    """
    return str(url).endswith("/user/workspaces")


def _routed_get(user_response, workspaces_response):
    async def fake_get(self, url, **kwargs):
        return workspaces_response if _is_workspaces_url(url) else user_response

    return fake_get


@pytest.mark.asyncio
async def test_verifier_resolves_identity_and_single_workspace():
    verifier = BitbucketTokenVerifier()
    with patch.object(
        httpx.AsyncClient, "get", _routed_get(_user_response(), _workspaces_response("acme"))
    ):
        token = await verifier.verify_token(SECRET)

    assert token is not None
    assert token.identity.account_id == "account-a"
    assert token.identity.workspace == "acme"
    assert token.subject == "account-a"
    assert token.token == SECRET


@pytest.mark.asyncio
async def test_verifier_uses_the_live_workspace_endpoint():
    """The workspace listing must target /user/workspaces, not the retired endpoint.

    /2.0/user/permissions/workspaces and /2.0/workspaces were removed on 2026-04-14
    (CHANGE-2770) and answer 410 for every caller. Every other test mocks the response,
    so a dead URL stays invisible to them — asserting on the requested path is the only
    thing that catches it (issue #77).
    """
    verifier = BitbucketTokenVerifier()
    requested = []

    async def recording_get(self, url, **kwargs):
        requested.append(str(url))
        return _workspaces_response("acme") if _is_workspaces_url(url) else _user_response()

    with patch.object(httpx.AsyncClient, "get", recording_get):
        token = await verifier.verify_token(SECRET)

    assert token.identity.workspace == "acme"
    assert any(url.endswith("/user/workspaces") for url in requested)
    assert not any("permissions/workspaces" in url for url in requested)


@pytest.mark.asyncio
async def test_verifier_survives_a_gone_workspace_endpoint(caplog):
    """A 410 leaves the identity usable, and says so at most once an hour.

    Should this endpoint be retired in turn, callers must still authenticate — only the
    implicit workspace is lost — and the log must name the cause distinctly, since a
    silent None is indistinguishable from "this identity has no membership".
    """
    verifier = BitbucketTokenVerifier(cache_ttl=0)
    gone = _response(410, {"type": "error", "error": {"message": "deprecated"}})

    with (
        patch.object(httpx.AsyncClient, "get", _routed_get(_user_response(), gone)),
        caplog.at_level(logging.ERROR, logger="src.auth"),
    ):
        first = await verifier.verify_token(SECRET)
        # A second, distinct token: caching is off, so this is a full re-verification
        # and would log again were the throttle missing.
        second = await verifier.verify_token("another-token")

    assert first is not None and second is not None
    assert first.identity.account_id == "account-a"
    assert first.identity.workspace is None
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1, "the 410 error must be throttled, not logged per request"
    assert "CHANGE-2770" in errors[0].getMessage()


@pytest.mark.asyncio
async def test_gone_workspace_endpoint_is_logged_again_after_the_interval(caplog):
    """The throttle must not silence the problem forever on a long-lived process.

    The verifier is a process singleton, so a "log once ever" flag would leave an
    operator with a single line for a degradation lasting weeks.
    """
    verifier = BitbucketTokenVerifier(cache_ttl=0)
    gone = _response(410, {"type": "error"})

    with (
        patch.object(httpx.AsyncClient, "get", _routed_get(_user_response(), gone)),
        caplog.at_level(logging.ERROR, logger="src.auth"),
    ):
        await verifier.verify_token(SECRET)
        with patch.object(
            src.auth.time,
            "monotonic",
            return_value=time.monotonic() + src.auth.WORKSPACE_GONE_LOG_INTERVAL + 1,
        ):
            await verifier.verify_token("another-token")

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2


@pytest.mark.asyncio
async def test_verifier_leaves_workspace_unset_when_ambiguous():
    verifier = BitbucketTokenVerifier()
    with patch.object(
        httpx.AsyncClient,
        "get",
        _routed_get(_user_response(), _workspaces_response("acme", "globex")),
    ):
        token = await verifier.verify_token(SECRET)
    assert token.identity.workspace is None


@pytest.mark.asyncio
async def test_verifier_leaves_workspace_unset_when_none():
    verifier = BitbucketTokenVerifier()
    with patch.object(
        httpx.AsyncClient, "get", _routed_get(_user_response(), _workspaces_response())
    ):
        token = await verifier.verify_token(SECRET)
    assert token.identity.workspace is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_verifier_rejects_an_invalid_token(status):
    verifier = BitbucketTokenVerifier()
    with patch.object(httpx.AsyncClient, "get", AsyncMock(return_value=httpx.Response(status))):
        assert await verifier.verify_token(SECRET) is None
    assert verifier.cache_size() == 0


@pytest.mark.asyncio
async def test_verifier_survives_a_network_failure():
    verifier = BitbucketTokenVerifier()
    with patch.object(
        httpx.AsyncClient, "get", AsyncMock(side_effect=httpx.ConnectError("boom"))
    ):
        assert await verifier.verify_token(SECRET) is None


@pytest.mark.asyncio
async def test_verifier_rejects_a_response_without_account_id():
    """Repository/Workspace Access Tokens are not bound to an account — unsupported."""
    verifier = BitbucketTokenVerifier()
    with patch.object(
        httpx.AsyncClient,
        "get",
        _routed_get(_response(200, {}), _workspaces_response("acme")),
    ):
        assert await verifier.verify_token(SECRET) is None


@pytest.mark.asyncio
async def test_verifier_caches_and_expires():
    verifier = BitbucketTokenVerifier(cache_ttl=300)
    calls = []

    async def counting_get(self, url, **kwargs):
        calls.append(url)
        return _workspaces_response("acme") if _is_workspaces_url(url) else _user_response()

    with patch.object(httpx.AsyncClient, "get", counting_get):
        first = await verifier.verify_token(SECRET)
        second = await verifier.verify_token(SECRET)
        assert first is second
        # Asserted, not just counted: without it a mock that stops matching the real URL
        # degrades this to the "no membership" branch and still passes.
        assert first.identity.workspace == "acme"
        assert len(calls) == 2  # /user + /user/workspaces, once

        with patch.object(
            src.auth.time, "monotonic", return_value=time.monotonic() + 3600
        ):
            third = await verifier.verify_token(SECRET)
        assert third is not first
        assert len(calls) == 4


@pytest.mark.asyncio
async def test_verifier_cache_is_bounded():
    verifier = BitbucketTokenVerifier(cache_size=3)
    with patch.object(
        httpx.AsyncClient, "get", _routed_get(_user_response(), _workspaces_response("acme"))
    ):
        for index in range(50):
            token = await verifier.verify_token(f"token-{index}")
    assert verifier.cache_size() == 3
    assert token.identity.workspace == "acme"


@pytest.mark.asyncio
async def test_verifier_ttl_zero_disables_caching():
    verifier = BitbucketTokenVerifier(cache_ttl=0)
    with patch.object(
        httpx.AsyncClient, "get", _routed_get(_user_response(), _workspaces_response("acme"))
    ):
        token = await verifier.verify_token(SECRET)
    assert verifier.cache_size() == 0
    assert token.identity.workspace == "acme"


@pytest.mark.asyncio
async def test_verifier_deduplicates_concurrent_verifications():
    """A burst on a cold cache must issue a single pair of Bitbucket calls."""
    verifier = BitbucketTokenVerifier()
    calls = []

    async def slow_get(self, url, **kwargs):
        calls.append(url)
        await asyncio.sleep(0.01)
        return _workspaces_response("acme") if _is_workspaces_url(url) else _user_response()

    with patch.object(httpx.AsyncClient, "get", slow_get):
        results = await asyncio.gather(*(verifier.verify_token(SECRET) for _ in range(10)))

    assert all(result is results[0] for result in results)
    assert results[0].identity.workspace == "acme"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_verifier_releases_waiters_on_failure():
    """A crashing verification must not leave concurrent callers hanging."""
    verifier = BitbucketTokenVerifier()

    async def exploding_get(self, url, **kwargs):
        await asyncio.sleep(0.01)
        raise RuntimeError("boom")

    with patch.object(httpx.AsyncClient, "get", exploding_get):
        results = await asyncio.gather(
            *(verifier.verify_token(SECRET) for _ in range(5)), return_exceptions=True
        )

    assert all(isinstance(result, RuntimeError) for result in results)
    assert verifier._inflight == {}


@pytest.mark.asyncio
async def test_verifier_survives_a_non_json_body():
    """A 200 carrying HTML (proxy error page) must yield None, not an unhandled error.

    The SDK's BearerAuthBackend does not guard verify_token(), so anything escaping here
    surfaces as a 500 instead of the clean 401 an unusable token must produce.
    """
    verifier = BitbucketTokenVerifier()
    html = httpx.Response(200, text="<html>gateway error</html>", request=_FAKE_REQUEST)
    with patch.object(httpx.AsyncClient, "get", AsyncMock(return_value=html)):
        assert await verifier.verify_token(SECRET) is None


@pytest.mark.asyncio
async def test_concurrent_drains_do_not_drop_a_retired_client(multi_tenant):
    """Two drains racing on one cache must not lose a client retired in between.

    Overwriting cache.pending at the end of a drain (instead of merging) would leave the
    late arrival retired, out of the cache and out of the queue — an untracked open
    connection pool nothing can ever close.
    """
    src.server._tenant_clients.clear()
    reset = as_caller(make_token("account-a"))
    get_client()
    auth_context_var.reset(reset)
    cache = src.server._tenant_clients[asyncio.get_running_loop()]

    busy = BitbucketClient.from_bearer("t-busy", "acme", account_id="busy")
    busy._inflight = 1
    cache._retire(busy)

    latecomer = BitbucketClient.from_bearer("t-late", "acme", account_id="late")

    async def slow_close(self):
        await asyncio.sleep(0.01)
        self._closed = True

    with patch.object(BitbucketClient, "close", slow_close):
        first = asyncio.create_task(src.server._drain_pending(cache))
        await asyncio.sleep(0)  # let the first drain swap the batch out and start awaiting
        cache._retire(latecomer)  # retired *during* the drain
        await first
        await src.server._drain_pending(cache)

    assert latecomer._closed is True
    # The busy one is kept, not dropped.
    assert busy in cache.pending
    assert busy._closed is False


# ========== Bearer clients surface 401/403 as a typed error ==========


@pytest.mark.asyncio
async def test_bearer_client_maps_403_to_authorization_error():
    client = BitbucketClient.from_bearer(SECRET, "acme", account_id="account-a")
    transport = httpx.MockTransport(lambda request: httpx.Response(403, json={}))
    client.client._transport = transport

    with pytest.raises(AuthorizationError) as exc:
        await client.get_repository("my-repo")

    assert exc.value.status_code == 403
    assert SECRET not in str(exc.value)
    await client.close()


@pytest.mark.asyncio
async def test_basic_client_keeps_raising_http_status_error():
    """Single-tenant behaviour is unchanged: a 403 stays an httpx.HTTPStatusError."""
    client = BitbucketClient("user@example.com", "token", "acme")
    client.client._transport = httpx.MockTransport(lambda request: httpx.Response(403, json={}))

    with pytest.raises(httpx.HTTPStatusError):
        await client.get_repository("my-repo")
    await client.close()


# ========== SDK guard-rails ==========


def test_sdk_exposes_the_private_hooks_we_rely_on():
    """Fail loudly if the SDK renames what enable_multi_tenant() assigns.

    ``_token_verifier`` is private and ``settings.auth`` is only read when the ASGI app is
    built, so a rename would silently disable authentication instead of crashing.
    """
    assert hasattr(mcp, "_token_verifier")
    assert hasattr(mcp.settings, "auth")

    from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
    from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
    from mcp.server.auth.settings import AuthSettings

    assert callable(get_access_token)
    assert AuthContextMiddleware is not None
    assert BearerAuthBackend is not None
    assert {"issuer_url", "resource_server_url"} <= set(AuthSettings.model_fields)


def test_enable_multi_tenant_wires_the_verifier():
    config = MultiTenantConfig(
        resource_server_url="https://mcp.example.com", issuer_url="https://bitbucket.org"
    )
    verifier = enable_multi_tenant(config)

    assert isinstance(verifier, BitbucketTokenVerifier)
    assert mcp._token_verifier is verifier
    assert str(mcp.settings.auth.resource_server_url).rstrip("/") == "https://mcp.example.com"
    assert str(mcp.settings.auth.issuer_url).rstrip("/") == "https://bitbucket.org"
    assert mcp.settings.auth.required_scopes is None
    assert src.server._multi_tenant is config


# ========== Transport-level integration ==========


@pytest.mark.asyncio
async def test_two_identities_through_the_real_asgi_stack(monkeypatch):
    """Push two bearer identities through the actual Streamable HTTP app.

    This is the test the unit tests above cannot replace: it exercises the SDK's real
    chain of anyio task spawns (session manager -> server run -> per-message task) and
    proves the identity contextvar survives it, so two callers really do get their own
    client. It also covers the 401 fail-closed path for an unauthenticated request.
    """
    config = MultiTenantConfig(
        resource_server_url="https://mcp.example.com", client_cache_size=8
    )
    verifier = enable_multi_tenant(config)

    identities = {
        "token-alice": ("account-alice", "ws-alice"),
        "token-bob": ("account-bob", "ws-bob"),
    }

    async def fake_verify(token):
        if token not in identities:
            return None
        account_id, workspace = identities[token]
        return make_token(account_id, workspace=workspace, token=token)

    monkeypatch.setattr(verifier, "verify_token", fake_verify)

    seen = []

    async def fake_get_repository(self, repo_slug, workspace=None):
        seen.append((self.account_id, self._resolve_workspace(workspace), id(self)))
        return {"slug": repo_slug, "workspace": {"slug": self._resolve_workspace(workspace)}}

    monkeypatch.setattr(
        "src.client.BitbucketClient.get_repository", fake_get_repository
    )

    monkeypatch.setattr(mcp.settings, "stateless_http", True)
    monkeypatch.setattr(mcp.settings, "json_response", True)
    monkeypatch.setattr(mcp.settings, "transport_security", None)
    app = mcp.streamable_http_app()

    async def call_tool(client, bearer):
        return await client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {bearer}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_repository", "arguments": {"repo_slug": "demo"}},
            },
        )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http:
            alice = await call_tool(http, "token-alice")
            bob = await call_tool(http, "token-bob")

            anonymous = await http.post(
                "/mcp",
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )

    assert alice.status_code == 200, alice.text
    assert bob.status_code == 200, bob.text
    assert anonymous.status_code == 401

    assert len(seen) == 2
    (alice_account, alice_ws, alice_client_id) = seen[0]
    (bob_account, bob_ws, bob_client_id) = seen[1]
    assert (alice_account, alice_ws) == ("account-alice", "ws-alice")
    assert (bob_account, bob_ws) == ("account-bob", "ws-bob")
    assert alice_client_id != bob_client_id

    await close_clients()


# ========== AC6 — documentation ==========


def test_deployment_modes_documentation_covers_every_mode():
    doc = Path(__file__).resolve().parent.parent / "docs" / "deployment-modes.md"
    assert doc.exists(), "docs/deployment-modes.md is the AC6 deliverable"
    text = doc.read_text().lower()
    for marker in ("stdio", "single-tenant", "multi-tenant", "threat model", "revocation"):
        assert marker in text, f"missing '{marker}' in the deployment/threat-model doc"
