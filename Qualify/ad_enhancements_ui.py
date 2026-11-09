"""Brand permissions for Meta changes, never an activation control."""

from __future__ import annotations

import reflex as rx

from .ad_enhancements_state import AdEnhancementsState as S
from .ad_enhancements_vm import AVAILABILITY_NOTICE, FEATURE_DESCRIPTIONS, FEATURE_LABELS, FEATURES
from .ui import callout, card, signal_pill, skeleton_card
from .ui import tokens as T


def _permission(key: str) -> rx.Component:
    return rx.vstack(
        rx.checkbox(
            FEATURE_LABELS[key],
            checked=S.values[key],
            on_change=lambda checked: S.change(key, checked),
            disabled=S.loading | S.saving | ~S.policy.loaded,
            min_height="44px",
            width="100%",
        ),
        rx.text(FEATURE_DESCRIPTIONS[key], size="2", color=T.TEXT_MUTED),
        spacing="1",
        align_items="start",
        width="100%",
    )


def _permission_choices() -> rx.Component:
    return rx.cond(
        S.policy.loaded,
        rx.vstack(
            signal_pill("Guardados: " + S.summary, "info"),
            *(_permission(key) for key in FEATURES),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        rx.text(
            "No pudimos conocer los permisos guardados de esta marca. "
            "Vuelve a consultar para revisarlos.",
            size="2",
            color=T.TEXT_MUTED,
        ),
    )


def ad_enhancement_permissions() -> rx.Component:
    return card(
        rx.vstack(
            rx.heading("Qué puede cambiar Meta en tus anuncios", size="4", as_="h2"),
            rx.text(
                "Tú decides si Meta puede modificar la imagen, el texto o el botón. "
                "Estos cuatro permisos empiezan apagados.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.cond(
                S.in_current_brand & S.editing,
                rx.vstack(
                    rx.cond(S.error != "", callout(S.error, "error")),
                    rx.cond(S.notice != "", callout(S.notice, "ok")),
                    rx.cond(
                        S.loading,
                        skeleton_card(4),
                        rx.vstack(
                            _permission_choices(),
                            callout(AVAILABILITY_NOTICE, "warn"),
                            rx.text(
                                "Los anuncios que ya están en circulación no cambian. "
                                "Si tienes una promoción pendiente de activar, "
                                "tendrás que revisarla de nuevo.",
                                size="2",
                                color=T.TEXT_MUTED,
                            ),
                            rx.cond(S.dirty, signal_pill("Cambios sin guardar", "warn")),
                            rx.flex(
                                rx.button(
                                    "Cancelar",
                                    on_click=S.cancel,
                                    disabled=S.saving,
                                    variant="outline",
                                    min_height="44px",
                                ),
                                rx.button(
                                    rx.cond(
                                        S.dirty,
                                        "Descartar cambios y consultar",
                                        "Volver a consultar",
                                    ),
                                    on_click=S.open,
                                    disabled=S.saving,
                                    variant="outline",
                                    min_height="44px",
                                ),
                                rx.button(
                                    "Guardar permisos",
                                    on_click=S.save,
                                    disabled=~S.dirty | S.saving | ~S.policy.loaded,
                                    loading=S.saving,
                                    min_height="44px",
                                ),
                                direction=rx.breakpoints(initial="column", sm="row"),
                                gap="3",
                                width="100%",
                            ),
                            spacing="3",
                            align_items="start",
                            width="100%",
                        ),
                    ),
                    spacing="3",
                    width="100%",
                ),
                rx.button(
                    "Revisar permisos de anuncios",
                    on_click=S.open,
                    variant="outline",
                    min_height="44px",
                ),
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        width="100%",
    )
