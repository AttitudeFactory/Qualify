"""m-25143223 (PR A): «Ver qué quedó fuera» — what of the reel the Clip does not use
(`left_out_spans`) and the part of one of those stretches (`span_entry`), plus the
refactor of `plan_from_analysis` around `_parts_for_group` (no behaviour change).
Offline and pure: no database, no vendor."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from qualify_creative.schemas import (
    PARTS_MAX,
    PartNotice,
    SourceSegment,
    VideoPartPlan,
)
from qualify_shared.objects.public import reel_frame_key

from qualify_api.creative import left_out
from qualify_api.creative.left_out import (
    LEFT_OUT_REASON_TEXTS,
    SPAN_EXTEND_ORDER,
    SPAN_IN_CLIP,
    SPAN_TEXTS,
    SPAN_UNKNOWN,
    UNCOVERED_END,
    SpanRefused,
    check_after_swap,
    left_out_spans,
    span_entry,
)
from qualify_api.creative.parts import (
    PART_MAX_SECONDS,
    _group_seconds,
    _groups,
    _seconds,
    _split,
    _talks,
    clip_description,
    is_vertical,
    join_unique,
    plan_from_analysis,
    reel_product_noun,
    shot_description,
)
from qualify_api.creative.plan_blocks import ClipBlocks, blocks_from_plan
from qualify_api.creative.video_pipeline.ai_parts import CLIP_AI_PARTS_SWITCH
from qualify_api.creative.video_pipeline.mode_choice import (
    ModeContext,
    ModePart,
    choose_part_mode,
    people_unclear,
)
from qualify_api.creative.video_pipeline.recipe import CLIP_BLOCK_TRANSITIONS_SWITCH
from qualify_api.referentes.reel_analysis_types import ReelAnalysis, ShotAnalysis

from .test_content_service import TENANT_ID
from .test_creative_parts import ANALYSIS_ID, FIXTURE, analysis, shot

VIDEO = f"uploads/{TENANT_ID}/mi-cocina.mp4"


@pytest.fixture
def ai_parts_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")


@pytest.fixture(autouse=True)
def _switches_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLIP_AI_PARTS_SWITCH, raising=False)
    monkeypatch.delenv(CLIP_BLOCK_TRANSITIONS_SWITCH, raising=False)


# ---------------------------------------------------------------------------
# The refactor: `plan_from_analysis` gives exactly what it gave before


def _old_plan_from_analysis(
    analysis_: ReelAnalysis, *, products: Any = (), extend_on: bool
) -> tuple[VideoPartPlan, ...]:
    """`plan_from_analysis` as it was before m-25143223 (origin/main 79f57b87), verbatim
    but the switch, which the caller passes."""
    shots = sorted(analysis_.shots, key=lambda s: s.shot_index)
    if not shots:
        return ()
    editable = (
        analysis_.edit_eligible
        and analysis_.source_available
        and is_vertical(analysis_.width, analysis_.height)
    )
    reel_product = reel_product_noun(analysis_)
    context = ModeContext(
        source="reel",
        source_available=analysis_.source_available,
        edit_eligible=analysis_.edit_eligible,
        vertical=is_vertical(analysis_.width, analysis_.height),
        extend_on=extend_on,
    )
    plan: list[VideoPartPlan] = []
    for group in _groups(shots, editable):
        unclear = any(people_unclear(s) for s in group)
        description = join_unique(shot_description(s, products, reel_product) for s in group)
        notices: list[PartNotice] = []
        if unclear:
            notices.append("people_unclear")
        if not description:
            notices.append("describe_it")
        common: dict[str, Any] = {
            "analysis_id": analysis_.id,
            "shot_indexes": tuple(s.shot_index for s in group),
            "description": clip_description(description),
            "talks_to_camera": any(_talks(s) for s in group),
            "notices": tuple(notices),
        }
        lengths = (
            _split(group[0].seconds)
            if len(group) == 1 and group[0].seconds > PART_MAX_SECONDS
            else [_seconds(_group_seconds(group))]
        )
        for at, seconds in enumerate(lengths):
            choice = choose_part_mode(ModePart(shots=tuple(group), split_tail=at > 0), context)
            plan.append(
                VideoPartPlan(
                    mode=choice.mode,
                    original_mode="extend" if at > 0 else choice.mode,
                    seconds=seconds,
                    mode_rule_version=choice.rule_version,
                    mode_reason=choice.reason_code,
                    mode_changed_by_owner=False,
                    **common,
                )
            )
    return tuple(plan[:PARTS_MAX])


def _sample() -> ReelAnalysis:
    return ReelAnalysis.from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _reels() -> list[ReelAnalysis]:
    person = {"people": "observed", "faces": "observed", "subject": "una persona cocina"}
    return [
        _sample(),
        analysis(shot(0, 0.0, 5.0), shot(1, 5.0, 9.0, **person), shot(2, 9.0, 24.0)),
        analysis(*(shot(i, i * 4.5, (i + 1) * 4.5) for i in range(12))),
        analysis(*(shot(i, i * 6.0, (i + 1) * 6.0) for i in range(8))),
        analysis(shot(0, 0.0, 3.0), shot(1, 3.0, 17.0), shot(2, 17.0, 42.0)),
        analysis(shot(0, 0.0, 5.0), shot(1, 5.0, 8.0, people="unknown"), shot(2, 8.0, 10.0)),
        analysis(shot(0, 0.0, 5.0), shot(1, 5.0, 26.0), width=1080, height=1080),
        analysis(
            shot(0, 0.0, 2.0, subject=None), shot(1, 2.0, 4.0, spoken="hola", faces="observed")
        ),
        analysis(
            shot(0, 0.0, 4.0, subject="sliders de pescado", product="sliders de pescado"),
            shot(1, 4.0, 9.0, subject="manos que sirven", product="sliders"),
        ),
        analysis(),
    ]


@pytest.mark.parametrize("extend_on", [True, False])
@pytest.mark.parametrize("products", [(), ("Pollo Crispy",)])
def test_the_plan_is_the_same_after_the_refactor(
    extend_on: bool, products: tuple[str, ...]
) -> None:
    for reel in _reels():
        assert plan_from_analysis(reel, products=products, extend_on=extend_on) == (
            _old_plan_from_analysis(reel, products=products, extend_on=extend_on)
        )


# ---------------------------------------------------------------------------
# Builders


# 5 cuts of 6 s (none joins: 12 s > 10 s), then one long take of 25 s split in 9+8+8:
# 8 parts proposed, the plan keeps 6 (the 5 cuts and the long take's head)
def _long_reel(**kw: Any) -> ReelAnalysis:
    shots = [shot(i, i * 6.0, (i + 1) * 6.0, subject=f"plano {i}") for i in range(5)]
    return analysis(*shots, shot(5, 30.0, 55.0, subject="la plancha llena"), **kw)


def _blocks(plan: tuple[VideoPartPlan, ...], reel: ReelAnalysis) -> ClipBlocks:
    return blocks_from_plan(plan, reel)


def _swap(blocks: ClipBlocks, at: int, entry: VideoPartPlan) -> ClipBlocks:
    """What the screen does: `entry` in the place of AI part `at`, its block as long."""
    ai_parts = list(blocks.ai_parts)
    ai_parts[at] = entry
    segments = [
        s.model_copy(update={"end_s": float(entry.seconds)}) if s.ai_part_at == at else s
        for s in blocks.segments
    ]
    return replace(blocks, ai_parts=tuple(ai_parts), segments=tuple(segments))


def _without(blocks: ClipBlocks, at: int) -> ClipBlocks:
    """The Clip with AI part `at`'s block taken out (its entry stays, named by nothing)."""
    return replace(blocks, segments=tuple(s for s in blocks.segments if s.ai_part_at != at))


