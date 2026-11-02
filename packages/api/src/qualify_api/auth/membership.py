"""Membership re-checks and the audit of every business opening (S5, m-24849192).

ADR 43 F5 (signed 2026-10-25): with several businesses per login, removing someone from
one of them must take effect with their session still open.

- **On every page load** — `check_membership(auth_user_id, tenant_id)`, cached for
  `MEMBERSHIP_CACHE_TTL` (60 s, F5). Within those 60 s a page keeps loading after the
  seat was removed; the first load after them raises `NotAMember`. The UI shows
  `NotAMember.message` and sends the session to /login (A15).
- **Right before publishing or sending** — never cached: `require_membership_now`
  (directly) or `qualify_api.tenancy.acting.require_acting_member(tenant_id)`, which the
  publish/send services call themselves for the login the UI marked with
  `acting_login(auth_user_id)`.
- **Every opening of a business** (the selector after login, S3; the switch, S4) —
  `open_business_audited(...)`: the same fresh check as `open_business`, plus one
  `business_open_audit` row in the DESTINATION tenant, in one transaction. RLS keeps it
  visible only from that tenant (migration 0114).

The cache is per process (a dict behind a lock): each Reflex backend process re-checks
at most once a minute per (login, business). A failed fresh check also evicts the cached
entry, so the next page load agrees with the refusal at once. Only positive results are
cached; a refusal is never remembered as access. Accepted, bounded race: a positive
check that read the database just before the seat was removed may re-cache after a
concurrent refusal evicted it — page loads then pass for at most one more TTL, and
publish/send (never cached) is unaffected. Expired entries are dropped when read; the
dict holds at most one entry per (login, business) this process has seen.

Hook for the UI (Reflex, owned by reflex-ui-engineer — S3/S4 in `Qualify/auth_state.py`):

    # AuthState.require_login (on_load of every protected page), after the
    # session_tenant_id check, with self._auth_user_id kept server-side (epic §8):
    try:
        await asyncio.to_thread(
            check_membership, UUID(self._auth_user_id), UUID(self.session_tenant_id)
        )
    except NotAMember as exc:
        ...clear the session...; self.auth_error = exc.message; return rx.redirect("/login")

    # Every event that publishes or sends:
    with acting_login(UUID(self._auth_user_id)):
        result = await asyncio.to_thread(service_call, ...)
    # and catch NotAMember like above.

    # Selector (S3) and switch (S4) — instead of open_business:
    business = await asyncio.to_thread(
        open_business_audited, auth_user_id, chosen_tenant_id,
        via="login" | "switch", from_tenant_id=<previous tenant or None>,
    )
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Literal
from uuid import UUID

from qualify_shared.db.session import tenant_session

from qualify_api.auth.business import ActiveBusiness, NotAMember, member_of, open_business
from qualify_api.tenancy.acting import acting_login, current_acting_login, require_acting_member
from qualify_api.tenancy.models import BusinessOpenAudit

#: ADR 43 F5: how long a page load may trust the last membership check.
MEMBERSHIP_CACHE_TTL = timedelta(seconds=60)

OpenVia = Literal["login", "switch"]
_VIAS: frozenset[str] = frozenset({"login", "switch"})


class MembershipCache:
    """Positive membership results for `ttl`, keyed by (auth_user_id, tenant_id)."""

    def __init__(
        self,
        ttl: timedelta = MEMBERSHIP_CACHE_TTL,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl.total_seconds()
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[tuple[UUID, UUID], tuple[float, ActiveBusiness]] = {}

    def get(self, auth_user_id: UUID, tenant_id: UUID) -> ActiveBusiness | None:
        key = (auth_user_id, tenant_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, business = entry
            if self._clock() >= expires_at:
                del self._entries[key]
                return None
            return business

    def put(self, auth_user_id: UUID, business: ActiveBusiness) -> None:
        with self._lock:
            self._entries[(auth_user_id, business.tenant_id)] = (
                self._clock() + self._ttl,
                business,
            )

    def evict(self, auth_user_id: UUID, tenant_id: UUID) -> None:
        with self._lock:
            self._entries.pop((auth_user_id, tenant_id), None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_cache = MembershipCache()


def membership_cache() -> MembershipCache:
    """The process-wide cache (tests clear it; nothing else should need it)."""
    return _cache


def check_membership(auth_user_id: UUID, tenant_id: UUID) -> ActiveBusiness:
    """Page-load check (F5): served from the 60 s cache when fresh, otherwise checked
    against the database and cached. Raises `NotAMember`."""
    cached = _cache.get(auth_user_id, tenant_id)
    if cached is not None:
        return cached
    return require_membership_now(auth_user_id, tenant_id)


def require_membership_now(auth_user_id: UUID, tenant_id: UUID) -> ActiveBusiness:
    """Fresh check, never cached (before publish/send). Refreshes the page-load cache on
    success and evicts it on refusal. Raises `NotAMember`."""
    try:
        business = open_business(auth_user_id, tenant_id)
    except NotAMember:
        _cache.evict(auth_user_id, tenant_id)
        raise
    _cache.put(auth_user_id, business)
    return business


def open_business_audited(
    auth_user_id: UUID,
    tenant_id: UUID,
    *,
    via: OpenVia,
    from_tenant_id: UUID | None = None,
) -> ActiveBusiness:
    """Open a business for the session (S3 selector / S4 switch) and audit it.

    The fresh membership check and the audit insert share one `tenant_session` of the
    destination, so a refused opening leaves no row and an accepted one always has its
    row. `from_tenant_id` is the business the session was in (None right after login);
    reopening the same business is audited with `from_tenant_id=None`."""
    if via not in _VIAS:
        raise ValueError(f"via must be one of {sorted(_VIAS)}")
    origin = from_tenant_id if from_tenant_id != tenant_id else None
    try:
        with tenant_session(tenant_id) as db:
            business = member_of(db, auth_user_id, tenant_id)
            db.add(
                BusinessOpenAudit(
                    tenant_id=tenant_id,
                    auth_user_id=auth_user_id,
                    user_id=business.user_id,
                    from_tenant_id=origin,
                    via=via,
                )
            )
    except NotAMember:
        _cache.evict(auth_user_id, tenant_id)
        raise
    _cache.put(auth_user_id, business)
    return business


__all__ = [
    "MEMBERSHIP_CACHE_TTL",
    "MembershipCache",
    "OpenVia",
    "acting_login",
    "check_membership",
    "current_acting_login",
    "membership_cache",
    "open_business_audited",
    "require_acting_member",
    "require_membership_now",
]
