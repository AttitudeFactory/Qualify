"""The five Brand Content Engine screens (design §6): /brand, /brand/voice, /create,
/drafts and /drafts/[draft_id].

Views only — every fact they render arrives pre-computed in a `creative_vm` dataclass,
and every action goes through `CreativeState`. Built on the `ui` shell (`app_shell` /
`page_header` / `page_body`, docs/design-system.md §4); status colors follow the
design-system tones (icon + label, never color alone). Material (Liquid Glass, lote E2):
blocks are `ui.card` or the `.q-rv-*` / `.q-decide-*` / `.q-gcard` card-material
classes, controls the `.q-cr-*` classes — all in `assets/qualify-creative.css`; no
colour, shadow or blur is written in this module.
"""

from __future__ import annotations

import reflex as rx

from .campaign_provider import COLOR_LABELS, NO_CAMPAIGN
from .campaign_state import CampaignState
from .content_generator import generator_page
from .creative_state import GENERATION_STAGES, CreativeState
from .creative_vm import (
    CopyVariantVM,
    GapVM,
    MediaVM,
    RouteOptionVM,
    SourceVM,
    ToneRowVM,
)
from .gallery_state import GalleryState
from .media_carousel import media_carousel
from .planner_vm import GALLERY_FILTER_ALL, GALLERY_STATE_FILTERS
from .post_card import campaign_badge, color_swatches, kind_chip, media_fill, viewable_src
from .r2_media import BACKEND_BASE
from .ui import (
    app_shell,
    callout,
    card,
    choice_card,
    dropzone,
    empty_state,
    loading_spinner,
    page_body,
    page_header,
    skeleton_rows,
    tone_badge,
)
from .ui import tokens as T

# ---------------------------------------------------------------------------
# Shared scaffolding


