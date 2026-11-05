"""Creadores' view models (Delivery 1, m-24946129 and m-24946132; epic m-24880379) —
pure, tested in `test_creators_vm.py`.

The screens (`docs/ux-creadores.md` §1-3) read the backend facade
`qualify_api.creators.service` (`docs/diseno-modulo-creadores.md` §10) through
`creators_provider`, and everything they show is shaped here, already as text:

- every figure in the es-CO/VE/UY format («8.300», «12,4 mil», «1,2 millones», «4,1 %»);
- **«Sin dato», never 0**, for a metric whose status is not ``ok`` (founder rule);
- the freshness in words («Datos de hoy», «Datos de hace 9 días») with the backend's
  own ``stale`` flag (``STALE_DAYS`` of `metrics.py`), never a threshold of our own;
- in Comparar, which cells are «Mejor» comes from the server (``ComparisonRow.best``,
  ties included); there is no summed score and no overall winner;
- the outcome of the one paid call (``refresh_creator``) as the owner's sentence and a
  tone — never credits, money, a vendor or a code.

The backend objects are read by attribute (duck typing), so this module imports nothing
from `qualify_api` and stays importable while the backend is being written.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

# --- routes (N5: every place has its address; ids are internal, never a handle) ------

CREATORS_ROUTE = "/creadores"
COMPARE_ROUTE = "/creadores/comparar"
FLOW_PARAM = "flujo"
FLOW_ADD = "agregar"
#: `/creadores?comparar=<id>[,<id>…]` — the list in «elige de 2 a 4» mode with those
#: already marked (N4: «Compararlo con otro creador» comes back with this one chosen).
PICK_PARAM = "comparar"
IDS_PARAM = "ids"
RESULTS_URL = "/resultados"

COMPARE_MIN = 2
COMPARE_MAX = 4
#: More than this many creators and the list gets a search box (UX §2.1).
SEARCH_FROM = 8
#: A creator whose window has fewer measurable reels than this gets «Solo N reels en
#: este tiempo» under its name in Comparar (UX §3.1).
FEW_IN_WINDOW = 6
#: 1-5 measurable reels: the sheet says the figures still say little (UX §2.2).
FEW_REELS = 5
#: How many standout reels the sheet shows before «Ver los N».
STANDOUT_VISIBLE = 3

# --- copy (docs/ux-creadores.md, final Spanish) ----------------------------------------

TITLE = "Creadores"
SUBTITLE = "Mira cuánta gente ve de verdad a un creador antes de darle producto o pagarle"
EMPTY_TITLE = "Todavía no revisaste a ningún creador"
EMPTY_BODY = (
    "Escribe su usuario de Instagram y en unos segundos ves cuántas personas ven sus "
    "reels, qué le funciona y con qué marcas trabajó."
)
EMPTY_HELP = "¿No sabes a quién? Empieza por alguien que ya recomendó un negocio de tu ciudad."
REVIEW_ONE = "Revisar un creador"
REVIEW_ANOTHER = "Revisar otro creador"
COMPARE_ENTER = "Comparar creadores"
PICK_HEAD = "Elige de 2 a 4"
PICK_LIMIT = "Puedes comparar hasta 4. Quita uno para elegir otro."
SEARCH_LABEL = "Buscar por nombre o usuario"
WORKING_ROW = "Revisando sus reels…"

DRAWER_TITLE = "Revisar un creador"
DRAWER_DESCRIPTION = "Te mostramos cuánta gente ve sus reels de verdad."
FIELD_LABEL = "Usuario de Instagram"
FIELD_PLACEHOLDER = "ej.: comeconmaria"
FIELD_HELP = "Está arriba en su perfil. También puedes pegar el enlace de su perfil."
DRAWER_SUBMIT = "Ver cómo le va"
DRAWER_EMPTY_REASON = "Escribe su usuario para seguir."
PROGRESS_DETAIL = "Tarda unos segundos. Si cierras esto, sigue en tu lista y te avisamos."
PROGRESS_STEPS: tuple[str, ...] = (
    "Buscando su perfil",
    "Leyendo sus últimos 48 reels",
    "Sacando sus números",
)
REVIEW_OTHER_ACCOUNT = "Revisar otra cuenta"
SEE_RESULTS = "Ver sus resultados"
UPDATE = "Actualizar"
UPDATING = "Actualizando…"
TRY_AGAIN = "Intentar de nuevo"
GO_RESULTS = "Ir a Resultados"

BACK_TO_LIST = "Creadores"
OPEN_INSTAGRAM = "Ver en Instagram"
COMPARE_WITH_OTHER = "Compararlo con otro creador"
ARCHIVE = "Quitar de tu lista"
ARCHIVE_CONFIRM = "Quitar"
CANCEL = "Cancelar"

SHEET_TOP = "Sus reels con más vistas"
SHEET_STANDOUT = "Reels que se salieron de lo normal"
SHEET_WORKS = "Lo que mejor le funciona"
SHEET_COLLABS = "Colaboraciones con marcas"
YOUNG_REEL = "Todavía sumando vistas"

COMPARE_TITLE = "Comparar creadores"
COMPARE_ADD = "Agregar otro a la comparación"
COMPARE_INVALID = "Elige de 2 a 4 creadores para comparar."
COMPARE_PREV = "Anteriores"
COMPARE_NEXT = "Siguientes"
BEST = "Mejor"
MISSING = "Sin dato"
MISSING_HINT = "Instagram no lo muestra para esta cuenta"
LOAD_FAILED = "No pudimos cargar tus creadores. Vuelve a intentarlo en un momento."
SHEET_LOAD_FAILED = "No pudimos cargar sus resultados. Vuelve a intentarlo en un momento."
SHEET_GONE = "Este creador ya no está en tu lista."
COMPARE_LOAD_FAILED = "No pudimos cargar la comparación. Vuelve a intentarlo en un momento."
NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
INVALID_HANDLE = (
    "Eso no parece un usuario de Instagram. Escríbelo como aparece en su perfil "
    "(letras, números, puntos o guiones bajos) o pega el enlace de su perfil."
)
ONLY_INSTAGRAM = "Por ahora solo podemos revisar cuentas de Instagram."
ADD_FAILED = "No pudimos agregarlo a tu lista. Vuelve a intentarlo en un momento."
ARCHIVE_FAILED = "No pudimos quitarlo de tu lista. Vuelve a intentarlo en un momento."

_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

# --- numbers ----------------------------------------------------------------------------


def _decimal(value: float, places: int) -> str:
    """``value`` with ``places`` decimals, comma as the decimal mark, «,0» dropped."""
    text = f"{value:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    whole, _, frac = text.partition(".")
    whole = f"{int(whole):,}".replace(",", ".") if whole.lstrip("-").isdigit() else whole
    return f"{whole},{frac}" if frac else whole


def format_count(value: float | int | None) -> str:
    """A count in the owner's format: «8.300» up to 9.999, «12,4 mil» up to a million,
    «1,2 millones» from there. None → «Sin dato» (never 0)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return MISSING
    n = round(float(value))
    if abs(n) < 10_000:
        return f"{n:,}".replace(",", ".")
    thousands = round(n / 1000, 1)
    if abs(thousands) < 1000:
        return f"{_decimal(thousands, 1)} mil"
    millions = round(n / 1_000_000, 1)
    return "1 millón" if millions == 1 else f"{_decimal(millions, 1)} millones"


