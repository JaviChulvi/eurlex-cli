import json
from pathlib import Path

import httpx
import pytest

from eurlex_cli.core import CellarClient, EurlexError, validate_celex


WORK = "http://publications.europa.eu/resource/cellar/work-1"
EXPR = "http://publications.europa.eu/resource/cellar/expression-en"
MAN_PDF = "http://publications.europa.eu/resource/cellar/manifestation-pdf"
ITEM_PDF = "http://publications.europa.eu/resource/cellar/item-pdf"


def sparql(*rows):
    variables = sorted({key for row in rows for key in row})
    return {
        "head": {"vars": variables},
        "results": {
            "bindings": [
                {key: {"type": "uri" if value.startswith("http") else "literal", "value": value}
                 for key, value in row.items()}
                for row in rows
            ]
        },
    }


def transport(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/sparql"):
        query = request.url.params["query"]
        assert 'FILTER(STR(?id) = "32016R0679")' in query
        if "manifestation_manifests_expression" in query:
            return httpx.Response(200, json=sparql(
                {"work": WORK, "expression": EXPR, "manifestation": MAN_PDF,
                 "item": ITEM_PDF, "type": "pdfa1a"},
            ))
        return httpx.Response(200, json=sparql({"work": WORK}))
    raise AssertionError(f"unexpected request: {request.url}")


@pytest.mark.parametrize("bad", [" 32016R0679", "32016r0679", "32016R0679 ", "not-celex", "", "32٠١٦R0679"])
def test_celex_is_rejected_literally_before_network(bad):
    with pytest.raises(EurlexError) as error:
        validate_celex(bad)
    assert error.value.code == "invalid_identifier"


@pytest.mark.parametrize("valid", ["32016R0679", "02016R0679-20160504", "32016R0679R(01)"])
def test_supported_original_consolidation_and_corrigendum_syntax(valid):
    assert validate_celex(valid) == valid


def test_get_and_formats_preserve_cellar_hierarchy():
    http = httpx.Client(transport=httpx.MockTransport(transport))
    client = CellarClient(http=http)
    assert client.get("32016R0679")["work"] == WORK
    result = client.formats("32016R0679", "en")
    assert result["complete"] is True
    assert result["representations"] == [{
        "work": WORK, "expression": EXPR, "manifestation": MAN_PDF,
        "item": ITEM_PDF, "format": "pdf",
        "raw_type": "pdfa1a",
        "mime_type": "application/pdf;type=pdfa1a",
        "supported": True,
    }]


def test_language_is_explicit_and_no_fallback():
    http = httpx.Client(transport=httpx.MockTransport(transport))
    client = CellarClient(http=http)
    with pytest.raises(EurlexError) as error:
        client.formats("32016R0679", "fr")
    assert error.value.code == "language_unavailable"


def test_ambiguous_and_missing_identifier_fail_distinctly():
    def responder(request):
        query = request.url.params["query"]
        if "32016M0001" in query:
            return httpx.Response(200, json=sparql())
        return httpx.Response(200, json=sparql({"work": WORK}, {"work": WORK + "-other"}))
    client = CellarClient(http=httpx.Client(transport=httpx.MockTransport(responder)))
    with pytest.raises(EurlexError) as missing:
        client.get("32016M0001")
    assert missing.value.code == "not_found"
    with pytest.raises(EurlexError) as ambiguous:
        client.get("32016R0679")
    assert ambiguous.value.code == "ambiguous_document"


def test_throttling_and_malformed_payload_are_stable():
    throttled = CellarClient(http=httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(429))), sleeper=lambda _seconds: None)
    with pytest.raises(EurlexError) as error:
        throttled.get("32016R0679")
    assert error.value.code == "rate_limited"
    malformed = CellarClient(http=httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, content=b"not-json"))))
    with pytest.raises(EurlexError) as error:
        malformed.get("32016R0679")
    assert error.value.code == "parse_error"


def test_formats_resolves_work_before_language_and_rejects_multiple_works():
    def missing(request):
        return httpx.Response(200, json=sparql())
    with pytest.raises(EurlexError) as error:
        CellarClient(http=httpx.Client(transport=httpx.MockTransport(missing))).formats("32000R0001", "en")
    assert error.value.code == "not_found"

    def ambiguous(request):
        return httpx.Response(200, json=sparql({"work": WORK}, {"work": WORK + "-other"}))
    with pytest.raises(EurlexError) as error:
        CellarClient(http=httpx.Client(transport=httpx.MockTransport(ambiguous))).formats("32016R0679", "en")
    assert error.value.code == "ambiguous_document"


def test_unknown_manifestation_is_visible_and_missing_binding_is_parse_error():
    calls = 0
    def unknown(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=sparql({"work": WORK}))
        return httpx.Response(200, json=sparql({
            "work": WORK, "expression": EXPR, "manifestation": MAN_PDF,
            "item": ITEM_PDF, "type": "future-format",
        }))
    result = CellarClient(http=httpx.Client(transport=httpx.MockTransport(unknown))).formats("32016R0679", "en")
    assert result["representations"][0]["raw_type"] == "future-format"
    assert result["representations"][0]["supported"] is False
    assert result["representations"][0]["format"] is None

    def malformed(request):
        query = request.url.params["query"]
        rows = [{"work": WORK}] if "manifestation_manifests_expression" not in query else [{"work": WORK}]
        return httpx.Response(200, json=sparql(*rows))
    with pytest.raises(EurlexError) as error:
        CellarClient(http=httpx.Client(transport=httpx.MockTransport(malformed))).formats("32016R0679", "en")
    assert error.value.code == "parse_error"


def test_metadata_stream_limit_is_enforced_before_full_body_is_read():
    class TooLarge(httpx.SyncByteStream):
        def __iter__(self):
            yield b"{" + b" " * (2 * 1024 * 1024)
            raise AssertionError("client read beyond metadata limit")
    def responder(request):
        return httpx.Response(200, stream=TooLarge(), headers={"content-type": "application/sparql-results+json"})
    with pytest.raises(EurlexError) as error:
        CellarClient(http=httpx.Client(transport=httpx.MockTransport(responder))).get("32016R0679")
    assert error.value.code == "parse_error"
