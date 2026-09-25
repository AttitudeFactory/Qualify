"""Señales — placeholder landing page for the "Mejorar tu perfil y posicionamiento"
CTA on the Brand Kit connect flow's final screen (`creative_wizard_pages.
_connect_step_insights`).

Fase 3 (typed signal detectors with provenance, `signals.events` — see
`docs/plan-ingesta-social.md` and the roadmap phase map in `CLAUDE.md`) is not built
yet: no schema, no detectors, no data. This route exists so that CTA has somewhere
honest to land — a labeled "not built yet" screen — instead of a dead link or a
made-up destination. Static, no state, no backend call: nothing here to load.
"""

from __future__ import annotations

import reflex as rx

from .content_generator import generator_panel
from .ui import app_shell, empty_state, page_body, page_header


def signals_index() -> rx.Component:
    return app_shell(
        page_header(
            "Señales",
            "Detectores de oportunidad sobre lo que se dice de tu marca",
        ),
        page_body(
            # The content generator lives here while it is being tested (§ request
            # 2026-09-25); /create keeps its original form.
            generator_panel(),
            empty_state(
                "radar",
                "Todavía no hay señales que mostrar",
                "Esta pantalla es un placeholder: la capa de señales (Fase 3 del "
                "roadmap) todavía no está construida. Cuando exista, aquí vas a ver "
                "detectores de oportunidad — quejas de precio, intención de "
                "colaboración, menciones de la competencia — con evidencia y una "
                "acción concreta para cada uno.",
            ),
        ),
    )
