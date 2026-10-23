"""QUA-22's comments-tranche service, fully offline against the Memory repository and
fakes. The tests that matter most: (1) nothing reaches `send()` without a prior human
decision — there is no code path from `'proposed'` straight to a Meta call; (2) a
transport-ambiguous failure never settles the draft, mirroring `PublishService`'s own
"settle nothing on ambiguity" rule; (3) the gate runs on every candidate BEFORE the
generator, so a rejected candidate never reaches the (fake) provider."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qualify_api.assisted.approval import ApprovalRequired, HumanApproval
from qualify_api.replies.client import CommentReplyError
from qualify_api.replies.repository import CandidateComment, MemoryReplyRepository
from qualify_api.replies.service import ReplyService, UnknownDraft
from qualify_api.sentiment.repository import AnalysisVersion

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")
VERSION = AnalysisVersion(
    detector_version="det-1", pipeline_version="pipe-1", model_id="model-1", model_revision=None
)
GENERATOR_VERSION = "qua22.1:test-model"


def _approval(draft_id: UUID, *, user_id: UUID = USER) -> HumanApproval:
    return HumanApproval(user_id=user_id, approved_at=datetime.now(UTC), draft_id=draft_id)


class FakeProvider:
    def __init__(self) -> None:
        self.model_id = "fake-model"
        self.calls: list[str] = []

    def draft_reply(self, *, comment_text: str, business_name: str | None = None) -> str:
        self.calls.append(comment_text)
        return f"¡Gracias! {comment_text[:10]}"


class FakeReplyClient:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.reply_id = "reply-1"
        self.calls: list[tuple[str, str]] = []

    async def post_reply(self, *, ig_comment_id: str, message: str) -> str:
        self.calls.append((ig_comment_id, message))
        if self.error is not None:
            raise self.error
        return self.reply_id


class FakeClientFactory:
    def __init__(self, client: FakeReplyClient) -> None:
        self._client = client

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> FakeReplyClient:
        return self._client


def _service(
    *, repo: MemoryReplyRepository, provider: FakeProvider, client: FakeReplyClient, degrader=None
) -> ReplyService:
    return ReplyService(
        repository=repo,
        version=VERSION,
        generator_version=GENERATOR_VERSION,
        provider=provider,
        client_factory=FakeClientFactory(client),
        connection_degrader=degrader,
    )


def _candidate(message_id: UUID | None = None, *, sentiment: str = "POS", text: str = "qué lindo!"):
    return CandidateComment(
        message_id=message_id or uuid4(),
        source_id="ext-comment-1",
        text=text,
        sentiment_result_id=uuid4(),
        sentiment_label=sentiment,
    )


def test_generate_drafts_only_creates_for_gate_passing_candidates() -> None:
    repo = MemoryReplyRepository()
    passing = _candidate(sentiment="POS", text="me encanta!")
    failing = _candidate(sentiment="NEG", text="no me gustó")
    repo.seed_candidates(connection_id=CONNECTION, candidates=(passing, failing))
    provider = FakeProvider()
    service = _service(repo=repo, provider=provider, client=FakeReplyClient())

    summary = service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)

    assert summary.candidates_seen == 2
    assert summary.drafts_created == 1
    assert summary.gate_rejected == 1
    # The generator was called ONLY for the passing candidate — the gate ran first.
    assert provider.calls == ["me encanta!"]
    pending = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert len(pending) == 1
    assert pending[0].message_id == passing.message_id
    assert pending[0].status == "proposed"
    assert pending[0].generator_version == GENERATOR_VERSION


def test_pending_draft_carries_the_comment_author_and_publication() -> None:
    """m-24842989: the review card shows who commented and on which publication — the
    candidate's author and media id reach the pending draft; a candidate without them
    (older seeding) yields `""`, never `None`."""
    repo = MemoryReplyRepository()
    with_context = replace(
        _candidate(text="me encanta!"),
        author_username="cliente.feliz",
        external_media_id="media-123",
    )
    bare = _candidate(text="qué rico todo")
    repo.seed_candidates(connection_id=CONNECTION, candidates=(with_context, bare))
    service = _service(repo=repo, provider=FakeProvider(), client=FakeReplyClient())

    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)

    by_message = {
        d.message_id: d
        for d in repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    }
    assert by_message[with_context.message_id].author_username == "cliente.feliz"
    assert by_message[with_context.message_id].external_media_id == "media-123"
    assert by_message[bare.message_id].author_username == ""
    assert by_message[bare.message_id].external_media_id == ""
    assert by_message[bare.message_id].media_caption == ""


def test_generate_drafts_is_idempotent_on_rerun() -> None:
    repo = MemoryReplyRepository()
    candidate = _candidate()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service = _service(repo=repo, provider=FakeProvider(), client=FakeReplyClient())

    first = service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    second = service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)

    assert first.drafts_created == 1
    # Second pass sees no candidates at all: MemoryReplyRepository's
    # list_positive_comments_without_draft already excludes messages with a draft.
    assert second.candidates_seen == 0
    assert second.drafts_created == 0


def test_send_refuses_a_proposed_draft_never_calls_meta() -> None:
    """QUA-22's own criterion, verbatim: 'ninguna respuesta se envía sin acción humana
    explícita' — there must be NO code path from 'proposed' straight into a send."""
    repo = MemoryReplyRepository()
    candidate = _candidate()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    client = FakeReplyClient()
    service = _service(repo=repo, provider=FakeProvider(), client=client)
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    draft = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)[0]

    with pytest.raises(ValueError, match="proposed"):
        import asyncio

        asyncio.run(service.send(tenant_id=TENANT, draft_id=draft.id, approval=_approval(draft.id)))

    assert client.calls == []


