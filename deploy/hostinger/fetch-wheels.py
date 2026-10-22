"""Download pinned CPython 3.12/Linux x64 wheels; verify official PyPI hashes.

Run on the build server. Optional HTTPS mirrors supply identical bytes, checked
against the committed manifest; the official URL is always a final fallback.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import hashlib
import json
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-prefix", action="append", default=[])
    args = parser.parse_args()
    for prefix in args.mirror_prefix:
        if urlsplit(prefix).scheme != "https":
            parser.error("Mirrors must use HTTPS")
    folder = Path(__file__).resolve().parent / "wheelhouse"
    manifest = json.loads((folder / "manifest.json").read_text())

    def valid(path, item):
        if not path.is_file() or path.stat().st_size != item["size"]:
            return False
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"]

    def fetch(item):
        name = item["filename"]
        if Path(name).name != name or not name.endswith(".whl"):
            raise ValueError("Unsafe manifest filename")
        original = urlsplit(item["url"])
        if original.scheme != "https" or original.hostname != "files.pythonhosted.org":
            raise ValueError("Manifest must reference official PyPI files")
        target = folder / name
        if valid(target, item):
            print("Verified cached", name, flush=True)
            return True
        temporary = target.with_suffix(".whl.part")
        urls = [prefix.rstrip("/") + original.path for prefix in args.mirror_prefix] + [item["url"]]
        for url in urls:
            result = subprocess.run([
                "curl", "--fail", "--location", "--silent", "--show-error",
                "--connect-timeout", "8", "--max-time", "45", "--retry", "1",
                "--output", str(temporary), url,
            ], capture_output=True)
            if result.returncode == 0 and valid(temporary, item):
                temporary.replace(target)
                print("Verified downloaded", name, flush=True)
                return True
            temporary.unlink(missing_ok=True)
        print("FAILED", name, flush=True)
        return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, manifest))
    print(f"{sum(results)}/{len(results)} pinned wheels verified", flush=True)
    return int(not all(results))


if __name__ == "__main__":
    raise SystemExit(main())