def format_percent(ratio: float | None, places: int = 1) -> str:
    """A ratio (0.041) as «4,1 %» — a space before %, comma decimal."""
    if ratio is None or math.isnan(ratio):
        return MISSING
    return f"{_decimal(ratio * 100, places)} %"


def format_date(day: date | datetime | None) -> str:
    """«2 de agosto»; «2 de agosto de 2025» when not this year is irrelevant here (the
    windows are at most 90 days), so the year is never written."""
    if day is None:
        return ""
    return f"{day.day} de {_MONTHS[day.month - 1]}"


def _local_date(moment: datetime, zone: tzinfo | None) -> date:
    if zone is not None and moment.tzinfo is not None:
        return moment.astimezone(zone).date()
    return moment.date()


def days_between(earlier: datetime, now: datetime, zone: tzinfo | None = None) -> int:
    """Whole calendar days from ``earlier`` to ``now`` in the business's zone (≥ 0)."""
    return max((_local_date(now, zone) - _local_date(earlier, zone)).days, 0)


def freshness_text(days: int) -> str:
    """The same words in the list, the sheet and Comparar (UX §2.1)."""
    if days <= 0:
        return "Datos de hoy"
    if days == 1:
        return "Datos de ayer"
    return f"Datos de hace {days} días"


def ago_text(days: int) -> str:
    """«hoy», «ayer», «hace 12 días», «hace 1 mes», «hace 3 meses»."""
    if days <= 0:
        return "hoy"
    if days == 1:
        return "ayer"
    if days < 30:
        return f"hace {days} días"
    months = days // 30
    return "hace 1 mes" if months == 1 else f"hace {months} meses"


# --- handles ----------------------------------------------------------------------------

_HANDLE_IN_URL = re.compile(r"instagram\.com/(?!p/|reel/|reels/|stories/)([A-Za-z0-9._]+)")


