"""Tests for the Deployments & Environments tools (issue #61)."""

import json

import httpx
import pytest
import respx
from unittest.mock import AsyncMock, patch

from src.client import BitbucketClient
from src.utils.transformers import (
    slim_environment,
    slim_environment_list,
    slim_deployment,
    slim_deployment_list,
    slim_deployment_variable,
    slim_deployment_variable_list,
)

REPO_URL = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo"
ENVS = f"{REPO_URL}/environments"          # collection requires a trailing slash
DEPS = f"{REPO_URL}/deployments"           # collection requires a trailing slash
DCFG = f"{REPO_URL}/deployments_config"    # underscore, like pipelines_config

ENV_UUID = "{env-1}"
ENV_UUID_ENC = "%7Benv-1%7D"

SAMPLE_ENV = {
    "type": "deployment_environment",
    "uuid": "{env-1}",
    "name": "Staging",
    "slug": "staging",
    "rank": 1,
    "hidden": False,
    "environment_type": {"name": "Staging", "rank": 1},
}

# Real deployment shape: state.name is the phase, state.status.name the sub-result,
# and the deployed commit lives under deployable.commit.hash.
SAMPLE_DEPLOYMENT = {
    "type": "deployment",
    "uuid": "{dep-1}",
    "state": {
        "type": "deployment_state_completed",
        "name": "COMPLETED",
        "status": {"type": "deployment_status_successful", "name": "SUCCESSFUL"},
    },
    "environment": {"uuid": "{env-1}", "name": "Staging"},
    "release": {"name": "1.2.3", "commit": {"hash": "deadbeefcafebabe1234"}},
    "deployable": {"commit": {"hash": "0123456789abcdef9999"}},
    "created_on": "2026-06-01T10:00:00+00:00",
    "last_update_time": "2026-06-01T10:05:00+00:00",
}

SAMPLE_VAR_PLAIN = {
    "uuid": "{var-1}", "key": "REGION", "value": "ca-central-1",
    "secured": False, "type": "pipeline_variable",
}
# Secured variables: the API omits "value" entirely.
SAMPLE_VAR_SECURED = {
    "uuid": "{var-2}", "key": "API_TOKEN", "secured": True,
    "type": "pipeline_variable",
}


# ========== Transformers ==========

class TestSlimEnvironment:
    def test_keeps_essentials(self):
        r = slim_environment(SAMPLE_ENV)
        assert r == {
            "uuid": "{env-1}", "name": "Staging", "environment_type": "Staging",
            "slug": "staging", "rank": 1, "hidden": False,
        }

    def test_missing_environment_type(self):
        r = slim_environment({"uuid": "{e}", "name": "X"})
        assert r["environment_type"] is None
        assert r["hidden"] is False  # defaulted

    def test_list(self):
        r = slim_environment_list({"values": [SAMPLE_ENV], "page": 1})
        assert r["count"] == 1
        assert r["values"][0]["name"] == "Staging"


class TestSlimDeployment:
    def test_reads_status_not_result(self):
        """Deployments use state.status.name (NOT state.result.name like pipelines)."""
        r = slim_deployment(SAMPLE_DEPLOYMENT)
        assert r["state"] == "COMPLETED"
        assert r["status"] == "SUCCESSFUL"

    def test_commit_from_deployable(self):
        """Canonical commit hash comes from deployable.commit.hash (12-char trim)."""
        r = slim_deployment(SAMPLE_DEPLOYMENT)
        assert r["commit"] == "0123456789ab"
        assert r["environment"] == "Staging"
        assert r["environment_uuid"] == "{env-1}"
        assert r["release_name"] == "1.2.3"

    def test_commit_falls_back_to_release_then_commit(self):
        dep = {"release": {"commit": {"hash": "abcdef123456ffff"}}}
        assert slim_deployment(dep)["commit"] == "abcdef123456"
        dep2 = {"commit": {"hash": "fedcba654321ffff"}}
        assert slim_deployment(dep2)["commit"] == "fedcba654321"

    def test_in_progress_null_status(self):
        """A running deployment has state.status = null — must not crash."""
        dep = {"uuid": "{d}", "state": {"name": "IN_PROGRESS", "status": None}}
        r = slim_deployment(dep)
        assert r["state"] == "IN_PROGRESS"
        assert r["status"] is None
        assert r["commit"] is None  # no commit anywhere

    def test_list(self):
        r = slim_deployment_list({"values": [SAMPLE_DEPLOYMENT], "page": 1})
        assert r["count"] == 1


