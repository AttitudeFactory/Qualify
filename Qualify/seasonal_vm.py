"""Stickers y videos de tu marca (m-24976895, spec `docs/ux-stickers-videos.md`) — the
words and pure rules of the season library, the three-step «Crear para esta temporada»
flow and the «Por aprobar» batch. No I/O here: the state hands in plain rows from
`seasonal_provider` (the backend's `SeasonalMediaService`) and gets frozen view models.

Founder's rules (2026-11-08): every batch passes «Por aprobar»; nothing unapproved
reaches a chat; seasons keep their previous batches; «Crear con IA» only makes videos
and always shows its estimated cost (from the pricing table, never written by hand)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

# -- words ---------------------------------------------------------------------------------

SECTION_TITLE: Final = "Stickers y videos de tu marca"
SECTION_HELP: Final = "Para saludar y celebrar con tu marca en WhatsApp."
CREATE_LABEL: Final = "Crear para esta temporada"
ARCHIVE_LABEL: Final = "Archivar"
ARCHIVED_TITLE: Final = "Archivadas"
RESTORE_LABEL: Final = "Volver a usar"
UNDO_LABEL: Final = "Deshacer"
EMPTY_TITLE: Final = "Aún no tienes stickers ni videos"
EMPTY_TEXT: Final = (
    "Créalos gratis con tu logo y tus fotos aprobadas. Los mandas en tus chats con un toque."
)
LOAD_FAILED: Final = "No pudimos traer tus stickers y videos. Vuelve a intentarlo en un momento."
ACTION_FAILED: Final = "No pudimos guardar el cambio. Vuelve a intentarlo en un momento."
NO_SESSION: Final = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
RETRY_LABEL: Final = "Reintentar"

# the flow
STEP_OCCASION: Final = "¿Para qué ocasión?"
STEP_HOW: Final = "¿Cómo lo creamos?"
STEP_REVIEW: Final = "Revisa y crea"
ALL_YEAR_LABEL: Final = "Todo el año"
ALL_YEAR_LINE: Final = "Para cualquier día, sin fecha."
OTHER_LABEL: Final = "Otra ocasión"
OTHER_NAME_LABEL: Final = "Nombre de la ocasión"
OTHER_NAME_HINT: Final = "Por ejemplo: Aniversario del local"
MAX_OTHER_NAME: Final = 24
OTHER_NAME_MISSING: Final = "Escribe el nombre de la ocasión."
FREE_TITLE: Final = "Con lo que ya tienes · gratis"
FREE_LINE: Final = (
    "Stickers con tu logo y tus colores, y videos con tus fotos ya aprobadas. Sin costo."
)
AI_LINE: Final = (
    "La IA anima tus fotos aprobadas para que se muevan solas. Tiene costo y solo hace "
    "videos: no puede dejar el fondo transparente que necesita un sticker."
)
#: m-24976893 «Crear con IA»: the step that shows WHAT will be animated before paying.
CHECKING_PRICE: Final = "Revisando el precio…"
NO_PHOTOS_TO_SHOW: Final = (
    "Todavía no tienes fotos aprobadas para animar. Aprueba una en Por aprobar o usa "
    "«Con lo que ya tienes», que es gratis."
)
AI_UNAVAILABLE: Final = "Crear con IA todavía no está disponible."
NEXT_LABEL: Final = "Siguiente"
BACK_LABEL: Final = "Atrás"
CREATE_BUTTON: Final = "Crear"
CREATING_LABEL: Final = "Creando…"
CREATE_FAILED: Final = "No pudimos empezar a crear. Vuelve a intentarlo en un momento."
AI_LIMIT: Final = (
    "Este mes ya usaste lo que tu plan trae para videos con IA. Usa «Con lo que ya tienes», "
    "que es gratis."
)
#: `NothingToMake` (no logo and no approved photo piece): said in step 3 with both ways.
MISSING_MATERIAL: Final = (
    "Primero aprueba una foto o sube tu logo: con eso creamos tus stickers y videos."
)
UPLOAD_LOGO_LABEL: Final = "Subir mi logo"
GO_DRAFTS_LABEL: Final = "Ir a Por aprobar"
DRAFTS_ROUTE: Final = "/drafts"
STARTED_TOAST: Final = "Listo: estamos preparando tus stickers y videos. Llegan a Por aprobar."

# Por aprobar
STICKER_BADGE: Final = "Sticker"
VIDEO_BADGE: Final = "Video"
PREPARING: Final = "Preparando…"
APPROVE_LABEL: Final = "Aprobar"
ANOTHER_LABEL: Final = "Pedir otro"
APPROVE_READY_LABEL: Final = "Aprobar los listos"
HEAVY_PILL: Final = "Muy pesado"
HEAVY_TEXT: Final = "Salió muy pesado para WhatsApp. Pide otro."
FAILED_TEXT: Final = "Este no salió. Pide otro."
BATCH_FAILED: Final = "No pudimos preparar tus stickers. Vuelve a intentarlo en un rato."
TRY_AGAIN_LABEL: Final = "Intentar de nuevo"
APPROVED_PILL: Final = "Aprobado"
TAP_TO_SEE: Final = "Toca para ver"
CANCEL_LABEL: Final = "Cancelar"
ANOTHER_AI_YES: Final = "Sí, crear otro"
APPROVED_TOAST: Final = "Listo: ya lo puedes mandar en tus chats."
EMPTY_DRAFTS_LINK: Final = "Crea tus stickers y videos de temporada"
# m-24986801 (docs/ux-aprobados-y-menus.md §2–§3): the approved leave «Por aprobar» and
# live in «Aprobados», by season, filtered by kind.
APPROVED_TOAST_ACTION: Final = "Ver aprobados"
APPROVED_STICKERS_HREF: Final = "/aprobados?ver=stickers"
PENDING_EMPTY_TITLE: Final = "Aún no tienes stickers ni videos por aprobar"
PENDING_EMPTY_TEXT: Final = (
    "Crea los de esta temporada: con tu logo y tus colores, para saludar en tus chats."
)
APPROVED_EMPTY_TITLE: Final = "Aún no apruebas stickers ni videos"
APPROVED_EMPTY_TEXT: Final = "Apruébalos en Por aprobar o crea los de esta temporada."
KIND_FILTER_LABEL: Final = "Tipo"
KIND_ALL: Final = "all"
KIND_ALL_LABEL: Final = "Todos"
KIND_STICKERS_LABEL: Final = "Stickers"
KIND_VIDEOS_LABEL: Final = "Videos"
KIND_EMPTY_TITLE: Final = "Nada de ese tipo todavía"
KIND_EMPTY_ACTION: Final = "Ver todos"
SEND_HINT: Final = (
    "Se mandan desde un chat de WhatsApp: toca «+» › «Fotos y videos» y elige los de tu marca."
)
SEND_LINK_LABEL: Final = "Ir a tus chats"
SEND_LINK_HREF: Final = "/whatsapp?tab=chats"

#: Row statuses (`SeasonalMediaService`).
PENDING: Final = "pending"
READY: Final = "ready"
APPROVED: Final = "approved"
REJECTED: Final = "rejected"
ARCHIVED: Final = "archived"
FAILED: Final = "failed"
STICKER: Final = "sticker"
VIDEO: Final = "video"

MODE_FREE: Final = "free"
MODE_AI: Final = "ai"
OTHER_KEY: Final = "otra"
ALL_YEAR_KEY: Final = "todo-el-ano"
#: The «Tu marca» route that holds the section (and the flow's way out).
BRAND_ROUTE: Final = "/brand/kit"
#: «Crear para esta temporada» from Por aprobar's empty state opens the flow there.
CREATE_HREF: Final = BRAND_ROUTE + "?crear=temporada"

# -- the seasons calendar (CO/VE/UY) ------------------------------------------------------
#
# Step 1 offers the backend's calendar (`whatsapp.seasons.SeasonCalendarService.upcoming`,
# m-24976896: names, dates and keys per country). The short list below is ONLY the
# fallback when that read fails, so the flow still opens.


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _occasions(year: int, country: str) -> list[tuple[str, str, date]]:
    """(slug, name, date) of one year's occasions for `country` (ISO-2)."""
    c = (country or "").upper()
    sunday, saturday = 6, 5
    days: list[tuple[str, str, date]] = [
        ("navidad", "Navidad", date(year, 12, 25)),
        ("madre", "Día de la Madre", _nth_weekday(year, 5, sunday, 2)),
        ("noche-de-brujas", "Noche de brujas", date(year, 10, 31)),
    ]
    if c == "UY":
        days.append(("padre", "Día del Padre", _nth_weekday(year, 7, sunday, 2)))
    else:
        days.append(("padre", "Día del Padre", _nth_weekday(year, 6, sunday, 3)))
    if c == "CO":
        days.append(("amor-amistad", "Amor y Amistad", _nth_weekday(year, 9, saturday, 3)))
    else:
        days.append(("san-valentin", "San Valentín", date(year, 2, 14)))
    return days


