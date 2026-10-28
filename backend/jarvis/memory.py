"""User settings and long-term memory.

Saved memory (this module) is distinct from temporary conversation context (the
messages table). Nothing is reported as saved unless the INSERT committed.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from .db import Database, iso

MemoryKind = Literal["preference", "project", "fact", "summary"]

PERMISSIONS = {
    "web.search": "Search the web",
    "memory.read": "Use saved memories",
    "memory.write": "Save new memories",
    "device.android": "Control the paired Android phone",
    "device.desktop": "Control the paired Windows computer",
    "files.read": "Read documents in approved computer folders",
    "files.organize": "Move files inside approved computer folders",
}


class VoiceSettings(BaseModel):
    lang: Literal["en-IN", "en-US", "en-GB", "hi-IN"] = "en-IN"
    rate: float = Field(1.0, ge=0.5, le=2.0)
    pitch: float = Field(1.0, ge=0.5, le=2.0)
    voice_name: str = Field("", max_length=120)


class UserSettings(BaseModel):
    memory_enabled: bool = True
    memory_require_approval: bool = True
    timezone: str = "UTC"
    assistant_name: str = Field("Jarvis", max_length=40)
    address_as: str = Field("sir", max_length=40)
    voice: VoiceSettings = VoiceSettings()
    permissions: dict[str, bool] = Field(default_factory=lambda: {
        "web.search": True, "memory.read": True, "memory.write": True,
        "device.android": True, "device.desktop": True,
        "files.read": True, "files.organize": False,
    })


class SettingsStore:
    def __init__(self, db: Database, default_timezone: str):
        self.db, self.default_tz = db, default_timezone

    def get(self, user_id: int) -> UserSettings:
        row = self.db.one("SELECT data FROM user_settings WHERE user_id=?", (user_id,))
        if not row:
            return UserSettings(timezone=self.default_tz)
        s = UserSettings.model_validate_json(row["data"])
        # unknown permission keys are dropped; missing ones get defaults
        defaults = UserSettings().permissions
        s.permissions = {k: bool(s.permissions.get(k, v)) for k, v in defaults.items()}
        return s

    def put(self, user_id: int, s: UserSettings) -> UserSettings:
        from zoneinfo import ZoneInfo
        ZoneInfo(s.timezone)  # raises if invalid
        defaults = UserSettings().permissions
        s.permissions = {k: bool(s.permissions.get(k, v)) for k, v in defaults.items()}
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO user_settings(user_id, data) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
                (user_id, s.model_dump_json()),
            )
        return s


# ---- sensitive-data filter --------------------------------------------
_SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("a password", re.compile(r"\b(pass\s?word|passwd|pwd|passcode|pin\b|पासवर्ड)", re.I)),
    ("a one-time/authentication code", re.compile(r"\b(otp|2fa|mfa|verification code|auth(?:entication)? code|one[- ]time)\b", re.I)),
    ("a CVV/card security code", re.compile(r"\b(cvv|cvc|card security code)\b", re.I)),
    ("an API key or secret token", re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|api[_ -]?key|secret key|private key|seed phrase|recovery phrase)\b", re.I)),
    ("a PAN number", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("an Aadhaar number", re.compile(r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b")),
    ("a bank account/IFSC detail", re.compile(r"\b(ifsc|account number|a/c no|upi pin)\b", re.I)),
]


def _luhn_card(text: str) -> bool:
    for m in re.finditer(r"(?:\d[ -]?){13,19}", text):
        digits = [int(d) for d in re.sub(r"\D", "", m.group())]
        if not 13 <= len(digits) <= 19:
            continue
        total = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2:
                d *= 2
                d -= 9 if d > 9 else 0
            total += d
        if total % 10 == 0:
            return True
    return False


def sensitive_reason(text: str) -> str | None:
    """Return why `text` must not be saved, or None if it looks safe."""
    if _luhn_card(text):
        return "a payment card number"
    for reason, pat in _SENSITIVE_PATTERNS:
        if pat.search(text):
            return reason
    return None


class MemoryRejected(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.user_message = message


class MemoryStore:
    def __init__(self, db: Database, settings: SettingsStore):
        self.db, self.settings = db, settings

    def save(self, user_id: int, content: str, kind: MemoryKind = "fact", source: str = "user") -> dict[str, Any]:
        content = content.strip()
        if not content:
            raise MemoryRejected("Nothing to save.")
        if len(content) > 2000:
            raise MemoryRejected("That memory is too long (max 2000 characters).")
        if not self.settings.get(user_id).memory_enabled:
            raise MemoryRejected("Memory is turned off in privacy settings.")
        reason = sensitive_reason(content)
        if reason:
            raise MemoryRejected(f"I won't save that because it looks like {reason}. Sensitive data is never stored in memory.")
        now = iso()
        with self.db.tx() as c:
            cur = c.execute(
                "INSERT INTO memories(user_id, kind, content, source, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (user_id, kind, content, source, now, now),
            )
            mid = cur.lastrowid
        row = self.get(user_id, mid)
        if not row:  # paranoia: only report success if we can read it back
            raise MemoryRejected("The memory could not be confirmed in the database.")
        return row

    def get(self, user_id: int, memory_id: int) -> dict[str, Any] | None:
        return self.db.one("SELECT id, kind, content, source, created_at, updated_at FROM memories WHERE id=? AND user_id=?",
                           (memory_id, user_id))

    def list(self, user_id: int, limit: int = 200) -> list[dict[str, Any]]:
        return self.db.all("SELECT id, kind, content, source, created_at, updated_at FROM memories "
                           "WHERE user_id=? ORDER BY updated_at DESC, id DESC LIMIT ?", (user_id, limit))

    def update(self, user_id: int, memory_id: int, content: str, kind: MemoryKind | None = None) -> dict[str, Any] | None:
        content = content.strip()
        if not content:
            raise MemoryRejected("Memory content cannot be empty.")
        reason = sensitive_reason(content)
        if reason:
            raise MemoryRejected(f"I won't store that because it looks like {reason}.")
        with self.db.tx() as c:
            cur = c.execute(
                "UPDATE memories SET content=?, kind=COALESCE(?, kind), updated_at=? WHERE id=? AND user_id=?",
                (content, kind, iso(), memory_id, user_id))
            if cur.rowcount == 0:
                return None
        return self.get(user_id, memory_id)

    def delete(self, user_id: int, memory_id: int) -> bool:
        with self.db.tx() as c:
            return c.execute("DELETE FROM memories WHERE id=? AND user_id=?", (memory_id, user_id)).rowcount > 0

    def clear(self, user_id: int) -> int:
        with self.db.tx() as c:
            return c.execute("DELETE FROM memories WHERE user_id=?", (user_id,)).rowcount

    def search(self, user_id: int, query: str, limit: int = 5) -> list[dict[str, Any]]:
        terms = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1][:12]
        if not terms:
            return []
        fts = " OR ".join('"' + w.replace('"', "") + '"' for w in terms)
        return self.db.all(
            "SELECT m.id, m.kind, m.content, m.source, m.created_at, m.updated_at FROM memories_fts f "
            "JOIN memories m ON m.id = f.rowid WHERE memories_fts MATCH ? AND m.user_id=? "
            "ORDER BY bm25(memories_fts) LIMIT ?", (fts, user_id, limit))

    def context_for(self, user_id: int, query: str) -> list[dict[str, Any]]:
        """Memories injected into the prompt: relevant matches plus recent preferences."""
        if not self.settings.get(user_id).memory_enabled:
            return []
        found = {m["id"]: m for m in self.search(user_id, query, 5)}
        for m in self.db.all("SELECT id, kind, content, source, created_at, updated_at FROM memories "
                             "WHERE user_id=? AND kind='preference' ORDER BY updated_at DESC LIMIT 5", (user_id,)):
            found.setdefault(m["id"], m)
        return list(found.values())[:8]


def to_json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)
