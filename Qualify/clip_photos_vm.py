"""ED-14 (m-25029109, D-T1): «Foto quieta de N s» — a still photo's seconds and turn in
the Clip editor, as plain data (no Reflex import), so its rules are tested offline.

A photo on the timeline is a still stretch, free, shown as it is in the preview. It comes
in at `DEFAULT_SECONDS` (2 s, the hypothesis of §3.1); ONLY dragging its end handle
changes it (Deivid 2026-11-24: no «− ½ s / + ½ s»; with the handle focused, ←/→ move it
½ s), between `timeline_vm.PHOTO_MIN_S` and `PHOTO_MAX_S` (1-5 s) on the ½ s magnet
(`timeline_vm.snap`). The panel only reads «Se ve N s»; at 1 s or 5 s `limit_line` says
why, once, under that reading (`LIMIT_ID`, also the handle's `aria-describedby`). The
bar is «Girar · Quitar» (`clip_editor_vm.EDITOR_ACTIONS`; Deivid 2026-11-20: no
«Duración» in the bar); «Girar» turns that block a quarter clockwise. It travels in the
recipe as `SourceSegment(kind="photo", start_s=0, end_s=seconds, rotate=turn)`
(`clip_editor_vm.timeline_segments`).

Where the seconds live (Deivid 2026-11-20): `CreativeState.clip_photo_seconds: {block id:
seconds}` — EACH BLOCK its own. The key is the block's id on the timeline
(`timeline_media`'s `id`, kept when blocks move), with the file's key as a fallback
(`block_key`, `_lookup`); today a photo block's id is its file's key (the strip holds each
file once). A block missing from the dict (a photo just added) reads `DEFAULT_SECONDS`; a
value out of range or off the magnet is read normalized, so a hand-made state never
reaches the recipe out of bounds. The same for its turn: `clip_photo_turns: {block id:
degrees}`, missing = upright. A photo that leaves the Clip forgets both (`prune`,
`prune_turns`, run on every sync of the strip).

ED-12 (#771) put the timeline's cap at 8 blocks: at 5 s with the timeline full, «agrega
otra foto» would be a dead end. Deivid 2026-11-24 («sugerir solo si se puede»): the line
then says to lengthen another photo only when one is still under 5 s (`AT_MAX_FULL`,
`other_room`); with none, it only says the video reached its limit (`AT_MAX_END`).

Integration: `apply_photo_settings` is laid over `clip_editor_vm.timeline_media`'s blocks
inside `CreativeState._clip_tl_media`, so the timeline's rows, the preview, the recipe and
where a new block goes all read the owner's seconds and turn. `photo_row_fields` adds what
the panel and the end handle need to each photo row of `_clip_tl_rows`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from . import editor_preview_contract as contract
from .ui.timeline_vm import PHOTO_MAX_S, PHOTO_MIN_S, STEP_S, amount, snap

#: How long a photo shows when it comes in (D-T1 = A; 2 s is the hypothesis of §3.1).
DEFAULT_SECONDS = 2.0
#: One arrow on the focused end handle, and the drag's magnet.
NUDGE_S = STEP_S
#: The id of the panel's line that says why the handle stops (1 s or 5 s): the handle's
#: `aria-describedby` while it is there.
LIMIT_ID = "clip-photo-why"

# -- copy (qualify-copy-es: plain Spanish, the owner's words) ----------------------------

#: Under the panel's «Duración · Se ve N s»: the only way to change it.
DRAG_HINT = "Para cambiarla, arrastra el borde derecho de su bloque en la línea de tiempo."

#: Shown once, under the panel's «Se ve N s», while the handle is at an edge, with what
#: to do instead.
AT_MIN = "La foto ya está en 1 segundo, el mínimo. Si no la quieres, toca «Quitar»."
AT_MAX = "La foto ya está en 5 segundos, el máximo. Para mostrarla más tiempo, agrega otra foto."
#: …and with the timeline at its 8 photos or videos (ED-12), where no other photo goes in,
#: while another photo can still be lengthened (it is under 5 s)…
AT_MAX_FULL = (
    "La foto ya está en 5 segundos, el máximo, y tu video ya tiene 8 fotos o videos. "
    "Para un video más largo, alarga otra foto."
)
#: …or when none can: no advice that cannot be followed (Deivid 2026-11-24).
AT_MAX_END = "La foto ya está en 5 segundos, el máximo, y tu video ya tiene 8 fotos o videos."


# -- seconds -------------------------------------------------------------------------------


def normalize(seconds: object) -> float:
    """A photo's seconds as the editor keeps them: on the ½ s magnet, inside 1-5 s.
    Anything unreadable (None, "", text, NaN) is `DEFAULT_SECONDS`."""
    try:
        value = float(seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_SECONDS
    if value != value:  # NaN
        return DEFAULT_SECONDS
    return min(max(snap(value), PHOTO_MIN_S), PHOTO_MAX_S)


def _at_max(full: bool, room: bool) -> str:
    if not full:
        return AT_MAX
    return AT_MAX_FULL if room else AT_MAX_END


def other_room(media: Sequence[Mapping[str, object]], block_id: str) -> bool:
    """Whether a photo block OTHER than `block_id` can still be lengthened (it shows under
    5 s) — what `AT_MAX_FULL` suggests (`media` after `apply_photo_settings`)."""
    return any(
        item.get("kind") == "photo"
        and block_key(item) != block_id
        and can_more(item.get("dur", DEFAULT_SECONDS))  # type: ignore[arg-type]
        for item in media
    )


def nudge(
    seconds: float, delta: float, *, full: bool = False, room: bool = True
) -> tuple[float, str]:
    """←/→ on the focused end handle: `(new seconds, "")`, or `(seconds, why not)` when
    it is already at 1 s or 5 s — the same words the panel's line shows (`limit_line`),
    never repeated in the live line. `full`: the timeline
    holds its 8 blocks (`clip_editor_vm.timeline_full`); `room`: another photo can still
    be lengthened (`other_room`)."""
    now = normalize(seconds)
    new = normalize(now + float(delta))
    if new == now and delta:
        return now, AT_MIN if delta < 0 else _at_max(full, room)
    return new, ""


def can_less(seconds: float) -> bool:
    """Whether the photo can still be shortened (not at 1 s)."""
    return normalize(seconds) > PHOTO_MIN_S


def can_more(seconds: float) -> bool:
    """Whether the photo can still be lengthened (not at 5 s)."""
    return normalize(seconds) < PHOTO_MAX_S


def limit_line(seconds: float, *, full: bool = False, room: bool = True) -> str:
    """The panel's line while the handle is at an edge ("" = between 1 s and 5 s)."""
    if not can_less(seconds):
        return AT_MIN
    if not can_more(seconds):
        return _at_max(full, room)
    return ""


