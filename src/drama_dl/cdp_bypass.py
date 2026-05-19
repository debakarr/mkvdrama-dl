"""Chrome CDP-based Cloudflare bypass for drama-dl.

Launches a real Chrome instance, connects via Chrome DevTools Protocol (CDP),
waits for Cloudflare challenge to solve, and extracts the cf_clearance cookie.

This is used as a fallback when curl-cffi and FlareSolverr both fail for
dramaday.me Cloudflare protection.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Module-level cache for cf_clearance cookie
_cf_clearance_cache: str | None = None
_chrome_process: subprocess.Popen | None = None


def _get_chrome_path() -> str | None:
    """Get Chrome executable path for the current platform."""
    candidates: list[Path] = []
    if os.name == "nt":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
    elif os.name == "posix":
        candidates = [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]

    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _find_free_port() -> int:
    """Find a free port for Chrome remote debugging."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get_cf_clearance(url: str, timeout: int = 30) -> str | None:
    """Obtain cf_clearance cookie by launching Chrome and solving Cloudflare challenge.

    Args:
        url: The URL to visit (Chrome will solve Cloudflare for this domain).
        timeout: Maximum seconds to wait for challenge resolution.

    Returns:
        cf_clearance cookie value, or None if failed.
    """
    global _cf_clearance_cache, _chrome_process

    # Return cached cookie if available
    if _cf_clearance_cache:
        logger.debug("Using cached cf_clearance cookie")
        return _cf_clearance_cache

    chrome_path = _get_chrome_path()
    if not chrome_path:
        logger.warning("Chrome executable not found — CDP bypass unavailable")
        return None

    logger.info("Launching Chrome for Cloudflare bypass...")

    # Use a temporary profile directory
    user_data_dir = Path(os.environ.get("TEMP", "/tmp")) / "drama-dl-chrome-profile"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    port = _find_free_port()

    try:
        proc = subprocess.Popen(
            [
                chrome_path,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-gpu",
                "--no-sandbox",
                "--window-size=1920,1080",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _chrome_process = proc

        # Wait for Chrome to start
        time.sleep(2)

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            logger.debug("Connecting to Chrome via CDP on port %d...", port)
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")

            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()

            # Wait for Cloudflare challenge to solve
            logger.info("Waiting for Cloudflare challenge to solve...")
            start = time.time()
            solved = False
            while time.time() - start < timeout:
                title = page.title()
                if "Just a moment" not in title:
                    logger.info("Cloudflare challenge solved in %.1fs", time.time() - start)
                    solved = True
                    break
                time.sleep(1)

            if not solved:
                logger.warning("Cloudflare challenge not solved within %ds timeout", timeout)
                browser.close()
                return None

            # Extract cookies
            cookies = context.cookies()
            cf_clearance = None
            for c in cookies:
                if c.get("name") == "cf_clearance":
                    cf_clearance = c.get("value")
                    break

            browser.close()

            if cf_clearance:
                _cf_clearance_cache = cf_clearance
                logger.info("cf_clearance obtained: %s...", cf_clearance[:30])
                return cf_clearance
            else:
                logger.warning("cf_clearance cookie not found in browser cookies")
                return None

    except Exception as e:
        logger.error("CDP bypass failed: %s", e)
        return None
    finally:
        # Clean up Chrome process
        if _chrome_process:
            try:
                _chrome_process.terminate()
                _chrome_process.wait(timeout=5)
            except Exception:
                _chrome_process.kill()
            _chrome_process = None


def clear_cache() -> None:
    """Clear the cached cf_clearance cookie."""
    global _cf_clearance_cache
    _cf_clearance_cache = None
    logger.debug("cf_clearance cache cleared")
