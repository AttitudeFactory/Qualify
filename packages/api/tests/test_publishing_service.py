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
    CONNECTION_NOT_ACTIVE_PREFIX,
    PUBLISH_SENT_MARKER,
    ConnectionTarget,
    PublishService,
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
        self.create_error: Exception | None = None
        self.upload_outcome = UploadOutcome(success=True)
        self.status_script: list[ContainerStatus] = []
        self.status_error: Exception | None = None
        self.publish_error: Exception | None = None
        self.publish_media_id = "media-1"
        self.calls = {"create": 0, "upload": 0, "status": 0, "publish": 0}
        self.upload_sizes: list[int] = []

    async def create_container(self, **kwargs: object) -> ResumableContainer:
        self.calls["create"] += 1
        if self.create_error is not None:
            raise self.create_error
        return self.container

    async def upload_bytes(self, *, upload_uri: str, fileobj, file_size: int) -> UploadOutcome:
        self.calls["upload"] += 1
        self.upload_sizes.append(file_size)
        return self.upload_outcome

    async def container_status(self, *, container_id: str) -> ContainerStatus:
        self.calls["status"] += 1
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
    assert h.client.calls == {"create": 0, "upload": 0, "status": 0, "publish": 0}


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
