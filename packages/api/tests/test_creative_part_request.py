"""m-24921081 (UI-6 «Revisa y crea» por partes): only the first part, the parts left later,
the owner's ask kept on the parent and made by the worker, and the vistas previas read
before the parent exists. In memory, offline."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import ContentBrief, MediaInputs, PartsRequest, VideoPartPlan

from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.fsm import DRAFTING, FAILED
from qualify_api.creative.part_final import NOT_READY, approval_problem
from qualify_api.creative.part_request import (
    PartsRequests,
    parts_preview_use,
    refusal_of,
)
from qualify_api.creative.parts import (
    PLANNED,
    PartNeedsDescription,
    PartNeedsPrevious,
    PartsExtendUnavailable,
    PartsService,
    PartsUnavailable,
)
from qualify_api.creative.service import UnknownDraft

from .test_content_service import BRAND_ID, TENANT_ID, USER_ID, make_brief
from .test_creative_part_final import TENANT, _part, _snapshot
from .test_creative_parts import (
    PartsRepository,
    _children,
    _part_rows,
    world,
)

AT = datetime(2026, 11, 9, 12, tzinfo=UTC)


class MemoryStore:
    """The `PartsRequestStore` double: the ask lives on the parent's brief, in place."""

    def __init__(self, repo: PartsRepository, *, requester: UUID | None = USER_ID) -> None:
        self.repo = repo
        self.who = requester
        self.records: list[PartsRequest] = []

    def requester(self, *, tenant_id: UUID, parent_id: UUID) -> UUID | None:
        return self.who

    def _stored(self, parent_id: UUID) -> PartsRequest | None:
        return self.repo.briefs[self.repo.drafts[parent_id].brief_id].media.parts_request

    def _keep(self, parent_id: UUID, request: PartsRequest) -> None:
        draft = self.repo.drafts[parent_id]
        brief = self.repo.briefs[draft.brief_id]
        media = brief.media.model_copy(update={"parts_request": request})
        self.repo.briefs[draft.brief_id] = brief.model_copy(update={"media": media})

    def begin(self, *, tenant_id: UUID, parent_id: UUID) -> int | None:
        if parent_id not in self.repo.drafts:
            return None
        stored = self._stored(parent_id) or PartsRequest()
        self._keep(parent_id, stored.model_copy(update={"attempt": stored.attempt + 1}))
        return stored.attempt + 1

    def record(
        self, *, tenant_id: UUID, parent_id: UUID, request: PartsRequest
    ) -> PartsRequest | None:
        stored = self._stored(parent_id)
        if (0 if stored is None else stored.attempt) != request.attempt:
            return None  # the same guard as the Postgres store: a later attempt started
        kept = request.model_copy(update={"attempted_at": AT})  # the store's own clock
        self._keep(parent_id, kept)
        self.records.append(kept)
        return kept

    def fail(self, *, tenant_id: UUID, parent_id: UUID, attempt: int) -> bool:
        stored = self._stored(parent_id)
        if stored is None or stored.attempt != attempt:
            return False  # the same guard as the Postgres store
        self._keep(
            parent_id,
            stored.model_copy(update={"attempt": max(attempt, 1), "refused": "error"}),
        )
        return True


def requests(parts: PartsService, content: object, repo: PartsRepository) -> PartsRequests:
    return PartsRequests(
        content,  # type: ignore[arg-type]
        parts=parts,
        store=MemoryStore(repo),
        analysis_of=lambda tenant_id, brief: None,
    )


def _asked(repo: PartsRepository, parent: UUID) -> PartsRequest | None:
    return repo.briefs[repo.drafts[parent].brief_id].media.parts_request


def _previews(ledger: object) -> int:
    return ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# create_parts over some parts


