"""SQLite-backed storage for the large prediction and parlay research ledgers.

JSONL remains the import/export format. In SQLite, prediction evidence is stored
once and parlay candidates keep references to it instead of embedding copies.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Optional

PREDICTION_LEDGER = "prediction_snapshots.jsonl"
PARLAY_LEDGER = "parlay_snapshots.jsonl"
DATABASE_NAME = "research.sqlite3"
PREDICTION_INDEX_TABLE = "research_prediction_index"
PARLAY_RUN_INDEX_TABLE = "research_parlay_run_index"
PARLAY_QUEUE_TABLE = "research_parlay_settlement_queue"


def _epoch(value: Any) -> Optional[float]:
    """Parse an ISO timestamp into UTC epoch seconds without accepting naive dates."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).timestamp()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _index_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM research_meta WHERE key=?", (key,)).fetchone()
    return str(row[0]) if row else None


def _prediction_index_values(record: dict, *, now_epoch: Optional[float] = None) -> tuple:
    now_epoch = time.time() if now_epoch is None else float(now_epoch)
    recorded_at = _epoch(record.get("recorded_at") or record.get("snapshot_timestamp") or record.get("timestamp"))
    event_start = _epoch(record.get("event_start") or record.get("start_time_utc"))
    is_settled = int(bool(record.get("is_settled")))
    due_at = None if is_settled else max(event_start or 0.0, now_epoch)
    return recorded_at, event_start, is_settled, due_at


def _sync_prediction_index(conn: sqlite3.Connection, record: dict) -> None:
    if not _table_exists(conn, PREDICTION_INDEX_TABLE):
        return
    snapshot_id = _record_id(record, "snapshot_id")
    recorded_at, event_start, is_settled, due_at = _prediction_index_values(record)
    previous = conn.execute(
        f"SELECT is_settled, settlement_due_epoch FROM {PREDICTION_INDEX_TABLE} WHERE snapshot_id=?",
        (snapshot_id,),
    ).fetchone()
    if previous and not is_settled:
        if int(previous[0]) == 0:
            due_at = previous[1]
    conn.execute(
        f"INSERT INTO {PREDICTION_INDEX_TABLE} "
        "(snapshot_id, recorded_at_epoch, event_start_epoch, is_settled, settlement_due_epoch, settlement_attempts) "
        "VALUES(?,?,?,?,?,0) ON CONFLICT(snapshot_id) DO UPDATE SET "
        "recorded_at_epoch=excluded.recorded_at_epoch, event_start_epoch=excluded.event_start_epoch, "
        "is_settled=excluded.is_settled, "
        "settlement_due_epoch=CASE WHEN excluded.is_settled=1 THEN NULL "
        f"WHEN {PREDICTION_INDEX_TABLE}.is_settled=1 THEN excluded.settlement_due_epoch "
        f"ELSE {PREDICTION_INDEX_TABLE}.settlement_due_epoch END",
        (snapshot_id, recorded_at, event_start, is_settled, due_at),
    )
    if is_settled and _table_exists(conn, PARLAY_QUEUE_TABLE) and _table_exists(conn, "candidate_snapshot_refs"):
        conn.execute(
            f"UPDATE {PARLAY_QUEUE_TABLE} SET due_at_epoch=? WHERE candidate_id IN "
            "(SELECT candidate_id FROM candidate_snapshot_refs WHERE snapshot_id=? AND kind='validation')",
            (time.time(), snapshot_id),
        )


def _sync_parlay_run_index(conn: sqlite3.Connection, record: dict) -> None:
    if not _table_exists(conn, PARLAY_RUN_INDEX_TABLE):
        return
    run_id = _record_id(record, "snapshot_id")
    recorded_at = _epoch(record.get("timestamp") or record.get("recorded_at") or record.get("date"))
    identity = record.get("experiment_identity") or (record.get("strategy_metadata") or {}).get("experiment_identity")
    identity_json = json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True) if identity else None
    conn.execute(
        f"INSERT INTO {PARLAY_RUN_INDEX_TABLE}(run_id, recorded_at_epoch, run_window_id, experiment_identity_json) "
        "VALUES(?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET recorded_at_epoch=excluded.recorded_at_epoch, "
        "run_window_id=excluded.run_window_id, experiment_identity_json=excluded.experiment_identity_json",
        (run_id, recorded_at, record.get("run_window_id"), identity_json),
    )


