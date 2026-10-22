"""FileStore: uploaded files on disk with metadata and a time-to-live.

Layout: <uploads_dir>/<fileId>/meta.json + <fileId>/data (the bytes).
File ids look like Sejda's: <uuid>-<16 uppercase alnum>_1.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import string
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import settings

_ALNUM = string.ascii_uppercase + string.digits
FILE_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-[A-Z0-9]{16}_\d$")
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
_MAX_NAME_BYTES = 200  # most filesystems allow 255 bytes per name; leave room for "-2" de-dup suffixes


def safe_filename(name: str, fallback: str = "file") -> str:
    """A single path component that is safe on Windows and POSIX: no separators or control
    characters, no leading/trailing dots or spaces, not a reserved device name, at most
    _MAX_NAME_BYTES of UTF-8 — truncation keeps the extension."""
    name = _UNSAFE_NAME.sub("_", (name or "").strip()).strip(". ")
    if not name:
        return fallback
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 10:
        stem, ext = name, ""
    if stem.split(".")[0].upper() in _RESERVED:
        stem = "_" + stem
    suffix = ("." + ext) if ext else ""
    budget = _MAX_NAME_BYTES - len(suffix.encode("utf-8"))
    raw = stem.encode("utf-8")
    if len(raw) > budget:
        stem = raw[:budget].decode("utf-8", "ignore").rstrip(". ")
    return (stem + suffix) or fallback


def new_file_id() -> str:
    return f"{uuid.uuid4()}-{''.join(secrets.choice(_ALNUM) for _ in range(16))}_1"


@dataclass
class StoredFile:
    id: str
    name: str
    size: int
    mime: str
    created: float
    touched: float
    password: str | None = None
    source_url: str | None = None

    @property
    def path(self) -> Path:
        return settings.uploads_dir / self.id / "data"


class FileNotFound(Exception):
    pass


class FileStore:
    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.RLock()

    def _dir(self, file_id: str) -> Path:
        if not FILE_ID_RE.match(file_id or ""):
            raise FileNotFound(file_id)
        return self.root / file_id

    def _write_meta(self, f: StoredFile) -> None:
        # Atomic replacement keeps readers from observing truncated JSON while a
        # keep-alive or password update writes metadata from another thread.
        target = self._dir(f.id) / "meta.json"
        temporary = target.with_name(f".meta-{secrets.token_hex(8)}.tmp")
        try:
            temporary.write_text(json.dumps(asdict(f)), encoding="utf-8")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def create_empty(self, name: str, mime: str = "application/octet-stream", source_url: str | None = None) -> StoredFile:
        fid = new_file_id()
        (self.root / fid).mkdir(parents=True)
        now = time.time()
        f = StoredFile(fid, safe_filename(name), 0, mime, now, now, source_url=source_url)
        f.path.touch()
        self._write_meta(f)
        return f

    def finalize(self, f: StoredFile) -> StoredFile:
        f.size = f.path.stat().st_size
        self._write_meta(f)
        return f

    def save_bytes(self, name: str, data: bytes, mime: str = "application/pdf") -> StoredFile:
        f = self.create_empty(name, mime)
        f.path.write_bytes(data)
        return self.finalize(f)

    def get(self, file_id: str) -> StoredFile:
        meta = self._dir(file_id) / "meta.json"
        try:
            f = StoredFile(**json.loads(meta.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            raise FileNotFound(file_id) from None
        if f.id != file_id or not f.path.is_file():
            raise FileNotFound(file_id)
        if time.time() - f.touched > settings.file_ttl_seconds:
            self.delete(file_id)
            raise FileNotFound(file_id)
        return f

    def touch(self, file_id: str) -> StoredFile:
        with self._lock:
            f = self.get(file_id)
            f.touched = time.time()
            self._write_meta(f)
            return f

    def set_password(self, file_id: str, password: str) -> StoredFile:
        with self._lock:
            f = self.get(file_id)
            f.password = password
            self._write_meta(f)
            return f

    def delete(self, file_id: str) -> None:
        try:
            shutil.rmtree(self._dir(file_id), ignore_errors=True)
        except FileNotFound:
            pass

    def sweep(self) -> int:
        """Delete expired entries. Returns how many were removed."""
        removed = 0
        cutoff = time.time() - settings.file_ttl_seconds
        for d in list(self.root.iterdir()):
            try:
                meta = d / "meta.json"
                try:
                    touched = json.loads(meta.read_text(encoding="utf-8"))["touched"]
                except Exception:  # unfinished chunked upload or broken entry: newest write wins
                    touched = max([d.stat().st_mtime] + [c.stat().st_mtime for c in d.iterdir()] if d.is_dir() else [d.stat().st_mtime])
                if touched < cutoff:
                    if d.is_dir():
                        shutil.rmtree(d, ignore_errors=True)
                    else:
                        d.unlink(missing_ok=True)
                    removed += not d.exists()  # a file still open elsewhere (Windows) is retried next sweep
            except OSError:  # deleted concurrently
                continue
        return removed


files = FileStore(settings.uploads_dir)
