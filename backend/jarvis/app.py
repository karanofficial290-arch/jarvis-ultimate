"""HTTP API (Starlette + Pydantic) and static web console."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__
from .assistant import Assistant, ChatError
from .config import Settings, get_settings
from .db import Database, DatabaseError, iso
from .devices import DeviceError, DeviceRegistry, TaskQueue
from .memory import PERMISSIONS, MemoryRejected, MemoryStore, SettingsStore, UserSettings
from .providers import LLMProvider, build_provider
from .search import SearchProvider, build_search
from .security import (
    Principal, RateLimiter, TokenError, decode_token, hash_password, issue_token, verify_password,
)
from .tools import ToolExecutor, build_catalog

log = logging.getLogger("jarvis")
STATIC_DIR = Path(__file__).parent / "static"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


# ---- request bodies -----------------------------------------------------------
class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(Body):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=200)


class ChatBody(Body):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: Optional[int] = None


class MemoryBody(Body):
    content: str = Field(min_length=1, max_length=2000)
    kind: Literal["preference", "project", "fact", "summary"] = "fact"


class MemoryUpdate(Body):
    content: str = Field(min_length=1, max_length=2000)
    kind: Optional[Literal["preference", "project", "fact", "summary"]] = None


class PairBody(Body):
    code: str = Field(min_length=6, max_length=20)
    name: str = Field(min_length=1, max_length=60)
    platform: Literal["android", "desktop"]


class DeviceTokenBody(Body):
    device_id: int
    device_secret: str = Field(min_length=20, max_length=200)


class HeartbeatBody(Body):
    capabilities: list[str] = Field(default_factory=list, max_length=50)


class TaskResultBody(Body):
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = Field(None, max_length=500)


class DirectTaskBody(Body):
    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None,
               search: SearchProvider | None = None) -> Starlette:
    s = settings or get_settings()
    db = Database(s.database_path)
    db.migrate()
    settings_store = SettingsStore(db, s.default_timezone)
    memory = MemoryStore(db, settings_store)
    devices = DeviceRegistry(db, s.pairing_code_ttl_s)
    tasks = TaskQueue(db)
    search = search or build_search(s)
    provider = provider or build_provider(s)
    executor = ToolExecutor(db, build_catalog(), settings_store, memory, search, devices, tasks,
                            s.tool_timeout_s, s.device_wait_s)
    assistant = Assistant(db, provider, executor, memory, settings_store, s.max_tool_rounds)
    limiter = RateLimiter()

    # ---- helpers ------------------------------------------------------------
    async def body(request: Request, model: type[BaseModel]) -> Any:
        try:
            raw = await request.json()
        except Exception:
            raise ApiError(400, "Request body must be JSON.")
        try:
            return model.model_validate(raw)
        except ValidationError as e:
            first = e.errors()[0]
            raise ApiError(422, f"{'.'.join(map(str, first['loc'])) or 'body'}: {first['msg']}")

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def limit(key: str, capacity: int, per_s: float) -> None:
        if not limiter.allow(key, capacity, per_s):
            raise ApiError(429, "Too many requests. Slow down and try again shortly.")

    def principal(request: Request, kind: str = "user") -> Principal:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            raise ApiError(401, "Authentication required.")
        try:
            p = decode_token(s.secret_key, auth[7:].strip())
        except TokenError:
            raise ApiError(401, "Invalid or expired token.")
        if p.kind != kind:
            raise ApiError(403, f"This endpoint needs a {kind} token.")
        if not db.one("SELECT id FROM users WHERE id=?", (p.user_id,)):
            raise ApiError(401, "Account no longer exists.")
        if p.kind == "device" and not devices.is_active(p.device_id):  # type: ignore[arg-type]
            raise ApiError(403, "This device has been revoked or is not approved.")
        return p

    def user(request: Request) -> int:
        return principal(request, "user").user_id

    def ok(data: Any, status: int = 200) -> JSONResponse:
        return JSONResponse(data, status_code=status)

    # ---- public ---------------------------------------------------------------
    async def health(request: Request):
        db.one("SELECT 1 AS ok")
        return ok({"status": "ok", "version": __version__, "time": iso()})

    async def status(request: Request):
        n_users = db.one("SELECT COUNT(*) AS n FROM users")["n"]
        return ok({"version": __version__, "provider": assistant.provider_info,
                   "search": {"name": search.name, "configured": search.configured},
                   "registration_open": n_users == 0 or s.allow_registration,
                   "permissions": PERMISSIONS})

    async def register(request: Request):
        limit("auth:" + client_ip(request), 10, 60)
        b = await body(request, Credentials)
        n_users = db.one("SELECT COUNT(*) AS n FROM users")["n"]
        if n_users > 0 and not s.allow_registration:
            raise ApiError(403, "Registration is closed.")
        if db.one("SELECT id FROM users WHERE username=?", (b.username,)):
            raise ApiError(409, "Username already taken.")
        with db.tx() as c:
            uid = c.execute("INSERT INTO users(username, password_hash, created_at) VALUES (?,?,?)",
                            (b.username, hash_password(b.password), iso())).lastrowid
        executor.audit(uid, "user", "auth.register", None, {"username": b.username}, "ok")
        token = issue_token(s.secret_key, Principal("user", uid), s.access_token_ttl_s)
        return ok({"token": token, "user": {"id": uid, "username": b.username}}, 201)

    async def login(request: Request):
        limit("auth:" + client_ip(request), 10, 60)
        b = await body(request, Credentials)
        row = db.one("SELECT * FROM users WHERE username=?", (b.username,))
        valid = await run_in_threadpool(verify_password, b.password, row["password_hash"] if row else
                                        "scrypt$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        if not row or not valid:
            executor.audit(row["id"] if row else None, "user", "auth.login", None, {"username": b.username}, "failed")
            raise ApiError(401, "Wrong username or password.")
        token = issue_token(s.secret_key, Principal("user", row["id"]), s.access_token_ttl_s)
        return ok({"token": token, "expires_in": s.access_token_ttl_s,
                   "user": {"id": row["id"], "username": row["username"]}})

    async def me(request: Request):
        uid = user(request)
        u = db.one("SELECT id, username, created_at FROM users WHERE id=?", (uid,))
        return ok(u)

    # ---- settings ---------------------------------------------------------------
    async def get_user_settings(request: Request):
        return ok(settings_store.get(user(request)).model_dump())

    async def put_user_settings(request: Request):
        uid = user(request)
        new = await body(request, UserSettings)
        try:
            saved = settings_store.put(uid, new)
        except Exception:
            raise ApiError(422, "Invalid settings (check the timezone name).")
        executor.audit(uid, "user", "settings.update", None, {"permissions": saved.permissions,
                       "memory_enabled": saved.memory_enabled}, "ok")
        return ok(saved.model_dump())

    # ---- chat & conversations -------------------------------------------------------
    async def chat(request: Request):
        uid = user(request)
        limit(f"chat:{uid}", 30, 60)
        b = await body(request, ChatBody)
        try:
            result = await run_in_threadpool(assistant.chat, uid, b.message, b.conversation_id)
        except ChatError as e:
            raise ApiError(e.status, e.user_message)
        return ok(result)

    async def list_conversations(request: Request):
        uid = user(request)
        return ok(db.all("SELECT id, title, created_at, updated_at FROM conversations WHERE user_id=? "
                         "ORDER BY updated_at DESC LIMIT 100", (uid,)))

    async def conversation_messages(request: Request):
        uid = user(request)
        cid = request.path_params["cid"]
        if not db.one("SELECT id FROM conversations WHERE id=? AND user_id=?", (cid, uid)):
            raise ApiError(404, "Conversation not found.")
        rows = db.all("SELECT id, role, content, created_at FROM messages WHERE conversation_id=? AND role != 'tool' "
                      "AND content != '' ORDER BY id", (cid,))
        return ok(rows)

    async def delete_conversation(request: Request):
        uid = user(request)
        with db.tx() as c:
            n = c.execute("DELETE FROM conversations WHERE id=? AND user_id=?", (request.path_params["cid"], uid)).rowcount
        if not n:
            raise ApiError(404, "Conversation not found.")
        return ok({"deleted": n})

    async def clear_conversations(request: Request):
        uid = user(request)
        with db.tx() as c:
            n = c.execute("DELETE FROM conversations WHERE user_id=?", (uid,)).rowcount
        executor.audit(uid, "user", "history.clear", None, {"conversations": n}, "ok")
        return ok({"deleted": n})

    async def summarize_conversation(request: Request):
        uid = user(request)
        try:
            mem = await run_in_threadpool(assistant.summarize, uid, request.path_params["cid"])
        except ChatError as e:
            raise ApiError(e.status, e.user_message)
        except MemoryRejected as e:
            raise ApiError(422, e.user_message)
        return ok(mem, 201)

    # ---- memory ------------------------------------------------------------------------
    async def memories(request: Request):
        uid = user(request)
        if request.method == "GET":
            q = request.query_params.get("q", "").strip()
            return ok(memory.search(uid, q, 50) if q else memory.list(uid))
        b = await body(request, MemoryBody)
        try:
            row = memory.save(uid, b.content, b.kind, source="user")
        except MemoryRejected as e:
            raise ApiError(422, e.user_message)
        return ok(row, 201)

    async def memory_item(request: Request):
        uid = user(request)
        mid = request.path_params["mid"]
        if request.method == "DELETE":
            if not memory.delete(uid, mid):
                raise ApiError(404, "Memory not found.")
            return ok({"deleted": True})
        b = await body(request, MemoryUpdate)
        try:
            row = memory.update(uid, mid, b.content, b.kind)
        except MemoryRejected as e:
            raise ApiError(422, e.user_message)
        if not row:
            raise ApiError(404, "Memory not found.")
        return ok(row)

    async def clear_memories(request: Request):
        uid = user(request)
        n = memory.clear(uid)
        executor.audit(uid, "user", "memory.clear", None, {"deleted": n}, "ok")
        return ok({"deleted": n})

    # ---- confirmations, audit, direct tasks ------------------------------------------------
    async def actions(request: Request):
        return ok(executor.pending(user(request)))

    async def resolve_action(request: Request):
        uid = user(request)
        approve = request.path_params["decision"] == "confirm"
        result = await run_in_threadpool(executor.resolve, uid, request.path_params["aid"], approve)
        if "http" in result:
            raise ApiError(result["http"], result["error"])
        return ok(result)

    async def audit(request: Request):
        uid = user(request)
        rows = db.all("SELECT id, actor, event, tool, detail, status, duration_ms, created_at FROM audit_log "
                      "WHERE user_id=? ORDER BY id DESC LIMIT 200", (uid,))
        return ok(rows)

    async def tools_list(request: Request):
        uid = user(request)
        avail = {t.name for t in executor.available(uid)}
        return ok([{"name": t.name, "description": t.description, "target": t.target, "permission": t.permission,
                    "available": t.name in avail, "confirmation": bool(t.confirm),
                    "input_schema": t.definition().input_schema} for t in executor.tools.values()])

    async def direct_task(request: Request):
        uid = user(request)
        limit(f"task:{uid}", 30, 60)
        b = await body(request, DirectTaskBody)
        tool = executor.tools.get(b.tool)
        if not tool or tool.target == "server":
            raise ApiError(400, "Only device tools can be sent directly.")
        result = await run_in_threadpool(executor.invoke, uid, None, b.tool, b.args, "user", False)
        return ok(result)

    async def list_tasks(request: Request):
        return ok(tasks.list(user(request)))

    async def get_task(request: Request):
        t = tasks.get(user(request), request.path_params["tid"])
        if not t:
            raise ApiError(404, "Task not found.")
        return ok(t)

    # ---- devices: owner side -----------------------------------------------------------------
    async def list_devices(request: Request):
        return ok(devices.list(user(request)))

    async def pairing_code(request: Request):
        uid = user(request)
        limit(f"pair-code:{uid}", 5, 60)
        code = devices.create_pairing_code(uid)
        executor.audit(uid, "user", "device.pairing_code", None, {}, "ok")
        return ok(code, 201)

    async def device_status(request: Request):
        uid = user(request)
        new = "approved" if request.path_params["action"] == "approve" else "revoked"
        try:
            dev = devices.set_status(uid, request.path_params["did"], new)  # type: ignore[arg-type]
        except DeviceError as e:
            raise ApiError(e.status, e.user_message)
        executor.audit(uid, "user", f"device.{new}", None, {"device_id": dev["id"], "name": dev["name"]}, "ok")
        return ok(dev)

    # ---- devices: device side ------------------------------------------------------------------
    async def pair(request: Request):
        limit("pair:" + client_ip(request), 5, 60)
        b = await body(request, PairBody)
        try:
            res = devices.redeem(b.code, b.name, b.platform)
        except DeviceError as e:
            executor.audit(None, "device", "device.pair", None, {"name": b.name}, "failed")
            raise ApiError(e.status, e.user_message)
        executor.audit(res.pop("user_id"), f"device:{res['device_id']}", "device.pair", None,
                       {"name": b.name, "platform": b.platform}, "pending")
        return ok(res, 201)

    async def device_token(request: Request):
        limit("devtoken:" + client_ip(request), 30, 60)
        b = await body(request, DeviceTokenBody)
        try:
            dev = devices.authenticate(b.device_id, b.device_secret)
        except DeviceError as e:
            raise ApiError(e.status, e.user_message)
        token = issue_token(s.secret_key, Principal("device", dev["user_id"], dev["id"]), s.device_token_ttl_s)
        return ok({"token": token, "expires_in": s.device_token_ttl_s})

    async def heartbeat(request: Request):
        p = principal(request, "device")
        b = await body(request, HeartbeatBody)
        devices.heartbeat(p.device_id, b.capabilities)  # type: ignore[arg-type]
        return ok({"ok": True, "time": iso()})

    async def next_task(request: Request):
        p = principal(request, "device")
        devices.heartbeat(p.device_id)  # type: ignore[arg-type]
        t = tasks.claim_next(p.device_id)  # type: ignore[arg-type]
        return ok(t) if t else Response(status_code=204)

    async def task_result(request: Request):
        p = principal(request, "device")
        b = await body(request, TaskResultBody)
        try:
            t = tasks.complete(p.device_id, request.path_params["tid"], b.ok, b.data, b.error)  # type: ignore[arg-type]
        except DeviceError as e:
            raise ApiError(e.status, e.user_message)
        executor.audit(p.user_id, p.actor, "device.task_result", t["tool"], {"task_id": t["id"]},
                       "ok" if b.ok else "failed")
        return ok({"id": t["id"], "status": t["status"]})

    # ---- console ---------------------------------------------------------------------------
    async def index(request: Request):
        return FileResponse(STATIC_DIR / "index.html")

    # ---- errors & headers ---------------------------------------------------------------------
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    async def db_error(request: Request, exc: DatabaseError):
        log.exception("database error")
        return JSONResponse({"error": "A database error occurred. Nothing was saved."}, status_code=500)

    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"error": "Internal server error."}, status_code=500)

    I = r"{%s:int}"
    routes = [
        Route("/", index),
        Route("/api/health", health),
        Route("/api/status", status),
        Route("/api/auth/register", register, methods=["POST"]),
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/me", me),
        Route("/api/settings", get_user_settings, methods=["GET"]),
        Route("/api/settings", put_user_settings, methods=["PUT"]),
        Route("/api/chat", chat, methods=["POST"]),
        Route("/api/conversations", list_conversations, methods=["GET"]),
        Route("/api/conversations", clear_conversations, methods=["DELETE"]),
        Route(f"/api/conversations/{I % 'cid'}/messages", conversation_messages),
        Route(f"/api/conversations/{I % 'cid'}/summarize", summarize_conversation, methods=["POST"]),
        Route(f"/api/conversations/{I % 'cid'}", delete_conversation, methods=["DELETE"]),
        Route("/api/memories", memories, methods=["GET", "POST"]),
        Route("/api/memories", clear_memories, methods=["DELETE"]),
        Route(f"/api/memories/{I % 'mid'}", memory_item, methods=["PUT", "DELETE"]),
        Route("/api/actions", actions),
        Route(f"/api/actions/{I % 'aid'}/" + "{decision:str}", resolve_action, methods=["POST"]),
        Route("/api/audit", audit),
        Route("/api/tools", tools_list),
        Route("/api/tasks", list_tasks, methods=["GET"]),
        Route("/api/tasks", direct_task, methods=["POST"]),
        Route(f"/api/tasks/{I % 'tid'}", get_task),
        Route("/api/devices", list_devices),
        Route("/api/devices/pairing-code", pairing_code, methods=["POST"]),
        Route("/api/devices/pair", pair, methods=["POST"]),
        Route("/api/devices/token", device_token, methods=["POST"]),
        Route(f"/api/devices/{I % 'did'}/" + "{action:str}", device_status, methods=["POST"]),
        Route("/api/device/heartbeat", heartbeat, methods=["POST"]),
        Route("/api/device/tasks/next", next_task),
        Route(f"/api/device/tasks/{I % 'tid'}/result", task_result, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ]

    async def security_headers(request: Request, call_next):
        p = request.url.path
        if p.startswith("/api/actions/") and not p.endswith(("/confirm", "/deny")) and request.method == "POST":
            return JSONResponse({"error": "Unknown decision."}, status_code=404)
        if p.startswith("/api/devices/") and request.method == "POST" and p.rsplit("/", 1)[-1] not in (
                "approve", "revoke", "pairing-code", "pair", "token"):
            return JSONResponse({"error": "Unknown device action."}, status_code=404)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if p.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    middleware = []
    middleware.append(Middleware(BaseHTTPMiddleware, dispatch=security_headers))
    if s.cors_origins:
        middleware.append(Middleware(CORSMiddleware, allow_origins=s.cors_origins,
                                     allow_methods=["GET", "POST", "PUT", "DELETE"],
                                     allow_headers=["authorization", "content-type"]))

    app = Starlette(routes=routes, middleware=middleware, exception_handlers={
        ApiError: api_error, DatabaseError: db_error, HTTPException: http_error, Exception: unhandled})

    app.state.db = db
    app.state.assistant = assistant
    app.state.executor = executor
    app.state.tasks = tasks
    app.state.devices = devices
    app.state.memory = memory
    return app
