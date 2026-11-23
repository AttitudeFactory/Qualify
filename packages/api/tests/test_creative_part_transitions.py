"""EF-16 (m-25026594, ADR 50 D9), offline: the plan's transitions between parts reach
the join — the joined preview (`join_preview`), the approval's fingerprint and the 1080p
final in segments (`join_final`) — and change nothing that is charged. Recording joiners
and segmenters, an in-memory store; no network, no vendor, no database."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.schemas import EffectUse, VideoPartPlan
from qualify_creative.video.join import JoinedVideo, JoinSegment, JoinTransition

from qualify_api.creative import part_final
from qualify_api.creative.part_final import join_final, preview_fingerprint
from qualify_api.creative.part_join import (
    PartsToJoin,
    join_fingerprint,
    join_preview,
    join_transition_of,
    join_transitions,
    part_span,
    plan_transitions,
)
from qualify_api.creative.video_pipeline.recipe import (
    is_built_transition,
    unbuilt_recipe_problems,
    validate_brief_recipe,
)

from .test_creative_part_final import TENANT as FINAL_TENANT
from .test_creative_part_final import FinalJoins, _approved, _final, _raw_files
from .test_creative_part_final import _snapshot as _final_snapshot
from .test_creative_part_join import PARENT, TENANT, Joiner, Joins, Store, _files, _part, _snapshot
from .test_creative_parts import FOUR_PARTS, USER_ID, parent_brief, world
from .test_creative_parts import TENANT_ID as WORLD_TENANT

FADE = {"effect_id": "fundido", "version": 2, "params": {"duration_s": 0.5}}
WIPE = {"effect_id": "barrido", "version": 2, "params": {"direction": "up"}}
CUT = {"effect_id": "corte", "version": 1, "params": {}}
#: Rule 6: what the join drew and the library entry the owner chose.
FADE_RECORD = {
    "effect_id": "fundido",
    "version": 2,
    "kind": "fade",
    "duration_s": 0.5,
    "direction": "left",
}


# ---------------------------------------------------------------------------
# the plan's transition → the join's (pure)


def test_a_library_transition_is_the_joins() -> None:
    assert join_transition_of(FADE) == JoinTransition("fade", 0.5)
    # what the owner left out is the library's default (barrido v2: 0.4 s)
    assert join_transition_of(WIPE) == JoinTransition("wipe", 0.4, "up")
    assert join_transition_of(EffectUse.model_validate(FADE)) == JoinTransition("fade", 0.5)
    # a cut, nothing, and what the join does not draw are cuts
    assert join_transition_of(CUT) is None
    assert join_transition_of(None) is None
    assert join_transition_of({"effect_id": "fundido", "version": 1}) is None
    assert (
        join_transition_of({"effect_id": "fundido", "version": 2, "params": {"duration_s": 1.2}})
        is None
    )
    assert join_transition_of({"broken": True}) is None


def test_the_plan_transitions_are_read_by_place() -> None:
    assert plan_transitions([None, FADE, CUT]) == {2: FADE, 3: CUT}
    assert plan_transitions(None) == {} and plan_transitions("x") == {}


def test_each_kept_part_blends_with_the_kept_one_before_it() -> None:
    """Part 2 was removed: part 3 blends with part 1, as its own plan entry says; the
    first part never blends (nothing before it), even if its entry had one."""
    parts = (_part(1), _part(3), _part(4))
    snapshot = PartsToJoin(
        parent_id=PARENT,
        revision=1,
        planned=4,
        parts=parts,
        removed=frozenset({2}),
        transitions={1: FADE, 2: WIPE, 3: FADE},
    )
    assert join_transitions(snapshot, parts) == [None, JoinTransition("fade", 0.5), None]
    assert join_transitions(None, parts) == [None, None, None]


def test_only_cuts_keep_every_fingerprint_made_before() -> None:
    parts = [_part(1), _part(2)]
    spans = [part_span(p.params) for p in parts]
    before = join_fingerprint(parts, spans)
    assert join_fingerprint(parts, spans, None, [None, None]) == before
    fade = join_fingerprint(parts, spans, None, [None, JoinTransition("fade", 0.5)])
    wipe = join_fingerprint(parts, spans, None, [None, JoinTransition("wipe", 0.5)])
    assert len({before, fade, wipe}) == 3


# ---------------------------------------------------------------------------
# creating: the join makes the transition, so it is no longer refused


def test_a_parent_with_a_drawn_transition_may_be_created() -> None:
    assert is_built_transition(EffectUse.model_validate(FADE))
    assert is_built_transition(EffectUse.model_validate(WIPE))
    assert not is_built_transition(EffectUse(effect_id="fundido", version=1))
    brief = parent_brief(
        VideoPartPlan(seconds=5, description="Uno."),
        VideoPartPlan(seconds=4, description="Dos.", transition_in=EffectUse.model_validate(FADE)),
        VideoPartPlan(seconds=4, description="Tres.", transition_in=EffectUse.model_validate(WIPE)),
    )
    assert unbuilt_recipe_problems(brief) == ()
    assert validate_brief_recipe(brief) == ()


# ---------------------------------------------------------------------------
# the joined preview


def test_the_preview_joins_with_the_plans_transitions() -> None:
    parts = (_part(1), _part(2), _part(3))
    snapshot = replace(_snapshot(*parts), transitions={2: FADE, 3: CUT})
    joins, store, joiner = Joins(snapshot), Store(_files(*parts)), Joiner()
    write = join_preview(store, joins, TENANT, PARENT, joiner=joiner)
    assert write is not None
    clips = joiner.calls[0]
    assert [c.transition_in for c in clips] == [None, JoinTransition("fade", 0.5), None]
    # the parts' 4 + 4 + 4 s, less the 0.5 s they overlap
    assert write.params["duration_seconds"] == 11.5
    assert write.params["join"]["transitions"] == [
        None,
        FADE_RECORD,
        None,
    ]
    # its fingerprint carries the transitions: the same parts with a cut are another join
    cut = join_fingerprint(parts, [part_span(p.params) for p in parts])
    assert write.params["draft"]["fingerprint"] != cut


def test_a_preview_with_only_cuts_records_no_transitions() -> None:
    parts = (_part(1), _part(2))
    joins, store, joiner = Joins(_snapshot(*parts)), Store(_files(*parts)), Joiner()
    write = join_preview(store, joins, TENANT, PARENT, joiner=joiner)
    assert write is not None and "transitions" not in write.params["join"]
    assert write.params["duration_seconds"] == 8.0
    assert all(c.transition_in is None for c in joiner.calls[0])


def test_a_transition_changed_after_the_preview_makes_it_stale() -> None:
    """The owner approves what they SAW: a plan whose transition changed since the join
    is not the shown preview."""
    parts = (_final(1), _final(2))
    seen = _final_snapshot(*parts)  # joined with cuts
    changed = replace(seen, transitions={2: FADE})
    assert part_final.approval_problem(seen, FINAL_TENANT) is None
    assert part_final.approval_problem(changed, FINAL_TENANT) == part_final.STALE


# ---------------------------------------------------------------------------
# the 1080p final, in segments


def _faded_snapshot(*parts: Any) -> PartsToJoin:
    """The parts approved as the owner saw them joined: a 0.5 s fade into part 2."""
    base = replace(_final_snapshot(*parts), transitions={2: FADE})
    shown = preview_fingerprint(parts, {"logo": "sin logo"}, join_transitions(base, parts))
    block = {**dict(base.joined_block or {}), "fingerprint": shown}
    return _approved(replace(base, joined_fingerprint=shown, joined_block=block))


def test_the_final_puts_the_transition_between_the_two_parts_segments() -> None:
    parts = (_final(1), _final(2), _final(3))
    snapshot = _faded_snapshot(*parts)
    store = Store(_raw_files(*parts))
    calls: list[tuple[str, Any]] = []

    def segmenter(clip, *, out, pcm_out, poster=False, **options):  # noqa: ANN001, ANN003, ANN202
        calls.append(("segment", clip.path.read_bytes(), options))
        out.write_bytes(b"seg:" + clip.path.read_bytes())
        frames = 96 - options.get("drop_head", 0) - options.get("drop_tail", 0)
        pcm_out.write_bytes(bytes(8 * 2000 * frames))
        return JoinSegment(out, pcm_out, frames, 2000 * frames, b"jpeg" if poster else None)

    def transitioner(before, after, *, out, pcm_out, **_):  # noqa: ANN001, ANN003, ANN202
        calls.append(("transition", before.path.read_bytes() + b">" + after.path.read_bytes(),
                      after.transition_in))  # fmt: skip
        out.write_bytes(b"tr")
        pcm_out.write_bytes(bytes(8 * 2000 * 12))
        return JoinSegment(out, pcm_out, 12, 24_000)

    def concat(segments, *, out):  # noqa: ANN001, ANN202
        out.write_bytes(b"|".join(s.path.read_bytes() for s in segments))
        frames = sum(s.frames for s in segments)
        return JoinedVideo(out, 1080, 1920, Fraction(24), frames, frames / 24, segments[0].poster)

    write = join_final(
        store,
        FinalJoins(snapshot),
        FINAL_TENANT,
        snapshot.parent_id,
        segmenter=segmenter,
        concat=concat,
        transitioner=transitioner,
    )
    assert write is not None
    assert calls == [
        ("segment", b"raw-1", {"fade_in": False, "fade_out": False, "drop_tail": 12,
                               "size": part_final.JOIN_FINAL_SIZE, "overlay": None}),
        ("transition", b"raw-1>raw-2", JoinTransition("fade", 0.5)),
        ("segment", b"raw-2", {"fade_in": False, "fade_out": True, "drop_head": 12,
                               "size": part_final.JOIN_FINAL_SIZE, "overlay": None}),
        ("segment", b"raw-3", {"fade_in": True, "fade_out": False,
                               "size": part_final.JOIN_FINAL_SIZE, "overlay": None}),
    ]  # fmt: skip
    assert store.files[write.object_key] == b"seg:raw-1|tr|seg:raw-2|seg:raw-3"
    assert write.params["join_final"]["frames"] == 96 * 3 - 12
    assert write.params["join_final"]["transitions"][1] == FADE_RECORD
    # no raw file left behind in the store's keys: only segments and the final
    assert not any(k.endswith("raw-1") for k in store.files)


def test_a_final_with_only_cuts_calls_the_segmenter_as_before() -> None:
    """VE-10b's calls, unchanged: no drop arguments, no transition segment."""
    parts = (_final(1), _final(2))
    snapshot = _approved(_final_snapshot(*parts))
    seen: list[dict[str, Any]] = []

    def segmenter(clip, *, out, pcm_out, poster=False, **options):  # noqa: ANN001, ANN003, ANN202
        seen.append(options)
        out.write_bytes(b"seg")
        pcm_out.write_bytes(bytes(8 * 2000))
        return JoinSegment(out, pcm_out, 1, 2000, None)

    def transitioner(*_: Any, **__: Any) -> JoinSegment:
        raise AssertionError("no transition between cuts")

    def concat(segments, *, out):  # noqa: ANN001, ANN202
        out.write_bytes(b"x")
        return JoinedVideo(out, 1080, 1920, Fraction(24), len(segments), 1.0, None)

    write = join_final(
        Store(_raw_files(*parts)),
        FinalJoins(snapshot),
        FINAL_TENANT,
        snapshot.parent_id,
        segmenter=segmenter,
        concat=concat,
        transitioner=transitioner,
    )
    assert write is not None and "transitions" not in write.params["join_final"]
    assert [set(o) for o in seen] == [{"fade_in", "fade_out", "size", "overlay"}] * 2


