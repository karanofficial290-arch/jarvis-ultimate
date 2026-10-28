import time

import jwt
import pytest

from jarvis.db import Database, DatabaseError
from jarvis.memory import MemoryRejected, MemoryStore, SettingsStore, UserSettings, sensitive_reason
from jarvis.security import (
    Principal, RateLimiter, TokenError, decode_token, hash_password, issue_token, redact, verify_password,
)

SECRET = "s" * 40


def test_password_hashing():
    h = hash_password("hunter2-but-longer")
    assert h.startswith("scrypt$") and "hunter2" not in h
    assert verify_password("hunter2-but-longer", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "garbage")


def test_tokens():
    t = issue_token(SECRET, Principal("device", 1, 7), 60)
    assert decode_token(SECRET, t) == Principal("device", 1, 7)
    with pytest.raises(TokenError):
        decode_token("other" * 10, t)
    with pytest.raises(TokenError):
        decode_token(SECRET, issue_token(SECRET, Principal("user", 1), -5))
    forged = jwt.encode({"sub": "1", "kind": "admin", "exp": int(time.time()) + 60}, SECRET, algorithm="HS256")
    with pytest.raises(TokenError):
        decode_token(SECRET, forged)
    none_alg = jwt.encode({"sub": "1", "kind": "user", "exp": int(time.time()) + 60}, None, algorithm="none")
    with pytest.raises(TokenError):
        decode_token(SECRET, none_alg)


def test_rate_limiter():
    rl = RateLimiter()
    assert all(rl.allow("k", 3, 60) for _ in range(3))
    assert not rl.allow("k", 3, 60)
    assert rl.allow("other", 3, 60)


def test_redaction():
    r = redact({"password": "p", "api_key": "k", "body": "private message", "url": "https://x", "nested": {"token": "t"}})
    assert r == {"password": "[redacted]", "api_key": "[redacted]", "body": "[15 chars]", "url": "https://x",
                 "nested": {"token": "[redacted]"}}


@pytest.mark.parametrize("text", [
    "my gmail password is tiger123", "the OTP is 482913", "card 4111 1111 1111 1111 exp 12/29",
    "CVV 123", "aadhaar 2345 6789 0123", "PAN ABCDE1234F", "key sk-abcdefghijklmnopqrstuv",
    "my UPI PIN is 4321", "मेरा पासवर्ड abc है",
])
def test_sensitive_data_detected(text):
    assert sensitive_reason(text)


@pytest.mark.parametrize("text", [
    "I prefer tea over coffee", "My project uses Kotlin and FastAPI", "Call me Karan",
    "Order number 1234567890123 shipped",  # not Luhn-valid
])
def test_ordinary_text_allowed(text):
    assert sensitive_reason(text) is None


@pytest.fixture
def store(tmp_path):
    db = Database(str(tmp_path / "m.db"))
    db.migrate()
    db.execute("INSERT INTO users(username, password_hash, created_at) VALUES ('a','x','now')")
    db.execute("INSERT INTO users(username, password_hash, created_at) VALUES ('b','x','now')")
    ss = SettingsStore(db, "UTC")
    return MemoryStore(db, ss), ss, db


def test_memory_crud_and_search(store):
    mem, _, _ = store
    a = mem.save(1, "I prefer dark mode in every app", "preference")
    b = mem.save(1, "Project Falcon deadline is Friday", "project")
    assert a["id"] and mem.get(1, a["id"])["content"].startswith("I prefer")
    assert [m["id"] for m in mem.search(1, "falcon deadline")] == [b["id"]]
    assert mem.search(2, "falcon") == []  # other users can't see it
    assert mem.update(1, b["id"], "Project Falcon deadline moved to Monday")["content"].endswith("Monday")
    assert mem.search(1, "monday")[0]["id"] == b["id"]
    assert mem.update(2, b["id"], "hijack") is None
    assert not mem.delete(2, b["id"]) and mem.delete(1, b["id"])
    assert [m["id"] for m in mem.list(1)] == [a["id"]]
    assert mem.context_for(1, "anything")[0]["id"] == a["id"]  # preferences always offered
    assert mem.clear(1) == 1 and mem.list(1) == []


def test_memory_rejects_sensitive_and_respects_disable(store):
    mem, ss, _ = store
    with pytest.raises(MemoryRejected, match="password"):
        mem.save(1, "wifi password is hunter22")
    ss.put(1, UserSettings(memory_enabled=False))
    with pytest.raises(MemoryRejected, match="turned off"):
        mem.save(1, "I like tea")
    assert mem.context_for(1, "tea") == []


def test_memory_not_reported_saved_when_db_fails(store):
    mem, _, db = store
    db.execute("DROP TRIGGER memories_ai")
    db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON memories BEGIN SELECT RAISE(ABORT, 'disk full'); END;")
    with pytest.raises(DatabaseError):
        mem.save(1, "I like tea")
    assert mem.list(1) == []


def test_migrations_idempotent_and_settings_validation(store):
    _, ss, db = store
    assert db.migrate() == []
    with pytest.raises(Exception):
        ss.put(1, UserSettings(timezone="Mars/Olympus"))
    s = UserSettings(timezone="Asia/Kolkata")
    s.permissions["made.up"] = True  # unknown permissions are dropped, never granted
    saved = ss.put(1, s)
    assert "made.up" not in saved.permissions and ss.get(1).timezone == "Asia/Kolkata"
