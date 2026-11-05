"""Groups of consecutive shots: what Haiku describes when the detector cut a reel finely
(m-24955652, VE-04c «salida cortada»; contract in
`docs/traspasos/historias-video-por-partes-backend.md` §VE-04c).

VE-05 (2026-11-05) measured that the sheet grows with the number of shots — about 500–650
output tokens per shot — so a reel the detector cut into 10–47 shots did not fit in the
output ceiling and was billed for a cut answer. The detector's shots are what VE-05 scores
(its cuts against a human annotation), so they are stored as detected; only the model's
view is coarser:

- **Rule (`GROUPING_VERSION`):** start with one group per detected shot. While there is
  more than one group and either some group lasts less than `GROUP_MIN_SECONDS` or there
  are more than `MAX_GROUPS`, merge the shortest group (ties: the earliest) with its
  shorter neighbour (ties: the earlier one). Deterministic, and a reel whose shots all
  last ≥ 1 s and are ≤ 12 is described shot by shot exactly as before.
- **Mapping back:** each stored shot takes its group's description (families, people and
  faces) — a merged shot says what its group shows; frames are sampled on the groups and
  stored under the detected shot they fall in, so every frame file and evidence label
  stays in the detector's numbering; what is said stays per detected shot (by time).
  `reel_sheet.groups` records the members of each group (provenance of the merge).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from qualify_creative.video.shots import ShotSpan

#: Bump with any change to the rule or its two limits (part of the prompt version).
GROUPING_VERSION = "groups-min1s-max12-1"
#: A group shorter than this is merged with a neighbour (VE-05: fast edits cut every
#: 0.3–1 s; one frame of such a shot says little on its own).
GROUP_MIN_SECONDS = 1.0
#: At most this many groups reach the model: ≈ 12 × 2 frames + 3 anchors ≤ 32 images, and
#: an answer that fits `MAX_OUTPUT_TOKENS` with room (VE-05 sizes in the module docstring).
MAX_GROUPS = 12


@dataclass(frozen=True)
class ShotGroup:
    """Consecutive detected shots described as one: `index` is what the model calls
    «plano», `members` the detected shot indices, in order."""

    index: int
    members: tuple[int, ...]
    start_s: float
    end_s: float

    @property
    def seconds(self) -> float:
        return self.end_s - self.start_s

    @property
    def span(self) -> ShotSpan:
        """The group as a span, for sampling and for the model's shot list."""
        return ShotSpan(self.index, self.start_s, self.end_s)


def group_shots(
    spans: Sequence[ShotSpan],
    *,
    min_seconds: float = GROUP_MIN_SECONDS,
    max_groups: int = MAX_GROUPS,
) -> tuple[ShotGroup, ...]:
    """The groups of `spans` by the module's rule (detected order kept)."""
    runs: list[list[ShotSpan]] = [[span] for span in spans]

    def seconds(run: list[ShotSpan]) -> float:
        return run[-1].end_s - run[0].start_s

    while len(runs) > 1:
        durations = [seconds(run) for run in runs]
        shortest = min(range(len(runs)), key=lambda i: (durations[i], i))
        if len(runs) <= max(1, max_groups) and durations[shortest] >= min_seconds:
            break
        if shortest == 0:
            other = 1
        elif shortest == len(runs) - 1:
            other = shortest - 1
        else:
            left, right = shortest - 1, shortest + 1
            other = left if durations[left] <= durations[right] else right
        first, second = sorted((shortest, other))
        runs[first : second + 1] = [runs[first] + runs[second]]
    return tuple(
        ShotGroup(
            index=i,
            members=tuple(span.index for span in run),
            start_s=float(run[0].start_s),
            end_s=float(run[-1].end_s),
        )
        for i, run in enumerate(runs)
    )


def shot_at(spans: Sequence[ShotSpan], group: ShotGroup, time_s: float) -> int:
    """The detected shot of `group` that holds `time_s` (a frame sampled on the group):
    the member whose span holds it, else the nearest member."""
    members = [span for span in spans if span.index in set(group.members)]
    for span in members:
        if span.start_s <= time_s < span.end_s:
            return span.index
    if not members:
        return group.members[0]
    return members[0].index if time_s < members[0].start_s else members[-1].index


__all__ = [
    "GROUPING_VERSION",
    "GROUP_MIN_SECONDS",
    "MAX_GROUPS",
    "ShotGroup",
    "group_shots",
    "shot_at",
]
