"""Task model and in-process job queue.

A task = one POST /api/tasks. It moves Queued -> Processing -> Completed | Failed
(or is Cancelled). Handlers live in app/tools and write their outputs into
ctx.out_dir; when there is more than one output a zip of all of them is added
and becomes the main result (resultFilename), like Sejda.
"""
from __future__ import annotations

import logging
import secrets
import shutil
import threading
import time
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .storage import FileNotFound, StoredFile, files, safe_filename

log = logging.getLogger("jobs")

_TASK_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ123456789"  # no I, L, O, 0


def new_task_id() -> str:
    rand = "".join(secrets.choice(_TASK_ALPHABET) for _ in range(8))
    return f"{rand}-{datetime.now(timezone.utc):%Y%m%d%H%M}"


class TaskError(Exception):
    """A failure whose message is safe to show to the user."""


class TaskCancelled(Exception):
    pass


@dataclass
class InputFile:
    id: str
    name: str
    path: Path
    password: str | None

    @property
    def stem(self) -> str:
        return Path(self.name).stem or "document"


@dataclass
class Task:
    id: str
    type: str
    params: dict
    file_ids: list[str]
    status: str = "Queued"
    remark: str | None = None
    warnings: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    result_filename: str | None = None
    result_items: list[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    finished: float | None = None
    cancelled: bool = False

    @property
    def out_dir(self) -> Path:
        return settings.results_dir / self.id


class TaskContext:
    def __init__(self, task: Task, inputs: list[InputFile]):
        self.task = task
        self.params = task.params
        self.inputs = inputs
        self.out_dir = task.out_dir
        self.work_dir = task.out_dir.parent / f"{task.id}.work"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # helpers for handlers ------------------------------------------------
    def output(self, name: str) -> Path:
        """Path for a new output file; de-duplicates names."""
        name = safe_filename(name, "result")
        p = self.out_dir / name
        n = 2
        while p.exists():
            p = self.out_dir / f"{Path(name).stem}-{n}{Path(name).suffix}"
            n += 1
        return p

    def temp(self, name: str) -> Path:
        return self.work_dir / safe_filename(name)

    def remark(self, text: str) -> None:
        self.task.remark = text

    def warn(self, text: str) -> None:
        self.task.warnings.append(text)

    def check_cancelled(self) -> None:
        if self.task.cancelled:
            raise TaskCancelled()

    def param(self, name: str, default=None):
        v = self.params.get(name, default)
        return default if v == "" else v

    def flag(self, name: str, default: bool = False) -> bool:
        v = self.params.get(name, default)
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return bool(v)

    def number(self, name: str, default: float) -> float:
        v = self.params.get(name, default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default


class JobQueue:
    def __init__(self, workers: int):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="task")
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def submit(self, task_type: str, file_ids: list[str], params: dict) -> Task:
        from .tools.registry import get_tool

        tool = get_tool(task_type)  # raises KeyError for unknown type
        stored = [files.get(fid) for fid in file_ids]  # raises FileNotFound
        tool.validate(stored, params)
        task = Task(new_task_id(), task_type, params, file_ids)
        with self._lock:
            self._tasks[task.id] = task
        self._pool.submit(self._run, task, stored)
        return task

    def get(self, task_id: str) -> Task | None:
        task = self._tasks.get(task_id)
        if task and task.finished and time.time() - task.finished > settings.file_ttl_seconds:
            self.delete(task_id)
            return None
        return task

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.cancelled = True
        if task.status in ("Queued", "Processing"):
            task.status = "Failed"
            task.failure_reason = "Cancelled"
            task.finished = time.time()
        return True

    def delete(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.pop(task_id, None)
        if task:
            task.cancelled = True
            shutil.rmtree(task.out_dir, ignore_errors=True)

    def sweep(self) -> None:
        for tid in list(self._tasks):
            self.get(tid)

    def _run(self, task: Task, stored: list[StoredFile]) -> None:
        from .tools.registry import get_tool

        if task.cancelled:
            return
        task.status = "Processing"
        ctx = None
        try:
            inputs = [InputFile(s.id, s.name, s.path, s.password) for s in stored]
            ctx = TaskContext(task, inputs)
            get_tool(task.type).handler(ctx)
            ctx.check_cancelled()
            self._finish(task)
            task.status = "Completed"
        except TaskCancelled:
            task.status, task.failure_reason = "Failed", "Cancelled"
        except TaskError as e:
            task.status, task.failure_reason = "Failed", str(e)
        except FileNotFound:
            task.status, task.failure_reason = "Failed", "File not found. Please upload it again and retry."
        except Exception as e:  # unexpected: log, show a generic message
            log.error("task %s (%s) crashed: %s\n%s", task.id, task.type, e, traceback.format_exc())
            task.status = "Failed"
            task.failure_reason = _friendly_error(e)
        finally:
            task.finished = time.time()
            if ctx:
                shutil.rmtree(ctx.work_dir, ignore_errors=True)

    def _finish(self, task: Task) -> None:
        outputs = sorted(p for p in task.out_dir.iterdir() if p.is_file())
        if not outputs:
            raise TaskError("The task produced no output")
        task.result_items = [p.name for p in outputs]
        if len(outputs) == 1:
            task.result_filename = outputs[0].name
            return
        first = files.get(task.file_ids[0]).name if task.file_ids else "results"
        zip_name = f"{Path(first).stem or 'results'}.zip"
        with zipfile.ZipFile(task.out_dir / zip_name, "w", zipfile.ZIP_DEFLATED) as z:
            for p in outputs:
                z.write(p, p.name)
        task.result_filename = zip_name


def _friendly_error(e: Exception) -> str:
    text = str(e).lower()
    if "password" in text or "encrypt" in text:
        return "This PDF is password protected. Enter its password and try again."
    if "pdf" in text and ("damaged" in text or "parse" in text or "xref" in text or "trailer" in text):
        return "This file looks damaged. Try the Repair tool first."
    return "Something went wrong while processing your file. Please try again or try a different file."


queue = JobQueue(settings.workers)
