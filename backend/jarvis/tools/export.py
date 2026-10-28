"""Regenerate shared/tool_catalog.json:  python -m jarvis.tools.export"""
import json
from pathlib import Path

from .catalog import catalog_json

out = Path(__file__).resolve().parents[3] / "shared" / "tool_catalog.json"
out.write_text(json.dumps(catalog_json(), indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out}")
