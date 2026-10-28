"""HTTPS client for the JARVIS backend (user session + device identity)."""
from __future__ import annotations

from typing import Any

import requests


class BackendError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class BackendClient:
    def __init__(self, base_url: str, timeout: float = 15.0, session: requests.Session | None = None):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.http = session or requests.Session()
        self.user_token: str | None = None
        self.device_token: str | None = None

    def _req(self, method: str, path: str, token: str | None = None, body: Any = None,
             timeout: float | None = None) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            r = self.http.request(method, self.base + path, json=body, headers=headers, timeout=timeout or self.timeout)
        except requests.RequestException as e:
            raise BackendError(0, f"Cannot reach the backend ({type(e).__name__}).") from e
        if r.status_code == 204:
            return None
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400:
            raise BackendError(r.status_code, data.get("error") or f"HTTP {r.status_code}")
        return data

    # ---- user -------------------------------------------------------------------
    def status(self) -> dict:
        return self._req("GET", "/api/status")

    def login(self, username: str, password: str) -> dict:
        d = self._req("POST", "/api/auth/login", body={"username": username, "password": password})
        self.user_token = d["token"]
        return d

    def chat(self, message: str, conversation_id: int | None) -> dict:
        return self._req("POST", "/api/chat", self.user_token, {"message": message, "conversation_id": conversation_id},
                         timeout=120)

    def pending_actions(self) -> list[dict]:
        return self._req("GET", "/api/actions", self.user_token)

    def resolve_action(self, action_id: int, approve: bool) -> dict:
        return self._req("POST", f"/api/actions/{action_id}/{'confirm' if approve else 'deny'}", self.user_token,
                         timeout=60)

    # ---- device ---------------------------------------------------------------------
    def pair(self, code: str, name: str) -> dict:
        return self._req("POST", "/api/devices/pair", body={"code": code, "name": name, "platform": "desktop"})

    def fetch_device_token(self, device_id: int, secret: str) -> str:
        d = self._req("POST", "/api/devices/token", body={"device_id": device_id, "device_secret": secret})
        self.device_token = d["token"]
        return self.device_token

    def heartbeat(self, capabilities: list[str]) -> None:
        self._req("POST", "/api/device/heartbeat", self.device_token, {"capabilities": capabilities})

    def next_task(self) -> dict | None:
        return self._req("GET", "/api/device/tasks/next", self.device_token)

    def post_result(self, task_id: int, ok: bool, data: dict, error: str | None) -> dict:
        return self._req("POST", f"/api/device/tasks/{task_id}/result", self.device_token,
                         {"ok": ok, "data": data, "error": error})
