"""Tests for the CLI entry point — transport selection (issue #62).

These tests validate the *selection* of the transport (mcp.run is mocked); they do
not exercise a real HTTP round-trip, which is FastMCP's responsibility.
"""

from unittest.mock import patch

import pytest

from src.main import main
from src.server import mcp


@pytest.fixture(autouse=True)
def restore_mcp_settings():
    """Save/restore the global mcp.settings host/port so HTTP tests don't leak state
    into the shared FastMCP singleton used by other test modules."""
    original_host = mcp.settings.host
    original_port = mcp.settings.port
    yield
    mcp.settings.host = original_host
    mcp.settings.port = original_port


# get_credentials is imported INSIDE main() (`from .utils.credentials import ...`),
# so the patch target is the source module, NOT `src.main.get_credentials`
# (that name does not exist at module scope in src.main).
CREDS_TARGET = "src.utils.credentials.get_credentials"


def test_default_transport_is_stdio():
    with patch.object(mcp, "run") as mock_run, patch(CREDS_TARGET):
        main([])
    mock_run.assert_called_once_with(transport="stdio")


def test_http_transport_uses_streamable_http():
    with patch.object(mcp, "run") as mock_run, patch(CREDS_TARGET):
        main(["--transport", "http"])
    mock_run.assert_called_once_with(transport="streamable-http")


@pytest.mark.filterwarnings("always::DeprecationWarning")
def test_sse_transport_warns_deprecation():
    with patch.object(mcp, "run") as mock_run, patch(CREDS_TARGET):
        with pytest.warns(DeprecationWarning, match="deprecated"):
            main(["--transport", "sse"])
    mock_run.assert_called_once_with(transport="sse")


@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_http_family_sets_host_and_port(transport):
    with patch.object(mcp, "run"), patch(CREDS_TARGET):
        main(["--transport", transport, "--host", "1.2.3.4", "--port", "9000"])
    assert mcp.settings.host == "1.2.3.4"
    assert mcp.settings.port == 9000


def test_stdio_does_not_touch_host_port():
    # The autouse fixture saved the originals; confirm stdio leaves them unchanged.
    host_before = mcp.settings.host
    port_before = mcp.settings.port
    with patch.object(mcp, "run"), patch(CREDS_TARGET):
        main(["--transport", "stdio"])
    assert mcp.settings.host == host_before
    assert mcp.settings.port == port_before


def test_missing_credentials_exits():
    with patch.object(mcp, "run"), \
            patch(CREDS_TARGET, side_effect=ValueError("no creds")):
        with pytest.raises(SystemExit) as exc:
            main(["--transport", "stdio"])
    assert exc.value.code == 1


def test_server_crash_exits_with_code_1():
    with patch.object(mcp, "run", side_effect=RuntimeError("boom")), \
            patch(CREDS_TARGET):
        with pytest.raises(SystemExit) as exc:
            main(["--transport", "stdio"])
    assert exc.value.code == 1
