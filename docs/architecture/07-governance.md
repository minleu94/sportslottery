# Dependency, lock-file, and test-data governance

## Dependency direction

- `core/contracts/` owns framework-free shared records. It must not import FastAPI, Streamlit, Pydantic, providers, server composition, storage helpers, or application pipelines.
- `integrations/` translates external sources to shared contracts. Adapters must not import application pipelines, SignalHub, schedulers, or server composition.
- `server/routers/` remains a presentation boundary and must not import `server.api`, which is the app composition root.
- A boundary test is a guard on module structure. It does not replace behavior tests for the relevant paths.

## Python and frontend installs

`requirements.txt` and `pyproject.toml` declare direct compatibility ranges and project metadata. `requirements-lock.txt` is the exact environment for the supported CPython 3.11 CI runtime and test suite; every runtime, build, and test dependency declared in those manifests must appear as a single `==` pin, and the pin must satisfy the declared range. CI installs only this lock file so a later unpinned requirements install cannot replace pinned versions.

When upgrading dependencies, update the direct declaration, resolve the complete runtime and test dependency closure for the supported Python range and platforms, update the lock, then run the lock-governance test and the cross-platform CI matrix. The frontend uses `frontend/package-lock.json` with `npm ci`; CI does not use `npm install` to rewrite the lock.

## Offline CI and local research data

Default pytest runs are offline. The root autouse fixture blocks `requests` and `urllib` network entry points, routes default SQLite/JSONL writers to pytest-owned temporary storage, and guards SQLite paths after resolving Junction aliases. Storage-boundary tests verify both temporary default paths and rejection of the project `data` alias before opening SQLite.

Tests marked `local_data` read developer-specific files and are skipped by default. A developer can explicitly run them with `--run-local-data`; CI must not pass this option. Tests marked `live` similarly require `--run-live`. CI checks both opt-in flags remain absent and includes the network and storage boundary tests.

The M8 CI matrix provides offline code and fixture evidence. It does not read a developer's formal data directory, call live providers, or prove production-data recovery.
