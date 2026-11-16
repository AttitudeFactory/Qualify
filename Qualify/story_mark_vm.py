"""«Es una historia» on a piece's own page (founder 2026-11-16, m-25040496): the owner
marks a piece he uses as an Instagram historia — so the gallery labels it, «Tipo» ›
«Historias» finds it, and on Android «Abrir en Instagram» hands it to Instagram — and
can undo it. The words and the pure rules; nothing here reads or writes the database.

What a piece's `category` drives downstream (why the rule below is narrow):
- `publishable._shape_product_type`: a whole piece with no destination of its own goes
  out as STORIES (one image or one video), IMAGE/CAROUSEL (`galeria`) or REELS (`reel`);
- `planner_provider.event_destination`: an event saved without a destination falls
  back to that — so a piece with a live event is never changed here;
- the planner's default destination, the preview frame (`frame_shape`), the gallery's
  label, «Tipo» filter and share button (`planner_vm.is_story_post`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

STORY: Final = "story"
GALERIA: Final = "galeria"
REEL: Final = "reel"
#: The categories this control may move between: a `tiktok_video` piece keeps its own.
_SWITCHABLE: Final = frozenset({STORY, GALERIA, REEL})

STORY_MARK_LABEL: Final = "Es una historia"
STORY_MARK_HELP: Final = (
    "Si la programas, sale en tus historias de Instagram. Nada se publica sin que lo apruebes."
)
UNMARKED_TOAST_IMAGE: Final = "Listo: vuelve a ser una publicación."
UNMARKED_TOAST_VIDEO: Final = "Listo: vuelve a ser un reel."
CHANGE_FAILED: Final = "No pudimos cambiarla. Vuelve a intentarlo en un momento."
NO_SESSION: Final = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."

#: Why the switch is off — said under it, in the owner's words.
REASON_SEVERAL_FILES: Final = "Solo una foto o un video puede ser historia."
REASON_SCHEDULED: Final = "Está programada. Quítala de Tu semana para cambiarlo."
REASON_PURGED: Final = "Sus archivos ya se borraron. Crea una nueva o súbela otra vez."
REASON_TOO_LONG: Final = "Dura más de un minuto. Recórtala a 60 segundos para usarla como historia."
REASON_OTHER: Final = "No se puede cambiar ahora. Recarga la página y vuelve a intentarlo."


def marked_toast(*, approved: bool) -> str:
    """Where the owner finds it now: «Aprobados» › «Historias», or «Por aprobar»."""
    where = "Aprobados" if approved else "Por aprobar"
    return f"Listo: ahora es una historia. La encuentras en {where} › Historias."


def unmarked_toast(undo_category: str) -> str:
    """What it is again: a «publicación» (an image) or a «reel» (a video)."""
    return UNMARKED_TOAST_VIDEO if undo_category == REEL else UNMARKED_TOAST_IMAGE


@dataclass(frozen=True)
class StoryMarkVM:
    """The control's facts for one piece. `shown`: the page offers the switch at all
    (False for a template package, whose outputs already say what each one is)."""

    shown: bool = False
    is_story: bool = False
    can_change: bool = False
    reason: str = ""
    #: What «quitar» sets: the piece's shape without the mark (`undo_category`).
    undo_category: str = ""
    #: Approved by the owner: the mark's toast says where to find it.
    approved: bool = False


HIDDEN = StoryMarkVM()


def undo_category(media_types: tuple[str, ...] | list[str]) -> str:
    """The category a piece goes back to: a lone image is a «Publicación» (`galeria`), a
    lone video a «Reel» (`reel`) — the same rule as an own upload's shape
    (`own_upload.shape_for`). Not `default_category`: it returns `reel` for an image of
    most kinds, and `story` for anything made 9:16, which would make undoing a no-op.
    The category before the mark is not stored anywhere, so it is not guessed."""
    types = tuple(media_types)
    if types == ("VIDEO",):
        return REEL
    return GALERIA


def story_mark(
    *,
    category: str | None,
    media_types: tuple[str, ...] | list[str],
    has_outputs: bool,
    has_live_event: bool,
    purged: bool,
    video_too_long: bool,
    approved: bool = False,
) -> StoryMarkVM:
    """Who may be marked (or unmarked) a historia: ONE image or ONE video, not a
    template package, not purged, with no event that may still go out (`scheduled` —
    overdue too, it can be moved to another day — or `publishing`; an event without its
    own destination publishes as the category says), in any approval state. A video
    known to last over Meta's story limit cannot be marked (it can be unmarked)."""
    if has_outputs:
        return HIDDEN
    current = category or ""
    base = StoryMarkVM(
        shown=True,
        is_story=current == STORY,
        undo_category=undo_category(tuple(media_types)),
        approved=approved,
    )
    types = tuple(media_types)
    if current not in _SWITCHABLE:
        return replace(base, reason=REASON_OTHER)
    if len(types) != 1 or types[0] not in ("IMAGE", "VIDEO"):
        return replace(base, reason=REASON_SEVERAL_FILES)
    if purged:
        return replace(base, reason=REASON_PURGED)
    if has_live_event:
        return replace(base, reason=REASON_SCHEDULED)
    if video_too_long and not base.is_story:
        return replace(base, reason=REASON_TOO_LONG)
    return replace(base, can_change=True)


def target_category(mark: StoryMarkVM, *, story: bool) -> str | None:
    """The category to write for the switch's new value, or None when nothing changes
    (already so) or the piece may not change."""
    if not mark.can_change or mark.is_story == story:
        return None
    return STORY if story else mark.undo_category
