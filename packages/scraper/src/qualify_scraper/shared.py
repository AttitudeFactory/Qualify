"""Cross-cutting primitives destined for `packages/shared` in Parte 3.

Everything here is deliberately parser-agnostic and platform-agnostic: the
natural-key helper, the provenance base, the raw-payload envelope (v2), and the
raw-payload persistence seam. Keeping them isolated means they lift into
`packages/shared` at Parte 3 without a rewrite, and the R2-backed store slots in
behind `RawPayloadStore` with no parser changes.

The envelope now spans two *source classes* (ADR 22 / Sprint-1 amendment R5):

- `SCRAPE` — brand-agnostic *content* artifact (ADR 18): keyed by `(platform, url)`,
  never by `brand_id` or `tenant_id`, so N brands monitoring the same post share a
  single scrape. `brand_id`/`post_id` enter only when the raw is parsed into a `Post`.
- `FIRST_PARTY_API` — a consented Graph-API response, never shareable across tenants.
  Its storage key is tenant-prefixed and keyed by `(connection_id, object_id)`
  overwrite-latest (R5), a disjoint key space from `SCRAPE`.

Isolation is a property of the *storage path* (the key prefix), not of content
identity: `content_signature` stays a pure hash of the payload bytes (dedup,
auditable re-parse, staleness), with no tenant salt and no role in the key (R5).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel, model_validator

PAYLOAD_SCHEMA_VERSION = 2
"""Current version of the raw-payload envelope shape + signature algorithm. Bumped
only when the envelope structure or `content_signature` scheme changes, so a stored
envelope self-describes which canonicalization produced its signature. v2 adds
`source_class`/`transport`/`tenant_id`/`connection_id`/`object_id` and renames
`zyte_request_meta` -> `transport_meta`."""


class Platform(StrEnum):
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


class SourceClass(StrEnum):
    """The legal/economic nature of a raw payload — orthogonal to `transport` (the
    concrete channel it arrived over)."""

    SCRAPE = "scrape"  # ADR 18: brand-agnostic, N brands share one scrape
    FIRST_PARTY_API = "first_party_api"  # consented Graph-API data, never shareable


# Query-string / metadata keys that may carry a credential. Stripped before an
# envelope is built or signed, so a token can never land in a persisted artifact
# (a token in an archived payload is a *persistent* leak — integracion doc §2.6).
_CREDENTIAL_KEYS = frozenset(
    {
        "access_token",
        "client_secret",
        "appsecret_proof",
        "code",
        "input_token",
        "fb_exchange_token",
    }
)


def make_natural_key(brand_id: UUID, platform: Platform, post_id: str) -> tuple[str, Platform, str]:
    """Idempotency key `(brand_id, platform, post_id)` — the single definition
    used by both the schema layer and any dedup/upsert logic."""
    return (str(brand_id), platform, post_id)


def sanitize_source_url(url: str) -> str:
    """Drop credential-bearing query params from a URL before it is signed/archived.
    A public scrape URL has none (no-op); a first-party Graph request URL carries the
    `access_token` — it must never survive into the envelope, key, or logs."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _CREDENTIAL_KEYS
    ]
    return urlunsplit(parts._replace(query=urlencode(kept)))


def sanitize_transport_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Recursively drop credential-keyed fields from transport metadata. Non-credential
    transport facts (request id, cost, timing, rate-limit headers) are preserved."""
    return {
        k: (sanitize_transport_meta(v) if isinstance(v, dict) else v)
        for k, v in meta.items()
        if k not in _CREDENTIAL_KEYS
    }


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
    (`"sha256:<hex>"` over the raw hydration). Because storage is overwrite-latest, a
    later re-fetch can replace the bytes at that key; the stored `content_signature`
    still identifies which content produced this row, giving auditable re-parse +
    staleness detection (envelope signature != row signature => content changed).

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
    parser-aware concern). Never salted by tenant — identity is a property of the
    content, isolation is a property of the storage path (R5)."""
    return "sha256:" + hashlib.sha256(canonical_bytes(hydration)).hexdigest()


