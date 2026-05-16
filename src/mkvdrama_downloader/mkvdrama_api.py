"""API client for mkvdrama.net.

Handles:
- Search dramas
- Fetch drama detail page
- Gate/pass verification flow for download panel
- AES-GCM decryption of download data
- Parse download links from decrypted HTML
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from base64 import b64decode
from typing import cast
from urllib.parse import quote

import cloudscraper
import requests  # for exception types (cloudscraper extends requests)
from bs4 import BeautifulSoup, Tag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

from mkvdrama_downloader.models.drama import DownloadLink, Drama, Episode
from mkvdrama_downloader.models.search import DramaInfo, Search

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://mkvdrama.net"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

JSON_HEADERS = {
    "Accept": "application/json",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Origin": BASE_URL,
    "Referer": BASE_URL + "/",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


def _extract_slug(url: str) -> str:
    """Extract the slug/path from a mkvdrama URL."""
    path = url.rstrip("/")
    slug = path.rsplit("/", 1)[-1] if "/" in path else path
    return slug


def _derive_aes_key(path: str) -> bytes:
    """Derive AES-256-GCM key from a path using SHA-256.

    Key = SHA-256('access-payload:' + path)
    where path = gatePath starting with '/'
    """
    if not path.startswith("/"):
        path = "/" + path
    payload = f"access-payload:{path}"
    return hashlib.sha256(payload.encode("utf-8")).digest()


def _hex_to_bytes(hex_str: str) -> bytes:
    """Convert hex string to bytes."""
    return bytes.fromhex(hex_str)


def _attr_str(el: Tag, attr: str, default: str | None = "") -> str | None:
    """Safely get a string attribute from a BeautifulSoup element.

    Args:
        el: BeautifulSoup Tag element.
        attr: Attribute name to extract.
        default: Default if not found — empty string ``""`` or ``None``.

    Returns the attribute value if present and non-empty, else *default*.
    """
    val = el.get(attr)
    if isinstance(val, str):
        return val or default
    if isinstance(val, list):
        joined = " ".join(val)
        return joined or default
    return default


class MkvDramaApi:
    """API client for mkvdrama.net."""

    def __init__(
        self,
        cookie_string: str | None = None,
        flaresolverr_url: str | None = None,
    ) -> None:
        self.session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False},
        )
        self.session.headers.update(DEFAULT_HEADERS)

        self._cookie_str = cookie_string or os.getenv("MKVDRAMA_COOKIE", "")
        if self._cookie_str:
            self.session.headers["Cookie"] = self._cookie_str
            self.session.headers["Origin"] = BASE_URL
            self.session.headers["Referer"] = BASE_URL + "/"

        self._flaresolverr_url = flaresolverr_url or os.getenv("FLARESOLVERR_URL", "")
        self._base_url = BASE_URL

    def search_dramas(self, query: str) -> Search:
        """Search for dramas by query string."""
        url = f"{self._base_url}/?s={quote(query)}"
        logger.info("Searching: %s", url)

        response = self.session.get(url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[DramaInfo] = []
        seen: set[str] = set()

        for article in soup.select("article.bs"):
            link_el = article.select_one(".bsx a")
            if not isinstance(link_el, Tag):
                continue

            title = cast(str, link_el.get("title") or link_el.get_text(strip=True) or "").strip()
            href = _attr_str(link_el, "href")
            if not title or not href or href in seen:
                continue
            seen.add(href)

            url_full = href if href.startswith("http") else f"{self._base_url}{href}"

            img = article.select_one("img")
            poster: str | None = None
            if isinstance(img, Tag):
                poster = _attr_str(img, "data-src", None) or _attr_str(img, "src", None)

            country_el = article.select_one(".country")
            country = country_el.get_text(strip=True) if isinstance(country_el, Tag) else None

            ep_el = article.select_one(".epx")
            episodes_count = None
            if isinstance(ep_el, Tag):
                ep_text = ep_el.get_text(strip=True)
                ep_match = re.search(r"EP\s*(\d+)", ep_text, re.IGNORECASE)
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
            logger.info("No search results, trying direct slug access...")
            direct = self._try_direct_slug(query)
            if direct:
                results.append(direct)

        return Search(results)

    def _try_direct_slug(self, query: str) -> DramaInfo | None:
        """Try to access a drama directly by slug."""
        slug = query.lower().strip()
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")

        url_patterns = [
            f"{self._base_url}/{slug}/",
            f"{self._base_url}/download-{slug}/",
        ]

        for url in url_patterns:
            try:
                response = self.session.get(url, timeout=15, allow_redirects=True)
                if response.status_code != 200:
                    continue
                soup = BeautifulSoup(response.text, "html.parser")
                title_el = soup.select_one("h1.entry-title")
                if not isinstance(title_el, Tag):
                    continue
                title = title_el.get_text(strip=True)
                if not title:
                    continue

                img = soup.select_one(".thumb img")
                poster: str | None = None
                if isinstance(img, Tag):
                    poster = _attr_str(img, "src", None)

                return DramaInfo(
                    title=title,
                    url=url.rstrip("/"),
                    poster=poster,
                )
            except requests.RequestException:
                continue

        return None

    def get_drama(self, url_or_slug: str) -> Drama:
        """Get drama details and episode download links."""
        if url_or_slug.startswith("http"):
            url = url_or_slug.rstrip("/")
        else:
            url = f"{self._base_url}/{url_or_slug.lstrip('/')}".rstrip("/")

        slug = _extract_slug(url)
        logger.info("Fetching drama: %s", url)

        response = self.session.get(url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        drama = self._parse_drama_page(soup, url, slug)

        download_html = self._resolve_download_panel(slug)
        if download_html:
            episodes = self._parse_download_html(download_html)
            self._resolve_c_links(episodes)
            drama.episodes = episodes

        return drama

    def _parse_drama_page(self, soup: BeautifulSoup, url: str, slug: str) -> Drama:
        """Parse drama metadata from the HTML page."""
        title_el = soup.select_one("h1.entry-title")
        title = title_el.get_text(strip=True) if isinstance(title_el, Tag) else slug.replace("-", " ").title()

        synopsis_el = soup.select_one(".entry-content p")
        synopsis = synopsis_el.get_text(strip=True) if isinstance(synopsis_el, Tag) else ""

        img = soup.select_one(".thumb img")
        poster: str | None = None
        if isinstance(img, Tag):
            poster = _attr_str(img, "src")

        country = None
        status = None
        drama_type = None
        episodes_count = None

        for item in soup.select(".spe .info-item"):
            text = item.get_text(strip=True)
            if text.startswith("Country:"):
                country = text.replace("Country:", "").strip()
            elif text.startswith("Status:"):
                status = text.replace("Status:", "").strip()
            elif text.startswith("Type:"):
                drama_type = text.replace("Type:", "").strip()
            elif text.startswith("Episodes:"):
                ep_str = text.replace("Episodes:", "").strip()
                try:
                    episodes_count = int(ep_str)
                except ValueError:
                    pass

        return Drama(
            title=title,
            slug=slug,
            url=url,
            synopsis=synopsis,
            poster=poster,
            country=country,
            status=status,
            type=drama_type,
            episodes_count=episodes_count,
        )

    def _resolve_download_panel(self, slug: str) -> str | None:
        """Execute the gate/pass API flow to get the download panel HTML.

        Flow:
        1. POST /{slug}/_jfsc_je_lou → {gatePath, passPath, honeypotKey}
        2. POST {gatePath} → verification (sets cookies)
        3. POST {passPath} → {d, s} (encrypted HTML)
        4. Decrypt {d, s} with AES-256-GCM
        """
        try:
            init_url = f"{self._base_url}/{slug}/_jfsc_je_lou"
            logger.debug("Step 1: POST %s", init_url)

            init_resp = self.session.post(
                init_url,
                headers=JSON_HEADERS,
                timeout=15,
            )
            if init_resp.status_code != 200:
                logger.warning("Gate init failed: %d", init_resp.status_code)
                return None

            init_data = init_resp.json()
            gate_path: str = init_data.get("gate_path", "")
            pass_path: str = init_data.get("pass_path", "")
            honeypot_key: str = init_data.get("dec_key", "")

            if not gate_path or not pass_path or not honeypot_key:
                logger.warning("Missing gate/pass paths or dec_key in init response")
                return None

            gate_url = f"{self._base_url}{gate_path}"
            pass_url = f"{self._base_url}{pass_path}"

            # Step 2: Gate verification
            logger.debug("Step 2: POST %s", gate_url)
            gate_body = {"r": None, "i": True, "w": False, honeypot_key: ""}
            gate_resp = self.session.post(gate_url, json=gate_body, headers=JSON_HEADERS, timeout=15)
            if gate_resp.status_code not in (200, 204):
                logger.warning("Gate verification failed: %d", gate_resp.status_code)
                return None

            # Step 3: Pass - get encrypted data
            logger.debug("Step 3: POST %s", pass_url)
            pass_body = {"r": None, "w": False, honeypot_key: ""}
            pass_resp = self.session.post(pass_url, json=pass_body, headers=JSON_HEADERS, timeout=15)
            if pass_resp.status_code != 200:
                logger.warning("Pass request failed: %d", pass_resp.status_code)
                return None

            pass_data = pass_resp.json()
            encrypted_data: str = pass_data.get("d", "")
            iv_hex: str = pass_data.get("s", "")

            if not encrypted_data or not iv_hex:
                logger.warning("Missing encrypted data in pass response")
                return None

            logger.debug("Step 4: Decrypting with AES-256-GCM")
            return self._decrypt_download_data(encrypted_data, iv_hex, gate_path)

        except requests.RequestException as e:
            logger.warning("Download panel request failed: %s", e)
            return None
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Download panel parsing failed: %s", e)
            return None

    def _decrypt_download_data(self, encrypted_b64: str, iv_hex: str, slug: str) -> str | None:
        """Decrypt AES-256-GCM encrypted download data."""
        try:
            key = _derive_aes_key(slug)
            iv = _hex_to_bytes(iv_hex)
            ciphertext = b64decode(encrypted_b64)

            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(iv, ciphertext, None)

            return plaintext.decode("utf-8")
        except Exception as e:
            logger.warning("Decryption failed: %s", e)
            return None

    def _resolve_url(self, url: str) -> str:
        """Resolve a potentially relative URL to absolute."""
        if not url or url.startswith("http://") or url.startswith("https://"):
            return url
        if url.startswith("/"):
            return f"{self._base_url}{url}"
        return url

    def _parse_download_html(self, html: str) -> list[Episode]:
        """Parse download links from decrypted HTML."""
        soup = BeautifulSoup(html, "html.parser")
        seen_episodes: dict[int | float, Episode] = {}

        for section in soup.select(".soraddlx, .soraddl, .soradd"):
            if isinstance(section, Tag):
                self._parse_download_section(section, seen_episodes)

        for link_el in soup.select("[data-riwjd]"):
            if isinstance(link_el, Tag):
                self._parse_token_link(link_el, soup, seen_episodes)

        for link_el in soup.select('a[href*="ouo.io"], a[href*="filecrypt"]'):
            if isinstance(link_el, Tag):
                self._parse_direct_link(link_el, seen_episodes)

        episodes = sorted(seen_episodes.values(), key=lambda e: e.number)
        return episodes

    def resolve_episode_shorteners(
        self,
        episodes: list[Episode],
        *,
        resolve: bool = False,
    ) -> None:
        """Resolve ouo.io/oii.la shortener URLs using Playwright/FlareSolverr.

        Args:
            episodes: Episode list whose links to resolve.
            resolve: Force resolution even without FlareSolverr configured.
        """
        from mkvdrama_downloader.shortener import is_shortener_url, resolve_shorteners

        resolve_enabled = resolve or bool(self._flaresolverr_url)
        if not resolve_enabled:
            return

        # Collect unique shortener URLs
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

    def _resolve_c_links(
        self,
        episodes: list[Episode],
    ) -> None:
        """Resolve _c/ internal redirect links to actual shortener URLs.

        The _c/ links are internal proxy URLs that redirect to ouo.io or
        filecrypt. Following them through the authenticated session reveals
        the actual shortener URL.
        """
        for episode in episodes:
            for link in episode.links:
                if "/_c/" not in link.url:
                    continue
                try:
                    resp = self.session.get(
                        link.url,
                        allow_redirects=True,
                        timeout=10,
                        headers={
                            "Referer": self._base_url + "/",
                            "Accept": "text/html,*/*",
                        },
                    )
                    if resp.status_code < 400 and resp.url != link.url:
                        # Reject Cloudflare/Turnstile challenge URLs
                        final = resp.url
                        if "turnstile" not in final and "challenge" not in final and "_c/" not in final:
                            logger.debug("Resolved _c/ link: %s -> %s", link.url, final)
                            link.url = final
                        else:
                            logger.debug("Rejected _c/ resolution (challenge page): %s", final)
                    elif resp.status_code == 403:
                        logger.debug("_c/ link access denied (403): %s", link.url)
                except Exception as e:
                    logger.debug("Failed to resolve _c/ link %s: %s", link.url, e)

    def _parse_download_section(
        self,
        section: Tag,
        seen: dict[int | float, Episode],
    ) -> None:
        """Parse a download section (.soraddlx) for episode links."""
        label_el = section.select_one(".sorattlx, .sorattl, .soratt, h3, h4")
        label = label_el.get_text(strip=True) if isinstance(label_el, Tag) else ""

        ep_range = self._extract_episode_range(label)

        for link_box in section.select(".soraurlx, .soraurl"):
            if not isinstance(link_box, Tag):
                continue

            quality_el = link_box.select_one("strong, b")
            quality = quality_el.get_text(strip=True) if isinstance(quality_el, Tag) else ""

            for link in link_box.select("a[href]"):
                if not isinstance(link, Tag):
                    continue

                href = _attr_str(link, "href").strip()
                if not href or href in ("#", "", "javascript:;"):
                    continue
                href = self._resolve_url(href)

                host_el = link_box.select_one("[data-oc2le], [data-07cgr]")
                host: str | None = None
                if isinstance(host_el, Tag):
                    host = _attr_str(host_el, "data-oc2le", None) or _attr_str(host_el, "data-07cgr", None)

                dl = DownloadLink(
                    url=href,
                    label=label,
                    quality=quality,
                    host=host,
                    episode_number=ep_range[0] if ep_range else None,
                    link_text=cast(str, link.get_text(strip=True)),
                )
                self._add_link_range(seen, ep_range, dl)

    def _parse_token_link(
        self,
        el: Tag,
        soup: BeautifulSoup,
        seen: dict[int | float, Episode],
    ) -> None:
        """Parse an element with token-based download URL."""
        token_raw = _attr_str(el, "data-riwjd")
        if not token_raw:
            return

        decoded_url = self._decode_token(token_raw)
        if not decoded_url:
            return

        token_url = f"{self._base_url}/?mkv_token={quote(decoded_url)}"

        container = el.find_parent("div")
        label = ""
        if isinstance(container, Tag):
            label_el = container.select_one(".sorattlx, .sorattl, h2, h3, h4")
            if isinstance(label_el, Tag):
                label = label_el.get_text(strip=True)
            else:
                ep_container = el.find_parent("[data-4xptf]")
                if isinstance(ep_container, Tag):
                    label = _attr_str(ep_container, "data-4xptf")

        ep_range = self._extract_episode_range(label)

        parent = el.find_parent()
        host: str | None = None
        if isinstance(parent, Tag):
            host_el = parent.select_one("[data-oc2le], [data-07cgr]")
            if isinstance(host_el, Tag):
                host = _attr_str(host_el, "data-oc2le") or _attr_str(host_el, "data-07cgr")

        dl = DownloadLink(
            url=token_url,
            label=label,
            quality="",
            host=host,
            episode_number=ep_range[0] if ep_range else None,
            link_text=label,
        )
        self._add_link_range(seen, ep_range, dl)

    def _parse_direct_link(
        self,
        el: Tag,
        seen: dict[int | float, Episode],
    ) -> None:
        """Parse a direct ouo.io or filecrypt link."""
        href = _attr_str(el, "href").strip()
        if not href or href in ("#", ""):
            return
        href = self._resolve_url(href)

        container = el.find_parent("li, p, div")
        label = ""
        if isinstance(container, Tag):
            label_el = container.select_one("h1, h2, h3, h4, h5, strong, b")
            if isinstance(label_el, Tag):
                label = label_el.get_text(strip=True)

            quality_el = container.select_one("strong, b")
            if isinstance(quality_el, Tag):
                quality = quality_el.get_text(strip=True)
            else:
                quality = ""
        else:
            quality = ""

        ep_range = self._extract_episode_range(label)

        dl = DownloadLink(
            url=href,
            label=label,
            quality=quality,
            episode_number=ep_range[0] if ep_range else None,
            link_text=cast(str, el.get_text(strip=True)),
        )
        self._add_link_range(seen, ep_range, dl)

    def _extract_episode_range(self, label: str) -> tuple[int, int] | None:
        """Extract episode number or range from a label string.

        Returns (start, end) tuple, e.g.:
        - "Episode 3" -> (3, 3)
        - "Episode 01 - 06" -> (1, 6)
        - "Episodes 1-13" -> (1, 13)
        - "E12" -> (12, 12)
        """
        if not label:
            return None

        # Pattern 1: "Episode 01 - 06", "Episodes 1-13", "EP 1 - 12"
        range_patterns = [
            r"(?:episode|episodes|ep|eps|ep\.)\s*(\d{1,4})\s*(?:-|–|—|to)\s*(\d{1,4})",
            r"\bE(\d{1,4})\s*(?:-|–|—)\s*E?(\d{1,4})\b",
        ]
        for pattern in range_patterns:
            match = re.search(pattern, label, re.IGNORECASE)
            if match:
                start, end = int(match.group(1)), int(match.group(2))
                if 0 < start <= end:
                    return (start, end)

        # Pattern 2: Single episode number
        single_patterns = [
            r"(?:episode|episodes|ep|eps|ep\.)\s*(\d{1,4})",
            r"\bE(\d{1,4})\b",
            r"^\s*0*(\d{1,4})\s*$",
        ]
        for pattern in single_patterns:
            match = re.search(pattern, label, re.IGNORECASE)
            if match:
                num = int(match.group(1))
                return (num, num)

        return None

    def _decode_token(self, token: str) -> str | None:
        """Decode a base64-encoded download token."""
        try:
            decoded = b64decode(token).decode("utf-8").strip()
            return decoded if decoded else None
        except Exception:
            return None

    def _add_link_range(
        self,
        seen: dict[int | float, Episode],
        ep_range: tuple[int, int] | None,
        link: DownloadLink,
    ) -> None:
        """Add a download link to episode(s), expanding ranges into individual episodes.

        For a range like (1, 6), the link is added to episodes 1 through 6.
        For None, the link is added to episode 0 (unknown).
        """
        if ep_range is None:
            # Unknown episode number
            if 0 not in seen:
                seen[0] = Episode(number=0, title="Unknown Episode")
            seen[0].links.append(link)
            return

        start, end = ep_range
        for ep_num in range(start, end + 1):
            if ep_num not in seen:
                seen[ep_num] = Episode(number=ep_num, title=f"Episode {ep_num}")
            seen[ep_num].links.append(link)
