"""Executes device tasks locally, strictly within the allowlist.

The backend already validated arguments; everything is validated again here because
this machine must never trust instructions from the network. There is deliberately
no "run command", "delete" or "install" action.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from .allowlist import Allowlist, AllowlistError
from .documents import DocumentError, extract_text

CATEGORIES = {
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt"},
    "Spreadsheets": {".xls", ".xlsx", ".csv", ".ods"},
    "Presentations": {".ppt", ".pptx", ".odp"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg"},
    "Audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"},
    "Video": {".mp4", ".mkv", ".mov", ".avi", ".webm"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Code": {".py", ".js", ".ts", ".kt", ".java", ".c", ".cpp", ".cs", ".html", ".css", ".json"},
}
TITLE_RE = re.compile(r"^[\w .,()'&-]{1,100}$")


@dataclass
class TaskOutcome:
    ok: bool
    data: dict[str, Any]
    error: str | None = None


class LocalToolExecutor:
    def __init__(self, allowlist: Allowlist,
                 launcher: Callable[[list[str]], Any] | None = None,
                 open_browser: Callable[[str], bool] | None = None,
                 on_event: Callable[[str, str, bool, str], None] | None = None):
        self.allowlist = allowlist
        self._launch = launcher or (lambda argv: subprocess.Popen(argv, shell=False, close_fds=True))
        self._browser = open_browser or webbrowser.open
        self._on_event = on_event or (lambda tool, summary, ok, err: None)

    def execute(self, tool: str, args: dict[str, Any]) -> TaskOutcome:
        start = time.monotonic()
        if tool not in self.allowlist.enabled_actions:
            out = TaskOutcome(False, {}, f"'{tool}' is not enabled on this computer.")
        else:
            handler = getattr(self, "_" + tool.removeprefix("desktop_"), None)
            try:
                if handler is None or not isinstance(args, dict):
                    raise AllowlistError(f"Unsupported action '{tool}'.")
                out = TaskOutcome(True, handler(**args))
            except TypeError:
                out = TaskOutcome(False, {}, "Invalid arguments for this action.")
            except (AllowlistError, DocumentError) as e:
                out = TaskOutcome(False, {}, str(e))
            except OSError as e:
                out = TaskOutcome(False, {}, f"The computer reported an error: {e.strerror or type(e).__name__}.")
        out.data.setdefault("elapsed_ms", int((time.monotonic() - start) * 1000))
        summary = out.data.get("message") or tool
        self._on_event(tool, summary, out.ok, out.error or "")
        return out

    # ---- actions ------------------------------------------------------------------
    def _open_app(self, app: str) -> dict:
        exe = self.allowlist.applications.get(app.strip().lower())
        if not exe:
            raise AllowlistError(f"'{app}' is not in this computer's application allowlist.")
        if not os.path.isfile(exe):
            raise AllowlistError(f"The allowlisted path for '{app}' does not exist on this computer.")
        self._launch([exe])  # fixed path, no arguments from the network, no shell
        return {"message": f"Opened {app}."}

    def _open_url(self, url: str) -> dict:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc or len(url) > 2000:
            raise AllowlistError("Only http(s) web addresses can be opened.")
        if not self._browser(url):
            raise AllowlistError("No web browser could be opened.")
        return {"message": f"Opened {p.netloc} in the browser."}

    def _create_note(self, title: str, content: str) -> dict:
        folder = self.allowlist.notes_folder
        if not folder:
            raise AllowlistError("No notes folder is configured in the allowlist.")
        if not TITLE_RE.match(title or "") or len(content) > 20000:
            raise AllowlistError("Invalid note title or content.")
        os.makedirs(folder, exist_ok=True)
        base = title.strip().rstrip(".")
        for n in range(1, 100):
            name = f"{base}.md" if n == 1 else f"{base} ({n}).md"
            path = os.path.join(folder, name)
            try:
                with open(path, "x", encoding="utf-8") as f:  # 'x' = never overwrite
                    f.write(f"# {title}\n\n{content}\n")
                return {"message": f"Note '{name}' created.", "path": path}
            except FileExistsError:
                continue
        raise AllowlistError("Too many notes with that title.")

    def _list_folder(self, folder: str) -> dict:
        root = self.allowlist.resolve_folder(folder)
        entries = []
        with os.scandir(root) as it:
            for e in sorted(it, key=lambda x: x.name.lower())[:200]:
                if e.name.startswith("."):
                    continue
                entries.append({"name": e.name, "type": "folder" if e.is_dir() else "file",
                                "size": e.stat().st_size if e.is_file() else None})
        return {"folder": root, "entries": entries, "message": f"{len(entries)} items in {os.path.basename(root)}."}

    def _read_document(self, path: str) -> dict:
        real = self.allowlist.resolve_file(path)
        doc = extract_text(real, self.allowlist.max_document_bytes)
        doc["message"] = f"Read {doc['name']} ({doc['chars']} characters)."
        return doc

    def _organize_folder(self, folder: str) -> dict:
        root = self.allowlist.resolve_folder(folder)
        moved, skipped = [], []
        for e in list(os.scandir(root)):
            if not e.is_file(follow_symlinks=False) or e.name.startswith("."):
                continue
            ext = os.path.splitext(e.name)[1].lower()
            cat = next((c for c, exts in CATEGORIES.items() if ext in exts), "Other")
            dest_dir = os.path.join(root, cat)
            dest = os.path.join(dest_dir, e.name)
            if os.path.exists(dest):
                skipped.append(e.name)  # never overwrite
                continue
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(e.path, dest)
            moved.append(f"{e.name} → {cat}")
        return {"moved": moved, "skipped_existing": skipped,
                "message": f"Moved {len(moved)} files into sub-folders; skipped {len(skipped)} that already existed."}
