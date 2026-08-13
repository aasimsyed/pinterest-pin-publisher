"""
PIN PUBLISHER — publish Pinterest pins from a CSV schedule.

A standalone tool. Not connected to any other app. Everything it needs is
in this one file (plus the requests and pillow libraries).

WHAT IT DOES
  You (or a VA) put pin images in a folder and fill a spreadsheet
  (pins.csv) with one row per pin: image filename, title, description,
  link, board, an optional publish date/time, tags, and alt text.
  Running this posts every pin that's due, marks it as posted in the CSV
  so nothing ever posts twice, and reports what's still waiting and what
  needs fixing. Run it daily and it acts like a pin scheduler.

WHERE THINGS LIVE
  Documents/PinPublisher/pins.csv     the schedule (edit in Excel)
  Documents/PinPublisher/images/      the pin images
  The first run creates both, with an example row.

SETUP (once)
  Needs a free Pinterest developer app (developers.pinterest.com) on your
  business account, with redirect address  http://localhost:8085/  added
  in the app's settings. The first run asks for the app's ID and secret,
  then opens your browser once so you can click "Allow" on Pinterest.
  NOTE: while the Pinterest app has Trial access, pins are sandbox-only
  (visible to you, not the public) until Pinterest grants Standard access.
"""

import base64
import csv
import json
import os
import secrets as pysecrets
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from PIL import Image

APP_NAME = "PinPublisher"
API = "https://api.pinterest.com/v5"
AUTH_URL = "https://www.pinterest.com/oauth/"
TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
REDIRECT_URI = "http://localhost:8085/"
SCOPES = "boards:read,boards:write,pins:read,pins:write"

COLUMNS = ["image", "title", "description", "link", "board",
           "publish_date", "tags", "alt_text", "posted"]

TEMPLATE_ROW = {
    "image": "1.png",
    "title": "Rain Cloud Handprint Craft for Spring",
    "description": "An easy printable spring keepsake kids can make with two painted handprints.",
    "link": "https://yourblog.com/spring-crafts-for-kids/",
    "board": "Spring Crafts for Kids",
    "publish_date": "2026-07-20 09:00",
    "tags": "spring crafts, kids crafts, printables",
    "alt_text": "Printable handprint craft showing a rain cloud and pink flower",
    "posted": "",
}

DATE_FORMATS = [
    "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y",
    "%m/%d/%y %H:%M", "%m/%d/%y %I:%M %p", "%m/%d/%y",
]


# ---------------------------------------------------------------- storage

def config_dir():
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_config():
    p = config_dir() / "config.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg):
    (config_dir() / "config.json").write_text(
        json.dumps(cfg, indent=2), encoding="utf-8")


def work_dir():
    docs = Path.home() / "Documents"
    base = docs if docs.exists() else Path.home()
    d = base / APP_NAME
    (d / "images").mkdir(parents=True, exist_ok=True)
    return d


def csv_path():
    return work_dir() / "pins.csv"


# ---------------------------------------------------------------- pinterest

class PinterestError(Exception):
    """Plain-English Pinterest problem."""


class _CodeCatcher(BaseHTTPRequestHandler):
    code = None
    state = None

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        _CodeCatcher.code = (qs.get("code") or [None])[0]
        _CodeCatcher.state = (qs.get("state") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Connected! You can close this tab and go back "
                         b"to the app window.</h2>")

    def log_message(self, *args):
        pass


