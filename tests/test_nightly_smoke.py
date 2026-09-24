import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("nightly_smoke", Path("scripts/nightly_smoke.py"))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def completed(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["eurlex"], code, stdout, stderr)


def test_success_envelope_rejects_malformed_json_and_stderr():
    with pytest.raises(smoke.SmokeFailure, match="get: invalid JSON"):
        smoke.parse("get", completed(stdout="not-json"))
    with pytest.raises(smoke.SmokeFailure, match="get: invalid success envelope"):
        smoke.parse("get", completed(stdout='{"schema_version":"1.0"}'))
    with pytest.raises(smoke.SmokeFailure, match="get: unexpected stderr"):
        smoke.parse("get", completed(stdout='{"schema_version":"1.0","data":{},"source":{},"warnings":[]}',
                                     stderr="noise"))


def test_nonzero_diagnostic_includes_exit_and_structured_error():
    error = {"schema_version": "1.0", "error": {
        "code": "upstream_unavailable", "message": "CELLAR unavailable", "details": {}}}
    with pytest.raises(smoke.SmokeFailure) as caught:
        smoke.parse("doctor", completed(1, stderr=json.dumps(error)))
    assert "doctor: exit 1 upstream_unavailable: CELLAR unavailable" in str(caught.value)


def test_expected_error_requires_clean_structured_channel():
    error = {"schema_version": "1.0", "error": {
        "code": "invalid_identifier", "message": "bad", "details": {}}}
    parsed = smoke.parse("invalid identifier", completed(2, stderr=json.dumps(error)),
                         expected="invalid_identifier")
    assert parsed["error"]["code"] == "invalid_identifier"


def test_artifact_verifier_checks_manifest_file_bytes_and_hash(tmp_path):
    data = b"fixture"
    artifact = tmp_path / "law.pdf"
    artifact.write_bytes(data)
    manifest = {"celex": smoke.CELEX, "language": "en", "format": "pdf",
                "item": "http://publications.europa.eu/item",
                "requested_url": "https://publications.europa.eu/item", "byte_count": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "cache": {"hit": False}}
    manifest_path = tmp_path / "law.manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    payload = {"source": {"requested_url": manifest["requested_url"]}, "data": {
        "path": str(artifact), "manifest_path": str(manifest_path), "manifest": manifest}}
    assert smoke.verify_artifact(payload, "en", "pdf") == manifest["sha256"]
    artifact.write_bytes(b"changed")
    with pytest.raises(smoke.SmokeFailure, match="artifact hash"):
        smoke.verify_artifact(payload, "en", "pdf")


def test_malformed_success_fields_report_failures_without_crashing(monkeypatch):
    payload = {"schema_version": "1.0", "data": {"celex": smoke.CELEX, "work": 7},
               "source": {}, "warnings": []}
    monkeypatch.setattr(smoke.subprocess, "run", lambda *a, **kw: completed(stdout=json.dumps(payload)))
    failures = smoke.run_smoke("eurlex")
    assert len(failures) == 7
    assert any(message.startswith("get:") for message in failures)


def test_slow_cli_error_reports_elapsed_time_and_keeps_retry_budget(monkeypatch, capsys):
    clock = [0.0]
    timeouts = []
    error = {"schema_version": "1.0", "error": {
        "code": "upstream_unavailable", "message": "CELLAR request failed", "details": {}}}

    def slow_error(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        clock[0] += 65
        return completed(1, stderr=json.dumps(error))

    monkeypatch.setattr(smoke.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(smoke.subprocess, "run", slow_error)
    failures = smoke.run_smoke("eurlex")

    assert timeouts == [120] * 7
    assert len(failures) == 7
    assert "doctor: exit 1 upstream_unavailable: CELLAR request failed (65.0s)" in failures
    assert "SKIP offline replay: PDF download failed" in capsys.readouterr().out


def test_pdf_timeout_skips_offline_replay_without_hiding_failure(monkeypatch, capsys):
    commands = []

    def fail_commands(command, **kwargs):
        commands.append(command)
        if command[1] == "download" and "en" in command:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return completed(1, stderr='{"error":{"code":"upstream_unavailable","message":"CELLAR failed"}}')

    monkeypatch.setattr(smoke.subprocess, "run", fail_commands)
    failures = smoke.run_smoke("eurlex")

    assert any(message.startswith("download en pdf: timeout") for message in failures)
    assert not any("--cache" in command and "only" in command for command in commands)
    assert "SKIP offline replay: PDF download failed" in capsys.readouterr().out


def test_overall_deadline_caps_remaining_command_time(monkeypatch):
    clock = [0.0]
    timeouts = []

    def slow_commands(command, **kwargs):
        timeouts.append(kwargs["timeout"])
        clock[0] += kwargs["timeout"]
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(smoke.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(smoke.subprocess, "run", slow_commands)
    failures = smoke.run_smoke("eurlex")

    assert timeouts == [120] * 6
    assert any("overall 720s timeout" in message for message in failures)
