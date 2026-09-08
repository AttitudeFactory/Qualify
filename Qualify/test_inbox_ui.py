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
9. `analyze_sentiment_now` (QUA-92, "Analizar sentimiento" button) reaches
   `POST /api/sentiment/analyze` — QUA-21's existing, already-wired route — and never
   calls `analyze_pending_comments`/`composition.analyze_pending_comments` directly (no
   second analysis engine). Projects `comments_checked`/`new_results`/`skipped_empty`
   field-for-field, including the all-zero "nothing pending" case, and raises
   `UnknownSentimentConnection` for both the dev-bridge tenant mismatch and a 404.
10. `reel_summaries_page`/`global_summary_vm`/`thread_comments_page` (QUA-93) call the
    real read seams (`qualify_api.sentiment.list_reel_summaries`/
    `global_sentiment_summary`/`list_comments_for_thread`), none `async def` (ordinary
    blocking Postgres access — `InboxState` is responsible for `asyncio.to_thread`).
    `reel_summaries_page` enriches thumbnail/caption/permalink from the ALREADY-loaded
    `CandidateMediaVM` list it's handed (opción A, zero extra Meta call) and builds a
    `ReelPageCursorVM` from the last row of a non-empty page. `thread_comments_page`
    maps `"ALL"`/blank search to `None` before calling the repository, passes any other
    filter/search value straight through. All three propagate
    `UnknownSentimentConnection` rather than swallowing it.
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
from qualify_api.sentiment import UnknownSentimentConnection
from qualify_api.sentiment.repository import (
    DEFAULT_REEL_PAGE_SIZE,
    AnalyzedComment,
    GlobalSentimentSummary,
    ReelSummary,
)

from . import inbox_provider
from .connections_vm import CapabilityVM, ConnectionVM
from .inbox_vm import CandidateMediaVM, CommentVM, ReelSummaryVM

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


def _comment(**overrides: object) -> AnalyzedComment:
    defaults: dict[str, object] = {
        "message_id": UUID("d0000000-0000-4000-8000-000000000001"),
        "source_id": "comment-1",
        "text": "me encanta",
        "author_username": "cliente_feliz",
        "posted_at": datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
        "external_thread_id": "media-1",
        "label": None,
        "score": None,
    }
    defaults.update(overrides)
    return AnalyzedComment(**defaults)


def test_vm_has_no_credential_fields() -> None:
    for f in dataclasses.fields(CandidateMediaVM):
        lowered = f.name.lower()
        for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
            assert fragment not in lowered, (
                f"CandidateMediaVM.{f.name} looks credential-bearing "
                f"(matched '{fragment}') — the VM is the security boundary."
            )


def test_comment_vm_has_no_credential_fields() -> None:
    for f in dataclasses.fields(CommentVM):
        lowered = f.name.lower()
        for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
            assert fragment not in lowered, (
                f"CommentVM.{f.name} looks credential-bearing "
                f"(matched '{fragment}') — the VM is the security boundary."
            )


def test_reel_summary_vm_has_no_credential_fields() -> None:
    for f in dataclasses.fields(ReelSummaryVM):
        lowered = f.name.lower()
        for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
            assert fragment not in lowered, (
                f"ReelSummaryVM.{f.name} looks credential-bearing "
                f"(matched '{fragment}') — the VM is the security boundary."
            )


def test_reel_summary_vm_has_only_scalar_summary_fields() -> None:
    """QUA-93 scale invariant, VM layer: same guarantee
    `test_reel_summary_domain_object_has_only_scalar_roll_up_fields` (packages/api/
    tests/test_sentiment_service.py) pins for the domain `ReelSummary`, one layer up —
    the main view's Reflex state can never hold a full comment list disguised as a Reel
    summary. A whitelist: a newly added field forces a conscious look here."""
    fields = {f.name: f.type for f in dataclasses.fields(ReelSummaryVM)}
    assert fields == {
        "thread_id": "str",
        "external_thread_id": "str",
        "last_message_at": "str",
        "total": "int",
        "positive": "int",
        "neutral": "int",
        "negative": "int",
        "not_analyzed": "int",
        "thumbnail_url": "str",
        "caption": "str",
        "permalink": "str",
        "is_monitored": "bool",
    }


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


