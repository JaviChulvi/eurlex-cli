# Test strategy and recorded evidence

Controlled fixtures contain only tiny synthetic PDF/XHTML markers and labelled SPARQL result shapes. No public document body is checked into the repository. Live checks are opt-in; ordinary CI is deterministic and offline after installing dependencies.

## Test-first command evidence

These outputs were produced during implementation on 2026-09-19, not reconstructed:

1. Core red: `uv run pytest -q` → `ModuleNotFoundError: No module named 'eurlex_cli'` (exit 2).
2. Core green: `uv run pytest -q` → `10 passed in 0.06s`.
3. Download/cache red: `uv run pytest tests/test_download.py -q` → missing `ArtifactCache` (exit 2).
4. Download/cache green: same command → `8 passed in 0.14s`.
5. CLI red: `uv run pytest tests/test_cli.py -q` → missing `eurlex_cli.cli` (exit 2).
6. CLI green: same command → `5 passed in 0.34s`.
7. Hardened suite: `uv run pytest -q` → `29 passed in 0.24s` before the final subprocess regression.
8. First installed E2E run exposed missing evidence-directory creation and exited 1.
9. Installed E2E after the fix: 40/40, ten cases for each command.
10. First live matrix: 20/22; DORA and AI Act PDF/A-1a were genuinely unavailable.
11. Corrected discovered-representation live matrix: 22/22.
12. Blocker regressions red: `uv run pytest -q` → `19 failed, 30 passed` (exit 1), covering the confirmed review findings.
13. Minimal owner fixes green: `uv run pytest -q` → `49 passed` (exit 0); final hardening expanded this to 54.
14. First expanded live evidence run: 41/43; the two failures established that the resolved GDPR corrigendum has no EN/ES item representations.
15. Availability expectations corrected without dropping those cases: expanded live matrix 43/43.
16. Final blocker regressions red: focused XHTML/cache command → `7 failed, 3 passed` (exit 1). UTF-16 entity expansion was accepted, artifact list/null JSON leaked `TypeError`, and query list/null JSON leaked `AttributeError`; UTF-32 and query doctor cases were already rejected.
17. Final blocker fixes green: focused XHTML/cache command, including UTF-16/UTF-32 entities and safe local/external DOCTYPE declarations → `12 passed in 0.22s` (exit 0).

Current final verification is recorded at handoff. Machine-readable case-level evidence is in [offline installed-wheel evidence](e2e-offline.json) and [real live evidence](e2e-live.json); totals are derived from subprocess results.

## Final verification

- `uv lock --check` → `Resolved 21 packages in 2ms` (exit 0).
- `uv run pytest -q` → 65 passed in 2.03s (exit 0).
- Installed-wheel matrix with evidence redirected to `/var/tmp` → 43 passed, 0 failed: 10 each for `get`, `formats`, and `download`; 13 distinct `doctor` cases (exit 0). Checked-in evidence was not overwritten.
- `EURLEX_LIVE=1 scripts/run-live-e2e.sh` → installed preflight 43/43, then expanded evidence 43/43: 33 real-live cases and 10 real-cache-offline replays (exit 0).
- `git diff --check` → clean (exit 0).
- Production Python → 769 lines, below the 1,000-line limit.

## CI infrastructure limitation

The initial HTTPS branch push was rejected because the available PAT lacks `workflow` scope for `.github/workflows/ci.yml`. An SSH read-only probe also could not proceed because no verified GitHub host key was configured. The workflow is supplied as [an inactive template](ci-workflow.yml), not an active check. Local unit, wheel-install and live checks were actually executed; no GitHub CI success is claimed.

## Matrix labels

- `controlled-fixture`: typed identifiers, ambiguity, throttling, bounded metadata streaming, unsafe/safe redirects, interrupted transfers, bad MIME/magic/XML, stale replacement, corrupt query/manifest/blob schemas, and structured I/O errors.
- `local-offline`: real subprocess and installed executable with `--cache only`; no network route exists.
- `real-live/public-CELLAR`: opt-in installed executable against public SPARQL and exact item URLs; three live doctor calls are labelled as three, not ten.
- `real-cache-offline`: each of ten real downloads replayed into a fresh output directory with no network and compared for exact provenance and bytes.

```bash
uv sync --locked
uv run pytest -q
scripts/run-installed-e2e.sh
EURLEX_LIVE=1 scripts/run-live-e2e.sh
```
