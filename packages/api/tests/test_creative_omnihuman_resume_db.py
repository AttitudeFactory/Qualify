"""m-24852495 against Postgres: a billed OmniHuman render is never lost after the wait.

A presenter whose render outlives the wait leaves the draft `drafting` with the task
recorded — the copy AND what the render was made from (`presenter`) beside it; the next
run resumes the task by id, reads that context back, lands the video and records its
cost once; running it again changes nothing. OmniHuman failing or expiring it fails the
piece and gives its creations back. The «en fila» note waits for the render window, and
another business never sees any of it. The media producer is scripted (its own side is
`test_creative_omnihuman_resume.py`); the repository, the task store, the reaper, the
claim and the recovery pass are the real ones."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED
from qualify_api.creative.media import PRESENTER_CONTEXT, MediaOutcome, MediaUsage, MediaWrite

from . import test_content_service as base
from .test_creative_vendor_tasks_db import Ledger, _age, _draft, _service, _tasks, _usage
from .test_creative_vendor_tasks_db import ScriptedMedia as _SeedanceMedia

pytestmark = pytest.mark.db

OMNI_MODEL = "omnihuman-1-5"
SLOT = "omnihuman-1"
VIDEO = MediaWrite(
    position=0,
    media_type="video",
    media_url="t/x/generated/d/r1/video.mp4",
    object_key="t/x/generated/d/r1/video.mp4",
    width=1080,
    height=1920,
    aspect_ratio="9:16",
    model_id=OMNI_MODEL,
    provider="omnihuman",
    content_type="video/mp4",
    ai_generated=True,
)
VIDEO_USAGE = MediaUsage(
    provider="omnihuman",
    model_id=OMNI_MODEL,
    unit="second",
    quantity=12,
    cost_usd=Decimal("1.44"),
)
PRESENTER = {
    "frame_key": "t/x/generated/d/r1/presenter.jpg",
    "voice_key": "t/x/generated/d/r1/voice.mp3",
    "seconds": 11.5,
    "voice": "public",
    "voice_id": "es_female_1",
    "voice_resource": "seed-tts-1.0",
}


@pytest.fixture
def db_seeded() -> tuple[UUID, UUID, UUID]:
    return base.seed_db_tenant()


class ScriptedPresenter(_SeedanceMedia):
    """The media producer as the service sees it, for a talking presenter: no task for
    `omnihuman-1` → OmniHuman accepts one (heard with the presenter's context) and the
    wait runs out; one → resumed with what was kept, and the video comes back."""

    def __init__(self, *, verdict: str = "succeeded") -> None:
        super().__init__(verdict=verdict)
        self.kept: list[Any] = []

    def produce(self, *, copy: Any, vendor_tasks: Any = None, **_: Any) -> MediaOutcome:
        assert vendor_tasks is not None
        self.copies.append(copy.hook)
        known = vendor_tasks.resume_id(SLOT)
        if known is None:
            self.created += 1
            vendor_tasks.observer(
                SLOT, "omnihuman", OMNI_MODEL, context={PRESENTER_CONTEXT: PRESENTER}
            ).created(f"oh-{self.created}")
            seedream = MediaUsage(
                provider="seedream",
                model_id="seedream-5-0-lite-260128",
                unit="piece",
                quantity=1,
                cost_usd=Decimal("0.035"),
            )
            return MediaOutcome(pending=True, usage=(seedream,))
        self.resumed.append(known)
        self.kept.append(vendor_tasks.resume_context(SLOT))
        vendor_tasks.settle(SLOT, "succeeded")
        return MediaOutcome(media=(VIDEO,), usage=(VIDEO_USAGE,))


def test_a_presenter_render_outlives_the_wait_and_lands_once(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id = db_seeded[0]
    media, ledger, copy = ScriptedPresenter(), Ledger(), base.FakeCopyAdapter()
    service = _service(media, ledger, copy)
    draft_id = _draft(service, db_seeded)

    # 1) the wait runs out: in progress, the task kept with the copy AND the presenter
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    assert service.get_draft(tenant_id=tenant_id, draft_id=draft_id).status == DRAFTING
    ((slot, task_id, status, context),) = _tasks(tenant_id, draft_id)
    assert (slot, task_id, status) == (SLOT, "oh-1", "pending")
    assert context["variants"][0]["copy"]["hook"] == "Hook 1"
    assert context[PRESENTER_CONTEXT] == PRESENTER
    assert ledger.refunds == []
    assert _usage(tenant_id, draft_id) == ["seedream"]  # the photo, paid once

    # 2) resumed (the screen's read or the worker): same task, the presenter read back
    _age(tenant_id, draft_id, quiet=timedelta(minutes=10), task_age=timedelta(minutes=50))
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail.status == GENERATED
    assert media.created == 1 and media.resumed == ["oh-1"]
    assert media.kept[0][PRESENTER_CONTEXT] == PRESENTER
    assert copy.calls == 1  # the copy is the one the video was made from
    assert [m.media_type for m in detail.media] == ["video"]
    assert _usage(tenant_id, draft_id) == ["anthropic", "omnihuman", "seedream"]
    assert [t[2] for t in _tasks(tenant_id, draft_id)] == ["succeeded"]

    # 3) running it again (a second resume, «Reintentar») duplicates neither video nor cost
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    assert _usage(tenant_id, draft_id) == ["anthropic", "omnihuman", "seedream"]
    assert media.created == 1 and media.resumed == ["oh-1"]
    assert ledger.refunds == []


def test_a_render_omnihuman_expired_fails_the_piece_unpaid_and_refunds(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id = db_seeded[0]
    media, ledger, copy = ScriptedPresenter(verdict="failed"), Ledger(), base.FakeCopyAdapter()
    service = _service(media, ledger, copy)
    draft_id = _draft(service, db_seeded)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)  # waits out

    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)  # resumed: expired
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail.status == FAILED
    assert media.resumed == []  # nothing rebuilt, nothing paid again
    assert "omnihuman" not in _usage(tenant_id, draft_id)  # no render cost
    assert [t[2] for t in _tasks(tenant_id, draft_id)] == ["failed"]
    assert [r["draft_id"] for r in ledger.refunds] == [draft_id]


def test_retrying_while_queued_never_orders_a_second_render(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id = db_seeded[0]
    media, ledger, copy = ScriptedPresenter(verdict="pending"), Ledger(), base.FakeCopyAdapter()
    service = _service(media, ledger, copy)
    draft_id = _draft(service, db_seeded)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)  # still in_queue

    assert service.get_draft(tenant_id=tenant_id, draft_id=draft_id).status == DRAFTING
    assert media.created == 1 and media.resumed == [] and copy.calls == 1
    assert ledger.refunds == [] and _usage(tenant_id, draft_id) == ["seedream"]
    assert [t[1] for t in _tasks(tenant_id, draft_id)] == ["oh-1"]


def test_the_waiting_note_waits_for_the_presenters_render_window(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    """A presenter renders ~25 min as a matter of course: «en fila» only past 40 min
    (a Seedance clip: past 8)."""
    from qualify_api.creative.vendor_tasks import PostgresVendorTaskStore

    tenant_id = db_seeded[0]
    media, ledger, copy = ScriptedPresenter(verdict="pending"), Ledger(), base.FakeCopyAdapter()
    service = _service(media, ledger, copy)
    draft_id = _draft(service, db_seeded)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    store = PostgresVendorTaskStore()

    _age(tenant_id, draft_id, quiet=timedelta(minutes=1), task_age=timedelta(minutes=20))
    assert store.waiting(tenant_id=tenant_id, draft_ids=[draft_id]) == frozenset()
    _age(tenant_id, draft_id, quiet=timedelta(minutes=1), task_age=timedelta(minutes=41))
    assert store.waiting(tenant_id=tenant_id, draft_ids=[draft_id]) == {draft_id}

    seedance = _service(_SeedanceMedia(verdict="pending"), Ledger(), base.FakeCopyAdapter())
    clip_id = _draft(seedance, db_seeded)
    seedance.run_generation(tenant_id=tenant_id, draft_id=clip_id)
    _age(tenant_id, clip_id, quiet=timedelta(minutes=1), task_age=timedelta(minutes=20))
    assert store.waiting(tenant_id=tenant_id, draft_ids=[clip_id]) == {clip_id}


def test_the_worker_lands_a_done_render_without_a_screen_read(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    """The recovery pass (m-24852492) asks OmniHuman for an `omnihuman` row and resumes
    the draft once the render is done."""
    from qualify_api.creative import vendor_recovery as rec

    tenant_id = db_seeded[0]
    media, ledger, copy = ScriptedPresenter(), Ledger(), base.FakeCopyAdapter()
    service = _service(media, ledger, copy)
    draft_id = _draft(service, db_seeded)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    _age(tenant_id, draft_id, quiet=timedelta(minutes=10), task_age=timedelta(minutes=50))

    class Never:
        def status(self, task: Any, **_: Any) -> str:
            raise AssertionError("a presenter's render is asked of OmniHuman")

    class Done:
        def __init__(self) -> None:
            self.asked: list[str] = []

        def status(self, task: Any, **_: Any) -> str:
            self.asked.append(task.vendor_task_id)
            return "succeeded"

    done = Done()
    report = rec.recover_once(
        tenants=lambda _now: [tenant_id],
        store=rec.PostgresRecoveryStore(),
        statuses=rec.StatusByProvider(Never(), done),
        resume=lambda t, d: service.run_generation(tenant_id=t, draft_id=d),
    )
    assert draft_id in report.resumed and "oh-1" in done.asked
    assert service.get_draft(tenant_id=tenant_id, draft_id=draft_id).status == GENERATED
    assert _usage(tenant_id, draft_id).count("omnihuman") == 1


def test_another_business_never_sees_the_presenters_task(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    from qualify_api.creative.dispatch import claim_waiting_drafts
    from qualify_api.creative.vendor_tasks import PostgresVendorTaskStore

    tenant_id = db_seeded[0]
    media, ledger, copy = ScriptedPresenter(verdict="pending"), Ledger(), base.FakeCopyAdapter()
    service = _service(media, ledger, copy)
    draft_id = _draft(service, db_seeded)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    _age(tenant_id, draft_id, quiet=timedelta(minutes=10), task_age=timedelta(minutes=50))

    other = uuid4()
    store = PostgresVendorTaskStore()
    assert store.tasks(tenant_id=other, draft_id=draft_id, revision=1) == ()
    assert store.waiting(tenant_id=other, draft_ids=[draft_id]) == frozenset()
    assert draft_id not in claim_waiting_drafts(tenant_id=other, quiet_minutes=0)
    # settling from another business touches nothing
    store.settle(tenant_id=other, draft_id=draft_id, revision=1, slot=SLOT, status="failed")
    assert [t[2] for t in _tasks(tenant_id, draft_id)] == ["pending"]
    # its own business still sees it
    (record,) = store.tasks(tenant_id=tenant_id, draft_id=draft_id, revision=1)
    assert record.provider == "omnihuman" and record.context[PRESENTER_CONTEXT] == PRESENTER
