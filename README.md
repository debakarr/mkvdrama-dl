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

## Notes

- This tool scrapes download links (via ouo.io/filecrypt shorteners).
- For Cloudflare bypass, set the `MKVDRAMA_COOKIE` environment variable.
