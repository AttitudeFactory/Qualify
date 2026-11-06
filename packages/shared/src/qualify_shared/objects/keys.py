"""Tenant prefixing for the object plane — the RLS equivalent for R2 (ADR 22/24).

The prefix is NOT invented here. `qualify_scraper.shared.raw_payload_key` already emits
`t/{tenant_id}/fp/{platform}/{connection_id}/{object_id}` for first-party payloads,
deliberately disjoint from the brand-agnostic `scrape/...` space (ADR 18/R5). Media written
by the publisher joins that same namespace rather than opening a second convention, so
"delete everything belonging to this tenant" stays a single delete-by-prefix.

Why enforcement lives here and not in the publisher: an isolation rule that each caller
re-implements is a rule that one caller eventually gets wrong. `require_tenant_prefix` is
the only place the invariant is expressed, and the gate calls it on every read AND every
write — including reads, because a key that came back from a database row is still input.
"""

from __future__ import annotations

import re
from uuid import UUID


class TenantPrefixViolation(Exception):
    """An object key does not sit under its tenant's prefix.

    Raised rather than silently corrected. A key outside the prefix is either a bug in key
    construction or an attempt to reach another tenant's objects, and both must be loud —
    "helpfully" rewriting the key would turn the second case into a silent success.
    """


def tenant_prefix(tenant_id: UUID) -> str:
    """The sole prefix under which a tenant's objects may live. Trailing slash included so
    that `t/{a}/` can never prefix-match `t/{ab}/...`."""
    return f"t/{tenant_id}/"


def media_key(tenant_id: UUID, connection_id: UUID, media_id: str) -> str:
    """Storage key for a composed media asset awaiting publication.

    Keyed by `connection_id` (not by brand) because a media asset belongs to the account it
    will be published to, and by an opaque `media_id` the caller owns. Scheduling is what
    forces this to exist at all: a reel composed today and scheduled for next Tuesday needs
    somewhere durable to live in between (ADR 28d).
    """
    return f"{tenant_prefix(tenant_id)}media/{connection_id}/{media_id}"


#: The Galería's root, deliberately OUTSIDE `t/` (founder, 2026-11-06, m-24971181): the
#: production bucket keeps a lock rule on `t/` that refuses deletes and overwrites, and
#: the Galería must really delete what the owner removes or cuts away (D4, ADR 47).
GALLERY_ROOT = "gallery/"
_GALLERY_FILE = re.compile(r"[a-z0-9][a-z0-9_-]*\.[a-z0-9]{2,5}")


def gallery_root(tenant_id: UUID) -> str:
    """The tenant's Galería root, `gallery/{tenant}/` (ADR 47 + ADR 39 amendment): business
    photos and videos, one folder per medium. Never under `t/`."""
    if not isinstance(tenant_id, UUID):
        raise TenantPrefixViolation("a gallery root is addressed by the tenant's UUID")
    return f"{GALLERY_ROOT}{tenant_id}/"


def gallery_media_prefix(tenant_id: UUID, media_id: UUID) -> str:
    """One Galería medium's folder, `gallery/{tenant}/{media_id}/`, built from UUIDs only
    (`video.mp4` + `poster.jpg`, or `photo.jpg`, live inside)."""
    if not isinstance(media_id, UUID):
        raise TenantPrefixViolation("a gallery medium is addressed by its UUID")
    return f"{gallery_root(tenant_id)}{media_id}/"


def gallery_media_key(tenant_id: UUID, media_id: UUID, filename: str) -> str:
    """One file of a Galería medium: `gallery/{tenant}/{media_id}/{filename}`, where the
    file name is a plain lower-case name (`video.mp4`, `poster.jpg`, `photo.jpg`) — no
    slash, no traversal."""
    if not _GALLERY_FILE.fullmatch(filename or ""):
        raise TenantPrefixViolation("not a gallery file name")
    return gallery_media_prefix(tenant_id, media_id) + filename


def tenant_roots(tenant_id: UUID) -> tuple[str, str]:
    """Every prefix this tenant's objects may live under: `t/{tenant}/` and the Galería's
    `gallery/{tenant}/`."""
    return (tenant_prefix(tenant_id), gallery_root(tenant_id))


def is_object_store_key(key: str | None) -> bool:
    """Whether a stored key names an object in R2 (`t/…` or `gallery/…`) rather than a file
    of the local upload store."""
    return bool(key) and (key.startswith("t/") or key.startswith(GALLERY_ROOT))


def require_tenant_object(tenant_id: UUID, object_key: str) -> str:
    """Like `require_tenant_prefix`, but also accepts this tenant's Galería
    (`gallery/{tenant}/…`). Used by the gate's READS (`open_object`, `sha256`,
    `object_size`, `open_range`), which serve both roots; writes to the Galería go only
    through `ObjectGate.put_gallery_media`, which builds the key itself."""
    if ".." in object_key:
        raise TenantPrefixViolation("object key contains '..'")
    if not any(object_key.startswith(root) for root in tenant_roots(tenant_id)):
        raise TenantPrefixViolation("object key is not under one of the tenant's roots")
    return object_key


def require_tenant_prefix(tenant_id: UUID, object_key: str) -> str:
    """Return `object_key` unchanged if it sits under this tenant's prefix; raise otherwise.

    Also rejects `..` outright. Path traversal is not expressible through the gate's public
    surface today (callers pass whole keys, never fragments joined onto a base), but this
    module is the one place that would have to change for that to stop being true, so the
    check belongs here rather than in a comment predicting good behaviour.
    """
    if ".." in object_key:
        raise TenantPrefixViolation("object key contains '..'")
    prefix = tenant_prefix(tenant_id)
    if not object_key.startswith(prefix):
        # The offending key is NOT echoed: it may carry another tenant's identifier, and an
        # exception message is a log line waiting to happen.
        raise TenantPrefixViolation(f"object key does not start with the tenant prefix {prefix!r}")
    return object_key