# ---------------------------------------------------------------------------
# left_out_spans


def test_past_six_parts_the_rest_is_left_out_in_reel_order() -> None:
    reel = _long_reel()
    plan = plan_from_analysis(reel, extend_on=True)
    assert len(plan) == PARTS_MAX
    found = left_out_spans(reel, _blocks(plan, reel), extend_on=True)

    assert [(s.id, s.reason, s.mode_hint, s.seconds) for s in found.spans] == [
        ("cut:5.1", "split_tail", "extend", 8),
        ("cut:5.2", "split_tail", "extend", 8),
    ]
    assert [(s.start_s, s.end_s) for s in found.spans] == [(39.0, 47.0), (47.0, 55.0)]
    assert all(s.description == "La plancha llena." for s in found.spans)
    assert all(s.shot_indexes == (5,) for s in found.spans)
    assert (found.reel_seconds, found.used_seconds, found.ai_parts) == (55.0, 39.0, 6)


def test_a_cut_past_the_cap_is_parts_cap() -> None:
    reel = analysis(*(shot(i, i * 6.0, (i + 1) * 6.0) for i in range(8)))
    plan = plan_from_analysis(reel, extend_on=True)
    found = left_out_spans(reel, plan, extend_on=True)
    assert [(s.id, s.reason, s.mode_hint, s.start_s, s.end_s) for s in found.spans] == [
        ("cut:6", "parts_cap", "edit", 36.0, 42.0),
        ("cut:7", "parts_cap", "edit", 42.0, 48.0),
    ]


