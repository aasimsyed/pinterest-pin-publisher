"""Resolve the Google Gemini API key for local scripts.

Stored alongside the rest of this app's settings in one config file (see
app_config.py). Only needed if you turn on --ai-images.
"""

from __future__ import annotations

import os
import sys
import webbrowser

from app_config import CONFIG_PATH, config_value, load_config, save_config
from masked_input import read_secret

GEMINI_KEYS_URL = "https://aistudio.google.com/apikey"


def save_api_key(key: str) -> None:
    save_config({"gemini_api_key": key})


def first_run_setup() -> str:
    print("No Google Gemini API key found.")
    print(f"Let's set one up -- it'll be saved to {CONFIG_PATH} "
          f"(readable only by your user account) so you won't be asked again.\n")
    print(f"Opening {GEMINI_KEYS_URL} -- sign in with a Google account, "
          f"click Create API key, then copy it. You'll need billing enabled "
          f"on that Google account (image generation is a paid feature, "
          f"about $0.04 per pin).\n")
    webbrowser.open(GEMINI_KEYS_URL)

    while True:
        key = read_secret("Paste your Gemini API key: ")
        if key:
            break
        print("That was empty -- try again.")

    save_api_key(key)
    print(f"Saved to {CONFIG_PATH}\n")
    return key


def load_api_key(cli_key: str | None) -> str:
    """Resolve the key from --gemini-api-key, GEMINI_API_KEY, or the config file."""
    if cli_key:
        return cli_key

    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key:
        return env_key

    saved = config_value(load_config(), "gemini_api_key")
    if saved:
        return saved

    if sys.stdin.isatty():
        return first_run_setup()

    sys.exit(
        "No Gemini API key found. Set the GEMINI_API_KEY environment "
        "variable, pass --gemini-api-key, or run this again from a terminal "
        "so it can ask you for one."
    )