def test_send_unknown_draft_raises() -> None:
    import asyncio

    service = _service(
        repo=MemoryReplyRepository(), provider=FakeProvider(), client=FakeReplyClient()
    )
    unknown = uuid4()
    with pytest.raises(UnknownDraft):
        asyncio.run(service.send(tenant_id=TENANT, draft_id=unknown, approval=_approval(unknown)))


def _accepted_draft(repo: MemoryReplyRepository, service: ReplyService):
    candidate = _candidate()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    draft = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)[0]
    result = service.decide(
        tenant_id=TENANT,
        draft_id=draft.id,
        decision="accepted",
        final_text=None,
        decided_by_user_id=USER,
    )
    return result.draft


def test_decide_accepted_sets_final_text_equal_to_generated_and_empty_diff() -> None:
    repo = MemoryReplyRepository()
    service = _service(repo=repo, provider=FakeProvider(), client=FakeReplyClient())
    candidate = _candidate()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    draft = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)[0]

    result = service.decide(
        tenant_id=TENANT,
        draft_id=draft.id,
        decision="accepted",
        final_text=None,
        decided_by_user_id=USER,
    )

    assert result.draft.status == "accepted"
    assert result.draft.final_text == result.draft.generated_text
    assert result.diff == ()
    assert result.draft.decided_by_user_id == USER


def test_decide_edited_records_a_nonempty_diff() -> None:
    repo = MemoryReplyRepository()
    service = _service(repo=repo, provider=FakeProvider(), client=FakeReplyClient())
    candidate = _candidate()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    draft = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)[0]

    result = service.decide(
        tenant_id=TENANT,
        draft_id=draft.id,
        decision="edited",
        final_text="Un texto completamente distinto",
        decided_by_user_id=USER,
    )

    assert result.draft.status == "edited"
    assert result.draft.final_text == "Un texto completamente distinto"
    assert len(result.diff) > 0


def test_decide_discarded_sets_no_final_text_and_settles() -> None:
    repo = MemoryReplyRepository()
    service = _service(repo=repo, provider=FakeProvider(), client=FakeReplyClient())
    candidate = _candidate()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    draft = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)[0]

    result = service.decide(
        tenant_id=TENANT,
        draft_id=draft.id,
        decision="discarded",
        final_text=None,
        decided_by_user_id=USER,
    )

    assert result.draft.status == "discarded"
    assert result.draft.final_text is None
    assert result.draft.is_settled is True


def test_decide_twice_raises() -> None:
    repo = MemoryReplyRepository()
    service = _service(repo=repo, provider=FakeProvider(), client=FakeReplyClient())
    draft = _accepted_draft(repo, service)

    with pytest.raises(ValueError, match="not 'proposed'"):
        service.decide(
            tenant_id=TENANT,
            draft_id=draft.id,
            decision="discarded",
            final_text=None,
            decided_by_user_id=USER,
        )


