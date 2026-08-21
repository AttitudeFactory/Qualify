"""View-models for the connections screen (C-06) — the security boundary.

Because **every Reflex var is serialized to the client**, the "never show or log
credential material" acceptance criterion (QUA-18) is enforced *structurally*: the
`ConnectionsState` only ever holds these whitelisted dataclasses, never an ORM row
of `social_connections` / `oauth_credentials`. There is no field here that can
carry a token, ciphertext, or `key_id`, so there is no route from the DB to the
browser. Same pattern as the existing `MentionRow` in `state.py`.

Keep this module free of Reflex and network imports so the whitelist can be
asserted by a plain unit test (`test_connections.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .capabilities import (
    CAPABILITY_DISABLED_REASONS,
    CAPABILITY_LABELS,
    CapabilityVerdict,
)

# Connection health states — the FSM surface of C-03.3 that the UI renders.
# "pending" exists in the FSM but is transient (mid-OAuth) and not listed here as a
# steady display state; the three below are what a loaded connection shows.
ConnectionStatus = str  # "active" | "degraded" | "revoked"


@dataclass(frozen=True)
class CapabilityVM:
    """Display-ready projection of a C-05 CapabilityVerdict. No credential fields."""

    key: str  # Capability enum value, stable id for rx.match / keys
    label: str  # UI-facing Spanish label
    enabled: bool
    reason: str  # motive shown when disabled ("" when enabled)
    provisional: bool  # C-05.4: capability rests on an unverified Meta doc row


@dataclass
class ConnectionVM:
    """Display-ready projection of one `social_connections` row.

    Whitelisted on purpose — adding a credential-bearing field here would be a
    security regression caught by `test_connection_vm_has_no_credential_fields`.
    """

    id: str
    platform: str  # "instagram" | "facebook"
    brand: str
    external_username: str
    status: ConnectionStatus
    last_verified_at: str  # PRE-FORMATTED server-side (never a raw datetime var)
    granted_scopes: list[str]  # human-readable scope labels, never the raw token
    enabled_capabilities: list[CapabilityVM] = field(default_factory=list)
    disabled_capabilities: list[CapabilityVM] = field(default_factory=list)
    # QUA-91: the data-access-window warning, INDEPENDENT of `status`/the FSM. Empty
    # string means "nothing to show" — never confuse this with `status == "degraded"`,
    # which is the real, evidence-based (401/190) case. `data_access_state` is a closed
    # vocabulary ("" | "warning_soon" | "warning_overdue") so the page can pick the icon
    # without re-deriving it; `data_access_message` is pre-formatted, same discipline as
    # `last_verified_at`.
    data_access_state: str = ""
    data_access_message: str = ""
    # NOTE: there is deliberately no `auth_url` field. The C-04 authorization URL is
    # minted by `start_connect`, which registers a one-shot `state` jti in Redis per
    # call; precomputing one per row at page load would burn a token for every
    # connection the operator never reconnects, and age it until it expired. The
    # reconnect buttons call the event handler instead.
    # True when any shown capability is provisional (C-05.4) — drives an honest
    # "por verificar" marker in the UI rather than asserting an unverified row.
    has_provisional_capabilities: bool = False


def _capability_vm(verdict: CapabilityVerdict) -> CapabilityVM:
    """Project a verdict for display: Spanish copy, and a reason only when disabled.

    The real C-05 verdict always carries a `reason` (English engineering prose) even
    when enabled; the client receives neither — the operator-facing wording comes from
    `CAPABILITY_DISABLED_REASONS`, and an enabled capability ships no reason at all.
    """
    return CapabilityVM(
        key=str(verdict.capability),
        label=CAPABILITY_LABELS[verdict.capability],
        enabled=verdict.enabled,
        reason="" if verdict.enabled else CAPABILITY_DISABLED_REASONS[verdict.capability],
        provisional=verdict.provisional,
    )


def build_connection_vm(
    *,
    connection_id: str,
    platform: str,
    brand: str,
    external_username: str,
    status: ConnectionStatus,
    last_verified_at: str,
    granted_scope_labels: list[str],
    verdicts: tuple[CapabilityVerdict, ...],
    data_access_state: str = "",
    data_access_message: str = "",
) -> ConnectionVM:
    """Assemble a whitelisted VM, partitioning capabilities enabled/disabled here.

    Partitioning happens in this builder (called from the loader/handler), not in a
    computed var, so the frontend never receives the full verdict objects — only the
    two whitelisted lists it renders.
    """
    enabled: list[CapabilityVM] = []
    disabled: list[CapabilityVM] = []
    provisional_shown = False
    for verdict in verdicts:
        vm = _capability_vm(verdict)
        if vm.provisional and vm.enabled:
            provisional_shown = True
        (enabled if vm.enabled else disabled).append(vm)
    return ConnectionVM(
        id=connection_id,
        platform=platform,
        brand=brand,
        external_username=external_username,
        status=status,
        last_verified_at=last_verified_at,
        granted_scopes=granted_scope_labels,
        enabled_capabilities=enabled,
        disabled_capabilities=disabled,
        has_provisional_capabilities=provisional_shown,
        data_access_state=data_access_state,
        data_access_message=data_access_message,
    )
