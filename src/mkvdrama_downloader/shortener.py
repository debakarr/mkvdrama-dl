"""URL shortener helpers for ouo.io / oii.la links.

Note: ouo.io/oii.la use Cloudflare JS challenges that cannot be bypassed
programmatically. These links work with JDownloader2 or a regular browser.
"""

from __future__ import annotations

from urllib.parse import urlparse

SHORTENER_DOMAINS = ["ouo.io", "oii.la", "ouo.press"]


def is_shortener_url(url: str) -> bool:
    """Check if a URL is from a supported shortener domain."""
    parsed = urlparse(url)
    return any(domain in parsed.netloc for domain in SHORTENER_DOMAINS)