def test_send_happy_path_marks_sent_and_settles() -> None:
    import asyncio

    repo = MemoryReplyRepository()
    client = FakeReplyClient()
    service = _service(repo=repo, provider=FakeProvider(), client=client)
    draft = _accepted_draft(repo, service)

    sent = asyncio.run(
        service.send(tenant_id=TENANT, draft_id=draft.id, approval=_approval(draft.id))
    )

    assert sent.status == "sent"
    assert sent.external_reply_id == "reply-1"
    assert sent.is_settled is True
    assert client.calls == [(draft.source_id, draft.final_text)]


def test_send_transport_ambiguity_never_settles() -> None:
    """The measured ambiguity `PublishService.advance()` already documents for its own
    send: a timeout does NOT prove the reply did not post. Settling here would be a
    lie in one direction or the other."""
    import asyncio

    repo = MemoryReplyRepository()
    client = FakeReplyClient()
    client.error = CommentReplyError("timeout", is_ambiguous=True)
    service = _service(repo=repo, provider=FakeProvider(), client=client)
    draft = _accepted_draft(repo, service)

    result = asyncio.run(
        service.send(tenant_id=TENANT, draft_id=draft.id, approval=_approval(draft.id))
    )

    assert result.status == "send_ambiguous"
    assert result.is_settled is False


def test_send_definite_platform_error_settles_as_failed() -> None:
    import asyncio

    repo = MemoryReplyRepository()
    client = FakeReplyClient()
    client.error = CommentReplyError("comment hidden", platform_code=100, http_status=400)
    service = _service(repo=repo, provider=FakeProvider(), client=client)
    draft = _accepted_draft(repo, service)

    result = asyncio.run(
        service.send(tenant_id=TENANT, draft_id=draft.id, approval=_approval(draft.id))
    )

    assert result.status == "send_failed"
    assert result.is_settled is True
    assert result.send_error_code == "platform:100"


def test_send_auth_error_degrades_connection_and_settles_as_failed() -> None:
    import asyncio

    repo = MemoryReplyRepository()
    client = FakeReplyClient()
    client.error = CommentReplyError("bad token", platform_code=190, http_status=401)
    degraded: list[tuple[UUID, UUID]] = []

    def degrader(*, tenant_id: UUID, connection_id: UUID) -> None:
        degraded.append((tenant_id, connection_id))

    service = _service(repo=repo, provider=FakeProvider(), client=client, degrader=degrader)
    draft = _accepted_draft(repo, service)

    result = asyncio.run(
        service.send(tenant_id=TENANT, draft_id=draft.id, approval=_approval(draft.id))
    )

    assert result.status == "send_failed"
    assert degraded == [(TENANT, draft.connection_id)]


# --- m-24789645 criterion 1: no public reply without a HumanApproval -----------------


@pytest.mark.parametrize(
    "approval",
    [
        None,
        "approved",
        {"user_id": USER, "draft_id": "x"},
        # A look-alike with the right attributes is still not a `HumanApproval`.
        type("FakeApproval", (), {"user_id": USER, "approved_at": None, "draft_id": None})(),
    ],
    ids=["none", "string", "dict", "look-alike"],
)
def test_send_without_a_human_approval_raises_and_never_calls_meta(approval: object) -> None:
    import asyncio

    repo = MemoryReplyRepository()
    client = FakeReplyClient()
    service = _service(repo=repo, provider=FakeProvider(), client=client)
    draft = _accepted_draft(repo, service)

    with pytest.raises(ApprovalRequired):
        asyncio.run(service.send(tenant_id=TENANT, draft_id=draft.id, approval=approval))  # type: ignore[arg-type]

    assert client.calls == []
    # Refused before any write: still accepted, not 'sending'.
    assert repo.get_draft(tenant_id=TENANT, draft_id=draft.id).status == "accepted"


def test_send_with_an_approval_for_another_draft_raises() -> None:
    import asyncio

    repo = MemoryReplyRepository()
    client = FakeReplyClient()
    service = _service(repo=repo, provider=FakeProvider(), client=client)
    draft = _accepted_draft(repo, service)

    for wrong in (_approval(uuid4()), HumanApproval(user_id=USER, approved_at=datetime.now(UTC))):
        with pytest.raises(ApprovalRequired, match="does not name"):
            asyncio.run(service.send(tenant_id=TENANT, draft_id=draft.id, approval=wrong))

    assert client.calls == []


