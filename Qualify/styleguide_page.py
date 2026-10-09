"""`/design` — the living style guide.

Renders every token and primitive of ``Qualify/ui`` with the real theme, so a change to
``rxconfig.py``, ``assets/qualify.css`` or ``ui/*`` is visible here first. Static and
tenant-free (no state, no session), which is why it is not behind ``require_login`` and
not in the sidebar. The written rules live in docs/design-system.md; this page is the
proof they render.
"""

from __future__ import annotations

import reflex as rx

from .ui import (
    app_shell,
    callout,
    card,
    demo_notice,
    drawer,
    empty_state,
    kv,
    loading_spinner,
    mono,
    page_body,
    page_header,
    pill_editor,
    platform_badge,
    progress_panel,
    removable_pill,
    section,
    sentiment_badge,
    signal_pill,
    skeleton_card,
    skeleton_rows,
    stat_card,
    stepper,
    tag,
    tone_badge,
)
from .ui import tokens as T
from .ui.state import NavState


class DrawerDemoState(rx.State):
    """The style guide's only state: whether the sample drawer is open, and which of
    its sample steps is current. Nothing tenant-bound."""

    open: bool = False
    step: int = 1

    @rx.event
    def set_open(self, value: bool) -> None:
        self.open = value

    @rx.event
    def go(self, index: int) -> None:
        self.step = index

    @rx.var
    def done(self) -> list[bool]:
        return [i < self.step for i in range(4)]


_TONES = ["accent", "ok", "warn", "error", "info", "neutral"]
_TONE_MEANING = {
    "accent": "acción principal, marca",
    "ok": "sano, positivo, entregado",
    "warn": "atención, degradado, demo",
    "error": "fallo, revocado, negativo",
    "info": "informativo, en curso",
    "neutral": "desconocido, pendiente",
}


# ---------------------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------------------


def _scale_row(name: str, scale: str) -> rx.Component:
    """The 12 steps of a Radix scale, labelled by their role bands."""
    return rx.vstack(
        rx.hstack(
            rx.text(name, size="2", weight="medium", min_width="6rem"),
            rx.text(
                "1-2 fondos · 3-5 superficies interactivas · 6-8 bordes · 9-10 sólidos · "
                "11-12 texto",
                size="1",
                color=T.TEXT_MUTED,
            ),
            align="baseline",
            spacing="3",
        ),
        rx.hstack(
            *[
                rx.box(
                    rx.text(str(step), size="1", color=rx.color(scale, 12 if step < 9 else 1)),
                    background=rx.color(scale, step),
                    height="2.5rem",
                    flex="1",
                    display="flex",
                    align_items="end",
                    justify_content="center",
                    padding_bottom="0.2rem",
                )
                for step in range(1, 13)
            ],
            spacing="0",
            width="100%",
            border_radius=T.RADIUS_CONTROL,
            overflow="hidden",
            border=T.BORDER,
        ),
        width="100%",
        spacing="1",
        align_items="start",
    )


def _tone_row(tone: str) -> rx.Component:
    return rx.hstack(
        rx.box(
            width="1.25rem",
            height="1.25rem",
            border_radius="9999px",
            background=T.tone_color(tone, 9),
        ),
        rx.text(tone, size="2", weight="medium", min_width="4.5rem", class_name="q-mono"),
        rx.text(T.tone_scale(tone), size="2", color=T.TEXT_MUTED, min_width="4rem"),
        rx.text(_TONE_MEANING[tone], size="2"),
        rx.spacer(),
        signal_pill("estado", tone),
        tone_badge("verdicto", tone, icon="circle"),
        align="center",
        spacing="3",
        width="100%",
    )


def _colour_section() -> rx.Component:
    return section(
        "Color",
        rx.text(
            "Todo color sale de una escala Radix. El acento y el gris se fijan una vez en "
            "rxconfig.py; los tonos semánticos se piden por rol (ok/warn/error), nunca por "
            "matiz. Un estado siempre lleva punto o icono + palabra.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        card(
            rx.vstack(
                _scale_row("accent (teal)", "accent"),
                _scale_row("gray (slate)", "gray"),
                spacing="4",
                width="100%",
            )
        ),
        card(
            rx.vstack(
                rx.text("Tonos semánticos", size="2", weight="medium"),
                *[_tone_row(t) for t in _TONES],
                spacing="2",
                width="100%",
            )
        ),
        card(
            rx.vstack(
                rx.text(
                    "Identidad de plataforma — siempre outline, nunca parece un estado",
                    size="2",
                    weight="medium",
                ),
                rx.hstack(
                    *[platform_badge(p) for p in T.PLATFORM_SCALE],
                    tag("etiqueta / categoría"),
                    spacing="2",
                    wrap="wrap",
                ),
                spacing="2",
                width="100%",
            )
        ),
        description="Escalas, tonos e identidad.",
    )


