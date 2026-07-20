"""Cross-cutting primitives destined for `packages/shared` in Parte 3.

Everything here is deliberately parser-agnostic and platform-agnostic: the
natural-key helper, the provenance base, the brand-agnostic raw-payload envelope,
and the raw-payload persistence seam. Keeping them isolated means they lift into
`packages/shared` at Parte 3 without a rewrite, and the R2-backed store slots in
behind `RawPayloadStore` with no parser changes.

Raw is a brand-agnostic *content* artifact (ADR 18): the persisted envelope is
keyed by `(platform, url)`, not `brand_id`, so N brands monitoring the same post
share a single scrape. `brand_id` (caller context) and `post_id` (parser-derived)
enter later, when the raw is parsed into a brand-scoped `Post`."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel

PAYLOAD_SCHEMA_VERSION = 1
"""Current version of the raw-payload envelope shape + signature algorithm. Bumped
only when the envelope structure or `content_signature` scheme changes, so a stored
envelope self-describes which canonicalization produced its signature."""


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

    `hydration_json_r2_key` is the key under which the raw envelope was persisted;
    it is produced *only* by `RawPayloadStore.persist`, so a `Post` cannot be
    constructed without the raw having been persisted first (raw-before-parse rule,
    enforced by type dependency).

    `content_signature` pins the exact *content version* the row was derived from
    (`"sha256:<hex>"` over the raw hydration). Because the R2 key is URL-derived and
    overwrite-latest, a later re-scrape can replace the bytes at that key; the stored
    `content_signature` still identifies which content produced this row, giving
    auditable re-parse + staleness detection (envelope signature != row signature
    ⇒ the content changed since parsing).

    `parser_version` and `pipeline_version` are distinct axes on purpose: the same
    persisted hydration can be re-parsed by an improved parser while `scraped_at` /
    `hydration_json_r2_key` stay fixed, so the row records *which parser* produced it
    (parser_version, a parser-internal constant) separately from the whole-pipeline
    config it ran under (pipeline_version, caller-threaded)."""

    hydration_json_r2_key: str
    content_signature: str
    source_url: str
    scraped_at: datetime
    parser_version: str
    pipeline_version: str


