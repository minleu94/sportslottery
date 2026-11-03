from pathlib import Path

from desktop_launcher import build_streamlit_cli_args


def test_legacy_streamlit_launcher_forces_loopback_bind():
    args = build_streamlit_cli_args(Path("app.py"))
    assert "--server.address=127.0.0.1" in args
    assert not any(arg == "--server.address=0.0.0.0" for arg in args)
