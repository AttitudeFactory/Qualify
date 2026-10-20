"""Where an imported stock file lives, and how a key says it is stock.

`t/{tenant}/stock/{provider}/{provider_media_id}/{sha256[:16]}.{ext}` — under the tenant's
R2 prefix (deleting a tenant stays a delete-by-prefix, ADR 22), and self-describing: the
producer's and the publisher's guards (§5.2) tell a stock key from any other by its path,
without a database read.
"""

from __future__ import annotations

import re
from uuid import UUID

from qualify_shared.objects.keys import tenant_prefix

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def stock_object_key(
    tenant_id: UUID, provider: str, provider_media_id: str, sha256: str, ext: str
) -> str:
    if not _SAFE_ID.match(provider) or not _SAFE_ID.match(provider_media_id):
        raise ValueError("stock provider and media id must be plain identifiers")
    return f"{tenant_prefix(tenant_id)}stock/{provider}/{provider_media_id}/{sha256[:16]}.{ext}"


def is_stock_key(key: str | None) -> bool:
    """`t/<tenant>/stock/…` — whichever tenant; ownership is `owned_by`'s job."""
    if not key:
        return False
    parts = key.split("/")
    return len(parts) >= 5 and parts[0] == "t" and parts[2] == "stock"


def stock_key_provider(key: str) -> str | None:
    return key.split("/")[3] if is_stock_key(key) else None
