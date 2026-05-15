"""URL shortener resolver for ouo.io / oii.la links.

Uses Playwright to automate browser-based verification (Turnstile) and
extract the final redirect URL from ouo.io and oii.la shorteners.

Optional dependency: pip install mkvdrama-downloader[resolve]
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SHORTENER_DOMAINS = ["ouo.io", "oii.la", "ouo.press"]


def _check_playwright() -> None:
    """Check if playwright is available, raise ImportError if not."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        msg = (
            "Playwright is required for shortener resolution. Install it with: pip install mkvdrama-downloader[resolve]"
        )
        raise ImportError(msg) from None


def is_shortener_url(url: str) -> bool:
    """Check if a URL is from a supported shortener domain."""
    parsed = urlparse(url)
    return any(domain in parsed.netloc for domain in SHORTENER_DOMAINS)


class ShortenerResolver:
    """Resolves ouo.io/oii.la shortener URLs to their final destination.

    Uses Playwright to handle Turnstile verification and button clicks.
    The browser instance is shared across multiple resolutions.
    """

    _browser = None
    _playwright = None
    _launched = False

    @classmethod
    async def _get_browser(cls):
        """Get or create the shared Playwright browser instance."""
        _check_playwright()
        from playwright.async_api import async_playwright

        if cls._browser is None and not cls._launched:
            cls._launched = True
            cls._playwright = await async_playwright().start()
            cls._browser = await cls._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
        return cls._browser

    @classmethod
    async def resolve_url(cls, url: str, timeout: int = 30) -> str:
        """Resolve a ouo.io/oii.la URL to its final destination.

        Opens the URL in a headless browser, waits for the verification
        to complete, and captures the redirect URL.

        Args:
            url: The ouo.io/oii.la shortener URL.
            timeout: Maximum time in seconds to wait for resolution.

        Returns:
            The final destination URL, or the original URL if resolution fails.
        """
        if not is_shortener_url(url):
            return url

        try:
            browser = await cls._get_browser()
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            resolved_url = await cls._resolve_page(page, url, timeout)
            await context.close()
            return resolved_url
        except Exception as e:
            logger.warning("Shortener resolution failed for %s: %s", url, e)
            return url

    @classmethod
    async def resolve_many(
        cls,
        urls: list[str],
        timeout: int = 30,
        max_concurrent: int = 3,
    ) -> dict[str, str]:
        """Resolve multiple shortener URLs concurrently.

        Args:
            urls: List of shortener URLs to resolve.
            timeout: Maximum time per URL in seconds.
            max_concurrent: Maximum number of concurrent resolutions.

        Returns:
            Dictionary mapping original URLs to resolved URLs.
        """
        results: dict[str, str] = {}
        semaphore = asyncio.Semaphore(max_concurrent)

        async def resolve_one(url: str) -> tuple[str, str]:
            async with semaphore:
                resolved = await cls.resolve_url(url, timeout)
                return url, resolved

        tasks = [resolve_one(url) for url in urls if is_shortener_url(url)]
        if not tasks:
            return {}

        for coro in asyncio.as_completed(tasks):
            original, resolved = await coro
            results[original] = resolved

        return results

    @classmethod
    async def _resolve_page(cls, page, url: str, timeout: int) -> str:
        """Open a shortener page and wait for the redirect."""
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        redirect_url: str | None = None

        async def on_response(response):
            nonlocal redirect_url
            if response.status in (301, 302, 303, 307, 308):
                loc = response.headers.get("location")
                if loc and not is_shortener_url(loc):
                    redirect_url = loc

        page.on("response", on_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)

            deadline = time.time() + timeout
            clicked = False

            while time.time() < deadline:
                if page.url != url and not is_shortener_url(page.url):
                    return page.url
                if redirect_url:
                    return redirect_url

                if not clicked:
                    btn = await page.query_selector("#btn-main")
                    if btn:
                        disabled = await btn.get_attribute("disabled")
                        if disabled is None:
                            await btn.click()
                            clicked = True
                            logger.debug("Clicked ouo.io button for %s", url)

                await page.wait_for_timeout(500)

            return redirect_url or page.url

        except PlaywrightTimeout:
            logger.debug("Timeout resolving %s", url)
            return redirect_url or page.url
        except Exception as e:
            logger.debug("Error resolving %s: %s", url, e)
            return redirect_url or page.url
        finally:
            page.remove_listener("response", on_response)

    @classmethod
    async def cleanup(cls) -> None:
        """Close the shared browser instance."""
        if cls._browser:
            await cls._browser.close()
            cls._browser = None
        if cls._playwright:
            await cls._playwright.stop()
            cls._playwright = None
        cls._launched = False


# --- Synchronous wrappers ---


def _run_async(coro):
    """Run an async coroutine synchronously."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # If there's already a running loop, create a new one in a thread
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


def resolve_shortener_url(url: str, timeout: int = 30) -> str:
    """Synchronous wrapper for ShortenerResolver.resolve_url."""
    return _run_async(ShortenerResolver.resolve_url(url, timeout))


def resolve_shortener_urls(
    urls: list[str],
    timeout: int = 30,
    max_concurrent: int = 3,
) -> dict[str, str]:
    """Synchronous wrapper for ShortenerResolver.resolve_many."""
    return _run_async(ShortenerResolver.resolve_many(urls, timeout, max_concurrent))


def cleanup_shortener() -> None:
    """Synchronous wrapper for ShortenerResolver.cleanup."""
    try:
        _run_async(ShortenerResolver.cleanup())
    except Exception:
        pass
