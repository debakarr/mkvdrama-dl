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
```

## How It Works

The tool scrapes download links from mkvdrama.net through a multi-step process:

1. **Gate/Pass API**: Executes the site's anti-bot verification flow (via cloudscraper)
2. **AES-GCM Decryption**: Decrypts the download panel HTML using the gate path as key
3. **`_c/` Link Resolution**: Resolves internal proxy links to ouo.io/oii.la shorteners

## Downloading Files

The tool outputs URL shortener links (ouo.io/oii.la). These lead to Filecrypt
pages where you can choose your preferred file host:

### Option 1: JDownloader2 (Recommended for bulk downloads)
[JDownloader2](https://jdownloader.org/) handles ouo.io/oii.la links natively.
Just copy all the links and it will automatically handle the verification
and pass them to your preferred download manager.

This is what the mkvdrama.net "How to Download" page recommends.

### Option 2: Manual browser
Open each ouo.io link in a regular browser, complete the "I'm a human"
verification, then download from the chosen file host (Mega, Gofile,
Send.cm, Pixeldrain).

### Option 3: FlareSolverr (Advanced)
For automated resolution, [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)
is a Docker-based service that runs a full browser to solve Cloudflare
challenges. The [sootio](https://github.com/iceblinker/sootio) project
uses this for ouo.io resolution.

### Option 4: ouo.io Premium
ouo.io offers a paid API that provides direct links without verification.

## Notes

- The mkvdrama.net site uses Cloudflare protection. The tool uses
  `cloudscraper` (TLS fingerprint impersonation) to bypass it.
- ouo.io/oii.la shorteners use Cloudflare Turnstile challenges that
  cannot be bypassed with simple HTTP requests — they need a real
  browser or JDownloader2.