class TestSlimDeploymentVariable:
    def test_plain_keeps_value(self):
        r = slim_deployment_variable(SAMPLE_VAR_PLAIN)
        assert r == {"uuid": "{var-1}", "key": "REGION",
                     "value": "ca-central-1", "secured": False}

    def test_secured_masks_value(self):
        r = slim_deployment_variable(SAMPLE_VAR_SECURED)
        assert r["secured"] is True
        assert r["value"] is None

    def test_secured_masks_even_if_value_leaks(self):
        leaked = {**SAMPLE_VAR_SECURED, "value": "super-secret"}
        assert slim_deployment_variable(leaked)["value"] is None

    def test_list(self):
        data = {"values": [SAMPLE_VAR_PLAIN, SAMPLE_VAR_SECURED], "page": 1}
        r = slim_deployment_variable_list(data)
        assert r["count"] == 2
        assert r["values"][1]["value"] is None


# ========== Client: environments ==========

@pytest.mark.asyncio
async def test_list_environments_requires_trailing_slash():
    data = {"page": 1, "values": [SAMPLE_ENV], "size": 1}
    with respx.mock:
        route = respx.get(f"{ENVS}/").mock(return_value=httpx.Response(200, json=data))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_environments("my-repo")
        assert r["values"][0]["name"] == "Staging"
        url = str(route.calls.last.request.url)
        assert "/environments/?" in url  # trailing slash preserved before query string