def display_handle(raw: str) -> str:
    """Best-effort «@usuario» from what the owner typed, ONLY to echo it in a message
    before the backend answers. The real normalization is `add_creator`'s."""
    text = (raw or "").strip()
    found = _HANDLE_IN_URL.search(text)
    if found:
        text = found.group(1)
    text = text.split("?")[0].strip("/ ").lstrip("@").lower()
    return f"@{text}" if text else ""


def at(handle: str) -> str:
    handle = (handle or "").lstrip("@")
    return f"@{handle}" if handle else ""


def initials(name: str) -> str:
    """Up to two letters for the avatar's fallback (the CDN picture expires)."""
    words = [w for w in re.split(r"[\s._@]+", name or "") if w]
    letters = "".join(w[0] for w in words[:2]).upper()
    return letters or "?"


def instagram_url(handle: str) -> str:
    return f"https://www.instagram.com/{(handle or '').lstrip('@')}/"


# --- metric values ----------------------------------------------------------------------


def _ok(metric: Any) -> bool:
    return (
        metric is not None
        and getattr(metric, "status", "") == "ok"
        and (getattr(metric, "value", None) is not None)
    )


#: key → (label, visible hint, «¿Cómo lo contamos?»). Same names in list, sheet and
#: Comparar (N1 applied to figures). From docs/ux-creadores.md §2.3.
METRIC_TEXT: dict[str, tuple[str, str, str]] = {
    "followers": (
        "Seguidores",
        "",
        "Cuántas personas siguen su cuenta hoy. Es fácil de inflar: mira también las "
        "vistas típicas.",
    ),
    "median_views": (
        "Vistas típicas por reel",
        "Lo que suele ver un reel suyo",
        "Ordenamos sus reels por vistas y tomamos el del medio. Así un reel que se volvió "
        "muy famoso no infla el número.",
    ),
    "views_per_follower": (
        "Vistas frente a seguidores",
        "Más de 100 % quiere decir que llega a gente que no lo sigue",
        "Dividimos sus vistas típicas entre sus seguidores. 67 % es que un reel típico lo "
        "ven tantas personas como 67 de cada 100 seguidores.",
    ),
    "engagement_rate": (
        "Interacción",
        "De cada 100 que lo ven, cuántos dan me gusta o comentan",
        "En cada reel sumamos los me gusta y los comentarios y los dividimos entre sus "
        "vistas. Mostramos el valor del medio, así un solo reel no lo cambia todo.",
    ),
    "standout_share": (
        "Reels que se salieron de lo normal",
        "Tuvieron más del doble de sus vistas típicas",
        "Un reel se sale de lo normal cuando tiene por lo menos el doble de las vistas que "
        "suele tener.",
    ),
    "reels_per_week": (
        "Reels por semana",
        "",
        "Miramos cuántos días pasan entre un reel y el siguiente y lo pasamos a semanas.",
    ),
    "best_duration": (
        "Duración que mejor le funciona",
        "",
        "Agrupamos sus reels por duración y comparamos las vistas típicas de cada grupo.",
    ),
    "paid_partnerships": (
        "Colaboraciones pagadas",
        "",
        "Reels que Instagram marca como «colaboración pagada».",
    ),
}

#: The figure's order in Comparar: first the rows that carry «Mejor» (UX §3.1).
COMPARE_ORDER: tuple[str, ...] = (
    "median_views",
    "views_per_follower",
    "engagement_rate",
    "standout_share",
    "followers",
    "reels_per_week",
    "best_duration",
    "paid_partnerships",
)

#: The duration buckets of `cm-1` (§9.2), for a `best_duration` that comes as an index.
DURATION_BUCKETS: tuple[str, ...] = ("≤15 s", "16–30 s", "31–60 s", "61–90 s", ">90 s")


def duration_text(label: str) -> str:
    """A bucket label in words: «≤15 s» → «hasta 15 s», «>90 s» → «más de 90 s»,
    «16–30 s» → «de 16 a 30 s»."""
    label = (label or "").strip()
    if not label:
        return MISSING
    if label.startswith("≤"):
        return f"hasta {label[1:].strip()}"
    if label.startswith(">"):
        return f"más de {label[1:].strip()}"
    low, sep, high = label.partition("–")
    if sep:
        return f"de {low.strip()} a {high.strip()}"
    return label


def reels_per_week_text(value: float | None) -> str:
    """«unos 3», «1», «menos de 1» — a pace, never false precision."""
    if value is None:
        return MISSING
    if value < 0.75:
        return "menos de 1"
    n = round(value)
    return str(n) if abs(value - n) < 0.15 else f"unos {n}"


