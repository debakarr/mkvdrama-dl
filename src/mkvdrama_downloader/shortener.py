"""URL shortener resolver for ouo.io / oii.la links.

Supports:
- Detection of shortener URLs
- Automatic resolution via Playwright with stealth techniques
- Optional FlareSolverr fallback

Playwright requirement: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import logging
import os
import random  # noqa: S311 - used for human mouse simulation, not crypto
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SHORTENER_DOMAINS = ["ouo.io", "oii.la", "ouo.press"]

FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "").rstrip("/") or ""


def is_shortener_url(url: str) -> bool:
    """Check if a URL is from a supported shortener domain."""
    parsed = urlparse(url)
    return any(domain in parsed.netloc for domain in SHORTENER_DOMAINS)


def _check_playwright() -> None:
    """Check if playwright is available."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        msg = (
            "Playwright is required for ouo.io resolution. "
            "Install: pip install playwright && playwright install chromium"
        )
        raise ImportError(msg) from None


# ---------------------------------------------------------------------------
# Playwright-based ouo.io bypass with stealth techniques
# ---------------------------------------------------------------------------


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


def _remove_overlays_and_click(page) -> bool:
    """Remove overlay iframes and click the verification button."""
    # Remove all iframes and overlay divs
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

    button_selectors = [
        "#btn-main",
        'button:has-text("I\'m human")',
        "button:has-text('I am human')",
        "button:has-text('Verify')",
        "button:has-text('Continue')",
        "form button[type='submit']",
        "input[type='submit']",
    ]

    from playwright.sync_api import TimeoutError as PlaywrightTimeout

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


def _is_ouo_domain(url: str) -> bool:
    """Check if URL is still on a shortener domain."""
    return is_shortener_url(url)


def resolve_ouo_url(url: str, timeout: int = 60) -> str | None:
    """Resolve a ouo.io / oii.la / ouo.press URL using Playwright.

    Uses a real browser with stealth techniques (human-like mouse movements,
    overlay removal, multi-step follow) to automate ouo.io verification.

    Args:
        url: The shortener URL.
        timeout: Max seconds per URL.

    Returns:
        Final destination URL, or None if failed.
    """
    _check_playwright()
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    logger.debug("Resolving ouo.io: %s", url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
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
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)

            max_steps = 5
            for step in range(max_steps):
                current = page.url
                logger.debug("Step %s: %s", step + 1, current)

                if not _is_ouo_domain(current):
                    logger.debug("Resolved: %s", current)
                    return current

                # Random mouse movements before interacting
                for _ in range(random.randint(3, 5)):
                    page.mouse.move(
                        random.randint(100, 1100),
                        random.randint(100, 600),
                    )
                    time.sleep(random.uniform(0.1, 0.3))

                # Wait for countdown timer
                time.sleep(10)

                # Remove overlays and click
                clicked = _remove_overlays_and_click(page)
                if not clicked:
                    logger.debug("No button found at step %s", step + 1)

                # Wait for navigation
                try:
                    page.wait_for_function(
                        f"() => window.location.href !== '{current}'",
                        timeout=timeout * 1000,
                    )
                except PlaywrightTimeout:
                    logger.debug("No navigation at step %s", step + 1)

                time.sleep(1)

            # After all steps, check final URL
            final_url = page.url
            if not _is_ouo_domain(final_url):
                logger.debug("Resolved: %s", final_url)
                return final_url

            # Last resort: scan page for target links
            links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href)",
            )
            for link in links:
                if not _is_ouo_domain(link):
                    logger.debug("Found target link: %s", link)
                    return link

            logger.debug("Failed to resolve after %s steps", max_steps)
            return None

        except Exception as e:
            logger.debug("ouo.io resolution error: %s", e)
            return None
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Batch resolution
# ---------------------------------------------------------------------------


def resolve_shorteners(
    urls: list[str],
    timeout: int = 60,
    max_workers: int = 2,
) -> dict[str, str]:
    """Resolve multiple shortener URLs.

    Uses Playwright-based bypass. Falls back to FlareSolverr if configured.

    Args:
        urls: List of shortener URLs.
        timeout: Max seconds per URL.
        max_workers: Max concurrent resolutions (each needs its own browser).

    Returns:
        Dict mapping original URLs to resolved URLs.
    """
    if not urls:
        return {}

    results: dict[str, str] = {}
    remaining: list[str] = []

    # Try Playwright first
    try:
        _check_playwright()
        logger.info("Resolving %d URLs with Playwright...", len(urls))
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def resolve_one(short_url: str) -> tuple[str, str]:
            resolved = resolve_ouo_url(short_url, timeout)
            return short_url, resolved or short_url

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(resolve_one, u): u for u in urls}
            for future in as_completed(futures):
                original, resolved = future.result()
                results[original] = resolved
                if resolved == original:
                    remaining.append(original)

    except ImportError as e:
        logger.info("Playwright not available: %s", e)
        remaining = urls

    # Try FlareSolverr fallback for unresolved URLs
    if remaining and FLARESOLVERR_URL:
        logger.info("Falling back to FlareSolverr for %d URLs...", len(remaining))
        for url in remaining:
            fs_resolved = resolve_via_flaresolverr(url, timeout)
            results[url] = url if fs_resolved is None else fs_resolved

    # Mark unresolvable URLs
    for url in urls:
        results.setdefault(url, url)

    resolved_count = sum(1 for o, r in results.items() if r != o)
    logger.info("Resolved %d/%d URLs", resolved_count, len(urls))
    return results


# ---------------------------------------------------------------------------
# FlareSolverr fallback
# ---------------------------------------------------------------------------


def is_flaresolverr_configured() -> bool:
    """Check if FlareSolverr is configured."""
    return bool(FLARESOLVERR_URL)


def resolve_via_flaresolverr(url: str, timeout: int = 30) -> str | None:
    """Resolve via FlareSolverr (fallback when Playwright is unavailable)."""
    if not FLARESOLVERR_URL:
        return None

    import requests as std_requests

    try:
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": timeout * 1000,
        }
        resp = std_requests.post(
            f"{FLARESOLVERR_URL}/v1",
            json=payload,
            timeout=timeout + 5,
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
