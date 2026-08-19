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
7. `sync_now` (2026-08-15, TEMPORARY manual-sync affordance; wired to HTTP 2026-08-16)
   reaches `POST /api/inbox/sync` — NOT `composition.sync_comments` in-process, unlike
   `candidate_media`/`toggle_monitoring` — projects the route's JSON response into
   `SyncSummaryVM` field-for-field, and raises `UnknownInboxConnection` both for a 404
   from the route and for a tenant the temporary dev bridge cannot authenticate as.
8. `sync_now` (2026-08-18, QUA-88) raises `CommentsPermissionMissing` on a 403 and
   `SyncBudgetExhausted` on a 429 — both reconstructed from the status code alone, same
   posture as the 404 case, and both distinct from the 502/`httpx.HTTPStatusError` a
   failed Meta call raises.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import inspect
from collections.abc import Callable, Coroutine, Iterator
from datetime import UTC, datetime
from uuid import UUID

import httpx
from qualify_api.inbox import (
    CommentsPermissionMissing,
    SyncBudgetExhausted,
    UnknownInboxConnection,
)
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


def test_sync_now_goes_through_the_http_route_not_composition_directly() -> None:
    """B2's acceptance criterion is `POST /api/inbox/sync` — `sync_now` must reach it,
    not call `composition.sync_comments` in-process the way the other two provider
    functions deliberately still do (see the module docstring for why sync is the one
    exception)."""
    source = inspect.getsource(inbox_provider.sync_now)
    assert '"/api/inbox/sync"' in source
    assert "composition.sync_comments(" not in source
    assert "await sync_comments(" not in source  # the old in-process call shape


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


def _mock_asgi_client(status_code: int, json_body: dict) -> httpx.AsyncClient:
    """A fake in-process ASGI client for `sync_now` — no FastAPI app involved, just the
    HTTP contract `sync_now` actually depends on (status code + JSON body). Lighter than
    building a real `create_app()`, and keeps this file's "never a database, never the
    API package's internals" posture (see the module docstring) even though
    `inbox_provider.py` itself now imports `qualify_api.http.app` lazily."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/inbox/sync"
        assert request.headers["authorization"] == f"Bearer {inbox_provider._DEV_SYNC_BEARER_TOKEN}"
        return httpx.Response(status_code, json=json_body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")


def test_sync_now_rejects_a_tenant_the_dev_bridge_is_not_wired_for() -> None:
    """The guard that runs BEFORE any HTTP call — a mismatched dev tenant must never
    silently sync against the one tenant the bridge actually authenticates as."""
    other_tenant = UUID("00000000-0000-4000-8000-000000000099")
    assert other_tenant != inbox_provider._DEV_SYNC_TENANT_ID  # sanity on the fixture itself

    try:
        _run_coro(inbox_provider.sync_now(tenant_id=other_tenant, connection_id=_CONNECTION))
    except UnknownInboxConnection:
        pass
    else:
        raise AssertionError("sync_now must refuse a tenant the dev bridge cannot authenticate as")


def test_sync_now_projects_summary_fields() -> None:
    client = _mock_asgi_client(200, {"media_checked": 3, "new_comments": 7, "truncated": False})

    with _patched(_inbox_sync_asgi_client=lambda: client):
        vm = _run_coro(
            inbox_provider.sync_now(
                tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
            )
        )
    assert vm.media_checked == 3
    assert vm.new_comments == 7
    assert vm.truncated is False


def test_sync_now_projects_a_truncated_summary() -> None:
    """QUA-88: a budget that ran out mid-sync is still a 200 with the flag set — must
    reach the VM, not be lost in translation."""
    client = _mock_asgi_client(200, {"media_checked": 1, "new_comments": 1, "truncated": True})

    with _patched(_inbox_sync_asgi_client=lambda: client):
        vm = _run_coro(
            inbox_provider.sync_now(
                tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
            )
        )
    assert vm.truncated is True


def test_sync_now_propagates_unknown_connection_on_a_404() -> None:
    client = _mock_asgi_client(404, {"detail": "unknown connection"})

    with _patched(_inbox_sync_asgi_client=lambda: client):
        try:
            _run_coro(
                inbox_provider.sync_now(
                    tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
                )
            )
        except UnknownInboxConnection:
            pass
        else:
            raise AssertionError("sync_now must not swallow a 404 as success")


def test_sync_now_raises_permission_missing_on_a_403() -> None:
    """`cannot_observe` (QUA-88) — distinct from a 404 (unknown connection) and from a
    502 (a call that was attempted and failed)."""
    client = _mock_asgi_client(403, {"detail": "missing scope"})

    with _patched(_inbox_sync_asgi_client=lambda: client):
        try:
            _run_coro(
                inbox_provider.sync_now(
                    tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
                )
            )
        except CommentsPermissionMissing:
            pass
        else:
            raise AssertionError("sync_now must not swallow a 403 as success")


def test_sync_now_raises_budget_exhausted_on_a_429() -> None:
    client = _mock_asgi_client(429, {"detail": "sync needs at least 5 Meta call(s)"})

    with _patched(_inbox_sync_asgi_client=lambda: client):
        try:
            _run_coro(
                inbox_provider.sync_now(
                    tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
                )
            )
        except SyncBudgetExhausted:
            pass
        else:
            raise AssertionError("sync_now must not swallow a 429 as success")


def test_sync_now_raises_for_a_failed_meta_call() -> None:
    """A 502 (the route's mapping for `CommentsReadError`) is deliberately NOT collapsed
    into `UnknownInboxConnection` — it is a different failure the caller should be able
    to tell apart, same as `httpx.HTTPStatusError` already lets `InboxState.sync_comments`
    tell apart via its blanket `except Exception` branch."""
    client = _mock_asgi_client(502, {"detail": "GET /m/comments failed with HTTP 500"})

    with _patched(_inbox_sync_asgi_client=lambda: client):
        try:
            _run_coro(
                inbox_provider.sync_now(
                    tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
                )
            )
        except httpx.HTTPStatusError:
            pass
        else:
            raise AssertionError("sync_now must not swallow a failed Meta call as success")


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
