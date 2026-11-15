"""«Tu rubro» in Tu marca (m-25029206): the rubro in the owner's words and up to
`CHOSEN_HASHTAGS` etiquetas, for a brand that already exists — pure, so it is tested
without a browser.

The pills are the wizard's own (`creative_wizard_pages.add_pills`: same shape, same
duplicate folding, same cap); what this module adds is the check the wizard does not
make: a tag is kept only when the shared catalog would accept it
(`qualify_api.hashtags.weekly.readable_tag` — letters, digits and `_`, at most
`MAX_TAG_LENGTH` long, stored without «#», lowercase as `normalize_tag` writes it)."""

from __future__ import annotations

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
NOTE_REPEATED = "Esa etiqueta ya está en tu lista."
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


def add_typed(pills: list[dict[str, str]], raw: str) -> tuple[list[dict[str, str]], str, bool]:
    """`pills` with what was typed added through the wizard's `add_pills`. Returns the
    pills, the note to show ("" when all went well) and whether the text was taken —
    False keeps it in the input so it can be fixed (refused, or no room left)."""
    pills = stored_pills(pills)  # a pill without a tag would break `add_pills`
    tag, note = typed_tag(raw)
    if not tag:  # refused (a note) — or nothing but «#», which simply closes the input
        return [dict(p) for p in pills], note, not note
    if fold(tag) in {fold(p.get("tag", "")) for p in pills}:
        return [dict(p) for p in pills], NOTE_REPEATED, True
    out, note = add_pills(pills, [{"tag": tag, "origin": "manual"}])
    return out, note, len(out) > len(pills)


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