# ---------------------------------------------------------------------------------------
# Type
# ---------------------------------------------------------------------------------------


def _type_section() -> rx.Component:
    sample = "Qué dicen de tu negocio, y qué haces ahora"
    return section(
        "Tipografía",
        card(
            rx.vstack(
                rx.hstack(
                    rx.text("heading 8", size="1", color=T.TEXT_MUTED, min_width="6rem"),
                    rx.text(sample, size="8", weight="bold"),
                    align="baseline",
                    spacing="3",
                ),
                rx.hstack(
                    rx.text("heading 6 · h1", size="1", color=T.TEXT_MUTED, min_width="6rem"),
                    rx.text(sample, size="6", weight="bold"),
                    align="baseline",
                    spacing="3",
                ),
                rx.hstack(
                    rx.text("heading 4 · h2", size="1", color=T.TEXT_MUTED, min_width="6rem"),
                    rx.text(sample, size="4", weight="bold"),
                    align="baseline",
                    spacing="3",
                ),
                rx.hstack(
                    rx.text("text 3", size="1", color=T.TEXT_MUTED, min_width="6rem"),
                    rx.text(sample, size="3"),
                    align="baseline",
                    spacing="3",
                ),
                rx.hstack(
                    rx.text("text 2 · cuerpo", size="1", color=T.TEXT_MUTED, min_width="6rem"),
                    rx.text(sample, size="2"),
                    align="baseline",
                    spacing="3",
                ),
                rx.hstack(
                    rx.text("text 2 · muted", size="1", color=T.TEXT_MUTED, min_width="6rem"),
                    rx.text(sample, size="2", color=T.TEXT_MUTED),
                    align="baseline",
                    spacing="3",
                ),
                rx.hstack(
                    rx.text("text 1 · meta", size="1", color=T.TEXT_MUTED, min_width="6rem"),
                    rx.text(sample, size="1", color=T.TEXT_MUTED),
                    align="baseline",
                    spacing="3",
                ),
                rx.divider(),
                rx.hstack(
                    rx.text("mono", size="1", color=T.TEXT_MUTED, min_width="6rem"),
                    mono("@lacasadelcafe · conn_7f3a · 2026-08-18 14:02"),
                    align="baseline",
                    spacing="3",
                ),
                rx.hstack(
                    rx.text("q-nums", size="1", color=T.TEXT_MUTED, min_width="6rem"),
                    rx.text("1.204  ·  38  ·  12.988  ·  0,7 %", size="2", class_name="q-nums"),
                    align="baseline",
                    spacing="3",
                ),
                spacing="3",
                width="100%",
                align_items="start",
            )
        ),
        description=(
            "IBM Plex Sans para interfaz, IBM Plex Mono para identificadores. Escala Radix "
            "1-9; una página usa h1=6, h2=4, cuerpo=2, meta=1."
        ),
    )


# ---------------------------------------------------------------------------------------
# Spacing / shape
# ---------------------------------------------------------------------------------------


def _space_section() -> rx.Component:
    steps = [("1", "4"), ("2", "8"), ("3", "12"), ("4", "16"), ("5", "24"), ("6", "32")]
    return section(
        "Espacio y forma",
        card(
            rx.vstack(
                rx.hstack(
                    *[
                        rx.vstack(
                            rx.box(
                                width=f"{px}px",
                                height=f"{px}px",
                                background=rx.color("accent", 6),
                                border_radius="2px",
                            ),
                            rx.text(f"{n} · {px}px", size="1", color=T.TEXT_MUTED),
                            align="center",
                            spacing="1",
                        )
                        for n, px in steps
                    ],
                    spacing="5",
                    align="end",
                ),
                rx.divider(),
                rx.hstack(
                    kv("gutter de página", "var(--q-page-x) = 2rem / 1rem < 900px", mono=True),
                    width="100%",
                ),
                kv("sidebar", "232px (zen: 72px)", mono=True),
                kv("radio isla", "32px = --q-lab-radius (dial del Lab)", mono=True),
                kv("radio tarjeta", "20px = --lq-radius", mono=True),
                kv("radio control", "12px = --lq-radius-sm", mono=True),
                kv("borde", "1px gray-5 (fuerte: gray-7)", mono=True),
                kv("elevación", "reposo --lq-shadow-soft · lift --lq-shadow · overlay", mono=True),
                spacing="3",
                width="100%",
                align_items="start",
            )
        ),
        description="Escala Radix (spacing 1-9). El gutter horizontal es un token CSS.",
    )


