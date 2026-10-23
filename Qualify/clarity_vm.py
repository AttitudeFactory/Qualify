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

from datetime import UTC, datetime
from typing import Literal

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
# remaining-quota badge: the screen refreshes itself at most once a (UTC) day — the
# service's daily request budget is the system's business, never the owner's.

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
ALL_NUMBERS = "Ver todos los números"
RECORDINGS_LINK = "Ver grabaciones de las visitas en Clarity ↗"

#: `qualify_api.support` context `screen` for «Avisar al equipo».
TEAM_ALERT_SCREEN = "website_problem"

#: Headline stats the owner reads; the rest stays under «Ver todos los números».
HEADLINE_LABELS = ("Visitas", "Personas")


def needs_daily_refresh(fetched_at: datetime | None, now: datetime) -> bool:
    """Whether the reading screen should spend its one automatic request today: never
    read yet, or the last read happened on an earlier UTC day."""
    if fetched_at is None:
        return True
    return fetched_at.astimezone(UTC).date() < now.astimezone(UTC).date()


def window_label(num_of_days: int) -> str:
    """«Últimos 3 días» — the owner's words for the snapshot's window."""
    if num_of_days == 1:
        return "Último día"
    return f"Últimos {num_of_days} días"


def team_alert_message(title: str, detail: str) -> str:
    """The support ticket text behind «Avisar al equipo» for one urgent problem."""
    return f"Problema urgente en la página web del negocio: {title}. {detail}".strip()
