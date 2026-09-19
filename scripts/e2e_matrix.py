#!/usr/bin/env python3
"""Installed-command E2E matrix. Offline is deterministic; live is opt-in."""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import subprocess
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

from eurlex_cli.core import ArtifactCache, CellarClient, EurlexError


ORIGINAL = "32016R0679"
CONSOLIDATION = "02016R0679-20160504"
CORRIGENDUM = "32016R0679R(01)"
PDF = b"%PDF-1.7\ncontrolled installed-E2E fixture\n%%EOF\n"
XHTML = b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>controlled fixture</body></html>'


def sparql(rows):
    return {"head": {"vars": sorted({k for row in rows for k in row})}, "results": {"bindings": [
        {key: {"type": "uri" if value.startswith("http") else "literal", "value": value}
         for key, value in row.items()} for row in rows
    ]}}


def fixture_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/sparql"):
        query = request.url.params["query"]
        identifier = next((value for value in [ORIGINAL, CONSOLIDATION, CORRIGENDUM, "32000R0001"]
                           if value in query), ORIGINAL)
        if identifier == "32000R0001":
            return httpx.Response(200, json=sparql([]))
        work = f"http://publications.europa.eu/resource/cellar/work-{hashlib.sha256(identifier.encode()).hexdigest()[:8]}"
        if "manifestation_manifests_expression" not in query:
            return httpx.Response(200, json=sparql([{"work": work}]))
        lang = "es" if "/SPA>" in query else "en"
        expression = f"{work}.{lang}"
        rows = []
        for cellar_type in ("pdfa1a", "xhtml"):
            manifestation = f"{expression}.{cellar_type}"
            rows.append({"work": work, "expression": expression, "manifestation": manifestation,
                         "type": cellar_type, "item": f"{manifestation}/DOC_1"})
        return httpx.Response(200, json=sparql(rows))
    accept = request.headers["accept"]
    data = PDF if accept.startswith("application/pdf") else XHTML
    content_type = "application/pdf" if data is PDF else "application/xhtml+xml"
    return httpx.Response(200, content=data, headers={"content-type": content_type,
                                                       "content-length": str(len(data))})


