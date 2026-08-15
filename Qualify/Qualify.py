import reflex as rx

from .components import filter_bar, mentions_table, sidebar, stats_row, topbar
from .connections_page import connections_index
from .connections_state import ConnectionsState
from .db import create_db_and_tables
from .inbox_page import inbox_index
from .inbox_state import InboxState
from .publishing_page import publish_index
from .publishing_state import PublishState
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
app.add_page(
    connections_index,
    route="/connections",
    on_load=ConnectionsState.load_connections,
    title="Qualify · Conexiones",
)
app.add_page(
    publish_index,
    route="/publish",
    on_load=PublishState.load_active_connections,
    title="Qualify · Publicar",
)
app.add_page(
    inbox_index,
    route="/inbox",
    on_load=InboxState.load_screen,
    title="Qualify · Contenido",
)
