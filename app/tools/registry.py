"""Tool registry: task type -> handler + the metadata the UI needs.

Each tool module calls `register(Tool(...))`. The tool page template renders
its option form from `options` (a list of Opt), so most tools need no custom
HTML. The `type` strings and option names follow research/SEJDA.md Part 1 §6.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..jobs import TaskError

CATEGORIES = [
    ("popular", "Popular"),
    ("organize", "Merge & organize"),
    ("edit", "Edit & sign"),
    ("optimize", "Optimize & repair"),
    ("from_pdf", "Convert from PDF"),
    ("to_pdf", "Convert to PDF"),
    ("pages", "Pages & layout"),
    ("security", "Security"),
    ("stamp", "Stamp & number"),
]

PDF = ["pdf"]
IMAGES = ["png", "gif", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"]


@dataclass
class Opt:
    name: str
    label: str
    kind: str = "text"  # radio | select | checkbox | text | number | range | textarea | color | pages | hidden
    choices: list[tuple[str, str]] = field(default_factory=list)
    default: object = ""
    help: str = ""
    advanced: bool = False  # shown under "More options"
    show_if: dict | None = None  # {"otherOption": "value"} or {"otherOption": ["a","b"]}
    min: float | None = None
    max: float | None = None
    step: float | None = None
    placeholder: str = ""


@dataclass
class Tool:
    type: str
    slug: str
    title: str
    tagline: str
    category: str
    handler: Callable
    icon: str = "file"
    accept: list[str] = field(default_factory=lambda: list(PDF))
    multiple: bool = True
    min_files: int = 1
    max_files: int = 50
    options: list[Opt] = field(default_factory=list)
    popular: bool = False
    page_ui: str | None = None  # "thumbs" for tools with a page picker
    template: str | None = None  # custom template instead of the generic tool page
    submit_label: str = ""
    keywords: str = ""
    requires: str | None = None  # name of an optional system dependency
    extra_categories: list[str] = field(default_factory=list)

    def validate(self, stored, params: dict) -> None:
        if len(stored) < self.min_files:
            raise TaskError(f"Please add at least {self.min_files} file{'s' if self.min_files > 1 else ''}")
        if len(stored) > self.max_files:
            raise TaskError(f"Too many files: at most {self.max_files}")
        for f in stored:
            ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
            if self.accept and ext not in self.accept and f.mime not in _mimes(self.accept):
                raise TaskError(f"'{f.name}' is not a supported file type for this tool")


def _mimes(exts: list[str]) -> set[str]:
    table = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
             "gif": "image/gif", "bmp": "image/bmp", "webp": "image/webp", "tif": "image/tiff", "tiff": "image/tiff"}
    return {table[e] for e in exts if e in table}


_TOOLS: dict[str, Tool] = {}
_BY_SLUG: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _TOOLS[tool.type] = tool
    _BY_SLUG[tool.slug] = tool
    return tool


def alias(task_type: str, target: str) -> None:
    """Accept another task type name for an existing handler (e.g. pdfToDoc)."""
    _TOOLS.setdefault(task_type, _TOOLS[target])


def get_tool(task_type: str) -> Tool:
    _load()
    return _TOOLS[task_type]


def by_slug(slug: str) -> Tool | None:
    _load()
    return _BY_SLUG.get(slug)


def all_tools() -> list[Tool]:
    _load()
    return list(_BY_SLUG.values())


_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    from . import organize, modify, stamp, security_tools, convert, editor  # noqa: F401
    _loaded = True
