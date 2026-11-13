"""The story-with-a-link-button steps of the promotion wizard (m-25026350): the piece's
9:16 file, where the button leads, who sees it (one country; the followers audience is
only a suggestion), and a review with ONE 9:16 preview and Instagram's safe zones.

Nothing is published on the owner's profile: this is only an ad, shown among other
accounts' stories. The budget step and the paused preview, approval and spending consent
are the unpublished wizard's own (`promotion_unpublished_ui`)."""

from __future__ import annotations

import reflex as rx

from .promotion_state import PromotionState as S
from .promotion_unpublished_ui import (
    _fact,
    _media_group,
    _preview,
    _text_field,
    _thumb,
    ad_status_pill,
    review_states,
)
from .promotion_vm import (
    COUNTRY_LABELS,
    STORY_AD_OPTION,
    STORY_AUDIENCE_SUGGESTION,
    STORY_AUTO_CHANGES,
    STORY_AUTO_CHANGES_LABEL,
    STORY_BACK_TO_PIECE,
    STORY_EMPTY,
    STORY_LEFT_WEEK,
    STORY_NO_CHARGE,
    STORY_PLACEMENT,
    STORY_SAFE_BOTTOM,
    STORY_SAFE_HINT,
    STORY_SAFE_TOP,
    WEBSITE_CTA_LABELS,
    AdMediaVM,
)
from .ui import callout, card, choice_card, page_body, page_header
from .ui import tokens as T

# Instagram covers the top ~14 % (account name) and the bottom ~20 % (the button) of a
# 9:16 story; text there gets hidden.
_SAFE_TOP, _SAFE_BOTTOM = "14%", "20%"


def _zone(title: str, edge: str, height: str) -> rx.Component:
    return rx.center(
        rx.text(title, size="1", weight="bold"),
        position="absolute",
        left="0",
        right="0",
        height=height,
        color="white",
        background="rgba(15, 23, 42, 0.55)",
        border="1px dashed rgba(255, 255, 255, 0.8)",
        text_align="center",
        padding="0.25rem",
        pointer_events="none",
        **{edge: "0"},
    )


def story_safe_zones(media: rx.Var[AdMediaVM]) -> rx.Component:
    """The chosen 9:16 file with the zones Instagram covers marked on top of it; small
    enough on a phone to see whole without scrolling."""
    return rx.vstack(
        rx.box(
            _thumb(media, "9 / 16"),
            _zone(STORY_SAFE_TOP, "top", _SAFE_TOP),
            _zone(STORY_SAFE_BOTTOM, "bottom", _SAFE_BOTTOM),
            position="relative",
            overflow="hidden",
            border_radius="8px",
            width="100%",
            aria_label="Zonas de tu historia que Instagram tapa con tu nombre y el botón",
        ),
        rx.text(STORY_SAFE_HINT, size="2", color=T.TEXT_MUTED),
        spacing="2",
        width="100%",
        max_width=rx.breakpoints(initial="13rem", sm="16rem"),
    )


def story_media() -> rx.Component:
    return rx.vstack(
        rx.text("Ya elegimos el de la pieza. Cámbialo si prefieres otro.", color=T.TEXT_MUTED),
        _media_group(
            "Archivos verticales de la pieza",
            "Elige uno.",
            S.selected_source.vertical_media,
            "vertical_asset_id",
            "9 / 16",
            "story-media-label",
        ),
        spacing="4",
        width="100%",
    )


def _cta_list() -> rx.Component:
    return rx.vstack(
        *[
            choice_card(
                rx.text(label, weight="medium"),
                selected=S.form.cta_type == code,
                on_select=S.choose_story_cta(code),
                disabled=S.busy,
                min_height="44px",
                width="100%",
                text_align="left",
            )
            for code, label in WEBSITE_CTA_LABELS.items()
        ],
        role="radiogroup",
        aria_labelledby="story-cta-label",
        spacing="2",
        width="100%",
    )


