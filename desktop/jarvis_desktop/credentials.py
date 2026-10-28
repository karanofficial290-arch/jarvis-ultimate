"""Device credential storage.

Preferred: the OS credential vault via the optional `keyring` package (Windows
Credential Manager). Fallback: a JSON file in the per-user config folder,
readable only by the current user where the OS supports it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SERVICE = "jarvis-ultimate-desktop"


def config_dir() -> Path:
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.environ.get("XDG_CONFIG_HOME")
    d = Path(base or Path.home() / ".config") / "JarvisDesktop"
    d.mkdir(parents=True, exist_ok=True)
    return d


class CredentialStore:
    def __init__(self, directory: Path | None = None, use_keyring: bool = True):
        self.dir = directory or config_dir()
        self.keyring = None
        if use_keyring:
            try:
                import keyring  # type: ignore
                self.keyring = keyring
            except ImportError:
                pass

    @property
    def backend(self) -> str:
        return "os-keyring" if self.keyring else "file"

    def save_device(self, backend_url: str, device_id: int, secret: str) -> None:
        meta = {"backend_url": backend_url, "device_id": device_id}
        if self.keyring:
            self.keyring.set_password(SERVICE, f"device:{device_id}", secret)
        else:
            meta["device_secret"] = secret
        path = self.dir / "device.json"
        path.write_text(json.dumps(meta), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def load_device(self) -> dict | None:
        path = self.dir / "device.json"
        if not path.exists():
            return None
        meta = json.loads(path.read_text(encoding="utf-8"))
        if self.keyring and "device_secret" not in meta:
            meta["device_secret"] = self.keyring.get_password(SERVICE, f"device:{meta['device_id']}")
        return meta if meta.get("device_secret") else None

    def forget_device(self) -> None:
        meta = self.load_device()
        if meta and self.keyring:
            try:
                self.keyring.delete_password(SERVICE, f"device:{meta['device_id']}")
            except Exception:
                pass
        (self.dir / "device.json").unlink(missing_ok=True)
