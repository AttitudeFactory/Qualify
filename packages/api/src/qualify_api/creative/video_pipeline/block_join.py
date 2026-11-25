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

So the Clip lasts its blocks minus each transition (`recipe.clip_seconds`). A Clip with
only cuts never reaches this step: its video is the speed step's, byte for byte.

Safety net: a block shorter than the transitions eating into it is refused before
anything is made (`recipe.block_transition_room_problems`); one that still reaches here
(the real frames of a prepared stretch differ from the recipe's by a frame) is joined
with a cut there — recorded in the provenance (`fallback_cuts`), never a failed video.

Provenance (`params.local.transitions`): this step's version, the rate, each blended join
(the block it leads into, the library entry and version, kind, duration, direction and
frames) and the segment encoder's settings. Deterministic: a retried preparation makes
the same file.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qualify_creative.schemas import PartRecipe

logger = logging.getLogger(__name__)

#: Version of this step (provenance, `steps["block_join"]`).
BLOCK_JOIN_VERSION = "block-join-v1"
#: At most this many codec threads (the creative worker runs with `cpus: 1.0`).
BLOCK_JOIN_THREADS = 1


@dataclass(frozen=True)
class BlockJoins:
    """The Clip with its blocks blended, on disk, and what its asset records."""

    path: Path
    frames: int
    seconds: float
    params: dict[str, Any]


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
    frames: Sequence[int], transitions: Sequence[Any], rate: int
) -> tuple[list[Any], list[int]]:
    """The safety net: `transitions` with a cut wherever a block would be shorter than the
    transitions eating into it (the one after it gives way first, then its own), and the
    blocks where that happened. Pure."""
    fitted = list(transitions)
    cuts: list[int] = []

    def eats(at: int) -> int:
        return fitted[at].frames(rate) if at < len(fitted) and fitted[at] is not None else 0

    for at, length in enumerate(frames):
        for side in (at + 1, at):
            if eats(at) + eats(at + 1) <= length:
                break
            if side < len(fitted) and fitted[side] is not None:
                fitted[side] = None
                cuts.append(side)
    return fitted, sorted(set(cuts))


def blend_block_joins(
    part: PartRecipe,
    video: Path,
    frames: Sequence[int],
    *,
    size: tuple[int, int],
    rate: int,
    root: Path,
    beat: Callable[[], None] | None = None,
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
    if cuts:
        logger.warning("blocks %s shorter than their transitions: joined with a cut", cuts)
    if not any(fitted):
        return None
    # the runs: a new one starts at each block that blends into the one before it
    starts = [0, *(at for at, how in enumerate(fitted) if how is not None)]
    bounds = [sum(frames[:at]) for at in (*starts, len(frames))]
    clips = [
        JoinClip(
            video,
            start_s=bounds[k] / rate,
            end_s=bounds[k + 1] / rate,
            transition_in=fitted[start] if k else None,
        )
        for k, start in enumerate(starts)
    ]
    segments = []
    written: list[Path] = []
    try:
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
    joins = [
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
    x264 = segment_x264()
    params = {
        "version": BLOCK_JOIN_VERSION,
        "fps": rate,
        "joins": joins,
        "fallback_cuts": cuts,
        "frames": joined.frames,
        "encoder": {"crf": x264["crf"], "rc-lookahead": x264["rc-lookahead"]},
    }
    return BlockJoins(
        path=joined.path, frames=joined.frames, seconds=joined.frames / rate, params=params
    )


__all__ = [
    "BLOCK_JOIN_VERSION",
    "BlockJoins",
    "blend_block_joins",
    "block_transitions",
    "fitting",
]
