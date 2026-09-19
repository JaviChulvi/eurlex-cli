# Testing

```bash
uv sync --locked
uv run pytest -q
```

The focused suite includes unit, regression, and in-process CLI contract tests. HTTP responses and document bytes are synthetic; it does not depend on CELLAR uptime.

Coverage includes identifier validation, exact-work ambiguity, format selection, offline cache integrity and refresh, redirects, bounded streaming, PDF/XHTML validation, encoded XML entities, atomic output publication, cleanup after filesystem failures, and structured errors.

The [CLI checks workflow](../.github/workflows/cli-checks.yml) runs regression tests on Python 3.11 and 3.14 for pull requests, pushes to `main`, nightly runs and manual runs. Nightly runs are scheduled for **21:00 Europe/Madrid daily**. Nightly and manual runs also execute `scripts/nightly_smoke.py` against public CELLAR services, checking all four commands, downloads, provenance hashes and offline replay. Historical live observations remain in [support.md](support.md).