def raw_payload_key(platform: Platform, url: str) -> str:
    """Stable, URL-derived storage key for a raw payload. Re-scraping the same
    URL yields the same key, so persistence is idempotent at the storage level
    (overwrite-latest, consistent with the `ReplacingMergeTree` convention)."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return f"hydration/{platform}/{digest}.json"


def canonical_bytes(obj: dict[str, Any]) -> bytes:
    """The single, shared canonical byte form used by both `content_signature`
    and the envelope-commit step, so the bytes written to storage are byte-identical
    to the bytes a signature is computed over — a signature can never be computed
    over different bytes than what is stored.

    `sort_keys=True` makes the output independent of dict key insertion order
    (semantically insignificant). **Arrays are NOT reordered** — array order is
    significant (it derives `MediaItem.ordinal`). `separators=(",", ":")` drops
    ambiguous whitespace; `ensure_ascii=False` keeps unicode byte-faithful (no NFC /
    no normalization, so the payload is not mutated). `allow_nan=False` makes
    `NaN`/`Infinity` (not valid JSON) raise instead of emitting non-deterministic,
    non-interoperable bytes."""
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_signature(hydration: dict[str, Any]) -> str:
    """Tamper-evident identity of a raw hydration payload: `"sha256:<hex>"` over its
    canonical bytes. Same content (any key order) → same signature; any content
    change → a different signature. The self-describing `sha256:` prefix lets the
    algorithm change under a new `payload_schema_version`. This is artifact identity,
    not semantic "did the post meaningfully change" detection (a separate,
    parser-aware concern)."""
    return "sha256:" + hashlib.sha256(canonical_bytes(hydration)).hexdigest()


class RawPayloadEnvelope(BaseModel):
    """Self-describing, brand-agnostic raw scrape artifact (ADR 18) — the single
    model that is both the in-memory capture and the persisted artifact. It carries
    the raw platform `hydration` plus enough metadata to verify and re-parse it.

    Keyed conceptually by `(platform, source_url)`, NOT by `brand_id`: the raw is
    shared platform content, so N brands monitoring the same post reuse one scrape.
    `brand_id` and `post_id` are deliberately absent — they are brand-scoped facts
    applied only when parsing into a `Post`. The R2 key is likewise absent: it is
    `RawPayloadStore.persist`'s return value, not an envelope field.

    `payload_schema_version` versions the SHAPE of the envelope + the signature
    algorithm — a distinct axis from `ScrapeProvenance.parser_version` (the code that
    reads the hydration) and `pipeline_version` (orchestration config)."""

    payload_schema_version: int
    platform: Platform
    source_url: str
    fetched_at: datetime
    content_signature: str
    zyte_request_meta: dict[str, Any] = {}
    hydration: dict[str, Any]


def build_envelope(
    *,
    platform: Platform,
    source_url: str,
    hydration: dict[str, Any],
    fetched_at: datetime,
    zyte_request_meta: dict[str, Any] | None = None,
    payload_schema_version: int = PAYLOAD_SCHEMA_VERSION,
) -> RawPayloadEnvelope:
    """Build + sign a `RawPayloadEnvelope` from a freshly captured hydration payload.
    Stamps `content_signature` over `hydration` (the same dict the envelope carries,
    so its signature matches the bytes that will be persisted) and defaults the
    schema version to the current `PAYLOAD_SCHEMA_VERSION`.

    `zyte_request_meta` is caller-populated (defaults empty); wiring real Zyte
    request metadata from the transport lands in Parte 3. Stays brand-agnostic —
    no `brand_id`/`post_id`; those enter at parse time."""
    return RawPayloadEnvelope(
        payload_schema_version=payload_schema_version,
        platform=platform,
        source_url=source_url,
        fetched_at=fetched_at,
        content_signature=content_signature(hydration),
        zyte_request_meta=zyte_request_meta or {},
        hydration=hydration,
    )


class RawPayloadStore(Protocol):
    """Persistence seam for raw payloads — a pure bytes sink. It derives the key
    from `(platform, source_url)`, writes `body` verbatim, and returns the key. It
    does NOT serialize and does not know `RawPayloadEnvelope`: canonicalization
    happens once, above the store, in `persist_envelope`. Local-disk implementation
    now; the Parte-3 R2 impl is a one-line `put_object(key, body)` behind this same
    Protocol with no caller changes."""

    def persist(self, platform: Platform, source_url: str, body: bytes) -> str: ...


class LocalDiskRawPayloadStore:
    """Writes raw payload bytes to a local directory. Stand-in for the R2 store
    until Parte 3. Returns the storage key (also the future R2 key). Writes `body`
    verbatim — it never re-encodes, so the stored bytes are exactly the canonical
    bytes produced at the commit site."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def persist(self, platform: Platform, source_url: str, body: bytes) -> str:
        key = raw_payload_key(platform, source_url)
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return key


def persist_envelope(store: RawPayloadStore, envelope: RawPayloadEnvelope) -> str:
    """Commit an envelope to the raw-payload store and return its storage key.

    Canonicalization lives here, once, above the store: the persisted bytes are
    `canonical_bytes(envelope.model_dump(mode="json"))`, so the whole self-describing
    envelope (including its embedded `content_signature`) is what lands in storage
    and the artifact is re-verifiable on its own. This is the scrape-worker's persist
    step in Parte 3; the returned key flows into `ScrapeProvenance.hydration_json_r2_key`."""
    body = canonical_bytes(envelope.model_dump(mode="json"))
    return store.persist(envelope.platform, envelope.source_url, body)
