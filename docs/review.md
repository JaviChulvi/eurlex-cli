# Phase 1 independent review and fixes

Fresh Codex CLI contexts reviewed the implementation separately from the coding run; the orchestrator reviewed the diff and reran the installed executable. No review agent committed or pushed code. The original main branch contains only the project introduction.

## Blocking findings fixed

- Mutable cache indexes did not replace stale entries on refresh. Atomic replacement plus fresh-client offline replay regressions now cover queries and artifact hashes.
- Cached manifests lacked identity/schema checks. Validate CELEX/language/format, timestamps, URLs, selected and returned MIME, byte counts, digest and payload; `doctor` inspects query and blob integrity too.
- Format discovery did not establish a unique work first, conflating absent works with absent representations. Resolution is explicit before discovery; unknown item-bearing types remain visible as unsupported.
- Metadata was fully buffered before its size check. SPARQL responses are streamed under a 2 MiB cap.
- URL validation allowed userinfo/nondefault ports. Official origin checks now reject credentials, fragments and nondefault ports at every item/redirect boundary.
- XHTML prefix checks accepted malformed XML. Complete namespaced XHTML parsing is now entity-safe through `defusedxml`. A second review reproduced a UTF-16 declaration bypass in the interim byte-regex approach; UTF-16/UTF-32 regressions cover the final parser.
- Malformed cache values and directory failures escaped machine errors. Object-shape, timestamp and structured I/O error coverage was added; a second pass covered valid JSON list/null cache files.
- Live evidence discarded provenance. Reports now retain identities, URLs, timestamps, byte counts, hashes and real-download offline replay comparisons.

## Review adjudication and documentation

A final review found no remaining security concerns but proposed labelling auto artifact hits `cached` instead of `not_checked`. This recommendation was not applied: artifact hits deliberately do not revalidate upstream freshness, in either auto or offline mode. Only metadata has a 24-hour policy. The contract now states that distinction explicitly; changing the label to imply a freshness check would be misleading. Original artifact retrieval time and hash remain unchanged.

Interrupted test runs could leave local source/cache directories beneath `docs`; those directories are ignored and no source bodies are committed.

## Acceptance evidence

See [testing.md](testing.md), [installed offline matrix](e2e-offline.json) and [live/replay matrix](e2e-live.json). Unit/regression suite: 65 passing tests. Installed matrix: 43 passing cases (get 10, formats 10, download 10, doctor 13). Live/replay matrix: 43 passing cases (33 actual public CELLAR executions, 10 offline replays of those real downloads). These are separate categories, not 86 live network tests.

The live observed limitations remain explicit: narrowly supported PDF/A-1a absent for DORA and AI Act; tested GDPR corrigendum resolves but no EN/ES item representations were returned. Expected failure checks are retained instead of manufacturing successful files. No search, versions, relationships, article extraction, broad language support or universal CELEX coverage is claimed.
