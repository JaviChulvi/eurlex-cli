from __future__ import annotations

import re
import hashlib
import json
import os
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException


SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"
CDM = "http://publications.europa.eu/ontology/cdm#"
CELEX_RE = re.compile(r"(?:[1-9][0-9]{4}[A-Z][0-9]{4}(?:R\([0-9]{2}\))?|0[0-9]{4}[A-Z][0-9]{4}-[0-9]{8})\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
LANGUAGES = {"en": "ENG", "es": "SPA"}
CELLAR_TYPES = {
    "pdfa1a": ("pdf", "application/pdf;type=pdfa1a", True),
    "xhtml": ("xhtml", "application/xhtml+xml", True),
    "fmx4": ("fmx4", "application/zip;type=fmx4", False),
}
FORMAT_MIMES = {fmt: mime for fmt, mime, supported in CELLAR_TYPES.values() if supported}
OFFICIAL_HOSTS = {"publications.europa.eu", "op.europa.eu"}
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
XHTML_ROOT = "{http://www.w3.org/1999/xhtml}html"


@dataclass
class EurlexError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None
    exit_code: int = 1

    def __str__(self) -> str:
        return self.message


def validate_celex(value: str) -> str:
    if not CELEX_RE.fullmatch(value):
        raise EurlexError("invalid_identifier", "CELEX identifier has unsupported syntax", {"identifier": value}, 2)
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _key(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is not a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed


def _validate_rows(rows: Any) -> list[dict[str, str]]:
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                         for k, v in row.items())
        for row in rows
    ):
        raise ValueError("invalid query rows")
    return rows


def _official_url(url: Any, *, allow_http: bool) -> tuple[str, bool]:
    if not isinstance(url, str):
        raise ValueError("URL is not a string")
    parsed = urlsplit(url)
    if (parsed.scheme not in ({"http", "https"} if allow_http else {"https"})
            or parsed.hostname not in OFFICIAL_HOSTS or parsed.username is not None
            or parsed.password is not None or parsed.fragment):
        raise ValueError("URL is not an allowed official origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL port") from exc
    default_port = 80 if parsed.scheme == "http" else 443
    if port not in {None, default_port}:
        raise ValueError("non-default URL port")
    upgraded = parsed.scheme == "http"
    normalized = urlunsplit(("https", parsed.hostname, parsed.path or "/", parsed.query, ""))
    return normalized, upgraded


def _validate_payload(data: bytes, selected_mime: str, response_mime: str) -> None:
    expected_base = selected_mime.split(";", 1)[0].lower()
    actual_base = response_mime.split(";", 1)[0].strip().lower()
    if actual_base != expected_base:
        raise ValueError("Content-Type did not match the selected format")
    if expected_base == "application/pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("artifact is not a PDF")
        return
    if expected_base == "application/xhtml+xml":
        try:
            root = DefusedET.fromstring(
                data, forbid_dtd=False, forbid_entities=True, forbid_external=True)
        except (ET.ParseError, DefusedXmlException) as exc:
            raise ValueError("artifact is not well-formed XHTML") from exc
        if root.tag != XHTML_ROOT:
            raise ValueError("artifact does not have a namespaced XHTML root")


