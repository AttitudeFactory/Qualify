"""EF-09: the pure rule that proposes each part's (and each Clip's) mode, with its reason.

One test per row of ADR 50 §1.3, F6 as a property over every people × faces combination,
D4 (an own video is never `edit`), `extend` only for a split tail and only with
`extend_on`, the owner's exact texts, EF-02's types, and `plan_from_analysis` wired to it
(EF-09): the rule's mode, version and reason on every part, split tails included.
"""

from __future__ import annotations

import ast
import dataclasses
import itertools
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args
from uuid import UUID

import pytest
from qualify_creative.schemas import (
    CLIP_MODE_OF_PART,
    MediaInputs,
    PartMode,
    VideoPartPlan,
)

from qualify_api.creative import parts, parts_plan
from qualify_api.creative.video_pipeline import mode_choice
from qualify_api.creative.video_pipeline.mode_choice import (
    MODE_OF_REASON,
    MODE_REASON_TEXTS,
    MODE_RULE_VERSION,
    ChosenMode,
    ClipChosenMode,
    ClipModeChoice,
    ModeChoice,
    ModeContext,
    ModePart,
    ModeReason,
    choose_clip_mode,
    choose_part_mode,
    edit_allowed,
    people_unclear,
    proposed_mode,
)
from qualify_api.referentes.reel_analysis_types import (
    NOT_OBSERVED,
    OBSERVATIONS,
    OBSERVED,
    UNKNOWN,
    AnalysisProvenance,
    ReelAnalysis,
    ShotAnalysis,
)

REEL = ModeContext(source="reel")


def cut(
    index: int = 0,
    seconds: float = 3.0,
    *,
    people: str = NOT_OBSERVED,
    faces: str = NOT_OBSERVED,
    start: float | None = None,
) -> ShotAnalysis:
    begin = float(index * 3) if start is None else start
    return ShotAnalysis(
        shot_index=index,
        start_s=begin,
        end_s=begin + seconds,
        people_presence=people,
        visible_faces=faces,
        families={"subject": {"status": OBSERVED, "value": "plato", "evidence_frames": []}},
    )


def reel_part(*shots: ShotAnalysis, tail: bool = False) -> ModePart:
    return ModePart(shots=shots, split_tail=tail)


# --- one test per row of §1.3 -----------------------------------------------------------


def test_own_video_without_seedance_effect_is_local() -> None:
    choice = choose_part_mode(ModePart(), ModeContext(source="own_video"))
    assert choice == ModeChoice("local", "own_video_local", MODE_RULE_VERSION)


def test_own_video_with_seedance_effect_is_local_by_d4() -> None:
    """D4 (2026-11-13): F6 protects the owner's own video too — the `own_video_ai_effect`
    row is unreachable in phase 1, even 9:16 with a Seedance effect."""
    choice = choose_part_mode(
        ModePart(), ModeContext(source="own_video", vertical=True, has_seedance_effect=True)
    )
    assert choice == ModeChoice("local", "own_video_local")


@pytest.mark.parametrize("effect", [False, True])
@pytest.mark.parametrize("vertical", [False, True])
@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("eligible", [False, True])
@pytest.mark.parametrize("tail", [False, True])
@pytest.mark.parametrize(
    "shots", [(), (cut(),), (cut(people=OBSERVED, faces=OBSERVED),), (cut(people=UNKNOWN),)]
)
def test_own_video_is_never_edit(
    effect: bool,
    vertical: bool,
    available: bool,
    eligible: bool,
    tail: bool,
    shots: tuple[ShotAnalysis, ...],
) -> None:
    context = ModeContext(
        source="own_video",
        source_available=available,
        edit_eligible=eligible,
        vertical=vertical,
        has_seedance_effect=effect,
    )
    choice = choose_part_mode(ModePart(shots=shots, split_tail=tail), context)
    assert choice.mode != "edit"
    assert choice.mode == "local"
    assert choice.reason_code == "own_video_local"


def test_reel_part_where_nobody_is_seen_is_edit() -> None:
    choice = choose_part_mode(reel_part(cut(0), cut(1)), REEL)
    assert choice == ModeChoice("edit", "reel_no_people")


def test_reel_part_with_a_person_seen_is_reference() -> None:
    seen = cut(1, people=OBSERVED, faces=NOT_OBSERVED)
    assert choose_part_mode(reel_part(cut(0), seen), REEL) == ModeChoice("reference", "reel_people")


