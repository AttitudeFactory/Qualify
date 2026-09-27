"""QUA-111 F3 + F4: the executor's claim + start, and its one-step advance — unit tests,
no DB.

The fake publisher reproduces the one property the executor relies on: an attempt row is
INSERTed per `(connection_id, idempotency_key)`, a repeated key returns the existing
attempt without "calling Meta", and Meta is only reached after a won INSERT.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.planner.discovery import ScopedTenants
from qualify_api.planner.executor import (
    AdvanceOutcome,
    EventExecutor,
    ExecutionOutcome,
    SettleOutcome,
)
from qualify_api.planner.locks import MemoryExecutionLock, attempt_lock_key, event_lock_key
from qualify_api.planner.post_reader import (
    NotPublishable,
    PublishableMedia,
    PublishablePost,
    UnpublishableReason,
)
from qualify_api.planner.repository import MemoryPlannerRepository, NewEvent
from qualify_api.planner.tick import TickRunner
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
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


@dataclass
class _Attempt:
    """The slice of `AttemptRecord` the executor reads."""

    id: UUID
    connection_id: UUID | None = None
    idempotency_key: str = ""
    status: str = "processing"
    settled_at: datetime | None = None
    published_media_id: str | None = None
    platform_error_code: str | None = None

    @property
    def is_settled(self) -> bool:
        return self.settled_at is not None

    def settle(self, status: str, **kw: object) -> None:
        self.status, self.settled_at = status, NOW
        for name, value in kw.items():
            setattr(self, name, value)


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
        attempt = _Attempt(uuid4(), connection_id=connection_id, idempotency_key=key)
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

    # advance (F4): answers with `next_advance`, or raises `raise_on_advance`.
    advance_calls: list[dict] = field(default_factory=list)
    next_advance: dict = field(default_factory=dict)
    raise_on_advance: Exception | None = None

    async def advance(self, **kw) -> PublishState:
        self.advance_calls.append(kw)
        if self.raise_on_advance is not None:
            raise self.raise_on_advance
        fields = {"status": "processing", "settled": False, **self.next_advance}
        return PublishState(
            attempt_id=kw["attempt_id"], published_media_id=None, reason=None, **fields
        )

    # AttemptLocator
    def find_by_idempotency_key(self, *, tenant_id, connection_id, idempotency_key):
        return self.attempts.get((connection_id, idempotency_key))

    def get_attempt(self, *, tenant_id, attempt_id):
        return next((a for a in self.attempts.values() if a.id == attempt_id), None)


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


def _due(world: World, *answers: PublishablePost | NotPublishable, connection=CONN, tenant=TENANT):
    post_id = uuid4()
    event = world.repo.add(
        NewEvent(
            tenant_id=tenant,
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
    row = world.repo.get(tenant_id=event.tenant_id, event_id=event.id)
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


# --- advance (F4) ------------------------------------------------------------------

A = AdvanceOutcome


async def _linked(world: World):
    """A due event taken through claim + start: `publishing` with an attempt."""
    event = _due(world)
    started = await world.executor.try_execute(event)
    assert started.outcome is Outcome.STARTED
    return world.repo.get(tenant_id=TENANT, event_id=event.id)


async def test_advance_calls_the_publisher_once_and_leaves_the_event_alone(world: World) -> None:
    event = await _linked(world)
    result = await world.executor.advance_event(event)
    assert result.outcome is A.ADVANCED and result.attempt_id == event.publish_attempt_id
    assert world.publisher.advance_calls == [
        {"tenant_id": TENANT, "attempt_id": event.publish_attempt_id}
    ]
    assert result.state is not None and result.state.poll_interval_seconds > 0
    assert _status(world, event) == ("publishing", event.publish_attempt_id)
    assert not world.lock.is_held(attempt_lock_key(event.publish_attempt_id))


@pytest.mark.parametrize("status", ["published", "failed"])
async def test_a_settled_attempt_is_reported_and_the_event_is_not_changed(
    world: World, status: str
) -> None:
    event = await _linked(world)
    world.publisher.next_advance = {"status": status, "settled": True}
    result = await world.executor.advance_event(event)
    assert result.outcome is A.SETTLED and result.state.status == status
    assert _status(world, event) == ("publishing", event.publish_attempt_id)  # F5's job


async def test_awaiting_confirmation_keeps_the_event_publishing(world: World) -> None:
    event = await _linked(world)
    world.publisher.next_advance = {"awaiting_confirmation": True}
    result = await world.executor.advance_event(event)
    assert result.outcome is A.AWAITING_CONFIRMATION
    assert _status(world, event)[0] == "publishing"


async def test_a_busy_attempt_lock_advances_nothing(world: World) -> None:
    event = await _linked(world)
    key = attempt_lock_key(event.publish_attempt_id)
    with world.lock.hold(tenant_id=TENANT, key=key) as held:
        assert held
        result = await world.executor.advance_event(event)
    assert result.outcome is A.BUSY
    assert not world.publisher.advance_calls


async def test_an_advance_error_leaves_the_event_intact_and_releases_the_lock(
    world: World,
) -> None:
    event = await _linked(world)
    world.publisher.raise_on_advance = RuntimeError("graph 500")
    result = await world.executor.advance_event(event)
    assert result.outcome is A.ADVANCE_ERROR and result.error == "RuntimeError"
    assert _status(world, event) == ("publishing", event.publish_attempt_id)
    assert not world.lock.is_held(attempt_lock_key(event.publish_attempt_id))
    world.publisher.raise_on_advance = None
    assert (await world.executor.advance_event(event)).outcome is A.ADVANCED


async def test_an_unlinked_event_is_not_advanced(world: World) -> None:
    event = _due(world)
    claimed = world.repo.claim(tenant_id=TENANT, event_id=event.id, expected_revision=1, now=NOW)
    result = await world.executor.advance_event(claimed)
    assert result.outcome is A.NOT_LINKED
    assert not world.publisher.advance_calls


async def test_an_event_no_longer_publishing_or_relinked_is_not_advanced(world: World) -> None:
    event = await _linked(world)
    stale = replace(event, publish_attempt_id=uuid4())  # a snapshot pointing elsewhere
    assert (await world.executor.advance_event(stale)).outcome is A.NOT_IN_FLIGHT
    world.repo._rows[event.id] = replace(event, status="published")
    assert (await world.executor.advance_event(event)).outcome is A.NOT_IN_FLIGHT
    assert not world.publisher.advance_calls


async def test_advance_in_flight_steps_only_the_tenants_linked_events(world: World) -> None:
    linked = await _linked(world)
    unlinked = _due(world)
    world.repo.claim(tenant_id=TENANT, event_id=unlinked.id, expected_revision=1, now=NOW)
    _due(world)  # still scheduled
    results = await world.executor.advance_in_flight(tenant_id=TENANT)
    assert [advanced.event_id for advanced, _ in results] == [linked.id]
    assert await world.executor.advance_in_flight(tenant_id=uuid4()) == []


def test_the_attempt_lock_and_the_event_lock_are_different_keys() -> None:
    same = uuid4()
    assert attempt_lock_key(same) != event_lock_key(same)
    assert attempt_lock_key(same) == f"qua111:publish-attempt:{same}"


# --- settle (F5) -------------------------------------------------------------------

S = SettleOutcome


def _attempt_of(world: World, event) -> _Attempt:
    attempt = world.publisher.get_attempt(tenant_id=TENANT, attempt_id=event.publish_attempt_id)
    assert attempt is not None
    return attempt


async def test_a_published_attempt_publishes_the_event_with_its_media_id(world: World) -> None:
    event = await _linked(world)
    _attempt_of(world, event).settle("published", published_media_id="1789")
    result = world.executor.settle_event(event)
    assert result.outcome is S.SETTLED_PUBLISHED and result.published_media_id == "1789"
    assert _status(world, event) == ("published", event.publish_attempt_id)


async def test_a_published_attempt_without_a_media_id_stays_without_one(world: World) -> None:
    """Confirmed through the container's PUBLISHED status: no id was ever returned."""
    event = await _linked(world)
    _attempt_of(world, event).settle("published", published_media_id=None)
    result = world.executor.settle_event(event)
    assert result.outcome is S.SETTLED_PUBLISHED and result.published_media_id is None
    assert _status(world, event)[0] == "published"


