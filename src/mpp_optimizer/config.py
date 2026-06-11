from __future__ import annotations

import os
from pathlib import Path


def data_file(name: str) -> Path:
    """Locate a data file in dev checkouts (repo root) and pip-installed runs (CWD)."""
    override = os.getenv("MPP_DATA_DIR")
    candidates = [Path(override) / name] if override else []
    candidates += [
        Path(__file__).resolve().parents[2] / "data" / name,
        Path.cwd() / "data" / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"{name} not found. Looked at: "
        + ", ".join(str(candidate) for candidate in candidates)
        + ". Set MPP_DATA_DIR to the data directory."
    )


def load_dotenv(path: Path | None = None) -> None:
    """Load a small .env file without overriding existing environment values."""
    env_path = path or Path.cwd() / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("'\"")
        os.environ.setdefault(key.strip(), value)