def test_reel_part_with_only_a_face_seen_is_reference() -> None:
    face = cut(0, people=NOT_OBSERVED, faces=OBSERVED)
    assert choose_part_mode(reel_part(face), REEL).reason_code == "reel_people"


@pytest.mark.parametrize(
    ("people", "faces"),
    [(UNKNOWN, UNKNOWN), (UNKNOWN, NOT_OBSERVED), (UNKNOWN, OBSERVED), (NOT_OBSERVED, UNKNOWN)],
)
def test_reel_part_where_people_are_unclear_is_reference(people: str, faces: str) -> None:
    choice = choose_part_mode(reel_part(cut(0), cut(1, people=people, faces=faces)), REEL)
    assert choice == ModeChoice("reference", "people_unclear")


def test_a_person_seen_outranks_an_unclear_cut() -> None:
    unclear = cut(0, people=UNKNOWN, faces=UNKNOWN)
    seen = cut(1, people=OBSERVED, faces=OBSERVED)
    assert choose_part_mode(reel_part(unclear, seen), REEL).reason_code == "reel_people"


def test_observed_person_with_unknown_faces_counts_as_seen() -> None:
    """Same split as `parts._people_unclear`: a person seen is not «unclear»."""
    choice = choose_part_mode(reel_part(cut(people=OBSERVED, faces=UNKNOWN)), REEL)
    assert choice.reason_code == "reel_people"


def test_no_source_is_reference() -> None:
    assert choose_part_mode(ModePart(), ModeContext()) == ModeChoice("reference", "no_source")


def test_reel_part_without_cuts_is_no_source() -> None:
    assert choose_part_mode(ModePart(), REEL).reason_code == "no_source"


def test_reel_the_editor_cannot_take_is_not_editable() -> None:
    """Deivid, 2026-11-14: a reel that is there but `edit_eligible=False` gets its own
    reason, `not_editable`, with the same words as `no_source`."""
    context = ModeContext(source="reel", edit_eligible=False)
    choice = choose_part_mode(reel_part(cut()), context)
    assert choice == ModeChoice("reference", "not_editable")
    assert choice.text == "Nueva, con tu producto."
    assert choice.text == MODE_REASON_TEXTS["no_source"]


@pytest.mark.parametrize(
    "shots", [(cut(),), (cut(people=OBSERVED, faces=OBSERVED),), (cut(people=UNKNOWN),)]
)
def test_not_editable_comes_before_people(shots: tuple[ShotAnalysis, ...]) -> None:
    """A present, vertical reel the editor cannot take is `not_editable` whoever is seen."""
    context = ModeContext(source="reel", edit_eligible=False)
    assert choose_part_mode(reel_part(*shots), context) == ModeChoice("reference", "not_editable")


_SOURCE_PROBLEMS = {
    "purged": ModeContext(source="reel", source_available=False),
    "not_vertical": ModeContext(source="reel", vertical=False),
    "not_editable": ModeContext(source="reel", edit_eligible=False),
}
_PEOPLE_SEEN_OR_UNCLEAR = [
    (p, f)
    for p, f in itertools.product(OBSERVATIONS, OBSERVATIONS)
    if (p, f) != (NOT_OBSERVED,) * 2
]


@pytest.mark.parametrize("reason", sorted(_SOURCE_PROBLEMS))
@pytest.mark.parametrize(("people", "faces"), _PEOPLE_SEEN_OR_UNCLEAR)
@pytest.mark.parametrize("with_clean_cut", [False, True])
def test_source_reason_wins_over_people_reason(
    reason: str, people: str, faces: str, with_clean_cut: bool
) -> None:
    """Deivid 2026-11-14 (EF-09 Q3): a source problem (purged, not 9:16, not editable) plus
    a person seen or unclear gives the source reason, never `reel_people`/`people_unclear`."""
    risky = cut(1, people=people, faces=faces)
    shots = (cut(0), risky) if with_clean_cut else (risky,)
    choice = choose_part_mode(reel_part(*shots), _SOURCE_PROBLEMS[reason])
    assert choice == ModeChoice("reference", reason)  # type: ignore[arg-type]
    assert choice.reason_code not in ("reel_people", "people_unclear")


def test_clip_from_a_reel_the_editor_cannot_take_is_motion_not_editable() -> None:
    context = ModeContext(source="reel", edit_eligible=False)
    assert choose_clip_mode(context, (cut(),)) == ClipModeChoice("motion", "not_editable")


