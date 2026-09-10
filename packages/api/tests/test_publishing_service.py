"""A5 + A6-min — the publish service, fully offline against fakes.

The tests that matter most here are the two the backlog marks MANDATORY: a timeout
injected AFTER `publish_container` goes out must leave every later `advance()` read-only
(zero new publish calls), including the slow case where the container still reads
`FINISHED` because the publish has not propagated — the exact double-post the 2026-08-07
live smoke demonstrated.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from qualify_shared.objects.gate import ObjectGate

from qualify_api.publishing.client import (
    ContainerStatus,
    PublishError,
    ResumableContainer,
    UploadOutcome,
)
from qualify_api.publishing.repository import MemoryPublishAttemptRepository
from qualify_api.publishing.service import (
    CEILING_EXCEEDED,
    CHILD_ERROR_PREFIX,
    CONNECTION_NOT_ACTIVE_PREFIX,
    MAX_CAROUSEL_ITEMS,
    PUBLISH_SENT_MARKER,
    ConnectionTarget,
    MediaItem,
    PublishService,
    TooManyItems,
    UnknownConnection,
)

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
IG_USER = "17840000000000000"
PUBLISHING_SRC = Path(__file__).resolve().parents[1] / "src" / "qualify_api" / "publishing"


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, fileobj: io.IOBase, content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key][0])


class FakePublishClient:
    """Programmable platform double that COUNTS its calls — the A6-min property is
    'zero new publish_container calls', and only a counter can assert a zero."""

    def __init__(self) -> None:
        self.container = ResumableContainer(container_id="c-1", upload_uri="https://rupload/u")
        # QUA-99 (4/6): if set, create_container POPS one entry per call instead of
        # always returning `self.container` — needed so N children get N DISTINCT
        # container ids. None (the default) preserves every pre-existing test's
        # behaviour byte-for-byte.
        self.container_sequence: list[ResumableContainer] | None = None
        self.create_container_calls: list[dict[str, object]] = []
        self.create_error: Exception | None = None
        self.upload_outcome = UploadOutcome(success=True)
        self.status_script: list[ContainerStatus] = []
        self.status_calls: list[str] = []
        self.status_error: Exception | None = None
        self.publish_error: Exception | None = None
        self.publish_media_id = "media-1"
        # QUA-99 (4/6): the carousel-container-creation call, counted and recorded
        # separately from `calls` (unchanged) so no pre-existing assertion on `calls`
        # needs to change.
        self.carousel_container_id = "carousel-1"
        self.carousel_error: Exception | None = None
        self.carousel_calls: list[list[str]] = []
        # QUA-99 (4.5/6): the caption seen on each create_carousel_container call,
        # recorded separately so tests can assert exactly what was sent to Meta.
        self.carousel_caption_calls: list[str | None] = []
        self.calls = {"create": 0, "upload": 0, "status": 0, "publish": 0, "create_carousel": 0}
        self.upload_sizes: list[int] = []

    async def create_container(self, **kwargs: object) -> ResumableContainer:
        self.calls["create"] += 1
        self.create_container_calls.append(kwargs)
        if self.create_error is not None:
            raise self.create_error
        if self.container_sequence:
            return self.container_sequence.pop(0)
        return self.container

    async def create_carousel_container(
        self, *, ig_user_id: str, children: list[str], caption: str | None = None
    ) -> str:
        self.calls["create_carousel"] += 1
        self.carousel_calls.append(list(children))
        self.carousel_caption_calls.append(caption)
        if self.carousel_error is not None:
            raise self.carousel_error
        return self.carousel_container_id

    async def upload_bytes(self, *, upload_uri: str, fileobj, file_size: int) -> UploadOutcome:
        self.calls["upload"] += 1
        self.upload_sizes.append(file_size)
        return self.upload_outcome

    async def container_status(self, *, container_id: str) -> ContainerStatus:
        self.calls["status"] += 1
        self.status_calls.append(container_id)
        if self.status_error is not None:
            raise self.status_error
        return self.status_script.pop(0)

    async def publish_container(self, *, ig_user_id: str, creation_id: str) -> str:
        self.calls["publish"] += 1
        if self.publish_error is not None:
            raise self.publish_error
        return self.publish_media_id


class Harness:
    def __init__(
        self,
        *,
        connection_status: str = "active",
        clock_offset_seconds: float = 0.0,
    ) -> None:
        self.repo = MemoryPublishAttemptRepository()
        self.store = MemoryStore()
        self.client = FakePublishClient()
        self.targets = {
            (TENANT, CONNECTION): ConnectionTarget(ig_user_id=IG_USER, status=connection_status)
        }
        harness = self

        class Connections:
            def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
                return harness.targets.get((tenant_id, connection_id))

        class Factory:
            async def client_for(self, *, tenant_id: UUID, connection_id: UUID):
                return harness.client

        self.degrade_calls: list[tuple[UUID, UUID]] = []

        def degrader(*, tenant_id: UUID, connection_id: UUID) -> None:
            harness.degrade_calls.append((tenant_id, connection_id))

        self.service = PublishService(
            repository=self.repo,
            gate=ObjectGate(self.store),
            connections=Connections(),
            client_factory=Factory(),
            clock=lambda: datetime.now(UTC) + timedelta(seconds=clock_offset_seconds),
            connection_degrader=degrader,
        )
        self.media_key = f"t/{TENANT}/media/{CONNECTION}/m-1"
        self.store.objects[self.media_key] = (b"reel-bytes", "video/mp4")

    async def start(self, key: str = "op-1"):
        return await self.service.start(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_object_key=self.media_key,
            media_product_type="REELS",
            idempotency_key=key,
        )

    async def advance(self, attempt_id: UUID):
        return await self.service.advance(tenant_id=TENANT, attempt_id=attempt_id)

    # --- QUA-99 (4/6): carousel helpers ---

    def stage_videos(self, n: int) -> list[MediaItem]:
        """Stages N distinct objects and returns them as MediaItems, ready for
        start_many. Also pre-loads a distinct container per child (container_sequence)
        so a carousel's children are genuinely distinguishable ids, not N copies of the
        same one."""
        items = []
        containers = []
        for i in range(n):
            key = f"t/{TENANT}/media/{CONNECTION}/child-{i}"
            self.store.objects[key] = (f"video-bytes-{i}".encode(), "video/mp4")
            items.append(MediaItem(media_object_key=key, content_type="video/mp4"))
            containers.append(
                ResumableContainer(container_id=f"child-c-{i}", upload_uri=f"https://rupload/{i}")
            )
        self.client.container_sequence = containers
        return items

    async def start_many(
        self, items: list[MediaItem], key: str = "op-1", caption: str | None = None
    ):
        return await self.service.start_many(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            items=items,
            idempotency_key=key,
            caption=caption,
        )

    async def drive_to_settled(self, attempt_id: UUID, *, max_steps: int = 50):
        """Repeatedly calls advance() — the same client-driven cadence Reflex's own poll
        loop uses — until the attempt settles. `max_steps` is a TEST safety net, never a
        production concept: a bug that stops making progress fails the test loudly
        instead of hanging it."""
        state = await self.advance(attempt_id)
        steps = 1
        while not state.settled:
            if steps >= max_steps:  # pragma: no cover — only a stuck design ever hits this
                raise AssertionError(f"did not settle within {max_steps} advance() calls")
            state = await self.advance(attempt_id)
            steps += 1
        return state


# --------------------------------------------------------------------------------------
# start()
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_happy_path_ends_processing_with_creation_id_recorded() -> None:
    h = Harness()
    state = await h.start()
    assert state.status == "processing" and not state.settled
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=state.attempt_id)
    assert record is not None and record.creation_id == "c-1"
    assert h.client.upload_sizes == [len(b"reel-bytes")]


@pytest.mark.asyncio
async def test_start_is_idempotent_by_key_and_never_publishes_twice() -> None:
    h = Harness()
    first = await h.start("same-key")
    second = await h.start("same-key")
    assert second.attempt_id == first.attempt_id
    assert h.client.calls["create"] == 1
    assert h.client.calls["upload"] == 1


@pytest.mark.asyncio
async def test_start_refuses_a_dead_connection_before_any_platform_call() -> None:
    """The token is resolved at PUBLISH time: a revoked connection fails distinguishably
    with zero Meta calls — never a mystery container error later."""
    h = Harness(connection_status="revoked")
    state = await h.start()
    assert state.settled and state.status == "failed"
    assert state.reason == f"{CONNECTION_NOT_ACTIVE_PREFIX}:revoked"
    assert h.client.calls == {
        "create": 0,
        "upload": 0,
        "status": 0,
        "publish": 0,
        "create_carousel": 0,
    }


@pytest.mark.asyncio
async def test_start_on_unknown_connection_raises_without_a_row() -> None:
    h = Harness()
    with pytest.raises(UnknownConnection):
        await h.service.start(
            tenant_id=TENANT,
            connection_id=uuid4(),
            media_object_key=h.media_key,
            media_product_type="REELS",
            idempotency_key="k",
        )
    assert h.repo.rows == {}


@pytest.mark.asyncio
async def test_container_failure_leaves_the_write_ahead_row_pending() -> None:
    """The A4 promise, exercised through the service: a create_container failure leaves a
    'pending' row with creation_id NULL — a trace, never an absence."""
    h = Harness()
    h.client.create_error = PublishError("POST /media failed with HTTP 500")
    with pytest.raises(PublishError):
        await h.start()
    (record,) = h.repo.rows.values()
    assert record.status == "pending" and record.creation_id is None and not record.is_settled


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retriable", "expect_settled"),
    [(False, True), (True, False), (None, False)],
)
async def test_upload_retriable_three_values(retriable: bool | None, expect_settled: bool) -> None:
    """`retriable=None` is UNKNOWN, not False (R10): only Meta's explicit 'this media will
    never be accepted' settles the attempt."""
    h = Harness()
    h.client.upload_outcome = UploadOutcome(success=False, retriable=retriable, error_type="boom")
    state = await h.start()
    assert state.settled is expect_settled
    if expect_settled:
        assert state.status == "failed" and state.reason == "boom"
    else:
        assert state.status == "uploading"


