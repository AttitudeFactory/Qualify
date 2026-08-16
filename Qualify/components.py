import reflex as rx

from .state import DashboardState, MentionRow

# (label, icon, route, enabled). Enabled items navigate; disabled show a "pronto"
# badge. The active item is derived from the current route, not a hardcoded flag.
_NAV_ITEMS = [
    ("Menciones", "message-circle", "/", True),
    ("Conexiones", "link", "/connections", True),
    ("Publicar", "upload", "/publish", True),
    ("Contenido", "film", "/inbox", True),
    ("Creadores", "users", "#", False),
    ("Señales", "bell", "#", False),
    ("Configuración", "settings", "#", False),
]


def sidebar() -> rx.Component:
    # `router` is available on any State subclass; DashboardState is already imported.
    current_path = DashboardState.router.page.path

    def nav_item(label: str, icon: str, route: str, enabled: bool) -> rx.Component:
        if not enabled:
            return rx.hstack(
                rx.icon(icon, size=18),
                rx.text(label, size="3"),
                rx.spacer(),
                rx.badge("pronto", variant="soft", color_scheme="gray", size="1"),
                width="100%",
                padding="0.5rem 0.75rem",
                border_radius="0.5rem",
                color=rx.color("gray", 10),
                opacity="0.6",
            )

        active = current_path == route
        return rx.link(
            rx.hstack(
                rx.icon(icon, size=18),
                rx.text(label, size="3"),
                width="100%",
                padding="0.5rem 0.75rem",
                border_radius="0.5rem",
                background=rx.cond(active, rx.color("accent", 4), "transparent"),
                color=rx.cond(active, rx.color("accent", 11), rx.color("gray", 11)),
            ),
            href=route,
            width="100%",
            underline="none",
        )

    return rx.vstack(
        rx.hstack(
            rx.icon("radar", size=22, color=rx.color("accent", 9)),
            rx.heading("Qualify", size="5"),
            padding="1rem 0.75rem",
        ),
        rx.vstack(
            *[nav_item(label, icon, route, enabled) for label, icon, route, enabled in _NAV_ITEMS],
            width="100%",
            spacing="1",
            padding="0 0.5rem",
        ),
        width="220px",
        min_width="220px",
        height="100vh",
        border_right=f"1px solid {rx.color('gray', 5)}",
        position="sticky",
        top="0",
        align_items="start",
    )


def topbar() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.heading("Dashboard de menciones", size="6"),
            rx.text(
                "Menciones de marca en TikTok e Instagram Reels",
                size="2",
                color=rx.color("gray", 10),
            ),
            spacing="0",
            align_items="start",
        ),
        rx.spacer(),
        rx.color_mode.button(),
        width="100%",
        padding="1.5rem 2rem 1rem 2rem",
        align_items="start",
    )


def stat_card(label: str, value: rx.Var, color_scheme: str) -> rx.Component:
    return rx.box(
        rx.text(label, size="2", color=rx.color("gray", 10)),
        rx.heading(value.to_string(), size="7", color=rx.color(color_scheme, 10)),
        padding="1rem 1.25rem",
        border=f"1px solid {rx.color('gray', 5)}",
        border_radius="0.75rem",
        background=rx.color("gray", 2),
        width="100%",
    )


def stats_row() -> rx.Component:
    return rx.grid(
        stat_card("Total menciones", DashboardState.total_mentions, "accent"),
        stat_card("Positivas", DashboardState.positive_count, "grass"),
        stat_card("Neutras", DashboardState.neutral_count, "gray"),
        stat_card("Negativas", DashboardState.negative_count, "tomato"),
        columns="4",
        spacing="3",
        width="100%",
        padding="0 2rem",
    )


def filter_bar() -> rx.Component:
    return rx.hstack(
        rx.select(
            DashboardState.brand_options,
            value=DashboardState.brand_filter,
            on_change=DashboardState.set_brand_filter,
            size="2",
        ),
        rx.select(
            DashboardState.platform_options,
            value=DashboardState.platform_filter,
            on_change=DashboardState.set_platform_filter,
            size="2",
        ),
        rx.select(
            ["Todos", "positive", "neutral", "negative"],
            value=DashboardState.sentiment_filter,
            on_change=DashboardState.set_sentiment_filter,
            size="2",
        ),
        rx.input(
            placeholder="Buscar por caption o creador...",
            value=DashboardState.search_query,
            on_change=DashboardState.set_search_query,
            size="2",
            width="260px",
        ),
        spacing="3",
        padding="1rem 2rem",
        wrap="wrap",
    )


def sentiment_badge(sentiment: rx.Var[str]) -> rx.Component:
    return rx.match(
        sentiment,
        ("positive", rx.badge("Positiva", color_scheme="grass", variant="soft")),
        ("negative", rx.badge("Negativa", color_scheme="tomato", variant="soft")),
        rx.badge("Neutra", color_scheme="gray", variant="soft"),
    )


def platform_badge(platform: rx.Var[str]) -> rx.Component:
    return rx.match(
        platform,
        ("tiktok", rx.badge("TikTok", variant="outline", color_scheme="purple")),
        rx.badge("Instagram", variant="outline", color_scheme="pink"),
    )


def mention_row(mention: MentionRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(mention.posted_at, white_space="nowrap"),
        rx.table.cell(platform_badge(mention.platform)),
        rx.table.cell(mention.brand),
        rx.table.cell(mention.creator_handle),
        rx.table.cell(
            mention.caption,
            max_width="360px",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        rx.table.cell(sentiment_badge(mention.sentiment)),
        rx.table.cell(mention.views.to_string(), text_align="right"),
        rx.table.cell(mention.likes.to_string(), text_align="right"),
    )


def mentions_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Fecha"),
                    rx.table.column_header_cell("Plataforma"),
                    rx.table.column_header_cell("Marca"),
                    rx.table.column_header_cell("Creador"),
                    rx.table.column_header_cell("Caption"),
                    rx.table.column_header_cell("Sentiment"),
                    rx.table.column_header_cell("Vistas", text_align="right"),
                    rx.table.column_header_cell("Likes", text_align="right"),
                )
            ),
            rx.table.body(
                rx.foreach(DashboardState.filtered_mentions, mention_row),
            ),
            variant="surface",
            width="100%",
        ),
        padding="0 2rem 2rem 2rem",
        overflow_x="auto",
        width="100%",
    )