def test_reel_not_vertical_is_reference() -> None:
    context = ModeContext(source="reel", vertical=False)
    assert choose_part_mode(reel_part(cut()), context) == ModeChoice("reference", "not_vertical")


def test_reel_purged_is_reference() -> None:
    context = ModeContext(source="reel", source_available=False)
    assert choose_part_mode(reel_part(cut()), context) == ModeChoice("reference", "purged")


def test_split_tail_with_extend_off_is_reference_extend_unavailable() -> None:
    long_cut = cut(0, 14.0)
    choice = choose_part_mode(reel_part(long_cut, tail=True), REEL)
    assert REEL.extend_on is False
    assert choice == ModeChoice("reference", "extend_unavailable")
    assert choice.text == '"Sigue a la anterior" todavía no está disponible. La hacemos nueva.'


def test_split_tail_with_extend_on_is_extend_split_cut_continues() -> None:
    long_cut = cut(0, 14.0)
    context = ModeContext(source="reel", extend_on=True)
    choice = choose_part_mode(reel_part(long_cut, tail=True), context)
    assert choice == ModeChoice("extend", "split_cut_continues")
    assert choice.text == "Sigue a la anterior: continúa la misma toma del original."


@pytest.mark.parametrize("effect", [False, True])
def test_own_video_tail_stays_local_with_extend_on(effect: bool) -> None:
    """D4 wins before the split tail, switch on or off."""
    context = ModeContext(source="own_video", has_seedance_effect=effect, extend_on=True)
    choice = choose_part_mode(ModePart(shots=(cut(),), split_tail=True), context)
    assert choice == ModeChoice("local", "own_video_local")


# --- invariants -------------------------------------------------------------------------

_CONTEXTS = [
    ModeContext(
        source=source,
        source_available=available,
        edit_eligible=eligible,
        vertical=vertical,
        has_seedance_effect=effect,
    )
    for source, available, eligible, vertical, effect in itertools.product(
        ("reel", "own_video", "none"), *([(False, True)] * 4)
    )
]
_PAIRS = list(itertools.product(OBSERVATIONS, OBSERVATIONS))
_SHOT_SETS = [(), *[(cut(people=p, faces=f),) for p, f in _PAIRS]]


def _with_extend(context: ModeContext, extend_on: bool) -> ModeContext:
    return dataclasses.replace(context, extend_on=extend_on)


@pytest.mark.parametrize(("people", "faces"), _PAIRS)
def test_f6_no_edit_when_any_cut_has_someone_or_unknown(people: str, faces: str) -> None:
    """F6 as a property: a part is never `edit` if one of its cuts has a person or a face
    `observed` or `unknown` — alone or next to a clean cut, in any position, any context."""
    risky = (people, faces) != (NOT_OBSERVED, NOT_OBSERVED)
    target = cut(1, people=people, faces=faces)
    for context, extend_on, tail, shots in itertools.product(
        _CONTEXTS, (False, True), (False, True), ((target,), (cut(0), target), (target, cut(2)))
    ):
        part = ModePart(shots=shots, split_tail=tail)
        choice = choose_part_mode(part, _with_extend(context, extend_on))
        if risky:
            assert choice.mode != "edit", (people, faces, context, tail)
        if choice.mode == "edit":
            assert all(edit_allowed(s) for s in shots)


@pytest.mark.parametrize("extend_on", [False, True])
def test_edit_only_from_an_editable_vertical_reel_without_people(extend_on: bool) -> None:
    for context, tail in itertools.product(_CONTEXTS, (False, True)):
        part = reel_part(cut(0), cut(1), tail=tail)
        choice = choose_part_mode(part, _with_extend(context, extend_on))
        expected_edit = (
            context.source == "reel"
            and context.source_available
            and context.edit_eligible
            and context.vertical
            and not tail
        )
        assert (choice.mode == "edit") is expected_edit, (context, tail)


def test_context_defaults_to_extend_off() -> None:
    assert ModeContext().extend_on is False


def test_never_extend_with_extend_off() -> None:
    for context, tail, shots in itertools.product(_CONTEXTS, (False, True), _SHOT_SETS):
        choice = choose_part_mode(ModePart(shots=shots, split_tail=tail), context)
        assert choice.mode != "extend"
        if tail and context.source != "own_video":
            assert choice == ModeChoice("reference", "extend_unavailable")


