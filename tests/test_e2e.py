"""End-to-end: real HTTP server + real desktop agent + real local tools (launcher stubbed).

Flow: owner registers → generates pairing code → computer pairs via the CLI → owner
approves → agent connects → chat "open notepad on my computer" → the agent executes
→ chat reply reflects the device's real result. Then document reading and a
confirmation-gated file organisation.
"""
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import requests
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "desktop")]

from jarvis.app import create_app  # noqa: E402
from jarvis.config import load_settings  # noqa: E402
from jarvis_desktop.__main__ import main as desktop_main  # noqa: E402
from jarvis_desktop.agent import DeviceAgent  # noqa: E402
from jarvis_desktop.allowlist import Allowlist  # noqa: E402
from jarvis_desktop.client import BackendClient  # noqa: E402
from jarvis_desktop.credentials import CredentialStore  # noqa: E402
from jarvis_desktop.local_tools import LocalToolExecutor  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(tmp_path):
    settings = load_settings({"JARVIS_ENV": "test", "JARVIS_SECRET_KEY": "e2e" * 20,
                              "JARVIS_DATABASE_PATH": str(tmp_path / "e2e.db"), "JARVIS_DEVICE_WAIT_S": "10"})
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if requests.get(url + "/api/health", timeout=1).ok:
                break
        except requests.ConnectionError:
            time.sleep(0.05)
    yield url
    srv.should_exit = True
    t.join(5)


def test_phone_to_pc_full_round_trip(server, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("APPDATA", raising=False)
    s = requests.Session()
    tok = s.post(server + "/api/auth/register", json={"username": "tony", "password": "correct horse battery"}).json()["token"]
    H = {"Authorization": f"Bearer {tok}"}

    # pairing through the real CLI
    code = s.post(server + "/api/devices/pairing-code", headers=H).json()["code"]
    assert desktop_main(["pair", "--backend", server, "--code", code, "--name", "Stark-PC"]) == 0
    creds = CredentialStore(use_keyring=False).load_device()
    assert creds["device_id"]

    # local allowlist + agent
    docs = tmp_path / "Jarvis"
    docs.mkdir()
    (docs / "plan.txt").write_text("Mark 85 armour: finish repulsor calibration by Friday.", encoding="utf-8")
    (docs / "photo.png").write_bytes(b"png")
    exe = tmp_path / "notepad.exe"
    exe.write_text("")
    launched = []
    allow = Allowlist.from_dict({"applications": {"notepad": str(exe)}, "folders": {"jarvis": str(docs)},
                                 "notes_folder": str(docs / "Notes")})
    agent = DeviceAgent(BackendClient(server), creds["device_id"], creds["device_secret"],
                        LocalToolExecutor(allow, launcher=launched.append, open_browser=lambda u: True),
                        poll_interval=0.2)
    agent.start()
    time.sleep(0.6)
    assert agent.state == "pending_approval"  # not trusted until the owner approves
    s.post(server + f"/api/devices/{creds['device_id']}/approve", headers=H)
    for _ in range(100):
        if agent.state == "online":
            break
        time.sleep(0.1)
    assert agent.state == "online"
    dev = s.get(server + "/api/devices", headers=H).json()[0]
    assert dev["online"] and set(dev["capabilities"]) >= {"desktop_open_app", "desktop_read_document"}

    try:
        r = s.post(server + "/api/chat", json={"message": "Jarvis, open notepad on my computer"}, headers=H).json()
        assert r["reply"] == "Opened notepad." and r["tool_events"][0]["ok"]
        assert launched == [[str(exe)]]

        r = s.post(server + "/api/chat", json={"message": "open regedit on my pc"}, headers=H).json()
        assert "not in this computer's application allowlist" in r["reply"]

        r = s.post(server + "/api/tasks", json={"tool": "desktop_read_document", "args": {"path": "plan.txt"}}, headers=H).json()
        assert r["ok"] and "repulsor calibration" in r["data"]["text"]
        r = s.post(server + "/api/tasks", json={"tool": "desktop_read_document", "args": {"path": "../../etc/passwd"}}, headers=H).json()
        assert not r["ok"] and "outside the approved folders" in r["error"]

        # files.organize is OFF by default → denied until the owner enables it
        r = s.post(server + "/api/tasks", json={"tool": "desktop_organize_folder", "args": {"folder": "jarvis"}}, headers=H).json()
        assert "turned off" in r["error"]
        st = s.get(server + "/api/settings", headers=H).json()
        st["permissions"]["files.organize"] = True
        s.put(server + "/api/settings", json=st, headers=H)
        r = s.post(server + "/api/tasks", json={"tool": "desktop_organize_folder", "args": {"folder": "jarvis"}}, headers=H).json()
        assert r["status"] == "awaiting_confirmation" and (docs / "photo.png").exists()
        done = s.post(server + f"/api/actions/{r['action_id']}/confirm", headers=H).json()
        assert done["ok"] and (docs / "Images" / "photo.png").exists()

        # revoking cuts the computer off immediately
        s.post(server + f"/api/devices/{creds['device_id']}/revoke", headers=H)
        for _ in range(100):
            if agent.state == "revoked":
                break
            time.sleep(0.1)
        assert agent.state == "revoked"
        audit = s.get(server + "/api/audit", headers=H).json()
        events = {a["event"] for a in audit}
        assert {"device.pair", "device.approved", "tool.call", "tool.confirmation_requested", "device.revoked"} <= events
    finally:
        agent.stop()