@dataclass(frozen=True)
class OccasionVM:
    key: str = ""  # «navidad-2026», «todo-el-ano», «otra»
    label: str = ""  # «Navidad 2026»
    line: str = ""  # «faltan 3 semanas»


def _until(today: date, day: date) -> str:
    days = (day - today).days
    if days <= 0:
        return "es hoy"
    if days == 1:
        return "falta 1 día"
    if days < 14:
        return f"faltan {days} días"
    weeks = days // 7
    if weeks < 9:
        return f"faltan {weeks} semanas"
    months = round(days / 30)
    return f"faltan {months} meses"


def upcoming_occasions(today: date, country: str, count: int = 2) -> list[OccasionVM]:
    """The next `count` dated occasions (today included), soonest first."""
    found: list[tuple[date, str, str]] = []
    for year in (today.year, today.year + 1):
        for slug, name, day in _occasions(year, country):
            if day >= today:
                found.append((day, slug, name))
    found.sort()
    return [
        OccasionVM(key=f"{slug}-{day.year}", label=f"{name} {day.year}", line=_until(today, day))
        for day, slug, name in found[:count]
    ]


def occasions_from_calendar(seasons: Iterable[Any], today: date) -> list[OccasionVM]:
    """The backend's `CalendarSeason`s (key, label, day) as step 1's dated cards, with
    «faltan N semanas» counted from the backend's own dates."""
    return [
        OccasionVM(key=s.season_key, label=s.season_label, line=_until(today, s.day))
        for s in seasons
    ]


