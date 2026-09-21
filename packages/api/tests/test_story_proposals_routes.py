"""QUA-106's five story-proposal routes, exercised end-to-end with zero network and
zero DB — same shape `test_replies_routes.py` establishes. Only `PublishService` and
the trend-audio client are fakes; the repository and service are real code."""

from __future__ import annotations

import io
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import deps, story_proposals_routes
from qualify_api.http.app import create_app
from qualify_api.publishing.service import ConnectionTarget, PublishState
from qualify_api.stories.repository import MemoryStoryProposalRepository
from qualify_api.stories.service import StoryProposalService

TENANT = UUID("11111111-1111-4111-8111-111111111111")
USER = UUID("33333333-3333-4333-8333-333333333333")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")


class FakeConnections:
    def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
        return ConnectionTarget(ig_user_id="17841448653847824", status="active")


class FakePublishService:
    def __init__(self) -> None:
        self.attempt_id = uuid4()

    async def start(self, **kwargs: object) -> PublishState:
        return PublishState(
            attempt_id=self.attempt_id,
            status="processing",
            settled=False,
            published_media_id=None,
            reason=None,
        )

    async def advance(self, *, tenant_id: UUID, attempt_id: UUID) -> PublishState:
        return PublishState(
            attempt_id=attempt_id,
            status="published",
            settled=True,
            published_media_id="media-1",
            reason=None,
        )


class Harness:
    def __init__(self) -> None:
        self.repo = MemoryStoryProposalRepository()
        self.service = StoryProposalService(
            repository=self.repo,
            publish_service=FakePublishService(),  # type: ignore[arg-type]
            connections=FakeConnections(),
            trend_client_factory=None,
        )
        app = create_app(configure_production=False)

        async def _propose_story(
            *,
            tenant_id: UUID,
            connection_id: UUID,
            fileobj,
            content_type: str,
            caption: str | None,
            trend_audio_id: str | None = None,
            trend_audio_title: str | None = None,
        ):
            return self.service.propose(
                tenant_id=tenant_id,
                connection_id=connection_id,
                media_object_key=f"t/{tenant_id}/stories/{uuid4().hex}.mp4",
                media_content_type=content_type,
                caption=caption,
                trend_audio_id=trend_audio_id,
                trend_audio_title=trend_audio_title,
            )

        app.dependency_overrides[story_proposals_routes.get_propose_story] = lambda: _propose_story
        app.dependency_overrides[story_proposals_routes.get_list_proposals] = lambda: (
            self.service.list_proposals
        )
        app.dependency_overrides[story_proposals_routes.get_decide_proposal] = lambda: (
            self.service.decide
        )
        app.dependency_overrides[story_proposals_routes.get_publish_proposal] = lambda: (
            self.service.publish
        )
        app.dependency_overrides[story_proposals_routes.get_refresh_proposal] = lambda: (
            self.service.refresh
        )
        app.dependency_overrides[story_proposals_routes.get_suggest_trend_audio] = lambda: (
            self.service.suggest_trend_audio
        )
        app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
        self.http = TestClient(app)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", f"tok:{TENANT}:{USER}")
    return Harness()


AUTH = {"Authorization": "Bearer tok"}


def _propose(harness: Harness) -> str:
    response = harness.http.post(
        "/api/story-proposals",
        data={"connection_id": str(CONNECTION), "caption": "Mi caption"},
        files={"file": ("clip.mp4", io.BytesIO(b"bytes"), "video/mp4")},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_propose_then_list(harness: Harness) -> None:
    proposal_id = _propose(harness)

    listed = harness.http.get("/api/story-proposals", headers=AUTH)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert len(body) == 1
    assert body[0]["id"] == proposal_id
    assert body[0]["status"] == "proposed"
    assert body[0]["caption"] == "Mi caption"


def test_publish_a_proposed_proposal_is_rejected(harness: Harness) -> None:
    """The route-level guarantee behind QUA-106's mandatory-approval requirement:
    publishing something nobody decided on is a 409, not a 200."""
    proposal_id = _propose(harness)

    response = harness.http.post(f"/api/story-proposals/{proposal_id}/publish", headers=AUTH)

    assert response.status_code == 409


def test_decide_edited_requires_final_caption(harness: Harness) -> None:
    proposal_id = _propose(harness)

    response = harness.http.post(
        f"/api/story-proposals/{proposal_id}/decide",
        json={"decision": "edited"},
        headers=AUTH,
    )

    assert response.status_code == 422


def test_decide_then_publish_then_refresh_full_flow(harness: Harness) -> None:
    proposal_id = _propose(harness)

    decided = harness.http.post(
        f"/api/story-proposals/{proposal_id}/decide",
        json={"decision": "approved"},
        headers=AUTH,
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["proposal"]["status"] == "approved"

    published = harness.http.post(f"/api/story-proposals/{proposal_id}/publish", headers=AUTH)
    assert published.status_code == 200, published.text
    assert published.json()["proposal"]["status"] == "publishing"

    refreshed = harness.http.get(f"/api/story-proposals/{proposal_id}", headers=AUTH)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["status"] == "published"


def test_decide_rejected_never_reaches_publish(harness: Harness) -> None:
    proposal_id = _propose(harness)
    harness.http.post(
        f"/api/story-proposals/{proposal_id}/decide",
        json={"decision": "rejected"},
        headers=AUTH,
    )

    response = harness.http.post(f"/api/story-proposals/{proposal_id}/publish", headers=AUTH)

    assert response.status_code == 409


def test_publish_unknown_proposal_is_404(harness: Harness) -> None:
    response = harness.http.post(f"/api/story-proposals/{uuid4()}/publish", headers=AUTH)
    assert response.status_code == 404


def test_trend_audio_never_errors_even_with_no_client_configured(harness: Harness) -> None:
    response = harness.http.get(
        "/api/story-proposals/trend-audio",
        params={"connection_id": str(CONNECTION)},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text
    assert response.json() == []