class Pinterest:
    def __init__(self, app_id, app_secret):
        self.app_id = app_id.strip()
        self.app_secret = app_secret.strip()
        self.token_path = config_dir() / "pinterest_token.json"
        self.token = (json.loads(self.token_path.read_text())
                      if self.token_path.exists() else None)

    def _basic_auth(self):
        raw = f"{self.app_id}:{self.app_secret}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}

    def connect(self, log=print):
        state = pysecrets.token_urlsafe(16)
        url = AUTH_URL + "?" + urlencode({
            "client_id": self.app_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
        })
        server = HTTPServer(("localhost", 8085), _CodeCatcher)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        log("Opening Pinterest in your browser — click 'Allow'…")
        webbrowser.open(url)
        thread.join(timeout=180)
        server.server_close()
        if not _CodeCatcher.code:
            raise PinterestError("Didn't receive Pinterest's approval within "
                                 "3 minutes. Run this again and click Allow.")
        if _CodeCatcher.state != state:
            raise PinterestError("Security check failed (state mismatch). "
                                 "Run this again.")
        r = requests.post(TOKEN_URL, headers=self._basic_auth(), data={
            "grant_type": "authorization_code",
            "code": _CodeCatcher.code,
            "redirect_uri": REDIRECT_URI,
        }, timeout=30)
        if r.status_code >= 400:
            raise PinterestError(f"Pinterest rejected the connection "
                                 f"({r.status_code}: {r.text[:120]})")
        self._save_token(r.json())
        log("Connected to Pinterest.")

    def _save_token(self, tok):
        self.token = tok
        self.token_path.write_text(json.dumps(tok, indent=2))

    def _refresh(self):
        if not self.token or not self.token.get("refresh_token"):
            raise PinterestError("Not connected to Pinterest yet.")
        r = requests.post(TOKEN_URL, headers=self._basic_auth(), data={
            "grant_type": "refresh_token",
            "refresh_token": self.token["refresh_token"],
        }, timeout=30)
        if r.status_code >= 400:
            raise PinterestError("Pinterest session expired — reconnect by "
                                 "running this again.")
        fresh = r.json()
        fresh.setdefault("refresh_token", self.token["refresh_token"])
        self._save_token(fresh)

    def _request(self, method, path, retry=True, **kwargs):
        if not self.token:
            raise PinterestError("Not connected to Pinterest yet.")
        headers = {"Authorization": f"Bearer {self.token['access_token']}"}
        r = requests.request(method, f"{API}{path}", headers=headers,
                             timeout=60, **kwargs)
        if r.status_code == 401 and retry:
            self._refresh()
            return self._request(method, path, retry=False, **kwargs)
        if r.status_code == 429:
            raise PinterestError("Pinterest rate limit reached — wait a while "
                                 "and run this again (Trial access is limited).")
        if r.status_code >= 400:
            raise PinterestError(f"Pinterest error {r.status_code}: "
                                 f"{r.text[:150]}")
        return r.json() if r.text else {}

    def boards(self):
        return self._request("GET", "/boards",
                             params={"page_size": 100}).get("items", [])

    def create_board(self, name, description=""):
        return self._request("POST", "/boards",
                             json={"name": name, "description": description})

    def create_pin(self, board_id, image_path, title, description,
                   link, alt_text):
        img_b64 = base64.standard_b64encode(
            Path(image_path).read_bytes()).decode()
        payload = {
            "board_id": board_id,
            "title": (title or "")[:100],
            "description": (description or "")[:500],
            "alt_text": (alt_text or "")[:500],
            "link": link,
            "media_source": {
                "source_type": "image_base64",
                "content_type": "image/jpeg",
                "data": img_b64,
            },
        }
        return self._request("POST", "/pins", json=payload)


# ---------------------------------------------------------------- csv logic

