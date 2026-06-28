"""Tests for the Lot 2 Pipelines Config tools (variables, schedules, caches)."""

import json

import httpx
import pytest
import respx
from unittest.mock import AsyncMock, patch

from src.client import BitbucketClient
from src.utils.transformers import (
    slim_pipeline_config,
    slim_pipeline_variable,
    slim_pipeline_variable_list,
    slim_pipeline_schedule,
    slim_pipeline_schedule_list,
    slim_pipeline_schedule_execution,
    slim_pipeline_schedule_execution_list,
    slim_pipeline_cache,
    slim_pipeline_cache_list,
)

REPO_URL = "https://api.bitbucket.org/2.0/repositories/workspace/my-repo"
CFG = f"{REPO_URL}/pipelines_config"

SAMPLE_CONFIG = {
    "type": "pipelines_config",
    "enabled": True,
    "repository": {"full_name": "workspace/my-repo"},
    "build_number_settings": {"next_build_number": 42},
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

SAMPLE_SCHEDULE = {
    "uuid": "{sched-1}",
    "enabled": True,
    "cron_pattern": "0 0 6 * * ? *",
    "target": {
        "ref_name": "main", "ref_type": "branch",
        "selector": {"type": "branches", "pattern": "main"},
    },
    "created_on": "2026-06-01T10:00:00+00:00",
    "updated_on": "2026-06-02T10:00:00+00:00",
}

SAMPLE_EXECUTION = {
    "state": {"name": "COMPLETED", "result": {"name": "SUCCESSFUL"}},
    "pipeline": {"uuid": "{pipe-9}", "build_number": 17},
    "created_on": "2026-06-03T06:00:00+00:00",
}

SAMPLE_CACHE = {
    "uuid": "{cache-1}", "name": "node", "path": "node_modules",
    "file_size_bytes": 123456, "created_on": "2026-06-01T00:00:00+00:00",
    "key_hash": "abcdef",
}


# ========== Transformers ==========

class TestSlimConfig:
    def test_keeps_essentials(self):
        r = slim_pipeline_config(SAMPLE_CONFIG)
        assert r == {"enabled": True, "next_build_number": 42}

    def test_missing_build_settings(self):
        r = slim_pipeline_config({"enabled": False})
        assert r == {"enabled": False, "next_build_number": None}


class TestSlimVariable:
    def test_plain_keeps_value(self):
        r = slim_pipeline_variable(SAMPLE_VAR_PLAIN)
        assert r == {"uuid": "{var-1}", "key": "REGION",
                     "value": "ca-central-1", "secured": False}

    def test_secured_masks_value(self):
        r = slim_pipeline_variable(SAMPLE_VAR_SECURED)
        assert r["secured"] is True
        assert r["value"] is None
        assert r["key"] == "API_TOKEN"

    def test_secured_masks_even_if_value_leaks(self):
        leaked = {**SAMPLE_VAR_SECURED, "value": "super-secret"}
        r = slim_pipeline_variable(leaked)
        assert r["value"] is None

    def test_list(self):
        data = {"values": [SAMPLE_VAR_PLAIN, SAMPLE_VAR_SECURED], "page": 1}
        r = slim_pipeline_variable_list(data)
        assert r["count"] == 2
        assert r["values"][1]["value"] is None


class TestSlimScheduleAndCache:
    def test_schedule(self):
        r = slim_pipeline_schedule(SAMPLE_SCHEDULE)
        assert r["uuid"] == "{sched-1}"
        assert r["cron_pattern"] == "0 0 6 * * ? *"
        assert r["target_ref"] == "main"
        assert r["selector_pattern"] == "main"

    def test_schedule_list(self):
        r = slim_pipeline_schedule_list({"values": [SAMPLE_SCHEDULE], "page": 1})
        assert r["count"] == 1

    def test_execution(self):
        r = slim_pipeline_schedule_execution(SAMPLE_EXECUTION)
        assert r["state"] == "COMPLETED"
        assert r["state_result"] == "SUCCESSFUL"
        assert r["build_number"] == 17

    def test_execution_list(self):
        r = slim_pipeline_schedule_execution_list({"values": [SAMPLE_EXECUTION], "page": 1})
        assert r["count"] == 1

    def test_execution_in_progress_null_result(self):
        """An in-progress execution has result=null — must not crash."""
        ex = {"state": {"name": "IN_PROGRESS", "result": None},
              "pipeline": {"uuid": "{p}", "build_number": 1}}
        r = slim_pipeline_schedule_execution(ex)
        assert r["state"] == "IN_PROGRESS"
        assert r["state_result"] is None

    def test_cache(self):
        r = slim_pipeline_cache(SAMPLE_CACHE)
        assert r == {"uuid": "{cache-1}", "name": "node", "path": "node_modules",
                     "file_size_bytes": 123456, "created_on": "2026-06-01T00:00:00+00:00"}
        assert "key_hash" not in r

    def test_cache_list(self):
        r = slim_pipeline_cache_list({"values": [SAMPLE_CACHE], "page": 1})
        assert r["count"] == 1


# ========== Client: variables ==========

@pytest.mark.asyncio
async def test_get_pipeline_config():
    with respx.mock:
        respx.get(CFG).mock(return_value=httpx.Response(200, json=SAMPLE_CONFIG))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.get_pipeline_config("my-repo")
        assert r["enabled"] is True


@pytest.mark.asyncio
async def test_list_pipeline_variables_empty():
    empty = {"page": 1, "values": [], "size": 0, "pagelen": 0}
    with respx.mock:
        respx.get(f"{CFG}/variables").mock(return_value=httpx.Response(200, json=empty))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_pipeline_variables("my-repo")
        assert r["values"] == []


@pytest.mark.asyncio
async def test_get_pipeline_variable():
    with respx.mock:
        respx.get(f"{CFG}/variables/%7Bvar-1%7D").mock(
            return_value=httpx.Response(200, json=SAMPLE_VAR_PLAIN)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.get_pipeline_variable("my-repo", "{var-1}")
        assert r["key"] == "REGION"


@pytest.mark.asyncio
async def test_create_pipeline_variable_payload():
    with respx.mock:
        route = respx.post(f"{CFG}/variables").mock(
            return_value=httpx.Response(201, json=SAMPLE_VAR_SECURED)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.create_pipeline_variable("my-repo", "API_TOKEN", "abc", secured=True)
        body = json.loads(route.calls.last.request.content)
        assert body == {"key": "API_TOKEN", "value": "abc", "secured": True}


@pytest.mark.asyncio
async def test_update_pipeline_variable_partial_payload():
    with respx.mock:
        route = respx.put(f"{CFG}/variables/%7Bvar-1%7D").mock(
            return_value=httpx.Response(200, json=SAMPLE_VAR_PLAIN)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.update_pipeline_variable("my-repo", "{var-1}", value="us-east-1")
        body = json.loads(route.calls.last.request.content)
        assert body == {"value": "us-east-1"}  # only provided field sent


@pytest.mark.asyncio
async def test_update_pipeline_variable_all_fields():
    with respx.mock:
        route = respx.put(f"{CFG}/variables/%7Bvar-1%7D").mock(
            return_value=httpx.Response(200, json=SAMPLE_VAR_PLAIN)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.update_pipeline_variable(
                "my-repo", "{var-1}", key="REGION", value="us-east-1", secured=True
            )
        body = json.loads(route.calls.last.request.content)
        assert body == {"key": "REGION", "value": "us-east-1", "secured": True}


@pytest.mark.asyncio
async def test_update_pipeline_variable_no_fields_raises():
    """An update with no field would PUT {} — must raise before any HTTP call."""
    async with BitbucketClient("e@x.com", "t", "workspace") as c:
        with pytest.raises(ValueError, match="at least one"):
            await c.update_pipeline_variable("my-repo", "{var-1}")


@pytest.mark.asyncio
async def test_delete_pipeline_variable_204_returns_none():
    with respx.mock:
        respx.delete(f"{CFG}/variables/%7Bvar-1%7D").mock(
            return_value=httpx.Response(204)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            result = await c.delete_pipeline_variable("my-repo", "{var-1}")
        assert result is None


# ========== Client: schedules ==========

@pytest.mark.asyncio
async def test_list_pipeline_schedules():
    data = {"page": 1, "values": [SAMPLE_SCHEDULE], "size": 1}
    with respx.mock:
        respx.get(f"{CFG}/schedules").mock(return_value=httpx.Response(200, json=data))
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_pipeline_schedules("my-repo")
        assert r["values"][0]["uuid"] == "{sched-1}"


@pytest.mark.asyncio
async def test_get_pipeline_schedule():
    with respx.mock:
        respx.get(f"{CFG}/schedules/%7Bsched-1%7D").mock(
            return_value=httpx.Response(200, json=SAMPLE_SCHEDULE)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.get_pipeline_schedule("my-repo", "{sched-1}")
        assert r["uuid"] == "{sched-1}"


@pytest.mark.asyncio
async def test_list_schedule_executions():
    data = {"page": 1, "values": [SAMPLE_EXECUTION], "size": 1}
    with respx.mock:
        respx.get(f"{CFG}/schedules/%7Bsched-1%7D/executions").mock(
            return_value=httpx.Response(200, json=data)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_pipeline_schedule_executions("my-repo", "{sched-1}")
        assert len(r["values"]) == 1


@pytest.mark.asyncio
async def test_create_pipeline_schedule_payload():
    with respx.mock:
        route = respx.post(f"{CFG}/schedules").mock(
            return_value=httpx.Response(201, json=SAMPLE_SCHEDULE)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.create_pipeline_schedule("my-repo", "main", "0 0 6 * * ? *")
        body = json.loads(route.calls.last.request.content)
        assert body["cron_pattern"] == "0 0 6 * * ? *"
        assert body["enabled"] is True
        assert body["target"]["ref_name"] == "main"
        assert body["target"]["selector"]["pattern"] == "main"


@pytest.mark.asyncio
async def test_update_pipeline_schedule_partial():
    with respx.mock:
        route = respx.put(f"{CFG}/schedules/%7Bsched-1%7D").mock(
            return_value=httpx.Response(200, json=SAMPLE_SCHEDULE)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.update_pipeline_schedule("my-repo", "{sched-1}", enabled=False)
        body = json.loads(route.calls.last.request.content)
        assert body == {"enabled": False}


@pytest.mark.asyncio
async def test_update_pipeline_schedule_cron():
    with respx.mock:
        route = respx.put(f"{CFG}/schedules/%7Bsched-1%7D").mock(
            return_value=httpx.Response(200, json=SAMPLE_SCHEDULE)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            await c.update_pipeline_schedule(
                "my-repo", "{sched-1}", cron_pattern="0 0 12 * * ? *"
            )
        body = json.loads(route.calls.last.request.content)
        assert body == {"cron_pattern": "0 0 12 * * ? *"}


@pytest.mark.asyncio
async def test_update_pipeline_schedule_no_fields_raises():
    async with BitbucketClient("e@x.com", "t", "workspace") as c:
        with pytest.raises(ValueError, match="at least one"):
            await c.update_pipeline_schedule("my-repo", "{sched-1}")


@pytest.mark.asyncio
async def test_delete_pipeline_schedule_204():
    with respx.mock:
        respx.delete(f"{CFG}/schedules/%7Bsched-1%7D").mock(
            return_value=httpx.Response(204)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            assert await c.delete_pipeline_schedule("my-repo", "{sched-1}") is None


# ========== Client: caches (HYPHEN path) ==========

@pytest.mark.asyncio
async def test_list_pipeline_caches_uses_hyphen_path():
    data = {"page": 1, "values": [SAMPLE_CACHE], "size": 1}
    with respx.mock:
        route = respx.get(f"{REPO_URL}/pipelines-config/caches").mock(
            return_value=httpx.Response(200, json=data)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            r = await c.list_pipeline_caches("my-repo")
        assert r["values"][0]["name"] == "node"
        url = str(route.calls.last.request.url)
        assert "/pipelines-config/caches" in url       # hyphen
        assert "/pipelines_config/caches" not in url   # not underscore


@pytest.mark.asyncio
async def test_delete_pipeline_cache_hyphen_204():
    with respx.mock:
        route = respx.delete(f"{REPO_URL}/pipelines-config/caches/%7Bcache-1%7D").mock(
            return_value=httpx.Response(204)
        )
        async with BitbucketClient("e@x.com", "t", "workspace") as c:
            assert await c.delete_pipeline_cache("my-repo", "{cache-1}") is None
        assert "/pipelines-config/caches" in str(route.calls.last.request.url)


# ========== Server tools (AsyncMock) ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_pipeline_config_tool(mock_get_client):
    from src.server import get_pipeline_config
    mock_client = AsyncMock()
    mock_client.get_pipeline_config.return_value = SAMPLE_CONFIG
    mock_get_client.return_value = mock_client
    r = await get_pipeline_config("my-repo")
    assert r == {"enabled": True, "next_build_number": 42}


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_pipeline_variables_tool_masks_secured(mock_get_client):
    from src.server import list_pipeline_variables
    mock_client = AsyncMock()
    mock_client.list_pipeline_variables.return_value = {
        "page": 1, "values": [SAMPLE_VAR_PLAIN, {**SAMPLE_VAR_SECURED, "value": "leak"}]
    }
    mock_get_client.return_value = mock_client
    r = await list_pipeline_variables("my-repo")
    assert r["count"] == 2
    assert r["values"][1]["value"] is None  # secured masked through the tool


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_pipeline_variable_tool_masks_secured(mock_get_client):
    from src.server import get_pipeline_variable
    mock_client = AsyncMock()
    mock_client.get_pipeline_variable.return_value = {**SAMPLE_VAR_SECURED, "value": "leak"}
    mock_get_client.return_value = mock_client
    r = await get_pipeline_variable("my-repo", "{var-2}")
    assert r["secured"] is True
    assert r["value"] is None


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_delete_pipeline_variable_tool_confirmation(mock_get_client):
    from src.server import delete_pipeline_variable
    mock_client = AsyncMock()
    mock_client.delete_pipeline_variable.return_value = None
    mock_get_client.return_value = mock_client
    r = await delete_pipeline_variable("my-repo", "{var-1}")
    assert r == {"deleted": True, "variable_uuid": "{var-1}"}


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_create_pipeline_schedule_tool(mock_get_client):
    from src.server import create_pipeline_schedule
    mock_client = AsyncMock()
    mock_client.create_pipeline_schedule.return_value = SAMPLE_SCHEDULE
    mock_get_client.return_value = mock_client
    r = await create_pipeline_schedule("my-repo", "main", "0 0 6 * * ? *")
    mock_client.create_pipeline_schedule.assert_awaited_once_with(
        "my-repo", "main", "0 0 6 * * ? *", None, True, None
    )
    assert r["uuid"] == "{sched-1}"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_update_pipeline_schedule_tool(mock_get_client):
    from src.server import update_pipeline_schedule
    mock_client = AsyncMock()
    mock_client.update_pipeline_schedule.return_value = SAMPLE_SCHEDULE
    mock_get_client.return_value = mock_client
    r = await update_pipeline_schedule("my-repo", "{sched-1}", enabled=False)
    mock_client.update_pipeline_schedule.assert_awaited_once_with(
        "my-repo", "{sched-1}", False, None, None
    )
    assert r["enabled"] is True  # slimmed from SAMPLE_SCHEDULE


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_delete_pipeline_schedule_tool_confirmation(mock_get_client):
    from src.server import delete_pipeline_schedule
    mock_client = AsyncMock()
    mock_client.delete_pipeline_schedule.return_value = None
    mock_get_client.return_value = mock_client
    r = await delete_pipeline_schedule("my-repo", "{sched-1}")
    assert r == {"deleted": True, "schedule_uuid": "{sched-1}"}


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_delete_pipeline_cache_tool_confirmation(mock_get_client):
    from src.server import delete_pipeline_cache
    mock_client = AsyncMock()
    mock_client.delete_pipeline_cache.return_value = None
    mock_get_client.return_value = mock_client
    r = await delete_pipeline_cache("my-repo", "{cache-1}")
    assert r == {"deleted": True, "cache_uuid": "{cache-1}"}


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_pipeline_caches_tool(mock_get_client):
    from src.server import list_pipeline_caches
    mock_client = AsyncMock()
    mock_client.list_pipeline_caches.return_value = {"page": 1, "values": [SAMPLE_CACHE]}
    mock_get_client.return_value = mock_client
    r = await list_pipeline_caches("my-repo")
    assert r["values"][0]["name"] == "node"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_create_pipeline_variable_tool_masks_secured(mock_get_client):
    from src.server import create_pipeline_variable
    mock_client = AsyncMock()
    mock_client.create_pipeline_variable.return_value = {**SAMPLE_VAR_SECURED, "value": "leak"}
    mock_get_client.return_value = mock_client
    r = await create_pipeline_variable("my-repo", "API_TOKEN", "abc", secured=True)
    mock_client.create_pipeline_variable.assert_awaited_once_with(
        "my-repo", "API_TOKEN", "abc", True, None
    )
    assert r["value"] is None  # secured masked through the tool


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_update_pipeline_variable_tool(mock_get_client):
    from src.server import update_pipeline_variable
    mock_client = AsyncMock()
    mock_client.update_pipeline_variable.return_value = SAMPLE_VAR_PLAIN
    mock_get_client.return_value = mock_client
    r = await update_pipeline_variable("my-repo", "{var-1}", value="us-east-1")
    mock_client.update_pipeline_variable.assert_awaited_once_with(
        "my-repo", "{var-1}", None, "us-east-1", None, None
    )
    assert r["key"] == "REGION"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_pipeline_schedules_tool_slims(mock_get_client):
    from src.server import list_pipeline_schedules
    mock_client = AsyncMock()
    mock_client.list_pipeline_schedules.return_value = {"page": 1, "values": [SAMPLE_SCHEDULE]}
    mock_get_client.return_value = mock_client
    r = await list_pipeline_schedules("my-repo")
    entry = r["values"][0]
    assert entry["selector_pattern"] == "main"
    assert "target" not in entry  # slimmed (no nested target.ref_type)


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_pipeline_schedule_tool_slims(mock_get_client):
    from src.server import get_pipeline_schedule
    mock_client = AsyncMock()
    mock_client.get_pipeline_schedule.return_value = SAMPLE_SCHEDULE
    mock_get_client.return_value = mock_client
    r = await get_pipeline_schedule("my-repo", "{sched-1}")
    assert r["target_ref"] == "main"
    assert "target" not in r


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_list_schedule_executions_tool_slims(mock_get_client):
    from src.server import list_pipeline_schedule_executions
    mock_client = AsyncMock()
    mock_client.list_pipeline_schedule_executions.return_value = {
        "page": 1, "values": [SAMPLE_EXECUTION]
    }
    mock_get_client.return_value = mock_client
    r = await list_pipeline_schedule_executions("my-repo", "{sched-1}")
    assert r["values"][0]["build_number"] == 17
    assert r["values"][0]["state_result"] == "SUCCESSFUL"
