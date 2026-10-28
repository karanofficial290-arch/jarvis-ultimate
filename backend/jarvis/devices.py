"""Device pairing (explicit owner approval) and the cross-device task queue.

Devices only ever make *outbound* authenticated HTTPS calls to the backend
(poll for tasks, post results). Nothing listens on the phone or the PC.
"""
from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any, Literal

from .db import Database, iso, iso_in, parse_iso, utcnow
from .security import hash_secret, new_device_secret, new_pairing_code

Platform = Literal["android", "desktop"]
ONLINE_WINDOW_S = 45


class DeviceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.user_message, self.status = message, status


class DeviceRegistry:
    def __init__(self, db: Database, pairing_ttl_s: int):
        self.db, self.pairing_ttl_s = db, pairing_ttl_s

    # ---- pairing ------------------------------------------------------
    def create_pairing_code(self, user_id: int) -> dict[str, Any]:
        code = new_pairing_code()
        expires = iso_in(self.pairing_ttl_s)
        with self.db.tx() as c:
            c.execute("DELETE FROM pairing_codes WHERE user_id=? AND (used=1 OR expires_at < ?)", (user_id, iso()))
            c.execute("INSERT INTO pairing_codes(user_id, code_hash, expires_at) VALUES (?,?,?)",
                      (user_id, hash_secret(code), expires))
        return {"code": code, "expires_at": expires}

    def redeem(self, code: str, name: str, platform: Platform) -> dict[str, Any]:
        """Device side: exchange a pairing code for a device id + secret. Device starts as *pending*."""
        code = code.strip().upper().replace("-", "").replace(" ", "")
        row = self.db.one("SELECT * FROM pairing_codes WHERE code_hash=?", (hash_secret(code),))
        if not row or row["used"] or parse_iso(row["expires_at"]) < utcnow():
            raise DeviceError("Invalid or expired pairing code.", 400)
        secret = new_device_secret()
        with self.db.tx() as c:
            # single use, guarded against races
            if c.execute("UPDATE pairing_codes SET used=1 WHERE id=? AND used=0", (row["id"],)).rowcount != 1:
                raise DeviceError("Invalid or expired pairing code.", 400)
            cur = c.execute(
                "INSERT INTO devices(user_id, name, platform, status, secret_hash, created_at) VALUES (?,?,?,?,?,?)",
                (row["user_id"], name.strip()[:60] or platform, platform, "pending", hash_secret(secret), iso()))
            device_id = cur.lastrowid
        return {"device_id": device_id, "device_secret": secret, "status": "pending", "user_id": row["user_id"]}

    def set_status(self, user_id: int, device_id: int, status: Literal["approved", "revoked"]) -> dict[str, Any]:
        dev = self.get(user_id, device_id)
        if not dev:
            raise DeviceError("Device not found.", 404)
        if status == "approved" and dev["status"] == "revoked":
            raise DeviceError("A revoked device must be paired again.", 409)
        with self.db.tx() as c:
            c.execute("UPDATE devices SET status=? WHERE id=? AND user_id=?", (status, device_id, user_id))
            if status == "revoked":
                c.execute("UPDATE device_tasks SET status='failed', error='device revoked', updated_at=? "
                          "WHERE device_id=? AND status IN ('queued','running')", (iso(), device_id))
        return self.get(user_id, device_id)  # type: ignore[return-value]

    def authenticate(self, device_id: int, secret: str) -> dict[str, Any]:
        dev = self.db.one("SELECT * FROM devices WHERE id=?", (device_id,))
        if not dev or dev["secret_hash"] != hash_secret(secret):
            raise DeviceError("Unknown device or wrong secret.", 401)
        if dev["status"] == "pending":
            raise DeviceError("This device is waiting for approval by the owner.", 403)
        if dev["status"] != "approved":
            raise DeviceError("This device has been revoked.", 403)
        return dev

    def is_active(self, device_id: int) -> bool:
        row = self.db.one("SELECT status FROM devices WHERE id=?", (device_id,))
        return bool(row and row["status"] == "approved")

    # ---- queries --------------------------------------------------------
    def get(self, user_id: int, device_id: int) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM devices WHERE id=? AND user_id=?", (device_id, user_id))
        return _public(row) if row else None

    def list(self, user_id: int) -> list[dict[str, Any]]:
        return [_public(r) for r in self.db.all("SELECT * FROM devices WHERE user_id=? ORDER BY id", (user_id,))]

    def online_targets(self, user_id: int, platform: Platform) -> list[dict[str, Any]]:
        return [d for d in self.list(user_id) if d["platform"] == platform and d["status"] == "approved"]

    def heartbeat(self, device_id: int, capabilities: list[str] | None = None) -> None:
        with self.db.tx() as c:
            if capabilities is not None:
                c.execute("UPDATE devices SET last_seen_at=?, capabilities=? WHERE id=?",
                          (iso(), json.dumps(capabilities[:50]), device_id))
            else:
                c.execute("UPDATE devices SET last_seen_at=? WHERE id=?", (iso(), device_id))


