"""Tests for the multi-tenant workspace allowlist (issue #92).

Two gates: admission (the verifier refuses a caller with no membership in an allowed
workspace) and scope (no request may reach a workspace outside the allowlist, whatever
the tool arguments). Organised by gate, then end to end through the real ASGI stack.
"""

import asyncio
import logging
from unittest.mock import patch

import httpx
import pytest
import respx

import src.server
from src.auth import (
    AUDIT_LOGGER_NAME,
    BitbucketTokenVerifier,
    MultiTenantConfig,
    admit,
    is_workspace_allowed,
    parse_allowed_workspaces,
)
from src.client import AuthorizationError, BitbucketClient, scope_violation
from src.server import close_clients, enable_multi_tenant, mcp
from tests.test_multitenant import (
    SECRET,
    _is_workspaces_url,
    _response,
    _user_response,
    _workspaces_response,
)

ALLOWED = frozenset({"acme"})
API = "https://api.bitbucket.org/2.0"


@pytest.fixture(autouse=True)
def reset_multi_tenant_state():
    saved_auth = mcp.settings.auth
    saved_verifier = getattr(mcp, "_token_verifier", None)
    yield
    src.server._multi_tenant = None
    src.server._tenant_clients.clear()
    mcp.settings.auth = saved_auth
    mcp._token_verifier = saved_verifier


# ========== The rule ==========


def test_allowlist_is_normalized_and_blanks_dropped():
    assert parse_allowed_workspaces([" Acme ", "", "beta", "ACME"]) == {"acme", "beta"}


@pytest.mark.parametrize(
    "workspace,allowed,expected",
    [
        ("anything", frozenset(), True),  # no allowlist: no restriction
        ("acme", ALLOWED, True),
        ("ACME", ALLOWED, True),
        ("foreign", ALLOWED, False),
        ("{a1b2c3d4-uuid}", ALLOWED, False),  # a UUID never equals a slug
        (None, ALLOWED, False),
        ("", ALLOWED, False),
    ],
)
def test_is_workspace_allowed(workspace, allowed, expected):
    assert is_workspace_allowed(workspace, allowed) is expected


@pytest.mark.parametrize(
    "memberships,complete,allowed,expected",
    [
        (["acme"], True, frozenset(), (True, "acme")),  # unchanged without allowlist
        (["a", "b"], True, frozenset(), (True, None)),
        ([], True, frozenset(), (True, None)),
        (["acme", "other"], True, ALLOWED, (True, "acme")),  # default among the allowed
        (["Acme"], True, ALLOWED, (True, "Acme")),  # slug kept as Bitbucket lists it
        (["other"], True, ALLOWED, (False, None)),
        ([], True, ALLOWED, (False, None)),
        (["acme"], False, ALLOWED, (True, None)),  # incomplete listing: no default
        (["acme", "beta"], True, frozenset({"acme", "beta"}), (True, None)),
    ],
)
def test_admit(memberships, complete, allowed, expected):
    assert admit(memberships, complete, allowed) == expected


# ========== Admission gate (verifier) ==========


def _counting_get(user, workspaces, calls):
    async def fake_get(self, url, **kwargs):
        calls.append(str(url))
        return workspaces if _is_workspaces_url(url) else user

    return fake_get


@pytest.mark.asyncio
async def test_member_of_an_allowed_workspace_is_admitted():
    verifier = BitbucketTokenVerifier(allowed_workspaces=ALLOWED)
    with patch.object(
        httpx.AsyncClient, "get", _counting_get(_user_response(), _workspaces_response("other", "acme"), [])
    ):
        token = await verifier.verify_token(SECRET)
    assert token is not None
    assert token.identity.workspace == "acme"


