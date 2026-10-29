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
            background: #1e293b;
            padding: 10px 14px;
            border-radius: 8px;
            border: 1px solid #334155;
            margin-bottom: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.sidebar:
        try:
            from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
            from core.wallet import WeeklyWalletManager
            pm = ProfileManager()
            active_id = st.session_state.get("active_profile_id", DEFAULT_PROFILE_ID)
            active_profile = pm.get_or_default(active_id)
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
                    <div style="font-size:0.8rem; color:#94a3b8; display:flex; justify-content:space-between;">
                        <span>👤 當前玩家 Profile</span>
                        <span style="color:#a855f7; font-weight:600;">PIN 保護</span>
                    </div>
                    <div style="font-size:1.15rem; font-weight:bold; color:#f8fafc; margin-top:2px;">{active_profile['name']}</div>
                    <div style="display:flex; justify-content:space-between; margin-top:6px; font-size:0.82rem;">
                        <span style="color:#38bdf8;">💵 可用: NT$ {ws['weekly_wallet_balance']:,.0f}</span>
                        <span style="color:#4ade80;">🏆 儲備: NT$ {ws['prize_pool']:,.1f}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        except Exception:
            pass

        st.markdown("**🧭 系統頁面**")
        st.page_link(str(HOME_PAGE), label="瘋狗流決策台", icon="🐕", use_container_width=True)
        st.page_link(str(GUIDE_PAGE), label="指標與資料來源", icon="📊", use_container_width=True)
        st.page_link(str(PROJECT_ROOT / "pages/2_資料健康與研究工具.py"), label="資料健康與研究工具", icon="🔎", use_container_width=True)
        st.page_link(str(PROJECT_ROOT / "pages/3_系統設定與資料存放.py"), label="系統設定與資料存放", icon="⚙️", use_container_width=True)
