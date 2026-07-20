"""Cross-cutting primitives destined for `packages/shared` in Parte 3.

Everything here is deliberately parser-agnostic and platform-agnostic: the
natural-key helper, the provenance base, the raw-payload wrapper, and the
raw-payload persistence seam. Keeping them isolated means they lift into
`packages/shared` at Parte 3 without a rewrite, and the R2-backed store slots in
behind `RawPayloadStore` with no parser changes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel


class Platform(StrEnum):
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


def make_natural_key(brand_id: UUID, platform: Platform, post_id: str) -> tuple[str, Platform, str]:
    """Idempotency key `(brand_id, platform, post_id)` — the single definition
    used by both the schema layer and any dedup/upsert logic."""
    return (str(brand_id), platform, post_id)


class ScrapeProvenance(BaseModel):
    """Mandatory provenance carried by every parsed object. Non-optional so a
    parsed row can never be built without a reference back to the raw hydration
    payload it came from — raw JSON is always kept so posts can be re-parsed
    without re-scraping (scraping costs money per request).

    `parser_version` and `pipeline_version` are distinct on purpose: the same
    persisted hydration JSON can be re-parsed by an improved parser while
    `scraped_at` / `hydration_json_r2_key` stay fixed, so the row must record
    *which parser* produced it (parser_version) separately from the whole-pipeline
    config it ran under (pipeline_version) for re-parse to stay auditable."""

    hydration_json_r2_key: str
    source_url: str
    scraped_at: datetime
    parser_version: str
    pipeline_version: str


class RawHydration(BaseModel):
    """A raw scrape result: the hydration JSON extracted from a post page plus
    the provenance needed to persist it and re-parse later. `hydration` is the
    parsed JSON object the platform embeds in its page; parsers consume it
    directly. `r2_key` is the key under which the raw payload was persisted."""

    url: str
    hydration: dict[str, Any]
    fetched_at: datetime
    r2_key: str


def raw_payload_key(platform: Platform, url: str) -> str:
    """Stable, URL-derived storage key for a raw payload. Re-scraping the same
    URL yields the same key, so persistence is idempotent at the storage level."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return f"hydration/{platform}/{digest}.json"


class RawPayloadStore(Protocol):
    """Persistence seam for raw hydration payloads. Local-disk implementation
    now; an R2-backed implementation drops in at Parte 3 behind this same
    Protocol with no caller changes."""

    def persist(self, platform: Platform, url: str, payload: dict[str, Any]) -> str: ...


class LocalDiskRawPayloadStore:
    """Writes raw hydration payloads to a local directory. Stand-in for the R2
    store until Parte 3. Returns the storage key (also the future R2 key)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def persist(self, platform: Platform, url: str, payload: dict[str, Any]) -> str:
        key = raw_payload_key(platform, url)
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False))
        return key
