"""m-24820842 (live test 2026-11-03, draft 320257e3): «Crear las que faltan». A gallery
that fails after finishing some slides keeps them on its failed version (R2 keys +
provenance) and says so; the owner's retry is a new revision that reuses the copy and
those slides — no Claude call, no vendor call for a finished slide."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from qualify_creative.enums import ContentKind, FailureReason, SlideSource
from qualify_creative.schemas import CarouselSlide, MediaInputs

from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED, InvalidTransition
from qualify_api.creative.media import KEPT_FROM_REVISION, MediaOutcome, MediaWrite
from qualify_api.creative.service import (
    BRAND_APPLIED_PIPELINE_VERSION,
    GALLERY_KEPT_TEXT,
    FailedAttempt,
    GalleryResume,
    NothingToFinish,
    VariantWrite,
)

from .test_content_service import (
    TENANT_ID,
    USER_ID,
    FakeRouter,
    InMemoryRepository,
    copy_dict,
    make_brief,
    make_kit,
    make_service,
    make_voice,
    ok_outcome,
)


def _slide(position: int, provider: str = "seedream", media_type: str = "image") -> MediaWrite:
    return MediaWrite(
        position=position,
        media_type=media_type,
        media_url=f"t/x/generated/d/r1/slide-{position + 1}.jpg",
        object_key=f"t/x/generated/d/r1/slide-{position + 1}.jpg",
        width=1080,
        height=1350,
        aspect_ratio="4:5",
        model_id="seedream-5-0-lite-260128",
        provider=provider,
        ai_generated=True,
        params={"slide": position + 1, "slides": 3, "source": "generated", "scene_prompt": ""},
    )


SLIDE_1, SLIDE_2, SLIDE_3 = _slide(0), _slide(1), _slide(2)
CUT = "Diapositiva 3: El generador de imágenes tardó demasiado y cortó la conexión."


class VersionedRepository(InMemoryRepository):
    """The in-memory repository plus what Postgres does with versions: each generation
    settles its own version; only a successful one is shown; a failed one keeps its copy
    and media for `failed_attempt`."""

    def __init__(self) -> None:
        super().__init__()
        self.versions: dict[UUID, list[tuple[int, str, tuple, tuple]]] = {}
        self.resumes: dict[tuple[UUID, int], GalleryResume] = {}

    def stamp_gallery_resume(self, *, tenant_id, draft_id, revision, resume):  # noqa: ANN001, ANN201
        self.resumes.setdefault((draft_id, revision), resume)

    def gallery_resume(self, *, tenant_id, draft_id, revision):  # noqa: ANN001, ANN201
        return self.resumes.get((draft_id, revision))

    def finish_generation(self, *, tenant_id, draft_id, new_status, variants, media=(), **kw):  # noqa: ANN001, ANN003, ANN201
        revision = self.drafts[draft_id].revision
        if self.drafts[draft_id].status == DRAFTING:
            self.versions.setdefault(draft_id, []).append(
                (revision, "active" if new_status == GENERATED else "failed", variants, media)
            )
        if new_status == GENERATED:
            return super().finish_generation(
                tenant_id=tenant_id,
                draft_id=draft_id,
                new_status=new_status,
                variants=variants,
                media=media,
                **kw,
            )
        # a failed version is never shown: neither its copy nor its media
        return super().finish_generation(
            tenant_id=tenant_id, draft_id=draft_id, new_status=new_status, variants=(), **kw
        )

    def failed_attempt(self, *, tenant_id, draft_id, revision):  # noqa: ANN001, ANN201
        rows = [v for v in self.versions.get(draft_id, []) if v[0] <= revision]
        if not rows or rows[-1][1] != "failed":
            return None
        number, _, variants, media = rows[-1]
        return FailedAttempt(
            revision=number,
            variants=tuple(variants),
            slides=tuple(
                replace(m, params={**m.params, KEPT_FROM_REVISION: number}) for m in media
            ),
        )


class ScriptedMedia:
    """Answers each `produce` with the next outcome and records what it was given."""

    def __init__(self, *outcomes: MediaOutcome) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def produce(self, **kwargs: Any) -> MediaOutcome:
        self.calls.append(kwargs)
        return self.outcomes.pop(0)


def _gallery_brief() -> Any:
    return make_brief(
        variants=1,
        kind=ContentKind.CAROUSEL,
        media=MediaInputs(
            slides=tuple(CarouselSlide(source=SlideSource.GENERATED) for _ in range(3))
        ),
    )


def _failed_gallery(*media_outcomes: MediaOutcome) -> tuple[Any, VersionedRepository, Any, Any]:
    router = FakeRouter([ok_outcome(copy_dict("Smash doble"))])  # ONE copy call, ever
    media = ScriptedMedia(*media_outcomes)
    repo = VersionedRepository()
    service, repo, dispatcher = make_service(
        router=router, kit=make_kit(), voice=make_voice(), repo=repo, media=media
    )
    draft_id = repo.seed_draft(_gallery_brief())
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    return service, repo, media, (router, dispatcher, draft_id)


CUT_OUTCOME = MediaOutcome(
    media=(SLIDE_1, SLIDE_2),
    failure=FailureReason.PROVIDER_ERROR.value,
    detail=CUT,
)


def test_a_cut_gallery_fails_with_its_finished_slides_kept_and_says_so() -> None:
    service, repo, _media, (_router, _dispatcher, draft_id) = _failed_gallery(CUT_OUTCOME)

    draft = repo.drafts[draft_id]
    assert draft.status == FAILED and draft.failure_reason == "provider_error"
    assert draft.failure_detail == f"{CUT} " + GALLERY_KEPT_TEXT.format(done=2, total=3)
    # kept on the failed version: never shown as the piece
    ((revision, status, variants, media),) = repo.versions[draft_id]
    assert (revision, status) == (1, "failed")
    assert media == (SLIDE_1, SLIDE_2) and len(variants) == 1
    detail = service.get_draft(tenant_id=TENANT_ID, draft_id=draft_id)
    assert detail is not None and detail.kept_slides == 2 and detail.media == ()


def test_finishing_the_gallery_pays_only_the_missing_slide() -> None:
    done = MediaOutcome(media=(SLIDE_1, SLIDE_2, SLIDE_3))
    service, repo, media, (router, dispatcher, draft_id) = _failed_gallery(CUT_OUTCOME, done)
    winner = media.calls[0]["copy"]

    detail = service.finish_gallery(tenant_id=TENANT_ID, draft_id=draft_id, user_id=USER_ID)
    assert detail.status == DRAFTING and detail.revision == 2
    assert dispatcher.calls[-1] == (TENANT_ID, draft_id)

    # the dispatched run (FakeRouter has no copy answer left: a Claude call would fail it)
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    assert repo.drafts[draft_id].status == GENERATED
    assert router.script == []  # the copy was reused, not written (nor paid) again
    second = media.calls[1]
    assert second["copy"] == winner and second["revision"] == 2
    kept = second["kept_slides"]
    assert sorted(kept) == [0, 1]
    assert kept[0].object_key == SLIDE_1.object_key and kept[0].params[KEPT_FROM_REVISION] == 1
    shown = service.get_draft(tenant_id=TENANT_ID, draft_id=draft_id)
    assert shown is not None and len(shown.media) == 3 and shown.kept_slides == 0


def test_a_retry_that_fails_again_keeps_every_slide_for_the_next_one() -> None:
    nothing_new = MediaOutcome(failure=FailureReason.BUDGET_EXCEEDED.value, detail="Sin saldo.")
    service, repo, _media, (_r, _d, draft_id) = _failed_gallery(CUT_OUTCOME, nothing_new)
    service.finish_gallery(tenant_id=TENANT_ID, draft_id=draft_id, user_id=USER_ID)
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    assert repo.drafts[draft_id].status == FAILED
    revision, status, variants, media = repo.versions[draft_id][-1]
    assert (revision, status) == (2, "failed") and len(variants) == 1
    assert [m.object_key for m in media] == [SLIDE_1.object_key, SLIDE_2.object_key]
    detail = service.get_draft(tenant_id=TENANT_ID, draft_id=draft_id)
    assert detail is not None and detail.kept_slides == 2


def test_nothing_to_finish_is_refused_before_any_write() -> None:
    nothing_kept = MediaOutcome(failure=FailureReason.PROVIDER_ERROR.value, detail="No.")
    service, repo, _media, (_r, dispatcher, draft_id) = _failed_gallery(nothing_kept)
    assert repo.drafts[draft_id].failure_detail == "No."  # no promise of a retry
    calls = len(dispatcher.calls)
    with pytest.raises(NothingToFinish):
        service.finish_gallery(tenant_id=TENANT_ID, draft_id=draft_id, user_id=USER_ID)
    assert repo.drafts[draft_id].status == FAILED and repo.drafts[draft_id].revision == 1
    assert len(dispatcher.calls) == calls


def test_only_a_failed_draft_can_be_finished() -> None:
    done = MediaOutcome(media=(SLIDE_1, SLIDE_2, SLIDE_3))
    service, repo, _media, (_r, _d, draft_id) = _failed_gallery(done)
    assert repo.drafts[draft_id].status == GENERATED
    with pytest.raises(InvalidTransition):
        service.finish_gallery(tenant_id=TENANT_ID, draft_id=draft_id, user_id=USER_ID)


def test_the_copy_of_a_kept_attempt_must_have_passed() -> None:
    attempt = FailedAttempt(
        revision=1,
        variants=(VariantWrite(0, {"hook": "x"}, {"passed": False}, "claude", None),),
        slides=(SLIDE_1,),
    )
    assert attempt.copy_passed is False


def test_another_version_after_a_restore_never_reuses_the_failed_attempt() -> None:
    """Review #2: a failed gallery (revision 1, two slides kept), «Usar esta versión» on an
    older version (revision 2, no version row), then «Pedir otra versión» (revision 3).
    Only the revision «Crear las que faltan» stamps may reuse the failed attempt: this one
    writes new copy and makes every slide again."""
    done = MediaOutcome(media=(SLIDE_1, SLIDE_2, SLIDE_3))
    service, repo, media, (router, _dispatcher, draft_id) = _failed_gallery(CUT_OUTCOME, done)
    router.script.append(ok_outcome(copy_dict("Smash triple")))  # the new copy, paid
    # «Usar esta versión»: the restore bumps the revision and writes no version row
    repo.drafts[draft_id] = replace(repo.drafts[draft_id], revision=2, status=GENERATED)

    service.reject(
        tenant_id=TENANT_ID, draft_id=draft_id, reason="otra", user_id=USER_ID, regenerate=True
    )
    if repo.drafts[draft_id].revision == 2:  # Postgres bumps it on the regenerate edge
        repo.drafts[draft_id] = replace(repo.drafts[draft_id], revision=3)
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    assert router.script == []  # the copy was written again
    second = media.calls[1]
    assert not second.get("kept_slides")
    assert repo.resumes == {}


def test_the_resume_stamp_is_only_on_the_revision_finish_creates() -> None:
    done = MediaOutcome(media=(SLIDE_1, SLIDE_2, SLIDE_3))
    service, repo, _media, (_r, _d, draft_id) = _failed_gallery(CUT_OUTCOME, done)
    service.finish_gallery(tenant_id=TENANT_ID, draft_id=draft_id, user_id=USER_ID)
    assert repo.resumes == {(draft_id, 2): GalleryResume(kept_revision=1)}


def test_the_missing_slides_use_the_galleries_own_prompt_compiler() -> None:
    """Founder, 2026-11-03: «Crear las que faltan» compiles the missing slides with the
    compiler version the kept ones were made with, not today's."""
    kept = tuple(
        replace(s, params={**s.params, "prompt_compiler_version": 2}) for s in (SLIDE_1, SLIDE_2)
    )
    cut = replace(CUT_OUTCOME, media=kept)
    done = MediaOutcome(media=(*kept, SLIDE_3))

    class StampingMedia(ScriptedMedia):
        def prepare_new_brief(self, brief, kit):  # noqa: ANN001, ANN201
            return brief.model_copy(
                update={"media": brief.media.model_copy(update={"prompt_compiler_version": 3})}
            )

    router = FakeRouter([ok_outcome(copy_dict("Smash doble"))])
    media = StampingMedia(cut, done)
    repo = VersionedRepository()
    service, repo, _dispatcher = make_service(
        router=router, kit=make_kit(), voice=make_voice(), repo=repo, media=media
    )
    draft_id = repo.seed_draft(_gallery_brief())
    repo.drafts[draft_id] = replace(
        repo.drafts[draft_id], pipeline_version=BRAND_APPLIED_PIPELINE_VERSION
    )
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert media.calls[0]["brief"].media.prompt_compiler_version == 3
    service.finish_gallery(tenant_id=TENANT_ID, draft_id=draft_id, user_id=USER_ID)
    assert repo.resumes[(draft_id, 2)].prompt_compiler_version == 2
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert media.calls[1]["brief"].media.prompt_compiler_version == 2
