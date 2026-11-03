# Repository governance

## Rights and reuse

This repository intentionally has no `LICENSE` file and grants no open-source
license. All rights are reserved by the applicable rights holders. Do not
assume that public visibility grants permission to copy, modify, redistribute,
or use the software. A future license change requires an explicit owner
decision.

## Version and release authority

`core/app_meta.py` is the canonical source for the application semantic version
(`APP_VERSION`). The Python wheel reads it through setuptools dynamic metadata;
the frontend package and lockfile must carry the same version. CI checks these
values together. `APP_BUILD` identifies a development build and does not set a
release version. Strategy or research-rule identifiers are separate from the
application version.

A published release must use the exact tag `v<APP_VERSION>`. The tagged commit
must be reachable from `main`; the release workflow rejects mismatched tags and
commits outside that history before building installers. Do not create a tag or
GitHub Release as part of ordinary `dev` work.

## File and data classes

| Class | Examples | Handling |
| --- | --- | --- |
| Source and tests | `core/`, `server/`, `frontend/src/`, `tests/` | Review and test as normal code. |
| Public configuration templates | `config/*.example.yaml` | Keep credential-free and safe to share. |
| Local configuration and secrets | `.env*`, `config/*.local.*`, API keys, webhook secrets | Keep untracked; never paste credentials into fixtures or logs. Rotate a credential if it is committed. |
| Operational and personal data | `data/`, SQLite ledgers, backups, local research history | Keep outside version control. Preserve the local data junction and formal data; do not copy it into test fixtures. |
| Research evidence artifacts | `artifacts/` and source-capture fixtures | Treat timestamped evidence and its manifests as historical records. Do not rewrite or delete it to make a check pass; add new evidence in a new, clearly dated location. |
| Generated outputs | `build/`, `dist/`, `*.egg-info/`, frontend bundles, executables | Regenerate from source; do not commit unless a release-specific workflow explicitly requires an artifact. |

When changing ignore rules or evidence retention, check tracked files first.
Preserve the byte identity of captured source bodies covered by SHA-256
manifests. The `data/` entry is a local junction and must not be traversed by
repository cleanup or test commands.

## Change and evidence expectations

Keep source changes, tests, and user-facing claims aligned. A passing offline
test validates only its fixtures and mocked/local contracts. It does not prove
that a live market source returned data, that an event was aligned, or that a
real forward sample settled. See [quality gates](QUALITY_GATES.md) for the
validation boundary and evidence required for operational claims.