def metric_text(key: str, metric: Any) -> str:
    """One MetricValue as the text of its cell. Anything not ``ok`` → «Sin dato»."""
    if key == "paid_partnerships":
        # «0 se muestra como «ninguna declarada»» (design §9.2): a real zero.
        if metric is None or getattr(metric, "value", None) is None:
            return MISSING
        count = round(metric.value)
        sample = getattr(metric, "sample", 0) or 0
        if count == 0:
            return "Ninguna declarada"
        return f"{count} de {sample}" if sample else str(count)
    if not _ok(metric):
        return MISSING
    value = float(metric.value)
    if key in ("followers", "median_views", "mean_views"):
        return format_count(value)
    if key == "views_per_follower":
        return format_percent(value, 0)
    if key == "engagement_rate":
        return format_percent(value, 1)
    if key == "reels_per_week":
        return reels_per_week_text(value)
    if key == "standout_share":
        sample = getattr(metric, "sample", 0) or 0
        if sample:
            return f"{round(value * sample)} de {sample}"
        return format_percent(value, 0)
    if key == "best_duration":
        note = getattr(metric, "note", "") or ""
        if note and not note.isidentifier():
            return duration_text(note)
        index = int(value)
        if 0 <= index < len(DURATION_BUCKETS):
            return duration_text(DURATION_BUCKETS[index])
        return MISSING
    return format_count(value)


# --- the one paid call: what its outcome means to the owner --------------------------


@dataclass(frozen=True)
class OutcomeVM:
    """What a refresh ended in, for the screen: ``done`` means the sheet can be shown;
    otherwise ``message`` goes in a callout of ``tone``. ``drop_new`` asks the drawer to
    take a just-added row back off the list (a typo or a private account is not a
    creator the owner wants to keep)."""

    done: bool
    tone: str = "info"
    message: str = ""
    action: str = ""
    drop_new: bool = False


def refresh_outcome_vm(status: str, handle: str) -> OutcomeVM:
    """`RefreshOutcome.status` (design §10.3) → the owner's sentence (UX §2.2). Never
    credits, money, a vendor or a code."""
    who = at(handle)
    if status in ("read", "fresh"):
        return OutcomeVM(done=True)
    if status == "missing":
        return OutcomeVM(
            done=False,
            tone="error",
            message=(
                f"No encontramos a {who} en Instagram. Revisa que esté bien escrito o pega "
                "el enlace de su perfil."
            ),
            drop_new=True,
        )
    if status == "private":
        return OutcomeVM(
            done=False,
            tone="warn",
            message=(
                f"La cuenta de {who} es privada: solo sus seguidores ven sus reels, así que "
                "no podemos contarlos. Prueba con otra cuenta o pídele sus números "
                "directamente."
            ),
            action=REVIEW_OTHER_ACCOUNT,
            drop_new=True,
        )
    if status == "busy":
        return OutcomeVM(
            done=False,
            tone="info",
            message=f"Ya estamos leyendo a {who}. Vuelve a intentarlo en unos segundos.",
            action=TRY_AGAIN,
        )
    if status == "cap_reached":
        return OutcomeVM(
            done=False,
            tone="warn",
            message=(
                "Por hoy ya revisaste todos los creadores que incluye tu plan. Mañana puedes "
                "actualizar otra vez."
            ),
        )
    if status == "blocked":
        return OutcomeVM(
            done=False,
            tone="error",
            message="Ahora no pudimos actualizar. Inténtalo de nuevo en unos minutos.",
            action=TRY_AGAIN,
        )
    return OutcomeVM(
        done=False,
        tone="error",
        message="No pudimos leer Instagram en este momento. Inténtalo de nuevo en unos minutos.",
        action=TRY_AGAIN,
    )


# --- the list -----------------------------------------------------------------------


@dataclass(frozen=True)
class CreatorCardVM:
    """One row of «Tus creadores». ``state``: ``ready`` (a card that opens the sheet),
    ``working`` (being read now), ``failed`` (never read, last try failed — a compact
    callout with «Intentar de nuevo»), ``pending`` (never read, nothing running)."""

    tracked_id: str
    href: str
    handle: str
    name: str
    avatar_url: str
    initials: str
    followers: str
    median_views: str
    freshness: str
    stale: bool
    state: str
    problem: str = ""
    problem_tone: str = "error"
    search_text: str = ""
    days: int = -1


