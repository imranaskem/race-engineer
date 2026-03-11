"""
LMU Race Engineer — Qt UI.

MainWindow: status indicator, transcript log, start/stop control.
SettingsDialog: API keys and PTT configuration.
System tray for background operation while racing.
"""
import os
import sys
import threading

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from dotenv import set_key

import config
from ui.worker import (
    EngineWorker,
    STATUS_IDLE,
    STATUS_LOADING,
    STATUS_READY,
    STATUS_LISTENING,
    STATUS_THINKING,
    STATUS_SPEAKING,
    STATUS_ERROR,
)

# ---------------------------------------------------------------------------
# Dark racing theme
# ---------------------------------------------------------------------------
_STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background-color: #1a1a1a;
    color: #e0e0e0;
    font-size: 13px;
}
QTextEdit {
    background-color: #111111;
    color: #cccccc;
    border: 1px solid #333333;
    border-radius: 4px;
    padding: 6px;
}
QLineEdit {
    background-color: #252525;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 5px 8px;
}
QLineEdit:focus {
    border-color: #e8a000;
}
QPushButton {
    background-color: #2a2a2a;
    color: #e0e0e0;
    border: 1px solid #444444;
    border-radius: 4px;
    padding: 7px 18px;
}
QPushButton:hover {
    background-color: #333333;
    border-color: #e8a000;
}
QPushButton:pressed {
    background-color: #1a1a1a;
}
QPushButton#startBtn {
    background-color: #1a4a1a;
    border-color: #2a7a2a;
    color: #88ff88;
    font-weight: bold;
    padding: 9px 24px;
}
QPushButton#startBtn:hover {
    background-color: #1f601f;
}
QPushButton#stopBtn {
    background-color: #4a1a1a;
    border-color: #7a2a2a;
    color: #ff8888;
    font-weight: bold;
    padding: 9px 24px;
}
QPushButton#stopBtn:hover {
    background-color: #601f1f;
}
QComboBox {
    background-color: #252525;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 5px 8px;
}
QComboBox::drop-down {
    border: none;
}
QLabel#sectionLabel {
    color: #888888;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}
