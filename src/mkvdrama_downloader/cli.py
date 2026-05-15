"""CLI entry point for mkvdrama-dl.

Usage:
    mkvdrama search <query>
    mkvdrama dl <url_or_query>
    mkvdrama dl <url_or_query> --episode 1-5
"""

from __future__ import annotations

import logging
import os
import sys

import click

from mkvdrama_downloader import __version__
from mkvdrama_downloader.downloader import format_episode_output
from mkvdrama_downloader.mkvdrama_api import MkvDramaApi

logger = logging.getLogger(__name__)


def _setup_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level."""
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


def _get_api(ctx: click.Context) -> MkvDramaApi:
    """Get or create the API client from click context."""
    ctx.ensure_object(dict)
    if "api" not in ctx.obj:
        cookie = os.getenv("MKVDRAMA_COOKIE", "")
        flaresolverr = os.getenv("FLARESOLVERR_URL", "") or None
        ctx.obj["api"] = MkvDramaApi(
            cookie_string=cookie or None,
            flaresolverr_url=flaresolverr,
        )
    return ctx.obj["api"]


@click.group()
@click.option("-v", "--verbose", count=True, help="Increase verbosity (-v, -vv)")
@click.version_option(__version__, prog_name="mkvdrama")
@click.pass_context
def mkvdrama(ctx: click.Context, verbose: int) -> None:
    """Download Asian dramas from mkvdrama.net.

    Search for dramas, browse episodes, and scrape download links.

    Note: This tool scrapes download links (ouo.io, filecrypt). Actual file
    downloads require resolving the shortener links.

    Set MKVDRAMA_COOKIE env var for Cloudflare bypass (optional).
    """
    _setup_logging(verbose)
    ctx.obj = {}


@mkvdrama.command()
@click.argument("query")
@click.pass_context
def search(ctx: click.Context, query: str) -> None:
    """Search for dramas on mkvdrama.net."""
    api = _get_api(ctx)
    results = api.search_dramas(query)

    if not results:
        print(f"No results found for '{query}'.")
        sys.exit(1)

    print(f"\nSearch results for '{query}':")
    print("=" * 60)

    for i, drama in enumerate(results, 1):
        ep_info = f" ({drama.episodes_count} eps)" if drama.episodes_count else ""
        country = f" [{drama.country}]" if drama.country else ""
        status = f" - {drama.status}" if drama.status else ""
        print(f"  {i:2d}. {drama.title}{ep_info}{country}{status}")
        print(f"      {drama.url}")


@mkvdrama.command()
@click.argument("drama_url_or_query")
@click.option(
    "--episode",
    "-e",
    default=None,
    help="Episode range (e.g. '1-5', '3', or '1,3,5')",
)
@click.option(
    "--output-dir",
    "-o",
    default=None,
    help="Directory to save link files",
    type=click.Path(file_okay=False, dir_okay=True),
)
@click.option(
    "--flaresolverr",
    "-f",
    default=None,
    metavar="URL",
    help="FlareSolverr endpoint for resolving ouo.io shorteners (e.g. http://localhost:8191)",
)
@click.pass_context
def dl(
    ctx: click.Context,
    drama_url_or_query: str,
    episode: str | None,
    output_dir: str | None,
    flaresolverr: str | None,
) -> None:
    """Download or list drama episodes from mkvdrama.net.

    Provide a drama URL or search query. If a search query returns multiple
    results, you'll be prompted to select one.
    """
    api = _get_api(ctx)

    # Override FlareSolverr URL from --flaresolverr flag if provided
    if flaresolverr:
        import os as _os

        _os.environ["FLARESOLVERR_URL"] = flaresolverr.rstrip("/")

    # Determine if input is URL or search query
    is_url = drama_url_or_query.startswith("http://") or drama_url_or_query.startswith("https://")

    if not is_url:
        # Search first
        results = api.search_dramas(drama_url_or_query)
        if not results:
            print(f"No results found for '{drama_url_or_query}'.")
            sys.exit(1)

        if len(results) == 1:
            drama_url: str = results[0].url or ""
            drama_title = results[0].title
        else:
            print(f"\nMultiple results for '{drama_url_or_query}':")
            for i, r in enumerate(results, 1):
                print(f"  {i}. {r.title}")
            print()
            choice = click.prompt(
                "Select a drama (number)",
                type=click.IntRange(1, len(results)),
            )
            selected = results[choice - 1]
            drama_url = selected.url or ""
            drama_title = selected.title

        if not drama_url:
            print("No valid URL found for selected drama.")
            sys.exit(1)
    else:
        drama_url = drama_url_or_query.rstrip("/")
        drama_title = drama_url.rsplit("/", 1)[-1].replace("-", " ").title()

    print(f"\nFetching: {drama_title}")
    print(f"  {drama_url}")

    drama = api.get_drama(drama_url)

    if not drama.episodes:
        print("\nNo download links found. This may be due to Cloudflare protection.")
        print("Try setting MKVDRAMA_COOKIE with a valid cf_clearance cookie.")
        sys.exit(1)

    # Filter episodes by range
    episodes = drama.episodes
    if episode:
        selected_nums = _parse_episode_range(episode, len(episodes))
        if selected_nums:
            episodes = [e for e in episodes if e.number in selected_nums]
        else:
            print(f"Invalid episode range: {episode}")
            sys.exit(1)

    print(f"\nDrama: {drama.title}")
    if drama.country:
        print(f"Country: {drama.country}")
    if drama.status:
        print(f"Status: {drama.status}")
    if drama.synopsis:
        synopsis_short = drama.synopsis[:150] + "..." if len(drama.synopsis) > 150 else drama.synopsis
        print(f"Synopsis: {synopsis_short}")

    print(f"\nEpisodes: {len(episodes)}")
    format_episode_output(drama, episodes, output_dir=output_dir)

    print(f"\nTotal download links found: {sum(len(e.links) for e in episodes)}")


def _parse_episode_range(range_str: str, max_ep: int) -> set[int]:
    """Parse episode range string like '1-5', '3', or '1,3,5'."""
    selected: set[int] = set()

    parts = [p.strip() for p in range_str.split(",")]
    for part in parts:
        if "-" in part:
            try:
                start_str, end_str = part.split("-", 1)
                start_num = int(start_str.strip())
                end_num = int(end_str.strip())
                selected.update(range(start_num, end_num + 1))
            except ValueError:
                continue
        else:
            try:
                selected.add(int(part))
            except ValueError:
                continue

    return selected
