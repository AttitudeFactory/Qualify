"""«Tocar la unión» (m-25114465, part 1; epic «Video con efectos, por pasos», ADR 50 §10):
how two blocks of «Fotos y videos» meet in the Clip editor — «Corte», «Fundido» or
«Barrido» — pure, no Reflex.

Between every two blocks of the timeline there is a join (Deivid: «la unión»). Tapped,
it offers «Corte» (the default: nothing travels), «Fundido» or «Barrido». The choice is
kept by the id of the block AFTER the join (`CreativeState.clip_block_joins`), so it
moves with that block when the owner reorders them, and is dropped when that block
becomes the first (it has no block before it) or is taken out.

Where every number comes from (nothing is written here by hand):

- which library entries the server blends and at what version: the server's
  `DRAWN_TRANSITIONS` (`qualify_api.creative.video_pipeline.recipe`);
- each one's duration range: the server's `transition_duration_range`; its defaults and
  a wipe's directions: that same library entry (`qualify_creative.effects`). Deivid
  2026-11-26: the owner picks the duration (a bar, 0,1 s a step, never past what fits)
  and a wipe's direction; a kind is offered when its range's SHORTEST fits, and starts at
  its default or at the longest that fits;
- the frames a transition overlaps its blocks, the room a join has and the blocks too
  short for their transitions: the server's own `transition_frames`,
  `block_transition_room_s` and `block_transition_room_problems`, with its words
  (`transitions_longer_than_block_text`).

What travels is `SourceSegment.transition_in` (the contract's last field), only when it
blends, only on a block after the first, only on a Clip made here from the owner's photos
and videos, and only with the switch `QUALIFY_CLIP_BLOCK_TRANSITIONS` on — off (the
default), no join is drawn and nothing changes.

The video lasts its blocks minus each transition (`recipe.clip_seconds`). On the
timeline each join's overlap comes off the END of the block before it (`tail_s`): block
`n` then starts exactly where the server starts it, and the track still has no gaps.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import editor_preview_contract as contract
from .ui import timeline_vm

#: The switch (Deivid 2026-11-25): off by default — no join on screen, no `transition_in`.
#: The server's own name and reading (`recipe.clip_block_transitions_on`): with it off the
#: server refuses any join but «Corte» (`recipe_unavailable`), so the screen never offers one.
JOINS_SWITCH = "QUALIFY_CLIP_BLOCK_TRANSITIONS"


def joins_enabled() -> bool:
    """The server's `clip_block_transitions_on()` (only `on`; anything else is off), read at
    call time. Off when the server cannot be read."""
    try:
        from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415
            clip_block_transitions_on,
        )

        return bool(clip_block_transitions_on())
    except Exception:  # noqa: BLE001 — never a transition the server may refuse
        return False


CUT = contract.CUT_EFFECT_ID
FADE = "fundido"
WIPE = "barrido"
#: In the order the join offers them.
KINDS: tuple[str, ...] = (CUT, FADE, WIPE)
#: A block kind whose joins stay «Corte» (the avatar is not on main yet: the rule waits).
AVATAR_KIND = "avatar"
#: Frames per second of the Clip's blocks (the speed step's; the server counts in them).
_FPS_FALLBACK = 30

# -- words -------------------------------------------------------------------------------

LABELS = {CUT: "Corte", FADE: "Fundido", WIPE: "Barrido"}
#: Deivid 2026-11-26 (option A): a sentence about ONE block names it as the timeline
#: does («Video 1», «Foto 2»: `ui.timeline_vm.media_label`); «bloque» stays where no
#: block in particular is meant («Estos bloques…», «Toca el punto entre dos bloques…»).
#: The join's button: «Unión entre Video 1 y Foto 2: Corte».
_NAME = "Unión entre {a} y {b}: {kind}"
_TITLE = "Unión entre {a} y {b}"
HELP = "Elige cómo pasa tu video de una foto o video al siguiente."
#: ux review (2026-11-26): how to find the joins, under the timeline, until the first one.
FIND_HINT = "Toca el punto entre dos fotos o videos para elegir cómo pasa tu video de uno al otro."


#: Server PR #804 (m-25114465, measured at 768 MiB and 1 CPU, noisy): a Clip with at
#: least one join that is not «Corte» is encoded again whole — about this many minutes
#: once per video — plus about `EXTRA_MINUTES_PER_JOIN` for each such join (2 wipes ≈ 7
#: min, 7 transitions ≈ 12 min). The server exposes no constant for it: these are the
#: ONE place to change when it is measured again.
EXTRA_MINUTES_FIXED = 5.0
EXTRA_MINUTES_PER_JOIN = 1.0


def extra_minutes(kinds: Sequence[str]) -> int | None:
    """How many minutes more the video takes to be ready with these joins, rounded UP
    (#804: `EXTRA_MINUTES_FIXED` + `EXTRA_MINUTES_PER_JOIN` × the joins that are not
    «Corte»); None with only cuts. The words follow it (`slower_line`)."""
    blending = sum(1 for kind in kinds if kind and kind != CUT)
    if not blending:
        return None
    return math.ceil(EXTRA_MINUTES_FIXED + EXTRA_MINUTES_PER_JOIN * blending - 1e-9)


def slower_line(kinds: Sequence[str]) -> str:
    """Beside «Crear» and in the join's panel: "" with only cuts; else that the video
    takes longer — in minutes only once `extra_minutes` knows them."""
    if all(kind == CUT for kind in kinds):
        return ""
    minutes = extra_minutes(kinds)
    how_much = f"unos {minutes} minutos" if minutes else "unos minutos"
    return f"Con las uniones que elegiste, tu video tarda {how_much} más en estar listo."


#: No room for any transition between these two blocks (`block_transition_room_s`).
NO_ROOM = (
    "Estas fotos o videos son muy cortos para unirlos con fundido o barrido. "
    "Alárgalos para elegirlos."
)
#: A block of avatar on either side.
WITH_AVATAR = "Con un bloque de avatar, la unión solo puede ser un corte."
#: The duration bar's accessible name, by kind.
SECONDS_LABELS = {FADE: "Duración del fundido", WIPE: "Duración del barrido"}
#: A wipe's directions (the library's `left|right|up|down`), as the owner reads them.
DIRECTION_LABELS = {"left": "Izquierda", "right": "Derecha", "up": "Arriba", "down": "Abajo"}
#: Each direction's arrow (`rx.icon`), the way the block moves in: checked against
#: `qualify_creative.video.join` — `left` uncovers the next block from the right edge, its
#: edge travelling left; `up` from the bottom, travelling up.
DIRECTION_ICONS = {
    "left": "arrow-left",
    "right": "arrow-right",
    "up": "arrow-up",
    "down": "arrow-down",
}
_DIRECTION_TITLE = "Hacia dónde se mueve {b}"


def direction_title(after: str) -> str:
    """The direction group's name: «Hacia dónde se mueve Foto 2» (`after`: the block
    coming in, as the timeline names it)."""
    return _DIRECTION_TITLE.format(b=after)


_SECONDS_PUT = "La unión entre {a} y {b} dura {s} s. Tu video queda {s} s más corto."
_DIRECTION_PUT = "{b} entra hacia {way}."
_TOWARDS = {"left": "la izquierda", "right": "la derecha", "up": "arriba", "down": "abajo"}
#: ux review (2026-11-26): why the video is shorter — the two blocks overlap.
_OVERLAP = "Durante el {kind} se ven los dos a la vez, así que tu video queda {s} s más corto."


def seconds_put_line(before: str, after: str, seconds: float) -> str:
    return _SECONDS_PUT.format(a=before, b=after, s=contract.seconds_text(seconds))


def overlap_line(kind: str, seconds: float) -> str:
    """Under «Dura 0,5 s»: «Durante el fundido se ven los dos a la vez, así que tu video
    queda 0,5 s más corto.» ("" for «Corte» or nothing overlapping)."""
    if kind not in (FADE, WIPE) or seconds <= 0:
        return ""
    return _OVERLAP.format(kind=kind, s=contract.seconds_text(seconds))


def direction_put_line(after: str, way: str) -> str:
    return _DIRECTION_PUT.format(b=after, way=_TOWARDS.get(way, way))


_PUT = {
    CUT: "Dejaste un corte entre {a} y {b}.",
    FADE: "Pusiste un fundido entre {a} y {b}.",
    WIPE: "Pusiste un barrido entre {a} y {b}.",
}


def join_name(before: str, after: str, kind: str) -> str:
    """The join between `before` and `after` (as the timeline names them) as a button's
    name: «Unión entre Video 1 y Foto 2: Corte»."""
    return _NAME.format(a=before, b=after, kind=LABELS.get(kind, LABELS[CUT]))


def join_title(before: str, after: str) -> str:
    return _TITLE.format(a=before, b=after)


def put_line(before: str, after: str, kind: str) -> str:
    """The live line once the owner chose: «Pusiste un fundido entre Video 1 y Foto 2.»"""
    return _PUT.get(kind, _PUT[CUT]).format(a=before, b=after)


# -- the library and the server ---------------------------------------------------------


@dataclass(frozen=True)
class JoinSpec:
    """A transition the join offers: its library entry and its parameters at their
    defaults (`params`, sorted pairs), its default length and its range."""

    effect_id: str
    version: int
    drawn: str  # "fade" | "wipe" (the server's `DRAWN_TRANSITIONS`)
    params: tuple[tuple[str, contract.EffectParamValue], ...]
    duration_s: float
    min_s: float
    max_s: float
    #: The directions a wipe may take, in the library's order (() for a fade).
    directions: tuple[str, ...] = ()

    @property
    def direction(self) -> str:
        """The library's default direction ("" for a fade)."""
        return str(dict(self.params).get("direction") or "")


