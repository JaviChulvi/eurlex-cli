import hashlib
from pathlib import Path

import httpx
import pytest

from eurlex_cli.core import ArtifactCache, CellarClient, EurlexError
from test_core import EXPR, ITEM_PDF, MAN_PDF, WORK, sparql


PDF = b"%PDF-1.7\ncontrolled fixture only\n%%EOF\n"
XHTML = b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>ok</body></html>'


class FixtureServer:
    def __init__(self, *, items=1, content=PDF, content_type="application/pdf;type=pdfa1a", cellar_type="pdfa1a"):
        self.items = items
        self.content = content
        self.content_type = content_type
        self.cellar_type = cellar_type
        self.requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        if request.url.path.endswith("/sparql"):
            rows = [
                {"work": WORK, "expression": EXPR, "manifestation": MAN_PDF,
                 "item": f"{ITEM_PDF}-{number}", "type": self.cellar_type}
                for number in range(self.items)
            ]
            return httpx.Response(200, json=sparql(*rows))
        if request.url.host == "publications.europa.eu":
            expected = "application/xhtml+xml" if self.cellar_type == "xhtml" else "application/pdf;type=pdfa1a"
            assert request.headers["accept"] == expected
            assert request.headers["accept-language"] == "eng"
            return httpx.Response(200, content=self.content, headers={
                "content-type": self.content_type,
                "content-length": str(len(self.content)),
            })
        raise AssertionError(request.url)


def client(tmp_path, server, mode="auto"):
    cache = ArtifactCache(tmp_path / "cache")
    return CellarClient(http=httpx.Client(transport=httpx.MockTransport(server)), cache=cache, cache_mode=mode)


