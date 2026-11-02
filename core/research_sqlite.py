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
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Optional

PREDICTION_LEDGER = "prediction_snapshots.jsonl"
PARLAY_LEDGER = "parlay_snapshots.jsonl"
DATABASE_NAME = "research.sqlite3"


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


def _store_parlay_run(conn: sqlite3.Connection, record: dict) -> None:
    run_id = _record_id(record, "snapshot_id")
    parent = dict(record)
    candidates = parent.pop("candidates", []) or []
    conn.execute(
        "INSERT INTO parlay_runs(snapshot_id, record_json) VALUES(?,?) "
        "ON CONFLICT(snapshot_id) DO UPDATE SET record_json=excluded.record_json",
        (run_id, json.dumps(parent, ensure_ascii=False, separators=(",", ":"), allow_nan=False)),
    )
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
        return record


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
