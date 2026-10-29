"""UI Component for Profile Management, PIN Authentication, and First-time Onboarding Guide."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
import streamlit as st

from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
from core.wallet import WeeklyWalletManager


def render_profile_view(
    profile_mgr: ProfileManager,
    current_profile_id: str,
    wallet_mgr: Optional[WeeklyWalletManager] = None,
) -> str:
    """Render the user profile dashboard and return the currently active profile_id."""
    active_id = current_profile_id or DEFAULT_PROFILE_ID
    profile = profile_mgr.get_or_default(active_id)
    if wallet_mgr is None:
        try:
            wallet_mgr = WeeklyWalletManager(profile_id=profile["id"])
        except TypeError:
            wallet_mgr = WeeklyWalletManager()
    if hasattr(wallet_mgr, "profile_id"):
        wallet_mgr.profile_id = profile["id"]
    wallet_status = wallet_mgr.get_status()

    st.markdown("### 👤 個人 Profile 與帳號設定中心")
    st.caption("每位玩家擁有獨立的每週娛樂限額、個人錢包、獲利保留儲備池與注單帳本。透過 4 位數 PIN 碼保障設定安全。")

    # 1. First-time Onboarding Guidance
    show_guide = st.session_state.get("show_onboarding_guide", False)
    with st.expander("🌟 使用設定指南與 PIN 碼說明 (點擊展開/收合說明)", expanded=show_guide):
        st.markdown(
            """
            #### 🔰 「瘋狗流」自己人獨立管理模式
            為了解決朋友、家人共用、想各自記錄戰績與資金池的需求，系統支援完整的 **多玩家 Profile**：
            
            1. **🏦 資金與帳本嚴格隔離**：
               - 每個玩家擁有自己的**每週預算限額**（可自由設定，如 NT$ 100, 200, 500 等）。
               - 每次下注從個人錢包扣款，中獎派彩全數存入個人的**保留儲備池**，互不影響。
            2. **🔑 4 位數安全 PIN 碼**：
               - 預設 PIN 碼均為 `0000`。
               - 輸入目前 PIN 碼驗證通過後，即可隨時自訂名稱、調整每週額度或變更成自己的私密 PIN 碼。
            3. **👥 免信箱快速開通**：
               - 點選「新增其他玩家 Profile」可為好友或家人立即建立新的獨立帳本，僅需姓名與 4 位數 PIN 碼。
            """
        )

    # 2. Logged-in Profile Overview Card
    col_card, col_logout = st.columns([4, 1])
    with col_card:
        st.markdown(
            f"""
            <div style="background:#141724; border:1px solid #2d334d; border-radius:10px; padding:12px 18px; margin-bottom:12px;">
                <div style="font-size:0.85rem; color:#94a3b8;">當前登入身分</div>
                <div style="font-size:1.35rem; font-weight:bold; color:#f8fafc; margin-top:2px;">
                    👤 【{profile['name']}】
                    <span style="font-size:0.80rem; background:rgba(56, 189, 248, 0.15); color:#38bdf8; border:1px solid #0284c7; padding:2px 8px; border-radius:4px; margin-left:8px;">PIN 碼防護中</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_logout:
        st.write("")
        if st.button("🚪 登出當前帳號", key="profile_page_logout_btn", use_container_width=True, type="secondary"):
            st.session_state.pop("authenticated_profile_id", None)
            st.session_state.pop("active_profile_id", None)
            st.rerun()

    # Active profile metrics (Responsive mobile 2x2 grid, desktop 4-col)
    st.markdown(
        f"""
        <div class='mobile-wallet-grid'>
            <div class='mobile-wallet-card card-blue'>
                <div class='m-label'>👤 玩家名稱</div>
                <div class='m-value'>{profile['name']}</div>
                <div class='m-sub'>PIN 防護中</div>
            </div>
            <div class='mobile-wallet-card card-amber'>
                <div class='m-label'>🎯 每週娛樂上限</div>
                <div class='m-value'>NT$ {profile['weekly_play_cap']:,.0f}</div>
                <div class='m-sub'>預算控制</div>
            </div>
            <div class='mobile-wallet-card card-green'>
                <div class='m-label'>💵 本週可玩餘額</div>
                <div class='m-value'>NT$ {wallet_status['weekly_wallet_balance']:,.0f}</div>
                <div class='m-sub'>錢包即時可用</div>
            </div>
            <div class='mobile-wallet-card card-purple'>
                <div class='m-label'>🏆 保留儲備池</div>
                <div class='m-value'>NT$ {wallet_status['prize_pool']:,.1f}</div>
                <div class='m-sub'>中獎累計儲備</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # Tabs for Settings and Creation (Archie sees all players, others see only self)
    is_admin = bool(profile.get("name") == "Archie")
    if is_admin:
        tab_edit, tab_admin_all, tab_create = st.tabs([
            "⚙️ 調整個人設定 (修改名稱 / 預算 / 變更 PIN 碼)",
            "👑 全系統玩家名單 (管理員 Archie 專屬)",
            "➕ 新增其他玩家 Profile",
        ])
    else:
        tab_edit, tab_create = st.tabs([
            "⚙️ 調整個人設定 (修改名稱 / 預算 / 變更 PIN 碼)",
            "➕ 新增其他玩家 Profile",
        ])

    with tab_edit:
        st.markdown(f"#### 🔒 修改「{profile['name']}」的個人設定")
        st.caption("預設 PIN 碼為 `0000`。修改名稱、每週金額或設定新 PIN 碼前，請先輸入當前 4 位數 PIN 碼進行身分確認。")

        with st.form("edit_profile_form"):
            current_pin = st.text_input(
                "🔑 輸入目前 4 位數 PIN 碼",
                type="password",
                max_chars=4,
                placeholder="0000",
                help="預設為 0000",
            )
            new_name = st.text_input("✏️ 修改玩家名稱 / 暱稱", value=profile["name"])
            new_cap = st.number_input(
                "💰 每週娛樂預算上限 (NT$)",
                min_value=10.0,
                max_value=100000.0,
                value=float(profile["weekly_play_cap"]),
                step=50.0,
                help="每週刷新時允許進入戰場的最大金額",
            )
            change_pin = st.checkbox("🔒 變更為新的 4 位數 PIN 碼")
            c_p1, c_p2 = st.columns(2)
            with c_p1:
                new_pin1 = st.text_input("新 PIN 碼 (4 位數字)", type="password", max_chars=4, disabled=not change_pin)
            with c_p2:
                new_pin2 = st.text_input("再次確認新 PIN 碼", type="password", max_chars=4, disabled=not change_pin)

            submit_edit = st.form_submit_button("儲存並套用個人設定", type="primary", use_container_width=True)

        if st.button("❓ 忘記目前 PIN 碼？", key="edit_profile_forgot_pin_btn"):
            st.info("💬 **忘記密碼？** 請聯絡管理員 **Archie** 為您重設 PIN 碼！")

        if submit_edit:
            if not current_pin:
                st.error("請輸入當前的 4 位數 PIN 碼進行身分驗證。忘記密碼請聯絡管理員 Archie。")
            else:
                try:
                    update_kwargs: Dict[str, Any] = {
                        "profile_id": profile["id"],
                        "current_pin": current_pin,
                        "new_name": new_name,
                        "new_weekly_play_cap": new_cap,
                    }
                    if change_pin:
                        if not new_pin1 or not re.fullmatch(r"\d{4}", new_pin1):
                            st.error("新 PIN 碼必須為 4 位純數字（例如：1234）！")
                            st.stop()
                        if new_pin1 != new_pin2:
                            st.error("兩次輸入的新 PIN 碼不一致，請重新檢查！")
                            st.stop()
                        update_kwargs["new_pin_code"] = new_pin1

                    updated = profile_mgr.update_profile(**update_kwargs)
                    st.success(f"✅ 已成功更新「{updated['name']}」的個人設定！每週額度設定為 NT$ {updated['weekly_play_cap']:.0f}。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ 更新失敗：{exc}（忘記密碼請聯絡管理員 Archie）")

    if is_admin:
        with tab_admin_all:
            st.markdown("#### 👑 管理員 Archie 專屬控制台：全系統所有玩家監控")
            st.caption("僅管理員 Archie 可查閱全體玩家之預算額度、即時餘額、儲備池及 LINE 綁定狀態。")
            all_profs = profile_mgr.list_profiles()

            prof_data_display = []
            for p in all_profs:
                try:
                    p_wm = WeeklyWalletManager(profile_id=p["id"])
                    p_status = p_wm.get_status()
                    w_bal = f"NT$ {p_status['weekly_wallet_balance']:,.0f}"
                    p_pool = f"NT$ {p_status['prize_pool']:,.1f}"
                except Exception:
                    w_bal = "N/A"
                    p_pool = "N/A"

                prof_data_display.append({
                    "玩家名稱": p["name"],
                    "每週預算限額": f"NT$ {p['weekly_play_cap']:.0f}",
                    "本週可玩": w_bal,
                    "保留儲備池": p_pool,
                    "LINE 綁定": "✅ 已綁定" if p.get("line_user_id") else "未綁定",
                    "建立日期": p.get("created_at", "")[:10],
                    "ID": p["id"][:8],
                })

            st.dataframe(prof_data_display, use_container_width=True)

            with st.expander("🛠️ 管理員重設玩家 PIN 碼 (僅 Archie 可見)", expanded=False):
                st.caption("若成員忘記密碼，管理員 Archie 可在此直接將其重設為預設 PIN 碼 0000。")
                reset_pnames = [p["name"] for p in all_profs if p["name"] != "Archie"]
                if reset_pnames:
                    col_r1, col_r2 = st.columns([3, 1])
                    with col_r1:
                        target_reset_name = st.selectbox("選擇要重設密碼的玩家：", reset_pnames, key="admin_reset_player_select")
                    with col_r2:
                        st.write("")
                        st.write("")
                        if st.button("🔄 重設為 0000", key="admin_do_reset_pin_btn", type="primary"):
                            target_p = next((p for p in all_profs if p["name"] == target_reset_name), None)
                            if target_p:
                                profile_mgr.change_pin(target_p["id"], "0000")
                                st.success(f"✅ 已成功將【{target_reset_name}】的 PIN 碼重設為預設值 0000！")
                                st.rerun()
                else:
                    st.info("目前尚無其他成員帳號。")

    with tab_create:
        st.markdown("#### ➕ 建立全新玩家 Profile")
        st.caption("為家人或好友建立獨立的資金與戰績空間，互相獨立不干擾。無需信箱或電話，輸入名字與自訂 PIN 碼即可完成。")

        with st.form("create_profile_form"):
            c_name = st.text_input("玩家暱稱 (如：小明、阿美、老陳)", placeholder="請輸入名稱")
            c_cap = st.number_input("每週預算限額 (NT$)", min_value=10.0, max_value=100000.0, value=200.0, step=50.0)
            c_pin = st.text_input("設定 4 位數安全 PIN 碼", value="0000", max_chars=4, type="password", help="預設為 0000")
            submit_create = st.form_submit_button("立即建立玩家 Profile", type="primary", use_container_width=True)

        if submit_create:
            clean_name = c_name.strip()
            clean_pin = c_pin.strip()
            if not clean_name:
                st.error("請填寫玩家暱稱！")
            elif not re.fullmatch(r"\d{4}", clean_pin):
                st.error("PIN 碼必須為 4 位純數字（例如：0000、1234）！")
            else:
                try:
                    created = profile_mgr.create_profile(name=clean_name, weekly_play_cap=c_cap, pin_code=clean_pin)
                    st.session_state["authenticated_profile_id"] = created["id"]
                    st.session_state["active_profile_id"] = created["id"]
                    st.success(f"🎉 成功建立新玩家「{created['name']}」！已自動切換至該玩家專屬空間。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ 建立失敗：{exc}")

    return profile["id"]
