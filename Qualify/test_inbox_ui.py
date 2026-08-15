"""Pure, network-free tests for the inbox content screen (Fase 1 Parte 4-B, B2 UI
slice) — mirrors `test_publishing_ui.py`'s conventions.

Import only the pure modules (VM / provider), never Reflex and never a database, so this
runs with a plain interpreter:

    uv run python -m Qualify.test_inbox_ui

or under pytest: `uv run pytest Qualify/test_inbox_ui.py`.

Pins:
1. `CandidateMediaVM` carries no credential-bearing field (same QUA-18 convention as
   `ConnectionVM`/`PublishAttemptVM`).
2. `inbox_provider` calls the REAL seam (`list_candidate_media`/`set_media_monitored`),
   not a reimplementation of it.
3. `instagram_connections` filters to `platform == "instagram"`, `status == "active"`
   AND the `READ_COMMENTS` capability enabled — not any one of the three alone.
4. `candidate_media`/`toggle_monitoring` propagate `UnknownInboxConnection`/
   `MediaNotEligible` rather than swallowing them — same posture
   `connections_provider.disconnect` already has for `ConnectionNotFound`.
5. The provider's VM projection coerces the service's nullable fields (`caption`,
   `permalink`, `thumbnail_url`) to `""`, never lets a raw `None` reach a `str` field.
6. Candidates come back newest-first.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import inspect
from collections.abc import Callable, Coroutine, Iterator
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.inbox import UnknownInboxConnection
from qualify_api.inbox.service import CandidateMedia, MediaNotEligible

from . import inbox_provider
from .connections_vm import CapabilityVM, ConnectionVM
from .inbox_vm import CandidateMediaVM

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

_TENANT = UUID("a0000000-0000-4000-8000-000000000003")
_CONNECTION = UUID("c0000000-0000-4000-8000-000000000003")


@contextlib.contextmanager
def _patched(**replacements: Callable[..., object]) -> Iterator[None]:
    """Swap module attributes of `inbox_provider` for the body of a `with`. Hand-rolled
    rather than `monkeypatch`, same reason `test_publishing_ui.py`/`test_connections.py`
    do it: these tests keep running under the plain `python -m` harness at the bottom of
    this file, which has no pytest fixtures."""
    originals = {name: getattr(inbox_provider, name) for name in replacements}
    for name, value in replacements.items():
        setattr(inbox_provider, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(inbox_provider, name, value)


def _run_coro(coro: Coroutine) -> object:
    return asyncio.run(coro)


def _cap(key: str, *, enabled: bool) -> CapabilityVM:
    return CapabilityVM(key=key, label=key, enabled=enabled, reason="", provisional=False)


def _connection_row(**overrides: object) -> ConnectionVM:
    defaults: dict[str, object] = {
        "id": str(_CONNECTION),
        "platform": "instagram",
        "brand": "PuntoServis",
        "external_username": "@puntoservis",
        "status": "active",
        "last_verified_at": "10 ago 2026, 09:00",
        "granted_scopes": [],
        "enabled_capabilities": [_cap("read_comments", enabled=True)],
    }
    defaults.update(overrides)
    return ConnectionVM(**defaults)


def _media(**overrides: object) -> CandidateMedia:
    defaults: dict[str, object] = {
        "external_media_id": "m-1",
        "timestamp": datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        "is_monitored": False,
        "caption": None,
        "permalink": None,
        "thumbnail_url": None,
    }
    defaults.update(overrides)
    return CandidateMedia(**defaults)


def test_vm_has_no_credential_fields() -> None:
    for f in dataclasses.fields(CandidateMediaVM):
        lowered = f.name.lower()
        for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
            assert fragment not in lowered, (
                f"CandidateMediaVM.{f.name} looks credential-bearing "
                f"(matched '{fragment}') — the VM is the security boundary."
            )


def test_provider_calls_the_real_inbox_seam() -> None:
    source = inspect.getsource(inbox_provider)
    assert "list_candidate_media(" in source
    assert "set_media_monitored(" in source


def test_instagram_connections_requires_active_instagram_and_read_comments() -> None:
    rows = [
        _connection_row(id="ok", status="active", platform="instagram"),
        _connection_row(id="not-active", status="degraded", platform="instagram"),
        _connection_row(id="not-instagram", status="active", platform="facebook"),
        _connection_row(
            id="no-capability",
            status="active",
            platform="instagram",
            enabled_capabilities=[],
        ),
    ]
    with _patched(connections_for=lambda _tenant: rows):
        options = inbox_provider.instagram_connections(_TENANT)
    assert [o.id for o in options] == ["ok"]


def test_candidate_media_projects_null_fields_to_empty_strings() -> None:
    async def _fake(**kwargs: object) -> tuple[CandidateMedia, ...]:
        return (_media(),)

    with _patched(list_candidate_media=_fake):
        (vm,) = _run_coro(
            inbox_provider.candidate_media(tenant_id=_TENANT, connection_id=_CONNECTION)
        )
    assert vm.caption == ""
    assert vm.permalink == ""
    assert vm.thumbnail_url == ""
    assert vm.external_media_id == "m-1"


def test_candidate_media_carries_display_fields_through() -> None:
    async def _fake(**kwargs: object) -> tuple[CandidateMedia, ...]:
        return (
            _media(
                caption="hola",
                permalink="https://instagram.com/reel/m-1",
                thumbnail_url="https://cdn/m-1.jpg",
            ),
        )

    with _patched(list_candidate_media=_fake):
        (vm,) = _run_coro(
            inbox_provider.candidate_media(tenant_id=_TENANT, connection_id=_CONNECTION)
        )
    assert vm.caption == "hola"
    assert vm.permalink == "https://instagram.com/reel/m-1"
    assert vm.thumbnail_url == "https://cdn/m-1.jpg"


def test_candidate_media_sorts_newest_first() -> None:
    older = _media(external_media_id="old", timestamp=datetime(2026, 8, 1, tzinfo=UTC))
    newer = _media(external_media_id="new", timestamp=datetime(2026, 8, 10, tzinfo=UTC))

    async def _fake(**kwargs: object) -> tuple[CandidateMedia, ...]:
        return (older, newer)

    with _patched(list_candidate_media=_fake):
        vms = _run_coro(
            inbox_provider.candidate_media(tenant_id=_TENANT, connection_id=_CONNECTION)
        )
    assert [vm.external_media_id for vm in vms] == ["new", "old"]


def test_candidate_media_propagates_unknown_connection() -> None:
    async def _raise(**kwargs: object) -> tuple[CandidateMedia, ...]:
        raise UnknownInboxConnection(str(_CONNECTION))

    with _patched(list_candidate_media=_raise):
        try:
            _run_coro(inbox_provider.candidate_media(tenant_id=_TENANT, connection_id=_CONNECTION))
        except UnknownInboxConnection:
            pass
        else:
            raise AssertionError("candidate_media must not swallow UnknownInboxConnection")


def test_toggle_monitoring_propagates_media_not_eligible() -> None:
    async def _raise(**kwargs: object) -> None:
        raise MediaNotEligible("m-1", reason="too_old")

    with _patched(set_media_monitored=_raise):
        try:
            _run_coro(
                inbox_provider.toggle_monitoring(
                    tenant_id=_TENANT,
                    connection_id=_CONNECTION,
                    external_media_id="m-1",
                    monitored=True,
                )
            )
        except MediaNotEligible as exc:
            assert exc.reason == "too_old"
        else:
            raise AssertionError("toggle_monitoring must not swallow MediaNotEligible")


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
