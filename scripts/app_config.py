"""Local settings for a non-technical publish workflow.

Everything the app needs to remember on this computer lives in one file:
Anthropic key, website, image folder, Pinterest board. Cloudflare has no
entry here on purpose -- all Cloudflare access goes through `wrangler`,
which keeps its own login session, so there is nothing Cloudflare-related
for this app to store or lose track of.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "pinterest-pin-publisher" / "config.json"

KEYS = (
    "anthropic_api_key",
    "site_url",
    "images_dir",
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


def save_config(updates: dict, path: Path = CONFIG_PATH) -> None:
    """Merge `updates` into the existing config and save (only known KEYS)."""
    current = load_config(path)
    current.update({key: updates[key] for key in KEYS if updates.get(key)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def config_value(data: dict, key: str, fallback: str = "") -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback
