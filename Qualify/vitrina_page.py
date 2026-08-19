"""The "Vitrina de locales" page — a UI demo, not a product surface.

What it is for: showing the owner of a microcentro comercial what their vacant
stalls would look like published with the data only they have. Nothing here
talks to a backend; see `vitrina_data` for why the numbers are hardcoded.

Chart decisions worth keeping if this ever grows a backend:

* The flow chart is a single series of magnitudes over time, so it uses one hue
  (the theme accent) and carries no legend — the title names the series. A
  categorical palette here would invent four identities the data does not have.
* Audience shares are direct-labeled rows rather than a stacked bar, so identity
  never rests on colour alone and no four-colour palette needs validating.
* The kitchen verdict uses status colour *plus* an icon *plus* a word. The
  three-state case ("desconocido") is the reason: a colour-only encoding would
  read as a soft "no", which is exactly the wrong answer.
"""

import reflex as rx

from . import vitrina_data as D
from .ui import app_shell, page_header
from .ui import tokens as T
from .vitrina_state import (
    HuecoRow,
    LocalCard,
    PublicoRow,
    RequisitoRow,
    VecinoRow,
    VitrinaState,
)

# Same recipe as `ui.card`, spread into `rx.box(**_CARD)` because these blocks build
# their children before the container.
_CARD = {
    "border": T.BORDER,
    "border_radius": T.RADIUS_CARD,
    "background": T.SURFACE_BG,
    "padding": "1.25rem",
    "width": "100%",
}

# Every block below the header shares the page gutter; the vertical rhythm is per block.
_GUTTER_TOP = f"1rem {T.PAGE_X} 0 {T.PAGE_X}"
_GUTTER_TOP_LG = f"1.5rem {T.PAGE_X} 0 {T.PAGE_X}"
_GUTTER_BOTTOM = f"1rem {T.PAGE_X} 2rem {T.PAGE_X}"


def _topbar() -> rx.Component:
    return page_header(
        D.MICROCENTRO,
        f"{D.LEMA} · {D.DIRECCION}",
        badge=rx.badge("demo", color_scheme="amber", variant="soft", size="1"),
    )


def _disclaimer() -> rx.Component:
    return rx.box(
        rx.callout(
            D.DISCLAIMER,
            icon="triangle_alert",
            color_scheme="amber",
            variant="surface",
            size="1",
        ),
        padding=f"0 {T.PAGE_X}",
        width="100%",
    )


def _resumen_card(row: PublicoRow) -> rx.Component:
    return rx.box(
        rx.text(row.nombre, size="2", color=T.TEXT_MUTED),
        rx.text(row.share_label, size="6", weight="bold", class_name="q-nums"),
        rx.text(row.nota, size="1", color=T.TEXT_FAINT),
        **_CARD,
    )


def _resumen() -> rx.Component:
    return rx.grid(
        rx.foreach(VitrinaState.resumen, _resumen_card),
        columns=rx.breakpoints(initial="1", sm="2", lg="4"),
        spacing="3",
        width="100%",
        padding=_GUTTER_TOP,
    )


# -- local picker ----------------------------------------------------------


def _apto_badge(apto: rx.Var[str], label: rx.Var[str]) -> rx.Component:
    """Status, never colour-alone: icon + word, in all three states."""
    return rx.match(
        apto,
        (
            "si",
            rx.badge(
                rx.icon("flame", size=13), label, color_scheme="grass", variant="soft", size="1"
            ),
        ),
        (
            "no",
            rx.badge(
                rx.icon("snowflake", size=13), label, color_scheme="gray", variant="soft", size="1"
            ),
        ),
        rx.badge(
            rx.icon("circle_help", size=13), label, color_scheme="amber", variant="soft", size="1"
        ),
    )


def _local_card(card: LocalCard) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.heading(card.nombre, size="4", as_="h3"),
                rx.spacer(),
                _apto_badge(card.apto, card.apto_label),
                width="100%",
                align="center",
            ),
            rx.text(card.ubicacion, size="2", color=rx.color("gray", 11)),
            rx.hstack(
                rx.text(card.area, size="2"),
                rx.text("·", color=T.TEXT_FAINT),
                rx.text(card.canon, size="2"),
                rx.text("·", color=T.TEXT_FAINT),
                rx.text(card.flujo, size="2", color=rx.color("accent", 11)),
                spacing="2",
                wrap="wrap",
            ),
            spacing="2",
            align_items="start",
            width="100%",
        ),
        on_click=VitrinaState.seleccionar(card.id),
        cursor="pointer",
        border=rx.cond(
            card.seleccionado,
            f"1px solid {rx.color('accent', 8)}",
            f"1px solid {rx.color('gray', 5)}",
        ),
        background=rx.cond(card.seleccionado, rx.color("accent", 2), rx.color("gray", 2)),
        box_shadow=rx.cond(card.seleccionado, f"0 0 0 1px {rx.color('accent', 8)}", "none"),
        border_radius="0.75rem",
        padding="1rem 1.25rem",
        width="100%",
    )


