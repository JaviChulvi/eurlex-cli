import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from eurlex_cli.core import ArtifactCache, CellarClient, EurlexError
from test_core import WORK, sparql, transport


def test_stale_auto_metadata_is_refreshed(tmp_path):
    cache = ArtifactCache(tmp_path / "cache")
    first = CellarClient(http=httpx.Client(transport=httpx.MockTransport(transport)), cache=cache)
    first.get("32016R0679")
    query_file = next(cache.queries.glob("*.json"))
    payload = json.loads(query_file.read_text())
    payload["cached_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    query_file.write_text(json.dumps(payload))
    calls = 0
    def counted(request):
        nonlocal calls
        calls += 1
        return transport(request)
    refreshed = CellarClient(http=httpx.Client(transport=httpx.MockTransport(counted)), cache=cache)
    result = refreshed.get("32016R0679")
    assert calls == 1
    assert result["cache"]["hit"] is False
    offline = CellarClient(cache=cache, cache_mode="only")
    assert offline.get("32016R0679")["work"] == WORK


def test_cache_off_does_not_read_or_write(tmp_path):
    cache = ArtifactCache(tmp_path / "cache")
    client = CellarClient(http=httpx.Client(transport=httpx.MockTransport(transport)),
                          cache=cache, cache_mode="off")
    client.get("32016R0679")
    assert not cache.root.exists()


def test_refresh_replaces_query_index(tmp_path):
    cache = ArtifactCache(tmp_path / "cache")
    query = "SELECT ?work WHERE {}"
    cache.store_query(query, [{"work": "old"}])
    cache.store_query(query, [{"work": "new"}])
    assert cache.load_query(query)[0] == [{"work": "new"}]


@pytest.mark.parametrize("mutation", [
    lambda payload: payload.update(cached_at="garbage"),
    lambda payload: payload.update(rows=[{"work": 7}]),
    lambda payload: payload.update(query_sha256="0" * 64),
])
def test_corrupt_query_schema_is_explicit_and_doctor_checks_queries(tmp_path, mutation):
    cache = ArtifactCache(tmp_path / "cache")
    query = "SELECT ?work WHERE {}"
    cache.store_query(query, [{"work": WORK}])
    path = next(cache.queries.glob("*.json"))
    payload = json.loads(path.read_text())
    mutation(payload)
    path.write_text(json.dumps(payload))
    with pytest.raises(EurlexError) as error:
        cache.load_query(query)
    assert error.value.code == "cache_corrupt"
    with pytest.raises(EurlexError) as error:
        cache.check()
    assert error.value.code == "cache_corrupt"


@pytest.mark.parametrize("payload", [[], None], ids=["list", "null"])
@pytest.mark.parametrize("operation", ["load", "check"])
def test_artifact_cache_non_object_json_is_explicit(tmp_path, payload, operation):
    cache = ArtifactCache(tmp_path / "cache")
    cache.entries.mkdir(parents=True)
    path = cache._entry_path("32016R0679", "en", "pdf")
    path.write_text(json.dumps(payload))
    with pytest.raises(EurlexError) as error:
        if operation == "load":
            cache.load("32016R0679", "en", "pdf")
        else:
            cache.check()
    assert error.value.code == "cache_corrupt"


@pytest.mark.parametrize("payload", [[], None], ids=["list", "null"])
@pytest.mark.parametrize("operation", ["load_query", "check"])
def test_query_cache_non_object_json_is_explicit(tmp_path, payload, operation):
    cache = ArtifactCache(tmp_path / "cache")
    query = "SELECT ?work WHERE {}"
    cache.store_query(query, [{"work": WORK}])
    path = next(cache.queries.glob("*.json"))
    path.write_text(json.dumps(payload))
    with pytest.raises(EurlexError) as error:
        if operation == "load_query":
            cache.load_query(query)
        else:
            cache.check()
    assert error.value.code == "cache_corrupt"


def test_cached_freshness_is_not_reported_as_newly_fresh(tmp_path):
    cache = ArtifactCache(tmp_path / "cache")
    CellarClient(http=httpx.Client(transport=httpx.MockTransport(transport)), cache=cache).get("32016R0679")
    result = CellarClient(cache=cache).get("32016R0679")
    assert result["cache"]["freshness"] == "cached"


def test_doctor_rejects_cache_root_file(tmp_path):
    root = tmp_path / "cache"
    root.write_text("not a directory")
    with pytest.raises(EurlexError) as error:
        ArtifactCache(root).check()
    assert error.value.code == "cache_corrupt"


def test_doctor_checks_orphan_blob_name_and_content(tmp_path):
    cache = ArtifactCache(tmp_path / "cache")
    cache.blobs.mkdir(parents=True)
    (cache.blobs / ("0" * 64)).write_bytes(b"wrong")
    with pytest.raises(EurlexError) as error:
        cache.check()
    assert error.value.code == "cache_corrupt"
