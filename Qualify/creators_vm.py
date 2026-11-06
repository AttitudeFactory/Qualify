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
from decimal import ROUND_HALF_UP, Decimal
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
SHEET_PAID = "Publicaciones pagadas"
SHEET_COAUTHORS = "Con quién publica"
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

# --- «Lo que cobra» (m-24955847): what the owner writes down; nothing reaches the creator

#: `/creadores/<id>?flujo=tarifa&paso=1` — the sheet's «Lo que cobra» drawer (N5).
FLOW_RATE = "tarifa"
RATE_TITLE = "Lo que cobra"
RATE_EMPTY = "Todavía no anotas cuánto cobra."
RATE_ADD = "Anotar lo que cobra"
RATE_CHANGE = "Cambiar"
RATE_DRAWER_DESCRIPTION = "Solo lo ves tú. No le enviamos nada al creador."
RATE_NOTES_LABEL = "Cómo trabaja (opcional)"
RATE_NOTES_PLACEHOLDER = "Ej.: 1 reel, 150.000. Paquete de 3 reels y 5 historias, 380.000."
RATE_AMOUNT_LABEL = "Su precio más bajo (para compararlo con otros)"
RATE_AMOUNT_PLACEHOLDER = "Ej.: 150.000"
RATE_CURRENCY_LABEL = "Moneda"
RATE_SAVE = "Guardar"
RATE_NOTES_MAX = 1000
RATE_NOT_A_NUMBER = "Escribe solo el número, por ejemplo 150.000."
RATE_NEGATIVE = "El precio no puede ser negativo."
RATE_TOO_LARGE = "Es demasiado grande; revisa los ceros."
RATE_NOTES_TOO_LONG = "Acorta el texto: caben hasta 1.000 letras."
RATE_NO_CENTS = "Los pesos no llevan centavos. Revisa el número; por ejemplo, 150.500."
RATE_CURRENCY_REQUIRED = "Elige la moneda de su precio."
RATE_BAD_CURRENCY = "Elige una de las monedas de la lista."
RATE_SAVE_FAILED = "No pudimos guardar lo que cobra. Vuelve a intentarlo en un momento."
#: The select's options: lowercase codes on the page, upper case only at the backend door.
RATE_CURRENCY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("cop", "Pesos colombianos"),
    ("usd", "Dólares"),
    ("ves", "Bolívares"),
    ("uyu", "Pesos uruguayos"),
)
RATE_DEFAULT_CURRENCY = "cop"
#: A price of 0: he works for products, never «Desde 0 pesos».
FOR_PRODUCTS = "Trabaja a cambio de productos"

COMPARE_RATE = "Cobra desde"
COMPARE_COST = "Por cada mil vistas (aprox.)"
COMPARE_COST_HINT = "Su precio más bajo entre las vistas que suele tener un reel suyo."
COMPARE_COST_HELP = (
    "Es un cálculo aproximado. Si ese precio incluye varios reels, en realidad te sale más barato."
)
COMPARE_NOTES = "Cómo trabaja"
LOWEST = "Más bajo"
NOT_NOTED = "Sin anotar"
NO_PRICE = "Falta su precio más bajo"
ADD_PRICE = "Anotar su precio más bajo"
SEE_MORE = "Ver más"
MIXED_CURRENCIES = (
    "Hay precios en monedas distintas; solo comparamos los que están en la misma moneda."
)
#: Longer than this (or more than 3 lines) and Comparar clamps the text behind «Ver más».
NOTES_CLAMP_CHARS = 90

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


def count_of(value: float | int | None, noun: str) -> str:
    """«8.300 vistas», «12,4 mil seguidores», «7,2 millones de vistas», «1 millón de
    seguidores»: Spanish puts «de» between a million and its noun."""
    text = format_count(value)
    if text == MISSING:
        return text
    joiner = " de " if text.endswith(("millón", "millones")) else " "
    return f"{text}{joiner}{noun}"


def plural(n: int, one: str, many: str) -> str:
    """«1 reel», «5 reels»."""
    return f"{n} {one if n == 1 else many}"


