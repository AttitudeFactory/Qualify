"""The rule that proposes how a part (or a Clip) is made, and why (EF-09, ADR 50 §1.3).

`choose_part_mode(part, context) -> ModeChoice` is PURE and cheap: no I/O, no network, no
model call, a handful of comparisons per cut. A live preview calls it every time the
owner changes something, so it must stay that way — no lookups, no parsing, no logging.

| Context | Mode | `reason_code` |
|---|---|---|
| The owner's own video | `local` | `own_video_local` |
| Own video + a Seedance effect, 9:16 | `edit` | `own_video_ai_effect` (unreachable, D4) |
| A reel part whose cuts show nobody (F6), editable 9:16 source | `edit` | `reel_no_people` |
| A reel part where someone is seen | `reference` | `reel_people` |
| A reel part where the analysis could not tell | `reference` | `people_unclear` |
| No source, not 9:16, purged | `reference` | `no_source`, `not_vertical`, `purged` |
| A reel the editor cannot take (`edit_eligible` False) | `reference` | `not_editable` |
| Second half onwards of a cut over 10 s, `extend_on` off | `reference` | `extend_unavailable` |
| Second half onwards of a cut over 10 s, `extend_on` on | `extend` | `split_cut_continues` |

`extend` is reachable ONLY for a split tail, and only when the caller passes
`ModeContext.extend_on=True`. The rule never reads the environment: the caller fills
`extend_on` from `qualify_api.creative.part_extend.extend_available()` (the
`QUALIFY_PARTS_EXTEND` switch of m-24880328, on main since #680). With it off, the tail
is `reference` and never in silence: `MODE_REASON_TEXTS["extend_unavailable"]` says so.
A Clip is never a tail, so `choose_clip_mode` never returns `extend`.

Wired (EF-09, after EF-02): `parts.plan_from_analysis` asks it for every part (split
tails included) and stores `mode_rule_version` / `mode_reason`; `parts_plan.save_parts_plan`
marks `mode_changed_by_owner` against `proposed_mode` (the mode the stored reason implies).
`choose_clip_mode` is not wired to any screen yet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol, cast

from qualify_creative.schemas import CLIP_MODE_OF_PART, PartMode

from qualify_api.referentes.reel_analysis_types import NOT_OBSERVED, UNKNOWN

#: Stored with every proposal as provenance (`mode_rule_version`, EF-02). Bump it on any
#: change of what the rule returns for the same input.
MODE_RULE_VERSION: Final = 1

# D4, decided by the founder on 2026-11-13: F6 (never `edit` where a person may be seen)
# applies to the owner's OWN video too — we cannot tell who is in it without analysing
# it, and Seedance 2.x refuses real faces. So an own video is always `local`, with or
# without a Seedance effect, and the `own_video_ai_effect` row of the table is
# unreachable in phase 1. It reopens with a cheap analysis of the owner's video.

#: A part's mode is EF-02's `PartMode` (`reference`, `edit`, `extend`, `local`).
ChosenMode = PartMode

#: The vocabulary of `MediaInputs.clip_reference_mode`. EF-02 declares that Literal inline
#: on the field and exports no name for it, so it is repeated here;
#: `test_video_mode_choice` pins the two equal. The translation itself is EF-02's
#: `CLIP_MODE_OF_PART`, never a table of ours.
ClipChosenMode = Literal["motion", "edit", "extend", "local"]

#: The codes the rule stores in `mode_reason`. Ours: in `qualify_creative.schemas` the
#: field is free text (`^[a-z0-9_]*$`, at most 40 characters — every code here fits,
#: pinned by a test), `""` on every part before the rule and `merged_parts` on a part
#: joined by «Juntar con la siguiente» (`parts_plan.MERGED_PARTS_REASON`).
ModeReason = Literal[
    "own_video_local",
    "own_video_ai_effect",
    "reel_no_people",
    "reel_people",
    "people_unclear",
    "no_source",
    # Deivid, 2026-11-14 (EF-09): a reel that is there but the editor cannot take gets its
    # own reason instead of `no_source`.
    "not_editable",
    "not_vertical",
    "purged",
    "extend_unavailable",
    "split_cut_continues",
]

#: Where a part's material comes from: a public reel, the owner's own video (its
#: `segments`), or nothing.
SourceKind = Literal["reel", "own_video", "none"]

#: What the owner reads next to each proposal (qualify-copy-es) — literally ADR 50 §1.3.
MODE_REASON_TEXTS: Mapping[ModeReason, str] = {
    "own_video_local": (
        "Usamos tu video tal cual, con los efectos que elegiste. No gasta segundos de video."
    ),
    "own_video_ai_effect": "Le pedimos a la IA que agregue el efecto sobre tu video.",
    "reel_no_people": "Igual al original, con tu producto: en esta parte no aparece nadie.",
    "reel_people": "Nueva, inspirada en el original: en el original aparece una persona.",
    "people_unclear": "Nueva, inspirada en el original: en el original aparece una persona.",
    "no_source": "Nueva, con tu producto.",
    # Deivid, 2026-11-14: same words as `no_source`; only the stored reason differs.
    "not_editable": "Nueva, con tu producto.",
    "not_vertical": "Nueva, con tu producto.",
    "purged": "Nueva, con tu producto.",
    "extend_unavailable": '"Sigue a la anterior" todavía no está disponible. La hacemos nueva.',
    # copy approved by Deivid on 2026-11-14 (EF-09, option A)
    "split_cut_continues": "Sigue a la anterior: continúa la misma toma del original.",
}

#: The mode each reason proposes — one per reason, so a stored `mode_reason` says which
#: mode the rule proposed (`proposed_mode`) without keeping the mode twice.
MODE_OF_REASON: Mapping[ModeReason, ChosenMode] = {
    "own_video_local": "local",
    "own_video_ai_effect": "edit",
    "reel_no_people": "edit",
    "reel_people": "reference",
    "people_unclear": "reference",
    "no_source": "reference",
    "not_editable": "reference",
    "not_vertical": "reference",
    "purged": "reference",
    "extend_unavailable": "reference",
    "split_cut_continues": "extend",
}


class PeopleSeen(Protocol):
    """What F6 reads of a cut — `ShotAnalysis` satisfies it."""

    @property
    def people_presence(self) -> str: ...

    @property
    def visible_faces(self) -> str: ...


# The one copy of F6: `parts` (and `parts_plan`) import these from here.
def edit_allowed(shot: PeopleSeen) -> bool:
    """F6: «Igual al original» only when no person and no face was seen."""
    return shot.people_presence == NOT_OBSERVED and shot.visible_faces == NOT_OBSERVED


def people_unclear(shot: PeopleSeen) -> bool:
    """The analysis could not tell whether someone is in the cut."""
    return shot.people_presence == UNKNOWN or (
        shot.people_presence == NOT_OBSERVED and shot.visible_faces == UNKNOWN
    )


@dataclass(frozen=True, slots=True)
class ModePart:
    """The part the rule looks at: the reel cuts it covers (empty without a reel), and
    whether it is the second half onwards of one cut over 10 s (`_split`)."""

    shots: Sequence[PeopleSeen] = ()
    split_tail: bool = False


# The caller fills these facts in from what it has (`plan_from_analysis`: the reel's
# analysis and `part_extend.extend_available()`).
@dataclass(frozen=True, slots=True)
class ModeContext:
    """The source of a part. For a reel, `source_available` False = purged (or never
    downloaded), `edit_eligible` False = a format the editor cannot take (V13), `vertical`
    = 9:16 (N5). `has_seedance_effect`: the owner picked an effect only Seedance makes.

    `extend_on`: «Sigue a la anterior» can be made (same name as m-24880328). The caller
    fills it with `part_extend.extend_available()` (on main since #680); the rule never
    reads the environment itself. It only matters for a split tail."""

    source: SourceKind = "none"
    source_available: bool = True
    edit_eligible: bool = True
    vertical: bool = True
    has_seedance_effect: bool = False
    extend_on: bool = False


@dataclass(frozen=True, slots=True)
class ModeChoice:
    mode: ChosenMode
    reason_code: ModeReason
    rule_version: int = MODE_RULE_VERSION

    @property
    def text(self) -> str:
        return MODE_REASON_TEXTS[self.reason_code]


@dataclass(frozen=True, slots=True)
class ClipModeChoice:
    """`ModeChoice` in the vocabulary of `MediaInputs.clip_reference_mode`."""

    mode: ClipChosenMode
    reason_code: ModeReason
    rule_version: int = MODE_RULE_VERSION

    @property
    def text(self) -> str:
        return MODE_REASON_TEXTS[self.reason_code]


def choose_part_mode(part: ModePart, context: ModeContext) -> ModeChoice:
    """How `part` is made and why — see the table in the module docstring. Order matters:
    the owner's own video first (D4), then the split tail (`extend` only with
    `context.extend_on`, never in silence), then the source (purged, not 9:16, not
    editable, none), then the people (F6).

    A split tail continues the previous part; it does not edit the original, so with
    `extend_on` it is `extend` whatever the source."""
    if context.source == "own_video":
        # D4 (2026-11-13): even with a Seedance effect, never `edit` — see the note above.
        return ModeChoice("local", "own_video_local")
    if part.split_tail:
        if context.extend_on:
            return ModeChoice("extend", "split_cut_continues")
        return ModeChoice("reference", "extend_unavailable")
    if context.source == "none" or not part.shots:
        return ModeChoice("reference", "no_source")
    # Deivid 2026-11-14 (EF-09 Q3): the source reason wins over the people reason — a
    # purged, non-9:16 or non-editable reel says so even when someone is (or may be) seen.
    if not context.source_available:
        return ModeChoice("reference", "purged")
    if not context.vertical:
        return ModeChoice("reference", "not_vertical")
    if not context.edit_eligible:
        # Deivid, 2026-11-14: its own reason, not `no_source` (EF-02 adds it to `mode_reason`).
        return ModeChoice("reference", "not_editable")
    if all(edit_allowed(shot) for shot in part.shots):
        return ModeChoice("edit", "reel_no_people")
    if any(not edit_allowed(s) and not people_unclear(s) for s in part.shots):
        return ModeChoice("reference", "reel_people")
    return ModeChoice("reference", "people_unclear")


def choose_clip_mode(context: ModeContext, shots: Sequence[PeopleSeen] = ()) -> ClipModeChoice:
    """A normal Clip is a plan of one part (ADR 50 §1.2): the same rule, translated to
    `clip_reference_mode` (`reference` → `motion`). A Clip is never a split tail, so it
    is never `extend`, whatever `context.extend_on` says."""
    choice = choose_part_mode(ModePart(shots=tuple(shots)), context)
    mode = cast(ClipChosenMode, CLIP_MODE_OF_PART[choice.mode])
    return ClipModeChoice(mode, choice.reason_code, choice.rule_version)


def proposed_mode(rule_version: int, reason: str) -> ChosenMode | None:
    """The mode the rule proposed for a stored part (`mode_rule_version`, `mode_reason`):
    None when no rule proposed it — a part from before the rule (version 0), one joined
    by «Juntar con la siguiente» (`merged_parts`), one the owner added by hand."""
    if rule_version < 1 or reason not in MODE_OF_REASON:
        return None
    return MODE_OF_REASON[cast(ModeReason, reason)]


__all__ = [
    "MODE_OF_REASON",
    "MODE_REASON_TEXTS",
    "MODE_RULE_VERSION",
    "ChosenMode",
    "ClipChosenMode",
    "ClipModeChoice",
    "ModeChoice",
    "ModeContext",
    "ModePart",
    "ModeReason",
    "PeopleSeen",
    "SourceKind",
    "choose_clip_mode",
    "choose_part_mode",
    "edit_allowed",
    "people_unclear",
    "proposed_mode",
]
