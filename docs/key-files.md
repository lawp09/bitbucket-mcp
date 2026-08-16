# Key Files Reference

Quick reference for important files in the bitbucket-mcp project.

| File | Purpose |
|------|---------|
| `src/server.py` | MCP tool registration, client singleton |
| `src/client.py` | Bitbucket API client (async, Basic Auth) |
| `src/main.py` | CLI entry point (stdio/HTTP transport) |
| `src/utils/credentials.py` | Secure credentials (env vars → keychain fallback) |
| `src/utils/pagination.py` | Pagination config and aggregation |
| `src/utils/transformers.py` | Slim response transformers (token reduction) |
| `src/prompts.py` | MCP Prompts templates |
| `configs/tools.json` | Tool enable/disable settings |
| `Makefile` | Container management (podman/docker) |
| `.github/workflows/ci.yml` | GitHub Actions CI pipeline |
| `.github/workflows/release.yml` | Release pipeline (PyPI + MCP Registry + GitHub Release) |
| `.env.example` | Template for credentials (copy to .env) |
| `server.json` | MCP Registry manifest |
| `pyproject.toml` | Python project configuration (uv, dependencies, build) |
| `tests/` | pytest test suite |
| `scripts/` | Shell scripts (build.sh, run.sh) |
| `Dockerfile` | Container image definition |
| `docker-compose.yml` | Multi-container setup (optional) |
