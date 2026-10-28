"""Password hashing, signed tokens, rate limiting and log redaction."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

import jwt

# ---- passwords (scrypt, stdlib) -------------------------------------
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


def hash_secret(value: str) -> str:
    """Fast hash for high-entropy random secrets (device secrets, pairing codes)."""
    return hashlib.sha256(value.encode()).hexdigest()


def new_device_secret() -> str:
    return secrets.token_urlsafe(32)


def new_pairing_code() -> str:
    # 8 chars from an unambiguous alphabet: ~40 bits, short-lived, single use, rate limited.
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


# ---- tokens ---------------------------------------------------------
TokenKind = Literal["user", "device"]


@dataclass(frozen=True)
class Principal:
    kind: TokenKind
    user_id: int
    device_id: int | None = None

    @property
    def actor(self) -> str:
        return f"device:{self.device_id}" if self.kind == "device" else "user"


class TokenError(Exception):
    pass


def issue_token(secret: str, principal: Principal, ttl_s: int) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(principal.user_id),
        "kind": principal.kind,
        "iat": now,
        "exp": now + ttl_s,
        "jti": secrets.token_hex(8),
    }
    if principal.device_id is not None:
        payload["dev"] = principal.device_id
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(secret: str, token: str) -> Principal:
    try:
        p = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub", "kind"]})
    except jwt.PyJWTError as e:
        raise TokenError("invalid or expired token") from e
    kind = p.get("kind")
    if kind not in ("user", "device"):
        raise TokenError("invalid token kind")
    dev = p.get("dev")
    if kind == "device" and not isinstance(dev, int):
        raise TokenError("invalid device token")
    return Principal(kind=kind, user_id=int(p["sub"]), device_id=dev if kind == "device" else None)


# ---- rate limiting (in-process token bucket) -------------------------
class RateLimiter:
    """Simple per-key token bucket. Single-process only; use a shared store when scaling out."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, capacity: int, per_seconds: float) -> bool:
        rate = capacity / per_seconds
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(capacity), now))
            tokens = min(capacity, tokens + (now - last) * rate)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1, now)
            return True


# ---- redaction for logs ----------------------------------------------
_SECRET_KEYS = {"password", "secret", "token", "api_key", "apikey", "authorization", "code"}
_PRIVATE_TEXT_KEYS = {"body", "content", "text", "message", "note"}


def redact(value: Any, depth: int = 0) -> Any:
    """Make tool arguments/results safe for the audit log: drop secrets, shorten private text."""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            lk = str(k).lower()
            if any(s in lk for s in _SECRET_KEYS):
                out[k] = "[redacted]"
            elif lk in _PRIVATE_TEXT_KEYS and isinstance(v, str):
                out[k] = f"[{len(v)} chars]"
            else:
                out[k] = redact(v, depth + 1)
        return out
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value[:20]]
    if isinstance(value, str) and len(value) > 160:
        return value[:160] + "…"
    return value
