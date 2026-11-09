"""m-24820842 against Postgres (review #3): «Crear las que faltan».

- `failed_attempt` reads the failed version back: its status, its copy and only the paid
  gallery slides (`ImageAsset.version_id`), each stamped with the revision it came from.
- `finish_gallery` locks the draft row for the whole step: a double click or a second tab
  waits, then finds the gallery `drafting` and is refused — one charge, one revision, one
  resume stamp and ONE dispatch, after the commit.
- The stamp (0116: `content_drafts.resume_*`) names exactly the revision it created;
  another version («Pedir otra versión») never reuses the failed attempt.

The media producer is scripted (no vendor); repository, vendor-task table and units of
work are the real ones."""

from __future__ import annotations

import threading
import time
from typing import Any
from uuid import UUID

import pytest
from qualify_creative.enums import ContentKind, FailureReason, SlideSource
from qualify_creative.schemas import CarouselSlide, MediaInputs

from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED, InvalidTransition
from qualify_api.creative.media import KEPT_FROM_REVISION, MediaOutcome, MediaWrite

from . import test_content_service as base
from .test_content_service import FakeCopyAdapter, StaticKeyResolver, make_brief

pytestmark = pytest.mark.db


@pytest.fixture
def db_seeded() -> tuple[UUID, UUID, UUID]:
    return base.seed_db_tenant()


def _slide(tenant_id: UUID, position: int, *, source: str = "generated") -> MediaWrite:
    key = f"t/{tenant_id}/generated/gallery-db/r1/slide-{position + 1}.jpg"
    return MediaWrite(
        position=position,
        media_type="image",
        media_url=key,
        object_key=key,
        width=1080,
        height=1350,
        aspect_ratio="4:5",
        model_id="seedream-5-0-lite-260128",
        provider="seedream",
        ai_generated=source != "existing",
        params={"slide": position + 1, "slides": 3, "source": source, "scene_prompt": ""},
    )


class ScriptedMedia:
    def __init__(self, *outcomes: MediaOutcome) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def produce(self, **kwargs: Any) -> MediaOutcome:
        self.calls.append(kwargs)
        return self.outcomes.pop(0)


class SlowLedger:
    """«Creaciones del mes»: counts charges; the first one is slow, so a second click
    arrives while the first still holds the row."""

    def __init__(self) -> None:
        self.charges: list[dict[str, Any]] = []
        self.refunds: list[dict[str, Any]] = []

    def charge(self, **kw: Any) -> None:
        self.charges.append(kw)
        if len(self.charges) == 2:  # the creation's own charge is the first
            time.sleep(0.8)

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


