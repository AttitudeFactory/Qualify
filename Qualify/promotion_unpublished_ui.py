"""The unpublished-piece steps of the promotion wizard (m-24828982): the piece's own
4:5 and 9:16 files, the ad's text, one country, and a review with both previews."""

from __future__ import annotations

import reflex as rx

from .connections_state import SUPPORT_QUERY_PARAM
from .promotion_state import PromotionState as S
from .promotion_vm import COUNTRY_LABELS, VIDEO_WAITING, WEBSITE_CTA_LABELS, AdMediaVM
from .r2_media import BACKEND_BASE
from .ui import callout, card, choice_card, choice_card_check, signal_pill
from .ui import tokens as T

PLACEMENTS_NOTE = (
    "Se mostrará solo en Instagram: la versión del perfil en el inicio y en el perfil, "
    "y la vertical de pantalla completa en historias y reels."
)


def _thumb(media: rx.Var[AdMediaVM], ratio: str) -> rx.Component:
    return rx.cond(
        media.url != "",
        rx.cond(
            media.media_type == "video",
            rx.el.video(
                src=BACKEND_BASE + media.url,
                muted=True,
                plays_inline=True,
                preload="metadata",
                aria_label=media.label,
                width="100%",
                style={"aspectRatio": ratio, "objectFit": "cover", "borderRadius": "8px"},
            ),
            rx.image(
                src=BACKEND_BASE + media.url,
                alt=media.label,
                width="100%",
                style={"aspectRatio": ratio, "objectFit": "cover", "borderRadius": "8px"},
            ),
        ),
        rx.center(
            rx.text("Vista no disponible", size="1", color=T.TEXT_MUTED),
            width="100%",
            style={"aspectRatio": ratio},
            border=T.BORDER,
            border_radius="8px",
        ),
    )


def _media_choice(media: rx.Var[AdMediaVM], slot: str, ratio: str) -> rx.Component:
    selected = getattr(S.form, slot) == media.id
    return choice_card(
        rx.vstack(
            rx.flex(
                rx.text(media.label, weight="medium", size="2"),
                rx.cond(selected, choice_card_check()),
                justify="between",
                align="center",
                width="100%",
            ),
            _thumb(media, ratio),
            rx.cond(selected, rx.text("Elegida", size="1", color=T.TEXT_MUTED)),
            spacing="2",
            width="100%",
        ),
        selected=selected,
        on_select=S.choose_media(slot, media.id),
        disabled=S.busy,
        padding="0.75rem",
        width="100%",
        text_align="left",
    )


def _media_group(
    heading: str, detail: str, options: rx.Var, slot: str, ratio: str, label_id: str
) -> rx.Component:
    return rx.vstack(
        rx.heading(heading, size="3", as_="h2", id=label_id),
        rx.text(detail, size="2", color=T.TEXT_MUTED),
        rx.grid(
            rx.foreach(options, lambda media: _media_choice(media, slot, ratio)),
            columns=rx.breakpoints(initial="2", sm="3"),
            gap="3",
            width="100%",
            role="radiogroup",
            aria_labelledby=label_id,
        ),
        spacing="2",
        width="100%",
    )


def unpublished_images() -> rx.Component:
    source = S.selected_source
    return rx.vstack(
        rx.text(
            "Ya elegimos las imágenes de la pieza. Cámbialas si prefieres otras.",
            color=T.TEXT_MUTED,
        ),
        _media_group(
            "Para el perfil",
            "Aparece en el inicio y en el perfil.",
            source.feed_media,
            "feed_asset_id",
            "4 / 5",
            "feed-image-label",
        ),
        _media_group(
            "Vertical de pantalla completa",
            "Aparece en historias y reels.",
            source.vertical_media,
            "vertical_asset_id",
            "9 / 16",
            "vertical-image-label",
        ),
        spacing="5",
        width="100%",
    )


def unpublished_feed_video() -> rx.Component:
    return rx.vstack(
        rx.text("Es el que verá la gente en el inicio y en el perfil.", color=T.TEXT_MUTED),
        _media_group(
            "Videos de la pieza para el perfil",
            "Elige uno.",
            S.selected_source.feed_media,
            "feed_asset_id",
            "4 / 5",
            "feed-video-label",
        ),
        spacing="4",
        width="100%",
    )


