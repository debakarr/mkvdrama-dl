"""Provider registry and auto-detection for drama-dl."""

from __future__ import annotations

from drama_dl.providers.base import DramaProvider
from drama_dl.providers.dramaday import DramadayProvider
from drama_dl.providers.mkvdrama import MkvDramaProvider

PROVIDERS: list[type[DramaProvider]] = [MkvDramaProvider, DramadayProvider]


def detect_provider(url: str) -> DramaProvider | None:
    """Auto-detect provider from URL domain."""
    for provider_cls in PROVIDERS:
        for domain in provider_cls.DOMAINS:
            if domain in url:
                return provider_cls()
    return None


def list_providers() -> list[DramaProvider]:
    """Return all available providers."""
    return [p() for p in PROVIDERS]
