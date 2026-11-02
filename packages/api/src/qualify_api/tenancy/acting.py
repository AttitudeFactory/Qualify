"""Who is acting right now, and the fresh membership gate before publish/send (S5).

ADR 43 A15 / F5 (m-24849192): removing someone from a business must stop their very
next publication or message, even with the session open. Every backend path that
publishes or sends on a person's behalf calls `require_acting_member(tenant_id)` before
it writes anything (no outbox row, no attempt, no Graph call):

- When a login is acting — the Reflex event wrapped its backend call in
  `acting_login(auth_user_id)` — the membership of that login in `tenant_id` is checked
  **now, without cache** (`open_business`). Not a member → `NotAMember`, whose `message`
  is «Ya no tienes acceso a este negocio. Vuelve a entrar para elegir otro.»
- When nobody is acting — workers, webhooks, CLI recipes, tests — it does nothing:
  those paths only send what a person already approved, and they keep entering through
  `tenant_session` exactly as before (ticket criterion «workers y webhooks sin cambios»).

`auth_user_id` is the identity provider's id kept server-side in the session
(`AuthState._auth_user_id`, epic §8), never a browser argument. A `ContextVar` carries
it: `asyncio.to_thread` copies the context into the worker thread, so a handler that does
`with acting_login(uid): await asyncio.to_thread(service_call)` is covered.

This module lives in `tenancy` (no heavy imports) so publishing, planner, replies,
conversations and WhatsApp can import it without importing the whole auth package; the
check itself is imported lazily.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

_ACTING: ContextVar[UUID | None] = ContextVar("qualify_acting_login", default=None)


@contextmanager
def acting_login(auth_user_id: UUID | None) -> Iterator[None]:
    """Mark `auth_user_id` as the login acting inside the block. `None` is allowed and
    leaves nothing acting (a session without an id yet), so callers need no branch —
    but never inside a block where a login is already acting: that would silently turn
    the gate off for the inner call."""
    if auth_user_id is not None and not isinstance(auth_user_id, UUID):
        raise TypeError("auth_user_id must be a UUID")
    if auth_user_id is None and _ACTING.get() is not None:
        raise RuntimeError("acting_login(None) cannot clear a login that is acting")
    token = _ACTING.set(auth_user_id)
    try:
        yield
    finally:
        _ACTING.reset(token)


def current_acting_login() -> UUID | None:
    """The login acting in this context, or None (system path)."""
    return _ACTING.get()


def require_acting_member(tenant_id: UUID) -> None:
    """Right before publishing or sending: fresh membership check of the acting login.

    Raises `qualify_api.auth.NotAMember` when the acting login is no longer a member of
    `tenant_id`; no-op when nobody is acting (workers, webhooks)."""
    auth_user_id = _ACTING.get()
    if auth_user_id is None:
        return
    from qualify_api.auth.membership import require_membership_now  # noqa: PLC0415

    require_membership_now(auth_user_id, tenant_id)


__all__ = ["acting_login", "current_acting_login", "require_acting_member"]
