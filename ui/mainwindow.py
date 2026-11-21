"""LiteClick UI and automation workers.

Linux note: pynput global input hooks generally work on X11. Wayland compositors
may block global listeners/injected input; see README.md.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from threading import Event, Lock

from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QFrame, QTabWidget, QComboBox, QSpinBox, QFormLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog, QAbstractItemView,
    QCheckBox, QGroupBox, QLineEdit, QDialog, QDialogButtonBox, QInputDialog,
)
from pynput import keyboard, mouse
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Controller as MouseController, Button

SPECIAL_KEYS = {
    "Space": Key.space, "Enter": Key.enter, "Tab": Key.tab,
    "Shift": Key.shift, "Ctrl": Key.ctrl, "Alt": Key.alt,
    "Esc": Key.esc, "Backspace": Key.backspace, "Delete": Key.delete,
    "Up": Key.up, "Down": Key.down, "Left": Key.left, "Right": Key.right,
    "F1": Key.f1, "F2": Key.f2, "F3": Key.f3, "F4": Key.f4,
    "F5": Key.f5, "F6": Key.f6, "F7": Key.f7, "F8": Key.f8,
    "F9": Key.f9, "F10": Key.f10, "F11": Key.f11, "F12": Key.f12,
}
BUTTONS = {"Left click": Button.left, "Middle click": Button.middle, "Right click": Button.right}
PROFILE_DIR = Path.home() / ".config" / "liteclick" / "profiles"
SETTINGS_FILE = Path.home() / ".config" / "liteclick" / "settings.json"
DEFAULT_PLAYBACK_FILE = PROFILE_DIR / "default-playback.json"
DEFAULT_HOTKEYS = {
    "keyboard": "F6",          # toggle keyboard automation
    "mouse": "F8",             # toggle mouse automation
    "record": "Ctrl+1",        # start/stop recording
    "play_start": "Ctrl+2",    # start playback only
    "play_stop": "Ctrl+3",     # stop playback only
    "stop_all": "Ctrl+0",      # emergency stop all activities
}


def resolve_key(value: str):
    value = value.strip()
    if value in SPECIAL_KEYS:
        return SPECIAL_KEYS[value]
    if len(value) == 1:
        return value.lower() if value.isalpha() else value
    raise ValueError(f"Unsupported key '{value}'. Use a single character or a listed special key.")


class KeyCaptureDialog(QDialog):
    """Small focused dialog that captures one key using Qt keyboard events."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Capture keyboard key")
        self.setModal(True)
        self.setMinimumWidth(340)
        self.captured_key = None
        layout = QVBoxLayout(self)
        prompt = QLabel("Press the key you want to add. Escape cancels.")
        prompt.setWordWrap(True)
        self.preview = QLabel("Waiting for key…")
        self.preview.setObjectName("SectionTitle")
        layout.addWidget(prompt)
        layout.addWidget(self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus()
        self.activateWindow()

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            return
        key = event.key()
        names = {
            Qt.Key_Space: "Space", Qt.Key_Return: "Enter", Qt.Key_Enter: "Enter",
            Qt.Key_Tab: "Tab", Qt.Key_Backspace: "Backspace", Qt.Key_Delete: "Delete",
            Qt.Key_Shift: "Shift", Qt.Key_Control: "Ctrl", Qt.Key_Alt: "Alt",
            Qt.Key_Escape: "Esc", Qt.Key_Up: "Up", Qt.Key_Down: "Down",
            Qt.Key_Left: "Left", Qt.Key_Right: "Right",
        }
        for number in range(1, 13):
            qt_key = getattr(Qt, f"Key_F{number}")
            if key == qt_key:
                names[key] = f"F{number}"
        if key == Qt.Key_Escape:
            self.reject()
            return
        text = event.text()
        if key in names:
            captured = names[key]
        elif text and text.isprintable() and len(text) == 1:
            captured = text.upper() if text.isalpha() else text
        else:
            self.preview.setText("Unsupported key — try a letter, number, or special key")
            return
        self.captured_key = captured
        self.accept()


class AutomationWorker(QThread):
    message = Signal(str)

    def __init__(self, actions: list[dict], repeat_count: int = 0):
        super().__init__()
        self.actions = actions
        self.repeat_count = repeat_count  # zero = infinite
        self.stop_event = Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        kb, ms = KeyboardController(), MouseController()
        cycle = 0
        try:
            while not self.stop_event.is_set() and (self.repeat_count == 0 or cycle < self.repeat_count):
                for action in self.actions:
                    if self.stop_event.is_set():
                        break
                    if action["kind"] == "key":
                        key = resolve_key(action["input"])
                        kb.press(key)
                        kb.release(key)
                    else:
                        ms.click(BUTTONS[action["input"]])
                    # Per-action interval: the delay after this input.
                    if self.stop_event.wait(max(0.01, action["interval"] / 1000)):
                        break
                cycle += 1
            self.message.emit("Automation stopped.")
        except Exception as exc:
            self.message.emit(f"Automation error: {exc}")


class Recorder:
    """Records keyboard/mouse presses and cursor movement with relative timings."""
    def __init__(self, callback):
        self.callback = callback
        self.events = []
        self.started_at = 0.0
        self.lock = Lock()
        self.keyboard_listener = None
        self.mouse_listener = None
        self.recording = False

    def start(self):
        self.events = []
        self.started_at = time.monotonic()
        self.recording = True
        self.keyboard_listener = keyboard.Listener(on_press=self._key_press, on_release=self._key_release)
        self.mouse_listener = mouse.Listener(on_click=self._click, on_move=self._move, on_scroll=self._scroll)
        self.keyboard_listener.start()
        self.mouse_listener.start()

    def _append(self, event):
        if not self.recording:
            return
        event["t"] = round(time.monotonic() - self.started_at, 4)
        with self.lock:
            self.events.append(event)
        self.callback(len(self.events))

    @staticmethod
    def _key_name(key):
        if isinstance(key, Key):
            raw = str(key).replace("Key.", "")
            aliases = {
                "space": "Space", "enter": "Enter", "return": "Enter", "tab": "Tab",
                "shift": "Shift", "shift_l": "Shift", "shift_r": "Shift",
                "ctrl": "Ctrl", "ctrl_l": "Ctrl", "ctrl_r": "Ctrl",
                "alt": "Alt", "alt_l": "Alt", "alt_r": "Alt",
                "esc": "Esc", "backspace": "Backspace", "delete": "Delete",
                "up": "Up", "down": "Down", "left": "Left", "right": "Right",
            }
            return aliases.get(raw.lower(), raw.upper() if raw.lower().startswith("f") and raw[1:].isdigit() else raw.capitalize())
        char = getattr(key, "char", None)
        return char.upper() if char and char.isalpha() else char

    def _key_press(self, key):
        name = self._key_name(key)
        if name:
            self._append({"type": "key_down", "key": name})

    def _key_release(self, key):
        name = self._key_name(key)
        if name:
            self._append({"type": "key_up", "key": name})

    def _click(self, x, y, button, pressed):
        name = {mouse.Button.left: "left", mouse.Button.middle: "middle", mouse.Button.right: "right"}.get(button)
        if name:
            self._append({"type": "mouse_down" if pressed else "mouse_up", "button": name, "x": x, "y": y})

    def _move(self, x, y):
        # Movement can create very large recordings, so only record when changed.
        if not self.events or self.events[-1].get("type") != "move" or (self.events[-1].get("x"), self.events[-1].get("y")) != (x, y):
            self._append({"type": "move", "x": x, "y": y})

    def _scroll(self, x, y, dx, dy):
        self._append({"type": "scroll", "x": x, "y": y, "dx": dx, "dy": dy})

    def stop(self):
        self.recording = False
        for listener in (self.keyboard_listener, self.mouse_listener):
            if listener:
                listener.stop()
        for listener in (self.keyboard_listener, self.mouse_listener):
            if listener:
                listener.join(timeout=1)
        return sorted(self.events, key=lambda item: item["t"])


class PlaybackWorker(QThread):
    message = Signal(str)

    def __init__(self, events: list[dict], repeats: int, speed: float, jitter_percent: int = 0, move_cursor: bool = True):
        super().__init__()
        self.events = events
        self.repeats = repeats  # zero = infinite
        self.speed = speed
        self.jitter_percent = max(0, min(50, int(jitter_percent)))
        self.move_cursor = move_cursor
        self.stop_event = Event()
        self.pause_event = Event()
        self.pause_event.set()

    def stop(self):
        self.stop_event.set()
        self.pause_event.set()

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()

    @property
    def is_paused(self):
        return not self.pause_event.is_set()

    def _wait_for_resume(self):
        while not self.stop_event.is_set():
            if self.pause_event.wait(0.05):
                return True
        return False

    def _wait_active(self, duration):
        remaining = max(0.0, duration)
        while remaining > 0 and not self.stop_event.is_set():
            if not self.pause_event.wait(0.05):
                continue
            chunk = min(remaining, 0.05)
            began = time.monotonic()
            if self.stop_event.wait(chunk):
                return False
            if self.pause_event.is_set():
                remaining = max(0.0, remaining - (time.monotonic() - began))
        return not self.stop_event.is_set()

    def run(self):
        kb, ms = KeyboardController(), MouseController()
        held_keys, held_buttons = set(), set()
        try:
            loops = 0
            while not self.stop_event.is_set() and (self.repeats == 0 or loops < self.repeats):
                previous = 0.0
                for event in self.events:
                    if self.stop_event.is_set() or not self._wait_for_resume():
                        break
                    target = max(previous, float(event.get("t", 0)) / self.speed)
                    delay = max(0.0, target - previous)
                    if delay and self.jitter_percent:
                        spread = self.jitter_percent / 100.0
                        delay *= random.uniform(1.0 - spread, 1.0 + spread)
                    if not self._wait_active(delay) or not self._wait_for_resume():
                        break
                    previous = target
                    typ = event["type"]
                    if typ.startswith("key_"):
                        raw = event.get("key", "")
                        key = SPECIAL_KEYS.get(raw, raw.lower() if len(raw) == 1 and raw.isalpha() else raw)
                        if typ == "key_down":
                            kb.press(key)
                            held_keys.add(key)
                        else:
                            kb.release(key)
                            held_keys.discard(key)
                    elif typ.startswith("mouse_"):
                        if self.move_cursor and "x" in event and "y" in event:
                            ms.position = (int(event["x"]), int(event["y"]))
                        button = {"left": Button.left, "middle": Button.middle, "right": Button.right}.get(event.get("button"))
                        if button:
                            if typ == "mouse_down":
                                ms.press(button)
                                held_buttons.add(button)
                            else:
                                ms.release(button)
                                held_buttons.discard(button)
                    elif typ == "move" and self.move_cursor:
                        ms.position = (int(event["x"]), int(event["y"]))
                    elif typ == "scroll":
                        ms.scroll(int(event.get("dx", 0)), int(event.get("dy", 0)))
                loops += 1
            self.message.emit("Playback stopped.")
        except Exception as exc:
            self.message.emit(f"Playback error: {exc}")
        finally:
            for key in held_keys:
                try: kb.release(key)
                except Exception: pass
            for button in held_buttons:
                try: ms.release(button)
                except Exception: pass


class MainWindow(QMainWindow):
    hotkey_keyboard_requested = Signal()
    hotkey_mouse_requested = Signal()
    hotkey_record_requested = Signal()
    hotkey_play_start_requested = Signal()
    hotkey_play_stop_requested = Signal()
    hotkey_stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LiteClick — Linux Auto Clicker & Key Presser")
        self.setMinimumSize(900, 650)
        self.worker = None
        self.playback_worker = None
        self.recorder = Recorder(self._record_count_changed)
        self.recorded_events = []
        self.playback_profile_name = "Unsaved recording"
        self.countdown_dialog = None
        self.countdown_timer = None
        self.countdown_remaining = 0
        self._hotkey_listener = None
        self._hotkeys = dict(DEFAULT_HOTKEYS)
        self._load_settings()
        self._active_automation_kind = None
        self.input_combos = {}
        self.interval_spins = {}
        self.start_buttons = {}
        self.stop_buttons = {}
        self.repeat_combos = {}
        self.running_kind = None
        self.hotkey_keyboard_requested.connect(lambda: self._toggle_automation_kind("key"))
        self.hotkey_mouse_requested.connect(lambda: self._toggle_automation_kind("mouse"))
        self.hotkey_record_requested.connect(self.toggle_recording)
        self.hotkey_play_start_requested.connect(self.start_playback)
        self.hotkey_play_stop_requested.connect(self.stop_playback)
        self.hotkey_stop_requested.connect(self._stop_everything)

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(24, 20, 24, 18)
        main.setSpacing(16)

        header = QHBoxLayout()
        titlebox = QVBoxLayout()
        title = QLabel("LiteClick")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Mouse • Keyboard • Macro playback")
        subtitle.setObjectName("Subtitle")
        titlebox.addWidget(title)
        titlebox.addWidget(subtitle)
        header.addLayout(titlebox)
        header.addStretch()
        badge = QLabel("LINUX EDITION  •  v7.5")
        badge.setObjectName("Badge")
        header.addWidget(badge)
        main.addLayout(header)

        self.tabs = QTabWidget()
        self._last_automation_kind = "key"
        self._build_keyboard_tab()
        self._build_mouse_tab()
        self._build_playback_tab()
        self._build_hotkeys_tab()
        self.tabs.currentChanged.connect(self._remember_automation_tab)
        main.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.status = QLabel("● Ready")
        self.status.setObjectName("Status")
        footer.addWidget(self.status)
        footer.addStretch()
        note = QLabel("Tip: test intervals in a safe window first.")
        note.setObjectName("Subtitle")
        footer.addWidget(note)
        main.addLayout(footer)
        self._load_default_playback_profile()
        self._start_hotkey_listener()

    def _panel(self, layout):
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setLayout(layout)
        return panel

    def _build_action_tab(self, kind):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        panel_layout = QVBoxLayout()
        panel_layout.setContentsMargins(18, 18, 18, 18)
        panel_layout.setSpacing(12)
        description = QLabel("Add multiple inputs. Each row has its own delay before the next input is sent.")
        description.setObjectName("Subtitle")
        description.setWordWrap(True)
        panel_layout.addWidget(description)

        controls = QHBoxLayout()
        input_combo = QComboBox()
        input_combo.setEditable(kind == "key")
        if kind == "key":
            input_combo.addItems(["1", "2", "3", "4", "5", "Q", "W", "E", "R", "A", "S", "D", "Space", "Enter", "Tab", "Shift", "Ctrl", "Alt", "Esc", "F1", "F2", "F3", "F4", "F5"])
            input_combo.setToolTip("Choose a key or type one character / supported special key")
        else:
            input_combo.addItems(list(BUTTONS.keys()))
        interval_spin = QSpinBox()
        interval_spin.setRange(10, 60000)
        interval_spin.setValue(500 if kind == "key" else 100)
        interval_spin.setSuffix(" ms delay")
        self.input_combos[kind] = input_combo
        self.interval_spins[kind] = interval_spin
        add = QPushButton("＋ Add input")
        add.setObjectName("AccentButton")
        add.clicked.connect(lambda: self._add_action_row(kind))
        controls.addWidget(QLabel("Input"))
        controls.addWidget(input_combo, 1)
        if kind == "key":
            capture = QPushButton("Capture key…")
            capture.clicked.connect(lambda checked=False, combo=input_combo: self._capture_key(combo))
            controls.addWidget(capture)
        controls.addWidget(interval_spin)
        controls.addWidget(add)
        panel_layout.addLayout(controls)

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Input", "Delay after input (ms)", "Enabled"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        table.setMinimumHeight(210)
        panel_layout.addWidget(table)
        setattr(self, f"{kind}_table", table)
        actions = QHBoxLayout()
        remove = QPushButton("Remove selected")
        clear = QPushButton("Clear list")
        remove.clicked.connect(lambda: self._remove_selected(table))
        clear.clicked.connect(lambda checked=False, t=table: t.setRowCount(0))
        actions.addWidget(remove)
        actions.addWidget(clear)
        up = QPushButton("↑ Move up")
        down = QPushButton("↓ Move down")
        up.clicked.connect(lambda: self._move_selected(table, -1))
        down.clicked.connect(lambda: self._move_selected(table, 1))
        actions.addWidget(up)
        actions.addWidget(down)
        if kind == "key":
            save_profile = QPushButton("Save keyboard profile…")
            load_profile = QPushButton("Load keyboard profile…")
            save_profile.clicked.connect(lambda: self.save_input_profile("key"))
            load_profile.clicked.connect(lambda: self.load_input_profile("key"))
            actions.addWidget(save_profile)
            actions.addWidget(load_profile)
        actions.addStretch()
        panel_layout.addLayout(actions)
        layout.addWidget(self._panel(panel_layout), 1)

        run_panel_layout = QHBoxLayout()
        run_panel_layout.setContentsMargins(18, 12, 18, 12)
        repeat_combo = QComboBox()
        repeat_combo.addItems(["Infinite", "1 cycle", "10 cycles", "100 cycles", "500 cycles", "1000 cycles"])
        self.repeat_combos[kind] = repeat_combo
        start = QPushButton(f"▶  Start all enabled inputs  [{self._hotkeys['keyboard' if kind == 'key' else 'mouse']}]")
        start.setObjectName("StartButton")
        stop = QPushButton("■  Stop")
        stop.setObjectName("StopButton")
        stop.setEnabled(False)
        start.clicked.connect(lambda checked=False, k=kind: self.start_automation(k))
        stop.clicked.connect(self.stop_automation)
        self.start_buttons[kind], self.stop_buttons[kind] = start, stop
        run_panel_layout.addWidget(QLabel("Repeat"))
        run_panel_layout.addWidget(repeat_combo)
        run_panel_layout.addStretch()
        run_panel_layout.addWidget(start)
        run_panel_layout.addWidget(stop)
        layout.addWidget(self._panel(run_panel_layout))
        return page

    def _build_keyboard_tab(self):
        self.tabs.addTab(self._build_action_tab("key"), "⌨ Keyboard")
        # Keep a safe, obvious starter example, but do not run until Start is pressed.
        self._insert_row(self.key_table, "1", 500)

    def _build_mouse_tab(self):
        self.tabs.addTab(self._build_action_tab("mouse"), "🖱 Mouse")
        self._insert_row(self.mouse_table, "Left click", 100)

    def _insert_row(self, table, value, interval):
        row = table.rowCount()
        table.insertRow(row)
        input_item = QTableWidgetItem(value)
        input_item.setFlags(input_item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, 0, input_item)
        delay = QSpinBox()
        delay.setRange(10, 60000)
        delay.setValue(int(interval))
        delay.setSuffix(" ms")
        delay.setToolTip("Delay after this input before the next input")
        table.setCellWidget(row, 1, delay)
        enabled = QCheckBox()
        enabled.setChecked(True)
        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setAlignment(Qt.AlignCenter)
        holder_layout.addWidget(enabled)
        table.setCellWidget(row, 2, holder)
        table.item(row, 0).setData(Qt.UserRole, int(interval))

    def _row_interval(self, table, row):
        widget = table.cellWidget(row, 1)
        if isinstance(widget, QSpinBox):
            return widget.value()
        item = table.item(row, 1)
        try:
            return int(item.text().split()[0]) if item else 100
        except (ValueError, IndexError):
            return 100

    def _move_selected(self, table, direction):
        selected = table.selectionModel().selectedRows()
        if not selected:
            return
        row = selected[0].row()
        target = row + direction
        if target < 0 or target >= table.rowCount():
            return

        entries = []
        for current in range(table.rowCount()):
            item = table.item(current, 0)
            holder = table.cellWidget(current, 2)
            check = holder.findChild(QCheckBox) if holder else None
            entries.append((item.text() if item else "", self._row_interval(table, current), check.isChecked() if check else True))
        entries[row], entries[target] = entries[target], entries[row]
        table.setRowCount(0)
        for value, interval, enabled in entries:
            self._insert_row(table, value, interval)
            holder = table.cellWidget(table.rowCount() - 1, 2)
            checkbox = holder.findChild(QCheckBox) if holder else None
            if checkbox:
                checkbox.setChecked(enabled)
        table.selectRow(target)

    def _insert_row_at_existing(self, table, row, value, interval, enabled):
        input_item = QTableWidgetItem(value)
        input_item.setFlags(input_item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, 0, input_item)
        delay = QSpinBox()
        delay.setRange(10, 60000)
        delay.setValue(int(interval))
        delay.setSuffix(" ms")
        table.setCellWidget(row, 1, delay)
        checkbox = QCheckBox()
        checkbox.setChecked(bool(enabled))
        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setAlignment(Qt.AlignCenter)
        holder_layout.addWidget(checkbox)
        table.setCellWidget(row, 2, holder)

    def _capture_key(self, combo):
        dialog = KeyCaptureDialog(self)
        if dialog.exec() == QDialog.Accepted and dialog.captured_key:
            combo.setCurrentText(dialog.captured_key)
            self.status.setText(f"● Captured key: {dialog.captured_key}")

    def save_input_profile(self, kind):
        table = self.key_table if kind == "key" else self.mouse_table
        default_name = f"{kind}-profile.json"
        path, _ = QFileDialog.getSaveFileName(self, "Save input profile", str(PROFILE_DIR / default_name), "LiteClick profile (*.json)")
        if not path:
            return
        rows = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if not item:
                continue
            holder = table.cellWidget(row, 2)
            checkbox = holder.findChild(QCheckBox) if holder else None
            rows.append({"input": item.text(), "interval": self._row_interval(table, row), "enabled": checkbox.isChecked() if checkbox else True})
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps({"format": "liteclick-input-profile-v1", "kind": kind, "actions": rows}, indent=2), encoding="utf-8")
            self.status.setText("● Input profile saved")
        except OSError as exc:
            QMessageBox.critical(self, "Save profile failed", str(exc))

    def load_input_profile(self, kind):
        path, _ = QFileDialog.getOpenFileName(self, "Load input profile", str(PROFILE_DIR), "LiteClick profile (*.json);;JSON files (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            rows = data.get("actions") if isinstance(data, dict) and data.get("kind") == kind else None
            if not isinstance(rows, list):
                raise ValueError(f"Choose a valid {kind} input profile.")
            table = self.key_table if kind == "key" else self.mouse_table
            validated = []
            for row in rows:
                value = str(row["input"])
                interval = int(row.get("interval", 100))
                if not 10 <= interval <= 60000:
                    raise ValueError("Profile intervals must be between 10 and 60000 ms.")
                if kind == "key":
                    resolve_key(value)
                elif value not in BUTTONS:
                    raise ValueError(f"Unsupported mouse input: {value}")
                validated.append((value, interval, bool(row.get("enabled", True))))
            table.setRowCount(0)
            for value, interval, enabled in validated:
                self._insert_row(table, value, interval)
                holder = table.cellWidget(table.rowCount() - 1, 2)
                checkbox = holder.findChild(QCheckBox) if holder else None
                if checkbox:
                    checkbox.setChecked(enabled)
            self.status.setText(f"● Loaded {kind} profile")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "Load profile failed", str(exc))

    def _add_action_row(self, kind):
        table = self.key_table if kind == "key" else self.mouse_table
        value = self.input_combos[kind].currentText().strip()
        if not value:
            self.status.setText("● Choose an input first")
            return
        if kind == "key":
            try:
                resolve_key(value)
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid key", str(exc))
                return
        elif value not in BUTTONS:
            return
        self._insert_row(table, value, self.interval_spins[kind].value())
        self.status.setText(f"● Added {value}")

    def _remove_selected(self, table):
        rows = sorted({index.row() for index in table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            table.removeRow(row)

    def _remember_automation_tab(self, index):
        if index == 0:
            self._last_automation_kind = "key"
        elif index == 1:
            self._last_automation_kind = "mouse"

    def _collect_actions(self, requested_kind=None):
        actions = []
        current = self.tabs.currentIndex()
        active_kind = requested_kind or ("key" if current == 0 else "mouse" if current == 1 else self._last_automation_kind)
        tables = [(self.key_table, "key")] if active_kind == "key" else [(self.mouse_table, "mouse")]
        for table, kind in tables:
            for row in range(table.rowCount()):
                holder = table.cellWidget(row, 2)
                checkbox = holder.findChild(QCheckBox) if holder else None
                if checkbox and not checkbox.isChecked():
                    continue
                item = table.item(row, 0)
                if not item:
                    continue
                actions.append({"kind": kind, "input": item.text(), "interval": self._row_interval(table, row)})
        return actions

    def start_automation(self, requested_kind=None):
        if self.worker and self.worker.isRunning():
            return
        actions = self._collect_actions(requested_kind)
        if not actions:
            QMessageBox.information(self, "No inputs", "Add and enable at least one keyboard or mouse input first.")
            return
        active_kind = requested_kind or ("key" if self.tabs.currentIndex() == 0 else "mouse" if self.tabs.currentIndex() == 1 else self._last_automation_kind)
        label = self.repeat_combos[active_kind].currentText()
        repeats = 0 if label == "Infinite" else int(label.split()[0])
        self._active_automation_kind = active_kind
        self.worker = AutomationWorker(actions, repeats)
        self.worker.message.connect(self._automation_finished)
        self.worker.finished.connect(self._automation_thread_finished)
        self.running_kind = active_kind
        for kind, button in self.start_buttons.items():
            button.setEnabled(kind != active_kind)
            button.setProperty("running", kind == active_kind)
            button.setObjectName("ActiveButton" if kind == active_kind else "StartButton")
            button.setText(("● KEYBOARD RUNNING" if kind == "key" else "● MOUSE RUNNING") + f"  [{self._hotkeys['keyboard' if kind == 'key' else 'mouse']}]" if kind == active_kind else ("▶ Start keyboard" if kind == "key" else "▶ Start mouse") + f"  [{self._hotkeys['keyboard' if kind == 'key' else 'mouse']}]" )
            button.style().unpolish(button); button.style().polish(button)
        for button in self.stop_buttons.values(): button.setEnabled(True)
        self.status.setText(f"● {active_kind.title()} automation running")
        self.worker.start()

    def stop_automation(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status.setText("● Stopping automation…")

    def _automation_finished(self, message):
        self.status.setText("● " + message)

    def _automation_thread_finished(self):
        for kind, button in self.start_buttons.items():
            button.setEnabled(True)
            button.setProperty("running", False)
            button.setObjectName("StartButton")
            button.setText(("▶ Start keyboard" if kind == "key" else "▶ Start mouse") + f"  [{self._hotkeys['keyboard' if kind == 'key' else 'mouse']}]" )
            button.style().unpolish(button); button.style().polish(button)
        for button in self.stop_buttons.values(): button.setEnabled(False)
        self.running_kind = None
        self.worker = None

    def _build_playback_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        panel_layout = QVBoxLayout()
        panel_layout.setContentsMargins(20, 20, 20, 20)
        heading = QLabel("Macro recorder")
        heading.setObjectName("SectionTitle")
        desc = QLabel("Record keyboard presses, mouse clicks, cursor movement and scrolling, then replay the sequence with its original timing.")
        desc.setObjectName("Subtitle")
        desc.setWordWrap(True)
        panel_layout.addWidget(heading)
        panel_layout.addWidget(desc)
        self.record_count = QLabel("Recorded events: 0")
        panel_layout.addWidget(self.record_count)
        row = QHBoxLayout()
        self.record_button = QPushButton(f"● Start recording  [{self._hotkeys['record']}]")
        self.record_button.setObjectName("StopButton")
        self.record_button.clicked.connect(self.toggle_recording)
        self.play_button = QPushButton(f"▶ Start playback  [{self._hotkeys['play_start']}]")
        self.play_button.setObjectName("StartButton")
        self.play_button.clicked.connect(self.start_playback)
        self.pause_playback_button = QPushButton("Ⅱ Pause")
        self.pause_playback_button.setEnabled(False)
        self.pause_playback_button.clicked.connect(self.pause_resume_playback)
        self.stop_playback_button = QPushButton(f"■ Stop playback  [{self._hotkeys['play_stop']}]")
        self.stop_playback_button.setEnabled(False)
        self.stop_playback_button.clicked.connect(self.stop_playback)
        row.addWidget(self.record_button)
        row.addWidget(self.play_button)
        row.addWidget(self.pause_playback_button)
        row.addWidget(self.stop_playback_button)
        panel_layout.addLayout(row)

        form = QFormLayout()
        self.play_repeat = QComboBox()
        self.play_repeat.addItems(["1 time", "2 times", "5 times", "10 times", "Infinite"])
        self.play_speed = QComboBox()
        self.play_speed.addItems(["0.5× slower", "0.75× slower", "1× original", "1.25× faster", "1.5× faster", "2× faster"])
        self.jitter_spin = QSpinBox()
        self.jitter_spin.setRange(0, 50)
        self.jitter_spin.setValue(0)
        self.jitter_spin.setSuffix(" % variation")
        self.jitter_spin.setToolTip("Randomly vary each recorded wait by up to this percentage. Set to 0 for exact timing.")
        self.move_cursor_check = QCheckBox("Replay cursor movement")
        self.move_cursor_check.setChecked(True)
        form.addRow("Playback repetitions:", self.play_repeat)
        form.addRow("Playback speed:", self.play_speed)
        form.addRow("Timing variation:", self.jitter_spin)
        form.addRow("Cursor:", self.move_cursor_check)
        panel_layout.addLayout(form)
        files = QHBoxLayout()
        save = QPushButton("Save playback profile…")
        load = QPushButton("Load playback profile…")
        rename_profile = QPushButton("Rename saved profile…")
        export_log = QPushButton("Export event log (.md/.txt)…")
        set_default = QPushButton("Set as default")
        save.setToolTip("Save the recorded events together with repeat, speed, timing, and cursor settings.")
        export_log.setToolTip("Export a human-readable list of recorded events. Markdown/text logs are for viewing; use a JSON profile to replay.")
        save.clicked.connect(self.save_recording)
        load.clicked.connect(self.load_recording)
        rename_profile.clicked.connect(self.rename_playback_profile)
        export_log.clicked.connect(self.export_event_log)
        set_default.clicked.connect(self.set_default_playback_profile)
        files.addWidget(save)
        files.addWidget(load)
        files.addWidget(rename_profile)
        files.addWidget(export_log)
        files.addWidget(set_default)
        files.addStretch()
        panel_layout.addLayout(files)
        warning = QLabel("Playback sends real input to your desktop and can move the cursor. Stop it before interacting normally. Only record actions in apps/games where automation is permitted.")
        warning.setObjectName("Warning")
        warning.setWordWrap(True)
        panel_layout.addWidget(warning)
        layout.addWidget(self._panel(panel_layout))
        layout.addStretch()
        self.tabs.addTab(page, "⏺ Playback")

    def _record_count_changed(self, count):
        # Listener callbacks run outside the UI thread; only update a queued signal would be ideal.
        # The count is also refreshed when recording stops, avoiding cross-thread widget access.
        self._pending_record_count = count

    def toggle_recording(self):
        if not self.recorder.recording:
            if self.worker and self.worker.isRunning():
                QMessageBox.information(self, "Automation running", "Stop automation before recording a macro.")
                return
            if self.playback_worker and self.playback_worker.isRunning():
                QMessageBox.information(self, "Playback running", "Stop playback before recording a macro.")
                return
            self.playback_profile_name = "New recording"
            self.recorder.start()
            self.record_button.setText(f"● RECORDING — click to stop  [{self._hotkeys['record']}]")
            self.record_button.setObjectName("ActiveButton")
            self.record_button.style().unpolish(self.record_button); self.record_button.style().polish(self.record_button)
            self.status.setText("● Recording input…")
        else:
            self.recorded_events = self.recorder.stop()
            self.record_count.setText(f"Recorded events: {len(self.recorded_events)}")
            self.record_button.setText(f"● Start recording  [{self._hotkeys['record']}]")
            self.record_button.setObjectName("StopButton")
            self.record_button.style().unpolish(self.record_button); self.record_button.style().polish(self.record_button)
            self.status.setText("● Recording saved in memory")

    def _speed_value(self):
        return {"0.5× slower": 0.5, "0.75× slower": 0.75, "1× original": 1.0,
                "1.25× faster": 1.25, "1.5× faster": 1.5, "2× faster": 2.0}[self.play_speed.currentText()]

    def start_playback(self):
        if self.playback_worker and self.playback_worker.isRunning():
            return
        if self.countdown_timer and self.countdown_timer.isActive():
            return
        if self.recorder.recording:
            QMessageBox.information(self, "Recording", "Stop recording before replaying.")
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Automation running", "Stop automation before replaying a macro.")
            return
        if not self.recorded_events:
            QMessageBox.information(self, "No recording", "Record a sequence or load a recording first.")
            return
        self.play_button.setEnabled(False)
        self.pause_playback_button.setEnabled(False)
        self.stop_playback_button.setEnabled(True)
        self._show_playback_countdown(3)
        self.status.setText(f"● {self.playback_profile_name} starts in 3…")

    def _show_playback_countdown(self, seconds=3):
        self.countdown_remaining = seconds
        if self.countdown_dialog is None:
            self.countdown_dialog = QDialog(self)
            self.countdown_dialog.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
            self.countdown_dialog.setFixedSize(170, 76)
            self.countdown_dialog.setWindowTitle(self.playback_profile_name)
            box = QVBoxLayout(self.countdown_dialog)
            box.setContentsMargins(8, 5, 8, 5)
            self.countdown_label = QLabel()
            self.countdown_label.setAlignment(Qt.AlignCenter)
            self.countdown_label.setStyleSheet("font-size: 22pt; font-weight: bold;")
            box.addWidget(self.countdown_label)
            self.countdown_dialog.setStyleSheet("QDialog { background:#202630; color:white; border:1px solid #4c5668; border-radius:7px; } QLabel { color:white; }")
        self.countdown_dialog.setWindowTitle(self.playback_profile_name)
        self.countdown_label.setText(str(seconds))
        self.countdown_dialog.show()
        self.countdown_dialog.raise_()
        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self._countdown_tick)
        self.countdown_timer.start()

    def _countdown_tick(self):
        self.countdown_remaining -= 1
        if self.countdown_remaining <= 0:
            self.countdown_timer.stop()
            if self.countdown_dialog:
                self.countdown_dialog.setWindowTitle(self.playback_profile_name)
                self.countdown_label.setText("▶")
            self._begin_playback()
        else:
            self.countdown_label.setText(str(self.countdown_remaining))

    def _begin_playback(self):
        label = self.play_repeat.currentText()
        repeats = 0 if label == "Infinite" else int(label.split()[0])
        self.playback_worker = PlaybackWorker(self.recorded_events, repeats, self._speed_value(), self.jitter_spin.value(), self.move_cursor_check.isChecked())
        self.playback_worker.message.connect(lambda msg: self.status.setText("● " + msg))
        self.playback_worker.finished.connect(self._playback_finished)
        self.pause_playback_button.setEnabled(True)
        self.pause_playback_button.setText("Ⅱ Pause")
        self.play_button.setEnabled(False)
        self.play_button.setProperty("running", True)
        self.play_button.setObjectName("ActiveButton")
        self.play_button.setText(f"● PLAYBACK RUNNING  [{self._hotkeys['play_start']}]")
        self.play_button.style().unpolish(self.play_button); self.play_button.style().polish(self.play_button)
        self.stop_playback_button.setEnabled(True)
        self.status.setText(f"● Playing: {self.playback_profile_name}")
        if self.countdown_dialog:
            self.countdown_dialog.setWindowTitle(self.playback_profile_name)
            self.countdown_label.setText("▶")
            self.countdown_dialog.show()
            self.countdown_dialog.raise_()
        self.playback_worker.start()

    def pause_resume_playback(self):
        if not self.playback_worker or not self.playback_worker.isRunning():
            return
        if self.playback_worker.is_paused:
            self.playback_worker.resume()
            self.pause_playback_button.setText("Ⅱ Pause")
            self.status.setText(f"● Playing: {self.playback_profile_name}")
            if self.countdown_dialog:
                self.countdown_dialog.setWindowTitle(self.playback_profile_name)
                self.countdown_label.setText("▶")
        else:
            self.playback_worker.pause()
            self.pause_playback_button.setText("▶ Resume")
            self.status.setText(f"● Paused: {self.playback_profile_name}")
            if self.countdown_dialog:
                self.countdown_dialog.setWindowTitle(f"Paused — {self.playback_profile_name}")
                self.countdown_label.setText("Ⅱ")
                self.countdown_dialog.show()
                self.countdown_dialog.raise_()

    def stop_playback(self):
        if self.countdown_timer and self.countdown_timer.isActive():
            self.countdown_timer.stop()
            if self.countdown_dialog:
                self.countdown_dialog.hide()
            self.play_button.setEnabled(True)
            self.pause_playback_button.setEnabled(False)
            self.stop_playback_button.setEnabled(False)
            self.status.setText("● Playback countdown cancelled")
        if self.playback_worker and self.playback_worker.isRunning():
            self.playback_worker.stop()
            if self.countdown_dialog:
                self.countdown_dialog.hide()
            self.status.setText("● Stopping playback…")

    def _playback_finished(self):
        self.play_button.setEnabled(True)
        self.play_button.setProperty("running", False)
        self.play_button.setObjectName("StartButton")
        self.play_button.setText(f"▶ Start playback  [{self._hotkeys['play_start']}]")
        self.play_button.style().unpolish(self.play_button); self.play_button.style().polish(self.play_button)
        self.pause_playback_button.setEnabled(False)
        self.pause_playback_button.setText("Ⅱ Pause")
        self.stop_playback_button.setEnabled(False)
        if self.countdown_dialog:
            self.countdown_dialog.hide()
        self.playback_worker = None

    def set_default_playback_profile(self):
        if not self.recorded_events:
            QMessageBox.information(self, "No recording", "Load or record a playback profile first.")
            return
        try:
            DEFAULT_PLAYBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = self._playback_profile_data()
            data["name"] = self.playback_profile_name
            DEFAULT_PLAYBACK_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self.status.setText(f"● Default playback profile set: {self.playback_profile_name}")
        except OSError as exc:
            QMessageBox.critical(self, "Default profile failed", str(exc))

    def _load_default_playback_profile(self):
        if not DEFAULT_PLAYBACK_FILE.exists():
            return
        try:
            self._apply_playback_profile(json.loads(DEFAULT_PLAYBACK_FILE.read_text(encoding="utf-8")))
            self.status.setText(f"● Default profile loaded: {self.playback_profile_name}")
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.status.setText(f"● Could not load default profile: {exc}")

    def _apply_playback_profile(self, data):
        events = data.get("events") if isinstance(data, dict) else None
        if not isinstance(events, list) or any(not isinstance(event, dict) or "type" not in event for event in events):
            raise ValueError("This file is not a valid LiteClick playback profile or recording.")
        for event in events:
            float(event.get("t", 0))
        self.recorded_events = sorted(events, key=lambda item: float(item.get("t", 0)))
        self.playback_profile_name = str(data.get("name") or "Loaded playback profile")
        playback = data.get("playback", {})
        if isinstance(playback, dict):
            repeat = playback.get("repeat")
            if repeat in [self.play_repeat.itemText(i) for i in range(self.play_repeat.count())]:
                self.play_repeat.setCurrentText(repeat)
            speed = playback.get("speed")
            if speed in [self.play_speed.itemText(i) for i in range(self.play_speed.count())]:
                self.play_speed.setCurrentText(speed)
            variation = playback.get("timing_variation_percent")
            if isinstance(variation, (int, float)):
                self.jitter_spin.setValue(max(self.jitter_spin.minimum(), min(self.jitter_spin.maximum(), int(variation))))
            cursor = playback.get("replay_cursor_movement")
            if isinstance(cursor, bool):
                self.move_cursor_check.setChecked(cursor)
        self.record_count.setText(f"Recorded events: {len(self.recorded_events)}")

    def _playback_profile_data(self):
        """Build a portable, replayable profile containing events and playback settings."""
        return {
            "format": "liteclick-playback-profile-v1",
            "name": "Playback profile",
            "created_by": "LiteClick",
            "events": self.recorded_events,
            "playback": {
                "repeat": self.play_repeat.currentText(),
                "speed": self.play_speed.currentText(),
                "timing_variation_percent": self.jitter_spin.value(),
                "replay_cursor_movement": self.move_cursor_check.isChecked(),
            },
        }

    def save_recording(self):
        if not self.recorded_events:
            QMessageBox.information(self, "No recording", "Record or load a sequence first.")
            return
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save playback profile", str(PROFILE_DIR / "playback-profile.json"),
            "LiteClick playback profile (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            profile_data = self._playback_profile_data()
            profile_data["name"] = target.stem
            self.playback_profile_name = target.stem
            target.write_text(json.dumps(profile_data, indent=2, ensure_ascii=False), encoding="utf-8")
            self.status.setText(f"● Playback profile saved: {target.stem}")
        except OSError as exc:
            QMessageBox.critical(self, "Save profile failed", str(exc))

    def rename_playback_profile(self):
        """Rename a saved JSON playback profile and keep its embedded name in sync."""
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose playback profile to rename", str(PROFILE_DIR),
            "LiteClick playback profile (*.json);;JSON files (*.json)"
        )
        if not path:
            return

        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("events"), list):
                raise ValueError("This file does not look like a LiteClick playback profile.")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "Cannot rename profile", str(exc))
            return

        current_name = str(data.get("name") or source.stem)
        new_name, accepted = QInputDialog.getText(
            self, "Rename playback profile", "New profile name:", text=current_name
        )
        if not accepted:
            return
        new_name = new_name.strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid name", "Enter a profile name.")
            return
        # Keep names portable and prevent path separators or hidden path tricks.
        safe_stem = re.sub(r"[^A-Za-z0-9 _().-]+", "_", new_name).strip(" .")
        if not safe_stem:
            QMessageBox.warning(self, "Invalid name", "That profile name cannot be used as a filename.")
            return
        destination = source.with_name(safe_stem + ".json")
        if destination != source and destination.exists():
            QMessageBox.warning(self, "Name already exists", f"A profile named '{safe_stem}' already exists.")
            return
        try:
            data["name"] = new_name
            # Write first, then rename; if the filename changes, keep the JSON and filename aligned.
            temp = source.with_name(source.name + ".tmp")
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            if destination != source:
                temp.replace(destination)
                source.unlink()
            else:
                temp.replace(source)
            self.status.setText(f"● Renamed playback profile to {new_name}")
            QMessageBox.information(self, "Profile renamed", f"Playback profile renamed to '{new_name}'.")
        except OSError as exc:
            QMessageBox.critical(self, "Rename failed", str(exc))

    def load_recording(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load playback profile", str(PROFILE_DIR),
            "LiteClick playback profile (*.json);;JSON files (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, dict) and not data.get("name"):
                data["name"] = Path(path).stem
            self._apply_playback_profile(data)
            self.status.setText(f"● Playback profile loaded: {self.playback_profile_name}")
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "Load failed", str(exc))

    @staticmethod
    def _describe_event(event):
        kind = str(event.get("type", "unknown"))
        t = float(event.get("t", 0))
        if kind in ("key_down", "key_up"):
            action = "Key down" if kind == "key_down" else "Key up"
            detail = str(event.get("key", "?"))
        elif kind in ("mouse_down", "mouse_up"):
            action = "Mouse button down" if kind == "mouse_down" else "Mouse button up"
            detail = f"{event.get('button', '?')} at ({event.get('x', '?')}, {event.get('y', '?')})"
        elif kind == "move":
            action, detail = "Cursor move", f"({event.get('x', '?')}, {event.get('y', '?')})"
        elif kind == "scroll":
            action, detail = "Scroll", f"at ({event.get('x', '?')}, {event.get('y', '?')}), dx={event.get('dx', 0)}, dy={event.get('dy', 0)}"
        else:
            action, detail = kind.replace("_", " ").title(), str({k: v for k, v in event.items() if k not in ("type", "t")})
        return t, action, detail

    def export_event_log(self):
        if not self.recorded_events:
            QMessageBox.information(self, "No events", "Record or load a playback profile first.")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export event log", str(PROFILE_DIR / "event-log.md"),
            "Markdown document (*.md);;Plain text (*.txt)"
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix not in (".md", ".txt"):
            suffix = ".md" if "Markdown" in selected_filter else ".txt"
            path += suffix
        try:
            lines = []
            if suffix == ".md":
                lines.extend(["# LiteClick Playback Event Log", "", f"- Events: {len(self.recorded_events)}", f"- Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}", "", "| # | Time (s) | Event | Details |", "|---:|---:|---|---|"])
                for i, event in enumerate(self.recorded_events, 1):
                    t, action, detail = self._describe_event(event)
                    safe_detail = detail.replace("|", "\\|").replace("\n", " ")
                    lines.append(f"| {i} | {t:.4f} | {action} | {safe_detail} |")
                lines.extend(["", "> This is a human-readable event log, not a replayable file. Save a JSON playback profile to replay these events."])
            else:
                lines.extend(["LiteClick Playback Event Log", "=" * 29, f"Events: {len(self.recorded_events)}", f"Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}", "", "#   Time (s)    Event                 Details", "-" * 72])
                for i, event in enumerate(self.recorded_events, 1):
                    t, action, detail = self._describe_event(event)
                    lines.append(f"{i:4d}  {t:10.4f}  {action:<21} {detail}")
                lines.extend(["", "Note: This text log is for viewing only. Save a JSON playback profile to replay events."])
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.status.setText("● Event log exported")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _build_hotkeys_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        box_layout = QVBoxLayout()
        box_layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Custom global hotkeys")
        title.setObjectName("SectionTitle")
        box_layout.addWidget(title)
        text = QLabel(
            "Every main action has its own customizable global hotkey. Keyboard and mouse hotkeys toggle their own automation on/off. "
            "Recording hotkey starts or stops recording; playback start and stop are deliberately separate actions. "
            "Hotkeys are shown beside their buttons. Use a unique combination for each action."
        )
        text.setWordWrap(True)
        text.setObjectName("Subtitle")
        box_layout.addWidget(text)
        form = QFormLayout()
        self.hotkey_edits = {}
        descriptions = [
            ("keyboard", "Toggle keyboard automation (default F6)"),
            ("mouse", "Toggle mouse automation (default F8)"),
            ("record", "Start / stop recording (default Ctrl+1)"),
            ("play_start", "Start playback only (default Ctrl+2)"),
            ("play_stop", "Stop playback only (default Ctrl+3)"),
            ("stop_all", "Emergency stop all (default Ctrl+0)"),
        ]
        for key, label in descriptions:
            edit = QLineEdit(self._hotkeys.get(key, DEFAULT_HOTKEYS[key]))
            edit.setPlaceholderText("e.g. Ctrl+Shift+K or F6")
            edit.setToolTip("Use modifiers Ctrl, Alt, Shift, Super and a key, e.g. Ctrl+3 or F8.")
            self.hotkey_edits[key] = edit
            form.addRow(label + ":", edit)
        box_layout.addLayout(form)
        buttons = QHBoxLayout()
        apply_button = QPushButton("Save and apply hotkeys")
        apply_button.setObjectName("AccentButton")
        apply_button.clicked.connect(self._save_hotkeys)
        reset_button = QPushButton("Reset defaults")
        reset_button.clicked.connect(self._reset_hotkeys)
        buttons.addWidget(apply_button)
        buttons.addWidget(reset_button)
        buttons.addStretch()
        box_layout.addLayout(buttons)
        self.hotkey_status = QLabel("Hotkey listener: starting…")
        self.hotkey_status.setWordWrap(True)
        box_layout.addWidget(self.hotkey_status)
        layout.addWidget(self._panel(box_layout))
        layout.addStretch()
        self.tabs.addTab(page, "⌘ Hotkeys")

    def _load_settings(self):
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            saved = data.get("hotkeys", {}) if isinstance(data, dict) else {}
            if isinstance(saved, dict):
                for key in DEFAULT_HOTKEYS:
                    if isinstance(saved.get(key), str) and saved[key].strip():
                        self._hotkeys[key] = saved[key].strip()
                # Migrate older v2 settings without breaking the saved choices.
                if "keyboard" in saved and "mouse" in saved and "stop" in saved and "stop_all" not in saved:
                    self._hotkeys["stop_all"] = saved.get("stop", DEFAULT_HOTKEYS["stop_all"])
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    @staticmethod
    def _pynput_hotkey(value):
        parts = [part.strip() for part in value.split("+") if part.strip()]
        if not parts:
            raise ValueError("Hotkey cannot be empty.")
        converted = []
        modifier_names = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift", "super": "cmd", "meta": "cmd"}
        for part in parts:
            low = part.lower()
            if low in modifier_names:
                converted.append(f"<{modifier_names[low]}>")
            elif low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
                converted.append(f"<{low}>")
            elif low in {"space", "enter", "tab", "esc", "escape", "backspace", "delete", "home", "end", "pageup", "pagedown", "up", "down", "left", "right"}:
                aliases = {"escape": "esc", "pageup": "page_up", "pagedown": "page_down"}
                converted.append(f"<{aliases.get(low, low)}>")
            elif len(part) == 1:
                converted.append(part.lower())
            else:
                raise ValueError(f"Unsupported hotkey part: {part}")
        if converted[-1] in {"<ctrl>", "<alt>", "<shift>", "<cmd>"}:
            raise ValueError("Add a non-modifier key after Ctrl/Alt/Shift/Super.")
        return "+".join(converted)

    def _save_hotkeys(self):
        candidate = {key: edit.text().strip() for key, edit in self.hotkey_edits.items()}
        try:
            normalized = {key: self._pynput_hotkey(value) for key, value in candidate.items()}
            if len(set(normalized.values())) != len(normalized):
                raise ValueError("Each action must have a different hotkey.")
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({"hotkeys": candidate}, indent=2), encoding="utf-8")
            self._hotkeys = candidate
            self._start_hotkey_listener()
            self._refresh_hotkey_button_labels()
            self.status.setText("● Global hotkeys saved")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Invalid hotkeys", str(exc))

    def _refresh_hotkey_button_labels(self):
        if hasattr(self, "record_button"):
            self.record_button.setText(
                f"● {'Stop recording' if self.recorder.recording else 'Start recording'}  [{self._hotkeys['record']}]"
            )
        if hasattr(self, "play_button"):
            running = bool(self.playback_worker and self.playback_worker.isRunning())
            self.play_button.setText(f"● PLAYBACK RUNNING  [{self._hotkeys['play_start']}]" if running else f"▶ Start playback  [{self._hotkeys['play_start']}]" )
        if hasattr(self, "stop_playback_button"):
            self.stop_playback_button.setText(f"■ Stop playback  [{self._hotkeys['play_stop']}]")
        for kind, button in getattr(self, "start_buttons", {}).items():
            button.setText(("● KEYBOARD RUNNING" if kind == "key" else "● MOUSE RUNNING") + f"  [{self._hotkeys['keyboard' if kind == 'key' else 'mouse']}]" if self.running_kind == kind else ("▶ Start keyboard" if kind == "key" else "▶ Start mouse") + f"  [{self._hotkeys['keyboard' if kind == 'key' else 'mouse']}]" )

    def _reset_hotkeys(self):
        for key, edit in self.hotkey_edits.items():
            edit.setText(DEFAULT_HOTKEYS[key])
        self._save_hotkeys()

    def _start_hotkey_listener(self):
        if self._hotkey_listener:
            try:
                self._hotkey_listener.stop()
                self._hotkey_listener.join(timeout=1)
            except Exception:
                pass
            self._hotkey_listener = None
        try:
            callbacks = {
                self._pynput_hotkey(self._hotkeys["keyboard"]): self._hotkey_keyboard,
                self._pynput_hotkey(self._hotkeys["mouse"]): self._hotkey_mouse,
                self._pynput_hotkey(self._hotkeys["record"]): self._hotkey_record,
                self._pynput_hotkey(self._hotkeys["play_start"]): self._hotkey_play_start,
                self._pynput_hotkey(self._hotkeys["play_stop"]): self._hotkey_play_stop,
                self._pynput_hotkey(self._hotkeys["stop_all"]): self._hotkey_stop,
            }
            if len(callbacks) != len(self._hotkeys):
                raise ValueError("Hotkeys must be unique.")
            self._hotkey_listener = keyboard.GlobalHotKeys(callbacks)
            self._hotkey_listener.start()
            self.hotkey_status.setText("Hotkey listener active: " + " • ".join(
                f"{name.replace('_', ' ').title()}: {self._hotkeys[name]}" for name in DEFAULT_HOTKEYS
            ))
        except Exception as exc:
            if hasattr(self, "hotkey_status"):
                self.hotkey_status.setText(f"Hotkey listener unavailable: {exc}")

    def _hotkey_keyboard(self):
        self.hotkey_keyboard_requested.emit()

    def _hotkey_mouse(self):
        self.hotkey_mouse_requested.emit()

    def _hotkey_record(self):
        self.hotkey_record_requested.emit()

    def _hotkey_play_start(self):
        self.hotkey_play_start_requested.emit()

    def _hotkey_play_stop(self):
        self.hotkey_play_stop_requested.emit()

    def _hotkey_stop(self):
        self.hotkey_stop_requested.emit()

    def _toggle_automation_kind(self, kind):
        if self.worker and self.worker.isRunning():
            if self._active_automation_kind == kind:
                self.stop_automation()
            else:
                self.status.setText("● Stop the current automation before switching modes")
            return
        if self.playback_worker and self.playback_worker.isRunning():
            self.status.setText("● Stop macro playback before starting automation")
            return
        self.tabs.setCurrentIndex(0 if kind == "key" else 1)
        self.start_automation(kind)

    def _stop_everything(self):
        self.stop_automation()
        self.stop_playback()
        if self.recorder.recording:
            self.recorded_events = self.recorder.stop()
            self.record_count.setText(f"Recorded events: {len(self.recorded_events)}")
            self.record_button.setText(f"● Start recording  [{self._hotkeys['record']}]")
            self.record_button.setObjectName("StopButton")
            self.record_button.setProperty("running", False)
            self.record_button.style().unpolish(self.record_button); self.record_button.style().polish(self.record_button)
        self.status.setText("● Emergency stop requested")

    def closeEvent(self, event):
        if self.countdown_timer and self.countdown_timer.isActive():
            self.countdown_timer.stop()
        if self.countdown_dialog:
            self.countdown_dialog.hide()
        if self.recorder.recording:
            self.recorded_events = self.recorder.stop()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)
        if self.playback_worker and self.playback_worker.isRunning():
            self.playback_worker.stop()
            self.playback_worker.wait(1500)
        if self._hotkey_listener:
            self._hotkey_listener.stop()
            self._hotkey_listener.join(timeout=1)
        event.accept()
