"""The reference tracks of the Clip's timeline (m-25142725): pure — no Reflex, no database,
no network.

Under «Fotos y videos», and only while the Clip has AI parts, three tracks hold what the
AI LOOKS AT to make the parts above them — «Fotos de referencia», «Videos de referencia»
and «Audios de referencia» —, after a thin line «✦ Para la IA · no sale en tu video»
(Deivid, 2026-11-27, decision 1). Each reference has its own seconds of the final video and
a row of its track; it is moved and trimmed like a text or an effect, and references that
overlap stack in rows.

The server's contract is `docs/contrato-editor-unico.md` §3.4 (PR A, on `main`): the
brief's `MediaInputs.clip_references` (`ClipReference`) and `references_version` 1, and
`video_pipeline.ai_parts` — which part takes which reference (`references_for_parts`), the
caps of the active model (`reference_caps`, never a number written here), the notices
(`reference_notices`) and their words (`reference_text`). This module never decides any of
it again: it lays the tracks, keeps the screen's items and turns the contract's answer into
rows, columns and lines.

The state keeps each reference as ONE item (a block of a track):

    {"uid", "kind": "photo"|"video"|"audio", "keys": [...], "start", "end", "row",
     "origin": "owner"|"product", "product_id", "name", "whole": "1"|""}

- an owner's reference has one key; the chosen product's photos are ONE item with all its
  keys, «De tu producto», along the whole video (decision 2: `whole` "1" follows the
  video's length until the owner moves or trims it) — each key is one `ClipReference` of
  the brief, so each photo counts for the cap and is removed one by one in its panel;
- ``start``/``end`` are seconds of the final video, ``row`` the track's line (0-based,
  compact: rows come and go on their own, as «Efectos»).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any, Final
from uuid import UUID

from pydantic import ValidationError
from qualify_api.creative.video_pipeline import ai_parts as contract_ai
from qualify_creative.schemas import CLIP_REFERENCES_MAX, ContentBrief

from .ui import timeline_vm

# -- the kinds and their names ----------------------------------------------------------

KINDS: Final = ("photo", "video", "audio")
#: Each kind's block on the timeline (`data-tl-block`, its lane `.q-tl__lane--<kind>`).
TL_KINDS: Final[Mapping[str, str]] = {
    "photo": "refphoto",
    "video": "refvideo",
    "audio": "refaudio",
}
KIND_OF_TL: Final[Mapping[str, str]] = {tl: kind for kind, tl in TL_KINDS.items()}
#: A reference's id on the timeline: this and its uid.
ID_PREFIX: Final = "ref:"
#: At most this many references in a brief (one per photo of a product's block).
REFERENCES_MAX: Final = CLIP_REFERENCES_MAX
#: A reference lasts at least this long (as a text or an effect).
MIN_S: Final = timeline_vm.MIN_S
#: Its edges land on the ½ s magnet; near an AI part's edge they stick to it (notas §7).
STEP_S: Final = timeline_vm.STEP_S
EDGE_PULL_S: Final = 0.3
#: A reference that sat whole under one AI part follows it when it moves (contract §3.4).
_EPS: Final = 0.05

#: The track's names (decision 1) and their empty names.
TRACK_NAMES: Final[Mapping[str, str]] = {
    "photo": "Fotos de referencia",
    "video": "Videos de referencia",
    "audio": "Audios de referencia",
}
EMPTY_NAMES: Final[Mapping[str, str]] = {
    "photo": "Pista de fotos de referencia vacía",
    "video": "Pista de videos de referencia vacía",
    "audio": "Pista de audios de referencia vacía",
}
#: The thin line over the group (Deivid, 2026-11-27, decision 1).
SEPARATOR: Final = timeline_vm.REF_SEPARATOR
GROUP_LABEL: Final = timeline_vm.REF_GROUP_LABEL
#: A block's name, counted in its own kind (as «Foto n», «Video n»).
BLOCK_NAMES: Final[Mapping[str, str]] = {
    "photo": "Foto de referencia {n}",
    "video": "Video de referencia {n}",
    "audio": "Audio de referencia {n}",
}
#: (singular, plural, article «una»/«un»).
NOUNS: Final[Mapping[str, tuple[str, str, str]]] = {
    "photo": ("foto", "fotos", "una"),
    "video": ("video", "videos", "un"),
    "audio": ("audio", "audios", "un"),
}
#: The definite article of each kind («la foto», «el video»).
THE: Final[Mapping[str, str]] = {"photo": "la", "video": "el", "audio": "el"}
PRODUCT_TAG: Final = "De tu producto"
UNUSED_TAG: Final = "No se usa"
IGNORED_TAG: Final = "No se usa aquí"
#: The help of a reference block, read once from a hidden span (`aria-describedby`).
HELP: Final = timeline_vm.REF_HELP
HELP_ID: Final = timeline_vm.REF_HELP_ID

# -- the panel of a reference (notas §8) ------------------------------------------------

USED_ONE: Final = "Se usa en la parte con IA {n}."
#: Decision 7: in the plural.
USED_MANY: Final = "Se usa en las partes con IA {parts}."
WHAT_IT_IS: Final = (
    "La IA la mira para hacer las partes con IA que tiene encima. No sale en tu video."
)
DRAG_HINT: Final = (
    "Para cambiar en qué partes se usa, muévela o acórtala: se pega a los bordes de cada "
    "parte con IA."
)
UNUSED_HELP: Final = "Muévela debajo de una, o quítala."
TIMES_LABEL: Final = "Empieza {start} · Termina {end}"
USE_IN_VIDEO: Final = "Usar también en el video"
USE_IN_VIDEO_HELP: Final = "Pone una copia en «Fotos y videos». Gratis."
USE_AS_REF: Final = "Usar también como referencia"
USE_AS_REF_HELP: Final = "Pone una copia en «{track}» para que la IA la mire. Gratis."
PRODUCT_PHOTOS_TITLE: Final = "Fotos de tu producto"
REMOVE_PHOTO: Final = "Quitar esta foto"
#: UX review: each «Quitar» names its photo.
REMOVE_PHOTO_NAME: Final = "Quitar la foto {n} de {product}"

# -- «Agregar» → «Mostrar a la IA» (notas §9) -------------------------------------

ADD_KEY: Final = "ref"
ADD_ICON: Final = "scan-eye"
#: Deivid chose it (2026-11-27): the orbit's pill takes 16 characters (design system §5.9).
ADD_LABEL: Final = "Mostrar a la IA"
KIND_LABEL: Final = "Qué le mostramos"
KIND_OPTIONS: Final = (("photo", "Foto"), ("video", "Video"), ("audio", "Audio"))
#: UX review: the two sources one under the other, never a segmented menu.
FROM_PRODUCTS: Final = "De tus productos"
FROM_PHONE: Final = "De tu teléfono"
PHONE_EXAMPLE: Final = "Ej.: una foto del local o de cómo sirves el plato."
WHERE_LINE: Final = (
    "Va debajo de la parte con IA {n}, donde está el cabezal, y dura lo mismo. La IA la mira "
    "para hacer esa parte; no sale en tu video."
)
NO_AI_PART: Final = "Primero agrega una parte con IA: las referencias son para ella."
UPLOAD_LABELS: Final[Mapping[str, str]] = {
    "photo": "Subir una foto",
    "video": "Subir un video",
    "audio": "Subir un audio",
}
PICK_LABEL: Final[Mapping[str, str]] = {
    "photo": "Agregar esta foto",
    "video": "Agregar este video",
    "audio": "Agregar este audio",
}
#: Proposed (the mockups have no words for it): a kind no product holds.
NO_PRODUCT_MEDIA: Final[Mapping[str, str]] = {
    "photo": "Tus productos aún no tienen fotos. Sube una desde tu teléfono.",
    "video": "Tus productos aún no tienen videos. Sube uno desde tu teléfono.",
    "audio": "Los audios se suben desde tu teléfono, en MP3 o WAV.",
}
WRONG_TYPE: Final = contract_ai.REFERENCE_TEXTS["reference_type"]

# -- the cap (decision 4: the number is the active model's, `reference_caps`) -----------

CAP_TAG: Final = "⚠ {count} {noun} · máx. {cap}"
CAP_CARD: Final = (
    "La parte con IA {n} tiene {count} {noun} de referencia y la IA usa hasta {cap}. "
    "Quita {art} o {move} a otra parte para seguir."
)
CAP_FULL: Final = (
    "La parte con IA {n} ya tiene {cap} {noun}, lo más que usa la IA. Quita {art} para "
    "agregar {other}."
)

# -- the AI part's panel (notas §11) ----------------------------------------------------

BOX_TITLE: Final = "Lo que la IA mira aquí"
BOX_HELP: Final = (
    "Son las fotos, videos y audios que están debajo de esta parte. Para cambiarlos, "
    "muévelos o quítalos en la línea."
)
BOX_EMPTY: Final = "Nada todavía. La IA usa lo que escribiste arriba."
ADD_SHORTCUT: Final = "Agregar una referencia"
IGNORED_HELP: Final = (
    "Para que use el video o el audio, elige «Nueva» en «¿Cómo la hacemos?», más abajo."
)

# -- the live line --------------------------------------------------------------------

PRODUCT_LINE: Final = "Pusimos las fotos de {product} en «Fotos de referencia», en todo tu video."
ADDED_LINE: Final = "Agregaste {art} {noun} de referencia a la parte con IA {n}."
REMOVED_LINE: Final = "Quitaste {what}."
PHOTO_REMOVED_LINE: Final = "Quitaste una foto de {product}."
LAST_PHOTO_REMOVED_LINE: Final = "Quitaste la última foto de {product}."
#: UX review: after a move, where it is used now — «Ahora la foto de referencia 1 se usa
#: en la parte con IA 2.» / «Ahora las fotos de Combo se usan en las partes con IA 1 y 2.».
NOW_USED_LINE: Final = "Ahora {what} {verb} en {parts}."
NOW_UNUSED_LINE: Final = "Ahora {what} {verb} debajo de ninguna parte con IA: la IA no {it} usa."
FOLLOW_ONE_LINE: Final = "Las referencias de la parte con IA {n} se movieron con ella."
FOLLOW_LINE: Final = "Las referencias se movieron con su parte con IA."
STAYED_LINE: Final = (
    "Las referencias que estaban debajo de varias partes con IA no se movieron. Revisa en "
    "qué partes se usan ahora."
)
COPIED_TO_VIDEO: Final = (
    "Copiamos {what} a «Fotos y videos», a las {clock}, como «{block}». Son copias "
    "aparte: si cambias una, la otra no cambia."
)
COPIED_TO_REFS: Final = (
    "Copiamos {what} a «{track}», justo debajo. Son copias aparte: si cambias una, la otra "
    "no cambia."
)
COPIED_UNUSED: Final = (
    "Esta referencia no está debajo de ninguna parte con IA: muévela debajo de una para que "
    "la IA la use."
)
ALREADY_IN_VIDEO: Final[Mapping[str, str]] = {
    "photo": "Esta foto ya está en tu video.",
    "video": "Este video ya está en tu video.",
}
TOO_MANY: Final = (
    f"Ya tienes {REFERENCES_MAX} referencias, lo más que cabe en un video. Quita una para "
    "agregar otra."
)
#: Proposed: «Usar también en el video» when the copy would pass 60 s.
NO_ROOM_IN_VIDEO: Final = "No cabe en tu video: pasaría de 60 s. Acorta o quita algo primero."
FOLDED: Final = "Sin {what} de referencia"
FOLDED_NONE: Final = "Sin referencias todavía"
#: The accessible name of a block over its part's cap (UX review).
OVER_NAME: Final = "Esta parte tiene más {noun} de las que usa la IA."
FOLDED_ADD: Final = timeline_vm.REF_FOLDED_ADD

#: The file types each kind takes (the contract's, `reference_type`).
SUFFIXES: Final[Mapping[str, tuple[str, ...]]] = contract_ai.REFERENCE_SUFFIXES
ACCEPT: Final[Mapping[str, dict[str, list[str]]]] = {
    "photo": {"image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"]},
    "video": {"video/mp4": [".mp4"], "video/quicktime": [".mov"]},
    "audio": {"audio/mpeg": [".mp3"], "audio/wav": [".wav"]},
}


# ---------------------------------------------------------------------------------------
# ids, numbers and words
# ---------------------------------------------------------------------------------------


def ref_id(uid: str) -> str:
    return f"{ID_PREFIX}{uid}"


def is_ref(block_id: str) -> bool:
    return str(block_id or "").startswith(ID_PREFIX)


def uid_of(block_id: str) -> str:
    return block_id[len(ID_PREFIX) :] if is_ref(block_id) else ""


def new_uid(items: Sequence[Mapping[str, Any]]) -> str:
    """A uid none of `items` has: «r1», «r2»…"""
    taken = {str(i.get("uid")) for i in items}
    n = len(items) + 1
    while f"r{n}" in taken:
        n += 1
    return f"r{n}"


def kind_of_key(key: str) -> str:
    """The kind a file is by its type ("" = none the tracks take)."""
    lower = str(key or "").lower()
    return next((k for k in KINDS if lower.endswith(SUFFIXES[k])), "")


def parts_words(numbers: Sequence[int]) -> str:
    """«1», «1 y 2», «1, 2 y 3»."""
    shown = [str(n) for n in numbers]
    if len(shown) <= 1:
        return "".join(shown)
    return f"{', '.join(shown[:-1])} y {shown[-1]}"


def used_text(numbers: Sequence[int]) -> str:
    """Decision 7: «Se usa en la parte con IA 1.» / «Se usa en las partes con IA 1 y 2.»;
    under none, the contract's `reference_unused`."""
    if not numbers:
        return contract_ai.reference_text("reference_unused") or ""
    if len(numbers) == 1:
        return USED_ONE.format(n=numbers[0])
    return USED_MANY.format(parts=parts_words(numbers))