_CLAMP_2 = {
    "display": "-webkit-box",
    "-webkit-line-clamp": "2",
    "-webkit-box-orient": "vertical",
    "overflow": "hidden",
}


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
        ("drafting", loading_spinner("sm")),
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
        rx.icon("circle-alert", size=15, color=T.tone_color("warn", 9)),
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
                    rx.icon("circle-check", size=15, color=T.tone_color("ok", 9)),
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
                callout(
                    "Esto se comprueba siempre, incluso si desactivas el resto.",
                    "warn",
                    icon="shield-alert",
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
                callout(CreativeState.kit_notice, "ok", icon="circle-check"),
            ),
            readiness_panel(),
            rx.cond(
                CreativeState.kit_loading,
                skeleton_rows(1, height="16rem", radius=T.RADIUS_CARD),
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
                tone_badge("difiere", "warn"),
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
            tone_badge(proposal.status_label, "warn", size="2"),
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
            callout(
                rx.text(
                    "Perfil activo: v",
                    CreativeState.voice_active.version.to_string(),
                    ". Aprobar una nueva propuesta lo reemplaza.",
                ),
                "ok",
                icon="badge-check",
            ),
        ),
        rx.cond(
            CreativeState.voice_loading,
            skeleton_rows(1, height="14rem", radius=T.RADIUS_CARD),
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
    """The chosen objective is solid in the `ok` tone, the others soft gray. Two buttons
    under a `cond` rather than a conditional `color_scheme`: the tone's scale comes
    from `T.tone_scheme`, which is a Python mapping, not a Var."""
    selected = CreativeState.brief_objective == value
    return rx.cond(
        selected,
        rx.button(
            label,
            variant="solid",
            on_click=CreativeState.set_objective(value),
            size="2",
            **T.tone_scheme("ok"),
        ),
        rx.button(
            label,
            variant="soft",
            color_scheme="gray",
            on_click=CreativeState.set_objective(value),
            size="2",
        ),
    )


def _route_option(option: RouteOptionVM) -> rx.Component:
    """One submodule of the image accordion — visible even when blocked, with the
    reason; GENERATE carries its ⚠ warning BEFORE being chosen."""
    selected = CreativeState.selected_route == option.key
    header = rx.hstack(
        rx.cond(
            selected,
            rx.icon("circle-dot", size=16, color=T.tone_color("accent", 9)),
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
        rx.text(option.description, size="2", color=T.TEXT_MUTED),
        rx.cond(
            option.warning != "",
            callout(option.warning, "error"),
        ),
        rx.cond(
            option.needs_upload,
            rx.vstack(
                dropzone(
                    rx.vstack(
                        rx.icon("image-up", size=22, color=T.TEXT_FAINT),
                        rx.text("Arrastra tu foto o haz clic para elegirla", size="2"),
                        align="center",
                        spacing="2",
                    ),
                    upload_id="creative_photo",
                    accept={"image/*": [".png", ".jpg", ".jpeg", ".webp"]},
                    max_files=1,
                    on_drop=CreativeState.handle_photo_upload(
                        rx.upload_files(upload_id="creative_photo")
                    ),
                    variant="compact",
                    padding="1.5rem",
                    width="100%",
                ),
                rx.cond(
                    CreativeState.staged_media_name != "",
                    rx.hstack(
                        rx.icon("circle-check", size=14, color=T.tone_color("ok", 9)),
                        rx.text("Foto lista: ", CreativeState.staged_media_name, size="2"),
                        align="center",
                    ),
                ),
                rx.cond(
                    CreativeState.upload_error != "",
                    rx.text(CreativeState.upload_error, size="2", color=T.tone_color("error", 11)),
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
        choice_card(
            header,
            rx.cond(selected, expanded),
            selected=selected,
            on_select=CreativeState.select_route(option.key),
            width="100%",
        ),
        choice_card(
            header,
            rx.text(option.disabled_reason, size="1", color=T.TEXT_MUTED),
            selected=False,
            disabled=True,
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
                tone_badge("Instagram · Post de feed 4:5", "ok"),
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
    """/create is the content generator (`content_generator.py`), moved here from
    /signals (§ request 2026-09-30). The BrandReadiness gate is lifted for now: the
    screen no longer swaps the form for `_create_blocked()`. The service still refuses
    a brand with no kit or no voice at all, and that refusal shows as the generator's
    error. `_create_form()` / `_create_blocked()` stay, unrouted, for when the gate
    comes back. Since the same day it is a step-by-step wizard like the Brand Kit
    (`content_generator.generator_page`)."""
    return generator_page()


# ---------------------------------------------------------------------------
# /drafts — the POST gallery (QUA-118)


_GALLERY_STATE_ICON = {
    "schedulable": "circle-check",
    "needs_action": "circle-alert",
    "draft": "pencil-line",
    "used": "history",
    "discarded": "circle-x",
}


def _gallery_state_badge(post) -> rx.Component:
    """The POST's state on its media: glyph + word, in the state's tone."""
    return rx.box(
        rx.match(
            post.gallery_state,
            *[(key, rx.icon(icon, size=12)) for key, icon in _GALLERY_STATE_ICON.items()],
            rx.icon("circle", size=12),
        ),
        rx.text(
            rx.cond(post.gallery_state == "schedulable", "Listo para publicar", post.gallery_label),
            as_="span",
        ),
        class_name="q-gstate q-gstate--" + post.gallery_state,
    )


def _gallery_card(post) -> rx.Component:
    """One POST of the gallery, picture first: its state on the media (a ready one is
    solid and glows, one that is not ready has a dashed frame), its temperature in big —
    Cold frosted, Hot in embers — and the actions it allows right on the card: review
    («Aprobar» / «Rechazar») while it waits for you, «Programar» once it is ready."""
    busy = GalleryState.busy_post_id == post.post_id
    view = rx.link(
        rx.button(
            rx.icon("eye", size=15),
            "Ver POST",
            variant="soft",
            color_scheme="gray",
            size="2",
            width="100%",
        ),
        href=post.detail_href,
        width="100%",
    )
    actions = rx.cond(
        post.can_review,
        rx.box(
            rx.button(
                rx.icon("circle-x", size=15),
                "Rechazar",
                variant="outline",
                size="2",
                width="100%",
                disabled=busy,
                **T.tone_scheme("error"),
                on_click=GalleryState.ask_reject_post(post.post_id, post.title),
            ),
            rx.button(
                rx.icon("circle-check", size=15),
                "Aprobar",
                size="2",
                width="100%",
                loading=busy,
                on_click=GalleryState.quick_approve(post.post_id),
            ),
            view,
            class_name="q-gcard-actions q-gcard-actions--review",
        ),
        rx.box(
            view,
            rx.cond(
                post.gallery_state == "schedulable",
                rx.button(
                    rx.icon("calendar-plus", size=15),
                    "Programar",
                    size="2",
                    width="100%",
                    on_click=GalleryState.assign(post.post_id),
                ),
            ),
            class_name="q-gcard-actions",
        ),
    )
    return rx.box(
        rx.box(
            media_fill(post.thumbnail_url, post.video_url, post.kind),
            rx.box(class_name="q-gcard-shade"),
            rx.box(_gallery_state_badge(post), class_name="q-gcard-tl"),
            rx.cond(
                post.temperature != "",
                rx.box(
                    rx.cond(
                        post.temperature == "cold",
                        rx.icon("snowflake", size=15),
                        rx.icon("flame", size=15),
                    ),
                    rx.text(post.temperature_label, as_="span"),
                    class_name="q-temp q-temp--big q-temp--" + post.temperature,
                    title=post.temperature_hint,
                ),
            ),
            rx.box(kind_chip(post.kind, post.kind_label, glass=True), class_name="q-gcard-bl"),
            class_name="q-gcard-media",
        ),
        rx.box(
            rx.text(post.title, class_name="q-gcard-title", style=_CLAMP_2),
            campaign_badge(post.campaign_name, post.campaign_color),  # QUA-143
            rx.flex(
                rx.text(post.media_label, size="1", color=T.TEXT_MUTED),
                rx.cond(
                    post.used_count > 0,
                    rx.box(
                        rx.icon("history", size=11),
                        "Usado ×" + post.used_count.to_string(),
                        class_name="q-gmeta",
                    ),
                ),
                rx.cond(
                    post.in_calendar,
                    rx.box(
                        rx.icon("calendar-check", size=11), "En calendario", class_name="q-gmeta"
                    ),
                ),
                wrap="wrap",
                gap="0.4rem",
                align="center",
            ),
            rx.cond(
                post.readiness_note != "",
                rx.hstack(
                    rx.icon("triangle-alert", size=13, flex_shrink="0"),
                    rx.text(post.readiness_note, size="1"),
                    class_name="q-gcard-note",
                    align="start",
                    spacing="1",
                ),
            ),
            class_name="q-gcard-body",
        ),
        actions,
        class_name="q-gcard q-gcard--"
        + post.gallery_state
        + " q-chip-temp q-chip-temp--"
        + post.temperature,
    )


def _gallery_reject_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("¿Rechazar este POST?"),
            rx.alert_dialog.description(
                "«" + GalleryState.reject_post_title + "» se descarta y no se genera nada "
                "nuevo. No se podrá aprobar ni publicar.",
                size="2",
            ),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button(
                        rx.icon("arrow-left", size=15),
                        "Volver",
                        variant="soft",
                        color_scheme="gray",
                        size="2",
                    ),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        rx.icon("circle-x", size=15),
                        "Sí, rechazar",
                        size="2",
                        on_click=GalleryState.confirm_reject_post,
                        **T.tone_scheme("error"),
                    ),
                ),
                justify="end",
                gap="0.75rem",
                margin_top="1.25rem",
            ),
            max_width="28rem",
        ),
        open=GalleryState.reject_post_id != "",
        on_open_change=GalleryState.set_reject_post_open,
    )


def _state_chip(value: str, label: str) -> rx.Component:
    """A state filter: the word, its count, selected = solid. «Todos» first."""
    selected = GalleryState.state_filter == value

    def count() -> rx.Component:
        return rx.badge(
            GalleryState.state_counts[value],
            variant="soft",
            color_scheme="gray",
            radius="full",
            size="1",
            class_name="q-nums",
        )

    # The selected chip is soft in the accent (no `color_scheme`: omitting it IS the
    # accent, `T.tone_scheme`), the others soft gray — two buttons under a `cond`. Soft,
    # not solid: a selected filter is a state; the page's one solid is «Crear POST» (P3).
    return rx.cond(
        selected,
        rx.button(
            label,
            count(),
            size="1",
            variant="soft",
            radius="full",
            on_click=GalleryState.set_state_filter(value),
            aria_pressed="true",
        ),
        rx.button(
            label,
            count(),
            size="1",
            variant="soft",
            color_scheme="gray",
            radius="full",
            on_click=GalleryState.set_state_filter(value),
            aria_pressed="false",
        ),
    )


def _gallery_toolbar() -> rx.Component:
    return rx.flex(
        rx.flex(
            _state_chip(GALLERY_FILTER_ALL, "Todos"),
            *[_state_chip(value, label) for value, label in GALLERY_STATE_FILTERS],
            wrap="wrap",
            gap="0.35rem",
            align="center",
        ),
        rx.spacer(),
        rx.link(
            rx.button(rx.icon("sparkles", size=15), "Crear POST", size="2"),
            href="/create",
        ),
        wrap="wrap",
        gap="0.75rem",
        align="center",
        width="100%",
    )


def _gallery_empty() -> rx.Component:
    return rx.cond(
        GalleryState.is_filtered,
        empty_state(
            "filter",
            "Nada con esos filtros",
            "Prueba otro estado u otra categoría, o quita los filtros.",
            action=rx.button(
                "Quitar filtros", variant="soft", size="2", on_click=GalleryState.clear_filters
            ),
        ),
        empty_state(
            "inbox",
            "Todavía no hay POSTs",
            "Cada pieza que encargues aparece aquí con su estado, lista para revisar y programar.",
            action=rx.link(
                rx.button(rx.icon("plus", size=16), "Crear el primero", size="3"),
                href="/create",
            ),
        ),
    )


def drafts_index() -> rx.Component:
    """The gallery: every POST of the brand as a card with its state (Borrador · Por
    completar · Listo · Usado · Desechado), filters, and «Asignar» into the
    Planificador's drawer (QUA-118 AC 1 / AC 3)."""
    return _screen(
        "Piezas",
        "Tus POSTs y en qué punto está cada uno: nada sale sin aprobación humana.",
        _padded(
            rx.cond(GalleryState.error != "", _error_callout(GalleryState.error)),
            _gallery_toolbar(),
            rx.cond(
                GalleryState.loading,
                rx.box(
                    *[skeleton_rows(1, height="7rem", radius=T.RADIUS_CARD) for _ in range(6)],
                    class_name="q-gallery",
                ),
                rx.cond(
                    GalleryState.visible_count > 0,
                    rx.vstack(
                        rx.text(
                            rx.cond(
                                GalleryState.is_filtered,
                                GalleryState.visible_count.to_string()
                                + " de "
                                + GalleryState.total_count.to_string()
                                + " POSTs",
                                GalleryState.total_count.to_string() + " POSTs",
                            ),
                            size="1",
                            color=T.TEXT_MUTED,
                        ),
                        rx.box(
                            rx.foreach(GalleryState.visible, _gallery_card),
                            class_name="q-gallery q-gallery--cards",
                        ),
                        _gallery_reject_dialog(),
                        spacing="2",
                        width="100%",
                        align_items="start",
                    ),
                    _gallery_empty(),
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
        color_scheme=rx.cond(variant.passed, "gray", T.tone_scale("error")),
        on_click=CreativeState.select_variant(variant.variant_id),
        size="2",
    )


def _blocking_item(message: rx.Var[str]) -> rx.Component:
    return rx.hstack(
        rx.icon("shield-x", size=14, color=T.tone_color("error", 9)),
        rx.text(message, size="2", color=T.tone_color("error", 11)),
        align="center",
    )


def _drafting_panel() -> rx.Component:
    """Real staged progress (§6.4), not a blind spinner; the poll gives up at 5 min."""
    return _card(
        rx.hstack(
            loading_spinner("md"),
            rx.heading("Generando tu pieza…", size="4", as_="h2"),
            rx.spacer(),
            rx.text(CreativeState.poll_elapsed_label, size="1", color=T.TEXT_MUTED),
            width="100%",
            align="center",
        ),
        rx.hstack(
            *[tone_badge(stage, "info", size="2") for stage in GENERATION_STAGES],
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
            rx.icon("triangle-alert", size=18, color=T.tone_color("error", 9)),
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
    # everything else is resolved the one way every POST picture is (`viewable_src`).
    local = viewable_src(item.key)
    src = rx.cond(item.url != "", BACKEND_BASE + item.url, local)
    download_href = rx.cond(item.url != "", BACKEND_BASE + item.url + "?download=1", local)
    file_name = rx.cond(item.media_type == "video", "qualify-video.mp4", "qualify-imagen.jpg")
    # Fluid up to 16rem: a fixed 240×427 box overflowed narrow screens and left a black
    # letterbox; the 9:16 ratio keeps a vertical video's shape at any width.
    return rx.vstack(
        # One size per medium, filling the column: a video vertical 9:16, an image 4:5
        # (Instagram's feed format), cropped to fill — never a small floating thumbnail.
        rx.cond(
            item.media_type == "video",
            rx.video(
                src=src,
                controls=True,
                width="100%",
                height="auto",
                # a carousel's video slide keeps its feed shape (see content_generator)
                class_name=rx.cond(
                    item.is_slide, "q-rv-media q-rv-media--slide", "q-rv-media q-rv-media--video"
                ),
            ),
            rx.image(src=src, alt="", class_name="q-rv-media q-rv-media--image"),
        ),
        # The file under its preview: what it is and its format on the left, «Descargar»
        # on the right — a bar of its own, not a loose icon.
        rx.hstack(
            rx.center(
                rx.cond(
                    item.media_type == "video",
                    rx.icon("film", size=15),
                    rx.icon("image", size=15),
                ),
                class_name="q-rv-glyph",
            ),
            rx.vstack(
                rx.text(item.label, size="2", weight="bold"),
                rx.text(
                    rx.cond(item.media_type == "video", "Vertical 9:16", "Publicación 4:5"),
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                spacing="0",
                min_width="0",
            ),
            rx.spacer(),
            rx.button(
                rx.icon("download", size=15),
                "Descargar",
                variant="soft",
                size="2",
                # A browser ignores `<a download>` for another origin (the backend's
                # upload store on its own port, a provider URL) and just opens the file;
                # fetching it and saving the blob downloads it right away. If the origin
                # refuses (no CORS), it opens in a new tab as before.
                on_click=rx.call_script(
                    f"window.qualifyDownload('{download_href.to(str)}', '{file_name}')"
                ),
            ),
            align="center",
            spacing="2",
            width="100%",
            class_name="q-rv-mediabar",
        ),
        spacing="3",
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
            rx.cond(
                # § request 2026-10-08: a carousel's slides as a real carousel
                CreativeState.draft_is_carousel,
                media_carousel(
                    draft.media,
                    CreativeState.draft_slide,
                    on_prev=CreativeState.draft_slide_step(-1),
                    on_next=CreativeState.draft_slide_step(1),
                    on_pick=CreativeState.draft_slide_pick,
                    on_tick=CreativeState.draft_slide_auto,
                    render_item=_media_item,
                ),
                rx.foreach(draft.media, _media_item),
            ),
            spacing="3",
            width=_MEDIA_COLUMN_WIDTH,
            max_width=rx.breakpoints(initial="22rem", md="none"),
            margin_x=rx.breakpoints(initial="auto", md="0"),
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
            class_name="q-rv-media-empty",
        ),
    )


def _edit_actions() -> rx.Component:
    """One action bar, always at the foot of the copy, in both modes: «Editar texto»
    while reading; «Cancelar» and «Guardar cambios» while editing (saving re-runs the
    brand rules). Same size, same shape, every button with its glyph."""
    draft = CreativeState.draft
    return rx.cond(
        CreativeState.edit_mode,
        rx.box(
            rx.flex(
                rx.text(
                    rx.cond(
                        draft.status == "approved",
                        "Al guardar, el POST vuelve a revisión: apruébalo de nuevo para que "
                        "se pueda publicar.",
                        "Al guardar se revisan las reglas de tu marca.",
                    ),
                    size="1",
                    color=T.TEXT_MUTED,
                    flex="1",
                    min_width="12rem",
                ),
                rx.flex(
                    rx.button(
                        rx.icon("x", size=15),
                        "Cancelar",
                        variant="soft",
                        color_scheme="gray",
                        on_click=CreativeState.cancel_edit,
                        disabled=CreativeState.edit_saving,
                        size="2",
                    ),
                    rx.button(
                        rx.icon("check", size=15),
                        "Guardar cambios",
                        on_click=CreativeState.save_edit,
                        loading=CreativeState.edit_saving,
                        size="2",
                    ),
                    gap="0.75rem",
                ),
                align="center",
                justify="between",
                gap="0.75rem",
                wrap="wrap",
                width="100%",
            ),
            class_name="q-rv-savebar q-rv-savebar--editing",
        ),
        rx.cond(
            draft.can_edit,
            rx.box(
                rx.flex(
                    rx.text(
                        "Edita el gancho, el texto, los hashtags, el llamado a la acción y el "
                        "guion.",
                        size="1",
                        color=T.TEXT_MUTED,
                        flex="1",
                        min_width="12rem",
                    ),
                    rx.button(
                        rx.icon("pencil", size=15),
                        "Editar texto",
                        variant="soft",
                        on_click=CreativeState.start_edit,
                        size="2",
                    ),
                    align="center",
                    justify="between",
                    gap="0.75rem",
                    wrap="wrap",
                    width="100%",
                ),
                class_name="q-rv-savebar",
            ),
        ),
    )


def _field_head(icon: str, title: str, hint: str, counter: rx.Var | None = None) -> rx.Component:
    return rx.hstack(
        rx.center(rx.icon(icon, size=14), class_name="q-rv-glyph"),
        rx.vstack(
            rx.text(title, class_name="q-rv-title"),
            rx.text(hint, class_name="q-rv-hint"),
            spacing="0",
            min_width="0",
        ),
        rx.spacer(),
        *([rx.text(counter, class_name="q-rv-count q-nums")] if counter is not None else []),
        align="center",
        spacing="2",
        width="100%",
    )


def _read_text(value: rx.Var[str], empty: str, *, multiline: bool = False) -> rx.Component:
    """A saved field, shown as text — a disabled input reads as broken, not as saved."""
    return rx.cond(
        value != "",
        rx.text(
            value,
            class_name="q-rv-read" + (" q-rv-read--multi" if multiline else ""),
        ),
        rx.text(empty, class_name="q-rv-read q-rv-read--empty"),
    )


def _rv_section(*children: rx.Component) -> rx.Component:
    return rx.box(*children, class_name="q-rv-section")


def _removable_chip(label: rx.Var[str], on_remove, *, prefix: str = "") -> rx.Component:
    return rx.box(
        rx.text(prefix + label, as_="span"),
        rx.cond(
            CreativeState.edit_mode,
            rx.el.button(
                rx.icon("x", size=11),
                type="button",
                class_name="q-rv-chip-x",
                aria_label="Quitar " + prefix + label,
                on_click=on_remove,
            ),
        ),
        class_name="q-rv-chip",
    )


def _add_chip(label: rx.Var[str], on_add, *, prefix: str = "", title=None) -> rx.Component:
    return rx.el.button(
        rx.icon("plus", size=11),
        rx.text(prefix + label, as_="span"),
        type="button",
        class_name="q-rv-chip q-rv-chip--suggest",
        title=title,
        on_click=on_add,
    )


def _add_row(value, on_change, on_add, placeholder: str, icon: str) -> rx.Component:
    """A field to type one more item and the button that adds it — the same pair for
    hashtags and calls to action."""
    return rx.hstack(
        rx.input(
            rx.input.slot(rx.icon(icon, size=13)),
            value=value,
            on_change=on_change,
            placeholder=placeholder,
            size="2",
            flex="1",
        ),
        rx.button(
            rx.icon("plus", size=15),
            "Agregar",
            size="2",
            variant="soft",
            on_click=on_add,
            disabled=value == "",
        ),
        width="100%",
        spacing="2",
    )


def _idea_chip(idea) -> rx.Component:
    return _add_chip(
        idea.tag,
        CreativeState.add_hashtag(idea.tag),
        prefix="#",
        title=idea.reason + rx.cond(idea.seen_label != "", " · " + idea.seen_label, ""),
    )


def _idea_group(icon: str, title: str, ideas) -> rx.Component:
    return rx.cond(
        ideas.length() > 0,
        rx.vstack(
            rx.hstack(
                rx.icon(icon, size=12),
                rx.text(title, size="1", weight="bold"),
                align="center",
                spacing="1",
                class_name="q-rv-group-head",
            ),
            rx.flex(rx.foreach(ideas, _idea_chip), wrap="wrap", gap="0.4rem"),
            spacing="1",
            width="100%",
        ),
    )


def _ai_hashtags() -> rx.Component:
    """«Sugerir con IA»: hashtags for the whole caption — popular, niche, local/brand —
    grounded in tags seen on real posts. The reason is on each chip's tooltip."""
    return rx.box(
        rx.flex(
            rx.hstack(
                rx.icon("sparkles", size=14),
                rx.vstack(
                    rx.text("Sugeridos para tu texto", size="2", weight="bold"),
                    rx.text(
                        "La IA lee todo el caption y propone populares, de nicho y locales, "
                        "priorizando los que vemos en publicaciones reales.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="0",
                ),
                align="start",
                spacing="2",
                flex="1",
                min_width="14rem",
            ),
            rx.flex(
                rx.cond(
                    CreativeState.ai_pending_count > 1,
                    rx.button(
                        rx.icon("list-plus", size=15),
                        "Agregar todos",
                        size="2",
                        variant="soft",
                        color_scheme="gray",
                        on_click=CreativeState.add_all_ai_hashtags,
                    ),
                ),
                rx.button(
                    rx.icon("sparkles", size=15),
                    rx.cond(
                        CreativeState.ai_hashtags.length() > 0, "Sugerir otra vez", "Sugerir con IA"
                    ),
                    size="2",
                    variant="soft",
                    loading=CreativeState.ai_hashtags_loading,
                    on_click=CreativeState.suggest_hashtags_ai,
                ),
                gap="0.75rem",
                wrap="wrap",
            ),
            align="center",
            justify="between",
            gap="0.75rem",
            wrap="wrap",
            width="100%",
        ),
        rx.cond(
            CreativeState.ai_hashtags_note != "",
            rx.text(CreativeState.ai_hashtags_note, size="1", color=T.TEXT_MUTED),
        ),
        _idea_group("flame", "Populares", CreativeState.ai_popular),
        _idea_group("target", "De nicho", CreativeState.ai_niche),
        _idea_group("map-pin", "Locales y de marca", CreativeState.ai_brand),
        rx.cond(
            (CreativeState.ai_hashtags.length() == 0)
            & (CreativeState.hashtag_suggestions.length() > 0),
            rx.vstack(
                rx.hstack(
                    rx.icon("text-search", size=12),
                    rx.text("Palabras de tu texto", size="1", weight="bold"),
                    align="center",
                    spacing="1",
                    class_name="q-rv-group-head",
                ),
                rx.flex(
                    rx.foreach(
                        CreativeState.hashtag_suggestions,
                        lambda tag: _add_chip(tag, CreativeState.add_hashtag(tag), prefix="#"),
                    ),
                    wrap="wrap",
                    gap="0.4rem",
                ),
                spacing="1",
                width="100%",
            ),
        ),
        class_name="q-rv-suggest",
    )


def _hashtags_field() -> rx.Component:
    return _rv_section(
        _field_head(
            "hash",
            "Hashtags",
            "Ayudan a que te encuentre gente que aún no te sigue.",
            CreativeState.hashtag_count_label,
        ),
        rx.cond(
            CreativeState.edit_hashtag_chips.length() > 0,
            rx.flex(
                rx.foreach(
                    CreativeState.edit_hashtag_chips,
                    lambda tag: _removable_chip(tag, CreativeState.remove_hashtag(tag), prefix="#"),
                ),
                wrap="wrap",
                gap="0.4rem",
            ),
            rx.text("Sin hashtags todavía.", class_name="q-rv-read q-rv-read--empty"),
        ),
        rx.cond(
            CreativeState.edit_mode,
            rx.vstack(
                _add_row(
                    CreativeState.edit_hashtag_query,
                    CreativeState.set_edit_hashtag_query,
                    CreativeState.add_typed_hashtag,
                    "Escribe un hashtag",
                    "hash",
                ),
                _ai_hashtags(),
                spacing="3",
                width="100%",
            ),
        ),
    )


def _cta_field() -> rx.Component:
    return _rv_section(
        _field_head(
            "megaphone",
            "Llamado a la acción (CTA)",
            "Lo que le pides a tu público que haga después de verlo. Puedes poner varios.",
        ),
        rx.cond(
            CreativeState.cta_chips.length() > 0,
            rx.flex(
                rx.foreach(
                    CreativeState.cta_chips,
                    lambda cta: _removable_chip(cta, CreativeState.remove_cta(cta)),
                ),
                wrap="wrap",
                gap="0.4rem",
            ),
            rx.text("Sin llamado a la acción.", class_name="q-rv-read q-rv-read--empty"),
        ),
        rx.cond(
            CreativeState.edit_mode,
            rx.vstack(
                _add_row(
                    CreativeState.edit_cta_query,
                    CreativeState.set_edit_cta_query,
                    CreativeState.add_typed_cta,
                    "Ej.: Reserva tu mesa por WhatsApp",
                    "megaphone",
                ),
                rx.cond(
                    CreativeState.cta_suggestions.length() > 0,
                    rx.flex(
                        rx.foreach(
                            CreativeState.cta_suggestions,
                            lambda cta: _add_chip(cta, CreativeState.add_cta(cta)),
                        ),
                        wrap="wrap",
                        gap="0.4rem",
                    ),
                ),
                spacing="3",
                width="100%",
            ),
        ),
    )


def _blocking_list(messages) -> rx.Component:
    return rx.cond(
        messages.length() > 0,
        rx.vstack(
            rx.foreach(messages, _blocking_item),
            spacing="1",
            align_items="start",
            width="100%",
            class_name="q-rv-blocking",
        ),
    )


def _variant_editor() -> rx.Component:
    variant = CreativeState.selected_variant
    editing = CreativeState.edit_mode
    return rx.vstack(
        rx.hstack(
            rx.hstack(
                rx.foreach(CreativeState.draft.variants, _variant_selector),
                spacing="2",
                wrap="wrap",
            ),
            rx.spacer(),
            rx.cond(
                variant,
                rx.cond(
                    variant.was_edited,
                    tone_badge("Editada por ti", "info", icon="pencil", size="2"),
                ),
            ),
            align="center",
            width="100%",
            wrap="wrap",
            gap="0.5rem",
        ),
        rx.cond(
            variant,
            rx.vstack(
                _rv_section(
                    _field_head(
                        "zap",
                        "Gancho",
                        "La primera frase: lo que hace que se detengan a mirar.",
                        CreativeState.hook_count_label,
                    ),
                    rx.cond(
                        editing,
                        rx.input(
                            value=CreativeState.edit_hook,
                            on_change=CreativeState.set_edit_hook,
                            max_length=60,
                            width="100%",
                            size="3",
                            placeholder="Ej.: ¿Ya probaste el sabor del mes?",
                        ),
                        _read_text(CreativeState.edit_hook, "Sin gancho."),
                    ),
                ),
                _rv_section(
                    _field_head(
                        "align-left",
                        "Texto de la publicación",
                        "El caption que acompaña al post en Instagram.",
                        CreativeState.caption_count_label,
                    ),
                    rx.cond(
                        editing,
                        rx.text_area(
                            value=CreativeState.edit_caption,
                            on_change=CreativeState.set_edit_caption,
                            on_blur=CreativeState.load_catalog_hashtags,
                            width="100%",
                            rows="6",
                            size="2",
                        ),
                        _read_text(CreativeState.edit_caption, "Sin texto.", multiline=True),
                    ),
                    # The brand rules the caption breaks, right where it is fixed.
                    rx.cond(
                        CreativeState.caption_blocking.length() > 0,
                        rx.vstack(
                            _blocking_list(CreativeState.caption_blocking),
                            rx.hstack(
                                rx.text(
                                    "Es una regla de tu Brand Kit.", size="1", color=T.TEXT_MUTED
                                ),
                                rx.link("Cambiarla", href="/brand", size="1"),
                                spacing="1",
                            ),
                            spacing="1",
                            width="100%",
                        ),
                    ),
                ),
                _hashtags_field(),
                _cta_field(),
                rx.cond(
                    CreativeState.draft.has_script,
                    _rv_section(
                        _field_head(
                            "mic",
                            "Guion",
                            "Lo que se dice en el video, palabra por palabra. Sin límite de largo.",
                        ),
                        rx.cond(
                            editing,
                            rx.text_area(
                                value=CreativeState.edit_script,
                                on_change=CreativeState.set_edit_script,
                                width="100%",
                                rows="10",
                                size="2",
                                resize="vertical",
                            ),
                            _read_text(CreativeState.edit_script, "Sin guion.", multiline=True),
                        ),
                        rx.cond(
                            variant.shots.length() > 0,
                            rx.vstack(
                                rx.text("Tomas", class_name="q-rv-title"),
                                rx.foreach(
                                    variant.shots,
                                    lambda line: rx.hstack(
                                        rx.icon("video", size=12, color=T.TEXT_MUTED),
                                        rx.text(line, size="2"),
                                        align="start",
                                        spacing="2",
                                    ),
                                ),
                                spacing="1",
                                align_items="start",
                                width="100%",
                            ),
                        ),
                    ),
                ),
                rx.cond(
                    variant.has_ads,
                    _rv_section(
                        _field_head("megaphone", "Anuncio", "Texto para la versión pagada."),
                        rx.text(variant.ads_headline, size="2", weight="bold"),
                        rx.text(variant.ads_description, size="2"),
                    ),
                ),
                _blocking_list(CreativeState.other_blocking),
                _edit_actions(),
                spacing="3",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _review_panel() -> rx.Component:
    draft = CreativeState.draft
    return _card(
        rx.hstack(
            rx.cond(
                draft.kind_label != "",
                rx.badge(
                    rx.icon("sparkles", size=12),
                    draft.kind_label,
                    color_scheme="gray",
                    variant="surface",
                    size="2",
                ),
            ),
            rx.spacer(),
            rx.box(
                rx.icon("shield-check", size=14),
                rx.text(draft.fidelity_summary, as_="span"),
                class_name="q-rv-pill q-rv-pill--ok",
                title="Fidelidad de marca: las reglas de tu brand kit",
            ),
            rx.cond(
                draft.requires_ai_disclosure,
                rx.box(
                    rx.icon("bot", size=14),
                    rx.text("Requiere etiqueta de IA", as_="span"),
                    class_name="q-rv-pill q-rv-pill--warn",
                ),
            ),
            # §6.5: the cost is shown ALWAYS — hiding it is what produces the loop.
            rx.box(
                rx.icon("coins", size=14),
                rx.text("Coste: ", draft.cost_label, as_="span"),
                class_name="q-rv-pill",
            ),
            align="center",
            width="100%",
            wrap="wrap",
            gap="0.5rem",
        ),
        # A grid, not a flex row: from `md` up the media gets its own track and a real
        # gutter, so the video never touches the form; on phones it stacks, media first.
        rx.box(
            rx.box(_media_column(), class_name="q-rv-stage"),
            rx.box(_variant_editor(), min_width="0", width="100%"),
            display="grid",
            grid_template_columns=rx.breakpoints(
                initial="minmax(0, 1fr)",
                md="20rem minmax(0, 1fr)",
                xl="24rem minmax(0, 1fr)",
            ),
            column_gap=rx.breakpoints(initial="0", md="2rem", xl="2.5rem"),
            row_gap="1.5rem",
            align_items="start",
            width="100%",
        ),
        rx.cond(
            draft.blocking_reason,
            _error_callout(draft.blocking_reason),
        ),
    )


def _decision_card(
    *,
    tone: str,
    icon: str,
    title: str,
    text: str,
    button: rx.Component,
) -> rx.Component:
    """One way to decide on the draft: what it does, in a sentence, right above the
    button that does it."""
    return rx.box(
        rx.hstack(
            rx.center(rx.icon(icon, size=16), class_name=f"q-decide-glyph q-decide-{tone}"),
            rx.text(title, class_name="q-rv-title"),
            align="center",
            spacing="2",
        ),
        rx.text(text, size="1", color=T.TEXT_MUTED, flex="1"),
        button,
        class_name=f"q-decide-card q-decide-card--{tone}",
    )


def _reject_dialog() -> rx.Component:
    """A discard is asked once more: a mis-click must not throw a draft away."""
    regenerate = CreativeState.reject_confirm == "regenerate"
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(
                rx.cond(regenerate, "¿Pedir otra versión?", "¿Rechazar este borrador?")
            ),
            rx.alert_dialog.description(
                rx.cond(
                    regenerate,
                    "Este borrador se descarta y se generan variantes nuevas del mismo "
                    "encargo. Consume créditos.",
                    "El borrador se descarta y no se genera nada nuevo. No se podrá "
                    "aprobar ni publicar.",
                ),
                size="2",
            ),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button(
                        rx.icon("arrow-left", size=15),
                        "Volver",
                        variant="soft",
                        color_scheme="gray",
                        size="2",
                    ),
                ),
                rx.alert_dialog.action(
                    rx.cond(
                        regenerate,
                        rx.button(
                            rx.icon("refresh-cw", size=15),
                            "Sí, pedir otra versión",
                            size="2",
                            on_click=CreativeState.confirm_reject,
                            **T.tone_scheme("warn"),
                        ),
                        rx.button(
                            rx.icon("circle-x", size=15),
                            "Sí, rechazar",
                            size="2",
                            on_click=CreativeState.confirm_reject,
                            **T.tone_scheme("error"),
                        ),
                    ),
                ),
                justify="end",
                gap="0.75rem",
                margin_top="1.25rem",
            ),
            max_width="28rem",
        ),
        open=CreativeState.reject_confirm != "",
        on_open_change=CreativeState.set_reject_confirm_open,
    )


def _decision_bar() -> rx.Component:
    """The review decision (HITL #2), as three cards — each one says what it does right
    above its own button. Discarding asks first. It only exists while the draft waits
    for a decision; once approved there is nothing to decide here."""
    draft = CreativeState.draft
    return rx.cond(
        draft.can_reject | draft.can_regenerate | draft.can_approve,
        _card(
            rx.hstack(
                rx.center(rx.icon("gavel", size=16), class_name="q-rv-glyph"),
                rx.vstack(
                    rx.text("¿Qué hacemos con este borrador?", class_name="q-rv-title"),
                    rx.text(
                        "Tú decides qué sale con el nombre de tu marca.",
                        class_name="q-rv-hint",
                    ),
                    spacing="0",
                ),
                align="center",
                spacing="2",
            ),
            rx.box(
                _decision_card(
                    tone="red",
                    icon="circle-x",
                    title="Rechazar",
                    text="Descarta este borrador. No se genera nada nuevo y no se publica.",
                    button=rx.button(
                        rx.icon("circle-x", size=15),
                        "Rechazar",
                        variant="outline",
                        size="2",
                        width="100%",
                        disabled=~draft.can_reject,
                        **T.tone_scheme("error"),
                        on_click=CreativeState.ask_reject(False),
                    ),
                ),
                _decision_card(
                    tone="amber",
                    icon="refresh-cw",
                    title="Pedir otra versión",
                    text="Si la idea sirve pero el resultado no: descarta este y crea "
                    "variantes nuevas del mismo encargo. Consume créditos.",
                    button=rx.button(
                        rx.icon("refresh-cw", size=15),
                        "Regenerar",
                        variant="soft",
                        size="2",
                        width="100%",
                        disabled=~draft.can_regenerate,
                        **T.tone_scheme("warn"),
                        on_click=CreativeState.ask_reject(True),
                    ),
                ),
                _decision_card(
                    tone="green",
                    icon="circle-check",
                    title="Aprobar",
                    text="Fija esta variante como el texto del POST. Queda lista para "
                    "programarla en el Planificador.",
                    button=rx.button(
                        rx.icon("circle-check", size=15),
                        "Aprobar",
                        size="2",
                        width="100%",
                        disabled=~CreativeState.can_approve_now,
                        on_click=CreativeState.approve_selected,
                    ),
                ),
                class_name="q-decide-grid",
            ),
            rx.cond(
                CreativeState.edit_mode,
                rx.text(
                    "Guarda o cancela la edición antes de aprobar.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
            ),
            _reject_dialog(),
        ),
        # Nothing to decide (already approved/staged/published): no bar at all — the
        # status badge at the top already says where the draft stands.
        rx.fragment(),
    )


# Download a file whatever its origin: fetch it and save the blob (a cross-origin
# `<a download>` only opens the file). Falls back to a new tab when the origin refuses.
_DOWNLOAD_SCRIPT = """
window.qualifyDownload = async function (url, name) {
  try {
    const response = await fetch(url, { mode: "cors", credentials: "omit" });
    if (!response.ok) throw new Error(String(response.status));
    const blob = await response.blob();
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(href), 5000);
  } catch (error) {
    window.open(url, "_blank", "noopener");
  }
};
"""


def _campaign_option(option) -> rx.Component:
    return rx.select.item(option.name, value=option.id)


def _campaign_recolor() -> rx.Component:
    """Change the colour of the POST's campaign — for every POST and event of it."""
    s = CampaignState
    return rx.popover.root(
        rx.popover.trigger(
            rx.button(
                rx.icon("palette", size=13),
                "Color",
                variant="ghost",
                color_scheme="gray",
                size="1",
                disabled=s.busy,
                aria_label="Cambiar el color de la campaña",
            )
        ),
        rx.popover.content(
            rx.vstack(
                rx.text("Color de la campaña", size="2", weight="bold"),
                color_swatches(
                    s.current_color, s.recolor, COLOR_LABELS, label="Color de la campaña"
                ),
                rx.text(
                    "Cambia el color en todos los posts y publicaciones de esta campaña.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                max_width="16rem",
            ),
            side="bottom",
            align="start",
        ),
    )


def _campaign_field() -> rx.Component:
    """QUA-143: the POST's campaign — the one place it is created and assigned. Pick one
    of the brand's campaigns, create one by name right here, or leave the POST
    independent. It never changes the POST's revision, status or approval, so it is
    available in every state, an approved and scheduled POST included."""
    s = CampaignState
    picker = rx.select.root(
        rx.select.trigger(placeholder="Sin campaña", aria_label="Campaña del POST"),
        rx.select.content(
            rx.select.item("Sin campaña (post independiente)", value=NO_CAMPAIGN),
            rx.cond(
                s.options.length() > 0,
                rx.select.separator(),
            ),
            rx.foreach(s.options, _campaign_option),
        ),
        value=s.current_id,
        on_change=s.choose,
        disabled=s.busy | s.loading,
        size="2",
    )
    create_form = rx.hstack(
        rx.input(
            value=s.new_name,
            on_change=s.set_new_name,
            on_key_down=s.create_on_enter,
            placeholder="Nombre de la campaña",
            max_length=60,
            auto_focus=True,
            size="2",
            width="16rem",
            aria_label="Nombre de la nueva campaña",
        ),
        color_swatches(
            s.new_color, s.set_new_color, COLOR_LABELS, label="Color de la nueva campaña"
        ),
        rx.button("Crear", on_click=s.create, loading=s.busy, size="2"),
        rx.button(
            "Cancelar", on_click=s.cancel_create, variant="ghost", color_scheme="gray", size="2"
        ),
        align="center",
        spacing="2",
        wrap="wrap",
    )
    return _card(
        rx.hstack(
            rx.center(rx.icon("flag", size=15), class_name="q-section-glyph"),
            rx.vstack(
                rx.text("Campaña", size="2", weight="bold"),
                rx.cond(
                    s.current_name != "",
                    rx.hstack(
                        campaign_badge(s.current_name, s.current_color),
                        _campaign_recolor(),
                        align="center",
                        spacing="2",
                    ),
                    rx.text(
                        "Post independiente: no pertenece a ninguna campaña.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                ),
                spacing="1",
                min_width="0",
            ),
            rx.spacer(),
            rx.cond(
                s.creating,
                create_form,
                rx.hstack(
                    picker,
                    rx.button(
                        rx.icon("plus", size=14),
                        "Nueva campaña",
                        on_click=s.start_create,
                        variant="soft",
                        size="2",
                        disabled=s.busy | s.loading,
                    ),
                    align="center",
                    spacing="2",
                    wrap="wrap",
                ),
            ),
            align="center",
            width="100%",
            wrap="wrap",
            gap="0.75rem",
        ),
        rx.cond(s.error != "", _error_callout(s.error)),
    )


def draft_detail_index() -> rx.Component:
    return _screen(
        "Revisión del borrador",
        "HITL #2: tú decides qué sale con el nombre de tu marca",
        rx.script(_DOWNLOAD_SCRIPT),
        _padded(
            rx.cond(CreativeState.detail_error != "", _error_callout(CreativeState.detail_error)),
            rx.cond(CreativeState.action_error != "", _error_callout(CreativeState.action_error)),
            rx.cond(
                CreativeState.detail_loading,
                skeleton_rows(1, height="18rem", radius=T.RADIUS_CARD),
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
                        _campaign_field(),
                        rx.cond(
                            CreativeState.draft.is_drafting,
                            _drafting_panel(),
                            rx.cond(
                                CreativeState.draft.is_failed,
                                _failed_panel(),
                                rx.vstack(
                                    # a regeneration that did not come out keeps the
                                    # previous version and says so (m-24828909)
                                    rx.cond(
                                        CreativeState.draft.failure_detail != "",
                                        callout(CreativeState.draft.failure_detail, "warn"),
                                    ),
                                    _review_panel(),
                                    _decision_bar(),
                                    spacing="4",
                                    width="100%",
                                ),
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