def _selector() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading("Locales disponibles", size="4", as_="h2"),
            rx.text("elegí uno para ver su ficha", size="2", color=T.TEXT_MUTED),
            align="baseline",
            spacing="3",
        ),
        rx.grid(
            rx.foreach(VitrinaState.locales, _local_card),
            columns=rx.breakpoints(initial="1", md="3"),
            spacing="3",
            width="100%",
        ),
        width="100%",
        padding=_GUTTER_TOP_LG,
        spacing="3",
        align_items="start",
    )


# -- flow ------------------------------------------------------------------


def _flujo() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.heading("Quién pasa por esta puerta, y a qué hora", size="4", as_="h2"),
                rx.text(
                    "Gasto capturado por hora, no personas: son cosas distintas y el "
                    "ticket promedio las separa.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.spacer(),
            rx.segmented_control.root(
                rx.segmented_control.item("Entre semana", value="semana"),
                rx.segmented_control.item("Fin de semana", value="finde"),
                value=VitrinaState.dia,
                on_change=VitrinaState.cambiar_dia,
                size="1",
            ),
            width="100%",
            align="start",
            wrap="wrap",
            spacing="3",
        ),
        rx.box(
            rx.recharts.bar_chart(
                rx.recharts.cartesian_grid(
                    stroke_dasharray="3 3",
                    vertical=False,
                    stroke=rx.color("gray", 4),
                ),
                rx.recharts.graphing_tooltip(),
                rx.recharts.bar(
                    data_key="valor",
                    fill=rx.color("accent", 9),
                    radius=[4, 4, 0, 0],
                ),
                rx.recharts.x_axis(
                    data_key="hora",
                    tick_line=False,
                    axis_line=False,
                    stroke=T.TEXT_FAINT,
                ),
                rx.recharts.y_axis(
                    tick_line=False,
                    axis_line=False,
                    width=34,
                    stroke=T.TEXT_FAINT,
                ),
                data=VitrinaState.flujo,
                bar_category_gap="16%",
                height=260,
                width="100%",
                # Remounts the chart when the curve changes; see `flujo_key`.
                key=VitrinaState.flujo_key,
            ),
            width="100%",
            margin_top="1rem",
        ),
        rx.hstack(
            rx.badge(
                rx.icon("clock", size=13),
                rx.text("Pico ", VitrinaState.pico),
                color_scheme="violet",
                variant="soft",
            ),
            rx.text(VitrinaState.flujo_nota, size="1", color=T.TEXT_MUTED),
            spacing="3",
            align="start",
            width="100%",
            margin_top="0.75rem",
        ),
        **_CARD,
    )


# -- audience --------------------------------------------------------------


def _publico_row(row: PublicoRow) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(row.nombre, size="2", weight="medium"),
            rx.spacer(),
            rx.text(row.share_label, size="2", color=rx.color("gray", 11)),
            width="100%",
        ),
        rx.progress(value=row.share, max=100, color_scheme="violet", size="1", width="100%"),
        rx.hstack(
            rx.badge(row.pico, variant="outline", color_scheme="gray", size="1"),
            rx.text(row.nota, size="1", color=T.TEXT_MUTED),
            spacing="2",
            align="center",
            wrap="wrap",
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _publicos() -> rx.Component:
    return rx.box(
        rx.heading("Qué público ya viene", size="4", as_="h2"),
        rx.text(
            "Repartición de los visitantes de la semana. Cada segmento trae su hora.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.vstack(
            rx.foreach(VitrinaState.publicos, _publico_row),
            spacing="4",
            width="100%",
            margin_top="1rem",
        ),
        **_CARD,
    )


# -- hot kitchen -----------------------------------------------------------


def _requisito_row(row: RequisitoRow) -> rx.Component:
    icono = rx.match(
        row.estado,
        ("si", rx.icon("circle_check", size=18, color=rx.color("grass", 9))),
        ("no", rx.icon("circle_x", size=18, color=rx.color("tomato", 9))),
        rx.icon("circle_help", size=18, color=rx.color("amber", 9)),
    )
    etiqueta = rx.match(
        row.estado,
        ("si", rx.text("Sí", size="1", color=rx.color("grass", 11), weight="bold")),
        ("no", rx.text("No", size="1", color=rx.color("tomato", 11), weight="bold")),
        rx.text("Sin dato", size="1", color=rx.color("amber", 11), weight="bold"),
    )
    return rx.hstack(
        icono,
        rx.vstack(
            rx.hstack(
                rx.text(row.nombre, size="2", weight="medium"),
                etiqueta,
                spacing="2",
                align="center",
            ),
            rx.text(row.nota, size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
        ),
        spacing="3",
        width="100%",
        align="start",
    )


def _cocina() -> rx.Component:
    veredicto = rx.match(
        VitrinaState.cocina_estado,
        (
            "si",
            rx.badge(
                rx.icon("flame", size=14),
                VitrinaState.cocina_veredicto,
                color_scheme="grass",
                variant="soft",
            ),
        ),
        (
            "no",
            rx.badge(
                rx.icon("snowflake", size=14),
                VitrinaState.cocina_veredicto,
                color_scheme="tomato",
                variant="soft",
            ),
        ),
        rx.badge(
            rx.icon("circle_help", size=14),
            VitrinaState.cocina_veredicto,
            color_scheme="amber",
            variant="soft",
        ),
    )
    return rx.box(
        rx.hstack(
            rx.heading("Cocina caliente", size="4", as_="h2"),
            rx.spacer(),
            veredicto,
            width="100%",
            align="center",
        ),
        rx.text(VitrinaState.cocina_detalle, size="2", color=T.TEXT_MUTED),
        rx.vstack(
            rx.foreach(VitrinaState.cocina, _requisito_row),
            spacing="3",
            width="100%",
            margin_top="1rem",
        ),
        **_CARD,
    )


# -- neighbours ------------------------------------------------------------


def _ticket_badge(ticket: rx.Var[str]) -> rx.Component:
    return rx.match(
        ticket,
        ("alto", rx.badge("Ticket alto", variant="outline", color_scheme="violet", size="1")),
        ("medio", rx.badge("Ticket medio", variant="outline", color_scheme="gray", size="1")),
        rx.badge("Ticket bajo", variant="outline", color_scheme="gray", size="1"),
    )


def _vecino_row(row: VecinoRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row.distancia, white_space="nowrap"),
        rx.table.cell(rx.text(row.nombre, weight="medium")),
        rx.table.cell(row.rubro),
        rx.table.cell(_ticket_badge(row.ticket)),
        rx.table.cell(row.horario, white_space="nowrap"),
        rx.table.cell(row.vende),
    )


def _vecinos() -> rx.Component:
    return rx.box(
        rx.heading("Qué venden los vecinos", size="4", as_="h2"),
        rx.text(
            "No cuántos hay: qué despachan, a qué precio y a qué hora cierran.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.box(
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Dist."),
                        rx.table.column_header_cell("Local"),
                        rx.table.column_header_cell("Rubro"),
                        rx.table.column_header_cell("Precio"),
                        rx.table.column_header_cell("Horario"),
                        rx.table.column_header_cell("Qué vende"),
                    )
                ),
                rx.table.body(rx.foreach(VitrinaState.vecinos, _vecino_row)),
                variant="surface",
                size="1",
                width="100%",
            ),
            overflow_x="auto",
            width="100%",
            margin_top="1rem",
        ),
        **_CARD,
    )


