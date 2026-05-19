"""DramadayProvider — dramaday.me provider for drama-dl.

WordPress site with Cloudflare protection.  No gate/pass API — all download
links are directly in the HTML page inside a Supsystic table.

Uses curl-cffi for Cloudflare bypass.  Falls back to FlareSolverr when
configured.  When both fail, shows a helpful error message.
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import quote

import requests as std_requests
from bs4 import BeautifulSoup, Tag
from curl_cffi import requests as curl_requests

from drama_dl.models.drama import DownloadLink, Drama, Episode
from drama_dl.models.search import DramaInfo, Search
from drama_dl.providers.base import DramaProvider

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _attr_str(el: Tag, attr: str, default: str | None = "") -> str | None:
    """Safely get a string attribute from a BeautifulSoup element."""
    val = el.get(attr)
    if isinstance(val, str):
        return val or default
    if isinstance(val, list):
        joined = " ".join(val)
        return joined or default
    return default


class DramadayProvider(DramaProvider):
    """Provider for dramaday.me / dramaday.net."""

    @property
    def name(self) -> str:
        return "dramaday"

    DOMAINS: list[str] = ["dramaday.me", "dramaday.net"]

    @property
    def domains(self) -> list[str]:
        return self.DOMAINS

    def __init__(
        self,
        cookie_string: str | None = None,
        flaresolverr_url: str | None = None,
    ) -> None:
        # curl-cffi impersonates Chrome TLS fingerprint.
        self.session = curl_requests.Session(impersonate="chrome131")
        self.session.headers.update(DEFAULT_HEADERS)

        self._cookie_str = cookie_string or os.getenv("DRAMADAY_COOKIE", "")
        if self._cookie_str:
            self.session.headers["Cookie"] = self._cookie_str

        self._flaresolverr_url = flaresolverr_url or os.getenv("FLARESOLVERR_URL", "")
        self._base_url = "https://dramaday.me"

    def _get(self, url: str, timeout: int = 30) -> str | None:
        """Fetch a URL, trying curl-cffi first then FlareSolverr.

        Returns the HTML text, or ``None`` if all methods fail.
        """
        # Try curl-cffi
        try:
            resp = self.session.get(url, timeout=timeout)
            if resp.status_code == 200 and "Just a moment" not in resp.text:
                return resp.text
        except Exception as e:
            logger.debug("curl-cffi failed: %s", e)

        # Try FlareSolverr
        if self._flaresolverr_url:
            try:
                payload = {
                    "cmd": "request.get",
                    "url": url,
                    "maxTimeout": 60_000,
                }
                resp = std_requests.post(
                    f"{self._flaresolverr_url}/v1",
                    json=payload,
                    timeout=65,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    solution = data.get("solution", {})
                    html = solution.get("response", "")
                    if html and "Just a moment" not in html:
                        return html
            except Exception as e:
                logger.debug("FlareSolverr failed: %s", e)

        return None

    def search(self, query: str) -> Search:
        """Search for dramas via WordPress search."""
        url = f"{self._base_url}/?s={quote(query)}"
        logger.info("Searching: %s", url)

        html = self._get(url, timeout=30)
        if html is None:
            logger.warning("Search failed — Cloudflare blocked the request.")
            return Search([])

        soup = BeautifulSoup(html, "html.parser")
        results: list[DramaInfo] = []
        seen: set[str] = set()

        # dramaday uses h3.article__title.entry-title for post titles
        for h3 in soup.select("h3.article__title.entry-title"):
            link_el = h3.select_one("a")
            if not isinstance(link_el, Tag):
                continue

            title = (link_el.get("title") or link_el.get_text(strip=True) or "").strip()
            href = _attr_str(link_el, "href")
            if not title or not href or href in seen:
                continue
            seen.add(href)

            url_full = href if href.startswith("http") else f"{self._base_url}{href}"

            # Skip OST posts — only keep drama/movie posts
            if "ost" in title.lower() and "–" in title:
                continue

            # Find the article parent for poster/category info
            article = h3.find_parent("article") or h3.find_parent(".item")
            poster: str | None = None
            country: str | None = None
            episodes_count: int | None = None

            if isinstance(article, Tag):
                img = article.select_one("img")
                if isinstance(img, Tag):
                    poster = _attr_str(img, "data-src", None) or _attr_str(img, "src", None)

                # Category labels (Drama, Movie, Ongoing, Completed)
                for cat_el in article.select(".category, .cat, [class*='category']"):
                    cat_text = cat_el.get_text(strip=True).upper()
                    if cat_text in ("DRAMA", "MOVIE", "ONGOING", "COMPLETED"):
                        if country is None:
                            country = cat_text

            # Try to extract episode count from nearby text
            if isinstance(article, Tag):
                desc = article.get_text()
                ep_match = re.search(r"(\d+)\s*episodes?", desc, re.IGNORECASE)
                if ep_match:
                    episodes_count = int(ep_match.group(1))

            results.append(
                DramaInfo(
                    title=title,
                    url=url_full,
                    poster=poster,
                    country=country,
                    episodes_count=episodes_count,
                )
            )

        if not results:
            logger.info("No search results for '%s'", query)

        return Search(results)

    def get_drama(self, url: str) -> Drama:
        """Fetch drama details and episode download links."""
        url = url.rstrip("/")
        logger.info("Fetching drama: %s", url)

        html = self._get(url, timeout=30)
        if html is None:
            raise RuntimeError(
                "dramaday.me is blocking automated requests (Cloudflare).\n"
                "Options:\n"
                "  1. Set FLARESOLVERR_URL to a running FlareSolverr instance\n"
                "  2. Set DRAMADAY_COOKIE with a valid cf_clearance cookie\n"
                "  3. Use mkvdrama.net instead (better automated support)"
            )

        soup = BeautifulSoup(html, "html.parser")
        drama = self._parse_drama_page(soup, url)
        drama.episodes = self._parse_download_section(soup)

        return drama

    def resolve_shorteners(self, episodes: list[Episode]) -> None:
        """Resolve shortener URLs using the shared resolver chain."""
        from drama_dl.shortener import is_shortener_url, resolve_shorteners

        unique: dict[str, str] = {}
        for episode in episodes:
            for link in episode.links:
                if is_shortener_url(link.url):
                    unique.setdefault(link.url, link.url)

        urls = list(unique.keys())
        if not urls:
            return

        logger.info("Resolving %d shortener URLs...", len(urls))
        resolved = resolve_shorteners(urls)

        for episode in episodes:
            for link in episode.links:
                if link.url in resolved and resolved[link.url] != link.url:
                    logger.debug("Resolved: %s -> %s", link.url, resolved[link.url])
                    link.url = resolved[link.url]

    def _parse_drama_page(self, soup: BeautifulSoup, url: str) -> Drama:
        """Parse drama metadata from the HTML page."""
        # Title from h1.entry-title
        title_el = soup.select_one("h1.entry-title")
        title = title_el.get_text(strip=True) if isinstance(title_el, Tag) else ""

        # Slug from URL
        slug = url.rstrip("/").rsplit("/", 1)[-1]

        # Synopsis from .entry-content — find the paragraph after metadata
        synopsis = ""
        entry_content = soup.select_one(".entry-content")
        if isinstance(entry_content, Tag):
            text = entry_content.get_text(separator="\n")
            for line in text.split("\n"):
                line = line.strip()
                if line and not line.startswith(
                    (
                        "Title:",
                        "Genre:",
                        "Episodes:",
                        "Broadcast network:",
                        "Broadcast period:",
                        "Air time:",
                        "Subtitles:",
                        "Download",
                        "CAST",
                        "TRAILER",
                    )
                ):
                    if len(line) > 20:
                        synopsis = line
                        break

        # Poster image
        poster: str | None = None
        img = soup.select_one(".entry-content img") or soup.select_one(".thumb img")
        if isinstance(img, Tag):
            poster = _attr_str(img, "data-src", None) or _attr_str(img, "src", None)

        # Metadata from text patterns in .entry-content
        country = None
        episodes_count = None
        status = None

        if isinstance(entry_content, Tag):
            content_text = entry_content.get_text(separator="\n")
            for line in content_text.split("\n"):
                line = line.strip()
                if line.startswith("Broadcast network:"):
                    country = line.replace("Broadcast network:", "").strip()
                elif line.startswith("Episodes:"):
                    ep_str = line.replace("Episodes:", "").strip()
                    try:
                        episodes_count = int(ep_str)
                    except ValueError:
                        pass

        # Determine status from URL categories
        for cat_link in soup.select('a[href*="/ongoing/"], a[href*="/completed/"]'):
            cat_text = cat_link.get_text(strip=True).upper()
            if cat_text in ("ONGOING", "COMPLETED"):
                status = cat_text
                break

        return Drama(
            title=title,
            slug=slug,
            url=url,
            synopsis=synopsis,
            poster=poster,
            country=country,
            status=status,
            episodes_count=episodes_count,
        )

    def _parse_download_section(self, soup: BeautifulSoup) -> list[Episode]:
        """Parse the download table from the drama page.

        dramaday uses a Supsystic table (DataTable) with columns:
        Episode | Quality | Download

        Each quality row has host links: AkiraBox | MEGA | Pixeldrain | Send | Buzzheavier
        Multiple quality rows per episode are separated by <br>.
        """
        seen_episodes: dict[int | float, Episode] = {}

        download_section = self._find_download_section(soup)
        if download_section is None:
            logger.warning("Could not find download section on page")
            return []

        # The table has a header row + data rows
        # Each data row: <td>episode_num</td> <td>quality lines</td> <td>host links</td>
        for row in download_section.select("tbody tr, tr"):
            if not isinstance(row, Tag):
                continue
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            ep_text = cells[0].get_text(strip=True)
            quality_cell = cells[1]
            download_cell = cells[2]

            ep_num = self._parse_episode_number(ep_text)
            if ep_num is None:
                continue

            # Quality labels are separated by <br> in the quality cell
            quality_labels = []
            if isinstance(quality_cell, Tag):
                for child in quality_cell.children:
                    if isinstance(child, Tag) and child.name == "br":
                        continue
                    text = child.strip() if isinstance(child, str) else ""
                    if text:
                        quality_labels.append(text)
                if not quality_labels:
                    qtext = quality_cell.get_text(strip=True)
                    quality_labels = [q.strip() for q in qtext.split("\n") if q.strip()]

            # Download cell has groups of links separated by <br>
            link_groups = self._split_link_groups(download_cell)

            # Match quality labels to link groups
            for i, quality in enumerate(quality_labels):
                if i < len(link_groups):
                    for a in link_groups[i]:
                        href = _attr_str(a, "href", "").strip()
                        if not href or href in ("#", ""):
                            continue
                        host_name = a.get_text(strip=True)
                        if not host_name:
                            continue

                        if ep_num not in seen_episodes:
                            seen_episodes[ep_num] = Episode(number=ep_num, title=f"Episode {ep_num}")
                        seen_episodes[ep_num].links.append(
                            DownloadLink(
                                url=href,
                                label=f"Episode {ep_num}",
                                quality=quality,
                                host=host_name,
                                episode_number=int(ep_num) if isinstance(ep_num, int) else ep_num,
                                link_text=host_name,
                            )
                        )

        episodes = sorted(seen_episodes.values(), key=lambda e: e.number)
        return episodes

    def _split_link_groups(self, cell: Tag) -> list[list[Tag]]:
        """Split download cell into groups of links separated by <br> tags."""
        groups: list[list[Tag]] = []
        current_group: list[Tag] = []

        for child in cell.children:
            if isinstance(child, Tag) and child.name == "br":
                if current_group:
                    groups.append(current_group)
                    current_group = []
            elif isinstance(child, Tag) and child.name == "a":
                current_group.append(child)

        if current_group:
            groups.append(current_group)

        return groups

    def _find_download_section(self, soup: BeautifulSoup) -> Tag | None:
        """Find the download table on the page."""
        entry_content = soup.select_one(".entry-content")
        if isinstance(entry_content, Tag):
            for table in entry_content.select("table"):
                if table.select_one("a[href*='exe.io'], a[href*='cutw.in'], a[href*='ouo.io']"):
                    return table
                if table.select_one("a[href*='mega.nz'], a[href*='pixeldrain']"):
                    return table

        for table in soup.select("table"):
            links = table.select("a[href]")
            for link in links:
                href = _attr_str(link, "href", "")
                if any(
                    d in href
                    for d in [
                        "exe.io",
                        "cutw.in",
                        "ouo.io",
                        "mega.nz",
                        "pixeldrain",
                        "akirabox",
                        "send.cm",
                        "buzzheavier",
                    ]
                ):
                    return table

        return None

    def _parse_episode_number(self, text: str) -> int | float | None:
        """Parse episode number from text like '01', 'Episode 1', 'E01'."""
        text = text.strip()
        if not text:
            return None

        try:
            return int(text)
        except ValueError:
            pass

        match = re.search(r"(?:episode|ep|e)\s*0*(\d+)", text, re.IGNORECASE)
        if match:
            return int(match.group(1))

        match = re.search(r"0*(\d+)", text)
        if match:
            return int(match.group(1))

        return None
