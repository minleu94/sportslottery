#!/usr/bin/env python3
"""LINE Bot Messaging API Notification Engine (LINE 即時推播引擎).

Supports Profile-scoped alerts for odds changes, local ticket settlements,
conditional hedge reminders, and the daily Radar summary.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlsplit
from core.line_flex import (
    TAIWAN_LOTTERY_URL,
    _parlay_probability_source,
    build_menu_flex,
    build_manual_slip_flex,
    build_notification_flex,
    build_parlay_flex,
    build_radar_flex,
    build_status_flex,
    build_wallet_flex,
    system_deep_link,
)
from core.tunnel_runtime import load_active_runtime
import requests
import yaml

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "line_notifier.yaml"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
LINE_SEARCH_STATE_TTL_SECONDS = 30 * 60
LINE_SEARCH_STATE_MAX_USERS = 1000
LINE_EVENT_DEDUPE_TTL_SECONDS = 24 * 60 * 60
LINE_EVENT_DEDUPE_MAX_IDS = 20000
LINE_NOTIFICATION_DEDUPE_TTL_SECONDS = 60 * 60
LINE_NOTIFICATION_DEDUPE_MAX_IDS = 20000
LINE_MAX_NOTIFICATION_AGE_SECONDS = 15 * 60
LINE_BINDING_REQUEST_TTL_SECONDS = 10 * 60
LINE_BINDING_REQUEST_MAX_IDS = 500
LINE_BINDING_REQUEST_MAX_PER_PROFILE = 5
LINE_PREFERENCE_KEYS = ("steam_drop", "ticket_settlement", "hedging_alert", "morning_radar")


def _attach_quick_replies(message: Dict[str, Any], quick_replies: Optional[List[Dict[str, str]]]) -> Dict[str, Any]:
    if quick_replies:
        message["quickReply"] = {
            "items": [
                {
                    "type": "action",
                    "action": {
                        "type": "message",
                        "label": item.get("label", item.get("text", ""))[:20],
                        "text": item.get("text", "")[:300],
                    },
                }
                for item in quick_replies[:13]
            ]
        }
    return message


@dataclass
class _LineUserSearchState:
    """Short-lived parlay conversation state isolated to one LINE user."""

    last_recommended_parlay: Optional[Dict[str, Any]] = None
    last_parlay_candidates: List[Dict[str, Any]] = field(default_factory=list)
    last_candidate_index: int = 0
    last_search_context: Dict[str, Any] = field(default_factory=dict)
    last_search_result: Dict[str, Any] = field(default_factory=dict)
    last_wallet_status: Optional[Dict[str, Any]] = None
    last_wallet_tickets: List[Dict[str, Any]] = field(default_factory=list)
    last_radar_status: Optional[Dict[str, Any]] = None
    last_profile_id: Optional[str] = None
    last_flex_message: Optional[Dict[str, Any]] = None
    lock: Any = field(default_factory=threading.RLock, repr=False)
    last_accessed: float = field(default_factory=time.monotonic)
    active_requests: int = 0


@dataclass
class _PendingLineBindingRequest:
    request_id: str
    profile_id: str
    line_user_id: str
    confirmation_code: str
    created_at: float
    expires_at: float


class LineNotifier:
    """Sends real-time sports betting alerts to LINE via LINE Messaging API."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        session: Optional[requests.Session] = None,
        profile_manager: Optional[Any] = None,
    ):
        self.config_path = config_path or CONFIG_PATH
        self.session = session or requests.Session()
        self._profile_manager_instance = profile_manager
        self.config = self.load_config()
        self.last_recommended_parlay: Optional[Dict[str, Any]] = None
        self.last_parlay_candidates: List[Dict[str, Any]] = []
        self.last_candidate_index: int = 0
        self.last_search_context: Dict[str, Any] = {}
        self._user_search_states: OrderedDict[str, _LineUserSearchState] = OrderedDict()
        self._user_search_states_lock = threading.Lock()
        self._seen_webhook_events: OrderedDict[str, float] = OrderedDict()
        self._seen_webhook_events_lock = threading.Lock()
        self._seen_notifications: OrderedDict[str, float] = OrderedDict()
        self._seen_notifications_lock = threading.Lock()
        self._pending_line_bindings: OrderedDict[str, _PendingLineBindingRequest] = OrderedDict()
        self._pending_line_bindings_lock = threading.Lock()

    def claim_webhook_event(self, event_id: Optional[str]) -> bool:
        """Claim a LINE webhook event once to avoid duplicate work on redelivery."""
        normalized_id = str(event_id or "").strip()
        if not normalized_id:
            return True
        now = time.monotonic()
        with self._seen_webhook_events_lock:
            while self._seen_webhook_events:
                oldest_id, seen_at = next(iter(self._seen_webhook_events.items()))
                if now - seen_at < LINE_EVENT_DEDUPE_TTL_SECONDS:
                    break
                self._seen_webhook_events.pop(oldest_id, None)

            if normalized_id in self._seen_webhook_events:
                return False

            self._seen_webhook_events[normalized_id] = now
            while len(self._seen_webhook_events) > LINE_EVENT_DEDUPE_MAX_IDS:
                self._seen_webhook_events.popitem(last=False)
            return True

    def release_webhook_event(self, event_id: Optional[str]) -> None:
        """Allow LINE redelivery to retry an event that failed during processing."""
        normalized_id = str(event_id or "").strip()
        if not normalized_id:
            return
        with self._seen_webhook_events_lock:
            self._seen_webhook_events.pop(normalized_id, None)

    @contextmanager
    def user_search_context(self, line_user_id: Optional[str]) -> Iterator[Any]:
        """Lock and yield one user's search state; anonymous direct calls retain legacy state."""
        user_id = str(line_user_id or "").strip()
        if not user_id:
            yield self
            return

        now = time.monotonic()
        with self._user_search_states_lock:
            self._prune_user_search_states(now)
            state = self._user_search_states.get(user_id)
            if state is None:
                state = _LineUserSearchState()
                self._user_search_states[user_id] = state
            else:
                self._user_search_states.move_to_end(user_id)
            state.active_requests += 1
            state.last_accessed = now

        try:
            with state.lock:
                yield state
        finally:
            with self._user_search_states_lock:
                state.active_requests = max(0, state.active_requests - 1)
                state.last_accessed = time.monotonic()
                self._user_search_states.move_to_end(user_id)
                self._prune_user_search_states(state.last_accessed)

    def _prune_user_search_states(self, now: float) -> None:
        expired = [
            user_id
            for user_id, state in self._user_search_states.items()
            if state.active_requests == 0 and now - state.last_accessed >= LINE_SEARCH_STATE_TTL_SECONDS
        ]
        for user_id in expired:
            self._user_search_states.pop(user_id, None)

        while len(self._user_search_states) > LINE_SEARCH_STATE_MAX_USERS:
            removable = next(
                (user_id for user_id, state in self._user_search_states.items() if state.active_requests == 0),
                None,
            )
            if removable is None:
                break
            self._user_search_states.pop(removable, None)

    def load_config(self) -> Dict[str, Any]:
        """Load LINE Bot settings from YAML config or environment variables."""
        cfg: Dict[str, Any] = {
            "enabled": False,
            "channel_access_token": "",
            "notify_events": {
                "steam_drop": True,
                "ticket_settlement": True,
                "hedging_alert": True,
                "morning_radar": True,
            },
        }

        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f) or {}
                if isinstance(loaded, dict):
                    cfg.update(loaded)
            except Exception as exc:
                logger.warning("Failed to load line_notifier.yaml: %s", exc)

        # Environment variable overrides
        env_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
        if env_token:
            cfg["channel_access_token"] = env_token

        # Ignore the legacy global recipient. Push delivery must resolve from
        # a Profile that explicitly bound this LINE identity.
        cfg.pop("user_id", None)
        if not isinstance(cfg.get("line_preferences"), dict):
            cfg["line_preferences"] = {}

        # Signed replies work without a global push recipient.
        if cfg["channel_access_token"] and "enabled" not in cfg:
            cfg["enabled"] = True

        return cfg

    def save_config(self, new_cfg: Dict[str, Any]) -> None:
        """Persist updated LINE Bot credentials and preference settings."""
        self.config.update(new_cfg)
        self.config.pop("user_id", None)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        persisted_config = dict(self.config)
        if os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"):
            # An environment override is runtime-only; never copy it into YAML
            # when an unrelated preference or setting is saved.
            try:
                disk_config = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                disk_config = None
            disk_token = disk_config.get("channel_access_token") if isinstance(disk_config, dict) else None
            if disk_token:
                persisted_config["channel_access_token"] = disk_token
            else:
                persisted_config.pop("channel_access_token", None)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(persisted_config, f, allow_unicode=True, sort_keys=False)

    def is_configured(self) -> bool:
        """Check whether the Messaging API channel credentials are active."""
        token = str(self.config.get("channel_access_token") or "").strip()
        return bool(self.config.get("enabled", False) and token)

    @staticmethod
    def is_slow_parlay_search_request(user_text: str) -> bool:
        """Return whether this command triggers a parlay search instead of a quick menu reply."""
        cmd = user_text.strip().lower()
        if not cmd:
            return False
        if any(k in cmd for k in ["高勝率", "保底", "穩健", "銀行家", "banker"]):
            return True
        if any(k in cmd for k in ["換一組", "另一組", "換一張", "下一組", "換", "next", "reroll", "再一組"]):
            return True
        mult_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:倍|x|X)?", cmd)
        if not mult_match or not ("倍" in cmd or "x" in cmd or cmd.isdigit() or "串" in cmd):
            return False
        try:
            target_mult = float(mult_match.group(1))
        except ValueError:
            return False
        return 1.5 <= target_mult <= 1000

    @staticmethod
    def requires_private_line_chat(user_text: str) -> bool:
        """Keep Profile, Wallet, notification, and hedge details out of group chats."""
        command = str(user_text or "").strip().lower()
        private_terms = (
            "戰績", "錢包", "餘額", "本金", "獲利", "本週", "通知", "聽牌", "對沖",
            "最後一關", "個人設定", "帳號", "綁定", "解綁", "解除綁定", "登入",
            "改密碼", "修改密碼", "pin", "預算", "限額", "profile", "login", "unbind",
        )
        return any(term in command for term in private_terms)

    def send_push_message(
        self,
        text: str,
        user_id: Optional[str] = None,
        image_url: Optional[str] = None,
        quick_replies: Optional[List[Dict[str, str]]] = None,
        flex_message: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a push only to an explicit, Profile-bound LINE recipient."""
        token = str(self.config.get("channel_access_token") or "").strip()
        target = str(user_id or "").strip()

        if not token:
            return {
                "success": False,
                "status_code": 0,
                "error": "LINE_NOT_CONFIGURED",
                "message": "尚未設定 Channel Access Token",
            }
        if not target:
            return {"success": False, "status_code": 0, "error": "LINE_TARGET_REQUIRED", "message": "未提供已綁定的 LINE 收件者"}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        messages_list = []
        if image_url:
            messages_list.append({
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            })
        use_flex = bool(flex_message and os.environ.get("LINE_DISABLE_FLEX", "").lower() not in {"1", "true", "yes"})
        msg_obj = _attach_quick_replies(dict(flex_message) if use_flex else {"type": "text", "text": text}, quick_replies)
        messages_list.append(msg_obj)

        payload = {
            "to": target,
            "messages": messages_list,
        }

        try:
            resp = self.session.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=8.0)
            if resp.status_code == 200:
                logger.info("LINE message successfully delivered to %s", target[:6] + "...")
                return {"success": True, "status_code": 200}
            else:
                err_text = resp.text
                if use_flex and 400 <= resp.status_code < 500:
                    fallback_message = _attach_quick_replies({"type": "text", "text": str(text)[:5000]}, quick_replies)
                    fallback = {"to": target, "messages": [fallback_message]}
                    fallback_response = self.session.post(LINE_PUSH_URL, headers=headers, json=fallback, timeout=8.0)
                    if fallback_response.status_code == 200:
                        return {"success": True, "status_code": 200, "fallback": "text"}
                logger.warning("LINE push failed [%d]: %s", resp.status_code, err_text)
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "error": "HTTP_ERROR",
                    "message": err_text,
                }
        except Exception as exc:
            logger.error("Network error while connecting to LINE API: %s", exc)
            return {
                "success": False,
                "status_code": 0,
                "error": "NETWORK_EXCEPTION",
                "message": str(exc),
            }

    def reply_message(
        self,
        reply_token: str,
        text: str,
        quick_replies: Optional[List[Dict[str, str]]] = None,
        image_url: Optional[str] = None,
        flex_message: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a LINE reply, using Flex altText as the complete unsupported-client fallback."""
        token = str(self.config.get("channel_access_token") or "").strip()
        if not token or not reply_token:
            return {
                "success": False,
                "status_code": 0,
                "error": "LINE_NOT_CONFIGURED",
                "message": "尚未設定 Channel Access Token 或無效的 reply_token",
            }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        messages_list = []
        if image_url:
            messages_list.append({
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            })

        use_flex = bool(flex_message and os.environ.get("LINE_DISABLE_FLEX", "").lower() not in {"1", "true", "yes"})
        msg_obj = _attach_quick_replies(dict(flex_message) if use_flex else {"type": "text", "text": text}, quick_replies)
        messages_list.append(msg_obj)

        payload = {
            "replyToken": reply_token,
            "messages": messages_list,
        }

        try:
            resp = self.session.post(LINE_REPLY_URL, headers=headers, json=payload, timeout=8.0)
            if resp.status_code == 200:
                logger.info("LINE reply delivered successfully via replyToken.")
                return {"success": True, "status_code": 200}
            else:
                err_text = resp.text
                if use_flex and 400 <= resp.status_code < 500:
                    fallback_message = _attach_quick_replies({"type": "text", "text": str(text)[:5000]}, quick_replies)
                    fallback = {"replyToken": reply_token, "messages": [fallback_message]}
                    fallback_response = self.session.post(LINE_REPLY_URL, headers=headers, json=fallback, timeout=8.0)
                    if fallback_response.status_code == 200:
                        return {"success": True, "status_code": 200, "fallback": "text"}
                logger.warning("LINE reply failed [%d]: %s", resp.status_code, err_text)
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "error": "HTTP_ERROR",
                    "message": err_text,
                }
        except Exception as exc:
            logger.error("Network error while replying to LINE API: %s", exc)
            return {
                "success": False,
                "status_code": 0,
                "error": "NETWORK_EXCEPTION",
                "message": str(exc),
            }

    @staticmethod
    def default_quick_replies() -> List[Dict[str, str]]:
        """Six primary entries that mirror the LINE Flex main menu."""
        return [
            {"label": "🎯 智慧串關", "text": "智慧串關"},
            {"label": "🛡️ Banker 精選", "text": "Banker 穩健精選"},
            {"label": "☀️ 今日賽事", "text": "今日開盤"},
            {"label": "💰 資產戰績", "text": "查戰績"},
            {"label": "🔔 通知設定", "text": "通知設定"},
            {"label": "👤 個人設定／主系統", "text": "個人設定"},
        ]

    @staticmethod
    def parlay_quick_replies(has_next: bool = True) -> List[Dict[str, str]]:
        """Contextual actions displayed immediately after a parlay recommendation."""
        replies: List[Dict[str, str]] = []
        if has_next:
            replies.append({"label": "🎲 換一組推薦", "text": "換一組"})
        replies.extend([
            {"label": "🛡️ Banker 精選", "text": "Banker 穩健精選"},
            {"label": "📋 投注單明細", "text": "投注單明細"},
            {"label": "🎯 找20倍", "text": "20倍"},
            {"label": "🔥 找50倍", "text": "50倍"},
            {"label": "🏠 回主選單", "text": "功能表"},
        ])
        return replies

    @staticmethod
    def multiplier_menu_quick_replies() -> List[Dict[str, str]]:
        """Sub-tier options when user asks for multiplier parlay menu."""
        return [
            {"label": "🛡️ Banker 1.5–6x", "text": "Banker 穩健精選"},
            {"label": "🔥 瘋狗 10倍", "text": "10倍"},
            {"label": "🎯 經典 20倍", "text": "20倍"},
            {"label": "💥 狂暴 50倍", "text": "50倍"},
            {"label": "🚀 登月 100倍", "text": "100倍"},
            {"label": "⚽ 足球 20倍", "text": "足球 20倍"},
            {"label": "🏀 NBA 15倍", "text": "NBA 15倍"},
            {"label": "🏠 回主選單", "text": "功能表"},
        ]

    @staticmethod
    def radar_menu_quick_replies() -> List[Dict[str, str]]:
        """Sub-tier options when user inspects daily radar or sports."""
        return [
            {"label": "⚽ 足球 20倍", "text": "足球 20倍"},
            {"label": "🏀 NBA 15倍", "text": "NBA 15倍"},
            {"label": "🎯 瘋狗 20倍", "text": "20倍"},
            {"label": "🛡️ Banker 精選", "text": "Banker 穩健精選"},
            {"label": "🏠 回主選單", "text": "功能表"},
        ]

    @staticmethod
    def wallet_menu_quick_replies() -> List[Dict[str, str]]:
        """Sub-tier options when user inspects wallet / finance."""
        return [
            {"label": "🛡️ 聽牌對沖計算", "text": "對沖"},
            {"label": "💰 重新整理戰績", "text": "查戰績"},
            {"label": "👤 玩家登入/設定", "text": "個人設定"},
            {"label": "🎯 智慧串關", "text": "智慧串關"},
            {"label": "🏠 回主選單", "text": "功能表"},
        ]

    @staticmethod
    def tools_menu_quick_replies() -> List[Dict[str, str]]:
        """Keep the main menu short and place account actions on the main web app."""
        return [
            {"label": "🎯 智慧串關", "text": "智慧串關"},
            {"label": "🛡️ Banker 精選", "text": "Banker 穩健精選"},
            {"label": "☀️ 今日賽事", "text": "今日開盤"},
            {"label": "💰 資產戰績", "text": "查戰績"},
            {"label": "🔔 通知設定", "text": "通知設定"},
            {"label": "👤 個人設定", "text": "個人設定"},
            {"label": "🏠 回主選單", "text": "功能表"},
        ]

    def _profile_manager(self) -> Any:
        if self._profile_manager_instance is None:
            from server import service_registry
            self._profile_manager_instance = service_registry.get_services().profile_mgr
        return self._profile_manager_instance

    def _runtime_system_url(self) -> Optional[str]:
        # Cloud deployments provide a stable public origin via environment.
        # Local tray-managed deployments continue to discover their active tunnel.
        configured_url = os.environ.get("SPORTSLOTTERY_PUBLIC_URL", "").strip()
        if configured_url:
            parts = urlsplit(configured_url)
            if parts.scheme.lower() == "https" and parts.hostname and not parts.username and not parts.password:
                return configured_url.rstrip("/")

        runtime = load_active_runtime(ROOT_DIR / "data" / "line_bot_runtime.json")
        url = str(runtime.get("tunnel_url") or "").strip()
        parts = urlsplit(url)
        if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
            return None
        return url.rstrip("/")

    def _get_bound_profile(self, line_user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        user_id = str(line_user_id or "").strip()
        if not user_id:
            return None
        try:
            return self._profile_manager().get_profile_by_line_user_id(user_id)
        except Exception as exc:
            logger.warning("Unable to resolve bound LINE Profile: %s", exc)
            return None

    def get_notification_preferences(self, profile_id: str) -> Dict[str, bool]:
        all_settings = self.config.get("line_preferences") if isinstance(self.config.get("line_preferences"), dict) else {}
        saved = all_settings.get(str(profile_id), {}) if isinstance(all_settings.get(str(profile_id)), dict) else {}
        return {key: bool(saved.get(key, True)) for key in LINE_PREFERENCE_KEYS}

    def update_notification_preferences(self, line_user_id: Optional[str], updates: Dict[str, Any]) -> Optional[Dict[str, bool]]:
        profile = self._get_bound_profile(line_user_id)
        if not profile:
            return None
        accepted = {key: value for key, value in updates.items() if key in LINE_PREFERENCE_KEYS and isinstance(value, bool)}
        if not accepted:
            return self.get_notification_preferences(str(profile["id"]))
        all_settings = self.config.get("line_preferences")
        if not isinstance(all_settings, dict):
            all_settings = {}
        settings = self.get_notification_preferences(str(profile["id"]))
        settings.update(accepted)
        all_settings[str(profile["id"])] = settings
        self.save_config({"line_preferences": all_settings})
        return settings

    def request_line_binding(self, profile_name: str, line_user_id: Optional[str]) -> Dict[str, Any]:
        """Create a short-lived request that must be approved in the authenticated web app."""
        uid = str(line_user_id or "").strip()
        name = str(profile_name or "").strip()
        if not uid or not name:
            return {"success": False, "reason": "PROFILE_NAME_REQUIRED"}
        try:
            manager = self._profile_manager()
            profile = manager.get_profile_by_name(name)
            if not profile:
                return {"success": False, "reason": "PROFILE_NOT_FOUND"}
            existing = manager.get_profile_by_line_user_id(uid)
            if existing and str(existing.get("id")) != str(profile.get("id")):
                return {"success": False, "reason": "LINE_ALREADY_BOUND"}
        except Exception as exc:
            logger.warning("Unable to create LINE binding request: %s", exc)
            return {"success": False, "reason": "PROFILE_SERVICE_UNAVAILABLE"}

        if existing:
            return {"success": True, "already_bound": True, "profile_name": profile.get("name")}

        now = time.time()
        request_id = uuid.uuid4().hex
        confirmation_code = "".join(secrets.choice("23456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6))
        request = _PendingLineBindingRequest(
            request_id=request_id,
            profile_id=str(profile["id"]),
            line_user_id=uid,
            confirmation_code=confirmation_code,
            created_at=now,
            expires_at=now + LINE_BINDING_REQUEST_TTL_SECONDS,
        )
        with self._pending_line_bindings_lock:
            expired = [key for key, value in self._pending_line_bindings.items() if value.expires_at <= now]
            for key in expired:
                self._pending_line_bindings.pop(key, None)
            existing_request = next(
                (
                    value for value in self._pending_line_bindings.values()
                    if value.profile_id == request.profile_id and value.line_user_id == uid
                ),
                None,
            )
            if existing_request:
                return {
                    "success": True,
                    "already_pending": True,
                    "profile_name": profile.get("name"),
                    "confirmation_code": existing_request.confirmation_code,
                    "expires_at": datetime.fromtimestamp(existing_request.expires_at, timezone.utc).isoformat(),
                }
            profile_request_count = sum(
                value.profile_id == request.profile_id for value in self._pending_line_bindings.values()
            )
            if profile_request_count >= LINE_BINDING_REQUEST_MAX_PER_PROFILE:
                return {"success": False, "reason": "TOO_MANY_PENDING_REQUESTS"}
            self._pending_line_bindings[request_id] = request
            while len(self._pending_line_bindings) > LINE_BINDING_REQUEST_MAX_IDS:
                self._pending_line_bindings.popitem(last=False)
        return {
            "success": True,
            "profile_name": profile.get("name"),
            "confirmation_code": confirmation_code,
            "expires_at": datetime.fromtimestamp(request.expires_at, timezone.utc).isoformat(),
        }

    def list_line_binding_requests(self, profile_id: str) -> List[Dict[str, Any]]:
        pid = str(profile_id or "").strip()
        now = time.time()
        with self._pending_line_bindings_lock:
            expired = [key for key, value in self._pending_line_bindings.items() if value.expires_at <= now]
            for key in expired:
                self._pending_line_bindings.pop(key, None)
            pending = [value for value in self._pending_line_bindings.values() if value.profile_id == pid]
        return [
            {
                "request_id": request.request_id,
                "display_name": "LINE 私人對話",
                "confirmation_code": request.confirmation_code,
                "created_at": datetime.fromtimestamp(request.created_at, timezone.utc).isoformat(),
                "expires_at": datetime.fromtimestamp(request.expires_at, timezone.utc).isoformat(),
            }
            for request in pending
        ]

    def approve_line_binding_request(self, profile_id: str, request_id: str) -> bool:
        pid = str(profile_id or "").strip()
        rid = str(request_id or "").strip()
        with self._pending_line_bindings_lock:
            request = self._pending_line_bindings.get(rid)
            if not request:
                return False
            if request.expires_at <= time.time():
                self._pending_line_bindings.pop(rid, None)
                return False
            if request.profile_id != pid:
                return False
            self._profile_manager().bind_line_user_from_authenticated_session(pid, request.line_user_id)
            self._pending_line_bindings.pop(rid, None)
            return True

    def reject_line_binding_request(self, profile_id: str, request_id: str) -> bool:
        pid = str(profile_id or "").strip()
        rid = str(request_id or "").strip()
        with self._pending_line_bindings_lock:
            request = self._pending_line_bindings.get(rid)
            if not request or request.profile_id != pid:
                return False
            self._pending_line_bindings.pop(rid, None)
            return True

    def _claim_notification(self, profile_id: str, event_name: str, event_key: str) -> bool:
        key = f"{profile_id}:{event_name}:{event_key}"
        now = time.monotonic()
        with self._seen_notifications_lock:
            expired = [item for item, created in self._seen_notifications.items() if now - created >= LINE_NOTIFICATION_DEDUPE_TTL_SECONDS]
            for item in expired:
                self._seen_notifications.pop(item, None)
            if key in self._seen_notifications:
                return False
            self._seen_notifications[key] = now
            while len(self._seen_notifications) > LINE_NOTIFICATION_DEDUPE_MAX_IDS:
                self._seen_notifications.popitem(last=False)
            return True

    def _notification_profiles(self, event_name: str, profile_id: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            if profile_id:
                profiles = [self._profile_manager().get_profile(profile_id)]
            else:
                profiles = self._profile_manager().list_profiles()
        except Exception as exc:
            logger.warning("Unable to load Profiles for LINE notification: %s", exc)
            return []
        result = []
        for profile in profiles:
            if not isinstance(profile, dict) or not profile.get("id") or not profile.get("line_user_id"):
                continue
            if not self.get_notification_preferences(str(profile["id"])).get(event_name, False):
                continue
            result.append(profile)
        return result

    def _dispatch_notification(
        self,
        event_name: str,
        event_key: str,
        text: str,
        *,
        profile_id: Optional[str] = None,
        system_tab: str = "radar",
        require_profile: bool = False,
    ) -> Dict[str, Any]:
        if not self.is_configured():
            return {"success": False, "skipped": True, "reason": "LINE_NOT_CONFIGURED"}
        if require_profile and not str(profile_id or "").strip():
            return {"success": False, "skipped": True, "reason": "PROFILE_REQUIRED"}
        recipients = self._notification_profiles(event_name, profile_id)
        if not recipients:
            return {"success": False, "skipped": True, "reason": "NO_BOUND_RECIPIENTS"}
        sent = 0
        failures = []
        for profile in recipients:
            pid = str(profile["id"])
            if not self._claim_notification(pid, event_name, event_key):
                continue
            card = build_status_flex(event_name.replace("_", " ").title(), "Sportslottery 本站通知", [text], system_url=self._runtime_system_url(), tab=system_tab)
            result = self.send_push_message(text, user_id=str(profile["line_user_id"]), flex_message=card)
            if result.get("success"):
                sent += 1
            else:
                self._release_notification(pid, event_name, event_key)
                failures.append(result.get("error", "SEND_FAILED"))
        if not sent and not failures:
            return {"success": False, "skipped": True, "reason": "DUPLICATE"}
        return {"success": sent > 0, "sent": sent, "failures": failures}

    def _release_notification(self, profile_id: str, event_name: str, event_key: str) -> None:
        key = f"{profile_id}:{event_name}:{event_key}"
        with self._seen_notifications_lock:
            self._seen_notifications.pop(key, None)

    def test_connection(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Send an instant test ping to verify LINE bot integration."""
        msg = (
            "🐕 【台灣運彩 瘋狗流決策台】\n"
            "---------------------------\n"
            "✅ LINE 即時通知推播連線成功！\n\n"
            "本頻道可依您的 Profile 通知偏好傳送資料變更與本站帳務摘要。\n"
            "推薦估值與對沖試算不保證賽果、成交或獲利。"
        )
        return self.send_push_message(msg, user_id=user_id)

    # -------------------------------------------------------------------------
    # High-level Alert Event Dispatchers
    # -------------------------------------------------------------------------

    def notify_steam_drop(
        self,
        league: str,
        match_title: str,
        market: str,
        selection: str,
        old_odds: float,
        new_odds: float,
        delta_odds: float,
        delta_pct: float,
        *,
        source: str = "本站台彩盤口快照",
        observed_at: Optional[str] = None,
        trigger: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Notify bound Profiles about a meaningful odds change without inferring money flow."""
        observed = str(observed_at or "").strip()
        if not self._is_recent_source_time(observed):
            return {"success": False, "skipped": True, "reason": "SOURCE_TIME_MISSING_OR_STALE"}
        condition = trigger or f"賠率變動 {delta_pct:+.1%}（由上游監控條件觸發）"
        text = (
            "📉 【重要賠率變動】\n"
            f"🏆 賽事：[{league}] {match_title}\n"
            f"🎯 玩法：{market} ➔ 【{selection}】\n"
            f"📊 賠率變動：{old_odds:.2f} ➔ {new_odds:.2f} ({delta_odds:+.2f} / {delta_pct:+.1%})\n\n"
            f"資料來源：{source}\n觀測時間：{observed}\n觸發條件：{condition}\n"
            "賠率變動本身無法證明資金流向或投注方向；盤口可能繼續變動。"
        )
        try:
            observed_dt = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if observed_dt.tzinfo is None:
                observed_dt = observed_dt.replace(tzinfo=timezone.utc)
            bucket = int(observed_dt.timestamp() // (15 * 60))
        except (TypeError, ValueError, OverflowError):
            return {"success": False, "skipped": True, "reason": "SOURCE_TIME_INVALID"}
        key = hashlib.sha256(f"{league}|{match_title}|{market}|{selection}|{bucket}".encode("utf-8")).hexdigest()[:24]
        return self._dispatch_notification("steam_drop", key, text, system_tab="radar")

    @staticmethod
    def _is_recent_source_time(value: str, max_age_seconds: int = LINE_MAX_NOTIFICATION_AGE_SECONDS) -> bool:
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
            return -60 <= age <= max_age_seconds
        except (TypeError, ValueError, OverflowError):
            return False

    def notify_ticket_settlement(
        self,
        ticket: Dict[str, Any],
        won: bool,
        actual_payout: float,
        prize_pool: float,
        weekly_balance: float,
    ) -> Dict[str, Any]:
        """Notify the LINE account bound to the Profile whose local ticket settled."""

        sports = ticket.get("sports_summary") or "運彩串關"
        stake = ticket.get("stake", 0.0)
        total_odds = ticket.get("placed_odds") or ticket.get("total_odds", 1.0)

        if won:
            net_profit = actual_payout - stake
            text = (
                "🎉 【本站注單結算】\n"
                f"🎫 組合：{sports}\n"
                f"🔥 賠率：{total_odds:.2f} 倍\n"
                f"💵 下注本金：NT$ {stake:,.0f}\n"
                f"💰 實際派彩：NT$ {actual_payout:,.2f} (+NT$ {net_profit:,.2f})\n\n"
                "本站帳務已記錄此結算。\n"
                f"• 目前儲備池總額：NT$ {prize_pool:,.2f}\n"
                f"• 本週可玩餘額：NT$ {weekly_balance:,.2f}"
            )
        else:
            text = (
                "ℹ️ 【本站注單結算】\n"
                f"🎫 組合：{sports} ({total_odds:.2f}x)\n"
                f"💵 投入本金：NT$ {stake:,.0f}\n"
                "結果：本站記錄為未全數命中。\n"
                f"• 本週剩餘可玩額度：NT$ {weekly_balance:,.2f}"
            )
        settled_at = str(ticket.get("settled_at") or ticket.get("updated_at") or "時間未提供")
        text += f"\n來源：Sportslottery 本站 Ticket 結算記錄。本站結算時間：{settled_at}。這不代表台灣運彩官方已受理投注或確認派彩。"
        ticket_key = str(ticket.get("ticket_id") or ticket.get("id") or hashlib.sha256(json.dumps(ticket, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20])
        return self._dispatch_notification(
            "ticket_settlement", f"{ticket_key}:{int(bool(won))}:{actual_payout:.2f}", text,
            profile_id=str(ticket.get("profile_id") or ""), system_tab="wallet", require_profile=True,
        )

    def notify_hedging_alert(
        self,
        ticket: Dict[str, Any],
        pending_leg: Dict[str, Any],
        hedge_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send an estimate notice; opposing odds are never represented as guaranteed."""

        sports = ticket.get("sports_summary") or "運彩高倍串關"
        potential_payout = float(ticket.get("potential_payout", 0.0))
        stake = float(ticket.get("stake", 0.0))

        match_str = f"{pending_leg.get('away_team')} vs {pending_leg.get('home_team')}"
        opposing_bet = hedge_analysis.get("opposing_selection", "反向盤口")
        try:
            hedge_odds = float(hedge_analysis.get("hedge_odds"))
            hedge_odds_text = f"{hedge_odds:.2f}" if hedge_odds > 1 else "未提供有效價格"
        except (TypeError, ValueError, OverflowError):
            hedge_odds = 0.0
            hedge_odds_text = "未提供有效價格"
        breakeven_stake = float(hedge_analysis.get("breakeven_stake", 0.0))
        source = str(hedge_analysis.get("source") or "未提供可信即時對向盤口")
        observed = str(hedge_analysis.get("observed_at") or "時間未提供")
        trigger = str(hedge_analysis.get("trigger") or "本站注單目前僅剩一關待賽")
        hedge_stake_line = f"• 假設可取得該價格時，平衡注金試算約 NT$ {breakeven_stake:.0f}\n" if hedge_odds > 1 else ""

        text = (
            "🔔 【本站聽牌／對沖提醒】\n"
            + f"🎫 串關：{sports}\n"
            + f"🎯 本站記錄潛在派彩：NT$ {potential_payout:,.2f} (本金 NT$ {stake:,.0f})\n"
            + f"⏳ 最後決戰：[{pending_leg.get('league')}] {match_str}\n"
            + f"目前手持關卡：【{pending_leg.get('selection')}】\n\n"
            + "試算條件：\n"
            + f"• 反向標的：【{opposing_bet}】；假設賠率 {hedge_odds_text}\n"
            + hedge_stake_line
            + f"• 資料來源：{source}\n觀測時間：{observed}\n觸發條件：{trigger}\n"
            + "此為條件式試算，未取得可信即時對向盤口；不保證可成交、打平或獲利。"
        )
        ticket_key = str(ticket.get("ticket_id") or ticket.get("id") or ticket.get("sports_summary") or "ticket")
        return self._dispatch_notification(
            "hedging_alert", f"{ticket_key}:{pending_leg.get('event_id') or match_str}", text,
            profile_id=str(ticket.get("profile_id") or ""), system_tab="wallet", require_profile=True,
        )

    def notify_morning_radar(
        self,
        radar_summary: List[Dict[str, Any]],
        top_picks: Optional[List[Dict[str, Any]]] = None,
        *,
        as_of: Optional[str] = None,
        source_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Daily snapshot of Taiwan Sports Lottery markets and source status."""

        observed = str(as_of or "").strip()
        if not self._is_recent_source_time(observed):
            return {"success": False, "skipped": True, "reason": "SOURCE_TIME_MISSING_OR_STALE"}

        green_leagues = [r for r in radar_summary if r.get("status") == "GREEN"]
        leagues_str = "、".join(f"{r['icon']}{r['name']}({r['taiwan_market_count']}場)" for r in green_leagues) or "今日各聯賽休兵"

        opened_count = sum(int(row.get("taiwan_market_count") or row.get("game_count") or 0) for row in radar_summary)
        data_source = "台灣運彩開盤快照／本站 Radar 摘要"
        text = (
            "☀️ 【每日 Radar 摘要】\n"
            f"今日已開盤場次：{opened_count}\n聯賽：{leagues_str}\n"
            f"資料來源：{data_source}\n來源狀態：{source_status or '未提供'}\n資料時間：{observed}\n"
            "此為開盤狀態摘要，不代表推薦或獲利保證。"
        )
        key = datetime.now(timezone.utc).date().isoformat()
        return self._dispatch_notification("morning_radar", key, text, system_tab="radar")

    def _generate_qr_for_combo(
        self,
        combo: Dict[str, Any],
        stake: float = 100.0,
    ) -> Dict[str, Any]:
        """Format a manual slip; the local TSL3 QR encoding is not official/verified."""
        legs = combo.get("legs", []) if isinstance(combo.get("legs"), list) else []
        parlay_name = str(combo.get("parlay_name") or f"{len(legs)} 串 1")
        try:
            total_odds = float(combo.get("total_odds_exact", combo.get("total_odds", 0)) or 0)
        except (TypeError, ValueError, OverflowError):
            total_odds = 0.0
        try:
            stake_value = max(0.0, float(stake))
        except (TypeError, ValueError, OverflowError):
            stake_value = 0.0

        lines = [
            "📋 【投注單明細（人工核對用）】",
            f"組合：{parlay_name}｜顯示總賠率：{total_odds:.2f}x｜注金參考：NT$ {stake_value:,.0f}",
            "本功能只整理本站資料，不是台灣運彩官方投注 QR，也不能直接出票。請在官方投注頁核對即時盤口、玩法與注金。",
        ]
        for index, leg in enumerate(legs, 1):
            if not isinstance(leg, dict):
                continue
            event_id = leg.get("event_id") or leg.get("canonical_event_id") or "未知"
            league = str(leg.get("display_league") or leg.get("league") or "聯賽未知")
            matchup = f"{leg.get('away_team') or '客隊未知'} vs {leg.get('home_team') or '主隊未知'}"
            market = str(leg.get("market") or leg.get("market_type") or "玩法未知")
            selection = str(leg.get("selection") or "選項未知")
            line = leg.get("line")
            odds = leg.get("taiwan_odds", leg.get("odds"))
            try:
                odds_text = f"{float(odds):.2f}"
            except (TypeError, ValueError, OverflowError):
                odds_text = "未提供"
            line_text = f" {line}" if line not in (None, "") else ""
            lines.append(f"{index}. #{event_id} {league}｜{matchup}\n   {market}{line_text}｜{selection} @ {odds_text}")
        lines.append(f"台灣運彩官方投注頁：{TAIWAN_LOTTERY_URL}")
        return {"text": "\n".join(lines), "image_url": None, "official_qr_verified": False}

    def notify_ticket_qr(
        self,
        combo: Dict[str, Any],
        stake: float = 100.0,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a manual slip; never imply this local payload is an official ticket QR."""
        qr_data = self._generate_qr_for_combo(combo, stake)
        return self.send_push_message(
            text=qr_data["text"],
            user_id=user_id,
            flex_message=build_manual_slip_flex(qr_data["text"]),
        )

    @staticmethod
    def format_parlay_leg(leg: Dict[str, Any], idx: int) -> str:
        """Format a betting selection with sport icon, clean Chinese league, matchup, kickoff time, and market."""
        sport = str(leg.get("sport") or "").lower().strip()
        raw_league = str(leg.get("league") or "").strip()
        market = str(leg.get("market") or "").strip()
        selection = str(leg.get("selection") or "").strip()
        # Clean redundant trailing odds inside selection text (e.g. "大 2.5分 (1.68)" -> "大 2.5分")
        clean_selection = re.sub(r"\s*\(\d+(?:\.\d+)?\)\s*$", "", selection).strip() or selection
        odds = float(leg.get("taiwan_odds") or 1.0)
        line = leg.get("line")
        away = str(leg.get("away_team") or "客隊").strip()
        home = str(leg.get("home_team") or "主隊").strip()
        start_time = leg.get("start_time_utc") or leg.get("start_time")

        # 1. Sport Icon & League Normalization
        SPORT_ICONS = {
            "baseball": "⚾",
            "basketball": "🏀",
            "soccer": "⚽",
            "football": "🏈",
            "hockey": "🏒",
            "tennis": "🎾",
        }

        LEAGUE_CHINESE_MAP = {
            "mlb": ("⚾", "MLB (美國職棒)"),
            "nba": ("🏀", "NBA (美國職籃)"),
            "wnba": ("🏀", "WNBA (女子職籃)"),
            "cpbl": ("⚾", "CPBL (中華職棒)"),
            "npb": ("⚾", "NPB (日本職棒)"),
            "kbo": ("⚾", "KBO (韓國職棒)"),
            "nfl": ("🏈", "NFL (美式足球)"),
            "nhl": ("🏒", "NHL (北美冰球)"),
            "premier": ("⚽", "英超 (英格蘭超級聯賽)"),
            "premier_league": ("⚽", "英超 (英格蘭超級聯賽)"),
            "epl": ("⚽", "英超 (英格蘭超級聯賽)"),
            "laliga": ("⚽", "西甲 (西班牙甲級聯賽)"),
            "serie_a": ("⚽", "義甲 (義大利甲級聯賽)"),
            "bundesliga": ("⚽", "德甲 (德國甲級聯賽)"),
            "ligue_1": ("⚽", "法甲 (法國甲級聯賽)"),
            "mls": ("⚽", "MLS (美國足球大聯盟)"),
            "columbia_primera_a": ("⚽", "哥倫比亞甲級足球聯賽"),
            "colombia_primera_a": ("⚽", "哥倫比亞甲級足球聯賽"),
            "costa_rica_primera": ("⚽", "哥斯大黎加甲級足球聯賽"),
            "afc_champions_league": ("⚽", "亞冠足球聯賽"),
            "champions_league": ("⚽", "歐冠足球聯賽"),
            "europa_league": ("⚽", "歐霸足球盃"),
            "j_league": ("⚽", "J聯盟 (日本職業足球)"),
            "k_league": ("⚽", "K聯盟 (韓國職業足球)"),
            "cpbl_(中職)": ("⚾", "CPBL (中華職棒)"),
            "npb_(日棒)": ("⚾", "NPB (日本職棒)"),
            "kbo_(韓棒)": ("⚾", "KBO (韓國職棒)"),
            "足球": ("⚽", "焦點足球賽事"),
        }

        norm_league = raw_league.lower().replace(" ", "_").replace("-", "_")
        # Strip generic "unknown_" prefix if present
        clean_raw = re.sub(r"^unknown_", "", raw_league, flags=re.IGNORECASE).strip()
        clean_norm = re.sub(r"^unknown_", "", norm_league, flags=re.IGNORECASE).strip()

        if norm_league in LEAGUE_CHINESE_MAP:
            icon, league_name = LEAGUE_CHINESE_MAP[norm_league]
        elif clean_norm in LEAGUE_CHINESE_MAP:
            icon, league_name = LEAGUE_CHINESE_MAP[clean_norm]
        elif clean_raw and clean_raw.lower() not in ("unknown", "soccer", "baseball", "basketball", "football", ""):
            icon = SPORT_ICONS.get(sport, "🎯")
            league_name = clean_raw
        else:
            # Fallback for generic/unknown
            icon = SPORT_ICONS.get(sport, "🎯")
            if sport == "soccer":
                league_name = "國際足球錦標賽"
            elif sport == "baseball":
                league_name = "職業棒球賽事"
            elif sport == "basketball":
                league_name = "職業籃球賽事"
            elif sport == "football":
                league_name = "美式足球賽事"
            elif sport == "hockey":
                league_name = "職業冰球賽事"
            else:
                league_name = "精選賽事"

        # 2. Matchup Formatting
        matchup = f"{away} vs {home}"

        # 3. Kickoff Time Formatting (convert UTC to Taipei Time)
        time_str = ""
        if start_time:
            try:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                clean_ts = str(start_time).replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_ts)
                taipei_tz = ZoneInfo("Asia/Taipei")
                dt_loc = dt.astimezone(taipei_tz) if dt.tzinfo else dt
                time_str = f" ⏰ {dt_loc.strftime('%m/%d %H:%M')}"
            except Exception:
                if len(str(start_time)) <= 16:
                    time_str = f" ⏰ {start_time}"

        # 4. Market & Selection Formatting
        if market == "讓分":
            line_part = f" [{line}]" if line else ""
            market_str = f"讓分盤{line_part} ➔ 【{clean_selection}】({odds:.2f}x)"
        elif market == "大小":
            line_part = f" [{line}]" if line else ""
            market_str = f"大小分{line_part} ➔ 【{clean_selection}】({odds:.2f}x)"
        elif market == "不讓分":
            market_str = f"不讓分 ➔ 【{clean_selection}】({odds:.2f}x)"
        elif market:
            line_part = f" [{line}]" if line else ""
            market_str = f"{market}{line_part} ➔ 【{clean_selection}】({odds:.2f}x)"
        else:
            market_str = f"【{clean_selection}】({odds:.2f}x)"

        # 5. Display only qualified market evidence; ticket-share data does not
        # establish where large cash flows are going.
        market_intel_notes = []
        evidence = leg.get("signal_evidence") or {}
        is_market_synth = bool(evidence.get("is_market_synthetic") or evidence.get("is_synthetic"))

        sharp_p = evidence.get("sharp_fair_probability")
        sharp_ev = evidence.get("sharp_expected_value_pct")
        sharp_qualified = (
            str(evidence.get("market_source_qualification") or "").upper() == "SHARP_QUALIFIED"
            and str(evidence.get("market_benchmark_status") or "").upper() == "AVAILABLE"
            and not is_market_synth
        )

        if is_market_synth:
            # Synthetic fixtures must NEVER be presented as verified +EV in recommendations
            synth_p = evidence.get("synthetic_fair_probability")
            if synth_p:
                market_intel_notes.append(f"   🌐 國際參考盤口: 模擬樣本 {synth_p * 100:.1f}% (測試展示，非真實優勢)")
        elif sharp_qualified and sharp_p is not None:
            ev_str = f" · Sharp EV {float(sharp_ev):+.1f}%" if isinstance(sharp_ev, (int, float)) else ""
            market_intel_notes.append(f"   🌐 Sharp 市場估計: {float(sharp_p) * 100:.1f}%{ev_str}")

        market_fair = evidence.get("market_fair_probability")
        if not is_market_synth and isinstance(market_fair, (int, float)) and 0 < market_fair < 1:
            market_method = str(evidence.get("market_fair_method") or "台彩市場估計").replace("_", " ")
            market_intel_notes.append(f"   📊 {market_method}: {market_fair * 100:.1f}%")

        model_status = str(evidence.get("probability_status") or "").upper()
        if model_status in {"UNVALIDATED_MODEL_ESTIMATE", "UNVALIDATED_MODEL_FUSION_ESTIMATE"}:
            market_intel_notes.append("   🧪 模型候選未驗收，不作正式模型推薦依據")
        elif model_status == "CALIBRATED_MODEL_ESTIMATE" and evidence.get("model_accepted_ids"):
            market_intel_notes.append("   🧪 使用已驗收模型輸入；串關機率仍未驗證")

        extra_text = ("\n" + "\n".join(market_intel_notes)) if market_intel_notes else ""

        return (
            f"{idx}. {icon} [{league_name}]\n"
            f"   {matchup}{time_str}\n"
            f"   🎯 {market_str}{extra_text}"
        )

    @staticmethod
    def get_menu_text() -> str:
        """Full interactive menu formatted for mobile LINE chat."""
        return (
            "Sportslottery LINE 主選單｜手機快捷助手\n"
            "🎯 智慧串關｜輸入目標倍率查詢主系統合格候選\n"
            "🛡️ Banker 穩健精選｜使用主系統正式 Banker 條件\n"
            "☀️ 今日賽事｜查看開盤與來源狀態\n"
            "💰 資產戰績｜僅限已綁定 Profile\n"
            "🔔 通知設定｜調整已綁定 Profile 的個別偏好\n"
            "👤 個人設定｜帳號、安全與完整操作在主系統完成\n"
            "投注單明細僅供人工核對；目前沒有驗證台灣運彩官方 QR 出票格式。所有機率、EV 與對沖資料均為估計，不保證結果。"
        )

    def handle_user_message(
        self,
        user_text: str,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        wallet_mgr: Optional[Any] = None,
        line_user_id: Optional[str] = None,
        search_state: Optional[Any] = None,
    ) -> str:
        """Process inbound text commands from LINE (e.g. '20倍', '功能表', '查戰績', '今日開盤', '對沖')."""
        import re
        search_state = search_state or self
        cmd = user_text.strip().lower()
        if not cmd:
            return self.get_menu_text()

        # 1. Greetings & Menu Triggers
        menu_triggers = [
            "功能表", "選單", "menu", "help", "說明", "指令", "你好", "您好", "哈囉",
            "hello", "hi", "嗨", "開始", "start", "安安", "?", "？", "怎麼用", "功能指南"
        ]
        if any(cmd == t for t in menu_triggers):
            return self.get_menu_text()

        # 1.1 Banker Mode / High Win Rate (保底/穩健)
        if any(k in cmd for k in ["高勝率", "保底", "穩健", "銀行家", "banker"]):
            return self._search_parlay_for_bot(3.75, parlay_engine, available_legs, sport_filter="banker", search_state=search_state)

        if cmd.startswith("通知"):
            return self._handle_notification_command(user_text, line_user_id)

        # 1.15 Next Combo / Alternative Parlay (換一組推薦)
        if any(k in cmd for k in ["換一組", "另一組", "換一張", "下一組", "換", "next", "reroll", "再一組"]):
            return self._get_next_parlay_candidate(parlay_engine, available_legs, search_state=search_state)

        # 1.2 Profile & Personal Settings (Interactive in-LINE + Public HTTPS Web Link)
        profile_reply = self._handle_profile_commands(user_text, line_user_id=line_user_id)
        if profile_reply:
            return profile_reply

        # 1.3 Multiplier Selection Menu (智慧串關選倍率)
        if any(cmd == k or k in cmd for k in ["智慧串關", "選倍率", "串關"]):
            return (
                "🎯 智慧串關使用主系統相同的合格條件與估值。請輸入目標倍率，例如「10倍」、「20倍」或「30倍」；若沒有合格候選，系統會說明原因，不會放寬條件湊單。\n"
                "Banker 請選擇「Banker 穩健精選」，使用主系統正式 Banker 篩選與排序。"
            )

        # 2. Match Target Multiplier: e.g. "20", "20倍", "20x", "50倍", "100"
        mult_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:倍|x|X)?", cmd)
        if mult_match and ("倍" in cmd or "x" in cmd or cmd.isdigit() or "串" in cmd):
            target_mult = float(mult_match.group(1))
            if 1.5 <= target_mult <= 1000:
                sport_filter = None
                if any(w in cmd for w in ["足球", "soccer"]):
                    sport_filter = "soccer"
                elif any(w in cmd for w in ["棒球", "baseball"]):
                    sport_filter = "baseball"
                elif re.search(r"\bnba\b", cmd):
                    sport_filter = "nba"
                elif any(w in cmd for w in ["籃球", "basketball"]):
                    sport_filter = "basketball"
                elif any(w in cmd for w in ["美足", "football", "nfl"]):
                    sport_filter = "football"
                return self._search_parlay_for_bot(
                    target_mult, parlay_engine, available_legs,
                    sport_filter=sport_filter, search_state=search_state,
                )

        # 3. Wallet & Staking Performance: e.g. "戰績", "錢包", "餘額", "本週"
        if any(k in cmd for k in ["戰績", "錢包", "餘額", "本金", "獲利", "本週"]):
            return self._get_wallet_status_text(wallet_mgr, line_user_id=line_user_id)

        # 4. Season Radar / Daily Matchups: e.g. "雷達", "開盤", "今天", "賽程"
        if any(k in cmd for k in ["雷達", "開盤", "今天", "賽程", "賽事"]):
            return self._get_radar_status_text()

        # 5. Hedging / Breakeven Queries: e.g. "對沖", "對衝", "聽牌", "鎖利", "保本"
        if any(k in cmd for k in ["對沖", "對衝", "聽牌", "鎖利", "保本"]):
            return self._get_hedging_status_text(line_user_id)

        # 6. QR Code Slip Generation: e.g. "qr", "產qr", "條碼", "投注單", "qrcode"
        if any(cmd == q or q in cmd for q in ["qr", "產qr", "條碼", "投注單", "qrcode", "出票", "劃單"]):
            return self._handle_qr_request(parlay_engine, available_legs, search_state=search_state)["text"]

        # 7. Fallback to Menu with Prompt
        if cmd in {"查看完整分析", "完整分析"}:
            return "完整串關分析需要 Sportslottery 正式 HTTPS 網址。請稍後重試，或從主系統的 Parlay 頁面查看。"
        return (
            "🐕 【瘋狗流 LINE 助手指令說明】\n"
            "---------------------------\n"
            f"收到指令：「{user_text}」\n"
            "未能辨識此關鍵字。您可以點擊下方快捷按鈕，或參考以下指令：\n\n"
            "• 發送「20倍」➔ 智慧搜尋 20 倍串關\n"
            "• 發送「投注單明細」➔ 整理本站選項供人工核對（本站 QR 未驗證為官方出票格式）\n"
            "• 發送「查戰績」➔ 查看每週額度與獲利\n"
            "• 發送「今日開盤」➔ 查看開盤聯賽與場次\n"
            "• 發送「對沖」➔ 查看本站 OPEN 注單與資料限制\n"
            "• 發送「功能表」➔ 查看完整功能說明"
        )

    def handle_user_message_full(
        self,
        user_text: str,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        wallet_mgr: Optional[Any] = None,
        line_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a text fallback, Flex card where available, and contextual Quick Replies."""
        with self.user_search_context(line_user_id) as search_state:
            return self._handle_user_message_full(
                user_text,
                parlay_engine=parlay_engine,
                available_legs=available_legs,
                wallet_mgr=wallet_mgr,
                line_user_id=line_user_id,
                search_state=search_state,
            )

    def _handle_user_message_full(
        self,
        user_text: str,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        wallet_mgr: Optional[Any] = None,
        line_user_id: Optional[str] = None,
        search_state: Optional[Any] = None,
    ) -> Dict[str, Any]:
        search_state = search_state or self
        cmd = user_text.strip().lower()
        is_next = any(k in cmd for k in ["換一組", "另一組", "換一張", "下一組", "換", "next", "reroll", "再一組"])
        previous_candidate = search_state.last_recommended_parlay

        # 1. QR Code Request
        if any(cmd == q or q in cmd for q in ["qr", "產qr", "條碼", "投注單", "qrcode", "出票", "劃單"]):
            qr_res = self._handle_qr_request(parlay_engine, available_legs, search_state=search_state)
            qr_res["quick_replies"] = [
                {"label": "🎲 換一組推薦", "text": "換一組"},
                {"label": "🎯 找20倍", "text": "20倍"},
                {"label": "🛡️ Banker 精選", "text": "Banker 穩健精選"},
                {"label": "🏠 回主選單", "text": "功能表"},
            ]
            qr_res["flex_message"] = build_manual_slip_flex(qr_res["text"])
            return qr_res

        # 2. Main Text Command Processing
        text_reply = self.handle_user_message(
            user_text,
            parlay_engine=parlay_engine,
            available_legs=available_legs,
            wallet_mgr=wallet_mgr,
            line_user_id=line_user_id,
            search_state=search_state,
        )

        # 3. Contextual Quick Reply Routing
        quick_replies = self.default_quick_replies()
        flex = None

        menu_triggers = ["功能表", "選單", "menu", "help", "說明", "指令", "你好", "您好", "哈囉", "hello", "hi", "嗨", "開始", "start", "安安", "?", "？", "怎麼用", "功能指南"]
        if any(cmd == trigger for trigger in menu_triggers):
            flex = build_menu_flex(self._runtime_system_url())

        elif "通知設定" in cmd or cmd.startswith("通知"):
            profile = self._get_bound_profile(line_user_id)
            if profile:
                flex = build_notification_flex(self.get_notification_preferences(str(profile["id"])))
            else:
                flex = build_status_flex("通知設定", "請先完成 Profile 綁定", [text_reply], system_url=self._runtime_system_url(), tab="profile")

        elif any(k in cmd for k in ["戰績", "錢包", "餘額", "本金", "獲利", "本週"]):
            snapshot = self._get_line_wallet_snapshot(line_user_id)
            if snapshot.get("profile"):
                flex = build_wallet_flex(snapshot["status"], snapshot["tickets"], system_url=self._runtime_system_url(), profile_id=str(snapshot["profile"]["id"]))
            else:
                flex = build_status_flex("資產戰績", "私人帳務僅限已綁定 Profile", [snapshot["text"]], system_url=self._runtime_system_url(), tab="profile")

        elif any(k in cmd for k in ["雷達", "開盤", "今天", "賽程", "賽事"]):
            radar = self._get_radar_snapshot()
            flex = build_radar_flex(radar, system_url=self._runtime_system_url()) if radar else build_status_flex("今日賽事", "資料服務暫時無法使用", [text_reply], system_url=self._runtime_system_url(), tab="radar")

        elif any(k in cmd for k in ["個人設定", "profile", "手機版", "決策台"]):
            flex = build_menu_flex(self._runtime_system_url())

        elif search_state.last_recommended_parlay and (not is_next or search_state.last_recommended_parlay is not previous_candidate) and (
            is_next or any(k in cmd for k in ["高勝率", "保底", "穩健", "銀行家", "banker"])
            or (("倍" in cmd or "x" in cmd or cmd.isdigit() or "串" in cmd) and re.search(r"\d", cmd))
        ):
            context = search_state.last_search_context or {}
            candidate = dict(search_state.last_recommended_parlay)
            candidate.setdefault("target_odds", context.get("target_mult"))
            flex = build_parlay_flex(candidate, system_url=self._runtime_system_url(), banker=context.get("mode") == "banker", index=search_state.last_candidate_index, count=len(search_state.last_parlay_candidates), search_complete=search_state.last_search_result.get("search_complete", True))

        # A. Multiplier Menu requested
        if any(cmd == k or k in cmd for k in ["智慧串關", "選倍率", "串關"]):
            quick_replies = self.multiplier_menu_quick_replies()

        # B. Parlay Search or Next Candidate triggered
        elif is_next or any(k in cmd for k in ["高勝率", "保底", "穩健", "銀行家", "banker"]) or (
            ("倍" in cmd or "x" in cmd or cmd.isdigit() or "串" in cmd) and re.search(r"\d", cmd)
        ):
            has_next = search_state.last_candidate_index + 1 < len(search_state.last_parlay_candidates)
            quick_replies = self.parlay_quick_replies(has_next=has_next)

        # C. Season Radar requested
        elif any(k in cmd for k in ["雷達", "開盤", "今天", "賽程", "賽事"]):
            quick_replies = self.radar_menu_quick_replies()

        # D. Wallet / Performance requested
        elif any(k in cmd for k in ["戰績", "錢包", "餘額", "本金", "獲利", "本週"]):
            quick_replies = self.wallet_menu_quick_replies()

        # E. Menu / Tools requested
        elif any(cmd == t for t in ["功能表", "選單", "menu", "help", "說明", "指令", "你好", "您好", "哈囉", "hello", "hi", "嗨", "開始", "start", "安安", "?", "？", "怎麼用", "功能指南"]):
            quick_replies = self.tools_menu_quick_replies()

        return {
            "text": text_reply,
            "image_url": None,
            "flex_message": flex,
            "quick_replies": quick_replies,
        }

    def _handle_notification_command(self, user_text: str, line_user_id: Optional[str]) -> str:
        """Update notification preferences only for the Profile bound to this LINE user."""
        profile = self._get_bound_profile(line_user_id)
        if not profile:
            return "通知偏好會存到已綁定 Profile。請先輸入「綁定請求 玩家名稱」，再於登入主系統的個人設定核准。"
        match = re.fullmatch(r"通知\s+(全部|賠率|結算|聽牌|Radar|雷達)\s+(開啟|關閉)", str(user_text or "").strip(), re.IGNORECASE)
        if not match:
            return "請使用通知設定圖卡按鈕，或輸入「通知 全部 開啟／關閉」。設定只套用到目前綁定的 Profile。"
        name, action = match.groups()
        value = action == "開啟"
        key_by_label = {"賠率": "steam_drop", "結算": "ticket_settlement", "聽牌": "hedging_alert", "Radar": "morning_radar", "雷達": "morning_radar"}
        updates = {key: value for key in LINE_PREFERENCE_KEYS} if name == "全部" else {key_by_label[name]: value}
        saved = self.update_notification_preferences(line_user_id, updates)
        if saved is None:
            return "無法更新通知偏好，請確認 LINE Profile 綁定狀態。"
        return f"已更新【{profile.get('name', '目前 Profile')}】的通知偏好。"

    def _handle_qr_request(
        self,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        search_state: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Return manual ticket details; no official Taiwan Lottery ticket QR is available."""
        search_state = search_state or self
        combo = search_state.last_recommended_parlay
        if not combo:
            # Trigger search to populate last_recommended_parlay if not yet present
            self._search_parlay_for_bot(20.0, parlay_engine, available_legs, search_state=search_state)
            combo = search_state.last_recommended_parlay

        if combo and combo.get("legs"):
            return self._generate_qr_for_combo(combo, stake=100.0)

        return {
            "text": (
                "📋 【投注單明細】\n"
                "目前尚未選定合格組合。請先查詢目標倍率後再查看明細。\n"
                "本站自製 QR 尚未驗證為台灣運彩官方格式，不能用於機台出票。"
                f"\n台灣運彩官方投注頁：{TAIWAN_LOTTERY_URL}"
            ),
            "image_url": None,
        }

    def _get_next_parlay_candidate(
        self,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        search_state: Optional[Any] = None,
    ) -> str:
        """Show the next distinct candidate without silently repeating results."""
        search_state = search_state or self
        if not search_state.last_parlay_candidates:
            return "目前沒有可切換的組合。請先選擇球種與目標倍率重新搜尋。"

        if search_state.last_candidate_index + 1 >= len(search_state.last_parlay_candidates):
            complete = (getattr(search_state, "last_search_result", {}) or {}).get("search_complete", True)
            detail = "本次搜尋尚未完成，可能還有其他組合。" if not complete else "目前搜尋結果已看完，沒有其他合格組合。"
            return f"{detail} 請調整倍率後重新搜尋。"

        search_state.last_candidate_index += 1
        next_combo = search_state.last_parlay_candidates[search_state.last_candidate_index]
        search_state.last_recommended_parlay = next_combo
        return self._format_line_parlay(next_combo, search_state.last_search_context, search_state.last_candidate_index, len(search_state.last_parlay_candidates))

    def _search_parlay_for_bot(
        self,
        target_mult: float,
        parlay_engine: Optional[Any] = None,
        available_legs: Optional[List[Any]] = None,
        sport_filter: Optional[str] = None,
        search_state: Optional[Any] = None,
    ) -> str:
        """Use the exact API search service and ranking that powers the React Parlay view."""
        search_state = search_state or self
        search_state.last_search_result = {}
        search_state.last_parlay_candidates = []
        search_state.last_candidate_index = 0
        search_state.last_recommended_parlay = None
        try:
            from core.scraper import ALLIANCE_MAP
            from server import service_registry
            from server.routers import parlay as parlay_api
            from server.schemas import ParlaySearchRequest

            banker = bool(sport_filter == "banker")
            alliances = None
            if sport_filter in {"soccer", "baseball", "basketball", "football", "nba"}:
                alliance_ids = {"soccer": ["4"], "baseball": ["1", "2", "6", "9"], "basketball": ["3", "7"], "nba": ["3"], "football": ["93"]}[sport_filter]
                alliances = [key for key in alliance_ids if key in ALLIANCE_MAP]
                if not alliances:
                    raise ValueError("Selected sport has no configured alliance")
            if banker:
                req = ParlaySearchRequest(
                    min_odds=1.5, max_odds=6.0, target_odds=3.75, tolerance=0.20,
                    min_legs=1, max_legs=3, alliances=None, signal_filter="value_only",
                    ranking_mode="WIN_PROBABILITY", exclude_traps=False, prefer_steam=True,
                    search_budget=60000,
                )
                context = {"mode": "banker", "target_mult": 3.75, "sport_filter": None}
            else:
                req = ParlaySearchRequest(
                    target_odds=float(target_mult), tolerance=0.20, min_legs=2, max_legs=5,
                    alliances=alliances, signal_filter="normal", ranking_mode="WIN_PROBABILITY",
                    exclude_traps=False, prefer_steam=True, search_budget=60000,
                )
                context = {"mode": "target", "target_mult": float(target_mult), "sport_filter": sport_filter}

            # A failed or busy search must never show a previous result as the new one.
            search_state.last_search_context = context

            if not parlay_api._parlay_search_capacity.acquire(blocking=False):
                return "主系統串關搜尋目前繁忙，請稍後再試。"
            slot_acquired = False
            try:
                if not parlay_api._parlay_search_slots.acquire(timeout=20):
                    return "主系統串關搜尋佇列目前已滿，請稍後再試。"
                slot_acquired = True
                result = parlay_api._execute_parlay_search(req)
            finally:
                if slot_acquired:
                    parlay_api._parlay_search_slots.release()
                parlay_api._parlay_search_capacity.release()
            search_state.last_search_context = context
            search_state.last_search_result = result
            candidates = []
            seen = set()
            for tier in ("high_consensus", "aggressive", "moonshot"):
                for candidate in result.get("tiers", {}).get(tier, []):
                    if sport_filter not in (None, "banker") and not self._matches_line_sport(candidate, sport_filter):
                        continue
                    key = candidate.get("candidate_id") or candidate.get("parlay_id")
                    if key and key in seen:
                        continue
                    if key:
                        seen.add(key)
                    candidates.append(candidate)
            search_state.last_parlay_candidates = candidates
            search_state.last_candidate_index = 0
            if not candidates:
                search_state.last_recommended_parlay = None
                diagnostic = result.get("diagnostics") or {}
                reason_counts = diagnostic.get("excluded_option_reasons") or {}
                reason_summary = "、".join(f"{key}: {value}" for key, value in list(reason_counts.items())[:3])
                try:
                    source = self._summarize_source_status(service_registry.get_services()[0].get_source_status())
                except Exception:
                    source = "使用主系統台灣運彩來源；來源狀態未提供"
                if banker:
                    headline = "Banker 正式條件（1.5–6.0 倍、1–3 關）目前沒有合格候選。"
                else:
                    scope = {"nba": "NBA ", "soccer": "足球 ", "basketball": "籃球 ", "baseball": "棒球 ", "football": "美式足球 "}.get(sport_filter, "")
                    headline = f"{scope}目標 {float(target_mult):.1f} 倍目前沒有符合主系統資格的候選。"
                return f"{headline}\n資料狀態：{source}。搜尋完成：{bool(result.get('search_complete', True))}。" + (f"\n主要排除原因：{reason_summary}。" if reason_summary else "") + "\n未放寬條件湊單；可調整目標倍率後重新搜尋。"

            search_state.last_recommended_parlay = candidates[0]
            return self._format_line_parlay(candidates[0], context, 0, len(candidates))
        except Exception as exc:
            search_state.last_parlay_candidates = []
            search_state.last_candidate_index = 0
            search_state.last_recommended_parlay = None
            logger.exception("Unified LINE parlay search failed")
            return "搜尋暫時無法完成，請稍後重試；未返回未驗證的候選。"

    @staticmethod
    def _matches_line_sport(candidate: Dict[str, Any], requested: str) -> bool:
        from core.identity.league_mapping import normalize_league_and_sport

        legs = candidate.get("legs") or []
        if not legs:
            return False
        for leg in legs:
            if not isinstance(leg, dict):
                return False
            league, inferred_sport = normalize_league_and_sport(str(leg.get("league") or ""))
            sport = str(leg.get("sport") or inferred_sport).lower().strip()
            if requested == "nba":
                if league != "NBA" or sport != "basketball":
                    return False
            elif sport != requested:
                return False
        return True

    @staticmethod
    def _format_line_parlay(candidate: Dict[str, Any], context: Dict[str, Any], index: int = 0, count: int = 1) -> str:
        legs = candidate.get("legs") or []
        odds = candidate.get("total_odds_exact", candidate.get("total_odds", 0))
        probability = candidate.get("joint_probability")
        probability_source = _parlay_probability_source(candidate)
        if candidate.get("has_sharp_benchmark"):
            try:
                sharp_probability = float(candidate.get("sharp_joint_probability"))
                if 0 < sharp_probability < 1:
                    probability = sharp_probability
            except (TypeError, ValueError, OverflowError):
                pass
        ev = candidate.get("parlay_ev_pct")
        ev_source = "未驗證估計 EV"
        if candidate.get("has_sharp_benchmark") and candidate.get("sharp_joint_probability") is not None:
            try:
                ev = (float(candidate["sharp_joint_probability"]) * float(odds) - 1) * 100
                ev_source = "Sharp 市場估計 EV"
            except (TypeError, ValueError, OverflowError):
                ev = None
        elif candidate.get("credible_value_basis"):
            ev_source = "合格來源估計 EV"
        freshness = sorted({str(leg.get("odds_scraped_at")) for leg in legs if isinstance(leg, dict) and leg.get("odds_scraped_at")})
        lines = [
            f"{'🛡️ Banker' if context.get('mode') == 'banker' else '🎯 智慧串關'}｜第 {index + 1}/{max(count, 1)} 組",
            f"關數：{len(legs)}｜總倍率：{float(odds or 0):.2f}x",
            f"組合機率：{float(probability) * 100:.1f}%" if probability is not None else "組合機率：來源不足",
            f"機率來源：{probability_source}",
            f"EV：{float(ev):+.1f}%｜來源：{ev_source}｜狀態：{candidate.get('credible_value_status') or 'UNVERIFIED'}" if ev is not None else "EV：未提供；不列為已驗證價值",
            f"相關性風險：{candidate.get('correlation_risk_grade') or '未提供'}",
            f"資料時間：{'；'.join(freshness) if freshness else '來源未提供抓取時間'}",
        ]
        lines.extend(LineNotifier.format_parlay_leg(leg, i) for i, leg in enumerate(legs, 1) if isinstance(leg, dict))
        lines.append("風險提示：機率與 EV 是估計值，會受盤口更新與串關相關性影響；不代表命中或獲利保證。")
        return "\n".join(lines)

    @staticmethod
    def _summarize_source_status(source_status: Any) -> str:
        if not isinstance(source_status, dict) or not source_status:
            return "來源狀態未提供"
        counts: Dict[str, int] = {}
        for item in source_status.values():
            state = str(item.get("source_status") or "UNKNOWN").upper() if isinstance(item, dict) else "UNKNOWN"
            counts[state] = counts.get(state, 0) + 1
        return "、".join(f"{state} {count} 個聯盟" for state, count in sorted(counts.items()))

    def _handle_profile_commands(self, user_text: str, line_user_id: Optional[str] = None) -> Optional[str]:
        """Expose only a main-system link and the authenticated binding approval flow."""
        clean_cmd = str(user_text or "").strip()
        lower = clean_cmd.lower()
        bind_match = re.fullmatch(r"(?:綁定請求|bind request)\s+(.{1,64})", clean_cmd, re.IGNORECASE)
        sensitive_cmd = re.match(
            r"^(?:綁定|bind|登入|login|解綁|解除綁定|unbind|改密碼|修改密碼|變更密碼|改pin|修改pin|切換|switch|新增玩家|建立玩家|新增|建立|create|修改預算|預算|限額)\b",
            clean_cmd,
            re.IGNORECASE,
        )
        is_profile_query = any(key in lower for key in ("個人設定", "profile", "帳號", "網頁", "決策台", "手機版", "忘記密碼", "忘記pin", "登入"))
        if not bind_match and not sensitive_cmd and not is_profile_query:
            return None

        if sensitive_cmd and not bind_match:
            return "帳號、PIN、預算與解綁操作請在 Sportslottery 主系統完成；LINE 不會接收或顯示 PIN、密碼或其他帳務資料。"

        if bind_match:
            result = self.request_line_binding(bind_match.group(1), line_user_id)
            if not result.get("success"):
                reasons = {
                    "PROFILE_NAME_REQUIRED": "請以「綁定請求 玩家名稱」提出綁定申請。",
                    "PROFILE_NOT_FOUND": "找不到此 Profile；請先在主系統確認帳號名稱。",
                    "LINE_ALREADY_BOUND": "此 LINE 帳號已綁定其他 Profile；請先登入原 Profile 在主系統解除。",
                    "PROFILE_SERVICE_UNAVAILABLE": "Profile 服務暫時無法使用，請稍後再試。",
                    "TOO_MANY_PENDING_REQUESTS": "此 Profile 暫有多筆待確認申請，請先於主系統處理後再試。",
                }
                return reasons.get(result.get("reason"), "目前無法建立綁定申請，請在主系統確認帳號狀態。")
            if result.get("already_bound"):
                return f"此 LINE 已綁定【{result.get('profile_name', '目前 Profile')}】。如需解除或更換，請在主系統個人設定操作。"
            repeated = "（此為先前尚未處理的申請）" if result.get("already_pending") else ""
            return (
                f"已建立【{result.get('profile_name', 'Profile')}】LINE 綁定申請{repeated}，有效 10 分鐘。\n"
                f"確認碼：{result.get('confirmation_code', '未提供')}。請登入同一 Profile 的 Sportslottery 主系統，核對相同確認碼後再核准。"
            )

        url = system_deep_link(self._runtime_system_url(), "profile")
        if url:
            return f"Sportslottery 個人設定與完整帳號管理：{url}\n未登入時請依主系統登入流程驗證。"
        return "目前未設定可用的正式 HTTPS 主系統網址。請稍後重試，或使用已部署的 Sportslottery HTTPS 網址登入。"

    def _get_wallet_status_text(self, wallet_mgr: Optional[Any] = None, line_user_id: Optional[str] = None) -> str:
        """Return a bound Profile's wallet summary; never fall back to the default Profile."""
        try:
            return self._get_line_wallet_snapshot(line_user_id)["text"]
        except Exception as exc:
            logger.error("Error reading bound LINE wallet: %s", exc)
            return "Wallet 服務暫時無法讀取，請稍後在主系統查看。"

    def _get_line_wallet_snapshot(self, line_user_id: Optional[str]) -> Dict[str, Any]:
        """Read wallet and recent tickets for exactly the Profile bound to this LINE user."""
        from server import service_registry

        profile = self._get_bound_profile(line_user_id)
        if not profile:
            return {
                "text": "此 LINE 尚未綁定 Profile，無法顯示私人 Wallet 或注單。請在 LINE 輸入「綁定請求 玩家名稱」，再於登入主系統的個人設定核准。",
                "profile": None,
                "status": None,
                "tickets": [],
            }
        profile_id = str(profile["id"])
        status = service_registry.get_wallet(profile_id=profile_id).get_status()
        all_tickets = service_registry.get_betting_service(profile_id=profile_id).list_tickets(limit=50, profile_id=profile_id)
        settled_tickets = [ticket for ticket in all_tickets if str(ticket.get("status") or "").upper() in {"WON", "LOST", "VOID"}][:2]
        open_tickets = [ticket for ticket in all_tickets if str(ticket.get("status") or "").upper() == "OPEN"][:1]
        tickets = settled_tickets + open_tickets
        status["profile_id"] = profile_id
        lines = [
            f"💰 【{profile.get('name', 'Profile')}｜資產戰績】",
            f"本週可用 NT$ {float(status.get('weekly_wallet_balance') or 0):,.0f}｜已記錄注金 NT$ {float(status.get('weekly_staked') or 0):,.0f}",
            f"獲利保留池 NT$ {float(status.get('prize_pool') or 0):,.0f}｜歷史淨利 NT$ {float(status.get('lifetime_net_profit') or 0):+,.0f}",
            "以下為 Sportslottery 本站記錄，不代表台灣運彩官方投注或派彩。",
        ]
        for ticket in tickets[:3]:
            try:
                stake = f"NT$ {float(ticket.get('stake') or 0):,.0f}"
            except (TypeError, ValueError, OverflowError):
                stake = "金額未提供"
            line = f"本站注單｜{ticket.get('sports_summary') or ticket.get('parlay_name') or '串關'}｜{ticket.get('status') or '狀態未知'}｜注金 {stake}"
            if str(ticket.get("status") or "").upper() in {"WON", "LOST", "VOID"}:
                try:
                    line += f"｜本站派彩 NT$ {float(ticket.get('actual_payout') or 0):,.0f}"
                except (TypeError, ValueError, OverflowError):
                    pass
                settled_at = ticket.get("settled_at") or ticket.get("updated_at")
                if settled_at:
                    line += f"｜本站結算時間 {settled_at}"
            lines.append(line)
        if not tickets:
            lines.append("目前沒有近期本站注單記錄。")
        return {"text": "\n".join(lines), "profile": profile, "status": status, "tickets": tickets}

    def _get_radar_snapshot(self) -> Optional[Dict[str, Any]]:
        """Use the same service objects and payload fields as the React Radar API."""
        try:
            from server import service_registry
            from core.scraper import ALLIANCE_MAP
            adapter, _, _, radar, _, _, _, _ = service_registry.get_services()
            legs = adapter.get_taiwan_legs(list(ALLIANCE_MAP))
            summary = radar.get_radar_summary(taiwan_legs=legs)
            source_status = adapter.get_source_status()
            observed_values = [
                str(item.get("observed_at"))
                for item in source_status.values()
                if isinstance(item, dict) and item.get("observed_at")
            ] if isinstance(source_status, dict) else []
            if not observed_values:
                observed_values = [
                    str(getattr(leg, "odds_scraped_at", ""))
                    for leg in legs
                    if getattr(leg, "odds_scraped_at", None)
                ]
            parsed_observed = []
            for value in observed_values:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is not None:
                        parsed_observed.append(parsed.astimezone(timezone.utc))
                except (TypeError, ValueError, OverflowError):
                    continue
            as_of = max(parsed_observed).isoformat() if parsed_observed else "來源時間未提供"
            return {
                "radar": summary,
                "total_legs": len(legs),
                "source_status": self._summarize_source_status(source_status),
                "as_of": as_of,
            }
        except Exception as exc:
            logger.error("Error reading radar: %s", exc)
            return None

    def _get_radar_status_text(self) -> str:
        snapshot = self._get_radar_snapshot()
        if not snapshot:
            return "今日賽事服務暫時無法使用，請稍後在主系統重試。"
        opened = [row for row in snapshot.get("radar", []) if int(row.get("taiwan_market_count") or 0) > 0]
        lines = [f"☀️ 今日台彩開盤摘要｜資料時間：{snapshot.get('as_of')}", f"來源狀態：{snapshot.get('source_status')}"]
        if not opened:
            lines.append("目前沒有確認已開盤的場次。")
        else:
            lines.extend(f"{row.get('icon') or '•'} {row.get('name')}｜{row.get('taiwan_market_count', 0)} 場" for row in opened[:8])
        return "\n".join(lines)

    def _get_hedging_status_text(self, line_user_id: Optional[str] = None) -> str:
        """Show only the bound Profile's open-ticket status and avoid assumed hedge prices."""
        try:
            profile = self._get_bound_profile(line_user_id)
            if not profile:
                return "此 LINE 尚未綁定 Profile，不能讀取私人注單或聽牌狀態。請先完成主系統綁定核准。"
            from server import service_registry
            open_tickets = service_registry.get_betting_service(profile_id=str(profile["id"])).list_tickets(
                status_filter="OPEN", limit=50, profile_id=str(profile["id"]),
            )
            if not open_tickets:
                return f"【{profile.get('name', 'Profile')}】目前沒有狀態為 OPEN 的本站注單。\n來源：Sportslottery 本站 Ticket 記錄。"
            return (
                f"【{profile.get('name', 'Profile')}｜聽牌／對沖提醒】\n"
                f"目前有 {len(open_tickets)} 筆本站 OPEN 注單。\n"
                "尚未取得可信即時對向盤口，因此此處不估算鎖利或保本注金。請在主系統核對注單與最新盤口。"
            )
        except Exception as exc:
            logger.error("Error reading hedging: %s", exc)
            return "聽牌／對沖狀態暫時無法讀取，請稍後在主系統查看。"
