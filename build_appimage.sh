#!/usr/bin/env bash
set -euo pipefail

# Build LiteClick as a portable AppImage on Linux Lite / Ubuntu X11.
# Prerequisites: linuxdeploy-x86_64.AppImage, linuxdeploy-plugin-qt-x86_64.AppImage,
# and appimagetool-x86_64.AppImage available in PATH (or set their *_BIN variables).

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"
LINUXDEPLOY="${LINUXDEPLOY_BIN:-linuxdeploy-x86_64.AppImage}"
APPIMAGETOOL="${APPIMAGETOOL_BIN:-appimagetool-x86_64.AppImage}"
QT_PLUGIN="${LINUXDEPLOY_PLUGIN_QT_BIN:-linuxdeploy-plugin-qt-x86_64.AppImage}"

for cmd in "$LINUXDEPLOY" "$APPIMAGETOOL" "$QT_PLUGIN"; do
    if ! command -v "$cmd" >/dev/null 2>&1 && [[ ! -x "$cmd" ]]; then
        echo "Missing build tool: $cmd" >&2
        echo "Download linuxdeploy, linuxdeploy-plugin-qt, and appimagetool, make them executable, and put them in PATH." >&2
        exit 1
    fi
done

# Make custom tool paths visible to linuxdeploy and its plugin discovery.
for tool in "$LINUXDEPLOY" "$APPIMAGETOOL" "$QT_PLUGIN"; do
    resolved="$(command -v "$tool" 2>/dev/null || printf '%s' "$tool")"
    export PATH="$(dirname "$resolved"):$PATH"
done
PLUGIN_DIR="$ROOT/build/appimage-tools"
mkdir -p "$PLUGIN_DIR"
QT_RESOLVED="$(command -v "$QT_PLUGIN" 2>/dev/null || printf '%s' "$QT_PLUGIN")"
APPIMAGE_RESOLVED="$(command -v "$APPIMAGETOOL" 2>/dev/null || printf '%s' "$APPIMAGETOOL")"
ln -sf "$QT_RESOLVED" "$PLUGIN_DIR/linuxdeploy-plugin-qt"
ln -sf "$APPIMAGE_RESOLVED" "$PLUGIN_DIR/appimagetool"
export PATH="$PLUGIN_DIR:$PATH"

"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r requirements.txt pyinstaller
rm -rf build/LiteClick.AppDir dist/LiteClick
"$PYTHON" -m PyInstaller --noconfirm --clean --windowed --onedir \
    --name LiteClick --add-data "ui:ui" main.py

APPDIR="$ROOT/build/LiteClick.AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps"
cp -a dist/LiteClick/. "$APPDIR/usr/bin/"
cp packaging/liteclick.desktop "$APPDIR/liteclick.desktop"
cp packaging/liteclick.desktop "$APPDIR/usr/share/applications/liteclick.desktop"
cp packaging/liteclick.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/liteclick.svg"
cp packaging/liteclick.svg "$APPDIR/liteclick.svg"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/LiteClick" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# The plugin collects Qt platform plugins and shared libraries.
"$LINUXDEPLOY" --appdir "$APPDIR" --plugin qt --output appimage

echo "Build finished. Look for LiteClick-x86_64.AppImage in the project directory."
