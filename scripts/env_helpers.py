"""Shared helpers for reading/updating .env-style files and platform resolution. Uses python-dotenv."""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key as dotenv_set_key

# Workspace root (parent of scripts/).
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


def get_platform() -> str:
    """Resolve PLATFORM from environment; exit if missing or unsupported. Returns 'aws' or 'gcp'."""
    platform = (os.environ.get("PLATFORM") or "").strip().lower()
    if not platform:
        print("Error: Set PLATFORM=aws.", file=sys.stderr)
        sys.exit(1)
    if platform not in ("aws", "gcp"):
        print(f"Error: Unsupported PLATFORM={platform}. Use aws or gcp.", file=sys.stderr)
        sys.exit(1)
    return platform


def infra_env_path(platform: str) -> Path:
    """Path to the infra .env file for the given platform (e.g. packages/aws-infra/.env)."""
    return WORKSPACE_ROOT / "packages" / f"{platform}-infra" / ".env"


def load_env(path: str | Path) -> dict[str, str | None]:
    """Read a .env-style file into a dict. Exits if file is missing or empty. Uses python-dotenv dotenv_values."""
    path = Path(path)
    if not path.exists():
        print(f"Error: Env file not found: {path}", file=sys.stderr)
        sys.exit(1)
    data = dict(dotenv_values(path))
    if not data:
        print(f"Error: Env file is empty: {path}", file=sys.stderr)
        sys.exit(1)
    return data


def set_env_var(path: str | Path, key: str, value: str) -> None:
    """Ensure key=value exists in the file. Update if key exists, else append. Uses python-dotenv set_key (quote_mode=never)."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    dotenv_set_key(path, key, value, quote_mode="never")
