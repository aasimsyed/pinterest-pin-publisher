# pinterest-pin-publisher

Schedule and publish Pinterest pins from a Cloudflare Worker.

## Layout

- `src/worker.js`: cron Worker that publishes due pins from D1
- `migrations/`: D1 schema
- `scripts/`: generate CSV, match WordPress links, OAuth, push to D1
- `desktop/`: optional Windows publisher (`Publish Pins.bat`)

Run Python scripts from the repo root.

```bash
pip install -r requirements.txt
python scripts/oauth_setup.py --client-id APP_ID --client-secret APP_SECRET
python scripts/generate_pinterest_csv.py --images-dir ./images --board "Board Name" --url-prefix "https://example.com/uploads/"
python scripts/match_wordpress_links.py --csv pinterest_bulk_upload.csv --site-url https://example.com --output pinterest_bulk_upload_with_links.csv
python scripts/push_to_d1.py --csv pinterest_bulk_upload.csv --board-id BOARD_ID
```
