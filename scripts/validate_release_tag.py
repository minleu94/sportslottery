"""Require release tags to match APP_VERSION and point into main history."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from check_version_consistency import check_version_consistency, validate_tag_name


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def validate_release(repo_root: Path, ref: str, expected_sha: str = "") -> str | None:
    """Return None for non-tag builds; validate release tag version and ancestry otherwise."""
    if not ref.startswith("refs/tags/"):
        return None

    version = check_version_consistency(repo_root)
    tag = ref.removeprefix("refs/tags/")
    validate_tag_name(tag, version)

    head = _git(repo_root, "rev-parse", "HEAD")
    commit = expected_sha or head
    if commit != head:
        raise ValueError(f"Checked out commit {head} does not match release commit {commit}")
    main_ref = os.environ.get("RELEASE_MAIN_REF", "origin/main")
    _git(repo_root, "rev-parse", "--verify", f"{main_ref}^{{commit}}")
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, main_ref],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"Release commit {commit} is not an ancestor of {main_ref}")
    return tag


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ref = os.environ.get("GITHUB_REF", "")
    sha = os.environ.get("GITHUB_SHA", "")
    try:
        tag = validate_release(root, ref, sha)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        return 1
    if tag is None:
        print("Non-tag build; no release will be published.")
    else:
        print(f"Validated {tag}: version matches and commit is reachable from main.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