def occasion_choices(
    today: date, country: str, calendar: Sequence[OccasionVM] | None = None
) -> list[OccasionVM]:
    """Step 1's cards: the dated seasons (the backend's; the client list only when that
    read failed — `calendar is None`), the first preselected, then «Todo el año» and
    «Otra ocasión» (named by the owner)."""
    dated = list(calendar) if calendar is not None else upcoming_occasions(today, country)
    return [
        *dated,
        OccasionVM(key=ALL_YEAR_KEY, label=ALL_YEAR_LABEL, line=ALL_YEAR_LINE),
        OccasionVM(key=OTHER_KEY, label=OTHER_LABEL, line=""),
    ]


def slug(text: str) -> str:
    import unicodedata  # noqa: PLC0415

    folded = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    parts = "".join(ch if ch.isalnum() else " " for ch in plain).split()
    return "-".join(parts)[:40]


def other_occasion(name: str, year: int) -> tuple[str, str]:
    """(key, label) for «Otra ocasión»: «aniversario-del-local-2026», as typed."""
    clean = " ".join((name or "").split())[:MAX_OTHER_NAME]
    return (f"{slug(clean)}-{year}" if clean else ""), clean


def name_count(name: str) -> str:
    return f"{len(name)}/{MAX_OTHER_NAME}"


# -- money -----------------------------------------------------------------------------------


def usd_label(amount: Decimal | float | None) -> str:
    """«US$0,05» (Spanish decimal comma, two decimals); «menos de US$0,01»; "" unknown."""
    if amount is None:
        return ""
    value = Decimal(str(amount))
    if value <= 0:
        return ""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded <= 0:
        return "menos de US$0,01"
    return f"US${rounded:.2f}".replace(".", ",")


def ai_title(cost: str) -> str:
    """«Crear con IA · unos US$0,05 por video» ("" cost: the plain name)."""
    return f"Crear con IA · unos {cost} por video" if cost else "Crear con IA"