def build_card_vm(
    card: Any, *, now: datetime, zone: tzinfo | None = None, working: bool = False
) -> CreatorCardVM:
    tracked = card.tracked
    handle = at(tracked.handle)
    name = (card.full_name or "").strip() or handle
    read_at = card.read_at
    days = days_between(read_at, now, zone) if read_at is not None else -1
    refresh_state = getattr(tracked, "refresh_state", "") or ""
    if working or refresh_state == "reading":
        state = "working"
    elif read_at is not None:
        state = "ready"
    elif refresh_state == "failed":
        state = "failed"
    else:
        state = "pending"
    problem, tone = "", "error"
    if state == "failed":
        outcome = refresh_outcome_vm(tracked.refresh_error or "error", tracked.handle)
        problem, tone = outcome.message, outcome.tone
    elif state == "pending":
        problem, tone = f"Todavía no revisamos a {handle}.", "info"
    return CreatorCardVM(
        tracked_id=str(tracked.id),
        href=sheet_url(tracked.id),
        handle=handle,
        name=name,
        avatar_url=card.avatar_url or "",
        initials=initials(name),
        followers=(
            f"{format_count(card.followers)} seguidores"
            if card.followers is not None
            else "Seguidores: sin dato"
        ),
        median_views=(
            f"{metric_text('median_views', card.median_views)} vistas típicas por reel"
            if _ok(card.median_views)
            else "Vistas típicas por reel: sin dato"
        ),
        freshness=freshness_text(days) if days >= 0 else "",
        stale=bool(card.stale) and read_at is not None,
        state=state,
        problem=problem,
        problem_tone=tone,
        search_text=f"{name} {handle}".lower(),
        days=days,
    )


def filter_cards(cards: Sequence[CreatorCardVM], query: str) -> list[CreatorCardVM]:
    needle = (query or "").strip().lstrip("@").lower()
    if not needle:
        return list(cards)
    return [card for card in cards if needle in card.search_text]


def sheet_url(tracked_id: UUID | str) -> str:
    return f"{CREATORS_ROUTE}/{tracked_id}"


def compare_url(ids: Iterable[str]) -> str:
    return f"{COMPARE_ROUTE}?{urlencode({IDS_PARAM: ','.join(ids)})}"


def pick_url(ids: Iterable[str]) -> str:
    """The list in «elige de 2 a 4» mode with ``ids`` already marked."""
    joined = ",".join(ids)
    return f"{CREATORS_ROUTE}?{urlencode({PICK_PARAM: joined})}" if joined else CREATORS_ROUTE


def parse_ids(raw: object, limit: int = COMPARE_MAX + 1) -> list[str]:
    """`?ids=a,b,c` → canonical UUID strings, in order, without duplicates. Anything
    that is not a UUID is dropped (the URL is never echoed). At most ``limit`` kept,
    so «more than 4» is still detectable."""
    if not isinstance(raw, str):
        return []
    seen: list[str] = []
    for part in raw.split(","):
        try:
            value = str(UUID(part.strip()))
        except (ValueError, AttributeError):
            continue
        if value not in seen:
            seen.append(value)
        if len(seen) >= limit:
            break
    return seen


def pick_reason(count: int) -> str:
    """Why «Comparar» is not available yet, read next to the button (§5.8)."""
    if count < COMPARE_MIN:
        missing = COMPARE_MIN - count
        return "Elige al menos uno más" if missing == 1 else "Elige al menos 2 más"
    return ""


def pick_button(count: int) -> str:
    return f"Comparar {count} creadores" if count >= COMPARE_MIN else "Comparar creadores"


def existing_notice(handle: str, days: int) -> str:
    """«Ya está en tu lista» (UX §2.2)."""
    return f"Ya revisaste a {at(handle)} {ago_text(days)}."


def archived_notice(handle: str) -> str:
    return f"Quitaste a {at(handle)} de tu lista."


# --- the sheet ----------------------------------------------------------------------


@dataclass(frozen=True)
class StatVM:
    key: str
    label: str
    value: str
    hint: str
    help: str
    missing: bool


@dataclass(frozen=True)
class ReelVM:
    url: str
    views: str
    when: str
    lift: str
    young: bool
    label: str  # the link's spoken name


@dataclass(frozen=True)
class TagVM:
    label: str


@dataclass(frozen=True)
class SheetVM:
    tracked_id: str
    handle: str
    title: str
    avatar_url: str
    initials: str
    profile_url: str
    verified: bool
    freshness: str
    stale: bool
    stale_message: str
    status_message: str
    status_tone: str
    stats: list[StatVM] = field(default_factory=list)
    cadence: str = ""
    top_reels: list[ReelVM] = field(default_factory=list)
    standout_sentence: str = ""
    standout_reels: list[ReelVM] = field(default_factory=list)
    standout_more: list[ReelVM] = field(default_factory=list)
    duration_sentence: str = ""
    audios: list[TagVM] = field(default_factory=list)
    collab_sentence: str = ""
    coauthor_sentence: str = ""
    collaborators: list[TagVM] = field(default_factory=list)
    trust: str = ""
    few_reels: str = ""
    hidden_note: str = ""
    no_reels: str = ""


def _stat(key: str, metric: Any, *, value: str | None = None) -> StatVM:
    label, hint, help_text = METRIC_TEXT[key]
    text = value if value is not None else metric_text(key, metric)
    missing = text == MISSING
    return StatVM(
        key=key,
        label=label,
        value=text,
        hint=MISSING_HINT if missing else hint,
        help=help_text,
        missing=missing,
    )