def _sync_parlay_candidate_queue(conn: sqlite3.Connection, candidate: dict, run_id: str) -> None:
    if not _table_exists(conn, PARLAY_QUEUE_TABLE):
        return
    candidate_id = _record_id(candidate, "candidate_id")
    if candidate.get("settled"):
        conn.execute(f"DELETE FROM {PARLAY_QUEUE_TABLE} WHERE candidate_id=?", (candidate_id,))
        return
    conn.execute(
        f"INSERT OR IGNORE INTO {PARLAY_QUEUE_TABLE}(candidate_id, run_id, due_at_epoch, attempts) "
        "VALUES(?,?,?,0)",
        (candidate_id, run_id, time.time()),
    )


def database_for_ledger(path: Path) -> Optional[tuple[Path, str]]:
    path = Path(path).resolve()
    if path.name not in {PREDICTION_LEDGER, PARLAY_LEDGER}:
        return None
    database = path.parent / DATABASE_NAME
    if not database.exists():
        return None
    try:
        with _connection(database) as conn:
            ready = conn.execute("SELECT value FROM research_meta WHERE key='state'").fetchone()
    except sqlite3.Error:
        return None
    if not ready or ready[0] != "ready":
        return None
    table = "predictions" if path.name == PREDICTION_LEDGER else "parlay_runs"
    return database, table


