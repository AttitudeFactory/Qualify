"""QUA-22's four replies routes, exercised end-to-end with zero network and zero DB —
same shape `test_publishing_routes.py` establishes. Only the Meta client and the
generator are fakes; the gate, repository, and service are real code."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import deps, replies_routes
from qualify_api.http.app import create_app
from qualify_api.replies.repository import CandidateComment, MemoryReplyRepository
from qualify_api.replies.service import ReplyService
from qualify_api.sentiment.repository import AnalysisVersion

TENANT = UUID("11111111-1111-4111-8111-111111111111")
USER = UUID("33333333-3333-4333-8333-333333333333")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
VERSION = AnalysisVersion(
    detector_version="det-1", pipeline_version="pipe-1", model_id="model-1", model_revision=None
)


class FakeProvider:
    model_id = "fake-model"

    def draft_reply(self, *, comment_text: str, business_name: str | None = None) -> str:
        return f"¡Gracias! {comment_text[:10]}"


class FakeReplyClient:
    async def post_reply(self, *, ig_comment_id: str, message: str) -> str:
        return "reply-1"


class FakeClientFactory:
    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> FakeReplyClient:
        return FakeReplyClient()


class Harness:
    def __init__(self) -> None:
        self.repo = MemoryReplyRepository()
        self.service = ReplyService(
            repository=self.repo,
            version=VERSION,
            generator_version="qua22.1:test-model",
            provider=FakeProvider(),
            client_factory=FakeClientFactory(),
        )
        app = create_app(configure_production=False)
        app.dependency_overrides[replies_routes.get_generate_drafts] = lambda: (
            self.service.generate_drafts
        )
        app.dependency_overrides[replies_routes.get_list_pending_drafts] = lambda: (
            self.service.list_pending_drafts
        )
        app.dependency_overrides[replies_routes.get_decide_draft] = lambda: self.service.decide
        app.dependency_overrides[replies_routes.get_send_draft] = lambda: self.service.send
        app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
        self.http = TestClient(app)

    def seed(self, text: str = "qué lindo!") -> UUID:
        candidate = CandidateComment(
            message_id=uuid4(),
            source_id="ext-comment-1",
            text=text,
            sentiment_result_id=uuid4(),
            sentiment_label="POS",
        )
        self.repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
        return candidate.message_id


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", f"tok:{TENANT}:{USER}")
    return Harness()


AUTH = {"Authorization": "Bearer tok"}


def test_generate_then_list_pending(harness: Harness) -> None:
    harness.seed()

    generated = harness.http.post(
        "/api/replies/generate", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )
    assert generated.status_code == 200, generated.text
    assert generated.json() == {"candidates_seen": 1, "drafts_created": 1, "gate_rejected": 0}

    pending = harness.http.get(
        "/api/replies/pending", params={"connection_id": str(CONNECTION)}, headers=AUTH
    )
    assert pending.status_code == 200, pending.text
    body = pending.json()
    assert len(body) == 1
    assert body[0]["status"] == "proposed"
    assert body[0]["sentiment_label"] == "POS"


def test_decide_edited_requires_final_text(harness: Harness) -> None:
    harness.seed()
    harness.http.post(
        "/api/replies/generate", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )
    draft_id = harness.http.get(
        "/api/replies/pending", params={"connection_id": str(CONNECTION)}, headers=AUTH
    ).json()[0]["id"]

    response = harness.http.post(
        f"/api/replies/{draft_id}/decide", json={"decision": "edited"}, headers=AUTH
    )

    assert response.status_code == 422


def test_decide_then_send_full_flow(harness: Harness) -> None:
    harness.seed()
    harness.http.post(
        "/api/replies/generate", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )
    draft_id = harness.http.get(
        "/api/replies/pending", params={"connection_id": str(CONNECTION)}, headers=AUTH
    ).json()[0]["id"]

    decided = harness.http.post(
        f"/api/replies/{draft_id}/decide", json={"decision": "accepted"}, headers=AUTH
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["draft"]["status"] == "accepted"
    assert decided.json()["diff"] == []

    sent = harness.http.post(f"/api/replies/{draft_id}/send", headers=AUTH)
    assert sent.status_code == 200, sent.text
    assert sent.json()["draft"]["status"] == "sent"

    # The pending queue no longer lists it — it left 'proposed' the moment it was decided.
    pending = harness.http.get(
        "/api/replies/pending", params={"connection_id": str(CONNECTION)}, headers=AUTH
    ).json()
    assert pending == []


def test_send_a_proposed_draft_is_rejected(harness: Harness) -> None:
    """The route-level guarantee behind QUA-22's 'ninguna respuesta se envía sin
    acción humana explícita': sending a draft nobody decided on is a 409, not a 200."""
    harness.seed()
    harness.http.post(
        "/api/replies/generate", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )
    draft_id = harness.http.get(
        "/api/replies/pending", params={"connection_id": str(CONNECTION)}, headers=AUTH
    ).json()[0]["id"]

    response = harness.http.post(f"/api/replies/{draft_id}/send", headers=AUTH)

    assert response.status_code == 409


def test_send_unknown_draft_is_404(harness: Harness) -> None:
    response = harness.http.post(f"/api/replies/{uuid4()}/send", headers=AUTH)
    assert response.status_code == 404


def test_send_route_hands_the_service_an_approval_from_the_principal(harness: Harness) -> None:
    """m-24789645 criterion 1 at the HTTP edge: the authenticated request IS the approval
    — the route builds a `HumanApproval` for THIS draft and THIS principal, and the
    service refuses without one."""
    from qualify_api.assisted.approval import HumanApproval

    harness.seed()
    harness.http.post(
        "/api/replies/generate", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )
    draft_id = harness.http.get(
        "/api/replies/pending", params={"connection_id": str(CONNECTION)}, headers=AUTH
    ).json()[0]["id"]
    harness.http.post(
        f"/api/replies/{draft_id}/decide", json={"decision": "accepted"}, headers=AUTH
    )
    seen: list[HumanApproval] = []

    async def spy(*, tenant_id: UUID, draft_id: UUID, approval: HumanApproval):  # noqa: ANN202
        seen.append(approval)
        return await harness.service.send(tenant_id=tenant_id, draft_id=draft_id, approval=approval)

    harness.http.app.dependency_overrides[replies_routes.get_send_draft] = lambda: spy

    sent = harness.http.post(f"/api/replies/{draft_id}/send", headers=AUTH)

    assert sent.status_code == 200, sent.text
    assert len(seen) == 1
    assert seen[0].user_id == USER
    assert seen[0].draft_id == UUID(draft_id)


def test_send_route_maps_a_refused_approval_to_403(harness: Harness) -> None:
    from qualify_api.assisted.approval import ApprovalRequired

    async def refuse(**_: object) -> None:
        raise ApprovalRequired("no approval")

    harness.http.app.dependency_overrides[replies_routes.get_send_draft] = lambda: refuse

    response = harness.http.post(f"/api/replies/{uuid4()}/send", headers=AUTH)

    assert response.status_code == 403