class RawPayloadEnvelope(BaseModel):
    """Self-describing raw scrape/first-party artifact — the single model that is both
    the in-memory capture and the persisted artifact. It carries the raw platform
    `hydration` plus enough metadata to verify and re-parse it.

    `source_class` splits two disjoint identities (see module docstring): `SCRAPE` is
    brand-agnostic and tenant-free; `FIRST_PARTY_API` requires `tenant_id`,
    `connection_id` and `object_id` (enforced below) — an envelope that would emit an
    un-prefixed key for consented data is *unconstructible*.

    `object_id` (first-party only) is the caller-composed logical-object identity used
    by the key: the Graph node id for a node fetch, or `"{parent_node_id}/{edge}"`
    (optionally `.../p{n}` when paginated) for an edge fetch.

    The R2 key is deliberately absent — it is derived above the store by
    `raw_payload_key(env)`, not stored on the envelope. `brand_id`/`post_id` are absent
    too: they are brand-scoped facts applied only when parsing into a `Post`.

    `payload_schema_version` versions the SHAPE of the envelope + the signature
    algorithm — a distinct axis from `ScrapeProvenance.parser_version` and
    `pipeline_version`."""

    payload_schema_version: int = PAYLOAD_SCHEMA_VERSION
    source_class: SourceClass
    transport: str
    platform: Platform
    source_url: str
    tenant_id: UUID | None = None
    connection_id: UUID | None = None
    object_id: str | None = None
    fetched_at: datetime
    content_signature: str
    transport_meta: dict[str, Any] = {}
    hydration: dict[str, Any]

    @model_validator(mode="after")
    def _check_source_class_invariants(self) -> RawPayloadEnvelope:
        tenant_scoped = ("tenant_id", "connection_id", "object_id")
        if self.source_class is SourceClass.FIRST_PARTY_API:
            missing = [name for name in tenant_scoped if getattr(self, name) is None]
            if missing:
                raise ValueError(f"first_party_api envelope requires {', '.join(missing)}")
        else:  # SCRAPE must stay brand-agnostic / tenant-free (ADR 18)
            present = [name for name in tenant_scoped if getattr(self, name) is not None]
            if present:
                raise ValueError(
                    f"scrape envelope must not carry tenant-scoped fields: {', '.join(present)}"
                )
        return self

    @model_validator(mode="after")
    def _check_object_id_is_not_a_traversal(self) -> RawPayloadEnvelope:
        """`object_id` feeds directly into `raw_payload_key()` and, downstream, into
        `LocalDiskRawPayloadStore.persist`'s filesystem path (dev/test store only — R2
        keys are opaque strings with no path semantics, so this is contained to disk).
        Multi-segment ids ARE legitimate (`"{node}/{edge}"`, optionally `.../p{n}` for
        pagination — see `test_edge_object_id_survives_into_key`), so this validates
        per path SEGMENT rather than rejecting `/` outright: no empty segment (also
        catches a leading/trailing `/` or `//`), no `.`/`..` segment (traversal), and no
        control characters anywhere in the string. Validated here, above the store, per
        ADR 22 reasoning 3 — the same argument that put key derivation above the store
        applies to input constraints: validate once, and every future store impl
        (including R2) inherits the guarantee for free."""
        if self.object_id is None:
            return self
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in self.object_id):
            raise ValueError("object_id must not contain control characters")
        segments = self.object_id.split("/")
        if any(segment in ("", ".", "..") for segment in segments):
            raise ValueError(
                f"object_id must not contain empty, '.', or '..' path segments: {self.object_id!r}"
            )
        return self


