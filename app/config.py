"""Settings read from environment variables. See sejedarules.md §7."""
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path = Path(__file__).resolve().parent.parent / ".env") -> None:
    """Read KEY=VALUE lines from .env into the environment (real env vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if not os.environ.get("NO_DOTENV"):
    _load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    app_name: str = os.environ.get("APP_NAME", "PDFNova")
    data_dir: Path = Path(os.environ.get("DATA_DIR", "data")).resolve()
    file_ttl_seconds: int = _int("FILE_TTL_SECONDS", 7200)
    max_file_mb: int = _int("MAX_FILE_MB", 200)
    tasks_per_hour: int = _int("TASKS_PER_HOUR", 0)
    workers: int = _int("WORKERS", 4)
    secret_key: str = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    chunk_size_mb: int = 5
    allow_private_urls: bool = os.environ.get("ALLOW_PRIVATE_URLS") == "1"
    trust_proxy: bool = os.environ.get("TRUST_PROXY") == "1"  # read client IP from X-Forwarded-For / CF headers
    uploads_dir: Path = field(init=False)
    results_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.uploads_dir = self.data_dir / "uploads"
        self.results_dir = self.data_dir / "results"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


settings = Settings()