def _connect(database: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(database, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _connection(database: Path):
    conn = _connect(database)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _record_id(record: dict, fallback: str) -> str:
    value = record.get("snapshot_id") or record.get("candidate_id")
    if not value:
        raise ValueError(f"Research ledger row is missing {fallback}")
    return str(value)


def _store_snapshot(conn: sqlite3.Connection, record: dict) -> None:
    payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    conn.execute(
        "INSERT INTO predictions(snapshot_id, uniqueness_key, record_json) VALUES(?,?,?) "
        "ON CONFLICT(snapshot_id) DO UPDATE SET uniqueness_key=excluded.uniqueness_key, record_json=excluded.record_json",
        (_record_id(record, "snapshot_id"), record.get("uniqueness_key"), payload),
    )
    _sync_prediction_index(conn, record)


def _store_parlay_run(conn: sqlite3.Connection, record: dict) -> None:
    run_id = _record_id(record, "snapshot_id")
    parent = dict(record)
    candidates = parent.pop("candidates", []) or []
    conn.execute(
        "INSERT INTO parlay_runs(snapshot_id, record_json) VALUES(?,?) "
        "ON CONFLICT(snapshot_id) DO UPDATE SET record_json=excluded.record_json",
        (run_id, json.dumps(parent, ensure_ascii=False, separators=(",", ":"), allow_nan=False)),
    )
    _sync_parlay_run_index(conn, record)
    conn.execute("DELETE FROM parlay_candidates WHERE run_id=?", (run_id,))
    for position, source in enumerate(candidates):
        candidate = dict(source)
        candidate_id = _record_id(candidate, "candidate_id")
        validations = candidate.pop("validation_legs", []) or []
        results = candidate.pop("leg_result_snapshots", []) or []
        conn.execute(
            "INSERT INTO parlay_candidates(candidate_id, run_id, position, record_json) VALUES(?,?,?,?)",
            (candidate_id, run_id, position, json.dumps(candidate, ensure_ascii=False, separators=(",", ":"), allow_nan=False)),
        )
        _sync_parlay_candidate_queue(conn, candidate, run_id)
        for kind, evidence_rows in (("validation", validations), ("result", results)):
            for leg_index, evidence in enumerate(evidence_rows):
                evidence = evidence if isinstance(evidence, dict) else {}
                snapshot_id = evidence.get("snapshot_id")
                if snapshot_id and not conn.execute(
                    "SELECT 1 FROM predictions WHERE snapshot_id=?", (str(snapshot_id),)
                ).fetchone():
                    snapshot_id = None
                if kind == "validation" and snapshot_id:
                    frozen_payload = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                    conn.execute(
                        "INSERT OR IGNORE INTO prediction_evidence(snapshot_id, record_json) VALUES(?,?)",
                        (str(snapshot_id), frozen_payload),
                    )
                # Keep exceptional evidence inline when it cannot reference a sealed snapshot.
                payload = None if snapshot_id else json.dumps(evidence, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                conn.execute(
                    "INSERT INTO candidate_snapshot_refs(candidate_id, kind, leg_index, snapshot_id, payload_json) VALUES(?,?,?,?,?)",
                    (candidate_id, kind, leg_index, str(snapshot_id) if snapshot_id else None, payload),
                )


def append(path: Path, record: dict | list[dict]) -> bool:
    target = database_for_ledger(path)
    if not target:
        return False
    database, table = target
    rows = record if isinstance(record, list) else [record]
    with _connection(database) as conn:
        for row in rows:
            if table == "predictions":
                _store_snapshot(conn, row)
            else:
                _store_parlay_run(conn, row)
    return True


def _hydrate_parlay(conn: sqlite3.Connection, run: sqlite3.Row) -> dict:
    result = json.loads(run["record_json"])
    candidates = []
    for stored in conn.execute(
        "SELECT candidate_id, record_json FROM parlay_candidates WHERE run_id=? ORDER BY position",
        (run["snapshot_id"],),
    ):
        candidate = json.loads(stored["record_json"])
        refs = list(conn.execute(
            "SELECT kind, leg_index, snapshot_id, payload_json FROM candidate_snapshot_refs WHERE candidate_id=? ORDER BY kind, leg_index",
            (stored["candidate_id"],),
        ))
        for kind, field in (("validation", "validation_legs"), ("result", "leg_result_snapshots")):
            evidence = []
            for ref in refs:
                if ref["kind"] != kind:
                    continue
                payload = ref["payload_json"]
                if payload is not None:
                    evidence.append(json.loads(payload))
                elif ref["snapshot_id"]:
                    table = "prediction_evidence" if kind == "validation" else "predictions"
                    snapshot = conn.execute(f"SELECT record_json FROM {table} WHERE snapshot_id=?", (ref["snapshot_id"],)).fetchone()
                    evidence.append(json.loads(snapshot[0]) if snapshot else {})
                else:
                    evidence.append({})
            if evidence or field in {"validation_legs", "leg_result_snapshots"}:
                candidate[field] = evidence
        candidates.append(candidate)
    result["candidates"] = candidates
    return result


def iter_records(path: Path) -> Iterator[dict]:
    target = database_for_ledger(path)
    if not target:
        return
    database, table = target
    with _connection(database) as conn:
        if table == "predictions":
            cursor = conn.execute("SELECT record_json FROM predictions ORDER BY rowid")
            for row in cursor:
                yield json.loads(row[0])
        else:
            cursor = conn.execute("SELECT snapshot_id, record_json FROM parlay_runs ORDER BY rowid")
            for row in cursor:
                yield _hydrate_parlay(conn, row)


def get_prediction_by_unique_key(path: Path, uniqueness_key: str) -> Optional[dict]:
    target = database_for_ledger(path)
    if not target or target[1] != "predictions":
        return None
    with _connection(target[0]) as conn:
        row = conn.execute(
            "SELECT record_json FROM predictions WHERE uniqueness_key=? ORDER BY rowid DESC LIMIT 1",
            (uniqueness_key,),
        ).fetchone()
        return json.loads(row[0]) if row else None


def get_predictions_by_ids(path: Path, snapshot_ids: Iterable[str]) -> Dict[str, dict]:
    target = database_for_ledger(path)
    if not target or target[1] != "predictions":
        return {}
    ids = list(dict.fromkeys(str(value) for value in snapshot_ids if value))
    found: Dict[str, dict] = {}
    with _connection(target[0]) as conn:
        for start in range(0, len(ids), 500):
            part = ids[start:start + 500]
            marks = ",".join("?" for _ in part)
            for row in conn.execute(
                f"SELECT snapshot_id, record_json FROM predictions WHERE snapshot_id IN ({marks})", part
            ):
                found[row["snapshot_id"]] = json.loads(row["record_json"])
    return found


def update_prediction(path: Path, snapshot_id: str, update: Callable[[dict], Optional[dict]]) -> Optional[dict]:
    target = database_for_ledger(path)
    if not target or target[1] != "predictions":
        return None
    with _connection(target[0]) as conn:
        row = conn.execute("SELECT record_json FROM predictions WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if not row:
            return None
        record = update(json.loads(row[0]))
        if record is None:
            return None
        conn.execute("UPDATE predictions SET record_json=? WHERE snapshot_id=?", (
            json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False), snapshot_id,
        ))
        _sync_prediction_index(conn, record)
        return record


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO research_meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def research_indexes_ready(path: Path) -> bool:
    target = database_for_ledger(path)
    if not target or target[1] != "predictions":
        return False
    with _connection(target[0]) as conn:
        return all(
            _index_state(conn, key) == "ready"
            for key in ("prediction_index_state", "parlay_run_index_state", "parlay_candidate_index_state")
        )


def build_research_indexes(database: Path, *, batch_size: int = 250,
                           progress: Optional[Callable[[str, int], None]] = None) -> dict[str, Any]:
    """Build resumable metadata indexes used by scheduled settlement and reports.

    The migration only adds side tables and indexes; prediction/parlay payloads
    and the source JSONL ledgers remain untouched. Batch cursors are persisted
    in research_meta so an interrupted build can continue from its last row.
    """
    database = Path(database).resolve()
    batch_size = max(1, int(batch_size))
    now_epoch = time.time()
    schemas = (
        ("prediction_index_state", "prediction_index_rowid", "predictions", "prediction_index"),
        ("parlay_run_index_state", "parlay_run_index_rowid", "parlay_runs", "parlay_run_index"),
        ("parlay_candidate_index_state", "parlay_candidate_index_rowid", "parlay_candidates", "parlay_candidate_index"),
    )
    with _connection(database) as conn:
        state = conn.execute("SELECT value FROM research_meta WHERE key='state'").fetchone()
        if not state or state[0] != "ready":
            raise RuntimeError("Research SQLite database is not in ready state.")
        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS {PREDICTION_INDEX_TABLE}(
                snapshot_id TEXT PRIMARY KEY REFERENCES predictions(snapshot_id) ON DELETE CASCADE,
                recorded_at_epoch REAL,
                event_start_epoch REAL,
                is_settled INTEGER NOT NULL DEFAULT 0,
                settlement_due_epoch REAL,
                settlement_attempts INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS {PARLAY_RUN_INDEX_TABLE}(
                run_id TEXT PRIMARY KEY REFERENCES parlay_runs(snapshot_id) ON DELETE CASCADE,
                recorded_at_epoch REAL,
                run_window_id TEXT,
                experiment_identity_json TEXT
            );
            CREATE TABLE IF NOT EXISTS {PARLAY_QUEUE_TABLE}(
                candidate_id TEXT PRIMARY KEY REFERENCES parlay_candidates(candidate_id) ON DELETE CASCADE,
                run_id TEXT NOT NULL,
                due_at_epoch REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0
            );
        """)
        run_index_columns = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({PARLAY_RUN_INDEX_TABLE})")
        }
        run_index_schema_upgraded = False
        if "run_window_id" not in run_index_columns:
            conn.execute(f"ALTER TABLE {PARLAY_RUN_INDEX_TABLE} ADD COLUMN run_window_id TEXT")
            run_index_schema_upgraded = True
        if "experiment_identity_json" not in run_index_columns:
            conn.execute(f"ALTER TABLE {PARLAY_RUN_INDEX_TABLE} ADD COLUMN experiment_identity_json TEXT")
            run_index_schema_upgraded = True
        for state_key, _, _, _ in schemas:
            if _index_state(conn, state_key) != "ready":
                _set_meta(conn, state_key, "building")
            progress_key = state_key.replace("_state", "_rowid")
            if _index_state(conn, progress_key) is None:
                _set_meta(conn, progress_key, "0")
        if run_index_schema_upgraded:
            _set_meta(conn, "parlay_run_index_state", "building")
            _set_meta(conn, "parlay_run_index_rowid", "0")

    for state_key, progress_key, source_table, kind in schemas:
        if _index_state_for_database(database, state_key) == "ready":
            continue
        while True:
            with _connection(database) as conn:
                last_rowid = int(_index_state(conn, progress_key) or 0)
                rows = conn.execute(
                    f"SELECT rowid, * FROM {source_table} WHERE rowid>? ORDER BY rowid LIMIT ?",
                    (last_rowid, batch_size),
                ).fetchall()
                if not rows:
                    break
                for row in rows:
                    record_json = row["record_json"]
                    record = json.loads(record_json)
                    if kind == "prediction_index":
                        recorded_at, event_start, is_settled, due_at = _prediction_index_values(record, now_epoch=now_epoch)
                        conn.execute(
                            f"INSERT OR IGNORE INTO {PREDICTION_INDEX_TABLE} "
                            "(snapshot_id,recorded_at_epoch,event_start_epoch,is_settled,settlement_due_epoch,settlement_attempts) "
                            "VALUES(?,?,?,?,?,0)",
                            (row["snapshot_id"], recorded_at, event_start, is_settled, due_at),
                        )
                    elif kind == "parlay_run_index":
                        recorded_at = _epoch(record.get("timestamp") or record.get("recorded_at") or record.get("date"))
                        identity = record.get("experiment_identity") or (record.get("strategy_metadata") or {}).get("experiment_identity")
                        identity_json = json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True) if identity else None
                        conn.execute(
                            f"INSERT INTO {PARLAY_RUN_INDEX_TABLE} "
                            "(run_id,recorded_at_epoch,run_window_id,experiment_identity_json) VALUES(?,?,?,?) "
                            "ON CONFLICT(run_id) DO UPDATE SET recorded_at_epoch=excluded.recorded_at_epoch, "
                            "run_window_id=excluded.run_window_id, experiment_identity_json=excluded.experiment_identity_json",
                            (row["snapshot_id"], recorded_at, record.get("run_window_id"), identity_json),
                        )
                    elif not bool(record.get("settled")):
                        conn.execute(
                            f"INSERT OR IGNORE INTO {PARLAY_QUEUE_TABLE}(candidate_id,run_id,due_at_epoch,attempts) "
                            "VALUES(?,?,?,0)",
                            (row["candidate_id"], row["run_id"], now_epoch),
                        )
                last_rowid = int(rows[-1]["rowid"])
                _set_meta(conn, progress_key, str(last_rowid))
            if progress:
                progress(kind, last_rowid)

        with _connection(database) as conn:
            _set_meta(conn, state_key, "ready")

    with _connection(database) as conn:
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_research_prediction_due ON {PREDICTION_INDEX_TABLE}(is_settled,settlement_due_epoch DESC,event_start_epoch DESC)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_research_prediction_recorded ON {PREDICTION_INDEX_TABLE}(recorded_at_epoch,snapshot_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_research_parlay_run_recorded ON {PARLAY_RUN_INDEX_TABLE}(recorded_at_epoch,run_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_research_parlay_window ON {PARLAY_RUN_INDEX_TABLE}(run_window_id,experiment_identity_json)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_research_parlay_due ON {PARLAY_QUEUE_TABLE}(due_at_epoch,candidate_id)")
    counts = research_index_counts(database)
    return {"database": str(database), "batch_size": batch_size, **counts}


def _index_state_for_database(database: Path, key: str) -> Optional[str]:
    with _connection(database) as conn:
        return _index_state(conn, key)


def research_index_counts(database: Path) -> dict[str, int]:
    with _connection(Path(database).resolve()) as conn:
        result = {}
        for key, table in (("prediction", PREDICTION_INDEX_TABLE),
                           ("parlay_run", PARLAY_RUN_INDEX_TABLE),
                           ("parlay_candidate", PARLAY_QUEUE_TABLE)):
            if _table_exists(conn, table):
                result[f"{key}_indexed_count"] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        due = conn.execute(
            f"SELECT COUNT(*) FROM {PREDICTION_INDEX_TABLE} WHERE is_settled=0 AND settlement_due_epoch<=?",
            (time.time(),),
        ).fetchone()[0] if _table_exists(conn, PREDICTION_INDEX_TABLE) else 0
        result["prediction_due_count"] = int(due)
        result["prediction_unsettled_count"] = int(conn.execute(
            f"SELECT COUNT(*) FROM {PREDICTION_INDEX_TABLE} WHERE is_settled=0"
        ).fetchone()[0]) if _table_exists(conn, PREDICTION_INDEX_TABLE) else 0
        result["parlay_pending_count"] = int(conn.execute(
            f"SELECT COUNT(*) FROM {PARLAY_QUEUE_TABLE}"
        ).fetchone()[0]) if _table_exists(conn, PARLAY_QUEUE_TABLE) else 0
        return result


def get_due_predictions(path: Path, *, now_epoch: Optional[float] = None, limit: int = 500,
                        minimum_event_age_seconds: int = 0,
                        claim_seconds: int = 900) -> Optional[list[dict]]:
    target = database_for_ledger(path)
    if not target or target[1] != "predictions":
        return None
    database, _ = target
    now = time.time() if now_epoch is None else float(now_epoch)
    with _connection(database) as conn:
        if _index_state(conn, "prediction_index_state") != "ready":
            return None
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            f"SELECT i.snapshot_id,p.record_json FROM {PREDICTION_INDEX_TABLE} AS i "
            "JOIN predictions AS p ON p.snapshot_id=i.snapshot_id "
            "WHERE i.is_settled=0 AND i.settlement_due_epoch IS NOT NULL AND i.settlement_due_epoch<=? "
            "AND (i.event_start_epoch IS NULL OR i.event_start_epoch<=?) "
            "ORDER BY i.settlement_due_epoch ASC, i.event_start_epoch ASC, i.recorded_at_epoch ASC LIMIT ?",
            (now, now - max(0, int(minimum_event_age_seconds)), max(1, int(limit))),
        ).fetchall()
        if rows:
            conn.executemany(
                f"UPDATE {PREDICTION_INDEX_TABLE} SET settlement_due_epoch=? "
                "WHERE snapshot_id=? AND is_settled=0",
                [(now + max(1, int(claim_seconds)), row[0]) for row in rows],
            )
        return [json.loads(row[1]) for row in rows]


def defer_predictions(path: Path, snapshot_ids: Iterable[str], *, due_epoch: float) -> int:
    target = database_for_ledger(path)
    if not target or target[1] != "predictions":
        return 0
    ids = list(dict.fromkeys(str(value) for value in snapshot_ids if value))
    if not ids:
        return 0
    changed = 0
    with _connection(target[0]) as conn:
        if _index_state(conn, "prediction_index_state") != "ready":
            return 0
        for start in range(0, len(ids), 500):
            part = ids[start:start + 500]
            marks = ",".join("?" for _ in part)
            cursor = conn.execute(
                f"UPDATE {PREDICTION_INDEX_TABLE} SET settlement_due_epoch=?,settlement_attempts=settlement_attempts+1 "
                f"WHERE is_settled=0 AND snapshot_id IN ({marks})",
                [float(due_epoch), *part],
            )
            changed += cursor.rowcount
    return changed


def get_due_parlay_candidates(path: Path, *, now_epoch: Optional[float] = None,
                              limit: int = 500) -> Optional[list[dict]]:
    target = database_for_ledger(path)
    if not target or target[1] != "parlay_runs":
        return None
    database, _ = target
    now = time.time() if now_epoch is None else float(now_epoch)
    with _connection(database) as conn:
        if _index_state(conn, "parlay_candidate_index_state") != "ready":
            return None
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            f"SELECT q.candidate_id,q.run_id,c.record_json FROM {PARLAY_QUEUE_TABLE} AS q "
            "JOIN parlay_candidates AS c ON c.candidate_id=q.candidate_id "
            "WHERE q.due_at_epoch<=? ORDER BY q.due_at_epoch,c.candidate_id LIMIT ?",
            (now, max(1, int(limit))),
        ).fetchall()
        if rows:
            conn.executemany(
                f"UPDATE {PARLAY_QUEUE_TABLE} SET due_at_epoch=?,attempts=attempts+1 WHERE candidate_id=?",
                [(now + 900, row[0]) for row in rows],
            )
        return [{"candidate_id": row[0], "run_id": row[1], "candidate": json.loads(row[2])} for row in rows]


def defer_parlay_candidates(path: Path, candidate_ids: Iterable[str], *, due_epoch: float) -> int:
    target = database_for_ledger(path)
    if not target or target[1] != "parlay_runs":
        return 0
    ids = list(dict.fromkeys(str(value) for value in candidate_ids if value))
    changed = 0
    with _connection(target[0]) as conn:
        if _index_state(conn, "parlay_candidate_index_state") != "ready":
            return 0
        for candidate_id in ids:
            cursor = conn.execute(
                f"UPDATE {PARLAY_QUEUE_TABLE} SET due_at_epoch=?,attempts=attempts+1 WHERE candidate_id=?",
                (float(due_epoch), candidate_id),
            )
            changed += cursor.rowcount
    return changed


def get_prediction_records_between(path: Path, start_epoch: float, end_epoch: float) -> Optional[list[dict]]:
    target = database_for_ledger(path)
    if not target or target[1] != "predictions":
        return None
    database, _ = target
    with _connection(database) as conn:
        if _index_state(conn, "prediction_index_state") != "ready":
            return None
        rows = conn.execute(
            f"SELECT p.record_json FROM {PREDICTION_INDEX_TABLE} AS i JOIN predictions AS p "
            "ON p.snapshot_id=i.snapshot_id WHERE i.recorded_at_epoch>=? AND i.recorded_at_epoch<? "
            "ORDER BY i.recorded_at_epoch,i.snapshot_id",
            (float(start_epoch), float(end_epoch)),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]


def get_parlay_records_between(path: Path, start_epoch: float, end_epoch: float) -> Optional[list[dict]]:
    target = database_for_ledger(path)
    if not target or target[1] != "parlay_runs":
        return None
    database, _ = target
    with _connection(database) as conn:
        if _index_state(conn, "parlay_run_index_state") != "ready":
            return None
        rows = conn.execute(
            f"SELECT r.snapshot_id,r.record_json FROM {PARLAY_RUN_INDEX_TABLE} AS i JOIN parlay_runs AS r "
            "ON r.snapshot_id=i.run_id WHERE i.recorded_at_epoch>=? AND i.recorded_at_epoch<? "
            "ORDER BY i.recorded_at_epoch,i.run_id",
            (float(start_epoch), float(end_epoch)),
        ).fetchall()
        return [_hydrate_parlay(conn, row) for row in rows]


def get_parlay_records_for_window(path: Path, run_window_id: str,
                                 experiment_identity: dict) -> Optional[list[dict]]:
    target = database_for_ledger(path)
    if not target or target[1] != "parlay_runs":
        return None
    database, _ = target
    identity_json = json.dumps(experiment_identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    with _connection(database) as conn:
        if _index_state(conn, "parlay_run_index_state") != "ready":
            return None
        rows = conn.execute(
            f"SELECT r.snapshot_id,r.record_json FROM {PARLAY_RUN_INDEX_TABLE} AS i JOIN parlay_runs AS r "
            "ON r.snapshot_id=i.run_id WHERE i.run_window_id=? AND i.experiment_identity_json=? "
            "ORDER BY i.recorded_at_epoch,i.run_id",
            (str(run_window_id), identity_json),
        ).fetchall()
        return [_hydrate_parlay(conn, row) for row in rows]


def settle_parlays(path: Path, settlements: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, dict]]:
    target = database_for_ledger(path)
    if not target or target[1] != "parlay_runs":
        return None
    database, _ = target
    settled = {}
    # The domain logger supplies the same settlement calculation used by JSONL.
    with _connection(database) as conn:
        for candidate_id, request in settlements.items():
            row = conn.execute("SELECT record_json FROM parlay_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
            if not row:
                continue
            candidate = json.loads(row[0])
            if candidate.get("settled"):
                settled[candidate_id] = candidate
                continue
            statuses = request.get("leg_statuses") or []
            stake = request.get("virtual_stake", 10.0)
            if len(statuses) != len(candidate.get("legs", [])):
                raise ValueError("Each ticket leg must have exactly one settlement result.")
            if not isinstance(stake, (int, float)) or not math.isfinite(stake) or stake <= 0:
                raise ValueError("Virtual stake must be finite and positive.")
            recalculated = 1.0
            any_lost = False
            all_void = True
            has_win = has_pending = False
            for leg, (status, odds) in zip(candidate["legs"], statuses):
                if not isinstance(odds, (int, float)) or not math.isfinite(odds) or odds <= 1:
                    raise ValueError("Settlement requires finite original odds greater than one.")
                if leg.get("taiwan_odds") is not None and abs(float(leg["taiwan_odds"]) - float(odds)) > 1e-9:
                    raise ValueError("Settlement odds differ from the immutable ticket odds.")
                if status == "LOST":
                    any_lost, all_void = True, False
                elif status in {"VOID", "PUSH"}:
                    continue
                elif status == "WON":
                    recalculated *= odds
                    all_void, has_win = False, True
                else:
                    has_pending = True
            recalculated = round(recalculated, 4)
            if has_pending:
                status, won, payout = "PENDING", None, 0.0
            elif any_lost:
                status, won, payout = "LOST", False, 0.0
            elif all_void:
                status, won, payout = "VOID", None, stake
            elif has_win:
                status, won, payout = "WON", True, round(stake * recalculated, 2)
            else:
                status, won, payout = "PENDING", None, 0.0
            candidate.update({
                "settled": status != "PENDING", "settlement_status": status, "won": won,
                "recalculated_total_odds": recalculated, "actual_payout": payout,
                "leg_settlement_statuses": list(statuses),
                "profit_loss": round(payout - stake, 2) if status != "PENDING" else 0.0,
                "settled_at": datetime.now(timezone.utc).isoformat(),
            })
            conn.execute("UPDATE parlay_candidates SET record_json=? WHERE candidate_id=?", (
                json.dumps(candidate, ensure_ascii=False, separators=(",", ":"), allow_nan=False), candidate_id,
            ))
            _sync_parlay_candidate_queue(conn, candidate, str(candidate.get("run_id") or ""))
            conn.execute("DELETE FROM candidate_snapshot_refs WHERE candidate_id=? AND kind='result'", (candidate_id,))
            for leg_index, snapshot in enumerate(request.get("leg_result_snapshots") or []):
                snapshot_id = snapshot.get("snapshot_id") if isinstance(snapshot, dict) else None
                if snapshot_id and not conn.execute(
                    "SELECT 1 FROM predictions WHERE snapshot_id=?", (str(snapshot_id),)
                ).fetchone():
                    snapshot_id = None
                payload = None if snapshot_id else json.dumps(snapshot or {}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                conn.execute("INSERT INTO candidate_snapshot_refs(candidate_id,kind,leg_index,snapshot_id,payload_json) VALUES(?,?,?,?,?)",
                             (candidate_id, "result", leg_index, str(snapshot_id) if snapshot_id else None, payload))
            candidate["leg_result_snapshots"] = request.get("leg_result_snapshots") or []
            settled[candidate_id] = candidate
    return settled


def migrate_jsonl_ledgers(directory: Path, destination: Optional[Path] = None, batch_size: int = 250) -> Path:
    """Build a compact SQLite ledger beside the source files, leaving originals intact."""
    directory = Path(directory).resolve()
    destination = Path(destination or directory / DATABASE_NAME).resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing database: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".research-migration-", suffix=".sqlite3", dir=destination.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        source_paths = [directory / PREDICTION_LEDGER, directory / PARLAY_LEDGER]
        source_signatures = {
            source: (source.stat().st_size, source.stat().st_mtime_ns) if source.exists() else None
            for source in source_paths
        }
        with closing(sqlite3.connect(temporary)) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript("""
                CREATE TABLE research_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE predictions(
                    snapshot_id TEXT PRIMARY KEY,
                    uniqueness_key TEXT,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE prediction_evidence(
                    snapshot_id TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE parlay_runs(snapshot_id TEXT PRIMARY KEY, record_json TEXT NOT NULL);
                CREATE TABLE parlay_candidates(
                    candidate_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES parlay_runs(snapshot_id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE candidate_snapshot_refs(
                    candidate_id TEXT NOT NULL REFERENCES parlay_candidates(candidate_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    leg_index INTEGER NOT NULL,
                    snapshot_id TEXT,
                    payload_json TEXT,
                    PRIMARY KEY(candidate_id, kind, leg_index)
                );
                CREATE INDEX idx_predictions_unique ON predictions(uniqueness_key);
                CREATE INDEX idx_candidates_run ON parlay_candidates(run_id, position);
                CREATE INDEX idx_refs_snapshot ON candidate_snapshot_refs(snapshot_id);
            """)
            conn.execute("INSERT INTO research_meta VALUES('state','migrating')")
            for filename, table in ((PREDICTION_LEDGER, "predictions"), (PARLAY_LEDGER, "parlay_runs")):
                source = directory / filename
                if not source.exists():
                    continue
                pending = 0
                total = 0
                print(f"[SQLite] Importing {filename}...")
                with source.open("r", encoding="utf-8") as stream:
                    for number, line in enumerate(stream, 1):
                        if not line.strip():
                            continue
                        try:
                            record = json.loads(line)
                            if not isinstance(record, dict):
                                raise ValueError("expected JSON object")
                            _store_snapshot(conn, record) if table == "predictions" else _store_parlay_run(conn, record)
                        except Exception as exc:
                            raise ValueError(f"Failed migrating {source}:{number}: {exc}") from exc
                        pending += 1
                        total += 1
                        if pending >= batch_size:
                            conn.commit()
                            pending = 0
                        if total % 1000 == 0:
                            print(f"[SQLite] {filename}: {total:,} records")
                conn.commit()
                print(f"[SQLite] {filename}: complete ({total:,} records)")
            current_signatures = {
                source: (source.stat().st_size, source.stat().st_mtime_ns) if source.exists() else None
                for source in source_paths
            }
            if current_signatures != source_signatures:
                raise RuntimeError("A source ledger changed during migration. Stop the app and retry; originals were not modified.")
            conn.execute("UPDATE research_meta SET value='ready' WHERE key='state'")
            conn.commit()
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
