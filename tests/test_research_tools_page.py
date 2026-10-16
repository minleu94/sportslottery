from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_research_tools_page_empty_data_is_readable_and_no_network(tmp_path, monkeypatch):
    import core.research_paths as paths
    import ui.navigation as navigation
    # Streamlit AppTest does not populate multipage page-link routing metadata.
    # Navigation links are covered separately and will be verified in the browser.
    monkeypatch.setattr(navigation,"render_sidebar_navigation",lambda:None)
    config=tmp_path/"research.yaml"
    root=tmp_path/"research"
    config.write_text("data_root: "+root.as_posix()+"\n",encoding="utf-8")
    monkeypatch.setattr(paths,"DEFAULT_CONFIG",config)
    page=Path(__file__).resolve().parents[1]/"pages/2_資料健康與研究工具.py"
    result=AppTest.from_file(str(page)).run(timeout=20)
    assert not result.exception
    assert [tab.label for tab in result.tabs]==["資料與排程健康","CLV價格追蹤","推薦重播與版本比較"]
    assert len(result.info)>=3
    assert not root.exists()
