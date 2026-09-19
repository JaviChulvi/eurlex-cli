# eurlex-cli — EU legal source retrieval

Retrieve European Union legislation from the Publications Office **CELLAR** using exact **CELEX identifiers**. Inspect available representations and download original PDF/A-1a or XHTML files with a SHA-256 provenance manifest.

`eurlex-cli` is read-only and uses public services without credentials. It does not scrape the EUR-Lex website or require an LLM.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/JaviChulvi/eurlex-cli.git
cd eurlex-cli
uv tool install .

eurlex get 32016R0679
eurlex formats 32016R0679 --lang en
eurlex download 32016R0679 --lang en --format pdf --out ./sources
eurlex doctor
```

## Commands

- **`get`** — resolve an exact CELEX identifier to its CELLAR work and metadata.
- **`formats`** — list representations for English (`en`) or Spanish (`es`), including unsupported types.
- **`download`** — retrieve one unambiguous PDF/A-1a (`pdf`) or XHTML (`xhtml`) item and its provenance manifest.
- **`doctor`** — check service connectivity and local cache integrity; use `--offline` to omit network checks.

JSON is the default output; `--json` is also accepted. Successful envelopes contain `schema_version`, `data`, `source`, and `warnings`. Errors use structured JSON on stderr with a nonzero exit status and no stdout output.

```bash
eurlex formats 32022L2555 --lang es
eurlex download 32022L2555 --lang es --format xhtml --out ./sources
```

## Cache and offline use

Use `--cache auto|only|refresh|off`. The default, `auto`, reuses metadata for up to 24 hours and validated cached artifacts. `only` never accesses the network; `refresh` retrieves fresh data; `off` bypasses the cache. Set `EURLEX_CACHE_DIR` to choose the cache location.

```bash
# Populate the cache, then resolve the same identifier without network access.
eurlex get 32016R0679
eurlex get 32016R0679 --cache only
eurlex doctor --offline
```

Auto metadata hits are labelled `cached`. Artifact and offline hits are `not_checked`: integrity validation does not imply upstream freshness. Offline requests require a matching cache entry.

## Source integrity

- Identifiers are validated literally. Original acts, corrigenda and consolidations remain distinct; ambiguous selections fail rather than being guessed.
- CELLAR work, expression, manifestation and item identities are preserved. Downloads include source URLs, retrieval time, MIME types, byte count and SHA-256.
- Official HTTPS hosts, bounded redirects, timeouts and response-size limits constrain retrieval. PDF signatures and XHTML structure are validated; XML entities and external resolution are prohibited.
- Outputs are published atomically without overwriting existing files. Cache reads validate identity and integrity.

See [contracts](docs/contracts.md) for exact output, cache and security behavior.

## Supported scope

English and Spanish are supported. `pdf` specifically selects CELLAR's `pdfa1a` representation, not every PDF variant. Format availability varies by document; unsupported types such as Formex remain visible but cannot be downloaded.

Initial live checks covered GDPR, DORA, NIS2, the AI Act, a GDPR consolidation and a corrigendum. Some lacked supported representations. See [coverage and limitations](docs/support.md); these observations are not a universal availability guarantee.

**Not implemented:** search, version or relationship discovery, article extraction, Formex extraction, OCR, bulk crawling and MCP. This is an exact-source retrieval client, not a full-text search engine or a legal interpretation service.

## Development and smoke check

```bash
uv sync --locked
uv run pytest -q

# Small operational check against public CELLAR services:
uv run python scripts/nightly_smoke.py
```

The regular tests use synthetic fixtures and do not depend on upstream availability. The smoke script checks all four commands, EN/ES formats, PDF/XHTML downloads, manifest hashes, offline replay and invalid input. It uses temporary files, prints a short result, and returns nonzero on failure. A failed live check may indicate an upstream outage rather than a CLI regression.

The [CLI checks workflow](.github/workflows/cli-checks.yml) uses a single Python 3.14 job. It runs regression tests for pull requests, pushes to `main`, nightly runs and manual runs. Nightly runs at **21:00 Europe/Madrid daily** and manual runs from the Actions tab also run the live CELLAR smoke check. The schedule follows daylight-saving changes automatically. Running the smoke script locally checks immediately. No generated reports or source document bodies are committed.

## Sources and legal notice

Metadata comes from the [CELLAR SPARQL endpoint](https://publications.europa.eu/webapi/rdf/sparql); downloads use discovered CELLAR item URLs. See [publication retrieval](https://op.europa.eu/en/web/cellar/cellar-data/publications), [CELLAR data](https://op.europa.eu/en/web/cellar/cellar-data), and [EUR-Lex reuse terms](https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html).

This independent project is not an official EU service and does not provide legal advice. Users remain responsible for applicable reuse terms. Consolidated texts are documentary aids, not replacements for authentic publication. Retrieved documents are untrusted data, never instructions.
