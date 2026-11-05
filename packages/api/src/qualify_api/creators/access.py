"""Who has the Creators module (`docs/diseno-modulo-creadores.md` §11).

Delivery 1 opens to a list of businesses in an environment variable,
`QUALIFY_CREATORS_TENANTS` — tenant UUIDs separated by commas; unset or empty = nobody.
A two-way door: no schema, changed with `just env-push` (the founder's,
`qualify-prod-ops`). It reopens when the module opens to clients: access will then come
from the plan a business pays for.

`creators_enabled` is the only source: the menu reads it, and every function of
`qualify_api.creators.service` checks it again (the screen is not the security boundary).
The parsed list is cached per process for 60 seconds.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from uuid import UUID

logger = logging.getLogger(__name__)

ENV = "QUALIFY_CREATORS_TENANTS"
CACHE_SECONDS = 60.0

_lock = threading.Lock()
_cache: tuple[float, str, frozenset[UUID]] | None = None


def _parse(raw: str) -> frozenset[UUID]:
    out: set[UUID] = set()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.add(UUID(piece))
        except ValueError:
            # A typo must never open the module to someone: skip it, and say so.
            logger.warning("%s: ignoring a value that is not a UUID", ENV)
    return frozenset(out)


def enabled_tenants(*, clock: float | None = None) -> frozenset[UUID]:
    """The tenants with the module, from `QUALIFY_CREATORS_TENANTS` (cached 60 s; a
    changed value is read at once)."""
    global _cache
    now = time.monotonic() if clock is None else clock
    raw = os.environ.get(ENV, "")
    with _lock:
        if _cache is not None and _cache[1] == raw and now - _cache[0] < CACHE_SECONDS:
            return _cache[2]
        tenants = _parse(raw)
        _cache = (now, raw, tenants)
        return tenants


def creators_enabled(tenant_id: UUID) -> bool:
    return tenant_id in enabled_tenants()


def reset_cache() -> None:
    """Forget the cached list (tests)."""
    global _cache
    with _lock:
        _cache = None


__all__ = ["CACHE_SECONDS", "ENV", "creators_enabled", "enabled_tenants", "reset_cache"]
