"""Page-selection strings, as used by every tool (research/SEJDA.md Part 3 §4).

Accepted forms (1-based, comma separated, whitespace ignored):
  "5"  "1-3,7"  "10-" (to the end)  "-4" (first four)  "all"  "odd"  "even"  "last"
An int is accepted too (the browser may send pages:5 as a number).
"""
from __future__ import annotations


class PageSelectionError(ValueError):
    pass


def parse_pages(spec, total: int, default_all: bool = True) -> list[int]:
    """Return sorted, unique 1-based page numbers selected by `spec`."""
    if spec is None or (isinstance(spec, str) and not spec.strip()):
        if default_all:
            return list(range(1, total + 1))
        raise PageSelectionError("No pages selected")
    if isinstance(spec, bool):
        raise PageSelectionError(f"Invalid page selection: {spec}")
    if isinstance(spec, (int, float)):
        spec = str(int(spec))
    if isinstance(spec, (list, tuple)):
        spec = ",".join(str(s) for s in spec)
    selected: set[int] = set()
    for raw in str(spec).lower().split(","):
        part = raw.strip()
        if not part:
            continue
        if part == "all":
            selected.update(range(1, total + 1))
        elif part == "odd":
            selected.update(range(1, total + 1, 2))
        elif part == "even":
            selected.update(range(2, total + 1, 2))
        elif part == "last":
            selected.add(total)
        elif "-" in part:
            a, _, b = part.partition("-")
            start = _num(a) if a.strip() else 1
            end = _num(b) if b.strip() else total
            if start > end:
                start, end = end, start
            selected.update(range(max(start, 1), min(end, total) + 1))
        else:
            n = _num(part)
            if 1 <= n <= total:
                selected.add(n)
    if not selected:
        raise PageSelectionError(f"No valid pages in '{spec}' (document has {total} pages)")
    return sorted(selected)


def _num(s: str) -> int:
    s = s.strip()
    if s == "last":
        raise PageSelectionError("'last' is not allowed inside a range")
    try:
        return int(s)
    except ValueError:
        raise PageSelectionError(f"Invalid page number: '{s}'") from None


def compress_ranges(pages: list[int]) -> str:
    """[1,2,3,7,9,10] -> "1-3,7,9-10" (the browser uses the same encoding)."""
    out, pages = [], sorted(set(pages))
    i = 0
    while i < len(pages):
        j = i
        while j + 1 < len(pages) and pages[j + 1] == pages[j] + 1:
            j += 1
        out.append(str(pages[i]) if i == j else f"{pages[i]}-{pages[j]}")
        i = j + 1
    return ",".join(out)