def test_only_the_first_part_uses_one_preview_and_leaves_the_rest_unmade() -> None:
    parts, _, repo, ledger, dispatcher, _, parent = world()
    (first,) = parts.create_parts(
        tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=(1,)
    )
    children = _children(repo, parent)
    assert [c.part_index for c in children] == [1] and children[0].id == first
    assert _previews(ledger) == 1 and dispatcher.calls == [(TENANT_ID, first)]
    shown = parts.parts(tenant_id=TENANT_ID, parent_id=parent)
    assert [p.status for p in shown[1:]] == [PLANNED] * 3 and shown[0].draft_id == first
    # asked again: the same part, nothing charged nor queued twice
    rows, calls = dict(ledger.rows), list(dispatcher.calls)
    again = parts.create_parts(
        tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=(1,)
    )
    assert again == [first] and ledger.rows == rows and dispatcher.calls == calls


def test_the_parts_left_are_created_later_all_or_one() -> None:
    parts, _, repo, ledger, dispatcher, _, parent = world()
    (first,) = parts.create_parts(
        tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=(1,)
    )
    (third,) = parts.create_parts(
        tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=(3,)
    )
    assert [c.part_index for c in _children(repo, parent)] == [1, 3]
    every = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    children = _children(repo, parent)
    assert [c.part_index for c in children] == [1, 2, 3, 4]
    assert every == [c.id for c in children] and every[0] == first and every[2] == third
    rows = _part_rows(ledger, every)
    assert sorted(rows) == sorted((child, 1) for child in every)  # one charge each
    assert _previews(ledger) == 4 and len(dispatcher.calls) == 4


def test_the_parts_asked_for_are_all_or_none() -> None:
    parts, _, repo, ledger, dispatcher, _, parent = world(previews_used=18)  # 2 left
    parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=(1,))
    rows, calls = dict(ledger.rows), list(dispatcher.calls)
    with pytest.raises(NotEnoughCreations) as short:
        parts.create_parts(
            tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=(2, 3)
        )
    assert short.value.missing_previews == 1
    assert [c.part_index for c in _children(repo, parent)] == [1]
    assert ledger.rows == rows and dispatcher.calls == calls


def test_extend_plan_makes_neither_one_nor_both_until_continuity_is_available() -> None:
    plan = (
        VideoPartPlan(seconds=5, description="La hamburguesa."),
        VideoPartPlan(seconds=5, description="Sigue la hamburguesa.", mode="extend"),
    )
    parts, _, repo, ledger, _, _, parent = world(plan=plan)
    for indexes in ((1,), (2,), (1, 2)):
        with pytest.raises(PartsExtendUnavailable):
            parts.create_parts(
                tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=indexes
            )
    assert _children(repo, parent) == [] and _previews(ledger) == 0


def test_a_part_outside_the_plan_is_unknown() -> None:
    parts, _, repo, _, _, _, parent = world()
    for asked in ((5,), (0,), ()):
        with pytest.raises(UnknownDraft):
            parts.create_parts(
                tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=asked
            )
    assert _children(repo, parent) == []


def test_the_whole_video_is_not_approved_while_a_part_is_unmade() -> None:
    made = (_part(1), _part(2))
    assert approval_problem(_snapshot(*made), TENANT) is None
    missing = replace(_snapshot(*made), planned=3)
    assert approval_problem(missing, TENANT) == NOT_READY


# ---------------------------------------------------------------------------
# the owner's ask, kept on the parent and made by the worker


def test_the_ask_is_only_for_a_video_by_parts_and_never_reaches_a_part() -> None:
    with pytest.raises(ValidationError):
        make_brief(kind=ContentKind.CLIP, media=MediaInputs(parts_request=PartsRequest()))
    parts, _, repo, _, _, _, parent = world(media={"parts_request": PartsRequest(scope="first")})
    parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=(1,))
    (child,) = _children(repo, parent)
    child_brief: ContentBrief = repo.briefs[child.brief_id]
    assert child_brief.media.parts_request is None
    assert _asked(repo, parent) == PartsRequest(scope="first")