def _mock_asgi_client(
    status_code: int, json_body: dict, *, expected_path: str = "/api/inbox/sync"
) -> httpx.AsyncClient:
    """A fake in-process ASGI client for `sync_now`/`analyze_sentiment_now` — no FastAPI
    app involved, just the HTTP contract each function actually depends on (status code +
    JSON body). Lighter than building a real `create_app()`, and keeps this file's "never
    a database, never the API package's internals" posture (see the module docstring)
    even though `inbox_provider.py` itself now imports `qualify_api.http.app` lazily.
    `expected_path` defaults to sync's route; QUA-92's analyze tests pass
    `"/api/sentiment/analyze"`."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == expected_path
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
    # A response shape from BEFORE this bug-fix field existed (no key at all) must not
    # raise a KeyError — `.get(..., [])` backward-compat, see `sync_now`'s own comment.
    assert vm.skipped_missing_media == ()
    # Same backward-compat posture for QUA-101's later field, `.get(..., 0)`.
    assert vm.deleted_comments == 0


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


def test_sync_now_projects_skipped_missing_media_without_raising() -> None:
    """Bug fix (2026-09-01): a deleted Reel skipped server-side is still a 200 — `sync_
    now` must return a normal `SyncSummaryVM` (never raise), with the skipped id(s)
    reaching the VM. This is the exact shape `InboxState.sync_comments` depends on to
    NEVER set `sync_error` for this case — see that handler's own comment for why."""
    client = _mock_asgi_client(
        200,
        {
            "media_checked": 2,
            "new_comments": 0,
            "truncated": False,
            "skipped_missing_media": ["18034792133641940"],
        },
    )

    with _patched(_inbox_sync_asgi_client=lambda: client):
        vm = _run_coro(
            inbox_provider.sync_now(
                tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
            )
        )
    assert vm.skipped_missing_media == ("18034792133641940",)
    assert vm.media_checked == 2


def test_sync_now_projects_deleted_comments_without_raising() -> None:
    """QUA-101: a comment soft-deleted server-side is still a 200 — `sync_now` must
    return a normal `SyncSummaryVM` (never raise), with the count reaching the VM. Same
    shape as `test_sync_now_projects_skipped_missing_media_without_raising` above, one
    level down (a comment, not the whole Reel)."""
    client = _mock_asgi_client(
        200,
        {
            "media_checked": 1,
            "new_comments": 0,
            "truncated": False,
            "skipped_missing_media": [],
            "deleted_comments": 1,
        },
    )

    with _patched(_inbox_sync_asgi_client=lambda: client):
        vm = _run_coro(
            inbox_provider.sync_now(
                tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
            )
        )
    assert vm.deleted_comments == 1


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


# --------------------------------------------------------------------------------------
# analyze_sentiment_now (QUA-92) — the "Analizar sentimiento" button's transport.
# Reuses QUA-21's existing route rather than a second analysis engine: pinned below by
# asserting the real path AND that `analyze_pending_comments` never appears in this
# module's source (no in-process shortcut around the route).
# --------------------------------------------------------------------------------------


def test_analyze_sentiment_now_calls_the_real_route_not_a_second_engine() -> None:
    source = inspect.getsource(inbox_provider.analyze_sentiment_now)
    assert '"/api/sentiment/analyze"' in source
    assert "analyze_pending_comments(" not in source  # no in-process shortcut around it


def test_analyze_sentiment_now_rejects_a_tenant_the_dev_bridge_is_not_wired_for() -> None:
    other_tenant = UUID("00000000-0000-4000-8000-000000000099")
    assert other_tenant != inbox_provider._DEV_SYNC_TENANT_ID

    try:
        _run_coro(
            inbox_provider.analyze_sentiment_now(tenant_id=other_tenant, connection_id=_CONNECTION)
        )
    except UnknownSentimentConnection:
        pass
    else:
        raise AssertionError(
            "analyze_sentiment_now must refuse a tenant the dev bridge cannot authenticate as"
        )


def test_analyze_sentiment_now_projects_summary_fields() -> None:
    client = _mock_asgi_client(
        200,
        {"comments_checked": 3, "new_results": 2, "skipped_empty": 1},
        expected_path="/api/sentiment/analyze",
    )

    with _patched(_inbox_sync_asgi_client=lambda: client):
        vm = _run_coro(
            inbox_provider.analyze_sentiment_now(
                tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
            )
        )
    assert vm.comments_checked == 3
    assert vm.new_results == 2
    assert vm.skipped_empty == 1