_SPECS: dict[str, JoinSpec] = {}


def _read_specs() -> dict[str, JoinSpec]:
    from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415 — pure, cached
        DRAWN_TRANSITIONS,
        transition_duration_range,
    )
    from qualify_creative.effects import load_effects  # noqa: PLC0415

    library = load_effects()
    out: dict[str, JoinSpec] = {}
    for effect_id in dict.fromkeys(effect for effect, _ in DRAWN_TRANSITIONS):
        # the range is the server's (`transition_duration_range`: the newest offered entry
        # the join draws); the default and the other parameters are that same entry's
        span = transition_duration_range(effect_id, library)
        drawn = [
            entry
            for entry in library.offered()
            if entry.id == effect_id and (entry.id, entry.version) in DRAWN_TRANSITIONS
        ]
        if span is None or not drawn:
            continue
        entry = max(drawn, key=lambda each: each.version)
        spec = entry.params.get("duration_s")
        if spec is None or spec.default is None:
            continue
        defaults = {name: p.default for name, p in entry.params.items() if p.default is not None}
        direction = entry.params.get("direction")
        out[effect_id] = JoinSpec(
            directions=tuple(str(v) for v in direction.values) if direction else (),
            effect_id=effect_id,
            version=int(entry.version),
            drawn=str(DRAWN_TRANSITIONS[(effect_id, entry.version)]),
            params=tuple(sorted(defaults.items())),
            duration_s=float(spec.default),  # type: ignore[arg-type]
            min_s=span[0],
            max_s=span[1],
        )
    return out


