"""A link to preparation, never a claim that the source is eligible or a paid action."""

from __future__ import annotations

import reflex as rx


def promotion_event_query(query: rx.Var[str], event_id: rx.Var[str]) -> rx.Var[str]:
    """Keep a published calendar source bound while preserving the week return address."""
    return query + "&evento=" + event_id


def promotion_link(
    piece_id: rx.Var[str],
    *,
    query: rx.Var[str] | str = "",
    label: rx.Var[str] | str = "Promocionar",
) -> rx.Component:
    return rx.link(
        rx.button(
            rx.icon("megaphone", size=16),
            label,
            variant="outline",
            size="2",
            min_height="44px",
        ),
        href="/drafts/" + piece_id + "/promote" + query,
    )
