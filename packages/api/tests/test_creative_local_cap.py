"""EF-15 (m-25026575): the daily cap of LOCAL builds per business («Tu video, con
efectos»). Offline: the in-memory ledger counts the day's `local_video` charge rows, as
`PostgresContentRepository.local_builds_today` counts them in `creation_charges`. The
Postgres side (RLS between businesses, the business's midnight) is in
`test_creative_local_cap_db.py`."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import pytest
from qualify_creative.creations import REQUEST_LOCAL_VIDEO
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import ContentBrief, MediaInputs, SourceSegment, VideoPartPlan

from qualify_api.creative import local_cap
from qualify_api.creative.creations import InMemoryCreationsLedger
from qualify_api.creative.fsm import FAILED, GENERATED
from qualify_api.creative.local_cap import (
    DEFAULT_LOCAL_DAILY_CAP,
    LOCAL_DAILY_CAP_CODE,
    LOCAL_DAILY_CAP_ENV,
    LocalDailyCapReached,
    check_local_daily_cap,
    local_cap_text,
    local_daily_cap,
)
from qualify_api.creative.part_actions import PartRecovery
from qualify_api.creative.part_request import refusal_of
from qualify_api.creative.parts import PartChanges, PartsService
from qualify_api.creative.queue_dispatch import SWITCH
from qualify_api.creative.service import ContentService

from .test_content_service import (
    BRAND_ID,
    TENANT_ID,
    USER_ID,
    FakeBrand,
    FakePricing,
    FakeRouter,
    FakeVoice,
    RecordingDispatcher,
    StaticKeyResolver,
    copy_dict,
    make_brief,
    make_kit,
    make_voice,
    ok_outcome,
)
from .test_creative_parts import PartsMedia, PartsRepository, parent_brief

VIDEO_KEY = f"uploads/{TENANT_ID}/mi-cocina.mp4"
CAP_TEXT = (
    "Por hoy ya usaste los 10 videos que puedes crear con tus fotos y videos. "
    "Cada parte y cada versión nueva cuenta como uno. Mañana tienes 10 más."
)


class CappedRepository(PartsRepository):
    """The parts' in-memory repository that counts today's local builds as Postgres
    does: `before` builds made earlier today plus the ledger's `local_video` rows."""

    def __init__(self) -> None:
        super().__init__()
        self.ledger: InMemoryCreationsLedger | None = None
        self.before = 0

    def local_builds_today(self, *, tenant_id: UUID) -> int:
        rows = self.ledger.rows.values() if self.ledger is not None else ()
        return self.before + sum(1 for r in rows if r.price.request_kind == REQUEST_LOCAL_VIDEO)


@pytest.fixture(autouse=True)
def queue_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SWITCH, "queue")
    monkeypatch.delenv(LOCAL_DAILY_CAP_ENV, raising=False)


def _stretch(seconds: float = 4.0) -> SourceSegment:
    return SourceSegment(key=VIDEO_KEY, start_s=0.0, end_s=seconds, speed=1.0)


def _local_clip() -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(duration_seconds=5, clip_reference_mode="local", segments=(_stretch(),)),
    )


def _generated_clip() -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(duration_seconds=5),
    )


def _local_part(description: str) -> VideoPartPlan:
    return VideoPartPlan(mode="local", seconds=4, segments=(_stretch(),), description=description)


def _world(
    *, before: int = 0, plan: tuple[VideoPartPlan, ...] = ()
) -> tuple[
    ContentService,
    CappedRepository,
    InMemoryCreationsLedger,
    RecordingDispatcher,
    PartsService,
    UUID | None,
]:
    repo = CappedRepository()
    ledger = InMemoryCreationsLedger()
    repo.ledger = ledger
    dispatcher = RecordingDispatcher()
    content = ContentService(
        router=FakeRouter([ok_outcome(copy_dict()) for _ in range(3)]),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
        dispatcher=dispatcher,
        media=PartsMedia(),  # type: ignore[arg-type]
        creations=ledger,
    )
    parent: UUID | None = None
    if plan:
        parent = content.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=parent_brief(*plan), user_id=USER_ID
        )
        content.run_generation(tenant_id=TENANT_ID, draft_id=parent)
        assert repo.drafts[parent].status == GENERATED
        dispatcher.calls.clear()
    repo.before = before
    return (
        content,
        repo,
        ledger,
        dispatcher,
        PartsService(content, require_queue=lambda: True),
        parent,
    )


