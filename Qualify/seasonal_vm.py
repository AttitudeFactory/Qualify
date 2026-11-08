"""Stickers y videos de tu marca (m-24976895, spec `docs/ux-stickers-videos.md`) — the
words and pure rules of the season library, the three-step «Crear para esta temporada»
flow and the «Por aprobar» batch. No I/O here: the state hands in plain rows from
`seasonal_provider` (the backend's `SeasonalMediaService`) and gets frozen view models.

Founder's rules (2026-11-08): every batch passes «Por aprobar»; nothing unapproved
reaches a chat; seasons keep their previous batches; «Crear con IA» only makes videos
and always shows its estimated cost (from the pricing table, never written by hand)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
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
    "La IA anima una foto tuya para que se mueva sola. Tiene costo y solo hace videos: "
    "no puede dejar el fondo transparente que necesita un sticker."
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
# What the owner can pick in step 1: the next dated occasions of the business's country
# (the backend keeps no calendar yet; this one is the spec's and lives here until it does).


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
        ("halloween", "Halloween", date(year, 10, 31)),
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


def occasion_choices(today: date, country: str) -> list[OccasionVM]:
    """Step 1's cards: the next season (preselected), the one after, «Todo el año», and
    «Otra ocasión» (named by the owner)."""
    return [
        *upcoming_occasions(today, country),
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


def ai_create_button(cost: str) -> str:
    return f"Crear el video · unos {cost}" if cost else CREATE_BUTTON


def another_ai_question(cost: str) -> str:
    return f"Pedir otro cuesta unos {cost}. ¿Lo creamos?" if cost else "¿Lo creamos de nuevo?"


#: What a free batch prepares (the recipes' default plan; the backend decides the real
#: set and the progress counts what came back).
FREE_STICKERS: Final = 6
FREE_VIDEOS: Final = 4


def review_text(label: str, mode: str) -> str:
    if mode == MODE_AI:
        return (
            f"Vamos a animar una foto tuya en un video para «{label}». Llega a Por aprobar "
            "en unos minutos. Nada se manda sin que lo apruebes."
        )
    return (
        f"Vamos a preparar {FREE_STICKERS} stickers y {FREE_VIDEOS} videos para «{label}». "
        "Llegan a Por aprobar en unos minutos. Nada se manda sin que lo apruebes."
    )


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


def _row(row: Any, label: str, src: str) -> SeasonalItemVM:
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
        fail_text=(HEAVY_TEXT if heavy else FAILED_TEXT) if status == FAILED else "",
        size_label=kb_label(getattr(row, "bytes", None)),
        src=src if status in (READY, APPROVED) else "",
        alt=f"{VIDEO_BADGE if video else STICKER_BADGE} de «{label}»",
        paid=Decimal(str(getattr(row, "cost_usd", 0) or 0)) > 0,
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
    items: list[SeasonalItemVM] = field(default_factory=list)
    #: Something here waits for the owner (Por aprobar shows the group).
    to_review: bool = False


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
    key: str, label: str, archived: bool, rows: Iterable[Any], src_for: Any = None
) -> SeasonVM:
    """One season: its live items (rejected ones are gone — «Pedir otro» replaced them)."""
    items = [
        _row(r, label, src_for(r) if src_for else "")
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
        items=items,
        to_review=any(i.preparing or i.ready or i.failed for i in items),
    )


def approve_ready_question(count: int, label: str) -> str:
    what = "sticker o video" if count == 1 else "stickers y videos"
    return f"Vas a aprobar {count} {what} de «{label}». Desde ahí los puedes mandar en tus chats."


def approve_ready_button(count: int) -> str:
    return f"{APPROVE_READY_LABEL} ({count})" if count else APPROVE_READY_LABEL


def archived_toast(label: str) -> str:
    return f"Listo: «{label}» ya no aparece en tus chats."


def restored_toast(label: str) -> str:
    return f"Listo: «{label}» vuelve a aparecer en tus chats."


def order_seasons(seasons: Sequence[SeasonVM], current_key: str = "") -> list[SeasonVM]:
    """Live seasons with the current one first (then as given: newest first), archived
    last."""
    live = [s for s in seasons if not s.archived]
    live.sort(key=lambda s: 0 if s.key == current_key else 1)
    return live + [s for s in seasons if s.archived]