@pytest.mark.asyncio
async def test_get_environment():
    with respx.mock:
        respx.get(f"{ENVS}/{ENV_UUID_ENC}").mock(
            return_value=httpx.Response(200, json=SAMPLE_ENV)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.get_environment("my-repo", ENV_UUID)
        assert r["uuid"] == "{env-1}"


@pytest.mark.asyncio
async def test_create_environment_payload():
    with respx.mock:
        route = respx.post(f"{ENVS}/").mock(
            return_value=httpx.Response(201, json=SAMPLE_ENV)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.create_environment("my-repo", "Staging", "Staging")
        body = json.loads(route.calls.last.request.content)
        assert body == {"name": "Staging", "environment_type": {"name": "Staging"}}
        assert str(route.calls.last.request.url).endswith("/environments/")


@pytest.mark.asyncio
async def test_delete_environment_204_returns_none():
    with respx.mock:
        respx.delete(f"{ENVS}/{ENV_UUID_ENC}").mock(return_value=httpx.Response(204))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            assert await c.delete_environment("my-repo", ENV_UUID) is None


# ========== Client: deployments ==========

@pytest.mark.asyncio
async def test_list_deployments_trailing_slash():
    data = {"page": 1, "values": [SAMPLE_DEPLOYMENT], "size": 1}
    with respx.mock:
        route = respx.get(f"{DEPS}/").mock(return_value=httpx.Response(200, json=data))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_deployments("my-repo")
        assert r["values"][0]["uuid"] == "{dep-1}"
        assert "/deployments/?" in str(route.calls.last.request.url)


@pytest.mark.asyncio
async def test_get_deployment():
    with respx.mock:
        respx.get(f"{DEPS}/%7Bdep-1%7D").mock(
            return_value=httpx.Response(200, json=SAMPLE_DEPLOYMENT)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.get_deployment("my-repo", "{dep-1}")
        assert r["state"]["name"] == "COMPLETED"


# ========== Client: deployment variables (UNDERSCORE path) ==========

@pytest.mark.asyncio
async def test_list_deployment_variables_uses_underscore_path():
    data = {"page": 1, "values": [SAMPLE_VAR_PLAIN], "size": 1}
    url = f"{DCFG}/environments/{ENV_UUID_ENC}/variables"
    with respx.mock:
        route = respx.get(url).mock(return_value=httpx.Response(200, json=data))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_deployment_variables("my-repo", ENV_UUID)
        assert r["values"][0]["key"] == "REGION"
        full = str(route.calls.last.request.url)
        assert "/deployments_config/" in full       # underscore
        assert "/deployments-config/" not in full   # not hyphen


@pytest.mark.asyncio
async def test_create_deployment_variable_payload():
    url = f"{DCFG}/environments/{ENV_UUID_ENC}/variables"
    with respx.mock:
        route = respx.post(url).mock(
            return_value=httpx.Response(201, json=SAMPLE_VAR_SECURED)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.create_deployment_variable("my-repo", ENV_UUID, "API_TOKEN", "abc", secured=True)
        body = json.loads(route.calls.last.request.content)
        assert body == {"key": "API_TOKEN", "value": "abc", "secured": True}


@pytest.mark.asyncio
async def test_update_deployment_variable_partial_payload():
    url = f"{DCFG}/environments/{ENV_UUID_ENC}/variables/%7Bvar-1%7D"
    with respx.mock:
        route = respx.put(url).mock(return_value=httpx.Response(200, json=SAMPLE_VAR_PLAIN))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.update_deployment_variable("my-repo", ENV_UUID, "{var-1}", value="us-east-1")
        body = json.loads(route.calls.last.request.content)
        assert body == {"value": "us-east-1"}  # only provided field sent


@pytest.mark.asyncio
async def test_update_deployment_variable_no_fields_raises():
    async with BitbucketClient("e@x.com", "t", "workspace") as c:
        with pytest.raises(ValueError, match="at least one"):
            await c.update_deployment_variable("my-repo", ENV_UUID, "{var-1}")


@pytest.mark.asyncio
async def test_delete_deployment_variable_204():
    url = f"{DCFG}/environments/{ENV_UUID_ENC}/variables/%7Bvar-1%7D"
    with respx.mock:
        respx.delete(url).mock(return_value=httpx.Response(204))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            assert await c.delete_deployment_variable("my-repo", ENV_UUID, "{var-1}") is None


# ========== Server tools (AsyncMock) ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_environments_tool_slims(mock_get_client):
    from src.server import list_environments
    mock_client = AsyncMock()
    mock_client.list_environments.return_value = {"page": 1, "values": [SAMPLE_ENV]}
    mock_get_client.return_value = mock_client
    r = await list_environments("my-repo")
    assert r["values"][0]["environment_type"] == "Staging"
    assert "type" not in r["values"][0]  # nested API noise dropped


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_deployment_tool_slims(mock_get_client):
    from src.server import get_deployment
    mock_client = AsyncMock()
    mock_client.get_deployment.return_value = SAMPLE_DEPLOYMENT
    mock_get_client.return_value = mock_client
    r = await get_deployment("my-repo", "{dep-1}")
    assert r["status"] == "SUCCESSFUL"
    assert r["commit"] == "0123456789ab"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_deployment_variables_tool_masks_secured(mock_get_client):
    from src.server import list_deployment_variables
    mock_client = AsyncMock()
    mock_client.list_deployment_variables.return_value = {
        "page": 1, "values": [SAMPLE_VAR_PLAIN, {**SAMPLE_VAR_SECURED, "value": "leak"}]
    }
    mock_get_client.return_value = mock_client
    r = await list_deployment_variables("my-repo", ENV_UUID)
    assert r["count"] == 2
    assert r["values"][1]["value"] is None  # secured masked through the tool


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_create_deployment_variable_tool_masks_secured(mock_get_client):
    from src.server import create_deployment_variable
    mock_client = AsyncMock()
    mock_client.create_deployment_variable.return_value = {**SAMPLE_VAR_SECURED, "value": "leak"}
    mock_get_client.return_value = mock_client
    r = await create_deployment_variable("my-repo", ENV_UUID, "API_TOKEN", "abc", secured=True)
    mock_client.create_deployment_variable.assert_awaited_once_with(
        "my-repo", ENV_UUID, "API_TOKEN", "abc", True, None
    )
    assert r["value"] is None  # secured masked through the tool


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_update_deployment_variable_tool_masks_secured(mock_get_client):
    from src.server import update_deployment_variable
    mock_client = AsyncMock()
    mock_client.update_deployment_variable.return_value = {**SAMPLE_VAR_SECURED, "value": "leak"}
    mock_get_client.return_value = mock_client
    r = await update_deployment_variable("my-repo", ENV_UUID, "{var-2}", value="new")
    mock_client.update_deployment_variable.assert_awaited_once_with(
        "my-repo", ENV_UUID, "{var-2}", None, "new", None, None
    )
    assert r["value"] is None


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_delete_environment_tool_confirmation(mock_get_client):
    from src.server import delete_environment
    mock_client = AsyncMock()
    mock_client.delete_environment.return_value = None
    mock_get_client.return_value = mock_client
    r = await delete_environment("my-repo", ENV_UUID)
    assert r == {"deleted": True, "environment_uuid": ENV_UUID}


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_delete_deployment_variable_tool_confirmation(mock_get_client):
    from src.server import delete_deployment_variable
    mock_client = AsyncMock()
    mock_client.delete_deployment_variable.return_value = None
    mock_get_client.return_value = mock_client
    r = await delete_deployment_variable("my-repo", ENV_UUID, "{var-1}")
    assert r == {"deleted": True, "variable_uuid": "{var-1}"}


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_create_environment_tool(mock_get_client):
    from src.server import create_environment
    mock_client = AsyncMock()
    mock_client.create_environment.return_value = SAMPLE_ENV
    mock_get_client.return_value = mock_client
    r = await create_environment("my-repo", "Staging", "Staging")
    mock_client.create_environment.assert_awaited_once_with(
        "my-repo", "Staging", "Staging", None
    )
    assert r["name"] == "Staging"
