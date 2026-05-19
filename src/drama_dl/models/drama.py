"""Drama and episode models for drama-dl."""

from __future__ import annotations

from pydantic import BaseModel


class DownloadLink(BaseModel):
    """A download link for an episode."""

    url: str = ""
    label: str = ""
    quality: str = ""
    host: str | None = None
    episode_number: int | None = None
    link_text: str = ""


class Episode(BaseModel):
    """An episode with its download links."""

    number: int | float = 0
    title: str = ""
    links: list[DownloadLink] = []


class Drama(BaseModel):
    """Full drama detail including episodes."""

    title: str = ""
    slug: str = ""
    url: str = ""
    synopsis: str = ""
    poster: str | None = None
    country: str | None = None
    status: str | None = None
    type: str | None = None
    episodes_count: int | None = None
    episodes: list[Episode] = []

    model_config = {"from_attributes": True, "extra": "ignore"}
