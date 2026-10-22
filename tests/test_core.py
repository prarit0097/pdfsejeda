import pytest

from app.pages import PageSelectionError, compress_ranges, parse_pages
from app.security import check_signature, sign_task
from app.storage import FILE_ID_RE, files, new_file_id


def test_parse_pages_forms():
    assert parse_pages("1-3,7", 10) == [1, 2, 3, 7]
    assert parse_pages("8-", 10) == [8, 9, 10]
    assert parse_pages("-2", 10) == [1, 2]
    assert parse_pages("odd", 5) == [1, 3, 5]
    assert parse_pages("even", 5) == [2, 4]
    assert parse_pages(5, 10) == [5]
    assert parse_pages("", 3) == [1, 2, 3]
    assert parse_pages("last", 4) == [4]
    with pytest.raises(PageSelectionError):
        parse_pages("abc", 3)
    with pytest.raises(PageSelectionError):
        parse_pages("20", 3)


def test_compress_ranges():
    assert compress_ranges([1, 2, 3, 7, 9, 10]) == "1-3,7,9-10"


def test_file_ids_and_store():
    fid = new_file_id()
    assert FILE_ID_RE.match(fid)
    f = files.save_bytes("../../evil name?.pdf", b"%PDF-1.4 test")
    assert "/" not in f.name and "?" not in f.name
    assert files.get(f.id).size == len(b"%PDF-1.4 test")
    files.delete(f.id)
    with pytest.raises(Exception):
        files.get(f.id)
    with pytest.raises(Exception):
        files.get("../../etc/passwd")


def test_signature():
    s = sign_task("ABC-1")
    assert s.startswith("web-") and len(s) == 39
    assert check_signature("ABC-1", s)
    assert not check_signature("ABC-2", s)
    assert not check_signature("ABC-1", None)
