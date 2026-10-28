"""Builds the real PySide6 main window offscreen. Skipped where PySide6 isn't installed."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_main_window_builds_and_reflects_state(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from jarvis_desktop.ui import main_window as mw

    monkeypatch.setattr(mw.MainWindow, "startup", lambda self: None)  # no login dialog in CI
    app = QApplication.instance() or QApplication([])
    w = mw.MainWindow(tmp_path / "allowlist.json")
    w.show()
    app.processEvents()
    assert w.state_label.text() == "IDLE"
    w.set_state("listening")
    assert w.core.state == "listening" and w.state_label.text() == "LISTENING"
    w.add_msg("You", "<script>alert(1)</script>")
    assert "<script>" not in w.chat.toHtml()  # user text is escaped
    w.refresh_allowlist_label()
    assert "allowlist file not found" in w.allow_label.text()
    w.close()
