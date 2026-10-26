"""Approving a version with Seedance 2.5 draft videos (m-24820142): the approval orders
the finals (or is refused, with nothing written, when a draft expired), `run_finalize`
puts each final in place of its draft and records its own spend, a failed final can be
ordered again. Same in-memory repository as `test_content_service.py`."""

from __future__ import annotations

import time
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.creative.draft_mode import (
    DRAFT_FAILED,
    DRAFT_FINAL,
    DRAFT_READY,
    DRAFT_RENDERING,
    FINAL_NOT_ORDERED_TEXT,
    FINAL_STALE_SECONDS,
    draft_state,
)
from qualify_api.creative.fsm import APPROVED, InvalidTransition
from qualify_api.creative.media import FinalOutcome, MediaUsage, MediaWrite
from qualify_api.creative.service import (
    ContentService,
    DraftExpired,
    ImageRecord,
)

from .test_content_service import (
    TENANT_ID,
    USER_ID,
    FakeRouter,
    InMemoryRepository,
    RecordingDispatcher,
    _generated_draft_with_variant,
    copy_dict,
    make_kit,
    make_service,
    make_voice,
    ok_outcome,
)


class FinalRepository(InMemoryRepository):
    def set_video_draft(self, *, tenant_id, asset_id, changes):  # noqa: ANN001, ANN201
        for draft_id, items in self.media.items():
            self.media[draft_id] = [
                replace(
                    item,
                    params={
                        **(item.params or {}),
                        "draft": {**draft_state(item.params), **changes},
                    },
                )
                if item.id == asset_id
                else item
                for item in items
            ]

    def _block(self, asset_id: UUID) -> dict[str, Any]:
        for items in self.media.values():
            for item in items:
                if item.id == asset_id:
                    return dict(draft_state(item.params) or {})
        return {}

    def claim_final(self, *, tenant_id, asset_id, attempt, claim):  # noqa: ANN001, ANN201
        block = self._block(asset_id)
        if (
            block.get("status") != DRAFT_RENDERING
            or block.get("attempt") != attempt
            or block.get("claim")
        ):
            return False
        self.set_video_draft(
            tenant_id=tenant_id,
            asset_id=asset_id,
            changes={"claim": claim, "rendering_at": time.time()},
        )
        return True

    def _held(self, asset_id: UUID, claim: str | None) -> bool:
        block = self._block(asset_id)
        return block.get("status") == DRAFT_RENDERING and block.get("claim") == claim

    def fail_final(self, *, tenant_id, asset_id, claim, error):  # noqa: ANN001, ANN201
        if self._held(asset_id, claim):
            self.set_video_draft(
                tenant_id=tenant_id,
                asset_id=asset_id,
                changes={"status": DRAFT_FAILED, "error": error},
            )

    def settle_final(
        self,
        *,
        tenant_id,  # noqa: ANN001
        draft_id,  # noqa: ANN001
        brand_id,  # noqa: ANN001
        asset_id,  # noqa: ANN001
        media,  # noqa: ANN001
        error,  # noqa: ANN001
        usage,  # noqa: ANN001
        spent_usd,  # noqa: ANN001
        claim=None,  # noqa: ANN001
        draft_changes=None,  # noqa: ANN001
    ):  # noqa: ANN201
        self.usage.extend(usage)
        self.spend_added += spent_usd
        if claim is not None and not self._held(asset_id, claim):
            return
        if media is None:
            self.set_video_draft(
                tenant_id=tenant_id,
                asset_id=asset_id,
                changes={**(draft_changes or {}), "status": DRAFT_FAILED, "error": error},
            )
            return
        self.media[draft_id] = [
            replace(
                item,
                media_url=media.media_url,
                object_key=media.object_key,
                width=media.width,
                height=media.height,
                params=media.params,
            )
            if item.id == asset_id
            else item
            for item in self.media[draft_id]
        ]