def folded_text(kinds: Sequence[str]) -> str:
    """«Sin videos ni audios de referencia» for the kinds with nothing ("" = none)."""
    words = [NOUNS[k][1] for k in KINDS if k in kinds]
    if not words:
        return ""
    if len(words) == len(KINDS):
        return FOLDED_NONE  # UX review: «Sin referencias todavía»
    what = words[0] if len(words) == 1 else f"{', '.join(words[:-1])} ni {words[-1]}"
    return FOLDED.format(what=what)


def cap_tag(kind: str, count: int, cap: int) -> str:
    return CAP_TAG.format(count=count, noun=NOUNS[kind][1], cap=cap)


def cap_card(kind: str, n: int, count: int, cap: int) -> str:
    noun, plural, art = NOUNS[kind]
    return CAP_CARD.format(
        n=n,
        count=count,
        noun=plural,
        cap=cap,
        art=art + ("" if art == "una" else "o"),
        move="muévela" if art == "una" else "muévelo",
    )


def cap_full(kind: str, n: int, cap: int) -> str:
    _noun, plural, art = NOUNS[kind]
    female = art == "una"
    return CAP_FULL.format(
        n=n,
        cap=cap,
        noun=plural,
        art=art + ("" if female else "o"),
        other="otra" if female else "otro",
    )