def _snapshot(
    repo: CappedRepository, ledger: InMemoryCreationsLedger, dispatcher: RecordingDispatcher
) -> tuple[Any, ...]:
    return (
        dict(repo.drafts),
        dict(repo.briefs),
        dict(ledger.rows),
        list(dispatcher.calls),
    )


# ---------------------------------------------------------------------------
# the number: the environment variable, its default and its fallback


def test_the_cap_is_ten_by_default() -> None:
    assert local_daily_cap() == DEFAULT_LOCAL_DAILY_CAP == 10


def test_the_environment_variable_changes_the_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOCAL_DAILY_CAP_ENV, " 3 ")
    assert local_daily_cap() == 3


@pytest.mark.parametrize("raw", ["diez", "0", "-2", "2.5", "   "])
def test_an_invalid_value_falls_back_to_ten_and_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    local_cap._parsed.cache_clear()
    monkeypatch.setenv(LOCAL_DAILY_CAP_ENV, raw)
    with caplog.at_level(logging.WARNING, logger=local_cap.__name__):
        assert local_daily_cap() == 10
    if raw.strip():
        assert LOCAL_DAILY_CAP_ENV in caplog.text


def test_the_owner_reads_the_cap_and_when_it_comes_back() -> None:
    assert local_cap_text(cap=10, used=10) == CAP_TEXT
    assert local_cap_text(cap=1, used=1) == (
        "Por hoy ya usaste el video que puedes crear con tus fotos y videos. Mañana tienes otro."
    )
    assert local_cap_text(cap=10, used=8, asked=3) == (
        "Este video necesita 3 partes con tus fotos y videos, y hoy solo te quedan 2. "
        "Mañana puedes crearlas. Lo que ya hiciste sigue guardado."
    )


def test_a_repository_that_cannot_count_is_not_capped() -> None:
    check_local_daily_cap(object(), tenant_id=TENANT_ID, asking=99)


# ---------------------------------------------------------------------------
# a new local piece (`create_draft`)


def test_with_nine_built_the_tenth_goes_on() -> None:
    content, repo, ledger, dispatcher, _, _ = _world(before=9)
    draft = content.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_local_clip(), user_id=USER_ID
    )
    assert draft in repo.drafts and dispatcher.calls == [(TENANT_ID, draft)]
    assert ledger.rows[(draft, 1)].price.request_kind == REQUEST_LOCAL_VIDEO
    assert repo.local_builds_today(tenant_id=TENANT_ID) == 10


def test_with_ten_built_the_eleventh_is_refused_and_nothing_is_written() -> None:
    content, repo, ledger, dispatcher, _, _ = _world(before=10)
    before = _snapshot(repo, ledger, dispatcher)
    with pytest.raises(LocalDailyCapReached) as refused:
        content.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_local_clip(), user_id=USER_ID
        )
    assert refused.value.code == LOCAL_DAILY_CAP_CODE == "local_daily_cap_reached"
    assert refused.value.text == CAP_TEXT and str(refused.value) == CAP_TEXT
    assert (refused.value.used, refused.value.cap, refused.value.asked) == (10, 10, 1)
    # no draft, no brief, no charge, no job
    assert _snapshot(repo, ledger, dispatcher) == before


def test_three_by_the_environment_refuses_the_fourth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOCAL_DAILY_CAP_ENV, "3")
    content, _repo, _ledger, _dispatcher, _, _ = _world()
    for _ in range(3):
        content.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_local_clip(), user_id=USER_ID
        )
    with pytest.raises(LocalDailyCapReached) as refused:
        content.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_local_clip(), user_id=USER_ID
        )
    assert refused.value.cap == 3 and "ya usaste los 3 videos" in refused.value.text


