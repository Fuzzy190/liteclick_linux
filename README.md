# LiteClick v7.5 — Linux Auto Clicker & Key Presser

LiteClick is a PySide6 desktop utility for repeating multiple keyboard/mouse inputs and recording/replaying desktop macros. The recommended target is Linux Lite on an X11 session.

## Run from source

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip python3-tk libxkbcommon-x11-0 libxcb-cursor0
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Check the current desktop session with `echo "$XDG_SESSION_TYPE"`; for this app, `x11` is recommended. Depending on your distribution's Qt/X11 packaging, additional `libxcb-*` runtime libraries may be required.

## Features

- Separate Keyboard and Mouse tabs, with multiple inputs and per-input delays.
- Capture a keyboard key by clicking **Capture key…** and pressing the desired key.
- Left, middle, and right mouse clicks.
- Enable/disable individual rows, reorder by removing/re-adding, and save/load named JSON keyboard profiles (mouse profile save/load is intentionally omitted).
- Infinite or finite automation cycles.
- Edit per-row delays directly using the delay spinbox; use Move up / Move down to reorder inputs.
- Customizable global hotkeys, saved between launches. Defaults: F6 toggles keyboard automation, F8 toggles mouse automation, Ctrl+1 starts/stops recording, Ctrl+2 starts playback, Ctrl+3 stops playback, and Ctrl+0 is the emergency stop for all activities.
- Keyboard automation and mouse automation each have a toggle hotkey (F6 and F8 by default) that starts or stops that mode. Playback controls are deliberately separate: the record hotkey toggles recording, the playback-start hotkey starts playback only, and the playback-stop hotkey stops playback only. Hotkeys appear beside their buttons and are customizable in the Hotkeys tab. Active buttons turn green.
- Record key down/up, mouse button down/up, cursor movement, and scroll events.
- Macro playback supports repeat counts, playback speed, configurable random timing variation (0–50%), and an option to disable cursor movement.
- Save/load macro recordings as JSON.
- Playback releases any keys/buttons it has held if stopped midway.
- Automation and macro playback are mutually exclusive; stop the current action before starting another mode.

## AppImage build

The repository includes `build_appimage.sh`, `packaging/liteclick.desktop`, and an SVG icon. The build script uses PyInstaller plus `linuxdeploy`, its Qt plugin, and `appimagetool`.

1. Download the Linux x86_64 AppImages for `linuxdeploy`, `linuxdeploy-plugin-qt`, and `appimagetool` from their official project release pages.
2. Make each executable (`chmod +x *.AppImage`) and put them in `PATH`, or set `LINUXDEPLOY_BIN`, `LINUXDEPLOY_PLUGIN_QT_BIN`, and `APPIMAGETOOL_BIN` to their paths.
3. Run from the project root:

   ```bash
   ./build_appimage.sh
   ```

4. Test the resulting AppImage on Linux Lite X11 and, ideally, a second machine. AppImage packaging can depend on host libraries; a successful build does not guarantee portability across every Linux distribution.

## Notes

- Global keyboard hooks and simulated input are most reliable under X11. Wayland sessions may restrict global listeners and injected input.
- Macro playback generates real desktop input and may move the cursor. Use the configured playback-stop hotkey or Stop button if needed, and test in a safe window first.
- Follow the game or service's rules about automation and macros.

## Playback profiles and event logs

- Use **Save playback profile…** to save a replayable `.json` profile. It includes the recorded events plus repetition count, playback speed, timing variation, and cursor-movement preference.
- Use **Load playback profile…** to restore the events and saved playback settings. Older LiteClick JSON recordings containing only `events` remain supported.
- Use **Rename saved profile…** in the Playback tab, choose a saved JSON profile, and enter a new display name. LiteClick updates both the profile name inside the JSON and its filename; existing events and playback settings are preserved.
- Use **Export event log (.md/.txt)…** to export a human-readable event timeline in Markdown or plain text. These exports are reports for reading/sharing and cannot be loaded for playback; use JSON for replay.
- The default profile folder is `~/.config/liteclick/profiles/`.


## v7.5 restoration and improvements

This iteration is based on the fuller v6 source. It preserves keyboard key capture, per-key delays, keyboard profile save/load, mouse and keyboard automation, customizable global hotkeys, playback profile save/load/rename, event-log export, playback speed, timing variation, and cursor movement. Mouse profile save/load controls are intentionally not shown; keyboard profile save/load remains available.

Playback now supports pause/resume without losing its current event position, a compact always-on-top countdown overlay that uses the loaded playback profile name as its window title, cancellation/closure on Stop and Emergency Stop, and a saved default playback profile that is automatically loaded on launch.

Timing variation randomly adjusts each recorded delay by up to the configured percentage (0% keeps the original delay).
