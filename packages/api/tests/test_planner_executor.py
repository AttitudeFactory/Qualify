"""QUA-111 F3: the executor's claim + start — unit tests, no DB.

The fake publisher reproduces the one property the executor relies on: an attempt row is
INSERTed per `(connection_id, idempotency_key)`, a repeated key returns the existing
attempt without "calling Meta", and Meta is only reached after a won INSERT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.planner.executor import EventExecutor, ExecutionOutcome
from qualify_api.planner.locks import MemoryExecutionLock, event_lock_key
from qualify_api.planner.post_reader import (
    NotPublishable,
    PublishableMedia,
    PublishablePost,
    UnpublishableReason,
)
from qualify_api.planner.repository import MemoryPlannerRepository, NewEvent
from qualify_api.publishing.service import PublishState, UnknownConnection

Outcome = ExecutionOutcome
NOW = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
TENANT = UUID("f3000000-0000-4000-8000-000000000001")
BRAND = UUID("f3000000-0000-4000-8000-0000000000b1")
CONN = UUID("f3000000-0000-4000-8000-0000000000c1")


def _media(media_type: str = "VIDEO", position: int = 0) -> PublishableMedia:
    content_type = "image/jpeg" if media_type == "IMAGE" else "video/mp4"
    return PublishableMedia(
        object_key=f"t/{TENANT}/media/{CONN}/{position}",
        content_type=content_type,
        media_type=media_type,
        position=position,
    )


def _publishable(
    post_id: UUID, media_product_type: str = "REELS", *media: PublishableMedia, brand=BRAND
) -> PublishablePost:
    return PublishablePost(
        tenant_id=TENANT,
        post_id=post_id,
        brand_id=brand,
        approved_revision=1,
        caption="Dos por uno",
        media_product_type=media_product_type,
        media=media or (_media(),),
    )


class FakePosts:
    """`get_publishable` answers from a per-post queue (the last answer repeats), so a
    test can make a POST publishable before the claim and not after it."""

    def __init__(self) -> None:
        self.answers: dict[UUID, list[PublishablePost | NotPublishable]] = {}

    def set(self, post_id: UUID, *answers: PublishablePost | NotPublishable) -> None:
        self.answers[post_id] = list(answers)

    def get_publishable(self, *, tenant_id: UUID, post_id: UUID):
        queue = self.answers[post_id]
        return queue.pop(0) if len(queue) > 1 else queue[0]


@dataclass
class _Attempt:
    id: UUID


@dataclass
class FakePublisher:
    """INSERT-once per (connection, key); `meta_calls` counts what reached "Meta"."""

    attempts: dict[tuple[UUID, str], _Attempt] = field(default_factory=dict)
    start_calls: list[dict] = field(default_factory=list)
    start_many_calls: list[dict] = field(default_factory=list)
    meta_calls: int = 0
    raise_before_insert: Exception | None = None
    raise_after_insert: Exception | None = None

    def _insert(self, connection_id: UUID, key: str) -> tuple[_Attempt, bool]:
        if self.raise_before_insert is not None:
            raise self.raise_before_insert
        existing = self.attempts.get((connection_id, key))
        if existing is not None:
            return existing, False
        attempt = _Attempt(uuid4())
        self.attempts[(connection_id, key)] = attempt
        return attempt, True

    def _state(self, attempt: _Attempt) -> PublishState:
        return PublishState(
            attempt_id=attempt.id,
            status="processing",
            settled=False,
            published_media_id=None,
            reason=None,
        )

    async def start(self, **kw) -> PublishState:
        self.start_calls.append(kw)
        attempt, created = self._insert(kw["connection_id"], kw["idempotency_key"])
        if created:
            if self.raise_after_insert is not None:
                raise self.raise_after_insert
            self.meta_calls += 1
        return self._state(attempt)

    async def start_many(self, **kw) -> PublishState:
        self.start_many_calls.append(kw)
        attempt, _ = self._insert(kw["connection_id"], kw["idempotency_key"])
        return self._state(attempt)  # start_many never calls Meta itself

    # AttemptLocator
    def find_by_idempotency_key(self, *, tenant_id, connection_id, idempotency_key):
        return self.attempts.get((connection_id, idempotency_key))


@dataclass
class World:
    repo: MemoryPlannerRepository
    posts: FakePosts
    publisher: FakePublisher
    lock: MemoryExecutionLock
    executor: EventExecutor


@pytest.fixture
def world() -> World:
    repo, posts, publisher, lock = (
        MemoryPlannerRepository(),
        FakePosts(),
        FakePublisher(),
        MemoryExecutionLock(),
    )
    executor = EventExecutor(
        repository=repo,
        posts=posts,
        publisher=publisher,
        attempts=publisher,
        lock=lock,
        clock=lambda: NOW,
    )
    return World(repo, posts, publisher, lock, executor)


def _due(world: World, *answers: PublishablePost | NotPublishable, connection=CONN):
    post_id = uuid4()
    event = world.repo.add(
        NewEvent(
            tenant_id=TENANT,
            brand_id=BRAND,
            post_id=post_id,
            connection_id=connection,
            scheduled_at=NOW - timedelta(minutes=5),
            scheduled_tz="America/Caracas",
            created_by_user_id=uuid4(),
        )
    )
    world.posts.set(post_id, *(answers or (_publishable(post_id),)))
    return event


def _status(world: World, event) -> tuple[str, UUID | None]:
    row = world.repo.get(tenant_id=TENANT, event_id=event.id)
    return row.status, row.publish_attempt_id


def _not(post_id: UUID, reason=UnpublishableReason.NOT_APPROVED) -> NotPublishable:
    return NotPublishable(post_id=post_id, reason=reason)


# --- the happy path --------------------------------------------------------------


async def test_a_ready_event_is_claimed_started_once_and_linked(world: World) -> None:
    event = _due(world)
    result = await world.executor.try_execute(event)
    assert result.outcome is Outcome.STARTED
    assert len(world.publisher.start_calls) == 1 and world.publisher.meta_calls == 1
    call = world.publisher.start_calls[0]
    assert call["idempotency_key"] == f"cal:{event.id}:1"
    assert call["connection_id"] == CONN and call["tenant_id"] == TENANT
    assert call["caption"] == "Dos por uno"
    assert call["media_product_type"] == "REELS"
    assert call["media_object_key"] == f"t/{TENANT}/media/{CONN}/0"
    assert _status(world, event) == ("publishing", result.attempt_id)
    assert not world.lock.is_held(event_lock_key(event.id))  # released


async def test_the_connection_is_the_events(world: World) -> None:
    other = uuid4()
    event = _due(world, connection=other)
    await world.executor.try_execute(event)
    assert world.publisher.start_calls[0]["connection_id"] == other


# --- routing by media_product_type -----------------------------------------------


async def test_an_image_goes_through_start_with_its_content_type(world: World) -> None:
    event = _due(world)
    world.posts.set(event.post_id, _publishable(event.post_id, "IMAGE", _media("IMAGE")))
    await world.executor.try_execute(event)
    (call,) = world.publisher.start_calls
    assert call["media_product_type"] == "IMAGE" and call["content_type"] == "image/jpeg"
    assert not world.publisher.start_many_calls


async def test_a_story_goes_through_start_and_never_becomes_a_reel(world: World) -> None:
    event = _due(world)
    world.posts.set(event.post_id, _publishable(event.post_id, "STORIES"))
    await world.executor.try_execute(event)
    (call,) = world.publisher.start_calls
    assert call["media_product_type"] == "STORIES"
    assert call["content_type"] is None  # video: the publisher ignores it anyway
    assert not world.publisher.start_many_calls


async def test_a_carousel_goes_through_start_many_in_position_order(world: World) -> None:
    event = _due(world)
    items = (_media("IMAGE", 0), _media("VIDEO", 1), _media("IMAGE", 2))
    world.posts.set(event.post_id, _publishable(event.post_id, "CAROUSEL", *items))
    result = await world.executor.try_execute(event)
    assert result.outcome is Outcome.STARTED
    assert not world.publisher.start_calls
    (call,) = world.publisher.start_many_calls
    assert [i.media_type for i in call["items"]] == ["IMAGE", "VIDEO", "IMAGE"]
    assert [i.media_object_key for i in call["items"]] == [m.object_key for m in items]
    assert call["caption"] == "Dos por uno" and call["idempotency_key"] == f"cal:{event.id}:1"


# --- not ready / claim lost ------------------------------------------------------


async def test_a_not_publishable_post_is_not_claimed_and_stays_scheduled(world: World) -> None:
    event = _due(world)
    world.posts.set(event.post_id, _not(event.post_id))
    result = await world.executor.try_execute(event)
    assert result.outcome is Outcome.NOT_READY and result.reason == "not_approved"
    assert _status(world, event) == ("scheduled", None)
    assert not world.publisher.start_calls


async def test_a_brand_mismatch_is_not_publishable(world: World) -> None:
    event = _due(world)
    world.posts.set(event.post_id, _publishable(event.post_id, brand=uuid4()))
    result = await world.executor.try_execute(event)
    assert result.outcome is Outcome.NOT_READY and result.reason == "post_not_found"
    assert _status(world, event) == ("scheduled", None)


async def test_a_lost_claim_starts_nothing(world: World) -> None:
    event = _due(world)
    world.repo.claim(tenant_id=TENANT, event_id=event.id, expected_revision=1, now=NOW)
    result = await world.executor.try_execute(event)  # stale `scheduled` snapshot
    assert result.outcome is Outcome.CLAIM_LOST
    assert not world.publisher.start_calls


# --- after the claim ---------------------------------------------------------------


async def test_a_post_that_stops_being_publishable_after_the_claim_fails_unstarted(
    world: World,
) -> None:
    event = _due(world)
    world.posts.set(
        event.post_id,
        _publishable(event.post_id),
        _not(event.post_id, UnpublishableReason.REVISION_NOT_APPROVED),
    )
    result = await world.executor.try_execute(event)
    assert result.outcome is Outcome.FAILED_NOT_PUBLISHABLE
    assert result.reason == "revision_not_approved"
    assert _status(world, event) == ("failed", None)
    assert not world.publisher.start_calls and not world.publisher.attempts


async def test_an_existing_attempt_for_the_key_is_only_linked(world: World) -> None:
    event = _due(world)
    claimed = world.repo.claim(tenant_id=TENANT, event_id=event.id, expected_revision=1, now=NOW)
    prior = _Attempt(uuid4())
    world.publisher.attempts[(CONN, f"cal:{event.id}:1")] = prior
    result = await world.executor.start_claimed(claimed)
    assert result.outcome is Outcome.LINKED_EXISTING and result.attempt_id == prior.id
    assert not world.publisher.start_calls  # never a second start
    assert _status(world, event) == ("publishing", prior.id)


async def test_an_already_linked_event_is_left_alone(world: World) -> None:
    event = _due(world)
    first = await world.executor.try_execute(event)
    again = await world.executor.start_claimed(world.repo.get(tenant_id=TENANT, event_id=event.id))
    assert again.outcome is Outcome.LINKED_EXISTING and again.attempt_id == first.attempt_id
    assert len(world.publisher.start_calls) == 1


async def test_start_failing_after_the_insert_is_linked_and_never_restarted(
    world: World,
) -> None:
    event = _due(world)
    world.publisher.raise_after_insert = RuntimeError("meta timeout")
    first = await world.executor.try_execute(event)
    assert first.outcome is Outcome.STARTED and first.attempt_id is not None
    assert _status(world, event) == ("publishing", first.attempt_id)
    # A resume of the same event: found linked, no second start, still one attempt.
    world.publisher.raise_after_insert = None
    again = await world.executor.start_claimed(world.repo.get(tenant_id=TENANT, event_id=event.id))
    assert again.attempt_id == first.attempt_id
    assert len(world.publisher.start_calls) == 1 and len(world.publisher.attempts) == 1
    assert world.publisher.meta_calls == 0


async def test_an_unlinked_event_whose_attempt_exists_is_relinked_without_start(
    world: World,
) -> None:
    """The crash window: start() wrote the attempt, the process died before the link."""
    event = _due(world)
    claimed = world.repo.claim(tenant_id=TENANT, event_id=event.id, expected_revision=1, now=NOW)
    await world.publisher.start(
        tenant_id=TENANT, connection_id=CONN, idempotency_key=f"cal:{event.id}:1"
    )
    world.publisher.start_calls.clear()
    result = await world.executor.start_claimed(claimed)
    assert result.outcome is Outcome.LINKED_EXISTING
    assert not world.publisher.start_calls
    assert world.publisher.meta_calls == 1  # only the crashed run's


async def test_unknown_connection_fails_the_event_unstarted(world: World) -> None:
    event = _due(world)
    world.publisher.raise_before_insert = UnknownConnection(str(CONN))
    result = await world.executor.try_execute(event)
    assert result.outcome is Outcome.FAILED_UNKNOWN_CONNECTION
    assert _status(world, event) == ("failed", None)
    assert not world.publisher.attempts


async def test_a_transient_error_before_the_insert_defers(world: World) -> None:
    event = _due(world)
    world.publisher.raise_before_insert = ConnectionError("db blip")
    result = await world.executor.try_execute(event)
    assert result.outcome is Outcome.DEFERRED
    assert _status(world, event) == ("publishing", None)  # left for the next tick
    world.publisher.raise_before_insert = None
    retry = await world.executor.start_claimed(world.repo.get(tenant_id=TENANT, event_id=event.id))
    assert retry.outcome is Outcome.STARTED
    assert len(world.publisher.attempts) == 1 and world.publisher.meta_calls == 1


async def test_a_busy_lock_does_nothing(world: World) -> None:
    event = _due(world)
    claimed = world.repo.claim(tenant_id=TENANT, event_id=event.id, expected_revision=1, now=NOW)
    with world.lock.hold(tenant_id=TENANT, key=event_lock_key(event.id)) as held:
        assert held
        result = await world.executor.start_claimed(claimed)
    assert result.outcome is Outcome.BUSY
    assert not world.publisher.start_calls
    assert _status(world, event) == ("publishing", None)


async def test_a_lost_link_never_starts_again(world: World, monkeypatch) -> None:
    event = _due(world)
    monkeypatch.setattr(world.repo, "link_attempt", lambda **_: None)
    result = await world.executor.try_execute(event)
    assert result.outcome is Outcome.LINK_LOST and result.attempt_id is not None
    assert len(world.publisher.start_calls) == 1
    # A second pass finds the attempt by its key: still no second start.
    again = await world.executor.start_claimed(world.repo.get(tenant_id=TENANT, event_id=event.id))
    assert again.outcome is Outcome.LINK_LOST and again.attempt_id == result.attempt_id
    assert len(world.publisher.start_calls) == 1


async def test_an_event_no_longer_publishing_is_not_touched(world: World) -> None:
    event = _due(world)
    result = await world.executor.start_claimed(event)  # still `scheduled`, never claimed
    assert result.outcome is Outcome.NOT_IN_FLIGHT
    assert not world.publisher.start_calls


# --- fail_unstarted (memory repository) ------------------------------------------


def test_fail_unstarted_only_matches_an_unlinked_publishing_event(world: World) -> None:
    event = _due(world)
    repo = world.repo
    assert repo.fail_unstarted(tenant_id=TENANT, event_id=event.id, expected_revision=1) is None
    repo.claim(tenant_id=TENANT, event_id=event.id, expected_revision=1, now=NOW)
    repo.link_attempt(tenant_id=TENANT, event_id=event.id, expected_revision=1, attempt_id=uuid4())
    assert repo.fail_unstarted(tenant_id=TENANT, event_id=event.id, expected_revision=1) is None
    assert _status(world, event)[0] == "publishing"
