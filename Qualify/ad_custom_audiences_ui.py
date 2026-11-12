"""Optional Instagram audience preparation inside the existing promotion step."""

from __future__ import annotations

import reflex as rx

from .ad_custom_audiences_vm import AUDIENCE_KIND_LABELS
from .promotion_state import PromotionState as S
from .ui import callout, loading_spinner, skeleton_rows
from .ui import tokens as T


def _select(label: str, name: str, value: rx.Var[str], options: dict[str, str]) -> rx.Component:
    field_id = "custom-audience-" + name
    return rx.vstack(
        rx.el.label(label, html_for=field_id, font_weight="500"),
        rx.select.root(
            rx.select.trigger(id=field_id, min_height="44px", width="100%"),
            rx.select.content(*[rx.select.item(text, value=key) for key, text in options.items()]),
            value=value,
            on_change=lambda selected: S.custom_edit(name, selected),
            disabled=S.busy | S.custom_working,
            size="3",
        ),
        width="100%",
        spacing="2",
    )


def _row(row: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.text(row.name, weight="medium", overflow_wrap="anywhere"),
        rx.text(
            rx.match(row.kind, *AUDIENCE_KIND_LABELS.items(), "Público de Instagram"),
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.cond(row.notice != "", rx.text(row.notice, size="2", overflow_wrap="anywhere")),
        rx.button(
            "Elegir este público",
            aria_label="Elegir público: " + row.name,
            on_click=S.choose_custom_audience(row.local_id),
            disabled=S.busy | S.custom_working | ~row.available | ~S.custom_catalog.terms_accepted,
            variant="outline",
            min_height="44px",
            width="100%",
        ),
        width="100%",
        spacing="2",
    )


def _seed(row: rx.Var) -> rx.Component:
    return rx.select.item(row.name, value=row.local_id)


def _create_form() -> rx.Component:
    return rx.el.details(
        rx.el.summary("Crear un público de Instagram", min_height="44px", cursor="pointer"),
        rx.vstack(
            rx.el.label("Nombre para reconocerlo", html_for="custom-audience-name"),
            rx.input(
                id="custom-audience-name",
                value=S.custom_name,
                on_change=lambda value: S.custom_edit("name", value),
                placeholder="Ejemplo: Personas que nos escribieron",
                max_length=100,
                disabled=S.busy | S.custom_working,
                min_height="44px",
                width="100%",
                size="3",
            ),
            rx.cond(
                S.form.housing,
                _select(
                    "¿A quiénes quieres reunir?",
                    "kind",
                    S.custom_kind,
                    {
                        key: value
                        for key, value in AUDIENCE_KIND_LABELS.items()
                        if key != "lookalike"
                    },
                ),
                _select("¿A quiénes quieres reunir?", "kind", S.custom_kind, AUDIENCE_KIND_LABELS),
            ),
            rx.cond(
                S.custom_kind == "lookalike",
                rx.vstack(
                    rx.el.label("Público de partida", html_for="custom-audience-seed"),
                    rx.select.root(
                        rx.select.trigger(
                            id="custom-audience-seed",
                            placeholder="Elige un público tuyo",
                            width="100%",
                            min_height="44px",
                        ),
                        rx.select.content(rx.foreach(S.custom_seed_choices, _seed)),
                        value=S.custom_seed,
                        on_change=lambda value: S.custom_edit("seed", value),
                        disabled=S.busy | S.custom_working,
                        size="3",
                    ),
                    rx.cond(
                        S.custom_seed_choices.length() == 0,
                        rx.text(
                            "Primero crea un público de interacción o mensajes "
                            "y espera a que Meta permita usarlo.",
                            size="2",
                            color=T.TEXT_MUTED,
                        ),
                    ),
                    _select(
                        "País donde buscar personas parecidas",
                        "country",
                        S.custom_country,
                        {"CO": "Colombia", "VE": "Venezuela", "UY": "Uruguay"},
                    ),
                    rx.text(
                        "Meta buscará el 1 % de personas más parecidas en ese país. "
                        "No garantiza visitas ni ventas.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="3",
                    width="100%",
                ),
                _select(
                    "Interacciones de los últimos…",
                    "retention",
                    S.custom_retention,
                    {
                        "30": "30 días",
                        "90": "90 días",
                        "180": "180 días",
                        "365": "365 días",
                        "730": "730 días",
                    },
                ),
            ),
            rx.checkbox(
                "Quiero crear este público en Meta. Esto no activa anuncios ni autoriza gasto.",
                checked=S.custom_confirmed,
                on_change=S.confirm_custom_creation,
                disabled=S.busy | S.custom_working,
                min_height="44px",
            ),
            rx.button(
                "Crear público",
                on_click=S.create_custom_audience,
                disabled=S.busy | S.custom_working | ~S.custom_confirmed,
                variant="outline",
                min_height="44px",
                width="100%",
            ),
            width="100%",
            spacing="3",
            padding_top="3",
        ),
        width="100%",
    )


def custom_audiences() -> rx.Component:
    return rx.el.details(
        rx.el.summary(
            "Personas que te conocen o se parecen a tu público (opcional)",
            min_height="44px",
            cursor="pointer",
        ),
        rx.vstack(
            rx.text(
                "Reúne a quienes interactuaron con tu Instagram o te escribieron. "
                "Meta debe confirmar que el público se puede usar.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.cond(
                S.form.housing,
                callout(
                    "En anuncios de vivienda no se ofrecen públicos de personas parecidas.", "info"
                ),
            ),
            rx.cond(
                S.form.custom_audiences.length() > 0,
                rx.vstack(
                    rx.text(
                        "Público elegido: " + S.custom_selection_label,
                        weight="medium",
                        overflow_wrap="anywhere",
                    ),
                    rx.button(
                        "Quitar público elegido",
                        on_click=S.remove_custom_audience,
                        disabled=S.busy | S.custom_working,
                        variant="ghost",
                        min_height="44px",
                    ),
                    width="100%",
                    spacing="2",
                ),
            ),
            rx.button(
                "Consultar públicos de esta cuenta",
                on_click=S.refresh_custom_audiences,
                disabled=S.busy | S.custom_working,
                variant="outline",
                min_height="44px",
                width="100%",
            ),
            rx.cond(
                S.custom_working,
                rx.cond(
                    S.custom_creating,
                    rx.hstack(loading_spinner(), rx.text("Creando tu público…"), role="status"),
                    rx.vstack(
                        rx.text("Consultando tus públicos…", role="status"),
                        skeleton_rows(rows=2),
                        width="100%",
                    ),
                ),
            ),
            rx.cond(S.custom_catalog.notice != "", callout(S.custom_catalog.notice, "info")),
            rx.cond(
                S.custom_catalog.loaded & ~S.custom_catalog.terms_accepted,
                rx.vstack(
                    rx.text(
                        "Abre Públicos en el Administrador de anuncios de Meta y acepta "
                        "los términos con una persona que administre esta cuenta. "
                        "Después vuelve y consulta los públicos.",
                        size="2",
                    ),
                    rx.link(
                        "Abrir el Administrador de anuncios de Meta",
                        href="https://adsmanager.facebook.com/",
                        is_external=True,
                    ),
                    width="100%",
                    spacing="2",
                ),
            ),
            rx.box(
                rx.cond(S.custom_error != "", callout(S.custom_error, "error")),
                rx.cond(S.custom_notice != "", callout(S.custom_notice, "info")),
                aria_live="polite",
                width="100%",
            ),
            rx.cond(
                S.custom_catalog.loaded & (S.custom_choices.length() == 0),
                rx.text(
                    "Todavía no hay públicos disponibles para este anuncio. "
                    "Crea uno cuando Meta permita hacerlo o continúa sin elegirlo.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
            ),
            rx.foreach(S.custom_choices, _row),
            rx.cond(S.custom_creation_enabled, _create_form()),
            spacing="3",
            width="100%",
            padding_top="3",
        ),
        width="100%",
    )
