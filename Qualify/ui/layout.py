"""Layout primitives: the app shell every business page is built from.

    app_shell(
        page_header("Leads", "Personas captadas por tu funnel"),
        page_body(...),
    )

Three guarantees the shell gives a screen for free, so no page re-implements them:

* the sidebar (with the active item derived from the route),
* the header row with the session badge + colour-mode toggle in a fixed position,
* the horizontal gutter (``tokens.PAGE_X``), responsive through CSS.

Reference: docs/design-system.md §4.
"""

from __future__ import annotations

from collections.abc import Sequence

import reflex as rx

from ..auth_state import AuthState
from ..state import DashboardState
from . import tokens as T

# (label, lucide icon, route, enabled). Enabled items navigate; disabled ones show a
# "pronto" badge. The active item is derived from the current route, never hardcoded.
NAV_ITEMS: list[tuple[str, str, str, bool]] = [
    ("Menciones", "message-circle", "/", True),
    ("Conexiones", "link", "/connections", True),
    ("Publicar", "upload", "/publish", True),
    ("Marca", "palette", "/brand", True),
    ("Crear pieza", "wand-sparkles", "/create", True),
    ("Borradores", "layout-list", "/drafts", True),
    ("Contenido", "film", "/inbox", True),
    ("Leads", "user-plus", "/leads", True),
    ("Clarity", "activity", "/clarity", True),
    ("Vitrina", "store", "/vitrina", True),
    ("Creadores", "users", "#", False),
    ("Señales", "bell", "#", False),
    ("Configuración", "settings", "#", False),
]


def brand_mark(size: int = 22, heading_size: str = "5") -> rx.Component:
    """The wordmark: radar icon in accent + "Qualify". Same everywhere it appears."""
    return rx.hstack(
        rx.icon("radar", size=size, color=rx.color("accent", 9)),
        # A text, not a heading: the wordmark must not enter the page outline as an h1.
        rx.text("Qualify", size=heading_size, weight="bold", letter_spacing="-0.02em"),
        align="center",
        spacing="2",
    )


def _nav_item(label: str, icon: str, route: str, enabled: bool) -> rx.Component:
    if not enabled:
        return rx.hstack(
            rx.icon(icon, size=T.ICON_MD),
            rx.text(label, size="3"),
            rx.spacer(),
            rx.badge("pronto", variant="soft", color_scheme="gray", size="1"),
            width="100%",
            padding="0.5rem 0.75rem",
            border_radius=T.RADIUS_CONTROL,
            color=T.TEXT_MUTED,
            opacity="0.6",
            aria_disabled="true",
        )

    active = DashboardState.router.page.path == route
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=T.ICON_MD),
            rx.text(label, size="3", weight=rx.cond(active, "medium", "regular")),
            width="100%",
            padding="0.5rem 0.75rem",
            border_radius=T.RADIUS_CONTROL,
            background=rx.cond(active, rx.color("accent", 4), "transparent"),
            color=rx.cond(active, rx.color("accent", 11), rx.color("gray", 11)),
            class_name="q-nav-item",
        ),
        href=route,
        width="100%",
        underline="none",
        aria_current=rx.cond(active, "page", ""),
    )


LANDING_URL = "https://attitudefactory.co/qualify"


def tenant_block() -> rx.Component:
    """Top of the sidebar: the business owns the screen. Its name first, then the
    "Supported by Qualify" line with the mark, linking to the landing. When there is no
    session (e.g. `/design`) the name falls back to "Qualify" so the block never reads
    empty."""
    name = rx.cond(AuthState.business_name != "", AuthState.business_name, "Qualify")
    return rx.vstack(
        rx.hstack(
            rx.icon("store", size=T.ICON_MD, color=rx.color("accent", 9)),
            # A text, not a heading: the wordmark must not enter the page outline.
            rx.text(
                name,
                size="4",
                weight="bold",
                letter_spacing="-0.02em",
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
            ),
            align="center",
            spacing="2",
            width="100%",
            min_width="0",
        ),
        rx.link(
            rx.hstack(
                rx.text("Supported by", size="1", color=T.TEXT_MUTED),
                rx.icon("radar", size=T.ICON_SM, color=rx.color("accent", 9)),
                rx.text("Qualify", size="1", weight="medium", color=rx.color("accent", 11)),
                align="center",
                spacing="1",
            ),
            href=LANDING_URL,
            is_external=True,
            underline="none",
            aria_label="Qualify — ir al sitio",
        ),
        spacing="1",
        align_items="start",
        padding="1rem 0.75rem 0.75rem",
        width="100%",
    )