async def test_a_failed_attempt_fails_the_event_with_the_platform_reason(world: World) -> None:
    event = await _linked(world)
    _attempt_of(world, event).settle("failed", platform_error_code="container_error")
    result = world.executor.settle_event(event)
    assert result.outcome is S.SETTLED_FAILED and result.reason == "container_error"
    assert _status(world, event) == ("failed", event.publish_attempt_id)
    assert event.post_id not in world.repo.occupied_post_ids(tenant_id=TENANT, brand_id=BRAND)


async def test_an_unsettled_attempt_changes_nothing(world: World) -> None:
    event = await _linked(world)
    result = world.executor.settle_event(event)
    assert result.outcome is S.NOT_SETTLED
    assert _status(world, event) == ("publishing", event.publish_attempt_id)


async def test_settling_twice_is_already_settled(world: World) -> None:
    event = await _linked(world)
    _attempt_of(world, event).settle("published", published_media_id="1789")
    assert world.executor.settle_event(event).outcome is S.SETTLED_PUBLISHED
    again = world.executor.settle_event(event)  # the same (stale) snapshot, same outcome
    assert again.outcome is S.ALREADY_SETTLED
    assert _status(world, event)[0] == "published"


async def test_an_event_in_another_terminal_status_is_a_mismatch(world: World) -> None:
    event = await _linked(world)
    _attempt_of(world, event).settle("failed", platform_error_code="x")
    world.repo._rows[event.id] = replace(event, status="published")  # a hand-edited row
    result = world.executor.settle_event(event)
    assert result.outcome is S.MISMATCH
    assert _status(world, event)[0] == "published"  # never "repaired"


