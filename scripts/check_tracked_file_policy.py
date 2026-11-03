"""Fail CI if local data, credentials, or generated build output is tracked."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable


FORBIDDEN_PREFIXES = (
    "data/",
    "backups/",
    "dist/",
    "build/",
    "frontend/dist/",
    "frontend/node_modules/",
    ".venv/",
    ".pytest_cache/",
)
FORBIDDEN_EXACT = {
    ".env",
    "config/odds_api.yaml",
    "config/line_notifier.yaml",
}
FORBIDDEN_SUFFIXES = (".sqlite", ".sqlite3", ".db", ".exe", ".bak")


def find_prohibited_paths(paths: Iterable[str]) -> list[str]:
    prohibited = []
    for raw_path in paths:
        path = raw_path.replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        normalized = path.casefold()
        name = normalized.rsplit("/", 1)[-1]
        if (
            normalized in FORBIDDEN_EXACT
            or (normalized.startswith("config/") and ".local." in name)
            or any(normalized.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
            or name == ".env"
            or (name.startswith(".env.") and name != ".env.example")
            or normalized.endswith(FORBIDDEN_SUFFIXES)
        ):
            prohibited.append(raw_path)
    return prohibited


def tracked_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo_root, check=True, capture_output=True
    )
    return [part.decode("utf-8", errors="surrogateescape") for part in result.stdout.split(b"\0") if part]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        prohibited = find_prohibited_paths(tracked_paths(root))
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Tracked-file policy check failed: {exc}", file=sys.stderr)
        return 2
    if prohibited:
        print("Prohibited tracked files found:", file=sys.stderr)
        for path in prohibited:
            print(f"  {path}", file=sys.stderr)
        return 1
    print("Tracked-file policy passed; local data, credentials, and build outputs are untracked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
