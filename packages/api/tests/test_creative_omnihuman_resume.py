"""m-24852495: a talking presenter whose OmniHuman render outlives the wait is kept by id
and resumed — never submitted twice, never lost while BytePlus bills it, and the resumed
run pays neither the presenter photo nor the voice again. The media producer's side,
offline (a scripted OmniHuman behind the real router).

The service and database side (draft left in progress, resumed, settled once, refunds,
tenant isolation) are in `test_creative_omnihuman_resume_db.py`."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from qualify_creative.adapters.byteplus_omnihuman import RESUME_TASK_PARAM
from qualify_creative.enums import FailureReason, GenerationTask
from qualify_creative.providers import GenerationRequest, GenerationResult, Usage
from qualify_creative.router import BudgetContext

from qualify_api.creative.media import (
    PRESENTER_CONTEXT,
    PRESENTER_SLOW_TEXT,
    MediaOutcome,
    MediaProducer,
    generated_key,
)

from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    PUBLIC_VOICE,
    TENANT_ID,
    FakeLinks,
    FakeSeedream,
    FakeSpeech,
    _kit,
    _presenter,
    _presenter_brief,
    _store,
)

OMNI_MODEL = "omnihuman-1-5"


class Book:
    """A `VendorTaskBinding` in memory: what the service hands the producer."""

    def __init__(
        self,
        known: Mapping[str, str] | None = None,
        contexts: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.known = dict(known or {})
        self.contexts = dict(contexts or {})
        self.recorded: list[tuple[str, str, str, str]] = []
        self.settled: list[tuple[str, str]] = []

    def resume_id(self, slot: str) -> str | None:
        return self.known.get(slot)

    def resume_context(self, slot: str) -> Mapping[str, Any] | None:
        return self.contexts.get(slot)

    def observer(
        self,
        slot: str,
        provider: str,
        model_id: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> Any:
        book = self

        class _Obs:
            def created(self, task_id: str) -> None:
                book.known[slot] = task_id
                book.contexts[slot] = dict(context or {})
                book.recorded.append((slot, provider, model_id, task_id))

            def polled(self, task_id: str, status: str) -> None:
                return None

        return _Obs()

    def settle(self, slot: str, status: str) -> None:
        self.settled.append((slot, status))

    def carried(self) -> Book:
        """What the next run reads back: the same ids and contexts, nothing recorded."""
        return Book(known=self.known, contexts=self.contexts)


class QueuedOmniHuman:
    """OmniHuman whose new renders outlive the wait: the submit is accepted (its id is
    heard), then the adapter stops waiting. A resumed task answers `resumed`."""

    name = "omnihuman"
    supports = frozenset({GenerationTask.AVATAR_VIDEO})

    def __init__(self, *, resumed: str = "done") -> None:
        self.resumed = resumed
        self.created = 0
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.requests.append(request)
        resume = request.params.get(RESUME_TASK_PARAM)
        if resume is None:
            self.created += 1
            task_id = f"oh-{self.created}"
            if request.observer is not None:
                request.observer.created(task_id)
            raise RuntimeError(f"OmniHumanTimeout: OmniHuman task {task_id} still in_queue")
        if self.resumed == "queued":
            raise RuntimeError(f"OmniHumanTimeout: OmniHuman task {resume} still in_queue")
        if self.resumed == "expired":
            raise RuntimeError(f"OmniHumanTaskFailed: OmniHuman task {resume} expired")
        return GenerationResult(
            payload={
                "task_id": resume,
                "req_key": "realman_avatar_picture_omni15_cv",
                "resolution": 720,
            },
            model_id=OMNI_MODEL,
            provider="omnihuman",
            # as the real adapter: a bare resume (the await) carries no length
            usage=Usage(
                pieces=1, media_seconds=Decimal(str(request.params.get("audio_seconds") or 0))
            ),
            model_revision="realman_avatar_picture_omni15_cv",
            media_url="https://cdn/omni.mp4",
        )

    def estimate_cost_usd(self, request: GenerationRequest, pricing: Any, **_: Any) -> Decimal:
        # as the real adapter: a resume orders nothing
        return Decimal(0) if request.params.get(RESUME_TASK_PARAM) else Decimal("1")


class Vendors:
    def __init__(self, omni: QueuedOmniHuman) -> None:
        self.store = _store()
        self.seedream = FakeSeedream()
        self.speech = FakeSpeech()
        self.omni = omni
        self.links = FakeLinks()
        self.producer: MediaProducer = _presenter(
            self.store,
            seedream=self.seedream,
            speech=self.speech,
            omni=omni,  # type: ignore[arg-type]
            links=self.links,
        )


def _produce(vendors: Vendors, book: Book | None, draft_id: UUID) -> MediaOutcome:
    return vendors.producer.produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=_presenter_brief(voice_id=PUBLIC_VOICE),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        vendor_tasks=book,
    )


def test_a_render_that_outlives_the_wait_leaves_the_piece_in_progress_with_its_id() -> None:
    vendors, book, draft_id = Vendors(QueuedOmniHuman()), Book(), uuid4()
    outcome = _produce(vendors, book, draft_id)

    assert outcome.pending is True
    assert outcome.failure is None and outcome.media == ()  # not failed, not made
    assert book.recorded == [("omnihuman-1", "omnihuman", OMNI_MODEL, "oh-1")]
    assert book.settled == []  # still pending: nobody settles it
    # what this run paid is kept; the render is not paid yet
    assert [u.provider for u in outcome.usage] == ["seedream", "seed_speech"]
    # what the render was made from rides with the task's id
    kept = book.contexts["omnihuman-1"][PRESENTER_CONTEXT]
    assert kept["frame_key"] == generated_key(TENANT_ID, draft_id, "presenter.jpg")
    assert kept["voice_key"] == generated_key(TENANT_ID, draft_id, "voice.mp3")
    assert kept["seconds"] > 0
    assert kept["voice"] == "public" and kept["voice_id"] == PUBLIC_VOICE


def test_the_resumed_run_lands_the_same_render_without_paying_anything_again() -> None:
    vendors, draft_id = Vendors(QueuedOmniHuman()), uuid4()
    first = Book()
    assert _produce(vendors, first, draft_id).pending

    resumed = first.carried()
    outcome = _produce(vendors, resumed, draft_id)

    assert outcome.failure is None and outcome.pending is False
    assert vendors.omni.created == 1  # one render, ever
    last = vendors.omni.requests[-1]
    assert last.params[RESUME_TASK_PARAM] == "oh-1"
    assert "image_url" not in last.params and "audio_url" not in last.params
    # the presenter and the voice were made (and paid) once, by the first run
    assert len(vendors.seedream.requests) == 1 and len(vendors.speech.requests) == 1
    assert len(vendors.links.served) == 2
    assert resumed.recorded == [] and resumed.settled == [("omnihuman-1", "succeeded")]
    (video,) = outcome.media
    assert video.media_type == "video" and video.provider == "omnihuman"
    assert video.params["task_id"] == "oh-1"
    assert video.params["thumbnail_key"] == generated_key(TENANT_ID, draft_id, "presenter.jpg")
    assert video.params["voice"] == "public" and video.params["voice_id"] == PUBLIC_VOICE
    assert vendors.store.files[video.object_key] == b"omni-mp4"
    # its spend is recorded now, once — the render BytePlus billed lands in the piece
    assert [(u.provider, u.unit) for u in outcome.usage] == [("omnihuman", "second")]
    assert outcome.usage[0].cost_usd > 0


def test_a_resumed_render_omnihuman_expired_fails_the_piece_without_its_cost() -> None:
    vendors, draft_id = Vendors(QueuedOmniHuman(resumed="expired")), uuid4()
    first = Book()
    assert _produce(vendors, first, draft_id).pending

    resumed = first.carried()
    outcome = _produce(vendors, resumed, draft_id)

    assert outcome.pending is False and outcome.media == ()
    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert resumed.settled == [("omnihuman-1", "failed")]
    assert not any(u.provider == "omnihuman" for u in outcome.usage)
    assert vendors.omni.created == 1


def test_retrying_while_the_render_is_pending_never_orders_a_second_one() -> None:
    """AC «Reintentar»: a run of the same generation while the render is still queued
    waits for the same task — no second render, no second presenter, no second voice."""
    vendors, draft_id = Vendors(QueuedOmniHuman(resumed="queued")), uuid4()
    first = Book()
    assert _produce(vendors, first, draft_id).pending

    again = first.carried()
    outcome = _produce(vendors, again, draft_id)

    assert outcome.pending is True and outcome.failure is None
    assert vendors.omni.created == 1
    assert vendors.omni.requests[-1].params[RESUME_TASK_PARAM] == "oh-1"
    assert len(vendors.seedream.requests) == 1 and len(vendors.speech.requests) == 1
    assert again.recorded == [] and again.settled == []
    assert outcome.usage == ()  # nothing paid by the retry


def test_without_a_binding_the_timeout_still_fails_with_the_approved_text() -> None:
    """Scripts and tests without a store: the old behaviour, the approved wording."""
    vendors = Vendors(QueuedOmniHuman())
    outcome = _produce(vendors, None, uuid4())
    assert outcome.pending is False
    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert outcome.detail == PRESENTER_SLOW_TEXT


def test_await_asks_omnihuman_for_a_presenter_task_at_zero_cost() -> None:
    vendors = Vendors(QueuedOmniHuman())
    no_money = BudgetContext(remaining_usd=Decimal(0), hard_stop=True)
    state, verdicts = vendors.producer.await_vendor_tasks(
        tenant_id=TENANT_ID,
        brand_id=uuid4(),
        tasks=[("omnihuman-1", "oh-7", OMNI_MODEL)],
        budget=no_money,
    )
    assert state == "done" and verdicts == {"omnihuman-1": "succeeded"}
    (asked,) = vendors.omni.requests
    assert asked.task is GenerationTask.AVATAR_VIDEO
    assert asked.params == {RESUME_TASK_PARAM: "oh-7"}
    assert vendors.omni.created == 0

    queued = Vendors(QueuedOmniHuman(resumed="queued"))
    state, verdicts = queued.producer.await_vendor_tasks(
        tenant_id=TENANT_ID,
        brand_id=uuid4(),
        tasks=[("omnihuman-1", "oh-7", OMNI_MODEL)],
        budget=no_money,
    )
    assert state == "pending" and verdicts == {}

    expired = Vendors(QueuedOmniHuman(resumed="expired"))
    state, verdicts = expired.producer.await_vendor_tasks(
        tenant_id=TENANT_ID,
        brand_id=uuid4(),
        tasks=[("omnihuman-1", "oh-7", OMNI_MODEL)],
        budget=no_money,
    )
    assert state == "done" and verdicts == {"omnihuman-1": "failed"}


def test_a_task_kept_without_its_presenter_is_still_resumed_not_reordered() -> None:
    """A row with an id but no `presenter` context (never written by this code, but a
    resume must not depend on it): the render is resumed by id all the same."""
    vendors, draft_id = Vendors(QueuedOmniHuman()), uuid4()
    outcome = _produce(vendors, Book(known={"omnihuman-1": "oh-9"}), draft_id)
    assert outcome.failure is None and outcome.pending is False
    assert vendors.omni.created == 0
    assert vendors.omni.requests[-1].params[RESUME_TASK_PARAM] == "oh-9"
