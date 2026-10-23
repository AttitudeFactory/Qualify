"""Small view helpers shared by the WA-18 tabs of `/whatsapp` (Plantillas, Contactos,
Campañas) and the Conexión metrics block.

They mirror `whatsapp_page.tone_pill`/`banner`/`retry_button`/`_field`, which cannot be
imported from here: `whatsapp_page` imports these tabs, so the reverse import would be
circular. Same rules: a state is a TONE through `signal_pill`/`callout`, never a raw
Radix colour (docs/design-system.md §5.2).
"""

from __future__ import annotations

from typing import Any

import reflex as rx

from .ui import callout, signal_pill, tone_badge
from .ui import tokens as T

_TONES = ("ok", "warn", "error", "info", "neutral")


def tone_pill(label: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """`signal_pill` for a tone that is a Var (the VM decides it per row)."""
    return rx.match(
        tone,
        *[(t, signal_pill(label, t)) for t in _TONES[:-1]],
        signal_pill(label, "neutral"),
    )


def tone_tag(label: rx.Var[str], tone: rx.Var[str], icon: str | None = None) -> rx.Component:
    """`tone_badge` for a Var tone — a cell that must be scanned."""
    return rx.match(
        tone,
        *[(t, tone_badge(label, t, icon=icon)) for t in _TONES[:-1]],
        tone_badge(label, "neutral", icon=icon),
    )


def tone_banner(message: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """A `callout` in a Var tone, shown only when there is a message."""
    return rx.cond(
        message != "",
        rx.match(
            tone,
            *[(t, callout(message, t)) for t in _TONES[:-1]],
            callout(message, "neutral"),
        ),
        rx.fragment(),
    )


def field(label: str, control: rx.Component, hint: str | rx.Var | None = None) -> rx.Component:
    """Visible label above, help below (docs/design-system.md §5.6)."""
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        *([rx.text(hint, size="1", color=T.TEXT_MUTED)] if hint is not None else []),
        spacing="1",
        width="100%",
        align_items="start",
    )


def ghost_refresh(label: str, on_click: Any, loading: rx.Var[bool] | bool = False) -> rx.Component:
    return rx.button(
        rx.icon("refresh-cw", size=T.ICON_SM),
        label,
        on_click=on_click,
        loading=loading,
        variant="ghost",
        size="1",
        **T.tone_scheme("neutral"),
    )


def retry_button(label: str, on_click: Any) -> rx.Component:
    """Shown in place of a tab's content when its read failed (the banner says why)."""
    return rx.button(
        rx.icon("refresh-cw", size=T.ICON_SM),
        label,
        on_click=on_click,
        variant="soft",
        size="2",
        **T.tone_scheme("neutral"),
    )


def confirm_action(
    trigger: rx.Component,
    *,
    title: str,
    description: str | rx.Var | rx.Component,
    verb: str,
    on_confirm: Any,
    tone: str = "error",
    dismiss: str | rx.Var = "Cancelar",
) -> rx.Component:
    """Destructive or irreversible action: alert dialog with the same verb on the title,
    the button and the toast (docs/design-system.md §6.2)."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(trigger),
        rx.alert_dialog.content(
            rx.alert_dialog.title(title),
            rx.alert_dialog.description(description, size="2"),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button(dismiss, variant="soft", **T.tone_scheme("neutral")),
                ),
                rx.alert_dialog.action(
                    rx.button(verb, on_click=on_confirm, **T.tone_scheme(tone)),
                ),
                spacing="3",
                margin_top="1rem",
                justify="end",
            ),
        ),
    )


def section_head(title: str, *actions: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.heading(title, size="3", as_="h2"),
        rx.spacer(),
        *actions,
        width="100%",
        align="center",
        wrap="wrap",
        spacing="2",
    )
