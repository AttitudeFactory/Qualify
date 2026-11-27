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

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
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
REASON_SCHEDULED: Final = (
    "Está programada. En Tu semana, quítala del calendario y vuelve aquí para cambiarlo."
)
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
    #: The file «Abrir en Instagram» hands over on this page (`planner_vm.story_share_source`,
    #: the gallery card's rule): "" unless an approved, publishable historia of one file.
    share_url: str = ""
    #: The iPhone line next to «Descargar»: exactly when `share_url` is set (the card's
    #: rule — approved, publishable, kept, one image or video). Independent of `shown`:
    #: a template package has no switch.
    story_ready: bool = False
    #: With `REASON_SCHEDULED`: Tu semana opened on the next event to go out
    #: (`scheduled_event_href`), where the owner can remove it.
    event_href: str = ""


HIDDEN = StoryMarkVM()

SCHEDULED_LINK: Final = "Ver en Tu semana"
SCHEDULED_LINK_ARIA: Final = "Ver en Tu semana cuándo sale y quitarla de ahí"


def next_live_event(events: Iterable[tuple[str, datetime]]) -> tuple[str, datetime] | None:
    """Of the piece's events that may still go out, `(id, when)`, the one that goes out
    first (an overdue one first of all: it is due); None when there is none."""
    pending = list(events)
    return min(pending, key=lambda item: item[1]) if pending else None


def scheduled_event_href(event_id: str, local_day: date) -> str:
    """Tu semana on the week of `local_day` (the business's own day of the event) with
    that event's panel open — the planner's own `?semana=` and `?ficha=` (it re-reads the
    event under the tenant, so a foreign or deleted id opens nothing and says so)."""
    monday = local_day - timedelta(days=local_day.weekday())
    return f"/planner?semana={monday.isoformat()}&ficha={event_id}"


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


# -- «Subir historia» in «Aprobados» (founder 2026-11-17) ------------------------------
# The owner chose «historia» by choosing this entry: the piece is saved as one whatever
# its shape; nothing is scheduled.

UPLOAD_STORY_ENTRY: Final = "Subir historia"
UPLOAD_STORY_TITLE: Final = "Sube tu historia"
UPLOAD_STORY_HINT: Final = (
    "Elige una foto o un video tuyo. La guardamos en Historias y nada se publica hasta "
    "que tú lo hagas."
)
UPLOAD_STORY_SAVE: Final = "Guardar historia"
STORY_SAVED_ANDROID: Final = (
    "Tu historia quedó guardada. Toca «Abrir en Instagram» en su tarjeta para ponerle música."
)
STORY_SAVED: Final = "Tu historia quedó guardada. La encuentras en Historias."
STORY_SAVED_NOT_MARKED: Final = (
    "Tu archivo quedó guardado, pero no como historia. Toca su tarjeta y activa «Es una historia»."
)


def story_saved_toast(*, platform: str, marked: bool) -> tuple[str, str]:
    """`(toast kind, words)` after «Guardar historia»: the music only where the button
    is (Android); a mark that failed says where to finish."""
    if not marked:
        return "warning", STORY_SAVED_NOT_MARKED
    if platform == "android":
        return "success", STORY_SAVED_ANDROID
    return "success", STORY_SAVED