# --------------------------------------------------------------------------------------
# advance()
# --------------------------------------------------------------------------------------


async def _started(h: Harness) -> UUID:
    state = await h.start()
    assert state.status == "processing"
    return state.attempt_id


@pytest.mark.asyncio
async def test_advance_in_progress_reports_without_settling_or_publishing() -> None:
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.IN_PROGRESS]
    state = await h.advance(attempt_id)
    assert not state.settled and state.container_status == "IN_PROGRESS"
    assert h.client.calls["publish"] == 0


@pytest.mark.asyncio
async def test_advance_finished_publishes_once_and_settles() -> None:
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED]
    state = await h.advance(attempt_id)
    assert state.settled and state.status == "published"
    assert state.published_media_id == "media-1"
    assert h.client.calls["publish"] == 1


@pytest.mark.asyncio
async def test_advance_published_settles_without_calling_publish_again() -> None:
    """PUBLISHED is how reconciliation discovers a publish we were unsure about DID land —
    success, with zero publish_container calls."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.PUBLISHED]
    state = await h.advance(attempt_id)
    assert state.settled and state.status == "published"
    assert h.client.calls["publish"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [ContainerStatus.ERROR, ContainerStatus.EXPIRED])
async def test_advance_terminal_container_settles_failed_distinguishably(
    terminal: ContainerStatus,
) -> None:
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [terminal]
    state = await h.advance(attempt_id)
    assert state.settled and state.status == "failed"
    assert state.reason == f"container_{terminal.value.lower()}"
    assert h.client.calls["publish"] == 0


@pytest.mark.asyncio
async def test_advance_on_a_settled_attempt_is_a_pure_read() -> None:
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED]
    await h.advance(attempt_id)
    calls_before = dict(h.client.calls)
    state = await h.advance(attempt_id)
    assert state.settled and h.client.calls == calls_before


# --------------------------------------------------------------------------------------
# A6-min — the second-publish prohibition (the two MANDATORY tests, then the PPA case)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timed_out_publish_settles_nothing_and_marks_the_send() -> None:
    """Property test, not happy-path: an ambiguous publish failure leaves the attempt
    UNSETTLED (published would be unproven, failed could be a lie made irreversible by the
    settle-once trigger) and visibly awaiting confirmation."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED]
    h.client.publish_error = TimeoutError("read timeout after the request went out")

    state = await h.advance(attempt_id)

    assert not state.settled and state.status == "processing"
    assert state.awaiting_confirmation
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=attempt_id)
    assert record is not None and record.platform_error_code == PUBLISH_SENT_MARKER
    assert h.client.calls["publish"] == 1