def test_with_extend_on_every_non_own_tail_is_extend() -> None:
    for context, shots in itertools.product(_CONTEXTS, _SHOT_SETS):
        choice = choose_part_mode(
            ModePart(shots=shots, split_tail=True), _with_extend(context, True)
        )
        if context.source == "own_video":
            assert choice == ModeChoice("local", "own_video_local")
        else:
            assert choice == ModeChoice("extend", "split_cut_continues")


def test_extend_only_ever_for_a_split_tail() -> None:
    for context, extend_on, tail, shots in itertools.product(
        _CONTEXTS, (False, True), (False, True), _SHOT_SETS
    ):
        choice = choose_part_mode(
            ModePart(shots=shots, split_tail=tail), _with_extend(context, extend_on)
        )
        if choice.mode == "extend":
            assert tail and extend_on, (context, shots)
            assert choice.reason_code == "split_cut_continues"


def test_extend_on_changes_no_other_row() -> None:
    """The switch only touches split tails of a non-own source: every other input gets the
    same choice with it on as with it off."""
    for context, tail, shots in itertools.product(_CONTEXTS, (False, True), _SHOT_SETS):
        if tail and context.source != "own_video":
            continue
        part = ModePart(shots=shots, split_tail=tail)
        off = choose_part_mode(part, _with_extend(context, False))
        on = choose_part_mode(part, _with_extend(context, True))
        assert on == off, (context, tail, shots)


def test_rule_version_is_stamped() -> None:
    assert MODE_RULE_VERSION == 1
    for context in _CONTEXTS:
        assert choose_part_mode(reel_part(cut()), context).rule_version == 1


def test_every_reason_the_rule_returns_has_a_text() -> None:
    seen: set[str] = set()
    for context, extend_on, tail, shots in itertools.product(
        _CONTEXTS, (False, True), (False, True), _SHOT_SETS
    ):
        choice = choose_part_mode(
            ModePart(shots=shots, split_tail=tail), _with_extend(context, extend_on)
        )
        assert choice.text == MODE_REASON_TEXTS[choice.reason_code]
        assert choice.text
        seen.add(choice.reason_code)
    # Every reason is reachable except `own_video_ai_effect` (unreachable by D4) —
    # `not_editable` included (Deivid, 2026-11-14), apart from `no_source`.
    assert "not_editable" in seen and "no_source" in seen
    assert seen == set(MODE_REASON_TEXTS) - {"own_video_ai_effect"}


def test_parts_uses_the_one_copy_of_f6() -> None:
    """EF-09: `parts` and `parts_plan` import F6 from the rule; their own copies are gone."""
    assert parts.edit_allowed is edit_allowed
    assert parts.people_unclear is people_unclear
    assert parts_plan.edit_allowed is edit_allowed
    for module in (parts, parts_plan):
        assert not hasattr(module, "_edit_allowed")
        assert not hasattr(module, "_people_unclear")


# --- EF-02's types ----------------------------------------------------------------------


def test_part_mode_is_ef02s() -> None:
    assert ChosenMode is PartMode


def test_clip_mode_vocabulary_is_media_inputs() -> None:
    """`clip_reference_mode`'s Literal is inline in `MediaInputs` (no exported name): ours
    must stay the same set, and the translation is EF-02's `CLIP_MODE_OF_PART`."""
    field = MediaInputs.model_fields["clip_reference_mode"].annotation
    assert set(get_args(ClipChosenMode)) == set(get_args(field))
    assert set(CLIP_MODE_OF_PART) == set(get_args(PartMode))
    assert set(CLIP_MODE_OF_PART.values()) == set(get_args(ClipChosenMode))


_REASON_PATTERN = re.compile(r"^[a-z0-9_]*$")


@pytest.mark.parametrize("reason", get_args(ModeReason))
def test_every_reason_code_fits_mode_reason(reason: str) -> None:
    """`mode_reason` is free text in the schema (`^[a-z0-9_]*$`, at most 40): every code
    fits, and a part stores it as it is."""
    assert _REASON_PATTERN.fullmatch(reason) and 0 < len(reason) <= 40
    stored = VideoPartPlan(mode_reason=reason, mode_rule_version=MODE_RULE_VERSION)
    assert stored.mode_reason == reason


def test_reason_vocabularies_agree() -> None:
    assert set(MODE_REASON_TEXTS) == set(get_args(ModeReason)) == set(MODE_OF_REASON)


