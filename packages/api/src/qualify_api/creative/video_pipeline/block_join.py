"""The transitions between a `local` Clip's blocks (m-25114465, ADR 50 §10 — proposed).

`local.render_local_part` lays the blocks (the owner's stretches and photos) end to end
with hard cuts in ONE encode (`speed.render_speed`, 30 fps, one AAC track). When a block
has a `transition_in` (`SourceSegment.transition_in`: `fundido` or `barrido` v2), this
step blends it with the block before it, BEFORE the layers and the texts, so their times
(seconds of the Clip's output) are read on the video that comes out:

- the built video is cut at the joins that blend into RUNS of blocks (blocks joined by a
  cut stay together, exactly as the speed step laid them, sound and fades included);
- each run is a `JoinClip` over that same file (its interval in frames of 30 fps), and
  the runs are joined with EF-16's own segment path — `video.join.encode_segment` for
  each run (`drop_head`/`drop_tail`: the frames a transition overlaps), one
  `video.join.encode_transition` per blending join (`JoinTransition`: the last `n`
  frames of one block blended with the first `n` of the next, the sound crossfaded over
  exactly those samples) and `video.join.concat_segments` (packets copied, the sound
  encoded once). Nothing of the transition is drawn here: it is the join's.
- One decoder at a time, 1 codec thread (the worker's `cpus: 1.0`), as the parts' final.
  The built video is our own closed-GOP H.264, so each run is decoded from the key frame
  before it (`JoinClip.seek`), not from the file's start.

So the Clip lasts its blocks minus each transition (`recipe.clip_seconds`). A Clip with
only cuts never reaches this step: its video is the speed step's, byte for byte.

Safety net: a block that keeps fewer than `recipe.BLOCK_MIN_FREE_FRAMES` frames of its own
besides the transitions eating into it is refused before anything is made
(`recipe.block_transition_room_problems`); one that still reaches here (the real frames of
a prepared stretch differ from the recipe's by a frame) is joined with a cut there —
recorded in the provenance (`fallback_cuts`) and the asset's warnings, never a failed
video.

The join can take minutes on one CPU (`docs/armado-local-medicion.md`): the draft's
heartbeat (`beat`) is called before it starts, after every run and every transition, and
every `BEAT_EVERY_S` from a thread while it runs, so `reap_stale_drafts` never takes it
for a dead one.

Provenance (`params.local.transitions`): this step's version, the rate, each blended join
(the block it leads into, the library entry and version, kind, duration, direction and
frames) and the segment encoder's settings. Deterministic: a retried preparation makes
the same file.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_creative.schemas import PartRecipe

from qualify_api.creative.video_pipeline.recipe import BLOCK_MIN_FREE_FRAMES

logger = logging.getLogger(__name__)

#: Version of this step (provenance, `steps["block_join"]`).
BLOCK_JOIN_VERSION = "block-join-v1"
#: At most this many codec threads (the creative worker runs with `cpus: 1.0`).
BLOCK_JOIN_THREADS = 1
#: How often the draft's heartbeat is called while the join runs (well under the 20 min
#: after which `reap_stale_drafts` fails a draft). Tests shorten it.
BEAT_EVERY_S = 60.0
#: The warning code a join made a cut instead of its transition leaves in the asset.
FALLBACK_CUT_WARNING = "transition_fallback_cut"


@dataclass(frozen=True)
class BlockJoins:
    """The Clip with its blocks blended, on disk, and what its asset records. `path` is
    the speed step's own video when every join fell back to a cut (`blended` False)."""

    path: Path
    frames: int
    seconds: float
    params: dict[str, Any]
    blended: bool = True
    warnings: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def block_transitions(part: PartRecipe) -> list[Any]:
    """The join's transition INTO each block, in block order (`JoinTransition` or None
    — a cut; always None for the first block), from each block's `transition_in` through
    EF-16's own reading (`part_join.join_transition_of`: `fundido`/`barrido` v2 with the
    library's defaults for what the owner left out). Pure (the library is cached)."""
    from qualify_api.creative.part_join import join_transition_of  # noqa: PLC0415

    return [
        None if at == 0 else join_transition_of(segment.transition_in)
        for at, segment in enumerate(part.segments)
    ]


def fitting(
    frames: Sequence[int],
    transitions: Sequence[Any],
    rate: int,
    *,
    min_free: int = BLOCK_MIN_FREE_FRAMES,
) -> tuple[list[Any], list[int]]:
    """The safety net: `transitions` with a cut wherever a block that blends would keep
    fewer than `min_free` frames of its own besides the transitions eating into it (the
    one after it gives way first, then its own), and the blocks whose transition became a
    cut, in order. Pure."""
    fitted = list(transitions)
    cuts: list[int] = []

    def eats(at: int) -> int:
        return fitted[at].frames(rate) if at < len(fitted) and fitted[at] is not None else 0

    def fits(at: int, length: int) -> bool:
        eaten = eats(at) + eats(at + 1)
        return eaten == 0 or eaten + min_free <= length

    for at, length in enumerate(frames):
        for side in (at + 1, at):
            if fits(at, length):
                break
            if side < len(fitted) and fitted[side] is not None:
                fitted[side] = None
                cuts.append(side)
    return fitted, sorted(set(cuts))


