"""«Revisar y rehacer una parte» (m-24921083, UI-8): the words of the chosen part's
panel inside «Tu video completo», and of «Me gusta así» on each part's tile.

Pure: takes what `part_review_provider.read_review` returned (plain data, media already
signed) and gives the panel its words — «Versión 2 de 2 · Ver la anterior» (the
version looked at plays in the part's tile), how the part is made (read only:
`PartChanges` never changes the mode), what happens in it (filled in), its photos and
what «Crear otra versión» uses of the month — and the «Video de inspiración» card of
the video's page (its account, «Ir al video ↗»). No provider, session or database object.

Copy from the approved design (`m-24921083-diseno-ux.md` §2-§6). The words UI-4 already
uses for a part (`QUESTION`, `DESCRIPTION_LABEL`, `DESCRIPTION_EXAMPLE`, `*_HELP`) are
imported from `part_editor_vm` — one source for both screens.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from qualify_api.creative.parts import join_unique

# UI-4's words for a part (its sheet in /create), the same here
from .part_editor_vm import (
    DESCRIPTION_EXAMPLE,
    DESCRIPTION_LABEL,
    EDIT_HELP,
    EXTEND_HELP,
    NEW_HELP,
    QUESTION,
    REFERENCE_HELP,
)
from .reel_parts_vm import FORM_EDIT, FORM_EXTEND, FORM_INSPIRED, FORM_NEW

# -- «Me gusta así» on a part's tile (§3) ------------------------------------------------
LIKE_LABEL = "Me gusta así"
LIKED_LABEL = "Lista"
#: the tile's `ok` pill once the owner likes the part
LIKED_PILL = "✓ Lista"
LIKE_FAILED_TEXT = "No pudimos guardar tu marca. Inténtalo de nuevo en un momento."
LIKE_REFUSED_TEXT = "Esta parte cambió y ya no se puede marcar. Mira cómo está ahora."

# -- the chosen part's panel (§2) ----------------------------------------------------------
#: Deivid, 2026-11-13: the reel the video is inspired by, once for the whole video, as
#: a card on its page above «Campaña» — its account and a button to it (another tab);
#: no card when there is no reel
INSPIRATION_TITLE = "Video de inspiración"
INSPIRATION_BUTTON = "Ir al video ↗"
VERSION_TEXT = "Versión {n} de {m}"
#: the tile's ▶ while it plays an earlier version (its name says which one)
PLAY_VERSION_TEXT = "Ver la versión {v} de {m} de la parte {n}"
PAUSE_VERSION_TEXT = "Pausar la versión {v} de la parte {n}"
SEE_PREVIOUS = "Ver la anterior"
SEE_NEXT = "Ver la siguiente"
MADE_WITH_TEXT = "Se hizo con: «{text}»"
USE_VERSION = "Usar esta versión"
USE_VERSION_NOTE = "Tu video completo se vuelve a juntar con esta versión. No usa vistas previas."
VERSION_EXPIRED_TEXT = "Esta versión venció. Crea otra versión."
USED_VERSION_TEXT = "Usamos la versión {v} de la parte {n}. Estamos juntando tu video."

PHOTOS_LABEL = "Fotos de tu producto"
PHOTO_ARIA = "Foto {i} de tu producto"
#: a part that uses no photo of the product: said, never an empty section
NO_PHOTOS_TEXT = "Esta parte no usa fotos de tu producto."

DESCRIPTION_REQUIRED = "Cuéntanos qué muestra esta parte para crearla otra vez."
PHOTO_REQUIRED = "Elige al menos una foto de tu producto."
#: what «Crear otra versión» uses when the month's balance could not be read
CHANGE_NOTE = "Usa 1 vista previa. Las demás partes no cambian."
#: the ticket's words, verbatim: what «Crear otra versión» uses and what is left
CHANGE_USE_TEXT = "Usa 1 vista previa. Te quedan {p}."
NO_PREVIEWS_TEXT = "Este mes no te quedan vistas previas. Vuelven el {renews}."
NO_PREVIEWS_SOON_TEXT = "Este mes no te quedan vistas previas. Vuelven el próximo mes."
#: UX review of UI-8: the panel could not be read — its fields stay hidden (never an
#: empty box that would replace the description) and [Intentar de nuevo] reads again
REVIEW_FAILED_TEXT = "No pudimos abrir esta parte."
REVIEW_RETRY = "Intentar de nuevo"


def photos_to_send(
    selected: Sequence[str],
    initial: Sequence[str],
    all_keys: Sequence[str],
) -> tuple[str, ...] | None:
    """The `photo_keys` «Crear otra versión» sends (review of UI-8). None when the owner
    did not touch the product photos — the part keeps every photo it has. Touched: his
    product photos plus every other photo of the active brief (place, style…) in the
    brief's order, then the product photos new to it. `PartChanges.photo_keys` replaces
    the whole list and `parts.part_brief_with` gives each key back the role it had, so
    nothing but the owner's choice changes. `initial`: the product photos the panel
    opened with; `all_keys`: every photo of the active brief, in order. Pure."""
    if set(selected) == set(initial):
        return None
    chosen, products = set(selected), set(initial)
    out = [k for k in all_keys if k not in products or k in chosen]
    out += [k for k in selected if k not in out]
    return tuple(dict.fromkeys(out))


def mode_words(mode: str, from_reel: bool) -> tuple[str, str]:
    """«¿Cómo la hacemos?» read only: the part's form, as step 2 names it, and UI-4's
    line under it. `from_reel`: the part was taken from an analysed reel."""
    if mode == "edit":
        return FORM_EDIT, EDIT_HELP
    if mode == "extend":
        return FORM_EXTEND, EXTEND_HELP
    if from_reel:
        return FORM_INSPIRED, REFERENCE_HELP
    return FORM_NEW, NEW_HELP


def change_use_text(
    quote: tuple[int, int, int, str, int, int, int] | None,
) -> tuple[str, bool]:
    """What «Crear otra versión» uses of the month, from
    `creative_provider.regeneration_creations`' quote — and whether the month has no
    vista previa left (the button then waits, with this text as its reason). One part
    is one vista previa: the ticket's words, «Usa 1 vista previa. Te quedan {p}.». No
    quote (no quota wired, or unreadable): the generic note, never blocked — the
    service still refuses what it cannot pay."""
    if quote is None:
        return CHANGE_NOTE, False
    _weight, _left, _quota, renews, _previews, previews_left, preview_quota = quote
    if preview_quota <= 0:
        return CHANGE_NOTE, False
    if previews_left <= 0:
        text = NO_PREVIEWS_TEXT.format(renews=renews) if renews else NO_PREVIEWS_SOON_TEXT
        return text, True
    return CHANGE_USE_TEXT.format(p=previews_left), False


@dataclass(frozen=True)
class VersionRead:
    """One version of a part as the provider hands it (`part_review.PartVersion`): its
    words, its photos and whether it can still be used."""

    version_id: str
    ordinal: int
    total: int
    current: bool
    description: str
    photo_keys: tuple[str, ...]
    seconds: float
    liked: bool = False
    expired: bool = False
    #: its own vista previa, signed (`/r2media`, "" when none): what the part's TILE
    #: plays while the owner looks at this version (Deivid, 2026-11-13)
    video_url: str = ""
    poster_url: str = ""


@dataclass(frozen=True)
class PhotoRead:
    """A photo of the product the part may use: its key (what `PartChanges` takes) and
    where the browser shows it from (`/r2media` path, else the local upload key)."""

    key: str
    url: str = ""


@dataclass(frozen=True)
class PartReview:
    """Everything the chosen part's panel shows, read once when the part is chosen."""

    mode: str
    description: str
    photo_keys: tuple[str, ...]
    versions: tuple[VersionRead, ...] = ()
    photos: tuple[PhotoRead, ...] = ()
    #: the part was taken from a reel
    from_reel: bool = False
    quote: tuple[int, int, int, str, int, int, int] | None = None
    #: every photo of the active brief, in order, whatever its role
    all_photo_keys: tuple[str, ...] = ()


