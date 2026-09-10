"""Pure, network-free tests for the publish screen (A5 vertical slice) — mirrors
`test_connections.py`'s conventions.

Import only the pure modules (VM / provider), never Reflex and never a database, so this
runs with a plain interpreter:

    uv run python -m Qualify.test_publishing_ui

or under pytest: `uv run pytest Qualify/test_publishing_ui.py`.

Pins:
1. `PublishAttemptVM`/`ConnectionOptionVM` carry no credential-bearing field (same QUA-18
   convention as `ConnectionVM`) — moot today since `PublishState`/`PublishService` never
   carry a token either, but the test guards against that changing silently.
2. `publishing_provider` calls the REAL seam (`stage_and_start_publish`/
   `advance_publish`), not a reimplementation of it.
3. `active_connections` filters to `status == "active"` only.
4. `start_publish`/`poll_publish` propagate `UnknownConnection`/`UnknownAttempt` rather
   than swallowing them — same posture `connections_provider.disconnect` already has for
   `ConnectionNotFound`.
5. The provider's VM projection coerces the service's nullable fields (`published_media_id`,
   `reason`) to `""`, never lets a raw `None` reach a `str` field.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import inspect
from collections.abc import Callable, Coroutine, Iterator
from uuid import UUID

from qualify_api.publishing.composition import PendingUpload
from qualify_api.publishing.service import PublishState as ServicePublishState
from qualify_api.publishing.service import TooManyItems, UnknownAttempt, UnknownConnection

from . import publishing_provider
from .connections_vm import ConnectionVM
from .publishing_vm import ConnectionOptionVM, PublishAttemptVM

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

_TENANT = UUID("a0000000-0000-4000-8000-000000000002")
_CONNECTION = UUID("c0000000-0000-4000-8000-000000000002")
_ATTEMPT = UUID("e0000000-0000-4000-8000-000000000002")


@contextlib.contextmanager
def _patched(**replacements: Callable[..., object]) -> Iterator[None]:
    """Swap module attributes of `publishing_provider` for the body of a `with`.

    Hand-rolled rather than `monkeypatch` for the same reason `test_connections.py` does
    it: these tests keep running under the plain `python -m` harness at the bottom of
    this file, which has no pytest fixtures.
    """
    originals = {name: getattr(publishing_provider, name) for name in replacements}
    for name, value in replacements.items():
        setattr(publishing_provider, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(publishing_provider, name, value)


def _run_coro(coro: Coroutine) -> object:
    return asyncio.run(coro)


def _connection_row(**overrides: object) -> ConnectionVM:
    defaults: dict[str, object] = {
        "id": str(_CONNECTION),
        "platform": "instagram",
        "brand": "PuntoServis",
        "external_username": "@puntoservis",
        "status": "active",
        "last_verified_at": "10 ago 2026, 09:00",
        "granted_scopes": [],
    }
    defaults.update(overrides)
    return ConnectionVM(**defaults)


def _service_state(**overrides: object) -> ServicePublishState:
    defaults: dict[str, object] = {
        "attempt_id": _ATTEMPT,
        "status": "processing",
        "settled": False,
        "published_media_id": None,
        "reason": None,
        "awaiting_confirmation": False,
        "poll_interval_seconds": 60,
    }
    defaults.update(overrides)
    return ServicePublishState(**defaults)


def test_vms_have_no_credential_fields() -> None:
    for vm_cls in (PublishAttemptVM, ConnectionOptionVM):
        for f in dataclasses.fields(vm_cls):
            lowered = f.name.lower()
            for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
                assert fragment not in lowered, (
                    f"{vm_cls.__name__}.{f.name} looks credential-bearing "
                    f"(matched '{fragment}') — the VM is the security boundary."
                )


def test_provider_calls_the_real_publishing_seam() -> None:
    """The write path must delegate to `qualify_api.publishing`, not reimplement it."""
    source = inspect.getsource(publishing_provider)
    assert "stage_and_start_publish(" in source
    assert "advance_publish(" in source


def test_active_connections_filters_to_status_active() -> None:
    rows = [
        _connection_row(id="c-active", status="active"),
        _connection_row(id="c-degraded", status="degraded"),
        _connection_row(id="c-revoked", status="revoked"),
    ]
    with _patched(connections_for=lambda _tenant: rows):
        options = publishing_provider.active_connections(_TENANT)
    assert [o.id for o in options] == ["c-active"]
    assert options[0].external_username == "@puntoservis"
    assert options[0].platform == "instagram"


def test_active_connections_projects_no_extra_fields() -> None:
    """The selector needs id/username/platform only — nothing else from `ConnectionVM`
    (capabilities, scopes, verification timestamps) should leak into this projection."""
    with _patched(connections_for=lambda _tenant: [_connection_row()]):
        (option,) = publishing_provider.active_connections(_TENANT)
    assert dataclasses.fields(type(option)) == dataclasses.fields(ConnectionOptionVM)


def test_start_publish_projects_null_fields_to_empty_strings() -> None:
    async def _fake(**kwargs: object) -> ServicePublishState:
        return _service_state()

    with _patched(stage_and_start_publish=_fake):
        vm = _run_coro(
            publishing_provider.start_publish(
                tenant_id=_TENANT,
                connection_id=_CONNECTION,
                fileobj=None,  # type: ignore[arg-type] — never touched by the fake
                content_type="video/mp4",
                caption="",
                idempotency_key="k-1",
            )
        )
    assert vm.published_media_id == ""
    assert vm.reason == ""
    assert vm.attempt_id == str(_ATTEMPT)


def test_start_publish_fixes_media_product_type_to_reels() -> None:
    seen: dict[str, object] = {}

    async def _fake(**kwargs: object) -> ServicePublishState:
        seen.update(kwargs)
        return _service_state()

    with _patched(stage_and_start_publish=_fake):
        _run_coro(
            publishing_provider.start_publish(
                tenant_id=_TENANT,
                connection_id=_CONNECTION,
                fileobj=None,  # type: ignore[arg-type]
                content_type="video/mp4",
                caption="hola",
                idempotency_key="k-1",
            )
        )
    assert seen["media_product_type"] == "REELS"
    assert seen["caption"] == "hola"
    assert seen["idempotency_key"] == "k-1"


def test_start_publish_propagates_unknown_connection() -> None:
    async def _raise(**kwargs: object) -> ServicePublishState:
        raise UnknownConnection(str(_CONNECTION))

    with _patched(stage_and_start_publish=_raise):
        try:
            _run_coro(
                publishing_provider.start_publish(
                    tenant_id=_TENANT,
                    connection_id=_CONNECTION,
                    fileobj=None,  # type: ignore[arg-type]
                    content_type="video/mp4",
                    caption="",
                    idempotency_key="k-1",
                )
            )
        except UnknownConnection:
            pass
        else:
            raise AssertionError("start_publish must not swallow UnknownConnection")


def test_poll_publish_propagates_unknown_attempt() -> None:
    async def _raise(**kwargs: object) -> ServicePublishState:
        raise UnknownAttempt(str(_ATTEMPT))

    with _patched(advance_publish=_raise):
        try:
            _run_coro(publishing_provider.poll_publish(tenant_id=_TENANT, attempt_id=_ATTEMPT))
        except UnknownAttempt:
            pass
        else:
            raise AssertionError("poll_publish must not swallow UnknownAttempt")


def test_poll_publish_projects_a_settled_state() -> None:
    async def _fake(**kwargs: object) -> ServicePublishState:
        return _service_state(
            status="published",
            settled=True,
            published_media_id="media-9",
            reason=None,
        )

    with _patched(advance_publish=_fake):
        vm = _run_coro(publishing_provider.poll_publish(tenant_id=_TENANT, attempt_id=_ATTEMPT))
    assert vm.settled is True
    assert vm.status == "published"
    assert vm.published_media_id == "media-9"


# --------------------------------------------------------------------------------------
# QUA-99 (5/6) — start_many_publish, the multi-video counterpart of start_publish
# --------------------------------------------------------------------------------------


def test_provider_calls_the_real_multi_publishing_seam() -> None:
    """Same posture as the single-video pin above: the multi-video write path must
    delegate to `qualify_api.publishing`, not reimplement staging/orchestration here."""
    source = inspect.getsource(publishing_provider)
    assert "stage_and_start_many_publish(" in source


def test_start_many_publish_projects_null_fields_to_empty_strings() -> None:
    async def _fake(**kwargs: object) -> ServicePublishState:
        return _service_state()

    with _patched(stage_and_start_many_publish=_fake):
        vm = _run_coro(
            publishing_provider.start_many_publish(
                tenant_id=_TENANT,
                connection_id=_CONNECTION,
                items=[PendingUpload(fileobj=None, content_type="video/mp4")],  # type: ignore[arg-type]
                caption="",
                idempotency_key="k-1",
            )
        )
    assert vm.published_media_id == ""
    assert vm.reason == ""
    assert vm.attempt_id == str(_ATTEMPT)


def test_start_many_publish_forwards_items_caption_and_idempotency_key() -> None:
    seen: dict[str, object] = {}

    async def _fake(**kwargs: object) -> ServicePublishState:
        seen.update(kwargs)
        return _service_state()

    items = [
        PendingUpload(fileobj=None, content_type="video/mp4"),  # type: ignore[arg-type]
        PendingUpload(fileobj=None, content_type="video/quicktime"),  # type: ignore[arg-type]
    ]
    with _patched(stage_and_start_many_publish=_fake):
        _run_coro(
            publishing_provider.start_many_publish(
                tenant_id=_TENANT,
                connection_id=_CONNECTION,
                items=items,
                caption="hola carrusel",
                idempotency_key="k-multi-1",
            )
        )
    assert seen["items"] == items  # same list, same order — nothing rebuilt in between
    assert seen["caption"] == "hola carrusel"
    assert seen["idempotency_key"] == "k-multi-1"


def test_start_many_publish_propagates_unknown_connection() -> None:
    async def _raise(**kwargs: object) -> ServicePublishState:
        raise UnknownConnection(str(_CONNECTION))

    with _patched(stage_and_start_many_publish=_raise):
        try:
            _run_coro(
                publishing_provider.start_many_publish(
                    tenant_id=_TENANT,
                    connection_id=_CONNECTION,
                    items=[PendingUpload(fileobj=None, content_type="video/mp4")],  # type: ignore[arg-type]
                    caption="",
                    idempotency_key="k-1",
                )
            )
        except UnknownConnection:
            pass
        else:
            raise AssertionError("start_many_publish must not swallow UnknownConnection")


def test_start_many_publish_propagates_too_many_items() -> None:
    """The >10 rejection (QUA-99, 4/6 and 5/6) must reach the caller, not be swallowed —
    same posture every other domain exception on this seam already has."""

    async def _raise(**kwargs: object) -> ServicePublishState:
        raise TooManyItems(11)

    with _patched(stage_and_start_many_publish=_raise):
        try:
            _run_coro(
                publishing_provider.start_many_publish(
                    tenant_id=_TENANT,
                    connection_id=_CONNECTION,
                    items=[PendingUpload(fileobj=None, content_type="video/mp4")],  # type: ignore[arg-type]
                    caption="",
                    idempotency_key="k-1",
                )
            )
        except TooManyItems:
            pass
        else:
            raise AssertionError("start_many_publish must not swallow TooManyItems")


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
