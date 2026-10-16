#!/usr/bin/env python3
"""Fetch immutable Football-Data.co.uk historical validation source files."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "validation_sources_20261012"
SEASONS = ("2324", "2425", "2526")
LEAGUES = {"eng.1": "E0", "esp.1": "SP1"}
SOURCE_ROOT = "https://www.football-data.co.uk"


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _fetch(session: requests.Session, url: str, timeout: float) -> tuple[bytes, dict[str, Any]]:
    requested_at = datetime.now(timezone.utc).isoformat()
    response = session.get(url, timeout=timeout)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    body = response.content
    item = {
        "source_url": url,
        "requested_at_utc": requested_at,
        "retrieved_at_utc": retrieved_at,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type"),
        "byte_count": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    if response.status_code != 200:
        raise requests.HTTPError(f"{url} returned HTTP {response.status_code}", response=response)
    if not body:
        raise ValueError(f"{url} returned an empty body")
    return body, item


def fetch_validation_sources(
    output_dir: Path = DEFAULT_OUTPUT,
    leagues: tuple[str, ...] = tuple(LEAGUES),
    seasons: tuple[str, ...] = SEASONS,
    timeout: float = 30.0,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    downloads: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    jobs: list[tuple[str, str | None, str, str]] = []
    for league in leagues:
        if league not in LEAGUES:
            raise ValueError(f"Unsupported league: {league}")
        code = LEAGUES[league]
        for season in seasons:
            if season not in SEASONS:
                raise ValueError(f"Unsupported season: {season}")
            jobs.append((league, season, f"{code}.csv", f"{SOURCE_ROOT}/mmz4281/{season}/{code}.csv"))
    jobs.append(("notes", None, "notes.txt", f"{SOURCE_ROOT}/notes.txt"))

    for league, season, source_name, url in jobs:
        try:
            body, metadata = _fetch(session, url, timeout)
        except Exception as exc:
            errors.append({"source_url": url, "error": f"{type(exc).__name__}: {exc}"})
            response = getattr(exc, "response", None)
            downloads.append({"league": league, "season": season, "source_filename": source_name,
                              "source_url": url, "http_status": getattr(response, "status_code", None),
                              "error": f"{type(exc).__name__}: {exc}"})
            continue

        digest = metadata["sha256"]
        if league == "notes":
            target_name = f"notes_{digest[:12]}.txt"
        else:
            target_name = f"{league.replace('.', '_')}_{season}_{Path(source_name).stem}_{digest[:12]}.csv"
        target = output_dir / target_name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Content-addressed source filename collision: {target}")
        if not target.exists():
            _atomic_write(target, body)
        downloads.append({"league": league, "season": season, "source_filename": source_name,
                          "stored_filename": target_name, **metadata})

    manifest = {
        "schema_version": "football-data-source-manifest-v1",
        "source": "Football-Data.co.uk official historical downloads",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_leagues": list(leagues),
        "requested_seasons": list(seasons),
        "downloads": downloads,
        "errors": errors,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_name = f"manifest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{manifest_hash[:10]}.json"
    _atomic_write(output_dir / manifest_name, manifest_bytes)
    manifest["manifest_filename"] = manifest_name
    if errors:
        raise RuntimeError(f"Fetched {len(downloads) - len(errors)} sources; {len(errors)} failed. See {manifest_name}")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--league", choices=["all", *LEAGUES], default="all")
    parser.add_argument("--seasons", default=",".join(SEASONS), help="Comma-separated season codes: 2324,2425,2526")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    leagues = tuple(LEAGUES) if args.league == "all" else (args.league,)
    seasons = tuple(part.strip() for part in args.seasons.split(",") if part.strip())
    manifest = fetch_validation_sources(args.output_dir, leagues, seasons, args.timeout)
    print(json.dumps({"manifest_filename": manifest["manifest_filename"],
                      "download_count": len(manifest["downloads"]),
                      "output_dir": str(args.output_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