def unique_text(text: str) -> str:
    """A description with each repeated sentence said once (live test 2026-11-13: a
    part joined from two cuts of the reel with the same description reads it twice in
    its brief — the data stays as it is; the field shows it once). The backend's own
    rule (`parts.join_unique`): case, spaces and the final period aside. The text's own
    line breaks stay; a text with nothing repeated comes back exactly as it was, so
    «Crear otra versión» without an edit never rewrites the brief's format. Pure."""
    seen: set[str] = set()
    lines: list[str] = []
    dropped = False
    for line in (text or "").split("\n"):
        if not line.strip():
            lines.append(line)
            continue
        sentences = _SENTENCES.split(line.strip())
        kept: list[str] = []
        for sentence in sentences:
            key = _sentence_key(sentence)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            kept.append(sentence)
        if len(kept) == len(sentences):
            lines.append(line)  # nothing repeated here: the line as it was
            continue
        dropped = True
        if kept:  # a line said before, whole, goes
            lines.append(" ".join(kept))
    return "\n".join(lines).strip() if dropped else text


def _sentence_key(sentence: str) -> str:
    """`parts.join_unique`'s comparison: case, spaces and the final period aside."""
    return join_unique([" ".join(sentence.casefold().split()).rstrip(".")])


_SENTENCES = re.compile(r"(?<=[.!?])\s+")
#: the account of a TikTok page, `/@handle/…`
_PAGE_HANDLE = re.compile(r"/@([A-Za-z0-9._]+)")


