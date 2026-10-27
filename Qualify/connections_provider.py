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

from datetime import UTC, datetime
from uuid import UUID

from qualify_api.connections import (
    DATA_ACCESS_WARNING_THRESHOLD,
    check_connection_health,
    revoke_connection,
    start_connect,
)
from qualify_api.connections.models import SocialConnection
from qualify_api.support import SupportTicket, create_support_request
from qualify_api.tenancy.models import Brand, TenantMember, User
from qualify_api.whatsapp.models import WhatsAppPhoneNumber
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .capabilities import (
    KNOWN_INFRASTRUCTURE_SCOPES,
    SCOPE_KEY_LABELS,
    ScopeKey,
    assess_capabilities,
    resolve_scope_keys,
)
from .connections_vm import (
    ConnectionVM,
    build_connection_vm,
    connection_hints,
    whatsapp_label,
)

_NO_BRAND_LABEL = "Sin marca"


_MONTHS_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic")

# m-24842969: the fallbacks the owner reads under «Más detalles» — plain words, never
# «Nunca verificada» / «Sin verificar».
NEVER_CONNECTED_AT = "Sin fecha"
NEVER_CHECKED_AT = "Todavía no"


def _format_when(value: datetime) -> str:
    """«21 ago 2026, 16:33» — Spanish month names whatever the server's locale
    (`strftime("%b")` printed «Aug»)."""
    return f"{value.day:02d} {_MONTHS_ES[value.month - 1]} {value.year}, {value:%H:%M}"


def _format_verified_at(value: datetime | None) -> str:
    """Pre-format server-side — the frontend never receives a raw datetime var."""
    if value is None:
        return NEVER_CONNECTED_AT
    return _format_when(value)


def _format_health_checked_at(value: datetime | None) -> str:
    """QUA-91: same pre-format discipline as `_format_verified_at`, distinct fallback
    copy — «Todavía no» reads as "nobody has pressed «Comprobar ahora» yet", never as
    `last_verified_at`'s own, unrelated fallback."""
    if value is None:
        return NEVER_CHECKED_AT
    return _format_when(value)