QDialogButtonBox QPushButton {
    min-width: 80px;
}
QCheckBox {
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #555555;
    border-radius: 3px;
    background-color: #252525;
}
QCheckBox::indicator:checked {
    background-color: #e8a000;
    border-color: #e8a000;
    image: url(none);
}
QCheckBox::indicator:hover {
    border-color: #e8a000;
}
"""

# Status display config: (label, dot colour)
_STATUS_CONFIG = {
    STATUS_IDLE:      ("IDLE",       "#555555"),
    STATUS_LOADING:   ("LOADING…",   "#e8a000"),
    STATUS_READY:     ("READY",      "#44cc44"),
    STATUS_LISTENING: ("LISTENING",  "#ff4444"),
    STATUS_THINKING:  ("THINKING…",  "#4488ff"),
    STATUS_SPEAKING:  ("SPEAKING",   "#e8a000"),
    STATUS_ERROR:     ("ERROR",      "#ff0000"),
}

# Log entry colours
_LOG_COLOURS = {
    "system":   "#666666",
    "driver":   "#ffffff",
    "engineer": "#e8a000",
    "alert":    "#ff6644",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), ".env")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".env"))


def _app_icon() -> QIcon:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    path = os.path.join(base, "images", "icon.ico")
    if os.path.exists(path):
        return QIcon(path)
    return QIcon(_make_tray_pixmap())


def _make_dot_pixmap(colour: str, size: int = 14) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(colour))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return px


def _make_tray_pixmap(colour: str = "#e8a000") -> QPixmap:
    px = QPixmap(32, 32)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(colour))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, 28, 28)
    p.setPen(QColor("#ffffff"))
    font = p.font()
    font.setPixelSize(11)
    font.setBold(True)
    p.setFont(font)
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "RE")
    p.end()
    return px


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    # Emitted from background joystick-capture thread → main thread
    _joystick_captured = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)

        # PTT state (updated by capture or loaded from config)
        self._ptt_type_val: str = ""
        self._ptt_key_val: str = ""
        self._ptt_joystick_val: str = ""

        # Capture state
        self._capture_mode = False
        self._joystick_capture_running = False

        self._joystick_captured.connect(self._on_joystick_captured)

        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # --- API Keys ---
        api_label = QLabel("API KEYS")
        api_label.setObjectName("sectionLabel")
        layout.addWidget(api_label)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._anthropic = QLineEdit()
        self._anthropic.setEchoMode(QLineEdit.EchoMode.Password)
        self._anthropic.setPlaceholderText("sk-ant-…")
        form.addRow("Anthropic Key:", self._anthropic)

        self._elevenlabs = QLineEdit()
        self._elevenlabs.setEchoMode(QLineEdit.EchoMode.Password)
        self._elevenlabs.setPlaceholderText("Your ElevenLabs API key")
        form.addRow("ElevenLabs Key:", self._elevenlabs)

        self._voice_id = QLineEdit()
        self._voice_id.setPlaceholderText("onwK4e9ZLuTAKqWW03F9")
        form.addRow("Voice ID:", self._voice_id)

        layout.addLayout(form)

        # --- STT ---
        stt_label = QLabel("SPEECH RECOGNITION")
        stt_label.setObjectName("sectionLabel")
        layout.addWidget(stt_label)

        stt_form = QFormLayout()
        stt_form.setSpacing(10)
        stt_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._vad_filter = QCheckBox()
        stt_form.addRow("VAD filter:", self._vad_filter)

        layout.addLayout(stt_form)

        # --- PTT ---
        ptt_label = QLabel("PUSH-TO-TALK")
        ptt_label.setObjectName("sectionLabel")
        layout.addWidget(ptt_label)

        ptt_row = QHBoxLayout()
        ptt_row.setSpacing(10)

        self._ptt_display = QLabel()
        self._ptt_display.setStyleSheet("color: #e8a000; font-weight: bold;")
        ptt_row.addWidget(self._ptt_display)
        ptt_row.addStretch()

        self._change_ptt_btn = QPushButton("Change PTT Button")
        self._change_ptt_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._change_ptt_btn.clicked.connect(self._start_ptt_capture)
        ptt_row.addWidget(self._change_ptt_btn)

        layout.addLayout(ptt_row)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _format_ptt_label(self) -> str:
        if self._ptt_type_val == "joystick":
            return f"{self._ptt_joystick_val}  (joystick)"
        return f"{self._ptt_key_val}  (keyboard)"

    # ------------------------------------------------------------------
    # PTT capture
    # ------------------------------------------------------------------

    def _start_ptt_capture(self) -> None:
        self._capture_mode = True
        self._change_ptt_btn.setText("Press any key or button…")
        self._change_ptt_btn.setEnabled(False)
        self._ptt_display.setText("Waiting…")
        # Grab keyboard focus so keyPressEvent fires
        self.setFocus()
        # Start joystick capture thread in parallel
        self._joystick_capture_running = True
        threading.Thread(target=self._joystick_capture_thread, daemon=True).start()

    def _joystick_capture_thread(self) -> None:
        try:
            import inputs as _inputs
            gamepads = _inputs.devices.gamepads
            if not gamepads:
                return
            device = gamepads[0]
            while self._joystick_capture_running:
                try:
                    events = device.read()
                except Exception:
                    break
                for event in events:
                    if event.ev_type == "Key" and event.state == 1:
                        if self._joystick_capture_running:
                            self._joystick_capture_running = False
                            self._joystick_captured.emit(event.code)
                        return
        except Exception:
            pass

    def _on_joystick_captured(self, code: str) -> None:
        """Called on main thread when a joystick button is captured."""
        if not self._capture_mode:
            return
        self._capture_mode = False
        self._ptt_type_val = "joystick"
        self._ptt_joystick_val = code
        self._ptt_display.setText(self._format_ptt_label())
        self._change_ptt_btn.setText("Change PTT Button")
        self._change_ptt_btn.setEnabled(True)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._capture_mode and not event.isAutoRepeat():
            self._capture_mode = False
            self._joystick_capture_running = False  # stop joystick thread
            key_name = self._qt_key_to_config_name(event)
            self._ptt_type_val = "keyboard"
            self._ptt_key_val = key_name
            self._ptt_display.setText(self._format_ptt_label())
            self._change_ptt_btn.setText("Change PTT Button")
            self._change_ptt_btn.setEnabled(True)
            event.accept()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _qt_key_to_config_name(event) -> str:
        """Map a Qt key event to the pynput/config key name string."""
        _special = {
            Qt.Key.Key_Space:   "space",
            Qt.Key.Key_Return:  "enter",
            Qt.Key.Key_Enter:   "enter",
            Qt.Key.Key_Tab:     "tab",
            Qt.Key.Key_Escape:  "esc",
            Qt.Key.Key_Control: "ctrl",
            Qt.Key.Key_Alt:     "alt",
            Qt.Key.Key_Shift:   "shift",
            Qt.Key.Key_Meta:    "cmd",
            Qt.Key.Key_F1:  "f1",  Qt.Key.Key_F2:  "f2",
            Qt.Key.Key_F3:  "f3",  Qt.Key.Key_F4:  "f4",
            Qt.Key.Key_F5:  "f5",  Qt.Key.Key_F6:  "f6",
            Qt.Key.Key_F7:  "f7",  Qt.Key.Key_F8:  "f8",
            Qt.Key.Key_F9:  "f9",  Qt.Key.Key_F10: "f10",
            Qt.Key.Key_F11: "f11", Qt.Key.Key_F12: "f12",
        }
        name = _special.get(event.key())
        if name:
            return name
        text = event.text()
        if text and text.isprintable():
            return text.lower()
        return f"key_{event.key()}"

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def _load(self) -> None:
        import config
        self._anthropic.setText(config.ANTHROPIC_API_KEY)
        self._elevenlabs.setText(config.ELEVENLABS_API_KEY)
        self._voice_id.setText(config.ELEVENLABS_VOICE_ID)
        self._ptt_type_val = config.PTT_TYPE
        self._ptt_key_val = config.PTT_KEY
        self._ptt_joystick_val = config.PTT_JOYSTICK_BUTTON
        self._ptt_display.setText(self._format_ptt_label())
        self._vad_filter.setChecked(config.STT_VAD_FILTER)

    def _save(self) -> None:
        env = _env_path()
        if not os.path.exists(env):
            open(env, "w").close()

        set_key(env, "ANTHROPIC_API_KEY", self._anthropic.text().strip())
        set_key(env, "ELEVENLABS_API_KEY", self._elevenlabs.text().strip())
        set_key(env, "ELEVENLABS_VOICE_ID", self._voice_id.text().strip())
        set_key(env, "PTT_TYPE", self._ptt_type_val)
        set_key(env, "PTT_KEY", self._ptt_key_val)
        set_key(env, "PTT_JOYSTICK_BUTTON", self._ptt_joystick_val)
        set_key(env, "STT_VAD_FILTER", "true" if self._vad_filter.isChecked() else "false")

        import importlib
        import config
        importlib.reload(config)

        self.accept()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LMU Race Engineer")
        self.setMinimumSize(480, 520)
        self._app_icon = _app_icon()
        self.setWindowIcon(self._app_icon)
        self._worker: EngineWorker | None = None
        self._active_stt = None  # WhisperSTT whose pynput listener we started
        self._build_ui()
        self._build_tray()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # --- Status bar ---
        status_row = QHBoxLayout()
        status_row.setSpacing(8)

        self._dot_label = QLabel()
        self._dot_label.setPixmap(_make_dot_pixmap("#555555", 16))
        self._dot_label.setFixedSize(16, 16)
        status_row.addWidget(self._dot_label)

        self._status_label = QLabel("IDLE")
        font = QFont()
        font.setBold(True)
        font.setPixelSize(15)
        self._status_label.setFont(font)
        self._status_label.setStyleSheet("color: #555555;")
        status_row.addWidget(self._status_label)
        status_row.addStretch()

        root.addLayout(status_row)

        # --- Log ---
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas, Courier New, monospace", 11))
        root.addWidget(self._log, stretch=1)

        # --- Controls ---
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        self._start_btn = QPushButton("Start")
        self._start_btn.setObjectName("startBtn")
        self._start_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._start_btn.clicked.connect(self._on_start)
        ctrl_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setObjectName("stopBtn")
        self._stop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        ctrl_row.addWidget(self._stop_btn)

        ctrl_row.addStretch()

        settings_btn = QPushButton("Settings")
        settings_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        settings_btn.clicked.connect(self._on_settings)
        ctrl_row.addWidget(settings_btn)

        root.addLayout(ctrl_row)

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(self._app_icon, self)
        self._tray.setToolTip("LMU Race Engineer")

        menu = QMenu()
        menu.addAction("Show / Hide", self._toggle_visible)
        menu.addSeparator()
        self._tray_start_action = menu.addAction("Start", self._on_start)
        self._tray_stop_action = menu.addAction("Stop", self._on_stop)
        self._tray_stop_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Settings", self._on_settings)
        menu.addSeparator()
        menu.addAction("Quit", self._quit)
        self._tray.setContextMenu(menu)

        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        import config
        if not config.ANTHROPIC_API_KEY or not config.ELEVENLABS_API_KEY:
            self._append_log("system", "API keys not set — open Settings first.")
            dlg = SettingsDialog(self)
            dlg.exec()
            import importlib
            importlib.reload(config)
            if not config.ANTHROPIC_API_KEY or not config.ELEVENLABS_API_KEY:
                return

        self._worker = EngineWorker()
        self._worker.status_changed.connect(self._on_status_changed)
        self._worker.log_entry.connect(self._append_log)
        self._worker.ptt_ready.connect(self._on_ptt_ready)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._tray_start_action.setEnabled(False)
        self._tray_stop_action.setEnabled(True)

    def _on_ptt_ready(self, stt) -> None:
        """Called on main thread when the worker is ready for PTT input."""
        worker = self._worker
        if worker is None:
            return
        self._active_stt = stt

        if sys.platform == "darwin":
            # pynput calls TSMGetInputSourceProperty from its callback thread,
            # which macOS (Tahoe+) requires on the main thread — hard crash.
            # Use Qt key events instead; window must be focused (fine for Mac dev).
            self._append_log("system", f"PTT: focus this window and hold [{config.PTT_KEY.upper()}].")
        else:
            def _on_transcript(text: str) -> None:
                worker.log_entry.emit("driver", text)
                worker.post_transcript(text)

            stt.start_ptt_listener(
                on_transcript=_on_transcript,
                on_quit=worker.request_stop,
                on_listening_start=lambda: worker.status_changed.emit(STATUS_LISTENING),
                on_listening_end=lambda: worker.status_changed.emit(STATUS_THINKING),
                on_no_speech=lambda: (
                    worker.log_entry.emit("system", "No speech detected — check mic level."),
                    worker.status_changed.emit(STATUS_READY),
                ),
            )

    def _ptt_qt_key(self):
        """Map config.PTT_KEY to a Qt.Key value for macOS key-event PTT."""
        import config as _cfg
        return {
            "space": Qt.Key.Key_Space,
            "f1": Qt.Key.Key_F1, "f2": Qt.Key.Key_F2,
            "f3": Qt.Key.Key_F3, "f4": Qt.Key.Key_F4,
            "f5": Qt.Key.Key_F5, "f6": Qt.Key.Key_F6,
            "ctrl": Qt.Key.Key_Control, "alt": Qt.Key.Key_Alt,
            "shift": Qt.Key.Key_Shift,
        }.get(_cfg.PTT_KEY.lower(), Qt.Key.Key_Space)

    def keyPressEvent(self, event):  # noqa: N802
        if not event.isAutoRepeat() and event.key() == self._ptt_qt_key():
            if sys.platform == "darwin" and self._active_stt:
                # macOS: pynput can't run on a background thread (crashes), so
                # we drive PTT from Qt key events instead.
                self._active_stt.begin_ptt()
                if self._worker:
                    self._worker.status_changed.emit(STATUS_LISTENING)
            # Always swallow the PTT key so it doesn't activate focused buttons.
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):  # noqa: N802
        if not event.isAutoRepeat() and event.key() == self._ptt_qt_key():
            if sys.platform == "darwin" and self._active_stt:
                audio = self._active_stt.end_ptt()
                worker = self._worker
                stt = self._active_stt
                if worker:
                    worker.status_changed.emit(STATUS_THINKING)
                if audio is not None and len(audio) > config.STT_SAMPLE_RATE * 0.3 and worker:
                    def _transcribe_and_post():
                        text = stt._transcribe(audio)
                        if text:
                            worker.log_entry.emit("driver", text)
                            worker.post_transcript(text)
                    threading.Thread(target=_transcribe_and_post, daemon=True).start()
            # Always swallow the PTT key so it doesn't activate focused buttons.
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _stop_ptt(self) -> None:
        if self._active_stt is not None:
            self._active_stt.stop_ptt_listener()
            self._active_stt = None

    def _on_stop(self) -> None:
        self._stop_ptt()
        if self._worker:
            self._worker.request_stop()
        self._stop_btn.setEnabled(False)

    def _on_worker_finished(self) -> None:
        self._stop_ptt()
        self._worker = None
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._tray_start_action.setEnabled(True)
        self._tray_stop_action.setEnabled(False)

    def _on_settings(self) -> None:
        dlg = SettingsDialog(self)
        dlg.exec()

    def _toggle_visible(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _quit(self) -> None:
        self._stop_ptt()
        if self._worker:
            self._worker.request_stop()
            self._worker.wait(3000)
        QApplication.quit()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visible()

    # ------------------------------------------------------------------
    # Status / log updates (called from Qt main thread via signals)
    # ------------------------------------------------------------------

    def _on_status_changed(self, status: str) -> None:
        label, colour = _STATUS_CONFIG.get(status, ("UNKNOWN", "#888888"))
        self._status_label.setText(label)
        self._status_label.setStyleSheet(f"color: {colour};")
        self._dot_label.setPixmap(_make_dot_pixmap(colour, 16))

    def _append_log(self, category: str, text: str) -> None:
        colour = _LOG_COLOURS.get(category, "#888888")
        prefix = {
            "driver":   "YOU",
            "engineer": "ENGINEER",
            "alert":    "ALERT",
            "system":   "—",
        }.get(category, category.upper())

        html = (
            f'<span style="color:{colour}; font-weight:bold;">[{prefix}]</span>'
            f'&nbsp;<span style="color:{colour};">{text}</span>'
        )
        self._log.append(html)
        # Scroll to bottom
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    # ------------------------------------------------------------------
    # Window close → minimise to tray
    # ------------------------------------------------------------------

    def closeEvent(self, event):  # noqa: N802
        if self._tray.isVisible():
            self.hide()
            event.ignore()
        else:
            self._quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("LMU Race Engineer")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(_STYLESHEET)
    app.setWindowIcon(_app_icon())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
