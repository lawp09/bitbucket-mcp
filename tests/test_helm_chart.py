"""Tests for the Helm chart in charts/bitbucket-mcp.

The chart is rendered with the real ``helm`` binary and the result is checked twice: for
what Kubernetes receives, and — the contract test — for whether ``main()`` accepts the
args and env the chart hands it. A renamed flag or a broken env pairing then fails here
rather than in a crash-looping pod.
"""

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import yaml

import src.server
from src.main import main
from src.server import mcp
from tests.test_main import CREDS_TARGET, _Transports

CHART = Path(__file__).resolve().parent.parent / "charts" / "bitbucket-mcp"
EXAMPLES = CHART / "examples"
PUBLIC_URL = "https://mcp.example.com"

if shutil.which("helm") is None:
    # CI installs helm for these tests: a silent skip there would hide a broken chart.
    if os.environ.get("CI"):
        pytest.fail("helm is not installed, but CI must run the chart tests", pytrace=False)
    pytest.skip("helm is not installed", allow_module_level=True)


def helm_template(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["helm", "template", "t", str(CHART), *args], capture_output=True, text=True
    )


def render(*args: str) -> dict:
    """Render the chart and index the resources by kind (one of each here)."""
    result = helm_template(*args)
    assert result.returncode == 0, result.stderr
    return {doc["kind"]: doc for doc in yaml.safe_load_all(result.stdout) if doc}


def container(resources: dict) -> dict:
    return resources["Deployment"]["spec"]["template"]["spec"]["containers"][0]


def env_of(resources: dict) -> dict:
    return {item["name"]: item["value"] for item in container(resources)["env"]}


# ========== Derived settings ==========


def test_settings_are_derived_from_public_url():
    env = env_of(render("--set", f"publicUrl={PUBLIC_URL}"))
    assert env == {
        "BITBUCKET_RESOURCE_SERVER_URL": "https://mcp.example.com/mcp",
        "BITBUCKET_ALLOWED_HOSTS": "mcp.example.com",
        "BITBUCKET_ALLOWED_ORIGINS": "https://mcp.example.com",
    }


def test_port_and_case_are_normalised_the_way_clients_send_them():
    resources = render(
        "--set", "publicUrl=https://MCP.Example.com:8443", "--set", "ingress.enabled=true"
    )
    env = env_of(resources)
    # The SDK compares Host exactly, port included; an Ingress host carries no port.
    assert env["BITBUCKET_ALLOWED_HOSTS"] == "mcp.example.com:8443"
    assert env["BITBUCKET_RESOURCE_SERVER_URL"] == "https://mcp.example.com:8443/mcp"
    assert resources["Ingress"]["spec"]["rules"][0]["host"] == "mcp.example.com"


def test_default_https_port_is_dropped_since_clients_omit_it():
    env = env_of(render("--set", "publicUrl=https://mcp.example.com:443"))
    assert env["BITBUCKET_ALLOWED_HOSTS"] == "mcp.example.com"
    assert env["BITBUCKET_RESOURCE_SERVER_URL"] == "https://mcp.example.com/mcp"


def test_extra_hosts_and_origins_are_appended():
    env = env_of(
        render(
            "--set", f"publicUrl={PUBLIC_URL}",
            "--set", "extraAllowedHosts={mcp.internal.example}",
            "--set", "extraAllowedOrigins={https://mcp.internal.example}",
        )
    )
    assert env["BITBUCKET_ALLOWED_HOSTS"] == "mcp.example.com,mcp.internal.example"
    assert env["BITBUCKET_ALLOWED_ORIGINS"] == "https://mcp.example.com,https://mcp.internal.example"


