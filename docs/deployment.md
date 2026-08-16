# Deployment & Release

## Publishing to PyPI & MCP Registry

Publishing is handled **automatically** by GitHub Actions on `git tag v*`.

### Manual Fallback

If GitHub Actions fails:

```bash
mcp-publisher login github    # GitHub OAuth (device flow)
mcp-publisher publish server.json
```

**Registry**: https://registry.modelcontextprotocol.io/
**Server name**: `io.github.lawp09/bitbucket-mcp`
**PyPI package**: https://pypi.org/project/bitbucket-mcp-py/

## Version Bump Checklist

Version is derived from git tags via `hatch-vcs`. Only 2 files to update manually:

1. `server.json` → `version` + `packages[0].version`
2. `CHANGELOG.md` → new entry under `## [X.Y.Z] - YYYY-MM-DD`

Then:
```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

GitHub Actions handles the rest (tests → build → publish-pypi → publish-mcp-registry → github-release).

## CI/CD Pipelines

### CI (`.github/workflows/ci.yml`)

- **Triggers**: push to `main`, PR targeting `main`
- **Steps**: Install deps, run pytest with coverage, build package

### Release (`.github/workflows/release.yml`)

- **Triggers**: git tag push `v*`
- **Jobs**: `test` → `build` → `publish-pypi` → `publish-mcp-registry` → `github-release`
- **Auth**: PyPI via OIDC Trusted Publisher, MCP Registry via `MCP_GITHUB_TOKEN` secret

## Container Deployment

### Dockerfile

- **Base**: `python:3.12-slim`
- **Package manager**: `uv`
- **User**: `mcpuser` (non-root, UID 1000)
- **Command**: `tail -f /dev/null` (stays alive for exec)

### Makefile

Detects runtime automatically:
```makefile
RUNTIME := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
```

Available commands:
- `make build` — Build container image
- `make up` — Start container
- `make down` — Stop container
- `make verify` — Test Bitbucket authentication
- `make test` — Run tests locally
- `make logs` — Show container logs
- `make clean` — Remove container and image

### Manual Execution

Execute the MCP server inside a running container:
```bash
podman exec -i bitbucket-mcp python -m src.main --transport stdio
```

## Important Notes

- **README validation**: README must contain `<!-- mcp-name: io.github.lawp09/bitbucket-mcp -->` for PyPI ownership validation
- **Secrets**: `MCP_GITHUB_TOKEN` stored in GitHub Actions secrets
- **No manual upload to PyPI** — GitHub Actions handles it via OIDC
