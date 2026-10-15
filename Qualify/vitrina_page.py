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

Every block is `ui.card` / `ui.stat_card` on the system's card material (design-system
debt 9.3-3 — the page's own `_CARD` recipe — retired with the Liquid Glass migration);
every state is a `tone_badge`, every category a `tag`, every colour a `T.*` token. The
copy keeps its voseo on purpose (docs/design-system.md §7.1).
"""

import reflex as rx

from . import vitrina_data as D
from .ui import (
    app_shell,
    card,
    choice_card,
    demo_notice,
    page_body,
    page_header,
    stat_card,
    tag,
    tone_badge,
)
from .ui import tokens as T
from .vitrina_state import (
    HuecoRow,
    LocalCard,
    PublicoRow,
    RequisitoRow,
    VecinoRow,
    VitrinaState,
)


def _topbar() -> rx.Component:
    return page_header(
        D.MICROCENTRO,
        f"{D.LEMA} · {D.DIRECCION}",
        badge=tone_badge("demo", "warn", icon="flask-conical"),
    )


def _disclaimer() -> rx.Component:
    return demo_notice(D.DISCLAIMER)


def _resumen_card(row: PublicoRow) -> rx.Component:
    # `stat_card` casts a Var value with `to_string()`, which JSON-encodes a string
    # Var (quotes included); the figure is already text, so it goes in as an element.
    return stat_card(row.nombre, rx.el.span(row.share_label), "accent", hint=row.nota)


def _resumen() -> rx.Component:
    return rx.grid(
        rx.foreach(VitrinaState.resumen, _resumen_card),
        columns=rx.breakpoints(initial="1", sm="2", lg="4"),
        spacing="3",
        width="100%",
    )


# -- local picker ----------------------------------------------------------


def _apto_badge(apto: rx.Var[str], label: rx.Var[str]) -> rx.Component:
    """Status, never colour-alone: icon + word, in all three states."""
    return rx.match(
        apto,
        ("si", tone_badge(label, "ok", icon="flame")),
        ("no", tone_badge(label, "neutral", icon="snowflake")),
        tone_badge(label, "warn", icon="circle-help"),
    )


def _local_card(card_vm: LocalCard) -> rx.Component:
    """A card that is a choice (`ui.choice_card`, docs/design-system.md §8: nothing
    clickable is a bare box): the card material, the accent ring on the chosen one."""
    return choice_card(
        rx.vstack(
            rx.hstack(
                rx.heading(card_vm.nombre, size="4", as_="h3"),
                rx.spacer(),
                _apto_badge(card_vm.apto, card_vm.apto_label),
                width="100%",
                align="center",
            ),
            rx.text(card_vm.ubicacion, size="2", color=T.TEXT_MUTED),
            rx.hstack(
                rx.text(card_vm.area, size="2"),
                rx.text("·", color=T.TEXT_FAINT),
                rx.text(card_vm.canon, size="2"),
                rx.text("·", color=T.TEXT_FAINT),
                rx.text(card_vm.flujo, size="2", color=T.tone_color("accent", 11)),
                spacing="2",
                wrap="wrap",
            ),
            spacing="2",
            align_items="start",
            width="100%",
        ),
        selected=card_vm.seleccionado,
        on_select=VitrinaState.seleccionar(card_vm.id),
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
        spacing="3",
        align_items="start",
    )


# -- flow ------------------------------------------------------------------


def _flujo() -> rx.Component:
    return card(
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
            # One series, one hue (the accent), no legend: the title names it. Grid and
            # axes recede into the gray scale.
            rx.recharts.bar_chart(
                rx.recharts.cartesian_grid(
                    stroke_dasharray="3 3",
                    vertical=False,
                    stroke=T.tone_color("neutral", 4),
                ),
                rx.recharts.graphing_tooltip(),
                rx.recharts.bar(
                    data_key="valor",
                    fill=T.tone_color("accent", 9),
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
            tone_badge(rx.text("Pico ", VitrinaState.pico), "info", icon="clock", size="2"),
            rx.text(VitrinaState.flujo_nota, size="1", color=T.TEXT_MUTED),
            spacing="3",
            align="start",
            width="100%",
            margin_top="0.75rem",
        ),
    )


# -- audience --------------------------------------------------------------


def _publico_row(row: PublicoRow) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(row.nombre, size="2", weight="medium"),
            rx.spacer(),
            rx.text(row.share_label, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
            width="100%",
        ),
        # The bar takes the accent gradient from the Radix skin (`.rt-ProgressIndicator`).
        rx.progress(value=row.share, max=100, size="1", width="100%"),
        rx.hstack(
            tag(row.pico),
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
    return card(
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
    )


# -- hot kitchen -----------------------------------------------------------


def _requisito_row(row: RequisitoRow) -> rx.Component:
    icono = rx.match(
        row.estado,
        ("si", rx.icon("circle-check", size=18, color=T.tone_color("ok", 9))),
        ("no", rx.icon("circle-x", size=18, color=T.tone_color("error", 9))),
        rx.icon("circle-help", size=18, color=T.tone_color("warn", 9)),
    )
    etiqueta = rx.match(
        row.estado,
        ("si", rx.text("Sí", size="1", color=T.tone_color("ok", 11), weight="bold")),
        ("no", rx.text("No", size="1", color=T.tone_color("error", 11), weight="bold")),
        rx.text("Sin dato", size="1", color=T.tone_color("warn", 11), weight="bold"),
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
        ("si", tone_badge(VitrinaState.cocina_veredicto, "ok", icon="flame", size="2")),
        ("no", tone_badge(VitrinaState.cocina_veredicto, "error", icon="snowflake", size="2")),
        tone_badge(VitrinaState.cocina_veredicto, "warn", icon="circle-help", size="2"),
    )
    return card(
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
    )


# -- neighbours ------------------------------------------------------------


def _ticket_badge(ticket: rx.Var[str]) -> rx.Component:
    """Price level is a category, not a state: a `tag`, told apart by its word."""
    return rx.match(
        ticket,
        ("alto", tag("Ticket alto")),
        ("medio", tag("Ticket medio")),
        tag("Ticket bajo"),
    )


def _vecino_row(row: VecinoRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row.distancia, white_space="nowrap", class_name="q-nums"),
        rx.table.cell(rx.text(row.nombre, weight="medium")),
        rx.table.cell(row.rubro),
        rx.table.cell(_ticket_badge(row.ticket)),
        rx.table.cell(row.horario, white_space="nowrap", class_name="q-nums"),
        rx.table.cell(row.vende),
    )


def _vecinos() -> rx.Component:
    return card(
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
    )


def _hueco_card(row: HuecoRow) -> rx.Component:
    return rx.hstack(
        rx.icon("target", size=18, color=T.tone_color("accent", 9)),
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
    return card(
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
    )


# -- assembly --------------------------------------------------------------


def _ficha_header() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading(VitrinaState.local_nombre, size="5", as_="h2"),
            rx.text("·", color=T.TEXT_FAINT),
            rx.text(VitrinaState.local_ubicacion, size="3", color=T.TEXT_MUTED),
            spacing="2",
            align="baseline",
            wrap="wrap",
        ),
        rx.text(VitrinaState.local_ficha, size="2", color=T.TEXT_MUTED),
        rx.text(VitrinaState.local_resumen, size="2"),
        spacing="1",
        align_items="start",
        width="100%",
    )


def _cta() -> rx.Component:
    return card(
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
            # The page's one solid action (P3) — disabled, as the demo has no backend.
            rx.button("Reservar visita", size="3", disabled=True),
            width="100%",
            align="center",
            wrap="wrap",
            spacing="4",
        ),
    )


def vitrina_index() -> rx.Component:
    return app_shell(
        _topbar(),
        page_body(
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
            ),
            rx.grid(
                _cocina(),
                _huecos(),
                columns=rx.breakpoints(initial="1", lg="2"),
                spacing="3",
                width="100%",
            ),
            _vecinos(),
            _cta(),
            spacing="5",
        ),
    )
