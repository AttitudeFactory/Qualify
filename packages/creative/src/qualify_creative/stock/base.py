"""The shape every stock provider answers with (`docs/plan-integracion-stock-pexels-pixabay.md`
§3.2, R4): one query in, one normalized page out, whichever bank served it.

Pure data and a `Protocol` — no network, no database. A provider (`pixabay.py`, Pexels the
day it hands out keys again, R1) turns its own JSON into `StockItem`s; the service above
(`qualify_api.stock`) adds the cache, the quota and the import, and never sees a vendor
field name.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import httpx


class StockMediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class Orientation(StrEnum):
    PORTRAIT = "portrait"
    SQUARE = "square"
    LANDSCAPE = "landscape"
    ANY = "any"


@dataclass(frozen=True)
class StockQuery:
    text: str  # in Spanish, as the operator typed it
    media_type: StockMediaType = StockMediaType.IMAGE
    orientation: Orientation = Orientation.ANY
    page: int = 1
    per_page: int = 24
    exclude_people: bool = True
    #: Pixabay only (backgrounds, places, food, …) — never "people".
    category: str | None = None


@dataclass(frozen=True)
class StockRendition:
    """The file the import downloads. Its URL may expire (Pixabay's `largeImageURL` is a
    signed `pixabay.com/get/…` link), which is why `StockProvider.resolve_download`
    exists: the import asks the provider again by id instead of trusting a cached URL."""

    url: str
    width: int
    height: int
    label: str  # "large", "medium", …
    fps: float | None = None


@dataclass(frozen=True)
class StockItem:
    provider: str
    provider_media_id: str
    media_type: StockMediaType
    width: int  # the original's size, as the provider reports it
    height: int
    duration_sec: float | None
    thumb_url: str  # shown in the selector only, never stored as a source
    author_name: str
    author_url: str | None
    page_url: str
    description: str  # what the people filter reads (Pixabay: tags)
    best: StockRendition
    #: The author opted out of AI use (Pixabay `noAiTraining`). The provider drops such a
    #: hit from every search: each slot that takes stock today feeds a model in production.
    no_ai: bool = False
    #: A video's smallest rendition, for the selector's preview only (like `thumb_url`,
    #: shown and never stored as a source). "" for an image.
    preview_url: str = ""
    #: The hit as the provider sent it, minus anything that expires or identifies us —
    #: kept as `stock_assets.provider_payload` so a field can be re-read without searching.
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StockPage:
    items: tuple[StockItem, ...]
    page: int
    has_more: bool
    total_hint: int | None
    #: How many hits the client-side filters dropped, by reason ("people", "orientation",
    #: "no_ai", "duration") — what tells, with data, how much a provider really offers.
    dropped: Mapping[str, int] = field(default_factory=dict)


class StockError(Exception):
    """A stock call failed. Never carries the API key nor the vendor's raw body."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class StockNotConfigured(StockError):
    """No key for this provider — the selector reads «no disponible», nothing fails."""


class StockRateLimited(StockError):
    def __init__(self, message: str, *, retry_after_s: int | None = None) -> None:
        super().__init__(message, status_code=429)
        self.retry_after_s = retry_after_s


class StockProvider(Protocol):
    name: str
    media_types: frozenset[StockMediaType]
    #: Closed in code, per provider: may its files go to Seedream/Seedance as a reference
    #: (§5.3, F1). Pixabay and Pexels: True; Vecteezy or Magnific would be False.
    ai_input_allowed: bool
    license_name: str
    license_url: str
    license_terms_date: str  # ISO date of the terms in force when this code was written

    def search(self, query: StockQuery, *, client: httpx.Client | None = None) -> StockPage: ...

    def resolve_download(
        self, item: StockItem, *, client: httpx.Client | None = None
    ) -> StockRendition: ...
