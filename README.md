# Pinterest Pin Publisher

This tool turns a folder of pin images into scheduled Pinterest posts.

You do three things:

1. One-time setup (a few accounts, a few clicks)
2. Put new pin images in a folder
3. Double-click **Publish Pins**

That's it. No terminal commands, no manual WordPress uploads, no Cloudflare CLI to learn.

---

## What you need (free accounts)

| What | Why | Where to get it |
| --- | --- | --- |
| Python 3.10 or newer | Runs the app | https://www.python.org/downloads/  On the installer, tick **Add python.exe to PATH**. |
| An Anthropic account | Claude reads each pin image and writes the title, description, and keywords. It also matches each pin to a blog post. | https://console.anthropic.com/ |
| A Pinterest Business account plus a developer app | Lets this tool post pins for you | https://developers.pinterest.com/apps/ |
| A Cloudflare account | Hosts the clock that posts pins on schedule, and your pin images | https://dash.cloudflare.com/ |
| Node.js | Only for the one-time Cloudflare install | https://nodejs.org/ |
| Your WordPress site | Blog post links come from here (images do not) | The site you already have |

You do **not** paste secrets into this GitHub folder. Setup saves them on your computer, in your Cloudflare account, or nowhere at all (some values only ever pass through, never stored).

---

## First time on this computer

### 1. Get an Anthropic (Claude) key

1. Go to https://console.anthropic.com/settings/keys
2. Sign in or create an account.
3. Click **Create Key**.
4. Copy the key (it starts with `sk-ant-`). Keep the tab open, you will paste it in setup.

Anthropic is paid usage. A batch of pins is usually a small bill. Add a payment method in the Anthropic console if it asks.

### 2. Create a Pinterest developer app

1. Go to https://developers.pinterest.com/apps/
2. Sign in with the Pinterest **business** account that owns the board.
3. Create an app. Name it anything, for example `pin-publisher`.
4. Open the app and find **App ID** and **App secret**.
5. Add this redirect URL **exactly** (copy and paste):

   `http://localhost:8765/callback`

6. Keep App ID and App secret handy.

While the app is in **Trial** mode, pins may only show in Pinterest's sandbox. Apply for **Standard** access in the same dashboard when you want public pins (see "Applying for Pinterest Standard access" below).

### 3. Turn on Cloudflare R2 (one click, one time)

1. Install Node.js from https://nodejs.org/ (LTS is fine).
2. Go to https://dash.cloudflare.com/ -> **R2** in the sidebar, and click **Enable** (the free tier is enough for this).

That's the only Cloudflare dashboard step. Everything else, the database, image storage, and the scheduler, gets created for you in the next step.

### 4. Run setup

- **Mac:** double-click `Setup.command`.
- **Windows:** double-click `Setup.bat`.

(First time only, macOS may ask you to confirm you want to run a file you downloaded, right-click it and choose **Open** if double-clicking refuses.)

It will:

- Install Python packages
- Ask for your Anthropic key
- Ask for your website URL, for example `https://yourfrugalmom.com`
- Ask where pin images live (default: a folder named `images`)
- Ask for your Pinterest App ID and App secret, then open a browser so you can click **Allow**
- Show your boards so you can pick one
- Open a browser so you can log into Cloudflare (only if you aren't already)
- Create the pin queue database, set up image storage, save your Pinterest credentials, and turn on the scheduler, all automatically

You only repeat this if you revoke Pinterest access, create a new Pinterest app, or want to change your website/board.

---

## Each time you have new pins

1. Put the pin image files in the `images` folder (PNG or JPG).
2. **Mac:** double-click `Publish Pins.command`. **Windows:** double-click `Publish Pins.bat`.

That's the whole loop. The window will show progress, then a summary like "12 pins queued, the first one posts around 2026-08-16T09:00:00", then wait for you to press Enter to close.

Behind the scenes it:

- Uploads each image to your own private image storage (so Pinterest always has a working link, even if WordPress blocks hotlinking)
- Reads each image with Claude and writes a title, description, and keywords
- Matches each pin to the right post on your WordPress site
- Queues the pins. The Worker posts each one when its time arrives (about every 15 minutes)

---

## If something asks for a flag

The double-click launchers cover the normal case. If you want to run a step by hand (for example, to fix one pin's link) you can still run any script directly from a terminal:

```bash
python scripts/generate_pinterest_csv.py
python scripts/match_wordpress_links.py --site-url https://yoursite.com
python scripts/push_to_d1.py --board-id YOUR_BOARD_ID
```

Open `pinterest_bulk_upload_with_links.csv` in Excel if you want to glance at titles and links before pushing.

---

## Applying for Pinterest Standard access

Pinterest's Trial/sandbox mode only shows pins to you, not the public (setup already asked whether you have Standard access yet, and uses sandbox automatically if not). To go live, apply for **Standard** access from your app's page at https://developers.pinterest.com/apps/. Pinterest requires a short screen recording showing:

1. The full OAuth login (clicking Allow on Pinterest's own consent screen, and the redirect back succeeding), and
2. A real API action, such as creating a pin.

Both already exist in this app:

1. Run setup (`Setup.command` / `Setup.bat`) and record the browser opening to Pinterest, you clicking **Allow**, and the terminal confirming success. Do not skip or speed up this part, Pinterest checks for it.
2. Run `Publish Pins` once with a test image, then trigger the Worker immediately instead of waiting for its 15-minute cron:

   ```bash
   curl -H "Authorization: Bearer YOUR_MANUAL_TRIGGER_SECRET" https://pinterest-pin-publisher.<your-subdomain>.workers.dev/run
   ```

   (Setup printed your `MANUAL_TRIGGER_SECRET` value, and your Worker's address is on its page at https://dash.cloudflare.com/ -> Workers & Pages.)
3. Show the pin appear on your Pinterest board.

Sandbox pins are fine for this video, you don't need Standard access yet to record it.

---

## Where things are stored

| What | Saved where |
| --- | --- |
| Anthropic key, website, image folder, board | `~/.config/pinterest-pin-publisher/config.json` (one file, readable only by your account) |
| Pinterest app credentials, refresh token | Cloudflare Worker secrets only, never written to this project folder |
| Cloudflare login | Your existing `wrangler login` session, this app never stores a separate Cloudflare token |
| Pin images | Your own private Cloudflare R2 bucket |

Never commit config files, images, or generated CSVs. `.gitignore` already ignores them.

---

## Common problems

**`python` not found**  
The double-click launchers try `python3` then fall back to `python`. If both fail, reinstall Python and tick "Add to PATH".

**No images found**  
Put `.png` or `.jpg` files in `images/` before double-clicking Publish Pins.

**Pinterest browser step does nothing**  
The redirect URL on the app must be exactly `http://localhost:8765/callback`.

**Pins never go public**  
The Pinterest app is still in Trial, which can only create pins in Pinterest's private sandbox (only visible to you). Setup already asked whether you have Standard access and set this up correctly either way, once you're approved, re-run `Setup.command` / `Setup.bat` and answer "y" to switch to production.

**"R2 storage isn't turned on"**  
Go to https://dash.cloudflare.com/ -> R2 and click Enable, then run setup again.

**Wrong blog link on a pin**  
Open `pinterest_bulk_upload_with_links.csv`, fix the Link cell, save, then run `python scripts/push_to_d1.py`.

**Worker not posting**  
Re-run setup, it will re-deploy the Worker and re-check your database and secrets.
