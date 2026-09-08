# Pinterest Pin Publisher

This app takes pictures from a folder and posts them to Pinterest on a schedule.

You do this once:

1. Install two free programs
2. Make three free accounts and copy a few keys
3. Double-click **Setup**

After that, every time you have new pins:

1. Put the pictures in the `images` folder
2. Double-click **Publish Pins**

You do not need to type commands for the normal loop. You do not upload pictures to WordPress. You do not learn Cloudflare.

If you already finished Setup on this computer, skip to [Every time you have new pins](#every-time-you-have-new-pins).

---

## Before you start

Put this whole folder somewhere easy to find, like your Desktop. Do not rename the files inside it.

You need:

- A computer (Mac or Windows)
- An internet connection
- The WordPress site you already have (this app only reads post links from it)
- About 20 minutes the first time

Have a notepad ready. You will copy and paste a few keys.

**Do not email your keys. Do not put them in this folder. Do not post them online.** Setup will ask you to paste them into a window. That is the only place they go.

---

## Part 1. Install two programs

Do this even if you think you already have them. It is safer to install again than to guess.

### Python (runs the app)

1. Open https://www.python.org/downloads/
2. Click the big yellow **Download** button.
3. Open the file you just downloaded.
4. On Windows: tick the box that says **Add python.exe to PATH** before you click Install. If you miss this box, uninstall Python and install it again.
5. Click **Install Now** (Windows) or go through the installer (Mac).
6. When it finishes, close the installer.

### Node.js (needed once, so Setup can talk to Cloudflare)

1. Open https://nodejs.org/
2. Click the button that says **LTS**.
3. Open the file you just downloaded and click through with the default choices.
4. When it finishes, close the installer.

Restart your computer if either installer asks you to.

---

## Part 2. Make three accounts and copy your keys

You can do these in any order. Finish all three before you run Setup.

### A. Anthropic (Claude writes the pin titles)

1. Open https://console.anthropic.com/
2. Create an account or sign in.
3. If it asks for a payment method, add one. Claude is a paid service. A batch of pins is usually a small bill.
4. Open https://console.anthropic.com/settings/keys
5. Click **Create Key**.
6. Copy the key. It starts with `sk-ant-`.
7. Paste it into your notepad. You will need it in Setup.

Keep that tab open until Setup is done.

### B. Pinterest (the account that will post the pins)

Use the **Pinterest business** account that owns the board you want.

1. Open https://developers.pinterest.com/apps/
2. Sign in.
3. Click to create an app. Name it anything, for example `pin-publisher`.
4. Open the app you just made.
5. Find **App ID** and **App secret**. Copy both into your notepad.
6. Find the box for a redirect URL (sometimes called Redirect URI or Callback).
7. Paste this in **exactly**, with no extra spaces and no `https`:

   `http://localhost:8765/callback`

8. Save if there is a Save button.

New Pinterest apps start in **Trial** mode. Trial pins are private. Only you can see them, and only on your own Pinterest profile (usually a board named **Sandbox pins**). A pin link that works on this computer may not open on another computer until Pinterest approves **Standard** access. That is normal. See [Make pins public](#make-pins-public-standard-access) when you are ready.

### C. Cloudflare (stores your pictures and posts on a clock)

1. Open https://dash.cloudflare.com/
2. Create a free account or sign in.
3. You do not need to add a website. If Cloudflare asks you to add a site, you can skip that or close it. This app does not need your domain on Cloudflare.

---

## Part 3. Turn on Cloudflare picture storage (one time)

Cloudflare calls this **R2**. It is not always sitting at the top of the left menu. Use search.

1. Stay on https://dash.cloudflare.com/
2. Click the search box at the top of the page.
3. Type `R2` and press Enter.
4. Open **R2** or **R2 Object Storage**.
5. If you still cannot find it, look on the left for **Storage & databases**, then click **R2**.
6. Click **Enable** or finish the free checkout if it asks. The free plan is enough.
7. You can close the tab. Setup will create the storage folder for you.

If Setup later says `R2 storage isn't turned on`, come back here, click Enable, then run Setup again.

---

## Part 4. Run Setup (one time on this computer)

### Open the right file

1. Open this project folder (the one that has `Setup.command` and `Setup.bat` in it).
2. **Mac:** double-click `Setup.command`.
3. **Windows:** double-click `Setup.bat`.

If the computer blocks it:

- **Mac:** right-click `Setup.command`, click **Open**, then click **Open** again.
- **Windows:** click **More info**, then **Run anyway**.

A black or white text window will open. Leave it open. You will type in it.

### What Setup will ask, in order

It installs a couple of Python packages first. That can take a minute. Wait.

Then it asks questions. After each one, press **Enter**.

1. **Anthropic key.** Paste the `sk-ant-` key from your notepad. You will see stars (`****`) instead of the real letters. Press Enter.
2. **Website URL.** Type your site the way people type it in a browser, for example `https://yourfrugalmom.com`. No slash at the end.
3. **Image folder.** Press Enter to use the default (`images`). Setup will create that folder if it is missing.
4. **Pinterest App ID.** Paste the App ID from your notepad.
5. **Pinterest App secret.** Paste the App secret. You will see stars (`****`) instead of the real letters. Press Enter.
6. **Do you already have Pinterest Standard access? (y/n)**  
   If you are not sure, type `n` and press Enter. That is the safe answer for a new app.

### What happens next (do not close the window)

1. A browser window opens to Pinterest. Sign in if it asks. Click **Allow**. Then come back to the text window.
2. Setup lists your boards and asks for a number. Type the number of the board you want (or `1` if there is only one) and press Enter.  
   If you are in Trial mode and have no boards yet, Setup makes one called **Sandbox pins** for you.
3. A browser window may open to Cloudflare. Sign in and click **Allow** if it asks.
4. Setup creates the queue, the picture storage, and the poster. Wait until it says **All set**.
5. Press Enter to close the window.

You only run Setup again if you make a new Pinterest app, revoke access, change your website or board, or get approved for Standard access.

---

## Every time you have new pins

1. Open this project folder.
2. Open the `images` folder. If you do not see it, run Setup once (it creates the folder).
3. Put your pin pictures in `images`. Use `.png` or `.jpg` files only. Do not use a Word file, a PDF, or a folder inside `images`.  
   **File names do not matter for the title.** The AI reads the words printed on the picture itself to write the Pinterest title, description, and keywords, it does not read the file name. Name your files however you want (`photo1.png`, `IMG_4821.jpg`, anything).  
   The one thing file names *do* control is posting order: pictures post in alphabetical file-name order unless you choose to shuffle in the next step. So if you want a specific order, name files like `01_...`, `02_...`, `03_...`.
4. **Mac:** double-click `Publish Pins.command`.
5. **Windows:** double-click `Publish Pins.bat`.
6. A list of options appears. Type `1` and press Enter (or just press Enter) to publish new pins.
7. It asks **Shuffle the post order?** Press Enter for no (posts in alphabetical file-name order). Type `y` if your image names group the same topic together (like `*_v1` through `*_v5`) and you would rather mix topics up instead of posting five in a row about the same thing.
8. Wait. The window will say what it is doing: uploading pictures, writing titles, matching blog links, then scheduling.
9. When it says **All done**, read the line that tells you how many pins were queued and when the first one posts.
10. Press Enter to close the window.

The other numbers on that list are for later: post waiting pins right now, clean up duplicate titles, reset or empty the queue, or delete stored pictures for pins that already posted.

The poster checks about every 15 minutes. A pin scheduled for 9:00 may go out any time between 9:00 and 9:14.

You can leave the pictures in `images` after that. Next time, only the new ones get uploaded and posted, anything already queued or posted gets skipped automatically (matched by file name), so you never end up with the same picture posted twice. New titles that happen to match a title already in the queue get reworded automatically too.

---

## Something went wrong

**The window says `python` is not found**  
Install Python again from https://www.python.org/downloads/. On Windows, tick **Add python.exe to PATH**. Then close every text window and try Setup again.

**The window says no images found**  
Put `.png` or `.jpg` files directly in the `images` folder, not in a subfolder, then double-click Publish Pins again.

**The Pinterest browser page does nothing, or Setup says the redirect failed**  
Open your Pinterest app at https://developers.pinterest.com/apps/. The redirect URL must be exactly `http://localhost:8765/callback`. Save, then run Setup again.

**The window says `R2 storage isn't turned on`**  
Go to https://dash.cloudflare.com/, search for `R2`, click **Enable**, then run Setup again.

**Pins never show up for other people**  
Your Pinterest app is still in Trial. Pins are private. On this computer, open your Pinterest profile and look for the **Sandbox pins** board (or the board you picked). Do not judge success by opening the pin link on a second computer. When Pinterest approves Standard access, run Setup again and answer `y` to the Standard access question.

**A pin got the wrong blog link**  
See [Fix one pin's link](#fix-one-pins-link) below.

**Nothing is posting, even after waiting**  
Run Setup again. It will reconnect the poster.

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

The menu already asks about this each time (step 7 above). If you would rather always shuffle without being asked, add the flag directly:

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
