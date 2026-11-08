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


#: The root of the reel cuts a part in `edit` mode sends to Seedance (VE-04d), also OUTSIDE
#: `t/` for the same bucket lock (m-24921060, founder's OK 2026-11-06): ADR 44 F9 says a
#: foreign reel lives 30 days, so its cuts must really be deletable (VE-12 RA5), while the
#: piece that used them lives 90 under `t/`. Named for what it holds — cuts of a REEL, not
#: a generic «windows» — and kept apart from `gallery/` (the owner's own media, with its own
#: lifecycle and reconciler).
REEL_WINDOWS_ROOT = "reel-windows/"


def reel_windows_root(tenant_id: UUID) -> str:
    """The tenant's root for reel cuts, `reel-windows/{tenant}/`."""
    if not isinstance(tenant_id, UUID):
        raise TenantPrefixViolation("a reel-windows root is addressed by the tenant's UUID")
    return f"{REEL_WINDOWS_ROOT}{tenant_id}/"


def source_window_prefix(tenant_id: UUID, draft_id: UUID) -> str:
    """One part's folder of reel cuts, `reel-windows/{tenant}/{draft_id}/` (UUIDs only)."""
    if not isinstance(draft_id, UUID):
        raise TenantPrefixViolation("a part's reel cuts are addressed by its draft UUID")
    return f"{reel_windows_root(tenant_id)}{draft_id}/"


def source_window_key(
    tenant_id: UUID, draft_id: UUID, analysis_id: UUID, start_s: int, end_s: int
) -> str:
    """`reel-windows/{tenant}/{draft_id}/source-window-{analysis_id}-{start}-{end}.mp4`."""
    if not isinstance(analysis_id, UUID):
        raise TenantPrefixViolation("a reel cut is named by its analysis UUID")
    if not all(isinstance(s, int) and not isinstance(s, bool) for s in (start_s, end_s)):
        raise TenantPrefixViolation("a reel cut is named by whole seconds")
    if start_s < 0 or end_s <= start_s:
        raise TenantPrefixViolation("a reel cut needs 0 <= start < end")
    name = f"source-window-{analysis_id}-{start_s}-{end_s}.mp4"
    return source_window_prefix(tenant_id, draft_id) + name


#: The seasonal library of stickers and short videos (m-24976891, ADR 39 amendment
#: 2026-11-08), also OUTSIDE `t/`: a season's media are kept after the season (not under
#: the 90-day purge) and deleted only when the owner deletes the season — which the `t/`
#: bucket lock would refuse. `seasonal/{tenant}/{brand}/{season_key}/{media_id}.{ext}`.
SEASONAL_ROOT = "seasonal/"
SEASON_KEY_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,47}")
SEASONAL_EXTENSIONS = ("webp", "mp4")


def seasonal_root(tenant_id: UUID) -> str:
    """The tenant's seasonal library root, `seasonal/{tenant}/`."""
    if not isinstance(tenant_id, UUID):
        raise TenantPrefixViolation("a seasonal root is addressed by the tenant's UUID")
    return f"{SEASONAL_ROOT}{tenant_id}/"


def seasonal_brand_prefix(tenant_id: UUID, brand_id: UUID) -> str:
    """One business's seasonal library, `seasonal/{tenant}/{brand}/` (UUIDs only)."""
    if not isinstance(brand_id, UUID):
        raise TenantPrefixViolation("a seasonal library is addressed by the brand's UUID")
    return f"{seasonal_root(tenant_id)}{brand_id}/"


def seasonal_media_key(
    tenant_id: UUID, brand_id: UUID, season_key: str, media_id: UUID, extension: str
) -> str:
    """`seasonal/{tenant}/{brand}/{season_key}/{media_id}.{webp|mp4}` — a slug season, a
    UUID file name, one of two extensions: no slash, no traversal."""
    if not SEASON_KEY_RE.fullmatch(season_key or ""):
        raise TenantPrefixViolation("not a season key")
    if not isinstance(media_id, UUID):
        raise TenantPrefixViolation("a seasonal medium is named by its UUID")
    if extension not in SEASONAL_EXTENSIONS:
        raise TenantPrefixViolation("a seasonal medium is a .webp or an .mp4")
    return f"{seasonal_brand_prefix(tenant_id, brand_id)}{season_key}/{media_id}.{extension}"


def tenant_roots(tenant_id: UUID) -> tuple[str, ...]:
    """Every prefix this tenant's objects may live under: `t/{tenant}/`, the Galería's
    `gallery/{tenant}/`, the reel cuts' `reel-windows/{tenant}/` and the seasonal
    library's `seasonal/{tenant}/`."""
    return (
        tenant_prefix(tenant_id),
        gallery_root(tenant_id),
        reel_windows_root(tenant_id),
        seasonal_root(tenant_id),
    )


def is_object_store_key(key: str | None) -> bool:
    """Whether a stored key names an object in R2 (`t/…`, `gallery/…`, `reel-windows/…`
    or `seasonal/…`) rather than a file of the local upload store."""
    return bool(key) and key.startswith(("t/", GALLERY_ROOT, REEL_WINDOWS_ROOT, SEASONAL_ROOT))


def require_tenant_object(tenant_id: UUID, object_key: str) -> str:
    """Like `require_tenant_prefix`, but also accepts this tenant's Galería
    (`gallery/{tenant}/…`) and reel cuts (`reel-windows/{tenant}/…`). Used by the gate's
    READS (`open_object`, `sha256`, `object_size`, `open_range`), which serve every root;
    writes there go only through `ObjectGate.put_gallery_media` / `put_source_window`,
    which build the key themselves."""
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