def specs() -> dict[str, JoinSpec]:
    """`{effect_id: JoinSpec}` of what the join may offer, read once per process ({} when
    the library or the server cannot be read: then only «Corte»)."""
    if not _SPECS:
        try:
            _SPECS.update(_read_specs())
        except Exception:  # noqa: BLE001 — the editor keeps working with cuts only
            return {}
    return _SPECS


#: The duration bar moves 0,1 s a step (Deivid 2026-11-26, like the texts' fade).
STEP_S = 0.1


def snap_seconds(value: float) -> float:
    """A duration on the bar's 0,1 s grid."""
    return round(round(float(value) / STEP_S) * STEP_S, 1)


def seconds_of(kind: str, seconds: float | None) -> float:
    """The duration a `kind` takes: `seconds` on the grid and inside the server's range
    (`transition_duration_range`), else the library's default. 0 for «Corte»."""
    spec = specs().get(kind)
    if spec is None:
        return 0.0
    if seconds is None:
        return spec.duration_s
    return min(max(snap_seconds(seconds), spec.min_s), spec.max_s)


def direction_of(kind: str, direction: str | None) -> str:
    """A wipe's direction: `direction` when the library offers it, else its default;
    "" for a fade."""
    spec = specs().get(kind)
    if spec is None or not spec.directions:
        return ""
    return direction if direction in spec.directions else spec.direction


