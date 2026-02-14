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

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
