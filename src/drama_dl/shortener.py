"""URL shortener resolver for ouo.io / oii.la / exe.io / cutw.in links.

Supports:
- Detection of shortener URLs
- Automatic resolution via Playwright with stealth techniques
- Optional FlareSolverr fallback
- Strategy pattern for swappable resolvers
- exe.io /full/ base64-encoded direct URL decoding

Playwright requirement: ``pip install playwright && playwright install chromium``
"""

from __future__ import annotations

import base64
import json
import logging
import os
import random  # noqa: S311 — human mouse simulation, not crypto
import re
import sys
import time
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

import cloudscraper
import requests as std_requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

SHORTENER_DOMAINS = ["ouo.io", "oii.la", "ouo.press", "exe.io", "cutw.in"]
FILECRYPT_DOMAIN = "filecrypt.cc"

FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "").rstrip("/") or ""


# ═══════════════════════════════════════════════════════════════════════
# Helper predicates
# ═══════════════════════════════════════════════════════════════════════


def is_shortener_url(url: str) -> bool:
    """Check if a URL is from a supported shortener domain."""
    parsed = urlparse(url)
    return any(domain in parsed.netloc for domain in SHORTENER_DOMAINS)


def is_filecrypt_url(url: str) -> bool:
    """Check if a URL is a filecrypt.cc container page."""
    return FILECRYPT_DOMAIN in url and "/Container/" in url


def is_flaresolverr_configured() -> bool:
    """Check if FlareSolverr is configured (via env or previous CLI flag)."""
    return bool(FLARESOLVERR_URL)


def resolve_exe_full(url: str) -> str | None:
    """Resolve exe.io/full/?api=...&url=BASE64&type=2 to direct URL.

    The /full/ endpoint returns a base64-encoded redirect URL in the ``url``
    query parameter.  Decoding it yields the final destination directly,
    avoiding the need for Playwright.
    """
    parsed = urlparse(url)
    if parsed.path.startswith("/full/"):
        qs = parse_qs(parsed.query)
        if "url" in qs:
            try:
                return base64.b64decode(qs["url"][0]).decode("utf-8")
            except Exception:
                pass
    return None


# ═══════════════════════════════════════════════════════════════════════
# Filecrypt extractor — pulls download entries from a container page
# ═══════════════════════════════════════════════════════════════════════


