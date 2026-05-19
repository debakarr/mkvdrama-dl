"""CLI entry point for drama-dl.

Usage:
    drama search <query>
    drama dl <url_or_query>
    drama dl <url_or_query> --episode 1-5
    drama dl <url_or_query> --resolve --jd
"""

from __future__ import annotations

import logging
import os

import click

from drama_dl import __version__
from drama_dl.downloader import (
    format_episode_output,
    write_organized_link_files,
)
from drama_dl.jd import find_crawljob_dir, write_crawljob
from drama_dl.providers import detect_provider, list_providers
from drama_dl.providers.base import DramaProvider

logger = logging.getLogger(__name__)

# ── Color palette ──────────────────────────────────────────────────────
_STYLE_ERROR = {"fg": "red", "bold": True}
_STYLE_WARN = {"fg": "yellow"}
_STYLE_OK = {"fg": "green"}
_STYLE_TITLE = {"fg": "cyan", "bold": True}
_STYLE_HINT = {"dim": True}


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


def _get_provider(ctx: click.Context, url: str) -> DramaProvider:
    """Auto-detect or prompt for a provider based on URL."""
    ctx.ensure_object(dict)

    # Try auto-detect from URL
    provider = detect_provider(url)
    if provider is not None:
        return provider

    # URL doesn't match any known provider
    providers = list_providers()
    supported = ", ".join(p.name for p in providers)
    raise click.ClickException(
        click.style(
            f"Unsupported URL: {url}\nSupported providers: {supported}",
            **_STYLE_ERROR,
        )
    )


def _supported_sites() -> str:
    """Return a formatted list of supported sites."""
    providers = list_providers()
    lines = []
    for p in providers:
        lines.append(f"  - {p.name}: {', '.join(p.domains)}")
    return "\n".join(lines)


@click.group(
    epilog=f"Supported sites: {_supported_sites()}",
)
@click.option("-v", "--verbose", count=True, help="Increase verbosity (-v, -vv)")
@click.version_option(__version__, prog_name="drama")
@click.pass_context
def drama(ctx: click.Context, verbose: int) -> None:
    """Download Asian dramas from multiple sites.

    Note: This tool scrapes download links. Actual file downloads require
    resolving the shortener links.

    Environment variables:
      MKVDRAMA_COOKIE  — cf_clearance cookie for Cloudflare bypass
      FLARESOLVERR_URL — FlareSolverr endpoint URL
    """
    _setup_logging(verbose)
    ctx.obj = {}


@drama.command()
@click.argument("query")
@click.pass_context
def search(ctx: click.Context, query: str) -> None:
    """Search for dramas across all providers."""
    providers = list_providers()
    all_results = []

    for provider in providers:
        try:
            results = provider.search(query)
            if results:
                all_results.extend(results)
        except Exception as e:
            logger.debug("Search failed for %s: %s", provider.name, e)

    if not all_results:
        raise click.ClickException(click.style(f"No results found for '{query}'.", **_STYLE_ERROR))

    click.echo(click.style(f"\nSearch results for '{query}':", bold=True))
    click.echo("=" * 60)

    for i, drama_info in enumerate(all_results, 1):
        parts = [f"  {i:2d}. {drama_info.title}"]
        if drama_info.episodes_count:
            parts.append(click.style(f"({drama_info.episodes_count} eps)", **_STYLE_HINT))
        if drama_info.country:
            parts.append(click.style(f"[{drama_info.country}]", **_STYLE_OK))
        click.echo(" ".join(parts))
        click.echo(f"      {drama_info.url}")