def from_drag(seconds: float) -> float:
    """Where the end handle lands when dropped: the magnet, inside 1-5 s."""
    return normalize(seconds)


# -- what the owner reads ------------------------------------------------------------------
# «Foto {n} de {m}» counts EVERY block of «Fotos y videos» (Deivid 2026-11-20), as
# `timeline_vm.media_blocks` does: `n` is the block's place, `m` the track's length.


def seconds_text(seconds: float) -> str:
    """«2», «2,5» — with the Spanish decimal comma."""
    return amount(normalize(seconds))


def seconds_words(seconds: float) -> str:
    """«1 segundo», «2,5 segundos» — the whole word, for a sentence read aloud (a bare «s»
    is read as the letter); the short «s» stays on labels and buttons."""
    value = normalize(seconds)
    return f"{seconds_text(value)} {'segundo' if value == 1 else 'segundos'}"


def changed_line(n: int, seconds: float) -> str:
    """The live line after a change: «La foto 2 ahora se ve 2,5 segundos.»"""
    return f"La foto {n} ahora se ve {seconds_words(seconds)}."


#: How a photo stands after «Girar», by its turn (a quarter turn per tap).
TURN_WORDS: dict[int, str] = {
    0: "volvió a quedar derecha",
    90: "ahora está de lado, girada a la derecha",
    180: "ahora está al revés",
    270: "ahora está de lado, girada a la izquierda",
}


def turned_line(n: int, turn: int = 90) -> str:
    """The live line after «Girar» (its own words: the snapshot's «Giraste tu video.» is
    the owner's video), with how the photo stands now, so a screen reader knows whether
    to tap again: «Giraste la foto 2: ahora está de lado.»"""
    words = TURN_WORDS.get(int(turn) % 360, TURN_WORDS[90])
    return f"Giraste la foto {n}: {words}."


def photo_place(media: Sequence[Mapping[str, object]], block_id: str) -> int:
    """The place (1-based, counting EVERY block) of photo block `block_id`; 0 = not a
    photo on the timeline (a video, a text, an effect, a removed block)."""
    for n, item in enumerate(media, start=1):
        if block_key(item) == block_id:
            return n if item.get("kind") == "photo" else 0
    return 0


def photo_row_fields(seconds: float, *, full: bool = False, room: bool = True) -> dict[str, str]:
    """What a photo's row of `CreativeState._clip_tl_rows` adds to `media_blocks`' own:
    its end handle shows (`handles`), the line that says why it stops at an edge
    (`limit`, "" between 1 s and 5 s) and the handle's `aria-describedby` pointing at it
    while it is there (`end_why`). All strings, like every row field."""
    limit = limit_line(seconds, full=full, room=room)
    return {
        "handles": "1",
        "limit": limit,
        "end_why": LIMIT_ID if limit else "",
    }