def _hueco_card(row: HuecoRow) -> rx.Component:
    return rx.hstack(
        rx.icon("target", size=18, color=rx.color("accent", 9)),
        rx.vstack(
            rx.text(row.titulo, size="2", weight="medium"),
            rx.text(row.detalle, size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
        ),
        spacing="3",
        align="start",
        width="100%",
    )


def _huecos() -> rx.Component:
    return rx.box(
        rx.heading("Lo que nadie está vendiendo", size="4", as_="h2"),
        rx.text(
            "El flujo que llega y se va sin encontrar lo que buscaba. Es la parte que "
            "le interesa al emprendedor.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.vstack(
            rx.foreach(VitrinaState.huecos, _hueco_card),
            spacing="3",
            width="100%",
            margin_top="1rem",
        ),
        **_CARD,
    )


# -- assembly --------------------------------------------------------------


def _ficha_header() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.hstack(
                rx.heading(VitrinaState.local_nombre, size="5", as_="h2"),
                rx.text("·", color=T.TEXT_FAINT),
                rx.text(VitrinaState.local_ubicacion, size="3", color=rx.color("gray", 11)),
                spacing="2",
                align="baseline",
                wrap="wrap",
            ),
            rx.text(VitrinaState.local_ficha, size="2", color=T.TEXT_MUTED),
            rx.text(VitrinaState.local_resumen, size="2"),
            spacing="1",
            align_items="start",
        ),
        width="100%",
        padding=_GUTTER_TOP_LG,
    )


def _cta() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.heading("¿Te sirve este local?", size="4", as_="h2"),
                rx.text(
                    "En la versión real, acá el emprendedor deja sus datos y el "
                    "microcentro recibe el contacto con el local ya elegido.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.spacer(),
            rx.button("Reservar visita", size="3", disabled=True),
            width="100%",
            align="center",
            wrap="wrap",
            spacing="4",
        ),
        **_CARD,
    )


def vitrina_index() -> rx.Component:
    return app_shell(
        _topbar(),
        _disclaimer(),
        _resumen(),
        _selector(),
        _ficha_header(),
        rx.grid(
            _flujo(),
            _publicos(),
            columns=rx.breakpoints(initial="1", lg="2"),
            spacing="3",
            width="100%",
            padding=_GUTTER_TOP,
        ),
        rx.grid(
            _cocina(),
            _huecos(),
            columns=rx.breakpoints(initial="1", lg="2"),
            spacing="3",
            width="100%",
            padding=_GUTTER_TOP,
        ),
        rx.box(_vecinos(), width="100%", padding=_GUTTER_TOP),
        rx.box(_cta(), width="100%", padding=_GUTTER_BOTTOM),
    )