def first_folded_kind(kinds: Sequence[str]) -> str:
    """The kind the folded row's «Agregar» opens the tab on: the first it names."""
    return next((k for k in KINDS if k in kinds), "photo")


def subject(item: Mapping[str, Any], numbers: Mapping[str, int]) -> tuple[str, bool]:
    """How the live line names a reference — «la foto de referencia 2», «el video de
    referencia 1», a product's «las fotos de Combo Vecino» (its name as written) — and
    whether that is plural."""
    if item.get("origin") == "product":
        name = str(item.get("name") or "").strip() or "tu producto"
        return f"las fotos de {name}", True
    kind = str(item["kind"])
    label = BLOCK_NAMES[kind].format(n=numbers.get(str(item["uid"]), 1))
    return f"{THE[kind]} {lower_label(label)}", False


def now_line(item: Mapping[str, Any], numbers: Mapping[str, int], used: Sequence[int]) -> str:
    """After a reference changed its time (UX review): «Ahora la foto de referencia 1 se
    usa en la parte con IA 2.», «…en las partes con IA 1 y 2.», or under none «Ahora el
    video de referencia 1 no está debajo de ninguna parte con IA: la IA no lo usa.»."""
    what, plural = subject(item, numbers)
    if not used:
        it = "las" if plural else ("la" if THE[str(item["kind"])] == "la" else "lo")
        return NOW_UNUSED_LINE.format(what=what, verb="no están" if plural else "no está", it=it)
    parts = (
        f"la parte con IA {used[0]}" if len(used) == 1 else f"las partes con IA {parts_words(used)}"
    )
    return NOW_USED_LINE.format(what=what, verb="se usan" if plural else "se usa", parts=parts)


def removed_line(item: Mapping[str, Any], numbers: Mapping[str, int]) -> str:
    return REMOVED_LINE.format(what=subject(item, numbers)[0])


def follow_line(numbers: Sequence[int]) -> str:
    """The references that followed their AI part(s)."""
    shown_n = list(dict.fromkeys(numbers))
    if len(shown_n) == 1:
        return FOLLOW_ONE_LINE.format(n=shown_n[0])
    return FOLLOW_LINE


def caps(model: str | None = None) -> dict[str, int]:
    """The active model's caps by kind (`ai_parts.reference_caps`); {} for a model whose
    caps nobody wrote down — never a number guessed here."""
    try:
        return dict(contract_ai.reference_caps(model))
    except ValueError:
        return {}


# ---------------------------------------------------------------------------------------
# the items
# ---------------------------------------------------------------------------------------


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def new_item(
    items: Sequence[Mapping[str, Any]],
    kind: str,
    keys: Sequence[str],
    start: float,
    end: float,
    *,
    origin: str = "owner",
    product_id: str = "",
    name: str = "",
    whole: bool = False,
) -> dict[str, Any]:
    """A new reference over `start`…`end`, on the first row of its kind that is free
    there (a new row when none is: they stack, decision «se apilan en filas»)."""
    item = {
        "uid": new_uid(items),
        "kind": kind,
        "keys": [str(k) for k in keys],
        "start": round(float(start), 2),
        "end": round(float(end), 2),
        "row": 0,
        "origin": origin,
        "product_id": product_id if origin == "product" else "",
        "name": name,
        "whole": "1" if whole else "",
    }
    item["row"] = free_row(items, item)
    return item


def _same_kind(items: Sequence[Mapping[str, Any]], kind: str, but: str = "") -> list[Any]:
    return [i for i in items if i.get("kind") == kind and str(i.get("uid")) != but]


def free_row(items: Sequence[Mapping[str, Any]], item: Mapping[str, Any]) -> int:
    """The upper row of `item`'s kind where its seconds are free (meeting at a second is
    fine), else a new one under the last."""
    others = _same_kind(items, str(item.get("kind")), str(item.get("uid")))
    count = max((int(i.get("row") or 0) for i in others), default=-1) + 1
    rows: list[list[tuple[float, float]]] = [[] for _ in range(count)]
    for other in others:
        rows[int(other.get("row") or 0)].append((_f(other.get("start")), _f(other.get("end"))))
    found = timeline_vm.first_free_row(rows, (_f(item.get("start")), _f(item.get("end"))))
    return count if found is None else found