def story_link() -> rx.Component:
    return rx.vstack(
        # Came from Tu semana: the historia left the plan when the owner chose the ad.
        rx.cond(S.back_label == "Tu semana", callout(STORY_LEFT_WEEK, "info")),
        card(
            rx.vstack(
                _text_field(
                    "Página que abre el botón",
                    "link_url",
                    S.form.link_url,
                    "Revisa que lleve a lo que ofreces en esta historia.",
                    placeholder="https://tu-negocio.com",
                    type="url",
                    min_height="44px",
                ),
                rx.vstack(
                    rx.heading("Texto del botón", size="3", as_="h2", id="story-cta-label"),
                    # The saved button, shown as one line; the whole list only on «Cambiar».
                    rx.hstack(
                        rx.text(S.button_label, weight="medium"),
                        rx.button(
                            rx.cond(S.story_cta_open, "Listo", "Cambiar"),
                            on_click=S.toggle_story_cta,
                            disabled=S.busy,
                            variant="outline",
                            size="2",
                            min_height="44px",
                        ),
                        justify="between",
                        align="center",
                        width="100%",
                    ),
                    rx.cond(S.story_cta_open, _cta_list()),
                    spacing="2",
                    width="100%",
                ),
                # Meta asks for a text and a title; the piece's own are already there.
                # Open on its own only when one is missing, so the step's error is fixable.
                rx.el.details(
                    rx.el.summary(
                        "Texto del anuncio (lo tomamos de la pieza)",
                        style={"cursor": "pointer", "minHeight": "44px", "paddingTop": "0.6rem"},
                    ),
                    rx.vstack(
                        _text_field(
                            "Texto", "message", S.form.message, "Hasta 2.200 caracteres.", rows="4"
                        ),
                        _text_field(
                            "Título",
                            "headline",
                            S.form.headline,
                            "Una frase corta. Hasta 100 caracteres.",
                            min_height="44px",
                        ),
                        spacing="3",
                        width="100%",
                        padding_top="0.5rem",
                    ),
                    open=(S.form.message.strip() == "") | (S.form.headline.strip() == ""),
                    width="100%",
                ),
                spacing="4",
                width="100%",
            ),
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def story_audience() -> rx.Component:
    return rx.vstack(
        rx.heading("¿En qué país?", size="3", as_="h2", id="story-country-label"),
        rx.vstack(
            *[
                choice_card(
                    rx.text(label, weight="medium"),
                    selected=S.form.country == code,
                    on_select=S.choose_country(code),
                    disabled=S.busy,
                    min_height="44px",
                    width="100%",
                    text_align="left",
                )
                for code, label in COUNTRY_LABELS.items()
            ],
            role="radiogroup",
            aria_labelledby="story-country-label",
            spacing="2",
            width="100%",
        ),
        # Only a suggestion: it cannot be applied to an unpublished piece yet, so it is
        # never drawn as a chosen option.
        callout(STORY_AUDIENCE_SUGGESTION, "info", icon="lightbulb"),
        rx.text(STORY_PLACEMENT, size="2", color=T.TEXT_MUTED),
        spacing="3",
        width="100%",
    )


def _story_file() -> rx.Component:
    video = S.form.media_kind == "videos"
    return card(
        rx.vstack(
            rx.heading("Así queda tu historia", size="3", as_="h2"),
            story_safe_zones(S.chosen_vertical),
            rx.cond(
                video,
                rx.vstack(
                    rx.text("Portada del video", size="1", color=T.TEXT_MUTED),
                    rx.box(_thumb(S.chosen_vertical_cover, "9 / 16"), width="6rem"),
                    rx.cond(
                        ~S.paid_operation_locked,
                        rx.button(
                            rx.cond(S.covers_open, "Listo", "Cambiar portada"),
                            on_click=S.toggle_covers,
                            disabled=S.busy,
                            variant="outline",
                            min_height="44px",
                        ),
                    ),
                    rx.cond(
                        S.covers_open,
                        _media_group(
                            "Portada del video",
                            "La imagen que se ve antes de que empiece el video.",
                            S.selected_source.vertical_covers,
                            "vertical_cover_id",
                            "9 / 16",
                            "story-cover-label",
                        ),
                    ),
                    spacing="2",
                    width="100%",
                ),
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def story_review() -> rx.Component:
    return rx.vstack(
        review_states(),
        rx.cond(
            S.has_remote_review,
            rx.vstack(
                ad_status_pill(),
                _preview("En historias de Instagram", S.review.vertical_preview_url, "640px"),
                spacing="3",
                width="100%",
                max_width="24rem",
            ),
            rx.cond(~S.video_waiting & ~S.needs_help, callout(STORY_NO_CHARGE, "info")),
        ),
        _story_file(),
        card(
            rx.vstack(
                _fact("Dónde aparece", STORY_PLACEMENT),
                _fact("Instagram", S.selected_source.account_label),
                _fact("Cuenta para anuncios", S.selected_source.account_name),
                _fact("Botón", S.button_label),
                _fact("Página que abre", S.form.link_url),
                _fact("Texto", S.form.message),
                _fact("Título", S.form.headline),
                _fact("País", S.country_label),
                _fact("Presupuesto para todo el período", S.budget_label),
                _fact("Inicio", S.start_label),
                _fact("Final", S.end_label),
                _fact("Horario", S.zone_label),
                _fact(STORY_AUTO_CHANGES_LABEL, STORY_AUTO_CHANGES),
                spacing="3",
                width="100%",
            ),
            width="100%",
        ),
        rx.cond(
            S.has_remote_review,
            rx.vstack(
                rx.text(S.review.charge_notice, weight="medium"),
                rx.text(
                    "Revisión válida hasta: " + S.review.expires_label,
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.checkbox(
                    "Revisé la vista previa y autorizo el presupuesto total indicado.",
                    checked=S.confirm_charge,
                    on_change=S.accept_charge,
                    disabled=S.busy | S.paid_operation_locked | S.checks_block_confirmation,
                    min_height="44px",
                ),
                spacing="3",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


def story_empty() -> rx.Component:
    """No story ad can be made from this piece: no step counter, no dead «Siguiente»,
    just why and the way back to the piece."""
    return rx.vstack(
        page_header(STORY_AD_OPTION),
        page_body(
            card(
                rx.vstack(
                    rx.cond(
                        S.error != "",
                        rx.vstack(
                            callout(S.error, "error"),
                            rx.button(
                                "Volver a consultar",
                                on_click=S.load,
                                variant="outline",
                                min_height="44px",
                            ),
                            spacing="3",
                            align_items="start",
                        ),
                        callout(STORY_EMPTY, "info"),
                    ),
                    rx.link(
                        rx.button(STORY_BACK_TO_PIECE, size="3", min_height="44px"),
                        href=S.piece_href,
                    ),
                    spacing="4",
                    align_items="start",
                    width="100%",
                ),
                width="100%",
            ),
        ),
        spacing="0",
        width="100%",
    )
