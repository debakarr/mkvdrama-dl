# mkvdrama-dl

Downloader for https://mkvdrama.net/ — scrape download links for Asian dramas.

## Usage (from source)

```bash
# Search for a drama
uv run mkvdrama search "flower of evil"

# List download links for a drama
uv run mkvdrama dl https://mkvdrama.net/804524-the-flowers-of-evil-2026

# Filter by episode range
uv run mkvdrama dl "sold out on you" --episode 1-5

# Filter by quality (540p, 720p, 1080p, 1080pHD)
uv run mkvdrama dl "all of us are dead" --quality 1080p

# Resolve ouo.io shorteners to filecrypt URLs (requires Playwright)
uv run mkvdrama dl "all of us are dead" --quality 1080p --resolve

# Use FlareSolverr instead of Playwright
uv run mkvdrama dl "all of us are dead" --flaresolverr http://localhost:8191

# Forward resolved URLs to JDownloader2 LinkGrabber
uv run mkvdrama dl "sold out on you" --resolve --jd

# Save organized link files to a custom directory
uv run mkvdrama dl "sold out on you" --resolve --output-dir ./my-links
```

## Setup

```bash
# Install dependencies
uv sync

# For ouo.io resolution with --resolve (optional)
uv run playwright install chromium
```

> **Note**: Once stable, this will be published to PyPI as `mkvdrama-downloader`.
> For now, run from the repo root with `uv run mkvdrama ...`.

## How It Works

The tool scrapes download links from mkvdrama.net through a multi-step process:

1. **Gate/Pass API**: Executes the site's anti-bot verification flow (via cloudscraper)
2. **AES-GCM Decryption**: Decrypts the download panel HTML using the gate path as key
3. **`_c/` Link Resolution**: Resolves internal proxy links to ouo.io shortener URLs
4. **Shortener Resolution** (`--resolve`): Opens ouo.io via Playwright/FlareSolverr, clicks through Turnstile/countdown, captures the final redirect URL (filecrypt container)
5. **Organized Output**: Writes per-host-domain `.txt` files with dcrypt.it direct links automatically

### Resolution chain

```
mkvdrama.net _c/ link  →  ouo.io shortener  →  filecrypt.cc container  →  Mega/Pixeldrain/Gofile direct links
```

With `--resolve`, the tool follows the chain: internal proxy → ouo.io (via Playwright) → filecrypt.cc → extracts dcrypt.it direct links → saves per-host `.txt` files automatically.

## Download Options

| Method | How | Best For |
|--------|-----|----------|
| **No resolution** | Just copy the ouo.io/oii.la links | Pasting into JDownloader2 |
| **`--resolve`** | Playwright automates ouo.io → filecrypt URL + per-host `.txt` files | Getting organized direct links |
| **`--jd` / `--jdownloader`** | Writes `.crawljob` file to JDownloader2's monitored folder | Bulk downloads without manual link copying |
| **dcrypt.it** | Paste filecrypt URL at dcrypt.it → all direct links | Extracting Mega/Pixeldrain/Gofile URLs |
| **JDownloader2** | Paste any ouo.io/filecrypt link | Bulk downloads (handles everything) |

### Option 1: No resolution (output ouo.io/oii.la links)

Default behavior. Outputs shortener links compatible with JDownloader2.

```bash
mkvdrama dl "sold out on you" --quality 1080p
```

### Option 2: Resolve shorteners with Playwright (`--resolve`)

Resolves ouo.io links to filecrypt container URLs using an automated browser, then
extracts direct download links and saves organized per-host-domain `.txt` files
automatically to `~/Downloads/mkvdrama-dl/{Drama Name}/`.

```bash
# Default output location (~/Downloads/mkvdrama-dl/)
mkvdrama dl "all of us are dead" --quality 1080p --resolve

# Custom output location
mkvdrama dl "all of us are dead" --resolve --output-dir ./my-downloads
```

Files created:
- `mega.nz.txt` — all Mega links
- `pixeldrain.com.txt` — all Pixeldrain links
- `gofile.io.txt` — all Gofile links (etc.)
- `all_links.txt` — combined file with everything
- `filecrypt_container.txt` — original resolved container URLs

Requires Playwright (installed separately):
```bash
uv run playwright install chromium
```

### Option 3: JDownloader2 integration (`--jd`)

Writes url-linked `.crawljob` files to JDownloader2's monitored folder.
Auto-detects the crawljob directory on Windows, macOS, and Linux.

```bash
mkvdrama dl "sold out on you" --resolve --jd
```

Overrides:
```bash
# Custom JDownloader2 folder
mkvdrama dl "sold out on you" --resolve --jd-dir C:/JDownloader2/cfg/crawljob

# Environment variable
set JD2_CRAWLJOB_DIR=C:/JDownloader2/cfg/crawljob
```

### Option 4: dcrypt.it (Direct links from filecrypt)

Paste a filecrypt container URL at [dcrypt.it](https://dcrypt.it/) to extract all
direct Mega/Pixeldrain/Gofile/etc. download links in one click.
The tool does this automatically when `--resolve` is used and a DLC button
is available on the filecrypt page.

## Quality Filter

```bash
# Single quality
mkvdrama dl "drama" --quality 1080p

# Multiple qualities
mkvdrama dl "drama" --quality "720p,1080p"
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MKVDRAMA_DOWNLOADS_DIR` | Default output directory for organized link files (default: `~/Downloads/mkvdrama-dl/`) |
| `MKVDRAMA_COOKIE` | `cf_clearance` cookie for Cloudflare-bypassed requests |
| `FLARESOLVERR_URL` | FlareSolverr endpoint URL (equivalent to `--flaresolverr`) |
| `JD2_CRAWLJOB_DIR` | JDownloader2 crawljob folder path (equivalent to `--jd-dir`) |

## Notes

- The mkvdrama.net site uses Cloudflare protection. The tool uses
  `cloudscraper` (TLS fingerprint impersonation) to bypass it.
- ouo.io uses Cloudflare Turnstile challenges that require browser
  automation (Playwright/FlareSolverr) or JDownloader2 to resolve.
- oii.la links are skipped during `--resolve` (complex multi-page chain).
- Filecrypt.cc pages load content via JavaScript — the tool attempts
  DLC/dcrypt.it extraction automatically; when blocked, paste the URL at
  [dcrypt.it](https://dcrypt.it/) for direct download links.
- Output files are written to `~/Downloads/mkvdrama-dl/{Drama Name}/`
  by default when `--resolve` is used.
