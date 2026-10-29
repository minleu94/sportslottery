"""UI Component for Profile Management, PIN Authentication, and First-time Onboarding Guide."""

from __future__ import annotations

import streamlit as st
from typing import Any, Dict, Optional
from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
from core.wallet import WeeklyWalletManager


def render_profile_view(profile_mgr: ProfileManager, current_profile_id: str, wallet_mgr: Optional[WeeklyWalletManager] = None) -> str:
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

    st.markdown("### 👤 個人 Profile 與多玩家獨立資金池")
    st.caption("每位玩家擁有獨立的每週娛樂限額、個人錢包、獲利保留儲備池與注單帳本。透過 4 位數 PIN 碼保障設定安全。")

    # 1. First-time Onboarding Guidance (初次設定引導)
    show_guide = st.session_state.get("show_onboarding_guide", True)
    with st.expander("🌟 初次使用設定指南與 PIN 碼說明 (點擊展開/收合說明)", expanded=show_guide):
        st.markdown(
            """
            #### 🔰 歡迎來到「瘋狗流」多玩家獨立管理系統！
            為了解決多人共用、想各自記錄戰績與資金池的需求，系統支援完整的 **多玩家 Profile**：
            
            1. **🏦 資金與帳本嚴格隔離**：
               - 每個玩家擁有自己的**每週預算限額**（可自由設定，如 NT$ 100, 200, 500 等）。
               - 每次下注從個人錢包扣款，中獎派彩全數存入個人的**保留儲備池**，互不影響。
            2. **🔑 預設 4 位數安全 PIN 碼**：
               - 每個新建立的玩家 Profile 預設 PIN 碼均為 `0000`。
               - 只要輸入正確的 PIN 碼，即可隨時自訂名稱、調整每週額度或變更 PIN 碼。
            3. **👥 隨時切換與新增玩家**：
               - 點選下方「切換玩家」即可在不同身分間無縫切換。
               - 點選「新增玩家 Profile」可為好友或家人立即建立新的獨立帳本。
            """
        )
        if st.button("我知道了，暫時收合引導", key="dismiss_guide_btn"):
            st.session_state["show_onboarding_guide"] = False
            st.rerun()

    st.markdown("---")

    # 2. Profile Overview Cards
    all_profiles = profile_mgr.list_profiles()
    p_names = {p["id"]: f"{p['name']} (每週 NT$ {p['weekly_play_cap']:.0f})" for p in all_profiles}

    col_sel, col_add_btn = st.columns([3, 1])
    with col_sel:
        profile_keys = list(p_names.keys())
        current_index = profile_keys.index(active_id) if active_id in profile_keys else 0
        selected_id = st.selectbox(
            "切換目前操作玩家：",
            options=profile_keys,
            index=current_index,
            format_func=lambda x: p_names.get(x, x),
            key="profile_selector_dropdown",
        )
        if selected_id != active_id:
            st.session_state["active_profile_id"] = selected_id
            st.rerun()

    with col_add_btn:
        st.write("")
        st.write("")
        show_create_modal = st.button("➕ 新增玩家 Profile", use_container_width=True, type="secondary")

    # Active profile cards
    active_profile = profile_mgr.get_or_default(selected_id)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("👤 玩家名稱", active_profile["name"])
    with c2:
        st.metric("🎯 每週娛樂上限", f"NT$ {active_profile['weekly_play_cap']:,.0f}")
    with c3:
        st.metric("💵 本週可玩餘額", f"NT$ {wallet_status['weekly_wallet_balance']:,.2f}")
    with c4:
        st.metric("🏆 保留儲備池 (獎金)", f"NT$ {wallet_status['prize_pool']:,.2f}")

    st.markdown("---")

    # Tabs for Settings and Creation
    tab_edit, tab_create = st.tabs(["⚙️ 調整個人設定 (需輸入 PIN 碼)", "➕ 新增其他玩家 Profile"])

    with tab_edit:
        st.markdown(f"#### 🔒 修改「{active_profile['name']}」的個人設定")
        st.caption("預設 PIN 碼為 `0000`。修改名稱、每週金額或設定新 PIN 碼前，請先輸入當前 4 位數 PIN 碼進行驗證。")

        with st.form("edit_profile_form"):
            current_pin = st.text_input("🔑 輸入目前 4 位數 PIN 碼", type="password", max_chars=4, placeholder="0000", help="預設為 0000")
            new_name = st.text_input("✏️ 修改玩家名稱", value=active_profile["name"])
            new_cap = st.number_input(
                "💰 每週娛樂預算上限 (NT$)",
                min_value=10.0,
                max_value=100000.0,
                value=float(active_profile["weekly_play_cap"]),
                step=50.0,
                help="每週刷新時允許進入戰場的最大金額",
            )
            change_pin = st.checkbox("🔒 變更新的 4 位數 PIN 碼")
            new_pin1 = st.text_input("新 PIN 碼 (4 位數字)", type="password", max_chars=4, disabled=not change_pin)
            new_pin2 = st.text_input("再次確認新 PIN 碼", type="password", max_chars=4, disabled=not change_pin)

            submit_edit = st.form_submit_button("儲存並套用個人設定", type="primary")

        if submit_edit:
            if not current_pin:
                st.error("請輸入當前的 4 位數 PIN 碼進行身分驗證。")
            else:
                try:
                    update_kwargs: Dict[str, Any] = {
                        "profile_id": active_profile["id"],
                        "current_pin": current_pin,
                        "new_name": new_name,
                        "new_weekly_play_cap": new_cap,
                    }
                    if change_pin:
                        if new_pin1 != new_pin2:
                            st.error("兩次輸入的新 PIN 碼不一致，請重新檢查！")
                            st.stop()
                        update_kwargs["new_pin_code"] = new_pin1

                    updated = profile_mgr.update_profile(**update_kwargs)
                    st.success(f"✅ 已成功更新「{updated['name']}」的設定！每週額度設定為 NT$ {updated['weekly_play_cap']:.0f}。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ 更新失敗：{exc}")

    with tab_create:
        st.markdown("#### ➕ 建立全新玩家 Profile")
        st.caption("為家人或好友建立獨立的資金與戰績空間，互相獨立不干擾。")

        with st.form("create_profile_form"):
            c_name = st.text_input("玩家暱稱 (如：小明、阿美)", placeholder="請輸入名稱")
            c_cap = st.number_input("每週預算限額 (NT$)", min_value=10.0, max_value=100000.0, value=200.0, step=50.0)
            c_pin = st.text_input("設定 4 位數安全 PIN 碼", value="0000", max_chars=4, type="password", help="預設為 0000")
            submit_create = st.form_submit_button("立即建立玩家 Profile", type="primary")

        if submit_create:
            try:
                created = profile_mgr.create_profile(name=c_name, weekly_play_cap=c_cap, pin_code=c_pin)
                st.session_state["active_profile_id"] = created["id"]
                st.success(f"🎉 成功建立新玩家「{created['name']}」！已自動切換至該玩家。")
                st.rerun()
            except Exception as exc:
                st.error(f"❌ 建立失敗：{exc}")

    return selected_id
