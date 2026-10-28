"""Extract plain text from user-approved documents. Optional formats need optional packages."""
from __future__ import annotations

import os

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".ts", ".html", ".xml", ".yaml", ".yml",
            ".ini", ".cfg", ".kt", ".java", ".c", ".cpp", ".cs", ".sql", ".rst"}
MAX_CHARS = 60_000


class DocumentError(Exception):
    pass


def extract_text(path: str, max_bytes: int) -> dict:
    size = os.path.getsize(path)
    if size > max_bytes:
        raise DocumentError(f"File is too large ({size // 1024} KB; limit {max_bytes // 1024} KB).")
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXT:
        with open(path, "rb") as f:
            raw = f.read()
        for enc in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise DocumentError("Could not decode the text file.")
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise DocumentError("Reading PDFs needs the optional 'pypdf' package (pip install pypdf).")
        text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    elif ext == ".docx":
        try:
            import docx
        except ImportError:
            raise DocumentError("Reading Word files needs the optional 'python-docx' package.")
        text = "\n".join(p.text for p in docx.Document(path).paragraphs)
    else:
        raise DocumentError(f"Unsupported file type '{ext}'.")
    truncated = len(text) > MAX_CHARS
    return {"name": os.path.basename(path), "chars": len(text), "truncated": truncated, "text": text[:MAX_CHARS]}