@pytest.mark.asyncio
async def test_finished_after_a_sent_publish_never_resends() -> None:
    """THE hole-closing test: the container can still read FINISHED after the publish went
    out (the live smoke measured exactly this lag), and a FINISHED-shaped answer must NOT
    trigger a second send."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED, ContainerStatus.FINISHED]
    h.client.publish_error = TimeoutError("boom")

    await h.advance(attempt_id)  # send goes out, times out, marker written
    state = await h.advance(attempt_id)  # container STILL says FINISHED

    assert h.client.calls["publish"] == 1  # zero NEW sends
    assert not state.settled and state.awaiting_confirmation


@pytest.mark.asyncio
async def test_published_after_a_sent_publish_confirms_and_settles() -> None:
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED, ContainerStatus.PUBLISHED]
    h.client.publish_error = TimeoutError("boom")

    await h.advance(attempt_id)
    state = await h.advance(attempt_id)

    assert state.settled and state.status == "published"
    assert h.client.calls["publish"] == 1


@pytest.mark.asyncio
async def test_coded_publish_refusal_is_recorded_distinguishably_but_not_settled() -> None:
    """A PPA-style refusal arrives as a NUMERIC platform code. It must not vanish into a
    generic failed — and after the send went out it is still not proof the publish did not
    land, so it settles nothing."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED]
    h.client.publish_error = PublishError(
        "POST /media_publish failed with HTTP 400", platform_code=200, platform_subcode=1363057
    )

    state = await h.advance(attempt_id)

    assert not state.settled
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=attempt_id)
    assert record is not None
    assert record.platform_error_code == "platform_error_code:200.1363057"


