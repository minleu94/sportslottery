from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from core.profile_manager import DEFAULT_PROFILE_ID
from server import service_registry
from server.auth import (
    SESSION_TTL_SECONDS,
    get_current_session_optional,
    require_active_admin_session,
    require_any_authenticated_session,
    session_manager,
    verify_profile_ownership,
)
from server.schemas import (
    AdminDeletePlayerRequest,
    AdminResetPinRequest,
    AdminUpdatePlayerRequest,
    ProfileLoginByNameRequest,
    ProfileLoginRequest,
    ProfileRegisterRequest,
    ProfileUpdateRequest,
)
from server.security import (
    get_client_ip,
    log_security_event,
    login_rate_limiter,
    registration_rate_limiter,
)

logger = logging.getLogger("server.api")

router = APIRouter()


def _include_legacy_session_token(request: Request) -> bool:
    """Preserve bearer-token responses unless a client explicitly selects cookie-only auth."""
    return request.headers.get("x-session-mode", "").strip().lower() != "cookie"



@router.get("/api/profiles")
def list_profiles(session: Optional[Dict[str, Any]] = Depends(get_current_session_optional)):
    """List profiles with privacy boundaries:
    - Admin session: receives all profiles (without PIN)
    - Regular user session: receives only their own profile
    - Unauthenticated: receives minimal public structure (id and name only for selector)
    """
    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    profiles = profile_mgr.list_profiles()

    if session and session.get("profile_id") == DEFAULT_PROFILE_ID:
        safe_profiles = []
        for p in profiles:
            p_dict = dict(p)
            p_dict.pop("pin_code", None)
            safe_profiles.append(p_dict)
        return {"profiles": safe_profiles}

    if session and session.get("profile_id"):
        my_prof = profile_mgr.get_profile(session["profile_id"])
        if my_prof:
            p_dict = dict(my_prof)
            p_dict.pop("pin_code", None)
            return {"profiles": [p_dict]}

    minimal_profiles = [{"id": p["id"], "name": p["name"]} for p in profiles]
    return {"profiles": minimal_profiles}


@router.get("/api/profiles/public_list")
def list_public_profiles():
    """Explicit public endpoint returning only minimal identifier & name for login dropdown."""
    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    profiles = profile_mgr.list_profiles()
    return {"profiles": [{"id": p["id"], "name": p["name"]} for p in profiles]}


@router.post("/api/profiles/login")
def profile_login(
    req: ProfileLoginByNameRequest,
    request: Request,
    response: Response,
):
    """Authenticate by player name or profile ID with rate limiting, lockout, and HttpOnly cookie."""
    ip = get_client_ip(request)
    ident = str(req.identifier or "").strip()
    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    target_profile = profile_mgr.get_profile(ident) or profile_mgr.get_profile_by_name(ident)
    rate_ident = str(target_profile.get("id")) if target_profile else ident

    # 1. Anti-brute-force check
    lock_rem = login_rate_limiter.check_rate_limit(rate_ident, ip)
    if lock_rem is not None:
        log_security_event("LOGIN_ATTEMPT_LOCKED", ident, ip, {"retry_after": lock_rem})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"【安全鎖定】登入嘗試過多，帳號或來源 IP 已暫時鎖定，請於 {lock_rem} 秒後再試。",
            headers={"Retry-After": str(lock_rem)},
        )

    success, profile, msg = profile_mgr.verify_login(ident, req.pin_code)

    if not success or not profile:
        fail_cnt, is_locked, lock_sec = login_rate_limiter.record_failure(rate_ident, ip)
        log_security_event("LOGIN_FAILED", ident, ip, {"fail_count": fail_cnt, "locked": is_locked})
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"【安全鎖定】登入連續失敗達 {fail_cnt} 次，帳號已鎖定，請於 {lock_sec} 秒後再試。",
                headers={"Retry-After": str(lock_sec)},
            )
        rem_attempts = max(0, login_rate_limiter.max_failures - fail_cnt)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{msg or '登入失敗，PIN 碼或帳號錯誤。'}（剩餘嘗試次數：{rem_attempts} 次）",
        )

    # Success: reset rate limiter
    login_rate_limiter.record_success(rate_ident, ip)
    log_security_event("LOGIN_SUCCESS", ident, ip, {"profile_id": profile["id"]})
    token = session_manager.create_session(profile)

    # Set secure HttpOnly Cookie
    is_secure = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https")
    response.set_cookie(
        key="auth_session_token",
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )

    # Check for default admin weak PIN
    is_admin = profile["id"] == DEFAULT_PROFILE_ID
    is_weak_pin = (str(req.pin_code).strip() == "0000")
    requires_pin_change = bool(is_admin and is_weak_pin)

    p_dict = dict(profile)
    p_dict.pop("pin_code", None)
    result = {
        "success": True,
        "profile": p_dict,
        "message": msg,
        "requires_pin_change": requires_pin_change,
        "warning": "【安全警告】管理員帳號目前使用預設弱 PIN 碼 (0000)，請立即修改為自訂安全密碼！" if requires_pin_change else None,
    }
    if _include_legacy_session_token(request):
        result["token"] = token
    return result