def test_the_worker_creates_only_the_first_part_when_asked_so() -> None:
    parts, content, repo, ledger, dispatcher, _, parent = world(
        media={"parts_request": PartsRequest(scope="first")}
    )
    asks = requests(parts, content, repo)
    stored = asks.after_generation(tenant_id=TENANT_ID, parent_id=parent)
    assert [c.part_index for c in _children(repo, parent)] == [1] and _previews(ledger) == 1
    assert stored == _asked(repo, parent)
    assert stored is not None and stored.refused is None and stored.attempted_parts == (1,)
    assert stored.scope == "first" and stored.attempted_at == AT and stored.attempt == 1
    # the hook again (a regenerated text, a retry): nothing more made nor charged
    rows, calls = dict(ledger.rows), list(dispatcher.calls)
    asks.after_generation(tenant_id=TENANT_ID, parent_id=parent)
    assert ledger.rows == rows and dispatcher.calls == calls


def test_the_worker_creates_every_part_when_asked_so() -> None:
    parts, content, repo, ledger, _, _, parent = world(media={"parts_request": PartsRequest()})
    stored = requests(parts, content, repo).after_generation(tenant_id=TENANT_ID, parent_id=parent)
    assert len(_children(repo, parent)) == 4 and _previews(ledger) == 4
    # m-24993031: «all» spells out the parts it asked for, as «first» does
    assert stored is not None and stored.refused is None and stored.attempted_parts == (1, 2, 3, 4)


def test_the_parts_left_are_kept_spelled_out_without_the_removed_ones() -> None:
    """m-24993031: «Crear las que faltan» (no indexes) keeps the plan minus the parts
    the owner removed — the same parts `create_parts` reads and returns."""
    parts, content, repo, _, _, _, parent = world(
        media={"parts_request": PartsRequest(scope="first")}
    )
    asks = requests(parts, content, repo)
    asks.after_generation(tenant_id=TENANT_ID, parent_id=parent)
    (first,) = _children(repo, parent)
    repo.mark_part_removed(tenant_id=TENANT_ID, draft_id=first.id, user_id=USER_ID)
    ids = asks.request_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    asked = _asked(repo, parent)
    assert asked is not None and asked.refused is None and asked.attempted_parts == (2, 3, 4)
    assert len(ids) == 3


def test_an_outcome_kept_before_the_fix_still_reads() -> None:
    """m-24993031: outcomes stored with an empty `attempted_parts` (the old «all») parse
    as they were; nothing reads the empty tuple as a meaning of its own."""
    old = PartsRequest.model_validate(
        {"scope": "all", "refused": None, "attempted_parts": [], "attempt": 1}
    )
    assert old.attempted_parts == () and old.scope == "all" and old.attempt == 1


def test_a_refusal_is_kept_for_the_result_screen_and_nothing_is_charged() -> None:
    parts, content, repo, ledger, dispatcher, _, parent = world(
        previews_used=17, media={"parts_request": PartsRequest()}
    )
    stored = requests(parts, content, repo).after_generation(tenant_id=TENANT_ID, parent_id=parent)
    assert stored is not None and stored.refused == "not_enough_previews" and stored.missing == 1
    assert stored.attempted_parts == (1, 2, 3, 4)  # what the refused attempt asked for
    assert _asked(repo, parent) == stored
    assert _children(repo, parent) == [] and _previews(ledger) == 17 and dispatcher.calls == []


def test_a_part_to_describe_is_named_in_the_kept_refusal() -> None:
    plan = (VideoPartPlan(seconds=5), VideoPartPlan(seconds=5, notices=("describe_it",)))
    parts, content, repo, _, _, _, parent = world(
        plan=plan, media={"parts_request": PartsRequest()}
    )
    stored = requests(parts, content, repo).after_generation(tenant_id=TENANT_ID, parent_id=parent)
    assert stored is not None and (stored.refused, stored.part) == ("needs_description", 2)