@pytest.mark.asyncio
async def test_401_settles_failed_not_awaiting_and_degrades_the_connection() -> None:
    """QUA-90: NOT the same ambiguity as a coded refusal or a timeout — a 401 means the
    send never went out, so unlike every test above this settles `failed` immediately,
    and the connection is degraded so Conexiones can offer 'reconnect'."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED]
    h.client.publish_error = PublishError(
        "POST /media_publish failed with HTTP 401", http_status=401
    )

    state = await h.advance(attempt_id)

    assert state.settled and state.status == "failed"
    assert not state.awaiting_confirmation
    assert h.degrade_calls == [(TENANT, CONNECTION)]


@pytest.mark.asyncio
async def test_code_190_settles_failed_even_without_a_401_status() -> None:
    """The ticket's detection condition is HTTP 401 **or** `error.code=190` — code 190
    alone (no captured HTTP status) must trigger the same path."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED]
    h.client.publish_error = PublishError(
        "POST /media_publish failed with HTTP 400", platform_code=190
    )

    state = await h.advance(attempt_id)

    assert state.settled and state.status == "failed"
    assert h.degrade_calls == [(TENANT, CONNECTION)]


@pytest.mark.asyncio
async def test_other_coded_refusals_do_not_degrade_the_connection() -> None:
    """Regression: only 401/190 triggers QUA-90's path — every other coded refusal keeps
    its pre-existing awaiting-confirmation behavior untouched."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED]
    h.client.publish_error = PublishError(
        "POST /media_publish failed with HTTP 400", platform_code=200, platform_subcode=1363057
    )

    state = await h.advance(attempt_id)

    assert not state.settled
    assert h.degrade_calls == []


# --------------------------------------------------------------------------------------
# QUA-90 — the same 401/190 detection on the container_status() POLL inside advance(),
# not just on the publish_container() SEND inside _publish_once()
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_container_status_401_degrades_the_connection_but_settles_nothing() -> None:
    """Unlike a 401/190 on the SEND (`publish_container`), a 401/190 on the STATUS POLL
    says nothing about whether the container ever published — A6-min means this must NOT
    settle the attempt, only degrade the connection so Conexiones can offer reconnect."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_error = PublishError("GET /c-1 failed with HTTP 401", http_status=401)

    with pytest.raises(PublishError):
        await h.advance(attempt_id)

    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=attempt_id)
    assert record is not None and not record.is_settled
    assert h.degrade_calls == [(TENANT, CONNECTION)]


@pytest.mark.asyncio
async def test_container_status_code_190_degrades_even_without_a_401_status() -> None:
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_error = PublishError("GET /c-1 failed with HTTP 400", platform_code=190)

    with pytest.raises(PublishError):
        await h.advance(attempt_id)

    assert h.degrade_calls == [(TENANT, CONNECTION)]


@pytest.mark.asyncio
async def test_container_status_other_errors_do_not_degrade() -> None:
    """Regression: a transient 5xx on the status poll must not degrade a healthy
    connection — only 401/190 is an auth signal."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_error = PublishError("GET /c-1 failed with HTTP 500")

    with pytest.raises(PublishError):
        await h.advance(attempt_id)

    assert h.degrade_calls == []


@pytest.mark.asyncio
async def test_coded_refusal_still_counts_as_sent_and_never_resends() -> None:
    """Regression for a hole found DURING implementation: the coded-refusal marker
    replaces the plain one, and if 'sent' matched only the plain spelling, the next
    FINISHED would trigger a second send — the exact double-post A6-min forbids."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED, ContainerStatus.FINISHED]
    h.client.publish_error = PublishError(
        "POST /media_publish failed with HTTP 400", platform_code=200
    )

    await h.advance(attempt_id)  # send emitted, refused with a code, marker replaced
    state = await h.advance(attempt_id)  # container still FINISHED

    assert h.client.calls["publish"] == 1  # zero NEW sends
    assert not state.settled and state.awaiting_confirmation


