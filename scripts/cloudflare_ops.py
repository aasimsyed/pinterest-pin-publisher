"""All Cloudflare access for this app goes through `wrangler`.

There is deliberately no separate Cloudflare API token or account-id/config
file: `wrangler login` already grants everything this app needs (D1, R2,
Workers), so reusing that one login avoids asking a non-technical user to
create and paste a second Cloudflare credential.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATABASE_NAME = "pin-publisher-db"
BUCKET_NAME = "pin-publisher-images"
R2_DEV_URL_RE = re.compile(r"https://[\w.-]+\.r2\.dev")
D1_UUID_RE = re.compile(r'database_id\s*=\s*"([0-9a-f-]+)"')


class WranglerError(RuntimeError):
    """Raised when a wrangler command fails, with a message meant for a
    non-technical user rather than a raw stack trace."""


def run_wrangler(args: list[str], input_text: str = "", check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["npx", "wrangler", *args],
        cwd=ROOT,
        input=input_text,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise WranglerError((result.stderr or result.stdout or "unknown error").strip())
    return result


def ensure_login() -> None:
    status = run_wrangler(["whoami"], check=False)
    if "You are logged in" in status.stdout:
        return
    print("Opening your browser to log into Cloudflare...")
    run_wrangler(["login"])


def ensure_d1_database() -> str:
    """Return the database's UUID, creating it if it doesn't exist yet."""
    listed = run_wrangler(["d1", "list", "--json"])
    for db in json.loads(listed.stdout or "[]"):
        if db.get("name") == DATABASE_NAME:
            return db["uuid"]

    print(f"Creating Cloudflare D1 database '{DATABASE_NAME}'...")
    created = run_wrangler(["d1", "create", DATABASE_NAME])
    match = D1_UUID_RE.search(created.stdout)
    if not match:
        raise WranglerError(f"Database was created but its ID could not be read from:\n{created.stdout}")
    return match.group(1)


def apply_migrations() -> None:
    run_wrangler(["d1", "migrations", "apply", DATABASE_NAME, "--remote"])


def write_database_id(database_id: str) -> None:
    """Keep wrangler.toml's database_id in sync with the real database."""
    toml_path = ROOT / "wrangler.toml"
    text = toml_path.read_text()
    updated = re.sub(r'database_id\s*=\s*"[0-9a-f-]+"', f'database_id = "{database_id}"', text)
    if updated != text:
        toml_path.write_text(updated)


def write_pinterest_vars(sandbox: bool, board_id: str = "") -> None:
    """Keep wrangler.toml's [vars] in sync with the chosen Pinterest
    environment. Trial apps can only create pins in Pinterest's sandbox
    (api-sandbox.pinterest.com), so the Worker needs to know which base URL
    and board to use."""
    toml_path = ROOT / "wrangler.toml"
    text = toml_path.read_text()
    text = re.sub(r'PINTEREST_SANDBOX\s*=\s*"[^"]*"',
                  f'PINTEREST_SANDBOX = "{"true" if sandbox else "false"}"', text)
    text = re.sub(r'PINTEREST_BOARD_ID\s*=\s*"[^"]*"',
                  f'PINTEREST_BOARD_ID = "{board_id if sandbox else ""}"', text)
    toml_path.write_text(text)


def reset_after_reauth() -> None:
    """Drop the cached access token and give failed pins another chance,
    since a new refresh token or a switch between sandbox/production makes
    both stale."""
    run_wrangler([
        "d1", "execute", DATABASE_NAME, "--remote", "--command",
        "DELETE FROM oauth_tokens; "
        "UPDATE pin_queue SET status = 'pending', error_message = NULL WHERE status = 'failed';",
    ])


def deploy_worker() -> None:
    run_wrangler(["deploy"])


def set_worker_secrets(secrets: dict[str, str]) -> None:
    """Set every Worker secret in one non-interactive call."""
    run_wrangler(["secret", "bulk"], input_text=json.dumps(secrets))


def _r2_enabled_error(message: str) -> bool:
    return "enable r2" in message.lower()


def ensure_image_bucket() -> str:
    """Create the R2 bucket (if needed), make it publicly readable, and
    return its public base URL."""
    created = run_wrangler(["r2", "bucket", "create", BUCKET_NAME], check=False)
    combined = f"{created.stdout}\n{created.stderr}"
    if created.returncode != 0 and "already exists" not in combined.lower():
        if _r2_enabled_error(combined):
            raise WranglerError(
                "R2 storage isn't turned on for this Cloudflare account yet. "
                "Open https://dash.cloudflare.com/ -> R2 and click Enable "
                "(free tier is fine), then run this again."
            )
        raise WranglerError(combined.strip())

    got = run_wrangler(["r2", "bucket", "dev-url", "get", BUCKET_NAME], check=False)
    match = R2_DEV_URL_RE.search(got.stdout)
    if match:
        return match.group(0)

    enabled = run_wrangler(["r2", "bucket", "dev-url", "enable", BUCKET_NAME, "-y"])
    match = R2_DEV_URL_RE.search(enabled.stdout)
    if not match:
        raise WranglerError(
            f"Created the R2 bucket but couldn't read its public URL. Check "
            f"https://dash.cloudflare.com/ -> R2 -> {BUCKET_NAME} -> Settings."
        )
    return match.group(0)


def upload_image(path: Path, public_base_url: str) -> str:
    """Upload one image to the R2 bucket and return its public URL."""
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    run_wrangler([
        "r2", "object", "put", f"{BUCKET_NAME}/{path.name}",
        "--file", str(path),
        "--content-type", content_type,
        "--remote",
        "-y",
    ])
    return f"{public_base_url.rstrip('/')}/{path.name}"


def _sql_quote(value) -> str:
    if value is None or value == "":
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def insert_pin_rows(rows: list[dict]) -> None:
    """Insert every row in a single wrangler call instead of one per row."""
    statements = []
    for row in rows:
        values = ", ".join(_sql_quote(v) for v in (
            row["title"], row["media_url"], row["board_id"],
            row["description"], row["link"], row["publish_at"], row["keywords"],
        ))
        statements.append(
            "INSERT INTO pin_queue (title, media_url, board_id, description, "
            f"link, publish_at, keywords) VALUES ({values});"
        )

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
        f.write("\n".join(statements))
        temp_path = f.name
    try:
        run_wrangler(["d1", "execute", DATABASE_NAME, "--remote", "--file", temp_path, "-y"])
    finally:
        os.unlink(temp_path)