def _public(row: dict[str, Any]) -> dict[str, Any]:
    last = row.get("last_seen_at")
    online = bool(last and utcnow() - parse_iso(last) < timedelta(seconds=ONLINE_WINDOW_S))
    return {
        "id": row["id"], "name": row["name"], "platform": row["platform"], "status": row["status"],
        "capabilities": json.loads(row.get("capabilities") or "[]"),
        "created_at": row["created_at"], "last_seen_at": last, "online": online and row["status"] == "approved",
    }


class TaskQueue:
    def __init__(self, db: Database):
        self.db = db

    def enqueue(self, user_id: int, device_id: int, tool: str, args: dict[str, Any],
                ttl_s: float = 300, origin: str = "assistant") -> dict[str, Any]:
        now = iso()
        with self.db.tx() as c:
            cur = c.execute(
                "INSERT INTO device_tasks(user_id, device_id, tool, args, status, origin, created_at, updated_at, expires_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (user_id, device_id, tool, json.dumps(args, ensure_ascii=False), "queued", origin, now, now, iso_in(ttl_s)))
            tid = cur.lastrowid
        return self.get(user_id, tid)  # type: ignore[return-value]

    def _expire(self) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE device_tasks SET status='expired', error='device did not pick up the task in time', "
                      "updated_at=? WHERE status IN ('queued','running') AND expires_at < ?", (iso(), iso()))

    def claim_next(self, device_id: int) -> dict[str, Any] | None:
        self._expire()
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM device_tasks WHERE device_id=? AND status='queued' ORDER BY id LIMIT 1",
                            (device_id,)).fetchone()
            if not row:
                return None
            c.execute("UPDATE device_tasks SET status='running', updated_at=? WHERE id=?", (iso(), row["id"]))
        return {"id": row["id"], "tool": row["tool"], "args": json.loads(row["args"])}

    def complete(self, device_id: int, task_id: int, ok: bool, result: Any, error: str | None) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM device_tasks WHERE id=? AND device_id=?", (task_id, device_id))
        if not row:
            raise DeviceError("Task not found for this device.", 404)
        if row["status"] != "running":
            raise DeviceError(f"Task is already {row['status']}.", 409)
        with self.db.tx() as c:
            c.execute("UPDATE device_tasks SET status=?, result=?, error=?, updated_at=? WHERE id=?",
                      ("succeeded" if ok else "failed", json.dumps(result, ensure_ascii=False)[:100_000],
                       (error or None) and str(error)[:500], iso(), task_id))
        return self.get(row["user_id"], task_id)  # type: ignore[return-value]

    def get(self, user_id: int, task_id: int) -> dict[str, Any] | None:
        r = self.db.one("SELECT t.*, d.name AS device_name, d.platform FROM device_tasks t "
                        "JOIN devices d ON d.id=t.device_id WHERE t.id=? AND t.user_id=?", (task_id, user_id))
        if not r:
            return None
        r["args"] = json.loads(r["args"])
        r["result"] = json.loads(r["result"]) if r["result"] else None
        return r

    def list(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        self._expire()
        rows = self.db.all("SELECT t.id FROM device_tasks t WHERE t.user_id=? ORDER BY t.id DESC LIMIT ?", (user_id, limit))
        return [self.get(user_id, r["id"]) for r in rows]  # type: ignore[misc]

    def wait(self, user_id: int, task_id: int, timeout_s: float, poll_s: float = 0.25) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while True:
            t = self.get(user_id, task_id)
            if t is None or t["status"] in ("succeeded", "failed", "expired") or time.monotonic() >= deadline:
                return t  # type: ignore[return-value]
            time.sleep(poll_s)
