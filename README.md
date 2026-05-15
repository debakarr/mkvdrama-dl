# mkvdrama-dl

Downloader for https://mkvdrama.net/ - scrape download links for Asian dramas.

## Installation

```bash
pip install mkvdrama-downloader
```

Or with uv:

```bash
uv tool install mkvdrama-downloader
```

For ouo.io shortener resolution (optional):

```bash
pip install mkvdrama-downloader[resolve]
playwright install chromium
```

## Usage

```bash
# Search for a drama
mkvdrama search "flower of evil"

# List download links for a drama
mkvdrama dl https://mkvdrama.net/804524-the-flowers-of-evil-2026

# Download specific episodes
mkvdrama dl "flower of evil" --episode 1-5

# Save links to files
mkvdrama dl "sold out on you" --output-dir ./links

# Resolve ouo.io shorteners to final download links (requires Playwright)
mkvdrama dl "sold out on you" --resolve
```

## How It Works

The tool scrapes download links from mkvdrama.net through a multi-step process:

1. **Gate/Pass API**: Executes the site's anti-bot verification flow
2. **Decryption**: Decrypts the download panel HTML (AES-256-GCM)
3. **Link resolution**: Resolves internal `_c/` proxy links to ouo.io/oii.la shorteners
4. **Optional shortener resolution** (`--resolve`): Uses Playwright to automate
   ouo.io verification and extract the final filecrypt URL

## Downloading Files

The tool outputs URL shortener links (ouo.io/oii.la). These lead to Filecrypt
pages where you can choose your preferred file host:

### Option 1: JDownloader2 (Recommended for bulk)
[JDownloader2](https://jdownloader.org/) supports ouo.io links natively.
Just copy all the links and it handles the verification chain automatically.

### Option 2: Manual browser
Open each ouo.io link in a browser, complete the "I'm a human" verification,
then download from the chosen file host (Mega, Gofile, Send.cm, Pixeldrain).

### Option 3: Playwright automation
Use `mkvdrama dl URL --resolve` to automatically resolve ouo.io links
to the final filecrypt URLs using Playwright (headless browser).

## Notes

- The site uses Cloudflare protection. The tool uses `cloudscraper` to bypass it.
- ouo.io shorteners have their own Turnstile verification (handled by Playwright
  with `--resolve` flag, or by JDownloader2/browser manually).


