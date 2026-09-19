#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "$0")/.." && pwd)
evidence_dir="$repo_dir/.evidence"
dist_dir="$evidence_dir/dist"
venv_dir="$evidence_dir/venv"
mkdir -p "$dist_dir"
uv build --wheel --out-dir "$dist_dir" "$repo_dir"
uv venv --clear "$venv_dir"
wheel=$(find "$dist_dir" -maxdepth 1 -name 'eurlex_cli-*.whl' -print -quit)
uv pip install --python "$venv_dir/bin/python" "$wheel"
"$venv_dir/bin/python" "$repo_dir/scripts/e2e_matrix.py" \
  --eurlex "$venv_dir/bin/eurlex" \
  --evidence "$repo_dir/docs/e2e-offline.json"