class FinalDispatcher(RecordingDispatcher):
    def __init__(self) -> None:
        super().__init__()
        self.finals: list[tuple[UUID, UUID]] = []

    def dispatch_finalize(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        self.finals.append((tenant_id, draft_id))


class FakeFinals:
    """The media producer's `finalize`, scripted: the final, or a failure."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[ImageRecord] = []

    def finalize(self, *, asset, **_: Any) -> FinalOutcome:  # noqa: ANN001
        self.calls.append(asset)
        usage = (
            MediaUsage(
                provider="seedance",
                model_id="dreamina-seedance-2-5-260628",
                unit="second",
                quantity=5,
                cost_usd=Decimal("2.84"),
            ),
        )
        if self.fail:
            return FinalOutcome(usage=(), failure="provider_error", detail="ModelArk falló.")
        return FinalOutcome(
            media=MediaWrite(
                position=asset.position,
                media_type="video",
                media_url="t/x/final.mp4",
                object_key="t/x/final.mp4",
                width=1080,
                height=1920,
                aspect_ratio="9:16",
                model_id="dreamina-seedance-2-5-260628",
                provider="seedance",
                params={**asset.params, "draft": {**asset.params["draft"], "status": DRAFT_FINAL}},
            ),
            usage=usage,
        )


def _draft_video(created_at: float | None = None, status: str = DRAFT_READY) -> ImageRecord:
    return ImageRecord(
        id=uuid4(),
        media_url="t/x/clip.mp4",
        width=480,
        height=854,
        aspect_ratio="9:16",
        media_type="video",
        params={
            "draft": {
                "status": status,
                "task_id": "cgt-draft",
                "created_at": time.time() if created_at is None else created_at,
                "model": "dreamina-seedance-2-5-260628",
            }
        },
        object_key="t/x/clip.mp4",
    )


def _setup(
    *, finals: FakeFinals | None = None, video: ImageRecord | None = None
) -> tuple[ContentService, FinalRepository, FinalDispatcher, UUID, UUID, FakeFinals]:
    finals = finals or FakeFinals()
    repo, dispatcher = FinalRepository(), FinalDispatcher()
    service, _, _ = make_service(
        router=FakeRouter([ok_outcome(copy_dict())]),
        kit=make_kit(),
        voice=make_voice(),
        repo=repo,
        dispatcher=dispatcher,
    )
    draft_id, variant_id = _generated_draft_with_variant(service, repo)
    repo.media[draft_id] = [video or _draft_video()]
    service._media = finals  # type: ignore[assignment]
    return service, repo, dispatcher, draft_id, variant_id, finals


def _status(repo: FinalRepository, draft_id: UUID) -> str:
    (video,) = repo.media[draft_id]
    return str(draft_state(video.params)["status"])


def test_approving_a_draft_video_orders_its_final() -> None:
    service, repo, dispatcher, draft_id, variant_id, _ = _setup()

    detail = service.approve(
        tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID
    )

    assert detail.status == APPROVED
    assert _status(repo, draft_id) == DRAFT_RENDERING
    assert dispatcher.finals == [(TENANT_ID, draft_id)]


def test_approving_without_draft_videos_orders_nothing() -> None:
    plain = replace(_draft_video(), params={"resolution": "720p"})
    service, _, dispatcher, draft_id, variant_id, _ = _setup(video=plain)
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    assert dispatcher.finals == []


def test_an_expired_draft_refuses_the_approval_before_any_write() -> None:
    service, repo, dispatcher, draft_id, variant_id, _ = _setup(video=_draft_video(created_at=1))

    with pytest.raises(DraftExpired) as excinfo:
        service.approve(
            tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID
        )

    assert "duran 7 días" in excinfo.value.detail
    assert repo.drafts[draft_id].status != APPROVED
    assert _status(repo, draft_id) == DRAFT_READY and dispatcher.finals == []


def test_run_finalize_puts_the_final_in_place_and_records_its_spend() -> None:
    service, repo, _, draft_id, variant_id, finals = _setup()
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    spent_before = repo.spend_added

    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)

    (video,) = repo.media[draft_id]
    assert video.object_key == "t/x/final.mp4" and (video.width, video.height) == (1080, 1920)
    assert _status(repo, draft_id) == DRAFT_FINAL
    assert repo.spend_added - spent_before == Decimal("2.84")
    assert repo.usage[-1].model_id == "dreamina-seedance-2-5-260628"
    # idempotent: nothing left in `rendering`, a second run does nothing
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert len(finals.calls) == 1


def test_a_failed_final_keeps_the_approved_version_and_can_be_ordered_again() -> None:
    service, repo, dispatcher, draft_id, variant_id, finals = _setup(finals=FakeFinals(fail=True))
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)

    (video,) = repo.media[draft_id]
    assert _status(repo, draft_id) == DRAFT_FAILED
    assert draft_state(video.params)["error"] == "ModelArk falló."
    assert video.object_key == "t/x/clip.mp4"  # the draft stays
    assert repo.drafts[draft_id].status == APPROVED

    finals.fail = False
    service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _status(repo, draft_id) == DRAFT_RENDERING
    assert dispatcher.finals == [(TENANT_ID, draft_id)] * 2
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _status(repo, draft_id) == DRAFT_FINAL


def test_an_unexpected_error_never_leaves_the_video_rendering() -> None:
    class Exploding(FakeFinals):
        def finalize(self, **_: Any) -> FinalOutcome:
            raise RuntimeError("boom")

    service, repo, _, draft_id, variant_id, _ = _setup(finals=Exploding())
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _status(repo, draft_id) == DRAFT_FAILED


def test_retry_refuses_an_expired_draft_and_an_unapproved_piece() -> None:
    expired = _draft_video(created_at=1, status=DRAFT_FAILED)
    service, repo, _, draft_id, _, _ = _setup(video=expired)
    with pytest.raises(InvalidTransition):
        service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)
    repo.drafts[draft_id] = replace(repo.drafts[draft_id], status=APPROVED)
    with pytest.raises(DraftExpired):
        service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)


def test_retry_orders_the_live_finals_and_marks_only_the_expired_ones() -> None:
    """Review round 4: one expired draft in a carousel used to block retrying the
    finals whose drafts still live."""
    from qualify_api.creative.draft_mode import DRAFT_EXPIRED_TEXT

    service, repo, dispatcher, draft_id, _, _ = _setup()
    expired = _draft_video(created_at=1, status=DRAFT_FAILED)
    live = replace(_draft_video(status=DRAFT_FAILED), position=1)
    repo.media[draft_id] = [expired, live]
    repo.drafts[draft_id] = replace(repo.drafts[draft_id], status=APPROVED)

    service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)

    assert dispatcher.finals == [(TENANT_ID, draft_id)]
    gone, ordered = (draft_state(video.params) for video in repo.media[draft_id])
    assert gone["status"] == DRAFT_FAILED and gone["error"] == DRAFT_EXPIRED_TEXT
    assert "attempt" not in gone  # never ordered
    assert ordered["status"] == DRAFT_RENDERING and ordered["attempt"]


def test_a_final_left_rendering_by_a_dead_process_can_be_ordered_again() -> None:
    stale = _draft_video(status=DRAFT_RENDERING)
    stale = replace(
        stale,
        params={
            "draft": {**stale.params["draft"], "rendering_at": time.time() - FINAL_STALE_SECONDS}
        },
    )
    fresh = _draft_video(status=DRAFT_RENDERING)
    fresh = replace(fresh, params={"draft": {**fresh.params["draft"], "rendering_at": time.time()}})
    for video, ordered in ((stale, True), (fresh, False)):
        service, repo, dispatcher, draft_id, _, _ = _setup(video=video)
        repo.drafts[draft_id] = replace(repo.drafts[draft_id], status=APPROVED)
        service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)
        assert bool(dispatcher.finals) is ordered


# -- review fixes: one final per order, every claimed video ends final or failed -------


def _two_videos(
    finals: FakeFinals,
) -> tuple[ContentService, FinalRepository, FinalDispatcher, UUID, UUID]:
    service, repo, dispatcher, draft_id, variant_id, _ = _setup(finals=finals)
    repo.media[draft_id] = [_draft_video(), replace(_draft_video(), position=1)]
    return service, repo, dispatcher, draft_id, variant_id


def _statuses(repo: FinalRepository, draft_id: UUID) -> list[str]:
    return [str(draft_state(video.params)["status"]) for video in repo.media[draft_id]]


def test_a_concurrent_run_never_makes_the_same_final_twice() -> None:
    class Reentrant(FakeFinals):
        """While making the first final, a second run of the same draft starts (a
        retry's thread, or a duplicated dispatch)."""

        service: ContentService
        draft_id: UUID
        nested = False

        def finalize(self, *, asset, **kwargs: Any) -> FinalOutcome:  # noqa: ANN001
            if not self.nested:
                self.nested = True
                self.service.run_finalize(tenant_id=TENANT_ID, draft_id=self.draft_id)
            return super().finalize(asset=asset, **kwargs)

    finals = Reentrant()
    service, repo, _, draft_id, variant_id = _two_videos(finals)
    finals.service, finals.draft_id = service, draft_id
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    spent_before = repo.spend_added

    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)

    assert sorted(call.position for call in finals.calls) == [0, 1]  # each video once
    assert _statuses(repo, draft_id) == [DRAFT_FINAL, DRAFT_FINAL]
    assert repo.spend_added - spent_before == Decimal("5.68")


def test_a_run_never_makes_a_final_ordered_again_after_it_read_it() -> None:
    """The second video waits behind the first in an old run; it goes stale and the
    operator orders it again: the old run skips it, the new run makes it, once."""

    class Slow(FakeFinals):
        service: ContentService
        repo: FinalRepository
        draft_id: UUID

        def finalize(self, *, asset, **kwargs: Any) -> FinalOutcome:  # noqa: ANN001
            if asset.position == 0 and not self.calls:
                second = self.repo.media[self.draft_id][1]
                self.repo.set_video_draft(
                    tenant_id=TENANT_ID,
                    asset_id=second.id,
                    changes={"rendering_at": time.time() - FINAL_STALE_SECONDS},
                )
                self.service.retry_final(tenant_id=TENANT_ID, draft_id=self.draft_id)
            return super().finalize(asset=asset, **kwargs)

    finals = Slow()
    service, repo, dispatcher, draft_id, variant_id = _two_videos(finals)
    finals.service, finals.repo, finals.draft_id = service, repo, draft_id
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)

    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)  # the old run
    assert [call.position for call in finals.calls] == [0]
    assert _statuses(repo, draft_id) == [DRAFT_FINAL, DRAFT_RENDERING]
    assert len(dispatcher.finals) == 2

    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)  # the retry's run
    assert [call.position for call in finals.calls] == [0, 1]
    assert _statuses(repo, draft_id) == [DRAFT_FINAL, DRAFT_FINAL]