@router.post("/api/profiles/logout")
def profile_logout(
    response: Response,
    session: Dict[str, Any] = Depends(require_any_authenticated_session),
):
    session_manager.revoke_session(session.get("token"))
    response.delete_cookie(key="auth_session_token", path="/")
    return {"success": True, "message": "已成功登出。"}


@router.get("/api/auth/me")
def get_auth_me(
    request: Request,
    response: Response,
    session: Dict[str, Any] = Depends(require_any_authenticated_session),
):
    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    profile = profile_mgr.get_profile(session.get("profile_id"))
    if not profile:
        raise HTTPException(status_code=404, detail="找不到目前登入者的 Profile。")
    p_dict = dict(profile)
    p_dict.pop("pin_code", None)
    token = session.get("token")
    if token:
        is_secure = (request.url.scheme == "https") or (
            request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower() == "https"
        )
        response.set_cookie(
            key="auth_session_token",
            value=token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=is_secure,
            path="/",
        )
    public_session = dict(session)
    public_session.pop("token", None)
    return {"success": True, "profile": p_dict, "session": public_session}


@router.post("/api/profiles/register")
def profile_register(
    req: ProfileRegisterRequest,
    request: Request,
    response: Response,
):
    ip = get_client_ip(request)
    allowed, retry_after = registration_rate_limiter.check_and_record(ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="註冊次數過多，請稍後再試。",
            headers={"Retry-After": str(retry_after)},
        )
    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    try:
        new_prof = profile_mgr.create_profile(
            name=req.name,
            weekly_play_cap=req.weekly_play_cap,
            pin_code=req.pin_code,
        )
        token = session_manager.create_session(new_prof)
        is_secure = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https")
        response.set_cookie(
            key="auth_session_token",
            value=token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=is_secure,
            path="/",
        )
        p_dict = dict(new_prof)
        p_dict.pop("pin_code", None)
        result = {"success": True, "profile": p_dict}
        if _include_legacy_session_token(request):
            result["token"] = token
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/profiles/verify_pin")
def verify_profile_pin(
    req: ProfileLoginRequest,
    request: Request,
    response: Response,
):
    """Verify profile PIN with rate limiting and issue session with HttpOnly cookie."""
    ip = get_client_ip(request)
    ident = str(req.profile_id or "").strip()

    lock_rem = login_rate_limiter.check_rate_limit(ident, ip)
    if lock_rem is not None:
        log_security_event("VERIFY_PIN_LOCKED", ident, ip, {"retry_after": lock_rem})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"【安全鎖定】PIN 碼嘗試次數過多，帳號或IP已暫時鎖定，請於 {lock_rem} 秒後再試。",
            headers={"Retry-After": str(lock_rem)},
        )

    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    is_valid = profile_mgr.verify_pin(profile_id=req.profile_id, pin_code=req.pin_code)
    if not is_valid:
        fail_cnt, is_locked, lock_sec = login_rate_limiter.record_failure(ident, ip)
        log_security_event("VERIFY_PIN_FAILED", ident, ip, {"fail_count": fail_cnt, "locked": is_locked})
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"【安全鎖定】PIN 碼嘗試失敗達 {fail_cnt} 次，帳號已鎖定，請於 {lock_sec} 秒後再試。",
                headers={"Retry-After": str(lock_sec)},
            )
        rem_attempts = max(0, login_rate_limiter.max_failures - fail_cnt)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"PIN 碼錯誤。（剩餘嘗試次數：{rem_attempts} 次）",
        )

    login_rate_limiter.record_success(ident, ip)
    profile = profile_mgr.get_profile(req.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="找不到玩家 Profile。")

    log_security_event("VERIFY_PIN_SUCCESS", ident, ip, {"profile_id": profile["id"]})
    token = session_manager.create_session(profile)

    is_secure = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https")
    response.set_cookie(
        key="auth_session_token",
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )

    is_admin = profile["id"] == DEFAULT_PROFILE_ID
    is_weak_pin = (str(req.pin_code).strip() == "0000")
    requires_pin_change = bool(is_admin and is_weak_pin)

    p_dict = dict(profile)
    p_dict.pop("pin_code", None)
    result = {
        "success": True,
        "profile": p_dict,
        "requires_pin_change": requires_pin_change,
        "warning": "【安全警告】管理員帳號目前使用預設弱 PIN 碼 (0000)，請立即修改為自訂安全密碼！" if requires_pin_change else None,
    }
    if _include_legacy_session_token(request):
        result["token"] = token
    return result


