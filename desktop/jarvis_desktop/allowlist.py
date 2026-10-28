"""The local allowlist: the ONLY apps, folders and actions the agent may touch.

It lives on the computer and is edited by the user, never by the backend or the AI.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ALL_ACTIONS = (
    "desktop_open_app", "desktop_open_url", "desktop_create_note",
    "desktop_list_folder", "desktop_read_document", "desktop_organize_folder",
)


class AllowlistError(Exception):
    pass


def _expand(p: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.expandvars(os.path.expanduser(p))))


@dataclass
class Allowlist:
    applications: dict[str, str] = field(default_factory=dict)   # name -> absolute exe path
    folders: dict[str, str] = field(default_factory=dict)        # name -> absolute folder
    notes_folder: str = ""
    enabled_actions: tuple[str, ...] = ALL_ACTIONS
    max_document_bytes: int = 5_000_000

    @classmethod
    def from_dict(cls, d: dict) -> "Allowlist":
        if not isinstance(d, dict):
            raise AllowlistError("allowlist must be a JSON object")
        apps = {str(k).strip().lower(): os.path.expandvars(str(v)) for k, v in (d.get("applications") or {}).items()}
        folders = {str(k).strip().lower(): _expand(str(v)) for k, v in (d.get("folders") or {}).items()}
        actions = tuple(a for a in (d.get("enabled_actions") or ALL_ACTIONS) if a in ALL_ACTIONS)
        notes = _expand(d["notes_folder"]) if d.get("notes_folder") else ""
        return cls(apps, folders, notes, actions, int(d.get("max_document_bytes", 5_000_000)))

    @classmethod
    def load(cls, path: str | Path) -> "Allowlist":
        p = Path(path)
        if not p.exists():
            raise AllowlistError(f"allowlist file not found: {p}")
        try:
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise AllowlistError(f"allowlist is not valid JSON: {e}") from e

    def capabilities(self) -> list[str]:
        return list(self.enabled_actions)

    # ---- path policy ------------------------------------------------------------
    def resolve_folder(self, ref: str) -> str:
        """Accept a folder *name* from the allowlist or a path inside an allowed folder."""
        key = ref.strip().lower()
        if key in self.folders:
            return self.folders[key]
        real = _expand(ref)
        if self.inside_allowed(real) and os.path.isdir(real):
            return real
        raise AllowlistError(f"'{ref}' is not an approved folder on this computer.")

    def resolve_file(self, ref: str) -> str:
        candidates = []
        if os.path.isabs(os.path.expandvars(os.path.expanduser(ref))):
            candidates.append(_expand(ref))
        else:
            candidates += [_expand(os.path.join(root, ref)) for root in self.folders.values()]
        for real in candidates:
            if self.inside_allowed(real) and os.path.isfile(real):
                return real
        if any(not self.inside_allowed(c) for c in candidates):
            raise AllowlistError("That file is outside the approved folders.")
        raise AllowlistError(f"File '{ref}' was not found in the approved folders.")

    def inside_allowed(self, real: str) -> bool:
        for root in self.folders.values():
            try:
                if os.path.commonpath([real, root]) == root:
                    return True
            except ValueError:  # different drives on Windows
                continue
        return False
