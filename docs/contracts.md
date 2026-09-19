# Command and error contracts

Normal results are one JSON object on stdout: `{"schema_version":"1.0","data":{},"source":{},"warnings":[]}`. Contract failures write one object to stderr and nothing to stdout: `{"schema_version":"1.0","error":{"code":"invalid_identifier","message":"...","details":{}}}`.

## Commands

- `get CELEX [--cache MODE] [--json]` resolves exactly one work.
- `formats CELEX --lang en|es [--cache MODE] [--json]` first resolves exactly one work, then returns a bounded, complete representation collection. Each entry retains work, expression, manifestation, item, raw CELLAR type, friendly format/MIME when known, and whether download is supported. Unknown types have `format: null`, `mime_type: null`, and `supported: false`.
- `download CELEX --lang en|es --format pdf|xhtml --out DIR [--cache MODE] [--json]` creates `CELEX_LANG.EXT` and `CELEX_LANG.manifest.json`. Neither file is overwritten.
- `doctor [--offline] [--json]` checks cache integrity and, unless offline, SPARQL connectivity.

`--cache` accepts `auto`, `only`, `refresh`, or `off`. Auto metadata freshness is 24 hours and an auto metadata hit is labelled `cached`. Artifact hits in both auto and only mode are labelled `not_checked`: their bytes and hashes are verified, but their upstream freshness is not rechecked. Only mode never performs network access. Artifact cache hits in both `auto` and `only` are always `not_checked`: unlike metadata, immutable local artifact bytes have no freshness TTL or upstream revalidation. Their original retrieval timestamp and hash remain unchanged. Refresh atomically replaces mutable query/artifact indexes; content-addressed blobs remain create-once unless an explicit refresh repairs corruption.

`item` is the exact URI discovered in CELLAR. `requested_url` is the normalized HTTPS URL actually sent, `final_url` is the exact final response URL, and `transport.upgraded_to_https` discloses an HTTP-to-HTTPS normalization. `mime_type` is the selected Accept contract; `response_mime_type` is the actual response Content-Type. When CELLAR supplies one valid `cdm:work_date_document`, it is exposed as `source_dates.document_date`; no other date semantics are inferred.

## Exit mapping

| Exit | Meaning | Codes |
|---:|---|---|
| 0 | success | — |
| 1 | operational/upstream/integrity failure | `rate_limited`, `upstream_unavailable`, `parse_error`, `cache_corrupt`, `download_incomplete`, `unsafe_redirect`, `io_error` |
| 2 | invalid caller input | `invalid_identifier`, `invalid_option` |
| 3 | requested source absent/unsupported | `not_found`, `language_unavailable`, `format_unavailable`, `unsupported_structure`, `cache_miss` |
| 4 | unsafe ambiguity | `ambiguous_document` |
| 5 | output collision | `output_exists` |

Typer's own syntax errors use its standard usage rendering. Once arguments parse, domain failures follow the JSON contract.

Collections use a safety-limit-plus-one query. More than 100 work/date or representation rows produces `parse_error`; the CLI never reports a truncated collection as complete. SPARQL bodies are streamed under 2 MiB. Cached query rows and timestamps and every essential artifact-manifest field are schema checked. Missing source dates remain absent.
