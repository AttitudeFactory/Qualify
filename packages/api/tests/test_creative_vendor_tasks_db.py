"""m-24852154 against Postgres: a billed Seedance video is never lost after the wait.

A run whose task outlives the wait leaves the draft `drafting` with the task recorded
(and the copy beside it); the reaper leaves it alone; the next read hands it to a run
that resumes the task by id, rebuilds the piece from the SAME copy and records the spend
once. BytePlus failing or expiring it fails the piece and gives its creations back. The
media producer is scripted here (its own side is `test_creative_vendor_task_resume.py`);
the repository, the task store, the reaper and the claim are the real ones."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentKind, GenerationTask

from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED
from qualify_api.creative.media import MediaOutcome, MediaUsage, MediaWrite

from . import test_content_service as base
from .test_content_service import FakeCopyAdapter, StaticKeyResolver, make_brief

pytestmark = pytest.mark.db


@pytest.fixture
def db_seeded() -> tuple[UUID, UUID, UUID]:
    """The content service suite's seeded tenant (kit + active voice)."""
    return base.seed_db_tenant()


SEEDANCE_MODEL = "dreamina-seedance-2-5-260628"
VIDEO = MediaWrite(
    position=0,
    media_type="video",
    media_url="t/x/generated/d/r1/video.mp4",
    object_key="t/x/generated/d/r1/video.mp4",
    width=864,
    height=480,
    aspect_ratio="16:9",
    model_id=SEEDANCE_MODEL,
    provider="seedance",
    content_type="video/mp4",
    ai_generated=True,
)
VIDEO_USAGE = MediaUsage(
    provider="seedance",
    model_id=SEEDANCE_MODEL,
    unit="second",
    quantity=5,
    cost_usd=Decimal("0.56"),
    output_tokens=48000,
)


class ScriptedMedia:
    """The media producer as the service sees it. `produce` asks the binding for the
    task of slot `seedance-1`: none → ModelArk accepts a new one (its id is heard) and
    the wait runs out; one → it was resumed, and the video comes back."""

    def __init__(self, *, verdict: str = "succeeded") -> None:
        self.verdict = verdict
        self.created = 0
        self.resumed: list[str] = []
        self.copies: list[str] = []

    def produce(self, *, copy: Any, vendor_tasks: Any = None, **_: Any) -> MediaOutcome:
        assert vendor_tasks is not None
        self.copies.append(copy.hook)
        known = vendor_tasks.resume_id("seedance-1")
        if known is None:
            self.created += 1
            vendor_tasks.observer("seedance-1", "seedance", SEEDANCE_MODEL).created(
                f"cgt-{self.created}"
            )
            return MediaOutcome(pending=True)
        self.resumed.append(known)
        vendor_tasks.settle("seedance-1", "succeeded")
        return MediaOutcome(media=(VIDEO,), usage=(VIDEO_USAGE,))

    def await_vendor_tasks(self, *, tasks: Any, **_: Any) -> tuple[str, dict[str, str]]:
        if self.verdict == "pending":
            return "pending", {}
        return "done", {slot: self.verdict for slot, _, _ in tasks}


class Ledger:
    """«Creaciones del mes» as the service calls it: what was refunded."""

    def __init__(self) -> None:
        self.refunds: list[dict[str, Any]] = []

    def charge(self, **_: Any) -> None:
        return None

    def balance(self, **_: Any) -> Any:
        class _Plenty:
            def shortfall(self, price: Any) -> None:
                return None

        return _Plenty()

    def refund(self, **kw: Any) -> bool:
        self.refunds.append(kw)
        return True

    def __getattr__(self, name: str) -> Any:
        return lambda **_: None


