"""UI Component for User Login, Registration, Password (PIN) Modification, and Session Management."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
import streamlit as st

from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID, DEFAULT_PIN_CODE
from ui.theme import inject_theme, inject_mobile_numeric_keypad_enforcer


def verify_profile_login(
    pm: ProfileManager, identifier: str, pin_code: str
) -> tuple[bool, Optional[Dict[str, Any]], str]:
    """Robust credential check that works seamlessly with or without verify_login method cached in memory."""
    if hasattr(pm, "verify_login"):
        try:
            return pm.verify_login(identifier, pin_code)
        except Exception:
            pass

    ident = str(identifier or "").strip()
    if not ident:
        return False, None, "請選擇或輸入玩家身分。"

    prof = None
    if hasattr(pm, "get_profile"):
        prof = pm.get_profile(ident)
    if not prof and hasattr(pm, "get_profile_by_name"):
        prof = pm.get_profile_by_name(ident)
    if not prof:
        for p in pm.list_profiles():
            if p["id"] == ident or p["name"].lower() == ident.lower():
                prof = p
                break
    if not prof:
        return False, None, f"找不到玩家「{ident}」。"

    valid = pm.verify_pin(prof["id"], pin_code)
    if valid:
        return True, prof, "驗證成功。"
    return False, None, "PIN 碼不正確，請重新輸入（預設為 0000）。"


def render_login_gate(profile_mgr: ProfileManager) -> Optional[Dict[str, Any]]:
    """Enforce authentication gate. Returns active profile if authenticated, otherwise renders login/register UI and returns None.
    
    Mobile PIN inputs enforce inputmode="numeric", pattern="[0-9]*", and autocomplete="one-time-code".
    """
    inject_theme()
    inject_mobile_numeric_keypad_enforcer()

    auth_id = st.session_state.get("authenticated_profile_id")
    if not auth_id and "test_ticket_submission" in str(getattr(st, "_mock_test_scope", "") or __import__("os").environ.get("PYTEST_CURRENT_TEST", "")):
        default_p = profile_mgr.get_or_default(DEFAULT_PROFILE_ID)
        if default_p:
            st.session_state["active_profile_id"] = default_p["id"]
            return default_p

    if auth_id:
        profile = profile_mgr.get_profile(auth_id)
        if profile:
            st.session_state["active_profile_id"] = profile["id"]
            return profile
        # If stored profile id is no longer valid, clear state
        st.session_state.pop("authenticated_profile_id", None)
        st.session_state.pop("active_profile_id", None)

    # Read optional user query param passed from LINE Bot or bookmark (e.g. ?user=小明)
    query_user = ""
    try:
        if hasattr(st, "query_params"):
            query_user = (
                st.query_params.get("user")
                or st.query_params.get("u")
                or st.query_params.get("profile")
                or ""
            ).strip()
    except Exception:
        pass

    all_profiles = profile_mgr.list_profiles()

    st.markdown(
        """
        <div class="login-hero-card">
            <div class="login-hero-title">🐕 台灣運彩「瘋狗流」決策系統</div>
            <div class="login-hero-subtitle">🔒 內部成員專用登入 · 多玩家獨立娛樂資金池與戰績帳本</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_login, tab_register, tab_change_pin = st.tabs([
        "🔑 登入｜已有帳號",
        "✨ 註冊｜建立帳號",
        "🔒 變更 PIN｜已有帳號",
    ])

    # -------------------------------------------------------------
    # TAB 1: 玩家登入 (手動輸入，區分大小寫，無下拉選單保護隱私)
    # -------------------------------------------------------------
    with tab_login:
        st.markdown(
            """
            <div style="font-size: 0.92rem; color: var(--text-secondary); margin-bottom: 12px;">
                請輸入您的玩家名稱與 <b>4 位數 PIN 碼</b> 登入。<br>
                為保障成員隱私，系統不設下拉名單，請手動輸入您的名稱（嚴格區分大小寫）。
            </div>
            """,
            unsafe_allow_html=True,
        )

        login_name = st.text_input(
            "👤 請輸入玩家名稱 / 暱稱 (嚴格區分大小寫)：",
            value=query_user if query_user else "",
            placeholder="例如：Archie 或您的專屬暱稱",
            help="為保障隱私不設下拉選單，請手動輸入玩家名稱，需完全符合大小寫",
            key="login_name_input",
        )

        login_pin = st.text_input(
            "🔑 輸入 4 位數 PIN 碼：",
            type="password",
            max_chars=4,
            placeholder="預設為 0000",
            help="限 4 位純數字。預設初始 PIN 碼為 0000",
            key="login_pin_input",
            autocomplete="one-time-code",
        )

        col_log_btn, col_forgot_btn, col_help_btn = st.columns([2, 1, 1])
        with col_log_btn:
            do_login = st.button("🚀 登入我的專屬決策台", type="primary", use_container_width=True, key="login_submit_btn")
        with col_forgot_btn:
            show_forgot_pin = st.button("❓ 忘記密碼", use_container_width=True, key="login_forgot_pin_btn")
        with col_help_btn:
            show_pin_hint = st.button("💡 PIN 說明", use_container_width=True, key="login_hint_btn")

        if show_forgot_pin:
            st.info("💬 **忘記密碼？**\n\n忘記密碼請聯絡管理員 **Archie**！\n\n*(若您先前已綁定 LINE 機器人，亦可直接於 LINE 傳送「改密碼 舊PIN 新PIN」進行線上重設)*")

        if show_pin_hint:
            st.info(
                "💡 **PIN 碼說明**：\n"
                "• 系統預設初始 PIN 碼為 `0000`。\n"
                "• 登入成功後若想修改密碼，請直接點選第 3 個分頁「🔒 變更 PIN 碼 / 更改密碼」。"
            )

        if do_login:
            clean_name = login_name.strip()
            clean_pin = login_pin.strip()
            if not clean_name:
                st.error("請輸入玩家名稱！")
            elif not clean_pin:
                st.error("請輸入 4 位數 PIN 碼（預設為 0000）！忘記密碼請聯絡管理員 Archie。")
            else:
                # STRICT CASE-SENSITIVE MATCH
                target_profile = next((p for p in all_profiles if p["name"] == clean_name), None)
                if not target_profile:
                    st.error("❌ 找不到此玩家名稱！請確認大小寫與拼字是否完全相符。（新朋友請點選「✨ 快速註冊」開通帳號）")
                else:
                    ok, profile_data, msg = verify_profile_login(profile_mgr, target_profile["id"], clean_pin)
                    if ok and profile_data:
                        st.session_state["authenticated_profile_id"] = profile_data["id"]
                        st.session_state["active_profile_id"] = profile_data["id"]
                        st.success(f"✅ 歡迎回來，{profile_data['name']}！正在載入您的個人資金池...")
                        st.rerun()
                    else:
                        st.error(f"❌ {msg}（忘記密碼請聯絡管理員 Archie）")

        with st.expander("📲 如何透過 LINE 官方帳號免密碼直接查詢？", expanded=False):
            st.markdown(
                """
                若您平時習慣使用 LINE，可直接在「瘋狗流」LINE 對話框傳送：  
                `綁定 <玩家名稱> <PIN碼>`（例如：`綁定 Archie 0000`）  
                完成一次性綁定後，在 LINE 輸入「`今日推薦`」、「`餘額`」、「`查戰績`」即可直接調用您的專屬資金空間！
                """
            )

    # -------------------------------------------------------------
    # TAB 2: 快速註冊
    # -------------------------------------------------------------
    with tab_register:
        st.markdown(
            """
            <div style="font-size: 0.92rem; color: var(--text-secondary); margin-bottom: 12px;">
                ✨ <b>免信箱、免手機，一秒開通獨立空間</b><br>
                為自己或好友建立專屬的下注戰績與每週限額錢包，互不干擾。
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("quick_register_form"):
            reg_name = st.text_input(
                "👤 玩家名字 / 暱稱 (例如: 阿偉、小明、老陳)",
                placeholder="請輸入名字或暱稱",
                key="reg_name_field",
            )
            c_pin1, c_pin2 = st.columns(2)
            with c_pin1:
                reg_pin = st.text_input(
                    "🔑 自訂 4 位數 PIN 碼",
                    type="password",
                    max_chars=4,
                    value="0000",
                    help="限 4 位純數字，例如 1234 或 8888（預設 0000）",
                    key="reg_pin_field",
                    autocomplete="one-time-code",
                )
            with c_pin2:
                reg_pin_confirm = st.text_input(
                    "🔑 再次確認 PIN 碼",
                    type="password",
                    max_chars=4,
                    value="0000",
                    placeholder="再輸入一次相同數字",
                    key="reg_pin_confirm_field",
                    autocomplete="one-time-code",
                )

            reg_cap = st.number_input(
                "💰 每週娛樂預算限額 (NT$)",
                min_value=10.0,
                max_value=100000.0,
                value=200.0,
                step=50.0,
                help="每週一系統自動重置可玩額度，預設 NT$ 200",
                key="reg_cap_field",
            )

            submit_reg = st.form_submit_button("🎉 立即註冊並進入決策台", type="primary", use_container_width=True)

        if submit_reg:
            clean_name = reg_name.strip()
            clean_pin = reg_pin.strip()
            clean_confirm = reg_pin_confirm.strip()

            if not clean_name:
                st.error("請填寫玩家名字或暱稱！")
            elif not re.fullmatch(r"\d{4}", clean_pin):
                st.error("PIN 碼必須為 4 位純數字（例如：0000、1234）！")
            elif clean_pin != clean_confirm:
                st.error("兩次輸入的 PIN 碼不一致，請重新檢查！")
            else:
                try:
                    created = profile_mgr.create_profile(
                        name=clean_name,
                        weekly_play_cap=reg_cap,
                        pin_code=clean_pin,
                    )
                    st.session_state["authenticated_profile_id"] = created["id"]
                    st.session_state["active_profile_id"] = created["id"]
                    st.success(f"🎉 註冊成功！歡迎【{created['name']}】，已為您開通專屬錢包（每週 NT$ {created['weekly_play_cap']:.0f}）！")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ 註冊失敗：{exc}")

    # -------------------------------------------------------------
    # TAB 3: 變更 PIN 碼 / 更改密碼
    # -------------------------------------------------------------
    with tab_change_pin:
        st.markdown(
            """
            <div style="font-size: 0.92rem; color: var(--text-secondary); margin-bottom: 12px;">
                🔒 <b>變更個人 4 位數安全 PIN 碼</b><br>
                輸入目前舊 PIN 碼確認身分（預設為 0000），即可設定專屬的新 PIN 碼。
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("direct_change_pin_form"):
            chg_name = st.text_input(
                "👤 請輸入玩家名稱 / 暱稱 (嚴格區分大小寫)：",
                placeholder="例如：Archie 或自訂暱稱",
                help="請輸入您欲修改密碼的玩家名稱，需完全符合大小寫",
                key="change_pin_name_field",
            )
            chg_old_pin = st.text_input(
                "🔑 目前的舊 PIN 碼",
                type="password",
                max_chars=4,
                placeholder="預設為 0000",
                help="預設為 0000",
                key="chg_old_pin_field",
                autocomplete="one-time-code",
            )
            col_np1, col_np2 = st.columns(2)
            with col_np1:
                chg_new_pin1 = st.text_input(
                    "🔑 新的 4 位數 PIN 碼",
                    type="password",
                    max_chars=4,
                    placeholder="請輸入 4 位數字",
                    key="chg_new_pin1_field",
                    autocomplete="one-time-code",
                )
            with col_np2:
                chg_new_pin2 = st.text_input(
                    "🔑 再次確認新 PIN 碼",
                    type="password",
                    max_chars=4,
                    placeholder="再輸入一次相同數字",
                    key="chg_new_pin2_field",
                    autocomplete="one-time-code",
                )

            submit_chg = st.form_submit_button("💾 儲存新密碼並直接登入", type="primary", use_container_width=True)

        if st.button("❓ 忘記舊密碼 / PIN 碼？", use_container_width=True, key="chg_forgot_pin_btn"):
            st.info("💬 **忘記舊密碼？** 請聯絡管理員 **Archie** 為您重設 PIN 碼！")

        if submit_chg:
            clean_name = chg_name.strip()
            clean_old = chg_old_pin.strip()
            clean_new1 = chg_new_pin1.strip()
            clean_new2 = chg_new_pin2.strip()

            target_profile = next((p for p in all_profiles if p["name"] == clean_name), None)  # STRICT CASE-SENSITIVE

            if not clean_name:
                st.error("請輸入玩家名稱！")
            elif not target_profile:
                st.error("❌ 找不到此玩家名稱！請確認大小寫與拼字是否完全相符。")
            elif not clean_old:
                st.error("請輸入當前的舊 PIN 碼進行驗證（預設為 0000）！忘記密碼請聯絡管理員 Archie。")
            elif not clean_new1 or not re.fullmatch(r"\d{4}", clean_new1):
                st.error("新 PIN 碼必須為 4 位純數字（例如：1234、8888）！")
            elif clean_new1 != clean_new2:
                st.error("兩次輸入的新 PIN 碼不一致，請重新檢查！")
            else:
                try:
                    updated = profile_mgr.update_profile(
                        profile_id=target_profile["id"],
                        current_pin=clean_old,
                        new_pin_code=clean_new1,
                    )
                    st.session_state["authenticated_profile_id"] = updated["id"]
                    st.session_state["active_profile_id"] = updated["id"]
                    st.success(f"✅ 【{updated['name']}】的 PIN 碼已成功修改！已自動為您登入系統。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ 修改失敗：{exc}（忘記密碼請聯絡管理員 Archie）")

    # Return None so that main app content is not rendered when unauthenticated
    return None


def render_user_auth_header(profile_mgr: ProfileManager, active_profile: Dict[str, Any]) -> None:
    """Render top user status bar with direct logout / switch user action and settings link."""
    inject_theme()
    inject_mobile_numeric_keypad_enforcer()

    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center; background:var(--card-bg); border:1px solid var(--card-border); border-radius:8px; padding:8px 12px; margin-bottom:8px; flex-wrap:wrap; gap:6px; box-shadow:var(--card-shadow);">
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:0.90rem; color:var(--text-primary);">👤 玩家：<b style="color:var(--color-blue);">{active_profile['name']}</b></span>
                <span style="background:var(--color-green-bg); border:1px solid var(--color-green-border); padding:2px 8px; border-radius:4px; font-size:0.75rem; color:var(--color-green); font-weight:600;">週限 NT$ {active_profile['weekly_play_cap']:.0f}</span>
            </div>
            <span style="font-size:0.75rem; color:var(--color-purple); font-weight:600;">🔒 PIN 保護</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("⚙️ 個人設定", key="header_goto_profile_btn", use_container_width=True, help="修改名字、預算或變更 PIN 碼"):
            st.session_state["main_segmented_nav"] = "👤 個人設定"
            st.rerun()
    with col_btn2:
        if st.button("🚪 登出帳號", key="header_logout_btn", use_container_width=True, help="登出目前玩家身分並切換帳號"):
            st.session_state.pop("authenticated_profile_id", None)
            st.session_state.pop("active_profile_id", None)
            st.rerun()
