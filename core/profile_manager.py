#!/usr/bin/env python3
"""Multi-user Profile Manager with PIN protection and bankroll isolation.

Each profile defines a user's display name, weekly betting budget cap,
and a 4-digit numeric PIN for modifying profile settings.
Each profile owns an isolated wallet state, prize reserve pool, and betting ledger.
"""

from __future__ import annotations

import math
import re
import sqlite3
import uuid
import hashlib
import math
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from core.storage_config import get_db_path

DEFAULT_DB_PATH = get_db_path()
DEFAULT_PROFILE_ID = "default"
DEFAULT_PROFILE_NAME = "主帳號"
DEFAULT_WEEKLY_CAP = 200.0
DEFAULT_PIN_CODE = "0000"
PBKDF2_PREFIX = "pbkdf2:sha256:100000:"


def get_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_pin_code(pin: str) -> str:
    pin_str = str(pin).strip()
    if not re.fullmatch(r"\d{4}", pin_str):
        raise ValueError("PIN 碼必須為 4 位純數字（例如：0000、1234）。")
    return pin_str


def hash_pin_code(pin: str) -> str:
    """Hash a 4-digit PIN code using PBKDF2-HMAC-SHA256 with a cryptographically random 16-byte salt."""
    valid_pin = validate_pin_code(pin)
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", valid_pin.encode("utf-8"), salt, 100000)
    return f"{PBKDF2_PREFIX}{salt.hex()}:{dk.hex()}"


def verify_pin_code(pin: str, stored_val: str) -> bool:
    """Verify PIN against stored PBKDF2 salt/hash or legacy plaintext PIN."""
    pin_str = str(pin).strip()
    stored_str = str(stored_val or "").strip()
    if not pin_str or not stored_str:
        return False

    if stored_str.startswith(PBKDF2_PREFIX):
        try:
            parts = stored_str.split(":")
            # format: pbkdf2 : sha256 : 100000 : <salt_hex> : <dk_hex>
            iterations = int(parts[2])
            salt = bytes.fromhex(parts[3])
            expected_dk = bytes.fromhex(parts[4])
            actual_dk = hashlib.pbkdf2_hmac("sha256", pin_str.encode("utf-8"), salt, iterations)
            return secrets.compare_digest(actual_dk, expected_dk)
        except Exception:
            return False

    # Legacy plaintext 4-digit PIN comparison (constant-time)
    return secrets.compare_digest(stored_str, pin_str)