def test_retry_does_not_order_again_a_final_still_rendering() -> None:
    service, repo, _, draft_id, variant_id = _two_videos(FakeFinals())
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    first, second = repo.media[draft_id]
    repo.set_video_draft(tenant_id=TENANT_ID, asset_id=first.id, changes={"status": DRAFT_FAILED})
    attempt = draft_state(second.params)["attempt"]

    service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)

    assert _statuses(repo, draft_id) == [DRAFT_RENDERING, DRAFT_RENDERING]
    assert draft_state(repo.media[draft_id][1].params)["attempt"] == attempt  # untouched
    assert draft_state(repo.media[draft_id][0].params)["attempt"] != attempt


def test_a_final_settled_after_it_was_ordered_again_keeps_only_its_spend() -> None:
    class Overtaken(FakeFinals):
        repo: FinalRepository

        def finalize(self, *, asset, **kwargs: Any) -> FinalOutcome:  # noqa: ANN001
            # the thread looked dead: the operator ordered the final again meanwhile
            self.repo.set_video_draft(
                tenant_id=TENANT_ID,
                asset_id=asset.id,
                changes={"attempt": "new", "claim": None},
            )
            return super().finalize(asset=asset, **kwargs)

    finals = Overtaken()
    service, repo, _, draft_id, variant_id, _ = _setup(finals=finals)
    finals.repo = repo
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    spent_before = repo.spend_added

    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)

    assert repo.spend_added - spent_before == Decimal("2.84")  # the money went
    (video,) = repo.media[draft_id]
    assert video.object_key == "t/x/clip.mp4"  # the new order owns the row
    assert _status(repo, draft_id) == DRAFT_RENDERING