def test_each_reason_implies_the_mode_the_rule_gives_with_it() -> None:
    """`proposed_mode` reads the proposal back from the stored reason: one mode per reason."""
    for context, extend_on, tail, shots in itertools.product(
        _CONTEXTS, (False, True), (False, True), _SHOT_SETS
    ):
        choice = choose_part_mode(
            ModePart(shots=shots, split_tail=tail), _with_extend(context, extend_on)
        )
        assert MODE_OF_REASON[choice.reason_code] == choice.mode
        assert proposed_mode(choice.rule_version, choice.reason_code) == choice.mode


@pytest.mark.parametrize(
    ("version", "reason"),
    [(0, ""), (0, "reel_people"), (1, ""), (1, "merged_parts"), (0, "merged_parts")],
)
def test_no_proposal_without_the_rule(version: int, reason: str) -> None:
    assert proposed_mode(version, reason) is None


def test_choice_is_immutable() -> None:
    choice = choose_part_mode(ModePart(), ModeContext())
    with pytest.raises(AttributeError):
        choice.mode = "edit"  # type: ignore[misc]


# --- the owner's words: literally ADR 50 §1.3 -------------------------------------------


def test_reason_texts_are_exactly_the_design_table() -> None:
    assert dict(MODE_REASON_TEXTS) == {
        "own_video_local": (
            "Usamos tu video tal cual, con los efectos que elegiste. No gasta segundos de video."
        ),
        "own_video_ai_effect": "Le pedimos a la IA que agregue el efecto sobre tu video.",
        "reel_no_people": "Igual al original, con tu producto: en esta parte no aparece nadie.",
        "reel_people": "Nueva, inspirada en el original: en el original aparece una persona.",
        "people_unclear": "Nueva, inspirada en el original: en el original aparece una persona.",
        "no_source": "Nueva, con tu producto.",
        # Deivid, 2026-11-14: its own reason, same words as `no_source`
        "not_editable": "Nueva, con tu producto.",
        "not_vertical": "Nueva, con tu producto.",
        "purged": "Nueva, con tu producto.",
        "extend_unavailable": (
            '"Sigue a la anterior" todavía no está disponible. La hacemos nueva.'
        ),
        # copy approved by Deivid on 2026-11-14 (EF-09, option A)
        "split_cut_continues": "Sigue a la anterior: continúa la misma toma del original.",
    }


# --- the Clip: a plan of one part -------------------------------------------------------


def test_clip_translates_reference_to_motion() -> None:
    choice = choose_clip_mode(REEL, (cut(people=OBSERVED, faces=OBSERVED),))
    assert choice == ClipModeChoice("motion", "reel_people", MODE_RULE_VERSION)
    assert choice.text == MODE_REASON_TEXTS["reel_people"]


def test_clip_without_source_is_motion() -> None:
    assert choose_clip_mode(ModeContext()) == ClipModeChoice("motion", "no_source")


def test_clip_from_a_clean_reel_is_edit() -> None:
    assert choose_clip_mode(REEL, (cut(),)) == ClipModeChoice("edit", "reel_no_people")


def test_clip_with_own_video_is_local_even_with_a_seedance_effect() -> None:
    context = ModeContext(source="own_video", has_seedance_effect=True)
    assert choose_clip_mode(context) == ClipModeChoice("local", "own_video_local")


@pytest.mark.parametrize("extend_on", [False, True])
def test_clip_is_never_extend(extend_on: bool) -> None:
    """A Clip is not a tail: never `extend`, even with the switch on."""
    for context, shots in itertools.product(_CONTEXTS, _SHOT_SETS):
        choice = choose_clip_mode(_with_extend(context, extend_on), shots)
        assert choice.mode != "extend"
        assert choice.reason_code not in ("split_cut_continues", "extend_unavailable")


# --- agreement with today's plan_from_analysis ------------------------------------------


def _analysis(
    *shots: ShotAnalysis,
    width: int = 720,
    height: int = 1280,
    edit_eligible: bool = True,
    source_available: bool = True,
) -> ReelAnalysis:
    return ReelAnalysis(
        id=UUID(int=9),
        network="instagram",
        post_id="p9",
        analysis_version=6,
        post_url="https://www.instagram.com/reel/p9/",
        source_seconds=shots[-1].end_s,
        width=width,
        height=height,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=shots[-1].end_s,
        edit_eligible=edit_eligible,
        source_available=source_available,
        transcript_text="",
        transcript_segments=(),
        transcript_source="none",
        reel_sheet={},
        shots=shots,
        provenance=AnalysisProvenance(
            model_id="m",
            model_revision=None,
            prompt_version="p",
            schema_version="s",
            detector_version="d",
            sampling_version="v",
            sampling_params={},
            source_sha256="0" * 64,
        ),
        finished_at=datetime(2026, 11, 13, tzinfo=UTC),
    )


