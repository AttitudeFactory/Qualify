"""Pure, network-free tests for the connections screen (C-06).

These import only the pure modules (capabilities / VM / provider projection), never
Reflex and never a database, so they run with a plain interpreter:

    uv run python -m Qualify.test_connections

or under pytest: `uv run pytest Qualify/test_connections.py`. The tests that need
the local Postgres live in `test_connections_db.py` and are marked `db`.

They pin six invariants:
0. The connect/disconnect seams call the REAL C-04 services and honour their contract:
   `ConnectionNotFound` surfaces as not-found and never as success, `changed is False`
   is a legitimate no-op, and the UI no longer drives the FSM itself. The services are
   substituted with local fakes here — the Postgres-backed proof is in
   `test_connections_db.py`.
1. The `ConnectionVM` boundary carries NO credential-bearing field (QUA-18 security).
2. The screen's Spanish copy covers the real C-05 matrix exhaustively — a capability
   added upstream fails here instead of raising KeyError in a running page.
3. The C-05 capability matrix is PESSIMISTIC: reading AND analyzing comments both
   require MANAGE_COMMENTS — CONFIRMED by Meta's own docs (QUA-95, 2026-08-27), no
   longer provisional; denying MANAGE_MESSAGES does NOT turn them off. This is the
   real matrix now, so the test also guards against a silent upstream relaxation.
4. The provider reaches Postgres only through `tenant_session` — the tenant-isolation
   guarantee is structural, not a property of any one query.
5. No trace of the pre-C-04 `/oauth/start` placeholder survives anywhere in the screen.
"""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import pathlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

from qualify_api.connections import DATA_ACCESS_WARNING_THRESHOLD, ConnectionNotFound, RevokeResult
from qualify_api.connections.fsm import ConnectionStatus as FsmStatus
from qualify_api.connections.models import SocialConnection
from qualify_api.connections.service import ConnectOutcome
from qualify_api.http import connections_routes

from . import connections_provider
from .capabilities import (
    ASSESSMENT_VERSION,
    CAPABILITY_DISABLED_REASONS,
    CAPABILITY_LABELS,
    SCOPE_KEY_LABELS,
    Capability,
    ScopeKey,
    assess_capabilities,
    resolve_scope_keys,
)
from .connections_provider import NoActingUser, _data_access_warning, _scope_labels, _to_vm
from .connections_vm import (
    CONNECT_RESULT_NOTICES,
    CapabilityVM,
    ConnectionVM,
    connect_result_notice,
)

# Field-name fragments that must never appear on a client-serialized view-model.
_FORBIDDEN_FIELD_FRAGMENTS = (
    "token",
    "credential",
    "cipher",
    "ciphertext",
    "secret",
    "key_id",
    "password",
    "plaintext",
)

_FULL_SCOPES = [
    "instagram_business_basic",
    "instagram_business_content_publish",
    "instagram_business_manage_comments",
    "instagram_business_manage_messages",
    "instagram_business_manage_insights",
]


_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_CONNECTION = UUID("c0000000-0000-4000-8000-000000000001")
_USER = UUID("d0000000-0000-4000-8000-000000000001")