@pytest.mark.asyncio
async def test_outsider_is_refused_remembered_and_audited_once(caplog):
    verifier = BitbucketTokenVerifier(allowed_workspaces=ALLOWED)
    calls = []
    with caplog.at_level(logging.WARNING, logger=AUDIT_LOGGER_NAME), patch.object(
        httpx.AsyncClient, "get", _counting_get(_user_response("outsider"), _workspaces_response("other"), calls)
    ):
        assert await verifier.verify_token(SECRET) is None
        assert await verifier.verify_token(SECRET) is None

    assert verifier.cache_size() == 0  # no identity is ever cached for a refusal
    assert len(calls) == 2  # /user + /user/workspaces once: the refusal was remembered
    refusals = [r for r in caplog.records if "admission refused" in r.getMessage()]
    assert len(refusals) == 1
    assert "account_id=outsider" in refusals[0].getMessage()
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_concurrent_refusals_share_one_verification():
    verifier = BitbucketTokenVerifier(allowed_workspaces=ALLOWED)
    calls = []
    with patch.object(
        httpx.AsyncClient, "get", _counting_get(_user_response("outsider"), _workspaces_response("other"), calls)
    ):
        results = await asyncio.gather(*(verifier.verify_token(SECRET) for _ in range(5)))
    assert results == [None] * 5
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_ttl_zero_remembers_no_refusal():
    verifier = BitbucketTokenVerifier(allowed_workspaces=ALLOWED, cache_ttl=0)
    calls = []
    with patch.object(
        httpx.AsyncClient, "get", _counting_get(_user_response("outsider"), _workspaces_response("other"), calls)
    ):
        await verifier.verify_token(SECRET)
        await verifier.verify_token(SECRET)
    assert len(calls) == 4


@pytest.mark.parametrize("status", [403, 410, 500])
@pytest.mark.asyncio
async def test_listing_failure_refuses_without_remembering(status, caplog):
    """Fail closed while the allowlist is set, but an outage is not a verdict to cache."""
    verifier = BitbucketTokenVerifier(allowed_workspaces=ALLOWED)
    calls = []
    with caplog.at_level(logging.WARNING, logger=AUDIT_LOGGER_NAME), patch.object(
        httpx.AsyncClient, "get", _counting_get(_user_response(), _response(status), calls)
    ):
        assert await verifier.verify_token(SECRET) is None
        assert await verifier.verify_token(SECRET) is None
    assert len(calls) == 4
    assert verifier.cache_size() == 0
    assert "memberships could not be listed" in caplog.text


def _paged_get(pages, calls):
    """Serve /user, then the membership pages in order; each page links to the next."""

    async def fake_get(self, url, **kwargs):
        calls.append(str(url))
        if not _is_workspaces_url(url) and "page=" not in str(url):
            return _user_response()
        index = sum(1 for c in calls if _is_workspaces_url(c) or "page=" in c) - 1
        return pages[index]

    return fake_get


def _page(slugs, next_url=None):
    body = {"values": [{"workspace": {"slug": slug}} for slug in slugs]}
    if next_url:
        body["next"] = next_url
    return _response(200, body)


@pytest.mark.asyncio
async def test_pagination_is_followed_with_an_allowlist():
    verifier = BitbucketTokenVerifier(allowed_workspaces=ALLOWED)
    calls = []
    pages = [_page(["other"], f"{API}/user/workspaces?page=2"), _page(["acme"])]
    with patch.object(httpx.AsyncClient, "get", _paged_get(pages, calls)):
        token = await verifier.verify_token(SECRET)
    assert token is not None and token.identity.workspace == "acme"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_pagination_is_not_followed_without_an_allowlist():
    verifier = BitbucketTokenVerifier()
    calls = []
    pages = [_page(["one"], f"{API}/user/workspaces?page=2"), _page(["two"])]
    with patch.object(httpx.AsyncClient, "get", _paged_get(pages, calls)):
        token = await verifier.verify_token(SECRET)
    assert token is not None and token.identity.workspace == "one"  # behaviour unchanged
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_next_link_to_another_host_is_never_followed():
    verifier = BitbucketTokenVerifier(allowed_workspaces=ALLOWED)
    calls = []
    pages = [_page(["acme"], "https://evil.example.com/steal?page=2"), _page(["x"])]
    with patch.object(httpx.AsyncClient, "get", _paged_get(pages, calls)):
        token = await verifier.verify_token(SECRET)
    assert all("evil.example.com" not in c for c in calls)
    assert token is not None
    assert token.identity.workspace is None  # admitted, but the listing is incomplete


