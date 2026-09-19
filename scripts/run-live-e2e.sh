#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "$0")/.." && pwd)
if [[ "${EURLEX_LIVE:-}" != "1" ]]; then
  echo "Set EURLEX_LIVE=1 to run public CELLAR checks." >&2
  exit 2
fi
"$repo_dir/scripts/run-installed-e2e.sh"
"$repo_dir/.evidence/venv/bin/python" "$repo_dir/scripts/live_matrix.py" \
  --eurlex "$repo_dir/.evidence/venv/bin/eurlex" \
  --evidence "$repo_dir/docs/e2e-live.json"
