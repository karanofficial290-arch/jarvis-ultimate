"""Background device agent: polls the backend for tasks (outbound HTTPS only).

The computer never opens a listening port, so it is not exposed to the internet.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .client import BackendClient, BackendError
from .local_tools import LocalToolExecutor, TaskOutcome

log = logging.getLogger("jarvis.agent")

STATES = ("stopped", "connecting", "online", "offline", "pending_approval", "revoked", "error")


class DeviceAgent:
    def __init__(self, client: BackendClient, device_id: int, device_secret: str, executor: LocalToolExecutor,
                 poll_interval: float = 1.5, heartbeat_every: float = 20.0, task_timeout: float = 60.0,
                 on_state: Callable[[str, str], None] | None = None,
                 on_task: Callable[[dict, TaskOutcome], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.client, self.device_id, self.secret = client, device_id, device_secret
        self.executor = executor
        self.poll_interval, self.heartbeat_every, self.task_timeout = poll_interval, heartbeat_every, task_timeout
        self.on_state = on_state or (lambda s, d: None)
        self.on_task = on_task or (lambda t, o: None)
        self._sleep = sleep
        self.state, self.detail = "stopped", ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_heartbeat = 0.0

    def _set(self, state: str, detail: str = "") -> None:
        if (state, detail) != (self.state, self.detail):
            self.state, self.detail = state, detail
            self.on_state(state, detail)

    # ---- lifecycle ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="jarvis-agent", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._set("stopped")

    def _loop(self) -> None:
        backoff = self.poll_interval
        while not self._stop.is_set():
            delay = self.run_once()
            if self.state in ("revoked",):
                return
            backoff = self.poll_interval if delay is None else min(60.0, max(backoff * 2, delay))
            self._stop.wait(self.poll_interval if delay is None else backoff)

    # ---- one iteration (also used directly by tests) ---------------------------------
    def run_once(self) -> float | None:
        """Returns None on success, or a suggested delay before retrying."""
        try:
            if not self.client.device_token:
                self._set("connecting")
                self.client.fetch_device_token(self.device_id, self.secret)
                self._last_heartbeat = 0
            if time.monotonic() - self._last_heartbeat > self.heartbeat_every:
                self.client.heartbeat(self.executor.allowlist.capabilities())
                self._last_heartbeat = time.monotonic()
            self._set("online")
            task = self.client.next_task()
            if task:
                self._handle(task)
            return None
        except BackendError as e:
            if e.status == 401:
                self.client.device_token = None
                self._set("connecting", "token expired; re-authenticating")
                return 1.0
            if e.status == 403:
                self.client.device_token = None
                if "waiting for approval" in e.message:
                    self._set("pending_approval", "Approve this computer in the Jarvis app.")
                    return 10.0
                self._set("revoked", e.message)
                self._stop.set()
                return 60.0
            if e.status == 0:
                self._set("offline", e.message)
                return 5.0
            self._set("error", e.message)
            return 10.0

    def _handle(self, task: dict) -> None:
        box: dict[str, TaskOutcome] = {}
        worker = threading.Thread(target=lambda: box.setdefault("o", self.executor.execute(task["tool"], task.get("args") or {})),
                                  daemon=True)
        worker.start()
        worker.join(self.task_timeout)
        outcome = box.get("o") or TaskOutcome(False, {}, f"Timed out after {int(self.task_timeout)} s on the computer.")
        try:
            self.client.post_result(task["id"], outcome.ok, outcome.data, outcome.error)
        except BackendError as e:
            log.warning("could not report task %s: %s", task["id"], e.message)
        self.on_task(task, outcome)