def test_a_clip_that_is_not_local_is_neither_capped_nor_counted() -> None:
    content, repo, ledger, dispatcher, _, _ = _world(before=10)
    draft = content.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_generated_clip(), user_id=USER_ID
    )
    assert draft in repo.drafts and dispatcher.calls == [(TENANT_ID, draft)]
    assert ledger.rows[(draft, 1)].price.request_kind != REQUEST_LOCAL_VIDEO
    assert repo.local_builds_today(tenant_id=TENANT_ID) == 10  # not counted


# ---------------------------------------------------------------------------
# «Pedir otra versión» of a local piece (`reject(regenerate=True)`)


def _made_local_clip(before: int) -> tuple[ContentService, CappedRepository, Any, Any, UUID]:
    content, repo, ledger, dispatcher, _, _ = _world()
    draft = content.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_local_clip(), user_id=USER_ID
    )
    content.run_generation(tenant_id=TENANT_ID, draft_id=draft)
    assert repo.drafts[draft].status == GENERATED
    dispatcher.calls.clear()
    repo.before = before  # + this piece's own row
    return content, repo, ledger, dispatcher, draft


def test_another_version_of_a_local_piece_counts_as_one_more() -> None:
    content, repo, ledger, dispatcher, draft = _made_local_clip(before=8)  # 9 today
    content.reject(
        tenant_id=TENANT_ID, draft_id=draft, reason="otra", user_id=USER_ID, regenerate=True
    )
    assert repo.drafts[draft].revision == 2 and dispatcher.calls == [(TENANT_ID, draft)]
    assert ledger.rows[(draft, 2)].price.request_kind == REQUEST_LOCAL_VIDEO
    assert repo.local_builds_today(tenant_id=TENANT_ID) == 10


def test_another_version_past_the_cap_changes_nothing() -> None:
    content, repo, ledger, dispatcher, draft = _made_local_clip(before=9)  # 10 today
    before = _snapshot(repo, ledger, dispatcher)
    with pytest.raises(LocalDailyCapReached):
        content.reject(
            tenant_id=TENANT_ID, draft_id=draft, reason="otra", user_id=USER_ID, regenerate=True
        )
    assert _snapshot(repo, ledger, dispatcher) == before
    assert repo.drafts[draft].status == GENERATED and repo.drafts[draft].revision == 1


def test_a_plain_rejection_of_a_local_piece_is_never_capped() -> None:
    content, repo, _ledger, _dispatcher, draft = _made_local_clip(before=20)
    content.reject(tenant_id=TENANT_ID, draft_id=draft, reason="no", user_id=USER_ID)
    assert repo.drafts[draft].revision == 1  # nothing built


# ---------------------------------------------------------------------------
# a video by parts: every `local` part counts, all of them or none


MIXED = (
    VideoPartPlan(seconds=5, description="La hamburguesa sobre la mesa."),
    _local_part("Mi cocina."),
    _local_part("Mi local."),
)


def test_each_local_part_counts_and_a_generated_part_does_not() -> None:
    _content, repo, ledger, dispatcher, parts, parent = _world(before=8, plan=MIXED)
    assert parent is not None
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    assert len(ids) == 3 and dispatcher.calls == [(TENANT_ID, child) for child in ids]
    kinds = [ledger.rows[(child, 1)].price.request_kind for child in ids]
    assert kinds.count(REQUEST_LOCAL_VIDEO) == 2
    assert repo.local_builds_today(tenant_id=TENANT_ID) == 10


