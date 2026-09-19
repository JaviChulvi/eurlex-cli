# Review and simplification

Four independent Codex review passes examined reuse, quality, efficiency, and ownership. The selected changes keep the CLI and cache contracts intact:

- Cache loads and `doctor` share manifest/query readers instead of maintaining duplicate validators.
- A shared staging helper owns temporary writes, fsync, and cleanup. Publication policy stays explicit: replace cache indexes, preserve existing blobs, never overwrite user outputs.
- One bounded body reader handles byte accounting; metadata and document retry/redirect handling remain separate.
- Artifact storage reuses the already-validated digest rather than hashing it again.

Follow-up review caught temporary-file cleanup and stream-error regressions in the draft refactor; failing regression tests were added before fixing them. Buffer limits are checked before copying a chunk, and exception subclasses remain structured errors.

Production Python is 733 physical lines, down from 769; nonblank/noncomment lines fell from 698 to 659. Security validation and exact-source selection were retained, not removed to meet a line target. See [testing.md](testing.md) for current validation. E2E infrastructure was removed separately at the user's request.
