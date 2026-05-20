"""Solver for cutw.in auto-redirect shortener.

Flow:
1. Navigate to cutw.in/xyz
2. Wait for auto-redirect (usually 3-5 seconds)
3. Final destination reached
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from drama_dl.redirect_solvers.base import RedirectSolver

logger = logging.getLogger(__name__)


class CutwSolver(RedirectSolver):
    """Solver for cutw.in shortener URLs."""

    @property
    def name(self) -> str:
        return "cutw.in solver"

    @property
    def domains(self) -> list[str]:
        return ["cutw.in"]

    def resolve(
        self,
        page,
        url: str,
        status: Callable[[str], None] | None = None,
    ) -> str | None:
        """Resolve cutw.in URL to final destination via auto-redirect."""

        def _status(msg: str) -> None:
            if status:
                status(msg)
            else:
                logger.debug(msg)

        _status("Loading page...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            logger.debug("Page load failed: %s", e)
            return None

        # Wait for auto-redirect
        _status("Waiting for auto-redirect...")
        start_url = page.url
        max_wait = 15  # seconds

        for i in range(max_wait):
            time.sleep(1)
            current = page.url
            if current != start_url and "cutw.in" not in current:
                _status(f"Redirected after {i+1}s")
                return current

        # Check if we're still on cutw.in
        final = page.url
        if "cutw.in" not in final:
            return final

        # Scan for links as fallback
        _status("Scanning for destination links...")
        links = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]'))
                .map(a => a.href)
                .filter(h => !h.includes('cutw.in') && !h.startsWith('javascript'));
        }""")
        if links:
            return links[0]

        return None