def _reel_vm(reel: Any, now: datetime, zone: tzinfo | None, *, show_lift: bool) -> ReelVM:
    views = f"{format_count(reel.views)} vistas" if reel.views is not None else "Vistas: sin dato"
    when = ago_text(days_between(reel.taken_at, now, zone)) if reel.taken_at else ""
    lift = ""
    if show_lift and reel.lift is not None and reel.lift >= 1:
        lift = f"{round(reel.lift)} veces lo normal"
    head = lift or views
    return ReelVM(
        url=reel.url,
        views=views,
        when=when,
        lift=lift,
        young=bool(reel.is_young),
        label=f"Ver en Instagram el reel de {head}, {when}".rstrip(", "),
    )


def build_sheet_vm(sheet: Any, *, now: datetime, zone: tzinfo | None = None) -> SheetVM:
    """A `CreatorSheet` (design §10.3) as the screen's text."""
    handle = at(sheet.handle)
    days = days_between(sheet.read_at, now, zone)
    total = sheet.reels_read
    measurable = sheet.measurable_reels

    status_message, status_tone = "", "info"
    if sheet.snapshot_status in ("private", "missing", "error"):
        outcome = refresh_outcome_vm(sheet.snapshot_status, sheet.handle)
        status_message, status_tone = outcome.message, outcome.tone
    elif sheet.snapshot_status == "partial":
        status_message = "No pudimos leer todos sus reels: los números salen de los que sí leímos."

    stats = [
        _stat("median_views", sheet.median_views),
        _stat("engagement_rate", sheet.engagement_rate),
        _stat("followers", sheet.followers),
        _stat("views_per_follower", sheet.views_per_follower),
    ]
    cadence = ""
    if _ok(sheet.reels_per_week):
        pace = reels_per_week_text(float(sheet.reels_per_week.value))
        if pace == "menos de 1":
            cadence = "Publica menos de un reel por semana."
        elif pace == "1":
            cadence = "Publica 1 reel por semana."
        else:
            cadence = f"Publica {pace} reels por semana."

    standout = list(sheet.standout_reels)
    standout_vms = [_reel_vm(r, now, zone, show_lift=True) for r in standout]
    if not _ok(sheet.standout_share):
        standout_sentence = (
            "Con tan pocos reels todavía no podemos decir cuáles se salieron de lo normal."
        )
    elif not standout:
        standout_sentence = (
            f"Ninguno de sus últimos {measurable} reels se salió de lo normal: sus vistas "
            "son parejas."
        )
    else:
        standout_sentence = (
            f"{len(standout)} de sus últimos {measurable} reels tuvieron más del doble de sus "
            "vistas típicas."
        )

    best = sheet.best_duration
    if best is not None and _ok(getattr(best, "median_views", None)):
        duration_sentence = (
            f"Duración: sus reels {duration_text(best.label)} tienen más vistas "
            f"({format_count(best.median_views.value)} típicas)."
        )
    elif len(sheet.duration_buckets) >= 2:
        duration_sentence = "Sus reels largos y cortos tienen vistas parecidas."
    else:
        duration_sentence = ""

    paid = sheet.paid_partnerships
    if paid > 0:
        collab_sentence = f"{paid} de sus últimos {total} reels son colaboraciones pagadas."
    else:
        collab_sentence = f"En sus últimos {total} reels no declaró colaboraciones pagadas."
    coauthor_sentence = ""
    if sheet.collabs > 0:
        coauthor_sentence = (
            "Publicó 1 reel junto con otra cuenta:"
            if sheet.collabs == 1
            else f"Publicó {sheet.collabs} reels junto con otras cuentas:"
        )

    trust = ""
    if total and sheet.covered_from and sheet.covered_to:
        trust = (
            f"Contamos sus últimos {total} reels, del {format_date(sheet.covered_from)} al "
            f"{format_date(sheet.covered_to)}."
        )
    elif total:
        trust = f"Contamos sus últimos {total} reels."

    few = ""
    if 0 < measurable <= FEW_REELS:
        few = f"Solo encontramos {measurable} reels. Con tan pocos, los números todavía dicen poco."
    hidden = ""
    if sheet.hidden_counts_reels:
        n = sheet.hidden_counts_reels
        hidden = (
            "1 reel tiene las vistas ocultas y no lo contamos."
            if n == 1
            else f"{n} reels tienen las vistas ocultas y no los contamos."
        )
    no_reels = ""
    if sheet.snapshot_status in ("ok", "partial") and total == 0:
        no_reels = f"{handle} todavía no tiene reels, así que no hay vistas que contar."

    return SheetVM(
        tracked_id=str(sheet.tracked_id),
        handle=handle,
        title=(sheet.full_name or "").strip() or handle,
        avatar_url=sheet.avatar_url or "",
        initials=initials((sheet.full_name or "").strip() or sheet.handle),
        profile_url=instagram_url(sheet.handle),
        verified=bool(sheet.is_verified),
        freshness=freshness_text(days),
        stale=bool(sheet.stale),
        stale_message=(
            f"Estos números son de hace {days} días. Actualízalos antes de decidir."
            if sheet.stale
            else ""
        ),
        status_message=status_message,
        status_tone=status_tone,
        stats=stats,
        cadence=cadence,
        top_reels=[_reel_vm(r, now, zone, show_lift=False) for r in sheet.top_reels],
        standout_sentence=standout_sentence,
        standout_reels=standout_vms[:STANDOUT_VISIBLE],
        standout_more=standout_vms[STANDOUT_VISIBLE:],
        duration_sentence=duration_sentence,
        audios=[
            TagVM(label=f"{'Audio original' if a.is_original else a.title} · {a.reels}")
            for a in sheet.top_audios
        ],
        collab_sentence=collab_sentence,
        coauthor_sentence=coauthor_sentence,
        collaborators=[TagVM(label=at(h)) for h in sheet.collaborators],
        trust=trust,
        few_reels=few,
        hidden_note=hidden,
        no_reels=no_reels,
    )