def _beating(beat: Callable[[], None] | None) -> AbstractContextManager[None]:
    """The draft's heartbeat every `BEAT_EVERY_S` while the join runs (the creative
    service's own `_beating`); nothing without a beat."""
    if beat is None:
        return nullcontext()
    from qualify_api.creative.service import _beating as beating  # noqa: PLC0415

    return beating(beat, BEAT_EVERY_S)


def blend_block_joins(
    part: PartRecipe,
    video: Path,
    frames: Sequence[int],
    *,
    size: tuple[int, int],
    rate: int,
    root: Path,
    beat: Callable[[], None] | None = None,
    draft_id: UUID | None = None,
) -> BlockJoins | None:
    """`video` (the speed step's, its blocks laid end to end: `frames[i]` frames each at
    `rate`) with each block's transition blended into the block before it (see the
    module), written in `root`. None when every join is a cut — the video stays as it
    is. Raises `JoinError` when the file cannot be read or written (the disk, a bug):
    the caller's video was not made, never a half-made one."""
    from qualify_creative.video.join import (  # noqa: PLC0415
        JoinClip,
        concat_segments,
        encode_segment,
        encode_transition,
        segment_x264,
    )

    wanted = block_transitions(part)
    if len(frames) != len(wanted) or not any(wanted):
        return None
    fitted, cuts = fitting(frames, wanted, rate)
    warnings = tuple({"block": at, "code": FALLBACK_CUT_WARNING} for at in cuts)
    if cuts:
        logger.warning(
            "draft %s: blocks %s shorter than their transitions: joined with a cut",
            draft_id,
            cuts,
        )
    x264 = segment_x264()
    params: dict[str, Any] = {
        "version": BLOCK_JOIN_VERSION,
        "fps": rate,
        "joins": [],
        "fallback_cuts": cuts,
        "frames": sum(frames),
        "encoder": {"crf": x264["crf"], "rc-lookahead": x264["rc-lookahead"]},
    }
    if not any(fitted):
        total = sum(frames)
        return BlockJoins(
            path=video,
            frames=total,
            seconds=total / rate,
            params=params,
            blended=False,
            warnings=warnings,
        )
    # the runs: a new one starts at each block that blends into the one before it
    starts = [0, *(at for at, how in enumerate(fitted) if how is not None)]
    bounds = [sum(frames[:at]) for at in (*starts, len(frames))]
    clips = [
        JoinClip(
            video,
            start_s=bounds[k] / rate,
            end_s=bounds[k + 1] / rate,
            transition_in=fitted[start] if k else None,
            seek=True,  # our own closed-GOP H.264: from the key frame before the run
        )
        for k, start in enumerate(starts)
    ]
    segments = []
    written: list[Path] = []
    if beat is not None:
        beat()  # the speed step may have taken minutes: alive again before the join
    try:
        with _beating(beat):
            for k, clip in enumerate(clips):
                if k:
                    made = encode_transition(
                        clips[k - 1],
                        clip,
                        out=root / f"block-join-{k}.mp4",
                        pcm_out=root / f"block-join-{k}.pcm",
                        size=size,
                        fps=rate,
                        threads=BLOCK_JOIN_THREADS,
                    )
                    segments.append(made)
                    written += [made.path, made.pcm]
                    if beat is not None:
                        beat()
                after = clips[k + 1].transition_in if k + 1 < len(clips) else None
                made = encode_segment(
                    clip,
                    out=root / f"block-run-{k}.mp4",
                    pcm_out=root / f"block-run-{k}.pcm",
                    size=size,
                    fps=rate,
                    threads=BLOCK_JOIN_THREADS,
                    drop_head=clip.transition_in.frames(rate) if clip.transition_in else 0,
                    drop_tail=after.frames(rate) if after is not None else 0,
                )
                segments.append(made)
                written += [made.path, made.pcm]
                if beat is not None:
                    beat()
            joined = concat_segments(segments, out=root / "local-blocks.mp4", fps=rate)
    finally:
        for path in written:
            path.unlink(missing_ok=True)
    params["joins"] = [
        {
            "block": at,
            "effect_id": how.source[0] if how.source else None,
            "version": how.source[1] if how.source else None,
            **how.as_spec(),
            "frames": how.frames(rate),
        }
        for at, how in enumerate(fitted)
        if how is not None
    ]
    params["frames"] = joined.frames
    return BlockJoins(
        path=joined.path,
        frames=joined.frames,
        seconds=joined.frames / rate,
        params=params,
        warnings=warnings,
    )


__all__ = [
    "BEAT_EVERY_S",
    "BLOCK_JOIN_VERSION",
    "BlockJoins",
    "FALLBACK_CUT_WARNING",
    "blend_block_joins",
    "block_transitions",
    "fitting",
]
