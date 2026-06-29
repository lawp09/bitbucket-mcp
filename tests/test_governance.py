"""Tests for Branch Restrictions & Workspace governance tools (issue #63)."""

import json

import httpx
import pytest
import respx
from unittest.mock import AsyncMock, patch

from src.client import BitbucketClient
from src.utils.transformers import (
    slim_branch_restriction,
    slim_branch_restriction_list,
    slim_workspace_membership,
    slim_workspace_membership_list,
    slim_workspace_permission,
    slim_workspace_permission_list,
    slim_repository_permission,
    slim_repository_permission_list,
)

REPO_URL = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo"
BR = f"{REPO_URL}/branch-restrictions"
WS = "https://api.bitbucket.org/2.0/workspaces/workspace"

SAMPLE_RESTRICTION = {
    "type": "branchrestriction",
    "id": 34,
    "kind": "require_approvals_to_merge",
    "pattern": "main",
    "branch_match_kind": "glob",
    "branch_type": None,
    "value": 2,
    "users": [
        {"type": "user", "account_id": "acc-1", "uuid": "{u-1}", "display_name": "Alice"},
    ],
    "groups": [
        {"type": "group", "name": "Admins", "slug": "admins", "full_slug": "proj:admins"},
    ],
    "links": {"self": {"href": "..."}},
}

# /members returns workspace_membership objects WITHOUT a permission field.
SAMPLE_MEMBERSHIP = {
    "type": "workspace_membership",
    "user": {
        "type": "user", "account_id": "acc-1", "uuid": "{u-1}",
        "display_name": "Alice", "nickname": "alice",
    },
    "workspace": {"type": "workspace", "slug": "workspace", "name": "My Workspace"},
}

# /permissions carries the permission alongside the user.
SAMPLE_WS_PERMISSION = {
    "type": "workspace_membership",
    "permission": "owner",
    "user": {
        "type": "user", "account_id": "acc-1", "uuid": "{u-1}",
        "display_name": "Alice", "nickname": "alice",
    },
    "workspace": {"type": "workspace", "slug": "workspace"},
}

SAMPLE_REPO_PERMISSION = {
    "type": "repository_permission",
    "permission": "admin",
    "user": {"type": "user", "account_id": "acc-2", "display_name": "Bob"},
    "repository": {"type": "repository", "full_name": "workspace/my-repo", "name": "my-repo"},
}


# ========== Transformers ==========

class TestSlimBranchRestriction:
    def test_keeps_essentials(self):
        r = slim_branch_restriction(SAMPLE_RESTRICTION)
        assert r["id"] == 34
        assert r["kind"] == "require_approvals_to_merge"
        assert r["pattern"] == "main"
        assert r["branch_match_kind"] == "glob"
        assert r["value"] == 2

    def test_extracts_users_and_groups(self):
        r = slim_branch_restriction(SAMPLE_RESTRICTION)
        assert r["users"] == ["acc-1"]      # account_id preferred
        assert r["groups"] == ["admins"]    # slug preferred

    def test_empty_users_groups(self):
        r = slim_branch_restriction({"id": 1, "kind": "push"})
        assert r["users"] == []
        assert r["groups"] == []

    def test_list(self):
        r = slim_branch_restriction_list({"values": [SAMPLE_RESTRICTION], "page": 1})
        assert r["count"] == 1


class TestSlimWorkspaceMembership:
    def test_keeps_account_id_and_uuid_no_permission(self):
        r = slim_workspace_membership(SAMPLE_MEMBERSHIP)
        # GDPR identifiers must be present...
        assert r["user"]["account_id"] == "acc-1"
        assert r["user"]["uuid"] == "{u-1}"
        assert r["user"]["display_name"] == "Alice"
        # ...and there must be NO permission on a membership.
        assert "permission" not in r

    def test_no_username_leak(self):
        member = {"user": {"account_id": "a", "username": "legacy", "display_name": "X"}}
        r = slim_workspace_membership(member)
        assert "username" not in r["user"]  # deprecated field not surfaced

    def test_list(self):
        r = slim_workspace_membership_list({"values": [SAMPLE_MEMBERSHIP], "page": 1})
        assert r["count"] == 1
        assert "permission" not in r["values"][0]


