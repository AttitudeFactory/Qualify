"""Who has the Creators module (`docs/diseno-modulo-creadores.md` §11).

The module opens per business from an environment variable, `QUALIFY_CREATORS_TENANTS`:

- `*` — every business, present and future (founder, 2026-11-05, m-24955836). A `*`
  anywhere in the list wins: `*, <uuid>` is everyone too;
- tenant UUIDs separated by commas — only those businesses;
- unset or empty — nobody. A value that is neither `*` nor a UUID opens nothing (it is
  skipped and logged: a typo never opens the module to someone).

A two-way door: no schema, changed with `just env-push` (the founder's,
`qualify-prod-ops`). It reopens when the module opens to clients: access will then come
from the plan a business pays for.

`creators_enabled` is the only check: the menu reads it, and every function of
`qualify_api.creators.service` checks it again (the screen is not the security boundary).
The parsed value is cached per process for 60 seconds.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from uuid import UUID

logger = logging.getLogger(__name__)

ENV = "QUALIFY_CREATORS_TENANTS"
#: The value that opens the module to every business.
EVERYONE = "*"
CACHE_SECONDS = 60.0


@dataclass(frozen=True)
class CreatorsAccess:
    """The parsed switch: `everyone` (a `*` was given), else only `tenants`."""

    everyone: bool
    tenants: frozenset[UUID]

    def allows(self, tenant_id: UUID) -> bool:
        return self.everyone or tenant_id in self.tenants


_lock = threading.Lock()
_cache: tuple[float, str, CreatorsAccess] | None = None


def _parse(raw: str) -> CreatorsAccess:
    everyone = False
    out: set[UUID] = set()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        if piece == EVERYONE:
            everyone = True
            continue
        try:
            out.add(UUID(piece))
        except ValueError:
            # A typo must never open the module to someone: skip it, and say so.
            logger.warning("%s: ignoring a value that is neither '*' nor a UUID", ENV)
    return CreatorsAccess(everyone, frozenset(out))


def current_access(*, clock: float | None = None) -> CreatorsAccess:
    """The switch as it stands (cached 60 s; a changed value is read at once)."""
    global _cache
    now = time.monotonic() if clock is None else clock
    raw = os.environ.get(ENV, "")
    with _lock:
        if _cache is not None and _cache[1] == raw and now - _cache[0] < CACHE_SECONDS:
            return _cache[2]
        access = _parse(raw)
        _cache = (now, raw, access)
        return access


def enabled_tenants(*, clock: float | None = None) -> frozenset[UUID]:
    """The businesses NAMED in the switch. Under `*` everyone has the module whatever
    this holds — ask `creators_enabled` (or `opens_to_everyone`), never this set."""
    return current_access(clock=clock).tenants


def opens_to_everyone() -> bool:
    return current_access().everyone


def creators_enabled(tenant_id: UUID) -> bool:
    return current_access().allows(tenant_id)


def reset_cache() -> None:
    """Forget the cached value (tests)."""
    global _cache
    with _lock:
        _cache = None


__all__ = [
    "CACHE_SECONDS",
    "ENV",
    "EVERYONE",
    "CreatorsAccess",
    "creators_enabled",
    "current_access",
    "enabled_tenants",
    "opens_to_everyone",
    "reset_cache",
]
