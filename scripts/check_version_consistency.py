"""Validate that all distributable package metadata follows APP_VERSION."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
VERSION_ATTRIBUTE = "core.app_meta.APP_VERSION"


def read_app_version(repo_root: Path) -> str:
    source = repo_root / "core" / "app_meta.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "APP_VERSION"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "APP_VERSION":
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError(f"{source} must define APP_VERSION as a string literal")


def validate_tag_name(tag: str, version: str) -> None:
    if not SEMVER.fullmatch(version):
        raise ValueError(f"APP_VERSION must be stable semantic version X.Y.Z, got {version!r}")
    expected = f"v{version}"
    if tag != expected:
        raise ValueError(f"Release tag {tag!r} does not match application version {expected!r}")


def check_version_consistency(repo_root: Path) -> str:
    version = read_app_version(repo_root)
    if not SEMVER.fullmatch(version):
        raise ValueError(f"APP_VERSION must be stable semantic version X.Y.Z, got {version!r}")

    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    if "version" in project or "version" not in project.get("dynamic", []):
        raise ValueError("pyproject.toml must declare a dynamic version sourced from core.app_meta.APP_VERSION")
    dynamic_version = pyproject.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get("version", {})
    if dynamic_version.get("attr") != VERSION_ATTRIBUTE:
        raise ValueError(f"pyproject.toml version source must be {VERSION_ATTRIBUTE!r}")

    frontend = json.loads((repo_root / "frontend" / "package.json").read_text(encoding="utf-8"))
    lockfile = json.loads((repo_root / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    versions = {
        "frontend/package.json": frontend.get("version"),
        "frontend/package-lock.json": lockfile.get("version"),
        "frontend/package-lock.json packages['']": lockfile.get("packages", {}).get("", {}).get("version"),
    }
    mismatches = {name: actual for name, actual in versions.items() if actual != version}
    if mismatches:
        raise ValueError(f"Frontend package versions must match APP_VERSION {version}: {mismatches}")
    return version


def main() -> int:
    try:
        version = check_version_consistency(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        print(f"Version consistency check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Version metadata is consistent: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
