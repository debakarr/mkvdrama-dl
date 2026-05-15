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
import sys  # noqa: F401 - used in closures for stdout flushing
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


def _resolve_with_page(page, url: str, timeout: int, status=None) -> str | None:
    """Resolve a single ouo.io URL using an existing Playwright page.

    Args:
        page: Playwright page object.
        url: URL to resolve.
        timeout: Max seconds.
        status: Optional function(msg) called at each step to show progress.
    """

    def _status(msg):
        if status:
            status(msg)
        else:
            logger.debug(msg)

    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    _status("Loading page...")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        logger.debug("Page load failed for %s: %s", url, e)
        return None

    max_steps = 2
    for _step in range(max_steps):
        current = page.url
        if not _is_ouo_domain(current):
            return current

        if "oii.la" in current:
            # oii.la: blog page with Turnstile + "Continue" button
            try:
                # Remove overlays, then wait for and click any post-captcha button
                page.evaluate("""
                    document.querySelectorAll('iframe').forEach(el => el.remove());
                    document.querySelectorAll('div[data-shb]').forEach(el => el.remove());
                """)
                btn = page.wait_for_selector(
                    "button:has-text('Continue'), a:has-text('Continue')",
                    timeout=20000,
                )
                if btn:
                    btn.evaluate("el => el.click()")
                    try:
                        page.wait_for_function(
                            f"() => window.location.href !== '{current}'",
                            timeout=15000,
                        )
                    except PlaywrightTimeout:
                        pass
                    continue
            except PlaywrightTimeout:
                pass
        else:
            # ouo.io / ouo.press: countdown + "Get Link" button
            _status("Waiting for countdown...")
            # Random mouse movements
            for _ in range(random.randint(2, 3)):
                page.mouse.move(random.randint(100, 1100), random.randint(100, 600))
                time.sleep(random.uniform(0.05, 0.1))

            # Wait for button to become active
            _status("Waiting for button...")
            try:
                page.wait_for_selector("#btn-main:not([disabled])", timeout=12000)
            except PlaywrightTimeout:
                pass

            _status("Clicking button...")
            # Remove overlays and click
            _remove_overlays_and_click(page)

            # Wait for navigation
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
    if not _is_ouo_domain(final):
        return final

    # Last resort: scan page for target links
    links = page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => e.href)",
    )
    for link in links:
        if not _is_ouo_domain(link):
            return link
    return None


def resolve_ouo_url(url: str, timeout: int = 60) -> str | None:
    """Resolve a single ouo.io URL using Playwright (opens own browser)."""
    _check_playwright()
    from playwright.sync_api import sync_playwright

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
            return _resolve_with_page(page, url, timeout)
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Batch resolution
# ---------------------------------------------------------------------------


def resolve_shorteners(
    urls: list[str],
    timeout: int = 60,
) -> dict[str, str]:
    """Resolve multiple shortener URLs sequentially using a shared Playwright browser.

    Falls back to FlareSolverr if configured and Playwright is unavailable.

    Args:
        urls: List of shortener URLs.
        timeout: Max seconds per URL.

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
        total = len(urls)
        import signal

        interrupted = False

        def _handle_sigint(signum, frame):
            nonlocal interrupted
            if not interrupted:
                print("\n    Interrupted. Cleaning up...")
                interrupted = True

        original_sigint = signal.signal(signal.SIGINT, _handle_sigint)

        print(f"\n  Resolving {total} shortener URL(s) with Playwright...")
        sys.stdout.flush()

        from playwright.sync_api import sync_playwright

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

            done = 0
            for url in urls:
                if interrupted:
                    print("    Skipping remaining URLs.")
                    for remaining_url in urls[done:]:
                        results[remaining_url] = remaining_url
                    break

                # Skip oii.la links — complex multi-page redirect chain
                if "oii.la" in url:
                    short_id = url.rstrip("/").rsplit("/", 1)[-1][:25]
                    print(f"    [{done + 1}/{total}] {short_id}... SKIP (oii.la not supported)")
                    results[url] = url
                    done += 1
                    sys.stdout.flush()
                    continue

                short_id = url.rstrip("/").rsplit("/", 1)[-1][:25]
                prefix = f"    [{done + 1}/{total}] {short_id}"
                print(f"{prefix}  Starting...", end="")
                sys.stdout.flush()

                def step_status(msg, _p=prefix):
                    # Use \r to overwrite the current line with updated status
                    print(f"\r{_p}  {msg}", end="")
                    sys.stdout.flush()

                page = context.new_page()
                try:
                    resolved = _resolve_with_page(page, url, timeout, status=step_status)
                except KeyboardInterrupt:
                    resolved = None
                    interrupted = True
                page.close()
                result_url = resolved or url
                results[url] = result_url
                done += 1
                status_sym = "OK" if resolved else "SKIP"
                display = result_url[:70] if resolved else "unchanged"
                # Clear line with spaces then print final result
                print(f"\r{prefix}  {status_sym} -> {display}")
                sys.stdout.flush()
                if not resolved:
                    remaining.append(url)

            context.close()
            browser.close()

        signal.signal(signal.SIGINT, original_sigint)

        if interrupted:
            print("  Resolution cancelled.")
            return results

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