@drama.command()
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
    help="Save per-host-domain link files to this directory (default: ~/Downloads/drama-dl/)",
    type=click.Path(file_okay=False, dir_okay=True),
    envvar="MKVDRAMA_DOWNLOADS_DIR",
)
@click.option(
    "--flaresolverr",
    "-f",
    default=None,
    metavar="URL",
    help="FlareSolverr endpoint for resolving shorteners (e.g. http://localhost:8191)",
)
@click.option(
    "--resolve",
    is_flag=True,
    default=False,
    help="Resolve shortener URLs using Playwright (requires: pip install playwright && playwright install chromium)",
)
@click.option(
    "--quality",
    "-q",
    default=None,
    metavar="QUALITY",
    help="Filter by resolution: 540p, 720p, 1080p (can specify multiple: 720p,1080p)",
)
@click.option(
    "--jd",
    "--jdownloader",
    is_flag=True,
    default=False,
    help="Forward resolved URLs to JDownloader2 LinkGrabber (via .crawljob file)",
)
@click.option(
    "--jd-dir",
    envvar="JD2_CRAWLJOB_DIR",
    default=None,
    metavar="DIR",
    help="JDownloader2 crawljob folder (auto-detected if omitted)",
    type=click.Path(file_okay=False, dir_okay=True),
)
@click.pass_context
def dl(
    ctx: click.Context,
    drama_url_or_query: str,
    episode: str | None,
    output_dir: str | None,
    flaresolverr: str | None,
    resolve: bool,
    quality: str | None,
    jd: bool,
    jd_dir: str | None,
) -> None:
    """Download or list drama episodes.

    Provide a drama URL or search query. If a search query returns multiple
    results, you'll be prompted to select one.
    """
    # Determine if input is URL or search query
    is_url = drama_url_or_query.startswith(("http://", "https://"))

    if is_url:
        drama_url = drama_url_or_query.rstrip("/")
        provider = _get_provider(ctx, drama_url)
        drama_title = None  # Will be set from fetched drama
    else:
        # Search across all providers
        providers = list_providers()
        all_results = []

        for p in providers:
            try:
                results = p.search(drama_url_or_query)
                if results:
                    all_results.extend(results)
            except Exception as e:
                logger.debug("Search failed for %s: %s", p.name, e)

        if not all_results:
            raise click.ClickException(click.style(f"No results found for '{drama_url_or_query}'.", **_STYLE_ERROR))

        if len(all_results) == 1:
            drama_url = all_results[0].url or ""
            drama_title = all_results[0].title
        else:
            click.echo(click.style(f"\nMultiple results for '{drama_url_or_query}':", bold=True))
            for i, r in enumerate(all_results, 1):
                click.echo(f"  {i}. {r.title}")
            click.echo("")
            choice = click.prompt(
                "Select a drama (number)",
                type=click.IntRange(1, len(all_results)),
            )
            selected = all_results[choice - 1]
            drama_url = selected.url or ""
            drama_title = selected.title

        if not drama_url:
            raise click.ClickException(click.style("No valid URL found for selected drama.", **_STYLE_ERROR))

        provider = _get_provider(ctx, drama_url)

    click.echo(click.style(f"\nProvider: {provider.name}", **_STYLE_HINT))
    click.echo(f"  {drama_url}")

    try:
        drama = provider.get_drama(drama_url)
    except RuntimeError as e:
        raise click.ClickException(click.style(str(e), **_STYLE_ERROR))

    # Use actual title from fetched drama
    drama_title = drama.title or drama_title or drama_url.rsplit("/", 1)[-1].replace("-", " ").title()
    click.echo(click.style(f"Fetching: {drama_title}", **_STYLE_TITLE))

    if not drama.episodes:
        raise click.ClickException(
            click.style(
                "\nNo download links found. This may be due to Cloudflare protection.\n"
                "Try setting MKVDRAMA_COOKIE with a valid cf_clearance cookie.",
                **_STYLE_ERROR,
            )
        )

    # Filter episodes by range
    episodes = drama.episodes
    if episode:
        selected_nums = _parse_episode_range(episode, len(episodes))
        if selected_nums:
            episodes = [e for e in episodes if e.number in selected_nums]
        else:
            raise click.UsageError(click.style(f"Invalid episode range: {episode}", **_STYLE_ERROR))

    click.echo(click.style(f"\nDrama: {drama.title}", **_STYLE_TITLE))
    if drama.country:
        click.echo(f"Country: {drama.country}")
    if drama.status:
        click.echo(f"Status: {drama.status}")
    if drama.synopsis:
        synopsis_short = drama.synopsis[:150] + "..." if len(drama.synopsis) > 150 else drama.synopsis
        click.echo(f"Synopsis: {synopsis_short}")

    # Filter by quality/resolution if specified (BEFORE resolving shorteners)
    if quality:
        qualities = [q.strip().lower() for q in quality.split(",")]
        for ep in episodes:
            ep.links = [ln for ln in ep.links if (ln.quality or "").lower() in qualities]
        episodes = [ep for ep in episodes if ep.links]

    # Resolve shorteners AFTER filtering
    if resolve or flaresolverr or os.getenv("FLARESOLVERR_URL"):
        provider.resolve_shorteners(episodes)

    # Collect resolved URLs and extract dcrypt.it direct links
    resolved_urls = _collect_resolved_urls(episodes)
    direct_links = _collect_direct_links(resolved_urls)

    click.echo(f"\nEpisodes: {len(episodes)}")
    format_episode_output(drama, episodes, output_dir=output_dir)

    total_links = sum(len(e.links) for e in episodes)
    click.echo(click.style(f"\nTotal download links found: {total_links}", bold=True))

    # ── Write organized host-domain files ─────────────────────────────
    out_dir = output_dir or os.getenv("MKVDRAMA_DOWNLOADS_DIR")
    if out_dir or direct_links:
        _ = write_organized_link_files(
            drama.title or drama_title,
            resolved_urls,
            direct_links,
            output_dir=out_dir,
        )

    # ── JDownloader2 integration ──────────────────────────────────────
    if jd:
        _send_to_jdownloader(episodes, jd_dir, resolved_urls)


