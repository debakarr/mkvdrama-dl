"""URL shortener helpers for ouo.io / oii.la links.

Supports:
- Detection of shortener URLs
- Optional resolution via FlareSolverr (if configured)
"""

from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

SHORTENER_DOMAINS = ["ouo.io", "oii.la", "ouo.press"]

# FlareSolverr configuration
FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "").rstrip("/") or ""


def is_shortener_url(url: str) -> bool:
    """Check if a URL is from a supported shortener domain."""
    parsed = urlparse(url)
    return any(domain in parsed.netloc for domain in SHORTENER_DOMAINS)


def is_flaresolverr_configured() -> bool:
    """Check if FlareSolverr is configured."""
    return bool(FLARESOLVERR_URL)


def resolve_via_flaresolverr(url: str, timeout: int = 30) -> str | None:
    """Resolve a shortener URL using FlareSolverr.

    FlareSolverr opens the URL in a real headless browser that can handle
    Cloudflare JS challenges and Turnstile. It returns the final page content
    and the final URL after all redirects.

    Requires a running FlareSolverr instance. Configure via:
    - FLARESOLVERR_URL environment variable (e.g. http://localhost:8191)
    - Or pass directly via --flaresolverr flag

    Args:
        url: The shortener URL to resolve.
        timeout: Maximum time in seconds to wait.

    Returns:
        The final resolved URL, or None if resolution failed.
    """
    if not FLARESOLVERR_URL:
        logger.warning("FlareSolverr not configured. Set FLARESOLVERR_URL env var.")
        return None

    try:
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": timeout * 1000,
        }

        resp = requests.post(
            f"{FLARESOLVERR_URL}/v1",
            json=payload,
            timeout=timeout + 5,
        )

        if resp.status_code != 200:
            logger.warning("FlareSolverr returned status %d", resp.status_code)
            return None

        data = resp.json()
        solution = data.get("solution", {})

        # Check if still blocked
        response_text = solution.get("response", "")
        if "Just a moment" in response_text or "cf-browser-verification" in response_text:
            logger.warning("FlareSolverr could not bypass Cloudflare for %s", url)
            return None

        # Get the final URL after redirects
        final_url = solution.get("url", "") or url
        logger.debug("FlareSolverr resolved %s -> %s", url, final_url)
        return final_url

    except requests.RequestException as e:
        logger.warning("FlareSolverr request failed: %s", e)
        return None
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("FlareSolverr response parsing failed: %s", e)
        return None


def resolve_shorteners(
    urls: list[str],
    timeout: int = 30,
) -> dict[str, str]:
    """Resolve multiple shortener URLs using FlareSolverr.

    Args:
        urls: List of shortener URLs to resolve.
        timeout: Maximum time per URL in seconds.

    Returns:
        Dictionary mapping original URLs to resolved URLs.
        Unresolvable URLs are mapped to themselves.
    """
    if not urls:
        return {}

    if not FLARESOLVERR_URL:
        logger.info(
            "FlareSolverr not configured. Set FLARESOLVERR_URL to enable automatic shortener resolution.",
        )
        return {u: u for u in urls}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict[str, str] = {}

    def resolve_one(short_url: str) -> tuple[str, str]:
        resolved = resolve_via_flaresolverr(short_url, timeout)
        return short_url, resolved or short_url

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(resolve_one, u): u for u in urls}
        for future in as_completed(futures):
            original, resolved = future.result()
            results[original] = resolved

    return results