def test_with_extend_off_a_tail_comes_back_new() -> None:
    reel = _long_reel()
    found = left_out_spans(reel, plan_from_analysis(reel, extend_on=False), extend_on=False)
    assert [(s.id, s.mode_hint) for s in found.spans] == [
        ("cut:5.1", "reference"),
        ("cut:5.2", "reference"),
    ]


def test_it_reads_the_clip_as_it_is_now_not_the_first_plan() -> None:
    reel = _long_reel()
    blocks = _blocks(plan_from_analysis(reel, extend_on=True), reel)
    found = left_out_spans(reel, _without(blocks, 1), extend_on=True)
    # the part the owner took out is left out too, by the cap's reason
    assert [(s.id, s.reason) for s in found.spans] == [
        ("cut:1", "parts_cap"),
        ("cut:5.1", "split_tail"),
        ("cut:5.2", "split_tail"),
    ]
    assert (found.used_seconds, found.ai_parts) == (33.0, 5)


def test_bare_cut_indexes_count_one_per_part() -> None:
    reel = _long_reel()
    # cuts 0-4 and the long take twice: its head and its first tail
    found = left_out_spans(reel, [0, 1, 2, 3, 4, 5, 5], extend_on=True)
    assert [s.id for s in found.spans] == ["cut:5.2"]
    assert (found.used_seconds, found.ai_parts) == (47.0, 7)


def test_a_part_of_another_reel_uses_nothing_of_this_one() -> None:
    reel = analysis(shot(0, 0.0, 5.0), shot(1, 5.0, 11.0))
    other = replace(reel, id=reel.id.__class__(int=1))
    entries = plan_from_analysis(other, extend_on=True)
    found = left_out_spans(reel, entries, extend_on=True)
    assert [s.id for s in found.spans] == ["cut:0", "cut:1"]
    assert (found.used_seconds, found.ai_parts) == (0.0, 2)


def test_what_the_analysis_did_not_cover_is_shown_and_cannot_be_swapped() -> None:
    reel = replace(analysis(shot(0, 2.0, 7.0)), covered_from_s=2.0, source_seconds=20.0)
    found = left_out_spans(reel, plan_from_analysis(reel, extend_on=True), extend_on=True)
    assert [(s.id, s.reason, s.start_s, s.end_s, s.seconds) for s in found.spans] == [
        ("uncovered:start", "not_analyzed", 0.0, 2.0, 2),
        ("uncovered:end", "not_analyzed", 7.0, 20.0, 13),
    ]
    assert all(not s.swappable and s.mode_hint is None for s in found.spans)
    assert all(s.thumbnail_key is None and s.description == "" for s in found.spans)
    with pytest.raises(SpanRefused) as refused:
        span_entry(reel, UNCOVERED_END, extend_on=True)
    assert refused.value.reason == SPAN_UNKNOWN