def compact(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rows come and go on their own: each kind's rows renumbered from 0, in order."""
    out = [dict(i) for i in items]
    for kind in KINDS:
        used = sorted({int(i.get("row") or 0) for i in out if i.get("kind") == kind})
        renumber = {row: n for n, row in enumerate(used)}
        for item in out:
            if item.get("kind") == kind:
                item["row"] = renumber[int(item.get("row") or 0)]
    return out


def unstack(items: Sequence[Mapping[str, Any]], uid: str) -> list[dict[str, Any]]:
    """`uid` dropped on a row where it overlaps another: it goes to the first free row
    of its kind (its seconds stay), then the rows are compacted."""
    out = [dict(i) for i in items]
    item = next((i for i in out if str(i.get("uid")) == uid), None)
    if item is not None:
        row = int(item.get("row") or 0)
        clash = any(
            int(o.get("row") or 0) == row
            and _f(o.get("start")) < _f(item.get("end")) - 1e-6
            and _f(item.get("start")) < _f(o.get("end")) - 1e-6
            for o in _same_kind(out, str(item.get("kind")), uid)
        )
        if clash:
            item["row"] = free_row(out, item)
    return compact(out)


def resolved(items: Sequence[Mapping[str, Any]], total: float) -> list[dict[str, Any]]:
    """The items as the video is now: a product's block along the whole video while it is
    `whole`, and every reference inside the video, never under `MIN_S` (as `_fit_overlays`
    fits texts and effects; `reference_out_of_clip` never comes from the screen)."""
    total = max(float(total), 0.0)
    out: list[dict[str, Any]] = []
    for item in items:
        fitted = dict(item)
        if item.get("whole"):
            start, end = 0.0, total
        else:
            end = min(_f(item.get("end")), total)
            start = min(_f(item.get("start")), max(end - MIN_S, 0.0))
        fitted["start"], fitted["end"] = round(max(start, 0.0), 2), round(end, 2)
        out.append(fitted)
    return out


def shown(items: Sequence[Mapping[str, Any]], total: float) -> list[dict[str, Any]]:
    """`resolved` without what has no seconds left (a video of 0 s, keys all removed)."""
    return [i for i in resolved(items, total) if i["end"] - i["start"] > 1e-6 and i.get("keys")]


def set_time(
    items: Sequence[Mapping[str, Any]],
    uid: str,
    start: float,
    end: float,
    total: float,
    *,
    edges: Sequence[float] = (),
) -> list[dict[str, Any]]:
    """`uid` at `start`…`end` (seconds of the final video): on the ½ s magnet, pulled to
    an AI part's edge within `EDGE_PULL_S` (`edges`), inside the video and never shorter
    than `MIN_S`; it stops following the whole video. Then it stacks if it overlaps."""
    out = [dict(i) for i in resolved(items, total)]
    for item in out:
        if str(item.get("uid")) != uid:
            continue
        a, b = _pull(float(start), edges), _pull(float(end), edges)
        total = max(float(total), 0.0)
        if b - a < MIN_S:
            b = a + MIN_S
        if b > total:
            a, b = max(total - (b - a), 0.0), total
        a = max(a, 0.0)
        item["start"], item["end"], item["whole"] = round(a, 2), round(b, 2), ""
    return unstack(out, uid)


def _pull(t: float, edges: Sequence[float]) -> float:
    near = [e for e in edges if abs(e - t) <= EDGE_PULL_S + 1e-9]
    if near:
        return min(near, key=lambda e: abs(e - t))
    return timeline_vm.snap(t)


def shift(
    items: Sequence[Mapping[str, Any]],
    uid: str,
    start: float,
    total: float,
    *,
    edges: Sequence[float] = (),
    row: int | None = None,
) -> list[dict[str, Any]]:
    """The whole reference dragged to `start` (same length), on `row` when given (↑/↓ or
    dropped on another row of its kind). Its start sticks to an AI part's edge as its
    end does (whichever is nearer)."""
    current = next((i for i in resolved(items, total) if str(i.get("uid")) == uid), None)
    if current is None:
        return [dict(i) for i in items]
    length = current["end"] - current["start"]
    a = float(start)
    # the start or the end sticks to an AI part's edge (the nearer one), else the ½ s magnet
    near = [(abs(e - a), e) for e in edges if abs(e - a) <= EDGE_PULL_S + 1e-9]
    near += [
        (abs(e - a - length), e - length)
        for e in edges
        if abs(e - a - length) <= EDGE_PULL_S + 1e-9
    ]
    a = min(near)[1] if near else timeline_vm.snap(a)
    a = min(max(a, 0.0), max(float(total) - length, 0.0))
    out = [dict(i) for i in resolved(items, total)]
    for item in out:
        if str(item.get("uid")) == uid:
            item["start"], item["end"], item["whole"] = round(a, 2), round(a + length, 2), ""
            if row is not None:
                item["row"] = max(int(row), 0)
    return unstack(out, uid)


def remove(items: Sequence[Mapping[str, Any]], uid: str) -> list[dict[str, Any]]:
    return compact([dict(i) for i in items if str(i.get("uid")) != uid])


def remove_key(items: Sequence[Mapping[str, Any]], uid: str, key: str) -> list[dict[str, Any]]:
    """One photo out of a product's block («Quitar esta foto»); the last one takes the
    block with it."""
    out: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("uid")) == uid:
            keys = [k for k in item.get("keys") or () if k != key]
            if not keys:
                continue
            item = {**item, "keys": keys}
        out.append(dict(item))
    return compact(out)


