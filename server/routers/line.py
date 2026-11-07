from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response

from core.line_notifier import LineNotifier
from core.line_flex import build_menu_flex
from server import service_registry
from server.auth import require_authenticated_session, verify_profile_ownership

logger = logging.getLogger("server.api")


class _LazyLineNotifier:
    """Defer reading local LINE credentials until an endpoint needs them."""

    def __init__(self) -> None:
        self._instance: Optional[LineNotifier] = None
        self._lock = threading.Lock()

    def _get_instance(self) -> LineNotifier:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = LineNotifier()
        return self._instance

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_instance(), name)


_line_notifier = _LazyLineNotifier()

router = APIRouter()


@router.get("/api/line/status")
async def line_service_status():
    return {"status": "online", "service": "sportslottery-line-bot", "configured": _line_notifier.is_configured()}


def _authenticated_profile(session: Dict[str, Any]) -> tuple[str, Any]:
    profile_id = str(session.get("profile_id") or "").strip()
    if not profile_id:
        raise HTTPException(status_code=401, detail="請先登入 Sportslottery 主系統。")
    verify_profile_ownership(profile_id, session)
    profile = service_registry.get_services().profile_mgr.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="找不到目前登入的 Profile。")
    return profile_id, profile


@router.get("/api/line/preferences")
def get_line_preferences(session: Dict[str, Any] = Depends(require_authenticated_session)):
    profile_id, profile = _authenticated_profile(session)
    return {"bound": bool(profile.get("line_user_id")), "preferences": _line_notifier.get_notification_preferences(profile_id)}


@router.put("/api/line/preferences")
async def put_line_preferences(request: Request, session: Dict[str, Any] = Depends(require_authenticated_session)):
    profile_id, profile = _authenticated_profile(session)
    if not profile.get("line_user_id"):
        raise HTTPException(status_code=409, detail="請先完成 LINE Profile 綁定。")
    declared_length = request.headers.get("content-length")
    try:
        if declared_length is not None and int(declared_length) > MAX_LINE_PREFERENCES_BODY_BYTES:
            raise HTTPException(status_code=413, detail="LINE notification preferences payload is too large.")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_LINE_PREFERENCES_BODY_BYTES:
            raise HTTPException(status_code=413, detail="LINE notification preferences payload is too large.")
        body.extend(chunk)
    try:
        payload = json.loads(bytes(body))
    except Exception:
        raise HTTPException(status_code=400, detail="無效的通知偏好資料。")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="通知偏好必須是物件。")
    valid_keys = {"steam_drop", "ticket_settlement", "hedging_alert", "morning_radar"}
    if any(key not in valid_keys or not isinstance(value, bool) for key, value in payload.items()):
        raise HTTPException(status_code=422, detail="通知偏好包含未知欄位或非布林值。")
    saved = _line_notifier.update_notification_preferences(str(profile["line_user_id"]), payload)
    return {"bound": True, "preferences": saved or _line_notifier.get_notification_preferences(profile_id)}


@router.get("/api/line/binding-requests")
def get_line_binding_requests(session: Dict[str, Any] = Depends(require_authenticated_session)):
    profile_id, _ = _authenticated_profile(session)
    return {"requests": _line_notifier.list_line_binding_requests(profile_id)}


@router.post("/api/line/binding-requests/{request_id}/approve")
def approve_line_binding_request(request_id: str, session: Dict[str, Any] = Depends(require_authenticated_session)):
    profile_id, _ = _authenticated_profile(session)
    try:
        approved = _line_notifier.approve_line_binding_request(profile_id, request_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not approved:
        raise HTTPException(status_code=404, detail="綁定申請已不存在或逾時。")
    profile = service_registry.get_services().profile_mgr.get_profile(profile_id)
    return {"success": True, "bound": bool(profile and profile.get("line_user_id"))}


@router.post("/api/line/binding-requests/{request_id}/reject")
def reject_line_binding_request(request_id: str, session: Dict[str, Any] = Depends(require_authenticated_session)):
    profile_id, _ = _authenticated_profile(session)
    if not _line_notifier.reject_line_binding_request(profile_id, request_id):
        raise HTTPException(status_code=404, detail="綁定申請已不存在或逾時。")
    return {"success": True}


@router.delete("/api/line/binding")
def unbind_line_profile(session: Dict[str, Any] = Depends(require_authenticated_session)):
    profile_id, _ = _authenticated_profile(session)
    service_registry.get_services().profile_mgr.unbind_line_user_from_authenticated_session(profile_id)
    return {"success": True, "bound": False}
MAX_LINE_WEBHOOK_BODY_BYTES = 1024 * 1024
MAX_LINE_WEBHOOK_EVENTS = 100
MAX_LINE_PREFERENCES_BODY_BYTES = 16 * 1024



@router.post("/callback")
async def line_webhook_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: Optional[str] = Header(None, alias="X-Line-Signature"),
):
    """Webhook callback endpoint for LINE Messaging API with mandatory cryptographic signature verification."""
    declared_length = request.headers.get("content-length")
    try:
        if declared_length is not None and int(declared_length) > MAX_LINE_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="LINE webhook payload is too large.")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_LINE_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="LINE webhook payload is too large.")
        body.extend(chunk)
    body_bytes = bytes(body)
    secret = str(_line_notifier.config.get("channel_secret") or "").strip()
    is_test_mode = os.environ.get("ALLOW_INSECURE_LINE_WEBHOOK", "").lower() in ("1", "true", "yes")

    if not is_test_mode:
        if not secret:
            logger.warning("LINE webhook rejected: channel_secret is not configured on this server.")
            raise HTTPException(
                status_code=503,
                detail="LINE webhook service unavailable: channel_secret is not configured",
            )
        if not x_line_signature or not verify_line_signature(body_bytes, x_line_signature, secret):
            logger.warning("LINE webhook rejected: invalid or missing X-Line-Signature header.")
            raise HTTPException(status_code=400, detail="Invalid LINE webhook signature")
    else:
        if secret and x_line_signature and not verify_line_signature(body_bytes, x_line_signature, secret):
            raise HTTPException(status_code=400, detail="Invalid LINE webhook signature")
        logger.debug("LINE webhook running in test mode (ALLOW_INSECURE_LINE_WEBHOOK=true).")

    try:
        data = json.loads(body_bytes)
    except Exception:
        return Response(content="Invalid JSON", status_code=400)

    if not isinstance(data, dict) or not isinstance(data.get("events", []), list):
        return Response(content="Invalid webhook event list", status_code=400)
    events = data.get("events", [])
    if len(events) > MAX_LINE_WEBHOOK_EVENTS:
        raise HTTPException(status_code=413, detail="LINE webhook contains too many events.")
    if events:
        background_tasks.add_task(process_line_events, events)
    return {"status": "ok", "events_processed": len(events)}