def test_an_unreadable_draft_fails_its_finals_instead_of_leaving_them_rendering() -> None:
    service, repo, _, draft_id, variant_id, finals = _setup()
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)

    def boom(**_: Any) -> None:
        raise RuntimeError("db down")

    repo.get_brief = boom  # type: ignore[method-assign]
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)

    assert _status(repo, draft_id) == DRAFT_FAILED and finals.calls == []


def test_a_final_that_cannot_be_saved_still_records_its_spend() -> None:
    service, repo, _, draft_id, variant_id, _ = _setup()
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    settle = repo.settle_final

    def media_write_fails(**kwargs: Any) -> None:
        if kwargs["media"] is not None:
            raise RuntimeError("row too big")
        settle(**kwargs)

    repo.settle_final = media_write_fails  # type: ignore[method-assign]
    spent_before = repo.spend_added
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)

    assert repo.spend_added - spent_before == Decimal("2.84")
    (video,) = repo.media[draft_id]
    assert _status(repo, draft_id) == DRAFT_FAILED
    assert "guardar" in draft_state(video.params)["error"]


def test_a_final_whose_every_save_fails_is_still_marked_failed() -> None:
    service, repo, _, draft_id, variant_id, _ = _setup()
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)

    def always_fails(**_: Any) -> None:
        raise RuntimeError("db down")

    repo.settle_final = always_fails  # type: ignore[method-assign]
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _status(repo, draft_id) == DRAFT_FAILED


