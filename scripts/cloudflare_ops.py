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
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from app_config import config_value, load_config

ROOT = Path(__file__).resolve().parent.parent
DATABASE_NAME = "pin-publisher-db"
BUCKET_NAME = "pin-publisher-images"
R2_DEV_URL_RE = re.compile(r"https://[\w.-]+\.r2\.dev")
D1_UUID_RE = re.compile(r'database_id\s*=\s*"([0-9a-f-]+)"')
WORKER_URL_RE = re.compile(r"https://[\w.-]+\.workers\.dev")


class WranglerError(RuntimeError):
    """Raised when a wrangler command fails, with a message meant for a
    non-technical user rather than a raw stack trace."""


class PublishTriggerError(RuntimeError):
    """Raised when calling the deployed Worker's /run endpoint fails."""


def _wrangler_env() -> dict:
    """Inherit the shell's environment, adding the saved Cloudflare
    account id (if any) so wrangler doesn't have to ask which account to
    use when the login has more than one."""
    env = os.environ.copy()
    account_id = config_value(load_config(), "account_id")
    if account_id:
        env["CLOUDFLARE_ACCOUNT_ID"] = account_id
    return env


_AUTH_ERROR_MARKERS = (
    "not authorized",
    "not authenticated",
    "please run `wrangler login`",
    "please run \"wrangler login\"",
)


def _looks_like_auth_error(output: str) -> bool:
    lowered = output.lower()
    return any(marker in lowered for marker in _AUTH_ERROR_MARKERS)


def _invoke_wrangler(args: list[str], input_text: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["npx", "wrangler", *args],
        cwd=ROOT,
        input=input_text,
        capture_output=True,
        text=True,
        env=_wrangler_env(),
    )


def run_wrangler(
    args: list[str], input_text: str = "", check: bool = True, _allow_relogin: bool = True,
) -> subprocess.CompletedProcess:
    result = _invoke_wrangler(args, input_text)
    if (
        result.returncode != 0
        and _allow_relogin
        and args[:1] != ["login"]
        and _looks_like_auth_error(f"{result.stdout}\n{result.stderr}")
    ):
        print("Your Cloudflare login expired or switched accounts -- reopening the login page...")
        run_wrangler(["login"], check=False, _allow_relogin=False)
        result = _invoke_wrangler(args, input_text)
    if check and result.returncode != 0:
        raise WranglerError((result.stderr or result.stdout or "unknown error").strip())
    return result


def ensure_login() -> None:
    status = run_wrangler(["whoami"], check=False)
    if "You are logged in" in status.stdout:
        return
    print("Opening your browser to log into Cloudflare...")
    run_wrangler(["login"])


ACCOUNT_ROW_RE = re.compile(r"│\s*(.+?)\s*│\s*([0-9a-f]{32})\s*│")


def list_accounts() -> list[dict]:
    """Every Cloudflare account visible to this login, parsed from
    `wrangler whoami`'s account table. One row unless the login has
    access to more than one account."""
    result = run_wrangler(["whoami"], check=False)
    return [{"name": name, "id": account_id} for name, account_id in ACCOUNT_ROW_RE.findall(result.stdout)]


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


def deploy_worker() -> str | None:
    """Deploy the Worker and return its workers.dev URL, so scripts can
    call its /run endpoint later without the user having to look it up
    on the Cloudflare dashboard. Returns None if the URL couldn't be
    found in wrangler's output (for example, a workers.dev subdomain
    that isn't registered yet)."""
    result = run_wrangler(["deploy"])
    match = WORKER_URL_RE.search(result.stdout)
    return match.group(0) if match else None


def worker_url_from_wrangler() -> str | None:
    """Read the live workers.dev URL without a full redeploy, so --run-now
    still works on a machine whose local config predates that field."""
    listed = run_wrangler(["deployments", "list"], check=False)
    match = WORKER_URL_RE.search(listed.stdout)
    return match.group(0) if match else None


