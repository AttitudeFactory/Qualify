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
    CONTAINER_POLL_INTERVAL_SECONDS,
    MEDIA_TYPE_IMAGE,
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
    MissingMediaLinker,
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
        # QUA-99 latency follow-up: parallel to `container_sequence`/`upload_outcomes`
        # below, popped in the SAME call order (position order, since children upload
        # concurrently via asyncio.gather and this fake never actually awaits real I/O,
        # so calls complete in the order they were scheduled) — lets a test make ONE
        # specific child in a concurrent batch fail while its siblings succeed. `None`
        # (the default) preserves every pre-existing test's behaviour byte-for-byte.
        self.create_errors: list[Exception | None] | None = None
        self.upload_outcome = UploadOutcome(success=True)
        self.upload_outcomes: list[UploadOutcome] | None = None
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
        # QUA-68 — image container creation, deliberately tracked OUTSIDE `self.calls`
        # (never added as a `"create_image"` key there): several existing tests assert
        # `h.client.calls == {...}` by exact dict equality, and adding a key would break
        # every one of them for a reason that has nothing to do with what they test. This
        # list is exactly as inspectable — `len(image_container_calls)` is the count.
        self.image_container_id = "image-container-1"
        self.create_image_error: Exception | None = None
        self.image_container_calls: list[dict[str, str]] = []
        self.calls = {"create": 0, "upload": 0, "status": 0, "publish": 0, "create_carousel": 0}
        self.upload_sizes: list[int] = []

    async def create_container(self, **kwargs: object) -> ResumableContainer:
        self.calls["create"] += 1
        self.create_container_calls.append(kwargs)
        if self.create_errors:
            error = self.create_errors.pop(0)
            if error is not None:
                raise error
        elif self.create_error is not None:
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

    async def create_image_container(
        self, *, ig_user_id: str, image_url: str, caption: str | None = None
    ) -> str:
        self.image_container_calls.append({"ig_user_id": ig_user_id, "image_url": image_url})
        if self.create_image_error is not None:
            raise self.create_image_error
        return self.image_container_id

    async def upload_bytes(self, *, upload_uri: str, fileobj, file_size: int) -> UploadOutcome:
        self.calls["upload"] += 1
        self.upload_sizes.append(file_size)
        if self.upload_outcomes:
            return self.upload_outcomes.pop(0)
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


class FakeMediaLinker:
    """QUA-68 — records every `link()` call so a test can assert exactly which
    `(tenant_id, object_key, content_type)` was minted into a public URL, and returns a
    deterministic, inspectable URL rather than a real token."""

    def __init__(self) -> None:
        self.link_calls: list[dict[str, object]] = []

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        self.link_calls.append(
            {"tenant_id": tenant_id, "object_key": object_key, "content_type": content_type}
        )
        return f"https://qualify.example/public/media/tok-for-{object_key.rsplit('/', 1)[-1]}"


class Harness:
    def __init__(
        self,
        *,
        connection_status: str = "active",
        clock_offset_seconds: float = 0.0,
        media_linker: FakeMediaLinker | None = None,
    ) -> None:
        self.repo = MemoryPublishAttemptRepository()
        self.store = MemoryStore()
        self.client = FakePublishClient()
        # QUA-68 — a real fake by default (never `None`) so every pre-existing VIDEO test
        # keeps working unchanged AND any future test can still assert on `self.linker`
        # without needing to remember to pass one in.
        self.linker = media_linker if media_linker is not None else FakeMediaLinker()
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
            media_linker=self.linker,
        )
        self.media_key = f"t/{TENANT}/media/{CONNECTION}/m-1"
        self.store.objects[self.media_key] = (b"reel-bytes", "video/mp4")
        self.image_key = f"t/{TENANT}/media/{CONNECTION}/img-1"
        self.store.objects[self.image_key] = (b"\xff\xd8\xff\xe0jpeg-bytes", "image/jpeg")

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

    # --- QUA-68: single-image helper ---

    async def start_image(self, key: str = "op-img-1", *, content_type: str | None = "image/jpeg"):
        return await self.service.start(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_object_key=self.image_key,
            media_product_type=MEDIA_TYPE_IMAGE,
            idempotency_key=key,
            content_type=content_type,
        )

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
async def test_advance_batches_all_pending_or_in_flight_children_per_call() -> None:
    """QUA-99 latency follow-up: a call no longer advances ONE child at a time — every
    PENDING child uploads CONCURRENTLY in one call (`asyncio.gather`), then every
    IN-FLIGHT child polls concurrently in the next. What used to be six calls for a
    2-item carousel (create+upload child0, create+upload child1, poll child0, poll
    child1, create the CAROUSEL, poll it and publish) is now four: create+upload BOTH,
    poll BOTH, create the CAROUSEL, poll it and publish."""
    h = Harness()
    items = h.stage_videos(2)
    h.client.status_script = [ContainerStatus.FINISHED] * 3
    start_state = await h.start_many(items)
    attempt_id = start_state.attempt_id

    await h.advance(attempt_id)  # create+upload BOTH children concurrently
    assert h.client.calls == {
        "create": 2,
        "upload": 2,
        "status": 0,
        "publish": 0,
        "create_carousel": 0,
    }

    await h.advance(attempt_id)  # poll BOTH children concurrently
    assert h.client.calls == {
        "create": 2,
        "upload": 2,
        "status": 2,
        "publish": 0,
        "create_carousel": 0,
    }

    await h.advance(attempt_id)  # create the CAROUSEL container
    assert h.client.calls == {
        "create": 2,
        "upload": 2,
        "status": 2,
        "publish": 0,
        "create_carousel": 1,
    }

    final = await h.advance(attempt_id)  # poll carousel -> FINISHED -> publish
    assert final.settled and final.status == "published"
    assert h.client.calls == {
        "create": 2,
        "upload": 2,
        "status": 3,
        "publish": 1,
        "create_carousel": 1,
    }