def unpublished_vertical_video() -> rx.Component:
    return rx.vstack(
        rx.text("Es el que verá la gente en historias y reels.", color=T.TEXT_MUTED),
        _media_group(
            "Videos verticales de la pieza",
            "Elige uno.",
            S.selected_source.vertical_media,
            "vertical_asset_id",
            "9 / 16",
            "vertical-video-label",
        ),
        spacing="4",
        width="100%",
    )


def unpublished_covers() -> rx.Component:
    source = S.selected_source
    return rx.vstack(
        rx.text(
            "La portada es la imagen que se ve antes de que empiece el video. "
            "Ya elegimos una de la pieza para cada video.",
            color=T.TEXT_MUTED,
        ),
        _media_group(
            "Portada del video para el perfil",
            "",
            source.feed_covers,
            "feed_cover_id",
            "4 / 5",
            "feed-cover-label",
        ),
        _media_group(
            "Portada del video vertical",
            "",
            source.vertical_covers,
            "vertical_cover_id",
            "9 / 16",
            "vertical-cover-label",
        ),
        spacing="5",
        width="100%",
    )


def _text_field(label: str, name: str, value: rx.Var[str], hint: str, **props) -> rx.Component:
    field_id = "promotion-" + name
    control = rx.text_area if name == "message" else rx.input
    return rx.vstack(
        rx.el.label(label, html_for=field_id, font_weight="500"),
        control(
            id=field_id,
            value=value,
            on_change=lambda text: S.edit(name, text),
            disabled=S.busy,
            size="3",
            width="100%",
            **props,
        ),
        rx.text(hint, size="2", color=T.TEXT_MUTED),
        spacing="2",
        width="100%",
    )


def unpublished_text() -> rx.Component:
    return card(
        rx.vstack(
            _text_field(
                "Texto del anuncio",
                "message",
                S.form.message,
                "Lo tomamos de la pieza. Hasta 2.200 caracteres.",
                rows="5",
            ),
            _text_field(
                "Título",
                "headline",
                S.form.headline,
                "Una frase corta. Hasta 100 caracteres.",
                min_height="44px",
            ),
            _text_field(
                "Página que abrirá el anuncio",
                "link_url",
                S.form.link_url,
                "Revisa que lleve a lo que ofreces en esta pieza.",
                placeholder="https://tu-negocio.com",
                type="url",
                min_height="44px",
            ),
            rx.vstack(
                rx.heading("Botón del anuncio", size="3", as_="h2", id="unpublished-cta-label"),
                rx.text("Ya viene el que guardaste en la pieza.", size="2", color=T.TEXT_MUTED),
                rx.vstack(
                    *[
                        choice_card(
                            rx.text(label, weight="medium"),
                            selected=S.form.cta_type == code,
                            on_select=S.choose_cta(code),
                            disabled=S.busy,
                            min_height="44px",
                            width="100%",
                            text_align="left",
                        )
                        for code, label in WEBSITE_CTA_LABELS.items()
                    ],
                    role="radiogroup",
                    aria_labelledby="unpublished-cta-label",
                    spacing="2",
                    width="100%",
                ),
                spacing="2",
                width="100%",
            ),
            spacing="4",
            width="100%",
        ),
        width="100%",
    )


def unpublished_country() -> rx.Component:
    return rx.vstack(
        rx.text("Meta mostrará el anuncio a personas de ese país.", color=T.TEXT_MUTED),
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
            aria_label="País",
            spacing="2",
            width="100%",
        ),
        callout(PLACEMENTS_NOTE, "info"),
        spacing="4",
        width="100%",
    )


def _fact(label: str, value: rx.Var[str] | str) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="1", color=T.TEXT_MUTED),
        rx.text(value, size="2", overflow_wrap="anywhere", white_space="pre-wrap"),
        spacing="1",
        width="100%",
    )


def _preview(title: str, url: rx.Var[str], height: str) -> rx.Component:
    return rx.vstack(
        rx.text(title, weight="medium"),
        rx.el.iframe(
            src=url,
            title="Vista previa de Meta: " + title,
            sandbox="",
            referrer_policy="no-referrer",
            width="100%",
            height=height,
            loading="lazy",
        ),
        spacing="2",
        width="100%",
    )


def _chosen(title: str, media: rx.Var[AdMediaVM], ratio: str) -> rx.Component:
    return rx.vstack(
        rx.text(title, size="1", color=T.TEXT_MUTED),
        _thumb(media, ratio),
        spacing="1",
        width="100%",
    )


