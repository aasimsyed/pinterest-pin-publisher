"""Resolve the Anthropic API key for local scripts.

Stored alongside the rest of this app's settings in one config file (see
app_config.py) instead of a separate ~/.config/anthropic/ folder.
"""

from __future__ import annotations

import os
import sys

from app_config import CONFIG_PATH, config_value, load_config, save_config
from masked_input import read_secret


def save_api_key(key: str) -> None:
    save_config({"anthropic_api_key": key})


def first_run_setup() -> str:
    print("No Anthropic API key found.")
    print(f"Let's set one up -- it'll be saved to {CONFIG_PATH} "
          f"(readable only by your user account) so you won't be asked again.\n")
    print("Get a key at: https://console.anthropic.com/settings/keys\n")

    while True:
        key = read_secret("Paste your Anthropic API key: ")
        if key:
            break
        print("That was empty -- try again.")

    save_api_key(key)
    print(f"Saved to {CONFIG_PATH}\n")
    return key


def load_api_key(cli_key: str | None) -> str:
    """Resolve the key from --api-key, ANTHROPIC_API_KEY, or the config file."""
    if cli_key:
        return cli_key

    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key

    saved = config_value(load_config(), "anthropic_api_key")
    if saved:
        return saved

    if sys.stdin.isatty():
        return first_run_setup()

    sys.exit(
        "No Anthropic API key found. Set the ANTHROPIC_API_KEY environment "
        f"variable, pass --api-key, or run: python scripts/setup.py"
    )