def _data_access_warning(
    data_access_expires_at: datetime | None, *, now: datetime
) -> tuple[str, str]:
    """QUA-91: (`data_access_state`, `data_access_message`) for the VM, pre-formatted
    server-side. Deliberately independent of `status`/the FSM — a near or passed
    `data_access_expires_at` NEVER implies `degraded`; only a real `is_valid=false` from
    `/debug_token` does that (see `composition.py::check_connection_health`). Wording is
    chosen to never imply the connection itself is broken (see the QUA-91 design note on
    why "Degradada" + `triangle-alert` are reserved for that real case and never reused
    here).
    """
    if data_access_expires_at is None:
        return "", ""
    remaining = data_access_expires_at - now
    if remaining.total_seconds() <= 0:
        return "warning_overdue", "Facebook pide que confirmes tu cuenta: vuelve a conectarla"
    if remaining > DATA_ACCESS_WARNING_THRESHOLD:
        return "", ""
    days_left = int(remaining.total_seconds() // 86400)
    if days_left <= 0:
        message = "Facebook te pedirá confirmar tu cuenta hoy"
    elif days_left == 1:
        message = "Facebook te pedirá confirmar tu cuenta mañana"
    else:
        message = f"Facebook te pedirá confirmar tu cuenta en {days_left} días"
    return "warning_soon", message


def _scope_labels(granted_literals: list[str]) -> tuple[list[str], frozenset[ScopeKey]]:
    """Granted Meta scope strings -> (chip labels, resolved abstract keys).

    Literals C-05's table does not know are surfaced rather than dropped: the real
    `resolve_scope_keys` reports them precisely so a renamed or brand-new Meta scope
    appears as "unknown" instead of a phantom denial.

    QUA-96 / m-24842969: an unrecognized literal is split by `KNOWN_INFRASTRUCTURE_SCOPES`
    — expected OAuth plumbing (Page enumeration, ADR 25/R4) is not shown at all, and a
    literal that is genuinely new or renamed shows as one «Otro permiso de Meta» chip.
    `resolve_scope_keys` itself is untouched; this is
    a presentation-only split of its `unrecognized` output.
    """
    resolved, unrecognized = resolve_scope_keys(frozenset(granted_literals))
    labels = [label for key, label in SCOPE_KEY_LABELS.items() if key in resolved]
    # m-24842969: infrastructure scopes are a normal part of the connection and are not
    # shown; genuinely unknown literals collapse into one owner-facing chip. The raw
    # names stay in the logs only.
    if any(literal not in KNOWN_INFRASTRUCTURE_SCOPES for literal in unrecognized):
        labels.append("Otro permiso de Facebook")
    return labels, resolved


def _to_vm(
    row: SocialConnection, brand_name: str | None, verified_name: str | None = None
) -> ConnectionVM:
    """`verified_name` is the WhatsApp number's Meta-verified business name from
    `whatsapp_phone_numbers` (WA-05); None for every other platform. The capability list
    is assessed for the row's OWN platform only — an Instagram card must not show the
    WhatsApp capabilities as disabled, nor the reverse (platform is data on each rule)."""
    scope_labels, resolved = _scope_labels(row.granted_scopes)
    data_access_state, data_access_message = _data_access_warning(
        row.data_access_expires_at, now=datetime.now(UTC)
    )
    label = row.external_username or row.external_account_id
    if row.platform == "whatsapp":
        label = whatsapp_label(label, verified_name)
    return build_connection_vm(
        connection_id=str(row.id),
        platform=row.platform,
        brand=brand_name or _NO_BRAND_LABEL,
        external_username=label,
        status=row.status,
        reconnect_reason=row.reconnect_reason or "",
        last_verified_at=_format_verified_at(row.last_verified_at),
        granted_scope_labels=scope_labels,
        verdicts=assess_capabilities(resolved, platform=row.platform),
        last_health_checked_at=_format_health_checked_at(row.last_health_checked_at),
        data_access_state=data_access_state,
        data_access_message=data_access_message,
        hints=connection_hints(
            platform=row.platform,
            status=row.status,
            granted_literals=frozenset(row.granted_scopes),
            resolved_keys=frozenset(str(key) for key in resolved),
            has_linked_page=bool(row.linked_page_id),
        ),
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
            select(SocialConnection, Brand.name, WhatsAppPhoneNumber.verified_name)
            .outerjoin(Brand, SocialConnection.brand_id == Brand.id)
            # WA-05: the verified name lives on the phone row, one per connection at most
            # (`phone_number_id` is UNIQUE and equals `external_account_id`). RLS on
            # `whatsapp_phone_numbers` scopes this join exactly like the base table.
            .outerjoin(
                WhatsAppPhoneNumber, WhatsAppPhoneNumber.connection_id == SocialConnection.id
            )
            .order_by(SocialConnection.connected_at.desc())
        ).all()
        # Built inside the session: the ORM rows are not usable once it closes.
        return [
            _to_vm(connection, brand_name, verified_name)
            for connection, brand_name, verified_name in rows
        ]


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


def begin_connect(tenant_id: UUID, *, rerequest: bool = False) -> str:
    """Start the C-04 OAuth flow: returns the Meta authorization URL to redirect to.

    `brand_id=None` on purpose: Sprint 1's screen has no brand picker, and the
    repository treats a null brand on a grant as "leave what is there" — so a reconnect
    preserves the brand the connection already had instead of clearing it.

    `rerequest` (QUA-202) is the retry after `page_access_required`: Meta shows the Page
    picker again instead of silently skipping what the operator left unticked last time.

    Blocking (Redis, plus Postgres for the actor lookup) — call it off the event loop.
    Raises `NoActingUser` when the tenant has nobody to attribute the grant to.
    """
    user_id = acting_user_id(tenant_id)
    if user_id is None:
        raise NoActingUser(f"tenant {tenant_id} has no user to attribute the grant to")
    return start_connect(tenant_id=tenant_id, brand_id=None, user_id=user_id, rerequest=rerequest)


def begin_reconnect(tenant_id: UUID, connection_id: UUID, *, cause: str, origin: str) -> str:
    """Start an account-specific consent round trip from any screen in the same tenant."""
    user_id = acting_user_id(tenant_id)
    if user_id is None:
        raise NoActingUser(f"tenant {tenant_id} has no user to attribute the grant to")
    return start_connect(
        tenant_id=tenant_id,
        brand_id=None,
        user_id=user_id,
        connection_id=connection_id,
        return_to=origin,
        cause=cause,
    )


def request_support(
    tenant_id: UUID,
    *,
    contact_email: str,
    contact_whatsapp: str,
    message: str,
    context: dict[str, str | int],
) -> SupportTicket:
    """QUA-202: "Pedir ayuda 1:1" from the connections screen — a ticket the tenant owns
    plus a best-effort notification to the global support channel.

    Thin adapter over `qualify_api.support.create_support_request`, same pattern as
    `disconnect`/`begin_connect`. The topic is fixed here: this screen only ever asks for
    help connecting accounts. `context` is what the screen knew about the last attempt
    (the outcome code and the two counts) — the service refuses any other key, so no
    identifier can be smuggled into a notification by a future caller.

    Raises `InvalidSupportRequest` for input that cannot become a ticket (bad email).
    Blocking (Postgres + one HTTP call) — callers on the event loop must run it off-thread.
    """
    return create_support_request(
        tenant_id=tenant_id,
        topic="connect_accounts",
        contact_email=contact_email,
        contact_whatsapp=contact_whatsapp,
        message=message,
        context=context,
    )


def check_health(tenant_id: UUID, connection_id: UUID) -> bool:
    """QUA-91: run a real, on-demand `/debug_token` check for one connection.

    Thin adapter over `qualify_api.connections.check_connection_health` — same pattern
    `disconnect`/`begin_connect` already use for their own seams. Manual-trigger-only:
    this function is called from exactly one place, the "Verificar ahora" button's event
    handler (`connections_state.py`) — nothing in this module calls it on a schedule.

    Returns whether the token was still valid. Raises on a lookup/transport failure
    (`CredentialNotFound`, `TokenHealthError`, `httpx.HTTPError`) rather than swallowing
    it — the caller surfaces these as an action error, same posture `begin_connect`
    already has for its own infra exceptions.

    Blocking DB call (plus a Meta call) — callers on the event loop must run it off-thread.
    """
    return check_connection_health(tenant_id=tenant_id, connection_id=connection_id)


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