def without_product(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The product changed or was let go: its block goes (an owner's stay)."""
    return compact([dict(i) for i in items if i.get("origin") != "product"])


def product_item(
    items: Sequence[Mapping[str, Any]], product_id: str, name: str, keys: Sequence[str]
) -> list[dict[str, Any]]:
    """Decision 2: the chosen product's photos as ONE block along the whole video,
    «De tu producto» — the old product's block replaced. No photo: nothing."""
    out = without_product(items)
    photos = [k for k in dict.fromkeys(str(k) for k in keys) if kind_of_key(k) == "photo"]
    if not photos or not product_id:
        return out
    item = new_item(
        out,
        "photo",
        photos,
        0.0,
        0.0,
        origin="product",
        product_id=product_id,
        name=name,
        whole=True,
    )
    item["row"] = 0
    # the product's block takes the first row; the owner's photos go under it
    for other in out:
        if other.get("kind") == "photo":
            other["row"] = int(other.get("row") or 0) + 1
    return compact([item, *out])


# Assumption shared by `own_spans`, `follow` and `whole_under` (fourth review): a join
# lasts less than `MIN_S`, so a reference — never shorter than `MIN_S` — never fits INSIDE
# a join; one over a join's stretch always reaches into one part's own seconds too.


def own_spans(spans: Mapping[str, Sequence[float]]) -> dict[str, tuple[float, float]]:
    """Each AI part's seconds less what it shares with the part before or after it (a
    join laid over both): the same rule for `follow` and `whole_under`."""
    ordered = sorted(spans.items(), key=lambda kv: (float(kv[1][0]), float(kv[1][1])))
    out: dict[str, tuple[float, float]] = {}
    for at, (pid, span) in enumerate(ordered):
        lo, hi = float(span[0]), float(span[1])
        if at > 0:
            lo = max(lo, min(hi, float(ordered[at - 1][1][1])))
        if at + 1 < len(ordered):
            hi = min(hi, max(lo, float(ordered[at + 1][1][0])))
        out[pid] = (lo, hi)
    return out


def follow(
    items: Sequence[Mapping[str, Any]],
    before: Mapping[str, Sequence[float]],
    after: Mapping[str, Sequence[float]],
    total: float,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Decision 3 (contract §3.4): an AI part changed place or length (`before`/`after`:
    its id → (start, end) in seconds of the video). A reference that sat WHOLE under one
    part that moved follows it — shifted by as much as the part's start, kept inside the
    part's new span; one that touched more than one part, or none, stays at its time.
    Returns (items, the ids of the parts whose references followed — one per reference —,
    how many under a moved part stayed)."""
    moved = {
        pid: (span, after[pid])
        for pid, span in before.items()
        if pid in after
        and (
            abs(float(after[pid][0]) - float(span[0])) > 1e-6
            or abs(float(after[pid][1]) - float(span[1])) > 1e-6
        )
    }
    if not moved:
        return [dict(i) for i in items], [], 0
    out: list[dict[str, Any]] = []
    own = own_spans(before)
    went: list[str] = []
    moved_uids: list[str] = []
    stayed = 0
    # code review: the shift is reckoned on the seconds as they were (a shorter video
    # would cut a reference before it moves with its part); cut to the video only at the end
    for raw in items:
        item = dict(raw)
        if item.get("whole"):
            out.append(item)
            continue
        a, b = _f(item.get("start")), _f(item.get("end"))
        # third review: a part's own seconds are its span less the join it shares with a
        # neighbour (a fade lays two parts over each other): a reference over that stretch
        # is still only its own part's
        under = [
            pid
            for pid, span in own.items()
            if _overlap(a, b, float(span[0]), float(span[1])) > _EPS
        ]
        whole_in = [
            pid
            for pid in under
            if a >= float(before[pid][0]) - _EPS and b <= float(before[pid][1]) + _EPS
        ]
        if len(under) == 1 and whole_in and whole_in[0] in moved:
            (old_a, _old_b), (new_a, new_b) = moved[whole_in[0]]
            delta = float(new_a) - float(old_a)
            length = b - a
            na = a + delta
            nb = min(na + length, float(new_b))
            if nb - na < MIN_S:
                na = max(float(new_a), nb - MIN_S)
            item = {**item, "start": round(na, 2), "end": round(nb, 2)}
            went.append(whole_in[0])
            moved_uids.append(str(item.get("uid")))
        elif any(pid in moved for pid in under):
            stayed += 1
        out.append(item)
    out = resolved(out, total) if total > 0 else out
    # code review: one that moved onto another on its row goes to the first free row
    for uid in moved_uids:
        out = unstack(out, uid)
    return compact(out), went, stayed


#: Deivid (2026-11-27, option A): removing an AI part removes the references WHOLE under
#: it; the ones that touch other parts stay. (Merging keeps them: they are still whole under
#: the joined part, `follow`.)
REMOVED_WITH_ONE: Final = "Quitaste la parte con IA {n} y su referencia."
REMOVED_WITH_MANY: Final = "Quitaste la parte con IA {n} y sus {k} referencias."
GO_WITH_PART: Final = "Sus referencias se quitan con ella."


def whole_under(
    items: Sequence[Mapping[str, Any]], spans: Mapping[str, Sequence[float]], pid: str
) -> list[str]:
    """The references that sit WHOLE under the AI part `pid` (`spans`: every part's
    seconds) and under no other part's own seconds — `follow`'s rule: the stretch of a
    join laid over a neighbour stays this part's. Never a product's block along the
    whole video."""
    if pid not in spans:
        return []
    lo, hi = float(spans[pid][0]), float(spans[pid][1])
    own = own_spans(spans)
    out: list[str] = []
    for item in items:
        if item.get("whole"):
            continue
        a, b = _f(item.get("start")), _f(item.get("end"))
        if not (a >= lo - _EPS and b <= hi + _EPS and _overlap(a, b, lo, hi) > _EPS):
            continue
        if any(
            other != pid and _overlap(a, b, float(s[0]), float(s[1])) > _EPS
            for other, s in own.items()
        ):
            continue
        out.append(str(item.get("uid")))
    return out


def applies(a: float, b: float, lo: float, hi: float) -> bool:
    """A reference over `a`…`b` applies to an AI part over `lo`…`hi` (the contract's
    more than `REFERENCE_OVERLAP_MIN_S` of overlap)."""
    return _overlap(a, b, lo, hi) > contract_ai.REFERENCE_OVERLAP_MIN_S


#: A reference cut to a joined part shorter than this is taken out.
CUT_MIN_S: Final = 0.5


def fit_into(
    items: Sequence[Mapping[str, Any]], uids: Sequence[str], span: Sequence[float]
) -> list[dict[str, Any]]:
    """`uids` kept inside `span` (a joined AI part): cut to it, and taken out when less
    than `CUT_MIN_S` is left."""
    lo, hi = float(span[0]), float(span[1])
    out: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("uid")) in uids:
            a, b = max(_f(item.get("start")), lo), min(_f(item.get("end")), hi)
            if b - a < CUT_MIN_S:
                continue
            item = {**item, "start": round(a, 2), "end": round(b, 2)}
        out.append(dict(item))
    return compact(out)


def removed_with_line(n: int, k: int) -> str:
    """The live line once an AI part went with `k` references ("" with none)."""
    if k <= 0:
        return ""
    return REMOVED_WITH_ONE.format(n=n) if k == 1 else REMOVED_WITH_MANY.format(n=n, k=k)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


# ---------------------------------------------------------------------------------------
# the AI parts on the track, and the contract's answer
# ---------------------------------------------------------------------------------------


def ai_spans(media: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Each AI part on «Fotos y videos» (`ai_block_vm.timeline_items`' items, joins
    applied): ``{"id", "n", "entry", "start", "end"}`` in seconds of the final video, as
    the track lays it (`timeline_vm.media_blocks`)."""
    rows = timeline_vm.media_blocks([dict(m) for m in media])
    spans = []
    for row, item in zip(rows, media, strict=True):
        if item.get("kind") != timeline_vm.AI_KIND:
            continue
        start = float(row["start"])
        spans.append(
            {
                "id": str(item.get("id")),
                "n": int(item.get("ai_n") or 0),
                "entry": int(item.get("entry") or 0),
                "start": start,
                "end": round(start + float(row["length"]), 2),
            }
        )
    return spans


def edges_of(spans: Sequence[Mapping[str, Any]]) -> list[float]:
    """The AI parts' edges, where a dragged reference sticks."""
    return sorted({float(s["start"]) for s in spans} | {float(s["end"]) for s in spans})


def brief_references(items: Sequence[Mapping[str, Any]], total: float) -> list[dict[str, Any]]:
    """`MediaInputs.clip_references` (`ClipReference` as JSON): one per key, in the
    items' order — a product's block gives one per photo."""
    out: list[dict[str, Any]] = []
    for item in shown(items, total):
        product = item.get("origin") == "product" and item.get("product_id")
        for key in item.get("keys") or ():
            out.append(
                {
                    "kind": item["kind"],
                    "key": str(key),
                    "start_s": item["start"],
                    "end_s": item["end"],
                    "row": int(item.get("row") or 0),
                    "origin": "product" if product else "owner",
                    "product_id": str(item["product_id"]) if product else None,
                }
            )
    return out[:REFERENCES_MAX]


def _owners(items: Sequence[Mapping[str, Any]], total: float) -> list[str]:
    return [str(item["uid"]) for item in shown(items, total) for _key in item.get("keys") or ()][
        :REFERENCES_MAX
    ]


def brief_of(
    segments: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
) -> ContentBrief:
    """The smallest brief the contract reads (`references_for_parts`, `reference_notices`):
    a normal `local` Clip with the timeline's blocks, its AI parts' entries and the
    tracks. Raises `ValidationError` while the timeline cannot be read yet (a video with
    no length)."""
    return ContentBrief.model_validate(
        {
            "brand_id": UUID(int=0),
            "objective": "sale",
            "content_type": "menu",
            "topic": "referencias",
            "image_route": "template_only",
            "variants_requested": 1,
            "kind": "clip",
            "format": "reels_9_16",
            "media": {
                "clip_reference_mode": "local",
                "segments": list(segments),
                "ai_parts": list(entries),
                "references_version": 1,
                "clip_references": list(references),
            },
        }
    )


def plan(
    items: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    spans: Sequence[Mapping[str, Any]],
    total: float,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """What each AI part takes, asked of the contract at every change
    (`references_for_parts(brief)` and `reference_notices(brief)`), keyed back to the
    screen's items:

    - ``parts``: per AI part (by its entry) ``{"entry", "n", "start", "end", "mode",
      "uses": {kind: [uid…]}, "counts": {kind: n}, "over": {kind: cap}}``;
    - ``used_by``: uid → the AI parts' numbers it applies to;
    - ``ignored``: uid → the AI parts' numbers that do not use it (`reference_mode_ignored`);
    - ``unused``: the uids under no AI part (`reference_unused`);
    - ``caps``: the active model's caps.

    While the brief cannot be read (a video with no length yet) the same rule is applied
    here — more than `REFERENCE_OVERLAP_MIN_S` of overlap, videos and audios only under
    «Nueva» — without caps."""
    cap = caps(model)
    refs = brief_references(items, total)
    owners = _owners(items, total)
    numbers = {int(s["entry"]): int(s["n"]) for s in spans}
    out: dict[str, Any] = {"parts": [], "used_by": {}, "ignored": {}, "unused": [], "caps": cap}
    if not spans:
        out["unused"] = list(dict.fromkeys(owners))
        return out
    try:
        if not cap:
            raise ValueError("no caps")
        brief = brief_of(segments, entries, refs)
        parts = contract_ai.references_for_parts(brief, model=model)
        notices = contract_ai.reference_notices(brief, model=model)
    except (ValidationError, ValueError):
        return _plan_here(items, entries, spans, total, out)
    typed = list(brief.media.clip_references)
    for part in parts:
        n = numbers.get(part.entry_at, part.entry_at + 1)
        uses: dict[str, list[str]] = {}
        counts: dict[str, int] = {}
        over: dict[str, int] = {}
        for kind in KINDS:
            chosen = part.of(kind)  # type: ignore[arg-type]
            counts[kind] = len(chosen)
            uids = [owners[i] for i, ref in enumerate(typed) if ref in chosen]
            uses[kind] = list(dict.fromkeys(uids))
            for uid in uses[kind]:
                out["used_by"].setdefault(uid, [])
                if n not in out["used_by"][uid]:
                    out["used_by"][uid].append(n)
        for problem in part.problems:
            kind = (problem.field or "").rpartition(".")[2]
            if problem.code == "too_many_references" and kind in KINDS:
                over[kind] = cap.get(kind, 0)
        out["parts"].append(
            {
                "entry": part.entry_at,
                "n": n,
                "start": part.start_s,
                "end": part.end_s,
                "mode": part.mode,
                "uses": uses,
                "counts": counts,
                "over": over,
            }
        )
    for note in notices:
        at = _index(note.field)
        if at is None or at >= len(owners):
            continue
        uid = owners[at]
        if note.code == "reference_mode_ignored" and note.entry_at is not None:
            n = numbers.get(note.entry_at, note.entry_at + 1)
            out["ignored"].setdefault(uid, [])
            if n not in out["ignored"][uid]:
                out["ignored"][uid].append(n)
        elif note.code == "reference_unused" and uid not in out["unused"]:
            out["unused"].append(uid)
    for part in out["parts"]:
        for kind in KINDS:
            part["counts"].setdefault(kind, 0)
    return out


def _plain(value: Any) -> Any:
    """Plain JSON data out of the state's proxies (mappings and lists, recursively)."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)) or (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    ):
        return [_plain(v) for v in value]
    return value


@lru_cache(maxsize=64)
def _plan_json(payload: str, model: str | None) -> str:
    data = json.loads(payload)
    return json.dumps(
        plan(
            data["items"],
            data["segments"],
            data["entries"],
            data["spans"],
            data["total"],
            model=model,
        )
    )


def plan_cached(
    items: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    spans: Sequence[Mapping[str, Any]],
    total: float,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """`plan`, asked once per state of the timeline: every var of the screen reads the
    same answer (the caps are read again with the active model's name)."""
    payload = json.dumps(
        _plain(
            {
                "items": items,
                "segments": segments,
                "entries": entries,
                "spans": spans,
                "total": float(total),
            }
        ),
        sort_keys=True,
        default=str,
    )
    return json.loads(_plan_json(payload, model or contract_ai.active_video_model()))


def _index(field: str) -> int | None:
    head, _, rest = str(field or "").partition("[")
    if head != "clip_references" or "]" not in rest:
        return None
    number = rest.partition("]")[0]
    return int(number) if number.isdigit() else None


def _plan_here(
    items: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    spans: Sequence[Mapping[str, Any]],
    total: float,
    out: dict[str, Any],
) -> dict[str, Any]:
    """The contract's rule, without its caps, for a timeline it cannot read yet."""
    out["caps"] = {}
    live = shown(items, total)
    for span in spans:
        entry = int(span["entry"])
        mode = str((entries[entry] if entry < len(entries) else {}).get("mode") or "reference")
        uses: dict[str, list[str]] = {k: [] for k in KINDS}
        for item in live:
            if (
                _overlap(item["start"], item["end"], span["start"], span["end"])
                <= contract_ai.REFERENCE_OVERLAP_MIN_S
            ):
                continue
            uid = str(item["uid"])
            if item["kind"] != "photo" and mode != "reference":
                out["ignored"].setdefault(uid, []).append(int(span["n"]))
                continue
            uses[item["kind"]].append(uid)
            out["used_by"].setdefault(uid, []).append(int(span["n"]))
        out["parts"].append(
            {
                "entry": entry,
                "n": int(span["n"]),
                "start": span["start"],
                "end": span["end"],
                "mode": mode,
                "uses": uses,
                "counts": {
                    k: sum(len(i.get("keys") or ()) for i in live if str(i["uid"]) in uses[k])
                    for k in KINDS
                },
                "over": {},
            }
        )
    seen = set(out["used_by"]) | set(out["ignored"])
    out["unused"] = [str(i["uid"]) for i in live if str(i["uid"]) not in seen]
    return out


def over_lines(the_plan: Mapping[str, Any]) -> list[str]:
    """The card under the line (and the «Siguiente» reason) for each part over a cap, in
    the parts' order: «La parte con IA 1 tiene 10 fotos de referencia y la IA usa hasta
    9. Quita una o muévela a otra parte.»."""
    lines = []
    for part in the_plan.get("parts") or ():
        for kind in KINDS:
            cap = (part.get("over") or {}).get(kind)
            if cap:
                lines.append(cap_card(kind, int(part["n"]), int(part["counts"][kind]), int(cap)))
    return lines


def part_problem(the_plan: Mapping[str, Any], entry: int) -> str:
    """The contract's words for an AI part over its caps (its panel): `reference_text`
    of `too_many_references`, with the model's number."""
    for part in the_plan.get("parts") or ():
        if int(part["entry"]) != int(entry):
            continue
        return " ".join(
            contract_ai.reference_text("too_many_references", kind=kind) or ""  # type: ignore[arg-type]
            for kind in KINDS
            if (part.get("over") or {}).get(kind)
        )
    return ""


def room_for(the_plan: Mapping[str, Any], entry: int, kind: str, adding: int = 1) -> str:
    """Why `adding` more of `kind` does not fit under the AI part `entry` ("" = it fits)."""
    cap = (the_plan.get("caps") or {}).get(kind)
    if not cap:
        return ""
    for part in the_plan.get("parts") or ():
        if int(part["entry"]) == int(entry):
            if int(part["counts"].get(kind, 0)) + adding > int(cap):
                return cap_full(kind, int(part["n"]), int(cap))
    return ""


# ---------------------------------------------------------------------------------------
# what the timeline draws
# ---------------------------------------------------------------------------------------


def _numbers(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Each owner's reference's number in its kind, by where it sits (start, row)."""
    out: dict[str, int] = {}
    for kind in KINDS:
        own = [i for i in items if i.get("kind") == kind and i.get("origin") != "product"]
        own.sort(key=lambda i: (_f(i.get("start")), int(i.get("row") or 0), str(i.get("uid"))))
        for n, item in enumerate(own, start=1):
            out[str(item["uid"])] = n
    return out


def label_of(item: Mapping[str, Any], numbers: Mapping[str, int]) -> str:
    """«Foto de referencia 2», or a product's «Combo Vecino · 2 fotos»."""
    if item.get("origin") == "product":
        count = len(item.get("keys") or ())
        what = "1 foto" if count == 1 else f"{count} fotos"
        name = str(item.get("name") or "").strip() or "Tu producto"
        return f"{name} · {what}"
    return BLOCK_NAMES[str(item["kind"])].format(n=numbers.get(str(item["uid"]), 1))


def _aria_label(item: Mapping[str, Any], numbers: Mapping[str, int]) -> str:
    """The block's accessible name before its times: a product's «Combo Vecino, 2 fotos de
    tu producto» (UX review), else its label."""
    if item.get("origin") == "product":
        count = len(item.get("keys") or ())
        what = "1 foto de tu producto" if count == 1 else f"{count} fotos de tu producto"
        name = str(item.get("name") or "").strip() or "Tu producto"
        return f"{name}, {what}"
    return BLOCK_NAMES[str(item["kind"])].format(n=numbers.get(str(item["uid"]), 1))


def numbers_of(items: Sequence[Mapping[str, Any]], total: float) -> dict[str, int]:
    """Each owner's reference's number in its kind, as the tracks show it now."""
    return _numbers(shown(items, total))


def lower_label(label: str) -> str:
    return label[:1].lower() + label[1:]


def rows(
    items: Sequence[Mapping[str, Any]],
    the_plan: Mapping[str, Any],
    total: float,
    *,
    thumbs: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Every reference's row, in the timeline's row shape (`timeline_vm.overlay_blocks`'
    keys, so `ui.timeline` draws it as a text or an effect: moved and trimmed in time),
    with its kind (`refphoto`…), its tag and its use."""
    thumbs = thumbs or {}
    live = shown(items, total)
    numbers = _numbers(live)
    over_uids = {
        uid
        for part in the_plan.get("parts") or ()
        for kind, _cap in (part.get("over") or {}).items()
        for uid in (part.get("uses") or {}).get(kind, ())
    }
    over_words = {
        "photo": OVER_NAME.format(noun="fotos"),
        "video": OVER_NAME.format(noun="videos").replace("de las que", "de los que"),
        "audio": OVER_NAME.format(noun="audios").replace("de las que", "de los que"),
    }
    out: list[dict[str, str]] = []
    for item in live:
        uid = str(item["uid"])
        label = label_of(item, numbers)
        used = list((the_plan.get("used_by") or {}).get(uid, ()))
        ignored = list((the_plan.get("ignored") or {}).get(uid, ()))
        fake = {
            "id": ref_id(uid),
            "kind": "effect",
            "label": label,
            "start": item["start"],
            "end": item["end"],
            "lane": int(item.get("row") or 0),
        }
        row = timeline_vm.overlay_blocks([fake], "effect", total)[0]
        a, b = timeline_vm.clock(item["start"]), timeline_vm.clock(item["end"])
        use = (
            used_text(used)
            if used or not ignored
            else contract_ai.reference_text("reference_mode_ignored") or ""
        )
        tag = (
            PRODUCT_TAG
            if item.get("origin") == "product"
            else (UNUSED_TAG if not used and not ignored else (IGNORED_TAG if not used else ""))
        )
        first = str((item.get("keys") or [""])[0])
        tl_kind = TL_KINDS[str(item["kind"])]
        row.update(
            {
                "kind": tl_kind,
                "track": tl_kind,
                "name": f"{_aria_label(item, numbers)}, de {a} a {b}. {use}"
                + (f" {over_words[str(item['kind'])]}" if uid in over_uids else ""),
                "panel": f"{label} · de {a} a {b}",
                "help": HELP,
                "help_id": HELP_ID,
                "thumb": thumbs.get(first, "") if item["kind"] != "audio" else "",
                "warn": "1" if uid in over_uids else "",
                "ref_tag": tag,
                "ref_kind": str(item["kind"]),
                "ref_use": use,
                "ref_off": "1" if not used else "",
                "start_label": "Empieza",
                "end_label": "Termina",
            }
        )
        out.append(row)
    return out


def lanes(
    ref_rows: Sequence[Mapping[str, str]],
) -> tuple[list[list[dict[str, str]]], list[dict[str, str]], str]:
    """The tracks the timeline draws, kind after kind: each row of a kind that holds
    something (`lanes`, the rows' blocks) with its names (`names`: ``index`` — its row
    in its kind, the one a drag lands on —, ``kind``, ``name``, ``empty``), and the
    folded row for the kinds that hold nothing («Sin videos ni audios de referencia»;
    "" when every kind holds something)."""
    out_lanes: list[list[dict[str, str]]] = []
    names: list[dict[str, str]] = []
    empty: list[str] = []
    for kind in KINDS:
        tl_kind = TL_KINDS[kind]
        mine = [dict(r) for r in ref_rows if r.get("kind") == tl_kind]
        if not mine:
            empty.append(kind)
            continue
        count = max(int(r.get("lane") or 0) for r in mine) + 1
        for lane in range(count):
            out_lanes.append([r for r in mine if int(r.get("lane") or 0) == lane])
            title = TRACK_NAMES[kind] if count == 1 else f"{TRACK_NAMES[kind]} {lane + 1}"
            names.append(
                {
                    "index": str(lane),
                    "kind": tl_kind,
                    "name": title,
                    "empty": EMPTY_NAMES[kind],
                    "cls": f"q-tl__lane q-tl__lane--ref q-tl__lane--{tl_kind}",
                }
            )
    return out_lanes, names, folded_text(empty)


def columns(
    spans: Sequence[Mapping[str, Any]], the_plan: Mapping[str, Any]
) -> list[dict[str, str]]:
    """One column per AI part under it, across the reference tracks (notas §2): iris
    (`--q-ai-*`) — amber with its capsule «⚠ 10 fotos · máx. 9» when the part is over a
    cap —; `mode` "other" for a part that is not «Nueva» (its videos and audios are not
    used)."""
    by_entry = {int(p["entry"]): p for p in the_plan.get("parts") or ()}
    out = []
    for span in spans:
        part = by_entry.get(int(span["entry"]), {})
        over = part.get("over") or {}
        tag = " ".join(
            cap_tag(kind, int(part["counts"][kind]), int(cap)) for kind, cap in over.items()
        )
        start = float(part.get("start", span["start"]))
        end = float(part.get("end", span["end"]))
        out.append(
            {
                "start": timeline_vm.exact(start),
                "length": timeline_vm.exact(max(end - start, 0.0)),
                "n": str(span["n"]),
                "tone": "warn" if over else "",
                "cap": tag,
                "mode": "reference" if part.get("mode", "reference") == "reference" else "other",
            }
        )
    return out


def panel(
    item: Mapping[str, Any] | None,
    the_plan: Mapping[str, Any],
    total: float,
    *,
    thumbs: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The chosen reference's panel ({} = none): «Se usa en…» (or why not), what it is,
    its times, «Usar también en el video» (photos and videos: an audio never goes as a
    block of «Fotos y videos», decision 6) and, for a product's block, its photos."""
    if not item:
        return {}
    thumbs = thumbs or {}
    live = {str(i["uid"]): i for i in shown([item], total)}
    current = live.get(str(item.get("uid")))
    if current is None:
        return {}
    uid = str(current["uid"])
    used = list((the_plan.get("used_by") or {}).get(uid, ()))
    ignored = list((the_plan.get("ignored") or {}).get(uid, ()))
    lines = [used_text(used)] if used else []
    if ignored:
        lines.append(contract_ai.reference_text("reference_mode_ignored") or "")
    if not used and not ignored:
        lines = [used_text([]), UNUSED_HELP]
    product = current.get("origin") == "product"
    return {
        "id": ref_id(uid),
        "kind": str(current["kind"]),
        "used": " ".join(w for w in lines if w),
        "off": "" if used else "1",
        "what": WHAT_IT_IS,
        "times": TIMES_LABEL.format(
            start=timeline_vm.clock(current["start"]), end=timeline_vm.clock(current["end"])
        ),
        "hint": DRAG_HINT,
        "copy": "" if current["kind"] == "audio" or product else "1",
        "product": "1" if product else "",
        "photos": [
            {
                "key": str(k),
                "thumb": thumbs.get(str(k), ""),
                "remove": REMOVE_PHOTO_NAME.format(
                    n=n, product=str(current.get("name") or "").strip() or "tu producto"
                ),
            }
            for n, k in enumerate(current.get("keys") or (), start=1)
        ]
        if product
        else [],
    }


def ai_box(
    items: Sequence[Mapping[str, Any]],
    the_plan: Mapping[str, Any],
    entry: int,
    total: float,
    *,
    thumbs: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """«Lo que la IA mira aquí» of the AI part `entry`: the references it takes, then the
    videos and audios under it it does not use in its mode (struck through, with the
    contract's `reference_mode_ignored` words). Read-only: one place per action."""
    thumbs = thumbs or {}
    live = shown(items, total)
    numbers = _numbers(live)
    by_uid = {str(i["uid"]): i for i in live}
    part = next((p for p in the_plan.get("parts") or () if int(p["entry"]) == int(entry)), None)
    if part is None:
        return []
    n = int(part["n"])
    out: list[dict[str, str]] = []
    for kind in KINDS:
        for uid in (part.get("uses") or {}).get(kind, ()):
            item = by_uid.get(uid)
            if item is None:
                continue
            out.append(_box_row(item, numbers, thumbs, ignored=False))
    for uid, parts_n in (the_plan.get("ignored") or {}).items():
        if n in parts_n and uid in by_uid:
            out.append(_box_row(by_uid[uid], numbers, thumbs, ignored=True))
    return out


def _box_row(
    item: Mapping[str, Any],
    numbers: Mapping[str, int],
    thumbs: Mapping[str, str],
    *,
    ignored: bool,
) -> dict[str, str]:
    first = str((item.get("keys") or [""])[0])
    return {
        "id": ref_id(str(item["uid"])),
        "kind": str(item["kind"]),
        "name": label_of(item, numbers),
        "thumb": thumbs.get(first, "") if item["kind"] != "audio" else "",
        "ignored": "1" if ignored else "",
        "note": (contract_ai.reference_text("reference_mode_ignored") or "") if ignored else "",
        "tag": PRODUCT_TAG if item.get("origin") == "product" else "",
    }


def target_span(
    spans: Sequence[Mapping[str, Any]], playhead: float, block_id: str = ""
) -> Mapping[str, Any] | None:
    """Where a new reference goes: under the AI part `block_id` (its panel's «Agregar una
    referencia»), else the one under the playhead, else the nearest one (notas §9)."""
    if not spans:
        return None
    if block_id:
        found = next((s for s in spans if s["id"] == block_id), None)
        if found is not None:
            return found
    t = float(playhead)
    under = next((s for s in spans if s["start"] - 1e-6 <= t < s["end"] - 1e-6), None)
    if under is not None:
        return under
    return min(spans, key=lambda s: min(abs(s["start"] - t), abs(s["end"] - t)))


def nearest_join(media: Sequence[Mapping[str, Any]], t: float) -> int:
    """Decision 6: the join of «Fotos y videos» nearest `t` — the index a block put there
    takes (0 = before the first, len = after the last)."""
    rows = timeline_vm.media_blocks([dict(m) for m in media])
    bounds = [float(r["start"]) for r in rows]
    bounds.append(float(rows[-1]["start"]) + float(rows[-1]["length"]) if rows else 0.0)
    return min(range(len(bounds)), key=lambda i: (abs(bounds[i] - float(t)), i))


def slug(items: Sequence[Mapping[str, Any]], block_id: str, total: float) -> str:
    """The address's word for a reference: `referencia-foto-2`, `referencia-producto`."""
    live = shown(items, total)
    item = next((i for i in live if ref_id(str(i["uid"])) == block_id), None)
    if item is None:
        return ""
    if item.get("origin") == "product":
        return "referencia-producto"
    return f"referencia-{NOUNS[str(item['kind'])][0]}-{_numbers(live).get(str(item['uid']), 1)}"


def added_line(kind: str, n: int) -> str:
    _noun, _plural, art = NOUNS[kind]
    return ADDED_LINE.format(art=art, noun=NOUNS[kind][0], n=n)


__all__ = [
    "ACCEPT",
    "ADD_KEY",
    "ADD_LABEL",
    "KINDS",
    "SEPARATOR",
    "TL_KINDS",
    "ai_box",
    "ai_spans",
    "brief_of",
    "brief_references",
    "columns",
    "follow",
    "lanes",
    "new_item",
    "panel",
    "plan",
    "product_item",
    "rows",
    "set_time",
    "shift",
]
