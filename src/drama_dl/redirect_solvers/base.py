"""Base class for redirect solvers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class RedirectSolver(ABC):
    """Abstract base class for shortener redirect solvers.

    Each solver handles a specific shortener domain and knows how to
    navigate its redirect chain to reach the final destination URL.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the solver."""
        ...

    @property
    @abstractmethod
    def domains(self) -> list[str]:
        """List of domains this solver can handle."""
        ...

    def can_handle(self, url: str) -> bool:
        """Check if this solver can handle the given URL."""
        return any(domain in url for domain in self.domains)

    @abstractmethod
    def resolve(
        self,
        page,
        url: str,
        status: Callable[[str], None] | None = None,
    ) -> str | None:
        """Resolve the shortener URL to its final destination.

        Args:
            page: Playwright page object (already navigated to URL).
            url: The original shortener URL.
            status: Optional callback for progress messages.

        Returns:
            Final destination URL, or None if resolution failed.
        """
        ...