@pytest.mark.parametrize(
    "next_url",
    ["http://api.bitbucket.org/2.0/user/workspaces?page=2", "https://api.bitbucket.org:8443/x?page=2"],
    ids=["plain-http", "other-port"],
)
@pytest.mark.asyncio
async def test_a_next_link_to_another_origin_is_never_followed(next_url):
    verifier = BitbucketTokenVerifier(allowed_workspaces=ALLOWED)
    calls = []
    pages = [_page(["acme"], next_url), _page(["x"])]
    with patch.object(httpx.AsyncClient, "get", _paged_get(pages, calls)):
        await verifier.verify_token(SECRET)
    assert next_url not in calls


@pytest.mark.parametrize("bad_next", ["http://[::1", 42])
@pytest.mark.asyncio
async def test_a_malformed_next_link_refuses_instead_of_crashing(bad_next):
    """A raise here would escape the SDK's auth backend as a 500, not the 401 it should be."""
    verifier = BitbucketTokenVerifier(allowed_workspaces=ALLOWED)
    with patch.object(httpx.AsyncClient, "get", _paged_get([_page(["other"], bad_next)], [])):
        assert await verifier.verify_token(SECRET) is None


@pytest.mark.asyncio
async def test_an_incomplete_listing_refusal_is_not_remembered(caplog):
    """Five pages without an allowed slug say nothing about the sixth: verify again."""
    verifier = BitbucketTokenVerifier(allowed_workspaces=ALLOWED)
    pages = [_page([f"ws{i}"], f"{API}/user/workspaces?page={i + 2}") for i in range(5)]
    calls = []
    with caplog.at_level(logging.WARNING, logger=AUDIT_LOGGER_NAME), patch.object(
        httpx.AsyncClient, "get", _paged_get(pages + pages, calls)
    ):
        assert await verifier.verify_token(SECRET) is None
        first_round = len(calls)
        assert await verifier.verify_token(SECRET) is None
    assert first_round == 6  # /user + the 5-page bound, no sixth page
    assert len(calls) == 12  # not remembered: verified again
    assert "no allowed workspace among the memberships listed" in caplog.text


# ========== Scope gate (client) ==========


@pytest.mark.parametrize(
    "raw_path,allowed_through",
    [
        (b"/2.0/repositories/acme/repo/pullrequests/1", True),
        (b"/2.0/workspaces/ACME/members", True),
        (b"/2.0/user", True),
        # Encoded slashes belong to the query and must pass (branch names, BBQL).
        (b'/2.0/repositories/acme/r/pullrequests?q=source.branch.name%3D%22feature%2Fx%22', True),
        (b"/2.0/repositories/foreign/repo", False),
        (b"/2.0/repositories/acme/..%2fforeign%2fx", False),
        (b"/2.0/repositories/acme/%2E%2E/foreign/x", False),
        (b"/2.0/repositories/acme/..\\foreign\\x", False),
        (b"/2.0/repositories/acme/repo/commit/abc;x", False),
        (b"/2.0/repositories/acme/repo/src/abc/a%5Cb", False),
        # A literal "%" in a file name is quoted to %25 by _src_url, and must pass.
        (b"/2.0/repositories/acme/repo/src/abc/100%2520off.txt", True),
        (b"/2.0/repositories/%7Buuid%7D/repo", False),
        (b"/2.0/repositories", False),
        (b"/2.0/user/", False),
        (b"/2.0/snippets", False),
        (b"/", False),
    ],
)
def test_scope_violation(raw_path, allowed_through):
    assert (scope_violation(raw_path, ALLOWED) is None) is allowed_through


def _client_with(transport, allowed=ALLOWED, workspace="acme"):
    client = BitbucketClient.from_bearer(
        SECRET, workspace, account_id="account-a", allowed_workspaces=allowed
    )
    client.client._transport = transport
    return client