def format_percent(ratio: float | None, places: int = 1) -> str:
    """A ratio (0.041) as «4,1 %» — a space before %, comma decimal."""
    if ratio is None or math.isnan(ratio):
        return MISSING
    return f"{_decimal(ratio * 100, places)} %"


def format_amount(value: Decimal | float | int, *, whole: bool = False) -> str:
    """A money amount in the owner's format: «150.000», «1.500,50». Cents only when they
    are not zero (and never with ``whole``); no «mil» shortening — a price is exact."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    integral = amount.to_integral_value(rounding=ROUND_HALF_UP)
    if whole or amount == integral:
        return f"{sign}{int(integral):,}".replace(",", ".")
    units, cents = f"{amount:.2f}".split(".")
    return f"{sign}{int(units):,}".replace(",", ".") + f",{cents}"


#: currency code (lower case) → (one, many), the full name. Only the business's own
#: pesos may say «pesos» alone (`_SHORT_PESOS`): any other currency is named in full.
_CURRENCY_WORDS: dict[str, tuple[str, str]] = {
    "cop": ("peso colombiano", "pesos colombianos"),
    "usd": ("dólar", "dólares"),
    "ves": ("bolívar", "bolívares"),
    "uyu": ("peso uruguayo", "pesos uruguayos"),
}
_SHORT_PESOS = ("peso", "pesos")


def currency_words(currency: str | None, *, home: str | None = None) -> tuple[str, str]:
    """(one, many) for a currency: «pesos» alone only for the business's own pesos
    (``home``), the full name otherwise; an unknown code reads as itself."""
    code = (currency or "").strip().lower()
    if code in ("cop", "uyu") and code == (home or "").strip().lower():
        return _SHORT_PESOS
    words = _CURRENCY_WORDS.get(code)
    return words if words is not None else (code.upper(), code.upper())


def money_text(
    amount: Decimal | float | int | None,
    currency: str | None,
    *,
    home: str | None = None,
    whole: bool = False,
) -> str:
    """«150.000 pesos» (the business's own), «150.000 pesos colombianos», «150 dólares»,
    «1 dólar», «1.500,50 bolívares». None → ""."""
    if amount is None:
        return ""
    one, many = currency_words(currency, home=home)
    number = format_amount(amount, whole=whole)
    return f"{number} {one if Decimal(str(amount)) == 1 else many}".strip()


def amount_input_text(amount: Decimal | float | int | None) -> str:
    """The amount as the drawer's field shows it again («150.000», «1.500,50»): the same
    Spanish format the backend's `parse_rate_amount` reads back."""
    return "" if amount is None else format_amount(amount)


def format_date(day: date | datetime | None, *, year: bool = False) -> str:
    """«2 de agosto», or «2 de agosto de 2025» with ``year``."""
    if day is None:
        return ""
    text = f"{day.day} de {_MONTHS[day.month - 1]}"
    return f"{text} de {day.year}" if year else text


def format_range(start: date | datetime, end: date | datetime) -> str:
    """«del 2 de agosto al 1 de noviembre»; both years written when the range crosses
    one («del 20 de diciembre de 2025 al 3 de enero de 2026»)."""
    crosses = start.year != end.year
    return f"del {format_date(start, year=crosses)} al {format_date(end, year=crosses)}"


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
        "Publicaciones pagadas",
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
            # Neutral: the outcome does not say whether the day's or the month's limit
            # was hit, and there is no per-plan limit to promise (review 2026-11-04).
            message=("Llegaste al límite de revisiones por ahora. Vuelve a intentarlo más tarde."),
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


# --- «Lo que cobra» -------------------------------------------------------------------


@dataclass(frozen=True)
class RateVM:
    """What the owner wrote down about a creator's price (m-24955847), as the sheet and
    its drawer show it. ``has_rate`` is False when nothing is written (the empty state,
    never «0»). ``amount_input`` / ``currency`` refill the drawer (currency in lower
    case, "" when no price was written)."""

    has_rate: bool = False
    from_text: str = ""  # «Desde 150.000 pesos»
    notes: str = ""
    updated: str = ""  # «Anotado el 5 de noviembre»
    amount_input: str = ""
    currency: str = ""


EMPTY_RATE = RateVM()


def price_text(
    amount: Decimal | float | int | None, currency: str | None, *, home: str | None = None
) -> str:
    """The price itself: «150.000 pesos», or «Trabaja a cambio de productos» for 0; ""
    without a price."""
    if amount is None:
        return ""
    if Decimal(str(amount)) == 0:
        return FOR_PRODUCTS
    return money_text(amount, currency, home=home)


def rate_from_text(
    amount: Decimal | float | int | None, currency: str | None, *, home: str | None = None
) -> str:
    """«Desde 150.000 pesos», «Trabaja a cambio de productos», or "" without a price."""
    text = price_text(amount, currency, home=home)
    return f"Desde {text}" if text and text != FOR_PRODUCTS else text


def build_rate_vm(
    source: Any, *, now: datetime, zone: tzinfo | None = None, home: str | None = None
) -> RateVM:
    """From anything carrying ``rate_notes`` / ``rate_from`` / ``rate_currency`` /
    ``rate_updated_at`` (the backend's `TrackedCreator` or `CreatorSheet`). Absent
    fields read as «nothing written», so an older backend shows the empty state."""
    notes = (getattr(source, "rate_notes", "") or "").strip()
    amount = getattr(source, "rate_from", None)
    currency = getattr(source, "rate_currency", None) or ""
    updated_at = getattr(source, "rate_updated_at", None)
    if not notes and amount is None:
        return EMPTY_RATE
    updated = ""
    if updated_at is not None:
        day = _local_date(updated_at, zone)
        updated = f"Anotado el {format_date(day, year=day.year != _local_date(now, zone).year)}"
    return RateVM(
        has_rate=True,
        from_text=rate_from_text(amount, currency, home=home),
        notes=notes,
        updated=updated,
        amount_input=amount_input_text(amount),
        currency=currency.lower() if amount is not None else "",
    )


def rate_error_text(reason: str, *, typed: str = "", chosen: str = "") -> tuple[str, str]:
    """`InvalidRate.reason` → (field, sentence). Field: ``amount`` or ``notes``; the
    sentence says what to do next, next to that field. ``typed`` / ``chosen`` are the
    currency codes of `currency_mismatch` (what the amount says, what the select says)."""
    if reason == "currency_mismatch":
        return ("amount", currency_mismatch_text(typed, chosen))
    return {
        "not_a_number": ("amount", RATE_NOT_A_NUMBER),
        "negative": ("amount", RATE_NEGATIVE),
        "too_large": ("amount", RATE_TOO_LARGE),
        "currency_required": ("amount", RATE_CURRENCY_REQUIRED),
        "unsupported_currency": ("amount", RATE_BAD_CURRENCY),
        "notes_too_long": ("notes", RATE_NOTES_TOO_LONG),
        "cents_not_allowed": ("amount", RATE_NO_CENTS),
    }.get(reason, ("", RATE_SAVE_FAILED))


def currency_mismatch_text(typed: str, chosen: str) -> str:
    """«Escribiste dólares pero elegiste pesos colombianos. Cambia la moneda o escribe solo
    el número.» — both named in full, so neither reads as the other."""
    said, picked = currency_words(typed)[1], currency_words(chosen)[1]
    if not typed or not chosen:
        return "El precio dice otra moneda. Cambia la moneda o escribe solo el número."
    return f"Escribiste {said} pero elegiste {picked}. Cambia la moneda o escribe solo el número."


def notes_length(text: str) -> int:
    """What counts against the 1.000 letters: the text without spaces at its edges (the
    backend stores it stripped)."""
    return len((text or "").strip())


def notes_counter(text: str) -> str:
    """«120 de 1.000 letras» under the text box."""
    return f"{format_amount(notes_length(text))} de {format_amount(RATE_NOTES_MAX)} letras"


def known_currency(code: str | None, fallback: str = RATE_DEFAULT_CURRENCY) -> str:
    """A code the select offers (lower case), else ``fallback``."""
    value = (code or "").strip().lower()
    return value if value in dict(RATE_CURRENCY_OPTIONS) else fallback


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
    rate_from: str = ""  # «Desde 150.000 pesos», "" without a price
    rate: RateVM = EMPTY_RATE


def build_card_vm(
    card: Any,
    *,
    now: datetime,
    zone: tzinfo | None = None,
    working: bool = False,
    stuck: bool = False,
    home: str | None = None,
) -> CreatorCardVM:
    """``stuck``: the backend's `refresh_stuck` — a «reading» whose read died on the way
    (`REFRESH_STUCK_AFTER`); the row then offers «Intentar de nuevo» instead of
    «Revisando…» forever."""
    tracked = card.tracked
    handle = at(tracked.handle)
    name = (card.full_name or "").strip() or handle
    read_at = card.read_at
    days = days_between(read_at, now, zone) if read_at is not None else -1
    refresh_state = getattr(tracked, "refresh_state", "") or ""
    stuck = stuck and not working
    if working or (refresh_state == "reading" and not stuck):
        state = "working"
    elif read_at is not None:
        state = "ready"
    elif refresh_state == "failed" or stuck:
        state = "failed"
    else:
        state = "pending"
    problem, tone = "", "error"
    if state == "failed":
        code = "error" if stuck else (tracked.refresh_error or "error")
        outcome = refresh_outcome_vm(code, tracked.handle)
        problem, tone = outcome.message, outcome.tone
    elif state == "pending":
        problem, tone = f"Todavía no revisamos a {handle}.", "info"
    rate = build_rate_vm(tracked, now=now, zone=zone, home=home)
    return CreatorCardVM(
        tracked_id=str(tracked.id),
        href=sheet_url(tracked.id),
        handle=handle,
        name=name,
        avatar_url=card.avatar_url or "",
        initials=initials(name),
        followers=(
            count_of(card.followers, "seguidores")
            if card.followers is not None
            else "Seguidores: sin dato"
        ),
        median_views=(
            count_of(card.median_views.value, "vistas típicas por reel")
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
        rate_from=rate.from_text,
        rate=rate,
    )


def filter_cards(cards: Sequence[CreatorCardVM], query: str) -> list[CreatorCardVM]:
    needle = (query or "").strip().lstrip("@").lower()
    if not needle:
        return list(cards)
    return [card for card in cards if needle in card.search_text]


def sheet_url(tracked_id: UUID | str) -> str:
    return f"{CREATORS_ROUTE}/{tracked_id}"


def rate_url(tracked_id: UUID | str) -> str:
    """The sheet with «Lo que cobra» open (`?flujo=tarifa&paso=1`)."""
    return f"{sheet_url(tracked_id)}?{urlencode({FLOW_PARAM: FLOW_RATE, 'paso': 1})}"


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
    views = count_of(reel.views, "vistas") if reel.views is not None else "Vistas: sin dato"
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
            f"({count_of(best.median_views.value, 'vistas típicas')})."
        )
    elif len(sheet.duration_buckets) >= 2:
        duration_sentence = "Sus reels largos y cortos tienen vistas parecidas."
    else:
        duration_sentence = ""

    paid = sheet.paid_partnerships
    if paid > 0:
        verb = "es una publicación pagada" if paid == 1 else "son publicaciones pagadas"
        collab_sentence = f"{paid} de sus últimos {total} reels {verb}."
    else:
        collab_sentence = f"En sus últimos {total} reels no declaró publicaciones pagadas."
    coauthor_sentence = ""
    if sheet.collabs > 0:
        coauthor_sentence = (
            "Publicó 1 reel junto con otra cuenta:"
            if sheet.collabs == 1
            else f"Publicó {sheet.collabs} reels junto con otras cuentas:"
        )
    elif getattr(sheet, "collabs_known", True) and total:
        coauthor_sentence = f"En sus últimos {total} reels no publicó junto con otras cuentas."

    trust = ""
    if total and sheet.covered_from and sheet.covered_to:
        trust = (
            f"Contamos sus últimos {plural(total, 'reel', 'reels')}, "
            f"{format_range(sheet.covered_from, sheet.covered_to)}."
        )
    elif total:
        trust = f"Contamos sus últimos {plural(total, 'reel', 'reels')}."

    few = ""
    if 0 < measurable <= FEW_REELS:
        few = (
            f"Solo encontramos {plural(measurable, 'reel', 'reels')}. Con tan pocos, los "
            "números todavía dicen poco."
        )
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
    #: ``metric`` (a figure), ``money`` (its badge says «Más bajo»), ``notes`` (free text,
    #: clamped behind «Ver más» when ``long``).
    kind: str = "metric"
    long: bool = False
    #: «Anotar lo que cobra» → the creator's sheet with the drawer open ("" = none).
    add_href: str = ""
    add_label: str = ""


@dataclass(frozen=True)
class RowVM:
    key: str
    label: str
    hint: str
    help: str
    cells: list[CellVM] = field(default_factory=list)
    kind: str = "metric"


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
    measured: str = ""  # «Medido en sus últimos 12 reels (del … al …)»
    handle_wrap: str = ""  # the handle with break points after «.» and «_»
    freshness_short: str = ""  # «hoy», «hace 3 días» (the table's «Datos de» row)


@dataclass(frozen=True)
class MobileItemVM:
    label: str
    text: str
    best: bool
    missing: bool
    kind: str = "metric"
    long: bool = False
    add_href: str = ""
    add_label: str = ""


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
    add_href: str = ""
    mixed_note: str = ""


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


def handle_wrap(handle: str) -> str:
    """A long handle may break after «.» or «_» (a zero-width space), never mid-word."""
    return handle.replace(".", ".\u200b").replace("_", "_\u200b")


def measured_text(count: int | None, start: Any, end: Any) -> str:
    """«Medido en sus últimos 12 reels (del 2 de agosto al 1 de noviembre)»."""
    if not count:
        return ""
    reels = "su último reel" if count == 1 else f"sus últimos {count} reels"
    span = f" ({format_range(start, end)})" if start and end else ""
    return f"Medido en {reels}{span}"


def notes_are_long(notes: str) -> bool:
    """Comparar shows 3 lines; longer text sits behind «Ver más»."""
    return len(notes) > NOTES_CLAMP_CHARS or notes.count("\n") >= 3


def cost_per_thousand_text(
    amount: Decimal | float | int | None, currency: str | None, *, home: str | None = None
) -> str:
    """An estimate, so whole units from 100 up («18.072 pesos»); below that, cents count
    («0,85 dólares»)."""
    if amount is None:
        return MISSING
    whole = abs(Decimal(str(amount))) >= 100
    return money_text(amount, currency, home=home, whole=whole)


def rate_compare_rows(
    creators: Sequence[Any], columns: Sequence[ColumnVM], *, home: str | None = None
) -> list[RowVM]:
    """«Cobra desde», «Por cada mil vistas (aprox.)» and «Cómo trabaja», one cell per
    creator. «Más bajo» comes from the server (`lowest_rate`, `lowest_cost_per_thousand`:
    within one currency, with 2 or more prices above zero), never computed here. Only the
    business's own pesos (``home``) say «pesos» alone; every other currency is named in
    full. Notes without a price ask for the price («Falta su precio más bajo»)."""
    total = len(creators)
    price_cells: list[CellVM] = []
    cost_cells: list[CellVM] = []
    note_cells: list[CellVM] = []
    for index, creator in enumerate(creators):
        handle = columns[index].handle
        tracked_id = columns[index].tracked_id
        amount = getattr(creator, "rate_from", None)
        currency = getattr(creator, "rate_currency", None)
        notes = (getattr(creator, "rate_notes", "") or "").strip()
        cost = getattr(creator, "cost_per_thousand_views", None)

        price = price_text(amount, currency, home=home)
        empty = NO_PRICE if notes else NOT_NOTED
        lowest = bool(getattr(creator, "lowest_rate", False)) and bool(price)
        spoken = f"{COMPARE_RATE}, {handle}: {price or empty}"
        price_cells.append(
            CellVM(
                text=price or empty,
                best=lowest,
                missing=not price,
                spoken=spoken + (f", el más bajo de los {total}" if lowest else ""),
                kind="money",
                add_href="" if price else rate_url(tracked_id),
                add_label="" if price else (ADD_PRICE if notes else RATE_ADD),
            )
        )

        cost_text = cost_per_thousand_text(cost, currency, home=home)
        cheap = bool(getattr(creator, "lowest_cost_per_thousand", False)) and cost is not None
        cost_cells.append(
            CellVM(
                text=cost_text,
                best=cheap,
                missing=cost is None,
                spoken=f"{COMPARE_COST}, {handle}: {cost_text}"
                + (f", el más bajo de los {total}" if cheap else ""),
                kind="money",
            )
        )

        note_cells.append(
            CellVM(
                text=notes or NOT_NOTED,
                best=False,
                missing=not notes,
                spoken=f"{COMPARE_NOTES}, {handle}: {notes or NOT_NOTED}",
                kind="notes",
                long=notes_are_long(notes),
            )
        )
    return [
        RowVM(
            key="rate_from", label=COMPARE_RATE, hint="", help="", cells=price_cells, kind="money"
        ),
        RowVM(
            key="cost_per_thousand",
            label=COMPARE_COST,
            hint=COMPARE_COST_HINT,
            help=COMPARE_COST_HELP,
            cells=cost_cells,
            kind="money",
        ),
        RowVM(
            key="rate_notes", label=COMPARE_NOTES, hint="", help="", cells=note_cells, kind="notes"
        ),
    ]


def build_comparison_vm(
    comparison: Any,
    *,
    now: datetime,
    names: dict[str, tuple[str, str]] | None = None,
    zone: tzinfo | None = None,
    home: str | None = None,
) -> ComparisonVM:
    """A `Comparison` (design §10.3, §9.3) as the table and the phone columns.
    ``names`` maps tracked id → (full name, avatar url) from the list, since the
    comparison itself carries only the handle; ``home`` is the business's currency."""
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
        # Each creator is measured on their OWN last N reels (`reels_used`, from
        # `used_from` to `used_to`); `few_reels` when fewer than N were available.
        count = creator.reels_used or creator.measurable_in_window
        start, end = creator.used_from, creator.used_to
        few = bool(creator.few_reels) or f"few_reels:{tracked_id}" in comparison.warnings
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
                few_note="Pocos reels para comparar" if few else "",
                remove_href=compare_url(others) if total > COMPARE_MIN else "",
                remove_label=f"Quitar a {handle} de la comparación",
                measured=measured_text(count, start, end),
                handle_wrap=handle_wrap(handle),
                freshness_short=ago_text(days),
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

    # «Lo que cobra» (m-24955847): after the four rows that carry «Mejor», the price and
    # what each thousand views costs; «Cómo trabaja» closes the table (long text).
    mixed = bool(getattr(comparison, "mixed_currencies", False))
    rate_rows = rate_compare_rows(creators, columns, home=home)
    insert_at = sum(1 for row in rows if row.key in COMPARE_ORDER[:4])
    rows[insert_at:insert_at] = rate_rows[:2]
    rows.append(rate_rows[2])

    mobile = [
        MobileColumnVM(
            column=column,
            figures=[
                MobileItemVM(
                    label=row.label,
                    text=row.cells[index].text,
                    best=row.cells[index].best,
                    missing=row.cells[index].missing,
                    kind=row.cells[index].kind,
                    long=row.cells[index].long,
                    add_href=row.cells[index].add_href,
                    add_label=row.cells[index].add_label,
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

    # Never a reason we cannot back («alguno publica poco» was wrong, review 2026-11-04):
    # the same N for everyone, and each column says what it was measured on.
    verdict = "Marcamos el mejor de cada fila; tú decides qué pesa más para tu negocio."
    n = comparison.reels_per_creator
    if n:
        reels = "su último reel" if n == 1 else f"los últimos {n} reels"
        intro = f"Comparamos {reels} de cada uno. {verdict}"
    else:
        intro = verdict

    return ComparisonVM(
        intro=intro,
        columns=columns,
        rows=rows,
        mobile=mobile,
        pages=mobile_pages(total),
        stale_message=stale_message,
        stale_ids=stale_ids,
        stale_button=stale_button,
        add_href=pick_url(ids) if total < COMPARE_MAX else "",
        mixed_note=MIXED_CURRENCIES if mixed else "",
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
