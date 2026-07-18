import reflex as rx

from .components import filter_bar, mentions_table, sidebar, stats_row, topbar
from .db import create_db_and_tables
from .state import DashboardState

create_db_and_tables()


def index() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.vstack(
            topbar(),
            stats_row(),
            filter_bar(),
            mentions_table(),
            width="100%",
            spacing="4",
            align_items="start",
        ),
        width="100%",
        spacing="0",
        align_items="start",
    )


app = rx.App()
app.add_page(index, on_load=DashboardState.load_mentions, title="Qualify · Menciones")
