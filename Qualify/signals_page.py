"""Oportunidades (formerly «Señales», founder decision §2b-6) — the «Pronto» screen behind
the menu's Oportunidades entry (founder decision 4, UX epic m-24842956: Creadores and
Oportunidades stay in the menu marked «Pronto»).

The signal layer (typed opportunity detectors with provenance, `signals.events` — see
`docs/plan-ingesta-social.md`) is not built: no schema, no detectors, no data. This
screen says so honestly, in the owner's words — what it will do for them, and one next
step that works today (their conversations). Static, no state, no backend call.
"""

from __future__ import annotations

import reflex as rx

from .ui import app_shell, empty_state, page_body, page_header, tone_badge
from .ui.layout import RESPOND_ROUTE


def signals_index() -> rx.Component:
    return app_shell(
        page_header(
            "Oportunidades",
            "Te avisaremos cuando alguien pregunte por precios o quiera trabajar contigo",
            badge=tone_badge("Pronto", "neutral"),
        ),
        page_body(
            empty_state(
                "radar",
                "Todavía no hay avisos",
                "Estamos preparando esta parte. Mientras tanto, responde a quien te escribió.",
                action=rx.link(
                    rx.button("Ir a Por responder", size="3"),
                    href=RESPOND_ROUTE,
                ),
            ),
        ),
    )