def test_nothing_is_asked_without_an_ask_or_while_the_text_is_being_made() -> None:
    parts, content, repo, ledger, _, _, parent = world()
    asks = requests(parts, content, repo)
    assert asks.after_generation(tenant_id=TENANT_ID, parent_id=parent) is None
    assert _children(repo, parent) == []
    parts, content, repo, ledger, _, _, parent = world(media={"parts_request": PartsRequest()})
    repo.drafts[parent] = replace(repo.drafts[parent], status=DRAFTING)
    store = MemoryStore(repo)
    asks = PartsRequests(content, parts=parts, store=store, analysis_of=lambda t, b: None)
    assert asks.after_generation(tenant_id=TENANT_ID, parent_id=parent) is None
    assert store.records == [] and _children(repo, parent) == []
    # an unknown draft (another business's reads the same): nothing either
    assert asks.after_generation(tenant_id=TENANT_ID, parent_id=uuid_of_nothing()) is None


def uuid_of_nothing() -> UUID:
    return UUID("00000000-0000-4000-8000-0000000000ff")


def test_a_failed_text_is_kept_as_text_missing() -> None:
    parts, content, repo, _, _, _, parent = world(media={"parts_request": PartsRequest()})
    repo.drafts[parent] = replace(repo.drafts[parent], status=FAILED)
    stored = requests(parts, content, repo).after_generation(tenant_id=TENANT_ID, parent_id=parent)
    assert stored is not None and stored.refused == "text_missing"


def test_the_owners_tap_records_and_raises_the_refusal_then_creates() -> None:
    parts, content, repo, ledger, _, _, parent = world(media={"parts_request": PartsRequest()})
    off = PartsService(content, require_queue=lambda: False)
    asks = PartsRequests(
        content,
        parts=off,
        store=MemoryStore(repo),
        analysis_of=lambda t, b: None,
    )
    with pytest.raises(PartsUnavailable):
        asks.request_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    assert _asked(repo, parent).refused == "unavailable"  # type: ignore[union-attr]
    ids = requests(parts, content, repo).request_parts(
        tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=(2,)
    )
    assert [c.part_index for c in _children(repo, parent)] == [2] and len(ids) == 1
    asked = _asked(repo, parent)
    assert asked is not None and asked.refused is None and asked.attempted_parts == (2,)
    with pytest.raises(UnknownDraft):
        requests(parts, content, repo).request_parts(
            tenant_id=TENANT_ID, parent_id=uuid_of_nothing(), user_id=USER_ID
        )


def test_every_refusal_has_a_code() -> None:
    assert refusal_of(PartNeedsDescription(3)) == ("needs_description", 3, 0)
    assert refusal_of(PartNeedsPrevious(2)) == ("needs_previous", 2, 0)
    assert refusal_of(NotEnoughCreations(previews=4, previews_left=1)) == (
        "not_enough_previews",
        None,
        3,
    )
    assert refusal_of(RuntimeError("boom")) is None


# ---------------------------------------------------------------------------
# the vistas previas, read before the parent exists


def test_the_previews_for_n_parts_are_read_without_writing() -> None:
    _, content, _, ledger, _, _, _ = world(previews_used=17)
    rows = dict(ledger.rows)
    use = parts_preview_use(content, tenant_id=TENANT_ID, brand_id=BRAND_ID, parts=4)
    assert use is not None and (use.uses, use.left) == (4, 3) and use.short
    assert use.quota == 20
    one = parts_preview_use(content, tenant_id=TENANT_ID, brand_id=BRAND_ID, parts=1)
    assert one is not None and not one.short
    assert ledger.rows == rows


