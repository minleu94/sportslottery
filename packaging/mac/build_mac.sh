#!/usr/bin/env bash
# packaging/mac/build_mac.sh
# macOS Build Script: Bundles Python 3.11 + Streamlit into Sportslottery.app and creates DMG installer.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

echo "=========================================================="
echo "  台灣運彩系統 - macOS 獨立安裝包構建工具"
echo "=========================================================="

APP_NAME="Sportslottery"
VERSION="2.1.0"
DIST_DIR="$PROJECT_ROOT/dist"
INSTALLER_DIR="$DIST_DIR/installer"

mkdir -p "$INSTALLER_DIR"

# 1. Clean previous build
rm -rf "$DIST_DIR/$APP_NAME" "$DIST_DIR/$APP_NAME.app"

# 2. Run PyInstaller
echo "[1/3] 執行 PyInstaller 打包 macOS Bundle..."
python3 -m PyInstaller --clean --noconfirm "$PROJECT_ROOT/sportslottery_dist.spec"

# 3. Rename to .app bundle structure on macOS if not done automatically
if [ -d "$DIST_DIR/$APP_NAME" ] && [ ! -d "$DIST_DIR/$APP_NAME.app" ]; then
    # Create simple macOS App wrapper
    APP_DIR="$DIST_DIR/$APP_NAME.app/Contents/MacOS"
    RESOURCES_DIR="$DIST_DIR/$APP_NAME.app/Contents/Resources"
    mkdir -p "$APP_DIR" "$RESOURCES_DIR"
    cp -r "$DIST_DIR/$APP_NAME/"* "$APP_DIR/"
    
    # Create Info.plist
    cat <<EOF > "$DIST_DIR/$APP_NAME.app/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>Sportslottery</string>
    <key>CFBundleIdentifier</key>
    <string>com.sportslottery.desktop</string>
    <key>CFBundleName</key>
    <string>Sportslottery</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
</dict>
</plist>
EOF
fi

# 4. Create DMG
DMG_PATH="$INSTALLER_DIR/${APP_NAME}_macOS_v${VERSION}.dmg"
echo "[2/3] 封裝 macOS DMG 安裝映像檔..."

if command -v create-dmg &> /dev/null; then
    rm -f "$DMG_PATH"
    create-dmg \
        --volname "Sportslottery Installer" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "$APP_NAME.app" 175 120 \
        --hide-extension "$APP_NAME.app" \
        --app-drop-link 425 120 \
        "$DMG_PATH" \
        "$DIST_DIR/$APP_NAME.app" || true
else
    # Fallback using standard macOS hdiutil
    echo "使用 macOS 內建 hdiutil 產生 DMG..."
    TMP_DMG_DIR="$DIST_DIR/dmg_tmp"
    rm -rf "$TMP_DMG_DIR" "$DMG_PATH"
    mkdir -p "$TMP_DMG_DIR"
    cp -R "$DIST_DIR/$APP_NAME.app" "$TMP_DMG_DIR/"
    ln -s /Applications "$TMP_DMG_DIR/Applications"
    hdiutil create -volname "Sportslottery" -srcfolder "$TMP_DMG_DIR" -ov -format UDZO "$DMG_PATH"
    rm -rf "$TMP_DMG_DIR"
fi

echo "=========================================================="
echo "🎉 macOS 打包完成！"
echo "產物路徑: $DMG_PATH"
echo "=========================================================="
