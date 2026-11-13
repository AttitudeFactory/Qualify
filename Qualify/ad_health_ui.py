"""Read-only account observations with a direct, safe next action."""

from __future__ import annotations

import reflex as rx

from .ad_health_vm import AccountHealthVM
from .ui import tokens as T
from .ui import tone_badge


def health_status(health: AccountHealthVM) -> rx.Component:
    return rx.match(
        health.tone,
        ("ok", tone_badge(health.label, "ok")),
        ("error", tone_badge(health.label, "error")),
        tone_badge(health.label, "warn"),
    )


def billing_link(health: AccountHealthVM) -> rx.Component:
    return rx.cond(
        (health.action_url != "") & (health.action_label != ""),
        rx.link(
            health.action_label,
            href=health.action_url,
            is_external=True,
            min_height="44px",
            display="inline-flex",
            align_items="center",
        ),
        rx.fragment(),
    )


def health_details(health: AccountHealthVM) -> rx.Component:
    return rx.vstack(
        health_status(health),
        rx.text(health.reason, size="2", overflow_wrap="anywhere"),
        rx.cond(
            health.refresh_failed,
            rx.text(
                "No pudimos actualizar el estado. La fecha corresponde "
                "a la última consulta correcta.",
                size="2",
                color=T.TEXT_MUTED,
            ),
        ),
        rx.cond(
            health.disable_reason_label != "",
            rx.text(health.disable_reason_label, size="2", color=T.TEXT_MUTED),
            rx.fragment(),
        ),
        rx.text("Última comprobación: " + health.checked_label, size="1", color=T.TEXT_MUTED),
        rx.cond(
            health.stale,
            rx.text("Actualiza el estado antes de anunciar.", size="2", color=T.TEXT_MUTED),
            rx.fragment(),
        ),
        rx.cond(
            (health.amount_spent_label != "") | (health.spend_cap_label != ""),
            rx.el.details(
                rx.el.summary("Gasto y límite de la cuenta", min_height="44px", cursor="pointer"),
                rx.vstack(
                    rx.cond(
                        health.amount_spent_label != "",
                        rx.text("Gasto informado por Meta: " + health.amount_spent_label, size="2"),
                    ),
                    rx.cond(
                        health.spend_cap_label != "",
                        rx.text("Límite de la cuenta: " + health.spend_cap_label, size="2"),
                    ),
                    rx.text(
                        "Estos importes corresponden a la cuenta, "
                        "no al presupuesto de esta promoción.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="2",
                    padding_top="0.5rem",
                ),
                width="100%",
            ),
            rx.fragment(),
        ),
        billing_link(health),
        spacing="2",
        align_items="start",
        width="100%",
    )