def test_the_worker_asks_for_the_parts_after_a_generation_run() -> None:
    from types import SimpleNamespace

    from qualify_api.creative.worker.pipeline import PipelinePreparation

    seen: list[tuple[UUID, UUID]] = []

    class Recorder:
        def after_generation(self, *, tenant_id: UUID, parent_id: UUID) -> None:
            seen.append((tenant_id, parent_id))

    preparation = PipelinePreparation(object(), object(), ())  # type: ignore[arg-type]
    preparation.parts_requests = Recorder()
    run = SimpleNamespace(tenant_id=TENANT_ID, draft_id=uuid_of_nothing())
    preparation._after_generation(run)
    assert seen == [(TENANT_ID, uuid_of_nothing())]


def test_a_regenerated_text_creates_nothing_on_its_own() -> None:
    """Coordinator decision: the hook acts on the parent's FIRST generation only."""
    parts, content, repo, ledger, dispatcher, _, parent = world(
        previews_used=17, media={"parts_request": PartsRequest()}
    )
    asks = requests(parts, content, repo)
    first = asks.after_generation(tenant_id=TENANT_ID, parent_id=parent)
    assert first is not None and first.refused == "not_enough_previews"
    ledger._opening_previews = 0  # the month renewed; the owner made a new text
    assert asks.after_generation(tenant_id=TENANT_ID, parent_id=parent) is None
    assert _children(repo, parent) == [] and dispatcher.calls == []
    assert _asked(repo, parent) == first
    # only the owner's tap creates them now
    assert len(asks.request_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)) == 4


def test_an_older_attempt_never_overwrites_a_newer_one_whatever_the_clocks() -> None:
    """Review fix: the guard is the store's attempt counter, never two processes' clocks
    — equal or skewed timestamps cannot drop a later outcome nor keep a stale one."""
    parts, _, repo, _, _, _, parent = world(media={"parts_request": PartsRequest()})
    store = MemoryStore(repo)
    older = store.begin(tenant_id=TENANT_ID, parent_id=parent)
    newer = store.begin(tenant_id=TENANT_ID, parent_id=parent)
    assert (older, newer) == (1, 2)
    ahead = datetime(2099, 1, 1, tzinfo=UTC)  # a process whose clock runs ahead
    stale = PartsRequest(refused="plan_busy", attempt=1, attempted_at=ahead)
    fresh = PartsRequest(attempt=2, attempted_at=ahead - timedelta(days=1))
    assert store.record(tenant_id=TENANT_ID, parent_id=parent, request=stale) is None
    assert store.record(tenant_id=TENANT_ID, parent_id=parent, request=fresh) is not None
    asked = _asked(repo, parent)
    assert asked is not None and asked.refused is None and asked.attempted_at == AT


def test_a_later_ask_with_the_same_timestamp_is_still_kept() -> None:
    parts, content, repo, _, _, _, parent = world(
        previews_used=17, media={"parts_request": PartsRequest()}
    )
    asks = requests(parts, content, repo)
    first = asks.after_generation(tenant_id=TENANT_ID, parent_id=parent)
    assert first is not None and first.refused == "not_enough_previews"
    with pytest.raises(NotEnoughCreations):
        asks.request_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    asked = _asked(repo, parent)  # the same store clock (AT) for both outcomes
    assert asked is not None and asked.attempt == 2 and asked.attempted_at == first.attempted_at
    asks.request_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=(1,))
    asked = _asked(repo, parent)
    assert asked is not None and asked.attempt == 3 and asked.refused is None


def test_a_hook_that_raises_never_fails_the_generation_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from types import SimpleNamespace

    from qualify_api.creative.worker.pipeline import PipelinePreparation

    class Broken:
        def after_generation(self, *, tenant_id: UUID, parent_id: UUID) -> None:
            raise RuntimeError("database gone")

    preparation = PipelinePreparation(object(), object(), ())  # type: ignore[arg-type]
    preparation.parts_requests = Broken()
    run = SimpleNamespace(tenant_id=TENANT_ID, draft_id=uuid_of_nothing())
    preparation._after_generation_safely(run)  # logged, not raised
    assert "parts_request_failed" in caplog.text


