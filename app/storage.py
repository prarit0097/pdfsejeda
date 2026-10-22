"""FileStore: uploaded files on disk with metadata and a time-to-live.

Layout: <uploads_dir>/<fileId>/meta.json + <fileId>/data (the bytes).
File ids look like Sejda's: <uuid>-<16 uppercase alnum>_1.
"""
from __future__ import annotations

import json
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


def safe_filename(name: str, fallback: str = "file") -> str:
    name = _UNSAFE_NAME.sub("_", (name or "").strip()).strip(". ")
    return name[:180] or fallback


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
        self._lock = threading.Lock()

    def _dir(self, file_id: str) -> Path:
        if not FILE_ID_RE.match(file_id or ""):
            raise FileNotFound(file_id)
        return self.root / file_id

    def _write_meta(self, f: StoredFile) -> None:
        (self.root / f.id / "meta.json").write_text(json.dumps(asdict(f)), encoding="utf-8")

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
        if not meta.exists():
            raise FileNotFound(file_id)
        f = StoredFile(**json.loads(meta.read_text(encoding="utf-8")))
        if time.time() - f.touched > settings.file_ttl_seconds:
            self.delete(file_id)
            raise FileNotFound(file_id)
        return f

    def touch(self, file_id: str) -> StoredFile:
        f = self.get(file_id)
        f.touched = time.time()
        self._write_meta(f)
        return f

    def set_password(self, file_id: str, password: str) -> StoredFile:
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
        for d in self.root.iterdir():
            meta = d / "meta.json"
            try:
                touched = json.loads(meta.read_text(encoding="utf-8"))["touched"]
            except Exception:
                touched = d.stat().st_mtime
            if touched < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        return removed


files = FileStore(settings.uploads_dir)
