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


# --------------------------------------------------------------------------------------
# The public prefix (ADR 44 F5; VE-04a m-24921056 + VE-12 m-24921060, the R8 slice)
# --------------------------------------------------------------------------------------
#
# `public/` means «no tenant», not «open to all»: these objects are copies of PUBLIC reels,
# shared by every business, and nothing serves them by URL (the media routes require a
# tenant prefix and reject this one). A signed exception to ADR 22's per-tenant keys, like
# the global tables of 0117/0119. The only root is `reel-analyses/`, and a key must have
# exactly the shape below — anything else is refused, `..` included.

#: The roots under `public/` (a new one is a reviewed decision, like `PURGEABLE_ROOTS`).
PUBLIC_ROOTS: tuple[str, ...] = ("reel-analyses/",)

_POST_ID = r"[A-Za-z0-9_-]{1,64}"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_PUBLIC_KEY = re.compile(
    rf"public/reel-analyses/(?:instagram|tiktok)/{_POST_ID}/{_UUID}/"
    r"(?:source/source\.mp4|frames/[0-9]{2}-[0-9]+\.jpg)"
)
_PUBLIC_FOLDER = re.compile(
    rf"public/reel-analyses/(?:instagram|tiktok)/{_POST_ID}/{_UUID}/(?:source|frames)/"
)


class PublicKeyViolation(Exception):
    """An object key does not have the exact shape of a public reel-analysis object."""


def require_public_key(object_key: str) -> str:
    """`object_key` unchanged when it is `public/reel-analyses/<network>/<post_id>/<uuid>/`
    followed by `source/source.mp4` or `frames/NN-N.jpg`; raise otherwise."""
    if ".." in object_key or not _PUBLIC_KEY.fullmatch(object_key):
        raise PublicKeyViolation("not a public reel-analysis object key")
    return object_key


def require_public_folder(prefix: str) -> str:
    """`prefix` unchanged when it is the `source/` or `frames/` folder of one analysis;
    raise otherwise (never `public/`, a network or a reel)."""
    if ".." in prefix or not _PUBLIC_FOLDER.fullmatch(prefix):
        raise PublicKeyViolation("not the source or frames folder of one analysis")
    return prefix


def public_analysis_prefix(network: str, post_id: str, analysis_id: UUID) -> str:
    """`public/reel-analyses/<network>/<post_id>/<analysis_id>/` — checked."""
    prefix = f"public/{PUBLIC_ROOTS[0]}{network}/{post_id}/{analysis_id}/"
    require_public_folder(prefix + "source/")
    return prefix


def public_source_key(network: str, post_id: str, analysis_id: UUID) -> str:
    """Where the stored copy of a public reel's video lives (one per analysis)."""
    return require_public_key(
        public_analysis_prefix(network, post_id, analysis_id) + "source/source.mp4"
    )
