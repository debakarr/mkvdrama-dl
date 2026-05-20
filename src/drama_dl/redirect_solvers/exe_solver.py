"""Solver for exe.io → exeygo.com redirect chain.

Flow:
1. exe.io/Vj9Gw → 302 redirect → exeygo.com/Vj9Gw
2. exeygo.com → POST form with CSRF tokens → page with JS redirect
3. JS redirect → intermediate URL (justkoalas.com, etc.) → final destination
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from drama_dl.redirect_solvers.base import RedirectSolver

logger = logging.getLogger(__name__)


class ExeSolver(RedirectSolver):
    """Solver for exe.io and exeygo.com shortener URLs."""

    @property
    def name(self) -> str:
        return "exe.io/exeygo.com solver"

    @property
    def domains(self) -> list[str]:
        return ["exe.io", "exeygo.com"]

    def resolve(
        self,
        page,
        url: str,
        status: Callable[[str], None] | None = None,
    ) -> str | None:
        """Resolve exe.io/exeygo.com URL to final destination."""

        def _status(msg: str) -> None:
            if status:
                status(msg)
            else:
                logger.debug(msg)

        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        # Navigate to URL (exe.io will redirect to exeygo.com automatically)
        _status("Loading page...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            logger.debug("Page load failed: %s", e)
            return None

        current = page.url
        _status(f"Redirected to: {current}")

        # If we're on exeygo.com, we need to submit the form
        if "exeygo.com" in current:
            return self._resolve_exeygo(page, current, _status)

        # If we're already past the shortener, return the URL
        if not self.can_handle(current):
            return current

        return None

    def _resolve_exeygo(
        self,
        page,
        url: str,
        status: Callable[[str], None],
    ) -> str | None:
        """Resolve exeygo.com by submitting the form and following JS redirect."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        status("Extracting form data...")

        # Extract form fields
        form_info = page.evaluate("""() => {
            const btn = document.querySelector('button.button.link-button.vhit, button[type="submit"]');
            const form = btn?.closest('form');
            if (!form) return null;
            const inputs = Array.from(form.querySelectorAll('input[type=hidden]')).map(i => ({
                name: i.name, value: i.value
            }));
            return {
                action: form.action,
                method: form.method,
                inputs: inputs
            };
        }""")

        if not form_info:
            status("No form found, trying button click...")
            # Fallback: try clicking the Continue button after removing overlays
            page.evaluate("""() => {
                document.querySelectorAll('.pum-overlay, .pum-modal, [class*="pum"]').forEach(el => el.remove());
            }""")
            time.sleep(1)

            btn = page.query_selector('button.button.link-button.vhit')
            if btn:
                btn.click()
                # Wait for navigation
                try:
                    page.wait_for_function(
                        f"() => window.location.href !== '{url}'",
                        timeout=15000,
                    )
                    time.sleep(2)
                    final = page.url
                    if not self.can_handle(final):
                        return final
                except PlaywrightTimeout:
                    pass
            return None

        status("Submitting form...")

        # Build form data
        form_data = {}
        for inp in form_info.get("inputs", []):
            form_data[inp["name"]] = inp["value"]

        # Submit via JavaScript to avoid page navigation issues
        result = page.evaluate("""(formData) => {
            // Create a form and submit it
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = window.location.href;
            form.style.display = 'none';

            for (const [name, value] of Object.entries(formData)) {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = name;
                input.value = value;
                form.appendChild(input);
            }

            document.body.appendChild(form);
            form.submit();
            return true;
        }""", form_data)

        # Wait for the response page to load
        time.sleep(3)

        # Extract JS redirect URL from response
        status("Extracting redirect URL...")
        redirect_url = page.evaluate("""() => {
            // Look for window.location.href = '...' in scripts
            const scripts = Array.from(document.querySelectorAll('script:not([src])'));
            for (const script of scripts) {
                const text = script.textContent || '';
                const match = text.match(/window\\.location\\.href\\s*=\\s*["']([^"']+)["']/);
                if (match) return match[1];
            }
            // Also check meta refresh
            const meta = document.querySelector('meta[http-equiv="refresh"]');
            if (meta) {
                const content = meta.getAttribute('content') || '';
                const match = content.match(/url=([^"']+)/i);
                if (match) return match[1];
            }
            return null;
        }""")

        if redirect_url:
            status(f"Following redirect to: {redirect_url[:60]}...")
            try:
                page.goto(redirect_url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                final = page.url
                if not self.can_handle(final):
                    return final
            except Exception as e:
                logger.debug("Redirect navigation failed: %s", e)

        # If still on exeygo.com, scan for links
        final = page.url
        if "exeygo.com" in final:
            status("Scanning for destination links...")
            links = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(h => !h.includes('exeygo.com') && !h.includes('exe.io') && !h.startsWith('javascript'));
            }""")
            if links:
                return links[0]

        return None