class TestSlimPermissions:
    def test_workspace_permission_has_permission(self):
        r = slim_workspace_permission(SAMPLE_WS_PERMISSION)
        assert r["permission"] == "owner"
        assert r["user"]["account_id"] == "acc-1"

    def test_workspace_permission_list(self):
        r = slim_workspace_permission_list({"values": [SAMPLE_WS_PERMISSION], "page": 1})
        assert r["values"][0]["permission"] == "owner"

    def test_repository_permission(self):
        r = slim_repository_permission(SAMPLE_REPO_PERMISSION)
        assert r["permission"] == "admin"
        assert r["user"]["account_id"] == "acc-2"
        assert r["repository"] == "workspace/my-repo"

    def test_repository_permission_list(self):
        r = slim_repository_permission_list({"values": [SAMPLE_REPO_PERMISSION], "page": 1})
        assert r["count"] == 1


# ========== Client: branch restrictions ==========

@pytest.mark.asyncio
async def test_list_branch_restrictions_requires_trailing_slash():
    data = {"page": 1, "values": [SAMPLE_RESTRICTION], "size": 1}
    with respx.mock:
        route = respx.get(f"{BR}/").mock(return_value=httpx.Response(200, json=data))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_branch_restrictions("my-repo")
        assert r["values"][0]["id"] == 34
        assert "/branch-restrictions/?" in str(route.calls.last.request.url)


@pytest.mark.asyncio
async def test_list_branch_restrictions_kind_filter():
    data = {"page": 1, "values": [], "size": 0}
    with respx.mock:
        route = respx.get(f"{BR}/").mock(return_value=httpx.Response(200, json=data))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.list_branch_restrictions("my-repo", kind="push")
        assert "kind=push" in str(route.calls.last.request.url)


@pytest.mark.asyncio
async def test_get_branch_restriction():
    with respx.mock:
        respx.get(f"{BR}/34").mock(return_value=httpx.Response(200, json=SAMPLE_RESTRICTION))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.get_branch_restriction("my-repo", 34)
        assert r["id"] == 34


@pytest.mark.asyncio
async def test_create_branch_restriction_payload():
    with respx.mock:
        route = respx.post(f"{BR}/").mock(
            return_value=httpx.Response(201, json=SAMPLE_RESTRICTION)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.create_branch_restriction(
                "my-repo", "require_approvals_to_merge", "main", value=2, users=["acc-1"]
            )
        body = json.loads(route.calls.last.request.content)
        assert body["kind"] == "require_approvals_to_merge"
        assert body["pattern"] == "main"
        assert body["value"] == 2
        assert body["users"] == [{"account_id": "acc-1"}]
        assert str(route.calls.last.request.url).endswith("/branch-restrictions/")


@pytest.mark.asyncio
async def test_update_branch_restriction_includes_kind():
    with respx.mock:
        route = respx.put(f"{BR}/34").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESTRICTION)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.update_branch_restriction(
                "my-repo", 34, kind="require_approvals_to_merge", value=3
            )
        body = json.loads(route.calls.last.request.content)
        assert body == {"kind": "require_approvals_to_merge", "value": 3}


@pytest.mark.asyncio
async def test_update_branch_restriction_requires_kind():
    """The Bitbucket PUT API mandates kind — omitting it must raise, not 400."""
    async with BitbucketClient("e@x.com", "t", "workspace") as c:
        with pytest.raises(ValueError, match="kind"):
            await c.update_branch_restriction("my-repo", 34, value=3)


@pytest.mark.asyncio
async def test_delete_branch_restriction_204():
    with respx.mock:
        respx.delete(f"{BR}/34").mock(return_value=httpx.Response(204))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            assert await c.delete_branch_restriction("my-repo", 34) is None


# ========== Client: workspace (NO trailing slash) ==========

@pytest.mark.asyncio
async def test_list_workspace_members_no_trailing_slash():
    data = {"page": 1, "values": [SAMPLE_MEMBERSHIP], "size": 1}
    with respx.mock:
        route = respx.get(f"{WS}/members").mock(return_value=httpx.Response(200, json=data))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_workspace_members()
        assert r["values"][0]["user"]["account_id"] == "acc-1"
        # collection endpoint without trailing slash: ".../members?pagelen=..."
        assert "/members?" in str(route.calls.last.request.url)
        assert "/members/?" not in str(route.calls.last.request.url)


