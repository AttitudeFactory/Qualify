"""The final is confirmed here, with its exact object visible, never on a card."""

from __future__ import annotations

import reflex as rx

from .final_review_state import FinalReviewState as S
from .r2_media import BACKEND_BASE
from .ui import callout, drawer, skeleton_card, tone_badge
from .ui import tokens as T


def final_review_panel() -> rx.Component:
    p = S.panel
    body = rx.vstack(
        rx.button(
            rx.icon("chevron-left", size=16),
            "Volver a Tu semana",
            variant="ghost",
            min_height="44px",
            on_click=S.close,
            id="q-final-review-close",
        ),
        rx.cond(S.error != "", callout(S.error, "error")),
        rx.cond(S.success != "", callout(S.success, "ok")),
        rx.cond(
            S.loading,
            skeleton_card(5),
            rx.vstack(
                rx.heading(p.title, size="5", as_="h2"),
                rx.match(
                    p.tone,
                    ("ok", tone_badge(p.badge, "ok")),
                    ("error", tone_badge(p.badge, "error")),
                    ("warn", tone_badge(p.badge, "warn")),
                    tone_badge(p.badge, "neutral"),
                ),
                rx.text(p.note, size="2"),
                rx.foreach(
                    p.videos,
                    lambda video: rx.video(
                        src=BACKEND_BASE + video.url,
                        controls=True,
                        preload="metadata",
                        aria_label=video.label,
                        width="100%",
                        max_height="55vh",
                        style={"object_fit": "contain"},
                    ),
                ),
                rx.text(p.date_note, size="2", weight="medium"),
                rx.cond(p.other_version_pending != "", callout(p.other_version_pending, "info")),
                rx.cond(
                    p.state == "other_version",
                    rx.link(
                        rx.button(
                            "Revisar la nueva vista previa", variant="soft", min_height="44px"
                        ),
                        href="/drafts/" + p.piece_id,
                    ),
                ),
                spacing="3",
                width="100%",
                align_items="start",
            ),
        ),
        spacing="3",
        width="100%",
    )
    footer = rx.vstack(
        rx.cond(
            p.can_confirm,
            rx.button(
                p.confirm_label,
                on_click=S.confirm,
                loading=S.busy,
                disabled=S.busy,
                size="3",
                width="100%",
                min_height="44px",
            ),
        ),
        rx.cond(
            p.can_retry,
            rx.button(
                "Intentar de nuevo",
                on_click=S.retry,
                loading=S.busy,
                size="3",
                width="100%",
                min_height="44px",
            ),
        ),
        rx.cond(
            (p.piece_id != "") & (p.state != "other_version"),
            rx.button(
                rx.cond(p.event_id != "", "Elegir otra hora", "Elegir día y hora"),
                variant="soft",
                on_click=S.choose_time,
                disabled=S.busy,
                size="3",
                width="100%",
                min_height="44px",
            ),
        ),
        rx.cond(
            (p.state == "final_ready") | (p.state == "final"),
            rx.vstack(
                rx.button(
                    "Pedir otra versión",
                    variant="soft",
                    on_click=S.another,
                    disabled=~p.can_another | S.busy,
                    size="3",
                    width="100%",
                    min_height="44px",
                ),
                rx.text(p.another_note, size="1", color=T.TEXT_MUTED),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            S.success != "",
            rx.button(
                p.next_label,
                variant="soft",
                on_click=S.next_review,
                size="3",
                width="100%",
                min_height="44px",
            ),
        ),
        spacing="2",
        width="100%",
    )
    panel = drawer(
        body,
        open=S.open,
        on_open_change=S.change_open,
        title="Revisa el video final",
        icon="clapperboard",
        description="Míralo y decide si sale con el nombre de tu marca.",
        footer=footer,
        width="36rem",
    )

    return rx.fragment(panel, rx.cond(S.open, rx.box(on_mount=S.remember_history)))