def _collect_resolved_urls(episodes: list) -> list[str]:
    """Collect unique resolved download URLs from all episodes."""
    seen: set[str] = set()
    urls: list[str] = []
    for ep in episodes:
        for link in ep.links:
            url = link.url
            if url and url.startswith(("http://", "https://")) and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def _collect_direct_links(resolved_urls: list[str]) -> list[str]:
    """Extract direct download links (dcrypt.it) from resolved filecrypt URLs."""
    from drama_dl.shortener import extract_filecrypt_links, is_filecrypt_url

    direct_links: list[str] = []
    for url in resolved_urls:
        if not is_filecrypt_url(url):
            continue
        entries = extract_filecrypt_links(url)
        for entry in entries:
            if entry.get("host") == "dcrypt.it":
                direct_links.extend(entry.get("dcrypt_links", []))
    return direct_links


def _send_to_jdownloader(
    episodes: list,
    jd_dir: str | None,
    resolved_urls: list[str] | None = None,
) -> None:
    """Send resolved episode URLs to JDownloader2 LinkGrabber."""
    crawljob_dir = jd_dir or find_crawljob_dir()
    if not crawljob_dir:
        click.echo(
            click.style(
                "  ⚠ Could not find JDownloader2 crawljob folder.\n"
                "    Set JD2_CRAWLJOB_DIR or use --jd-dir to point at it.",
                **_STYLE_WARN,
            )
        )
        return

    urls = resolved_urls if resolved_urls is not None else _collect_resolved_urls(episodes)
    if not urls:
        click.echo(click.style("  ⚠ No URLs to send to JDownloader2.", **_STYLE_WARN))
        return

    result = write_crawljob(urls, crawljob_dir)
    if result:
        click.echo(click.style(f"  ✓ Sent {len(urls)} URL(s) to JDownloader2 LinkGrabber", **_STYLE_OK))


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
