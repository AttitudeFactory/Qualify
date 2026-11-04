"""Audience choices use resolved Meta options and separate people from ad positions."""

from __future__ import annotations

import reflex as rx

from .promotion_audience_vm import GENDER_LABELS, PLACE_KIND_LABELS, PLACEMENT_LABELS
from .promotion_state import PromotionState as S
from .ui import callout, card, loading_spinner
from .ui import tokens as T


def _select(label: str, name: str, value: rx.Var[str], options: dict[str, str]) -> rx.Component:
    field_id = "audience-" + name
    return rx.vstack(
        rx.el.label(label, html_for=field_id, font_weight="500"),
        rx.select.root(
            rx.select.trigger(id=field_id, min_height="44px", width="100%"),
            rx.select.content(*[rx.select.item(text, value=key) for key, text in options.items()]),
            value=value,
            on_change=lambda selected: S.audience_edit(name, selected),
            disabled=S.busy,
            size="3",
        ),
        spacing="2",
        width="100%",
    )


def _number(label: str, name: str, value: rx.Var[str]) -> rx.Component:
    field_id = "audience-" + name
    return rx.vstack(
        rx.el.label(label, html_for=field_id, font_weight="500"),
        rx.input(
            id=field_id,
            value=value,
            on_change=lambda text: S.edit(name, text),
            type="number",
            min="1" if name == "radius_km" else "18",
            max="80" if name == "radius_km" else "65",
            disabled=S.busy,
            min_height="44px",
            size="3",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def _place(place: rx.Var) -> rx.Component:
    return rx.button(
        rx.vstack(
            rx.text(place.label, weight="medium", overflow_wrap="anywhere"),
            rx.text(place.region + " · " + place.country, size="1", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        on_click=S.choose_place(place.key),
        disabled=S.busy,
        variant="outline",
        min_height="44px",
        height="auto",
        white_space="normal",
        text_align="left",
        width="100%",
    )


def _interest(interest: rx.Var) -> rx.Component:
    return rx.button(
        interest.label,
        on_click=S.choose_interest(interest.id),
        disabled=S.busy,
        variant="outline",
        min_height="44px",
        white_space="normal",
        height="auto",
        width="100%",
    )


def _selected_interest(interest: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.flex(
            rx.text(interest.label, overflow_wrap="anywhere", flex="1"),
            rx.button(
                "Quitar",
                aria_label="Quitar interés: " + interest.label,
                on_click=S.remove_interest(interest.id),
                variant="ghost",
                disabled=S.busy,
                min_height="44px",
            ),
            align="center",
            wrap="wrap",
            width="100%",
        ),
        rx.cond(
            interest.notice != "active",
            rx.text(
                rx.match(
                    interest.notice,
                    ("retiring", "Meta va a retirar este interés. Quítalo y elige otro."),
                    ("unavailable", "Este interés ya no está disponible. Quítalo y elige otro."),
                    "Meta debe confirmar que este interés sigue disponible "
                    "antes de crear el anuncio.",
                ),
                size="2",
                color=T.TEXT_MUTED,
            ),
        ),
        width="100%",
        spacing="1",
    )


def _people() -> rx.Component:
    return rx.vstack(
        rx.checkbox(
            "Es un anuncio de vivienda",
            checked=S.form.housing,
            on_change=lambda checked: S.option("housing", checked),
            disabled=S.busy,
            min_height="44px",
        ),
        rx.cond(
            S.form.housing,
            callout(
                "En vivienda no elegimos edades, género ni intereses. Las reglas del lugar "
                "deben comprobarse con Meta antes de crear el anuncio.",
                "info",
            ),
            rx.el.details(
                rx.el.summary("Más opciones de público", min_height="44px", cursor="pointer"),
                rx.vstack(
                    _number("Edad mínima", "age_min", S.form.age_min),
                    _number("Edad máxima (65 significa 65 o más)", "age_max", S.form.age_max),
                    _select("Personas", "gender", S.form.gender, GENDER_LABELS),
                    rx.el.label("Intereses (opcional)", html_for="audience-interest-query"),
                    rx.input(
                        id="audience-interest-query",
                        value=S.interest_query,
                        on_change=lambda value: S.audience_edit("interest_query", value),
                        placeholder="Ejemplo: café",
                        disabled=S.busy,
                        min_height="44px",
                        width="100%",
                        size="3",
                    ),
                    rx.button(
                        "Buscar intereses",
                        on_click=S.search_interests,
                        disabled=S.busy | (S.interest_query.length() < 2),
                        variant="outline",
                        min_height="44px",
                    ),
                    rx.foreach(S.interest_results, _interest),
                    rx.foreach(S.form.interests, _selected_interest),
                    rx.cond(
                        S.form.interests.length() > 0,
                        rx.button(
                            "Ver intereses relacionados",
                            on_click=S.suggest_interests,
                            disabled=S.busy,
                            variant="outline",
                            min_height="44px",
                        ),
                    ),
                    spacing="3",
                    width="100%",
                    align_items="stretch",
                ),
                width="100%",
            ),
        ),
        rx.checkbox(
            "Permitir que Meta amplíe el público",
            checked=S.form.advantage_audience,
            on_change=lambda checked: S.option("advantage_audience", checked),
            disabled=S.busy,
            min_height="44px",
        ),
        spacing="3",
        width="100%",
    )


def _placements() -> rx.Component:
    return rx.el.details(
        rx.el.summary("Dónde aparece el anuncio", min_height="44px", cursor="pointer"),
        rx.vstack(
            rx.text(
                "Esto elige espacios en las redes; el lugar de las personas se elige arriba.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            _select(
                "Espacios en Facebook e Instagram",
                "placement_mode",
                S.form.placement_mode,
                {"automatic": "Que Meta elija", "manual": "Elegir espacios"},
            ),
            rx.cond(
                S.form.placement_mode == "manual",
                rx.vstack(
                    *[
                        rx.checkbox(
                            label,
                            checked=S.form.placements.contains(key),
                            on_change=lambda checked, placement=key: S.placement(
                                placement, checked
                            ),
                            disabled=S.busy,
                            min_height="44px",
                        )
                        for key, label in PLACEMENT_LABELS.items()
                    ],
                    width="100%",
                    spacing="2",
                ),
                rx.text(
                    "Meta elige dónde mostrarlo en Facebook e Instagram.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def promotion_audience() -> rx.Component:
    return card(
        rx.vstack(
            _select("Tipo de lugar", "location_kind", S.form.location_kind, PLACE_KIND_LABELS),
            rx.el.label("¿Dónde están las personas?", html_for="audience-place-query"),
            rx.input(
                id="audience-place-query",
                value=S.place_query,
                on_change=lambda value: S.audience_edit("place_query", value),
                placeholder="Ejemplo: Cúcuta o Colombia",
                disabled=S.busy,
                min_height="44px",
                width="100%",
                size="3",
            ),
            rx.button(
                "Buscar lugares",
                on_click=S.search_places,
                disabled=S.busy | (S.place_query.length() < 2),
                variant="outline",
                min_height="44px",
            ),
            rx.foreach(S.place_results, _place),
            rx.cond(
                S.form.location_key != "",
                rx.text("Lugar elegido: " + S.form.city_name, weight="medium"),
            ),
            rx.cond(
                (S.form.location_kind == "city") & (S.form.location_key != "") & ~S.form.housing,
                rx.el.details(
                    rx.el.summary("Añadir distancia alrededor (opcional)", min_height="44px"),
                    _number(
                        "Distancia en km (deja vacío para usar la ciudad)",
                        "radius_km",
                        S.form.radius_km,
                    ),
                    rx.text(
                        "Esta distancia es una preparación. Meta debe confirmar "
                        "si está permitida antes de crear el anuncio.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    width="100%",
                ),
            ),
            _people(),
            _placements(),
            rx.cond(
                S.audience_working != "",
                rx.hstack(loading_spinner(), rx.text(S.audience_working, size="2"), role="status"),
            ),
            rx.cond(S.audience_error != "", callout(S.audience_error, "error")),
            rx.cond(S.audience_notice != "", callout(S.audience_notice, "info")),
            rx.vstack(
                rx.text("Cuántas personas podrían verlo", weight="medium"),
                rx.cond(
                    S.reach_loading,
                    rx.hstack(
                        loading_spinner(), rx.text("Consultando la estimación…"), role="status"
                    ),
                    rx.text(S.audience_reach.label, aria_live="polite"),
                ),
                rx.text(S.audience_reach.notice, size="2", color=T.TEXT_MUTED),
                rx.button(
                    "Volver a consultar la estimación",
                    on_click=S.refresh_reach,
                    disabled=S.busy | S.reach_loading | (S.form.location_key == ""),
                    min_height="44px",
                    variant="ghost",
                    white_space="normal",
                    height="auto",
                ),
                spacing="2",
                width="100%",
            ),
            rx.button(
                "Guardar público para después",
                on_click=S.save_audience,
                disabled=S.busy | (S.form.location_key == ""),
                variant="outline",
                min_height="44px",
            ),
            rx.button(
                "Volver al público guardado",
                on_click=S.restore_audience,
                disabled=S.busy,
                variant="ghost",
                min_height="44px",
            ),
            rx.text(
                "Se guarda como preparación en Qualify. No crea ni activa un anuncio.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            spacing="4",
            width="100%",
            align_items="stretch",
        ),
        width="100%",
    )
