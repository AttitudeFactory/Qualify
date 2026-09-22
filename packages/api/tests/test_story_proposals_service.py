"""QUA-106's Story-proposal service, fully offline against the Memory repository and
fakes. The tests that matter most: (1) nothing reaches `publish()` without a prior
human decision — there is no code path from `'proposed'` straight to a Meta call,
mirroring `ReplyService.send()`'s own guarantee; (2) `publish()`/`refresh()` never
reimplement any part of `PublishService`'s own state machine, only mirror its verdict;
(3) a failed trending-audio lookup degrades to an empty list, never an exception."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from qualify_api.publishing.client import MEDIA_TYPE_STORIES
from qualify_api.publishing.service import ConnectionTarget, PublishState
from qualify_api.stories.repository import MemoryStoryProposalRepository
from qualify_api.stories.service import StoryProposalService
from qualify_api.stories.trend_audio_client import TrendAudioError, TrendAudioOption

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")


class FakeConnections:
    def __init__(self, target: ConnectionTarget | None) -> None:
        self.target = target

    def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
        return self.target


class FakePublishService:
    """Stands in for `qualify_api.publishing.service.PublishService` — only the two
    methods `StoryProposalService` ever calls."""

    def __init__(self) -> None:
        self.start_calls: list[dict[str, object]] = []
        self.advance_calls: list[UUID] = []
        self.next_start_state = PublishState(
            attempt_id=uuid4(),
            status="processing",
            settled=False,
            published_media_id=None,
            reason=None,
        )
        self.next_advance_state: PublishState | None = None

    async def start(self, **kwargs: object) -> PublishState:
        self.start_calls.append(kwargs)
        return self.next_start_state

    async def advance(self, *, tenant_id: UUID, attempt_id: UUID) -> PublishState:
        self.advance_calls.append(attempt_id)
        assert self.next_advance_state is not None
        return self.next_advance_state


class FakeTrendAudioClient:
    def __init__(self, options: tuple[TrendAudioOption, ...] | Exception) -> None:
        self._options = options

    async def trending_audio(
        self, *, ig_user_id: str, audio_type: str
    ) -> tuple[TrendAudioOption, ...]:
        if isinstance(self._options, Exception):
            raise self._options
        return self._options


class FakeTrendAudioClientFactory:
    def __init__(self, client: FakeTrendAudioClient) -> None:
        self._client = client

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> FakeTrendAudioClient:
        return self._client


def _service(
    *,
    repo: MemoryStoryProposalRepository | None = None,
    publish: FakePublishService | None = None,
    connections: FakeConnections | None = None,
    trend_clients: FakeTrendAudioClientFactory | None = None,
) -> tuple[StoryProposalService, MemoryStoryProposalRepository, FakePublishService]:
    repo = repo or MemoryStoryProposalRepository()
    publish = publish or FakePublishService()
    connections = connections or FakeConnections(
        ConnectionTarget(ig_user_id="17841448653847824", status="active")
    )
    service = StoryProposalService(
        repository=repo,
        publish_service=publish,  # type: ignore[arg-type]
        connections=connections,
        trend_client_factory=trend_clients,
    )
    return service, repo, publish


def _proposed(repo: MemoryStoryProposalRepository):
    return repo.propose(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_object_key=f"t/{TENANT}/stories/video.mp4",
        media_content_type="video/mp4",
        caption="Un caption cualquiera",
        trend_audio_id=None,
        trend_audio_title=None,
    )


def test_publish_refuses_a_proposed_proposal_never_calls_meta() -> None:
    """QUA-106's own criterion, verbatim: no ruta de código va de 'proposed' a Meta."""
    service, repo, publish = _service()
    proposal = _proposed(repo)

    import asyncio

    with pytest.raises(ValueError, match="proposed"):
        asyncio.run(service.publish(tenant_id=TENANT, proposal_id=proposal.id))

    assert publish.start_calls == []


def test_decide_approved_sets_final_caption_equal_to_proposed() -> None:
    service, repo, _publish = _service()
    proposal = _proposed(repo)

    decided = service.decide(
        tenant_id=TENANT,
        proposal_id=proposal.id,
        decision="approved",
        final_caption=None,
        decided_by_user_id=USER,
    )

    assert decided.status == "approved"
    assert decided.final_caption == proposal.caption
    assert decided.decided_by_user_id == USER
    assert decided.is_settled is False  # approved is NOT terminal


def test_decide_rejected_settles_immediately_with_no_final_caption() -> None:
    service, repo, _publish = _service()
    proposal = _proposed(repo)

    decided = service.decide(
        tenant_id=TENANT,
        proposal_id=proposal.id,
        decision="rejected",
        final_caption=None,
        decided_by_user_id=USER,
    )

    assert decided.status == "rejected"
    assert decided.final_caption is None
    assert decided.is_settled is True