# --- Comparar ----------------------------------------------------------------------


@dataclass(frozen=True)
class CellVM:
    text: str
    best: bool
    missing: bool
    spoken: str  # «Interacción, @maria: 4,1 %, mejor de los 3»


@dataclass(frozen=True)
class RowVM:
    key: str
    label: str
    hint: str
    help: str
    cells: list[CellVM] = field(default_factory=list)


@dataclass(frozen=True)
class ColumnVM:
    tracked_id: str
    handle: str
    name: str
    avatar_url: str
    initials: str
    href: str
    freshness: str
    stale: bool
    few_note: str
    remove_href: str  # "" when removing would leave fewer than 2
    remove_label: str


@dataclass(frozen=True)
class MobileItemVM:
    label: str
    text: str
    best: bool
    missing: bool


@dataclass(frozen=True)
class MobileColumnVM:
    column: ColumnVM
    figures: list[MobileItemVM] = field(default_factory=list)


@dataclass(frozen=True)
class ComparisonVM:
    intro: str
    columns: list[ColumnVM] = field(default_factory=list)
    rows: list[RowVM] = field(default_factory=list)
    mobile: list[MobileColumnVM] = field(default_factory=list)
    pages: list[list[int]] = field(default_factory=list)
    stale_message: str = ""
    stale_ids: list[str] = field(default_factory=list)
    stale_button: str = ""
    short_window: str = ""
    add_href: str = ""


def mobile_pages(count: int) -> list[list[int]]:
    """Two columns per screen on a phone (UX §3.2). With an odd count the last screen
    shows the last one next to the FIRST, so a column is never alone."""
    if count < 2:
        return [list(range(count))] if count else []
    pages = [[i, i + 1] for i in range(0, count - 1, 2)]
    if count % 2:
        pages.append([count - 1, 0])
    return pages


def page_counter(page: int, pages: Sequence[Sequence[int]], total: int) -> str:
    """«1–2 de 3» — the visible columns in words, next to the buttons."""
    if not pages:
        return ""
    shown = pages[max(0, min(page, len(pages) - 1))]
    numbers = sorted(i + 1 for i in shown)
    if len(numbers) == 2 and numbers[1] == numbers[0] + 1:
        return f"{numbers[0]}–{numbers[1]} de {total}"
    return f"{' y '.join(str(n) for n in numbers)} de {total}"


def _join_handles(handles: Sequence[str]) -> str:
    if len(handles) <= 1:
        return "".join(handles)
    return f"{', '.join(handles[:-1])} y {handles[-1]}"