@contextlib.contextmanager
def _patched(**replacements: Callable[..., object]) -> Iterator[None]:
    """Swap module attributes of `connections_provider` for the body of a `with`.

    Hand-rolled rather than `monkeypatch` so these tests keep running under the plain
    `python -m Qualify.test_connections` harness at the bottom of this file, which has
    no pytest fixtures.
    """
    originals = {name: getattr(connections_provider, name) for name in replacements}
    for name, value in replacements.items():
        setattr(connections_provider, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(connections_provider, name, value)


def _patched_revoke(fake: Callable[..., RevokeResult]) -> contextlib.AbstractContextManager[None]:
    return _patched(revoke_connection=fake)


def _verdict_map(granted: frozenset[ScopeKey]) -> dict[Capability, tuple[bool, bool]]:
    """capability -> (enabled, provisional)."""
    return {v.capability: (v.enabled, v.provisional) for v in assess_capabilities(granted)}


def _row(**overrides: object) -> SocialConnection:
    """An unattached `social_connections` row — constructing the ORM object touches no DB."""
    defaults: dict[str, object] = {
        "platform": "instagram",
        "external_account_id": "17841400000000000",
        "external_username": "@puntoservis",
        "status": "active",
        "granted_scopes": list(_FULL_SCOPES),
        "last_verified_at": datetime(2026, 7, 25, 9, 12, tzinfo=UTC),
        "current_credential_version": 1,
    }
    defaults.update(overrides)
    return SocialConnection(**defaults)


def test_connection_vm_has_no_credential_fields() -> None:
    for vm_cls in (ConnectionVM, CapabilityVM):
        for f in dataclasses.fields(vm_cls):
            lowered = f.name.lower()
            for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
                assert fragment not in lowered, (
                    f"{vm_cls.__name__}.{f.name} looks credential-bearing "
                    f"(matched '{fragment}') — the VM is the security boundary."
                )


def test_ui_copy_covers_every_capability_and_scope() -> None:
    for capability in Capability:
        assert capability in CAPABILITY_LABELS, f"{capability} has no UI label"
        assert capability in CAPABILITY_DISABLED_REASONS, f"{capability} has no disabled reason"
    for scope_key in ScopeKey:
        assert scope_key in SCOPE_KEY_LABELS, f"{scope_key} has no chip label"


def test_using_the_real_assessment_not_a_stub() -> None:
    assert ASSESSMENT_VERSION == "perm-capability-v2"


def test_matrix_pessimistic_read_analyze_require_manage_comments() -> None:
    # With only BASIC granted, reading and analyzing are OFF (pessimistic reading).
    basic_only = _verdict_map(frozenset({ScopeKey.BASIC}))
    assert basic_only[Capability.READ_COMMENTS][0] is False
    assert basic_only[Capability.ANALYZE_COMMENTS][0] is False
    assert basic_only[Capability.REPLY_COMMENTS][0] is False
    # QUA-95 (2026-08-27): the manage_comments gate is CONFIRMED by Meta's own docs,
    # not a pessimistic guess pending a live check anymore — none of the three is
    # provisional.
    assert basic_only[Capability.READ_COMMENTS][1] is False
    assert basic_only[Capability.ANALYZE_COMMENTS][1] is False
    assert basic_only[Capability.REPLY_COMMENTS][1] is False


def test_manage_comments_enables_read_analyze_reply() -> None:
    granted = frozenset({ScopeKey.BASIC, ScopeKey.MANAGE_COMMENTS})
    m = _verdict_map(granted)
    assert m[Capability.READ_COMMENTS][0] is True
    assert m[Capability.ANALYZE_COMMENTS][0] is True
    assert m[Capability.REPLY_COMMENTS][0] is True


def test_denying_dms_does_not_disable_read_or_analyze() -> None:
    # MANAGE_COMMENTS present, MANAGE_MESSAGES absent: comments capabilities survive,
    # only the DM inbox is off. This is the property that must stay alive.
    granted = frozenset({ScopeKey.BASIC, ScopeKey.MANAGE_COMMENTS})
    m = _verdict_map(granted)
    assert m[Capability.MANAGE_DMS][0] is False
    assert m[Capability.READ_COMMENTS][0] is True
    assert m[Capability.ANALYZE_COMMENTS][0] is True


def test_alternate_scope_spellings_resolve_to_the_same_key() -> None:
    # ADR 25: four spellings of the publish scope circulate. The Facebook-Login fork
    # spelling must light up the same capability as the Instagram-Login one.
    fork = frozenset({"instagram_basic", "instagram_content_publish"})
    resolved, unrecognized = resolve_scope_keys(fork)
    assert resolved == frozenset({ScopeKey.BASIC, ScopeKey.CONTENT_PUBLISH})
    assert unrecognized == frozenset()
    assert _verdict_map(resolved)[Capability.PUBLISH_CONTENT][0] is True


def test_unrecognized_scope_is_surfaced_not_swallowed() -> None:
    labels, resolved = _scope_labels(["instagram_business_basic", "instagram_future_scope"])
    assert "Básico" in labels
    assert any("instagram_future_scope" in label for label in labels), (
        "an unknown Meta scope must be shown, not silently dropped"
    )
    assert resolved == frozenset({ScopeKey.BASIC})


def test_known_infrastructure_scopes_are_labeled_distinctly() -> None:
    # QUA-96: the four scopes Meta grants to complete the OAuth/Page-enumeration flow
    # (ADR 25/R4) or automatically (`public_profile`) must read as "Infraestructura: …",
    # never as "Sin reconocer: …" — that text is reserved for a genuinely unknown scope.
    infra_literals = [
        "business_management",
        "pages_read_engagement",
        "pages_show_list",
        "public_profile",
    ]
    labels, resolved = _scope_labels(["instagram_business_basic", *infra_literals])
    for literal in infra_literals:
        assert f"Infraestructura: {literal}" in labels, f"{literal} not labeled as infra"
        assert f"Sin reconocer: {literal}" not in labels, f"{literal} still reads as unrecognized"
    assert resolved == frozenset({ScopeKey.BASIC})


def test_known_infrastructure_and_genuinely_unknown_scopes_coexist() -> None:
    # A known-infra literal and a truly unknown one in the same grant must not bleed
    # into each other's classification.
    labels, _resolved = _scope_labels(["business_management", "instagram_future_scope"])
    assert "Infraestructura: business_management" in labels
    assert "Sin reconocer: instagram_future_scope" in labels
    assert "Sin reconocer: business_management" not in labels
    assert "Infraestructura: instagram_future_scope" not in labels


def test_vm_shows_a_spanish_reason_only_when_disabled() -> None:
    vm = _to_vm(_row(granted_scopes=["instagram_business_basic"]), "PuntoServis")
    for cap in vm.enabled_capabilities:
        assert cap.reason == "", "an enabled capability must not ship a reason to the client"
    for cap in vm.disabled_capabilities:
        assert cap.reason, f"{cap.key} is disabled but has no reason"
        assert cap.reason in CAPABILITY_DISABLED_REASONS.values(), (
            "the screen must show the Spanish copy, not the engineering prose of the verdict"
        )
    disabled_keys = {c.key for c in vm.disabled_capabilities}
    assert str(Capability.READ_COMMENTS) in disabled_keys
    assert str(Capability.ANALYZE_COMMENTS) in disabled_keys
    # QUA-95 (2026-08-27): READ_COMMENTS/ANALYZE_COMMENTS were the only provisional
    # rows in the matrix; now that their gate is confirmed by Meta's own docs, no
    # capability shown here is provisional anymore.
    assert not any(c.provisional for c in vm.disabled_capabilities)


def test_vm_serializes_only_plain_values() -> None:
    vm = _to_vm(_row(), "PuntoServis")
    assert isinstance(vm.last_verified_at, str), "no raw datetime may reach the client"
    assert isinstance(vm.last_health_checked_at, str), "no raw datetime may reach the client"
    assert isinstance(vm.id, str)
    assert vm.external_username == "@puntoservis"


def test_vm_falls_back_when_username_or_brand_is_missing() -> None:
    vm = _to_vm(_row(external_username=None), None)
    assert vm.external_username == "17841400000000000"
    assert vm.brand == "Sin marca"


def test_never_verified_connection_reads_honestly() -> None:
    vm = _to_vm(_row(last_verified_at=None), "PuntoServis")
    assert vm.last_verified_at == "Nunca verificada"


def test_never_health_checked_connection_reads_honestly() -> None:
    """QUA-91: `_row()` sets no `last_health_checked_at` — the honest state before any
    "Verificar ahora" click has ever happened. Distinct fallback copy from
    `last_verified_at`'s own — the two must never be conflated."""
    vm = _to_vm(_row(), "PuntoServis")
    assert vm.last_health_checked_at == "Sin verificar"
    assert vm.last_health_checked_at != vm.last_verified_at


def test_health_checked_at_is_formatted_like_verified_at() -> None:
    """Same pre-format discipline, same pattern, a different concept and a different
    stored column (`last_health_checked_at`, not `last_verified_at`)."""
    checked_at = datetime(2026, 8, 21, 16, 33, tzinfo=UTC)
    vm = _to_vm(_row(last_health_checked_at=checked_at), "PuntoServis")
    assert vm.last_health_checked_at == "21 Aug 2026, 16:33"


def test_health_check_click_is_visible_even_when_last_verified_at_is_unchanged() -> None:
    """The exact UX gap this field closes: a "Verificar ahora" click updates
    `last_health_checked_at` only — `last_verified_at` legitimately stays untouched. The
    VM must still show something changed."""
    unchanged_verified_at = datetime(2026, 8, 20, 20, 57, tzinfo=UTC)
    vm = _to_vm(
        _row(last_verified_at=unchanged_verified_at, last_health_checked_at=None),
        "PuntoServis",
    )
    assert vm.last_health_checked_at == "Sin verificar"

    vm_after_click = _to_vm(
        _row(
            last_verified_at=unchanged_verified_at,
            last_health_checked_at=datetime(2026, 8, 21, 16, 33, tzinfo=UTC),
        ),
        "PuntoServis",
    )
    assert vm_after_click.last_verified_at == vm.last_verified_at, (
        "last_verified_at is untouched by a health-check, by design"
    )
    assert vm_after_click.last_health_checked_at != vm.last_health_checked_at, (
        "the click must be visible somewhere on the VM even though last_verified_at isn't"
    )


# --- QUA-91: data-access-window warning, deliberately independent of status/the FSM -----

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_data_access_warning_empty_when_never_checked() -> None:
    assert _data_access_warning(None, now=_NOW) == ("", "")


def test_data_access_warning_empty_when_far() -> None:
    far = _NOW + DATA_ACCESS_WARNING_THRESHOLD + timedelta(days=1)
    assert _data_access_warning(far, now=_NOW) == ("", "")


def test_data_access_warning_soon_within_threshold() -> None:
    delta = DATA_ACCESS_WARNING_THRESHOLD - timedelta(days=4)
    state, message = _data_access_warning(_NOW + delta, now=_NOW)
    assert state == "warning_soon"
    assert message == f"Acceso a datos vence en {delta.days} días"


def test_data_access_warning_today_and_tomorrow_read_naturally() -> None:
    assert _data_access_warning(_NOW + timedelta(hours=2), now=_NOW) == (
        "warning_soon",
        "Acceso a datos vence hoy",
    )
    assert _data_access_warning(_NOW + timedelta(days=1, hours=2), now=_NOW) == (
        "warning_soon",
        "Acceso a datos vence mañana",
    )


def test_data_access_warning_overdue_when_passed() -> None:
    state, message = _data_access_warning(_NOW - timedelta(days=1), now=_NOW)
    assert state == "warning_overdue"
    assert message == "Acceso a datos vencido"


def test_data_access_warning_never_implies_the_connection_is_broken() -> None:
    """The wording must never be confusable with the real, evidence-based `degraded`
    case (401/190 from `/debug_token`, QUA-90) — that is a separate, unrelated signal."""
    for expiry in (_NOW + timedelta(days=5), _NOW - timedelta(days=5)):
        _, message = _data_access_warning(expiry, now=_NOW)
        lowered = message.lower()
        for forbidden in ("inválid", "invalid", "degradad", "rota", "desconectad"):
            assert forbidden not in lowered, f"{message!r} reads as broken, not as a warning"


def test_vm_has_no_data_access_warning_by_default() -> None:
    """`_row()` sets no `data_access_expires_at` — the honest state before any
    "Verificar ahora" click has ever happened."""
    vm = _to_vm(_row(), "PuntoServis")
    assert vm.data_access_state == ""
    assert vm.data_access_message == ""


def test_vm_wires_the_data_access_warning_from_the_row() -> None:
    vm_overdue = _to_vm(
        _row(data_access_expires_at=datetime.now(UTC) - timedelta(days=1)), "PuntoServis"
    )
    assert vm_overdue.data_access_state == "warning_overdue"
    assert vm_overdue.data_access_message == "Acceso a datos vencido"
    # The warning never touches status — that is the whole point of keeping it separate.
    assert vm_overdue.status == "active"


def test_check_health_delegates_to_the_real_seam() -> None:
    seen: dict[str, object] = {}

    def _capture(*, tenant_id: UUID, connection_id: UUID) -> bool:
        seen.update(tenant_id=tenant_id, connection_id=connection_id)
        return True

    with _patched(check_connection_health=_capture):
        assert connections_provider.check_health(_TENANT, _CONNECTION) is True
    assert seen == {"tenant_id": _TENANT, "connection_id": _CONNECTION}


def test_disconnect_surfaces_not_found_instead_of_reporting_success() -> None:
    """The behavior C-04 changed, pinned.

    The old UI workaround `return`ed silently when the row was `None`, which told an
    operator who passed an id they do not own that the revoke succeeded — `None` also
    means "another tenant's row, filtered by RLS". The real service raises, and this
    module must let it through.
    """
    raised: list[UUID] = []

    def _not_found(*, tenant_id: UUID, connection_id: UUID, actor: str = "user") -> RevokeResult:
        raised.append(connection_id)
        raise ConnectionNotFound(str(connection_id))

    with _patched_revoke(_not_found):
        try:
            connections_provider.disconnect(_TENANT, _CONNECTION)
        except ConnectionNotFound:
            pass
        else:
            raise AssertionError(
                "disconnect must not swallow ConnectionNotFound — silently reporting "
                "success for another tenant's id is the bug C-04 fixed"
            )
    assert raised == [_CONNECTION]


def test_disconnect_treats_an_already_revoked_connection_as_a_no_op() -> None:
    """`changed is False` is a legitimate outcome: a double-click must not raise."""

    def _unchanged(*, tenant_id: UUID, connection_id: UUID, actor: str = "user") -> RevokeResult:
        return RevokeResult(connection_id=connection_id, status=FsmStatus.REVOKED, changed=False)

    with _patched_revoke(_unchanged):
        assert connections_provider.disconnect(_TENANT, _CONNECTION) is False


def test_disconnect_attributes_the_action_to_the_user() -> None:
    seen: dict[str, object] = {}

    def _capture(*, tenant_id: UUID, connection_id: UUID, actor: str = "user") -> RevokeResult:
        seen.update(tenant_id=tenant_id, connection_id=connection_id, actor=actor)
        return RevokeResult(connection_id=connection_id, status=FsmStatus.REVOKED, changed=True)

    with _patched_revoke(_capture):
        assert connections_provider.disconnect(_TENANT, _CONNECTION) is True
    assert seen == {"tenant_id": _TENANT, "connection_id": _CONNECTION, "actor": "user"}


def test_ui_no_longer_drives_the_fsm_itself() -> None:
    """The revoke write must go through the service, not through `next_status`.

    Driving the FSM from the UI produced the right status but announced the transition
    to nobody: no `apply_transition`, so no domain event. Guard against it coming back.
    """
    source = inspect.getsource(connections_provider)
    assert "revoke_connection(" in source, "revocation must delegate to the C-04 service"
    # Call form, not bare name: the module's prose legitimately NAMES these to explain
    # what the service does on its behalf.
    for forbidden in ("next_status(", "ConnectionEvent(", "apply_transition("):
        assert forbidden not in source, (
            f"{forbidden} in the UI layer means the UI is driving the FSM itself"
        )


def test_the_oauth_placeholder_route_is_gone() -> None:
    """C-04 shipped, so no stub target may survive in the UI.

    `connections_page.py` is read from disk rather than imported: importing it would
    pull Reflex into this deliberately Reflex-free module.
    """
    here = pathlib.Path(__file__).parent
    for filename in ("connections_provider.py", "connections_page.py", "connections_state.py"):
        source = (here / filename).read_text(encoding="utf-8")
        assert "/oauth/start" not in source, f"{filename} still points at the C-04 stub"
    assert not hasattr(connections_provider, "_OAUTH_START_ROUTE")


def test_begin_connect_attributes_the_grant_to_the_tenants_own_user() -> None:
    """`user_id` is signed into the `state` payload, so it must be a real in-tenant row."""
    seen: dict[str, object] = {}

    def _capture(*, tenant_id: UUID, brand_id: UUID | None, user_id: UUID) -> str:
        seen.update(tenant_id=tenant_id, brand_id=brand_id, user_id=user_id)
        return "https://www.facebook.com/v23.0/dialog/oauth?state=signed"

    with _patched(start_connect=_capture, acting_user_id=lambda _tenant: _USER):
        assert connections_provider.begin_connect(_TENANT).startswith("https://")
    # brand_id is None on purpose: no brand picker in Sprint 1, and the repository
    # reads a null brand on a grant as "keep the one already there".
    assert seen == {"tenant_id": _TENANT, "brand_id": None, "user_id": _USER}


def test_begin_connect_refuses_when_the_tenant_has_no_user() -> None:
    """Rather than fabricate a uuid into the audit trail of `connected_by_user_id`."""

    def _unreachable(*, tenant_id: UUID, brand_id: UUID | None, user_id: UUID) -> str:
        raise AssertionError("start_connect must not be called without an acting user")

    with _patched(start_connect=_unreachable, acting_user_id=lambda _tenant: None):
        try:
            connections_provider.begin_connect(_TENANT)
        except NoActingUser:
            pass
        else:
            raise AssertionError("begin_connect must raise NoActingUser, not guess a user")


def test_provider_reaches_postgres_only_through_tenant_session() -> None:
    """Tenant isolation is structural: `tenant_session` sets the RLS GUC, so no query
    in this module can read another tenant's rows even if it forgets a WHERE clause.
    A `create_engine`/`sessionmaker` here would route around that."""
    source = inspect.getsource(connections_provider)
    for forbidden in ("create_engine", "sessionmaker", "admin_session", "credential_dsn"):
        assert forbidden not in source, f"{forbidden} bypasses the single sanctioned door (C-01.4)"
    assert source.count("tenant_session(") >= 2, "every DB access must open a tenant_session"


def test_verify_now_button_wires_a_per_card_loading_indicator() -> None:
    """QUA-91 UX follow-up: a manual validation found the click gave no visible
    feedback while a real `/debug_token` call ran. `connections_page.py` is read from
    disk rather than imported — same reason `test_the_oauth_placeholder_route_is_gone`
    does — so this stays Reflex-free.

    Pins that `loading=` is keyed to THIS card's id (`.contains(conn.id)`, the same
    per-row pattern `InboxState.toggling_media_ids` uses), not a page-wide flag — a
    single `ConnectionsState.is_loading`-style bool here would freeze every OTHER
    card's button too. No separate `disabled=` is expected: Radix's `loading` prop
    already covers both the spinner and the disabled state in one prop.
    """
    here = pathlib.Path(__file__).parent
    source = (here / "connections_page.py").read_text(encoding="utf-8")
    button_start = source.index("def verify_now_button")
    return_start = source.index("return rx.button(", button_start)
    button_call = source[return_start : source.index("\n\n\n", return_start)]
    assert "loading=ConnectionsState.checking_connection_ids.contains(conn.id)" in button_call
    assert "disabled=" not in button_call, (
        "loading= already disables the button; a separate disabled= would be redundant"
    )


def test_every_callback_code_has_a_notice() -> None:
    """QUA-123: the callback redirects with `?connect=<code>`; each code it can emit has
    copy here, and a junk value in the URL renders nothing instead of being echoed."""
    emitted = {str(o) for o in ConnectOutcome} | {
        connections_routes.INVALID_STATE,
        connections_routes.DENIED,
    }
    assert set(CONNECT_RESULT_NOTICES) == emitted
    for message, tone in CONNECT_RESULT_NOTICES.values():
        assert message
        assert tone in {"ok", "warn", "info"}
    assert connect_result_notice("active")[1] == "ok"
    assert connect_result_notice("") == ("", "info")
    assert connect_result_notice("<script>") == ("", "info")


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface any error in the harness
            failures += 1
            print(f"ERROR {test.__name__}: {exc!r}")
        else:
            print(f"ok   {test.__name__}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run())
