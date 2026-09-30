"""The five Brand Content Engine screens (design §6): /brand, /brand/voice, /create,
/drafts and /drafts/[draft_id].

Views only — every fact they render arrives pre-computed in a `creative_vm` dataclass,
and every action goes through `CreativeState`. Built on the `ui` shell (`app_shell` /
`page_header` / `page_body`, docs/design-system.md §4); status colors follow the
design-system tones (icon + label, never color alone).
"""

from __future__ import annotations

import reflex as rx

from .creative_state import GENERATION_STAGES, CreativeState
from .creative_vm import (
    CopyVariantVM,
    DraftSummaryVM,
    GapVM,
    MediaVM,
    RouteOptionVM,
    SourceVM,
    ToneRowVM,
)
from .r2_media import BACKEND_BASE
from .ui import app_shell, callout, card, empty_state, page_body, page_header
from .ui import tokens as T

# ---------------------------------------------------------------------------
# Shared scaffolding


def _screen(topbar_title: str, topbar_subtitle: str, *body: rx.Component) -> rx.Component:
    return app_shell(page_header(topbar_title, topbar_subtitle), *body)


def _padded(*children: rx.Component) -> rx.Component:
    return page_body(*children)


def _error_callout(message: rx.Var[str]) -> rx.Component:
    return callout(message, "error")


def _card(*children: rx.Component, **props) -> rx.Component:
    """`ui.card` with the children stacked — every creative panel is a vertical stack."""
    return card(
        rx.vstack(*children, spacing="3", align_items="start", width="100%"),
        padding="1.25rem 1.5rem",
        **props,
    )