def test_a_frame_already_stored_is_the_thumbnail_and_nothing_else() -> None:
    def framed(index: int, start: float, end: float, frames: int) -> ShotAnalysis:
        keys = tuple(
            reel_frame_key("instagram", "p1", ANALYSIS_ID, index, n) for n in range(frames)
        )
        times = tuple(start + n for n in range(frames))
        return replace(shot(index, start, end), frame_keys=keys, frame_times_s=times)

    shots = [framed(i, i * 6.0, (i + 1) * 6.0, 3) for i in range(7)]
    shots.append(shot(7, 42.0, 48.0))  # no frame stored
    reel = analysis(*shots)
    found = left_out_spans(reel, plan_from_analysis(reel, extend_on=True), extend_on=True)
    assert [(s.id, s.thumbnail_key) for s in found.spans] == [
        ("cut:6", reel_frame_key("instagram", "p1", ANALYSIS_ID, 6, 1)),
        ("cut:7", None),
    ]
    purged = replace(reel, frames_available=False)
    found = left_out_spans(purged, plan_from_analysis(purged, extend_on=True), extend_on=True)
    assert all(s.thumbnail_key is None for s in found.spans)


def test_nothing_is_left_out_when_the_clip_uses_the_whole_reel() -> None:
    reel = _sample()
    found = left_out_spans(reel, plan_from_analysis(reel, extend_on=True), extend_on=True)
    assert found.spans == ()
    assert found.reel_seconds == 18.4


# ---------------------------------------------------------------------------
# span_entry


def test_a_left_out_part_is_the_part_the_plan_would_have_proposed() -> None:
    reel = analysis(*(shot(i, i * 6.0, (i + 1) * 6.0, subject=f"plano {i}") for i in range(8)))
    entry = span_entry(reel, "cut:7", extend_on=True)
    # the same rule as the plan: what a plan that started at cut 7 proposes for it
    alone = analysis(*(s for s in reel.shots if s.shot_index == 7))
    assert entry == plan_from_analysis(alone, extend_on=True)[0]
    assert (entry.mode, entry.mode_reason, entry.seconds) == ("edit", "reel_no_people", 6)
    assert (entry.analysis_id, entry.shot_indexes) == (ANALYSIS_ID, (7,))
    assert entry.description == "Plano 7."
    assert not entry.clip_image_keys and not entry.clip_video_keys
    assert not entry.clip_audio_keys and not entry.text_layers and not entry.effects


def test_a_cut_with_someone_comes_back_new() -> None:
    person = {"people": "observed", "faces": "observed", "subject": "una persona sirve"}
    shots = [shot(i, i * 6.0, (i + 1) * 6.0) for i in range(6)]
    reel = analysis(*shots, shot(6, 36.0, 42.0, **person))
    (span,) = left_out_spans(reel, plan_from_analysis(reel, extend_on=True), extend_on=True).spans
    entry = span_entry(reel, span.id, extend_on=True)
    assert span.mode_hint == entry.mode == "reference"
    assert span.description == entry.description


@pytest.mark.usefixtures("ai_parts_on")
def test_placed_in_the_slot_of_the_part_it_replaces_the_clip_still_holds() -> None:
    reel = analysis(*(shot(i, i * 6.0, (i + 1) * 6.0) for i in range(8)))
    blocks = _blocks(plan_from_analysis(reel, extend_on=True), reel)
    assert check_after_swap(blocks) == ()
    swapped = _swap(blocks, 2, span_entry(reel, "cut:7", used=_without(blocks, 2), extend_on=True))
    assert swapped.ai_parts[2].shot_indexes == (7,)
    assert [e.shot_indexes for e in swapped.ai_parts][:2] == [(0,), (1,)]
    assert check_after_swap(swapped) == swapped.problems() == ()
    # and what was swapped out is now the one left out
    assert "cut:2" in {s.id for s in left_out_spans(reel, swapped, extend_on=True).spans}


