"""Solver for ouo.io shortener with countdown + button click flow.

Flow:
1. Navigate to ouo.io/xyz
2. Wait for countdown (~25 seconds)
3. Click "I'm a human" button (#btn-main)
4. Wait for redirect to next ouo.io page
5. Repeat steps 2-4 (usually 2 iterations)
6. Final destination reached
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from drama_dl.redirect_solvers.base import RedirectSolver

logger = logging.getLogger(__name__)


class OuoSolver(RedirectSolver):
    """Solver for ouo.io shortener URLs."""

    @property
    def name(self) -> str:
        return "ouo.io solver"

    @property
    def domains(self) -> list[str]:
        return ["ouo.io", "ouo.press"]

    def resolve(
        self,
        page,
        url: str,
        status: Callable[[str], None] | None = None,
    ) -> str | None:
        """Resolve ouo.io URL through countdown + button click chain."""

        def _status(msg: str) -> None:
            if status:
                status(msg)
            else:
                logger.debug(msg)

        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        # Navigate to URL
        _status("Loading page...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
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
                page.mouse.move(
                    random.randint(100, 1100),
                    random.randint(100, 600),
                )
                time.sleep(random.uniform(0.05, 0.1))

            # Wait for button to become enabled
            _status("Waiting for button...")
            try:
                page.wait_for_selector(
                    "#btn-main:not([disabled])",
                    timeout=30000,  # ouo.io has ~25s countdown
                )
            except PlaywrightTimeout:
                _status("Button timeout, checking page...")

            # Check if button exists and click it
            btn = page.query_selector("#btn-main")
            if btn and btn.is_visible():
                _status("Clicking button...")
                # Human-like mouse movement to button
                box = btn.bounding_box()
                if box:
                    page.mouse.move(
                        int(box["x"] + box["width"] / 2),
                        int(box["y"] + box["height"] / 2),
                    )
                    time.sleep(random.uniform(0.1, 0.3))

                btn.evaluate("el => el.click()")

                # Wait for navigation
                _status("Following redirect...")
                try:
                    page.wait_for_function(
                        f"() => window.location.href !== '{current}'",
                        timeout=15000,
                    )
                    time.sleep(1)
                except PlaywrightTimeout:
                    _status("Navigation timeout")
            else:
                _status("No button found, scanning for links...")
                # Scan for destination links
                links = page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => !h.includes('ouo.io') && !h.includes('ouo.press') && !h.startsWith('javascript'));
                }""")
                if links:
                    return links[0]
                break

        # Final check
        final = page.url
        if not self.can_handle(final):
            return final

        # Last resort: scan for links
        links = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]'))
                .map(a => a.href)
                .filter(h => !h.includes('ouo.io') && !h.includes('ouo.press') && !h.startsWith('javascript'));
        }""")
        if links:
            return links[0]

        return None
