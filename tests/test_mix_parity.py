"""Alternate mix per-source arrays and page conservation regressions."""
import io

import pypdf
import pytest

from app.jobs import TaskCancelled, TaskError
from conftest import make_pdf, run_tool, store


def source(letter, count):
    return store(make_pdf(count, texts=[f"{letter}{i + 1}" for i in range(count)]), f"{letter}.pdf")


def pages(outputs):
    reader = pypdf.PdfReader(io.BytesIO(next(iter(outputs.values()))))
    return [page.extract_text().splitlines()[0] for page in reader.pages]


def test_three_sources_use_independent_steps_and_directions():
    a, b, c = source("A", 5), source("B", 3), source("C", 4)
    _, outputs = run_tool("alternateMix", [a, b, c], step=[2, 1, 3], reverse=[True, False, True])
    assert pages(outputs) == ["A5", "A4", "B1", "C4", "C3", "C2", "A3", "A2", "B2", "C1", "A1", "B3"]


def test_exact_sejda_array_aliases_and_short_arrays_default_per_source():
    a, b, c = source("A", 3), source("B", 2), source("C", 2)
    _, outputs = run_tool("alternateMix", [a, b, c], **{"step[]": [2], "reverse[]": ["true", "false", "on"]})
    assert pages(outputs) == ["A3", "A2", "B1", "C2", "A1", "B2", "C1"]


def test_unequal_sources_exhaust_then_keep_remaining_pages():
    a, b, c = source("A", 1), source("B", 5), source("C", 2)
    _, outputs = run_tool("alternateMix", [a, b, c], step=[10, 2, 1])
    assert pages(outputs) == ["A1", "B1", "B2", "C1", "B3", "B4", "C2", "B5"]


def test_legacy_scalar_step_and_reverse_keep_existing_behavior():
    a, b, c = source("A", 3), source("B", 3), source("C", 3)
    _, outputs = run_tool("alternateMix", [a, b, c], step="2", reverse=True)
    assert pages(outputs) == ["A1", "A2", "B3", "B2", "C3", "C2", "A3", "B1", "C1"]


@pytest.mark.parametrize("bad", [0, -1, "bad", 1.5, "2.5", float("inf"), float("nan"), True, {}, None])
def test_invalid_steps_reject_instead_of_hanging_or_silently_changing_order(bad):
    a, b = source("A", 1), source("B", 1)
    with pytest.raises(TaskError, match="positive integer"):
        run_tool("alternateMix", [a, b], step=[1, bad])


def test_list_lengths_are_validated():
    a, b = source("A", 1), source("B", 1)
    with pytest.raises(TaskError, match="step"):
        run_tool("alternateMix", [a, b], step=[1, 1, 1])
    with pytest.raises(TaskError, match="reverse"):
        run_tool("alternateMix", [a, b], reverse=[False, False, True])


def test_mixing_checks_cancellation_and_closes_inputs(monkeypatch):
    from app.jobs import TaskContext
    from app.tools import organize
    a, b = source("A", 2), source("B", 2)
    from contextlib import contextmanager
    opened, closed = [], []
    original = organize._open_any
    @contextmanager
    def track(inp):
        with original(inp) as pdf:
            opened.append(inp.id)
            try:
                yield pdf
            finally:
                closed.append(inp.id)
    def cancelled(self):
        raise TaskCancelled()
    monkeypatch.setattr(organize, "_open_any", track)
    monkeypatch.setattr(TaskContext, "check_cancelled", cancelled)
    with pytest.raises(TaskCancelled):
        run_tool("alternateMix", [a, b])
    assert len(opened) == 2
    assert set(closed) == set(opened)


def test_source_rotations_follow_pages_through_mix_order():
    a, b, c = source("A", 2), source("B", 1), source("C", 2)
    _, outputs = run_tool("alternateMix", [a, b, c], step=[1, 1, 2], reverse=[True, False, False], rotations=[90, 180, -90])
    reader = pypdf.PdfReader(io.BytesIO(next(iter(outputs.values()))))
    assert [page.extract_text().splitlines()[0] for page in reader.pages] == ["A2", "B1", "C1", "C2", "A1"]
    assert [page.get("/Rotate", 0) for page in reader.pages] == [90, 180, 270, 270, 90]


@pytest.mark.parametrize("bad", [45, 90.5, "bad", float("nan"), float("inf")])
def test_mix_rotation_requires_finite_quarter_turns(bad):
    a, b = source("A", 1), source("B", 1)
    with pytest.raises(TaskError, match="multiple of 90"):
        run_tool("alternateMix", [a, b], rotations=[0, bad])
