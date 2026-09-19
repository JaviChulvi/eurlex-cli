#!/usr/bin/env python3
"""Opt-in live CELLAR checks using an installed eurlex executable."""
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


IDENTIFIERS = [
    ("gdpr", "32016R0679"),
    ("dora", "32022R2554"),
    ("nis2", "32022L2555"),
    ("ai-act", "32024R1689"),
    ("gdpr-consolidation", "02016R0679-20160504"),
    ("gdpr-corrigendum", "32016R0679R(01)"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eurlex", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="live-e2e-", dir=args.evidence.parent))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    env = {**os.environ, "EURLEX_CACHE_DIR": str(root / "cache")}
    results = []

    def run(name, command, command_args, check, *, expected_exit=0, expected_code=None,
            execution="real-live/public-CELLAR"):
        process = subprocess.run([args.eurlex, command, *command_args], capture_output=True, text=True, env=env)
        try:
            payload = json.loads(process.stdout if expected_exit == 0 else process.stderr)
        except ValueError:
            payload = None
        assertion = False
        summary = None
        try:
            clean = process.stderr == "" if expected_exit == 0 else process.stdout == ""
            assertion = bool(process.returncode == expected_exit and payload is not None and clean)
            if expected_exit == 0:
                assertion = assertion and set(payload) == {"schema_version", "data", "source", "warnings"}
                assertion = assertion and bool(check(payload))
            else:
                assertion = assertion and set(payload) == {"schema_version", "error"}
                assertion = assertion and payload["error"]["code"] == expected_code
                summary = {"error": payload["error"]}
        except (KeyError, OSError, TypeError, ValueError):
            assertion = False
        if assertion and expected_exit == 0:
            data = payload["data"]
            if command == "get":
                summary = {key: data[key] for key in ("celex", "work")}
                if "source_dates" in data:
                    summary["source_dates"] = data["source_dates"]
            elif command == "formats":
                summary = {"celex": data["celex"], "language": data["language"], "work": data["work"],
                           "representation_count": len(data["representations"]),
                           "representations": data["representations"]}
            elif command == "download":
                manifest = data["manifest"]
                keys = ("celex", "language", "format", "work", "expression", "manifestation", "item",
                        "requested_url", "final_url", "retrieved_at", "mime_type", "response_mime_type",
                        "byte_count", "sha256", "transport", "cache")
                summary = {key: manifest[key] for key in keys}
            else:
                summary = data
        results.append({"name": name, "command": command, "args": command_args,
                        "execution": execution, "expected_exit": expected_exit,
                        "exit": process.returncode, "passed": assertion, "summary": summary})
        return payload if assertion else None

    for label, identifier in IDENTIFIERS:
        run(f"get-{label}", "get", [identifier, "--cache", "refresh"],
            lambda p, expected=identifier: p["data"]["celex"] == expected and p["data"]["work"].startswith("http://publications.europa.eu/resource/cellar/"))
    for label, identifier in IDENTIFIERS:
        for language in ("en", "es"):
            command_args = [identifier, "--lang", language, "--cache", "refresh"]
            if label == "gdpr-corrigendum":
                run(f"formats-{label}-{language}-unavailable", "formats", command_args,
                    lambda _p: False, expected_exit=3, expected_code="language_unavailable")
            else:
                run(f"formats-{label}-{language}", "formats", command_args,
                    lambda p: p["data"]["complete"] is True and len(p["data"]["representations"]) >= 1)

    downloads = [
        ("gdpr-en-pdf", "32016R0679", "en", "pdf"),
        ("gdpr-en-xhtml", "32016R0679", "en", "xhtml"),
        ("gdpr-es-pdf", "32016R0679", "es", "pdf"),
        ("gdpr-es-xhtml", "32016R0679", "es", "xhtml"),
        ("dora-en-xhtml", "32022R2554", "en", "xhtml"),
        ("dora-es-xhtml", "32022R2554", "es", "xhtml"),
        ("nis2-en-xhtml", "32022L2555", "en", "xhtml"),
        ("nis2-es-xhtml", "32022L2555", "es", "xhtml"),
        ("ai-act-en-xhtml", "32024R1689", "en", "xhtml"),
        ("ai-act-es-xhtml", "32024R1689", "es", "xhtml"),
    ]
    def downloaded(payload):
        data = payload["data"]
        path = Path(data["path"])
        blob = path.read_bytes()
        return len(blob) == data["manifest"]["byte_count"] and hashlib.sha256(blob).hexdigest() == data["manifest"]["sha256"]
    for label, identifier, language, fmt in downloads:
        first = run(f"download-{label}", "download",
                    [identifier, "--lang", language, "--format", fmt,
                     "--out", str(root / "downloads" / label), "--cache", "refresh"], downloaded)
        if first is not None:
            original = first["data"]["manifest"]
            def replayed(payload, expected=original):
                if not downloaded(payload):
                    return False
                replay = payload["data"]["manifest"]
                identity = ("celex", "language", "format", "work", "expression", "manifestation", "item",
                            "requested_url", "final_url", "retrieved_at", "mime_type", "response_mime_type",
                            "byte_count", "sha256")
                return all(replay[key] == expected[key] for key in identity) and replay["cache"]["hit"] is True
            run(f"download-{label}-offline-replay", "download",
                [identifier, "--lang", language, "--format", fmt,
                 "--out", str(root / "replays" / label), "--cache", "only"], replayed,
                execution="real-cache-offline")
    for label, identifier in (("dora-en-pdf-a1a-unavailable", "32022R2554"),
                              ("ai-act-en-pdf-a1a-unavailable", "32024R1689")):
        run(f"download-{label}", "download",
            [identifier, "--lang", "en", "--format", "pdf",
             "--out", str(root / "expected-failures" / label), "--cache", "refresh"],
            lambda _p: False, expected_exit=3, expected_code="format_unavailable")
    for number in range(1, 4):
        run(f"doctor-network-{number}", "doctor", [],
            lambda p: p["data"]["network"]["status"] == "ok" and p["data"]["cache"]["status"] == "ok")

    passed = sum(case["passed"] for case in results)
    counts = Counter(case["command"] for case in results)
    execution_counts = Counter(case["execution"] for case in results)
    evidence = {"schema_version": "1.0", "matrix": "real-live/public-CELLAR + real-cache-offline",
                "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "installed_executable": str(Path(args.eurlex).resolve()),
                "counts": {"total": len(results), "passed": passed, "failed": len(results) - passed,
                           "by_command": dict(counts), "by_execution": dict(execution_counts)},
                "cases": results}
    args.evidence.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    print(json.dumps(evidence["counts"], sort_keys=True))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