def ai_create_button(total: str, videos: int = 1) -> str:
    """«Crear 3 videos · unos US$0,15» / «Crear 1 video · unos US$0,05» — the TOTAL the
    owner confirms."""
    what = "1 video" if videos == 1 else f"{videos} videos"
    return f"Crear {what} · unos {total}" if total else CREATE_BUTTON


def another_ai_question(cost: str) -> str:
    """«Pedir otro» on a video made with IA: another paid call (spec §2). Only asked
    with a price — without one the action is not offered."""
    return f"Pedir otro cuesta unos {cost}. ¿Lo creamos?" if cost else ""


def photos_line(count: int) -> str:
    """Read-only in the beta: the backend picks them (choosing is a later ticket)."""
    if count == 1:
        return "Elegimos tu foto aprobada más reciente."
    return f"Elegimos tus {count} fotos aprobadas más recientes."


def total_line(total: str) -> str:
    return f"Total: unos {total}" if total else ""


#: `SelectionChanged`: an approved photo came or went between the quote and «Crear».
PHOTOS_CHANGED: Final = "Tus fotos aprobadas cambiaron: ahora animaríamos estas. ¿Seguimos?"


def price_changed(total: str) -> str:
    """`CostNotConfirmed`: the quote moved between the step and «Crear»."""
    return f"El precio cambió: ahora son unos {total}. ¿Seguimos?"


def month_spend_line(amount: Decimal | None) -> str:
    """«Este mes has gastado US$0,45 en videos con IA.» — only when something was spent."""
    label = usd_label(amount) if amount is not None and amount > 0 else ""
    return f"Este mes has gastado {label} en videos con IA." if label else ""


def _batch_words(stickers: int, videos: int) -> str:
    parts = []
    if stickers:
        parts.append(f"{stickers} sticker" if stickers == 1 else f"{stickers} stickers")
    if videos:
        parts.append(f"{videos} video" if videos == 1 else f"{videos} videos")
    return " y ".join(parts) or "tus stickers y videos"


def review_text(
    label: str, mode: str, stickers: int = 0, videos: int = 0, ai_videos: int = 0
) -> str:
    """«Vamos a preparar 6 stickers y 4 videos para «Navidad 2026». …» (the counts are
    the backend's `STANDARD_BATCH`); with IA, the QUOTE's count: «Vamos a animar 3 fotos
    para «Navidad 2026»: un video por foto. …»."""
    tail = " Llegan a Por aprobar en unos minutos. Nada se manda sin que lo apruebes."
    if mode == MODE_AI:
        if ai_videos == 1:
            return f"Vamos a animar 1 foto para «{label}»: un video.{tail}"
        return f"Vamos a animar {ai_videos} fotos para «{label}»: un video por foto.{tail}"
    made = _batch_words(stickers, videos)
    return f"Vamos a preparar {made} para «{label}».{tail}"


# -- rows → view models -----------------------------------------------------------------------


def kb_label(size: int | None) -> str:
    """«320 KB» / «1,4 MB»; "" when unknown."""
    if not size or size <= 0:
        return ""
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024))} KB"
    return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")


@dataclass(frozen=True)
class SeasonalItemVM:
    id: str = ""
    season_key: str = ""
    season_label: str = ""
    kind: str = STICKER
    kind_label: str = STICKER_BADGE
    is_video: bool = False
    status: str = PENDING
    preparing: bool = False
    ready: bool = False
    approved: bool = False
    failed: bool = False
    heavy: bool = False
    fail_text: str = ""
    size_label: str = ""
    #: A signed `/r2media/…` path (""while it is being prepared).
    src: str = ""
    alt: str = ""
    #: Made with IA: «Pedir otro» says the cost and asks first.
    paid: bool = False


#: What each recipe makes, for the screen reader («Sticker de «Navidad 2026»: tu logo con
#: latido»); an unknown recipe says only the kind and the season.
RECIPE_WORDS: Final[dict[str, str]] = {
    "e-latido": "tu logo con latido",
    "e-rebote": "tu logo con rebote",
    "e-giro": "tu logo que gira",
    "e-brillo": "tu logo con brillo",
    "e-texto": "un texto de la temporada",
    "b-zoom": "una foto tuya que se acerca",
    "b-pan": "una foto tuya que se desliza",
    "b-xfade": "tus fotos, una tras otra",
    "b-logo": "tu logo en movimiento",
    "ai-seedance": "una foto tuya animada con IA",
}