@pytest.mark.parametrize("extend_on", [True, False])
@pytest.mark.parametrize("source_available", [True, False])
@pytest.mark.parametrize("edit_eligible", [True, False])
@pytest.mark.parametrize("width", [720, 1280])
def test_plan_from_analysis_stores_the_rule(
    width: int, edit_eligible: bool, source_available: bool, extend_on: bool
) -> None:
    """The offline twin of the dev-database regression. Every part of the plan carries the
    rule's mode, version and reason, and was not changed by the owner. Split tails are
    born `extend` (`original_mode`) whatever the switch: `extend` with it on, `reference`
    / `extend_unavailable` with it off — the «converted split tail» every check accepts.
    A part the plan flags `people_unclear` with nobody seen gets that reason from the rule
    when the source is editable."""
    reel = _analysis(
        cut(0, 2.0, start=0.0),
        cut(1, 2.5, start=2.0, people=OBSERVED, faces=OBSERVED),
        cut(2, 23.0, start=4.5),
        cut(3, 3.0, start=27.5, people=UNKNOWN, faces=UNKNOWN),
        cut(4, 5.0, start=30.5),
        width=width,
        edit_eligible=edit_eligible,
        source_available=source_available,
    )
    plan = parts.plan_from_analysis(reel, extend_on=extend_on)
    by_index = {s.shot_index: s for s in reel.shots}
    context = ModeContext(
        source="reel",
        source_available=reel.source_available,
        edit_eligible=reel.edit_eligible,
        vertical=parts.is_vertical(reel.width, reel.height),
        extend_on=extend_on,
    )
    editable = context.source_available and context.edit_eligible and context.vertical
    tails = 0
    unclear_parts = 0
    previous = None
    for part in plan:
        tail = previous is not None and previous.shot_indexes == part.shot_indexes
        shots = tuple(by_index[i] for i in part.shot_indexes)
        choice = choose_part_mode(ModePart(shots=shots, split_tail=tail), context)
        assert (part.mode, part.mode_reason, part.mode_rule_version) == (
            choice.mode,
            choice.reason_code,
            MODE_RULE_VERSION,
        ), part
        assert part.mode_changed_by_owner is False
        if part.original_mode == "extend":
            tails += 1
            assert tail
            expected = (
                ModeChoice("extend", "split_cut_continues")
                if extend_on
                else ModeChoice("reference", "extend_unavailable")
            )
            assert choice == expected
        else:
            assert not tail and part.original_mode == part.mode
        nobody_seen = all(edit_allowed(s) or people_unclear(s) for s in shots)
        if editable and "people_unclear" in part.notices and nobody_seen and not tail:
            unclear_parts += 1
            assert choice.reason_code == "people_unclear", part
        previous = part
    assert tails == 2  # 23 s → 8 + 8 + 7
    assert unclear_parts == (1 if editable else 0)
    # the split checks accept it, switch on or off (`check_edited_plan` too: see
    # `test_a_converted_split_tail_passes_every_check`; here the 2 s clean cut next to a
    # person has no window to edit, which that check refuses with or without the rule)
    parts.check_split_parts(plan, reel)
    parts.check_extend_parts(plan, reel)


def test_plan_from_analysis_reads_the_switch_when_not_told(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative.part_extend import EXTEND_SWITCH

    reel = _analysis(cut(0, 14.0, start=0.0))
    monkeypatch.delenv(EXTEND_SWITCH, raising=False)
    assert [p.mode for p in parts.plan_from_analysis(reel)] == ["edit", "reference"]
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    assert [p.mode for p in parts.plan_from_analysis(reel)] == ["edit", "extend"]
    assert [p.original_mode for p in parts.plan_from_analysis(reel, extend_on=False)] == [
        "edit",
        "extend",
    ]


def test_the_rule_imports_only_the_analysis_vocabulary() -> None:
    """The rule stays pure and cycle-free: its own imports are the stdlib, EF-02's schema
    types and the analysis observation constants — never `media`, `parts` or I/O."""
    tree = ast.parse(Path(mode_choice.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    assert imported == {
        "__future__",
        "collections.abc",
        "dataclasses",
        "typing",
        "qualify_creative.schemas",
        "qualify_api.referentes.reel_analysis_types",
    }