@pytest.mark.usefixtures("ai_parts_on")
def test_a_tail_comes_in_right_after_its_head() -> None:
    reel = _long_reel()
    blocks = _blocks(plan_from_analysis(reel, extend_on=True), reel)
    # cut 4's part goes; the long take is the last part, so its first tail follows it
    rest = _without(blocks, 4)
    tail = span_entry(reel, "cut:5.1", used=rest, extend_on=True)
    assert (tail.mode, tail.original_mode, tail.shot_indexes, tail.seconds) == (
        "extend",
        "extend",
        (5,),
        8,
    )
    with pytest.raises(SpanRefused) as refused:
        span_entry(reel, "cut:5.2", used=rest, extend_on=True)
    assert refused.value.reason == SPAN_EXTEND_ORDER
    assert refused.value.text == SPAN_TEXTS[SPAN_EXTEND_ORDER]


def test_a_tail_without_its_head_is_refused() -> None:
    reel = _long_reel()
    blocks = _blocks(plan_from_analysis(reel, extend_on=True), reel)
    with pytest.raises(SpanRefused) as refused:
        span_entry(reel, "cut:5.1", used=_without(blocks, 5), extend_on=True)
    assert refused.value.reason == SPAN_EXTEND_ORDER


@pytest.mark.parametrize("span_id", ["cut:99", "cut:5.9", "nada", "uncovered:start"])
def test_a_stretch_that_is_not_in_the_analysis_is_unknown(span_id: str) -> None:
    reel = _long_reel()
    blocks = _blocks(plan_from_analysis(reel, extend_on=True), reel)
    with pytest.raises(SpanRefused) as refused:
        span_entry(reel, span_id, used=blocks, extend_on=True)
    assert refused.value.reason == SPAN_UNKNOWN
    assert refused.value.text == "Ese tramo del reel ya no está disponible. Elige otro."


def test_a_stretch_already_in_the_video_says_so() -> None:
    reel = _long_reel()
    blocks = _blocks(plan_from_analysis(reel, extend_on=True), reel)
    with pytest.raises(SpanRefused) as refused:
        span_entry(reel, "cut:1", used=blocks, extend_on=True)
    assert refused.value.reason == SPAN_IN_CLIP
    assert refused.value.text == "Ese tramo ya está en tu video. Elige otro."
    # with bare cut indexes too
    with pytest.raises(SpanRefused):
        span_entry(reel, "cut:1", used=[0, 1, 2], extend_on=True)
    assert span_entry(reel, "cut:3", used=[0, 1, 2], extend_on=True).shot_indexes == (3,)


def test_a_tail_made_new_stands_on_its_own() -> None:
    """Switch off: a split tail is `reference` (new), so it needs no head before it."""
    reel = _long_reel()
    blocks = _blocks(plan_from_analysis(reel, extend_on=False), reel)
    entry = span_entry(reel, "cut:5.2", used=_without(blocks, 5), extend_on=False)
    assert (entry.mode, entry.original_mode, entry.mode_reason) == (
        "reference",
        "extend",
        "extend_unavailable",
    )


def test_tails_are_counted_so_a_middle_one_taken_out_leaves_the_last_one_out() -> None:
    """A tail carries no piece number: the Clip's tails of a cut are its first tails."""
    reel = analysis(shot(0, 0.0, 6.0), shot(1, 6.0, 12.0), shot(2, 12.0, 37.0))
    plan = plan_from_analysis(reel, extend_on=False)
    assert [p.shot_indexes for p in plan] == [(0,), (1,), (2,), (2,), (2,)]
    blocks = _blocks(plan, reel)
    found = left_out_spans(reel, _without(blocks, 3), extend_on=False)
    assert [s.id for s in found.spans] == ["cut:2.2"]
    # the part that comes back is the same tail, made new from the same description
    assert span_entry(reel, "cut:2.2", used=_without(blocks, 3), extend_on=False) == plan[3]