class ProfileManager:
    """Manages player profiles and settings with PIN authentication."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
        return conn

    @contextmanager
    def _transaction(self, conn: Optional[sqlite3.Connection] = None) -> Iterator[sqlite3.Connection]:
        owns = conn is None
        if conn is None:
            conn = self._get_connection()
        if conn.in_transaction:
            yield conn
            return
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            if owns:
                conn.close()

    def _init_db(self) -> None:
        with self._transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                weekly_play_cap REAL NOT NULL DEFAULT 200.0,
                pin_code TEXT NOT NULL DEFAULT '0000',
                line_user_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_name ON profiles(name)")

            # Migration: Ensure line_user_id column exists in existing DB
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(profiles)").fetchall()]
            if "line_user_id" not in cols:
                try:
                    conn.execute("ALTER TABLE profiles ADD COLUMN line_user_id TEXT")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_line_user ON profiles(line_user_id)")
                except Exception:
                    pass

            # Ensure default profile exists
            row = conn.execute("SELECT 1 FROM profiles WHERE id = ?", (DEFAULT_PROFILE_ID,)).fetchone()
            if row is None:
                now = get_now_iso()
                conn.execute(
                    """INSERT INTO profiles (id, name, weekly_play_cap, pin_code, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (DEFAULT_PROFILE_ID, DEFAULT_PROFILE_NAME, DEFAULT_WEEKLY_CAP, hash_pin_code(DEFAULT_PIN_CODE), now, now),
                )

            # Migration: Auto-migrate any legacy plaintext PINs to salted PBKDF2 hashes
            rows = conn.execute("SELECT id, pin_code FROM profiles").fetchall()
            for r in rows:
                raw_pin = str(r["pin_code"] or "").strip()
                if raw_pin and not raw_pin.startswith(PBKDF2_PREFIX):
                    try:
                        conn.execute("UPDATE profiles SET pin_code = ? WHERE id = ?", (hash_pin_code(raw_pin), r["id"]))
                    except Exception:
                        pass

    def list_profiles(self) -> List[Dict[str, Any]]:
        with self._transaction() as conn:
            rows = conn.execute("SELECT * FROM profiles ORDER BY created_at ASC").fetchall()
            return [dict(r) for r in rows]

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        pid = str(profile_id or DEFAULT_PROFILE_ID).strip()
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE id = ?", (pid,)).fetchone()
            return dict(row) if row else None

    def get_profile_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        name_str = str(name or "").strip()
        if not name_str:
            return None
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE lower(name) = lower(?)", (name_str,)).fetchone()
            return dict(row) if row else None

    def get_profile_by_line_user_id(self, line_user_id: str) -> Optional[Dict[str, Any]]:
        uid = str(line_user_id or "").strip()
        if not uid:
            return None
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE line_user_id = ?", (uid,)).fetchone()
            return dict(row) if row else None

    def bind_line_user(self, profile_id: str, line_user_id: str, current_pin: str) -> Dict[str, Any]:
        pid = str(profile_id or "").strip()
        uid = str(line_user_id or "").strip()
        if not uid:
            raise ValueError("LINE 使用者 ID 不可為空。")
        if not self.verify_pin(pid, current_pin):
            raise ValueError("【PIN 碼驗證失敗】目前輸入的 PIN 碼不正確，無法綁定此 LINE 帳號。")
        now = get_now_iso()
        with self._transaction() as conn:
            # Unbind other profile that had this line_user_id
            conn.execute("UPDATE profiles SET line_user_id = NULL, updated_at = ? WHERE line_user_id = ?", (now, uid))
            # Bind this profile
            conn.execute("UPDATE profiles SET line_user_id = ?, updated_at = ? WHERE id = ?", (uid, now, pid))
        return self.get_profile(pid)

    def unbind_line_user(self, profile_id: str, current_pin: str) -> bool:
        pid = str(profile_id or "").strip()
        if not self.verify_pin(pid, current_pin):
            raise ValueError("【PIN 碼驗證失敗】目前輸入的 PIN 碼不正確，無法解除綁定。")
        now = get_now_iso()
        with self._transaction() as conn:
            conn.execute("UPDATE profiles SET line_user_id = NULL, updated_at = ? WHERE id = ?", (now, pid))
        return True

    def change_pin(self, profile_id: str, current_pin: str, new_pin: str) -> Dict[str, Any]:
        """Convenience method to change PIN code for a profile."""
        return self.update_profile(profile_id, current_pin=current_pin, new_pin_code=new_pin)

    def verify_login(self, identifier: str, pin_code: str) -> tuple[bool, Optional[Dict[str, Any]], str]:
        """Verify login credentials by either profile_id or player name."""
        ident = str(identifier or "").strip()
        if not ident:
            return False, None, "請選擇或輸入玩家名稱。"
        profile = self.get_profile(ident) or self.get_profile_by_name(ident)
        if not profile:
            return False, None, f"找不到玩家「{ident}」。"
        stored_pin = str(profile.get("pin_code", DEFAULT_PIN_CODE)).strip()
        if not verify_pin_code(pin_code, stored_pin):
            return False, None, "PIN 碼不正確，請重新輸入（預設為 0000）。"
        if not stored_pin.startswith(PBKDF2_PREFIX):
            try:
                with self._transaction() as conn:
                    conn.execute("UPDATE profiles SET pin_code = ? WHERE id = ?", (hash_pin_code(pin_code), profile["id"]))
            except Exception:
                pass
        return True, profile, "驗證成功。"

    def get_or_default(self, profile_id: Optional[str] = None) -> Dict[str, Any]:
        if profile_id:
            profile = self.get_profile(profile_id)
            if profile:
                return profile
        default_profile = self.get_profile(DEFAULT_PROFILE_ID)
        if default_profile:
            return default_profile
        return {
            "id": DEFAULT_PROFILE_ID,
            "name": DEFAULT_PROFILE_NAME,
            "weekly_play_cap": DEFAULT_WEEKLY_CAP,
            "pin_code": hash_pin_code(DEFAULT_PIN_CODE),
            "created_at": get_now_iso(),
            "updated_at": get_now_iso(),
        }

    def verify_pin(self, profile_id: str, pin_code: str) -> bool:
        profile = self.get_profile(profile_id)
        if not profile:
            return False
        stored_pin = str(profile.get("pin_code", "")).strip()
        is_valid = verify_pin_code(pin_code, stored_pin)
        if is_valid and not stored_pin.startswith(PBKDF2_PREFIX):
            try:
                with self._transaction() as conn:
                    conn.execute("UPDATE profiles SET pin_code = ? WHERE id = ?", (hash_pin_code(pin_code), profile_id))
            except Exception:
                pass
        return is_valid

    def create_profile(
        self,
        name: str,
        weekly_play_cap: float = DEFAULT_WEEKLY_CAP,
        pin_code: str = DEFAULT_PIN_CODE,
    ) -> Dict[str, Any]:
        name_str = str(name).strip()
        if not name_str:
            raise ValueError("玩家名稱不可為空。")
        try:
            cap = float(weekly_play_cap)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("每週預算必須為大於 0 的正數。") from exc
        if not math.isfinite(cap) or cap <= 0:
            raise ValueError("每週預算必須為大於 0 的正數。")
        cap = round(cap, 2)
        valid_pin = validate_pin_code(pin_code)
        hashed_pin = hash_pin_code(valid_pin)

        profile_id = f"p_{uuid.uuid4().hex[:8]}"
        now = get_now_iso()

        with self._transaction() as conn:
            # Check duplicate name
            existing = conn.execute("SELECT id FROM profiles WHERE name = ?", (name_str,)).fetchone()
            if existing:
                raise ValueError(f"已存在名為「{name_str}」的玩家 Profile，請使用不同名稱。")

            conn.execute(
                """INSERT INTO profiles (id, name, weekly_play_cap, pin_code, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (profile_id, name_str, cap, hashed_pin, now, now),
            )

        return {
            "id": profile_id,
            "name": name_str,
            "weekly_play_cap": cap,
            "pin_code": hashed_pin,
            "created_at": now,
            "updated_at": now,
        }

    def update_profile(
        self,
        profile_id: str,
        current_pin: str,
        new_name: Optional[str] = None,
        new_weekly_play_cap: Optional[float] = None,
        new_pin_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        pid = str(profile_id or "").strip()
        if not self.verify_pin(pid, current_pin):
            raise ValueError("【PIN 碼驗證失敗】目前輸入的 PIN 碼不正確，無法修改個人設定。")

        profile = self.get_profile(pid)
        if not profile:
            raise ValueError(f"找不到 ID 為 {pid} 的 Profile。")

        target_name = profile["name"]
        if new_name is not None:
            name_str = str(new_name).strip()
            if not name_str:
                raise ValueError("玩家名稱不可為空。")
            target_name = name_str

        target_cap = float(profile["weekly_play_cap"])
        if new_weekly_play_cap is not None:
            try:
                cap_val = float(new_weekly_play_cap)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("每週預算必須為大於 0 的正數。") from exc
            if not math.isfinite(cap_val) or cap_val <= 0:
                raise ValueError("每週預算必須為大於 0 的正數。")
            target_cap = round(cap_val, 2)

        target_pin = profile["pin_code"]
        if new_pin_code is not None:
            target_pin = hash_pin_code(new_pin_code)

        now = get_now_iso()
        with self._transaction() as conn:
            # Check duplicate name if renamed
            if target_name != profile["name"]:
                existing = conn.execute("SELECT id FROM profiles WHERE name = ? AND id != ?", (target_name, pid)).fetchone()
                if existing:
                    raise ValueError(f"已存在名為「{target_name}」的其他玩家 Profile。")

            conn.execute(
                """UPDATE profiles SET name = ?, weekly_play_cap = ?, pin_code = ?, updated_at = ?
                WHERE id = ?""",
                (target_name, target_cap, target_pin, now, pid),
            )

            # Sync weekly_play_cap to wallet_state if wallet_state exists
            table_info = [r["name"] for r in conn.execute("PRAGMA table_info(wallet_state)").fetchall()]
            if "profile_id" in table_info and "weekly_play_cap" in table_info:
                conn.execute(
                    "UPDATE wallet_state SET weekly_play_cap = ?, updated_at = ? WHERE profile_id = ?",
                    (target_cap, now, pid),
                )

        return {
            "id": pid,
            "name": target_name,
            "weekly_play_cap": target_cap,
            "pin_code": target_pin,
            "created_at": profile["created_at"],
            "updated_at": now,
        }

    def delete_profile(self, profile_id: str, current_pin: str) -> bool:
        pid = str(profile_id or "").strip()
        if pid == DEFAULT_PROFILE_ID:
            raise ValueError("系統預設的「主帳號」不可被刪除。")
        if not self.verify_pin(pid, current_pin):
            raise ValueError("【PIN 碼驗證失敗】目前輸入的 PIN 碼不正確，無法刪除 Profile。")

        with self._transaction() as conn:
            conn.execute("DELETE FROM profiles WHERE id = ?", (pid,))
            table_info = [r["name"] for r in conn.execute("PRAGMA table_info(wallet_state)").fetchall()]
            if "profile_id" in table_info:
                conn.execute("DELETE FROM wallet_state WHERE profile_id = ?", (pid,))
            ledger_info = [r["name"] for r in conn.execute("PRAGMA table_info(ledger)").fetchall()]
            if "profile_id" in ledger_info:
                conn.execute("DELETE FROM ledger WHERE profile_id = ?", (pid,))
            ticket_info = [r["name"] for r in conn.execute("PRAGMA table_info(tickets)").fetchall()]
            if "profile_id" in ticket_info:
                conn.execute("DELETE FROM tickets WHERE profile_id = ?", (pid,))
        return True