# --------------------------------------------------------------------------------------
# The 300 s ceiling — measured against the ROW, not a loop counter
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ceiling_settles_failed_distinguishably_from_a_container_error() -> None:
    h = Harness(clock_offset_seconds=400)
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.IN_PROGRESS]
    state = await h.advance(attempt_id)
    assert state.settled and state.status == "failed"
    assert state.reason == CEILING_EXCEEDED


@pytest.mark.asyncio
async def test_ceiling_never_overrides_a_sent_publish() -> None:
    """Once the send went out, only the container's own verdict may end the attempt —
    a ceiling-settled 'failed' over a publish that landed would be the irreversible lie."""
    h = Harness()
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.FINISHED, ContainerStatus.IN_PROGRESS]
    h.client.publish_error = TimeoutError("boom")
    await h.advance(attempt_id)  # marker written

    h2_clock = datetime.now(UTC) + timedelta(seconds=4000)
    h.service._clock = lambda: h2_clock  # noqa: SLF001 — direct, honest test seam

    state = await h.advance(attempt_id)
    assert not state.settled and state.awaiting_confirmation


# --------------------------------------------------------------------------------------
# QUA-99 (4/6) — multi-video (carousel) orchestration
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_many_with_one_item_delegates_to_start_unchanged() -> None:
    """The case QUA-19 already covers must go through the EXACT same code, not a
    parallel one-item special case of the carousel machinery."""
    h = Harness()
    items = h.stage_videos(1)
    state = await h.start_many(items)
    assert state.status == "processing" and not state.settled
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=state.attempt_id)
    assert record is not None
    assert record.media_product_type == "REELS"  # never "CAROUSEL" for one item
    assert h.repo.list_children(tenant_id=TENANT, attempt_id=state.attempt_id) == []
    assert h.client.calls["create"] == 1
    assert h.client.calls["create_carousel"] == 0