# ---------------------------------------------------------------------------------------
# Material (Glass Lab)
# ---------------------------------------------------------------------------------------

# The Glass Lab's dials, one per token (assets/qualify.css, "Glass Lab dials"; the two
# filter dials also in ui.layout.LAB_REFRACTION / LAB_FREQUENCY). Static strings on
# purpose: this is the record a designer compares against the Lab, and the CSS is the
# source — change both when the Lab changes (docs/design-system.md §3.4).
_LAB_DIALS: list[tuple[str, str]] = [
    ("material", "Liquid (--q-glass-fill)"),
    ("backdrop scene", "Noir (.q-ground)"),
    ("backdrop blur", "0px (--q-lab-blur)"),
    ("surface opacity", "9% (--q-lab-opacity: 0.09)"),
    ("saturation", "120% (--q-lab-saturation)"),
    ("corner radius", "32px (--q-lab-radius)"),
    ("edge highlight", "34% (--q-lab-border: 0.34)"),
    ("refraction", "21 (--q-lab-refraction, #q-refraction)"),
    ("surface frequency", "9 → 0.009 (--q-lab-frequency)"),
    ("optical depth", "100% (--q-lab-depth: 1 · blur 6px)"),
    ("material tint", "el acento (--q-lab-tint: --accent-9)"),
]


def _material_sample(role: str, where: str, surface: rx.Component) -> rx.Component:
    """One of the three materials, rendered by the real theme, with its role above it."""
    return rx.vstack(
        rx.text(role, size="2", weight="medium"),
        rx.text(where, size="1", color=T.TEXT_MUTED),
        surface,
        spacing="1",
        width="100%",
        align_items="start",
    )


