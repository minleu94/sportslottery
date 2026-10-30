#!/usr/bin/env python3
"""SQLite Database Backup and Restore Service.

Provides:
- Transactionally consistent online backups using SQLite Backup API
- Cryptographic SHA-256 checksums and backup manifests
- Automated restore into target destination
- Table consistency and row-count verification for profiles, wallet_state, ledger, and tickets
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Dict, Optional

from core.storage_config import get_db_path

logger = logging.getLogger("sportslottery.backup")

CORE_TABLES = ("profiles", "wallet_state", "ledger", "tickets")


def get_table_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    """Retrieve row counts for core domain tables."""
    counts = {}
    existing_tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    for table in CORE_TABLES:
        if table in existing_tables:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0]) if row else 0
        else:
            counts[table] = 0
    return counts


def backup_database(
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    tag: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform atomic online backup of SQLite database to output directory."""
    src_path = Path(db_path or get_db_path()).resolve()
    if not src_path.exists():
        raise FileNotFoundError(f"Source database file not found: {src_path}")

    target_dir = Path(output_dir or (src_path.parent / "backups")).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag_suffix = f"_{tag}" if tag else ""
    backup_filename = f"db_backup_{timestamp}{tag_suffix}.sqlite3"
    backup_file = target_dir / backup_filename
    manifest_file = target_dir / f"db_backup_{timestamp}{tag_suffix}_manifest.json"

    # Use SQLite Online Backup API for 100% consistent live backup
    with closing(sqlite3.connect(f"file:{src_path.as_posix()}?mode=ro", uri=True, timeout=30.0)) as src_conn:
        with closing(sqlite3.connect(str(backup_file))) as dst_conn:
            src_conn.backup(dst_conn)
            table_counts = get_table_counts(dst_conn)
            # Run quick integrity check on backup
            check_row = dst_conn.execute("PRAGMA integrity_check").fetchone()
            if not check_row or check_row[0] != "ok":
                raise RuntimeError(f"Backup integrity check failed: {check_row}")

    backup_bytes = backup_file.read_bytes()
    sha256 = hashlib.sha256(backup_bytes).hexdigest()

    manifest = {
        "schema": "sqlite-backup-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_db": str(src_path),
        "backup_file": str(backup_file.name),
        "file_size_bytes": len(backup_bytes),
        "sha256": sha256,
        "table_counts": table_counts,
        "integrity": "ok",
    }
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(
        "[DB_BACKUP_SUCCESS] file=%s sha256=%s tables=%s",
        backup_file.name,
        sha256[:12],
        table_counts,
    )
    return {
        "backup_file": str(backup_file),
        "manifest_file": str(manifest_file),
        "sha256": sha256,
        "table_counts": table_counts,
        "file_size_bytes": len(backup_bytes),
    }


def restore_database(
    backup_file: Path,
    target_db_path: Path,
    expected_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Restore SQLite database from verified backup into target path."""
    src_file = Path(backup_file).resolve()
    target_path = Path(target_db_path).resolve()

    if not src_file.is_file():
        raise FileNotFoundError(f"Backup file not found: {src_file}")

    # Check manifest if it exists alongside
    manifest_file = src_file.parent / f"{src_file.stem}_manifest.json"
    manifest: Optional[Dict[str, Any]] = None
    if manifest_file.exists():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if not expected_sha256 and manifest.get("sha256"):
                expected_sha256 = manifest["sha256"]
        except Exception:
            pass

    # Verify SHA-256 integrity
    file_bytes = src_file.read_bytes()
    actual_sha256 = hashlib.sha256(file_bytes).hexdigest()
    if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
        raise ValueError(
            f"Backup SHA256 checksum mismatch! Expected: {expected_sha256}, actual: {actual_sha256}"
        )

    # Verify source database integrity before restoring
    try:
        with closing(sqlite3.connect(f"file:{src_file.as_posix()}?mode=ro", uri=True)) as check_conn:
            res = check_conn.execute("PRAGMA integrity_check").fetchone()
            if not res or res[0] != "ok":
                raise RuntimeError(f"Corrupted backup database: {res}")
            source_counts = get_table_counts(check_conn)
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"Corrupted backup database: {exc}") from exc

    # Ensure target parent directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Online backup into target to preserve WAL settings and prevent partial file writes
    with closing(sqlite3.connect(f"file:{src_file.as_posix()}?mode=ro", uri=True)) as src_conn:
        with closing(sqlite3.connect(str(target_path))) as dst_conn:
            src_conn.backup(dst_conn)
            # Recheck destination integrity
            dst_res = dst_conn.execute("PRAGMA integrity_check").fetchone()
            if not dst_res or dst_res[0] != "ok":
                raise RuntimeError(f"Restored database integrity check failed: {dst_res}")
            target_counts = get_table_counts(dst_conn)

    # Verify all table counts match
    if source_counts != target_counts:
        raise ValueError(
            f"Table row counts mismatch after restore! Source: {source_counts}, target: {target_counts}"
        )

    logger.info(
        "[DB_RESTORE_SUCCESS] target=%s sha256=%s tables=%s",
        str(target_path),
        actual_sha256[:12],
        target_counts,
    )
    return {
        "target_db": str(target_path),
        "sha256": actual_sha256,
        "table_counts": target_counts,
        "status": "RESTORED",
    }