def test_a_hook_that_breaks_before_recording_keeps_an_error_for_the_screen() -> None:
    """Review fix: the screen never shows «pending» forever."""
    from types import SimpleNamespace

    from qualify_api.creative.worker.pipeline import PipelinePreparation

    parts, content, repo, _, _, _, parent = world(media={"parts_request": PartsRequest()})
    store = MemoryStore(repo)

    def broken_requester(**_: object) -> UUID:
        raise RuntimeError("database gone")

    store.requester = broken_requester  # type: ignore[method-assign]
    asks = PartsRequests(content, parts=parts, store=store, analysis_of=lambda t, b: None)
    preparation = PipelinePreparation(object(), object(), ())  # type: ignore[arg-type]
    preparation.parts_requests = asks
    preparation._after_generation_safely(SimpleNamespace(tenant_id=TENANT_ID, draft_id=parent))
    asked = _asked(repo, parent)
    assert asked is not None and asked.refused == "error" and asked.attempt == 1
    assert _children(repo, parent) == []

    # a second failure (recording it too) is only logged, never raised
    class BrokenTwice:
        def after_generation(self, **_: object) -> None:
            raise RuntimeError("database gone")

        def record_failure(self, **_: object) -> bool:
            raise RuntimeError("still gone")

    preparation.parts_requests = BrokenTwice()
    preparation._after_generation_safely(SimpleNamespace(tenant_id=TENANT_ID, draft_id=parent))


def test_the_first_text_of_a_video_by_parts_counts_toward_the_daily_cap() -> None:
    """Deivid, 2026-11-09: creating a video by parts asks Claude for its first text — at
    the cap it is refused with the cap's own words, before anything is written; other
    pieces are created as before."""
    from qualify_api.creative.parts import (
        PARENT_TEXT_CAP_TEXT,
        PARENT_TEXT_DAILY_CAP,
        ParentTextCapReached,
    )

    from .test_creative_parts import FOUR_PARTS, parent_brief

    _, content, repo, ledger, dispatcher, _, parent = world()
    repo.parent_texts = PARENT_TEXT_DAILY_CAP - 1  # one left: still created
    content.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=parent_brief(*FOUR_PARTS), user_id=USER_ID
    )
    repo.parent_texts = PARENT_TEXT_DAILY_CAP
    drafts, rows, calls = set(repo.drafts), dict(ledger.rows), list(dispatcher.calls)
    with pytest.raises(ParentTextCapReached) as refused:
        content.create_draft(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            brief=parent_brief(*FOUR_PARTS),
            user_id=USER_ID,
        )
    assert str(refused.value) == PARENT_TEXT_CAP_TEXT
    assert set(repo.drafts) == drafts and ledger.rows == rows and dispatcher.calls == calls
    # any other piece is created as before
    flyer = content.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(variants=1), user_id=USER_ID
    )
    assert flyer in repo.drafts and parent in repo.drafts


def test_a_hook_failure_never_overwrites_a_good_outcome() -> None:
    """Review fix: a regenerated text's hook does nothing (first generation only); a
    failure there must not turn the parts already made into «error»."""
    parts, content, repo, _, _, _, parent = world(media={"parts_request": PartsRequest()})
    store = MemoryStore(repo)
    asks = PartsRequests(content, parts=parts, store=store, analysis_of=lambda t, b: None)
    good = asks.after_generation(tenant_id=TENANT_ID, parent_id=parent)
    assert good is not None and good.refused is None and len(_children(repo, parent)) == 4
    # the next generation's hook breaks before anything (it took no attempt)
    assert asks.after_generation(tenant_id=TENANT_ID, parent_id=parent) is None
    assert asks.record_failure(tenant_id=TENANT_ID, parent_id=parent) is False
    assert _asked(repo, parent) == good
