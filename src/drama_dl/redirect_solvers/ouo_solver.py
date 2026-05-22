"""Solver for ouo.io shortener with countdown + button click flow.

Flow:
1. Navigate to ouo.io/xyz
2. Wait for countdown to finish (~25 seconds) by monitoring button text
3. Click "I'm a human" / "Continue" button (#btn-main)
4. Wait for redirect to final destination
5. If still on ouo.io (e.g. /go/ page), repeat from step 2

Note: #btn-main is an <a> tag, not a <button>, so the ``disabled``
attribute is never set. We detect countdown completion by checking
when the button text stops showing a number and reads like "I'm a human".
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Callable

from drama_dl.redirect_solvers.base import RedirectSolver

logger = logging.getLogger(__name__)

# Text patterns indicating the countdown is still running
_COUNTDOWN_PATTERN = re.compile(r"^\d+$")

# Text indicating a button is ready to click
_READY_PATTERNS = [
    "human",
    "continue",
    "get link",
    "proceed",
    "verify",
    "submit",
    "go",
]


class OuoSolver(RedirectSolver):
    """Solver for ouo.io shortener URLs with automatic retries."""

    MAX_ATTEMPTS = 3
    RETRY_DELAY_S = 2

    @property
    def name(self) -> str:
        return "ouo.io solver"

    @property
    def domains(self) -> list[str]:
        return ["ouo.io", "ouo.press"]

    async def resolve(
        self,
        page,
        url: str,
        status: Callable[[str], None] | None = None,
    ) -> str | None:
        """Resolve ouo.io URL with retries.

        The redirect chain (form submit → countdown → button click) can be
        flaky — the page may time out or the countdown widget might not
        initialise.  We retry up to ``MAX_ATTEMPTS`` times with a fresh
        navigation each time.
        """

        def _status(msg: str) -> None:
            if status:
                status(msg)
            else:
                logger.debug(msg)

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            if attempt > 1:
                _status(f"Retry {attempt}/{self.MAX_ATTEMPTS}...")
                # Navigate to blank so the next goto starts fresh
                try:
                    await page.goto("about:blank", timeout=5000)
                except Exception:
                    pass
                await asyncio.sleep(self.RETRY_DELAY_S)

            result = await self._resolve_once(page, url, _status)
            if result is not None and result != url:
                return result

        return None

    async def _resolve_once(
        self,
        page,
        url: str,
        _status: Callable[[str], None],
    ) -> str | None:
        """Single attempt at resolving an ouo.io URL.

        Strategy:
        1. Try submitting any form on the page first (fast path from AdsBypasser) —
           this POSTs the shortener data and triggers a redirect past the first page.
        2. On the /go/ page, wait for the button text to indicate countdown is
           finished (``#btn-main`` text changes from a number to "I'm a human").
        3. Click the button to reach the final destination.
        """
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        # Navigate to URL
        _status("Loading page...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            logger.debug("Page load failed: %s", e)
            return None

        # Maximum iterations to prevent infinite loops
        max_iterations = 5
        visited_urls: set[str] = set()

        for iteration in range(max_iterations):
            current = page.url

            # Not a shortener anymore — we're done
            if not self.can_handle(current):
                return current

            # Detect loops
            if current in visited_urls:
                _status(f"Loop detected at {current}")
                break
            visited_urls.add(current)

            _status(f"Iteration {iteration + 1}: Waiting for countdown...")

            # Human-like mouse movement
            for _ in range(random.randint(2, 3)):
                await page.mouse.move(
                    random.randint(100, 1100),
                    random.randint(100, 600),
                )
                await asyncio.sleep(random.uniform(0.05, 0.1))

            # Also try submitting any form first (fast path used by AdsBypasser)
            form_submitted = await page.evaluate("""() => {
                const form = document.querySelector('form');
                if (form && form.action && !form.action.includes('javascript')) {
                    const btn = form.querySelector('button, input[type="submit"]');
                    if (btn && !btn.disabled) { btn.click(); return true; }
                    form.submit(); return true;
                }
                return false;
            }""")
            if form_submitted:
                _status("Form submitted, waiting for redirect...")
                try:
                    await page.wait_for_function(
                        f"() => window.location.href !== '{current}'",
                        timeout=15000,
                    )
                    await asyncio.sleep(1)
                    continue  # Re-check the URL in next iteration
                except PlaywrightTimeout:
                    _status("No redirect from form submit")

            # Wait for the button to be ready (countdown finished).
            _status("Waiting for countdown to finish...")
            try:
                await page.wait_for_function(
                    """() => {
                        const btn = document.querySelector('#btn-main');
                        if (!btn) return false;
                        const text = (btn.textContent || '').trim().toLowerCase();
                        // Button is ready when text is NOT a bare number
                        if (/^\\d+$/.test(text)) return false;
                        // Also make sure it doesn't just say "wait" or "second"
                        if (text.includes('wait') || text.includes('second')) return false;
                        return text.length > 0;
                    }""",
                    timeout=45000,  # ouo.io has ~25s countdown
                )
            except PlaywrightTimeout:
                _status("Countdown timeout, trying button anyway...")

            # Click the button with human-like behavior
            btn = await page.query_selector("#btn-main")
            if btn and await btn.is_visible():
                _status("Clicking button...")
                box = await btn.bounding_box()
                if box:
                    await page.mouse.move(
                        int(box["x"] + box["width"] / 2),
                        int(box["y"] + box["height"] / 2),
                    )
                    await asyncio.sleep(random.uniform(0.1, 0.3))

                await btn.evaluate("el => { el.click(); el.dispatchEvent(new MouseEvent('click', {bubbles: true})); }")

                # Wait for navigation
                _status("Following redirect...")
                try:
                    await page.wait_for_function(
                        f"() => window.location.href !== '{current}'",
                        timeout=20000,
                    )
                    await asyncio.sleep(1.5)
                except PlaywrightTimeout:
                    _status("Navigation timeout")
            else:
                _status("No button found, scanning for links...")
                links = await _scan_for_links(page)
                if links:
                    return links[0]
                break

        # Final check
        final = page.url
        if not self.can_handle(final):
            return final

        # Last resort: scan for links
        links = await _scan_for_links(page)
        if links:
            return links[0]

        return None


async def _scan_for_links(page) -> list[str]:
    """Scan page for external links not pointing to ouo.io."""
    return await page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href]'))
            .map(a => a.href)
            .filter(h => !h.includes('ouo.io') && !h.includes('ouo.press') && !h.startsWith('javascript'));
    }""")
