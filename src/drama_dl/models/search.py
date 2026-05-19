"""Search result model for drama-dl."""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel, RootModel


class DramaInfo(BaseModel):
    """A single search result item."""

    title: str = ""
    url: str | None = None
    poster: str | None = None
    episodes_count: int | None = None
    country: str | None = None

    model_config = {"from_attributes": True, "extra": "ignore"}


class Search(RootModel[list[DramaInfo]]):
    """Root model wrapping search results."""

    def __iter__(self) -> Iterator[DramaInfo]:  # type: ignore[override]
        return iter(self.root)

    def __getitem__(self, index: int) -> DramaInfo:
        return self.root[index]

    def __len__(self) -> int:
        return len(self.root)

    def __bool__(self) -> bool:
        return len(self.root) > 0
