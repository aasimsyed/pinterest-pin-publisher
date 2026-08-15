# Pinterest Pin Publisher

This tool turns a folder of pin images into scheduled Pinterest posts.

You do four things, in order:

1. One-time setup (keys and accounts)
2. Put new pin images in a folder
3. Run two commands that write a spreadsheet
4. Run one command that queues the pins. A small Cloudflare program posts them when the time comes.

If a command says `python` is not found, try `python3` instead.

---

## What you need (free accounts)

| What | Why | Where to get it |
| --- | --- | --- |
| Python 3.10 or newer | Runs the scripts | https://www.python.org/downloads/  On the installer, tick **Add python.exe to PATH**. |
| An Anthropic account | Claude reads each pin image and writes the title, description, and keywords. It also matches each pin to a blog post. | https://console.anthropic.com/ |
| A Pinterest Business account plus a developer app | Lets this tool post pins for you | https://developers.pinterest.com/apps/ |
| A Cloudflare account | Hosts the clock that posts pins on schedule | https://dash.cloudflare.com/ |
| Node.js | Only for the one-time Cloudflare install | https://nodejs.org/ |
| Your WordPress site | Pin images and blog post links come from here | The site you already have |

You do **not** paste secrets into this GitHub folder. Setup saves them on your computer only.

---

## First time on this computer

### 0. Open a terminal in this folder

- **Mac:** open Terminal, then:
  `cd` into this project folder (the one that contains `README.md`).
- **Windows:** open Command Prompt, then `cd` into this folder.

### 1. Get an Anthropic (Claude) key

1. Go to https://console.anthropic.com/settings/keys
2. Sign in or create an account.
3. Click **Create Key**.
4. Copy the key (it starts with `sk-ant-`). Keep the tab open. You will paste it in setup.

Anthropic is paid usage. A batch of pins is usually a small bill. Add a payment method in the Anthropic console if it asks.

### 2. Create a Pinterest developer app

1. Go to https://developers.pinterest.com/apps/
2. Sign in with the Pinterest **business** account that owns the board.
3. Create an app. Name it anything, for example `pin-publisher`.
4. Open the app and find **App ID** and **App secret**.
5. Add this redirect URL **exactly** (copy and paste):

   `http://localhost:8765/callback`

6. Keep App ID and App secret handy.

While the app is in **Trial** mode, pins may only show in Pinterest's sandbox. Apply for **Standard** access in the same dashboard when you want public pins.

### 3. Create a Cloudflare database (one time)

1. Install Node.js from https://nodejs.org/ (LTS is fine).
2. In the same terminal:

```bash
npm install -g wrangler
wrangler login
wrangler d1 create pin-publisher-db
```

3. Copy the **database_id** it prints.
4. Apply the table layout:

```bash
wrangler d1 migrations apply pin-publisher-db --remote
```

5. Make a Cloudflare API token:
   - https://dash.cloudflare.com/profile/api-tokens
   - **Create Token**
   - Use a token that can **edit D1**
   - Copy the token once. You will not see it again.

6. Find your **Account ID**: open any domain in https://dash.cloudflare.com/ and copy **Account ID** from the right sidebar.

### 4. Run setup

```bash
python scripts/setup.py
```

It will:

- Install Python packages
- Ask for the Anthropic key
- Ask for your website URL, for example `https://yourfrugalmom.com`
- Ask where pin images live (default: a folder named `images`)
- Ask for the public image URL prefix (see below)
- Open a browser so you can click **Allow** on Pinterest
- Show your boards so you can pick one
- Ask for Cloudflare Account ID, API token, and D1 database ID
- Print three `wrangler secret put` commands. Run those next.

**Image URL prefix:** upload the pin images to WordPress (Media, Add New). Open one image, copy its link, then delete the filename.

Example image link:

`https://yourfrugalmom.com/wp-content/uploads/2026/08/tuna.png`

Prefix to paste:

`https://yourfrugalmom.com/wp-content/uploads/2026/08`

### 5. Save Pinterest secrets on Cloudflare

Setup prints the values. In this folder, run:

```bash
wrangler secret put PINTEREST_CLIENT_ID
wrangler secret put PINTEREST_CLIENT_SECRET
wrangler secret put PINTEREST_REFRESH_TOKEN
```

Paste the matching value when each command asks.

Then start the publisher:

```bash
wrangler deploy
```

