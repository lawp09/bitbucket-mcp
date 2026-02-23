# Contributing to bitbucket-mcp-py

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/lawp09/bitbucket-mcp.git
   cd bitbucket-mcp
   ```

2. **Install dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

3. **Run tests**
   ```bash
   pytest tests/ -v
   ```

## Making Changes

1. **Fork** the repository and create a branch from `main`
2. **Write tests** for any new functionality
3. **Run the test suite** to make sure nothing is broken
4. **Follow existing code style** (async/await, type hints, structured output)
5. **Keep changes focused** — one feature or fix per PR

## Pull Request Guidelines

- Keep PRs small and focused
- Write a clear title and description
- Reference any related issues
- Ensure CI passes (tests + build)
- Update documentation if needed (`docs/`, `README.md`, `CLAUDE.md`)

## Code Style

- **Python 3.12+** with type annotations
- **Async-first** — all API calls use `async/await`
- **pytest** with `pytest-asyncio` for tests
- **Structured output** — tools return `Dict[str, Any]`

## Reporting Issues

Open an issue on GitHub with:
- A clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Python version and OS

## Releasing (maintainers only)

Releases are automated via GitHub Actions. The pipeline triggers on git tags and handles build, PyPI publish, and GitHub Release creation automatically.

### Prerequisites (one-time setup)

- **PyPI Trusted Publisher** configured at `pypi.org/manage/project/bitbucket-mcp-py/settings/publishing/`
  - Repository: `lawp09/bitbucket-mcp`, Workflow: `release.yml`, Environment: `release`
- **GitHub environment** named `release` created in repository Settings → Environments

### Release process

1. **Update `CHANGELOG.md`** — add a new `## [X.Y.Z] - YYYY-MM-DD` section with the changes

2. **Update `server.json`** — bump `version` and `packages[0].version` to `X.Y.Z`

3. **Open a PR** with these two changes, get it merged into `main`

4. **Tag and push**
   ```bash
   git checkout main && git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

5. **GitHub Actions takes over** — the `release.yml` pipeline runs automatically:
   - Runs tests
   - Builds the package (`hatch-vcs` derives version from the tag)
   - Verifies the tag matches the package version and `server.json`
   - Publishes to PyPI via OIDC (no token required)
   - Creates a GitHub Release with the CHANGELOG notes

### Versioning

This project uses [hatch-vcs](https://github.com/ofek/hatch-vcs) — the package version is derived from git tags at build time. There is no `version` field to update in `pyproject.toml` or `src/__init__.py`.

Version format follows [Semantic Versioning](https://semver.org/):
- `MAJOR.MINOR.PATCH` on a tagged commit (e.g. `v1.6.0` → `1.6.0`)
- `MAJOR.MINOR.PATCH.devN+gHASH` on untagged commits (development builds)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
