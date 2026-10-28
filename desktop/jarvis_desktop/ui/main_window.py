"""PySide6 desktop UI.

Every indicator reflects real state: the core colour follows the assistant state
machine (idle/listening/processing/speaking), which only changes on real events
(microphone opened/closed, HTTP request in flight, TTS engine start/stop).
"""
from __future__ import annotations

import html
import math
import os
import platform
import shutil
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSlider, QSplitter,
    QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from ..agent import DeviceAgent
from ..allowlist import Allowlist, AllowlistError
from ..client import BackendClient, BackendError
from ..credentials import CredentialStore
from ..local_tools import LocalToolExecutor
from ..voice import Listener, Speaker

COLORS = {"idle": QColor(34, 211, 238), "listening": QColor(248, 113, 113),
          "processing": QColor(96, 165, 250), "speaking": QColor(52, 211, 153)}
STYLE = """
QWidget { background: #03070d; color: #d8f3ff; font-family: 'Segoe UI'; font-size: 10pt; }
QLineEdit, QTextBrowser, QListWidget, QComboBox { background: #06101a; border: 1px solid #12404d; border-radius: 6px; padding: 6px; }
QPushButton { background: #082030; border: 1px solid #1f8fa6; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #0c3346; } QPushButton:disabled { color: #4b6470; border-color: #1b3945; }
QPushButton#mic[listening="true"] { background: #4a1414; border-color: #f87171; }
QTabWidget::pane { border: 1px solid #12404d; border-radius: 6px; }
QTabBar::tab { background: #06101a; padding: 6px 12px; border: 1px solid #12404d; }
QTabBar::tab:selected { color: #22d3ee; border-bottom: 2px solid #22d3ee; }
QLabel#state { color: #22d3ee; font-family: Consolas; letter-spacing: 4px; font-size: 11pt; }
QLabel[class="muted"] { color: #7aa3b8; }
"""


class Bridge(QObject):
    """Thread-safe signals from worker threads to the GUI thread."""
    agent_state = Signal(str, str)
    task_done = Signal(str, bool, str)
    speaking = Signal(bool)
    listening = Signal(bool)
    chat_done = Signal(dict)
    chat_failed = Signal(str)
    heard = Signal(str, str)          # text, error
    actions = Signal(list)
    status = Signal(dict, str)
    resolved = Signal(str)


class CoreWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.state = "idle"
        self.energy = 0.0
        self.setMinimumSize(260, 260)
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def pulse(self, amount: float = 0.6) -> None:
        self.energy = min(1.6, self.energy + amount)

    def _tick(self) -> None:
        self.energy = max(0.0, self.energy - 0.04)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy, R = w / 2, h / 2, min(w, h) * 0.36
        t = time.monotonic() - self._t0
        c = COLORS[self.state]
        speed = {"idle": 0.15, "listening": 0.6, "processing": 1.6, "speaking": 0.8}[self.state]

        g = QRadialGradient(QPointF(cx, cy), R * 1.25)
        glow = QColor(c); glow.setAlphaF(0.30 + self.energy * 0.12)
        g.setColorAt(0, glow); g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen); p.setBrush(g); p.drawEllipse(QPointF(cx, cy), R * 1.25, R * 1.25)

        for k, alpha, lw, direction in ((1.0, 0.9, 5, 1), (0.86, 0.5, 3, -1.4), (0.72, 0.35, 2, 2.2)):
            col = QColor(c); col.setAlphaF(alpha)
            p.setPen(QPen(col, lw, Qt.SolidLine, Qt.RoundCap)); p.setBrush(Qt.NoBrush)
            rect = QRectF(cx - R * k, cy - R * k, 2 * R * k, 2 * R * k)
            rot = t * speed * direction * 57.3
            for i in range(6):
                start = rot + i * 60
                p.drawArc(rect, int(-start * 16), int(-50 * 16))

        amp = (4 + self.energy * 16) if self.state in ("listening", "speaking") else (2 if self.state == "processing" else 0)
        path = QPainterPath()
        for i in range(181):
            a = i / 180 * 2 * math.pi
            rr = R * 0.56 + amp * math.sin(a * 9 + t * 7) * math.sin(a * 3 - t * 3)
            pt = QPointF(cx + rr * math.cos(a), cy + rr * math.sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.setPen(QPen(c, 2)); p.drawPath(path)
        p.setPen(Qt.NoPen); p.setBrush(c); p.drawEllipse(QPointF(cx, cy), R * 0.12 + self.energy * 5, R * 0.12 + self.energy * 5)
        p.end()


class LoginDialog(QDialog):
    def __init__(self, parent, url: str, username: str, message: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Sign in to Jarvis")
        form = QFormLayout(self)
        self.url = QLineEdit(url or "https://")
        self.user = QLineEdit(username)
        self.pw = QLineEdit(); self.pw.setEchoMode(QLineEdit.Password)
        form.addRow("Backend URL", self.url); form.addRow("Username", self.user); form.addRow("Password", self.pw)
        if message:
            form.addRow(QLabel(message))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)


class MainWindow(QMainWindow):
    def __init__(self, allowlist_path: Path):
        super().__init__()
        self.setWindowTitle("JARVIS — Desktop")
        self.resize(1200, 760)
        self.qs = QSettings("JarvisUltimate", "Desktop")
        self.bridge = Bridge()
        self.client: BackendClient | None = None
        self.conversation_id: int | None = None
        self.state = "idle"
        self.allowlist_path = allowlist_path
        self.creds = CredentialStore()
        self.agent: DeviceAgent | None = None
        self.speaker = Speaker()
        self.listener = Listener()
        self.speaker.on_state = self.bridge.speaking.emit
        self.listener.on_state = self.bridge.listening.emit
        self._build()
        self._wire()
        QTimer.singleShot(100, self.startup)

    # ---- layout -----------------------------------------------------------------
    def _build(self) -> None:
        split = QSplitter()
        left = QWidget(); lv = QVBoxLayout(left)
        self.core = CoreWidget()
        self.state_label = QLabel("IDLE"); self.state_label.setObjectName("state"); self.state_label.setAlignment(Qt.AlignCenter)
        self.reply_label = QLabel(""); self.reply_label.setWordWrap(True)
        self.conn_label = QLabel("Backend: not connected"); self.conn_label.setProperty("class", "muted")
        lv.addWidget(self.core, 1); lv.addWidget(self.state_label); lv.addWidget(self.reply_label); lv.addWidget(self.conn_label)

        mid = QWidget(); mv = QVBoxLayout(mid)
        self.chat = QTextBrowser(); self.chat.setOpenExternalLinks(False)
        row = QHBoxLayout()
        self.mic = QPushButton("🎙 Talk"); self.mic.setObjectName("mic")
        self.input = QLineEdit(); self.input.setPlaceholderText("Ask Jarvis…"); self.input.setMaxLength(8000)
        self.send = QPushButton("Send"); self.stop_btn = QPushButton("Stop speaking")
        for wdg in (self.mic, self.input, self.send, self.stop_btn):
            row.addWidget(wdg)
        mv.addWidget(self.chat, 1); mv.addLayout(row)

        tabs = QTabWidget()
        self.approvals = QListWidget(); appr = QWidget(); av = QVBoxLayout(appr)
        ab = QHBoxLayout(); self.approve_btn = QPushButton("Approve"); self.deny_btn = QPushButton("Deny")
        ab.addWidget(self.approve_btn); ab.addWidget(self.deny_btn)
        av.addWidget(self.approvals); av.addLayout(ab)
        tabs.addTab(appr, "Approvals")
        self.activity = QListWidget(); tabs.addTab(self.activity, "Activity")

        dev = QWidget(); dv = QVBoxLayout(dev)
        self.agent_label = QLabel("Agent: stopped"); self.agent_label.setWordWrap(True)
        self.pair_btn = QPushButton("Pair this computer…")
        self.agent_btn = QPushButton("Start agent")
        self.allow_label = QLabel(""); self.allow_label.setWordWrap(True)
        self.open_allow_btn = QPushButton("Edit allowlist"); self.reload_allow_btn = QPushButton("Reload allowlist")
        self.forget_btn = QPushButton("Forget pairing")
        for wdg in (self.agent_label, self.pair_btn, self.agent_btn, self.allow_label, self.open_allow_btn,
                    self.reload_allow_btn, self.forget_btn):
            dv.addWidget(wdg)
        dv.addStretch(1)
        tabs.addTab(dev, "This computer")

        st = QWidget(); sf = QFormLayout(st)
        self.speak_cb = QCheckBox("Speak replies"); self.speak_cb.setChecked(self.qs.value("speak", True, type=bool))
        self.lang = QComboBox()
        for code, label in (("en-IN", "English (India)"), ("hi-IN", "Hindi / Hinglish"), ("en-US", "English (US)")):
            self.lang.addItem(label, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(self.qs.value("lang", "en-IN"))))
        self.rate = QSlider(Qt.Horizontal); self.rate.setRange(5, 20); self.rate.setValue(int(self.qs.value("rate", 10)))
        self.voice_info = QLabel(self._voice_info()); self.voice_info.setWordWrap(True)
        sf.addRow(self.speak_cb); sf.addRow("Language", self.lang); sf.addRow("Speech rate", self.rate); sf.addRow(self.voice_info)
        tabs.addTab(st, "Settings")

        split.addWidget(left); split.addWidget(mid); split.addWidget(tabs)
        split.setSizes([320, 560, 320])
        self.setCentralWidget(split)
        self.mic.setEnabled(self.listener.available)
        if not self.listener.available:
            self.mic.setToolTip(self.listener.reason)

    def _voice_info(self) -> str:
        out = "Voice output: " + ("Windows speech (offline)" if self.speaker.available else self.speaker.reason)
        out += "\nVoice input: " + ("push-to-talk via Google Web Speech (audio is sent to Google; mic is open only while 'Listening')"
                                    if self.listener.available else self.listener.reason)
        return out

    def _wire(self) -> None:
        b = self.bridge
        b.agent_state.connect(self.on_agent_state)
        b.task_done.connect(lambda tool, ok, msg: self.log_activity(f"{tool}: {'OK' if ok else 'FAILED'} — {msg}"))
        b.speaking.connect(lambda on: self.set_state("speaking" if on else "idle") if on or self.state == "speaking" else None)
        b.listening.connect(lambda on: self.set_state("listening" if on else "idle") if on or self.state == "listening" else None)
        b.chat_done.connect(self.on_chat_done)
        b.chat_failed.connect(self.on_chat_failed)
        b.heard.connect(self.on_heard)
        b.actions.connect(self.render_actions)
        b.status.connect(self.on_status)
        b.resolved.connect(lambda msg: (self.add_msg("Jarvis", msg), self.refresh_actions()))
        self.send.clicked.connect(self.submit)
        self.input.returnPressed.connect(self.submit)
        self.mic.clicked.connect(self.push_to_talk)
        self.stop_btn.clicked.connect(self.speaker.stop)
        self.approve_btn.clicked.connect(lambda: self.resolve_selected(True))
        self.deny_btn.clicked.connect(lambda: self.resolve_selected(False))
        self.pair_btn.clicked.connect(self.pair)
        self.agent_btn.clicked.connect(self.toggle_agent)
        self.open_allow_btn.clicked.connect(self.open_allowlist)
        self.reload_allow_btn.clicked.connect(self.refresh_allowlist_label)
        self.forget_btn.clicked.connect(self.forget)
        self.speak_cb.toggled.connect(lambda v: self.qs.setValue("speak", v))
        self.lang.currentIndexChanged.connect(lambda _: self.qs.setValue("lang", self.lang.currentData()))
        self.rate.valueChanged.connect(lambda v: (self.qs.setValue("rate", v), self.speaker.set_rate(v / 10)))
        self.speaker.set_rate(self.rate.value() / 10)
        self.poll = QTimer(self)
        self.poll.setInterval(5000)
        self.poll.timeout.connect(self.refresh_actions)

    # ---- helpers -------------------------------------------------------------------
    def run_bg(self, fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    def set_state(self, state: str) -> None:
        self.state = state
        self.core.state = state
        self.state_label.setText(state.upper())
        self.mic.setProperty("listening", state == "listening")
        self.mic.style().unpolish(self.mic); self.mic.style().polish(self.mic)
        if state in ("listening", "speaking"):
            self.core.pulse(0.8)

    def add_msg(self, who: str, text: str, color: str = "#d8f3ff") -> None:
        self.chat.append(f'<p><b style="color:#22d3ee">{html.escape(who)}:</b> '
                         f'<span style="color:{color}">{html.escape(text).replace(chr(10), "<br>")}</span></p>')

    def log_activity(self, text: str) -> None:
        self.activity.insertItem(0, QListWidgetItem(time.strftime("%H:%M:%S ") + text))

    # ---- startup & auth -------------------------------------------------------------------
    def startup(self) -> None:
        self.refresh_allowlist_label()
        creds = self.creds.load_device()
        url = (creds or {}).get("backend_url") or self.qs.value("backend_url", "")
        self.login(url)
        if creds and self.client:
            self.toggle_agent()

    def login(self, url: str, message: str = "") -> None:
        dlg = LoginDialog(self, url, self.qs.value("username", ""), message)
        if dlg.exec() != QDialog.Accepted:
            self.conn_label.setText("Backend: not signed in (chat disabled). The device agent can still run.")
            return
        client = BackendClient(dlg.url.text().strip())
        try:
            st = client.status()
            client.login(dlg.user.text().strip(), dlg.pw.text())
        except BackendError as e:
            return self.login(dlg.url.text().strip(), f"Sign-in failed: {e.message}")
        self.client = client
        self.qs.setValue("backend_url", client.base); self.qs.setValue("username", dlg.user.text().strip())
        self.on_status(st, "")
        self.poll.start(); self.refresh_actions()

    def on_status(self, st: dict, err: str) -> None:
        if err:
            self.conn_label.setText(f"Backend: {err}")
            return
        p = st["provider"]
        mode = f"AI: {p['name']} · {p['model']}" if p["ai"] else "Local command mode (no AI model configured)"
        self.conn_label.setText(f"Backend: connected v{st['version']} — {mode}")

    # ---- chat & voice -------------------------------------------------------------------------
    def submit(self) -> None:
        text = self.input.text().strip()
        self.input.clear()
        if text:
            self.send_chat(text, spoken=False)

    def send_chat(self, text: str, spoken: bool) -> None:
        if not self.client:
            self.add_msg("Jarvis", "Not signed in to the backend.", "#f87171")
            return
        self.speaker.stop()
        self.add_msg("You", text)
        self.set_state("processing")
        self._spoken = spoken

        def work():
            try:
                self.bridge.chat_done.emit(self.client.chat(text, self.conversation_id))
            except BackendError as e:
                self.bridge.chat_failed.emit(e.message)
        self.run_bg(work)

    def on_chat_done(self, r: dict) -> None:
        self.conversation_id = r["conversation_id"]
        self.set_state("idle")
        self.add_msg("Jarvis", r["reply"], "#f87171" if r.get("error") else "#d8f3ff")
        self.reply_label.setText(r["reply"])
        for ev in r.get("tool_events", []):
            self.log_activity(f"{ev['tool']}: {ev['status']}" + (f" — {ev['error']}" if ev.get("error") else ""))
        self.render_actions(r.get("pending_actions", []))
        if self.speak_cb.isChecked() and self.speaker.available:
            self.speaker.say(r["reply"], self.lang.currentData())

    def on_chat_failed(self, msg: str) -> None:
        self.set_state("idle")
        self.add_msg("Jarvis", msg, "#f87171")

    def push_to_talk(self) -> None:
        if self.listener.listening:
            return
        self.speaker.stop()  # barge-in
        lang = self.lang.currentData()
        self.run_bg(lambda: self.bridge.heard.emit(*[x or "" for x in self.listener.listen_once(lang)]))

    def on_heard(self, text: str, error: str) -> None:
        if error:
            self.add_msg("Jarvis", error, "#fbbf24")
        elif text:
            self.send_chat(text, spoken=True)

    # ---- approvals ------------------------------------------------------------------------------
    def refresh_actions(self) -> None:
        if not self.client:
            return

        def work():
            try:
                self.bridge.actions.emit(self.client.pending_actions())
            except BackendError:
                pass
        self.run_bg(work)

    def render_actions(self, actions: list) -> None:
        self.approvals.clear()
        for a in actions:
            item = QListWidgetItem(f"{a['summary']}  [{a['tool']}]")
            item.setData(Qt.UserRole, a["id"])
            self.approvals.addItem(item)

    def resolve_selected(self, approve: bool) -> None:
        item = self.approvals.currentItem()
        if not item or not self.client:
            return
        aid = item.data(Qt.UserRole)
        client = self.client

        def work():  # may wait for a device to finish, so keep it off the GUI thread
            try:
                r = client.resolve_action(aid, approve)
            except BackendError as e:
                self.bridge.resolved.emit(f"Could not resolve the action: {e.message}")
                return
            if not approve:
                msg = "Denied. Nothing was done."
            elif r.get("ok"):
                msg = (r.get("data") or {}).get("message") or "Done."
            else:
                msg = f"Not completed: {r.get('error') or r.get('status')}"
            self.bridge.resolved.emit(msg)
        self.run_bg(work)

    # ---- device agent ------------------------------------------------------------------------------
    def refresh_allowlist_label(self) -> None:
        try:
            a = Allowlist.load(self.allowlist_path)
            self.allow_label.setText(f"Allowlist: {self.allowlist_path}\nApps: {', '.join(a.applications) or 'none'}\n"
                                     f"Folders: {', '.join(a.folders) or 'none'}\nActions: {len(a.enabled_actions)} enabled")
        except AllowlistError as e:
            self.allow_label.setText(f"{e}\nCreate it from allowlist.example.json.")

    def open_allowlist(self) -> None:
        if not self.allowlist_path.exists():
            example = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "allowlist.example.json"
            if example.exists():
                shutil.copy(example, self.allowlist_path)
        if sys.platform == "win32" and self.allowlist_path.exists():
            os.startfile(str(self.allowlist_path))  # opens in the user's editor
        else:
            QMessageBox.information(self, "Allowlist", f"Edit this file:\n{self.allowlist_path}")

    def pair(self) -> None:
        if not self.client:
            QMessageBox.information(self, "Pairing", "Sign in first so I know which backend to pair with.")
            return
        code, ok = QInputDialog.getText(self, "Pair this computer", "Pairing code from the Jarvis app (Devices screen):")
        if not ok or not code.strip():
            return
        try:
            res = BackendClient(self.client.base).pair(code.strip(), platform.node() or "Windows PC")
        except BackendError as e:
            QMessageBox.warning(self, "Pairing failed", e.message)
            return
        self.creds.save_device(self.client.base, res["device_id"], res["device_secret"])
        self.agent_label.setText("Paired. Approve this computer in the Devices screen, then start the agent.")

    def toggle_agent(self) -> None:
        if self.agent and self.agent.state != "stopped":
            self.agent.stop(); self.agent = None
            self.agent_btn.setText("Start agent")
            return
        creds = self.creds.load_device()
        if not creds:
            self.agent_label.setText("Agent: this computer is not paired yet.")
            return
        try:
            allow = Allowlist.load(self.allowlist_path)
        except AllowlistError as e:
            self.agent_label.setText(f"Agent not started: {e}")
            return
        executor = LocalToolExecutor(allow, on_event=lambda t, s, ok, err: self.bridge.task_done.emit(t, ok, s if ok else err))
        self.agent = DeviceAgent(BackendClient(creds["backend_url"]), creds["device_id"], creds["device_secret"], executor,
                                 on_state=self.bridge.agent_state.emit)
        self.agent.start()
        self.agent_btn.setText("Stop agent")

    def on_agent_state(self, state: str, detail: str) -> None:
        self.agent_label.setText(f"Agent: {state.replace('_', ' ')}" + (f" — {detail}" if detail else ""))

    def forget(self) -> None:
        if QMessageBox.question(self, "Forget pairing", "Remove this computer's device credentials?") == QMessageBox.Yes:
            if self.agent:
                self.agent.stop(); self.agent = None
            self.creds.forget_device()
            self.agent_label.setText("Agent: not paired. Revoke the old device in the Jarvis app too.")

    def closeEvent(self, e) -> None:
        if self.agent:
            self.agent.stop()
        self.speaker.stop()
        super().closeEvent(e)


def run_gui(allowlist_path: Path) -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Segoe UI", 10))
    w = MainWindow(allowlist_path)
    w.show()
    return app.exec()
