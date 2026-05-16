"""JDownloader 2 integration — sends resolved links to LinkGrabber.

Works by writing ``.crawljob`` files to JD2's monitored watch folder.
JD2 automatically detects new ``.crawljob`` files and adds their URLs
to the LinkGrabber — no API setup, no clipboard interference, no
extra dependencies.

Usage::
    >>> from mkvdrama_downloader.jd import write_crawljob
    >>> write_crawljob(["https://mega.nz/file/xxx#key"])

Crawljob format reference:
    https://support.jdownloader.org/Knowledgebase/Article/View/crawljob
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Priority-ordered candidate paths for JD2's crawljob watch folder.
# JD2 polls this folder for new ``.crawljob`` files.
_CRAWLJOB_DIRS: list[str] = [
    # Windows — LocalAppData (most common portable install)
    os.path.join(os.getenv("LOCALAPPDATA", ""), "JDownloader 2", "cfg", "crawljob"),
    os.path.join(os.getenv("LOCALAPPDATA", ""), "JDownloader 2.0", "cfg", "crawljob"),
    # Windows — Roaming AppData
    os.path.join(os.getenv("APPDATA", ""), "JDownloader 2.0", "cfg", "crawljob"),
    # Windows — Downloads folder
    os.path.join(os.path.expanduser("~"), "Downloads", "JDownloader 2.0", "cfg", "crawljob"),
    # macOS
    os.path.join(os.path.expanduser("~"), "Library", "Application Support", "JDownloader 2.0", "cfg", "crawljob"),
    # Linux
    os.path.join(os.path.expanduser("~"), ".jd2", "crawljob"),
    os.path.join(os.path.expanduser("~"), ".jdownloader2", "crawljob"),
]

# Environment variable users can set to point at a custom crawljob folder.
_ENV_VAR = "JD2_CRAWLJOB_DIR"


def find_crawljob_dir() -> str | None:
    """Locate JD2's crawljob watch folder.

    Checks (in order):
    1. The ``JD2_CRAWLJOB_DIR`` environment variable.
    2. A set of known OS-specific install paths.

    Returns the first existing directory, or ``None``.
    """
    # 1. Env var override
    env_dir = os.getenv(_ENV_VAR)
    if env_dir and os.path.isdir(env_dir):
        return env_dir

    # 2. Known paths
    for path in _CRAWLJOB_DIRS:
        if path and os.path.isdir(path):
            logger.debug("Auto-detected JD2 crawljob dir: %s", path)
            return path

    logger.info("JD2 crawljob folder not found — set %s to point at it.", _ENV_VAR)
    return None


def write_crawljob(urls: list[str], output_dir: str | Path | None = None) -> Path | None:
    """Write a ``.crawljob`` file that JD2 will auto-import into LinkGrabber.

    Each URL gets its own ``url = …`` line inside one timestamped file.
    JD2 will put them all in the same LinkGrabber package.

    Args:
        urls: Resolved download URLs to add.
        output_dir: Explicit crawljob directory. Auto-detected if ``None``.

    Returns:
        Path of the written ``.crawljob`` file, or ``None`` if no directory
        could be resolved.
    """
    raw = str(output_dir) if output_dir else find_crawljob_dir()
    if not raw:
        return None

    target = Path(raw)
    target.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = target / f"mkvdrama_{ts}.crawljob"

    with open(dst, "w", encoding="utf-8", newline="") as f:
        f.write("[{\n")
        for url in urls:
            f.write(f"url = {url}\n")
        f.write("}]\n")

    logger.info("Wrote crawljob: %s (%d URLs)", dst, len(urls))
    return dst