@pytest.mark.asyncio
async def test_get_workspace_member():
    with respx.mock:
        respx.get(f"{WS}/members/acc-1").mock(
            return_value=httpx.Response(200, json=SAMPLE_MEMBERSHIP)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.get_workspace_member("acc-1")
        assert r["user"]["account_id"] == "acc-1"


@pytest.mark.asyncio
async def test_list_workspace_permissions():
    data = {"page": 1, "values": [SAMPLE_WS_PERMISSION], "size": 1}
    with respx.mock:
        respx.get(f"{WS}/permissions").mock(return_value=httpx.Response(200, json=data))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_workspace_permissions()
        assert r["values"][0]["permission"] == "owner"


@pytest.mark.asyncio
async def test_list_repository_permissions():
    data = {"page": 1, "values": [SAMPLE_REPO_PERMISSION], "size": 1}
    with respx.mock:
        route = respx.get(f"{WS}/permissions/repositories/my-repo").mock(
            return_value=httpx.Response(200, json=data)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_repository_permissions("my-repo")
        assert r["values"][0]["permission"] == "admin"
        assert "/permissions/repositories/my-repo" in str(route.calls.last.request.url)


# ========== Server tools (AsyncMock) ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_branch_restrictions_tool_slims(mock_get_client):
    from src.server import list_branch_restrictions
    mock_client = AsyncMock()
    mock_client.list_branch_restrictions.return_value = {"page": 1, "values": [SAMPLE_RESTRICTION]}
    mock_get_client.return_value = mock_client
    r = await list_branch_restrictions("my-repo")
    mock_client.list_branch_restrictions.assert_awaited_once_with("my-repo", None, None, 30, 1)
    assert r["values"][0]["users"] == ["acc-1"]


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_workspace_members_tool_no_permission(mock_get_client):
    from src.server import list_workspace_members
    mock_client = AsyncMock()
    mock_client.list_workspace_members.return_value = {"page": 1, "values": [SAMPLE_MEMBERSHIP]}
    mock_get_client.return_value = mock_client
    r = await list_workspace_members()
    mock_client.list_workspace_members.assert_awaited_once_with(None, 30, 1)
    entry = r["values"][0]
    assert entry["user"]["account_id"] == "acc-1"
    assert entry["user"]["uuid"] == "{u-1}"
    assert "permission" not in entry  # members never carry a permission


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_workspace_member_tool(mock_get_client):
    from src.server import get_workspace_member
    mock_client = AsyncMock()
    mock_client.get_workspace_member.return_value = SAMPLE_MEMBERSHIP
    mock_get_client.return_value = mock_client
    r = await get_workspace_member("acc-1")
    mock_client.get_workspace_member.assert_awaited_once_with("acc-1", None)
    assert "permission" not in r  # uses membership transformer, not permission


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_workspace_permissions_tool(mock_get_client):
    from src.server import list_workspace_permissions
    mock_client = AsyncMock()
    mock_client.list_workspace_permissions.return_value = {"page": 1, "values": [SAMPLE_WS_PERMISSION]}
    mock_get_client.return_value = mock_client
    r = await list_workspace_permissions()
    mock_client.list_workspace_permissions.assert_awaited_once_with(None, 30, 1)
    assert r["values"][0]["permission"] == "owner"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_repository_permissions_tool(mock_get_client):
    from src.server import list_repository_permissions
    mock_client = AsyncMock()
    mock_client.list_repository_permissions.return_value = {"page": 1, "values": [SAMPLE_REPO_PERMISSION]}
    mock_get_client.return_value = mock_client
    r = await list_repository_permissions("my-repo")
    mock_client.list_repository_permissions.assert_awaited_once_with("my-repo", None, 30, 1)
    assert r["values"][0]["permission"] == "admin"
    assert r["values"][0]["repository"] == "workspace/my-repo"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_create_branch_restriction_tool(mock_get_client):
    from src.server import create_branch_restriction
    mock_client = AsyncMock()
    mock_client.create_branch_restriction.return_value = SAMPLE_RESTRICTION
    mock_get_client.return_value = mock_client
    r = await create_branch_restriction("my-repo", "push", "main")
    mock_client.create_branch_restriction.assert_awaited_once_with(
        "my-repo", "push", "main", None, None, None, None
    )
    assert r["id"] == 34


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_update_branch_restriction_tool(mock_get_client):
    from src.server import update_branch_restriction
    mock_client = AsyncMock()
    mock_client.update_branch_restriction.return_value = SAMPLE_RESTRICTION
    mock_get_client.return_value = mock_client
    r = await update_branch_restriction("my-repo", 34, kind="push", pattern="release/*")
    mock_client.update_branch_restriction.assert_awaited_once_with(
        "my-repo", 34, "push", "release/*", None, None, None, None
    )
    assert r["id"] == 34


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_delete_branch_restriction_tool_confirmation(mock_get_client):
    from src.server import delete_branch_restriction
    mock_client = AsyncMock()
    mock_client.delete_branch_restriction.return_value = None
    mock_get_client.return_value = mock_client
    r = await delete_branch_restriction("my-repo", 34)
    assert r == {"deleted": True, "restriction_id": 34}
