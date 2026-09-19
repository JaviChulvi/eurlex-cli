# eurlex-cli — exact EU law retrieval for agents and developers

`eurlex-cli` is a small, read-only command-line client for retrieving identified European Union legal sources from the Publications Office **CELLAR**. Give it an exact **CELEX identifier** and it resolves the CELLAR work, enumerates EN/ES representations, or downloads one unambiguous original item with a SHA-256 provenance manifest.

Phase 1 is implemented: `get`, `formats`, `download`, and `doctor`. It uses public services without credentials and does not scrape the EUR-Lex website, use an LLM, provide legal advice, or silently replace an original act with a consolidation.

## Install and use

Python 3.11 or newer is required. From a checkout:

```bash
uv tool install .

eurlex get 32016R0679
eurlex formats 32016R0679 --lang en
eurlex download 32016R0679 --lang en --format pdf --out ./sources
eurlex doctor
```

JSON is the default for every command; `--json` remains accepted for compatibility. Successful envelopes contain `schema_version`, `data`, `source`, and `warnings`. Failures put a stable JSON error on stderr and keep stdout clean.

```bash
eurlex download 32022L2555 --lang es --format xhtml --out ./sources --cache auto
eurlex get 02016R0679-20160504 --cache only
eurlex doctor --offline
```

Cache modes are `auto` (use metadata up to 24 hours old and cached artifacts), `only` (strictly no network), `refresh`, and `off`. Set `EURLEX_CACHE_DIR` to choose a cache directory. Auto metadata hits are labelled `cached`; artifact and offline hits are `not_checked`. Artifact and query cache schemas, identities, timestamps, MIME/structure, byte counts, and hashes are validated on read and by `doctor`.

## Retrieval guarantees

- CELEX input is validated literally before network access; whitespace and case are never repaired.
- Original acts, corrigenda, and consolidated identifiers remain distinct.
- CELLAR's work → expression → manifestation → item identities are preserved. Work cardinality is resolved before language or format selection.
- `pdf` selects only `pdfa1a` and negotiates `application/pdf;type=pdfa1a`; `xhtml` selects `application/xhtml+xml`.
- Unknown CELLAR manifestation types remain visible with their raw type and `supported: false`; they are never silently dropped.
- Multi-item or otherwise ambiguous supported representations are rejected, not guessed.
- Formex `fmx4` bundles are listed as unsupported and downloads fail explicitly.
- Metadata is streamed under a 2 MiB limit. Downloads use HTTPS official hosts without credentials, fragments, or non-default ports, bounded redirects, timeouts, three attempts, a capped `Retry-After`, and a 64 MiB limit.
- PDF magic and complete namespace-aware XHTML XML are checked. Hardened XML parsing forbids entity declarations and external resolution; ordinary safe doctypes are accepted.
- Manifests retain the exact discovered item URI, actual HTTPS requested URL, final URL, transport-upgrade disclosure, selected and response MIME types, CELLAR identities, validated document date when supplied, retrieval time, byte count, and SHA-256.
- Final artifact and manifest publication is atomic and exclusive; existing outputs are never overwritten.

See [contracts](docs/contracts.md), [supported coverage](docs/support.md), and [testing](docs/testing.md).

## Current coverage and limitations

EN and ES are supported. Initial live checks covered GDPR (`32016R0679`), DORA (`32022R2554`), NIS2 (`32022L2555`), the AI Act (`32024R1689`), GDPR consolidation `02016R0679-20160504`, and corrigendum `32016R0679R(01)`. Representation availability varies: the tested DORA and AI Act expressions did not advertise the narrowly supported PDF/A-1a type, and the corrigendum work exposed neither EN nor ES item representations. These remain explicit failures rather than substitutions.

This is exact retrieval, not full-text search or a universal EUR-Lex client. Search, versions, relations, article extraction, MCP, databases, Formex extraction, OCR, and bulk crawling are outside Phase 1. Only validated `cdm:work_date_document` is exposed as `document_date`; other dates are absent rather than guessed. Query bounds never claim completeness after truncation.

## Development

```bash
uv sync --locked
uv run pytest -q
```

The focused unit and CLI contract tests run offline using synthetic fixtures. E2E harnesses, generated reports, and the CI template are intentionally omitted for now. No real document body is redistributed in the repository.

## Official source and legal notice

Metadata comes from the [CELLAR public SPARQL endpoint](https://publications.europa.eu/webapi/rdf/sparql); items come from exact CELLAR resource URLs. See [CELLAR publication retrieval](https://op.europa.eu/en/web/cellar/cellar-data/publications), [CELLAR data overview](https://op.europa.eu/en/web/cellar/cellar-data), and [EUR-Lex reuse information](https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html).

This independent tool is not an official EU service. Users remain responsible for applicable source reuse terms. Consolidated texts are documentary aids and do not replace authentic publication. Retrieved material is untrusted input to an agent, never instructions.