def test_analyze_sentiment_now_projects_nothing_pending() -> None:
    """QUA-92's requirement: nothing pending is a normal, all-zero success — the caller
    (`InboxState.analyze_sentiment`) is what turns `comments_checked == 0` into "No hay
    comentarios pendientes de análisis" (as a toast message), not this function."""
    client = _mock_asgi_client(
        200,
        {"comments_checked": 0, "new_results": 0, "skipped_empty": 0},
        expected_path="/api/sentiment/analyze",
    )

    with _patched(_inbox_sync_asgi_client=lambda: client):
        vm = _run_coro(
            inbox_provider.analyze_sentiment_now(
                tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
            )
        )
    assert vm.comments_checked == 0
    assert vm.new_results == 0
    assert vm.skipped_empty == 0


def test_analyze_sentiment_now_propagates_unknown_connection_on_a_404() -> None:
    client = _mock_asgi_client(
        404, {"detail": "unknown connection"}, expected_path="/api/sentiment/analyze"
    )

    with _patched(_inbox_sync_asgi_client=lambda: client):
        try:
            _run_coro(
                inbox_provider.analyze_sentiment_now(
                    tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
                )
            )
        except UnknownSentimentConnection:
            pass
        else:
            raise AssertionError("analyze_sentiment_now must not swallow a 404 as success")


def test_analyze_sentiment_now_raises_for_a_failed_call() -> None:
    client = _mock_asgi_client(
        500, {"detail": "unexpected"}, expected_path="/api/sentiment/analyze"
    )

    with _patched(_inbox_sync_asgi_client=lambda: client):
        try:
            _run_coro(
                inbox_provider.analyze_sentiment_now(
                    tenant_id=inbox_provider._DEV_SYNC_TENANT_ID, connection_id=_CONNECTION
                )
            )
        except httpx.HTTPStatusError:
            pass
        else:
            raise AssertionError("analyze_sentiment_now must not swallow a failed call as success")


def _reel_summary(**overrides: object) -> ReelSummary:
    defaults: dict[str, object] = {
        "thread_id": UUID("e0000000-0000-4000-8000-000000000001"),
        "external_thread_id": "media-1",
        "last_message_at": datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
        "total": 3,
        "positive": 1,
        "neutral": 1,
        "negative": 0,
        "not_analyzed": 1,
        "is_monitored": True,
    }
    defaults.update(overrides)
    return ReelSummary(**defaults)


def _global_summary(**overrides: object) -> GlobalSentimentSummary:
    defaults: dict[str, object] = {
        "positive": 5,
        "neutral": 3,
        "negative": 2,
        "not_analyzed": 1,
        "total": 11,
    }
    defaults.update(overrides)
    return GlobalSentimentSummary(**defaults)


# --------------------------------------------------------------------------------------
# reel_summaries_page (QUA-93)
# --------------------------------------------------------------------------------------


def test_reel_summaries_page_calls_the_real_seam() -> None:
    source = inspect.getsource(inbox_provider.reel_summaries_page)
    assert "_list_reel_summaries(" in source


def test_reel_summaries_page_is_synchronous_not_async() -> None:
    assert not inspect.iscoroutinefunction(inbox_provider.reel_summaries_page)


def test_reel_summaries_page_enriches_from_already_loaded_candidates() -> None:
    """Opción A: thumbnail/caption/permalink come from `CandidateMediaVM`s the CALLER
    already loaded — zero extra query, zero extra Meta call inside this function."""
    candidate = CandidateMediaVM(
        external_media_id="media-1",
        posted_at="20 ago 2026, 09:00",
        is_monitored=True,
        caption="Mi Reel",
        permalink="https://instagram.com/reel/media-1",
        thumbnail_url="https://cdn/media-1.jpg",
    )
    with _patched(_list_reel_summaries=lambda **kwargs: (_reel_summary(),)):
        items, _cursor, _has_more = inbox_provider.reel_summaries_page(
            tenant_id=_TENANT, connection_id=_CONNECTION, cursor=None, candidates=[candidate]
        )
    assert items[0].thumbnail_url == "https://cdn/media-1.jpg"
    assert items[0].caption == "Mi Reel"
    assert items[0].permalink == "https://instagram.com/reel/media-1"


def test_reel_summaries_page_no_enrichment_for_a_reel_outside_the_candidate_list() -> None:
    """A Reel monitored longer than 2 weeks ago has no matching `CandidateMediaVM` —
    falls back to `""` for all three, never crashes on the missing lookup."""
    with _patched(_list_reel_summaries=lambda **kwargs: (_reel_summary(),)):
        items, _cursor, _has_more = inbox_provider.reel_summaries_page(
            tenant_id=_TENANT, connection_id=_CONNECTION, cursor=None, candidates=[]
        )
    assert items[0].thumbnail_url == ""
    assert items[0].caption == ""
    assert items[0].permalink == ""


def test_reel_summaries_page_carries_counts_through() -> None:
    with _patched(
        _list_reel_summaries=lambda **kwargs: (
            _reel_summary(total=10, positive=4, neutral=3, negative=2, not_analyzed=1),
        )
    ):
        items, _cursor, _has_more = inbox_provider.reel_summaries_page(
            tenant_id=_TENANT, connection_id=_CONNECTION, cursor=None, candidates=[]
        )
    assert items[0].total == 10
    assert items[0].positive == 4
    assert items[0].neutral == 3
    assert items[0].negative == 2
    assert items[0].not_analyzed == 1


def test_reel_summaries_page_carries_is_monitored_through() -> None:
    """QUA-94: `is_monitored` is a straight pass-through from `ReelSummary`, no lookup
    against `candidates` — must survive both `True` and `False` unchanged."""
    with _patched(_list_reel_summaries=lambda **kwargs: (_reel_summary(is_monitored=True),)):
        monitored_items, _cursor, _has_more = inbox_provider.reel_summaries_page(
            tenant_id=_TENANT, connection_id=_CONNECTION, cursor=None, candidates=[]
        )
    with _patched(_list_reel_summaries=lambda **kwargs: (_reel_summary(is_monitored=False),)):
        desmonitored_items, _cursor, _has_more = inbox_provider.reel_summaries_page(
            tenant_id=_TENANT, connection_id=_CONNECTION, cursor=None, candidates=[]
        )
    assert monitored_items[0].is_monitored is True
    assert desmonitored_items[0].is_monitored is False


def test_reel_summaries_page_has_more_when_page_is_full() -> None:
    full_page = tuple(
        _reel_summary(thread_id=UUID(int=i), external_thread_id=f"media-{i}")
        for i in range(DEFAULT_REEL_PAGE_SIZE)
    )
    with _patched(_list_reel_summaries=lambda **kwargs: full_page):
        _items, cursor, has_more = inbox_provider.reel_summaries_page(
            tenant_id=_TENANT, connection_id=_CONNECTION, cursor=None, candidates=[]
        )
    assert has_more is True
    assert cursor is not None
    assert cursor.thread_id == str(full_page[-1].thread_id)


def test_reel_summaries_page_has_no_more_when_page_is_short() -> None:
    with _patched(_list_reel_summaries=lambda **kwargs: (_reel_summary(),)):
        _items, _cursor, has_more = inbox_provider.reel_summaries_page(
            tenant_id=_TENANT, connection_id=_CONNECTION, cursor=None, candidates=[]
        )
    assert has_more is False


def test_reel_summaries_page_returns_no_cursor_on_an_empty_page() -> None:
    with _patched(_list_reel_summaries=lambda **kwargs: ()):
        items, cursor, has_more = inbox_provider.reel_summaries_page(
            tenant_id=_TENANT, connection_id=_CONNECTION, cursor=None, candidates=[]
        )
    assert items == []
    assert cursor is None
    assert has_more is False


def test_reel_summaries_page_propagates_unknown_connection() -> None:
    def _raise(**kwargs: object) -> tuple[ReelSummary, ...]:
        raise UnknownSentimentConnection(str(_CONNECTION))

    with _patched(_list_reel_summaries=_raise):
        try:
            inbox_provider.reel_summaries_page(
                tenant_id=_TENANT, connection_id=_CONNECTION, cursor=None, candidates=[]
            )
        except UnknownSentimentConnection:
            pass
        else:
            raise AssertionError("reel_summaries_page must not swallow UnknownSentimentConnection")


# --------------------------------------------------------------------------------------
# global_summary_vm (QUA-93)
# --------------------------------------------------------------------------------------


def test_global_summary_vm_calls_the_real_seam() -> None:
    source = inspect.getsource(inbox_provider.global_summary_vm)
    assert "_global_sentiment_summary(" in source


def test_global_summary_vm_projects_fields() -> None:
    with _patched(_global_sentiment_summary=lambda **kwargs: _global_summary(positive=7)):
        vm = inbox_provider.global_summary_vm(tenant_id=_TENANT, connection_id=_CONNECTION)
    assert vm.positive == 7
    assert vm.total == 11


def test_global_summary_vm_propagates_unknown_connection() -> None:
    def _raise(**kwargs: object) -> GlobalSentimentSummary:
        raise UnknownSentimentConnection(str(_CONNECTION))

    with _patched(_global_sentiment_summary=_raise):
        try:
            inbox_provider.global_summary_vm(tenant_id=_TENANT, connection_id=_CONNECTION)
        except UnknownSentimentConnection:
            pass
        else:
            raise AssertionError("global_summary_vm must not swallow UnknownSentimentConnection")


# --------------------------------------------------------------------------------------
# thread_comments_page (QUA-93)
# --------------------------------------------------------------------------------------


def test_thread_comments_page_calls_the_real_seam() -> None:
    source = inspect.getsource(inbox_provider.thread_comments_page)
    assert "_list_comments_for_thread(" in source


def test_thread_comments_page_is_synchronous_not_async() -> None:
    assert not inspect.iscoroutinefunction(inbox_provider.thread_comments_page)


def test_thread_comments_page_maps_all_filter_and_blank_search_to_none() -> None:
    captured: dict[str, object] = {}

    def _capture(**kwargs: object) -> tuple[AnalyzedComment, ...]:
        captured.update(kwargs)
        return ()

    with _patched(_list_comments_for_thread=_capture):
        inbox_provider.thread_comments_page(
            tenant_id=_TENANT,
            connection_id=_CONNECTION,
            thread_id=UUID(int=1),
            sentiment_filter="ALL",
            search="   ",
            cursor=None,
        )
    assert captured["sentiment_filter"] is None
    assert captured["search"] is None


def test_thread_comments_page_passes_through_a_real_filter_and_search() -> None:
    captured: dict[str, object] = {}

    def _capture(**kwargs: object) -> tuple[AnalyzedComment, ...]:
        captured.update(kwargs)
        return ()

    with _patched(_list_comments_for_thread=_capture):
        inbox_provider.thread_comments_page(
            tenant_id=_TENANT,
            connection_id=_CONNECTION,
            thread_id=UUID(int=1),
            sentiment_filter="PENDING",
            search="  precio  ",
            cursor=None,
        )
    assert captured["sentiment_filter"] == "PENDING"
    assert captured["search"] == "precio"  # stripped


def test_thread_comments_page_shows_pending_as_empty_label_never_neu() -> None:
    with _patched(_list_comments_for_thread=lambda **kwargs: (_comment(),)):
        (vm,) = inbox_provider.thread_comments_page(
            tenant_id=_TENANT,
            connection_id=_CONNECTION,
            thread_id=UUID(int=1),
            sentiment_filter="ALL",
            search="",
            cursor=None,
        )[0]
    assert vm.sentiment_label == ""
    assert vm.sentiment_label != "NEU"


def test_thread_comments_page_propagates_unknown_connection() -> None:
    def _raise(**kwargs: object) -> tuple[AnalyzedComment, ...]:
        raise UnknownSentimentConnection(str(_CONNECTION))

    with _patched(_list_comments_for_thread=_raise):
        try:
            inbox_provider.thread_comments_page(
                tenant_id=_TENANT,
                connection_id=_CONNECTION,
                thread_id=UUID(int=1),
                sentiment_filter="ALL",
                search="",
                cursor=None,
            )
        except UnknownSentimentConnection:
            pass
        else:
            raise AssertionError("thread_comments_page must not swallow UnknownSentimentConnection")


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