def _validate_manifest(manifest: Any, data: bytes, identity: tuple[str, str, str] | None = None) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest is not an object")
    strings = ("schema_version", "celex", "language", "format", "work", "expression",
               "manifestation", "item", "requested_url", "final_url", "retrieved_at",
               "mime_type", "response_mime_type", "sha256")
    if any(not isinstance(manifest.get(field), str) for field in strings):
        raise ValueError("manifest required field is absent or invalid")
    if manifest["schema_version"] != "1.0" or not SHA256_RE.fullmatch(manifest["sha256"]):
        raise ValueError("manifest version or digest is invalid")
    validate_celex(manifest["celex"])
    if manifest["language"] not in LANGUAGES or manifest["format"] not in FORMAT_MIMES:
        raise ValueError("manifest selection is invalid")
    if identity and tuple(manifest[field] for field in ("celex", "language", "format")) != identity:
        raise ValueError("manifest does not match cache key")
    if manifest["mime_type"] != FORMAT_MIMES[manifest["format"]]:
        raise ValueError("manifest selected MIME is invalid")
    if (not isinstance(manifest.get("byte_count"), int) or isinstance(manifest["byte_count"], bool)
            or manifest["byte_count"] != len(data)):
        raise ValueError("manifest byte count is invalid")
    if hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise ValueError("manifest digest does not match")
    _parse_timestamp(manifest["retrieved_at"])
    for field in ("work", "expression", "manifestation"):
        _official_url(manifest[field], allow_http=True)
    normalized_item, upgraded = _official_url(manifest["item"], allow_http=True)
    normalized_request, _ = _official_url(manifest["requested_url"], allow_http=False)
    if manifest["requested_url"] != normalized_request or normalized_item != normalized_request:
        raise ValueError("manifest request URL does not match item transport normalization")
    _official_url(manifest["final_url"], allow_http=False)
    cache = manifest.get("cache")
    transport = manifest.get("transport")
    if (not isinstance(cache, dict) or cache.get("mode") not in {"auto", "only", "refresh", "off"}
            or not isinstance(cache.get("hit"), bool)
            or cache.get("freshness") not in {"fresh", "cached", "not_checked"}
            or not isinstance(transport, dict) or transport.get("upgraded_to_https") is not upgraded):
        raise ValueError("manifest metadata is invalid")
    cached_at = cache.get("cached_at")
    if cached_at is not None:
        _parse_timestamp(cached_at)
    source_dates = manifest.get("source_dates")
    if source_dates is not None and (not isinstance(source_dates, dict)
            or set(source_dates) != {"document_date"}
            or not isinstance(source_dates["document_date"], str)
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", source_dates["document_date"])):
        raise ValueError("manifest source dates are invalid")
    _validate_payload(data, manifest["mime_type"], manifest["response_mime_type"])
    return manifest


@contextmanager
def _staged_file(path: Path, data: bytes):
    handle = tempfile.NamedTemporaryFile(prefix=".eurlex-", dir=path.parent, delete=False)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        yield handle.name
    finally:
        Path(handle.name).unlink(missing_ok=True)


def _read_bounded(response: httpx.Response, limit: int, *, require_exact_length: bool) -> bytes:
    value = response.headers.get("content-length")
    declared = int(value) if value is not None else None
    if declared is not None and (declared > limit or require_exact_length and declared < 0):
        raise OverflowError
    body = bytearray()
    for chunk in response.iter_bytes():
        if len(chunk) > limit - len(body):
            raise OverflowError
        body.extend(chunk)
    if require_exact_length and declared is not None and declared != len(body):
        raise EOFError
    return bytes(body)


class ArtifactCache:
    """Small content-addressed cache; request values only appear behind hashes."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.entries = self.root / "entries"
        self.queries = self.root / "queries"

    def _entry_path(self, celex: str, language: str, fmt: str) -> Path:
        return self.entries / f"{_key(celex, language, fmt)}.json"

    def _read_manifest(self, path: Path, identity: tuple[str, str, str] | None = None) -> tuple[bytes, dict[str, Any]]:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest is not an object")
        digest = manifest.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ValueError("invalid digest")
        data = (self.blobs / digest).read_bytes()
        manifest = _validate_manifest(manifest, data, identity)
        expected_name = f"{_key(manifest['celex'], manifest['language'], manifest['format'])}.json"
        if path.name != expected_name:
            raise ValueError("entry identity mismatch")
        return data, manifest

    @staticmethod
    def _read_query(path: Path) -> tuple[list[dict[str, str]], str]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("query cache is not an object")
        digest = payload.get("query_sha256")
        if (payload.get("schema_version") != "1.0" or not isinstance(digest, str)
                or not SHA256_RE.fullmatch(digest) or path.name != f"{digest}.json"):
            raise ValueError("query identity mismatch")
        _parse_timestamp(payload["cached_at"])
        return _validate_rows(payload["rows"]), payload["cached_at"]

    def load(self, celex: str, language: str, fmt: str) -> tuple[bytes, dict[str, Any]] | None:
        path = self._entry_path(celex, language, fmt)
        if not path.exists():
            return None
        try:
            blob, manifest = self._read_manifest(path, (celex, language, fmt))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, EurlexError) as exc:
            raise EurlexError("cache_corrupt", "Cached artifact metadata is corrupt") from exc
        return blob, manifest

    def store(self, celex: str, language: str, fmt: str, data: bytes, manifest: dict[str, Any]) -> None:
        try:
            digest = _validate_manifest(manifest, data, (celex, language, fmt))["sha256"]
            self.blobs.mkdir(parents=True, exist_ok=True)
            self.entries.mkdir(parents=True, exist_ok=True)
            blob_path = self.blobs / digest
            if not blob_path.exists():
                with _staged_file(blob_path, data) as temporary:
                    try:
                        os.link(temporary, blob_path)
                    except FileExistsError:
                        pass
            if blob_path.read_bytes() != data:
                with _staged_file(blob_path, data) as temporary:
                    os.replace(temporary, blob_path)
            entry = self._entry_path(celex, language, fmt)
            with _staged_file(entry, json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n") as temporary:
                os.replace(temporary, entry)
        except (OSError, ValueError, TypeError) as exc:
            raise EurlexError("io_error", "Could not update the artifact cache", {"reason": str(exc)}) from exc

    def load_query(self, query: str) -> tuple[list[dict[str, str]], str] | None:
        path = self.queries / f"{_key(query)}.json"
        if not path.exists():
            return None
        try:
            return self._read_query(path)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise EurlexError("cache_corrupt", "Cached metadata is corrupt") from exc

    def store_query(self, query: str, rows: list[dict[str, str]]) -> str:
        cached_at = _utc_now()
        try:
            payload = {"schema_version": "1.0", "query_sha256": _key(query),
                       "cached_at": cached_at, "rows": _validate_rows(rows)}
            self.queries.mkdir(parents=True, exist_ok=True)
            path = self.queries / f"{_key(query)}.json"
            with _staged_file(path, json.dumps(payload, sort_keys=True).encode() + b"\n") as temporary:
                os.replace(temporary, path)
        except (OSError, ValueError, TypeError) as exc:
            raise EurlexError("io_error", "Could not update the metadata cache", {"reason": str(exc)}) from exc
        return cached_at

    def check(self) -> dict[str, Any]:
        checked = queries_checked = blobs_checked = 0
        try:
            for cache_path in (self.root, self.blobs, self.entries, self.queries):
                if cache_path.exists() and not cache_path.is_dir():
                    raise OSError(f"cache path is not a directory: {cache_path}")
            entry_files = list(self.entries.glob("*.json")) if self.entries.exists() else []
            query_files = list(self.queries.glob("*.json")) if self.queries.exists() else []
            blob_files = list(self.blobs.iterdir()) if self.blobs.exists() else []
        except OSError as exc:
            raise EurlexError("cache_corrupt", "Cache paths cannot be inspected") from exc
        for blob_path in blob_files:
            try:
                if not blob_path.is_file() or not SHA256_RE.fullmatch(blob_path.name):
                    raise ValueError("blob path is invalid")
                if hashlib.sha256(blob_path.read_bytes()).hexdigest() != blob_path.name:
                    raise ValueError("blob digest mismatch")
                blobs_checked += 1
            except (OSError, ValueError) as exc:
                raise EurlexError("cache_corrupt", f"Cache integrity check failed for blob {blob_path.name}") from exc
        for entry in entry_files:
            try:
                self._read_manifest(entry)
                checked += 1
            except (OSError, ValueError, KeyError, TypeError, AttributeError, EurlexError) as exc:
                raise EurlexError("cache_corrupt", f"Cache integrity check failed for {entry.name}") from exc
        for query_path in query_files:
            try:
                self._read_query(query_path)
                queries_checked += 1
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise EurlexError("cache_corrupt", f"Cache integrity check failed for {query_path.name}") from exc
        return {"status": "ok", "artifacts_checked": checked, "blobs_checked": blobs_checked,
                "queries_checked": queries_checked, "path": str(self.root)}

class CellarClient:
    def __init__(self, http: httpx.Client | None = None, cache: ArtifactCache | None = None,
                 cache_mode: str = "auto", sleeper: Any = time.sleep) -> None:
        if cache_mode not in {"auto", "only", "refresh", "off"}:
            raise EurlexError("invalid_option", "Cache mode must be auto, only, refresh, or off", exit_code=2)
        self.http = http or httpx.Client(
            timeout=httpx.Timeout(20, connect=10),
            follow_redirects=False,
            headers={"User-Agent": "eurlex-cli/0.1 (+https://op.europa.eu/)"},
        )
        self.cache = cache
        self.cache_mode = cache_mode
        self.sleeper = sleeper
        self.last_query_cache: dict[str, Any] = {"hit": False, "cached_at": None, "freshness": "fresh"}

    def _query(self, query: str) -> list[dict[str, str]]:
        cached = self.cache.load_query(query) if self.cache and self.cache_mode in {"auto", "only"} else None
        if cached:
            rows, cached_at = cached
            age = datetime.now(timezone.utc) - datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
            if self.cache_mode == "only" or age <= timedelta(hours=24):
                self.last_query_cache = {"hit": True, "cached_at": cached_at,
                                         "freshness": "not_checked" if self.cache_mode == "only" else "cached"}
                return rows
        if self.cache_mode == "only":
            raise EurlexError("cache_miss", "Metadata is not available offline", exit_code=3)
        response = None
        body = b""
        for attempt in range(3):
            try:
                with self.http.stream("GET", SPARQL_URL, params={
                        "query": query, "format": "application/sparql-results+json",
                }, headers={"Accept": "application/sparql-results+json"}) as streamed:
                    response = streamed
                    try:
                        body = _read_bounded(streamed, MAX_METADATA_BYTES, require_exact_length=False)
                    except OverflowError as exc:
                        raise EurlexError(
                            "parse_error", "SPARQL response exceeds the 2 MiB safety limit") from exc
            except EurlexError:
                raise
            except httpx.HTTPError as exc:
                if attempt < 2:
                    self.sleeper(min(0.25 * (2 ** attempt), 2))
                    continue
                raise EurlexError("upstream_unavailable", "CELLAR request failed", {"reason": str(exc)}) from exc
            except ValueError as exc:
                raise EurlexError("parse_error", "Invalid SPARQL Content-Length") from exc
            if response.status_code not in {429, 502, 503, 504}:
                break
            if attempt < 2:
                self._retry_delay(response, attempt)
        assert response is not None
        if response.status_code == 429:
            raise EurlexError("rate_limited", "CELLAR rate limit reached")
        if response.status_code >= 400:
            raise EurlexError("upstream_unavailable", f"CELLAR returned HTTP {response.status_code}")
        if response.headers.get("content-type", "").lower().startswith("text/html"):
            raise EurlexError("parse_error", "CELLAR returned HTML instead of SPARQL JSON")
        try:
            payload = json.loads(body)
            bindings = payload["results"]["bindings"]
            if not isinstance(bindings, list):
                raise TypeError("bindings is not a list")
            rows = []
            for row in bindings:
                if not isinstance(row, dict):
                    raise TypeError("binding is not an object")
                parsed_row = {}
                for key, cell in row.items():
                    if not isinstance(key, str) or not isinstance(cell, dict) or not isinstance(cell.get("value"), str):
                        raise TypeError("binding cell is malformed")
                    parsed_row[key] = cell["value"]
                rows.append(parsed_row)
        except (ValueError, KeyError, TypeError) as exc:
            raise EurlexError("parse_error", "Invalid SPARQL response") from exc
        cached_at = self.cache.store_query(query, rows) if self.cache and self.cache_mode != "off" else None
        self.last_query_cache = {"hit": False, "cached_at": cached_at, "freshness": "fresh"}
        return rows

    def _retry_delay(self, response: httpx.Response, attempt: int) -> None:
        value = response.headers.get("retry-after")
        try:
            if value is None:
                delay = 0.25 * (2 ** attempt)
            else:
                try:
                    delay = float(value)
                except ValueError:
                    retry_at = parsedate_to_datetime(value)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            delay = 0.25 * (2 ** attempt)
        delay = min(max(delay, 0), 2)
        if delay:
            self.sleeper(delay)

    def get(self, celex: str) -> dict[str, Any]:
        validate_celex(celex)
        query = f"""PREFIX cdm: <{CDM}>
SELECT DISTINCT ?work ?document_date WHERE {{
  ?work cdm:resource_legal_id_celex ?id .
  FILTER(STR(?id) = \"{celex}\")
  OPTIONAL {{ ?work cdm:work_date_document ?document_date . }}
}} ORDER BY STR(?work) STR(?document_date) LIMIT 101"""
        rows = self._query(query)
        if not rows:
            raise EurlexError("not_found", "No CELLAR work found", {"identifier": celex}, 3)
        try:
            works = {row["work"] for row in rows}
        except (KeyError, TypeError) as exc:
            raise EurlexError("parse_error", "Work binding is missing") from exc
        if len(rows) > 100:
            raise EurlexError("parse_error", "Work query exceeded safety limit")
        if len(works) > 1:
            raise EurlexError("ambiguous_document", "CELEX resolved to multiple works", {"identifier": celex}, 4)
        dates = sorted({row["document_date"] for row in rows if "document_date" in row})
        if any(not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) for value in dates) or len(dates) > 1:
            raise EurlexError("parse_error", "Document date binding is invalid or ambiguous")
        result = {"celex": celex, "work": next(iter(works)), "cache": self.last_query_cache}
        if dates:
            result["source_dates"] = {"document_date": dates[0]}
        return result

    def formats(self, celex: str, language: str) -> dict[str, Any]:
        validate_celex(celex)
        if language not in LANGUAGES:
            raise EurlexError("language_unavailable", "Supported languages are en and es", {"language": language}, 3)
        resolved = self.get(celex)
        resolved_work = resolved["work"]
        authority = LANGUAGES[language]
        query = f"""PREFIX cdm: <{CDM}>
SELECT DISTINCT ?work ?expression ?manifestation ?type ?item WHERE {{
  ?work cdm:resource_legal_id_celex ?id .
  FILTER(STR(?id) = \"{celex}\")
  ?expression cdm:expression_belongs_to_work ?work ;
              cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/{authority}> .
  ?manifestation cdm:manifestation_manifests_expression ?expression ;
                 cdm:manifestation_type ?type .
  ?item cdm:item_belongs_to_manifestation ?manifestation .
}} ORDER BY STR(?manifestation) STR(?item) LIMIT 101"""
        rows = self._query(query)
        if len(rows) > 100:
            raise EurlexError("parse_error", "Representation query exceeded safety limit")
        if not rows:
            raise EurlexError("language_unavailable", "Requested language is unavailable", {"language": language}, 3)
        representations = []
        for row in rows:
            required = ("work", "expression", "manifestation", "type", "item")
            if any(field not in row for field in required):
                raise EurlexError("parse_error", "Representation binding is missing required fields")
            if row["work"] != resolved_work:
                raise EurlexError("ambiguous_document", "Representation belongs to a different work", exit_code=4)
            cellar_type = row["type"]
            fmt, mime, supported = CELLAR_TYPES.get(cellar_type, (None, None, False))
            representations.append({
                "work": row["work"], "expression": row["expression"],
                "manifestation": row["manifestation"], "item": row["item"],
                "raw_type": cellar_type, "format": fmt, "mime_type": mime, "supported": supported,
            })
        result = {"celex": celex, "language": language, "work": resolved_work, "complete": True,
                "representations": representations, "cache": self.last_query_cache}
        if "source_dates" in resolved:
            result["source_dates"] = resolved["source_dates"]
        return result

    def _fetch_item(self, url: str, mime: str, language: str) -> tuple[bytes, str, str]:
        try:
            current, _ = _official_url(url, allow_http=True)
        except ValueError as exc:
            raise EurlexError("unsafe_redirect", "CELLAR item URL is not an allowed official host")
        for attempt in range(3):
            try:
                for _ in range(6):
                    with self.http.stream("GET", current, headers={
                        "Accept": mime, "Accept-Language": LANGUAGES[language].lower(),
                    }) as response:
                        if response.status_code in {429, 502, 503, 504} and attempt < 2:
                            self._retry_delay(response, attempt)
                            break
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise EurlexError("unsafe_redirect", "Redirect had no location")
                            try:
                                current, _ = _official_url(urljoin(current, location), allow_http=False)
                            except ValueError as exc:
                                raise EurlexError("unsafe_redirect", "Redirect target is not an allowed HTTPS official host")
                            continue
                        if response.status_code == 429:
                            raise EurlexError("rate_limited", "CELLAR rate limit reached")
                        if response.status_code >= 400:
                            raise EurlexError("upstream_unavailable", f"CELLAR returned HTTP {response.status_code}")
                        try:
                            data = _read_bounded(response, MAX_ARTIFACT_BYTES, require_exact_length=True)
                        except OverflowError as exc:
                            raise EurlexError("download_incomplete", "Artifact exceeds the 64 MiB safety limit") from exc
                        except ValueError as exc:
                            raise EurlexError("download_incomplete", "Artifact Content-Length is invalid") from exc
                        except EOFError as exc:
                            raise EurlexError("download_incomplete", "Artifact length did not match Content-Length") from exc
                        content_type = response.headers.get("content-type", "").split(",", 1)[0].strip().lower()
                        try:
                            _validate_payload(data, mime, content_type)
                        except ValueError as exc:
                            raise EurlexError("download_incomplete", str(exc)) from exc
                        return data, str(response.url), content_type
                else:
                    raise EurlexError("unsafe_redirect", "Too many redirects")
            except EurlexError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                if attempt == 2:
                    raise EurlexError("download_incomplete", "Artifact transfer was interrupted", {"reason": str(exc)}) from exc
                self.sleeper(min(0.25 * (2 ** attempt), 2))
        raise EurlexError("upstream_unavailable", "CELLAR remained unavailable after bounded retries")

    def download(self, celex: str, language: str, fmt: str, out: Path) -> dict[str, Any]:
        validate_celex(celex)
        if language not in LANGUAGES:
            raise EurlexError("language_unavailable", "Supported languages are en and es", {"language": language}, 3)
        if fmt == "fmx4":
            raise EurlexError("unsupported_structure", "Formex bundles are not supported", exit_code=3)
        if fmt not in FORMAT_MIMES:
            raise EurlexError("format_unavailable", "Supported formats are pdf and xhtml", {"format": fmt}, 3)

        cached = self.cache.load(celex, language, fmt) if self.cache and self.cache_mode in {"auto", "only"} else None
        if self.cache_mode == "only" and cached is None:
            raise EurlexError("cache_miss", "Artifact is not available offline", exit_code=3)
        if cached:
            data, original_manifest = cached
            manifest = {**original_manifest, "cache": {
                "mode": self.cache_mode, "hit": True,
                "cached_at": original_manifest.get("cache", {}).get("cached_at"),
                "freshness": "not_checked",
            }}
        else:
            listed = self.formats(celex, language)
            matches = [item for item in listed["representations"] if item["format"] == fmt]
            if not matches:
                raise EurlexError("format_unavailable", "Requested format is unavailable", {"format": fmt}, 3)
            if len(matches) != 1:
                raise EurlexError("ambiguous_document", "Format has multiple items; selection is unsafe", exit_code=4)
            selected = matches[0]
            discovered_url = selected["item"]
            try:
                requested_url, upgraded = _official_url(discovered_url, allow_http=True)
            except ValueError as exc:
                raise EurlexError("unsafe_redirect", "CELLAR item URL is not an allowed official host") from exc
            data, final_url, response_mime = self._fetch_item(discovered_url, selected["mime_type"], language)
            now = _utc_now()
            manifest = {
                "schema_version": "1.0", "celex": celex, "language": language,
                "format": fmt, "work": selected["work"], "expression": selected["expression"],
                "manifestation": selected["manifestation"], "item": selected["item"],
                "requested_url": requested_url,
                "final_url": final_url, "retrieved_at": now,
                "mime_type": selected["mime_type"], "response_mime_type": response_mime,
                "byte_count": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "transport": {"upgraded_to_https": upgraded},
                "cache": {"mode": self.cache_mode, "hit": False,
                          "cached_at": now if self.cache_mode != "off" else None,
                          "freshness": "fresh"},
            }
            if "source_dates" in listed:
                manifest["source_dates"] = listed["source_dates"]
            if self.cache and self.cache_mode != "off":
                self.cache.store(celex, language, fmt, data, manifest)

        out = Path(out)
        try:
            out.mkdir(parents=True, exist_ok=True)
            if not out.is_dir():
                raise OSError("output path is not a directory")
        except OSError as exc:
            raise EurlexError("io_error", "Could not create the output directory", {"reason": str(exc)}) from exc
        artifact = out / f"{celex}_{language}.{fmt}"
        manifest_path = out / f"{celex}_{language}.manifest.json"
        self._write_exclusive(artifact, data)
        try:
            self._write_exclusive(manifest_path, json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n")
        except Exception:
            artifact.unlink(missing_ok=True)
            raise
        return {"path": str(artifact), "manifest_path": str(manifest_path), "manifest": manifest}

    @staticmethod
    def _write_exclusive(path: Path, data: bytes) -> None:
        try:
            with _staged_file(path, data) as temporary:
                os.link(temporary, path)
        except FileExistsError as exc:
            raise EurlexError("output_exists", "Output already exists; refusing to overwrite", exit_code=5) from exc
        except OSError as exc:
            raise EurlexError("download_incomplete", "Could not write the complete output", {"reason": str(exc)}) from exc
