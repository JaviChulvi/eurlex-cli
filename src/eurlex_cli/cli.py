from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Any

import typer

from .core import ArtifactCache, CellarClient, EurlexError, SPARQL_URL


app = typer.Typer(add_completion=False, no_args_is_help=True, help="Retrieve exact EU legal sources from CELLAR.")


def cache_root() -> Path:
    configured = os.environ.get("EURLEX_CACHE_DIR")
    if configured:
        return Path(configured)
    xdg = os.environ.get("XDG_CACHE_HOME")
    return Path(xdg) / "eurlex" if xdg else Path.home() / ".cache" / "eurlex"


def make_client(mode: str = "auto") -> CellarClient:
    return CellarClient(cache=ArtifactCache(cache_root()), cache_mode=mode)


def envelope(data: Any, source: dict[str, Any] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    return {"schema_version": "1.0", "data": data, "source": source or {}, "warnings": warnings or []}


def _emit(action: Callable[[], dict[str, Any]]) -> None:
    try:
        typer.echo(json.dumps(action(), sort_keys=True))
    except EurlexError as exc:
        error = {"schema_version": "1.0", "error": {
            "code": exc.code, "message": exc.message, "details": exc.details or {},
        }}
        typer.echo(json.dumps(error, sort_keys=True), err=True)
        raise typer.Exit(exc.exit_code)


def _source(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    cached = data.get("cache", {})
    source = {"endpoint": SPARQL_URL, "cache": cached}
    warnings = ["Metadata was replayed offline and was not freshness-checked."] if cached.get("freshness") == "not_checked" else []
    return source, warnings


@app.command()
def get(identifier: str, json_output: bool = typer.Option(False, "--json", help="Compatibility flag; JSON is the default."),
        cache: str = typer.Option("auto", "--cache")) -> None:
    """Resolve one exact CELEX identifier."""
    def run() -> dict[str, Any]:
        data = make_client(cache).get(identifier)
        source, warnings = _source(data)
        return envelope(data, source, warnings)
    _emit(run)


@app.command()
def formats(identifier: str, lang: str = typer.Option(..., "--lang"),
            json_output: bool = typer.Option(False, "--json"),
            cache: str = typer.Option("auto", "--cache")) -> None:
    """List supported item representations for one language."""
    def run() -> dict[str, Any]:
        data = make_client(cache).formats(identifier, lang)
        source, warnings = _source(data)
        return envelope(data, source, warnings)
    _emit(run)


@app.command()
def download(identifier: str, lang: str = typer.Option(..., "--lang"),
             format_: str = typer.Option(..., "--format"), out: Path = typer.Option(..., "--out"),
             json_output: bool = typer.Option(False, "--json"),
             cache: str = typer.Option("auto", "--cache")) -> None:
    """Download one unambiguous official item and provenance manifest."""
    def run() -> dict[str, Any]:
        data = make_client(cache).download(identifier, lang, format_, out)
        manifest = data["manifest"]
        return envelope(data, {"requested_url": manifest["requested_url"],
                               "final_url": manifest["final_url"], "cache": manifest["cache"]})
    _emit(run)


@app.command()
def doctor(offline: bool = typer.Option(False, "--offline"),
           json_output: bool = typer.Option(False, "--json")) -> None:
    """Check cache integrity and optionally CELLAR connectivity."""
    def run() -> dict[str, Any]:
        cache = ArtifactCache(cache_root())
        cache_check = cache.check()
        if offline:
            network = {"status": "skipped", "reason": "offline mode"}
        else:
            client = CellarClient(cache=None, cache_mode="off")
            client._query("SELECT (1 AS ?ok) WHERE {} LIMIT 1")
            network = {"status": "ok", "endpoint": SPARQL_URL}
        return envelope({"cache": cache_check, "network": network},
                        {"endpoint": SPARQL_URL if not offline else None})
    _emit(run)


if __name__ == "__main__":
    app()
