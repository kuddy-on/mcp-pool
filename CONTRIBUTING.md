# Contributing

Thank you for improving MCPPool. For substantial behavior changes, open an issue first so protocol,
security, and compatibility tradeoffs can be agreed before implementation.

## Development

Requirements are Python 3.12+, `uv`, Node.js 20+, and npm.

```bash
uv sync --all-groups
cd web && npm ci && cd ..
```

Before opening a pull request, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
cd web && npm run lint && npm run build
```

Add focused tests for every bug fix and user-visible behavior. Never commit `.env`, databases,
credentials, generated build output, or production logs. Keep pull requests small enough to review
and update `CHANGELOG.md` for notable changes.

Commits should explain intent and use a concise conventional prefix such as `feat:`, `fix:`,
`docs:`, `test:`, or `chore:`.