def test_the_segment_fingerprints_of_cuts_are_the_ones_before() -> None:
    part = _final(1)
    span = part_span(part.params)
    before = part_final.segment_fingerprint(part, span, None, fade_in=True, fade_out=False)
    again = part_final.segment_fingerprint(
        part, span, None, fade_in=True, fade_out=False, drop_head=0, drop_tail=0
    )
    dropped = part_final.segment_fingerprint(
        part, span, None, fade_in=False, fade_out=False, drop_head=12
    )
    assert before == again != dropped


# ---------------------------------------------------------------------------
# Criterion 4: the seconds charged do not change


def _charged(plan: tuple[VideoPartPlan, ...]) -> list[tuple[int, int, str]]:
    """What creating the parts of `plan` charged: each row's videos, seconds, status."""
    parts, _, _, ledger, _, _, parent = world(plan=plan)
    parts.create_parts(tenant_id=WORLD_TENANT, parent_id=parent, user_id=USER_ID)
    return sorted((r.videos, r.video_seconds, r.status) for r in ledger.rows.values())


def test_the_seconds_charged_do_not_depend_on_the_transitions() -> None:
    """The quota charged is the parts' own (D29): the same plan with a fade and a wipe
    between its parts charges exactly what it charges with cuts — the joined video is
    shorter by the overlaps, the seconds used are not."""
    faded = (
        FOUR_PARTS[0],
        FOUR_PARTS[1].model_copy(update={"transition_in": EffectUse.model_validate(FADE)}),
        FOUR_PARTS[2].model_copy(update={"transition_in": EffectUse.model_validate(WIPE)}),
        FOUR_PARTS[3],
    )
    with_cuts = _charged(FOUR_PARTS)
    assert with_cuts and _charged(faded) == with_cuts


