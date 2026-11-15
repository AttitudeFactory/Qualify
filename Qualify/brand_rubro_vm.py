"""«Tu rubro» in Tu marca (m-25029206): the rubro in the owner's words and up to
`CHOSEN_HASHTAGS` etiquetas, for a brand that already exists — pure, so it is tested
without a browser.

The pills are the wizard's own (`creative_wizard_pages.add_pills`: same shape, same
duplicate folding, same cap); what this module adds is the check the wizard does not
make: a tag is kept only when the shared catalog would accept it
(`qualify_api.hashtags.weekly.readable_tag` — letters, digits and `_`, at most
`MAX_TAG_LENGTH` long, stored without «#», lowercase as `normalize_tag` writes it)."""

from __future__ import annotations

import re

from qualify_api.hashtags import fold, normalize_tag
from qualify_api.hashtags.weekly import MAX_TAG_LENGTH, readable_tag
from qualify_api.referentes.discovery_seed import CHOSEN_HASHTAGS

from .creative_wizard_pages import add_pills

#: The section's key in `brand_kit_editor.SECTIONS`.
RUBRO_SECTION = "rubro"
#: The rubro is a short description, not a text: what the input lets through.
RUBRO_MAX_LENGTH = 200

NOTE_CHARACTERS = (
    "Usa solo letras, números o guion bajo, sin signos ni emojis. Por ejemplo: comidaarabe."
)
NOTE_TOO_LONG = (
    f"Una etiqueta puede tener hasta {MAX_TAG_LENGTH} letras. Escribe una más corta, "
    "por ejemplo: pizzeria."
)
#: Typed etiquetas that were already there moved to the typed order: said, once.
NOTE_REORDERED = "Las ordenamos como las escribiste."
#: The wizard's own words for a full list (`add_pills`).
_FULL_NOTE = f"Caben {CHOSEN_HASHTAGS} etiquetas: quita alguna para agregar otra."
#: Why the order matters, in words true for every business.
ORDER_HELP = "Pon primero las más importantes."
#: Words typed apart became one etiqueta: said, so three typed as one is not missed.
NOTE_JOINED = "La unimos en una sola: #{tag}. Si eran varias, sepáralas con comas."
#: What separates etiquetas typed at once.
_SEPARATORS = re.compile(r"[,;]")
#: An old etiqueta (saved before this check) the catalog would refuse: shown marked, and
#: «Guardar» waits until it is changed or removed — it never vanishes unseen.
NOTE_INVALID_STORED = (
    "Las etiquetas marcadas no sirven: quítalas con la ✕ y escríbelas de nuevo con solo "
    "letras, números o guion bajo."
)
RUBRO_MISSING = "Escribe a qué se dedica tu negocio para poder guardar."


def clean_rubro(text: str) -> str:
    """The rubro as it is stored: one line, single spaces, at most `RUBRO_MAX_LENGTH`."""
    return " ".join(str(text or "").split())[:RUBRO_MAX_LENGTH]


def stored_pills(raw: object) -> list[dict[str, str]]:
    """The pills as the section edits them: only objects with a tag (anything else in the
    stored list has nothing to show or keep), every value a string."""
    if not isinstance(raw, list):
        return []
    return [
        {str(k): str(v) for k, v in item.items()}
        for item in raw
        if isinstance(item, dict) and str(item.get("tag") or "").strip()
    ]


def invalid_tags(pills: list[dict[str, str]]) -> list[str]:
    """The tags among `pills` the catalog would refuse — old ones the wizard let through."""
    return [p["tag"] for p in pills if readable_tag(p.get("tag")) is None]


def typed_tag(raw: str) -> tuple[str, str]:
    """What the owner typed as ONE tag: `(tag, "")` when the catalog would accept it, or
    `("", note)` saying what to fix. Words are joined («comida árabe» → «comidaárabe»):
    only signs, emojis or a tag over `MAX_TAG_LENGTH` are refused. Empty (or just «#») is
    `("", "")`: nothing to add."""
    text = "".join(str(raw or "").split())
    if not text.lstrip("#"):
        return "", ""
    try:
        tag = normalize_tag(text)
    except ValueError:  # a «#» inside the word: a sign like any other
        return "", NOTE_CHARACTERS
    if len(tag) > MAX_TAG_LENGTH:
        return "", NOTE_TOO_LONG
    if readable_tag(tag) is None:
        return "", NOTE_CHARACTERS
    return tag, ""


