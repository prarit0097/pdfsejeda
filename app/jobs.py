"""Task model and in-process job queue.

A task = one POST /api/tasks. It moves Queued -> Processing -> Completed | Failed
(or is Cancelled). Handlers live in app/tools and write their outputs into
ctx.out_dir; when there is more than one output a zip of all of them is added
and becomes the main result (resultFilename), like Sejda.
"""
from __future__ import annotations

import gc
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
    rand = "".join(secrets.choice(_TASK_ALPHABET) for _ in range(32))
    return f"{rand}-{datetime.now(timezone.utc):%Y%m%d%H%M}"


class TaskError(Exception):
    """A failure whose message is safe to show to the user."""


class QueueFull(TaskError):
    """Admission rejected because all worker and waiting slots are occupied."""


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
    started: float | None = None
    cancelled: bool = False
    timed_out: bool = False

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
    """Runs tasks on worker threads, at most `workers` at a time.

    Timeouts are cooperative: a timed-out handler retains its worker until it exits.
    Admission includes both running and waiting work, so stuck handlers cannot create
    an unbounded executor queue. Task IDs are secret bearer capabilities (160 bits).
    """

    def __init__(self, workers: int):
        self.workers = max(1, workers)
        self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="task")
        self._admission = threading.BoundedSemaphore(self.workers + max(0, settings.max_queued_tasks))
        self._tasks: dict[str, Task] = {}
        self._futures = {}
        self._lock = threading.RLock()
        self._watchdog: threading.Thread | None = None
        self._stopped = threading.Event()

    def submit(self, task_type: str, file_ids: list[str], params: dict) -> Task:
        from .tools.registry import get_tool

        tool = get_tool(task_type)  # raises KeyError for unknown type
        # Reject oversized lists before metadata IO: the JSON body limit still
        # permits hundreds of thousands of IDs and touching each one is a write.
        if len(file_ids) > tool.max_files:
            raise TaskError(f"Too many files: at most {tool.max_files}")
        if self._stopped.is_set() or not self._admission.acquire(blocking=False):
            raise QueueFull("The server is busy. Please try again shortly.")
        try:
            stored = [files.touch(fid) for fid in file_ids]  # raises FileNotFound
            tool.validate(stored, params)
        except BaseException:
            self._admission.release()
            raise
        task = Task(new_task_id(), task_type, params, file_ids)
        with self._lock:
            while task.id in self._tasks:  # astronomically unlikely, but ids must be unique
                task.id = new_task_id()
            self._tasks[task.id] = task
        self._ensure_watchdog()
        try:
            future = self._pool.submit(self._run, task, stored)
        except RuntimeError:
            self._admission.release()
            with self._lock:
                self._tasks.pop(task.id, None)
            raise QueueFull("The server is shutting down. Please try again shortly.") from None
        with self._lock:
            self._futures[task.id] = future
        def done(_):
            self._admission.release()
            with self._lock:
                self._futures.pop(task.id, None)
        future.add_done_callback(done)
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
        with self._lock:
            if task.status in ("Queued", "Processing"):
                task.cancelled = True
                task.status = "Failed"
                task.failure_reason = "Cancelled"
                task.finished = time.time()
                future = self._futures.get(task_id)
                if future:
                    future.cancel()
        return True

    def delete(self, task_id: str) -> None:
        self.cancel(task_id)
        with self._lock:
            task = self._tasks.pop(task_id, None)
        if task:
            task.cancelled = True
            if task.status in ("Queued", "Processing"):
                task.status, task.failure_reason, task.finished = "Failed", "Cancelled", time.time()
            shutil.rmtree(task.out_dir, ignore_errors=True)
            shutil.rmtree(task.out_dir.parent / f"{task.id}.work", ignore_errors=True)

    def sweep(self) -> None:
        for tid in list(self._tasks):
            self.get(tid)

    def stats(self) -> dict:
        counts: dict[str, int] = {}
        for t in list(self._tasks.values()):
            counts[t.status] = counts.get(t.status, 0) + 1
        return counts

    # ---- timeouts ----------------------------------------------------------
    def _ensure_watchdog(self) -> None:
        if self._watchdog and self._watchdog.is_alive():
            return
        with self._lock:
            if self._watchdog and self._watchdog.is_alive():
                return
            self._watchdog = threading.Thread(target=self._watch, name="task-watchdog", daemon=True)
            self._watchdog.start()

    def _watch(self) -> None:
        while not self._stopped.wait(1 if settings.task_timeout_seconds > 5 else 0.2):
            try:
                self.check_timeouts()
            except Exception:  # never let the watchdog die
                log.exception("watchdog")

    def check_timeouts(self) -> None:
        limit = settings.task_timeout_seconds
        if limit <= 0:
            return
        now = time.time()
        with self._lock:
            for task in list(self._tasks.values()):
                queued_expired = task.status == "Queued" and now - task.created > min(limit, settings.file_ttl_seconds)
                if queued_expired or (task.status == "Processing" and task.started and now - task.started > limit):
                    log.warning("task %s (%s) timed out after %ss", task.id, task.type, limit)
                    task.timed_out = task.cancelled = True
                    task.status = "Failed"
                    task.failure_reason = "This task took too long and was stopped. Try a smaller file or fewer pages."
                    task.finished = now
                    future = self._futures.get(task.id)
                    if future:
                        future.cancel()

    def shutdown(self, wait: bool = False) -> None:
        """Stop admission, cancel queued jobs and ask active handlers to stop."""
        self._stopped.set()
        for tid in list(self._tasks):
            self.cancel(tid)
        self._pool.shutdown(wait=wait, cancel_futures=True)

    # ---- running -----------------------------------------------------------
    def _run(self, task: Task, stored: list[StoredFile]) -> None:
        from .tools.registry import get_tool

        if task.cancelled:
            return
        ctx = None
        try:
            with self._lock:
                if task.cancelled:
                    return
                task.status = "Processing"
                task.started = time.time()
            inputs = [InputFile(s.id, s.name, s.path, s.password) for s in stored]
            ctx = TaskContext(task, inputs)
            get_tool(task.type).handler(ctx)
            ctx.check_cancelled()
            self._finish(task)
            self._settle(task, "Completed")
        except TaskCancelled:
            self._settle(task, "Failed", "Cancelled")
        except TaskError as e:
            self._settle(task, "Failed", str(e))
        except FileNotFound:
            self._settle(task, "Failed", "File not found. Please upload it again and retry.")
        except Exception as e:  # unexpected (MemoryError included): log, show a generic message
            log.error("task %s (%s) crashed: %s\n%s", task.id, task.type, e, traceback.format_exc())
            self._settle(task, "Failed", _friendly_error(e))
        finally:
            if not task.finished:
                task.finished = time.time()
            # Handlers often leave pikepdf/pdfium documents for the garbage collector; collect now so
            # their file handles close (an open handle blocks deleting the upload on Windows and
            # leaks file descriptors elsewhere).
            ctx = _drop_ctx(ctx)
            # Collection can invoke native PDFium finalizers. Never collect on
            # another worker while a PDFium document is being used.
            from .tools.common import PDFIUM_LOCK
            with PDFIUM_LOCK:
                gc.collect()
            if task.status == "Failed" or task.id not in self._tasks:  # never retain partial failed results
                shutil.rmtree(task.out_dir, ignore_errors=True)

    def _settle(self, task: Task, status: str, reason: str | None = None) -> None:
        """Set the final status unless a timeout/cancel already decided it."""
        with self._lock:
            if task.timed_out or task.cancelled:
                return
            task.status = status
            if reason is not None:
                task.failure_reason = reason
            task.finished = time.time()

    def _finish(self, task: Task) -> None:
        outputs = sorted(p for p in task.out_dir.iterdir() if p.is_file())
        if not outputs:
            raise TaskError("The task produced no output")
        task.result_items = [p.name for p in outputs]
        if len(outputs) == 1:
            task.result_filename = outputs[0].name
            return
        try:
            first = files.get(task.file_ids[0]).name if task.file_ids else "results"
        except FileNotFound:
            first = "results"
        zip_name = f"{Path(first).stem or 'results'}.zip"
        if zip_name in task.result_items:
            zip_name = f"{Path(first).stem or 'results'}-all.zip"
        with zipfile.ZipFile(task.out_dir / zip_name, "w", zipfile.ZIP_DEFLATED) as z:
            for p in outputs:
                z.write(p, p.name)
        task.result_filename = zip_name


def _drop_ctx(ctx: "TaskContext | None") -> None:
    if ctx:
        shutil.rmtree(ctx.work_dir, ignore_errors=True)
        ctx.inputs = []
        ctx.params = {}
    return None


def _friendly_error(e: Exception) -> str:
    text = str(e).lower()
    if "password" in text or "encrypt" in text:
        return "This PDF is password protected. Enter its password and try again."
    if "pdf" in text and ("damaged" in text or "parse" in text or "xref" in text or "trailer" in text):
        return "This file looks damaged. Try the Repair tool first."
    return "Something went wrong while processing your file. Please try again or try a different file."


queue = JobQueue(settings.workers)