def build_comparison_vm(
    comparison: Any,
    *,
    now: datetime,
    names: dict[str, tuple[str, str]] | None = None,
    zone: tzinfo | None = None,
) -> ComparisonVM:
    """A `Comparison` (design §10.3, §9.3) as the table and the phone columns.
    ``names`` maps tracked id → (full name, avatar url) from the list, since the
    comparison itself carries only the handle."""
    names = names or {}
    creators = list(comparison.creators)
    ids = [str(c.tracked_id) for c in creators]
    total = len(creators)
    columns: list[ColumnVM] = []
    for creator in creators:
        tracked_id = str(creator.tracked_id)
        handle = at(creator.handle)
        full_name, avatar = names.get(tracked_id, ("", ""))
        days = days_between(creator.read_at, now, zone)
        others = [i for i in ids if i != tracked_id]
        few = creator.measurable_in_window
        columns.append(
            ColumnVM(
                tracked_id=tracked_id,
                handle=handle,
                name=(full_name or "").strip() or handle,
                avatar_url=avatar or "",
                initials=initials((full_name or "").strip() or handle),
                href=sheet_url(tracked_id),
                freshness=freshness_text(days),
                stale=bool(creator.stale),
                few_note=f"Solo {few} reels en este tiempo" if few < FEW_IN_WINDOW else "",
                remove_href=compare_url(others) if total > COMPARE_MIN else "",
                remove_label=f"Quitar a {handle} de la comparación",
            )
        )

    by_key = {row.key: row for row in comparison.rows}
    rows: list[RowVM] = []
    for key in [k for k in COMPARE_ORDER if k in by_key] + [
        row.key for row in comparison.rows if row.key not in COMPARE_ORDER
    ]:
        row = by_key[key]
        label, hint, help_text = METRIC_TEXT.get(key, (key, "", ""))
        best = set(row.best) if row.highlights else set()
        cells = []
        for index, metric in enumerate(row.values):
            text = metric_text(key, metric)
            is_best = index in best and text != MISSING
            spoken = f"{label}, {columns[index].handle}: {text}"
            if is_best:
                spoken += f", mejor de los {total}"
            cells.append(CellVM(text=text, best=is_best, missing=text == MISSING, spoken=spoken))
        rows.append(RowVM(key=key, label=label, hint=hint, help=help_text, cells=cells))

    mobile = [
        MobileColumnVM(
            column=column,
            figures=[
                MobileItemVM(
                    label=row.label,
                    text=row.cells[index].text,
                    best=row.cells[index].best,
                    missing=row.cells[index].missing,
                )
                for row in rows
            ],
        )
        for index, column in enumerate(columns)
    ]

    # Warnings (design §9.3): stale reads and reads far apart → one callout with the
    # button inside (UX §3.1); a short common window → its own sentence.
    codes = list(comparison.warnings)
    stale_ids = [code.split(":", 1)[1] for code in codes if code.startswith("stale:")]
    stale_cols = [c for c in columns if c.tracked_id in stale_ids]
    stale_message, stale_button = "", ""
    if len(stale_cols) == 1:
        col = stale_cols[0]
        days = days_between(
            next(c.read_at for c in creators if str(c.tracked_id) == col.tracked_id), now, zone
        )
        stale_message = (
            f"Los datos de {col.handle} son de hace {days} días. Actualízalos para comparar parejo."
        )
        stale_button = f"Actualizar {col.handle}"
    elif stale_cols:
        stale_message = (
            f"Los datos de {_join_handles([c.handle for c in stale_cols])} tienen más de una "
            "semana. Actualízalos para comparar parejo."
        )
        stale_button = f"Actualizar los {len(stale_cols)}"
    elif "reads_apart" in codes:
        oldest = min(creators, key=lambda c: c.read_at)
        stale_ids = [str(oldest.tracked_id)]
        stale_message = (
            "Sus datos son de días muy distintos. Actualiza el más viejo para comparar parejo."
        )
        stale_button = f"Actualizar {at(oldest.handle)}"

    short_window = ""
    window_from, window_to = comparison.window_from, comparison.window_to
    if "short_window" in codes and window_from and window_to:
        span = max((window_to - window_from).days, 1)
        short_window = f"Comparamos solo {span} días porque alguno de ellos publica poco."

    if window_from and window_to:
        intro = (
            f"Con los reels del {format_date(window_from)} al {format_date(window_to)}, las "
            "mismas fechas para todos. Marcamos el mejor de cada fila; tú decides qué pesa "
            "más para tu negocio."
        )
    else:
        intro = "Marcamos el mejor de cada fila; tú decides qué pesa más para tu negocio."

    return ComparisonVM(
        intro=intro,
        columns=columns,
        rows=rows,
        mobile=mobile,
        pages=mobile_pages(total),
        stale_message=stale_message,
        stale_ids=stale_ids,
        stale_button=stale_button,
        short_window=short_window,
        add_href=pick_url(ids) if total < COMPARE_MAX else "",
    )


#: The states hold a VM, never None (a `Var` of an optional dataclass cannot be walked
#: with `rx.foreach`); `has_sheet` / `has_comparison` say whether it is real.
EMPTY_SHEET = SheetVM(
    tracked_id="",
    handle="",
    title="",
    avatar_url="",
    initials="",
    profile_url="",
    verified=False,
    freshness="",
    stale=False,
    stale_message="",
    status_message="",
    status_tone="info",
)
EMPTY_COMPARISON = ComparisonVM(intro="")