def extract_filecrypt_links(url: str) -> list[dict[str, Any]]:
    """Fetch a filecrypt.cc container page and extract download entries.

    Returns a list of dicts with keys: host, filename, size, online, link_url.
    Also attempts DLC + dcrypt.it extraction for direct download links.
    """
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False},
    )

    try:
        resp = scraper.get(url, timeout=20)
        if resp.status_code != 200:
            logger.warning("Filecrypt fetch failed: %d", resp.status_code)
            return []
    except Exception as e:
        logger.warning("Filecrypt request failed: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    entries: list[dict[str, Any]] = []

    def _tag_attr(el: Tag, attr: str, default: str = "") -> str:
        val = el.get(attr)
        return str(val) if val else default

    for row in soup.select("tr.kwj3"):
        if not isinstance(row, Tag):
            continue
        btn = row.select_one("button.download")
        if not isinstance(btn, Tag):
            continue

        btn_id = _tag_attr(btn, "id")
        if not btn_id:
            continue

        data_attr = f"data-{btn_id.lower()}"
        link_id = _tag_attr(btn, data_attr) or _tag_attr(btn, "value")
        if not link_id:
            continue

        host_el = row.select_one("a.external_link")
        host = _tag_attr(host_el, "href") if isinstance(host_el, Tag) else ""

        title_cell = row.select_one("td[title]")
        filename = _tag_attr(title_cell, "title") if isinstance(title_cell, Tag) else ""

        size = ""
        for cell in row.select("td"):
            if isinstance(cell, Tag):
                text = cell.get_text(strip=True)
                if re.match(r"^\d+(\.\d+)?\s*(GB|MB|KB|TB)$", text, re.IGNORECASE):
                    size = text
                    break

        is_online = row.select_one("i.online") is not None

        entries.append(
            {
                "host": host,
                "filename": filename,
                "size": size,
                "online": "online" if is_online else "offline",
                "link_url": f"https://{FILECRYPT_DOMAIN}/Link/{link_id}.html",
            }
        )

    # Try DLC + dcrypt.it for direct download links
    _try_dcrypt_extraction(scraper, soup, entries)

    return entries


def _try_dcrypt_extraction(
    scraper: cloudscraper.CloudScraper,
    soup: BeautifulSoup,
    entries: list[dict[str, Any]],
) -> None:
    """Attempt DLC download + dcrypt.it decryption as a side channel."""
    try:
        dlc_btn = soup.select_one("button.dlcdownload")
        if not dlc_btn:
            return

        onclick = dlc_btn.get("onclick", "")
        if isinstance(onclick, list):
            onclick = " ".join(onclick)
        m = re.search(r"getAttribute\('([^']+)'\)", onclick or "")
        if not m:
            return

        attr_name = m.group(1).lower()
        dlc_id = ""
        for k, v in dlc_btn.attrs.items():
            if k.lower() == attr_name:
                dlc_id = v if isinstance(v, str) else (v[0] if isinstance(v, list) else "")
                break
        if not dlc_id:
            return

        dlc_url = f"https://{FILECRYPT_DOMAIN}/DLC/{dlc_id}.dlc"
        dlc_resp = scraper.get(dlc_url, timeout=15)
        if dlc_resp.status_code != 200 or len(dlc_resp.text) < 100:
            return

        dcrypt_resp = scraper.post(
            "http://dcrypt.it/decrypt/paste",
            data={"content": dlc_resp.text},
            timeout=15,
        )
        if dcrypt_resp.status_code != 200:
            return

        dcrypt_data = json.loads(dcrypt_resp.text)
        dcrypt_links = dcrypt_data.get("success", {}).get("links", [])
        if dcrypt_links:
            entries.append(
                {
                    "host": "dcrypt.it",
                    "filename": f"{len(dcrypt_links)} direct links",
                    "size": "",
                    "online": "online",
                    "link_url": "",
                    "dcrypt_links": dcrypt_links,
                }
            )
    except Exception as e:
        logger.debug("DLC/dcrypt.it extraction failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════
# Strategy pattern — swappable URL resolvers
# ═══════════════════════════════════════════════════════════════════════


class ResolverStrategy(Protocol):
    """Protocol for a shortener URL resolution strategy.

    Each strategy receives a single URL and an optional status callback,
    and returns the resolved URL, or ``None`` if it could not resolve it.
    """

    def __call__(self, url: str, /, status: Callable[[str], None] | None = None) -> str | None:
        """Resolve *url* and return the final destination, or ``None``.

        Args:
            url: The shortener URL to resolve.
            status: Optional callback invoked with progress messages (e.g.
                    ``"Loading page…"``) that the caller can display.
        """
        ...


class NullResolver:
    """Strategy that passes URLs through unchanged.

    Used when resolution is not requested (*--resolve* not set).
    This is the **Null Object** pattern — avoids ``if`` checks everywhere.
    """

    def __call__(self, url: str, /, status: Callable[[str], None] | None = None) -> str | None:
        return url


class FlareSolverrResolver:
    """Strategy that resolves URLs via the FlareSolverr API.

    Useful as a fallback when Playwright is unavailable.
    """

    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint.rstrip("/")

    def __call__(self, url: str, /, status: Callable[[str], None] | None = None) -> str | None:
        try:
            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60_000,
            }
            resp = std_requests.post(
                f"{self._endpoint}/v1",
                json=payload,
                timeout=65,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            solution = data.get("solution", {})
            response_text = solution.get("response", "")
            if "Just a moment" in response_text or "cf-browser-verification" in response_text:
                return None

            return solution.get("url", "") or url
        except Exception as e:
            logger.debug("FlareSolverr failed: %s", e)
            return None


class CompositeResolver:
    """Chain-of-responsibility resolver.

    Tries each strategy in order and returns the first successful result.
    If all fail, returns ``None``.
    """

    def __init__(self, strategies: list[ResolverStrategy]) -> None:
        self._strategies = strategies

    def __call__(self, url: str, /, status: Callable[[str], None] | None = None) -> str | None:
        for strategy in self._strategies:
            result = strategy(url)
            if result is not None and result != url:
                return result
        return None

    def __or__(self, other: ResolverStrategy) -> CompositeResolver:
        """Combine two resolvers with the ``|`` operator."""
        if isinstance(other, CompositeResolver):
            return CompositeResolver(self._strategies + other._strategies)
        return CompositeResolver(self._strategies + [other])

    def __repr__(self) -> str:
        return f"CompositeResolver({self._strategies!r})"


# ═══════════════════════════════════════════════════════════════════════
# Public entry point — builds the resolver chain and runs it
# ═══════════════════════════════════════════════════════════════════════


def _check_playwright() -> None:
    """Check if playwright is available, raise helpful error otherwise."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        msg = (
            "Playwright is required for shortener resolution. "
            "Install: pip install playwright && playwright install chromium"
        )
        raise ImportError(msg) from None


def resolve_shorteners(
    urls: list[str],
    timeout: int = 60,
) -> dict[str, str]:
    """Resolve multiple shortener URLs using a shared Playwright browser.

    Falls back to FlareSolverr if configured and Playwright is unavailable.
    Handles exe.io /full/ base64 URLs directly without Playwright.

    Args:
        urls: List of shortener URLs to resolve.
        timeout: Max seconds per URL (unused in this revision, kept for compat).

    Returns:
        Dict mapping original URLs to resolved URLs.
    """
    if not urls:
        return {}

    results: dict[str, str] = {}

    # Pre-resolve exe.io /full/ URLs (base64-encoded, no browser needed)
    pre_resolved: dict[str, str] = {}
    remaining: list[str] = []
    for url in urls:
        direct = resolve_exe_full(url)
        if direct:
            pre_resolved[url] = direct
        else:
            remaining.append(url)

    results.update(pre_resolved)

    if not remaining:
        return results

    # Build the strategy chain for remaining URLs
    if _has_playwright():
        strategy: ResolverStrategy = _PlaywrightResolver()
        if FLARESOLVERR_URL:
            strategy = CompositeResolver([strategy, FlareSolverrResolver(FLARESOLVERR_URL)])
    elif FLARESOLVERR_URL:
        strategy = FlareSolverrResolver(FLARESOLVERR_URL)
    else:
        logger.info("No resolver available — shortener URLs will not be resolved.")
        return {**results, **{u: u for u in remaining}}

    total = len(remaining)
    print(f"\n  Resolving {total} shortener URL(s)...")
    sys.stdout.flush()

    for idx, url in enumerate(remaining):
        # Show full URL (truncate to 60 chars for display)
        display_url = url if len(url) <= 60 else url[:57] + "..."
        prefix = f"    [{idx + 1}/{total}] {display_url}"

        def step_status(msg: str, _p: str = prefix) -> None:
            """Overwrite the current line with updated progress."""
            print(f"\r{_p}  {msg}", end="")
            sys.stdout.flush()

        print(f"{prefix}  Starting...", end="")
        sys.stdout.flush()

        resolved = strategy(url, status=step_status)
        result_url = resolved or url
        results[url] = result_url

        status_sym = "OK" if resolved else "SKIP"
        display = result_url[:70] if resolved else "unchanged"
        print(f"\r{prefix}  {status_sym} -> {display}")
        sys.stdout.flush()

        if resolved and is_filecrypt_url(resolved):
            _display_filecrypt_entries(prefix, resolved)

    resolved_count = sum(1 for o, r in results.items() if r != o)
    logger.info("Resolved %d/%d URLs", resolved_count, len(urls))
    return results


def _has_playwright() -> bool:
    """Return ``True`` if Playwright can be imported."""
    try:
        _check_playwright()
        return True
    except ImportError:
        return False


# ═══════════════════════════════════════════════════════════════════════
# Playwright-based shortener resolver
# ═══════════════════════════════════════════════════════════════════════


class _PlaywrightResolver:
    """Strategy that resolves shortener URLs using Playwright with stealth."""

    def __call__(self, url: str, /, status: Callable[[str], None] | None = None) -> str | None:
        _check_playwright()
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
                )
                context = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/148.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                try:
                    result = _resolve_with_page(page, url, status=status)
                finally:
                    page.close()
                    context.close()
                    browser.close()
                return result
        except KeyboardInterrupt:
            print("\n    Interrupted. Cleaning up...")
            return None


# ---------------------------------------------------------------------------
# Playwright page-level helpers
# ---------------------------------------------------------------------------


def _resolve_with_page(page, url: str, status=None) -> str | None:
    """Resolve a single shortener URL using an existing Playwright page.

    Args:
        page: Playwright page object.
        url: URL to resolve.
        status: Optional ``fn(msg)`` called at each step for progress.
    """

    def _status(msg):
        if status:
            status(msg)
        else:
            logger.debug(msg)

    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    # Skip oii.la — complex multi-page redirect chain
    if "oii.la" in url:
        return None

    _status("Loading page...")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        logger.debug("Page load failed for %s: %s", url, e)
        return None

    max_steps = 2
    for _step in range(max_steps):
        current = page.url
        if not is_shortener_url(current):
            return current

        # ouo.io / ouo.press / cutw.in: countdown + "Get Link" button
        _status("Waiting for countdown...")
        for _ in range(random.randint(2, 3)):
            page.mouse.move(random.randint(100, 1100), random.randint(100, 600))
            time.sleep(random.uniform(0.05, 0.1))

        _status("Waiting for button...")
        try:
            page.wait_for_selector("#btn-main:not([disabled])", timeout=12000)
        except PlaywrightTimeout:
            pass

        _status("Clicking button...")
        _remove_overlays_and_click(page)

        _status("Following redirect...")
        try:
            page.wait_for_function(
                f"() => window.location.href !== '{current}'",
                timeout=10000,
            )
        except PlaywrightTimeout:
            pass
        time.sleep(0.5)

    # After all steps, check final URL
    final = page.url
    if not is_shortener_url(final):
        return final

    # Last resort: scan page for target links
    links = page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => e.href)",
    )
    for link in links:
        if not is_shortener_url(link):
            return link
    return None


def _remove_overlays_and_click(page) -> bool:
    """Remove overlay iframes and click the verification button."""
    removed = page.evaluate("""
        (() => {
            let count = 0;
            document.querySelectorAll('iframe').forEach(el => { el.remove(); count++; });
            document.querySelectorAll('div[data-shb]').forEach(el => { el.remove(); count++; });
            document.querySelectorAll('div').forEach(el => {
                const style = window.getComputedStyle(el);
                if ((style.position === 'fixed' || style.position === 'absolute') &&
                    parseInt(style.zIndex) > 100 &&
                    el.offsetWidth > 500 && el.offsetHeight > 300) {
                    el.remove(); count++;
                }
            });
            return count;
        })()
    """)
    logger.debug("Removed %s overlay(s)", removed)
    time.sleep(0.5)

    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    button_selectors = [
        "#btn-main",
        'button:has-text("I\'m human")',
        "button:has-text('I am human')",
        "button:has-text('Verify')",
        "button:has-text('Continue')",
        "form button[type='submit']",
        "input[type='submit']",
    ]

    for selector in button_selectors:
        try:
            btn = page.wait_for_selector(selector, timeout=3000)
            if btn and btn.is_visible():
                box = btn.bounding_box()
                if box:
                    _human_mouse_move(
                        page,
                        int(box["x"] + box["width"] / 2),
                        int(box["y"] + box["height"] / 2),
                    )
                btn.evaluate("el => el.click()")
                logger.debug("Clicked: %s", selector)
                return True
        except PlaywrightTimeout:
            continue

    # Fallback: JS form submit
    submitted = page.evaluate(
        "() => { const f = document.querySelector('form'); if (f) { f.submit(); return true; } return false; }"
    )
    if submitted:
        logger.debug("Submitted form via JS (fallback)")
        return True
    return False


def _human_mouse_move(page, target_x: int, target_y: int):
    """Move mouse to target with random waypoints to appear human."""
    vw = page.viewport_size["width"]
    vh = page.viewport_size["height"]

    x, y = random.randint(100, vw - 100), random.randint(100, vh - 100)
    page.mouse.move(x, y)

    waypoints = random.randint(2, 4)
    for _ in range(waypoints):
        x += random.randint(-100, 100) + (target_x - x) // (waypoints + 1)
        y += random.randint(-80, 80) + (target_y - y) // (waypoints + 1)
        x = max(10, min(vw - 10, x))
        y = max(10, min(vh - 10, y))
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.05, 0.2))

    page.mouse.move(target_x, target_y)
    time.sleep(random.uniform(0.1, 0.3))


# ═══════════════════════════════════════════════════════════════════════
# Filecrypt display helpers
# ═══════════════════════════════════════════════════════════════════════


def _display_filecrypt_entries(prefix: str, url: str) -> None:
    """Fetch filecrypt entries from a resolved URL and display them."""
    fc_entries = extract_filecrypt_links(url)
    if not fc_entries:
        print(f"    {' ' * len(prefix)}  Filecrypt blocked by Cloudflare — manual steps:")
        print(f"    {' ' * len(prefix)}    1. Open URL in browser, solve security check")
        print(f"    {' ' * len(prefix)}    2. Download the .dlc file from the page")
        print(f"    {' ' * len(prefix)}    3. Upload .dlc at https://dcrypt.it/ for direct links")
        print(f"    {' ' * len(prefix)}  Or use JDownloader2 — handles it automatically.")
        sys.stdout.flush()
        return

    # Show dcrypt.it links first (direct download links)
    dcrypt_entry = next((e for e in fc_entries if e.get("host") == "dcrypt.it"), None)
    if dcrypt_entry:
        dcrypt_links = dcrypt_entry.get("dcrypt_links", [])
        print(f"    {' ' * len(prefix)}  Direct download links (via dcrypt.it):")
        for dl in dcrypt_links[:6]:
            print(f"    {' ' * len(prefix)}    {dl}")
        if len(dcrypt_links) > 6:
            print(f"    {' ' * len(prefix)}    ... and {len(dcrypt_links) - 6} more")
        sys.stdout.flush()
        fc_entries = [e for e in fc_entries if e.get("host") != "dcrypt.it"]

    online = [e for e in fc_entries if e["online"] == "online"]
    shown: set[str] = set()
    for entry in online:
        host_short = entry["host"].replace("https://", "").replace("http://", "").split("/")[0]
        ep_match = re.search(r"S\d+E\d+", entry["filename"])
        ep_str = f" ({ep_match.group(0)})" if ep_match else ""
        key = f"{host_short}{ep_str}"
        if key in shown:
            continue
        shown.add(key)
        print(f"    {' ' * len(prefix)}  {host_short:20s} {entry['filename'][:55]}")
        if len(shown) >= 6:
            break
    if len(online) > 6:
        rest = len(online) - len(shown)
        print(f"    {' ' * len(prefix)}  ... ({rest} more host links)")
    sys.stdout.flush()
