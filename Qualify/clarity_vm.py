"""RESULTADOS-4 (m-24843002): the «Tu página web» block of Configuración, as pure data.

The Clarity connection used to live on the reading screen (`/clarity`), with a token
form the owner saw every time. It now lives in Configuración as a short guided step:

1. «¿Tu negocio tiene página web?» — Sí / No.
2. No → «No hace falta: tus redes ya cuentan.» and nothing else.
3. Sí → «Pídele al equipo de Qualify que la conecte» + «Escribir al equipo»; the two
   labelled fields the team fills («Código del proyecto», «Clave de acceso») sit folded
   under «Para el equipo de Qualify», never open by default.
4. Already connected → «Conectada» and no question.

The key stays write-only (`ClarityState.form_api_token` is cleared after the save and
never read back), so no screen ever shows it. Pure functions, tested offline.
"""

from __future__ import annotations

from typing import Literal

WebsiteStep = Literal["connected", "ask", "no_site", "ask_team"]

ANSWER_YES = "si"
ANSWER_NO = "no"

QUESTION = "¿Tu negocio tiene página web?"
NO_SITE = "No hace falta: tus redes ya cuentan."
ASK_TEAM = "Pídele al equipo de Qualify que la conecte."
ASK_TEAM_BUTTON = "Escribir al equipo"
CONNECTED = "Tu página web ya está conectada. Mira cómo le va en «Tu página web»."
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
