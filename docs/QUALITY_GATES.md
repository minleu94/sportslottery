# Quality gates and acceptance evidence

## Automated gates

Every push and pull request to `dev` or `main` runs the full default pytest
suite and builds the Python wheel on Ubuntu and Windows. The same jobs check
version consistency, install the locked frontend dependencies, run the
frontend linter and production build, check that local data and private runtime
files are not tracked, and upload a JUnit test report for 30
days, including when tests fail.

The default pytest suite is offline. Tests marked `live` are skipped unless
`--run-live` is explicitly supplied; tests marked `local_data` are skipped
unless `--run-local-data` is supplied. CI must not use either opt-in. Tests
should use temporary SQLite and research roots, never the developer's `data/`
junction. The linter currently reports warnings in existing React components;
warnings are visible in CI output and are not treated as errors.

Local equivalents:

```powershell
python scripts/check_version_consistency.py
python -m pytest tests -v --basetemp .pytest-local-tmp
python -m pip wheel --no-deps --no-build-isolation --wheel-dir .wheelhouse .
Set-Location frontend
npm ci
npm run lint
npm run build
```

Use a disposable `.pytest-local-tmp` and `.wheelhouse`; both are generated
outputs and must remain untracked.

## What CI proves

CI proves that checked-in fixtures, offline service mocks, static checks,
packaging metadata, and builds pass on the listed operating systems at the
tested commit. It does not prove API key validity, current market coverage,
live odds freshness, production event alignment, successful real settlement,
model advantage, LINE message delivery, long-running Tray reliability, or
recovery of a user's database backup.

## Evidence for a real research cycle

Before describing a market workflow as operationally verified, retain a
reviewable record containing:

1. The code commit and run timestamp.
2. Source identity, retrieval timestamp, and whether data was live, cached,
   stale, or synthetic.
3. Candidate counts, rejection reasons, matched event/market/line details, and
   the applicable API credit delta.
4. At least one sealed pre-event snapshot and its later result source, with
   idempotent settlement evidence.
5. A reproducible evaluation summary that reports sample qualification and
   uncertainty, without treating a minimum sample count as proof of advantage.

Real API calls, formal local data, real messaging, and any betting action need
their own explicit operational authorization; they are not part of CI.
