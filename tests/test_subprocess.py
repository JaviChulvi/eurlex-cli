import json
import os
import subprocess
import sys

import httpx

from eurlex_cli.core import ArtifactCache, CellarClient
from test_core import transport


def test_offline_fixture_works_in_a_real_subprocess(tmp_path):
    cache = ArtifactCache(tmp_path / "cache")
    CellarClient(http=httpx.Client(transport=httpx.MockTransport(transport)), cache=cache).get("32016R0679")
    process = subprocess.run(
        [sys.executable, "-m", "eurlex_cli.cli", "get", "32016R0679", "--cache", "only"],
        text=True, capture_output=True,
        env={**os.environ, "EURLEX_CACHE_DIR": str(cache.root)},
    )
    assert process.returncode == 0
    assert process.stderr == ""
    payload = json.loads(process.stdout)
    assert payload["data"]["cache"]["hit"] is True
    assert payload["source"]["cache"]["freshness"] == "not_checked"