def create_template():
    with open(csv_path(), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerow(TEMPLATE_ROW)


def parse_when(text):
    text = (text or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{text}' — use YYYY-MM-DD HH:MM "
                     f"like 2026-07-20 09:00")


def load_rows():
    with open(csv_path(), newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for c in COLUMNS:
            r.setdefault(c, "")
    return rows


def save_rows(rows):
    with open(csv_path(), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def as_jpeg(image_path):
    image_path = Path(image_path)
    if image_path.suffix.lower() in (".jpg", ".jpeg"):
        return image_path
    jpg = image_path.with_suffix(".jpg")
    if not jpg.exists():
        Image.open(image_path).convert("RGB").save(jpg, "JPEG", quality=92)
    return jpg


def build_description(row):
    desc = (row["description"] or "").strip()
    tags = [t.strip().replace(" ", "") for t in (row["tags"] or "").split(",")
            if t.strip()]
    if tags:
        desc = (desc + " " + " ".join("#" + t for t in tags)).strip()
    return desc[:500]


def validate(row, images):
    if not (row["image"] or "").strip():
        return "no image filename"
    if row["image"].strip() not in images:
        return f"image '{row['image'].strip()}' not found in the images folder"
    if not (row["title"] or "").strip():
        return "no title"
    if not (row["link"] or "").strip().startswith("http"):
        return "link is missing or not a web address"
    if not (row["board"] or "").strip():
        return "no board name"
    return None


# ---------------------------------------------------------------- main

def hold_open():
    if os.name == "nt":
        try:
            input("\nPress Enter to close this window...")
        except (EOFError, KeyboardInterrupt):
            pass


def main():
    print("=" * 62)
    print("  PIN PUBLISHER — publish pins from your CSV schedule")
    print("=" * 62)

    cfg = load_config()
    if not cfg.get("pinterest_app_id"):
        print("\nOne-time Pinterest setup. From developers.pinterest.com,")
        print("open your app and copy these two values:")
        cfg["pinterest_app_id"] = input("  App ID: ").strip()
        cfg["pinterest_app_secret"] = input("  App secret: ").strip()
        if not cfg["pinterest_app_id"] or not cfg["pinterest_app_secret"]:
            print("Both values are needed. Run this again when you have them.")
            return 1
        save_config(cfg)

    d = work_dir()
    if not csv_path().exists():
        create_template()
        print(f"\nFirst run! I created your pin schedule here:\n\n   {csv_path()}\n")
        print("How it works:")
        print("  1. Put pin images in the 'images' folder next to it")
        print("     (any filenames — 1.png, 2.png, or descriptive names).")
        print("  2. Open pins.csv in Excel. One row per pin. The example row")
        print("     shows every column. Leave publish_date blank to post on")
        print("     the next run, or set a date/time to hold it until then.")
        print("     Leave the 'posted' column alone — the app fills it in.")
        print("  3. Run this again. It posts everything that's due.")
        return 0

    rows = load_rows()
    images = {p.name for p in (d / "images").iterdir() if p.is_file()}
    now = datetime.now()

    due, future, skipped = [], [], []
    for i, row in enumerate(rows):
        if (row["posted"] or "").strip():
            continue
        problem = validate(row, images)
        if problem:
            skipped.append((i, row, problem))
            continue
        try:
            when = parse_when(row["publish_date"])
        except ValueError as e:
            skipped.append((i, row, str(e)))
            continue
        if when and when > now:
            future.append((row, when))
        else:
            due.append((i, row))

    if not due and not future and not skipped:
        print("\nNothing to do — every row in pins.csv is already posted.")
        return 0

    if due:
        pin = Pinterest(cfg["pinterest_app_id"], cfg["pinterest_app_secret"])
        if pin.token is None:
            pin.connect()

        print(f"\nPosting {len(due)} pin(s) that are due…\n")
        boards_by_name = {}

        def board_id(name):
            if not boards_by_name:
                boards_by_name.update({b["name"].lower(): b["id"]
                                       for b in pin.boards()})
            key = name.lower()
            if key not in boards_by_name:
                b = pin.create_board(name)
                boards_by_name[key] = b["id"]
                print(f"     (created new board '{name}')")
            return boards_by_name[key]

        for i, row in due:
            try:
                img = as_jpeg(d / "images" / row["image"].strip())
                pin.create_pin(
                    board_id=board_id(row["board"].strip()),
                    image_path=img,
                    title=row["title"].strip(),
                    description=build_description(row),
                    link=row["link"].strip(),
                    alt_text=(row["alt_text"] or row["title"]).strip(),
                )
                rows[i]["posted"] = now.strftime("%Y-%m-%d %H:%M")
                save_rows(rows)          # save after EVERY pin: crash-safe
                print(f"  posted: {row['title']}")
            except PinterestError as e:
                print(f"  FAILED: {row['title']} — {e}")

    if future:
        print(f"\nWaiting for their date/time ({len(future)}):")
        for row, when in sorted(future, key=lambda x: x[1]):
            print(f"  {when:%Y-%m-%d %H:%M}  {row['title']}")
        print("Run this again after those times (or daily) and they'll post.")

    if skipped:
        print(f"\nRows with problems ({len(skipped)}) — fix these in pins.csv:")
        for i, row, why in skipped:
            label = row.get("title") or row.get("image") or f"row {i + 2}"
            print(f"  row {i + 2} ({label}): {why}")

    return 0


if __name__ == "__main__":
    try:
        try:
            sys.exit(main())
        except PinterestError as e:
            print(f"\n{e}")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n\nStopped. Pins already posted were marked in pins.csv.")
            sys.exit(1)
    finally:
        hold_open()