# ---------------------------------------------------------------------------
# review (2026-11-20): a part shorter than its transitions is refused BEFORE any charge

LONG_FADE = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.8})
SHORT_PLAN = (
    VideoPartPlan(seconds=5, description="Uno."),
    VideoPartPlan(seconds=1, description="Dos.", transition_in=LONG_FADE),
    VideoPartPlan(seconds=5, description="Tres.", transition_in=LONG_FADE),
)


def test_a_part_shorter_than_its_transitions_is_a_recipe_problem() -> None:
    """1 s (24 frames) between two 0.8 s fades (19 + 19 frames): refused on part 2,
    with its length; the same part with one fade, or 2 s long, fits."""
    from qualify_creative.effects import load_effects

    from qualify_api.creative.video_pipeline.recipe import recipe_of_parts as recipe
    from qualify_api.creative.video_pipeline.recipe import (
        transition_frames,
        transition_room_problems,
        transitions_longer_than_part_text,
    )

    assert transition_frames(LONG_FADE) == 19
    assert transition_frames(EffectUse.model_validate(WIPE)) == 10  # the default 0.4 s
    assert transition_frames(EffectUse.model_validate(CUT)) == 0
    assert transition_frames(None) == 0
    problems = transition_room_problems(recipe(SHORT_PLAN), load_effects())
    assert [(p.code, p.part, p.field, p.duration_s) for p in problems] == [
        ("transitions_longer_than_part", 2, "seconds", 1.0)
    ]
    one = (SHORT_PLAN[0], SHORT_PLAN[1], SHORT_PLAN[2].model_copy(update={"transition_in": None}))
    assert transition_room_problems(recipe(one)) == ()
    longer = SHORT_PLAN[1].model_copy(update={"seconds": 2})
    assert transition_room_problems(recipe((SHORT_PLAN[0], longer, SHORT_PLAN[2]))) == ()
    assert transitions_longer_than_part_text(2) == (
        "La parte 2 es más corta que sus transiciones. "
        "Hazla más larga o elige transiciones más cortas."
    )


