import reflex as rx

from .clarity_page import clarity_index
from .clarity_state import ClarityState
from .components import filter_bar, mentions_table, sidebar, stats_row, topbar
from .connections_page import connections_index
from .connections_state import ConnectionsState
from .db import create_db_and_tables
from .inbox_page import inbox_index
from .inbox_state import InboxState
from .leads_page import leads_index
from .leads_state import LeadsState
from .publishing_page import publish_index
from .publishing_state import PublishState
from .state import DashboardState
from .vitrina_page import vitrina_index

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
app.add_page(
    leads_index,
    route="/leads",
    on_load=LeadsState.load_leads,
    title="Qualify · Leads",
)
app.add_page(
    clarity_index,
    route="/clarity",
    on_load=ClarityState.load,
    title="Qualify · Clarity",
)
# UI demo, no backend: no on_load because there is nothing to load.
app.add_page(vitrina_index, route="/vitrina", title="Qualify · Vitrina de locales")