@pytest.mark.asyncio
async def test_eleven_items_is_rejected_before_any_meta_or_repository_call() -> None:
    h = Harness()
    items = h.stage_videos(MAX_CAROUSEL_ITEMS + 1)
    with pytest.raises(TooManyItems):
        await h.start_many(items)
    assert h.repo.rows == {}
    assert h.repo.children == {}
    assert h.client.calls == {
        "create": 0,
        "upload": 0,
        "status": 0,
        "publish": 0,
        "create_carousel": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("n", [2, 5, 10])
async def test_carousel_happy_path_end_to_end(n: int) -> None:
    """2, 5, and 10 videos — the full range this PR must support — each produce ONE
    settled, published attempt with N children and exactly one CAROUSEL container."""
    h = Harness()
    items = h.stage_videos(n)
    h.client.status_script = [ContainerStatus.FINISHED] * (n + 1)  # n children + carousel

    start_state = await h.start_many(items)
    assert not start_state.settled
    final = await h.drive_to_settled(start_state.attempt_id)

    assert final.settled and final.status == "published"
    assert final.published_media_id == "media-1"
    assert h.client.calls["create"] == n
    assert h.client.calls["create_carousel"] == 1
    assert h.client.calls["publish"] == 1
    assert h.client.carousel_calls == [[f"child-c-{i}" for i in range(n)]]
    children = h.repo.list_children(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert all(c.status == "finished" for c in children)
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert record.creation_id == "carousel-1"  # the CAROUSEL's id, never a child's


@pytest.mark.asyncio
async def test_advance_makes_exactly_one_unit_of_progress_per_call() -> None:
    """The service cannot assume everything happens in one call — pinned step by step
    for a 2-item carousel: create+upload child0, create+upload child1, poll child0, poll
    child1, create the CAROUSEL, poll it and publish. Six calls, six units of work."""
    h = Harness()
    items = h.stage_videos(2)
    h.client.status_script = [ContainerStatus.FINISHED] * 3
    start_state = await h.start_many(items)
    attempt_id = start_state.attempt_id

    await h.advance(attempt_id)
    assert h.client.calls == {
        "create": 1,
        "upload": 1,
        "status": 0,
        "publish": 0,
        "create_carousel": 0,
    }

    await h.advance(attempt_id)
    assert h.client.calls == {
        "create": 2,
        "upload": 2,
        "status": 0,
        "publish": 0,
        "create_carousel": 0,
    }

    await h.advance(attempt_id)
    assert h.client.calls == {
        "create": 2,
        "upload": 2,
        "status": 1,
        "publish": 0,
        "create_carousel": 0,
    }

    await h.advance(attempt_id)
    assert h.client.calls == {
        "create": 2,
        "upload": 2,
        "status": 2,
        "publish": 0,
        "create_carousel": 0,
    }

    await h.advance(attempt_id)
    assert h.client.calls == {
        "create": 2,
        "upload": 2,
        "status": 2,
        "publish": 0,
        "create_carousel": 1,
    }

    final = await h.advance(attempt_id)
    assert final.settled and final.status == "published"
    assert h.client.calls == {
        "create": 2,
        "upload": 2,
        "status": 3,
        "publish": 1,
        "create_carousel": 1,
    }


@pytest.mark.asyncio
async def test_failing_child_upload_settles_the_attempt_never_touching_later_children() -> None:
    h = Harness()
    items = h.stage_videos(2)
    h.client.upload_outcome = UploadOutcome(success=False, retriable=False, error_type="boom")
    start_state = await h.start_many(items)

    state = await h.advance(start_state.attempt_id)  # creates+uploads child 0, fails

    assert state.settled and state.status == "failed"
    assert state.reason == f"{CHILD_ERROR_PREFIX}:boom"
    assert h.client.calls["create"] == 1  # child 1 was never even created
    children = h.repo.list_children(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert children[0].status == "failed" and children[0].platform_error_code == "boom"
    assert children[1].status == "pending"  # untouched, and that is fine — nothing published


@pytest.mark.asyncio
async def test_a_child_container_error_status_settles_the_whole_attempt() -> None:
    h = Harness()
    items = h.stage_videos(2)
    start_state = await h.start_many(items)
    await h.advance(start_state.attempt_id)  # create+upload child 0
    await h.advance(start_state.attempt_id)  # create+upload child 1
    h.client.status_script = [ContainerStatus.ERROR]

    state = await h.advance(start_state.attempt_id)  # poll child 0 -> ERROR

    assert state.settled and state.status == "failed"
    assert state.reason == f"{CHILD_ERROR_PREFIX}:container_error"
    assert h.client.calls["create_carousel"] == 0  # never reached


@pytest.mark.asyncio
async def test_carousel_creation_failure_propagates_and_is_safely_retryable() -> None:
    """Same posture start()'s own create_container call takes: a PublishError here
    PROPAGATES rather than being caught and settled — the row stays unsettled with
    creation_id still None, so a later advance() call retries it."""
    h = Harness()
    items = h.stage_videos(2)
    h.client.status_script = [ContainerStatus.FINISHED, ContainerStatus.FINISHED]
    start_state = await h.start_many(items)
    await h.advance(start_state.attempt_id)  # create+upload child 0
    await h.advance(start_state.attempt_id)  # create+upload child 1
    await h.advance(start_state.attempt_id)  # poll child 0 -> finished
    await h.advance(start_state.attempt_id)  # poll child 1 -> finished

    h.client.carousel_error = PublishError("POST /media failed with HTTP 500")
    with pytest.raises(PublishError):
        await h.advance(start_state.attempt_id)  # attempts to create the CAROUSEL, fails

    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert record is not None and record.creation_id is None and not record.is_settled

    h.client.carousel_error = None
    h.client.status_script = [ContainerStatus.FINISHED]
    state = await h.advance(start_state.attempt_id)  # retried -> succeeds this time

    assert not state.settled  # carousel created, now (still) polling
    record2 = h.repo.get_attempt(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert record2.creation_id == "carousel-1"
    assert h.client.calls["create_carousel"] == 2  # the failed attempt + the retry


@pytest.mark.asyncio
async def test_start_many_retry_after_a_partial_write_ahead_converges_without_duplicates() -> None:
    """Simulates a crash mid-loop inside start_many (only position 0 got written before
    the process died). A retry with the SAME idempotency_key and the full item list must
    converge to exactly N children, never duplicate the ones already there."""
    h = Harness()
    items = h.stage_videos(3)
    key = "op-crash-1"

    pre_start = h.repo.start_attempt(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        idempotency_key=key,
        media_product_type="CAROUSEL",
        adapter_version="v1",
    )
    h.repo.add_child(
        tenant_id=TENANT,
        attempt_id=pre_start.record.id,
        position=0,
        media_object_key=items[0].media_object_key,
        media_content_type=items[0].content_type,
        media_product_type="VIDEO",
    )
    assert len(h.repo.list_children(tenant_id=TENANT, attempt_id=pre_start.record.id)) == 1

    state = await h.start_many(items, key=key)  # the caller retries the WHOLE call

    assert state.attempt_id == pre_start.record.id  # same attempt, not a new one
    children = h.repo.list_children(tenant_id=TENANT, attempt_id=state.attempt_id)
    assert [c.position for c in children] == [0, 1, 2]
    assert len(h.repo.children) == 3  # not 4


@pytest.mark.asyncio
async def test_start_many_is_idempotent_by_key() -> None:
    h = Harness()
    items = h.stage_videos(2)
    first = await h.start_many(items, key="same-key")
    second = await h.start_many(items, key="same-key")
    assert first.attempt_id == second.attempt_id
    assert len(h.repo.rows) == 1
    assert len(h.repo.children) == 2  # not 4


@pytest.mark.asyncio
async def test_carousel_publish_ambiguity_reuses_publish_once_and_never_resends() -> None:
    """The A6-min guarantee, exercised through the carousel path — this exercises ZERO
    new send-side code: `_publish_once` is reached the same way, via the same
    FINISHED-and-not-sent branch, using whatever `creation_id` currently sits on the row
    (here, the CAROUSEL's, not a child's)."""
    h = Harness()
    items = h.stage_videos(2)
    h.client.status_script = [ContainerStatus.FINISHED] * 3
    h.client.publish_error = TimeoutError("read timeout after the request went out")
    start_state = await h.start_many(items)
    attempt_id = start_state.attempt_id
    for _ in range(5):  # create+upload x2, poll x2, create the carousel
        await h.advance(attempt_id)

    state = await h.advance(attempt_id)  # poll carousel -> FINISHED -> _publish_once -> timeout

    assert not state.settled and state.awaiting_confirmation
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=attempt_id)
    assert record is not None and record.platform_error_code == PUBLISH_SENT_MARKER
    assert h.client.calls["publish"] == 1

    h.client.status_script = [ContainerStatus.FINISHED]  # the container may still lag
    state2 = await h.advance(attempt_id)
    assert h.client.calls["publish"] == 1  # zero NEW sends
    assert not state2.settled and state2.awaiting_confirmation


@pytest.mark.asyncio
async def test_carousel_children_are_sent_to_meta_in_position_order() -> None:
    h = Harness()
    items = h.stage_videos(3)
    h.client.status_script = [ContainerStatus.FINISHED] * 4
    start_state = await h.start_many(items)
    await h.drive_to_settled(start_state.attempt_id)
    assert h.client.carousel_calls == [["child-c-0", "child-c-1", "child-c-2"]]


@pytest.mark.asyncio
async def test_carousel_children_use_video_media_type_with_is_carousel_item() -> None:
    h = Harness()
    items = h.stage_videos(2)
    start_state = await h.start_many(items)
    await h.advance(start_state.attempt_id)
    await h.advance(start_state.attempt_id)
    assert len(h.client.create_container_calls) == 2
    for call in h.client.create_container_calls:
        assert call["media_type"] == "VIDEO"
        assert call["is_carousel_item"] is True


@pytest.mark.asyncio
async def test_parent_media_product_type_is_carousel_only_for_multi_item() -> None:
    h = Harness()
    single = await h.start()
    single_record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=single.attempt_id)
    assert single_record is not None and single_record.media_product_type == "REELS"

    h2 = Harness()
    items = h2.stage_videos(2)
    multi = await h2.start_many(items)
    multi_record = h2.repo.get_attempt(tenant_id=TENANT, attempt_id=multi.attempt_id)
    assert multi_record is not None and multi_record.media_product_type == "CAROUSEL"


@pytest.mark.asyncio
async def test_ceiling_does_not_fire_prematurely_for_a_ten_item_carousel() -> None:
    """300 s alone (the single-video ceiling) would already be exceeded here — the scaled
    ceiling (300 * (10 + 1) = 3300 s) must not fire at 1000 s elapsed."""
    h = Harness(clock_offset_seconds=1000)
    items = h.stage_videos(10)
    start_state = await h.start_many(items)
    state = await h.advance(start_state.attempt_id)
    assert not state.settled
    assert state.reason != CEILING_EXCEEDED
    assert h.client.calls["create"] == 1  # real progress happened, not a ceiling bail-out


@pytest.mark.asyncio
async def test_ceiling_still_fires_once_truly_exceeded_for_a_ten_item_carousel() -> None:
    h = Harness(clock_offset_seconds=4000)  # > 300 * 11 = 3300 s
    items = h.stage_videos(10)
    start_state = await h.start_many(items)
    state = await h.advance(start_state.attempt_id)
    assert state.settled and state.status == "failed"
    assert state.reason == CEILING_EXCEEDED


@pytest.mark.asyncio
async def test_single_video_ceiling_is_unaffected_by_the_carousel_scaling() -> None:
    """The same 400 s offset that fails a single video today
    (test_ceiling_settles_failed_distinguishably_from_a_container_error) must behave
    IDENTICALLY after QUA-99 (4/6) — media_product_type='REELS' never enters the CAROUSEL
    branch of `_over_ceiling`."""
    h = Harness(clock_offset_seconds=400)
    attempt_id = await _started(h)
    h.client.status_script = [ContainerStatus.IN_PROGRESS]
    state = await h.advance(attempt_id)
    assert state.settled and state.status == "failed" and state.reason == CEILING_EXCEEDED


# --------------------------------------------------------------------------------------
# QUA-99 (4.5/6) — carousel caption persistence
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_many_persists_the_caption_on_the_parent_attempt() -> None:
    h = Harness()
    items = h.stage_videos(2)
    state = await h.start_many(items, caption="hola carrusel")
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=state.attempt_id)
    assert record is not None and record.caption == "hola carrusel"


@pytest.mark.asyncio
async def test_start_many_without_a_caption_keeps_it_null() -> None:
    h = Harness()
    items = h.stage_videos(2)
    state = await h.start_many(items)
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=state.attempt_id)
    assert record is not None and record.caption is None