def item_alt(kind_label: str, season: str, recipe: str) -> str:
    what = RECIPE_WORDS.get(recipe, "")
    head = f"{kind_label} de «{season}»"
    return f"{head}: {what}" if what else head


def _row(
    row: Any, label: str, src: str, reasons: Mapping[str, str] | None = None
) -> SeasonalItemVM:
    kind = str(getattr(row, "kind", STICKER) or STICKER)
    status = str(getattr(row, "status", PENDING) or PENDING)
    reason = str(getattr(row, "fail_reason", "") or "")
    heavy = status == FAILED and ("large" in reason or "heavy" in reason)
    video = kind == VIDEO
    return SeasonalItemVM(
        id=str(row.id),
        season_key=str(getattr(row, "season_key", "") or ""),
        season_label=label,
        kind=kind,
        kind_label=VIDEO_BADGE if video else STICKER_BADGE,
        is_video=video,
        status=status,
        preparing=status == PENDING,
        ready=status == READY,
        approved=status == APPROVED,
        failed=status == FAILED,
        heavy=heavy,
        # a refusal the backend words (`budget_cap` → «Esta pieza superaría tu tope de
        # gasto.»), else ours
        fail_text=(
            (reasons or {}).get(reason) or (HEAVY_TEXT if heavy else FAILED_TEXT)
            if status == FAILED
            else ""
        ),
        # the weight only once there is a file (never «0 KB» while it is prepared)
        size_label=kb_label(getattr(row, "bytes", None)) if status in (READY, APPROVED) else "",
        src=src if status in (READY, APPROVED) else "",
        alt=item_alt(
            VIDEO_BADGE if video else STICKER_BADGE, label, str(getattr(row, "recipe", ""))
        ),
        # made with IA: «Pedir otro» is another paid call (asks first)
        paid=str(getattr(row, "recipe", "")).startswith("ai-")
        or Decimal(str(getattr(row, "cost_usd", 0) or 0)) > 0,
    )


@dataclass(frozen=True)
class SeasonVM:
    key: str = ""
    label: str = ""
    archived: bool = False
    counts_label: str = ""  # «6 stickers, 4 videos» (approved, for the library)
    progress_label: str = ""  # «Navidad 2026 · 3 de 10 listos» (for Por aprobar)
    progress: int = 0  # 0–100
    preparing: bool = False
    all_failed: bool = False
    ready_count: int = 0
    ready_ids: list[str] = field(default_factory=list)
    pieces: list[SeasonalItemVM] = field(default_factory=list)
    #: Something here waits for the owner (Por aprobar shows the group).
    to_review: bool = False
    #: m-24986801: what «Por aprobar» shows (being prepared, ready, failed — never the
    #: approved ones) and what «Aprobados» shows.
    pending_pieces: list[SeasonalItemVM] = field(default_factory=list)
    approved_pieces: list[SeasonalItemVM] = field(default_factory=list)
    #: «Navidad 2026 · 3 de 4 listos para aprobar» — counted over what Por aprobar shows
    #: (the approved ones left), with its bar (0–100, what is no longer being prepared).
    pending_progress_label: str = ""
    pending_progress: int = 0


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def counts_label(items: Sequence[SeasonalItemVM]) -> str:
    stickers = sum(1 for i in items if i.approved and not i.is_video)
    videos = sum(1 for i in items if i.approved and i.is_video)
    if not stickers and not videos:
        return "Nada aprobado todavía"
    parts = []
    if stickers:
        parts.append(_plural(stickers, "sticker", "stickers"))
    if videos:
        parts.append(_plural(videos, "video", "videos"))
    return ", ".join(parts)


