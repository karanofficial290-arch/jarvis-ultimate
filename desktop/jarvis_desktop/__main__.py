"""Entry point.

  python -m jarvis_desktop                         # GUI (needs PySide6)
  python -m jarvis_desktop pair --backend URL --code ABCD-EFGH [--name "My PC"]
  python -m jarvis_desktop agent [--allowlist allowlist.json]   # headless agent
  python -m jarvis_desktop check-allowlist allowlist.json
"""
from __future__ import annotations

import argparse
import logging
import platform
import signal
import sys
import threading
from pathlib import Path

from .agent import DeviceAgent
from .allowlist import Allowlist, AllowlistError
from .client import BackendClient, BackendError
from .credentials import CredentialStore, config_dir
from .local_tools import LocalToolExecutor


def default_allowlist() -> Path:
    return config_dir() / "allowlist.json"


def cmd_pair(a) -> int:
    client = BackendClient(a.backend)
    try:
        res = client.pair(a.code, a.name or platform.node() or "Windows PC")
    except BackendError as e:
        print(f"Pairing failed: {e.message}")
        return 1
    store = CredentialStore()
    store.save_device(a.backend, res["device_id"], res["device_secret"])
    print(f"Paired as device #{res['device_id']} (secret stored in {store.backend}).")
    print("Now approve this computer in the Jarvis app (Devices screen), then run: python -m jarvis_desktop agent")
    return 0


def cmd_agent(a) -> int:
    creds = CredentialStore().load_device()
    if not creds:
        print("This computer is not paired. Run: python -m jarvis_desktop pair --backend URL --code CODE")
        return 1
    try:
        allow = Allowlist.load(a.allowlist)
    except AllowlistError as e:
        print(e)
        return 1
    executor = LocalToolExecutor(allow, on_event=lambda t, s, ok, err: print(f"[task] {t}: {'OK' if ok else 'FAILED'} {s if ok else err}"))
    agent = DeviceAgent(BackendClient(creds["backend_url"]), creds["device_id"], creds["device_secret"], executor,
                        on_state=lambda s, d: print(f"[agent] {s} {d}".rstrip()))
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    agent.start()
    print(f"Agent running with actions: {', '.join(allow.capabilities())}. Ctrl+C to stop.")
    while not stop.wait(0.5):
        if agent.state == "revoked":
            break
    agent.stop()
    return 0


def cmd_check(a) -> int:
    try:
        allow = Allowlist.load(a.path)
    except AllowlistError as e:
        print(e)
        return 1
    import os
    print("Actions:", ", ".join(allow.enabled_actions))
    for name, exe in allow.applications.items():
        print(f"  app {name:12} {'OK ' if os.path.isfile(exe) else 'MISSING'} {exe}")
    for name, folder in allow.folders.items():
        print(f"  folder {name:9} {'OK ' if os.path.isdir(folder) else 'MISSING'} {folder}")
    print("  notes  ", allow.notes_folder or "(not set)")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="jarvis_desktop")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("pair"); p.add_argument("--backend", required=True); p.add_argument("--code", required=True)
    p.add_argument("--name", default="")
    g = sub.add_parser("agent"); g.add_argument("--allowlist", default=str(default_allowlist()))
    c = sub.add_parser("check-allowlist"); c.add_argument("path")
    a = ap.parse_args(argv)
    if a.cmd == "pair":
        return cmd_pair(a)
    if a.cmd == "agent":
        return cmd_agent(a)
    if a.cmd == "check-allowlist":
        return cmd_check(a)
    try:
        from .ui.main_window import run_gui
    except ImportError as e:
        print(f"The GUI needs PySide6 ({e}). Install with: pip install -r requirements.txt")
        return 1
    return run_gui(default_allowlist())


if __name__ == "__main__":
    sys.exit(main())