def test_an_owner_who_made_a_tail_new_still_uses_it() -> None:
    reel = _long_reel()
    plan = list(plan_from_analysis(reel, extend_on=True))
    plan[5] = plan[5].model_copy(update={"mode_changed_by_owner": True})
    blocks = _blocks(tuple(plan), reel)
    extended = list(blocks.ai_parts)
    extended.append(
        span_entry(reel, "cut:5.1", used=blocks, extend_on=True).model_copy(
            update={"mode": "reference", "mode_changed_by_owner": True}
        )
    )
    found = left_out_spans(reel, extended, extend_on=True)
    assert [s.id for s in found.spans] == ["cut:5.2"]


def test_clip_blocks_without_blocks_count_their_entries() -> None:
    reel = _long_reel()
    plan = plan_from_analysis(reel, extend_on=True)
    found = left_out_spans(reel, ClipBlocks(ai_parts=plan), extend_on=True)
    assert [s.id for s in found.spans] == ["cut:5.1", "cut:5.2"]
    assert (found.used_seconds, found.ai_parts) == (39.0, 6)


def test_the_seconds_used_are_the_blocks_as_the_owner_left_them() -> None:
    reel = _long_reel()
    blocks = _blocks(plan_from_analysis(reel, extend_on=True), reel)
    trimmed = replace(
        blocks,
        segments=tuple(
            s.model_copy(update={"end_s": 3.0}) if s.ai_part_at == 0 else s for s in blocks.segments
        ),
    )
    assert left_out_spans(reel, trimmed, extend_on=True).used_seconds == 36.0


def test_the_notice_carries_the_caps_that_explain_it() -> None:
    found = left_out_spans(_long_reel(), [], extend_on=True)
    assert (found.max_seconds, found.max_parts) == (60.0, PARTS_MAX)
    assert set(LEFT_OUT_REASON_TEXTS) == {"parts_cap", "split_tail", "not_analyzed"}


def test_each_piece_of_a_long_take_shows_a_frame_of_its_own_seconds() -> None:
    keys = tuple(reel_frame_key("instagram", "p1", ANALYSIS_ID, 0, n) for n in range(6))
    long_take = replace(
        shot(0, 0.0, 25.0), frame_keys=keys, frame_times_s=(1.0, 4.0, 12.0, 15.0, 20.0, 23.0)
    )
    reel = analysis(long_take)
    found = left_out_spans(reel, [], extend_on=True)
    assert [(s.id, s.start_s, s.end_s) for s in found.spans] == [
        ("cut:0", 0.0, 9.0),
        ("cut:0.1", 9.0, 17.0),
        ("cut:0.2", 17.0, 25.0),
    ]
    assert [s.thumbnail_key for s in found.spans] == [keys[1], keys[3], keys[5]]


@pytest.mark.usefixtures("ai_parts_on")
def test_over_sixty_seconds_the_contract_refuses_it_after_the_swap() -> None:
    reel = analysis(*(shot(i, i * 10.0, (i + 1) * 10.0) for i in range(7)))
    plan = plan_from_analysis(reel, extend_on=True)
    own = SourceSegment(key=VIDEO, start_s=0.0, end_s=5.0)
    # 5 s of the owner's own video, then five AI parts of 10 s: 55 s
    blocks = _blocks(plan[:5], reel)
    blocks = replace(blocks, segments=(own, *blocks.segments))
    entry = span_entry(reel, "cut:6", used=blocks, extend_on=True)
    longer = replace(
        blocks,
        ai_parts=(*blocks.ai_parts, entry),
        segments=(
            *blocks.segments,
            SourceSegment(key="ai_part:5", kind="ai_part", start_s=0.0, end_s=10.0),
        ),
    )
    codes = {p.code for p in check_after_swap(longer, tenant_id=TENANT_ID)}
    assert "local_length_out_of_range" in codes


def test_it_opens_no_session_and_pays_nothing() -> None:
    names = vars(left_out)
    assert "tenant_session" not in names
    assert "admin_session" not in names
    assert "open_frame" not in names
