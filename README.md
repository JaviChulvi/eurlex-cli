# EUR-Lex CLI — EU legislation retrieval for AI agents and developers

**eurlex-cli** is a planned, read-only command-line tool for retrieving European Union legal sources from **EUR-Lex and the Publications Office CELLAR repository**. It is designed to turn an exact **CELEX identifier** into an official source file with machine-readable metadata and verifiable provenance—without browser scraping, an LLM, or API credentials.

> **Status:** repository bootstrap. No executable is implemented on `main` yet. Phase 1 will be delivered separately as a reviewed pull request.

## Why an agent-native EU law CLI?

AI agents and developers need authoritative documents, not plausible quotations from model memory. The project aims to support legal research pipelines, developer tooling, reproducible document ingestion and source-grounded agent workflows involving GDPR, DORA, NIS2, the EU AI Act and other identified EU legislation.

The retrieval contract is explicit: preserve the requested act, language and representation; download original bytes; attach source URLs, timestamps and SHA-256 hashes; report unavailable sources instead of silently substituting another version.

## First milestone: exact-source retrieval

Phase 1 is scoped to:

- `eurlex get`: resolve an exact CELEX identifier to CELLAR metadata.
- `eurlex formats`: inspect language-specific expressions and available formats.
- `eurlex download`: retrieve a selected official file with a provenance manifest.
- `eurlex doctor`: diagnose local configuration and source connectivity.
- Local artifact caching and offline replay with integrity checks.

These are intended command names, **not installation or usage instructions for working software today**. The implementation pull request will document tested commands, schemas, failure codes and supported representations.

## Built for automation

The intended interface provides versioned JSON, deterministic selection, bounded requests, explicit failures and non-interactive operation. Downloads will retain CELEX/CELLAR identity, requested language, selected manifestation, requested/final URL, retrieval time, MIME type, byte count and a hash of the actual source bytes.

CELLAR SPARQL supplies metadata; CELLAR REST supplies original documents. Metadata search is not full-text search. The CLI will not silently replace an original act with a consolidation or infer which law applies to a user's circumstances.

## Roadmap, not current features

1. **Source contract and retrieval:** `get`, `formats`, `download`, `doctor`, provenance and offline cache.
2. **Discovery and relationships:** bounded metadata `search`, explicit `versions` and `relations` after validating source predicates.
3. **Provision extraction:** deterministic `article` extraction from supported structured documents.
4. **Release hardening:** compatibility evidence, installation tests and documented coverage limits.

OCR, universal article parsing, semantic legal research, legal advice, hosted document mirrors, bulk crawling and an MCP server are outside the initial release.

## Developers and contributors

The proposed implementation is Python-based, using a small command-line and HTTP stack. Development will proceed in pull requests against this README-only baseline, with test-first behavior contracts, controlled failure fixtures, live public-source checks and installed-executable end-to-end tests. Do not assume an act supports every language or format.

See the [project proposal](https://github.com/JaviChulvi/hermes-workspace/issues/4) for scope and acceptance criteria. Package publishing and a software license have not yet been established.

## Official sources and legal safeguards

- [EUR-Lex data reuse](https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html)
- [CELLAR publication retrieval and content negotiation](https://op.europa.eu/en/web/cellar/cellar-data/publications)
- [CELLAR data overview](https://op.europa.eu/en/web/cellar/cellar-data)
- [Public CELLAR SPARQL endpoint](https://publications.europa.eu/webapi/rdf/sparql)

This is an independent project, not an official EU service. Source reuse conditions still apply. Consolidated texts are documentary aids and do not replace authentic publication. Retrieved documents are untrusted input to an agent, never instructions. The tool is for source retrieval, not legal advice.