def test_decide_twice_raises() -> None:
    service, repo, _publish = _service()
    proposal = _proposed(repo)
    service.decide(
        tenant_id=TENANT,
        proposal_id=proposal.id,
        decision="approved",
        final_caption=None,
        decided_by_user_id=USER,
    )

    with pytest.raises(ValueError, match="not 'proposed'"):
        service.decide(
            tenant_id=TENANT,
            proposal_id=proposal.id,
            decision="rejected",
            final_caption=None,
            decided_by_user_id=USER,
        )


def test_publish_calls_publish_service_with_stories_media_type_and_marks_publishing() -> None:
    import asyncio

    service, repo, publish = _service()
    proposal = _proposed(repo)
    service.decide(
        tenant_id=TENANT,
        proposal_id=proposal.id,
        decision="approved",
        final_caption=None,
        decided_by_user_id=USER,
    )

    result = asyncio.run(service.publish(tenant_id=TENANT, proposal_id=proposal.id))

    assert len(publish.start_calls) == 1
    call = publish.start_calls[0]
    assert call["media_product_type"] == MEDIA_TYPE_STORIES
    assert call["connection_id"] == CONNECTION
    assert call["media_object_key"] == proposal.media_object_key
    assert result.status == "publishing"
    assert result.publish_attempt_id == publish.next_start_state.attempt_id


def test_refresh_marks_published_once_the_linked_attempt_settles() -> None:
    import asyncio

    service, repo, publish = _service()
    proposal = _proposed(repo)
    service.decide(
        tenant_id=TENANT,
        proposal_id=proposal.id,
        decision="approved",
        final_caption=None,
        decided_by_user_id=USER,
    )
    publishing = asyncio.run(service.publish(tenant_id=TENANT, proposal_id=proposal.id))
    publish.next_advance_state = PublishState(
        attempt_id=publishing.publish_attempt_id,
        status="published",
        settled=True,
        published_media_id="media-1",
        reason=None,
    )

    refreshed = asyncio.run(service.refresh(tenant_id=TENANT, proposal_id=proposal.id))

    assert refreshed.status == "published"
    assert refreshed.is_settled is True
    assert publish.advance_calls == [publishing.publish_attempt_id]


def test_refresh_marks_publish_failed_and_records_the_reason() -> None:
    import asyncio

    service, repo, publish = _service()
    proposal = _proposed(repo)
    service.decide(
        tenant_id=TENANT,
        proposal_id=proposal.id,
        decision="approved",
        final_caption=None,
        decided_by_user_id=USER,
    )
    publishing = asyncio.run(service.publish(tenant_id=TENANT, proposal_id=proposal.id))
    publish.next_advance_state = PublishState(
        attempt_id=publishing.publish_attempt_id,
        status="failed",
        settled=True,
        published_media_id=None,
        reason="container_error",
    )

    refreshed = asyncio.run(service.refresh(tenant_id=TENANT, proposal_id=proposal.id))

    assert refreshed.status == "publish_failed"
    assert refreshed.publish_error_code == "container_error"


def test_refresh_is_a_no_op_for_a_proposal_not_currently_publishing() -> None:
    import asyncio

    service, repo, publish = _service()
    proposal = _proposed(repo)

    refreshed = asyncio.run(service.refresh(tenant_id=TENANT, proposal_id=proposal.id))

    assert refreshed.status == "proposed"
    assert publish.advance_calls == []


def test_suggest_trend_audio_returns_options_from_the_client() -> None:
    import asyncio

    option = TrendAudioOption(
        audio_id="a1",
        title="Song",
        artist_or_creator="Artist",
        audio_type="music",
        duration_ms=1000,
        rank=0,
    )
    service, _repo, _publish = _service(
        trend_clients=FakeTrendAudioClientFactory(FakeTrendAudioClient((option,)))
    )

    options = asyncio.run(service.suggest_trend_audio(tenant_id=TENANT, connection_id=CONNECTION))

    assert options == (option,)


def test_suggest_trend_audio_degrades_to_empty_on_error_never_raises() -> None:
    import asyncio

    service, _repo, _publish = _service(
        trend_clients=FakeTrendAudioClientFactory(FakeTrendAudioClient(TrendAudioError("boom")))
    )

    options = asyncio.run(service.suggest_trend_audio(tenant_id=TENANT, connection_id=CONNECTION))

    assert options == ()


def test_suggest_trend_audio_without_a_client_factory_returns_empty() -> None:
    import asyncio

    service, _repo, _publish = _service(trend_clients=None)

    options = asyncio.run(service.suggest_trend_audio(tenant_id=TENANT, connection_id=CONNECTION))

    assert options == ()
