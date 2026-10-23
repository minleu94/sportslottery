from pathlib import Path
import tomllib


def test_streamlit_sidebar_uses_two_explicit_full_label_icon_links_and_hides_duplicate_auto_nav():
    import ui.navigation as navigation

    observed = []
    class Sidebar:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def page_link(self, path, **kwargs): observed.append((Path(path).name, kwargs))

    class FakeStreamlit:
        sidebar = Sidebar()
        @staticmethod
        def markdown(*args, **kwargs): pass
        @staticmethod
        def page_link(path, **kwargs): observed.append((Path(path).name, kwargs))

    original = navigation.st
    navigation.st = FakeStreamlit()
    try:
        navigation.render_sidebar_navigation()
    finally:
        navigation.st = original

    assert [entry[0] for entry in observed] == ["app.py", "1_指標與資料來源.py", "2_資料健康與研究工具.py", "3_系統設定與資料存放.py"]
    assert [item["label"] for _, item in observed] == ["瘋狗流決策台", "指標與資料來源", "資料健康與研究工具", "系統設定與資料存放"]
    assert [item["icon"] for _, item in observed] == ["🐕", "📊", "🔎", "⚙️"]
    config = tomllib.loads((Path(__file__).parents[1] / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert config["client"]["showSidebarNavigation"] is False