@pytest.mark.asyncio
async def test_create_carousel_sends_the_persisted_caption_to_meta() -> None:
    h = Harness()
    items = h.stage_videos(2)
    h.client.status_script = [ContainerStatus.FINISHED, ContainerStatus.FINISHED]
    start_state = await h.start_many(items, caption="una descripcion real")
    for _ in range(4):  # create+upload x2, poll x2
        await h.advance(start_state.attempt_id)

    await h.advance(start_state.attempt_id)  # creates the CAROUSEL container

    assert h.client.carousel_caption_calls == ["una descripcion real"]


@pytest.mark.asyncio
async def test_caption_survives_from_start_many_through_multiple_advance_calls() -> None:
    """The whole reason this column exists: the caption must still be there several
    advance() calls after start_many() returned, none of which ever touch it."""
    h = Harness()
    items = h.stage_videos(2)
    h.client.status_script = [ContainerStatus.IN_PROGRESS, ContainerStatus.IN_PROGRESS]
    start_state = await h.start_many(items, caption="persistent caption")

    for _ in range(4):  # create+upload x2, poll x2 — none of these write caption
        await h.advance(start_state.attempt_id)
        record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=start_state.attempt_id)
        assert record is not None and record.caption == "persistent caption"


@pytest.mark.asyncio
async def test_start_many_retry_same_key_no_second_parent_no_corrupted_caption() -> None:
    h = Harness()
    items = h.stage_videos(2)
    first = await h.start_many(items, key="same-key", caption="original caption")
    second = await h.start_many(items, key="same-key", caption="a different caption, ignored")

    assert first.attempt_id == second.attempt_id
    assert len(h.repo.rows) == 1
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=first.attempt_id)
    # Same idempotency semantics start_attempt already has for every other field: the
    # SECOND call's caption is not applied, exactly like a second call with a different
    # media_object_key would not re-stage anything either.
    assert record is not None and record.caption == "original caption"


