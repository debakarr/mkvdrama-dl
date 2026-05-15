"""Download orchestration for mkvdrama-dl.

Collects download links from mkvdrama.net and outputs them.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from mkvdrama_downloader.models.drama import Drama, Episode

logger = logging.getLogger(__name__)


def format_episode_output(
    drama: Drama,
    episodes: list[Episode],
    output_dir: str | Path | None = None,
) -> None:
    """Format and output episode download links.

    Args:
        drama: Drama metadata
        episodes: List of episodes with download links
        output_dir: Optional directory to save link files
    """
    if not episodes:
        print("  No download links found.")
        return

    base_dir = Path(output_dir) if output_dir else None
    if base_dir:
        base_dir.mkdir(parents=True, exist_ok=True)

    for ep in episodes:
        if not ep.links:
            continue

        ep_label = f"Episode {int(ep.number)}"
        print(f"\n  {ep_label}:")
        print(f"  {'=' * 40}")

        if base_dir:
            link_file = base_dir / f"{_sanitize_filename(drama.title)}_E{int(ep.number):02d}_links.txt"
            with open(link_file, "w", encoding="utf-8") as f:
                for link in ep.links:
                    quality = f" [{link.quality}]" if link.quality else ""
                    host = f" @ {link.host}" if link.host else ""
                    line = f"{link.url}"
                    print(f"    {quality}{host}: {link.url}")
                    f.write(line + "\n")
            print(f"    [Links saved to: {link_file}]")
        else:
            for link in ep.links:
                quality = f" [{link.quality}]" if link.quality else ""
                host = f" @ {link.host}" if link.host else ""
                print(f"    {quality}{host}: {link.url}")


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    sanitized = re.sub(r"\s+", "_", sanitized)
    return sanitized.strip("._")
