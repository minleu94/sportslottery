"""Operational evidence and research diagnostics."""
import sys
from pathlib import Path
import streamlit as st
root=Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0,str(root))
from ui.navigation import render_sidebar_navigation
from ui.research_tools import render_health_panel, render_clv_panel, render_replay_panel
st.set_page_config(page_title="資料健康與研究工具｜瘋狗流",page_icon="🔎",layout="wide")
render_sidebar_navigation()
health,clv,replay=st.tabs(["資料與排程健康","CLV價格追蹤","推薦重播與版本比較"])
with health:
    render_health_panel()
with clv:
    render_clv_panel()
with replay:
    render_replay_panel()