def test_send_without_the_approval_argument_is_a_type_error() -> None:
    """`approval` is keyword-only with no default: forgetting it fails at the call."""
    import asyncio

    repo = MemoryReplyRepository()
    service = _service(repo=repo, provider=FakeProvider(), client=FakeReplyClient())
    draft = _accepted_draft(repo, service)

    with pytest.raises(TypeError, match="approval"):
        asyncio.run(service.send(tenant_id=TENANT, draft_id=draft.id))  # type: ignore[call-arg]


def test_send_draft_seam_requires_the_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """The published seam (`replies.send_draft`, what Reflex and HTTP call) passes the
    approval through; without one it refuses like the service."""
    import asyncio

    from qualify_api.replies import composition

    repo = MemoryReplyRepository()
    client = FakeReplyClient()
    service = _service(repo=repo, provider=FakeProvider(), client=client)
    draft = _accepted_draft(repo, service)
    monkeypatch.setattr(composition, "production_reply_service", lambda: service)

    with pytest.raises(ApprovalRequired):
        asyncio.run(composition.send_draft(tenant_id=TENANT, draft_id=draft.id, approval=None))  # type: ignore[arg-type]
    assert client.calls == []

    sent = asyncio.run(
        composition.send_draft(tenant_id=TENANT, draft_id=draft.id, approval=_approval(draft.id))
    )
    assert sent.status == "sent"
    assert len(client.calls) == 1


# --- m-24789645: provenance and one live draft per comment (Memory repository) -------


def test_create_draft_carries_provenance_and_defaults_to_none() -> None:
    from decimal import Decimal

    from qualify_api.replies.repository import DraftProvenance

    repo = MemoryReplyRepository()
    bare = repo.create_draft(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        candidate=_candidate(),
        gate_reason="r",
        generator_version="v",
        generated_text="t",
    )
    assert bare is not None
    assert (bare.grounding, bare.needs_review, bare.unsupported_claims) == (None, False, ())
    assert (bare.model_id, bare.cost_usd, bare.intent_result_id) == (None, None, None)

    intent = uuid4()
    grounded = repo.create_draft(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        candidate=_candidate(),
        gate_reason="r",
        generator_version="v",
        generated_text="t",
        provenance=DraftProvenance(
            grounding={"business_name": "Polet", "products": []},
            needs_review=True,
            unsupported_claims=("horario",),
            model_id="claude-haiku-5-5",
            input_tokens=10,
            output_tokens=5,
            cost_usd=Decimal("0.000035"),
            intent_result_id=intent,
        ),
    )
    assert grounded is not None
    assert grounded.grounding == {"business_name": "Polet", "products": []}
    assert grounded.needs_review is True
    assert grounded.unsupported_claims == ("horario",)
    assert (grounded.model_id, grounded.input_tokens, grounded.output_tokens) == (
        "claude-haiku-5-5",
        10,
        5,
    )
    assert grounded.intent_result_id == intent


def test_one_live_draft_per_comment_and_a_new_one_after_discard() -> None:
    repo = MemoryReplyRepository()
    candidate = _candidate()

    def create() -> object:
        return repo.create_draft(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            candidate=candidate,
            gate_reason="r",
            generator_version="v",
            generated_text="t",
        )

    first = create()
    assert first is not None
    assert create() is None  # the first one is live
    assert repo.get_live_draft(tenant_id=TENANT, message_id=candidate.message_id) == first

    repo.decide_draft(
        tenant_id=TENANT,
        draft_id=first.id,
        decision="discarded",
        final_text=None,
        decided_by_user_id=USER,
    )
    assert repo.get_live_draft(tenant_id=TENANT, message_id=candidate.message_id) is None
    second = create()
    assert second is not None and second.id != first.id
    # Generation still treats the comment as handled: it has drafts, live or not.
    assert repo.has_draft(tenant_id=TENANT, message_id=candidate.message_id)


def test_a_sent_draft_stays_live_so_the_comment_is_never_answered_twice() -> None:
    import asyncio

    repo = MemoryReplyRepository()
    service = _service(repo=repo, provider=FakeProvider(), client=FakeReplyClient())
    draft = _accepted_draft(repo, service)
    sent = asyncio.run(
        service.send(tenant_id=TENANT, draft_id=draft.id, approval=_approval(draft.id))
    )
    assert sent.status == "sent" and sent.is_live

    again = repo.create_draft(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        candidate=_candidate(draft.message_id),
        gate_reason="r",
        generator_version="v",
        generated_text="otra",
    )
    assert again is None