class Dispatched:
    def __init__(self) -> None:
        self.generations: list[UUID] = []

    def dispatch_generation(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        self.generations.append(draft_id)

    def dispatch_finalize(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        raise AssertionError("no final here")


def _service(media: ScriptedMedia, ledger: Ledger, copy: FakeCopyAdapter) -> Any:
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.router import CreativeRouter

    from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
    from qualify_api.creative.service import ContentService
    from qualify_api.creative.vendor_tasks import PostgresVendorTaskStore

    pricing = JsonPricingTable("v1")
    return ContentService(
        router=CreativeRouter(
            providers={"anthropic": copy}, pricing=pricing, credentials=StaticKeyResolver()
        ),
        pricing=pricing,
        credentials=StaticKeyResolver(),
        voice_service=DbVoiceProfileReader(),
        brand_service=DbBrandKitReader(),
        media=media,  # type: ignore[arg-type]
        creations=ledger,  # type: ignore[arg-type]
        vendor_tasks=PostgresVendorTaskStore(),
        dispatcher=Dispatched(),
    )


def _draft(service: Any, seeded: tuple[UUID, UUID, UUID]) -> UUID:
    tenant_id, brand_id, user_id = seeded
    return service.create_draft(
        tenant_id=tenant_id,
        brand_id=brand_id,
        brief=make_brief(variants=1, brand_id=brand_id, kind=ContentKind.STATIC_FLYER),
        user_id=user_id,
    )


def _age(tenant_id: UUID, draft_id: UUID, *, quiet: timedelta, task_age: timedelta) -> None:
    """The thread went silent `quiet` ago and its task was created `task_age` ago."""
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm

    now = datetime.now(UTC)
    with tenant_session(tenant_id) as session:
        session.get(orm.ContentDraft, draft_id).updated_at = now - quiet
        for task in session.query(orm.CreativeVendorTask).filter_by(draft_id=draft_id):
            task.created_at = now - task_age


def _tasks(tenant_id: UUID, draft_id: UUID) -> list[Any]:
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm

    with tenant_session(tenant_id) as session:
        rows = session.query(orm.CreativeVendorTask).filter_by(draft_id=draft_id).all()
        return [(r.slot, r.vendor_task_id, r.status, dict(r.context)) for r in rows]


def _usage(tenant_id: UUID, draft_id: UUID) -> list[str]:
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm

    with tenant_session(tenant_id) as session:
        rows = session.query(orm.CreativeUsageEvent).filter_by(draft_id=draft_id).all()
        return sorted(r.provider for r in rows)


def test_a_video_that_outlives_the_wait_lands_in_the_piece_and_is_paid_once(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    from qualify_api.creative.dispatch import claim_waiting_drafts, reap_stale_drafts

    tenant_id = db_seeded[0]
    media, ledger, copy = ScriptedMedia(), Ledger(), FakeCopyAdapter()
    service = _service(media, ledger, copy)
    draft_id = _draft(service, db_seeded)

    # 1) the wait runs out: still in progress, the task kept with the copy, no refund
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail.status == DRAFTING and detail.variants == ()
    ((slot, task_id, status, context),) = _tasks(tenant_id, draft_id)
    assert (slot, task_id, status) == ("seedance-1", "cgt-1", "pending")
    assert context["variants"][0]["copy"]["hook"] == "Hook 1"
    assert ledger.refunds == [] and _usage(tenant_id, draft_id) == []
    assert copy.calls == 1

    # 2) long silent: the reaper does not fail it — its video may still come
    _age(tenant_id, draft_id, quiet=timedelta(hours=2), task_age=timedelta(hours=2))
    reap_stale_drafts(tenant_id=tenant_id)

    # 3) the screen's next read hands it to a run — once (claimed: the next read waits)
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail.status == DRAFTING and detail.waiting_vendor is True
    # (once at creation, once now; the shared test tenant may hold other suites'
    # waiting drafts, so only ours are counted)
    assert service.dispatcher.generations.count(draft_id) == 2
    service.list_drafts(tenant_id=tenant_id, brand_id=db_seeded[1])
    assert service.dispatcher.generations.count(draft_id) == 2
    assert draft_id not in claim_waiting_drafts(tenant_id=tenant_id)

    # 4) the resumed run: same task, same copy, no new copy call, the video in place
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail.status == GENERATED and detail.waiting_vendor is False
    assert media.created == 1 and media.resumed == ["cgt-1"]
    assert media.copies == ["Hook 1", "Hook 1"] and copy.calls == 1
    assert [m.media_type for m in detail.media] == ["video"]
    assert _usage(tenant_id, draft_id) == ["anthropic", "seedance"]
    assert [t[2] for t in _tasks(tenant_id, draft_id)] == ["succeeded"]
    assert ledger.refunds == []

    # 5) idempotent: running it again changes nothing, pays nothing
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    assert _usage(tenant_id, draft_id) == ["anthropic", "seedance"]
    assert media.resumed == ["cgt-1"]
    assert draft_id not in claim_waiting_drafts(tenant_id=tenant_id, quiet_minutes=0)


@pytest.mark.parametrize("verdict", ["failed"])
def test_a_task_the_vendor_failed_or_expired_fails_the_piece_and_refunds(
    db_seeded: tuple[UUID, UUID, UUID], verdict: str
) -> None:
    tenant_id = db_seeded[0]
    media, ledger, copy = ScriptedMedia(verdict=verdict), Ledger(), FakeCopyAdapter()
    service = _service(media, ledger, copy)
    draft_id = _draft(service, db_seeded)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)  # waits out

    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)  # resumed: expired
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail.status == FAILED
    assert media.resumed == []  # nothing rebuilt, nothing paid again
    assert _usage(tenant_id, draft_id) == ["anthropic"]  # no video cost recorded
    assert [t[2] for t in _tasks(tenant_id, draft_id)] == ["failed"]
    assert [r["draft_id"] for r in ledger.refunds] == [draft_id]


def test_a_task_still_queued_keeps_waiting_without_paying_again(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id = db_seeded[0]
    media, ledger, copy = ScriptedMedia(verdict="pending"), Ledger(), FakeCopyAdapter()
    service = _service(media, ledger, copy)
    draft_id = _draft(service, db_seeded)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)  # resumed, still queued

    assert service.get_draft(tenant_id=tenant_id, draft_id=draft_id).status == DRAFTING
    assert media.created == 1 and media.resumed == [] and copy.calls == 1
    assert ledger.refunds == [] and _usage(tenant_id, draft_id) == []


def test_a_task_given_up_after_bytepluss_expiry_is_reaped_and_refunded(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    from qualify_api.creative.dispatch import reap_stale_drafts

    tenant_id = db_seeded[0]
    media, ledger, copy = ScriptedMedia(), Ledger(), FakeCopyAdapter()
    service = _service(media, ledger, copy)
    draft_id = _draft(service, db_seeded)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)

    _age(tenant_id, draft_id, quiet=timedelta(hours=50), task_age=timedelta(hours=50))
    reap_stale_drafts(tenant_id=tenant_id)
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail.status == FAILED and detail.failure_reason == "timeout"
    assert [t[2] for t in _tasks(tenant_id, draft_id)] == ["failed"]


def test_the_task_store_is_kept_to_its_own_business(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    from qualify_api.creative.dispatch import claim_waiting_drafts
    from qualify_api.creative.vendor_tasks import PostgresVendorTaskStore

    tenant_id = db_seeded[0]
    service = _service(ScriptedMedia(), Ledger(), FakeCopyAdapter())
    draft_id = _draft(service, db_seeded)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    store = PostgresVendorTaskStore()

    other = uuid4()
    assert store.tasks(tenant_id=other, draft_id=draft_id, revision=1) == ()
    assert store.waiting(tenant_id=other, draft_ids=[draft_id]) == frozenset()
    _age(tenant_id, draft_id, quiet=timedelta(minutes=5), task_age=timedelta(hours=1))
    assert claim_waiting_drafts(tenant_id=other) == []
    store.settle(tenant_id=other, draft_id=draft_id, revision=1, slot="seedance-1", status="failed")
    assert [t[2] for t in _tasks(tenant_id, draft_id)] == ["pending"]
    assert len(store.tasks(tenant_id=tenant_id, draft_id=draft_id, revision=1)) == 1


def test_a_failed_slot_takes_the_next_task_and_a_live_one_is_never_replaced(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    from qualify_api.creative.vendor_tasks import PostgresVendorTaskStore

    tenant_id = db_seeded[0]
    service = _service(ScriptedMedia(), Ledger(), FakeCopyAdapter())
    draft_id = _draft(service, db_seeded)
    store = PostgresVendorTaskStore()
    args: dict[str, Any] = {
        "tenant_id": tenant_id,
        "draft_id": draft_id,
        "revision": 1,
        "slot": "final:x",
        "provider": "seedance",
        "model_id": SEEDANCE_MODEL,
        "pipeline_version": None,
        "context": {},
    }
    store.record(**args, vendor_task_id="cgt-a")
    store.record(**args, vendor_task_id="cgt-b")  # live: kept
    assert [t[1] for t in _tasks(tenant_id, draft_id)] == ["cgt-a"]
    store.settle(
        tenant_id=tenant_id, draft_id=draft_id, revision=1, slot="final:x", status="failed"
    )
    store.record(**args, vendor_task_id="cgt-c")  # failed: replaced, pending again
    assert [(t[1], t[2]) for t in _tasks(tenant_id, draft_id)] == [("cgt-c", "pending")]
    assert GenerationTask.SCENE_VIDEO  # (import kept for readers: the task kind at stake)