def seed(cache_dir: Path, seed_out: Path) -> None:
    client = CellarClient(http=httpx.Client(transport=httpx.MockTransport(fixture_transport)),
                          cache=ArtifactCache(cache_dir))
    for identifier in (ORIGINAL, CONSOLIDATION, CORRIGENDUM):
        client.get(identifier)
        for language in ("en", "es"):
            client.formats(identifier, language)
    try:
        client.get("32000R0001")
    except EurlexError:
        pass
    for language in ("en", "es"):
        for fmt in ("pdf", "xhtml"):
            client.download(ORIGINAL, language, fmt, seed_out / f"{language}-{fmt}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eurlex", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="installed-e2e-", dir=args.evidence.parent))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    cache = root / "cache"
    seed(cache, root / "seed-output")
    results = []

    def case(name, command, args_, expected=0, code=None, cache_dir=cache):
        env = {**os.environ, "EURLEX_CACHE_DIR": str(cache_dir)}
        process = subprocess.run([args.eurlex, command, *args_], text=True, capture_output=True, env=env)
        stream = process.stdout if process.returncode == 0 else process.stderr
        try:
            payload = json.loads(stream)
        except ValueError:
            payload = None
        clean_other_stream = process.stderr == "" if expected == 0 else process.stdout == ""
        summary = None
        passed = process.returncode == expected and payload is not None and clean_other_stream
        try:
            if expected == 0:
                passed = passed and set(payload) == {"schema_version", "data", "source", "warnings"}
                data = payload["data"]
                if command == "get":
                    passed = passed and data["celex"] == args_[0] and data["work"].startswith(
                        "http://publications.europa.eu/resource/cellar/")
                    summary = {"celex": data["celex"], "work": data["work"], "cache": data["cache"]}
                elif command == "formats":
                    reps = data["representations"]
                    required = {"work", "expression", "manifestation", "item", "raw_type",
                                "format", "mime_type", "supported"}
                    passed = passed and data["celex"] == args_[0] and data["language"] == args_[args_.index("--lang") + 1]
                    passed = passed and data["complete"] is True and bool(reps) and all(required <= set(rep) for rep in reps)
                    passed = passed and {rep["work"] for rep in reps} == {data["work"]}
                    summary = {"celex": data["celex"], "language": data["language"], "work": data["work"],
                               "representations": [{key: rep[key] for key in required} for rep in reps]}
                elif command == "download":
                    manifest = data["manifest"]
                    blob = Path(data["path"]).read_bytes()
                    expected_hash = hashlib.sha256(blob).hexdigest()
                    passed = passed and manifest["celex"] == args_[0]
                    passed = passed and manifest["language"] == args_[args_.index("--lang") + 1]
                    passed = passed and manifest["format"] == args_[args_.index("--format") + 1]
                    passed = passed and manifest["sha256"] == expected_hash and manifest["byte_count"] == len(blob)
                    passed = passed and json.loads(Path(data["manifest_path"]).read_text())["sha256"] == expected_hash
                    summary_keys = ("celex", "language", "format", "work", "expression", "manifestation",
                                    "item", "requested_url", "final_url", "retrieved_at", "mime_type",
                                    "response_mime_type", "byte_count", "sha256", "transport", "cache")
                    summary = {key: manifest[key] for key in summary_keys}
                elif command == "doctor":
                    passed = passed and data["cache"]["status"] == "ok"
                    summary = {"cache": data["cache"], "network": data["network"]}
            else:
                passed = passed and set(payload) == {"schema_version", "error"}
                passed = passed and payload.get("error", {}).get("code") == code
                summary = {"error": payload.get("error")}
        except (KeyError, OSError, TypeError, ValueError):
            passed = False
        results.append({"name": name, "command": command, "args": args_, "expected_exit": expected,
                        "actual_exit": process.returncode, "expected_error": code, "passed": bool(passed),
                        "stdout_clean": process.stdout == "" if expected else True,
                        "stderr_clean": process.stderr == "" if expected == 0 else True,
                        "summary": summary})

    # get: exact identities, compatibility, literal validation, missing/cached distinctions.
    case("get-original", "get", [ORIGINAL, "--cache", "only"])
    case("get-json-compat", "get", [ORIGINAL, "--cache", "only", "--json"])
    case("get-consolidation", "get", [CONSOLIDATION, "--cache", "only"])
    case("get-corrigendum", "get", [CORRIGENDUM, "--cache", "only"])
    case("get-known-not-found", "get", ["32000R0001", "--cache", "only"], 3, "not_found")
    case("get-offline-miss", "get", ["32022R2554", "--cache", "only"], 3, "cache_miss")
    case("get-leading-space", "get", [" 32016R0679", "--cache", "only"], 2, "invalid_identifier")
    case("get-trailing-space", "get", ["32016R0679 ", "--cache", "only"], 2, "invalid_identifier")
    case("get-lowercase", "get", ["32016r0679", "--cache", "only"], 2, "invalid_identifier")
    case("get-malformed", "get", ["not-celex", "--cache", "only"], 2, "invalid_identifier")

    # formats: two languages and identity classes plus explicit unsupported inputs.
    case("formats-original-en", "formats", [ORIGINAL, "--lang", "en", "--cache", "only"])
    case("formats-original-es", "formats", [ORIGINAL, "--lang", "es", "--cache", "only"])
    case("formats-json", "formats", [ORIGINAL, "--lang", "en", "--cache", "only", "--json"])
    case("formats-consolidation-en", "formats", [CONSOLIDATION, "--lang", "en", "--cache", "only"])
    case("formats-consolidation-es", "formats", [CONSOLIDATION, "--lang", "es", "--cache", "only"])
    case("formats-corrigendum-en", "formats", [CORRIGENDUM, "--lang", "en", "--cache", "only"])
    case("formats-corrigendum-es", "formats", [CORRIGENDUM, "--lang", "es", "--cache", "only"])
    case("formats-language-fr", "formats", [ORIGINAL, "--lang", "fr", "--cache", "only"], 3, "language_unavailable")
    case("formats-invalid-id", "formats", ["bad", "--lang", "en", "--cache", "only"], 2, "invalid_identifier")
    case("formats-offline-miss", "formats", ["32022R2554", "--lang", "en", "--cache", "only"], 3, "cache_miss")

    # download: both bytes contracts/languages, replay, overwrite and unsupported requests.
    outputs = root / "outputs"
    case("download-en-pdf", "download", [ORIGINAL, "--lang", "en", "--format", "pdf", "--out", str(outputs / "en-pdf"), "--cache", "only"])
    case("download-en-xhtml", "download", [ORIGINAL, "--lang", "en", "--format", "xhtml", "--out", str(outputs / "en-xhtml"), "--cache", "only"])
    case("download-es-pdf", "download", [ORIGINAL, "--lang", "es", "--format", "pdf", "--out", str(outputs / "es-pdf"), "--cache", "only"])
    case("download-es-xhtml", "download", [ORIGINAL, "--lang", "es", "--format", "xhtml", "--out", str(outputs / "es-xhtml"), "--cache", "only"])
    case("download-json", "download", [ORIGINAL, "--lang", "en", "--format", "pdf", "--out", str(outputs / "json"), "--cache", "only", "--json"])
    case("download-second-replay", "download", [ORIGINAL, "--lang", "en", "--format", "pdf", "--out", str(outputs / "replay"), "--cache", "only"])
    case("download-no-overwrite", "download", [ORIGINAL, "--lang", "en", "--format", "pdf", "--out", str(outputs / "en-pdf"), "--cache", "only"], 5, "output_exists")
    case("download-formex", "download", [ORIGINAL, "--lang", "en", "--format", "fmx4", "--out", str(outputs / "fmx"), "--cache", "only"], 3, "unsupported_structure")
    case("download-invalid-id", "download", ["bad", "--lang", "en", "--format", "pdf", "--out", str(outputs / "bad"), "--cache", "only"], 2, "invalid_identifier")
    case("download-offline-miss", "download", ["32022R2554", "--lang", "en", "--format", "pdf", "--out", str(outputs / "miss"), "--cache", "only"], 3, "cache_miss")

    # doctor: cache state variants, JSON compatibility and three corruption modes.
    empty = root / "empty"
    absent = root / "absent"
    case("doctor-populated", "doctor", ["--offline"], cache_dir=cache)
    case("doctor-populated-json", "doctor", ["--offline", "--json"], cache_dir=cache)
    case("doctor-empty", "doctor", ["--offline"], cache_dir=empty)
    case("doctor-absent", "doctor", ["--offline"], cache_dir=absent)
    query_only = root / "query-only"
    ArtifactCache(query_only).store_query("SELECT (1 AS ?ok) WHERE {}", [{"ok": "1"}])
    case("doctor-query-only", "doctor", ["--offline"], cache_dir=query_only)
    cache_file = root / "cache-file"
    cache_file.write_text("not a directory")
    case("doctor-cache-path-file", "doctor", ["--offline"], 1, "cache_corrupt", cache_file)
    for label, content in (("invalid-json", b"{"), ("missing-blob", json.dumps({"sha256": "0" * 64}).encode())):
        bad = root / label
        (bad / "entries").mkdir(parents=True)
        (bad / "entries" / "bad.json").write_bytes(content)
        case(f"doctor-{label}", "doctor", ["--offline"], 1, "cache_corrupt", bad)
    mismatch = root / "mismatch"
    (mismatch / "entries").mkdir(parents=True)
    (mismatch / "blobs").mkdir()
    (mismatch / "entries" / "bad.json").write_text(json.dumps({"sha256": "0" * 64}))
    (mismatch / "blobs" / ("0" * 64)).write_bytes(b"wrong")
    case("doctor-hash-mismatch", "doctor", ["--offline"], 1, "cache_corrupt", mismatch)
    orphan_blob = root / "orphan-blob"
    (orphan_blob / "blobs").mkdir(parents=True)
    (orphan_blob / "blobs" / ("0" * 64)).write_bytes(b"wrong")
    case("doctor-orphan-blob", "doctor", ["--offline"], 1, "cache_corrupt", orphan_blob)
    bad_timestamp = root / "bad-query-timestamp"
    ArtifactCache(bad_timestamp).store_query("SELECT ?x WHERE {}", [{"x": "1"}])
    query_path = next((bad_timestamp / "queries").glob("*.json"))
    query_payload = json.loads(query_path.read_text())
    query_payload["cached_at"] = "garbage"
    query_path.write_text(json.dumps(query_payload))
    case("doctor-query-timestamp", "doctor", ["--offline"], 1, "cache_corrupt", bad_timestamp)
    bad_shape = root / "bad-query-shape"
    ArtifactCache(bad_shape).store_query("SELECT ?x WHERE {}", [{"x": "1"}])
    query_path = next((bad_shape / "queries").glob("*.json"))
    query_payload = json.loads(query_path.read_text())
    query_payload["rows"] = [{"x": 1}]
    query_path.write_text(json.dumps(query_payload))
    case("doctor-query-shape", "doctor", ["--offline"], 1, "cache_corrupt", bad_shape)
    bad_identity = root / "bad-manifest-identity"
    seed(bad_identity, root / "bad-identity-seed")
    entry_path = next((bad_identity / "entries").glob("*.json"))
    entry_payload = json.loads(entry_path.read_text())
    entry_payload["language"] = "es" if entry_payload["language"] == "en" else "en"
    entry_path.write_text(json.dumps(entry_payload))
    case("doctor-manifest-identity", "doctor", ["--offline"], 1, "cache_corrupt", bad_identity)

    counts = Counter(item["command"] for item in results)
    passed = sum(item["passed"] for item in results)
    evidence = {"schema_version": "1.0", "matrix": "controlled-fixture/local-offline",
                "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "installed_executable": str(Path(args.eurlex).resolve()),
                "counts": {"total": len(results), "passed": passed, "failed": len(results) - passed,
                           "by_command": dict(counts)}, "cases": results}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(evidence["counts"], sort_keys=True))
    return 0 if passed == len(results) and all(counts[name] >= 10 for name in ("get", "formats", "download", "doctor")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