def test_creating_a_parent_too_short_for_its_transitions_is_refused_before_any_row() -> None:
    from qualify_api.creative.part_request import refusal_of
    from qualify_api.creative.video_pipeline.recipe import RecipeRefused

    with pytest.raises(RecipeRefused) as refused:
        world(plan=SHORT_PLAN)  # `create_draft` refuses before any row, charge or call
    assert [(p.code, p.part) for p in refused.value.problems] == [
        ("transitions_longer_than_part", 2)
    ]
    assert refusal_of(refused.value) == ("transitions_longer_than_part", 2, 0)


def test_saving_a_plan_too_short_for_its_transitions_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative.parts_plan import PartsPlanRefused, save_parts_plan

    from .test_video_pipeline_recipe import _saving

    row = _saving(monkeypatch, parent_brief(*SHORT_PLAN))  # stored before the check
    with pytest.raises(PartsPlanRefused) as refused:
        save_parts_plan(tenant_id=WORLD_TENANT, parent_id=uuid4(), parts=SHORT_PLAN)
    assert [(p.code, p.part) for p in refused.value.problems] == [
        ("transitions_longer_than_part", 2)
    ]
    assert row.media is None  # nothing written


def test_the_join_falls_back_to_a_cut_rather_than_fail_paid_parts() -> None:
    """The safety net: a stored plan that slipped past the check (stored before it, or a
    removed neighbour that brought a longer transition) joins with a cut where the part
    is too short — never a join that fails after the parts are paid."""
    short = _part(2, seconds=1, generation=1)  # 24 frames
    parts = (_part(1), short, _part(3))
    long = {"effect_id": "fundido", "version": 2, "params": {"duration_s": 0.8}}
    snapshot = replace(_snapshot(*parts), transitions={2: long, 3: long})
    fitted = join_transitions(snapshot, parts)
    assert fitted == [None, JoinTransition("fade", 0.8), None]  # the one after it went
    roomy = replace(_snapshot(*parts), transitions={2: FADE})  # 12 frames of 24: fits
    assert join_transitions(roomy, parts) == [None, JoinTransition("fade", 0.5), None]


def test_the_record_names_the_library_entry_but_cuts_record_nothing() -> None:
    from qualify_api.creative.part_join import transitions_record

    fade = join_transition_of(FADE)
    assert fade is not None and fade.source == ("fundido", 2)
    assert transitions_record([None, fade]) == [None, FADE_RECORD]
    assert transitions_record([None, None]) is None
    # the source is provenance, not what the join draws: not in the child's spec
    assert "effect_id" not in fade.as_spec() and fade == JoinTransition("fade", 0.5)
