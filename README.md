# Pinterest Pin Publisher

This app takes pictures from a folder and posts them to Pinterest on a schedule, automatically.

You do this once: create a couple of free accounts, then double-click **Setup**.
After that, every time you have new pins: drop pictures in a folder, double-click **Publish Pins**.

You do not need to type commands for the normal loop. You do not upload pictures to WordPress. You do not learn Cloudflare.

If you already finished Setup on this computer, skip to [Every time you have new pins](#every-time-you-have-new-pins).

For extra commands, troubleshooting, and the Pinterest Standard access video walkthrough, see [ADVANCED.md](ADVANCED.md).

---

## One-time setup (about 15 minutes)

Put this whole folder somewhere easy to find, like your Desktop. Do not rename the files inside it.

**Do not email your keys. Do not put them in this folder. Do not post them online.** Setup opens the right page for you and asks you to paste each key straight into a window. That is the only place they go.

1. **Create a free Cloudflare account** at https://dash.cloudflare.com/ (skip adding a website if it asks, you don't need one). Then turn on picture storage: click the search box at the top, type `R2`, open it, and click **Enable** (the free plan is enough).

2. **Double-click Setup** (`Setup.command` on Mac, `Setup.bat` on Windows).  
   If the computer blocks it:
   - **Mac:** right-click `Setup.command`, click **Open**, then click **Open** again.
   - **Windows:** click **More info**, then **Run anyway**.

3. **Follow the window.** It installs Python and Node.js for you automatically if you don't already have them (a browser tab or an extra window may briefly pop up for that, that's normal), then walks you through everything else in order, opening the right page for you each time:
   - **Anthropic** (writes your pin titles): sign in or create an account, add a payment method if it asks (this is a paid service, a batch of pins is usually a small bill), and copy the key it generates.
   - **Your website address**, typed the way you'd type it in a browser, e.g. `https://yourfrugalmom.com`.
   - **A folder for your pin pictures.** Press Enter to use the default (`images`).
   - **Pinterest app**: create one (any name is fine), paste this redirect URL into it exactly: `http://localhost:8765/callback`, then copy the App ID and App secret back into the Setup window.
   - **Whether you already have Pinterest Standard access.** If you're not sure, type `n`, that's the safe answer for a brand-new app. (New apps start in Trial mode, where pins are private to you. See [ADVANCED.md](ADVANCED.md#make-pins-public-standard-access) for applying for Standard access.)
   - A browser window opens to **Pinterest**, click **Allow**, then come back to the window.
   - A browser window may open to **Cloudflare**, sign in and click **Allow** if it asks.
   - Pick which board to post to when it lists them.

4. **Wait for "All set."** Press Enter to close the window. You only run Setup again if you make a new Pinterest app, revoke access, change your website or board, or get approved for Standard access.

---

## Every time you have new pins

1. Open this project folder, then open the `images` folder (Setup created it for you).
2. Put your pin pictures in `images`. Use `.png` or `.jpg` files only. Do not use a Word file, a PDF, or a folder inside `images`.  
   **File names do not matter for the title.** The AI reads the words printed on the picture itself, it does not read the file name. Name your files however you want.  
   The one thing file names *do* control is posting order: pictures post in alphabetical file-name order unless you shuffle in the next step. Name files like `01_...`, `02_...` if you want a specific order.
3. **Mac:** double-click `Publish Pins.command`. **Windows:** double-click `Publish Pins.bat`.
4. A list of options appears. Type `1` and press Enter (or just press Enter) to publish new pins.
5. It asks **Shuffle the post order?** Press Enter for no. Type `y` if your image names group the same topic together (like `*_v1` through `*_v5`) and you'd rather mix topics up instead of posting several in a row about the same thing.
6. Wait. The window says what it's doing: uploading pictures, writing titles, matching blog links, then scheduling.
7. When it says **All done**, read the line that tells you how many pins were queued and when the first one posts.
8. Press Enter to close the window.

The other numbers on that list are for later: post waiting pins right now, clean up duplicate titles, reset or empty the queue, or delete stored pictures for pins that already posted. See [ADVANCED.md](ADVANCED.md) for what each one does.

The poster checks about every 15 minutes. A pin scheduled for 9:00 may go out any time between 9:00 and 9:14.

You can leave the pictures in `images` after that. Next time, only the new ones get uploaded and posted, anything already queued or posted gets skipped automatically (matched by file name), so you never end up with the same picture posted twice. New titles that happen to match a title already in the queue get reworded automatically too.

---

## If something goes wrong

**The window says `python` is not found**  
Close every text window and double-click Setup again, it installs Python automatically. If it still can't, see [ADVANCED.md](ADVANCED.md#something-went-wrong) for a manual install link.

**The window says no images found**  
Put `.png` or `.jpg` files directly in the `images` folder, not in a subfolder, then double-click Publish Pins again.

**Pins never show up for other people**  
Your Pinterest app is still in Trial. Pins are private. See [ADVANCED.md](ADVANCED.md#something-went-wrong) for details and how to get Standard access.

More issues and fixes are in [ADVANCED.md](ADVANCED.md#something-went-wrong).