def status_badge(status: rx.Var[str], label: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """Status pill: pre-computed label + tone from the VM, icon per status family."""
    icon = rx.match(
        status,
        ("drafting", rx.spinner(size="1")),
        ("generated", rx.icon("eye", size=14)),
        ("approved", rx.icon("circle-check", size=14)),
        ("published", rx.icon("circle-check", size=14)),
        ("staged", rx.icon("clock", size=14)),
        ("rejected", rx.icon("circle-x", size=14)),
        ("failed", rx.icon("triangle-alert", size=14)),
        rx.icon("circle-help", size=14),
    )
    return rx.badge(icon, label, color_scheme=tone, variant="soft", size="2")


# ---------------------------------------------------------------------------
# Readiness (§6.1: what is missing links to the screen that fixes it)


def _gap_row(gap: GapVM) -> rx.Component:
    return rx.hstack(
        rx.icon("circle-alert", size=15, color=rx.color("amber", 9)),
        rx.text(gap.label, size="2"),
        rx.spacer(),
        rx.link(gap.fix_label, href=gap.fix_route, size="2"),
        width="100%",
        align="center",
    )


def readiness_panel() -> rx.Component:
    """Completeness meter + the gap list. Never a disabled button without the fix."""
    return rx.cond(
        CreativeState.readiness,
        _card(
            rx.hstack(
                rx.text("Completitud del sustrato de marca", size="2", weight="medium"),
                rx.spacer(),
                rx.text(
                    CreativeState.readiness.completeness_pct.to_string(),
                    "%",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                width="100%",
                align="center",
            ),
            rx.progress(value=CreativeState.readiness.completeness_pct, max=100, width="100%"),
            rx.text(
                "Los ejemplos de copy pesan más que la paleta: completa primero lo que "
                "mueve el resultado.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.cond(
                CreativeState.readiness.gaps.length() > 0,
                rx.vstack(
                    rx.text("Qué falta", size="1", color=T.TEXT_MUTED),
                    rx.foreach(CreativeState.readiness.gaps, _gap_row),
                    spacing="2",
                    align_items="start",
                    width="100%",
                ),
                rx.hstack(
                    rx.icon("circle-check", size=15, color=rx.color("grass", 9)),
                    rx.text("La marca está lista para generar.", size="2"),
                    align="center",
                ),
            ),
        ),
        rx.fragment(),
    )


# ---------------------------------------------------------------------------
# /brand — the kit editor (§6.2)


def _tone_slider(
    left: str, right: str, value: rx.Var[int], handler: rx.event.EventHandler
) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(left, size="1", color=T.TEXT_MUTED),
            rx.spacer(),
            rx.text(right, size="1", color=T.TEXT_MUTED),
            width="100%",
        ),
        rx.slider(value=[value], on_change=handler, min=0, max=100, step=1, width="100%"),
        rx.text(value.to_string(), size="1", color=T.TEXT_FAINT),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _labeled_area(
    label: str, value: rx.Var[str], handler: rx.event.EventHandler, placeholder: str = ""
) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        rx.text_area(
            value=value, on_change=handler, placeholder=placeholder, width="100%", rows="3"
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _kit_accordion() -> rx.Component:
    """Identity / voice / visual / restrictions, per the §6.2 table."""
    return rx.accordion.root(
        rx.accordion.item(
            header="Identidad",
            content=rx.vstack(
                _labeled_area(
                    "Posicionamiento",
                    CreativeState.kit_positioning,
                    CreativeState.set_kit_positioning,
                    "Qué es la marca y por qué importa",
                ),
                _labeled_area(
                    "Audiencia",
                    CreativeState.kit_audience,
                    CreativeState.set_kit_audience,
                    "A quién le habla",
                ),
                rx.vstack(
                    rx.text("Idioma y variante regional", size="2", weight="medium"),
                    # A select, not free text: es-CO and es-ES produce different copy
                    # and the model drifts to Spain if the variant is not pinned.
                    rx.select(
                        ["es-CO", "es-VE", "es-MX", "es-AR", "es-ES"],
                        value=CreativeState.kit_regional_variant,
                        on_change=CreativeState.set_kit_regional_variant,
                        size="2",
                    ),
                    spacing="1",
                    align_items="start",
                ),
                spacing="3",
                width="100%",
                align_items="start",
            ),
            value="identity",
        ),
        rx.accordion.item(
            header="Voz",
            content=rx.vstack(
                _tone_slider(
                    "formal",
                    "coloquial",
                    CreativeState.tone_formal_casual,
                    CreativeState.set_tone_formal_casual,
                ),
                _tone_slider(
                    "sobrio",
                    "entusiasta",
                    CreativeState.tone_sober_enthusiastic,
                    CreativeState.set_tone_sober_enthusiastic,
                ),
                _tone_slider(
                    "técnico",
                    "llano",
                    CreativeState.tone_technical_plain,
                    CreativeState.set_tone_technical_plain,
                ),
                _tone_slider(
                    "breve",
                    "elaborado",
                    CreativeState.tone_brief_elaborate,
                    CreativeState.set_tone_brief_elaborate,
                ),
                _labeled_area(
                    "Ejemplos que SÍ suenan a la marca (uno por línea)",
                    CreativeState.kit_do_examples,
                    CreativeState.set_kit_do_examples,
                ),
                _labeled_area(
                    "Ejemplos que NO suenan a la marca (uno por línea)",
                    CreativeState.kit_dont_examples,
                    CreativeState.set_kit_dont_examples,
                ),
                _labeled_area(
                    "Patrones de llamado a la acción (uno por línea)",
                    CreativeState.kit_cta_patterns,
                    CreativeState.set_kit_cta_patterns,
                ),
                spacing="3",
                width="100%",
                align_items="start",
            ),
            value="voice",
        ),
        rx.accordion.item(
            header="Visual",
            content=rx.vstack(
                _labeled_area(
                    "Paleta de colores (hex, separados por coma)",
                    CreativeState.kit_palette,
                    CreativeState.set_kit_palette,
                    "#0A3D2E, #F2C94C",
                ),
                rx.text(
                    "El logo, la plantilla de marca y las imágenes de referencia se "
                    "gestionan aparte (subida a R2 pendiente en este corte).",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                spacing="3",
                width="100%",
                align_items="start",
            ),
            value="visual",
        ),
        rx.accordion.item(
            header="Restricciones",
            content=rx.vstack(
                _labeled_area(
                    "Palabras vetadas (una por línea)",
                    CreativeState.kit_banned_words,
                    CreativeState.set_kit_banned_words,
                ),
                _labeled_area(
                    "Claims prohibidos (uno por línea)",
                    CreativeState.kit_forbidden_claims,
                    CreativeState.set_kit_forbidden_claims,
                ),
                rx.callout(
                    "Esto se comprueba siempre, incluso si desactivas el resto.",
                    icon="shield-alert",
                    color_scheme="amber",
                    width="100%",
                ),
                spacing="3",
                width="100%",
                align_items="start",
            ),
            value="restrictions",
        ),
        collapsible=True,
        type="multiple",
        default_value=["identity"],
        variant="surface",
        width="100%",
    )


def brand_index() -> rx.Component:
    return _screen(
        "Brand Kit",
        "El sustrato de marca del que sale cada pieza",
        _padded(
            rx.cond(CreativeState.kit_error != "", _error_callout(CreativeState.kit_error)),
            rx.cond(
                CreativeState.kit_notice != "",
                rx.callout(
                    CreativeState.kit_notice,
                    icon="circle-check",
                    color_scheme="grass",
                    width="100%",
                ),
            ),
            readiness_panel(),
            rx.cond(
                CreativeState.kit_loading,
                rx.skeleton(rx.box(height="16rem", width="100%")),
                rx.vstack(
                    _kit_accordion(),
                    rx.hstack(
                        rx.spacer(),
                        rx.link(
                            rx.button("Perfil de voz →", variant="soft", size="2"),
                            href="/brand/voice",
                        ),
                        rx.button(
                            rx.icon("save", size=15),
                            "Guardar kit",
                            on_click=CreativeState.save_kit_form,
                            size="2",
                        ),
                        width="100%",
                        spacing="3",
                    ),
                    spacing="4",
                    width="100%",
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# /brand/voice — HITL #0 (§6.3: each field next to its evidence)


def _tone_row(row: ToneRowVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row.label),
        rx.table.cell(row.value.to_string(), text_align="right"),
        rx.table.cell(row.kit_value.to_string(), text_align="right"),
        rx.table.cell(
            rx.cond(
                row.differs,
                rx.badge("difiere", color_scheme="amber", variant="soft", size="1"),
                rx.fragment(),
            )
        ),
    )


def _source_row(source: SourceVM) -> rx.Component:
    return rx.hstack(
        rx.icon("file-text", size=14, color=T.TEXT_FAINT),
        rx.text(source.kind_label, size="2", weight="medium"),
        rx.text("«", source.excerpt, "»", size="2", color=T.TEXT_MUTED),
        spacing="2",
        align="center",
        width="100%",
    )


def _chip(text: rx.Var[str]) -> rx.Component:
    return rx.badge(text, variant="surface", color_scheme="gray", size="1")


def _voice_profile_card() -> rx.Component:
    proposal = CreativeState.voice_proposal
    return _card(
        rx.hstack(
            rx.heading(
                "Perfil de voz propuesto · v", proposal.version.to_string(), size="4", as_="h2"
            ),
            rx.spacer(),
            rx.badge(proposal.status_label, color_scheme="amber", variant="soft", size="2"),
            width="100%",
            align="center",
        ),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Ejes de tono"),
                    rx.table.column_header_cell("destilado", text_align="right"),
                    rx.table.column_header_cell("del kit", text_align="right"),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(rx.foreach(proposal.tone_rows, _tone_row)),
            variant="surface",
            width="100%",
        ),
        rx.cond(
            proposal.lexicon.length() > 0,
            rx.vstack(
                rx.text("Léxico propio", size="1", color=T.TEXT_MUTED),
                rx.hstack(rx.foreach(proposal.lexicon, _chip), spacing="2", wrap="wrap"),
                spacing="1",
                align_items="start",
                width="100%",
            ),
        ),
        rx.cond(
            proposal.avoid_lexicon.length() > 0,
            rx.vstack(
                rx.text("Léxico a evitar", size="1", color=T.TEXT_MUTED),
                rx.hstack(rx.foreach(proposal.avoid_lexicon, _chip), spacing="2", wrap="wrap"),
                spacing="1",
                align_items="start",
                width="100%",
            ),
        ),
        rx.cond(
            proposal.sources.length() > 0,
            rx.vstack(
                rx.text("Fuentes", size="1", color=T.TEXT_MUTED),
                rx.foreach(proposal.sources, _source_row),
                spacing="2",
                align_items="start",
                width="100%",
            ),
        ),
        rx.hstack(
            rx.spacer(),
            rx.link(
                # S1 distills deterministically from the kit, so editing the proposal
                # = editing the kit and distilling again.
                rx.button(rx.icon("pencil", size=15), "Editar el kit", variant="soft", size="2"),
                href="/brand",
            ),
            rx.button(
                rx.icon("refresh-cw", size=15),
                "Volver a destilar",
                variant="soft",
                size="2",
                on_click=CreativeState.distill_voice,
            ),
            rx.button(
                rx.icon("circle-check", size=15),
                "Aprobar",
                size="2",
                on_click=CreativeState.approve_voice_version(proposal.version),
                disabled=~proposal.can_approve,
            ),
            width="100%",
            spacing="3",
        ),
    )


def _voice_empty_state() -> rx.Component:
    """No proposal yet. When the kit is not distillable, say WHAT is missing and where
    to fix it (the §6.3 InsufficientEvidence posture) instead of a bare button."""
    return _card(
        rx.heading("Aún no hay un perfil de voz propuesto", size="4", as_="h2"),
        rx.cond(
            CreativeState.readiness & CreativeState.readiness.can_distill,
            rx.vstack(
                rx.text(
                    "El brand kit tiene evidencia suficiente. Destila la primera "
                    "propuesta y revísala antes de aprobar.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.button(
                    rx.icon("sparkles", size=15),
                    "Destilar del brand kit",
                    on_click=CreativeState.distill_voice,
                    size="2",
                ),
                spacing="3",
                align_items="start",
            ),
            rx.vstack(
                rx.text(
                    "No hay evidencia suficiente para proponer una voz sin inventarla. "
                    "Completa esto primero:",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.cond(
                    CreativeState.readiness,
                    rx.foreach(CreativeState.readiness.gaps, _gap_row),
                ),
                spacing="3",
                align_items="start",
                width="100%",
            ),
            _voice_section(),
        ),
    )


def _voice_section() -> rx.Component:
    """Voice, folded into /brand (founder, 2026-08-18): in S1 the profile derives
    deterministically from the kit, so a dedicated review screen was ceremony. The
    approval (HITL #0) survives as an ACTION here; a separate evidence screen returns
    with LLM distillation (S2/S3), where there is real evidence to review."""
    return rx.vstack(
        rx.heading("Voz de marca", size="5", as_="h2"),
        rx.text(
            "Se activa con tu aprobación; es la voz con la que se escribe cada pieza.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        _voice_body(),
        spacing="3",
        width="100%",
        margin_top="1.5rem",
    )


def _voice_body() -> rx.Component:
    return rx.vstack(
        rx.cond(CreativeState.voice_error != "", _error_callout(CreativeState.voice_error)),
        rx.cond(
            CreativeState.voice_active,
            rx.callout(
                rx.text(
                    "Perfil activo: v",
                    CreativeState.voice_active.version.to_string(),
                    ". Aprobar una nueva propuesta lo reemplaza.",
                ),
                icon="badge-check",
                color_scheme="grass",
                width="100%",
            ),
        ),
        rx.cond(
            CreativeState.voice_loading,
            rx.skeleton(rx.box(height="14rem", width="100%")),
            rx.cond(
                CreativeState.voice_proposal,
                _voice_profile_card(),
                _voice_empty_state(),
            ),
        ),
        spacing="3",
        width="100%",
    )


# ---------------------------------------------------------------------------
# /create — the brief (§6.4)


def _objective_button(value: str, label: str) -> rx.Component:
    return rx.button(
        label,
        variant=rx.cond(CreativeState.brief_objective == value, "solid", "soft"),
        color_scheme=rx.cond(CreativeState.brief_objective == value, "grass", "gray"),
        on_click=CreativeState.set_objective(value),
        size="2",
    )


def _route_option(option: RouteOptionVM) -> rx.Component:
    """One submodule of the image accordion — visible even when blocked, with the
    reason; GENERATE carries its ⚠ warning BEFORE being chosen."""
    selected = CreativeState.selected_route == option.key
    header = rx.hstack(
        rx.cond(
            selected,
            rx.icon("circle-dot", size=16, color=rx.color("accent", 9)),
            rx.icon("circle", size=16, color=T.TEXT_FAINT),
        ),
        rx.text(option.title, size="2", weight="medium"),
        rx.cond(
            option.badge != "",
            rx.badge(option.badge, color_scheme=option.badge_tone, variant="soft", size="1"),
        ),
        rx.spacer(),
        rx.text(option.cost_label, size="1", color=T.TEXT_MUTED),
        width="100%",
        align="center",
    )
    expanded = rx.vstack(
        rx.text(option.description, size="2", color=rx.color("gray", 11)),
        rx.cond(
            option.warning != "",
            rx.callout(option.warning, icon="triangle-alert", color_scheme="tomato", width="100%"),
        ),
        rx.cond(
            option.needs_upload,
            rx.vstack(
                rx.upload(
                    rx.vstack(
                        rx.icon("image-up", size=22, color=T.TEXT_FAINT),
                        rx.text("Arrastra tu foto o haz clic para elegirla", size="2"),
                        align="center",
                        spacing="2",
                    ),
                    id="creative_photo",
                    accept={"image/*": [".png", ".jpg", ".jpeg", ".webp"]},
                    max_files=1,
                    on_drop=CreativeState.handle_photo_upload(
                        rx.upload_files(upload_id="creative_photo")
                    ),
                    border=f"1px dashed {rx.color('gray', 7)}",
                    border_radius="0.5rem",
                    padding="1.5rem",
                    width="100%",
                ),
                rx.cond(
                    CreativeState.staged_media_name != "",
                    rx.hstack(
                        rx.icon("circle-check", size=14, color=rx.color("grass", 9)),
                        rx.text("Foto lista: ", CreativeState.staged_media_name, size="2"),
                        align="center",
                    ),
                ),
                rx.cond(
                    CreativeState.upload_error != "",
                    rx.text(CreativeState.upload_error, size="2", color=rx.color("tomato", 10)),
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
        padding_top="0.5rem",
    )
    return rx.cond(
        option.enabled,
        rx.box(
            header,
            rx.cond(selected, expanded),
            on_click=CreativeState.select_route(option.key),
            cursor="pointer",
            padding="1rem 1.25rem",
            border=rx.cond(
                selected,
                f"1px solid {rx.color('accent', 8)}",
                f"1px solid {rx.color('gray', 5)}",
            ),
            border_radius="0.75rem",
            background=rx.color("gray", 2),
            width="100%",
        ),
        rx.box(
            header,
            rx.text(option.disabled_reason, size="1", color=T.TEXT_MUTED),
            padding="1rem 1.25rem",
            border=f"1px dashed {rx.color('gray', 5)}",
            border_radius="0.75rem",
            opacity="0.6",
            width="100%",
        ),
    )


def _create_form() -> rx.Component:
    return rx.vstack(
        _card(
            rx.text("Objetivo", size="2", weight="medium"),
            rx.hstack(
                _objective_button("awareness", "Reconocimiento"),
                _objective_button("consideration", "Consideración"),
                _objective_button("lead", "Captar contacto"),
                _objective_button("sale", "Vender"),
                spacing="2",
                wrap="wrap",
            ),
            rx.text("Tipo de pieza", size="2", weight="medium"),
            rx.select.root(
                rx.select.trigger(width="100%"),
                rx.select.content(
                    rx.foreach(
                        CreativeState.content_type_choices,
                        lambda pair: rx.select.item(pair[1], value=pair[0]),
                    ),
                ),
                value=CreativeState.brief_content_type,
                on_change=CreativeState.set_content_type,
            ),
            rx.text("Tema o producto", size="2", weight="medium"),
            rx.text_area(
                value=CreativeState.brief_topic,
                on_change=CreativeState.set_brief_topic,
                placeholder="Qué anuncia esta pieza",
                width="100%",
                rows="2",
            ),
            rx.text("Plataforma y formato", size="2", weight="medium"),
            rx.hstack(
                rx.badge("Instagram · Post de feed 4:5", color_scheme="grass", variant="soft"),
                rx.tooltip(
                    rx.badge(
                        "Anuncio en Reels 9:16 — pronto",
                        color_scheme="gray",
                        variant="soft",
                        opacity="0.7",
                    ),
                    content=(
                        "El 9:16 es un render aparte con las zonas seguras de Meta "
                        "aplicadas, nunca un recorte del 4:5. Llega en un corte "
                        "posterior (D8)."
                    ),
                ),
                spacing="2",
                wrap="wrap",
            ),
            rx.text("Destino", size="2", weight="medium"),
            rx.hstack(
                rx.button(
                    "Orgánico",
                    variant=rx.cond(CreativeState.brief_intent == "organic", "solid", "soft"),
                    color_scheme="gray",
                    on_click=CreativeState.set_intent("organic"),
                    size="2",
                ),
                rx.button(
                    "Anuncio",
                    variant=rx.cond(CreativeState.brief_intent == "ads", "solid", "soft"),
                    color_scheme="gray",
                    on_click=CreativeState.set_intent("ads"),
                    size="2",
                ),
                rx.button(
                    "Ambos",
                    variant=rx.cond(CreativeState.brief_intent == "both", "solid", "soft"),
                    color_scheme="gray",
                    on_click=CreativeState.set_intent("both"),
                    size="2",
                ),
                spacing="2",
            ),
        ),
        _card(
            rx.text("La imagen", size="2", weight="medium"),
            rx.text(
                "El orden ES la recomendación: de «ningún píxel se toca» a «la imagen se inventa».",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.foreach(CreativeState.route_options, _route_option),
        ),
        _card(
            rx.text("Restricciones opcionales", size="2", weight="medium"),
            rx.input(
                value=CreativeState.brief_must_mention,
                on_change=CreativeState.set_brief_must_mention,
                placeholder="Debe mencionar (separado por comas)",
                width="100%",
            ),
            rx.input(
                value=CreativeState.brief_must_avoid,
                on_change=CreativeState.set_brief_must_avoid,
                placeholder="Debe evitar (separado por comas)",
                width="100%",
            ),
        ),
        rx.hstack(
            rx.spacer(),
            rx.button(
                rx.icon("sparkles", size=16),
                "Generar borrador",
                on_click=CreativeState.submit_brief_form,
                loading=CreativeState.is_submitting,
                size="3",
            ),
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


def _create_blocked() -> rx.Component:
    """§6.1: never a disabled generate button without an explanation + the fix link."""
    return _card(
        rx.heading("La marca aún no está lista para generar", size="4", as_="h2"),
        rx.text(
            "Antes de encargar contenido hay que completar el sustrato: es lo que hace "
            "que cada pieza suene a TU marca.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.cond(
            CreativeState.readiness,
            rx.foreach(CreativeState.readiness.gaps, _gap_row),
        ),
    )


def create_index() -> rx.Component:
    return _screen(
        "Nuevo encargo",
        "Un formulario corto a propósito: el valor está en el sustrato",
        _padded(
            rx.cond(CreativeState.create_error != "", _error_callout(CreativeState.create_error)),
            rx.cond(
                CreativeState.create_loading,
                rx.skeleton(rx.box(height="20rem", width="100%")),
                rx.cond(
                    CreativeState.readiness & CreativeState.readiness.can_generate,
                    _create_form(),
                    _create_blocked(),
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# /drafts — the tray


def _draft_row(draft: DraftSummaryVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.link(
                rx.text(
                    rx.cond(draft.topic != "", draft.topic, "(sin tema)"),
                    size="2",
                    weight="medium",
                ),
                href=f"/drafts/{draft.draft_id}",
                underline="none",
            ),
            max_width="360px",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        rx.table.cell(status_badge(draft.status, draft.status_label, draft.status_tone)),
        rx.table.cell(
            rx.cond(
                draft.failure_label != "",
                rx.text(draft.failure_label, size="1", color=rx.color("tomato", 10)),
                rx.fragment(),
            )
        ),
        rx.table.cell(draft.created_label, white_space="nowrap"),
    )


def drafts_index() -> rx.Component:
    return _screen(
        "Borradores",
        "Cada pieza espera tu revisión: nada sale sin aprobación humana",
        _padded(
            rx.cond(CreativeState.drafts_error != "", _error_callout(CreativeState.drafts_error)),
            rx.hstack(
                rx.spacer(),
                rx.link(
                    rx.button(rx.icon("plus", size=15), "Nuevo encargo", size="2"),
                    href="/create",
                ),
                width="100%",
            ),
            rx.cond(
                CreativeState.drafts_loading,
                rx.skeleton(rx.box(height="10rem", width="100%")),
                rx.cond(
                    CreativeState.drafts.length() > 0,
                    rx.box(
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("Tema"),
                                    rx.table.column_header_cell("Estado"),
                                    rx.table.column_header_cell(""),
                                    rx.table.column_header_cell("Creado"),
                                )
                            ),
                            rx.table.body(rx.foreach(CreativeState.drafts, _draft_row)),
                            variant="surface",
                            width="100%",
                        ),
                        overflow_x="auto",
                        width="100%",
                    ),
                    empty_state(
                        "inbox",
                        "Todavía no hay borradores",
                        "Cada pieza que encargues aparece aquí para tu revisión antes de "
                        "publicarse.",
                        action=rx.link(
                            rx.button(rx.icon("plus", size=16), "Crear el primero", size="3"),
                            href="/create",
                        ),
                    ),
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# /drafts/[draft_id] — HITL #2 (§6.5)


def _variant_selector(variant: CopyVariantVM) -> rx.Component:
    selected = CreativeState.selected_variant_id == variant.variant_id
    return rx.button(
        rx.cond(
            variant.passed,
            rx.icon("circle-check", size=14),
            rx.icon("triangle-alert", size=14),
        ),
        variant.label,
        variant=rx.cond(selected, "solid", "soft"),
        color_scheme=rx.cond(variant.passed, "gray", "tomato"),
        on_click=CreativeState.select_variant(variant.variant_id),
        size="2",
    )


def _blocking_item(message: rx.Var[str]) -> rx.Component:
    return rx.hstack(
        rx.icon("shield-x", size=14, color=rx.color("tomato", 9)),
        rx.text(message, size="2", color=rx.color("tomato", 10)),
        align="center",
    )


def _drafting_panel() -> rx.Component:
    """Real staged progress (§6.4), not a blind spinner; the poll gives up at 5 min."""
    return _card(
        rx.hstack(
            rx.spinner(size="3"),
            rx.heading("Generando tu pieza…", size="4", as_="h2"),
            rx.spacer(),
            rx.text(CreativeState.poll_elapsed_label, size="1", color=T.TEXT_MUTED),
            width="100%",
            align="center",
        ),
        rx.hstack(
            *[
                rx.badge(stage, variant="soft", color_scheme="blue", size="2")
                for stage in GENERATION_STAGES
            ],
            spacing="2",
        ),
        rx.text(
            "Copy → imagen → verificación. La pantalla se actualiza sola.",
            size="1",
            color=T.TEXT_MUTED,
        ),
    )


def _failed_panel() -> rx.Component:
    """FAILED: the reason translated + the concrete action (§6.5), never a bare code."""
    failure = CreativeState.draft.failure
    return _card(
        rx.hstack(
            rx.icon("triangle-alert", size=18, color=rx.color("tomato", 9)),
            rx.heading("La generación falló", size="4", as_="h2"),
            width="100%",
            align="center",
        ),
        rx.cond(
            failure,
            rx.vstack(
                rx.text(failure.label, size="2"),
                rx.cond(
                    CreativeState.draft.failure_detail != "",
                    rx.text(CreativeState.draft.failure_detail, size="2", color=T.TEXT_MUTED),
                ),
                rx.cond(
                    failure.action_route != "",
                    rx.link(
                        rx.button(failure.action_label, variant="soft", size="2"),
                        href=failure.action_route,
                    ),
                    rx.text(failure.action_label, size="2", weight="medium"),
                ),
                spacing="3",
                align_items="start",
            ),
        ),
    )


def _media_item(item: rx.Var[MediaVM]) -> rx.Component:
    # R2-only media comes through the backend's `/r2media/<token>` (`r2_media.py`);
    # everything else from the local upload store, as before.
    local = rx.get_upload_url(item.key)
    src = rx.cond(item.url != "", BACKEND_BASE + item.url, local)
    download_href = rx.cond(item.url != "", BACKEND_BASE + item.url + "?download=1", local)
    # Fluid up to 16rem: a fixed 240×427 box overflowed narrow screens and left a black
    # letterbox; the 9:16 ratio keeps a vertical video's shape at any width.
    return rx.vstack(
        rx.cond(
            item.media_type == "video",
            rx.video(
                src=src,
                controls=True,
                width="100%",
                height="auto",
                style={"aspect_ratio": "9 / 16", "background": "black", "border_radius": "0.5rem"},
            ),
            rx.image(src=src, width="100%", border_radius="0.5rem"),
        ),
        rx.hstack(
            rx.text(item.label, size="1", color=T.TEXT_MUTED),
            rx.link(
                rx.icon("download", size=13),
                href=download_href,
                is_external=True,
                download=True,
                title="Descargar",
            ),
            spacing="2",
            align="center",
        ),
        spacing="1",
        align="center",
        width="100%",
    )


# The media column fills its grid track (see `_review_panel`); on phones the track is the
# full width, so it is capped and centred there.
_MEDIA_COLUMN_WIDTH = "100%"


def _media_column() -> rx.Component:
    draft = CreativeState.draft
    return rx.cond(
        draft.media.length() > 0,
        rx.vstack(
            rx.foreach(draft.media, _media_item),
            spacing="3",
            width=_MEDIA_COLUMN_WIDTH,
            max_width=rx.breakpoints(initial="16rem", md="none"),
            margin_x=rx.breakpoints(initial="auto", md="0"),
            max_height=rx.breakpoints(initial="none", md="40rem"),
            overflow_y="auto",
        ),
        rx.center(
            rx.vstack(
                rx.cond(
                    draft.kind == "creator_script",
                    rx.icon("clapperboard", size=26, color=T.TEXT_FAINT),
                    rx.icon("image-off", size=26, color=T.TEXT_FAINT),
                ),
                rx.text(
                    rx.cond(
                        draft.kind == "creator_script",
                        "Guion para grabar: el video lo hace tu creador.",
                        "Pieza solo de copy: adjunta tu foto al publicar.",
                    ),
                    size="1",
                    color=T.TEXT_MUTED,
                    text_align="center",
                ),
                spacing="2",
                align="center",
            ),
            width=_MEDIA_COLUMN_WIDTH,
            max_width=rx.breakpoints(initial="16rem", md="none"),
            margin_x=rx.breakpoints(initial="auto", md="0"),
            height="275px",
            border=f"1px dashed {rx.color('gray', 6)}",
            border_radius="0.5rem",
            flex_shrink="0",
        ),
    )


def _edit_actions() -> rx.Component:
    """Read-only by default: "Editar" unlocks the fields; "Guardar" re-runs the brand
    rules and locks them again; "Cancelar" restores the saved copy."""
    draft = CreativeState.draft
    return rx.cond(
        CreativeState.edit_mode,
        rx.vstack(
            rx.flex(
                rx.button(
                    rx.icon("shield-check", size=15),
                    "Guardar edición (revalida las reglas)",
                    on_click=CreativeState.save_edit,
                    loading=CreativeState.edit_saving,
                    size="2",
                ),
                rx.button(
                    "Cancelar",
                    variant="soft",
                    color_scheme="gray",
                    on_click=CreativeState.cancel_edit,
                    disabled=CreativeState.edit_saving,
                    size="2",
                ),
                gap="2",
                wrap="wrap",
            ),
            # Only while editing something already approved: saving sends it back to
            # review (the FSM's `edit` edge) — said before the click, not after.
            rx.cond(
                draft.status == "approved",
                rx.text(
                    "Al guardar, el POST vuelve a revisión: apruébalo de nuevo para que se "
                    "pueda publicar.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
            ),
            spacing="1",
            align_items="start",
        ),
        rx.cond(
            draft.can_edit,
            rx.button(
                rx.icon("pencil", size=15),
                "Editar",
                variant="soft",
                on_click=CreativeState.start_edit,
                size="2",
            ),
        ),
    )


def _variant_editor() -> rx.Component:
    variant = CreativeState.selected_variant
    return rx.vstack(
        rx.hstack(
            rx.foreach(CreativeState.draft.variants, _variant_selector),
            spacing="2",
            wrap="wrap",
        ),
        rx.cond(
            variant,
            rx.vstack(
                rx.cond(
                    variant.was_edited,
                    rx.badge("editada por ti", color_scheme="iris", variant="soft", size="1"),
                ),
                rx.text("Gancho", size="1", color=T.TEXT_MUTED),
                rx.input(
                    value=CreativeState.edit_hook,
                    on_change=CreativeState.set_edit_hook,
                    disabled=~CreativeState.edit_mode,
                    max_length=60,
                    width="100%",
                ),
                rx.text("Caption", size="1", color=T.TEXT_MUTED),
                rx.text_area(
                    value=CreativeState.edit_caption,
                    on_change=CreativeState.set_edit_caption,
                    disabled=~CreativeState.edit_mode,
                    width="100%",
                    rows="6",
                ),
                rx.text("Hashtags", size="1", color=T.TEXT_MUTED),
                rx.input(
                    value=CreativeState.edit_hashtags,
                    on_change=CreativeState.set_edit_hashtags,
                    disabled=~CreativeState.edit_mode,
                    width="100%",
                ),
                rx.text("CTA", size="1", color=T.TEXT_MUTED),
                rx.input(
                    value=CreativeState.edit_cta,
                    on_change=CreativeState.set_edit_cta,
                    disabled=~CreativeState.edit_mode,
                    width="100%",
                ),
                rx.cond(
                    CreativeState.draft.has_script,
                    rx.vstack(
                        rx.text("Guion (lo que se dice)", size="1", color=T.TEXT_MUTED),
                        rx.text_area(
                            value=CreativeState.edit_script,
                            on_change=CreativeState.set_edit_script,
                            disabled=~CreativeState.edit_mode,
                            width="100%",
                            rows="8",
                        ),
                        rx.cond(
                            variant.shots.length() > 0,
                            rx.vstack(
                                rx.text("Tomas", size="1", color=T.TEXT_MUTED),
                                rx.foreach(variant.shots, lambda line: rx.text(line, size="2")),
                                spacing="1",
                                align_items="start",
                                width="100%",
                            ),
                        ),
                        spacing="1",
                        align_items="start",
                        width="100%",
                    ),
                ),
                rx.cond(
                    variant.has_ads,
                    rx.vstack(
                        rx.divider(),
                        rx.text("Ads", size="1", color=T.TEXT_MUTED),
                        rx.text(variant.ads_headline, size="2", weight="medium"),
                        rx.text(variant.ads_description, size="2"),
                        spacing="1",
                        align_items="start",
                        width="100%",
                    ),
                ),
                _edit_actions(),
                rx.cond(
                    CreativeState.edit_blocking.length() > 0,
                    rx.vstack(
                        rx.foreach(CreativeState.edit_blocking, _blocking_item),
                        spacing="1",
                        align_items="start",
                        width="100%",
                    ),
                ),
                spacing="2",
                align_items="start",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _review_panel() -> rx.Component:
    draft = CreativeState.draft
    return _card(
        rx.cond(
            draft.kind_label != "",
            rx.badge(draft.kind_label, color_scheme="gray", variant="soft", size="1"),
        ),
        # A grid, not a flex row: from `md` up the media gets its own track and a real
        # gutter, so the video never touches the form; on phones it stacks, media first.
        rx.box(
            _media_column(),
            rx.box(_variant_editor(), min_width="0", width="100%"),
            display="grid",
            grid_template_columns=rx.breakpoints(
                initial="minmax(0, 1fr)",
                md="15rem minmax(0, 1fr)",
                xl="17rem minmax(0, 1fr)",
            ),
            column_gap=rx.breakpoints(initial="0", md="2.5rem", xl="3rem"),
            row_gap="1.5rem",
            align_items="start",
            width="100%",
        ),
        rx.divider(),
        rx.hstack(
            rx.text("Fidelidad de marca:", size="2", color=T.TEXT_MUTED),
            rx.text(draft.fidelity_summary, size="2"),
            rx.cond(
                draft.requires_ai_disclosure,
                rx.badge("requiere etiqueta de IA", color_scheme="amber", variant="soft"),
            ),
            spacing="2",
            align="center",
            wrap="wrap",
        ),
        # §6.5: the cost is shown ALWAYS — hiding it is what produces the loop.
        rx.text("Coste: ", draft.cost_label, size="2", color=T.TEXT_MUTED),
        rx.cond(
            draft.blocking_reason,
            _error_callout(draft.blocking_reason),
        ),
        _decision_bar(),
    )


def _decision_bar() -> rx.Component:
    """The review decision (HITL #2). It only exists while the draft waits for one
    (`generated`, or `rejected` for a regeneration): once approved, the buttons are gone
    and the operator is told why, instead of three disabled buttons with no reason."""
    draft = CreativeState.draft
    return rx.cond(
        draft.can_reject | draft.can_regenerate | draft.can_approve,
        rx.vstack(
            rx.flex(
                rx.button(
                    "Rechazar",
                    variant="soft",
                    color_scheme="gray",
                    on_click=CreativeState.reject_current(False),
                    disabled=~draft.can_reject,
                    size="2",
                    title="Descarta este borrador. No genera nada nuevo.",
                ),
                rx.button(
                    rx.icon("refresh-cw", size=15),
                    "Rechazar y regenerar",
                    variant="soft",
                    color_scheme="amber",
                    on_click=CreativeState.reject_current(True),
                    disabled=~draft.can_regenerate,
                    size="2",
                    title="Descarta este borrador y genera variantes nuevas del mismo encargo "
                    "(consume créditos).",
                ),
                rx.button(
                    rx.icon("circle-check", size=15),
                    "Aprobar y descargar",
                    on_click=CreativeState.approve_selected,
                    disabled=~CreativeState.can_approve_now,
                    size="2",
                ),
                gap="3",
                wrap="wrap",
                justify="end",
                align=rx.breakpoints(initial="stretch", sm="center"),
                direction=rx.breakpoints(initial="column", sm="row"),
                width="100%",
            ),
            rx.text(
                "Rechazar descarta el borrador. Rechazar y regenerar lo descarta y genera "
                "variantes nuevas del mismo encargo (consume créditos). Aprobar fija la "
                "variante elegida como el texto aprobado del POST.",
                size="1",
                color=T.TEXT_MUTED,
                text_align=rx.breakpoints(initial="left", sm="right"),
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
        # Nothing to decide (already approved/staged/published): no bar at all — the
        # status badge at the top already says where the draft stands.
        rx.fragment(),
    )


def draft_detail_index() -> rx.Component:
    return _screen(
        "Revisión del borrador",
        "HITL #2: tú decides qué sale con el nombre de tu marca",
        _padded(
            rx.cond(CreativeState.detail_error != "", _error_callout(CreativeState.detail_error)),
            rx.cond(CreativeState.action_error != "", _error_callout(CreativeState.action_error)),
            rx.cond(
                CreativeState.detail_loading,
                rx.skeleton(rx.box(height="18rem", width="100%")),
                rx.cond(
                    CreativeState.draft,
                    rx.vstack(
                        rx.hstack(
                            rx.link(
                                rx.button(
                                    rx.icon("arrow-left", size=14),
                                    "Bandeja",
                                    variant="ghost",
                                    size="1",
                                ),
                                href="/drafts",
                            ),
                            rx.spacer(),
                            status_badge(
                                CreativeState.draft.status,
                                CreativeState.draft.status_label,
                                CreativeState.draft.status_tone,
                            ),
                            width="100%",
                            align="center",
                        ),
                        rx.cond(
                            CreativeState.draft.is_drafting,
                            _drafting_panel(),
                            rx.cond(
                                CreativeState.draft.is_failed,
                                _failed_panel(),
                                _review_panel(),
                            ),
                        ),
                        spacing="4",
                        width="100%",
                    ),
                    rx.fragment(),
                ),
            ),
        ),
    )