async def test_an_attempt_of_another_key_or_connection_is_a_mismatch(world: World) -> None:
    event = await _linked(world)
    attempt = _attempt_of(world, event)
    attempt.settle("published")
    attempt.idempotency_key = f"cal:{event.id}:99"
    assert world.executor.settle_event(event).outcome is S.MISMATCH
    attempt.idempotency_key, attempt.connection_id = f"cal:{event.id}:1", uuid4()
    assert world.executor.settle_event(event).outcome is S.MISMATCH
    assert _status(world, event)[0] == "publishing"


async def test_a_stale_revision_or_link_is_a_mismatch(world: World) -> None:
    event = await _linked(world)
    _attempt_of(world, event).settle("published")
    other = replace(event, publish_attempt_id=uuid4())
    assert world.executor.settle_event(other).outcome is S.MISMATCH
    assert world.executor.settle_event(replace(event, revision=2)).outcome is S.MISMATCH
    assert _status(world, event)[0] == "publishing"


def test_an_unlinked_event_is_not_settled(world: World) -> None:
    event = _due(world)
    assert world.executor.settle_event(event).outcome is S.NOT_LINKED


async def test_advance_in_flight_settles_only_after_settled_or_advance_error(
    world: World,
) -> None:
    event = await _linked(world)
    attempt = _attempt_of(world, event)

    # Still in progress: advanced, not settled.
    ((advanced, settled),) = await world.executor.advance_in_flight(tenant_id=TENANT)
    assert advanced.outcome is A.ADVANCED and settled is None

    # Awaiting confirmation: not settled either.
    world.publisher.next_advance = {"awaiting_confirmation": True}
    ((advanced, settled),) = await world.executor.advance_in_flight(tenant_id=TENANT)
    assert advanced.outcome is A.AWAITING_CONFIRMATION and settled is None

    # A transient error with the attempt NOT settled: the event stays publishing.
    world.publisher.next_advance = {}
    world.publisher.raise_on_advance = RuntimeError("graph 500")
    ((advanced, settled),) = await world.executor.advance_in_flight(tenant_id=TENANT)
    assert advanced.outcome is A.ADVANCE_ERROR and settled.outcome is S.NOT_SETTLED
    assert _status(world, event)[0] == "publishing"

    # An error after someone else settled the attempt: the row decides.
    attempt.settle("published", published_media_id="42")
    ((advanced, settled),) = await world.executor.advance_in_flight(tenant_id=TENANT)
    assert advanced.outcome is A.ADVANCE_ERROR and settled.outcome is S.SETTLED_PUBLISHED
    assert _status(world, event)[0] == "published"
    assert await world.executor.advance_in_flight(tenant_id=TENANT) == []  # nothing in flight