def _files() -> rx.Component:
    """The piece's files the ad will use, also when a single file skipped its step;
    covers (prefilled) change here instead of on a step of their own."""
    video = S.form.media_kind == "videos"
    return card(
        rx.vstack(
            rx.heading("Archivos de la pieza", size="3", as_="h2"),
            rx.grid(
                _chosen("Para el perfil", S.chosen_feed, "4 / 5"),
                _chosen("Vertical", S.chosen_vertical, "9 / 16"),
                rx.cond(video, _chosen("Portada del perfil", S.chosen_feed_cover, "4 / 5")),
                rx.cond(video, _chosen("Portada vertical", S.chosen_vertical_cover, "9 / 16")),
                columns=rx.breakpoints(initial="2", md="4"),
                gap="3",
                width="100%",
                align_items="end",
            ),
            rx.cond(
                video & ~S.paid_operation_locked,
                rx.button(
                    rx.cond(S.covers_open, "Listo", "Cambiar portada"),
                    on_click=S.toggle_covers,
                    disabled=S.busy,
                    variant="outline",
                    min_height="44px",
                ),
            ),
            rx.cond(video & S.covers_open, unpublished_covers()),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def _help() -> rx.Component:
    return rx.vstack(
        rx.text("El anuncio no se activó y no se hizo ningún cobro.", size="2"),
        rx.link(
            rx.button(
                rx.icon("life-buoy", size=15),
                "Pedir ayuda 1:1",
                variant="soft",
                min_height="44px",
                **T.tone_scheme("neutral"),
            ),
            # The same «Pedir ayuda 1:1» drawer as Tus redes (QUA-202), opened on arrival.
            href=f"/connections?{SUPPORT_QUERY_PARAM}=1",
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def review_states() -> rx.Component:
    """What blocks the review: the account, a video Meta still prepares, or help."""
    return rx.fragment(
        rx.cond(S.execution_reason != "", callout(S.execution_reason, "warn")),
        rx.cond(
            S.video_waiting,
            card(
                rx.vstack(
                    signal_pill("Video en preparación", "info"),
                    rx.text(VIDEO_WAITING, weight="medium"),
                    spacing="2",
                    align_items="start",
                    width="100%",
                ),
                width="100%",
            ),
        ),
        rx.cond(S.needs_help, _help()),
    )


def ad_status_pill() -> rx.Component:
    return rx.cond(
        ~S.paid_operation_locked,
        signal_pill("Anuncio en pausa", "info"),
        rx.cond(
            S.result.status == "active",
            signal_pill("Activación solicitada a Meta", "info"),
            signal_pill("Activación por comprobar", "warn"),
        ),
    )


def unpublished_review() -> rx.Component:
    return rx.vstack(
        review_states(),
        # The ad itself first: nobody authorizes without having seen it.
        rx.cond(
            S.has_remote_review,
            rx.vstack(
                ad_status_pill(),
                rx.grid(
                    _preview("En el inicio y el perfil", S.review.preview_url, "520px"),
                    _preview("En historias y reels", S.review.vertical_preview_url, "640px"),
                    columns=rx.breakpoints(initial="1", md="2"),
                    gap="4",
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            rx.cond(
                ~S.video_waiting & ~S.needs_help,
                callout(
                    "Este es el resumen. No activa el anuncio: primero lo creamos en pausa "
                    "para que veas cómo queda en el perfil y en historias.",
                    "info",
                ),
            ),
        ),
        _files(),
        card(
            rx.vstack(
                _fact("Dónde aparece", PLACEMENTS_NOTE),
                _fact("Instagram", S.selected_source.account_label),
                _fact("Cuenta para anuncios", S.selected_source.account_name),
                _fact("Texto", S.form.message),
                _fact("Título", S.form.headline),
                _fact("Botón", S.button_label),
                _fact("Página de destino", S.form.link_url),
                _fact("País", S.country_label),
                _fact("Presupuesto para todo el período", S.budget_label),
                _fact("Inicio", S.start_label),
                _fact("Final", S.end_label),
                _fact("Horario", S.zone_label),
                _fact("Cambios automáticos de Meta", "Apagados"),
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
                    "Revisé las dos vistas y autorizo el presupuesto total indicado.",
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