# -- where the seconds and turns are kept (one per block) ------------------------------------


def block_key(item: Mapping[str, object]) -> str:
    """The key a photo block's seconds and turn are kept under: its id on the timeline
    (stable when blocks move), else its file's key."""
    return str(item.get("id") or item.get("key") or "")


def _lookup(store: Mapping[str, object] | None, block_id: str, file_key: str) -> object:
    """A block's stored value: under its own id first, then under its file's key (a state
    kept by file); None = not stored."""
    if not store:
        return None
    for key in (block_id, file_key):
        if key and key in store:
            return store[key]
    return None


def seconds_of(store: Mapping[str, object] | None, block_id: str, file_key: str = "") -> float:
    """A photo block's seconds from `clip_photo_seconds` — `DEFAULT_SECONDS` when neither
    its id nor its file's key is there (a state saved before ED-14, a photo just added)."""
    value = _lookup(store, block_id, file_key)
    return DEFAULT_SECONDS if value is None else normalize(value)


def with_seconds(
    store: Mapping[str, object] | None, block_id: str, seconds: float
) -> dict[str, float]:
    """A NEW `clip_photo_seconds` with block `block_id` at `seconds` (normalized). Reflex
    only sees a change when the var is assigned a new dict, never one mutated in place.
    The default is not stored: 2 s is the absence of a value. The other blocks' values
    are kept normalized (empty keys and defaults dropped)."""
    out: dict[str, float] = {}
    for key, kept in (store or {}).items():
        kept_s = normalize(kept)
        if str(key) and kept_s != DEFAULT_SECONDS:
            out[str(key)] = kept_s
    value = normalize(seconds)
    if value == DEFAULT_SECONDS:
        out.pop(block_id, None)
    else:
        out[block_id] = value
    return out


def prune(
    store: Mapping[str, object] | None, media: Sequence[Mapping[str, object]]
) -> dict[str, float]:
    """Only the photo blocks on the timeline (`media`), each under its own id — a value
    found through the file key moves to the block's id. A removed photo forgets its
    seconds, so the same file added again comes in at 2 s."""
    out: dict[str, float] = {}
    for item in media:
        if item.get("kind") != "photo":
            continue
        block = block_key(item)
        value = seconds_of(store, block, str(item.get("key") or ""))
        if block and value != DEFAULT_SECONDS:
            out[block] = value
    return out


def turn_of(store: Mapping[str, object] | None, block_id: str, file_key: str = "") -> int:
    """A photo block's turn from `clip_photo_turns`, its id first, then its file's key
    (0 when missing or not a quarter turn)."""
    try:
        value = int(_lookup(store, block_id, file_key) or 0)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0
    return value if value in contract.ROTATIONS else 0


def with_turn(
    store: Mapping[str, object] | None, block_id: str, file_key: str = ""
) -> dict[str, int]:
    """A NEW `clip_photo_turns` after «Girar» on block `block_id`: a quarter turn
    clockwise from where it is now (no turn is not stored)."""
    out = {str(k): turn_of(store, str(k)) for k in (store or {}) if str(k)}
    out[block_id] = contract.rotate_quarter(turn_of(store, block_id, file_key))
    return {k: v for k, v in out.items() if v}


def prune_turns(
    store: Mapping[str, object] | None, media: Sequence[Mapping[str, object]]
) -> dict[str, int]:
    """`prune` for the turns: only the photo blocks on the timeline, by id."""
    out: dict[str, int] = {}
    for item in media:
        if item.get("kind") != "photo":
            continue
        block = block_key(item)
        turn = turn_of(store, block, str(item.get("key") or ""))
        if block and turn:
            out[block] = turn
    return out


# -- the timeline and the recipe --------------------------------------------------------------


def apply_photo_settings(
    media: Sequence[Mapping[str, object]],
    seconds: Mapping[str, object] | None = None,
    turns: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    """`clip_editor_vm.timeline_media`'s blocks with each photo block's own seconds and
    turn (`dur`, `rotate`; by block id, then file key) — copies; videos untouched. What
    `media_blocks`, the preview (`edit_sequence.from_timeline`) and the recipe read."""
    out: list[dict[str, object]] = []
    for item in media:
        block = dict(item)
        if block.get("kind") == "photo":
            block_id, file_key = block_key(block), str(block.get("key") or "")
            block["dur"] = seconds_of(seconds, block_id, file_key)
            block["rotate"] = turn_of(turns, block_id, file_key)
        out.append(block)
    return out