async def test_advance_in_flight_settles_a_settled_step(world: World) -> None:
    event = await _linked(world)
    _attempt_of(world, event).settle("failed", platform_error_code="container_poll_ceiling")
    world.publisher.next_advance = {"status": "failed", "settled": True}
    ((advanced, settled),) = await world.executor.advance_in_flight(tenant_id=TENANT)
    assert advanced.outcome is A.SETTLED and settled.outcome is S.SETTLED_FAILED
    assert _status(world, event)[0] == "failed"


def test_settle_from_attempt_compares_status_revision_and_attempt(world: World) -> None:
    repo, event = world.repo, _due(world)
    attempt_id = uuid4()
    kw = {"tenant_id": TENANT, "event_id": event.id, "attempt_id": attempt_id}
    assert repo.settle_from_attempt(expected_revision=1, published=True, **kw) is None  # scheduled
    repo.claim(tenant_id=TENANT, event_id=event.id, expected_revision=1, now=NOW)
    repo.link_attempt(
        tenant_id=TENANT, event_id=event.id, expected_revision=1, attempt_id=attempt_id
    )
    assert repo.settle_from_attempt(expected_revision=2, published=True, **kw) is None
    wrong = {**kw, "attempt_id": uuid4()}
    assert repo.settle_from_attempt(expected_revision=1, published=True, **wrong) is None
    done = repo.settle_from_attempt(expected_revision=1, published=True, **kw)
    assert done is not None and done.status == "published"
    assert repo.settle_from_attempt(expected_revision=1, published=False, **kw) is None


# --- the tick (F6) -----------------------------------------------------------------

TENANT_B = UUID("f3000000-0000-4000-8000-000000000002")


class _Source:
    """A TenantSource stand-in: a fixed answer, or an exception."""

    def __init__(self, *tenant_ids: UUID, fails: Exception | None = None) -> None:
        self.tenant_ids, self.fails = list(tenant_ids), fails

    def tenants(self, *, now):
        if self.fails is not None:
            raise self.fails
        return list(self.tenant_ids)


def _runner(world: World, source) -> TickRunner:
    return TickRunner(
        tenants=source, repository=world.repo, executor=world.executor, clock=lambda: NOW
    )


async def test_the_tick_processes_its_snapshot_in_order(world: World) -> None:
    linked = await _linked(world)  # (a) pre-existing linked
    unlinked = _due(world)
    world.repo.claim(tenant_id=TENANT, event_id=unlinked.id, expected_revision=1, now=NOW)
    due = _due(world)  # (c)
    world.publisher.advance_calls.clear()

    report = await _runner(world, _Source(TENANT)).run_once()
    (tenant,) = report.tenants
    assert [a.event_id for a, _ in tenant.advanced] == [linked.id]
    assert [r.event_id for r in tenant.resumed] == [unlinked.id]
    assert [r.event_id for r in tenant.executed] == [due.id]
    assert tenant.resumed[0].outcome is Outcome.STARTED
    assert tenant.executed[0].outcome is Outcome.STARTED
    # Only the pre-existing attempt was polled: the two started this tick wait.
    assert [c["attempt_id"] for c in world.publisher.advance_calls] == [linked.publish_attempt_id]
    assert tenant.errors == [] and report.error == "" and report.finished_at is not None


async def test_an_event_created_during_the_tick_waits_for_the_next(world: World) -> None:
    _due(world)
    created: list = []
    original = world.publisher.start

    async def start_and_plan_another(**kw):
        if not created:
            created.append(_due(world))  # appears mid-tick, after the snapshot
        return await original(**kw)

    world.publisher.start = start_and_plan_another
    first = await _runner(world, _Source(TENANT)).run_once()
    assert len(first.tenants[0].executed) == 1
    assert _status(world, created[0]) == ("scheduled", None)
    second = await _runner(world, _Source(TENANT)).run_once()
    assert [r.event_id for r in second.tenants[0].executed] == [created[0].id]


