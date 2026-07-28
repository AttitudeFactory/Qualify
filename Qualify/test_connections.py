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
   require MANAGE_COMMENTS (provisional); denying MANAGE_MESSAGES does NOT turn them
   off. This is the real matrix now, so the test also guards against a silent
   upstream relaxation.
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
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.connections import ConnectionNotFound, RevokeResult
from qualify_api.connections.fsm import ConnectionStatus as FsmStatus
from qualify_api.connections.models import SocialConnection

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
from .connections_provider import NoActingUser, _scope_labels, _to_vm
from .connections_vm import CapabilityVM, ConnectionVM

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
    assert ASSESSMENT_VERSION == "perm-capability-v1"


def test_matrix_pessimistic_read_analyze_require_manage_comments() -> None:
    # With only BASIC granted, reading and analyzing are OFF (pessimistic reading).
    basic_only = _verdict_map(frozenset({ScopeKey.BASIC}))
    assert basic_only[Capability.READ_COMMENTS][0] is False
    assert basic_only[Capability.ANALYZE_COMMENTS][0] is False
    assert basic_only[Capability.REPLY_COMMENTS][0] is False
    # And they are flagged provisional (rest on the unverified Meta doc row).
    assert basic_only[Capability.READ_COMMENTS][1] is True
    assert basic_only[Capability.ANALYZE_COMMENTS][1] is True
    # Reply is non-provisional.
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
    assert any(c.provisional for c in vm.disabled_capabilities)


def test_vm_serializes_only_plain_values() -> None:
    vm = _to_vm(_row(), "PuntoServis")
    assert isinstance(vm.last_verified_at, str), "no raw datetime may reach the client"
    assert isinstance(vm.id, str)
    assert vm.external_username == "@puntoservis"


def test_vm_falls_back_when_username_or_brand_is_missing() -> None:
    vm = _to_vm(_row(external_username=None), None)
    assert vm.external_username == "17841400000000000"
    assert vm.brand == "Sin marca"


def test_never_verified_connection_reads_honestly() -> None:
    vm = _to_vm(_row(last_verified_at=None), "PuntoServis")
    assert vm.last_verified_at == "Nunca verificada"


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
