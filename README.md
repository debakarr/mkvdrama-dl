# drama-dl

Downloader for Asian drama sites — **mkvdrama.net**, **dramaday.me**, and more.

A multi-provider CLI with a clean plugin architecture for adding future sites.

## Supported Sites

| Provider | Domain | Shorteners | Notes |
|----------|--------|------------|-------|
| **mkvdrama** | mkvdrama.net | ouo.io, oii.la, ouo.press | Gate/Pass API + AES-GCM decryption |
| **dramaday** | dramaday.me, dramaday.net | exe.io, cutw.in, ouo.io | Direct HTML parsing, no API needed |

## Usage (from source)

```bash
# Search for a drama (all providers)
uv run drama search "flower of evil"

# Download from mkvdrama.net
uv run drama dl https://mkvdrama.net/804524-the-flowers-of-evil-2026

# Download from dramaday.me
uv run drama dl https://dramaday.me/sold-out-on-you/

# Filter by episode range
uv run drama dl "sold out on you" --episode 1-5

# Filter by quality (540p, 720p, 1080p)
uv run drama dl "all of us are dead" --quality 1080p

# Resolve shorteners to final URLs (requires Playwright)
uv run drama dl "all of us are dead" --quality 1080p --resolve

# Use FlareSolverr instead of Playwright
uv run drama dl "all of us are dead" --flaresolverr http://localhost:8191

# Forward resolved URLs to JDownloader2 LinkGrabber
uv run drama dl "sold out on you" --resolve --jd

# Save organized link files to a custom directory
uv run drama dl "sold out on you" --resolve --output-dir ./my-links
```

## Setup

```bash
# Install dependencies
uv sync

# For shortener resolution with --resolve (optional)
uv run playwright install chromium
```

> **Note**: The old `mkvdrama` command still works for backward compatibility.
> New features and providers are only available via the `drama` command.

## How It Works

### mkvdrama.net Resolution Chain

```
mkvdrama.net _c/ link  →  ouo.io shortener  →  filecrypt.cc container  →  Mega/Pixeldrain/Gofile direct links
```

1. **Gate/Pass API**: Executes the site's anti-bot verification flow (via cloudscraper)
2. **AES-GCM Decryption**: Decrypts the download panel HTML using the gate path as key
3. **`_c/` Link Resolution**: Resolves internal proxy links to ouo.io shortener URLs
4. **Shortener Resolution** (`--resolve`): Opens ouo.io via Playwright/FlareSolverr, clicks through Turnstile/countdown, captures the final redirect URL (filecrypt container)
5. **Organized Output**: Writes per-host-domain `.txt` files with dcrypt.it direct links automatically

### dramaday.me Resolution Chain

```
dramaday.me page  →  HTML table parse  →  exe.io/cutw.in/ouo.io  →  Mega/Pixeldrain/Send/Buzzheavier
```

1. **HTML Parsing**: Scrapes the drama page directly (no API needed)
2. **Download Table**: Parses the Episode | Quality | Download table structure
3. **Shortener Resolution** (`--resolve`):
   - `exe.io/full/` URLs are decoded directly (base64, no browser needed)
   - `cutw.in` and `ouo.io` URLs are resolved via Playwright/FlareSolverr
4. **Organized Output**: Same per-host-domain `.txt` file structure

## Download Options

| Method | How | Best For |
|--------|-----|----------|
| **No resolution** | Just copy the shortener links | Pasting into JDownloader2 |
| **`--resolve`** | Playwright automates shorteners → direct URLs + per-host `.txt` files | Getting organized direct links |
| **`--jd` / `--jdownloader`** | Writes `.crawljob` file to JDownloader2's monitored folder | Bulk downloads without manual link copying |
| **dcrypt.it** | Paste filecrypt URL at dcrypt.it → all direct links | Extracting Mega/Pixeldrain/Gofile URLs |
| **JDownloader2** | Paste any shortener/filecrypt link | Bulk downloads (handles everything) |

### Option 1: No resolution (output shortener links)

Default behavior. Outputs shortener links compatible with JDownloader2.

```bash
drama dl "sold out on you" --quality 1080p
```

### Option 2: Resolve shorteners with Playwright (`--resolve`)

Resolves shortener links to final destination URLs using an automated browser, then
extracts direct download links and saves organized per-host-domain `.txt` files
automatically to `~/Downloads/drama-dl/{Drama Name}/`.

```bash
# Default output location (~/Downloads/drama-dl/)
drama dl "all of us are dead" --quality 1080p --resolve

# Custom output location
drama dl "all of us are dead" --resolve --output-dir ./my-downloads
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
drama dl "sold out on you" --resolve --jd
```

Overrides:
```bash
# Custom JDownloader2 folder
drama dl "sold out on you" --resolve --jd-dir C:/JDownloader2/cfg/crawljob

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
drama dl "drama" --quality 1080p

# Multiple qualities
drama dl "drama" --quality "720p,1080p"
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MKVDRAMA_DOWNLOADS_DIR` | Default output directory for organized link files (default: `~/Downloads/drama-dl/`) |
| `MKVDRAMA_COOKIE` | `cf_clearance` cookie for Cloudflare-bypassed requests (mkvdrama.net) |
| `DRAMADAY_COOKIE` | `cf_clearance` cookie for dramaday.me (optional) |
| `FLARESOLVERR_URL` | FlareSolverr endpoint URL (equivalent to `--flaresolverr`) |
| `JD2_CRAWLJOB_DIR` | JDownloader2 crawljob folder path (equivalent to `--jd-dir`) |

## Provider-Specific Notes

### mkvdrama.net
- Uses Cloudflare protection with a gate/pass API flow
- Requires `cloudscraper` for TLS fingerprint impersonation
- ouo.io uses Cloudflare Turnstile challenges that require browser automation
- oii.la links are skipped during `--resolve` (complex multi-page chain)

### dramaday.me

> ⚠️ **Cloudflare Notice**: dramaday.me has strict Cloudflare protection that blocks
> automated requests (curl-cffi, cloudscraper, and headless browsers). To use this
> provider, you need either a running **FlareSolverr** instance or a valid
> `cf_clearance` cookie via `DRAMADAY_COOKIE`.

- WordPress/Madara theme site, Cloudflare-protected
- No gate/pass API — all links are directly in the HTML page
- Download section uses a table with columns: Episode | Quality | Download
- Host links: AkiraBox, MEGA, Pixeldrain, Send, Buzzheavier
- Shortener domains:
  - **exe.io** — main shortener; `/full/` URLs are base64-decoded directly (no browser)
  - **cutw.in** — used for MEGA links; resolved via Playwright
  - **ouo.io** — used for Send and Buzzheavier links; resolved via Playwright

## Adding New Providers

The provider architecture makes it easy to add new sites:

1. Create `src/drama_dl/providers/newsite.py`
2. Subclass `DramaProvider` and implement: `name`, `domains`, `search`, `get_drama`, `resolve_shorteners`
3. Register in `src/drama_dl/providers/__init__.py`:
   ```python
   from drama_dl.providers.newsite import NewSiteProvider
   PROVIDERS.append(NewSiteProvider)
   ```

## Notes

- Output files are written to `~/Downloads/drama-dl/{Drama Name}/` by default when `--resolve` is used.
- The old `mkvdrama_downloader` package is kept for reference — do not delete it.
- Filecrypt.cc pages load content via JavaScript — the tool attempts DLC/dcrypt.it extraction automatically.
