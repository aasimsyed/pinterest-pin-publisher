"""Resolve the Anthropic API key for local scripts."""

from __future__ import annotations

import getpass
import json
import os
import stat
import sys
from pathlib import Path

PRIMARY_CONFIG_PATH = Path.home() / ".config" / "anthropic" / "config.json"
CONFIG_PATHS = [
    PRIMARY_CONFIG_PATH,
    Path.home() / ".anthropic" / "config.json",
]


def save_api_key(key: str, config_path: Path = PRIMARY_CONFIG_PATH) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"api_key": key}, indent=2) + "\n")
    os.chmod(config_path, stat.S_IRUSR | stat.S_IWUSR)


def first_run_setup() -> str:
    print("No Anthropic API key found.")
    print(f"Let's set one up -- it'll be saved to {PRIMARY_CONFIG_PATH} "
          f"(readable only by your user account) so you won't be asked again.\n")
    print("Get a key at: https://console.anthropic.com/settings/keys\n")

    while True:
        key = getpass.getpass("Paste your Anthropic API key (input hidden): ").strip()
        if key:
            break
        print("That was empty -- try again.")

    save_api_key(key)
    print(f"Saved to {PRIMARY_CONFIG_PATH}\n")
    return key


def load_api_key(cli_key: str | None) -> str:
    """Resolve the key from --api-key, ANTHROPIC_API_KEY, or config.json."""
    if cli_key:
        return cli_key

    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key

    for config_path in CONFIG_PATHS:
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                continue
            key = data.get("api_key") or data.get("ANTHROPIC_API_KEY")
            if key:
                return key

    if sys.stdin.isatty():
        return first_run_setup()

    checked = "\n  ".join(str(p) for p in CONFIG_PATHS)
    sys.exit(
        "No Anthropic API key found. Set the ANTHROPIC_API_KEY environment "
        "variable, pass --api-key, or create one of these files:\n  "
        f"{checked}\ncontaining: {{\"api_key\": \"sk-ant-...\"}}"
    )