async def test_a_scoped_tick_never_touches_another_tenant(world: World) -> None:
    mine = _due(world)
    theirs = _due(world, tenant=TENANT_B)
    report = await _runner(world, ScopedTenants([TENANT])).run_once()
    assert [t.tenant_id for t in report.tenants] == [TENANT]
    assert _status(world, mine)[0] == "publishing"
    assert _status(world, theirs) == ("scheduled", None)
    assert all(c["tenant_id"] == TENANT for c in world.publisher.start_calls)


async def test_a_multi_tenant_source_processes_every_tenant(world: World) -> None:
    a, b = _due(world), _due(world, tenant=TENANT_B)
    report = await _runner(world, _Source(TENANT, TENANT_B)).run_once()
    assert [t.tenant_id for t in report.tenants] == [TENANT, TENANT_B]
    assert _status(world, a)[0] == _status(world, b)[0] == "publishing"


async def test_a_failing_tenant_does_not_stop_the_others(world: World, monkeypatch) -> None:
    b = _due(world, tenant=TENANT_B)
    real = world.repo.list_in_flight

    def broken(*, tenant_id, limit=100):
        if tenant_id == TENANT:
            raise ConnectionError("tenant A unreachable")
        return real(tenant_id=tenant_id, limit=limit)

    monkeypatch.setattr(world.repo, "list_in_flight", broken)
    report = await _runner(world, _Source(TENANT, TENANT_B)).run_once()
    a_report, b_report = report.tenants
    assert a_report.errors == ["snapshot:ConnectionError"] and a_report.operations == 0
    assert b_report.errors == [] and _status(world, b)[0] == "publishing"


async def test_a_failing_event_does_not_stop_the_others(world: World) -> None:
    bad, good = _due(world), _due(world)
    world.posts.set(bad.post_id, RuntimeError("reader down"))
    report = await _runner(world, _Source(TENANT)).run_once()
    (tenant,) = report.tenants
    assert tenant.errors == [f"{bad.id}:RuntimeError"]
    assert [r.event_id for r in tenant.executed] == [good.id]
    assert _status(world, bad) == ("scheduled", None)


async def test_a_tenant_without_work_does_nothing(world: World) -> None:
    report = await _runner(world, ScopedTenants([uuid4()])).run_once()
    assert report.tenants[0].operations == 0
    assert not world.publisher.start_calls and not world.publisher.advance_calls


async def test_a_change_after_the_snapshot_is_caught_by_the_claim(
    world: World, monkeypatch
) -> None:
    event = _due(world)
    real = world.repo.list_due

    def snapshot_then_cancel(*, tenant_id, now, limit=100):
        rows = real(tenant_id=tenant_id, now=now, limit=limit)
        world.repo.set_status(  # the operator cancels right after the snapshot
            tenant_id=tenant_id,
            event_id=event.id,
            expected_status="scheduled",
            new_status="cancelled",
        )
        return rows

    monkeypatch.setattr(world.repo, "list_due", snapshot_then_cancel)
    report = await _runner(world, _Source(TENANT)).run_once()
    assert [r.outcome for r in report.tenants[0].executed] == [Outcome.CLAIM_LOST]
    assert _status(world, event)[0] == "cancelled"
    assert not world.publisher.start_calls


async def test_a_failing_tenant_source_runs_nothing(world: World) -> None:
    _due(world)
    report = await _runner(world, _Source(fails=RuntimeError("admin down"))).run_once()
    assert report.error == "RuntimeError" and report.tenants == []
    assert not world.publisher.start_calls


async def test_a_second_tick_starts_nothing_new_and_polls_once(world: World) -> None:
    _due(world)
    await _runner(world, _Source(TENANT)).run_once()
    second = await _runner(world, _Source(TENANT)).run_once()
    (tenant,) = second.tenants
    assert not tenant.executed and not tenant.resumed and len(tenant.advanced) == 1
    assert len(world.publisher.start_calls) == 1
    advanced, _ = tenant.advanced[0]
    assert advanced.state.poll_interval_seconds > 0  # reported, never slept on


def test_a_scoped_source_needs_at_least_one_tenant() -> None:
    with pytest.raises(ValueError):
        ScopedTenants([])
    assert ScopedTenants([TENANT, TENANT]).tenants(now=NOW) == [TENANT]