# -- review 2026-10-23 -------------------------------------------------------------------


def test_approving_reads_the_media_rows_once() -> None:
    """The approval reads only the draft videos (filtered in SQL) before approving; the
    piece's every media row is read once, for the detail it returns."""
    service, repo, _, draft_id, variant_id, _ = _setup()
    repo.media_reads = repo.draft_video_reads = 0

    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)

    assert repo.draft_video_reads == 1 and repo.media_reads == 1


def test_an_approval_whose_finals_could_not_be_ordered_can_order_them_again() -> None:
    """The approval is saved first; when ordering the finals then fails the piece is
    approved with its video still at its draft — `retry_final` orders it."""
    service, repo, dispatcher, draft_id, variant_id, _ = _setup()
    set_video_draft = repo.set_video_draft

    def down(**_: Any) -> None:
        raise RuntimeError("db down")

    repo.set_video_draft = down  # type: ignore[method-assign]
    detail = service.approve(
        tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID
    )
    assert detail.status == APPROVED
    assert _status(repo, draft_id) == DRAFT_READY and dispatcher.finals == []

    repo.set_video_draft = set_video_draft  # type: ignore[method-assign]
    service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)

    assert _status(repo, draft_id) == DRAFT_RENDERING
    assert dispatcher.finals == [(TENANT_ID, draft_id)]


def test_a_final_that_could_not_be_dispatched_shows_as_failed_at_once() -> None:
    service, repo, dispatcher, draft_id, variant_id, _ = _setup()

    def refuse(**_: Any) -> None:
        raise RuntimeError("queue down")

    dispatcher.dispatch_finalize = refuse  # type: ignore[method-assign]
    detail = service.approve(
        tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID
    )

    assert detail.status == APPROVED
    (video,) = repo.media[draft_id]
    block = draft_state(video.params)
    assert block["status"] == DRAFT_FAILED and block["error"] == FINAL_NOT_ORDERED_TEXT


def test_a_failed_final_keeps_its_paid_raw_file_for_the_retry() -> None:
    raw = {"key": "t/x/clip-final-raw.mp4", "cost_usd": "2.84", "task_id": "cgt-final"}

    class RawLeft(FakeFinals):
        def finalize(self, *, asset, **_: Any) -> FinalOutcome:  # noqa: ANN001
            self.calls.append(asset)
            return FinalOutcome(
                failure="provider_error",
                detail="No se pudo recodificar.",
                draft_changes={"raw_final": raw},
            )

    service, repo, _, draft_id, variant_id, _ = _setup(finals=RawLeft())
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)

    (video,) = repo.media[draft_id]
    block = draft_state(video.params)
    assert block["status"] == DRAFT_FAILED and block["raw_final"] == raw


