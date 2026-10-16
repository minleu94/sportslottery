"""Shared two-entry sidebar navigation for the Streamlit multipage app."""
from __future__ import annotations

from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOME_PAGE = PROJECT_ROOT / "app.py"
GUIDE_PAGE = PROJECT_ROOT / "pages" / "1_指標與資料來源.py"


def render_sidebar_navigation() -> None:
    """Render the two existing pages with full labels and high-contrast controls."""
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
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.sidebar:
        st.page_link(str(HOME_PAGE), label="瘋狗流決策台", icon="🐕", use_container_width=True)
        st.page_link(str(GUIDE_PAGE), label="指標與資料來源", icon="📊", use_container_width=True)

        st.page_link(str(PROJECT_ROOT / "pages/2_資料健康與研究工具.py"), label="資料健康與研究工具", icon="🔎", use_container_width=True)
        st.page_link(str(PROJECT_ROOT / "pages/3_系統設定與資料存放.py"), label="系統設定與資料存放", icon="⚙️", use_container_width=True)
