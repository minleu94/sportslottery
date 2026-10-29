from pathlib import Path
import tomllib


def test_streamlit_sidebar_uses_two_explicit_full_label_icon_links_and_hides_duplicate_auto_nav():
    import ui.navigation as navigation
    from core.profile_manager import ProfileManager

    observed = []
    class Sidebar:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def page_link(self, path, **kwargs): observed.append((Path(path).name, kwargs))

    class FakeStreamlit:
        sidebar = Sidebar()
        session_state = {}
        @staticmethod
        def markdown(*args, **kwargs): pass
        @staticmethod
        def page_link(path, **kwargs): observed.append((Path(path).name, kwargs))

    original = navigation.st
    navigation.st = FakeStreamlit()
    try:
        # 1. Unauthenticated or non-Archie player: settings page is hidden
        navigation.render_sidebar_navigation()
        assert [entry[0] for entry in observed] == ["app.py", "1_指標與資料來源.py", "2_資料健康與研究工具.py"]

        # 2. Logged in as Archie: admin settings page is visible
        pm = ProfileManager()
        archie = pm.get_profile_by_name("Archie") or pm.create_profile("Archie", weekly_play_cap=500.0, pin_code="0000")
        FakeStreamlit.session_state = {"authenticated_profile_id": archie["id"]}
        observed.clear()
        navigation.render_sidebar_navigation()
        assert [entry[0] for entry in observed] == ["app.py", "1_指標與資料來源.py", "2_資料健康與研究工具.py", "3_系統設定與資料存放.py"]
        assert "系統設定與資料存放" in observed[3][1]["label"]
        assert observed[3][1]["icon"] == "⚙️"
    finally:
        navigation.st = original

    config = tomllib.loads((Path(__file__).parents[1] / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert config["client"]["showSidebarNavigation"] is False