# -- review round 3 (m-24820142) -----------------------------------------------------------


class RawThenFinal(FakeFinals):
    """Keeps the paid raw 1080p (heard at once, like `MediaProducer.finalize`), then
    returns the final — carrying the raw file in `draft_changes`, as the producer does."""

    raw = {"key": "t/x/clip-final-raw.mp4", "cost_usd": "2.84", "task_id": "cgt-final"}

    def finalize(self, *, asset, on_raw_kept=None, **kwargs: Any) -> FinalOutcome:  # noqa: ANN001
        assert on_raw_kept is not None
        on_raw_kept(self.raw)
        outcome = super().finalize(asset=asset, **kwargs)
        return replace(outcome, draft_changes={"raw_final": self.raw})


def test_the_raw_final_is_in_the_draft_block_before_the_final_is_settled() -> None:
    finals = RawThenFinal()
    service, repo, _, draft_id, variant_id, _ = _setup(finals=finals)
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)

    def dead(**_: Any) -> None:  # the process died: no write ever lands
        raise RuntimeError("db down")

    repo.settle_final = dead  # type: ignore[method-assign]
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)

    (video,) = repo.media[draft_id]
    assert draft_state(video.params)["raw_final"] == RawThenFinal.raw


def test_a_final_that_could_not_be_put_in_place_keeps_its_raw_file() -> None:
    """Success, then the write of the final fails: the failure written instead keeps the
    raw file (`draft_changes` rides on success too), so the retry pays nothing."""
    finals = RawThenFinal()
    service, repo, _, draft_id, variant_id, _ = _setup(finals=finals)
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    # the early write is lost too: only `draft_changes` can carry the raw file now
    repo_set = repo.set_video_draft

    def early_write_lost(**kwargs: Any) -> None:
        if "raw_final" in kwargs["changes"] and len(kwargs["changes"]) == 1:
            raise RuntimeError("db hiccup")
        repo_set(**kwargs)

    repo.set_video_draft = early_write_lost  # type: ignore[method-assign]
    settle = repo.settle_final

    def media_write_fails(**kwargs: Any) -> None:
        if kwargs["media"] is not None:
            raise RuntimeError("row too big")
        settle(**kwargs)

    repo.settle_final = media_write_fails  # type: ignore[method-assign]
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)

    (video,) = repo.media[draft_id]
    block = draft_state(video.params)
    assert block["status"] == DRAFT_FAILED and block["raw_final"] == RawThenFinal.raw


def test_the_final_poll_reads_only_the_draft_row_and_its_draft_videos() -> None:
    service, repo, _, draft_id, variant_id, _ = _setup()
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    repo.media_reads = repo.draft_video_reads = 0

    status, params = service.video_drafts_state(tenant_id=TENANT_ID, draft_id=draft_id)

    assert status == APPROVED and repo.media_reads == 0 and repo.draft_video_reads == 1
    (block,) = (draft_state(p) for p in params)
    assert block["status"] == DRAFT_RENDERING
    assert service.video_drafts_state(tenant_id=TENANT_ID, draft_id=uuid4()) is None


def test_retry_refuses_an_uncertain_final_without_dispatching_another_paid_task() -> None:
    from qualify_creative.queue_errors import UNCERTAIN_REASON, UNCERTAIN_VIDEO_TEXT

    service, repo, dispatcher, draft_id, variant_id, _ = _setup()
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    dispatcher.finals.clear()
    asset = repo.media[draft_id][0]
    repo.set_video_draft(
        tenant_id=TENANT_ID,
        asset_id=asset.id,
        changes={
            "status": DRAFT_FAILED,
            "error": UNCERTAIN_VIDEO_TEXT,
            "failure_reason": UNCERTAIN_REASON,
        },
    )
    with pytest.raises(InvalidTransition, match="equipo debe revisarlo"):
        service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)
    assert dispatcher.finals == []
