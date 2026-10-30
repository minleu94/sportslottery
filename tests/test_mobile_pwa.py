"""Tests for iPhone / Mobile PWA configuration, static assets, and helper scripts."""

from __future__ import annotations

import json
from pathlib import Path
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "static"


def test_pwa_manifest_validity():
    """Verify static/manifest.json conforms to PWA standalone specifications."""
    manifest_path = STATIC_DIR / "manifest.json"
    assert manifest_path.exists(), "static/manifest.json must exist"

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("name") == "台灣運彩 瘋狗流高倍串關決策台"
    assert data.get("short_name") == "瘋狗流運彩"
    assert data.get("display") == "standalone", "Display mode must be standalone for iPhone WebClip"
    assert data.get("start_url") == "/"
    assert "theme_color" in data
    assert "background_color" in data

    icons = data.get("icons", [])
    assert len(icons) >= 2, "Must specify at least 2 icon sizes"
    srcs = [i["src"] for i in icons]
    assert any("apple-touch-icon" in s for s in srcs)
    assert any("192" in s for s in srcs)


def test_static_icons_exist_and_valid():
    """Verify generated icons exist and have valid dimensions."""
    icon_apple = STATIC_DIR / "apple-touch-icon.png"
    icon_192 = STATIC_DIR / "icon-192.png"
    icon_512 = STATIC_DIR / "icon-512.png"
    favicon = STATIC_DIR / "favicon.png"

    for icon_path in [icon_apple, icon_192, icon_512, favicon]:
        assert icon_path.exists(), f"Icon {icon_path.name} must exist"
        with Image.open(icon_path) as img:
            assert img.format == "PNG", f"{icon_path.name} must be a PNG image"

    with Image.open(icon_apple) as img:
        assert img.size == (180, 180), "apple-touch-icon.png must be 180x180"

    with Image.open(icon_192) as img:
        assert img.size == (192, 192), "icon-192.png must be 192x192"

    with Image.open(icon_512) as img:
        assert img.size == (512, 512), "icon-512.png must be 512x512"


def test_streamlit_static_serving_enabled():
    """Verify .streamlit/config.toml has enableStaticServing = true."""
    config_path = ROOT_DIR / ".streamlit" / "config.toml"
    assert config_path.exists(), ".streamlit/config.toml must exist"

    content = config_path.read_text(encoding="utf-8")
    assert "enableStaticServing = true" in content or "enableStaticServing=true" in content


def test_serve_mobile_ip_detection():
    """Verify scripts/serve_mobile.py IP detection function runs cleanly."""
    from scripts.serve_mobile import detect_network_ips, print_mobile_banner

    lan_ip, tailscale_ip = detect_network_ips()
    assert isinstance(lan_ip, str)
    assert len(lan_ip.split(".")) == 4, "LAN IP should be IPv4"

    if tailscale_ip:
        assert tailscale_ip.startswith("100."), "Tailscale IP should be in CGNAT range 100.x.x.x"

    target_url = print_mobile_banner(lan_ip, tailscale_ip, port=8000, qr_target="auto")
    assert f":8000" in target_url


def test_start_mobile_bat_exists():
    """Verify root startup script start_mobile.bat exists and references serve_mobile."""
    bat_path = ROOT_DIR / "start_mobile.bat"
    assert bat_path.exists(), "start_mobile.bat must exist in project root"
    content = bat_path.read_text(encoding="utf-8")
    assert "serve_mobile.py" in content


def test_app_py_mobile_and_pwa_injections():
    """Verify app.py includes Apple mobile WebClip meta tags and responsive CSS."""
    app_path = ROOT_DIR / "app.py"
    content = app_path.read_text(encoding="utf-8")

    assert "apple-mobile-web-app-capable" in content
    assert "apple-touch-icon" in content
    assert "manifest.json" in content
    assert "@media (max-width: 768px)" in content
    assert "mobile-leg-card" in content
