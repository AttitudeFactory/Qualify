"""m-24852154: a Seedance task that outlives the wait is kept by id and resumed, never
submitted twice and never lost while BytePlus bills it — the media producer's side,
offline (a scripted Seedance behind the real router).

The service and the database side (draft left in progress, resumed by the next read,
settled once, refunds) are in `test_creative_vendor_tasks_db.py`."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from qualify_creative.adapters.byteplus_ark import RESUME_TASK_PARAM
from qualify_creative.enums import FailureReason
from qualify_creative.providers import GenerationRequest, GenerationResult, VendorTaskObserver
from qualify_creative.router import BudgetContext

from qualify_api.creative.media import MediaOutcome

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _kit
from .test_creative_seedance_draft import (
    DraftSeedance,
    RecordingFitter,
    _clip,
    _producer,
    _record,
    _store,
)


class Book:
    """A `VendorTaskBinding` in memory: what the service hands the producer."""

    def __init__(self, known: dict[str, str] | None = None) -> None:
        self.known = dict(known or {})
        self.recorded: list[tuple[str, str, str]] = []
        self.settled: list[tuple[str, str]] = []
        self.polls = 0

    def resume_id(self, slot: str) -> str | None:
        return self.known.get(slot)

    def observer(self, slot: str, provider: str, model_id: str) -> VendorTaskObserver:
        book = self

        class _Obs:
            def created(self, task_id: str) -> None:
                book.known[slot] = task_id
                book.recorded.append((slot, task_id, model_id))

            def polled(self, task_id: str, status: str) -> None:
                book.polls += 1

        return _Obs()

    def settle(self, slot: str, status: str) -> None:
        self.settled.append((slot, status))


class QueuedSeedance(DraftSeedance):
    """Seedance whose new tasks outlive the wait: ModelArk accepts the task (its id is
    heard), then the adapter gives up waiting. A resumed task comes back finished."""

    def __init__(self, *, resumed: str = "succeeded") -> None:
        super().__init__()
        self.resumed = resumed
        self.created = 0

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        resume = request.params.get(RESUME_TASK_PARAM)
        if resume is None:
            self.created += 1
            task_id = f"cgt-{self.created}"
            if request.observer is not None:
                request.observer.created(task_id)
            self.requests.append(request)
            raise RuntimeError(f"ArkTaskTimeout: Seedance task {task_id} still queued after 3600s")
        if self.resumed == "expired":
            self.requests.append(request)
            raise RuntimeError(f"ArkTaskFailed: Seedance task {resume} expired: Expired")
        return super().generate(request, api_key=api_key)


def _produce(producer: Any, book: Book | None, draft_id: Any) -> MediaOutcome:
    return producer.produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=_clip(),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        vendor_tasks=book,
    )


def test_a_task_that_outlives_the_wait_leaves_the_piece_in_progress_with_its_id() -> None:
    seedance, book = QueuedSeedance(), Book()
    outcome = _produce(_producer(_store(), seedance, RecordingFitter()), book, uuid4())

    assert outcome.pending is True
    assert outcome.failure is None and outcome.media == ()  # not failed, not made
    assert book.recorded == [("seedance-1", "cgt-1", "dreamina-seedance-2-5-260628")]
    assert book.settled == []  # still pending: nobody settles it
    assert not any(u.provider == "seedance" for u in outcome.usage)  # not paid yet


def test_the_resumed_run_waits_for_the_same_task_and_never_creates_another() -> None:
    seedance, draft_id = QueuedSeedance(), uuid4()
    producer = _producer(_store(), seedance, RecordingFitter())
    book = Book()
    assert _produce(producer, book, draft_id).pending

    resumed = Book(known=book.known)
    outcome = _produce(producer, resumed, draft_id)

    assert outcome.failure is None and outcome.pending is False
    assert seedance.created == 1  # one task, ever
    last = seedance.requests[-1]
    assert last.params[RESUME_TASK_PARAM] == "cgt-1"
    assert resumed.recorded == [] and resumed.settled == [("seedance-1", "succeeded")]
    (video,) = outcome.media
    assert video.media_type == "video"
    # its spend is recorded now, once — the video BytePlus billed lands in the piece
    assert [u.provider for u in outcome.usage if u.provider == "seedance"] == ["seedance"]


def test_a_resumed_task_the_vendor_expired_fails_the_piece_unpaid() -> None:
    seedance = QueuedSeedance(resumed="expired")
    producer = _producer(_store(), seedance, RecordingFitter())
    book = Book(known={"seedance-1": "cgt-1"})
    outcome = _produce(producer, book, uuid4())

    assert outcome.pending is False
    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert book.settled == [("seedance-1", "failed")]
    assert not any(u.provider == "seedance" for u in outcome.usage)
    assert seedance.created == 0


def test_without_a_binding_nothing_changes_for_the_caller() -> None:
    """Tests and scripts without a store: the call is the one it always was."""
    seedance = DraftSeedance()
    outcome = _produce(_producer(_store(), seedance, RecordingFitter()), None, uuid4())
    assert outcome.failure is None and outcome.pending is False
    assert RESUME_TASK_PARAM not in seedance.requests[0].params
    assert seedance.requests[0].observer is None


def test_await_reports_a_task_still_waiting_without_paying_anything() -> None:
    seedance = QueuedSeedance()
    producer = _producer(_store(), seedance, RecordingFitter())

    class StillQueued(QueuedSeedance):
        def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
            assert request.params[RESUME_TASK_PARAM] == "cgt-1"
            raise RuntimeError("ArkTaskTimeout: Seedance task cgt-1 still queued after 3600s")

    waiting = _producer(_store(), StillQueued(), RecordingFitter())
    state, verdicts = waiting.await_vendor_tasks(
        tenant_id=TENANT_ID,
        brand_id=uuid4(),
        tasks=[("seedance-1", "cgt-1", "dreamina-seedance-2-5-260628")],
        budget=BudgetContext(remaining_usd=BUDGET.remaining_usd),
    )
    assert state == "pending" and verdicts == {}

    state, verdicts = producer.await_vendor_tasks(
        tenant_id=TENANT_ID,
        brand_id=uuid4(),
        tasks=[("seedance-1", "cgt-1", "dreamina-seedance-2-5-260628")],
        budget=BudgetContext(remaining_usd=BUDGET.remaining_usd),
    )
    assert state == "done" and verdicts == {"seedance-1": "succeeded"}
    assert seedance.created == 0


def test_a_retried_final_resumes_the_task_of_the_earlier_order() -> None:
    """AC: a final whose task outlived the wait is never ordered (nor paid) twice."""
    store = _store()
    draft_seedance = DraftSeedance()
    (draft,) = (
        _producer(store, draft_seedance, RecordingFitter())
        .produce(
            tenant_id=TENANT_ID,
            draft_id=(draft_id := uuid4()),
            brief=_clip(),
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
        )
        .media
    )
    asset = _record(draft)
    seedance = QueuedSeedance()
    producer = _producer(store, seedance, RecordingFitter())

    def finalize(book: Book) -> Any:
        return producer.finalize(
            tenant_id=TENANT_ID,
            draft_id=draft_id,
            brief=_clip(),
            kit=_kit(),
            asset=asset,
            budget=BUDGET,
            revision=1,
            vendor_tasks=book,
        )

    first = Book()
    waited = finalize(first)
    assert waited.pending is True and waited.failure is None and waited.media is None
    assert [task for _, task, _ in first.recorded] == ["cgt-1"]

    retried = finalize(Book(known=first.known))
    assert retried.media is not None and retried.failure is None
    assert seedance.created == 1  # the retry resumed it
    finals = [r for r in seedance.requests if "draft_task_id" in r.params]
    assert finals[-1].params[RESUME_TASK_PARAM] == "cgt-1"