def inspiration_href(url: str | None) -> str:
    """The inspiration reel's address for «Ir al video ↗», only an `https://` one (""
    otherwise — `http:`, `javascript:` or anything else: no card). Pure."""
    value = str(url or "").strip()
    return value if value.lower().startswith("https://") else ""


def account_text(handle: str | None, url: str | None = None) -> str:
    """«@thegoldenbalance» — the reel's account as the owner reads it: the stored one,
    else the one its page names (`/@handle/` on TikTok); "" when neither says it. Pure."""
    value = str(handle or "").strip().lstrip("@")
    if not value:
        found = _PAGE_HANDLE.search(str(url or ""))
        value = found.group(1) if found else ""
    return f"@{value}" if value else ""


def version_rows(versions: Sequence[VersionRead], number: int) -> list[dict[str, Any]]:
    """The versions in order (oldest first), each with its words: «Versión 1 de 2»,
    «Se hizo con: «…»», why it cannot be used, and its own vista previa with the names
    of its ▶ — played in the part's TILE while the owner looks at it (Deivid,
    2026-11-13: the panel plays no video of its own)."""
    ordered = sorted(versions, key=lambda v: v.ordinal)
    total = len(ordered)
    rows: list[dict[str, Any]] = []
    for position, version in enumerate(ordered, start=1):
        text = unique_text(version.description)
        rows.append(
            {
                "version_id": version.version_id,
                "ordinal": position,
                "current": version.current,
                "description": text,
                "photo_keys": list(version.photo_keys),
                "expired": version.expired,
                "label": VERSION_TEXT.format(n=position, m=max(total, version.total, 1)),
                "made_with": MADE_WITH_TEXT.format(text=text) if text else "",
                "use_reason": VERSION_EXPIRED_TEXT if version.expired else "",
                # seen in the part's tile before it is used (Deivid, 2026-11-13)
                "video_url": "" if version.expired else version.video_url,
                "poster_url": "" if version.expired else version.poster_url,
                "play_label": PLAY_VERSION_TEXT.format(v=position, m=total, n=number),
                "pause_label": PAUSE_VERSION_TEXT.format(v=position, n=number),
            }
        )
    return rows


@dataclass(frozen=True)
class ReviewView:
    """The panel as plain values for the state."""

    mode_label: str
    mode_help: str
    description: str
    selected: list[str]
    photos: list[dict[str, str]]
    versions: list[dict[str, Any]]
    at: int  # the version on screen (position in `versions`, 0-based)
    use_text: str
    out_of_previews: bool
    all_photo_keys: list[str]


def review_view(review: PartReview, number: int) -> ReviewView:
    """The chosen part's panel. The version on screen starts at the current one; the
    fields are filled with what the part has now (`part_edit_fields`)."""
    label, help_text = mode_words(review.mode, review.from_reel)
    versions = version_rows(review.versions, number)
    at = next((i for i, v in enumerate(versions) if v["current"]), len(versions) - 1)
    keys = list(dict.fromkeys(review.photo_keys))
    photos = [{"key": p.key, "url": p.url} for p in review.photos if p.key]
    known = {p["key"] for p in photos}
    for version in versions:  # every photo some version used stays choosable
        for key in version["photo_keys"]:
            if key not in known:
                photos.append({"key": key, "url": ""})
                known.add(key)
    for key in keys:
        if key not in known:
            photos.append({"key": key, "url": ""})
            known.add(key)
    for i, photo in enumerate(photos, start=1):
        photo["label"] = PHOTO_ARIA.format(i=i)
    use_text, out = change_use_text(review.quote)
    return ReviewView(
        mode_label=label,
        mode_help=help_text,
        description=unique_text(review.description),
        selected=keys,
        photos=photos,
        versions=versions,
        at=max(at, 0),
        use_text=use_text,
        out_of_previews=out,
        all_photo_keys=list(review.all_photo_keys or review.photo_keys),
    )


__all__ = [
    "CHANGE_NOTE",
    "DESCRIPTION_EXAMPLE",
    "DESCRIPTION_LABEL",
    "DESCRIPTION_REQUIRED",
    "LIKED_LABEL",
    "LIKED_PILL",
    "LIKE_LABEL",
    "MADE_WITH_TEXT",
    "NO_PHOTOS_TEXT",
    "INSPIRATION_BUTTON",
    "INSPIRATION_TITLE",
    "PHOTOS_LABEL",
    "PHOTO_REQUIRED",
    "PartReview",
    "PhotoRead",
    "QUESTION",
    "ReviewView",
    "SEE_NEXT",
    "SEE_PREVIOUS",
    "USE_VERSION",
    "USE_VERSION_NOTE",
    "VERSION_EXPIRED_TEXT",
    "VersionRead",
    "change_use_text",
    "mode_words",
    "account_text",
    "inspiration_href",
    "review_view",
    "unique_text",
    "version_rows",
]