class AfterCommit:
    """Dispatches the way `InlineDispatcher` does (after the unit commits) and records
    what a worker would read at that moment from its own session."""

    def __init__(self) -> None:
        self.seen: list[tuple[UUID, str, int]] = []

    def dispatch_generation(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        from qualify_shared.db.session import after_tenant_commit, tenant_session

        from qualify_api.creative import models as orm

        def read() -> None:
            with tenant_session(tenant_id, independent=True) as session:
                row = session.get(orm.ContentDraft, draft_id)
                self.seen.append((draft_id, row.status, row.revision))

        after_tenant_commit(tenant_id, read)

    def dispatch_finalize(self, **_: Any) -> None:
        raise AssertionError("no final here")


def _service(media: ScriptedMedia, ledger: SlowLedger) -> Any:
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.router import CreativeRouter

    from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
    from qualify_api.creative.service import ContentService
    from qualify_api.creative.vendor_tasks import PostgresVendorTaskStore

    pricing = JsonPricingTable("v1")
    return ContentService(
        router=CreativeRouter(
            providers={"anthropic": FakeCopyAdapter()},
            pricing=pricing,
            credentials=StaticKeyResolver(),
        ),
        pricing=pricing,
        credentials=StaticKeyResolver(),
        voice_service=DbVoiceProfileReader(),
        brand_service=DbBrandKitReader(),
        media=media,  # type: ignore[arg-type]
        creations=ledger,  # type: ignore[arg-type]
        vendor_tasks=PostgresVendorTaskStore(),
        dispatcher=AfterCommit(),
    )


def _failed_gallery(
    seeded: tuple[UUID, UUID, UUID], *more: MediaOutcome
) -> tuple[Any, ScriptedMedia, SlowLedger, UUID]:
    tenant_id, brand_id, user_id = seeded
    cut = MediaOutcome(
        media=(_slide(tenant_id, 0), _slide(tenant_id, 1), _slide(tenant_id, 2, source="existing")),
        failure=FailureReason.PROVIDER_ERROR.value,
        detail="Diapositiva 3: no salió.",
    )
    media, ledger = ScriptedMedia(cut, *more), SlowLedger()
    service = _service(media, ledger)
    brief = make_brief(
        variants=1,
        brand_id=brand_id,
        kind=ContentKind.CAROUSEL,
        media=MediaInputs(
            slides=tuple(CarouselSlide(source=SlideSource.GENERATED) for _ in range(3))
        ),
    )
    draft_id = service.create_draft(
        tenant_id=tenant_id, brand_id=brand_id, brief=brief, user_id=user_id
    )
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    return service, media, ledger, draft_id


def _stamp(tenant_id: UUID, draft_id: UUID) -> tuple[int | None, int | None, int | None]:
    """The resume stamp on the draft row (0116)."""
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm

    with tenant_session(tenant_id) as session:
        row = session.get(orm.ContentDraft, draft_id)
        return row.resume_for_revision, row.resume_of_revision, row.resume_compiler_version


def test_failed_attempt_reads_back_the_failed_versions_copy_and_paid_slides(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    from qualify_api.creative.service import PostgresContentRepository

    tenant_id = db_seeded[0]
    service, _media, _ledger, draft_id = _failed_gallery(db_seeded)
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail.status == FAILED and detail.media == ()
    assert (detail.kept_slides, detail.gallery_slides) == (2, 3)

    repo = PostgresContentRepository()
    attempt = repo.failed_attempt(tenant_id=tenant_id, draft_id=draft_id, revision=1)
    assert attempt is not None and attempt.revision == 1 and attempt.copy_passed
    assert [s.position for s in attempt.slides] == [0, 1]  # the existing piece is not kept
    assert {s.params[KEPT_FROM_REVISION] for s in attempt.slides} == {1}
    assert len(attempt.variants) == 1
    # a later revision with no version row of its own still finds it (a reaped attempt)
    assert repo.failed_attempt(tenant_id=tenant_id, draft_id=draft_id, revision=5) is not None
    assert repo.failed_attempt(tenant_id=tenant_id, draft_id=draft_id, revision=0) is None
    assert repo.gallery_resume(tenant_id=tenant_id, draft_id=draft_id, revision=2) is None


def test_a_double_click_is_charged_and_dispatched_once(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id, _brand_id, user_id = db_seeded
    service, _media, ledger, draft_id = _failed_gallery(db_seeded)
    charges_before = len(ledger.charges)
    results: list[object] = []

    def click() -> None:
        try:
            results.append(
                service.finish_gallery(tenant_id=tenant_id, draft_id=draft_id, user_id=user_id)
            )
        except Exception as exc:  # noqa: BLE001 - the second click's refusal is the point
            results.append(exc)

    first = threading.Thread(target=click)
    second = threading.Thread(target=click)
    first.start()
    time.sleep(0.2)  # the first click holds the row (its charge sleeps)
    second.start()
    first.join(10)
    second.join(10)

    refused = [r for r in results if isinstance(r, Exception)]
    done = [r for r in results if not isinstance(r, Exception)]
    assert len(done) == 1 and len(refused) == 1
    assert isinstance(refused[0], InvalidTransition)
    assert done[0].status == DRAFTING and done[0].revision == 2
    assert len(ledger.charges) - charges_before == 1
    assert ledger.charges[-1]["revision"] == 2
    # dispatched once, after the commit: the worker already reads the new revision
    assert service.dispatcher.seen.count((draft_id, DRAFTING, 2)) == 1
    assert len([s for s in service.dispatcher.seen if s[0] == draft_id]) == 2  # + creation
    assert _stamp(tenant_id, draft_id) == (2, 1, None)


def test_the_stamped_revision_reuses_the_slides_and_another_version_does_not(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id, _brand_id, user_id = db_seeded
    third = _slide(tenant_id, 2)
    service, media, _ledger, draft_id = _failed_gallery(
        db_seeded,
        MediaOutcome(media=(_slide(tenant_id, 0), _slide(tenant_id, 1), third)),
        MediaOutcome(media=(_slide(tenant_id, 0), _slide(tenant_id, 1), third)),
    )
    service.finish_gallery(tenant_id=tenant_id, draft_id=draft_id, user_id=user_id)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    assert sorted(media.calls[1]["kept_slides"]) == [0, 1]
    assert service.get_draft(tenant_id=tenant_id, draft_id=draft_id).status == GENERATED

    # «Pedir otra versión»: a new revision without a stamp — nothing is reused
    service.reject(
        tenant_id=tenant_id, draft_id=draft_id, reason="otra", user_id=user_id, regenerate=True
    )
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    assert not media.calls[2].get("kept_slides")
    # the stamp still names revision 2: revision 3 is not a resume
    assert _stamp(tenant_id, draft_id)[0] == 2
    from qualify_api.creative.service import PostgresContentRepository

    assert (
        PostgresContentRepository().gallery_resume(
            tenant_id=tenant_id, draft_id=draft_id, revision=3
        )
        is None
    )