@pytest.mark.asyncio
async def test_failing_child_upload_settles_the_attempt() -> None:
    """QUA-99 latency follow-up: pending children upload CONCURRENTLY now, so a failing
    upload no longer guarantees a sibling was 'never even created' — both are attempted
    in the SAME batch (this fake's `upload_outcome` applies to every call alike). What
    still holds, unchanged: the parent settles failed, and nothing ever reaches
    media_publish."""
    h = Harness()
    items = h.stage_videos(2)
    h.client.upload_outcome = UploadOutcome(success=False, retriable=False, error_type="boom")
    start_state = await h.start_many(items)

    state = await h.advance(start_state.attempt_id)  # creates+uploads BOTH, both fail

    assert state.settled and state.status == "failed"
    assert state.reason == f"{CHILD_ERROR_PREFIX}:boom"
    assert h.client.calls["create"] == 2  # both attempted concurrently
    children = h.repo.list_children(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert all(c.status == "failed" and c.platform_error_code == "boom" for c in children)
    assert h.client.calls["publish"] == 0


@pytest.mark.asyncio
async def test_one_child_failing_does_not_stop_a_sibling_from_advancing_in_the_same_batch() -> None:
    """QUA-99 latency follow-up, the concurrency-specific case this PR exists for: child
    0's upload fails while child 1's succeeds, in the SAME concurrent batch. Both are
    still genuinely attempted (`return_exceptions=True` lets every task in the gather
    finish on its own); the parent settles failed using child 0's error; child 1's own
    row still records what actually happened to it (uploaded successfully), never
    silently discarded just because a sibling failed."""
    h = Harness()
    items = h.stage_videos(2)
    h.client.upload_outcomes = [
        UploadOutcome(success=False, retriable=False, error_type="boom"),
        UploadOutcome(success=True),
    ]
    start_state = await h.start_many(items)

    state = await h.advance(start_state.attempt_id)

    assert state.settled and state.status == "failed"
    assert state.reason == f"{CHILD_ERROR_PREFIX}:boom"
    children = h.repo.list_children(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert children[0].status == "failed" and children[0].platform_error_code == "boom"
    assert children[1].status == "processing"  # genuinely uploaded, not skipped
    assert h.client.calls["publish"] == 0


@pytest.mark.asyncio
async def test_a_child_container_error_status_settles_the_whole_attempt() -> None:
    h = Harness()
    items = h.stage_videos(2)
    start_state = await h.start_many(items)
    await h.advance(start_state.attempt_id)  # create+upload BOTH children concurrently
    h.client.status_script = [ContainerStatus.ERROR, ContainerStatus.FINISHED]

    state = await h.advance(start_state.attempt_id)  # poll BOTH: child 0 -> ERROR

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
    await h.advance(start_state.attempt_id)  # create+upload BOTH children concurrently
    await h.advance(start_state.attempt_id)  # poll BOTH children concurrently -> finished

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
    for _ in range(3):  # create+upload BOTH, poll BOTH, create the carousel
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
    await h.advance(start_state.attempt_id)  # create+upload BOTH children concurrently
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
    # QUA-99 latency follow-up: ALL 10 pending children upload concurrently in this one
    # call now, not just the first — real progress happened, not a ceiling bail-out.
    assert h.client.calls["create"] == 10


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
# QUA-99 latency follow-up — concurrent children (position mapping + error propagation)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_child_uploads_preserve_position_to_container_id_mapping() -> None:
    """QUA-99 latency follow-up: with every pending child uploading CONCURRENTLY in one
    call, each child's OWN creation_id must land on its OWN row — never swapped because
    two coroutines happened to interleave. Exercised with 4 children (more than 2, so a
    naive off-by-one swap would actually show up) and confirmed all the way through to
    what Meta receives for the CAROUSEL itself."""
    h = Harness()
    items = h.stage_videos(4)
    h.client.status_script = [ContainerStatus.FINISHED] * 5  # 4 children + the carousel
    start_state = await h.start_many(items)

    await h.advance(start_state.attempt_id)  # create+upload all 4 children concurrently

    children = h.repo.list_children(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert [(c.position, c.creation_id) for c in children] == [
        (0, "child-c-0"),
        (1, "child-c-1"),
        (2, "child-c-2"),
        (3, "child-c-3"),
    ]

    final = await h.drive_to_settled(start_state.attempt_id)
    assert final.settled and final.status == "published"
    assert h.client.carousel_calls == [["child-c-0", "child-c-1", "child-c-2", "child-c-3"]]


@pytest.mark.asyncio
async def test_one_child_create_container_error_propagates_and_preserves_the_sibling() -> None:
    """A `PublishError` from ONE child's `create_container`, concurrent with a sibling
    that succeeds, still PROPAGATES — same posture the sequential path always had (see
    `test_carousel_creation_failure_propagates_and_is_safely_retryable`) — and does NOT
    cancel or lose the sibling's already-successful work: a retry only needs to redo the
    failed child (its `creation_id` is still `None`), never re-uploading the one that
    already has one."""
    h = Harness()
    items = h.stage_videos(2)
    h.client.create_errors = [PublishError("POST /media failed with HTTP 500"), None]
    h.client.container_sequence = [
        ResumableContainer(container_id="child-c-1", upload_uri="https://rupload/1")
    ]
    start_state = await h.start_many(items)

    with pytest.raises(PublishError):
        await h.advance(start_state.attempt_id)

    children = h.repo.list_children(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert children[0].creation_id is None  # failed -- retries on the next tick
    assert children[1].creation_id == "child-c-1"  # the sibling's success was NOT lost
    assert children[1].status == "processing"
    record = h.repo.get_attempt(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert record is not None and not record.is_settled  # PROPAGATES, never settled here

    # Retried: only child 0 is still pending, child 1 is left alone.
    h.client.create_errors = None
    h.client.container_sequence = [
        ResumableContainer(container_id="child-c-0", upload_uri="https://rupload/0")
    ]
    await h.advance(start_state.attempt_id)
    assert h.client.calls["create"] == 3  # 2 attempted + 1 retry, never a needless re-upload
    children2 = h.repo.list_children(tenant_id=TENANT, attempt_id=start_state.attempt_id)
    assert children2[0].creation_id == "child-c-0"
    assert children2[1].creation_id == "child-c-1"  # untouched by the retry


# --------------------------------------------------------------------------------------
# QUA-99 latency follow-up — carousel poll backoff (INERT for single-video attempts)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_interval_starts_fast_for_a_fresh_carousel() -> None:
    h = Harness()
    items = h.stage_videos(2)
    h.client.status_script = [ContainerStatus.IN_PROGRESS, ContainerStatus.IN_PROGRESS]
    start_state = await h.start_many(items)
    await h.advance(start_state.attempt_id)  # create+upload BOTH children concurrently

    state = await h.advance(start_state.attempt_id)  # poll BOTH -- still IN_PROGRESS

    assert not state.settled
    assert state.poll_interval_seconds == 5


@pytest.mark.asyncio
async def test_poll_interval_reaches_the_old_steady_state_after_75s() -> None:
    """Never slower than the original fixed cadence every attempt used before this
    follow-up — the backoff only ever makes the EARLY checks faster."""
    h = Harness(clock_offset_seconds=80)
    items = h.stage_videos(2)
    h.client.status_script = [ContainerStatus.IN_PROGRESS, ContainerStatus.IN_PROGRESS]
    start_state = await h.start_many(items)
    await h.advance(start_state.attempt_id)

    state = await h.advance(start_state.attempt_id)

    assert not state.settled
    assert state.poll_interval_seconds == CONTAINER_POLL_INTERVAL_SECONDS


@pytest.mark.asyncio
async def test_poll_interval_is_unaffected_for_a_single_video() -> None:
    """INERT for a single video — media_product_type is never CAROUSEL for that path, so
    it must keep advertising the exact same fixed cadence it always has."""
    h = Harness()
    state = await h.start()
    h.client.status_script = [ContainerStatus.IN_PROGRESS]

    polled = await h.advance(state.attempt_id)

    assert not polled.settled
    assert polled.poll_interval_seconds == CONTAINER_POLL_INTERVAL_SECONDS


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
    await h.advance(start_state.attempt_id)  # create+upload BOTH children concurrently
    await h.advance(start_state.attempt_id)  # poll BOTH children concurrently -> finished

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

    # QUA-99 latency follow-up: create+upload BOTH concurrently, then poll BOTH
    # concurrently — two calls now, not four; neither ever writes caption.
    for _ in range(2):
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
# QUA-99 UX follow-up — list_children_status, a READ-ONLY carousel-progress projection
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_children_status_reflects_a_mixed_in_progress_carousel() -> None:
    """The exact shape a polling UI needs: which position is finished vs still moving,
    read at a point mid-assembly — proves this is a live read of `list_children`, not a
    snapshot taken once at `start_many` time.

    QUA-99 latency follow-up: children now poll CONCURRENTLY in one call, so 'mixed'
    here means Meta itself reporting different statuses for each child in the SAME
    batch — not one child getting ahead of another because of sequential ticks."""
    h = Harness()
    items = h.stage_videos(2)
    h.client.status_script = [ContainerStatus.FINISHED, ContainerStatus.IN_PROGRESS]
    start_state = await h.start_many(items)

    await h.advance(start_state.attempt_id)  # create+upload BOTH children concurrently
    await h.advance(start_state.attempt_id)  # poll BOTH concurrently: 0->finished, 1->still going

    rows = h.service.list_children_status(tenant_id=TENANT, attempt_id=start_state.attempt_id)

    assert [(r.position, r.status) for r in rows] == [(0, "finished"), (1, "processing")]


@pytest.mark.asyncio
async def test_list_children_status_never_calls_the_platform() -> None:
    """A pure Postgres/memory read — asserted the same way A6-min's own zero-calls
    properties are, via the client's own call counters."""
    h = Harness()
    items = h.stage_videos(2)
    start_state = await h.start_many(items)
    before = dict(h.client.calls)

    h.service.list_children_status(tenant_id=TENANT, attempt_id=start_state.attempt_id)

    assert h.client.calls == before


def test_list_children_status_is_empty_for_an_unknown_attempt() -> None:
    """Same posture `list_children` itself already has for a nonexistent attempt_id — an
    empty list, not an exception; the caller (a polling UI) should never need a
    try/except around a display-only read."""
    h = Harness()
    rows = h.service.list_children_status(tenant_id=TENANT, attempt_id=uuid4())
    assert rows == []


# --------------------------------------------------------------------------------------
# IMAGE (QUA-68) — single image, no carousel, no upload phase
# --------------------------------------------------------------------------------------


class _StatusSpyRepository(MemoryPublishAttemptRepository):
    """Wraps `advance_status` to record every status ever written — the only way to
    PROVE `'uploading'` is never reached for IMAGE, as opposed to merely observing the
    final state (which could coincidentally look right even if `'uploading'` flashed by
    unobserved between two `advance_status` calls in a differently-shaped bug)."""

    def __init__(self) -> None:
        super().__init__()
        self.statuses_written: list[str] = []

    def advance_status(self, *, tenant_id: UUID, attempt_id: UUID, status: str) -> None:
        self.statuses_written.append(status)
        super().advance_status(tenant_id=tenant_id, attempt_id=attempt_id, status=status)


async def test_start_image_creates_an_image_container_and_skips_upload() -> None:
    h = Harness()

    state = await h.start_image()

    assert state.status == "processing"
    assert not state.settled
    assert len(h.client.image_container_calls) == 1
    assert h.client.calls["create"] == 0  # create_container (VIDEO) never called
    assert h.client.calls["upload"] == 0  # upload_bytes never called — nothing to upload


async def test_start_image_never_writes_status_uploading() -> None:
    """The direct proof, via a spy on every `advance_status` call — not an inference from
    the final state alone."""
    repo = _StatusSpyRepository()
    linker = FakeMediaLinker()
    client = FakePublishClient()
    store = MemoryStore()
    store.objects[f"t/{TENANT}/media/{CONNECTION}/img-1"] = (b"jpeg-bytes", "image/jpeg")

    class Connections:
        def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
            return ConnectionTarget(ig_user_id=IG_USER, status="active")

    class Factory:
        async def client_for(self, *, tenant_id: UUID, connection_id: UUID):
            return client

    service = PublishService(
        repository=repo,
        gate=ObjectGate(store),
        connections=Connections(),
        client_factory=Factory(),
        media_linker=linker,
    )

    await service.start(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_object_key=f"t/{TENANT}/media/{CONNECTION}/img-1",
        media_product_type=MEDIA_TYPE_IMAGE,
        idempotency_key="op-img-spy",
        content_type="image/jpeg",
    )

    assert "uploading" not in repo.statuses_written
    assert repo.statuses_written == ["processing"]


async def test_start_image_requires_content_type() -> None:
    h = Harness()

    with pytest.raises(ValueError, match="content_type"):
        await h.start_image(content_type=None)


async def test_start_image_requires_a_configured_media_linker() -> None:
    """A `PublishService` built WITHOUT `media_linker` (every pre-QUA-68 construction site,
    and every test in this file that does not explicitly pass one) must fail loudly and
    distinguishably the moment an IMAGE attempt actually needs it — never fall through to
    the video branch (which would send `media_type='IMAGE'` to `create_container`, a
    request `client.py` already refuses for an unrelated reason)."""
    repo = MemoryPublishAttemptRepository()
    client = FakePublishClient()
    store = MemoryStore()
    store.objects[f"t/{TENANT}/media/{CONNECTION}/img-1"] = (b"jpeg-bytes", "image/jpeg")

    class Connections:
        def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
            return ConnectionTarget(ig_user_id=IG_USER, status="active")

    class Factory:
        async def client_for(self, *, tenant_id: UUID, connection_id: UUID):
            return client

    service = PublishService(
        repository=repo, gate=ObjectGate(store), connections=Connections(), client_factory=Factory()
    )  # no media_linker passed — the default

    with pytest.raises(MissingMediaLinker):
        await service.start(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_object_key=f"t/{TENANT}/media/{CONNECTION}/img-1",
            media_product_type=MEDIA_TYPE_IMAGE,
            idempotency_key="op-img-no-linker",
            content_type="image/jpeg",
        )
    assert client.image_container_calls == []  # refused before any platform call


async def test_start_image_mints_the_public_link_with_the_staged_content_type() -> None:
    h = Harness()

    await h.start_image(content_type="image/jpeg")

    assert len(h.linker.link_calls) == 1
    call = h.linker.link_calls[0]
    assert call["tenant_id"] == TENANT
    assert call["object_key"] == h.image_key
    assert call["content_type"] == "image/jpeg"


async def test_start_image_sends_the_minted_url_to_meta() -> None:
    h = Harness()

    await h.start_image()

    [call] = h.client.image_container_calls
    assert call["image_url"] == "https://qualify.example/public/media/tok-for-img-1"
    assert call["ig_user_id"] == IG_USER


async def test_start_image_propagates_a_create_image_container_error() -> None:
    """Same posture the VIDEO branch's own `create_container` call already has: the
    write-ahead row survives in 'pending', and the exception propagates rather than
    being swallowed into a generic failure."""
    h = Harness()
    h.client.create_image_error = PublishError("boom")

    with pytest.raises(PublishError, match="boom"):
        await h.start_image()


async def test_image_attempt_settles_through_the_unmodified_advance_machinery() -> None:
    """The property that matters most: `advance()`/`_publish_once`/reconciliation are
    UNTOUCHED by QUA-68 — an image attempt, once it has a `creation_id`, is polled and
    published by exactly the same code a video attempt already uses."""
    h = Harness()
    start_state = await h.start_image()
    h.client.status_script = [ContainerStatus.FINISHED]

    final = await h.drive_to_settled(start_state.attempt_id)

    assert final.settled
    assert final.status == "published"
    assert final.published_media_id == h.client.publish_media_id
    assert h.client.calls["publish"] == 1


async def test_video_publish_never_touches_the_media_linker() -> None:
    """The other direction of the same regression guard: a completely ordinary VIDEO
    `start()` call must never mint a public link — that machinery is IMAGE-only."""
    h = Harness()

    await h.start()

    assert h.linker.link_calls == []


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