You only repeat this if you revoke Pinterest access or create a new app.

---

## Each time you have new pins

1. Put the pin image files in the `images` folder (PNG or JPG).
2. Upload those same files to WordPress Media so the public URLs work.
3. If the WordPress upload folder changed month (for example `/2026/09/` instead of `/2026/08/`), run setup again or pass `--url-prefix` on the generate command.
4. In the project folder, run:

```bash
python scripts/generate_pinterest_csv.py
python scripts/match_wordpress_links.py
python scripts/push_to_d1.py
wrangler deploy
```

`wrangler deploy` also uploads the PNG/JPG files in `images/` so the publisher does not have to download them from WordPress.

That is the whole loop.

- **generate** reads each image with Claude and writes `pinterest_bulk_upload.csv`
- **match** fills the Link column from your WordPress posts
- **push** puts the rows in the Cloudflare queue. The Worker posts each pin when its time arrives (about every 15 minutes)

Open `pinterest_bulk_upload_with_links.csv` in Excel if you want to glance at titles and links before you push.

---

## If something asks for a flag

After setup, the short commands above are enough. You can still override a value:

```bash
python scripts/generate_pinterest_csv.py --url-prefix https://yoursite.com/wp-content/uploads/2026/09
python scripts/match_wordpress_links.py --site-url https://yoursite.com
python scripts/push_to_d1.py --board-id YOUR_BOARD_ID
```

---

## Optional: Windows double-click publisher

If you do not want Cloudflare, `desktop/Install (run once).bat` then `desktop/Publish Pins.bat` posts from a spreadsheet on that PC. That path is separate from the Worker. Prefer the three commands above if you already ran setup.

---

## Where keys are stored

| Secret | Saved on your computer |
| --- | --- |
| Anthropic key | `~/.config/anthropic/config.json` |
| Website, image folder, board | `~/.config/pinterest-pin-publisher/config.json` |
| Cloudflare account, token, D1 id | `~/.config/cloudflare/config.json` |
| Pinterest refresh token | Cloudflare Worker secret only (not this git repo) |

Never commit those files. `.gitignore` already ignores `.env`, images, and generated CSVs.

---

## Common problems

**`python` not found**  
Use `python3`, or reinstall Python and tick Add to PATH.

**No images found**  
Put `.png` or `.jpg` files in `images/` and run the command from this project folder.

**Pinterest browser step does nothing**  
The redirect URL on the app must be exactly `http://localhost:8765/callback`.

**Pinterest says missing `boards:write` or `pins:read`**  
The login must request those scopes. Re-authorize, then replace the refresh token and clear the old cached token:

```bash
python scripts/oauth_setup.py --client-id YOUR_APP_ID --client-secret YOUR_APP_SECRET
wrangler secret put PINTEREST_REFRESH_TOKEN
wrangler d1 execute pin-publisher-db --remote --command "DELETE FROM oauth_tokens;"
wrangler d1 execute pin-publisher-db --remote --command "UPDATE pin_queue SET status = 'pending', error_message = NULL WHERE status = 'failed';"
```

Click Allow in the browser. The Worker will pick up pending pins on the next 15-minute run.

**Pins never go public**  
The Pinterest app is still in Trial. Apply for Standard access. Until then you can publish to sandbox (pins are only visible to you):

```bash
python scripts/oauth_setup.py --client-id YOUR_APP_ID --client-secret YOUR_APP_SECRET --sandbox
wrangler secret put PINTEREST_REFRESH_TOKEN
```

In `wrangler.toml` set `PINTEREST_SANDBOX = "true"` and uncomment `PINTEREST_BOARD_ID` with a sandbox board id from the oauth output. Then:

```bash
wrangler d1 execute pin-publisher-db --remote --command "DELETE FROM oauth_tokens;"
wrangler d1 execute pin-publisher-db --remote --command "UPDATE pin_queue SET status = 'pending', error_message = NULL WHERE status = 'failed';"
wrangler deploy
```

Switch back to production by setting `PINTEREST_SANDBOX = "false"`, putting the production refresh token, clearing `oauth_tokens`, and deploying again.

**Wrong blog link on a pin**  
Open the CSV, fix the Link cell, save, then run `python scripts/push_to_d1.py`.

**Worker not posting**  
Confirm `wrangler deploy` succeeded and the three secrets are set. Check `wrangler.toml` has your real `database_id`, not the placeholder.
