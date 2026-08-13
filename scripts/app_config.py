"""Local settings for a non-technical publish workflow."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "pinterest-pin-publisher" / "config.json"

KEYS = (
    "site_url",
    "images_dir",
    "url_prefix",
    "board_name",
    "board_id",
    "pinterest_client_id",
)


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = {key: data[key] for key in KEYS if data.get(key)}
    path.write_text(json.dumps(cleaned, indent=2) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def config_value(data: dict, key: str, fallback: str = "") -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback
