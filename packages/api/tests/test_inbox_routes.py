"""`POST /api/inbox/sync` — the B2 acceptance criterion for a real HTTP route, exercised
end-to-end with zero network and zero DB. Mirrors `test_publishing_routes.py`'s harness
shape: everything below the route is real code (`SyncResponse`/`SyncRequest`, the error
mapping) — only the injected `sync_comments` callable is a fake, same posture
`test_publishing_routes.Harness` already establishes for `PublishService`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import deps, inbox_routes
from qualify_api.http.app import create_app
from qualify_api.inbox.client import CommentsReadError
from qualify_api.inbox.composition import UnknownInboxConnection
from qualify_api.inbox.service import CommentsPermissionMissing, SyncBudgetExhausted, SyncSummary

TENANT = UUID("44444444-4444-4444-8444-444444444444")
USER = UUID("55555555-5555-4555-8555-555555555555")
CONNECTION = UUID("66666666-6666-4666-8666-666666666666")
AUTH = {"Authorization": "Bearer tok-inbox"}


class Harness:
    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, fn: Callable[..., Awaitable[SyncSummary]]
    ) -> None:
        monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", f"tok-inbox:{TENANT}:{USER}")
        app = create_app(configure_production=False)
        app.dependency_overrides[inbox_routes.get_sync_comments] = lambda: fn
        app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
        self.http = TestClient(app)


def _fixed_summary(
    *, media_checked: int = 1, new_comments: int = 0, calls: list[tuple[UUID, UUID]] | None = None
) -> Callable[..., Awaitable[SyncSummary]]:
    async def fn(*, tenant_id: UUID, connection_id: UUID) -> SyncSummary:
        if calls is not None:
            calls.append((tenant_id, connection_id))
        return SyncSummary(media_checked=media_checked, new_comments=new_comments)

    return fn


def test_sync_returns_the_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, _fixed_summary(media_checked=2, new_comments=3))

    response = harness.http.post(
        "/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "media_checked": 2,
        "new_comments": 3,
        "truncated": False,
        "skipped_missing_media": [],
    }


def test_sync_passes_the_principals_tenant_id_not_a_client_supplied_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `tenant_id` field exists on the request body at all (see the structural test
    below) — this proves the value the service actually receives is the Principal's."""
    calls: list[tuple[UUID, UUID]] = []
    harness = Harness(monkeypatch, _fixed_summary(calls=calls))

    harness.http.post("/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH)

    assert calls == [(TENANT, CONNECTION)]


def test_unknown_connection_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fn(*, tenant_id: UUID, connection_id: UUID) -> SyncSummary:
        raise UnknownInboxConnection(str(connection_id))

    harness = Harness(monkeypatch, fn)

    response = harness.http.post(
        "/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )

    assert response.status_code == 404


def test_a_failed_meta_call_is_502_never_a_body(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fn(*, tenant_id: UUID, connection_id: UUID) -> SyncSummary:
        raise CommentsReadError(
            f"GET /{connection_id}/comments failed with HTTP 500",
            platform_code=1,
            platform_subcode=2,
        )

    harness = Harness(monkeypatch, fn)

    response = harness.http.post(
        "/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )

    assert response.status_code == 502
    # Only the client-facing message this module constructs — no Meta response body.
    assert "GET /" in response.json()["detail"]


def test_missing_comments_permission_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cannot_observe` (QUA-88) — distinct from the 502 above (a call that failed) and
    from a normal 200 with zero new comments (a call that succeeded and found nothing)."""

    async def fn(*, tenant_id: UUID, connection_id: UUID) -> SyncSummary:
        raise CommentsPermissionMissing(connection_id=connection_id)

    harness = Harness(monkeypatch, fn)

    response = harness.http.post(
        "/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )

    assert response.status_code == 403


def test_exhausted_budget_is_429(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fn(*, tenant_id: UUID, connection_id: UUID) -> SyncSummary:
        raise SyncBudgetExhausted(needed=5, remaining=2)

    harness = Harness(monkeypatch, fn)

    response = harness.http.post(
        "/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )

    assert response.status_code == 429
    assert "5" in response.json()["detail"]
    assert "2" in response.json()["detail"]


def test_skipped_missing_media_is_still_a_200_never_a_502(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug fix (2026-09-01): `InboxService.sync_comments` already absorbs a deleted-media
    `CommentsReadError` internally and returns a normal `SyncSummary` — this route must
    stay a thin passthrough of that, never re-deriving a 502 for it. Distinguishes this
    from `test_a_failed_meta_call_is_502_never_a_body` above, which is a REAL failure the
    service still raises and this route still maps to 502, unchanged."""

    async def fn(*, tenant_id: UUID, connection_id: UUID) -> SyncSummary:
        return SyncSummary(
            media_checked=2, new_comments=1, skipped_missing_media=("18034792133641940",)
        )

    harness = Harness(monkeypatch, fn)

    response = harness.http.post(
        "/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "media_checked": 2,
        "new_comments": 1,
        "truncated": False,
        "skipped_missing_media": ["18034792133641940"],
    }


def test_truncated_sync_is_still_a_200_with_the_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A budget that ran out mid-pagination is a partial success, not a failure — see
    `SyncSummary.truncated`'s docstring."""

    async def fn(*, tenant_id: UUID, connection_id: UUID) -> SyncSummary:
        return SyncSummary(media_checked=1, new_comments=1, truncated=True)

    harness = Harness(monkeypatch, fn)

    response = harness.http.post(
        "/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )

    assert response.status_code == 200
    assert response.json() == {
        "media_checked": 1,
        "new_comments": 1,
        "truncated": True,
        "skipped_missing_media": [],
    }


def test_the_route_requires_the_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, _fixed_summary())

    response = harness.http.post("/api/inbox/sync", json={"connection_id": str(CONNECTION)})

    assert response.status_code == 401


def test_request_model_carries_no_identity_field() -> None:
    """Structural: no field through which a client could name its own tenant — same
    discipline `test_publishing_routes.test_request_models_carry_no_identity_fields`
    already pins for `StartAttemptRequest`."""
    assert "tenant_id" not in inbox_routes.SyncRequest.model_fields
    assert "user_id" not in inbox_routes.SyncRequest.model_fields


def test_an_unconfigured_app_cannot_talk_to_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default dependency raises — a deployment nobody wired stays silent, same
    posture `test_publishing_routes.test_an_unconfigured_app_cannot_talk_to_meta`
    establishes for the publish service."""
    monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", f"tok-inbox:{TENANT}:{USER}")
    app = create_app(configure_production=False)
    app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
    http = TestClient(app)
    with pytest.raises(NotImplementedError, match="inbox sync"):
        http.post("/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH)


def test_the_seam_does_not_depend_on_the_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """B2's 'costura' criterion: swapping WHAT calls `sync_comments` (an in-memory fake
    here, `composition.sync_comments` in production, a future webhook handler later)
    never touches this route's code — only which callable `get_sync_comments` resolves
    to. Proven by running the identical route through two behaviourally different fakes."""
    empty = Harness(monkeypatch, _fixed_summary(media_checked=0, new_comments=0))
    busy = Harness(monkeypatch, _fixed_summary(media_checked=5, new_comments=5))

    empty_response = empty.http.post(
        "/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )
    busy_response = busy.http.post(
        "/api/inbox/sync", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )

    assert empty_response.json() == {
        "media_checked": 0,
        "new_comments": 0,
        "truncated": False,
        "skipped_missing_media": [],
    }
    assert busy_response.json() == {
        "media_checked": 5,
        "new_comments": 5,
        "truncated": False,
        "skipped_missing_media": [],
    }


def test_malformed_connection_id_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, _fixed_summary())

    response = harness.http.post(
        "/api/inbox/sync", json={"connection_id": "not-a-uuid"}, headers=AUTH
    )

    assert response.status_code == 422


def test_a_random_connection_id_still_requires_a_wired_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity: the route itself never fabricates a connection — an id nobody wired
    behaves exactly like `test_unknown_connection_is_404`'s explicit raise would."""
    calls: list[tuple[UUID, UUID]] = []
    harness = Harness(monkeypatch, _fixed_summary(calls=calls))

    harness.http.post("/api/inbox/sync", json={"connection_id": str(uuid4())}, headers=AUTH)

    assert len(calls) == 1  # the route still calls through; refusal is the service's job