def logout_action() -> rx.Component:
    """Bottom of the sidebar. There is no tenant switch (`1 login = 1 tenant`): changing
    business = logout + login, so this is the only session control in the app."""
    return rx.box(
        rx.button(
            rx.icon("log-out", size=T.ICON_MD),
            "Salir",
            variant="ghost",
            color_scheme="gray",
            size="2",
            width="100%",
            justify_content="start",
            on_click=AuthState.logout,
        ),
        width="100%",
        padding="0.75rem 0.5rem",
        border_top=T.BORDER,
    )


def sidebar() -> rx.Component:
    return rx.el.nav(
        rx.vstack(
            tenant_block(),
            rx.vstack(
                *[_nav_item(*item) for item in NAV_ITEMS],
                width="100%",
                spacing="1",
                padding="0 0.5rem",
            ),
            rx.spacer(),
            logout_action(),
            width="100%",
            height="100%",
            align_items="start",
            spacing="0",
        ),
        aria_label="Secciones",
        width=T.SIDEBAR_W,
        min_width=T.SIDEBAR_W,
        height="100vh",
        border_right=T.BORDER,
        position="sticky",
        top="0",
        flex_shrink="0",
    )


def session_badge() -> rx.Component:
    """Kept for import compatibility; the session now lives in the sidebar
    (`tenant_block` on top, `logout_action` at the bottom). Renders nothing."""
    return rx.fragment()


def page_header(
    title: str | rx.Var,
    subtitle: str | rx.Var | None = None,
    *actions: rx.Component,
    badge: rx.Component | None = None,
    show_session: bool = False,
) -> rx.Component:
    """Title row of a business page.

    ``actions`` render right-aligned, in the order given, before the colour-mode toggle.
    ``badge`` sits next to the title — for a state that describes the whole page ("demo",
    a count), never for an action. ``show_session`` is accepted for compatibility and
    ignored: the session lives in the sidebar (name on top, "Salir" at the bottom).
    """
    title_row = rx.hstack(
        rx.heading(title, size="6", as_="h1"),
        *([badge] if badge is not None else []),
        align="center",
        spacing="2",
    )
    title_block = rx.vstack(
        title_row,
        *([rx.text(subtitle, size="2", color=T.TEXT_MUTED)] if subtitle is not None else []),
        spacing="1",
        align_items="start",
    )
    right: list[rx.Component] = list(actions)
    right.append(rx.color_mode.button())
    return rx.hstack(
        title_block,
        rx.spacer(),
        *right,
        width="100%",
        padding=T.PAD_HEADER,
        align="center",
        spacing="3",
        wrap="wrap",
    )


def page_body(*children: rx.Component, spacing: str = "4") -> rx.Component:
    """The gutter every block below the header shares. Stack children vertically."""
    return rx.vstack(
        *children,
        width="100%",
        max_width=T.CONTENT_MAX,
        spacing=spacing,
        align_items="start",
        padding=T.PAD_BODY,
    )


def app_shell(*children: rx.Component, spacing: str = "0") -> rx.Component:
    """Sidebar + main column. Pass ``page_header`` first, then the body blocks."""
    return rx.hstack(
        sidebar(),
        rx.el.main(
            rx.vstack(
                *children,
                width="100%",
                spacing=spacing,
                align_items="start",
            ),
            flex="1",
            min_width="0",
        ),
        width="100%",
        spacing="0",
        align_items="start",
    )


def section(
    title: str | rx.Var,
    *children: rx.Component,
    description: str | rx.Var | None = None,
    actions: Sequence[rx.Component] = (),
    spacing: str = "3",
) -> rx.Component:
    """A titled block inside ``page_body``: h2 + optional description + actions on the
    right, then its content. Use it instead of ad-hoc ``rx.heading(size="4")`` rows."""
    return rx.vstack(
        rx.hstack(
            rx.vstack(
                rx.heading(title, size="4", as_="h2"),
                *(
                    [rx.text(description, size="2", color=T.TEXT_MUTED)]
                    if description is not None
                    else []
                ),
                spacing="1",
                align_items="start",
            ),
            rx.spacer(),
            *actions,
            width="100%",
            align="center",
            spacing="3",
        ),
        *children,
        width="100%",
        spacing=spacing,
        align_items="start",
    )