def trigger_publish(
    worker_url: str, secret: str, limit: int, force: bool = True, random_order: bool = False,
) -> dict:
    """Call the deployed Worker's /run endpoint directly, so pins can be
    posted right now instead of waiting for the next cron tick.
    random_order picks which pending pins to post randomly instead of
    earliest-scheduled-first."""
    query = (
        f"?force={'true' if force else 'false'}&limit={limit}"
        f"&random={'true' if random_order else 'false'}"
    )
    request = urllib.request.Request(
        worker_url.rstrip("/") + "/run" + query,
        headers={
            "Authorization": f"Bearer {secret}",
            "User-Agent": "pinterest-pin-publisher/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise PublishTriggerError(f"Worker returned {e.code}: {body[:300]}") from e
    except urllib.error.URLError as e:
        raise PublishTriggerError(f"Could not reach the Worker at {worker_url}: {e.reason}") from e


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
            webbrowser.open("https://dash.cloudflare.com/?to=/:account/r2/overview")
            raise WranglerError(
                "R2 storage isn't turned on for this Cloudflare account yet. "
                "Opened the R2 page for you -- click Enable (free tier is "
                "fine), then run this again."
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


def _object_key(media_url: str) -> str:
    """R2 object key is the filename we uploaded (last path segment)."""
    raw = (media_url or "").strip()
    if not raw:
        return ""
    return urllib.parse.unquote(raw.rstrip("/").rsplit("/", 1)[-1])


def prune_published_images() -> dict:
    """Delete R2 objects that belong only to published pins.

    A file still referenced by a pending or failed pin is left alone, so
    a retry or a later --run-now still has a working image URL."""
    result = run_wrangler([
        "d1", "execute", DATABASE_NAME, "--remote", "--command",
        "SELECT status, media_url FROM pin_queue;", "--json",
    ])
    payload = json.loads(result.stdout or "[]")
    rows = payload[0].get("results", []) if payload else []

    published: set[str] = set()
    in_use: set[str] = set()
    for row in rows:
        key = _object_key(row.get("media_url") or "")
        if not key:
            continue
        if row.get("status") == "published":
            published.add(key)
        else:
            in_use.add(key)

    skipped = sorted(published & in_use)
    to_delete = sorted(published - in_use)
    deleted = []
    for key in to_delete:
        deleted_obj = run_wrangler(
            ["r2", "object", "delete", f"{BUCKET_NAME}/{key}", "--remote", "-y"],
            check=False,
        )
        combined = f"{deleted_obj.stdout}\n{deleted_obj.stderr}".lower()
        if deleted_obj.returncode == 0 or "not found" in combined:
            deleted.append(key)
        else:
            raise WranglerError((deleted_obj.stderr or deleted_obj.stdout or "unknown error").strip())
    return {"deleted": deleted, "skipped": skipped}


def _sql_quote(value) -> str:
    if value is None or value == "":
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def existing_titles() -> set[str]:
    """Return every title already in the queue (any status), so a new
    batch never gives a pin the same title as one already queued or
    published -- Pinterest's bulk CSV upload rejects exact duplicates,
    and repeated titles hurt search ranking anyway."""
    result = run_wrangler([
        "d1", "execute", DATABASE_NAME, "--remote", "--command",
        "SELECT title FROM pin_queue;", "--json",
    ])
    payload = json.loads(result.stdout or "[]")
    if not payload:
        return set()
    rows = payload[0].get("results", [])
    return {row["title"].strip().lower() for row in rows if row.get("title")}


def existing_media_filenames() -> set[str]:
    """Return the filename of every image already queued or published (any
    status), so re-running on a folder that still has old pictures in it
    skips re-uploading and re-analyzing ones already sent through."""
    result = run_wrangler([
        "d1", "execute", DATABASE_NAME, "--remote", "--command",
        "SELECT media_url FROM pin_queue;", "--json",
    ])
    payload = json.loads(result.stdout or "[]")
    if not payload:
        return set()
    rows = payload[0].get("results", [])
    return {key for row in rows if (key := _object_key(row.get("media_url") or ""))}


def list_queue(status: str = "pending") -> list[dict]:
    """Return queued pins ordered by when they'll post, for showing what's
    scheduled. Pass status="" for every row regardless of status."""
    where = f" WHERE status = {_sql_quote(status)}" if status else ""
    result = run_wrangler([
        "d1", "execute", DATABASE_NAME, "--remote", "--command",
        f"SELECT id, title, status, publish_at, pinterest_pin_url, link "
        f"FROM pin_queue{where} ORDER BY publish_at ASC;", "--json",
    ])
    payload = json.loads(result.stdout or "[]")
    return payload[0].get("results", []) if payload else []


def dedupe_queue(pending_only: bool = True) -> list[dict]:
    """Remove duplicate-titled rows already sitting in pin_queue, keeping
    the oldest row for each title and deleting the more recent ones.
    Only pending rows are touched by default, since published/failed
    rows are history rather than upcoming work."""
    where = " WHERE status = 'pending'" if pending_only else ""
    result = run_wrangler([
        "d1", "execute", DATABASE_NAME, "--remote", "--command",
        f"SELECT id, title, status FROM pin_queue{where} ORDER BY id ASC;", "--json",
    ])
    payload = json.loads(result.stdout or "[]")
    rows = payload[0].get("results", []) if payload else []

    seen: set[str] = set()
    to_remove: list[dict] = []
    for row in rows:
        key = row["title"].strip().lower()
        if key in seen:
            to_remove.append(row)
        else:
            seen.add(key)

    if to_remove:
        ids = ", ".join(str(row["id"]) for row in to_remove)
        run_wrangler([
            "d1", "execute", DATABASE_NAME, "--remote", "--command",
            f"DELETE FROM pin_queue WHERE id IN ({ids});",
        ])
    return to_remove


def reset_queue() -> dict:
    """Wipe the queue for a fresh start: pending/failed rows are deleted
    outright, and published rows are reset back to pending (clearing
    their old Pinterest pin id and timestamps) so they'll be posted
    again -- useful after switching a board between sandbox and
    production, where old "published" pins were never actually public."""
    result = run_wrangler([
        "d1", "execute", DATABASE_NAME, "--remote", "--command",
        "SELECT id, status FROM pin_queue;", "--json",
    ])
    payload = json.loads(result.stdout or "[]")
    rows = payload[0].get("results", []) if payload else []

    cleared_ids = [row["id"] for row in rows if row["status"] in ("pending", "failed")]
    reset_ids = [row["id"] for row in rows if row["status"] == "published"]

    if cleared_ids:
        ids = ", ".join(str(i) for i in cleared_ids)
        run_wrangler([
            "d1", "execute", DATABASE_NAME, "--remote", "--command",
            f"DELETE FROM pin_queue WHERE id IN ({ids});",
        ])
    if reset_ids:
        ids = ", ".join(str(i) for i in reset_ids)
        run_wrangler([
            "d1", "execute", DATABASE_NAME, "--remote", "--command",
            "UPDATE pin_queue SET status = 'pending', pinterest_pin_id = NULL, "
            "pinterest_pin_url = NULL, "
            f"published_at = NULL, error_message = NULL WHERE id IN ({ids});",
        ])
    return {"cleared": len(cleared_ids), "reset": len(reset_ids)}


def clear_queue() -> int:
    """Delete every row in pin_queue, any status. This is a full wipe,
    unlike reset_queue which keeps published rows and puts them back
    to pending."""
    counted = run_wrangler([
        "d1", "execute", DATABASE_NAME, "--remote", "--command",
        "SELECT COUNT(*) AS n FROM pin_queue;", "--json",
    ])
    payload = json.loads(counted.stdout or "[]")
    rows = payload[0].get("results", []) if payload else []
    n = int(rows[0]["n"]) if rows else 0
    if n:
        run_wrangler([
            "d1", "execute", DATABASE_NAME, "--remote", "--command",
            "DELETE FROM pin_queue;",
        ])
    return n


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
