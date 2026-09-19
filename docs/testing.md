# Testing

```bash
uv sync --locked
uv run pytest -q
```

The focused suite currently passes 70 unit, regression, and in-process CLI contract tests. HTTP responses and document bytes are synthetic; it does not depend on CELLAR uptime.

Coverage includes identifier validation, exact-work ambiguity, format selection, offline cache integrity and refresh, redirects, bounded streaming, PDF/XHTML validation, encoded XML entities, atomic output publication, cleanup after filesystem failures, and structured errors.

The E2E harnesses, subprocess test, generated evidence files, and CI template were removed at the user's request to keep Phase 1 small. Historical live observations remain in [support.md](support.md); they are not a live validation of the current refactor. No active CI checks are configured.