def _url_hash(url: str) -> str:
    """Stable digest of a source URL for the scrape key space."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def raw_payload_key(env: RawPayloadEnvelope) -> str:
    """Derive a raw payload's storage key FROM THE ENVELOPE, above the store — the
    single place the two disjoint key spaces are defined (ADR 22, reasoning 3: if each
    store derived its own key, each impl would re-implement isolation and any one could
    get it wrong). The store is a pure `(key, body)` sink.

    - `SCRAPE` → `scrape/{platform}/{url_hash}`: brand-agnostic, URL-derived,
      overwrite-latest (ADR 18) — N brands share one scrape.
    - `FIRST_PARTY_API` → `t/{tenant_id}/fp/{platform}/{connection_id}/{object_id}`:
      tenant-prefixed, keyed by logical object, overwrite-latest (R5).

    The two prefixes (`scrape/…` vs `t/{tenant_id}/fp/…`) never overlap: isolation is
    by construction of the path, and targeted deletion of a tenant's raw is a
    delete-by-prefix. The first-party fields are guaranteed non-None by the envelope
    validator, so this branch cannot emit an un-prefixed key."""
    if env.source_class is SourceClass.SCRAPE:
        return f"scrape/{env.platform}/{_url_hash(env.source_url)}"
    return f"t/{env.tenant_id}/fp/{env.platform}/{env.connection_id}/{env.object_id}"


def build_scrape_envelope(
    *,
    platform: Platform,
    source_url: str,
    hydration: dict[str, Any],
    fetched_at: datetime,
    transport: str = "zyte",
    transport_meta: dict[str, Any] | None = None,
    payload_schema_version: int = PAYLOAD_SCHEMA_VERSION,
) -> RawPayloadEnvelope:
    """Build + sign a brand-agnostic `SCRAPE` envelope (ADR 18). Stamps
    `content_signature` over `hydration` and sanitizes `source_url`/`transport_meta`
    so no credential can leak into the artifact. No `brand_id`/`post_id` — those enter
    at parse time; no tenant fields — a scrape is tenant-free."""
    return RawPayloadEnvelope(
        payload_schema_version=payload_schema_version,
        source_class=SourceClass.SCRAPE,
        transport=transport,
        platform=platform,
        source_url=sanitize_source_url(source_url),
        fetched_at=fetched_at,
        content_signature=content_signature(hydration),
        transport_meta=sanitize_transport_meta(transport_meta or {}),
        hydration=hydration,
    )


def build_first_party_envelope(
    *,
    platform: Platform,
    source_url: str,
    hydration: dict[str, Any],
    fetched_at: datetime,
    tenant_id: UUID,
    connection_id: UUID,
    object_id: str,
    transport: str = "graph_api",
    transport_meta: dict[str, Any] | None = None,
    payload_schema_version: int = PAYLOAD_SCHEMA_VERSION,
) -> RawPayloadEnvelope:
    """Build + sign a `FIRST_PARTY_API` envelope. `tenant_id`/`connection_id`/
    `object_id` are required kwargs — the only entry point for consented data makes an
    un-prefixed (leaky) envelope unconstructible, with the model validator as backstop.
    `source_url` (the Graph request URL) and `transport_meta` are sanitized so the
    `access_token` never survives into the persisted artifact."""
    return RawPayloadEnvelope(
        payload_schema_version=payload_schema_version,
        source_class=SourceClass.FIRST_PARTY_API,
        transport=transport,
        platform=platform,
        source_url=sanitize_source_url(source_url),
        tenant_id=tenant_id,
        connection_id=connection_id,
        object_id=object_id,
        fetched_at=fetched_at,
        content_signature=content_signature(hydration),
        transport_meta=sanitize_transport_meta(transport_meta or {}),
        hydration=hydration,
    )


class RawPayloadStore(Protocol):
    """Persistence seam for raw payloads — a pure `(key, body)` bytes sink. It does NOT
    derive the key (that happens once, above the store, in `raw_payload_key`) and does
    NOT serialize (canonicalization happens once, above the store, in
    `persist_envelope`). It writes `body` verbatim and returns the key. Local-disk
    implementation now; the Parte-3 R2 impl is a one-line `put_object(key, body)`
    behind this same Protocol with no caller changes."""

    def persist(self, key: str, body: bytes) -> str: ...


class LocalDiskRawPayloadStore:
    """Writes raw payload bytes to a local directory. Stand-in for the R2 store until
    Parte 3. Returns the storage key (also the future R2 key). Writes `body` verbatim —
    it never re-encodes, so the stored bytes are exactly the canonical bytes produced
    at the commit site."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def persist(self, key: str, body: bytes) -> str:
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return key


def persist_envelope(store: RawPayloadStore, envelope: RawPayloadEnvelope) -> str:
    """Commit an envelope to the raw-payload store and return its storage key.

    Both the key derivation (`raw_payload_key`) and canonicalization live here, once,
    above the store: the persisted bytes are `canonical_bytes(envelope.model_dump)`, so
    the whole self-describing envelope (including its embedded `content_signature`) is
    what lands in storage and the artifact is re-verifiable on its own. This is the
    scrape/first-party worker's persist step; the returned key flows into
    `ScrapeProvenance.hydration_json_r2_key`."""
    key = raw_payload_key(envelope)
    body = canonical_bytes(envelope.model_dump(mode="json"))
    return store.persist(key, body)