def build_season(
    key: str,
    label: str,
    archived: bool,
    rows: Iterable[Any],
    src_for: Any = None,
    reasons: Mapping[str, str] | None = None,
) -> SeasonVM:
    """One season: its live items (rejected ones are gone — «Pedir otro» replaced them)."""
    items = [
        _row(r, label, src_for(r) if src_for else "", reasons)
        for r in rows
        if str(getattr(r, "status", "")) not in (REJECTED, ARCHIVED)
    ]
    done = [i for i in items if not i.preparing]
    finished = sum(1 for i in items if i.ready or i.approved)
    total = len(items)
    ready = [i.id for i in items if i.ready]
    return SeasonVM(
        key=key,
        label=label,
        archived=archived,
        counts_label=counts_label(items),
        progress_label=f"{label} · {finished} de {total} listos" if total else label,
        progress=round(100 * len(done) / total) if total else 0,
        preparing=any(i.preparing for i in items),
        all_failed=bool(items) and all(i.failed for i in items),
        ready_count=len(ready),
        ready_ids=ready,
        pieces=items,
        to_review=any(i.preparing or i.ready or i.failed for i in items),
        pending_pieces=(pending := [i for i in items if i.preparing or i.ready or i.failed]),
        approved_pieces=[i for i in items if i.approved],
        pending_progress_label=pending_progress_label(label, pending),
        pending_progress=(
            round(100 * sum(1 for i in pending if not i.preparing) / len(pending)) if pending else 0
        ),
    )


def pending_progress_label(label: str, pending: Sequence[SeasonalItemVM]) -> str:
    """«Navidad 2026 · 3 de 4 listos para aprobar» — only what waits in Por aprobar."""
    if not pending:
        return label
    ready = sum(1 for i in pending if i.ready)
    noun = "listo" if len(pending) == 1 else "listos"
    return f"{label} · {ready} de {len(pending)} {noun} para aprobar"


def kind_matches(item: SeasonalItemVM, kind: str) -> bool:
    """«Aprobados»' type filter: «Todos» · «Stickers» · «Videos» (`&tipo=sticker|video`)."""
    return kind not in (STICKER, VIDEO) or item.kind == kind


def approved_seasons(
    seasons: Sequence[SeasonVM], kind: str = KIND_ALL, current_key: str = ""
) -> list[SeasonVM]:
    """«Aprobados» › Stickers y videos: the live seasons (the coming one first) with
    their approved pieces of `kind`; a season with none of them is left out."""
    shown = []
    for season in order_seasons(seasons, current_key):
        if season.archived:
            continue
        pieces = [i for i in season.approved_pieces if kind_matches(i, kind)]
        if pieces:
            shown.append(replace(season, approved_pieces=pieces, counts_label=counts_label(pieces)))
    return shown


def pending_count(seasons: Sequence[SeasonVM]) -> int:
    """How many stickers and videos wait for the owner (live seasons)."""
    return sum(len(s.pending_pieces) for s in seasons if not s.archived)


def approved_count(seasons: Sequence[SeasonVM]) -> int:
    """How many approved stickers and videos are in use (live seasons)."""
    return sum(len(s.approved_pieces) for s in seasons if not s.archived)


def approve_ready_question(count: int, label: str) -> str:
    what = "sticker o video" if count == 1 else "stickers y videos"
    return f"Vas a aprobar {count} {what} de «{label}». Desde ahí los puedes mandar en tus chats."


def approve_ready_button(count: int) -> str:
    return f"{APPROVE_READY_LABEL} ({count})" if count else APPROVE_READY_LABEL


def archived_toast(label: str) -> str:
    return f"Listo: «{label}» ya no aparece en tus chats."


def archived_here_toast(label: str) -> str:
    """«Archivar» in «Aprobados»: where the season went (m-24986801, UX review)."""
    return f"{label} archivada: la encuentras abajo en Archivadas."


def restored_toast(label: str) -> str:
    return f"Listo: «{label}» vuelve a aparecer en tus chats."


def order_seasons(seasons: Sequence[SeasonVM], current_key: str = "") -> list[SeasonVM]:
    """Live seasons with the current one first (then as given: newest first), archived
    last."""
    live = [s for s in seasons if not s.archived]
    live.sort(key=lambda s: 0 if s.key == current_key else 1)
    return live + [s for s in seasons if s.archived]


@dataclass(frozen=True)
class AiPhotoVM:
    """One approved photo piece the IA will animate (shown before paying)."""

    id: str = ""
    title: str = ""
    src: str = ""  # `/r2media/…` path, or "" (the card shows its icon)