def test_multi_tenant_flags_become_env():
    env = env_of(
        render(
            "--set", f"publicUrl={PUBLIC_URL}",
            "--set", "multiTenant.readOnly=true",
            "--set", "multiTenant.allowDestructive=true",
            "--set", "multiTenant.issuerUrl=https://idp.example.com",
        )
    )
    assert env["BITBUCKET_MULTITENANT_READ_ONLY"] == "1"
    assert env["BITBUCKET_MULTITENANT_ALLOW_DESTRUCTIVE"] == "1"
    assert env["BITBUCKET_OAUTH_ISSUER_URL"] == "https://idp.example.com"


@pytest.mark.parametrize(
    "public_url",
    ["", "https://mcp.example.com/", "https://mcp.example.com/mcp", "http://mcp.example.com"],
    ids=["missing", "trailing-slash", "with-path", "plain-http"],
)
def test_invalid_public_url_fails_the_render(public_url):
    assert helm_template("--set", f"publicUrl={public_url}").returncode != 0


def test_extra_env_cannot_override_a_derived_variable():
    result = helm_template(
        "--set", f"publicUrl={PUBLIC_URL}",
        "--set", "extraEnv[0].name=BITBUCKET_ALLOWED_HOSTS",
        "--set", "extraEnv[0].value=evil.example.com",
    )
    assert result.returncode != 0
    assert "extraEnv must not set BITBUCKET_ALLOWED_HOSTS" in result.stderr


def test_extra_env_passes_other_variables_through():
    env = env_of(
        render(
            "--set", f"publicUrl={PUBLIC_URL}",
            "--set", "extraEnv[0].name=BITBUCKET_TOKEN_CACHE_TTL",
            "--set-string", "extraEnv[0].value=0",
        )
    )
    assert env["BITBUCKET_TOKEN_CACHE_TTL"] == "0"


# ========== Pod ==========


def test_pod_runs_the_http_server_hardened():
    resources = render("--set", f"publicUrl={PUBLIC_URL}")
    pod = resources["Deployment"]["spec"]["template"]["spec"]
    c = container(resources)

    assert c["image"] == "ghcr.io/lawp09/bitbucket-mcp:latest"  # appVersion of a checkout
    assert "imagePullPolicy" not in c  # Kubernetes picks Always for latest, IfNotPresent otherwise
    assert c["command"] == ["python", "-m", "src.main"]
    assert c["args"] == [
        "--transport", "http", "--host", "0.0.0.0", "--port", "8000", "--stateless", "--multi-tenant",
    ]
    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert c[probe]["httpGet"]["path"] == "/healthz"

    assert pod["automountServiceAccountToken"] is False
    # runAsNonRoot alone cannot verify the image's named user: the UID must be numeric.
    assert pod["securityContext"]["runAsUser"] == 1000
    assert c["securityContext"]["readOnlyRootFilesystem"] is True
    assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert {"name": "tmp", "mountPath": "/tmp"} in c["volumeMounts"]


