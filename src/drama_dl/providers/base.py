"""Provider base interface for drama-dl."""

from __future__ import annotations

from abc import ABC, abstractmethod

from drama_dl.models.drama import Drama, Episode
from drama_dl.models.search import Search


class DramaProvider(ABC):
    """Abstract base for drama download site providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""

    @property
    @abstractmethod
    def domains(self) -> list[str]:
        """URL domains this provider handles."""

    @abstractmethod
    def search(self, query: str) -> Search:
        """Search for dramas."""

    @abstractmethod
    def get_drama(self, url: str) -> Drama:
        """Fetch drama details and episode links."""

    @abstractmethod
    def resolve_shorteners(
        self,
        episodes: list[Episode],
        max_workers: int = 4,
    ) -> None:
        """Resolve shortener URLs to final destinations.

        Args:
            episodes: Episode list whose links should be resolved in-place.
            max_workers: Max parallel browser pages for resolution.
        """
