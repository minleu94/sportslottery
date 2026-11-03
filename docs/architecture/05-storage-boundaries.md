# Storage paths and test isolation

## Process path bundle

`core.storage_config.StoragePathBundle` is an immutable set of canonical absolute paths for the active process:

- `root`: configured application data root;
- `wallet_db`: `root/war_chest.sqlite3`;
- `research_root`: `root/research_pipeline`;
- `shadow_root` and `shadow_db`: the isolated paper-trading store below `root/shadow`.

`resolve_storage_path_bundle()` is side-effect free. `get_storage_path_bundle()` captures the default bundle on first use, and the compatibility helpers `get_storage_root()`, `get_db_path()`, and `get_research_root()` read from that same object. Storage configuration changes are picked up by a fresh process; a running process keeps the paths it started with.

Callers that run a separate research cohort may continue passing an explicit data root and configuration. That root is validated and canonicalized without merging its snapshots, model state, or results into another cohort.

## Junction and protected-root handling

Research path validation resolves the requested root and the project `data` alias before comparing protected directories. The returned path is the resolved target, so downstream SQLite and JSONL operations do not retain a Junction alias that could resolve differently later.

Reading or resolving paths does not create directories. Existing schema and files are not migrated by the bundle resolver.

## Test storage boundary

The autouse test fixture constructs a temporary `StoragePathBundle` and redirects import-time defaults for wallet/profile databases, shadow SQLite, prediction/parlay/odds JSONL, model acceptance, and service registry instances into that temporary root.

The SQLite guard strips `file:` URI query parameters and resolves each database path before checking it against the checkout `data` target and configured production data root. A test that opens a database through a Junction alias fails before `sqlite3.connect` is called. Dedicated boundary tests also verify that default JSONL writes land under the temporary research root.

Existing wallet atomicity and backup/restore tests exercise the same temporary SQLite boundary. They verify transaction rollback, online backup integrity, restore row counts, and rejection of tampered backups without using the formal database.