@router.post("/api/profiles/update")
def update_profile(
    req: ProfileUpdateRequest,
    request: Request,
    response: Response,
    session: Dict[str, Any] = Depends(require_any_authenticated_session),
):
    verify_profile_ownership(req.profile_id, session)
    if session.get("must_change_password") and not req.new_pin:
        raise HTTPException(
            status_code=403,
            detail="【安全限制】管理員使用預設密碼 0000，必須設定新密碼（剛好 8 位純數字）。",
        )
    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    ip = get_client_ip(request)
    lock_rem = login_rate_limiter.check_rate_limit(req.profile_id, ip)
    if lock_rem is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"【安全鎖定】PIN 碼嘗試過多，請於 {lock_rem} 秒後再試。",
            headers={"Retry-After": str(lock_rem)},
        )
    is_valid = profile_mgr.verify_pin(profile_id=req.profile_id, pin_code=req.current_pin)
    if not is_valid:
        fail_cnt, is_locked, lock_sec = login_rate_limiter.record_failure(req.profile_id, ip)
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"【安全鎖定】PIN 碼嘗試過多，請於 {lock_sec} 秒後再試。",
                headers={"Retry-After": str(lock_sec)},
            )
        raise HTTPException(status_code=401, detail="目前 PIN 碼驗證失敗。")
    login_rate_limiter.record_success(req.profile_id, ip)

    try:
        updated = profile_mgr.update_profile(
            profile_id=req.profile_id,
            current_pin=req.current_pin,
            new_name=req.name,
            new_weekly_play_cap=req.weekly_play_cap,
            new_pin_code=req.new_pin,
        )

        p_dict = dict(updated)
        p_dict.pop("pin_code", None)

        # If PIN was updated, revoke all existing sessions for this profile across devices
        new_token = None
        if req.new_pin:
            session_manager.revoke_all_for_profile(req.profile_id)
            new_token = session_manager.create_session(updated)
            is_secure = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https")
            response.set_cookie(
                key="auth_session_token",
                value=new_token,
                max_age=SESSION_TTL_SECONDS,
                httponly=True,
                samesite="lax",
                secure=is_secure,
                path="/",
            )

        res = {"success": True, "profile": p_dict}
        if new_token:
            res["message"] = "PIN 碼已更新，其他裝置已強制登出。"
            if _include_legacy_session_token(request):
                res["token"] = new_token
        return res
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/admin/players_overview")
def get_admin_players_overview(
    admin_profile_id: str = Query("default"),
    session: Dict[str, Any] = Depends(require_active_admin_session),
):
    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    all_profs = profile_mgr.list_profiles()
    overview = []
    for p in all_profs:
        try:
            bs = service_registry.get_betting_service(profile_id=p["id"])
            ws = bs.get_wallet_status()
            bal = ws.get("weekly_wallet_balance", 0.0)
            staked = ws.get("weekly_staked", 0.0)
            prize = ws.get("prize_pool", 0.0)
            pnl = ws.get("lifetime_net_profit", 0.0)
            cap = p.get("weekly_play_cap", 200.0)
        except Exception:
            bal, staked, prize, pnl, cap = 0.0, 0.0, 0.0, 0.0, 200.0

        try:
            bs = service_registry.get_betting_service(profile_id=p["id"])
            t_list = bs.list_tickets(limit=100, profile_id=p["id"])
            active_cnt = sum(1 for t in t_list if t.get("status") == "OPEN")
            total_cnt = len(t_list)
        except Exception:
            active_cnt, total_cnt = 0, 0

        overview.append({
            "id": p["id"],
            "name": p["name"],
            "weekly_play_cap": cap,
            "weekly_wallet_balance": bal,
            "weekly_staked": staked,
            "prize_pool": prize,
            "lifetime_net_profit": pnl,
            "is_line_bound": bool(p.get("line_user_id")),
            "created_at": p.get("created_at", ""),
            "active_tickets_count": active_cnt,
            "total_tickets_count": total_cnt,
        })
    return {"players": overview, "total_players": len(overview)}


