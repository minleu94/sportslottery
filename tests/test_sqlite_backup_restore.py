"""Test suite for SQLite backup and restore verification (P3-4).

Validates:
1. Online atomic backup using SQLite Backup API preserves WAL transactions.
2. Cryptographic SHA-256 checksums and backup manifests.
3. Automated restore into a new database directory.
4. Verification that profiles, wallet_state, ledger, and tickets are 100% consistent.
5. Detection of corrupted or tampered backups.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from core.backup_service import backup_database, restore_database, get_table_counts
from core.betting_service import BettingService
from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager


def test_sqlite_backup_and_restore_cycle(tmp_path: Path):
    """Full lifecycle test of backup creation, manifest verification, and database restore."""
    db_path = tmp_path / "live_db" / "war_chest.sqlite3"
    backup_dir = tmp_path / "backups"
    restore_path = tmp_path / "restored_db" / "war_chest.sqlite3"

    # 1. Initialize DB and create domain data
    pm = ProfileManager(db_path=db_path)
    p1 = pm.create_profile("Alice", weekly_play_cap=300.0, pin_code="1122")
    p2 = pm.create_profile("Bob", weekly_play_cap=500.0, pin_code="3344")

    # Alice deposits and places a bet
    alice_wallet = WeeklyWalletManager(db_path=db_path, profile_id=p1["id"])
    alice_wallet.deposit_external(200.0, notes="Alice initial funds")

    alice_service = BettingService(db_path=db_path, profile_id=p1["id"])
    leg = {
        "event_id": "game-test-1",
        "sport": "baseball",
        "league": "CPBL",
        "home_team": "中信兄弟",
        "away_team": "味全龍",
        "market": "不讓分",
        "selection": "中信兄弟",
        "taiwan_odds": 1.85,
    }
    ticket1 = alice_service.place_ticket(
        legs=[leg],
        stake=50.0,
        total_odds=1.85,
        entry_mode="manual",
        notes="Alice bet 1",
    )

    # Bob deposits and settles a winning bet
    bob_wallet = WeeklyWalletManager(db_path=db_path, profile_id=p2["id"])
    bob_wallet.deposit_external(300.0, notes="Bob initial funds")

    bob_service = BettingService(db_path=db_path, profile_id=p2["id"])
    ticket2 = bob_service.place_ticket(
        legs=[leg],
        stake=100.0,
        total_odds=1.85,
        entry_mode="manual",
        notes="Bob bet 2",
    )
    bob_service.settle_ticket(ticket_id=ticket2["ticket_id"], won=True, notes="Bob won")

    # Get live counts before backup
    with sqlite3.connect(str(db_path)) as conn:
        live_counts = get_table_counts(conn)

    assert live_counts["profiles"] >= 3  # default + Alice + Bob
    assert live_counts["wallet_state"] >= 2
    assert live_counts["ledger"] >= 4
    assert live_counts["tickets"] == 2

    # 2. Perform online atomic backup
    backup_meta = backup_database(db_path=db_path, output_dir=backup_dir, tag="test_run")
    backup_file = Path(backup_meta["backup_file"])
    manifest_file = Path(backup_meta["manifest_file"])

    assert backup_file.is_file()
    assert manifest_file.is_file()
    assert backup_meta["table_counts"] == live_counts

    # Verify manifest JSON
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["schema"] == "sqlite-backup-v1"
    assert manifest_data["sha256"] == backup_meta["sha256"]
    assert manifest_data["integrity"] == "ok"

    # 3. Restore into clean directory
    restore_meta = restore_database(
        backup_file=backup_file,
        target_db_path=restore_path,
        expected_sha256=backup_meta["sha256"],
    )

    assert restore_path.is_file()
    assert restore_meta["status"] == "RESTORED"
    assert restore_meta["table_counts"] == live_counts

    # 4. Verify functionality of restored database
    pm_restored = ProfileManager(db_path=restore_path)
    alice_restored = pm_restored.get_profile_by_name("Alice")
    assert alice_restored is not None
    assert alice_restored["id"] == p1["id"]
    assert pm_restored.verify_pin(alice_restored["id"], "1122") is True

    bob_restored = pm_restored.get_profile_by_name("Bob")
    assert bob_restored is not None
    assert pm_restored.verify_pin(bob_restored["id"], "3344") is True

    # Verify tickets in restored DB
    recorder_restored = TicketRecorder(db_path=restore_path, profile_id=p1["id"])
    t1_check = recorder_restored.get_ticket(ticket1["ticket_id"])
    assert t1_check is not None
    assert t1_check["stake"] == 50.0
    assert t1_check["status"] == "OPEN"

    t2_check = recorder_restored.get_ticket(ticket2["ticket_id"])
    assert t2_check is not None
    assert t2_check["stake"] == 100.0
    assert t2_check["status"] == "WON"
    assert t2_check["actual_payout"] == 185.0


def test_tampered_backup_rejection(tmp_path: Path):
    """Verify that restore_database rejects corrupted or checksum-mismatched files."""
    db_path = tmp_path / "src_db" / "war_chest.sqlite3"
    backup_dir = tmp_path / "backups"
    restore_path = tmp_path / "restored" / "war_chest.sqlite3"

    pm = ProfileManager(db_path=db_path)
    meta = backup_database(db_path=db_path, output_dir=backup_dir)
    backup_file = Path(meta["backup_file"])
    real_sha = meta["sha256"]

    # Attempt restore with invalid checksum expected
    with pytest.raises(ValueError, match="SHA256 checksum mismatch"):
        restore_database(
            backup_file=backup_file,
            target_db_path=restore_path,
            expected_sha256="0000000000000000000000000000000000000000000000000000000000000000",
        )

    # Corrupt the backup file
    raw = bytearray(backup_file.read_bytes())
    raw[10:30] = b"CORRUPTED_BYTES_HERE"
    corrupted_file = tmp_path / "corrupted.sqlite3"
    corrupted_file.write_bytes(raw)

    with pytest.raises((RuntimeError, ValueError)):
        restore_database(
            backup_file=corrupted_file,
            target_db_path=restore_path,
        )