def use_of(
    kind: str, seconds: float | None = None, direction: str | None = None
) -> contract.EffectUse | None:
    """The `transition_in` of a choice (None for «Corte» or one not offered): its
    `duration_s` (`seconds_of`) and, a wipe, its `direction` (`direction_of`) — the
    library's defaults for what the owner did not choose."""
    spec = specs().get(kind)
    if spec is None:
        return None
    params = dict(spec.params)
    params["duration_s"] = seconds_of(kind, seconds)
    if spec.directions:
        params["direction"] = direction_of(kind, direction)
    return contract.EffectUse(spec.effect_id, spec.version, params=tuple(sorted(params.items())))


def _fps() -> int:
    try:
        from qualify_creative.video.speed import SPEED_FPS  # noqa: PLC0415

        return int(SPEED_FPS)
    except Exception:  # noqa: BLE001
        return _FPS_FALLBACK


def _server_use(use: contract.EffectUse) -> Any:
    from qualify_creative.schemas import EffectUse  # noqa: PLC0415

    return EffectUse(effect_id=use.effect_id, version=use.version, params=use.params)


def overlap_s(use: contract.EffectUse | None) -> float:
    """How many seconds a block's `transition_in` takes off the Clip — the server's
    frames (`transition_frames` at the speed step's rate), 0 for a cut or one it does not
    draw."""
    if use is None:
        return 0.0
    try:
        from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415
            transition_frames,
        )

        rate = _fps()
        return transition_frames(_server_use(use), rate=rate) / rate
    except Exception:  # noqa: BLE001
        return 0.0


def transitions_seconds(segments: Sequence[contract.SourceSegment]) -> float:
    """What the transitions of `segments` take off the Clip (never the first block's)."""
    return sum(overlap_s(s.transition_in) for at, s in enumerate(segments) if at > 0)


def _server_part(segments: Sequence[contract.SourceSegment]) -> Any:
    """The server's `PartRecipe` of a local Clip of `segments` (None when the server
    would not read them: a stretch the editor already stops for another reason)."""
    from qualify_creative.schemas import PartRecipe  # noqa: PLC0415

    data = contract.to_dict(contract.PartRecipe(segments=tuple(segments)))["segments"]
    seconds = max(sum(s.output_seconds for s in segments), 0.1)
    try:
        return PartRecipe(index=1, mode="local", seconds=seconds, segments=data)
    except ValueError:
        return None


def room_problems(segments: Sequence[contract.SourceSegment]) -> dict[int, str]:
    """`{block: words}` for every block (0-based) shorter than the transitions eating
    into it — the server's own check and words (`block_transition_room_problems`,
    `transitions_longer_than_block_text`). {} with only cuts."""
    if not any(s.transition_in is not None for s in segments[1:]):
        return {}
    try:
        from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415
            block_transition_room_problems,
            transitions_longer_than_block_text,
        )

        part = _server_part(segments)
        if part is None:
            return {}
        out: dict[int, str] = {}
        for problem in block_transition_room_problems(part):
            field = str(problem.field or "")
            if field.startswith("segments[") and field.endswith("]"):
                at = int(field[len("segments[") : -1])
                out[at] = transitions_longer_than_block_text(at + 1)
        return out
    except Exception:  # noqa: BLE001
        return {}


def options(
    segments: Sequence[contract.SourceSegment],
    block: int,
    *,
    local: bool,
    kinds: Sequence[str] = (),
) -> tuple[str, ...]:
    """What the join INTO `block` (0-based, 1 or more) offers: always «Corte»; «Fundido»
    and «Barrido» only on a Clip made here (`local`), with no avatar on either side
    (`kinds`: each block's kind), and only where the transition fits at the SHORTEST of
    its range (`fit_seconds`). () for the first block or one out of range."""
    if not 1 <= block < len(segments):
        return ()
    near = [kinds[at] for at in (block - 1, block) if at < len(kinds)]
    if not local or AVATAR_KIND in near or not specs():
        return (CUT,)
    offered = [CUT]
    for kind in (FADE, WIPE):
        if fit_seconds(segments, block, kind) is not None:
            offered.append(kind)
    return tuple(offered)


