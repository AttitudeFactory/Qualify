"""Audience choices use resolved Meta options and separate people from ad positions."""

from __future__ import annotations

import reflex as rx

from .ad_custom_audiences_ui import custom_audiences
from .promotion_audience_vm import GENDER_LABELS, PLACEMENT_LABELS, POINT_DISTANCES, POINT_LABEL
from .promotion_state import PromotionState as S
from .ui import callout, card, choice_card, choice_card_check, loading_spinner
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
            min="17" if name == "radius_km" else "18",
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


def _area(title: str, detail: str, area: str, selected: rx.Var[bool]) -> rx.Component:
    return choice_card(
        rx.flex(
            rx.vstack(
                rx.text(title, weight="medium"),
                rx.text(detail, size="2", color=T.TEXT_MUTED),
                spacing="1",
                align="start",
                flex="1",
            ),
            rx.cond(selected, choice_card_check()),
            align="start",
            gap="2",
            width="100%",
        ),
        selected=selected,
        on_select=S.choose_area(area),
        disabled=S.busy,
        min_height="44px",
        width="100%",
        text_align="left",
    )


def _areas() -> rx.Component:
    return rx.vstack(
        rx.text("¿Dónde están tus clientes?", weight="medium", id="audience-area-title"),
        rx.vstack(
            _area(
                "Cerca de mi negocio",
                "Personas que viven o pasan cerca de tu local.",
                "near",
                S.form.near,
            ),
            _area(
                "En una ciudad",
                "Busca la ciudad donde están tus clientes.",
                "city",
                ~S.form.near & (S.form.location_kind != "country"),
            ),
            _area(
                "En todo un país",
                "Para vender o enviar a todo el país.",
                "country",
                ~S.form.near & (S.form.location_kind == "country"),
            ),
            role="radiogroup",
            aria_labelledby="audience-area-title",
            spacing="2",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def _distance_chip(km: str) -> rx.Component:
    chosen = S.form.radius_km == km
    return rx.button(
        km + " km",
        on_click=S.edit("radius_km", km),
        disabled=S.busy,
        variant=rx.cond(chosen, "solid", "outline"),
        aria_pressed=rx.cond(chosen, "true", "false"),
        min_height="44px",
        min_width="64px",
        size="3",
    )


def _near_business() -> rx.Component:
    has_point = S.form.point_latitude != ""
    return rx.vstack(
        rx.text("¿Dónde está tu negocio?", weight="medium"),
        rx.cond(
            has_point,
            rx.flex(
                rx.flex(
                    rx.icon("map-pin", size=18, color=T.tone_color("ok", 11)),
                    rx.text(POINT_LABEL, weight="medium"),
                    align="center",
                    gap="2",
                ),
                rx.button(
                    "Volver a tomar la ubicación",
                    on_click=S.locate,
                    loading=S.locating,
                    disabled=S.busy,
                    variant="ghost",
                    min_height="44px",
                ),
                align="center",
                justify="between",
                wrap="wrap",
                gap="2",
                width="100%",
            ),
            rx.button(
                rx.icon("locate-fixed", size=18),
                "Estoy en el negocio: usar mi ubicación",
                on_click=S.locate,
                loading=S.locating,
                disabled=S.busy,
                min_height="44px",
                height="auto",
                white_space="normal",
                size="3",
                width="100%",
            ),
        ),
        rx.cond(
            S.locating,
            rx.text(
                "Tu teléfono puede preguntarte si permites usar tu ubicación.",
                size="2",
                color=T.TEXT_MUTED,
                role="status",
            ),
        ),
        rx.cond(S.location_error != "", callout(S.location_error, "error")),
        rx.cond(
            has_point,
            rx.vstack(
                rx.text("¿Hasta qué distancia?", weight="medium"),
                rx.flex(
                    *[_distance_chip(km) for km in POINT_DISTANCES],
                    gap="2",
                    wrap="wrap",
                    role="group",
                    aria_label="Distancia desde tu negocio",
                ),
                rx.el.label("Otra distancia (km)", html_for="audience-near-km"),
                rx.input(
                    id="audience-near-km",
                    value=S.form.radius_km,
                    on_change=lambda text: S.edit("radius_km", text),
                    type="number",
                    min="1",
                    max="80",
                    input_mode="numeric",
                    disabled=S.busy,
                    min_height="44px",
                    size="3",
                    width="8rem",
                ),
                rx.text(
                    S.near_distance_hint,
                    size="2",
                    aria_live="polite",
                    color=rx.cond(
                        S.near_distance_hint.startswith("Escribe"),
                        T.tone_color("error", 11),
                        T.TEXT_MUTED,
                    ),
                ),
                spacing="2",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
    )


def _place_search() -> rx.Component:
    """«En una ciudad» / «En todo un país»: the search exactly as it was before."""
    return rx.vstack(
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
                    "Escribe entre 17 y 80 km. Si lo dejas vacío, el anuncio se muestra "
                    "en toda la ciudad.",
                    size="2",
                    color=rx.cond(
                        S.radius_out_of_range,
                        T.tone_color("error", 11),
                        T.TEXT_MUTED,
                    ),
                ),
                # Open whenever a distance exists, so a saved one outside 17-80 km shows;
                # bound to "out of range" only, it would snap shut mid-typing at 17.
                open=S.form.radius_km != "",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
        align_items="stretch",
    )


def promotion_audience() -> rx.Component:
    return card(
        rx.vstack(
            _areas(),
            rx.cond(S.form.near, _near_business(), _place_search()),
            _people(),
            custom_audiences(),
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
