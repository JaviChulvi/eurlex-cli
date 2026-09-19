#!/usr/bin/env python3
"""Eight-check, bounded smoke test of the installed eurlex CLI."""
import argparse, hashlib, json, os, shutil, subprocess, tempfile, time
from pathlib import Path
CELEX, FIELDS = "32016R0679", {"schema_version", "data", "source", "warnings"}
class SmokeFailure(Exception): pass
def require(condition, message):
    if not condition:
        raise SmokeFailure(message)
def parse(name, result, expected=None):
    if expected:
        require(not result.stdout and result.returncode == 2,
                f"{name}: expected error, exit {result.returncode}")
        try:
            body = json.loads(result.stderr); error = body["error"]
            valid = (set(body) == {"schema_version", "error"} and body["schema_version"] == "1.0"
                     and set(error) == {"code", "message", "details"})
        except (ValueError, KeyError, TypeError):
            valid = False
        require(valid and error["code"] == expected,
                f"{name}: malformed/unexpected error, exit {result.returncode}")
        return body
    if result.returncode:
        try:
            error = json.loads(result.stderr)["error"]
            detail = f"{error['code']}: {error['message']}"
        except (ValueError, KeyError, TypeError):
            detail = result.stderr.strip() or "no error output"
        raise SmokeFailure(f"{name}: exit {result.returncode} {detail}")
    require(not result.stderr, f"{name}: unexpected stderr: {result.stderr.strip()}")
    try:
        body = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise SmokeFailure(f"{name}: invalid JSON") from None
    valid = (isinstance(body, dict) and set(body) == FIELDS and body["schema_version"] == "1.0"
             and isinstance(body["data"], dict) and isinstance(body["source"], dict)
             and isinstance(body["warnings"], list))
    require(valid, f"{name}: invalid success envelope")
    return body
def verify_artifact(body, language, fmt):
    try:
        result, manifest = body["data"], body["data"]["manifest"]
        raw = Path(result["path"]).read_bytes(); disk_manifest = json.loads(Path(result["manifest_path"]).read_text())
        digest = hashlib.sha256(raw).hexdigest()
        valid = disk_manifest == manifest
        valid &= (manifest["celex"], manifest["language"], manifest["format"]) == (CELEX, language, fmt)
        valid &= manifest["byte_count"] == len(raw) and manifest["sha256"] == digest
        valid &= manifest["item"].startswith(("http://publications.europa.eu/", "https://publications.europa.eu/"))
        valid &= body["source"]["requested_url"] == manifest["requested_url"]
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    require(valid, f"download {language} {fmt}: artifact hash/manifest invalid")
    return digest
def run_smoke(exe):
    deadline, state, failures = time.monotonic() + 90, {}, []
    with tempfile.TemporaryDirectory(prefix="eurlex-smoke-") as temporary:
        root = Path(temporary); env = {**os.environ, "EURLEX_CACHE_DIR": str(root / "cache")}
        def check(name, args, validate=lambda body: None, expected=None):
            try:
                remaining = deadline - time.monotonic(); require(remaining > 0, f"{name}: overall 90s timeout")
                result = subprocess.run([exe, *args], text=True, capture_output=True, env=env,
                                        timeout=min(25, remaining), check=False)
                body = parse(name, result, expected); validate(body); state[name] = body
            except subprocess.TimeoutExpired:
                failures.append(f"{name}: timeout")
            except (SmokeFailure, OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
                failures.append(str(exc) if isinstance(exc, SmokeFailure) else f"{name}: {exc}")
        check("doctor", ["doctor", "--json"], lambda b: require(
            b["data"]["network"]["status"] == b["data"]["cache"]["status"] == "ok", "doctor: health not ok"))
        check("get", ["get", CELEX, "--cache", "refresh", "--json"], lambda b: require(
            b["data"]["celex"] == CELEX and b["data"]["work"].startswith("http://publications.europa.eu/"), "get: identity/source mismatch"))
        def has_format(language, fmt):
            return lambda b: require(b["data"]["celex"] == CELEX and b["data"]["language"] == language and b["data"]["complete"] is True
                and any(r["format"] == fmt and r["supported"] for r in b["data"]["representations"]), f"formats {language}: {fmt} missing")
        check("formats en", ["formats", CELEX, "--lang", "en", "--json"], has_format("en", "pdf"))
        check("formats es", ["formats", CELEX, "--lang", "es", "--json"], has_format("es", "xhtml"))
        def download(name, lang, fmt, mode, folder, validator):
            check(name, ["download", CELEX, "--lang", lang, "--format", fmt, "--cache", mode,
                         "--out", str(root / folder), "--json"], validator)
        download("download en pdf", "en", "pdf", "refresh", "en", lambda b: state.update(pdf_hash=verify_artifact(b, "en", "pdf")))
        download("download es xhtml", "es", "xhtml", "refresh", "es", lambda b: verify_artifact(b, "es", "xhtml"))
        download("offline replay", "en", "pdf", "only", "offline", lambda b: require(
            verify_artifact(b, "en", "pdf") == state.get("pdf_hash") and b["data"]["manifest"]["cache"]["hit"], "offline replay: cache/hash mismatch"))
        check("invalid identifier", ["get", "not-a-celex", "--json"], expected="invalid_identifier")
    return failures
def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    exe = shutil.which("eurlex")
    if not exe: print("FAIL setup: eurlex executable not found\nFAIL 8/8 source_available=unknown"); return 1
    failures = run_smoke(exe)
    for failure in failures: print("FAIL " + failure.replace("\n", " ")[:200])
    print("PASS 8/8" if not failures else f"FAIL {len(failures)}/8 source_available=unknown")
    return bool(failures)
if __name__ == "__main__":
    raise SystemExit(main())