def _room_frames(segments: Sequence[contract.SourceSegment], block: int) -> int | None:
    """The server's room of the join INTO `block`, in frames (`block_transition_room_s`:
    its two blocks keep their own frames, the other joins as they are now; this join's
    own choice does not count). None when the server cannot say."""
    try:
        from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415
            block_transition_room_s,
        )

        part = _server_part(segments)
        if part is None:
            return None
        rate = _fps()
        return round(block_transition_room_s(part, block) * rate)
    except Exception:  # noqa: BLE001
        return None


def fit_seconds(segments: Sequence[contract.SourceSegment], block: int, kind: str) -> float | None:
    """The LONGEST duration of `kind`, on the bar's grid and inside its range, that the
    join INTO `block` fits now — None when not even the range's shortest fits."""
    spec = specs().get(kind)
    if spec is None or not 1 <= block < len(segments):
        return None
    room = _room_frames(segments, block)
    if room is None:
        return None
    rate = _fps()
    best: float | None = None
    value = spec.min_s
    while value <= spec.max_s + 1e-9:
        if round(overlap_s(use_of(kind, value)) * rate) <= room:
            best = seconds_of(kind, value)
        value = round(value + STEP_S, 1)
    return best


def start_seconds(kind: str, fit: float | None) -> float | None:
    """Where the bar starts when the owner picks `kind`: the library's default, or the
    longest that fits (`fit`) when the default does not (None: nothing fits)."""
    spec = specs().get(kind)
    if spec is None or fit is None:
        return None
    return spec.duration_s if spec.duration_s <= fit + 1e-9 else fit


# -- the timeline's media ---------------------------------------------------------------