def _recording_transport(sent):
    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(200, json={"slug": "repo"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_default_and_explicit_allowed_workspace_reach_bitbucket():
    sent = []
    client = _client_with(_recording_transport(sent))
    await client.get_repository("repo")
    await client.get_repository("repo", workspace="ACME")
    assert len(sent) == 2
    await client.close()


@pytest.mark.asyncio
async def test_explicit_foreign_workspace_is_refused_before_sending(caplog):
    sent = []
    client = _client_with(_recording_transport(sent))
    with caplog.at_level(logging.WARNING, logger=AUDIT_LOGGER_NAME):
        with pytest.raises(AuthorizationError) as exc:
            await client.get_repository("repo", workspace="foreign")
    assert sent == []
    assert "foreign" in str(exc.value)
    assert "acme" not in str(exc.value)  # the allowlist itself is never disclosed
    assert "scope refused account_id=account-a" in caplog.text
    await client.close()


@pytest.mark.parametrize("repo_slug", ["../foreign/x", "..\\foreign\\x", "%2e%2e/foreign/x"])
@pytest.mark.asyncio
async def test_path_traversal_through_repo_slug_is_refused(repo_slug):
    """httpx collapses '/../' before sending: only a check on the final path catches it."""
    sent = []
    client = _client_with(_recording_transport(sent))
    with pytest.raises(AuthorizationError):
        await client.get_repository(repo_slug)
    assert sent == []
    await client.close()


@pytest.mark.asyncio
async def test_query_with_encoded_slashes_passes():
    sent = []
    client = _client_with(_recording_transport(sent))
    await client.client.get(
        "/repositories/acme/repo/pullrequests", params={"q": 'source.branch.name="feature/x"'}
    )
    assert len(sent) == 1
    await client.close()


@pytest.mark.asyncio
async def test_redirect_to_storage_without_the_token_passes():
    """The hop httpx strips Authorization from carries no credential: nothing to scope."""
    sent = []

    def handler(request):
        sent.append(str(request.url))
        if request.url.host == "api.bitbucket.org":
            return httpx.Response(307, headers={"Location": "https://storage.example.com/log?sig=x"})
        return httpx.Response(200, content=b"log")

    client = _client_with(httpx.MockTransport(handler))
    response = await client.client.get("/repositories/acme/repo/log", follow_redirects=True)
    assert response.status_code == 200
    assert len(sent) == 2
    await client.close()


@pytest.mark.asyncio
async def test_same_origin_redirect_to_a_foreign_workspace_is_refused():
    """The hook runs before every redirect leg that still carries the token."""
    sent = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(302, headers={"Location": "/2.0/repositories/foreign/repo/diff/x"})

    client = _client_with(httpx.MockTransport(handler))
    with pytest.raises(AuthorizationError):
        await client.get_pull_request_diff("repo", "1")
    assert sent == [f"{API}/repositories/acme/repo/pullrequests/1/diff"]
    await client.close()


@pytest.mark.asyncio
async def test_pagination_next_link_to_a_foreign_workspace_is_refused():
    sent = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(
            200,
            json={"values": [{"slug": "a"}], "next": f"{API}/repositories/foreign?page=2"},
        )

    client = _client_with(httpx.MockTransport(handler))
    with pytest.raises(AuthorizationError):
        await client.list_repositories(max_pages=2)
    assert len(sent) == 1
    await client.close()


@pytest.mark.asyncio
async def test_a_request_carrying_the_token_to_another_host_is_refused():
    sent = []
    client = _client_with(_recording_transport(sent))
    with pytest.raises(AuthorizationError):
        await client.client.get("https://evil.example.com/2.0/repositories/acme/repo")
    assert sent == []
    await client.close()


@pytest.mark.asyncio
async def test_stream_and_write_requests_are_scoped_too():
    sent = []
    client = _client_with(_recording_transport(sent))
    with pytest.raises(AuthorizationError):
        async with client.client.stream("GET", "/repositories/foreign/repo/src/x"):
            pass
    with pytest.raises(AuthorizationError):
        await client.add_pull_request_comment("../foreign/repo", "1", "hello")
    await client.add_pull_request_comment("repo", "1", "hello")
    assert sent == [f"{API}/repositories/acme/repo/pullrequests/1/comments"]
    await client.close()


@pytest.mark.asyncio
async def test_no_allowlist_installs_no_scope_hook():
    sent = []
    client = _client_with(_recording_transport(sent), allowed=frozenset())
    await client.get_repository("repo", workspace="foreign")
    assert len(sent) == 1
    assert client.client.event_hooks["request"] == []
    await client.close()


# ========== Wiring ==========


def test_enable_multi_tenant_warns_without_an_allowlist(caplog):
    with caplog.at_level(logging.WARNING, logger="src.server"):
        enable_multi_tenant(MultiTenantConfig(resource_server_url="https://mcp.example.com"))
    assert "any Bitbucket account is admitted" in caplog.text


def test_enable_multi_tenant_passes_the_allowlist_to_the_verifier(caplog):
    with caplog.at_level(logging.WARNING, logger="src.server"):
        verifier = enable_multi_tenant(
            MultiTenantConfig(resource_server_url="https://mcp.example.com", allowed_workspaces=ALLOWED)
        )
    assert verifier._allowed_workspaces == ALLOWED
    assert "any Bitbucket account is admitted" not in caplog.text


# ========== End to end through the real ASGI stack ==========


@pytest.mark.asyncio
async def test_member_outsider_and_foreign_workspace_through_the_asgi_stack(monkeypatch):
    """Real verifier, real tool wrapper: Bitbucket is the only thing mocked."""
    verifier = enable_multi_tenant(
        MultiTenantConfig(
            resource_server_url="https://mcp.example.com",
            client_cache_size=8,
            allowed_workspaces=ALLOWED,
        )
    )
    monkeypatch.setattr(mcp.settings, "stateless_http", True)
    monkeypatch.setattr(mcp.settings, "json_response", True)
    monkeypatch.setattr(mcp.settings, "transport_security", None)
    monkeypatch.setattr(mcp, "_session_manager", None)
    app = mcp.streamable_http_app()

    def by_bearer(member, outsider):
        def respond(request):
            token = request.headers["Authorization"].removeprefix("Bearer ")
            return member if token == "token-member" else outsider

        return respond

    async def call(http, bearer, arguments):
        return await http.post(
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
                "params": {"name": "get_repository", "arguments": arguments},
            },
        )

    with respx.mock(assert_all_called=False) as bitbucket:
        bitbucket.get(f"{API}/user").mock(
            side_effect=by_bearer(
                httpx.Response(200, json={"account_id": "member"}),
                httpx.Response(200, json={"account_id": "outsider"}),
            )
        )
        bitbucket.get(f"{API}/user/workspaces").mock(
            side_effect=by_bearer(
                httpx.Response(200, json={"values": [{"workspace": {"slug": "acme"}}]}),
                httpx.Response(200, json={"values": [{"workspace": {"slug": "other"}}]}),
            )
        )
        repo_route = bitbucket.get(url__regex=rf"{API}/repositories/.*").mock(
            return_value=httpx.Response(200, json={"slug": "demo", "full_name": "acme/demo"})
        )

        audit = logging.getLogger(AUDIT_LOGGER_NAME)
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        audit.addHandler(handler)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as http:
                outsider = await call(http, "token-outsider", {"repo_slug": "demo"})
                member = await call(http, "token-member", {"repo_slug": "demo"})
                foreign = await call(
                    http, "token-member", {"repo_slug": "demo", "workspace": "foreign"}
                )

    audit.removeHandler(handler)
    assert outsider.status_code == 401
    messages = [r.getMessage() for r in records]
    assert any("admission refused account_id=outsider" in m for m in messages)
    assert any("scope refused account_id=member" in m for m in messages)
    assert member.status_code == 200, member.text
    assert member.json()["result"].get("isError") is not True
    assert foreign.json()["result"]["isError"] is True
    # Only the member's allowed call reached a repository endpoint.
    assert [str(c.request.url) for c in repo_route.calls] == [f"{API}/repositories/acme/demo"]
    # One identity cached (the member); the outsider left no identity and no client.
    assert verifier.cache_size() == 1
    accounts = {
        account
        for cache in src.server._tenant_clients.values()
        for (account, _) in list(cache._entries)
    }
    assert accounts == {"member"}
    await close_clients()
