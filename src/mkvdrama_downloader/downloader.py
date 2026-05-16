"""Download orchestration for mkvdrama-dl.

Collects download links from mkvdrama.net and outputs them.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from mkvdrama_downloader.models.drama import Drama, Episode

logger = logging.getLogger(__name__)

# Default download directory — overridable via ``MKVDRAMA_DOWNLOADS_DIR``.
_DEFAULT_DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "mkvdrama-dl")


def _default_output_dir() -> str:
    """Return the default download directory, falling back to env var / standard path."""
    return os.getenv("MKVDRAMA_DOWNLOADS_DIR") or _DEFAULT_DOWNLOADS_DIR


def _links_key(ep: Episode) -> str:
    """Create a hashable key from an episode's links for comparison."""
    return "|".join(sorted(f"{ln.quality}|{ln.url}" for ln in ep.links))


def format_episode_output(
    drama: Drama,
    episodes: list[Episode],
    output_dir: str | Path | None = None,
) -> None:
    """Format and output episode download links.

    If all episodes share the exact same download links, shows them
    once with a compact note (e.g. "Same links for episodes 1-6").

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

    # Check if all episodes share the same links
    link_keys = [_links_key(ep) for ep in episodes if ep.links]
    all_same = len(set(link_keys)) == 1 and len(link_keys) > 1

    if all_same:
        # Compact display: show links once for the whole range
        ep_nums = sorted(int(e.number) for e in episodes if e.links)
        range_str = _format_ep_range(ep_nums)
        first_ep = next(e for e in episodes if e.links)

        print(f"\n  Same links for episodes {range_str}:")
        print(f"  {'=' * 40}")
        _print_links(first_ep.links)

        if base_dir:
            filename = f"{_sanitize_filename(drama.title)}_E{ep_nums[0]:02d}-{ep_nums[-1]:02d}_links.txt"
            link_file = base_dir / filename
            with open(link_file, "w", encoding="utf-8") as f:
                for link in first_ep.links:
                    f.write(f"{link.url}\n")
            print(f"    [Links saved to: {link_file}]")
    else:
        # Standard display: show each episode separately
        for ep in episodes:
            if not ep.links:
                continue

            ep_label = f"Episode {int(ep.number)}"
            print(f"\n  {ep_label}:")
            print(f"  {'=' * 40}")

            if base_dir:
                link_file = base_dir / f"{_sanitize_filename(drama.title)}_E{int(ep.number):02d}_links.txt"
                with open(link_file, "w", encoding="utf-8") as f:
                    _print_links(ep.links, f)
                print(f"    [Links saved to: {link_file}]")
            else:
                _print_links(ep.links)


def _print_links(links: list, file=None) -> None:
    """Print download links, optionally writing to a file."""
    for link in links:
        quality = f" [{link.quality}]" if link.quality else ""
        host = f" @ {link.host}" if link.host else ""
        line = f"    {quality}{host}: {link.url}"
        print(line)
        if file:
            file.write(f"{link.url}\n")


def _format_ep_range(nums: list[int]) -> str:
    """Format a list of episode numbers into a compact range string.

    Examples:
        [1, 2, 3] -> '1-3'
        [1, 2, 3, 5, 6] -> '1-3, 5-6'
        [1, 3, 5] -> '1, 3, 5'
    """
    if not nums:
        return ""

    ranges: list[tuple[int, int]] = []
    start = end = nums[0]

    for n in nums[1:]:
        if n == end + 1:
            end = n
        else:
            ranges.append((start, end))
            start = end = n
    ranges.append((start, end))

    parts = []
    for s, e in ranges:
        if s == e:
            parts.append(str(s))
        else:
            parts.append(f"{s}-{e}")

    return ", ".join(parts)


def write_organized_link_files(
    drama_title: str,
    urls: list[str],
    direct_links: list[str],
    output_dir: str | Path | None = None,
) -> Path | None:
    """Write per-host-domain link files into a drama-named subfolder.

    Creates ``{output_dir}/{drama_title}/`` with one ``.txt`` file per
    host domain (``mega.nz.txt``, ``pixeldrain.com.txt``, …), plus a
    combined ``all_links.txt``.

    Args:
        drama_title: Used for the subfolder name.
        urls: Resolved shortener URLs (filecrypt.cc etc.).
        direct_links: Direct download links from dcrypt.it resolution.
        output_dir: Root output directory (auto-detected defaults to
                    ``~/Downloads/mkvdrama-dl/``).

    Returns:
        Path of the created drama folder, or ``None`` if nothing was written.
    """
    if not urls and not direct_links:
        return None

    root = Path(output_dir) if output_dir else Path(_default_output_dir())
    drama_folder = root / _sanitize_filename(drama_title)
    drama_folder.mkdir(parents=True, exist_ok=True)

    # ── Group direct links by host domain ────────────────────────────
    by_host: dict[str, list[str]] = defaultdict(list)
    for link in direct_links:
        host = urlparse(link).netloc or "unknown"
        by_host[host].append(link)

    # ── Write one file per host domain ───────────────────────────────
    for host, host_urls in sorted(by_host.items()):
        host_file = drama_folder / f"{host}.txt"
        with open(host_file, "w", encoding="utf-8", newline="") as f:
            for url in sorted(host_urls):
                f.write(f"{url}\n")

        count_str = f"{len(host_urls)} link(s)"
        print(f"    [Links saved to: {host_file}  ({count_str})]")

    # ── Write combined all-links file ────────────────────────────────
    all_file = drama_folder / "all_links.txt"
    with open(all_file, "w", encoding="utf-8", newline="") as f:
        for link in direct_links:
            f.write(f"{link}\n")
        if urls:
            f.write("\n# --- Resolved container URLs ---\n")
            for url in urls:
                f.write(f"{url}\n")

    print(f"    [All links saved to: {all_file}]")

    # ── Write filecrypt URLs separately ──────────────────────────────
    if urls:
        fc_file = drama_folder / "filecrypt_container.txt"
        with open(fc_file, "w", encoding="utf-8", newline="") as f:
            for url in urls:
                f.write(f"{url}\n")
        print(f"    [Container URLs saved to: {fc_file}]")

    return drama_folder


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    sanitized = re.sub(r"\s+", "_", sanitized)
    return sanitized.strip("._")