def test_packaged_chart_pins_the_image_of_its_own_version(tmp_path):
    """What the release does: package with the tag's version, which must reach the image."""
    packaged = subprocess.run(
        ["helm", "package", str(CHART), "--version", "1.2.3", "--app-version", "1.2.3", "-d", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert packaged.returncode == 0, packaged.stderr
    result = subprocess.run(
        ["helm", "template", "t", str(tmp_path / "bitbucket-mcp-1.2.3.tgz"), "--set", f"publicUrl={PUBLIC_URL}"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    resources = {doc["kind"]: doc for doc in yaml.safe_load_all(result.stdout) if doc}
    assert container(resources)["image"] == "ghcr.io/lawp09/bitbucket-mcp:1.2.3"


def test_image_tag_can_be_pinned():
    c = container(render("--set", f"publicUrl={PUBLIC_URL}", "--set", "image.tag=1.28.0"))
    assert c["image"] == "ghcr.io/lawp09/bitbucket-mcp:1.28.0"


# ========== Examples ==========


def test_k3s_traefik_example():
    resources = render("-f", str(EXAMPLES / "k3s-traefik.yaml"))
    ingress = resources["Ingress"]["spec"]

    assert ingress["ingressClassName"] == "traefik"
    rule = ingress["rules"][0]
    assert rule["host"] == "mcp.example.com"
    # The whole host: OAuth discovery lives under /.well-known/, not under /mcp.
    assert rule["http"]["paths"][0]["path"] == "/"
    assert rule["http"]["paths"][0]["pathType"] == "Prefix"
    assert ingress["tls"] == [{"hosts": ["mcp.example.com"], "secretName": "mcp-example-com-tls"}]
    assert "BackendConfig" not in resources


def test_gke_example():
    resources = render("-f", str(EXAMPLES / "gke.yaml"))
    ingress = resources["Ingress"]

    # GKE ignores spec.ingressClassName and reads the annotation.
    assert "ingressClassName" not in ingress["spec"]
    assert ingress["metadata"]["annotations"]["kubernetes.io/ingress.class"] == "gce"

    backend = resources["BackendConfig"]
    annotations = resources["Service"]["metadata"]["annotations"]
    assert annotations["cloud.google.com/neg"] == '{"ingress": true}'
    assert annotations["cloud.google.com/backend-config"] == (
        f'{{"default": "{backend["metadata"]["name"]}"}}'
    )
    assert backend["spec"]["healthCheck"] == {"type": "HTTP", "requestPath": "/healthz", "port": 8000}
    assert backend["spec"]["timeoutSec"] == 120


# ========== Contract with the server ==========


@pytest.fixture
def isolated_server(monkeypatch):
    """Let main() mutate the server singleton; monkeypatch puts everything back."""
    for name in ("host", "port", "stateless_http", "json_response", "transport_security", "auth"):
        monkeypatch.setattr(mcp.settings, name, getattr(mcp.settings, name))
    monkeypatch.setattr(mcp, "_token_verifier", getattr(mcp, "_token_verifier", None))
    monkeypatch.setattr(src.server, "_multi_tenant", None)
    # Only the chart's env may reach main(): not a BITBUCKET_* left in the developer's shell.
    for name in [k for k in os.environ if k.startswith("BITBUCKET_")]:
        monkeypatch.delenv(name)
    yield
    src.server._tenant_clients.clear()


def test_main_accepts_what_the_chart_renders(monkeypatch, isolated_server):
    c = container(render("-f", str(EXAMPLES / "k3s-traefik.yaml")))
    assert c["command"][-1] == "src.main"
    for item in c["env"]:
        monkeypatch.setenv(item["name"], item["value"])

    with _Transports() as transports, patch(CREDS_TARGET) as creds:
        main(c["args"])  # a parser.error here would be a SystemExit

    transports["run_streamable_http_async"].assert_awaited_once()
    creds.assert_not_called()  # multi-tenant: no process credential
    assert mcp.settings.port == 8000 and mcp.settings.stateless_http is True
    assert mcp.settings.transport_security.allowed_hosts == ["mcp.example.com"]
    config = src.server._multi_tenant
    assert config.resource_server_url == "https://mcp.example.com/mcp"
    assert config.serves_authorization_metadata is True


def test_probes_reach_healthz_through_the_host_allowlist(monkeypatch, isolated_server):
    """The kubelet probes with Host = pod IP, which the allowlist would reject on /mcp."""
    c = container(render("--set", f"publicUrl={PUBLIC_URL}"))
    for item in c["env"]:
        monkeypatch.setenv(item["name"], item["value"])
    with _Transports(), patch(CREDS_TARGET):
        main(c["args"])  # sync on purpose: main() runs its own event loop
    monkeypatch.setattr(mcp, "_session_manager", None)

    async def call_as_the_kubelet():
        transport = httpx.ASGITransport(app=mcp.streamable_http_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://10.42.0.7:8000") as http:
            return await http.get("/healthz")

    probe = asyncio.run(call_as_the_kubelet())

    assert probe.status_code == 200
