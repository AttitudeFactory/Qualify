"""The seam between the CRM screen and the real connections backend (C-03/C-04).

Two kinds of call live here, and the difference matters:

- **Reads this module owns.** `connections_for` and `acting_user_id` query Postgres
  directly through `tenant_session(tenant_id)` (C-01.4) — the only sanctioned door —
  so Row Level Security scopes the rows to the tenant even though the queries carry no
  `WHERE tenant_id`. That is the lower net; passing the tenant explicitly is the upper
  one.
- **Writes this module delegates.** `disconnect` and `begin_connect` are thin adapters
  over `qualify_api.connections`' published seam (`revoke_connection` / `start_connect`),
  which are plain Python calls in this same process — no HTTP hop, so the exception
  types survive. The UI does not drive the FSM itself: revocation goes through
  `apply_transition` inside the service, which writes the audit row *and* publishes the
  domain event.

Nothing credential-bearing crosses this module: it touches `social_connections`,
`brands`, `users` and `tenant_members` only. `oauth_credentials` is never read, and the
`qualify_app` role these sessions run as is not even granted its `ciphertext`/`key_id`
columns (migration 0002, R3), so there is no route from this screen to a token.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from qualify_api.connections import revoke_connection, start_connect
from qualify_api.connections.models import SocialConnection
from qualify_api.tenancy.models import Brand, TenantMember, User
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .capabilities import SCOPE_KEY_LABELS, ScopeKey, assess_capabilities, resolve_scope_keys
from .connections_vm import ConnectionVM, build_connection_vm

_NO_BRAND_LABEL = "Sin marca"


def _format_verified_at(value: datetime | None) -> str:
    """Pre-format server-side — the frontend never receives a raw datetime var."""
    if value is None:
        return "Nunca verificada"
    return value.strftime("%d %b %Y, %H:%M")


def _scope_labels(granted_literals: list[str]) -> tuple[list[str], frozenset[ScopeKey]]:
    """Granted Meta scope strings -> (chip labels, resolved abstract keys).

    Literals C-05's table does not know are shown as-is rather than dropped: the real
    `resolve_scope_keys` surfaces them precisely so a renamed or brand-new Meta scope
    appears as "unknown" instead of a phantom denial. A scope name is a permission
    name, not credential material, so it is safe to render.
    """
    resolved, unrecognized = resolve_scope_keys(frozenset(granted_literals))
    labels = [label for key, label in SCOPE_KEY_LABELS.items() if key in resolved]
    labels += [f"Sin reconocer: {literal}" for literal in sorted(unrecognized)]
    return labels, resolved


def _to_vm(row: SocialConnection, brand_name: str | None) -> ConnectionVM:
    scope_labels, resolved = _scope_labels(row.granted_scopes)
    return build_connection_vm(
        connection_id=str(row.id),
        platform=row.platform,
        brand=brand_name or _NO_BRAND_LABEL,
        external_username=row.external_username or row.external_account_id,
        status=row.status,
        last_verified_at=_format_verified_at(row.last_verified_at),
        granted_scope_labels=scope_labels,
        verdicts=assess_capabilities(resolved),
    )


class NoActingUser(RuntimeError):
    """The tenant has no user to attribute an OAuth grant to.

    Only reachable against a tenant row provisioned without any member — the seed
    always creates an owner. Raised rather than defaulted, because `user_id` lands in
    the SIGNED `state` payload and ends up as `connected_by_user_id`: inventing one
    would put a fabricated actor in the audit trail.
    """


def connections_for(tenant_id: UUID) -> list[ConnectionVM]:
    """The tenant's connections, newest first, as client-safe view-models.

    Blocking DB call — callers on the event loop must run it off-thread.
    """
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(SocialConnection, Brand.name)
            .outerjoin(Brand, SocialConnection.brand_id == Brand.id)
            .order_by(SocialConnection.connected_at.desc())
        ).all()
        # Built inside the session: the ORM rows are not usable once it closes.
        return [_to_vm(connection, brand_name) for connection, brand_name in rows]


def acting_user_id(tenant_id: UUID) -> UUID | None:
    """The user an OAuth grant is attributed to. Dev crutch until real login (QUA-66).

    Sprint 1 has no authentication, so there is no session user to take this from — and
    `start_connect` needs one for the signed `state` payload. The tenant's `owner` is
    the honest stand-in: it is a real row, not a fabricated uuid. Read through
    `tenant_session`, so a tenant can only ever resolve to its OWN user.

    Blocking DB call — callers on the event loop must run it off-thread.
    """
    with tenant_session(tenant_id) as session:
        owner_id = session.scalar(
            select(User.id)
            .join(TenantMember, TenantMember.user_id == User.id)
            .where(TenantMember.role == "owner")
            .order_by(User.created_at)
        )
        if owner_id is not None:
            return owner_id
        # A tenant seeded without a membership row still has users; take the eldest
        # rather than failing the connect flow over a missing role assignment.
        return session.scalar(select(User.id).order_by(User.created_at))


def begin_connect(tenant_id: UUID) -> str:
    """Start the C-04 OAuth flow: returns the Meta authorization URL to redirect to.

    `brand_id=None` on purpose: Sprint 1's screen has no brand picker, and the
    repository treats a null brand on a grant as "leave what is there" — so a reconnect
    preserves the brand the connection already had instead of clearing it.

    Blocking (Redis, plus Postgres for the actor lookup) — call it off the event loop.
    Raises `NoActingUser` when the tenant has nobody to attribute the grant to.
    """
    user_id = acting_user_id(tenant_id)
    if user_id is None:
        raise NoActingUser(f"tenant {tenant_id} has no user to attribute the grant to")
    return start_connect(tenant_id=tenant_id, brand_id=None, user_id=user_id)


def disconnect(tenant_id: UUID, connection_id: UUID) -> bool:
    """Revoke a connection through the real C-04 service. Returns whether it changed.

    `False` is a legitimate outcome, not an error: the connection was already `revoked`
    and nothing was written (no audit row, no domain event), so a double-click on
    "Desconectar" must not break the screen.

    Raises `ConnectionNotFound` when no connection with that id is visible to this
    tenant. That case **deliberately covers another tenant's id too** — RLS filters the
    row before the service ever sees it, so "does not exist" and "is not yours" are
    literally the same read. The caller must surface it as not-found and must never
    report success; telling someone their revoke worked on an id they do not own is the
    bug this replaced.

    `InvalidTransition` (no `revoke` edge from the current status) and `ValueError` (a
    status outside the FSM's vocabulary) are bugs, not user flows — they propagate.

    Blocking DB call — callers on the event loop must run it off-thread.
    """
    return revoke_connection(tenant_id=tenant_id, connection_id=connection_id, actor="user").changed