@pytest.mark.asyncio
async def test_single_video_caption_still_flows_directly_through_start_unchanged() -> None:
    """start() is UNCHANGED by QUA-99 (4.5/6) — caption still travels ONLY as a
    parameter straight into create_container(), and the new column stays NULL for this
    path: single-video does not depend on it in any way."""
    h = Harness()
    state = await h.service.start(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_object_key=h.media_key,
        media_product_type="REELS",
        idempotency_key="op-cap-1",
        caption="video caption",
    )
    assert h.client.create_container_calls[-1]["caption"] == "video caption"
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=state.attempt_id)
    assert record is not None and record.caption is None


@pytest.mark.asyncio
async def test_start_many_with_one_item_forwards_caption_to_start() -> None:
    """The 1-item delegation branch of start_many must not silently drop a caption the
    caller supplied — same posture as every other field it forwards unchanged."""
    h = Harness()
    items = h.stage_videos(1)
    await h.start_many(items, caption="single item caption")
    assert h.client.create_container_calls[-1]["caption"] == "single item caption"


# --------------------------------------------------------------------------------------
# Static shields
# --------------------------------------------------------------------------------------


def test_nothing_in_publishing_sleeps() -> None:
    """The poll is CLIENT-driven; a sleep in this package is a five-minute HTTP request."""
    for source_file in PUBLISHING_SRC.glob("*.py"):
        source = source_file.read_text()
        assert "asyncio.sleep" not in source, source_file.name
        assert "time.sleep" not in source, source_file.name


def test_nothing_in_publishing_builds_its_own_http_client() -> None:
    """Clients arrive through the credential resolver seam; a second `httpx.AsyncClient(`
    construction would be a second door past the credential gate."""
    for source_file in PUBLISHING_SRC.glob("*.py"):
        assert "AsyncClient(" not in source_file.read_text(), source_file.name
