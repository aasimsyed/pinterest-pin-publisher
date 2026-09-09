# Advanced guide

This covers everything you don't need for the normal day-to-day loop: troubleshooting, extra commands, applying for Pinterest Standard access, and where your keys live. See [README.md](README.md) for the everyday setup and publishing steps.

---

## Something went wrong

**The window says `python` is not found**  
Double-click Setup again, it tries to install Python automatically. If that still doesn't work, install it yourself from https://www.python.org/downloads/. On Windows, tick **Add python.exe to PATH**. Then close every text window and try Setup again.

**The window says `node` is not found**  
Same as above, but for https://nodejs.org/ (click the **LTS** button). Setup needs this once to talk to Cloudflare.

**The window says no images found**  
Put `.png` or `.jpg` files directly in the `images` folder, not in a subfolder, then double-click Publish Pins again.

**The Pinterest browser page does nothing, or Setup says the redirect failed**  
Open your Pinterest app at https://developers.pinterest.com/apps/. The redirect URL must be exactly `http://localhost:8765/callback`. Save, then run Setup again.

**The window says `R2 storage isn't turned on`**  
Setup already opened the R2 page for you, click **Enable**, then run Setup again. If the page didn't open, go to https://dash.cloudflare.com/, search for `R2`, click **Enable**.

**Pins never show up for other people**  
Your Pinterest app is still in Trial. Pins are private. On this computer, open your Pinterest profile and look for the **Sandbox pins** board (or the board you picked). Do not judge success by opening the pin link on a second computer. When Pinterest approves Standard access, run Setup again and answer `y` to the Standard access question.

**A pin got the wrong blog link**  
See [Fix one pin's link](#fix-one-pins-link) below.

**Nothing is posting, even after waiting**  
Run Setup again. It will reconnect the poster.

**A window says the Cloudflare login is not authorized or expired**  
It reopens the Cloudflare login page for you automatically, click **Allow** and it retries on its own. If it happens again right after, run Setup again.

---

## Extra commands (only if you need them)

You do not need this section for the normal loop.

Most of these are also on the list when you double-click **Publish Pins**:

- `2` posts waiting pins right now (it will ask how many)
- `3` removes duplicate titles
- `4` resets the queue
- `5` empties the queue
- `6` deletes pictures for pins that already posted
- `7` shows pins waiting to be published

If you would rather type a command, open a text window in this project folder.

### How to open that window

**Mac**

1. Open **Terminal** (press Command + Space, type `Terminal`, press Enter).
2. Type `cd ` (c d space). Do not press Enter yet.
3. Drag this project folder onto the Terminal window. The path appears after `cd `.
4. Press Enter.

**Windows**

1. Open this project folder in File Explorer.
2. Click the address bar at the top (the line that shows the folder path).
3. Type `cmd` and press Enter.

You should now be able to paste a command and press Enter.

### Post pins in a shuffled order

The menu already asks about this each time. If you would rather always shuffle without being asked, add the flag directly:

```
python scripts/publish.py --shuffle
```

### Post the same picture again on purpose

Normally, a picture already queued or posted gets skipped automatically. If you deliberately want to re-post one (for example, you changed the text on the graphic), add this flag:

```
python scripts/publish.py --force-requeue
```

This re-processes every picture currently in `images`, not just the new ones, so only use it when you mean to.

### Look at titles and links before they go out

After Publish Pins runs, open `pinterest_bulk_upload_with_links.csv` in Excel or Google Sheets.

### Fix one pin's link

1. Open `pinterest_bulk_upload_with_links.csv`.
2. Fix the **Link** cell.
3. Save the file.
4. In the text window, paste this and press Enter:

```
python scripts/push_to_d1.py
```

### See what's waiting to post

Shows every pin that hasn't posted yet, with its scheduled time.

```
python scripts/publish.py --list-queue
```

To also see pins that already posted or failed, add `--all-statuses`.

### Remove extra copies of the same title

Keeps the oldest pin for each title. Deletes the newer copies. Only touches pins that have not posted yet.

```
python scripts/publish.py --dedupe-queue
```

### Post the next pins right now

Does not wait for the scheduled time. Use this for a test, or for the Standard access video.

```
python scripts/publish.py --run-now
```

That posts the next 3. To post just one:

```
python scripts/publish.py --run-now 1
```

The window prints each title and a Pinterest link. In Trial mode, that link may only work on this computer while you are logged into the same Pinterest account. On another computer, open your **Sandbox pins** board instead.

From the menu, choice `2` also asks **"Pick which ones randomly instead of earliest-scheduled first?"** Press Enter for no. From the command line, add `--shuffle`:

```
python scripts/publish.py --run-now 1 --shuffle
```

### Put already-posted pins back in line

Deletes pins that are waiting or failed. Puts already-posted pins back to waiting so they can post again.

```
python scripts/publish.py --reset-queue
```

It will ask `Continue?` Type `y` and press Enter.

### Empty the queue completely

Deletes every pin in the queue, including ones that already posted. The queue will be empty.

```
python scripts/publish.py --clear-queue
```

It will ask `Continue?` Type `y` and press Enter.

### Delete pictures for pins that already posted

Removes those pictures from Cloudflare storage. Pictures still needed by a pin that is waiting or failed are kept. Already-posted Pinterest pins keep working, because Pinterest has its own copy.

```
python scripts/publish.py --prune-images
```

It will ask `Continue?` Type `y` and press Enter.

---

## Make pins public (Standard access)

Trial pins stay private. To post real public pins, apply for **Standard** access on your app page: https://developers.pinterest.com/apps/

Pinterest wants a short screen recording that shows two things:

1. You click **Allow** on Pinterest's own login page, and it comes back successfully.
2. The app really creates a pin.

How to record that video:

1. Start your screen recorder.
2. Double-click **Setup** (`Setup.command` on Mac, `Setup.bat` on Windows).
3. When the browser opens to Pinterest, click **Allow**. Do not skip this. Do not speed it up. Pinterest checks for it.
4. Wait until Setup says it finished.
5. Put one test picture in the `images` folder.
6. Double-click **Publish Pins**, type `1`, and press Enter.
7. Double-click **Publish Pins** again, type `2`, press Enter, then type `1` for how many pins.
8. On screen, open your Pinterest board and show the pin. In Trial mode, use your **Sandbox pins** board. That is enough for the video. You do not need Standard access yet to record it.

When Pinterest approves you, run Setup again and answer `y` to "Do you already have Pinterest Standard access?"

---

## Where your keys live (you can skip this)

You do not need to open these files.

- Your Anthropic key, website, image folder, board, and a couple of poster settings live in a private file on this computer: `~/.config/pinterest-pin-publisher/config.json` (Mac) or the same kind of file under your user folder (Windows).
- Your Pinterest App secret and refresh token live in your Cloudflare account, not in this project folder.
- Your Cloudflare login lives in Cloudflare's own login on this computer.
- Your pin pictures live in your own Cloudflare picture storage.

Do not copy those files into email, chat, or GitHub.
