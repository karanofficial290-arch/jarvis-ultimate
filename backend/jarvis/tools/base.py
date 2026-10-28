"""Tool framework: every capability Jarvis has goes through here.

Guarantees (enforced in code, not in the prompt):
  * only registered tools can run, with arguments validated by a Pydantic model;
  * the user's permission switches are checked on every call;
  * sensitive tools create a pending action that only an authenticated *user*
    request can confirm — the model has no tool for confirming or for changing
    permissions, so it cannot grant itself anything;
  * server tools run under a timeout; device tools go through the task queue
    to an approved, paired device only;
  * every attempt is written to the audit log with redacted arguments.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ValidationError

from ..db import Database, iso, iso_in, parse_iso, utcnow
from ..devices import DeviceRegistry, TaskQueue
from ..memory import MemoryStore, SettingsStore, UserSettings
from ..providers import ToolDefinition
from ..search import SearchProvider
from ..security import redact

Target = Literal["server", "android", "desktop"]
PENDING_TTL_S = 15 * 60


class ToolFailure(Exception):
    """Raise inside a handler to return a clean, user-safe error."""


@dataclass
class ToolContext:
    user_id: int
    conversation_id: int | None
    settings: UserSettings
    memory: MemoryStore
    search: SearchProvider


@dataclass
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    target: Target
    permission: str | None = None
    confirm: bool | Callable[[ToolContext, BaseModel], bool] = False
    timeout_s: float | None = None
    handler: Callable[[ToolContext, BaseModel], dict[str, Any]] | None = None
    summarize: Callable[[BaseModel], str] = field(default=lambda a: "")

    def definition(self) -> ToolDefinition:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return ToolDefinition(self.name, self.description, schema)

    def needs_confirmation(self, ctx: ToolContext, args: BaseModel) -> bool:
        return self.confirm(ctx, args) if callable(self.confirm) else bool(self.confirm)


def _validation_message(e: ValidationError) -> str:
    parts = []
    for err in e.errors()[:5]:
        loc = ".".join(str(x) for x in err["loc"]) or "input"
        parts.append(f"{loc}: {err['msg']}")
    return "Invalid arguments — " + "; ".join(parts)


class ToolExecutor:
    def __init__(self, db: Database, tools: list[Tool], settings_store: SettingsStore,
                 memory: MemoryStore, search: SearchProvider, devices: DeviceRegistry,
                 tasks: TaskQueue, default_timeout_s: float, device_wait_s: float):
        self.db = db
        self.tools = {t.name: t for t in tools}
        self.settings_store, self.memory, self.search = settings_store, memory, search
        self.devices, self.tasks = devices, tasks
        self.default_timeout_s, self.device_wait_s = default_timeout_s, device_wait_s
        self._pool = cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool")

    # ---- discovery -------------------------------------------------------
    def available(self, user_id: int) -> list[Tool]:
        s = self.settings_store.get(user_id)
        platforms = {d["platform"] for d in self.devices.list(user_id) if d["status"] == "approved"}
        out = []
        for t in self.tools.values():
            if t.permission and not s.permissions.get(t.permission, False):
                continue
            if t.target != "server" and t.target not in platforms:
                continue
            out.append(t)
        return out

    def definitions(self, user_id: int) -> list[ToolDefinition]:
        return [t.definition() for t in self.available(user_id)]

    # ---- audit -------------------------------------------------------------
    def audit(self, user_id: int | None, actor: str, event: str, tool: str | None, detail: Any,
              status: str, duration_ms: int | None = None) -> None:
        try:
            with self.db.tx() as c:
                c.execute("INSERT INTO audit_log(user_id, actor, event, tool, detail, status, duration_ms, created_at)"
                          " VALUES (?,?,?,?,?,?,?,?)",
                          (user_id, actor, event, tool, json.dumps(redact(detail), ensure_ascii=False)[:4000],
                           status, duration_ms, iso()))
        except Exception:  # auditing must never break the user flow
            pass

    # ---- invocation ---------------------------------------------------------
    def invoke(self, user_id: int, conversation_id: int | None, name: str, raw_args: Any,
               actor: str = "assistant", confirmed: bool = False) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            self.audit(user_id, actor, "tool.unknown", name, {}, "rejected")
            return {"ok": False, "error": f"Unknown tool '{name}'."}
        try:
            args = tool.input_model.model_validate(raw_args if isinstance(raw_args, dict) else {})
        except ValidationError as e:
            msg = _validation_message(e)
            self.audit(user_id, actor, "tool.invalid", name, raw_args if isinstance(raw_args, dict) else {}, "rejected")
            return {"ok": False, "error": msg}

        settings = self.settings_store.get(user_id)
        if tool.permission and not settings.permissions.get(tool.permission, False):
            self.audit(user_id, actor, "tool.denied", name, args.model_dump(), "denied")
            return {"ok": False, "error": f"Permission '{tool.permission}' is turned off in privacy settings."}

        ctx = ToolContext(user_id, conversation_id, settings, self.memory, self.search)
        if not confirmed and tool.needs_confirmation(ctx, args):
            summary = tool.summarize(args) or f"Run {name}"
            with self.db.tx() as c:
                cur = c.execute(
                    "INSERT INTO pending_actions(user_id, conversation_id, tool, args, summary, status, created_at, expires_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (user_id, conversation_id, name, args.model_dump_json(), summary, "awaiting", iso(), iso_in(PENDING_TTL_S)))
                action_id = cur.lastrowid
            self.audit(user_id, actor, "tool.confirmation_requested", name, args.model_dump(), "awaiting")
            return {"ok": False, "status": "awaiting_confirmation", "action_id": action_id, "summary": summary,
                    "note": "Not executed. The user must approve this in the app; you cannot approve it yourself."}

        start = time.monotonic()
        if tool.target == "server":
            result = self._run_server(tool, ctx, args)
        else:
            result = self._run_on_device(tool, user_id, args, actor)
        ms = int((time.monotonic() - start) * 1000)
        status = "ok" if result.get("ok") else result.get("status", "error")
        self.audit(user_id, actor, "tool.call", name,
                   {"args": args.model_dump(), "error": result.get("error")}, status, ms)
        return result

    def _run_server(self, tool: Tool, ctx: ToolContext, args: BaseModel) -> dict[str, Any]:
        assert tool.handler is not None
        fut = self._pool.submit(tool.handler, ctx, args)
        try:
            data = fut.result(timeout=tool.timeout_s or self.default_timeout_s)
            return {"ok": True, "data": data}
        except cf.TimeoutError:
            return {"ok": False, "error": f"{tool.name} timed out."}
        except ToolFailure as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # never leak internals to the model
            msg = getattr(e, "user_message", None) or "Internal error while running the tool."
            return {"ok": False, "error": msg}

    def _run_on_device(self, tool: Tool, user_id: int, args: BaseModel, actor: str) -> dict[str, Any]:
        candidates = self.devices.online_targets(user_id, tool.target)  # approved only
        if not candidates:
            label = "Android phone" if tool.target == "android" else "Windows computer"
            return {"ok": False, "error": f"No approved {label} is paired with Jarvis."}
        candidates.sort(key=lambda d: (d["online"], d["last_seen_at"] or ""), reverse=True)
        dev = candidates[0]
        task = self.tasks.enqueue(user_id, dev["id"], tool.name, args.model_dump(),
                                  origin="assistant" if actor == "assistant" else "user")
        done = self.tasks.wait(user_id, task["id"], self.device_wait_s if dev["online"] else 0)
        if done["status"] == "succeeded":
            return {"ok": True, "data": done["result"] or {}, "device": dev["name"], "task_id": task["id"]}
        if done["status"] in ("failed", "expired"):
            return {"ok": False, "error": done["error"] or "The device reported a failure.",
                    "device": dev["name"], "task_id": task["id"]}
        return {"ok": False, "status": "queued", "task_id": task["id"], "device": dev["name"],
                "note": "Sent to the device; no result yet." + ("" if dev["online"] else " The device appears offline.")}

    # ---- confirmations (user-only path) --------------------------------------
    def pending(self, user_id: int) -> list[dict[str, Any]]:
        self._expire_pending()
        rows = self.db.all("SELECT id, conversation_id, tool, args, summary, status, created_at, expires_at "
                           "FROM pending_actions WHERE user_id=? AND status='awaiting' ORDER BY id", (user_id,))
        for r in rows:
            r["args"] = redact(json.loads(r["args"]))
        return rows

    def _expire_pending(self) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE pending_actions SET status='expired' WHERE status='awaiting' AND expires_at < ?", (iso(),))

    def resolve(self, user_id: int, action_id: int, approve: bool) -> dict[str, Any]:
        self._expire_pending()
        row = self.db.one("SELECT * FROM pending_actions WHERE id=? AND user_id=?", (action_id, user_id))
        if not row:
            return {"ok": False, "error": "Action not found.", "http": 404}
        if row["status"] != "awaiting":
            return {"ok": False, "error": f"Action is already {row['status']}.", "http": 409}
        with self.db.tx() as c:
            n = c.execute("UPDATE pending_actions SET status=? WHERE id=? AND status='awaiting'",
                          ("confirmed" if approve else "denied", action_id)).rowcount
        if n != 1:
            return {"ok": False, "error": "Action was resolved concurrently.", "http": 409}
        if not approve:
            self.audit(user_id, "user", "tool.denied_by_user", row["tool"], json.loads(row["args"]), "denied")
            return {"ok": True, "status": "denied", "action_id": action_id}
        result = self.invoke(user_id, row["conversation_id"], row["tool"], json.loads(row["args"]),
                             actor="user", confirmed=True)
        with self.db.tx() as c:
            c.execute("UPDATE pending_actions SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), action_id))
        return {**result, "action_id": action_id, "tool": row["tool"]}
