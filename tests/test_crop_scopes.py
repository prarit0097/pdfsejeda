import io

import pikepdf
import pytest

from app.jobs import TaskError
from conftest import run_tool


def dimensions(data):
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return [(float(p.mediabox[2])-float(p.mediabox[0]), float(p.mediabox[3])-float(p.mediabox[1])) for p in pdf.pages]


def test_individual_crop_preserves_unmarked_pages(pdf3):
    task, out = run_tool("crop", [pdf3], cropMode="area", cropScope="individual",
                         cropAreas={"2": {"x": 10, "y": 20, "width": 200, "height": 300}})
    sizes = dimensions(out[task.result_filename])
    assert sizes[1] == (200, 300)
    assert sizes[0] == sizes[2] and sizes[0][0] > 500


def test_odd_even_crop_uses_distinct_regions(pdf3):
    task, out = run_tool("crop", [pdf3], cropMode="area", cropScope="odd-even", cropAreas={
        "odd": {"x": 10, "y": 20, "width": 200, "height": 300},
        "even": {"x": 30, "y": 40, "width": 350, "height": 400}})
    for actual, expected in zip(dimensions(out[task.result_filename]), [(200, 300), (350, 400), (200, 300)]):
        assert actual == pytest.approx(expected)


@pytest.mark.parametrize("area", [{}, {"x": 0, "y": 0, "width": float("nan"), "height": 20},
                                 {"x": 0, "y": 0, "width": -10, "height": 20}])
def test_invalid_crop_regions_fail_clearly(pdf3, area):
    with pytest.raises(TaskError):
        run_tool("crop", [pdf3], cropMode="area", cropScope="individual", cropAreas={"1": area})