def test_download_original_bytes_manifest_and_offline_replay(tmp_path):
    server = FixtureServer()
    online = client(tmp_path, server)
    first = online.download("32016R0679", "en", "pdf", tmp_path / "first")
    artifact = Path(first["path"])
    assert artifact.read_bytes() == PDF
    assert first["manifest"]["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert first["manifest"]["requested_url"].startswith("https://publications.europa.eu/")
    assert first["manifest"]["cache"]["hit"] is False

    offline_server = FixtureServer()
    offline = client(tmp_path, offline_server, "only")
    second = offline.download("32016R0679", "en", "pdf", tmp_path / "second")
    assert Path(second["path"]).read_bytes() == PDF
    assert second["manifest"]["sha256"] == first["manifest"]["sha256"]
    assert second["manifest"]["cache"]["hit"] is True
    assert offline_server.requests == 0


def test_multi_item_manifestation_is_ambiguous(tmp_path):
    with pytest.raises(EurlexError) as error:
        client(tmp_path, FixtureServer(items=2)).download(
            "32016R0679", "en", "pdf", tmp_path / "out")
    assert error.value.code == "ambiguous_document"


@pytest.mark.parametrize("content,content_type", [
    (b"<html>upstream error</html>", "text/html"),
    (b"not a pdf", "application/pdf;type=pdfa1a"),
])
def test_payload_validation_rejects_html_and_bad_magic(tmp_path, content, content_type):
    with pytest.raises(EurlexError) as error:
        client(tmp_path, FixtureServer(content=content, content_type=content_type)).download(
            "32016R0679", "en", "pdf", tmp_path / "out")
    assert error.value.code == "download_incomplete"


def test_never_overwrites_existing_output(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    target = out / "32016R0679_en.pdf"
    target.write_bytes(b"mine")
    with pytest.raises(EurlexError) as error:
        client(tmp_path, FixtureServer()).download("32016R0679", "en", "pdf", out)
    assert error.value.code == "output_exists"
    assert target.read_bytes() == b"mine"


def test_manifest_collision_rolls_back_new_artifact(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    manifest = out / "32016R0679_en.manifest.json"
    manifest.write_bytes(b"mine")
    with pytest.raises(EurlexError) as error:
        client(tmp_path, FixtureServer()).download("32016R0679", "en", "pdf", out)
    assert error.value.code == "output_exists"
    assert manifest.read_bytes() == b"mine"
    assert not (out / "32016R0679_en.pdf").exists()


def test_corrupt_cached_blob_is_explicit(tmp_path):
    online = client(tmp_path, FixtureServer())
    result = online.download("32016R0679", "en", "pdf", tmp_path / "first")
    digest = result["manifest"]["sha256"]
    (tmp_path / "cache" / "blobs" / digest).write_bytes(b"corrupt")
    with pytest.raises(EurlexError) as error:
        client(tmp_path, FixtureServer(), "only").download(
            "32016R0679", "en", "pdf", tmp_path / "second")
    assert error.value.code == "cache_corrupt"


def test_explicit_refresh_repairs_corrupt_content_addressed_blob(tmp_path):
    cache_client = client(tmp_path, FixtureServer())
    result = cache_client.download("32016R0679", "en", "pdf", tmp_path / "first")
    digest = result["manifest"]["sha256"]
    blob = tmp_path / "cache" / "blobs" / digest
    blob.write_bytes(b"corrupt")
    client(tmp_path, FixtureServer(), "refresh").download(
        "32016R0679", "en", "pdf", tmp_path / "refreshed")
    replay = client(tmp_path, FixtureServer(), "only").download(
        "32016R0679", "en", "pdf", tmp_path / "replayed")
    assert Path(replay["path"]).read_bytes() == PDF


def test_unsafe_redirect_is_rejected(tmp_path):
    def redirect(request):
        if request.url.path.endswith("/sparql"):
            return FixtureServer()(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    with pytest.raises(EurlexError) as error:
        client(tmp_path, redirect).download("32016R0679", "en", "pdf", tmp_path / "out")
    assert error.value.code == "unsafe_redirect"


def test_safe_https_redirect_is_followed(tmp_path):
    server = FixtureServer()
    redirects = 0
    def redirect(request):
        nonlocal redirects
        if request.url.path.endswith("/sparql"):
            return server(request)
        if request.url.host == "publications.europa.eu":
            redirects += 1
            return httpx.Response(302, headers={"location": "https://op.europa.eu/safe-item"})
        return httpx.Response(200, content=PDF, headers={
            "content-type": "application/pdf", "content-length": str(len(PDF))})
    result = client(tmp_path, redirect).download("32016R0679", "en", "pdf", tmp_path / "out")
    assert result["manifest"]["final_url"] == "https://op.europa.eu/safe-item"
    assert redirects == 1


@pytest.mark.parametrize("url", [
    "https://user:pass@publications.europa.eu/item",
    "https://publications.europa.eu:444/item",
    "https://publications.europa.eu/item#fragment",
])
def test_item_url_rejects_credentials_nondefault_port_and_fragment(tmp_path, url):
    server = FixtureServer()
    with pytest.raises(EurlexError) as error:
        client(tmp_path, server)._fetch_item(url, "application/pdf;type=pdfa1a", "en")
    assert error.value.code == "unsafe_redirect"


def test_http_item_preserves_discovery_and_records_transport_upgrade(tmp_path):
    result = client(tmp_path, FixtureServer()).download("32016R0679", "en", "pdf", tmp_path / "out")
    manifest = result["manifest"]
    assert manifest["item"].startswith("http://")
    assert manifest["requested_url"].startswith("https://")
    assert manifest["transport"]["upgraded_to_https"] is True
    assert manifest["response_mime_type"].startswith("application/pdf")


@pytest.mark.parametrize("content", [
    b"<?xml definitely-not-well-formed",
    b"<html><body>no namespace</body></html>",
    b'<?xml version="1.0"?><!DOCTYPE html [<!ENTITY x "boom">]><html xmlns="http://www.w3.org/1999/xhtml"><body>&x;</body></html>',
])
def test_xhtml_requires_complete_namespaced_entity_safe_xml(tmp_path, content):
    server = FixtureServer(content=content, content_type="application/xhtml+xml", cellar_type="xhtml")
    with pytest.raises(EurlexError) as error:
        client(tmp_path, server).download("32016R0679", "en", "xhtml", tmp_path / "out")
    assert error.value.code == "download_incomplete"


@pytest.mark.parametrize("encoding", ["UTF-16", "UTF-32"])
def test_xhtml_rejects_encoded_entity_declarations(tmp_path, encoding):
    content = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        '<!DOCTYPE html [<!ENTITY x "expanded">]>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>&x;</body></html>'
    ).encode(encoding)
    server = FixtureServer(content=content, content_type="application/xhtml+xml", cellar_type="xhtml")
    with pytest.raises(EurlexError) as error:
        client(tmp_path, server).download("32016R0679", "en", "xhtml", tmp_path / "out")
    assert error.value.code == "download_incomplete"


def test_valid_namespaced_xhtml_is_accepted(tmp_path):
    server = FixtureServer(content=XHTML, content_type="application/xhtml+xml", cellar_type="xhtml")
    result = client(tmp_path, server).download("32016R0679", "en", "xhtml", tmp_path / "out")
    assert Path(result["path"]).read_bytes() == XHTML


def test_ordinary_xhtml_doctype_is_accepted_without_entity_resolution(tmp_path):
    content = b'<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><body>ok</body></html>'
    server = FixtureServer(content=content, content_type="application/xhtml+xml", cellar_type="xhtml")
    result = client(tmp_path, server).download("32016R0679", "en", "xhtml", tmp_path / "out")
    assert Path(result["path"]).read_bytes() == content


def test_external_xhtml_doctype_is_accepted_without_entity_resolution(tmp_path):
    content = (
        b'<!DOCTYPE html SYSTEM "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><body>ok</body></html>'
    )
    server = FixtureServer(content=content, content_type="application/xhtml+xml", cellar_type="xhtml")
    result = client(tmp_path, server).download("32016R0679", "en", "xhtml", tmp_path / "out")
    assert Path(result["path"]).read_bytes() == content


def test_cache_manifest_identity_and_mime_are_validated(tmp_path):
    online = client(tmp_path, FixtureServer())
    online.download("32016R0679", "en", "pdf", tmp_path / "first")
    entry = next((tmp_path / "cache" / "entries").glob("*.json"))
    manifest = __import__("json").loads(entry.read_text())
    manifest["language"] = "es"
    entry.write_text(__import__("json").dumps(manifest))
    with pytest.raises(EurlexError) as error:
        client(tmp_path, FixtureServer(), "only").download("32016R0679", "en", "pdf", tmp_path / "second")
    assert error.value.code == "cache_corrupt"


def test_cached_response_mime_is_revalidated(tmp_path):
    client(tmp_path, FixtureServer()).download("32016R0679", "en", "pdf", tmp_path / "first")
    entry = next((tmp_path / "cache" / "entries").glob("*.json"))
    manifest = __import__("json").loads(entry.read_text())
    manifest["response_mime_type"] = "application/xhtml+xml"
    entry.write_text(__import__("json").dumps(manifest))
    with pytest.raises(EurlexError) as error:
        client(tmp_path, FixtureServer(), "only").download("32016R0679", "en", "pdf", tmp_path / "second")
    assert error.value.code == "cache_corrupt"


def test_output_directory_failure_is_structured(tmp_path):
    out = tmp_path / "a-file"
    out.write_text("not a directory")
    with pytest.raises(EurlexError) as error:
        client(tmp_path, FixtureServer()).download("32016R0679", "en", "pdf", out)
    assert error.value.code == "io_error"


def test_interrupted_transfer_is_explicit(tmp_path):
    def interrupted(request):
        if request.url.path.endswith("/sparql"):
            return FixtureServer()(request)
        raise httpx.ReadError("connection reset", request=request)
    with pytest.raises(EurlexError) as error:
        client(tmp_path, interrupted).download("32016R0679", "en", "pdf", tmp_path / "out")
    assert error.value.code == "download_incomplete"


def test_artifact_content_length_must_match_body(tmp_path):
    server = FixtureServer()
    def mismatched(request):
        if request.url.path.endswith("/sparql"):
            return server(request)
        return httpx.Response(200, content=PDF, headers={
            "content-type": "application/pdf", "content-length": str(len(PDF) + 1)})
    with pytest.raises(EurlexError) as error:
        client(tmp_path, mismatched).download("32016R0679", "en", "pdf", tmp_path / "out")
    assert error.value.code == "download_incomplete"


def test_stream_value_error_subclass_stays_structured(tmp_path):
    class DecodeError(ValueError):
        pass
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            raise DecodeError("controlled decoder failure")
            yield b""
    def responder(request):
        return httpx.Response(200, stream=Broken())
    with pytest.raises(EurlexError) as error:
        client(tmp_path, responder)._fetch_item(ITEM_PDF, "application/pdf;type=pdfa1a", "en")
    assert error.value.code == "download_incomplete"


def test_failed_staging_cleans_temporary_file(tmp_path, monkeypatch):
    def fail_sync(_fd):
        raise OSError("controlled disk failure")
    monkeypatch.setattr("eurlex_cli.core.os.fsync", fail_sync)
    with pytest.raises(EurlexError) as error:
        CellarClient._write_exclusive(tmp_path / "output.pdf", PDF)
    assert error.value.code == "download_incomplete"
    assert list(tmp_path.iterdir()) == []


def test_format_unavailable_and_formex_are_explicit(tmp_path):
    with pytest.raises(EurlexError) as error:
        client(tmp_path, FixtureServer()).download("32016R0679", "en", "xhtml", tmp_path / "out")
    assert error.value.code == "format_unavailable"
    with pytest.raises(EurlexError) as error:
        client(tmp_path, FixtureServer()).download("32016R0679", "en", "fmx4", tmp_path / "out")
    assert error.value.code == "unsupported_structure"
