import json

import httpx
from typer.testing import CliRunner

from eurlex_cli import cli
from eurlex_cli.core import ArtifactCache, CellarClient
from test_core import transport


runner = CliRunner()


def parsed(output):
    return json.loads(output)


def test_get_default_json_and_json_compatibility(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "make_client", lambda *_args, **_kwargs:
                        CellarClient(http=httpx.Client(transport=httpx.MockTransport(transport))))
    for extra in ([], ["--json"]):
        result = runner.invoke(cli.app, ["get", "32016R0679", *extra])
        assert result.exit_code == 0, result.output
        body = parsed(result.stdout)
        assert body["schema_version"] == "1.0"
        assert body["data"]["celex"] == "32016R0679"
        assert body["source"]["endpoint"].startswith("https://publications.europa.eu/")
        assert body["warnings"] == []


def test_contract_error_is_stderr_only_and_stable_json():
    result = runner.invoke(cli.app, ["get", " 32016R0679"])
    assert result.exit_code == 2
    assert result.stdout == ""
    error = parsed(result.stderr)
    assert error["schema_version"] == "1.0"
    assert error["error"]["code"] == "invalid_identifier"


def test_formats_collection_reports_completeness(monkeypatch):
    monkeypatch.setattr(cli, "make_client", lambda *_args, **_kwargs:
                        CellarClient(http=httpx.Client(transport=httpx.MockTransport(transport))))
    result = runner.invoke(cli.app, ["formats", "32016R0679", "--lang", "en"])
    assert result.exit_code == 0
    assert parsed(result.stdout)["data"]["complete"] is True


def test_offline_metadata_subsequently_avoids_network(tmp_path):
    cache = ArtifactCache(tmp_path / "cache")
    online = CellarClient(http=httpx.Client(transport=httpx.MockTransport(transport)), cache=cache)
    online.get("32016R0679")

    def forbidden(_request):
        raise AssertionError("offline attempted network")

    offline = CellarClient(http=httpx.Client(transport=httpx.MockTransport(forbidden)),
                           cache=cache, cache_mode="only")
    result = offline.get("32016R0679")
    assert result["cache"]["hit"] is True
    assert result["cache"]["freshness"] == "not_checked"


def test_doctor_offline_reports_cache_health(monkeypatch, tmp_path):
    monkeypatch.setenv("EURLEX_CACHE_DIR", str(tmp_path / "cache"))
    result = runner.invoke(cli.app, ["doctor", "--offline"])
    assert result.exit_code == 0
    body = parsed(result.stdout)
    assert body["data"]["network"]["status"] == "skipped"
    assert body["data"]["cache"]["status"] == "ok"
