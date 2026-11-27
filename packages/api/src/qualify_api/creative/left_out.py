"""m-25143223 (PR A): «Ver qué quedó fuera» in «Hacer uno parecido».

A reel's analysis proposes more than a Clip can hold: `plan_from_analysis` keeps the
first `PARTS_MAX` parts, a cut over 10 s becomes a head and its split tails, and what the
analysis did not cover has no cuts at all. This module tells the screen which stretches
of the reel the CURRENT Clip does not use, and builds the part for one of them so the
owner can swap it in:

- `left_out_spans(analysis, used, products=…)` — every stretch of the reel the Clip does
  not use (`LeftOutSpan`, in reel order) plus the totals the screen's notice needs
  (`LeftOut`: the reel's seconds, the seconds the Clip uses, its AI parts). `used` is
  what the Clip uses NOW — its `ClipBlocks`, its AI entries, or the cut indexes they use
  — never only the plan first proposed: the owner may have removed or swapped parts.
- `span_entry(analysis, left_out_id, products=…, used=…)` — the `VideoPartPlan` of that
  stretch, built by the same rule as the plan (`parts._parts_for_group`): its mode
  («Igual al original» `edit` with its reel window — `analysis_id` + `shot_indexes` —
  or new), seconds, description, notices and `mode_reason`. The screen puts it in the
  place of the part it replaces: this module never rebuilds the plan or the blocks.
  After placing it, the screen checks the Clip as always (`ClipBlocks.problems()`,
  `check_after_swap`): the 60 s, the 8 blocks and the 6 AI children are the contract's.

A stretch's `id` is stable for one analysis: `cut:<shot>` for a part (a group of
consecutive cuts takes its first cut's index), `cut:<shot>.<k>` for the k-th split tail
of a cut over 10 s, `uncovered:start` / `uncovered:end` for what the analysis did not
cover (shown, never swappable).

Pure: no database, no file, no vendor, nothing written or paid. No video is processed:
a stretch's thumbnail is a frame the analysis already stored (`thumbnail_key`), else None.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from qualify_creative.effects import RecipeProblem
from qualify_creative.schemas import VideoPartPlan

from qualify_api.creative.parts import _split, proposed_groups
from qualify_api.creative.plan_blocks import ClipBlocks
from qualify_api.referentes.reel_analysis_frames import frame_key, representative_frame
from qualify_api.referentes.reel_analysis_types import ReelAnalysis, ShotAnalysis

#: Why a stretch of the reel is not in the Clip (`LeftOutSpan.reason`).
#: - `parts_cap`: a part the plan proposes that is not in the Clip — past the 6 parts,
#:   or taken out by the owner;
#: - `split_tail`: a later piece of a cut over 10 s («Sigue a la anterior»); it can come
#:   in only right after the piece before it;
#: - `not_analyzed`: outside what the analysis covered; it has no cuts and cannot be
#:   swapped in.
LeftOutReason = Literal["parts_cap", "split_tail", "not_analyzed"]

#: Why `span_entry` refuses (`SpanRefused.reason`). Codes, the words are `SPAN_TEXTS`.
SPAN_UNKNOWN = "span_unknown"
SPAN_EXTEND_ORDER = "extend_order"

#: What the owner reads for each refusal (`qualify-copy-es`).
SPAN_TEXTS: dict[str, str] = {
    SPAN_UNKNOWN: "Ese tramo del reel ya no está disponible. Elige otro.",
    SPAN_EXTEND_ORDER: (
        "Ese tramo sigue a otro que no está en tu video. Cambia primero el tramo anterior."
    ),
}

#: Less than this before or after the analysed cuts is detector noise, not a stretch.
UNCOVERED_MIN_S = 0.5
UNCOVERED_START = "uncovered:start"
UNCOVERED_END = "uncovered:end"


class SpanRefused(ValueError):
    """`span_entry` cannot build that stretch (`reason`: `SPAN_UNKNOWN` or
    `SPAN_EXTEND_ORDER`; the owner's words: `SPAN_TEXTS[reason]`). `str(exc)` is for
    logs."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason

    @property
    def text(self) -> str:
        return SPAN_TEXTS[self.reason]


@dataclass(frozen=True)
class LeftOutSpan:
    """One stretch of the reel the Clip does not use, in seconds of the REEL.

    `seconds`: what the part would last in the video (whole seconds, as the plan gives
    them; for `not_analyzed`, the stretch's own length rounded). `description`: the
    part's, as the plan would write it ("" for `not_analyzed`). `mode_hint`: the mode
    the part would come in with (`edit` = «Igual al original», `reference` = new,
    `extend` = «Sigue a la anterior»); None for `not_analyzed`. `shot_indexes`: the cuts
    it comes from (for `Qualify/avatar_proxy.part_thumbnail_path`). `thumbnail_key`: the
    R2 key of a frame the analysis already stored for those cuts, or None."""

    id: str
    start_s: float
    end_s: float
    seconds: int
    description: str
    reason: LeftOutReason
    mode_hint: str | None
    thumbnail_key: str | None
    shot_indexes: tuple[int, ...] = ()

    @property
    def swappable(self) -> bool:
        return self.reason != "not_analyzed"


@dataclass(frozen=True)
class LeftOut:
    """`left_out_spans`'s answer: the stretches in reel order and the notice's totals —
    `reel_seconds` (the reel's length), `used_seconds` (what the Clip's parts from this
    reel last) and `ai_parts` (how many AI parts the Clip has)."""

    spans: tuple[LeftOutSpan, ...]
    reel_seconds: float
    used_seconds: float
    ai_parts: int


@dataclass(frozen=True)
class _Piece:
    """One part the analysis proposes, with where it sits in the reel."""

    id: str
    head_id: str
    tail: int  # 0 = the head; k = the k-th split tail
    entry: VideoPartPlan
    start_s: float
    end_s: float


def _pieces(
    analysis: ReelAnalysis, products: Sequence[str], extend_on: bool | None
) -> list[_Piece]:
    pieces: list[_Piece] = []
    for group, parts in proposed_groups(analysis, products, extend_on):
        head_id = f"cut:{group[0].shot_index}"
        if len(parts) == 1:
            pieces.append(_Piece(head_id, head_id, 0, parts[0], group[0].start_s, group[-1].end_s))
            continue
        cut: ShotAnalysis = group[0]
        lengths = _split(cut.seconds)
        start = cut.start_s
        for k, part in enumerate(parts):
            end = cut.end_s if k == len(parts) - 1 else min(start + lengths[k], cut.end_s)
            piece_id = head_id if k == 0 else f"{head_id}.{k}"
            pieces.append(_Piece(piece_id, head_id, k, part, round(start, 3), round(end, 3)))
            start = end
    return pieces


@dataclass(frozen=True)
class _Uses:
    """What the Clip uses of the reel: per cut, its heads and its split tails."""

    heads: Counter[int]
    tails: Counter[int]
    seconds: float
    ai_parts: int


def _entries(used: ClipBlocks | Sequence[VideoPartPlan]) -> tuple[VideoPartPlan, ...]:
    if not isinstance(used, ClipBlocks):
        return tuple(used)
    if not used.segments:
        return used.ai_parts
    named = {s.ai_part_at for s in used.segments if s.ai_part_at is not None}
    return tuple(entry for at, entry in enumerate(used.ai_parts) if at in named)


def _uses(
    analysis: ReelAnalysis, used: ClipBlocks | Sequence[VideoPartPlan] | Iterable[int]
) -> _Uses:
    heads: Counter[int] = Counter()
    tails: Counter[int] = Counter()
    if isinstance(used, ClipBlocks) or (
        isinstance(used, Sequence) and all(isinstance(u, VideoPartPlan) for u in used)
    ):
        entries = _entries(used)  # type: ignore[arg-type]
        seconds = 0.0
        for entry in entries:
            if entry.analysis_id != analysis.id or not entry.shot_indexes:
                continue
            seconds += entry.seconds
            tail = entry.original_mode == "extend" or (
                entry.original_mode is None and entry.mode == "extend"
            )
            for shot in entry.shot_indexes:
                (tails if tail else heads)[shot] += 1
        return _Uses(heads, tails, seconds, len(entries))
    # bare cut indexes: one per piece that uses the cut — the head first, then its tails
    for shot, count in Counter(int(u) for u in used).items():  # type: ignore[union-attr]
        heads[shot] = 1
        tails[shot] = count - 1
    return _Uses(heads, tails, -1.0, -1)


def _is_used(piece: _Piece, uses: _Uses) -> bool:
    shots = piece.entry.shot_indexes
    if piece.tail == 0:
        return any(uses.heads[s] for s in shots)
    return uses.tails[shots[0]] >= piece.tail


def _thumbnail(analysis: ReelAnalysis, shot_indexes: Sequence[int]) -> str | None:
    pick = representative_frame(analysis, shot_indexes)
    if pick is None:
        return None
    return frame_key(pick.network, pick.post_id, pick.analysis_id, pick.frame)


def _uncovered(analysis: ReelAnalysis) -> list[LeftOutSpan]:
    shots = analysis.shots
    first = min([analysis.covered_from_s, *(s.start_s for s in shots)])
    last = max([analysis.covered_to_s, *(s.end_s for s in shots)])
    found: list[LeftOutSpan] = []
    for span_id, start, end in (
        (UNCOVERED_START, 0.0, first),
        (UNCOVERED_END, last, analysis.source_seconds),
    ):
        if end - start >= UNCOVERED_MIN_S:
            found.append(
                LeftOutSpan(
                    id=span_id,
                    start_s=round(start, 3),
                    end_s=round(end, 3),
                    seconds=max(1, round(end - start)),
                    description="",
                    reason="not_analyzed",
                    mode_hint=None,
                    thumbnail_key=None,
                )
            )
    return found


def left_out_spans(
    analysis: ReelAnalysis,
    used: ClipBlocks | Sequence[VideoPartPlan] | Iterable[int],
    *,
    products: Sequence[str] = (),
    extend_on: bool | None = None,
) -> LeftOut:
    """What of `analysis`'s reel the Clip does not use (see the module), in reel order.

    `used`: the Clip as it is NOW — its `ClipBlocks` (only the AI entries a block points
    to count), its AI entries (`Sequence[VideoPartPlan]`), or the cut indexes its parts
    use (one occurrence per part: a cut over 10 s used by its head and one tail is
    listed twice). Only entries of THIS analysis count as using the reel. With bare
    indexes the totals are counted from the plan's parts instead of the Clip's entries.
    `products` / `extend_on`: as `plan_from_analysis` (None reads the «Sigue a la
    anterior» switch). Pure."""
    uses = _uses(analysis, used)
    pieces = _pieces(analysis, products, extend_on)
    spans: list[LeftOutSpan] = []
    plan_seconds = 0.0
    plan_parts = 0
    for piece in pieces:
        if _is_used(piece, uses):
            plan_seconds += piece.entry.seconds
            plan_parts += 1
            continue
        spans.append(
            LeftOutSpan(
                id=piece.id,
                start_s=piece.start_s,
                end_s=piece.end_s,
                seconds=piece.entry.seconds,
                description=piece.entry.description,
                reason="split_tail" if piece.tail else "parts_cap",
                mode_hint=piece.entry.mode,
                thumbnail_key=_thumbnail(analysis, piece.entry.shot_indexes),
                shot_indexes=piece.entry.shot_indexes,
            )
        )
    spans.extend(_uncovered(analysis))
    spans.sort(key=lambda span: (span.start_s, span.end_s))
    return LeftOut(
        spans=tuple(spans),
        reel_seconds=round(analysis.source_seconds, 3),
        used_seconds=round(uses.seconds if uses.seconds >= 0 else plan_seconds, 3),
        ai_parts=uses.ai_parts if uses.ai_parts >= 0 else plan_parts,
    )


def _check_entry(entry: VideoPartPlan, analysis: ReelAnalysis) -> None:
    """The entry holds the v1 contract of an AI part on the tracks (m-25142725): no
    references of its own (`clip_image_keys`, `clip_audio_keys`; `clip_video_keys` only
    as the reel's window of «Igual al original», `REEL_WINDOW_ENTRY_FIELD`), no recipe
    of its own (`ai_part_own_recipe`), and an `edit` names its reel window
    (`edit_needs_reel_window`). A broken invariant here is a bug, never the owner's."""
    if entry.clip_image_keys or entry.clip_audio_keys:
        raise RuntimeError("a swapped-in part carries no references")
    if entry.clip_video_keys and entry.mode != "edit":
        raise RuntimeError("only «Igual al original» keeps a reel window")
    if entry.effects or entry.text_layers or entry.segments or entry.transition_in:
        raise RuntimeError("a swapped-in part has no recipe of its own")
    if entry.mode == "edit" and (entry.analysis_id != analysis.id or not entry.shot_indexes):
        raise RuntimeError("«Igual al original» needs its reel window")


def span_entry(
    analysis: ReelAnalysis,
    left_out_id: str,
    *,
    products: Sequence[str] = (),
    extend_on: bool | None = None,
    used: ClipBlocks | Sequence[VideoPartPlan] | Iterable[int] | None = None,
) -> VideoPartPlan:
    """The part for stretch `left_out_id` (an id of `left_out_spans`), as the plan would
    have proposed it (`parts._parts_for_group`). The screen puts it in the place of the
    part it replaces, then checks the Clip (`check_after_swap`).

    `used`: the Clip WITHOUT the part being replaced (as `left_out_spans` takes it). When
    given, a stretch the Clip already uses is `span_unknown`, and a split tail whose
    piece before it is not in the Clip is `extend_order`. Without it, only the id is
    checked.

    Raises `SpanRefused` (`span_unknown`: no such stretch in this analysis, or one that
    cannot be swapped — `not_analyzed`; `extend_order`). Pure."""
    pieces = {piece.id: piece for piece in _pieces(analysis, products, extend_on)}
    piece = pieces.get(left_out_id)
    if piece is None:
        raise SpanRefused(SPAN_UNKNOWN, left_out_id)
    if used is not None:
        uses = _uses(analysis, used)
        if _is_used(piece, uses):
            raise SpanRefused(SPAN_UNKNOWN, f"{left_out_id} is already in the Clip")
        if piece.tail:
            before_id = piece.head_id if piece.tail == 1 else f"{piece.head_id}.{piece.tail - 1}"
            before = pieces[before_id]
            if not _is_used(before, uses):
                raise SpanRefused(SPAN_EXTEND_ORDER, left_out_id)
    _check_entry(piece.entry, analysis)
    return piece.entry


def check_after_swap(
    blocks: ClipBlocks, *, other_ai_children: int = 0
) -> tuple[RecipeProblem, ...]:
    """The Clip's problems once the screen placed `span_entry`'s part: the contract's
    (`ClipBlocks.problems`) — the 60 s (`local_length_out_of_range`), the 8 blocks, the 6 AI
    children, «Sigue a la anterior» right after its part. `()` when it may be created.
    A thin name for the screen to call after every swap. Pure."""
    return blocks.problems(other_ai_children=other_ai_children)


__all__ = [
    "SPAN_EXTEND_ORDER",
    "SPAN_TEXTS",
    "SPAN_UNKNOWN",
    "UNCOVERED_END",
    "UNCOVERED_START",
    "LeftOut",
    "LeftOutReason",
    "LeftOutSpan",
    "SpanRefused",
    "check_after_swap",
    "left_out_spans",
    "span_entry",
]
