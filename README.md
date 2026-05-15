# mkvdrama-dl

Downloader for https://mkvdrama.net/ — scrape download links for Asian dramas.

## Installation

```bash
pip install mkvdrama-downloader
```

Or with uv:

```bash
uv tool install mkvdrama-downloader
```

For ouo.io shortener resolution (optional, requires Chromium):

```bash
pip install playwright && playwright install chromium
```

## Usage

```bash
# Search for a drama
mkvdrama search "flower of evil"

# List download links for a drama
mkvdrama dl https://mkvdrama.net/804524-the-flowers-of-evil-2026

# Filter by episode range
mkvdrama dl "sold out on you" --episode 1-5

# Filter by quality (540p, 720p, 1080p, 1080pHD)
mkvdrama dl "all of us are dead" --quality 1080p

# Save links to files
mkvdrama dl "sold out on you" --output-dir ./links

# Resolve ouo.io shorteners to direct download pages
mkvdrama dl "all of us are dead" --quality 1080p --resolve

# Use FlareSolverr instead of Playwright
mkvdrama dl "all of us are dead" --flaresolverr http://localhost:8191
```

## How It Works

The tool scrapes download links from mkvdrama.net through a multi-step process:

1. **Gate/Pass API**: Executes the site's anti-bot verification flow (via cloudscraper)
2. **AES-GCM Decryption**: Decrypts the download panel HTML using the gate path as key
3. **`_c/` Link Resolution**: Resolves internal proxy links to ouo.io shortener URLs
4. **Playwright Resolution** (`--resolve`): Opens ouo.io in a headless browser, clicks through Turnstile/countdown, captures the final redirect URL

### Resolution chain

```
mkvdrama.net _c/ link  →  ouo.io shortener  →  filecrypt.cc container  →  Mega/Pixeldrain/Gofile direct links
```

With `--resolve`, the tool follows the chain: internal proxy → ouo.io (via Playwright) → filecrypt.cc → output the container URL. For direct download links from filecrypt, paste the container URL at [dcrypt.it](https://dcrypt.it/).

## Download Options

| Method | How | Best For |
|--------|-----|----------|
| **No resolution** | Just copy the ouo.io/oii.la links | Pasting into JDownloader2 |
| **`--resolve`** | Playwright automates ouo.io → filecrypt URL | Getting the filecrypt container URL |
| **dcrypt.it** | Paste filecrypt URL at dcrypt.it → all direct links | Extracting Mega/Pixeldrain/Gofile URLs |
| **JDownloader2** | Paste any ouo.io/filecrypt link | Bulk downloads (handles everything) |

### Option 1: No resolution (output ouo.io/oii.la links)

Default behavior. Outputs shortener links compatible with JDownloader2.

```bash
mkvdrama dl "sold out on you" --quality 1080p
```

### Option 2: Resolve shorteners with Playwright (`--resolve`)

Resolves ouo.io links to filecrypt container URLs using an automated browser.
Requires Playwright (installed separately).

```bash
mkvdrama dl "all of us are dead" --quality 1080p --resolve
```

### Option 3: JDownloader2 (Recommended for bulk)

[JDownloader2](https://jdownloader.org/) handles ouo.io, oii.la, and filecrypt links
natively. Just copy all the links and it handles everything automatically.

### Option 4: dcrypt.it (Direct links from filecrypt)

Paste a filecrypt container URL at [dcrypt.it](https://dcrypt.it/) to extract all
direct Mega/Pixeldrain/Gofile/etc. download links in one click.

## Quality Filter

```bash
# Single quality
mkvdrama dl "drama" --quality 1080p

# Multiple qualities
mkvdrama dl "drama" --quality "720p,1080p"
```

## Notes

- The mkvdrama.net site uses Cloudflare protection. The tool uses
  `cloudscraper` (TLS fingerprint impersonation) to bypass it.
- ouo.io uses Cloudflare Turnstile challenges that require browser
  automation (Playwright/FlareSolverr) or JDownloader2 to resolve.
- oii.la links are skipped during `--resolve` (complex multi-page chain).
- Filecrypt.cc pages load content via JavaScript — paste the URL at
  [dcrypt.it](https://dcrypt.it/) for direct download links.
