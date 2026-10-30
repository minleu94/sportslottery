"""Shared sidebar navigation for the Streamlit multipage app with Profile quick status."""
from __future__ import annotations

from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOME_PAGE = PROJECT_ROOT / "app.py"
GUIDE_PAGE = PROJECT_ROOT / "pages" / "1_指標與資料來源.py"


def render_sidebar_navigation() -> None:
    """Render the sidebar navigation with high-contrast controls and Profile status."""
    st.markdown(
        """
        <style>
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapsedControl"] {
            opacity: 1 !important;
            visibility: visible !important;
        }
        [data-testid="stSidebarCollapseButton"] button,
        [data-testid="stSidebarCollapsedControl"] button,
        button[data-testid="stExpandSidebarButton"],
        button[data-testid="stSidebarCollapseButton"] {
            width: 2.5rem !important;
            min-width: 2.5rem !important;
            height: 2.5rem !important;
            border: 1px solid #9aa4c2 !important;
            border-radius: 0.55rem !important;
            background: #292d40 !important;
            color: #ffffff !important;
            opacity: 1 !important;
            visibility: visible !important;
            box-shadow: 0 0 0 1px rgba(255,255,255,.12) !important;
        }
        [data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"],
        [data-testid="stSidebarCollapsedControl"] [data-testid="stIconMaterial"],
        [data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] {
            font-size: 1.45rem !important;
            color: #ffffff !important;
        }
        [data-testid="stSidebarCollapseButton"] button svg,
        [data-testid="stSidebarCollapsedControl"] button svg,
        [data-testid="stExpandSidebarButton"] svg {
            width: 1.45rem !important;
            height: 1.45rem !important;
            color: #ffffff !important;
            fill: #ffffff !important;
        }
        [data-testid="stSidebarCollapseButton"] button:hover,
        [data-testid="stSidebarCollapsedControl"] button:hover,
        button[data-testid="stExpandSidebarButton"]:hover {
            background: #46506e !important;
            border-color: #ffffff !important;
        }
        .profile-side-card {
            background: var(--card-bg, #1e293b);
            padding: 10px 14px;
            border-radius: 8px;
            border: 1px solid var(--card-border, #334155);
            box-shadow: var(--card-shadow, 0 2px 6px rgba(0,0,0,0.2));
            margin-bottom: 12px;
        }
        /* Mobile top clearance: ensure top banner never cuts off page content */
        header[data-testid="stHeader"], [data-testid="stHeader"] {
            background: var(--card-bg, #0e1117) !important;
            backdrop-filter: blur(12px) !important;
            -webkit-backdrop-filter: blur(12px) !important;
            border-bottom: 1px solid var(--card-border, rgba(255, 255, 255, 0.08)) !important;
            z-index: 99990 !important;
        }
        @media (max-width: 768px) {
            .block-container {
                padding-top: calc(4.8rem + env(safe-area-inset-top, 0px)) !important;
                padding-bottom: calc(3.0rem + env(safe-area-inset-bottom, 0px)) !important;
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    active_profile = None
    with st.sidebar:
        try:
            from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
            from core.wallet import WeeklyWalletManager
            pm = ProfileManager()
            session_state = getattr(st, "session_state", {})
            auth_id = session_state.get("authenticated_profile_id") if isinstance(session_state, dict) or hasattr(session_state, "get") else None
            active_profile = pm.get_profile(auth_id) if auth_id else None

            if active_profile:
                try:
                    wm = WeeklyWalletManager(profile_id=active_profile["id"])
                except TypeError:
                    wm = WeeklyWalletManager()
                if hasattr(wm, "profile_id"):
                    wm.profile_id = active_profile["id"]
                ws = wm.get_status()
                
                st.markdown(
                    f"""
                    <div class="profile-side-card">
                        <div style="font-size:0.8rem; color:var(--text-secondary); display:flex; justify-content:space-between;">
                            <span>👤 當前登入玩家</span>
                            <span style="color:#a855f7; font-weight:600;">PIN 保護</span>
                        </div>
                        <div style="font-size:1.15rem; font-weight:bold; color:var(--text-primary); margin-top:2px;">{active_profile['name']}</div>
                        <div style="display:flex; justify-content:space-between; margin-top:6px; font-size:0.82rem;">
                            <span style="color:#38bdf8;">💵 可用: NT$ {ws['weekly_wallet_balance']:,.0f}</span>
                            <span style="color:#4ade80;">🏆 儲備: NT$ {ws['prize_pool']:,.1f}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button("🚪 登出當前帳號", key="sidebar_logout_btn", use_container_width=True):
                    st.session_state.pop("authenticated_profile_id", None)
                    st.session_state.pop("active_profile_id", None)
                    st.rerun()
            else:
                st.markdown(
                    """
                    <div class="profile-side-card">
                        <div style="font-size:0.85rem; color:#f59e0b; font-weight:bold;">🔒 尚未登入身分</div>
                        <div style="font-size:0.80rem; color:#94a3b8; margin-top:4px;">請於主頁以姓名與 4 位數 PIN 碼登入或快速註冊。</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        except Exception:
            pass

        is_admin_archie = bool(active_profile and active_profile.get("name") == "Archie")

        st.markdown("**🧭 系統頁面**")
        st.page_link(str(HOME_PAGE), label="瘋狗流決策台", icon="🐕", use_container_width=True)
        st.page_link(str(GUIDE_PAGE), label="指標與資料來源", icon="📊", use_container_width=True)
        st.page_link(str(PROJECT_ROOT / "pages/2_資料健康與研究工具.py"), label="資料健康與研究工具", icon="🔎", use_container_width=True)
        if is_admin_archie:
            st.page_link(str(PROJECT_ROOT / "pages/3_系統設定與資料存放.py"), label="系統設定與資料存放 (管理員)", icon="⚙️", use_container_width=True)