def test_parts_that_would_pass_the_cap_are_refused_together() -> None:
    _content, repo, ledger, dispatcher, parts, parent = _world(before=9, plan=MIXED)
    assert parent is not None
    before = _snapshot(repo, ledger, dispatcher)
    with pytest.raises(LocalDailyCapReached) as refused:
        parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    assert (refused.value.used, refused.value.asked) == (9, 2)
    assert refused.value.text == (
        "Este video necesita 2 partes con tus fotos y videos, y hoy solo te queda 1. "
        "Mañana puedes crearlas. Lo que ya hiciste sigue guardado."
    )
    # not even the generated part was made: all or nothing
    assert _snapshot(repo, ledger, dispatcher) == before
    assert repo.parts_of(tenant_id=TENANT_ID, parent_id=parent) == ()
    # what the worker's hook keeps on the parent for the screen
    assert refusal_of(refused.value) == ("local_daily_cap_reached", None, 0)


def test_a_part_that_is_not_local_is_made_at_the_cap() -> None:
    _content, repo, _ledger, _dispatcher, parts, parent = _world(before=10, plan=MIXED)
    assert parent is not None
    (child,) = parts.create_parts(
        tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, part_indexes=(1,)
    )
    assert repo.drafts[child].part_index == 1


def _made_local_parts(
    before: int,
) -> tuple[ContentService, CappedRepository, Any, Any, PartsService, UUID, list[UUID]]:
    content, repo, ledger, dispatcher, parts, parent = _world(plan=MIXED)
    assert parent is not None
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    for child in ids:
        content.run_generation(tenant_id=TENANT_ID, draft_id=child)
    dispatcher.calls.clear()
    repo.before = before  # + the two local parts' rows
    return content, repo, ledger, dispatcher, parts, parent, ids


def test_another_version_of_a_local_part_counts_and_is_capped() -> None:
    _content, repo, ledger, dispatcher, parts, parent, ids = _made_local_parts(before=7)
    parts.regenerate_part(
        tenant_id=TENANT_ID,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Mi cocina de cerca."),
        user_id=USER_ID,
    )
    assert ledger.rows[(ids[1], 2)].price.request_kind == REQUEST_LOCAL_VIDEO
    assert repo.local_builds_today(tenant_id=TENANT_ID) == 10
    before = _snapshot(repo, ledger, dispatcher)
    with pytest.raises(LocalDailyCapReached):
        parts.regenerate_part(
            tenant_id=TENANT_ID,
            parent_id=parent,
            part_index=3,
            changes=PartChanges(description="Mi local de noche."),
            user_id=USER_ID,
        )
    # the new brief is never written, the part keeps its revision
    assert _snapshot(repo, ledger, dispatcher) == before
    assert repo.drafts[ids[2]].revision == 1


def test_another_version_of_a_generated_part_is_not_capped() -> None:
    _content, repo, ledger, _dispatcher, parts, parent, ids = _made_local_parts(before=30)
    parts.regenerate_part(
        tenant_id=TENANT_ID,
        parent_id=parent,
        part_index=1,
        changes=PartChanges(description="Otra mesa."),
        user_id=USER_ID,
    )
    assert repo.drafts[ids[0]].revision == 2 and (ids[0], 2) in ledger.rows


def test_trying_a_failed_local_part_again_is_capped() -> None:
    _content, repo, ledger, dispatcher, parts, parent, ids = _made_local_parts(before=8)
    repo.update_status(tenant_id=TENANT_ID, draft_id=ids[1], new_status=FAILED, failure_reason=None)
    before = _snapshot(repo, ledger, dispatcher)
    with pytest.raises(LocalDailyCapReached):
        PartRecovery(parts).retry_part(
            tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID
        )
    assert _snapshot(repo, ledger, dispatcher) == before
    assert repo.drafts[ids[1]].status == FAILED and repo.drafts[ids[1]].revision == 1
    repo.before = 7  # one place left today
    PartRecovery(parts).retry_part(
        tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID
    )
    assert repo.drafts[ids[1]].revision == 2 and dispatcher.calls == [(TENANT_ID, ids[1])]
    assert ledger.rows[(ids[1], 2)].price.request_kind == REQUEST_LOCAL_VIDEO