def _material_section() -> rx.Component:
    """§3.4: the dials the material is made of, and the three materials by role side by
    side — island (glass with blur), card (translucent relief, no blur), control
    (relief). Only existing primitives and the system's own classes."""
    island = rx.box(
        rx.vstack(
            rx.text("Isla de vidrio", size="2", weight="medium"),
            rx.text("Refracta el suelo; la luz sigue al puntero.", size="1", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
            # Above the island's own depth layer (`.q-island::before`, z 0).
            position="relative",
            z_index="1",
        ),
        class_name="q-island",
        padding="1rem 1.25rem",
        width="100%",
        style={"--q-zone-tint": T.zone_tint("listen"), "--q-zone-line": T.zone_line("listen")},
    )
    sample_card = card(
        rx.vstack(
            rx.text("Tarjeta", size="2", weight="medium"),
            rx.text("Relieve translúcido dentro del panel opaco.", size="1", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
        ),
        padding="1rem 1.25rem",
    )
    control = rx.hstack(
        rx.button("Control", variant="soft", size="2"),
        rx.button("Principal", size="2"),
        spacing="2",
        align="center",
        wrap="wrap",
    )
    return section(
        "Material (Glass Lab)",
        rx.text(
            "El material lo definen los diales del Glass Lab del kit, uno por token "
            "(--q-lab-*). La paleta sigue siendo nuestra: el tinte es el acento. Para "
            "cambiarlo, mover los diales en el Lab y copiar los números al CSS.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        card(
            rx.vstack(
                *[kv(label, value, mono=True) for label, value in _LAB_DIALS],
                spacing="2",
                width="100%",
                align_items="start",
            )
        ),
        rx.grid(
            _material_sample("island", "sidebar, overlays, header sticky · con blur", island),
            _material_sample("card", "ui.card, tabla, callout · sin blur", sample_card),
            _material_sample("control", "botón, campo, badge · solo relieve", control),
            columns=rx.breakpoints(initial="1", md="3"),
            spacing="3",
            width="100%",
        ),
        description="Tres materiales por rol; nunca blur en grids, ≤ 8 por pantalla.",
        spacing="4",
    )


# ---------------------------------------------------------------------------------------
# Motion and elevation
# ---------------------------------------------------------------------------------------


def _motion_row(name: str, value: str, use: str) -> rx.Component:
    return rx.hstack(
        rx.text(name, size="2", weight="medium", min_width="7rem", class_name="q-mono"),
        rx.text(value, size="1", color=T.TEXT_MUTED, min_width="11rem", class_name="q-mono"),
        rx.text(use, size="2"),
        align="center",
        spacing="3",
        width="100%",
    )


def _motion_section() -> rx.Component:
    return section(
        "Movimiento y elevación",
        rx.text(
            "Dos curvas y tres duraciones, no más. El muelle es para lo que cambia de "
            "tamaño o de forma; el ease, para lo que cambia de color u opacidad. La "
            "elevación significa «esto responde»: una tarjeta se levanta al pasar el "
            "ratón sólo si al pulsarla ocurre algo.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        card(
            rx.vstack(
                _motion_row("--q-spring", "cubic-bezier(.16,1.18,.3,1)", "ancho, forma, colapso"),
                _motion_row("--q-ease", "cubic-bezier(.22,1,.36,1)", "color, opacidad, máscara"),
                _motion_row("--q-dur-fast", "140ms", "hover, foco, cambio de color"),
                _motion_row("--q-dur", "240ms", "elevación, entrada de un bloque"),
                _motion_row("--q-dur-slow", "380ms", "colapso del rail, revelado de etiqueta"),
                spacing="2",
                width="100%",
            )
        ),
        rx.grid(
            card(
                rx.vstack(
                    rx.text("Isla en reposo", size="2", weight="medium"),
                    rx.text(
                        "Toda superficie flota sobre el fondo con --q-elev-island. Es el "
                        "estado por defecto: no se mueve.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    align_items="start",
                )
            ),
            card(
                rx.vstack(
                    rx.text("Tarjeta interactiva", size="2", weight="medium"),
                    rx.text(
                        "Pasa el ratón: sube 2 px y gana sombra. Sólo para tarjetas que "
                        "hacen algo al pulsarlas — card(interactive=True).",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    align_items="start",
                ),
                interactive=True,
            ),
            card(
                rx.vstack(
                    rx.text("Modo zen", size="2", weight="medium"),
                    rx.text(
                        "El menú se contrae a 72 px con muelle y las etiquetas se "
                        "revelan con máscara, no con fundido.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    rx.button(
                        rx.icon(
                            rx.cond(NavState.zen, "panel-left-open", "panel-left-close"),
                            size=T.ICON_SM,
                        ),
                        rx.cond(NavState.zen, "Expandir el menú", "Contraer el menú"),
                        on_click=NavState.toggle_zen,
                        variant="soft",
                        size="2",
                        margin_top="0.25rem",
                    ),
                    rx.text("Atajo: ⌘ .", size="1", color=T.TEXT_FAINT),
                    spacing="1",
                    align_items="start",
                )
            ),
            columns=rx.breakpoints(initial="1", md="3"),
            spacing="3",
            width="100%",
        ),
        description="Las mismas curvas en todo el producto; la elevación no decora.",
        spacing="4",
    )


# ---------------------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------------------


def _buttons() -> rx.Component:
    return card(
        rx.vstack(
            rx.text("Botones — un solo solid por pantalla", size="2", weight="medium"),
            rx.hstack(
                rx.button(rx.icon("plus", size=16), "Acción principal", size="2"),
                rx.button("Secundaria", variant="soft", size="2"),
                rx.button("Terciaria", variant="outline", size="2"),
                rx.button("Fantasma", variant="ghost", size="2"),
                rx.button(
                    rx.icon("trash-2", size=16),
                    "Destructiva",
                    color_scheme=T.tone_scale("error"),
                    variant="soft",
                    size="2",
                ),
                rx.button("Cargando", loading=True, size="2"),
                rx.button("Deshabilitado", disabled=True, size="2"),
                spacing="2",
                wrap="wrap",
            ),
            rx.hstack(
                rx.button("size 1", size="1"),
                rx.button("size 2 (por defecto)", size="2"),
                rx.button("size 3 (empty states)", size="3"),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            spacing="3",
            width="100%",
            align_items="start",
        )
    )


def _forms() -> rx.Component:
    return card(
        rx.vstack(
            rx.text("Formularios", size="2", weight="medium"),
            rx.grid(
                rx.vstack(
                    rx.text("Email", size="2", weight="medium"),
                    rx.input(placeholder="nombre@negocio.com", type="email", width="100%"),
                    rx.text("Un alias por negocio.", size="1", color=T.TEXT_MUTED),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                rx.vstack(
                    rx.text("Cuenta conectada", size="2", weight="medium"),
                    rx.select(
                        ["@lacasadelcafe · instagram", "@cafeteria · facebook"], width="100%"
                    ),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                rx.vstack(
                    rx.text("Buscar", size="2", weight="medium"),
                    rx.input(
                        rx.input.slot(rx.icon("search", size=T.ICON_SM)),
                        placeholder="Buscar por caption o creador",
                        width="100%",
                    ),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                rx.vstack(
                    rx.text("Monitorear", size="2", weight="medium"),
                    rx.hstack(
                        rx.switch(default_checked=True),
                        rx.text("Activo", size="2"),
                        align="center",
                        spacing="2",
                    ),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                columns=rx.breakpoints(initial="1", md="2"),
                spacing="4",
                width="100%",
            ),
            spacing="3",
            width="100%",
            align_items="start",
        )
    )


def _feedback() -> rx.Component:
    return rx.vstack(
        rx.text("Feedback en línea", size="2", weight="medium"),
        callout("No se pudo cargar la lista. Recarga la página o vuelve más tarde.", "error"),
        callout("La conexión dejó de responder. Reconéctala para restaurar el acceso.", "warn"),
        callout("Cada actualización gasta 1 de las 10 llamadas diarias.", "info"),
        callout("Publicado. El reel ya está en tu cuenta.", "ok"),
        demo_notice("Datos de demostración: los números son ilustrativos."),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _stats() -> rx.Component:
    return rx.grid(
        stat_card("Total menciones", "1.204", "accent", hint="últimos 14 días"),
        stat_card("Positivas", "812", "ok"),
        stat_card("Neutras", "354", "neutral"),
        stat_card("Negativas", "38", "error", hint="3 sin responder"),
        columns=rx.breakpoints(initial="2", md="4"),
        spacing="3",
        width="100%",
    )


def _table() -> rx.Component:
    def row(date: str, plat: str, handle: str, caption: str, sent: str, tone: str, n: str):
        return rx.table.row(
            rx.table.cell(date, white_space="nowrap", class_name="q-nums"),
            rx.table.cell(platform_badge(plat)),
            rx.table.cell(mono(handle)),
            rx.table.cell(caption, max_width="320px", overflow="hidden", text_overflow="ellipsis"),
            rx.table.cell(signal_pill(sent, tone)),
            rx.table.cell(n, text_align="right", class_name="q-nums"),
        )

    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Fecha"),
                    rx.table.column_header_cell("Plataforma"),
                    rx.table.column_header_cell("Creador"),
                    rx.table.column_header_cell("Caption"),
                    rx.table.column_header_cell("Sentimiento"),
                    rx.table.column_header_cell("Vistas", text_align="right"),
                )
            ),
            rx.table.body(
                row(
                    "2026-08-17",
                    "tiktok",
                    "@anaviaja",
                    "El mejor café de la 5ta",
                    "Positiva",
                    "ok",
                    "12.988",
                ),
                row(
                    "2026-08-16",
                    "instagram",
                    "@cucutafoodie",
                    "Fui y me atendieron regular",
                    "Neutra",
                    "neutral",
                    "1.204",
                ),
                row(
                    "2026-08-15",
                    "instagram",
                    "@juanp",
                    "Nunca más, 40 min esperando",
                    "Negativa",
                    "error",
                    "388",
                ),
            ),
            variant="surface",
            width="100%",
        ),
        overflow_x="auto",
        width="100%",
    )


def _card_sample() -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                platform_badge("instagram"),
                rx.heading("@lacasadelcafe", size="4", as_="h3"),
                rx.spacer(),
                tone_badge("Activa", "ok", icon="circle-check", size="2"),
                width="100%",
                align="center",
            ),
            rx.hstack(
                rx.icon("building-2", size=14, color=T.TEXT_FAINT),
                rx.text("La Casa del Café", size="2", color=T.TEXT_MUTED),
                rx.text("·", color=T.TEXT_FAINT),
                rx.icon("clock", size=14, color=T.TEXT_FAINT),
                rx.text("Verificada: hace 2 h", size="2", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
            rx.hstack(tag("instagram_basic"), tag("pages_show_list"), spacing="2", wrap="wrap"),
            rx.divider(),
            kv("Conexión", "conn_7f3a9c", mono=True),
            kv("Marca", "La Casa del Café"),
            rx.hstack(
                rx.spacer(),
                rx.button(
                    rx.icon("unplug", size=15),
                    "Desconectar",
                    variant="soft",
                    color_scheme="gray",
                    size="2",
                ),
                width="100%",
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        padding="1.25rem 1.5rem",
    )


def _states() -> rx.Component:
    return rx.grid(
        card(
            rx.vstack(
                rx.text("Cargando contenido = skeleton", size="2", weight="medium"),
                rx.text(
                    "Algo se está leyendo y va a aparecer aquí: la forma de lo que viene. "
                    "Siempre skeleton, nunca spinner.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                skeleton_card(),
                skeleton_rows(2),
                rx.text("Trabajo en curso = spinner", size="2", weight="medium"),
                rx.text(
                    "Algo se está haciendo: scraping, generando, sincronizando, publicando. "
                    "Siempre junto a la frase que dice qué pasa.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                rx.hstack(
                    *(
                        rx.vstack(
                            loading_spinner(size),
                            rx.text(size, size="1", color=T.TEXT_MUTED),
                            spacing="2",
                            align="center",
                        )
                        for size in ("sm", "md", "lg")
                    ),
                    spacing="5",
                    align="end",
                ),
                rx.text(
                    "Espera que bloquea, con progreso real o estimado", size="1", color=T.TEXT_MUTED
                ),
                progress_panel(
                    "Analizando tu voz",
                    "Progreso real, por etapas",
                    value=60,
                    steps=rx.Var.create(
                        [
                            {"title": "Preparamos tu grabación", "status": "done"},
                            {"title": "Transcribimos lo que dices", "status": "running"},
                            {"title": "Leemos tu tono", "status": "pending"},
                        ]
                    ),
                ),
                progress_panel("Buscando hashtags", "Sin progreso medible: avanza con el tiempo"),
                spacing="3",
                width="100%",
                align_items="start",
            )
        ),
        card(
            rx.vstack(
                rx.text("Vacío", size="2", weight="medium"),
                empty_state(
                    "link-2-off",
                    "Aún no conectas ninguna cuenta",
                    "Conecta tu primera cuenta de Instagram o Facebook para empezar a "
                    "escuchar y responder desde Qualify.",
                    action=rx.button(rx.icon("plus", size=16), "Conectar cuenta", size="3"),
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            padding="1.25rem 1.25rem 0",
        ),
        columns=rx.breakpoints(initial="1", lg="2"),
        spacing="3",
        width="100%",
    )


def _sentiment_badges() -> rx.Component:
    """QUA-92: the four states `sentiment_badge` renders for the pipeline vocabulary
    (`POS`/`NEG`/`NEU`/`""`) — `""` is "Sin analizar", never NEU."""
    return rx.hstack(
        sentiment_badge(rx.Var.create("POS")),
        sentiment_badge(rx.Var.create("NEG")),
        sentiment_badge(rx.Var.create("NEU")),
        sentiment_badge(rx.Var.create("")),
        spacing="2",
        wrap="wrap",
    )


def _pills() -> rx.Component:
    """`removable_pill` / `pill_editor`: values the operator curates (a Brand Kit list, the
    hashtags, an uploaded file). Static here — the ✕ and the input do nothing."""
    return card(
        rx.vstack(
            rx.hstack(
                removable_pill("barato", rx.noop()),
                removable_pill("#streetfood", rx.noop(), suggested=True),
                removable_pill("fondo-local.jpg", rx.noop(), icon="image"),
                spacing="2",
                wrap="wrap",
            ),
            rx.text(
                "surface gris = valor escrito por el operador · soft acento = sugerido por el "
                "producto (aún no confirmado). Nunca un tono: una pill no es un estado.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.divider(),
            rx.text("Palabras vetadas (pill_editor)", size="2", weight="medium"),
            pill_editor(
                rx.Var.create(["barato", "el mejor de la ciudad"]),
                draft=rx.Var.create(""),
                on_draft_change=lambda _value: rx.noop(),
                on_add=rx.noop(),
                on_remove=lambda _index: rx.noop(),
                placeholder="Escribe una palabra y pulsa Enter",
                add_label="Agregar palabra vetada",
            ),
            spacing="3",
            width="100%",
            align_items="start",
        )
    )


_DEMO_STEPS = ["Post", "Fecha y hora", "Cuentas", "Confirmar"]


def _flow() -> rx.Component:
    """`stepper` + `drawer` (QUA-118): a flow with steps lives in a right-edge panel, not
    a centred dialog. Completed steps are clickable (back to fix), unreached ones are
    not; the body scrolls, title and footer stay put; a phone gets the full width."""
    return card(
        rx.vstack(
            stepper(
                _DEMO_STEPS,
                current=DrawerDemoState.step,
                completed=DrawerDemoState.done,
                on_select=DrawerDemoState.go,
            ),
            rx.text(
                "check lleno = paso completado (clicable para volver) · anillo = paso actual · "
                "número = paso aún no alcanzado (nunca clicable). La etiqueta es lo que se "
                "lee; el número es el respaldo.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.divider(),
            rx.button(
                rx.icon("panel-right-open", size=T.ICON_SM),
                "Abrir drawer de ejemplo",
                variant="soft",
                on_click=DrawerDemoState.set_open(True),
            ),
            drawer(
                stepper(
                    _DEMO_STEPS,
                    current=DrawerDemoState.step,
                    completed=DrawerDemoState.done,
                    on_select=DrawerDemoState.go,
                ),
                rx.text(
                    "El cuerpo del drawer se desplaza; el título y el pie quedan fijos. "
                    "Esc o el fondo lo cierran. En un teléfono ocupa toda la pantalla.",
                    size="2",
                    margin_top="1rem",
                ),
                open=DrawerDemoState.open,
                on_open_change=DrawerDemoState.set_open,
                title="Drawer de ejemplo",
                description="Un flujo por pasos, al borde derecho.",
                footer=rx.hstack(
                    rx.button(
                        "Cerrar",
                        variant="soft",
                        color_scheme="gray",
                        on_click=DrawerDemoState.set_open(False),
                    ),
                    rx.button("Siguiente", on_click=DrawerDemoState.go(2)),
                    justify="end",
                    spacing="2",
                    width="100%",
                ),
            ),
            spacing="3",
            width="100%",
            align_items="start",
        )
    )


def _components_section() -> rx.Component:
    return section(
        "Componentes",
        _buttons(),
        _forms(),
        card(_feedback()),
        rx.text("Flujo por pasos (stepper + drawer — QUA-118)", size="2", weight="medium"),
        _flow(),
        rx.text(
            "Pills (removable_pill / pill_editor — listas que el operador arma)",
            size="2",
            weight="medium",
        ),
        _pills(),
        rx.text("Cifras", size="2", weight="medium"),
        _stats(),
        rx.text(
            "Sentimiento (sentiment_badge — POS/NEG/NEU + sin analizar, QUA-92)",
            size="2",
            weight="medium",
        ),
        _sentiment_badges(),
        rx.text(
            "Tarjeta de entidad (card + platform_badge + tone_badge + tag + kv)",
            size="2",
            weight="medium",
        ),
        _card_sample(),
        rx.text(
            "Tabla (surface, cifras tabulares, identificadores mono)", size="2", weight="medium"
        ),
        _table(),
        rx.text("Estados de pantalla", size="2", weight="medium"),
        _states(),
        description="Cada bloque es una primitiva de Qualify/ui o una composición documentada.",
        spacing="4",
    )


def styleguide_index() -> rx.Component:
    return app_shell(
        page_header(
            "Design system",
            "Tokens y primitivas de Qualify/ui, renderizados con el tema real. "
            "Reglas escritas: docs/design-system.md",
            badge=rx.badge("interno", variant="soft", color_scheme="gray", size="1"),
        ),
        page_body(
            _colour_section(),
            _type_section(),
            _space_section(),
            _material_section(),
            _motion_section(),
            _components_section(),
            spacing="6",
        ),
    )