def apply_joins(
    media: Sequence[Mapping[str, object]],
    joins: Mapping[str, str],
    *,
    enabled: bool,
    local: bool,
    seconds: Mapping[str, float] | None = None,
    directions: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """The timeline's media with each block's chosen join (`joins`: block id → kind;
    `seconds` / `directions`: the owner's duration and wipe direction by the same id, the
    library's defaults when missing): `join` (the kind), `join_len` (its chosen
    duration), `join_s` (seconds it overlaps, the server's frames), `join_drawn` /
    `join_dir` (what the preview draws) on the block after the join, and `tail_s` on the
    block before it. Never on the first block, nor off the switch, nor on a Clip not made
    here, nor beside an avatar. Copies: `media` is not changed."""
    out = [dict(item) for item in media]
    if not enabled or not local:
        return out
    # only blocks that become a stretch meet (`has_length`, as `timeline_segments` skips
    # the others): a block of no length neither joins nor is joined
    laid = [item for item in out if has_length(item)]
    for at in range(1, len(laid)):
        item, before = laid[at], laid[at - 1]
        block = str(item.get("id") or "")
        kind = joins.get(block, CUT)
        if kind == CUT or AVATAR_KIND in (item.get("kind"), before.get("kind")):
            continue
        spec = specs().get(kind)
        length = seconds_of(kind, (seconds or {}).get(block))
        way = direction_of(kind, (directions or {}).get(block))
        overlap = overlap_s(use_of(kind, length, way))
        if spec is None or overlap <= 0:
            continue
        item.update(join=kind, join_len=length, join_s=overlap, join_drawn=spec.drawn, join_dir=way)
        before["tail_s"] = overlap
    return out


def has_length(item: Mapping[str, object]) -> bool:
    """Whether a timeline block becomes a stretch of the recipe — the same test as
    `clip_editor_vm.timeline_segments` (a key, and a photo's seconds or a video's span
    over 0 to the hundredth)."""
    if not str(item.get("key") or ""):
        return False
    try:
        if item.get("kind") == "photo":
            return round(float(item.get("dur") or 0.0), 2) > 0  # type: ignore[arg-type]
        if item.get("kind") == AVATAR_KIND:
            return True  # not on main yet: kept, so the joins beside it stay «Corte»
        start = round(float(item.get("src_start") or 0.0), 2)  # type: ignore[arg-type]
        return round(float(item.get("src_end") or 0.0), 2) > start  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def segment_ids(media: Sequence[Mapping[str, object]]) -> list[str]:
    """The block id of each stretch of the recipe, in order: a join's segment index is
    its block's place here, never its place in `media` (review: a block of no length is
    on the timeline but not in the recipe)."""
    return [str(item.get("id") or "") for item in media if has_length(item)]


def tail_of(item: Mapping[str, object]) -> float:
    """Seconds the block's END overlaps the next block's join (0 = a cut)."""
    try:
        return max(float(item.get("tail_s") or 0.0), 0.0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def transition_of(item: Mapping[str, object]) -> contract.EffectUse | None:
    """The `transition_in` of a timeline block (`apply_joins`'s `join`)."""
    kind = str(item.get("join") or "")
    if not kind or kind == CUT:
        return None
    length = item.get("join_len")
    return use_of(
        kind,
        float(length) if isinstance(length, int | float) else None,
        str(item.get("join_dir") or "") or None,
    )


def clean_joins(joins: Mapping[str, str], media: Sequence[Mapping[str, object]]) -> dict[str, str]:
    """The joins kept after the blocks changed: only blocks still there and not first,
    and only a kind the join knows (none left on the first block — reordered or not)."""
    after_first = set(segment_ids(media)[1:])
    return {
        block: kind
        for block, kind in joins.items()
        if block in after_first and kind in KINDS and kind != CUT
    }


def clean_by_join(values: Mapping[str, Any], joins: Mapping[str, str]) -> dict[str, Any]:
    """A join's duration or direction kept only while its join still blends."""
    return {block: value for block, value in values.items() if block in joins}


def join_rows(
    media: Sequence[Mapping[str, object]],
    segments: Sequence[contract.SourceSegment],
    *,
    local: bool,
    open_id: str = "",
    starts: Sequence[float] = (),
) -> list[dict[str, str]]:
    """Every join of the timeline, for the screen: `id` (the block after it), `at` (its
    second on the track, where that block starts: `starts`), `kind`, `label` (its
    choice), `name` (the button's accessible name), `title`, `open` ("1" = its panel
    shows), `warn` ("1" = one of its blocks is too short for its transitions), the
    offered kinds (`offered`, comma-separated), `slower` (the line for its choice), `why`
    (why only «Corte», "" when more is offered) and `problem` (the server's words)."""
    problems = room_problems(segments)
    # the joins are between the blocks that become stretches (`segment_ids`), indexed as
    # the recipe's segments; `starts` stays by the block's place on the timeline
    places = [n for n, item in enumerate(media) if has_length(item)]
    laid = [media[n] for n in places]
    kinds = [str(item.get("kind") or "") for item in laid]
    matched = len(laid) == len(segments)
    rows: list[dict[str, str]] = []
    # the whole Clip's extra time (#804: once per video, plus each join), in every panel
    slower = slower_line([str(item.get("join") or CUT) for item in laid[1:]])
    for at in range(1, len(laid)):
        item = laid[at]
        kind = str(item.get("join") or CUT)
        offered = options(segments, at, local=local, kinds=kinds) if matched else (CUT,)
        problem = problems.get(at) or problems.get(at - 1) or ""
        why = ""
        if offered == (CUT,):
            near = (kinds[at - 1], kinds[at])
            why = WITH_AVATAR if AVATAR_KIND in near else (NO_ROOM if local else "")
        spec = specs().get(kind)
        length = float(item.get("join_len") or 0.0)  # type: ignore[arg-type]
        fit = fit_seconds(segments, at, kind) if spec is not None and matched else None
        place = places[at]
        # the names the timeline shows («Video 1», «Foto 2»), by place on the track
        before_label = timeline_vm.media_label(laid[at - 1], places[at - 1] + 1)
        after_label = timeline_vm.media_label(item, place + 1)
        begin = float(starts[place]) if place < len(starts) else 0.0
        centre = begin + float(item.get("join_s") or 0.0) / 2  # type: ignore[arg-type]
        low = spec.min_s if spec is not None else 0.0
        # the bar never goes past what fits (nor hides a length chosen before it stopped
        # fitting: then the server's words say so, and the bar brings it back)
        high = max(fit if fit is not None else low, length)
        way = str(item.get("join_dir") or "")
        rows.append(
            {
                "id": str(item.get("id") or ""),
                # the block before it: its trim handles win while either is chosen
                "before": str(laid[at - 1].get("id") or ""),
                # the block right before it ON THE TRACK (one of no length may sit there):
                # chosen, its handles sit on this point too
                "beside": str(media[place - 1].get("id") or "") if place > 0 else "",
                # centred on the overlap (Deivid: «bloques enteros, encimados»): the
                # block after starts there and lies over the block before for `join_s`
                "at": f"{round(centre, 2):g}",
                "kind": kind,
                "label": LABELS.get(kind, LABELS[CUT]),
                "name": join_name(before_label, after_label, kind),
                "title": join_title(before_label, after_label),
                "before_label": before_label,
                "after_label": after_label,
                "open": "1" if open_id and open_id == str(item.get("id") or "") else "",
                "warn": "1" if problem else "",
                "offered": ",".join(offered),
                "slower": slower,
                "direction_title": direction_title(after_label),
                "why": "" if problem else why,
                "problem": problem,
                # Deivid 2026-11-26: its duration (a bar, 0,1 s a step) and a wipe's way
                "has_seconds": "1" if spec is not None else "",
                "seconds": f"{length:g}" if spec is not None else "",
                "seconds_min": f"{low:g}",
                "seconds_max": f"{high:g}",
                "fit": "" if fit is None else f"{fit:g}",
                "seconds_line": seconds_line(length) if spec is not None else "",
                # ux review: why the video comes out shorter, in the words of its choice
                "overlap_line": overlap_line(kind, float(item.get("join_s") or 0.0))
                if spec is not None
                else "",
                "seconds_label": SECONDS_LABELS.get(kind, ""),
                "has_direction": "1" if spec is not None and spec.directions else "",
                "direction": way,
                "directions": ",".join(spec.directions) if spec is not None else "",
            }
        )
    return rows


def option_rows(row: Mapping[str, str]) -> list[dict[str, str]]:
    """The open join's choices, in order (`row` is one of `join_rows`)."""
    offered = [k for k in str(row.get("offered") or "").split(",") if k]
    return [{"value": kind, "label": LABELS[kind]} for kind in KINDS if kind in offered]


def direction_rows(row: Mapping[str, str]) -> list[dict[str, str]]:
    """The open wipe's directions, in the library's order: `{value, label, icon}`."""
    ways = [w for w in str(row.get("directions") or "").split(",") if w]
    return [
        {
            "value": way,
            "label": DIRECTION_LABELS.get(way, way),
            "icon": DIRECTION_ICONS.get(way, "arrow-left"),
        }
        for way in ways
    ]


def seconds_line(seconds: float) -> str:
    """«Dura 0,5 s» over the duration bar."""
    return f"Dura {contract.seconds_text(seconds)} s"


def seconds_from_slider(value: object) -> float | None:
    """The bar's value (Radix sends a list) as a number, None when it is not one."""
    raw = value[0] if isinstance(value, list | tuple) and value else value
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


__all__ = [
    "AVATAR_KIND",
    "CUT",
    "FADE",
    "HELP",
    "JOINS_SWITCH",
    "KINDS",
    "LABELS",
    "FIND_HINT",
    "DIRECTION_ICONS",
    "direction_title",
    "extra_minutes",
    "slower_line",
    "WIPE",
    "JoinSpec",
    "DIRECTION_LABELS",
    "SECONDS_LABELS",
    "STEP_S",
    "apply_joins",
    "clean_by_join",
    "clean_joins",
    "direction_of",
    "direction_put_line",
    "direction_rows",
    "fit_seconds",
    "seconds_from_slider",
    "seconds_line",
    "seconds_of",
    "seconds_put_line",
    "snap_seconds",
    "start_seconds",
    "join_name",
    "join_rows",
    "join_title",
    "joins_enabled",
    "option_rows",
    "options",
    "overlap_s",
    "put_line",
    "room_problems",
    "specs",
    "tail_of",
    "transition_of",
    "transitions_seconds",
    "use_of",
]
