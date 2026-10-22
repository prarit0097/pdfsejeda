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


def test_task_capabilities_have_sufficient_entropy():
    from app.jobs import new_task_id
    ids = {new_task_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(len(value.split("-", 1)[0]) == 32 for value in ids)


def test_store_missing_data_and_corrupt_metadata_are_not_found():
    from app.storage import FileNotFound
    f = files.save_bytes("doc.pdf", b"example")
    f.path.unlink()
    with pytest.raises(FileNotFound):
        files.get(f.id)
    (f.path.parent / "meta.json").write_text("broken JSON", encoding="utf-8")
    with pytest.raises(FileNotFound):
        files.get(f.id)
    files.delete(f.id)


def test_expired_upload_cannot_be_revived(monkeypatch):
    from app.config import settings
    from app.storage import FileNotFound
    f = files.save_bytes("doc.pdf", b"example")
    monkeypatch.setattr(settings, "file_ttl_seconds", -1)
    with pytest.raises(FileNotFound):
        files.touch(f.id)
    assert not f.path.parent.exists()


def test_pinned_fetch_validates_redirects_and_size(monkeypatch):
    import io
    import socket
    import httpx
    from app.security import UnsafeUrl, fetch_url

    def resolve(host, port, **kwargs):
        ip = "127.0.0.1" if host == "private.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    requests = []
    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://private.example/secret"})
    with pytest.raises(UnsafeUrl, match="private"):
        fetch_url("https://public.example/doc", io.BytesIO(), 100, transport=httpx.MockTransport(redirect))
    assert len(requests) == 1
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "public.example"
    assert requests[0].extensions["sni_hostname"] == "public.example"
    with pytest.raises(UnsafeUrl, match="too large"):
        fetch_url("https://public.example/doc", io.BytesIO(), 2,
                  transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"123")))
    with pytest.raises(UnsafeUrl, match="credentials"):
        fetch_url("https://user:password@public.example/doc", io.BytesIO(), 100)


def test_queue_bounds_cancellation_and_timeouts(monkeypatch):
    import threading
    import time
    from app.config import settings
    from app.jobs import JobQueue, QueueFull
    from app.tools import registry

    entered, release = threading.Event(), threading.Event()
    def handler(ctx):
        entered.set()
        assert release.wait(5)
        ctx.output("result.pdf").write_bytes(b"output")
    tool = registry.Tool("bounded-test", "bounded-test", "Test", "Test", "popular", handler, min_files=0)
    registry._load()
    monkeypatch.setitem(registry._TOOLS, tool.type, tool)
    monkeypatch.setattr(settings, "max_queued_tasks", 1)
    monkeypatch.setattr(settings, "task_timeout_seconds", 60)
    q = JobQueue(1)
    try:
        first = q.submit(tool.type, [], {})
        assert entered.wait(2)
        waiting = q.submit(tool.type, [], {})
        with pytest.raises(QueueFull):
            q.submit(tool.type, [], {})
        assert q.cancel(waiting.id)
        assert waiting.status == "Failed"
        next_waiting = q.submit(tool.type, [], {})
        # Even a timed-out thread consumes its real worker/admission capacity.
        first.started = time.time() - 120
        q.check_timeouts()
        assert first.timed_out and first.status == "Failed"
        assert next_waiting.status == "Queued"
        with pytest.raises(QueueFull):
            q.submit(tool.type, [], {})
        next_waiting.created = time.time() - 120
        q.check_timeouts()
        assert next_waiting.timed_out
        replacement = q.submit(tool.type, [], {})
        assert replacement.status == "Queued"
        release.set()
    finally:
        release.set()
        q.shutdown(wait=True)
    assert not first.out_dir.exists()
    with pytest.raises(QueueFull):
        q.submit(tool.type, [], {})


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "100.64.0.1", "::1", "::ffff:127.0.0.1", "2002:7f00:1::"])
def test_ssrf_blocks_nonpublic_and_embedded_addresses(address):
    import ipaddress
    from app.security import ip_blocked
    assert ip_blocked(ipaddress.ip_address(address))


def test_mixing_rejects_oversized_source_list_before_storage_io(monkeypatch):
    from app.jobs import JobQueue, TaskError
    from app.storage import files
    from app.tools.registry import get_tool
    maximum = get_tool("alternateMix").max_files
    def must_not_touch(file_id):
        raise AssertionError("Oversized source lists must be rejected before disk IO")
    monkeypatch.setattr(files, "touch", must_not_touch)
    queue = JobQueue(1)
    try:
        with pytest.raises(TaskError, match="Too many files"):
            queue.submit("alternateMix", ["bogus-id"] * (maximum + 1), {})
    finally:
        queue.shutdown(wait=True)


def test_queue_releases_admission_when_file_lookup_fails(monkeypatch):
    from app.config import settings
    from app.jobs import JobQueue, QueueFull
    from app.storage import FileNotFound, files
    monkeypatch.setattr(settings, "max_queued_tasks", 0)
    touched = []
    def missing(file_id):
        touched.append(file_id)
        raise FileNotFound(file_id)
    monkeypatch.setattr(files, "touch", missing)
    queue = JobQueue(1)
    try:
        for _ in range(2):
            with pytest.raises(FileNotFound):
                queue.submit("extractPages", ["missing"], {})
        assert touched == ["missing", "missing"]
        # A genuinely full queue rejects admission before touching uploads.
        assert queue._admission.acquire(blocking=False)
        try:
            with pytest.raises(QueueFull):
                queue.submit("extractPages", ["not-read"], {})
            assert touched == ["missing", "missing"]
        finally:
            queue._admission.release()
    finally:
        queue.shutdown(wait=True)
