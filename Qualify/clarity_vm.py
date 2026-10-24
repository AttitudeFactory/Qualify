"""RESULTADOS-4 (m-24843002): the «Tu página web» block of Configuración, as pure data.

The Clarity connection used to live on the reading screen (`/clarity`), with a token
form the owner saw every time. It now lives in Configuración as a short guided step:

1. «¿Tu negocio tiene página web?» — Sí / No.
2. No → «No es obligatorio: Qualify te funciona igual solo con tus redes.» and nothing else.
3. Sí → «Pídele al equipo de Qualify que la conecte» + «Escribir al equipo»; the two
   labelled fields the team fills («Código del proyecto», «Clave de acceso») sit folded
   under «Para el equipo de Qualify», never open by default.
4. Already connected → «Conectada» and no question.

The key stays write-only (`ClarityState.form_api_token` is cleared after the save and
never read back), so no screen ever shows it. Pure functions, tested offline.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WebsiteStep = Literal["connected", "ask", "no_site", "ask_team"]

ANSWER_YES = "si"
ANSWER_NO = "no"

QUESTION = "¿Tu negocio tiene página web?"
NO_SITE = "No es obligatorio: Qualify te funciona igual solo con tus redes."
ASK_TEAM = "Pídele al equipo de Qualify que la conecte."
ASK_TEAM_BUTTON = "Escribir al equipo"
CONNECTED = "Tu página web ya está conectada."
TEAM_FOLD = "Para el equipo de Qualify"
TEAM_FOLD_HINT = (
    "Estos datos los llena el equipo de Qualify. La clave se guarda protegida y nadie "
    "vuelve a verla."
)
FIELD_PROJECT = "Código del proyecto"
FIELD_KEY = "Clave de acceso"
SAVE = "Guardar"

#: What the team ticket says; the session's email is the contact.
TEAM_REQUEST_MESSAGE = "Quiero conectar mi página web para ver cuántas personas la visitan."
#: `qualify_api.support` accepts only its closed context keys; `screen` is one of them.
TEAM_REQUEST_SCREEN = "settings_website"


def website_step(*, configured: bool, answer: str) -> WebsiteStep:
    """Which part of the guided block to show for this connection state and answer."""
    if configured:
        return "connected"
    if answer == ANSWER_NO:
        return "no_site"
    if answer == ANSWER_YES:
        return "ask_team"
    return "ask"


# --- RESULTADOS-3 (m-24843001): the reading screen «Tu página web» -----------------------
#
# The owner reads two numbers (visits, people) for the last 3 days and the urgent
# problems, each with «Avisar al equipo». No window or breakdown selector and no
# remaining-quota badge: the screen refreshes itself at most once a day, counted in the
# business's time zone — the service's daily request budget is never the owner's.

#: What the automatic daily read asks Clarity for: 3 days broken down by page, so every
#: problem says where it happened.
READ_DAYS = 3
READ_DIMENSION = "URL"

PAGE_TITLE = "Tu página web"
PAGE_SUBTITLE = "Cuántas personas la visitaron y dónde se trabaron."
FIX_FIRST = "Qué arreglar primero"
ALL_GOOD = "Lo demás está bien."
NOTHING_URGENT = "En estos días no hubo nada urgente. Lo demás está bien."
UPDATES_DAILY = "Se actualiza sola una vez al día."
URGENT = "Urgente"
WARN_TEAM = "Avisar al equipo"
WARNED_TEAM = "Ya le avisaste al equipo"
NOT_CONNECTED_TITLE = "Tu página web todavía no está conectada"
NOT_CONNECTED_BODY = (
    "No hace falta: tus redes ya cuentan. Si tienes página web, en Configuración puedes "
    "pedirle al equipo de Qualify que la conecte."
)
GO_TO_SETTINGS = "Ir a Configuración"
NO_DATA_TITLE = "Todavía no hay datos de tu página web"
NO_DATA_BODY = "Los traemos solos una vez al día. Vuelve a mirar mañana."
BACK_HOME = "Volver al inicio"
LOOKING_TODAY = "Buscando los datos de hoy…"
HOME_PAGE = "tu página de inicio"
ALL_NUMBERS = "Ver todos los números"
RECORDINGS_LINK = "Ver grabaciones de las visitas en Clarity ↗"

#: `qualify_api.support` context `screen` for «Avisar al equipo».
TEAM_ALERT_SCREEN = "website_problem"

#: Headline stats the owner reads; the rest stays under «Ver todos los números».
HEADLINE_LABELS = ("Visitas", "Personas")


#: The tenant's zone when none is stored — same default as `conversations_provider`.
DEFAULT_TIMEZONE = "America/Bogota"

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


def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def local_day(moment: datetime, tz: str = DEFAULT_TIMEZONE) -> date:
    """The calendar day `moment` falls on in the business's time zone."""
    return moment.astimezone(_zone(tz)).date()


def needs_daily_refresh(
    fetched_at: datetime | None, now: datetime, tz: str = DEFAULT_TIMEZONE
) -> bool:
    """Whether the reading screen should spend its one automatic request today: never
    read yet, or the last read happened on an earlier day in the business's zone."""
    if fetched_at is None:
        return True
    return local_day(fetched_at, tz) < local_day(now, tz)


def day_label(moment: datetime, tz: str = DEFAULT_TIMEZONE) -> str:
    """«15 de agosto» in the business's zone — no clock and no zone code on screen."""
    day = local_day(moment, tz)
    return f"{day.day} de {_MONTHS[day.month - 1]}"


def date_line(fetched_at: datetime, now: datetime, tz: str = DEFAULT_TIMEZONE) -> str:
    """«Datos de hoy.» or «Datos del 22 de octubre.» — the first line of the screen."""
    if local_day(fetched_at, tz) == local_day(now, tz):
        return "Datos de hoy."
    return f"Datos del {day_label(fetched_at, tz)}."


def es_int(value: int) -> str:
    """«1.240» — thousands with a dot, as read in Colombia, Venezuela and Uruguay."""
    return f"{value:,}".replace(",", ".")


def es_percent(value: float) -> str:
    """«13 %» — whole percentages are easier to read than «12,5%»."""
    if 0 < value < 0.5:
        return "menos de 1 %"
    return f"{int(value + 0.5)} %"  # half up: 12,5 → 13


def es_number(raw: str) -> str:
    """A raw table cell in local notation: «1.240», «12,5»; anything else unchanged."""
    text = raw.strip()
    try:
        number = float(text)
    except ValueError:
        return raw
    if number.is_integer() and "e" not in text.lower():
        return es_int(int(number))
    formatted = f"{number:,.1f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def page_path(url: str) -> str:
    """«/reservas» from «https://www.bianki.com/reservas?utm_source=ig#x» — the owner
    recognises the page, not the address; «/» or nothing is «tu página de inicio»."""
    text = url.strip()
    if not text:
        return ""
    parts = urlsplit(text if "://" in text or text.startswith("/") else f"//{text}")
    path = parts.path.rstrip("/")
    return path or HOME_PAGE


def window_label(num_of_days: int) -> str:
    """«Últimos 3 días» — the owner's words for the snapshot's window."""
    if num_of_days == 1:
        return "Último día"
    return f"Últimos {num_of_days} días"


def team_alert_message(title: str, detail: str, url: str = "") -> str:
    """The support ticket text behind «Avisar al equipo» for one urgent problem. The
    full address goes to the team (it helps whoever fixes it), never to the screen."""
    text = f"Problema urgente en la página web del negocio: {title}. {detail}".strip()
    return f"{text} Dirección completa: {url}" if url else text
