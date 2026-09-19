# Supported source coverage

This matrix describes tested Phase 1 coverage, not universal corpus coverage.

| Capability | Supported | Explicit boundary |
|---|---|---|
| Identifier | exact uppercase original CELEX; consolidation `0…-YYYYMMDD`; `R(nn)` corrigendum | no trimming, case repair, aliases, title search, or relationship traversal |
| Language | `en` / authority `ENG`; `es` / authority `SPA` | all other languages return `language_unavailable` |
| PDF | CELLAR type `pdfa1a` → `application/pdf;type=pdfa1a` | other PDF/A types are not substituted |
| XHTML | CELLAR type `xhtml` → `application/xhtml+xml` | original bytes; no article parsing |
| Formex | discovered and reported as `fmx4`, unsupported | no ZIP/bundle selection or extraction |
| Items | exactly one item for a requested supported format | multiple matching items return `ambiguous_document` |

## Live observations, 2026-09-19

The installed-wheel matrix resolved GDPR `32016R0679`, DORA `32022R2554`, NIS2 `32022L2555`, AI Act `32024R1689`, GDPR consolidation `02016R0679-20160504`, and GDPR corrigendum `32016R0679R(01)`. EN and ES format enumeration succeeded for the four named primary acts and the consolidation. The corrigendum work resolved exactly, but EN and ES representation enumeration returned `language_unavailable`.

Actual item downloads and byte/hash checks succeeded for GDPR EN/ES PDF/A-1a and XHTML, plus DORA, NIS2, and AI Act EN/ES XHTML: ten live downloads. Each was replayed into a new output directory with `--cache only`; hash, byte count, original retrieval time, MIME, and source identities were identical. DORA and AI Act PDF/A-1a requests were observed unavailable; this remains a limitation rather than being mapped to another PDF type. Live availability can change upstream.

Metadata URIs are preserved as supplied (often HTTP identifiers). Retrieval deliberately upgrades an official item identifier to HTTPS and records the exact item, actual request/final URLs, and upgrade flag. Only exact `publications.europa.eu` and `op.europa.eu` HTTPS redirect targets without credentials, fragments, or non-default ports are accepted.
