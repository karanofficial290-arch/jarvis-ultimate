"""SQLite access layer with a tiny forward-only migration runner."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class DatabaseError(Exception):
    """Raised when a database operation fails; message is safe to show users."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat(timespec="seconds")


def iso_in(seconds: float) -> str:
    return iso(utcnow() + timedelta(seconds=seconds))


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


class Database:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- migrations -------------------------------------------------
    def migrate(self) -> list[str]:
        applied: list[str] = []
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {r[0] for r in self._conn.execute("SELECT name FROM schema_migrations")}
            for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if f.name in done:
                    continue
                self._conn.execute("BEGIN")
                try:
                    for stmt in _split_sql(f.read_text(encoding="utf-8")):
                        self._conn.execute(stmt)
                    self._conn.execute(
                        "INSERT INTO schema_migrations VALUES (?, ?)", (f.name, iso())
                    )
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise
                applied.append(f.name)
        return applied

    # ---- helpers ----------------------------------------------------
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except sqlite3.Error as e:
                self._conn.execute("ROLLBACK")
                raise DatabaseError("Database operation failed") from e
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            try:
                return self._conn.execute(sql, params)
            except sqlite3.Error as e:
                raise DatabaseError("Database operation failed") from e

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        row = self.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.execute(sql, params).fetchall()]


def _split_sql(script: str) -> list[str]:
    """Split a migration script into statements, keeping trigger bodies intact."""
    stmts, buf, in_trigger = [], [], False
    for line in script.splitlines():
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            in_trigger = True
        if in_trigger:
            if upper == "END;":
                stmts.append("\n".join(buf))
                buf, in_trigger = [], False
        elif stripped.endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    if "".join(buf).strip():
        stmts.append("\n".join(buf))
    return stmts


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