def verify_line_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    """Validate X-Line-Signature against channel secret."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(expected).decode("utf-8")
    return hmac.compare_digest(expected_b64, signature)


def process_line_events(events: list[Dict[str, Any]]) -> None:
    """Process accepted LINE events asynchronously outside the webhook response path."""
    for ev in events:
        if not isinstance(ev, dict):
            logger.warning("Skipping malformed LINE webhook event")
            continue
        event_id = ev.get("webhookEventId")
        if event_id and not _line_notifier.claim_webhook_event(str(event_id)):
            logger.info("Ignoring duplicate LINE webhook event %s", str(event_id)[:10])
            continue
        early_reply = None
        user_id = None
        ev_type = None
        try:
            ev_type = ev.get("type")
            reply_token = ev.get("replyToken")
            source = ev.get("source", {})
            if not isinstance(source, dict):
                source = {}
            user_id = source.get("userId")

            if ev_type == "message":
                msg = ev.get("message", {})
                if msg.get("type") == "text":
                    user_text = str(msg.get("text", "")).strip()
                    if source.get("type") != "user" and _line_notifier.requires_private_line_chat(user_text):
                        if reply_token:
                            _line_notifier.reply_message(
                                reply_token=reply_token,
                                text="私人 Wallet、通知與帳號設定請在 LINE 官方帳號的一對一聊天使用。",
                            )
                        continue
                    if reply_token and user_id and _line_notifier.is_slow_parlay_search_request(user_text):
                        early_reply = _line_notifier.reply_message(
                            reply_token=reply_token,
                            text="🐕 收到，正在搜尋串關組合，完成後會接著傳送結果。",
                        )
                    full_res = _line_notifier.handle_user_message_full(user_text, line_user_id=user_id)
                    reply_text = full_res.get("text", "")
                    image_url = full_res.get("image_url")
                    flex_message = full_res.get("flex_message")
                    quick_replies = full_res.get("quick_replies") or _line_notifier.default_quick_replies()
                    if early_reply and early_reply.get("success"):
                        result = _line_notifier.send_push_message(
                            text=reply_text,
                            user_id=user_id,
                            image_url=image_url,
                            quick_replies=quick_replies,
                            flex_message=flex_message,
                        )
                        if not result.get("success"):
                            logger.warning("LINE parlay result push failed for user %s: %s", user_id[:8], result.get("error"))
                    elif reply_token:
                        _line_notifier.reply_message(
                            reply_token=reply_token,
                            text=reply_text,
                            quick_replies=quick_replies,
                            image_url=image_url,
                            flex_message=flex_message,
                        )

            elif ev_type == "follow":
                welcome_text = "歡迎使用 Sportslottery LINE 手機快捷助手。查詢與提醒使用主系統資料；私人 Wallet 需先綁定 Profile。完整帳號管理請前往主系統。"
                if reply_token:
                    _line_notifier.reply_message(
                        reply_token=reply_token,
                        text=welcome_text,
                        quick_replies=_line_notifier.default_quick_replies(),
                        flex_message=build_menu_flex(_line_notifier._runtime_system_url()),
                    )
        except Exception as exc:
            event_id = ev.get("webhookEventId")
            _line_notifier.release_webhook_event(str(event_id) if event_id else None)
            if early_reply and early_reply.get("success") and user_id:
                _line_notifier.send_push_message(
                    text="⚠️ 串關搜尋暫時發生問題，請稍後再試。",
                    user_id=user_id,
                    quick_replies=_line_notifier.default_quick_replies(),
                )
            logger.warning("[LINE_BOT_EVENT_ERROR] event_type=%s user_id=%s error=%s", ev_type, user_id, str(exc), exc_info=True)