def add_typed_parts(pills: list[dict[str, str]], raw: str) -> tuple[list[dict[str, str]], str, str]:
    """`pills` with what was typed — THE TYPED ORDER WINS (m-25029206, founder's report of
    2026-11-15). A comma or a semicolon separates etiquetas («pizza, pasta, vino» is
    three), each checked on its own. Typing only new etiquetas adds them at the end, in
    the typed order. As soon as the text names one already in the list, the list becomes
    the typed etiquetas in the order typed — the ones already there MOVE to their typed
    place, never refused as a repeat — followed by the ones not typed, in their order.

    Nothing is ever removed without the owner's ✕: moving never changes the count, and a
    NEW etiqueta that does not fit under `CHOSEN_HASHTAGS` stays in the input with
    «Caben 5 etiquetas…». Returns the pills, the note to show ("" when all went well)
    and what stays in the input: the parts refused or with no room left ("" closes it)."""
    current = stored_pills(pills)  # a pill without a tag would break `add_pills`
    by_fold = {fold(p["tag"]): p for p in current}
    typed: list[dict[str, str]] = []
    typed_folds: set[str] = set()
    room = CHOSEN_HASHTAGS - len(current)
    notes: list[str] = []
    left: list[str] = []
    moved = False
    for part in (p.strip() for p in _SEPARATORS.split(str(raw or ""))):
        tag, note = typed_tag(part)
        if not tag:  # refused (a note) — or nothing but «#», which adds nothing
            if note:
                notes.append(note)
                left.append(part)
            continue
        key = fold(tag)
        if key in typed_folds:  # typed twice in one go: the first place counts
            continue
        if key in by_fold:
            typed.append(dict(by_fold[key]))
            typed_folds.add(key)
            moved = True
            continue
        if room <= 0:
            notes.append(_FULL_NOTE)
            left.append(part)
            continue
        new, _ = add_pills([], [{"tag": tag, "origin": "manual"}])
        typed.extend(new)
        typed_folds.add(key)
        room -= 1
        if len(part.lstrip("#").split()) > 1:
            notes.append(NOTE_JOINED.format(tag=tag))
    rest = [dict(p) for p in current if fold(p["tag"]) not in typed_folds]
    # only new ones typed: an ordinary add, at the end; naming one already there means
    # «this is my order» — the typed ones first, the rest after them
    out = typed + rest if moved else rest + typed
    if moved and [p["tag"] for p in out] != [p["tag"] for p in current]:
        notes.append(NOTE_REORDERED)
    return out, " ".join(dict.fromkeys(notes)), ", ".join(left)


def move_tag(pills: list[dict[str, str]], tag: str, to: int) -> list[dict[str, str]]:
    """`tag` moved to place `to` (remove, then insert) — «Subir», «Bajar», «Mover al
    principio», the handle's arrows and a drag all go through here. An unknown tag or a
    place out of range leaves the list as it was."""
    out = [dict(p) for p in pills]
    tags = [p.get("tag") for p in out]
    if tag not in tags or not 0 <= to < len(out):
        return out
    out.insert(to, out.pop(tags.index(tag)))
    return out


def tag_rows(pills: list[dict[str, str]], invalid: list[str]) -> list[dict[str, str]]:
    """What each row of the open section shows: its number, and the words a screen reader
    hears for the handle and the «⋯» (flags are "1" or "", as the view reads them)."""
    count = len(pills)
    return [
        {
            "tag": p["tag"],
            "number": str(i + 1),
            "index": str(i),
            "up": str(i - 1),
            "down": str(i + 1),
            "can_up": "1" if i > 0 else "",
            "can_down": "1" if i < count - 1 else "",
            "invalid": "1" if p["tag"] in invalid else "",
            "handle_label": f"Mover «#{p['tag']}», posición {i + 1} de {count}",
            "more_label": f"Más opciones para «#{p['tag']}»",
        }
        for i, p in enumerate(pills)
    ]


def tag_place_text(tag: str, index: int, count: int) -> str:
    """What a screen reader hears after a move."""
    return f"#{tag}, posición {index + 1} de {count}"


def tag_lifted_text(tag: str, index: int, count: int) -> str:
    return (
        f"Levantaste «#{tag}», posición {index + 1} de {count}. Muévela con las flechas y "
        "suéltala con Espacio. Escape la deja donde estaba."
    )


def add_typed(pills: list[dict[str, str]], raw: str) -> tuple[list[dict[str, str]], str, bool]:
    """`add_typed_parts`, with whether the whole text was taken instead of what is left."""
    out, note, left = add_typed_parts(pills, raw)
    return out, note, not left


def can_search_again(profile_username: str, username: str, network: str) -> bool:
    """«Buscar de nuevo» can run: exactly `BrandConnectState.refresh_discovery`'s own
    condition — the brand's handle (read or typed) AND its network."""
    return bool(profile_username or username.strip()) and bool(network)


def remove_tag(pills: list[dict[str, str]], tag: str) -> list[dict[str, str]]:
    return [dict(p) for p in pills if p.get("tag") != tag]


def pills_for_save(pills: list[dict[str, str]]) -> list[dict[str, str]]:
    """The pills as they are written: only the ones the catalog would accept (an old pill
    the wizard let through, e.g. «c++», is dropped), each tag in its stored spelling,
    duplicates folded, at most `CHOSEN_HASHTAGS` — every other key of a pill (origin,
    Claude's reason) kept as the wizard wrote it."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for pill in pills:
        tag = readable_tag(pill.get("tag"))
        if tag is None or fold(tag) in seen:
            continue
        if len(out) >= CHOSEN_HASHTAGS:
            break
        seen.add(fold(tag))
        out.append({"origin": "manual", "reason": "", "model": "", **pill, "tag": tag})
    return out


def can_add(pills: list[dict[str, str]]) -> bool:
    return len(pills) < CHOSEN_HASHTAGS