@router.delete("/api/admin/players/{profile_id}")
def admin_delete_player(
    profile_id: str,
    admin_pin: Optional[str] = None,
    delete_history: bool = Query(True, description="Whether to permanently delete the player's ticket and ledger history"),
    session: Dict[str, Any] = Depends(require_active_admin_session),
):
    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    profile = profile_mgr.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"找不到 ID 為 {profile_id} 的玩家。")
    if profile_id == DEFAULT_PROFILE_ID:
        raise HTTPException(status_code=400, detail="系統預設管理員帳號不可被刪除。")

    try:
        profile_mgr.admin_delete_profile(
            target_profile_id=profile_id,
            admin_pin=admin_pin,
            admin_profile_id=session.get("profile_id", "default"),
            delete_history=delete_history,
        )
        session_manager.revoke_all_for_profile(profile_id)
        return {
            "success": True,
            "message": f"已成功刪除玩家【{profile['name']}】的帳號與錢包。" + ("投注及帳本歷史已一併刪除。" if delete_history else "投注及帳本歷史已保留。"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/admin/players/delete")
def admin_delete_player_post(
    req: AdminDeletePlayerRequest,
    session: Dict[str, Any] = Depends(require_active_admin_session),
):
    return admin_delete_player(profile_id=req.profile_id, admin_pin=req.admin_pin, session=session)


@router.post("/api/admin/players/reset_pin")
def admin_reset_player_pin(
    req: AdminResetPinRequest,
    request: Request,
    session: Optional[Dict[str, Any]] = Depends(get_current_session_optional),
):
    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    if req.profile_id == DEFAULT_PROFILE_ID:
        raise HTTPException(
            status_code=400,
            detail="管理員 PIN 請由本人帳號設定流程變更。",
        )
    is_admin = bool(session and session.get("profile_id") == DEFAULT_PROFILE_ID)

    if is_admin:
        if session.get("must_change_password"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="【安全限制】管理員使用預設密碼 0000，必須先變更為 8 位純數字密碼方可操作管理功能。",
            )
    else:
        ip = get_client_ip(request)
        lock_rem = login_rate_limiter.check_rate_limit(DEFAULT_PROFILE_ID, ip)
        if lock_rem is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"【安全鎖定】管理員 PIN 嘗試過多，請於 {lock_rem} 秒後再試。",
                headers={"Retry-After": str(lock_rem)},
            )
        # If not authenticated as admin via session, verify admin_pin against Archie (default profile)
        if session and not req.admin_pin:
            raise HTTPException(status_code=403, detail="【權限不足】僅系統管理者可重設玩家 PIN 碼。")
        if not req.admin_pin:
            raise HTTPException(status_code=401, detail="【需要管理員授權】請輸入管理員 Archie 的密碼以執行重設。")
        if profile_mgr.is_default_admin_pin():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="【安全限制】管理員使用預設密碼 0000，必須先登入變更為 8 位純數字密碼方可授權重設。",
            )
        if not profile_mgr.verify_pin(DEFAULT_PROFILE_ID, req.admin_pin):
            fail_cnt, is_locked, lock_sec = login_rate_limiter.record_failure(DEFAULT_PROFILE_ID, ip)
            if is_locked:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"【安全鎖定】管理員 PIN 嘗試過多，請於 {lock_sec} 秒後再試。",
                    headers={"Retry-After": str(lock_sec)},
                )
            raise HTTPException(status_code=401, detail="【管理員密碼驗證失敗】輸入的管理員密碼不正確。")
        login_rate_limiter.record_success(DEFAULT_PROFILE_ID, ip)

    try:
        updated = profile_mgr.admin_reset_pin(
            target_profile_id=req.profile_id,
            new_pin_code=req.new_pin,
        )
        session_manager.revoke_all_for_profile(req.profile_id)
        p_dict = dict(updated)
        p_dict.pop("pin_code", None)
        return {
            "success": True,
            "profile": p_dict,
            "message": f"已成功將【{updated['name']}】的 PIN 碼重設為 {req.new_pin}！已強制登出該帳號所有作用中 Session。",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/admin/players/update")
def admin_update_player_settings(
    req: AdminUpdatePlayerRequest,
    session: Dict[str, Any] = Depends(require_active_admin_session),
):
    _, _, _, _, profile_mgr, _, _, _ = service_registry.get_services()
    try:
        updated = profile_mgr.admin_update_player(
            target_profile_id=req.profile_id,
            new_name=req.name,
            new_weekly_play_cap=req.weekly_play_cap,
            new_pin_code=req.new_pin,
            admin_pin=req.admin_pin,
            admin_profile_id=session.get("profile_id", "default"),
        )
        p_dict = dict(updated)
        p_dict.pop("pin_code", None)
        return {
            "success": True,
            "profile": p_dict,
            "message": f"已成功更新玩家【{updated['name']}】的管理設定！",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
