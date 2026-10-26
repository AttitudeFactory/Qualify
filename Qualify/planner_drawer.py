"""The Planificador's side panels (QUA-118 v2, founder review 2026-10-06): «Nueva
publicación» — several POSTs planned in one go — and the event's own panel, which also
shows the POST. No modal anywhere on the screen: both are right-edge panels (`ui.drawer`)
and every confirmation is asked inside the panel, never in a dialog on top of it.

«Nueva publicación» walks three steps named by a glyph and a word, never a number:

1. **Contenido** — the POSTs as a grid of tiles in their real shape. A ready one is a
   solid tile you can pick (several); one that is not ready is drawn with a dashed frame
   and cannot be picked (D1), with the reason on hover. Each tile says its format (Reel,
   Historia, Carrusel, Feed) by colour + glyph + word, and its temperature: **Cold**
   (evergreen, proven — it has gone out again and again) or **Hot** (new, still proving
   itself), see `planner_vm.temperature`.
2. **Cuándo sale** («Paso 2 de 3 · ¿Cuándo sale?», m-24842985, N6) — one card per piece
   asking only the day and the hour, or «Ahora» (planned at the instant «Programar» is
   tapped). The accounts already chosen are said in one line («Sale en @cuenta
   (Instagram)»); output, destination, accounts, campaign, tags and weekly repetition
   sit behind «Más opciones», which opens on its own when what is missing is in there.
3. **Confirmar** — one sentence («Sale el jueves 30 a las 7:00 p. m. en Instagram
   @cuenta», N13), then the day as it will go out: a phone-shaped mock of each piece in
   its channel's shape on a timeline, each with ✎ / 🗑, and the plan's goals folded
   behind «Más opciones».

Colours are identity here, never state: a format has its scale (`q-kind-*` in
`assets/qualify.css`), a goal has its scale, and Cold/Hot their own gradient. States keep
speaking through `signal_pill` tones. Every block of the steps and of the event panel
(tiles, plan cards, fact tiles, the hero, the timeline) sits on the system's card
material and every chip on its control material — `assets/qualify-planner.css`, on the
`--q-card-*` / `--q-control-*` tokens, no blur inside the grids (plan D5).
"""

from __future__ import annotations

import reflex as rx
from qualify_api.planner.publishable import STORY_CAPTION_NOTE

from .campaign_provider import COLOR_LABELS
from .planner_state import CONFIRM_CANCEL, CONFIRM_REMOVE, PlannerState
from .planner_vm import (
    ASSIGN_STEP_ICONS,
    ASSIGN_STEPS,
    AUTO_PUBLISH_ACTIVE,
    AUTO_PUBLISH_NO_CONNECTION,
    BACK_TO_WEEK,
    EXPIRED_NOTE,
    KIND_ICONS,
    NOW_LABEL,
    PLAN_GOALS,
    REVIEW_EDIT_LINK,
    REVIEW_NOTHING_WITHOUT_YOU,
    STEP_POST,
    STEP_PREVIEW,
    STEP_WHEN,
    TAG_COLORS,
    WEEKDAY_INITIALS,
    WEEKDAY_NAMES,
)
from .post_card import (
    campaign_badge,
    color_swatches,
    destination_badge,
    destination_icon,
    kind_chip,
    media_fill,
    pill,
    temperature_badge,
    viewable_src,
)
from .r2_media import BACKEND_BASE
from .ui import callout, drawer, skeleton_card, stepper
from .ui import tokens as T
from .ui.flow_history import flow_sync
from .ui.steps import step_progress

#: m-24842985 (N6): what is not the day and the hour waits behind this fold.
MORE_OPTIONS = "Más opciones"
MORE_OPTIONS_GOALS = "Más opciones: metas de esta planificación"

_ONE_LINE = {"overflow": "hidden", "text_overflow": "ellipsis", "white_space": "nowrap"}
_CLAMP_2 = {
    "display": "-webkit-box",
    "-webkit-line-clamp": "2",
    "-webkit-box-orient": "vertical",
    "overflow": "hidden",
}
# Lucide ships no brand logos, so each platform gets a generic glyph in its identity
# colour (T.PLATFORM_SCALE); the list view and the panel spell the name out.
_PLATFORM_ICON = {"instagram": "camera", "facebook": "users", "tiktok": "music-2"}
_KIND_FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "Todo"),
    ("image", "Imágenes"),
    ("video", "Videos"),
    ("carousel", "Galerías"),
    ("pack", "Multiformato"),
)


# ---------------------------------------------------------------------------
# Small shared pieces (also used by the calendar)


def platform_icon(platform: rx.Var[str], size: int = T.ICON_SM) -> rx.Component:
    """The platform's glyph in its identity scale (`T.platform_scale`, step 9 — the solid
    step, as the Radix variable so it follows light and dark)."""
    return rx.match(
        platform,
        *[
            (key, rx.icon(icon, size=size, color=f"var(--{T.platform_scale(key)}-9)"))
            for key, icon in _PLATFORM_ICON.items()
        ],
        rx.icon("globe", size=size, color=T.TEXT_MUTED),
    )


def channel_mark(platform: rx.Var[str]) -> rx.Component:
    """The channel at a glance: a small tile in the platform's own colours (`.q-ch-*`,
    `assets/qualify-planner.css` — the brand said in Radix scales) with a generic glyph
    (Lucide has no brand logos) that inherits the tile's white, the platform's name as
    tooltip. Always next to the account handle, so the word is there too."""
    return rx.match(
        platform,
        *[
            (
                key,
                rx.center(
                    rx.icon(icon, size=10, stroke_width=2.5),
                    class_name=f"q-ch q-ch-{key}",
                    title=T.PLATFORM_LABEL.get(key, key),
                    aria_label=T.PLATFORM_LABEL.get(key, key),
                ),
            )
            for key, icon in _PLATFORM_ICON.items()
        ],
        rx.center(rx.icon("globe", size=10), class_name="q-ch"),
    )


def tag_badge(tag, *, solid: bool = False, closable: bool = False) -> rx.Component:
    """A planning tag in its palette colour (identity, like a platform: never a state).
    `closable` adds a trailing × so it reads as removable."""
    content = [tag.name, rx.icon("x", size=11)] if closable else [tag.name]
    return rx.match(
        tag.color,
        *[
            (
                c,
                rx.badge(
                    *content,
                    color_scheme=c,
                    variant="solid" if solid else "soft",
                    radius="full",
                    size="1",
                ),
            )
            for c in TAG_COLORS
        ],
        rx.badge(tag.name, color_scheme="gray", variant="soft", radius="full", size="1"),
    )


def tag_badge_plain(tag) -> rx.Component:
    """One-parameter form for `rx.foreach`, which counts the render function's params."""
    return tag_badge(tag)


def tag_dot(tag) -> rx.Component:
    return rx.box(
        class_name="q-tag-dot q-tint-" + tag.color,
        title=tag.name,
    )


def _section_title(icon: str, title: str, hint: str | rx.Var | None = None) -> rx.Component:
    return rx.hstack(
        rx.center(rx.icon(icon, size=15), class_name="q-section-glyph"),
        rx.vstack(
            rx.text(title, size="3", weight="bold"),
            *([rx.text(hint, size="1", color=T.TEXT_MUTED)] if hint is not None else []),
            spacing="0",
        ),
        align="center",
        spacing="3",
    )


def _label(text: str) -> rx.Component:
    return rx.text(text, class_name="q-field-label")


# ---------------------------------------------------------------------------
# Step «Contenido» — the grid


def _kind_filter(key: str, label: str) -> rx.Component:
    selected = PlannerState.form_kind_filter == key
    count = PlannerState.form_kind_counts[key]
    chip = rx.el.button(
        rx.icon(KIND_ICONS[key], size=13) if key != "all" else rx.icon("sparkles", size=13),
        label,
        rx.text(count.to_string(), as_="span", class_name="q-filter-count"),
        type="button",
        class_name=rx.cond(selected, "q-filter q-filter--on q-kind-" + key, "q-filter"),
        aria_pressed=selected,
        on_click=PlannerState.set_form_kind_filter(key),
    )
    if key == "all":
        return chip
    return rx.cond(count > 0, chip)


def _tile(post) -> rx.Component:
    selected = PlannerState.form_selected_ids.contains(post.post_id)
    state_class = rx.cond(
        post.schedulable,
        rx.cond(selected, " q-tile--ready q-tile--selected", " q-tile--ready"),
        " q-tile--pending",
    )
    return rx.el.button(
        rx.box(
            media_fill(post.thumbnail_url, post.video_url, post.kind),
            rx.box(class_name="q-tile-shade"),
            rx.box(kind_chip(post.kind, post.kind_label, glass=True), class_name="q-tile-tl"),
            rx.cond(
                post.schedulable,
                rx.box(
                    rx.icon("check", size=13, stroke_width=3),
                    class_name="q-tile-check",
                    aria_hidden="true",
                ),
            ),
            rx.box(
                temperature_badge(post.temperature, post.temperature_label, post.temperature_hint),
                class_name="q-tile-bl",
            ),
            rx.cond(
                ~post.schedulable,
                rx.center(
                    rx.vstack(
                        rx.icon("hourglass", size=16),
                        rx.text("No listo", size="1", weight="bold"),
                        align="center",
                        spacing="1",
                    ),
                    class_name="q-tile-pending",
                ),
            ),
            class_name="q-tile-media",
        ),
        rx.box(
            rx.text(post.title, size="1", weight="bold", style=_CLAMP_2, text_align="left"),
            rx.cond(
                post.schedulable,
                rx.hstack(
                    rx.text("Sale como", size="1", color=T.TEXT_MUTED),
                    rx.foreach(
                        post.destinations,
                        lambda d: rx.cond(
                            d.available,
                            rx.box(
                                destination_icon(d.key, 11),
                                class_name="q-dest-dot q-dest-" + d.key,
                                title=d.label,
                                aria_label=d.label,
                            ),
                        ),
                    ),
                    spacing="1",
                    align="center",
                ),
                rx.text(
                    rx.cond(post.readiness_note != "", post.readiness_note, post.approval_label),
                    size="1",
                    color=T.tone_color("warn", 11),
                    style=_ONE_LINE,
                ),
            ),
            class_name="q-tile-body",
        ),
        type="button",
        role="checkbox",
        aria_checked=selected,
        aria_disabled=~post.schedulable,
        aria_label=post.kind_label + " · " + post.title,
        title=rx.cond(
            post.schedulable,
            post.temperature_hint,
            "Aún no está listo: "
            + rx.cond(post.readiness_note != "", post.readiness_note, post.approval_label),
        ),
        # The same Cold/Hot frost and embers as the /drafts cards.
        class_name="q-tile q-kind-"
        + post.kind
        + state_class
        + " q-chip-temp q-chip-temp--"
        + post.temperature,
        on_click=PlannerState.toggle_plan_post(post.post_id),
    )


def _legend_item(swatch: rx.Component, title: str, text: str) -> rx.Component:
    return rx.hstack(
        swatch,
        rx.vstack(
            rx.text(title, size="1", weight="bold"),
            rx.text(text, size="1", color=T.TEXT_MUTED),
            spacing="0",
            min_width="0",
        ),
        align="center",
        spacing="2",
        min_width="0",
    )


def _legend() -> rx.Component:
    """How to read a tile, in one box at the top of the step: its frame (ready or not)
    and its temperature."""
    return rx.box(
        _legend_item(
            rx.box(class_name="q-legend-solid"),
            "Lista para programar",
            "Marco sólido: puedes elegirla.",
        ),
        _legend_item(
            rx.box(class_name="q-legend-dashed"),
            "Aún no está lista",
            "Marco punteado: falta aprobación, texto o media.",
        ),
        _legend_item(
            rx.box(rx.icon("snowflake", size=12), class_name="q-temp q-temp--cold q-temp--mini"),
            "Ya probada",
            "Ya salió antes y funcionó: puedes repetirla.",
        ),
        _legend_item(
            rx.box(rx.icon("flame", size=12), class_name="q-temp q-temp--hot q-temp--mini"),
            "Por probar",
            "Todavía no ha salido en tus redes.",
        ),
        class_name="q-legend-box",
    )


def _step_content() -> rx.Component:
    empty = rx.vstack(
        rx.center(rx.icon("layout-grid", size=22), class_name="q-section-glyph q-glyph-lg"),
        rx.text("No hay publicaciones para programar", size="3", weight="bold"),
        rx.text(
            "Crea una publicación y apruébala: aparecerá aquí lista para programar.",
            size="2",
            color=T.TEXT_MUTED,
            text_align="center",
        ),
        rx.link(
            rx.button(
                rx.icon("sparkles", size=16), "Crear una publicación", variant="soft", size="3"
            ),
            href="/create",
        ),
        align="center",
        spacing="3",
        padding="2.5rem 1rem",
        class_name="q-step-panel",
        width="100%",
    )
    return rx.vstack(
        # How to read a tile comes first, then the question and the pieces.
        rx.cond(PlannerState.schedulable.length() > 0, _legend()),
        # The question and how to pick, in one header panel.
        rx.box(
            _section_title(
                "layout-grid",
                "¿Qué vas a publicar?",
                "Elige una o varias publicaciones listas. Cada una tendrá su propio horario.",
            ),
            rx.cond(
                PlannerState.schedulable.length() > 0,
                rx.flex(
                    *[_kind_filter(key, label) for key, label in _KIND_FILTERS],
                    wrap="wrap",
                    gap="0.4rem",
                    width="100%",
                ),
            ),
            class_name="q-step-panel",
        ),
        rx.cond(
            PlannerState.schedulable.length() > 0,
            rx.box(rx.foreach(PlannerState.form_tiles, _tile), class_name="q-tile-grid"),
            empty,
        ),
        spacing="4",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Step «Programación» — one card per piece


def _meridiem(row, value: str, label: str) -> rx.Component:
    selected = row.meridiem == value
    return rx.el.button(
        label,
        type="button",
        class_name=rx.cond(selected, "q-ampm q-ampm--on", "q-ampm"),
        aria_pressed=selected,
        on_click=PlannerState.set_item_meridiem(row.post_id, value),
    )


def _time_picker(row) -> rx.Component:
    """Hour, minute and a. m./p. m. with the app's own controls (the native time popup
    is drawn by the browser and cannot be styled)."""
    return rx.hstack(
        rx.select.root(
            rx.select.trigger(aria_label="Hora", min_width="3.6rem"),
            rx.select.content(*[rx.select.item(str(h), value=str(h)) for h in range(1, 13)]),
            value=row.hour12,
            on_change=lambda v: PlannerState.set_item_hour12(row.post_id, v),
        ),
        rx.text(":", weight="bold", color=T.TEXT_MUTED),
        rx.select.root(
            rx.select.trigger(aria_label="Minutos", min_width="3.6rem"),
            rx.select.content(
                rx.foreach(PlannerState.minute_options, lambda m: rx.select.item(m, value=m))
            ),
            value=row.minute,
            on_change=lambda v: PlannerState.set_item_minute(row.post_id, v),
        ),
        rx.box(
            _meridiem(row, "am", "a. m."),
            _meridiem(row, "pm", "p. m."),
            class_name="q-ampm-group",
            role="group",
            aria_label="a. m. o p. m.",
        ),
        align="center",
        spacing="1",
    )


def _account_chip(row, c) -> rx.Component:
    """One account to publish this piece to. An incompatible one is listed, disabled,
    with the reason (QUA-118 AC 6) — it can never be chosen."""
    on = row.connection_ids.contains(c.id)
    return rx.el.button(
        platform_icon(c.platform),
        rx.text(c.label, as_="span"),
        rx.cond(on, rx.icon("check", size=12, stroke_width=3)),
        type="button",
        role="checkbox",
        aria_checked=on,
        disabled=~c.compatible,
        title=rx.cond(c.compatible, c.label, "No compatible: " + c.note),
        class_name=rx.cond(on, "q-choice q-choice--on", "q-choice"),
        on_click=PlannerState.toggle_item_connection(row.post_id, c.id),
    )


def _tag_chip(row, t) -> rx.Component:
    on = row.tag_ids.contains(t.id)
    return rx.el.button(
        rx.box(class_name="q-tag-dot q-tint-" + t.color),
        rx.text(t.name, as_="span"),
        type="button",
        role="checkbox",
        aria_checked=on,
        class_name=rx.cond(on, "q-choice q-choice--tag q-tint-" + t.color, "q-choice"),
        on_click=PlannerState.toggle_item_tag(row.post_id, t.id),
    )


def _suggested_chip(row, suggestion) -> rx.Component:
    """A recommended tag not created yet: one click creates it and puts it here."""
    return rx.el.button(
        rx.icon("plus", size=11),
        rx.text(suggestion.name, as_="span"),
        type="button",
        title=suggestion.hint,
        class_name="q-choice q-choice--ghost",
        on_click=PlannerState.add_suggested_tag(suggestion.name, suggestion.color, row.post_id),
    )


def _weekday_chip(row, day: int) -> rx.Component:
    on = row.repeat_days.contains(day)
    return rx.el.button(
        WEEKDAY_INITIALS[day],
        type="button",
        role="checkbox",
        aria_checked=on,
        aria_label=WEEKDAY_NAMES[day],
        title=WEEKDAY_NAMES[day].capitalize(),
        class_name=rx.cond(on, "q-weekday q-weekday--on", "q-weekday"),
        on_click=PlannerState.toggle_item_repeat_day(row.post_id, day),
    )


def _repeat(row) -> rx.Component:
    """QUA-118 v2: a weekly series — which days of the week, at what time, for how many
    weeks — with the dates it adds up to. Hidden on a reschedule (a move is one event)."""
    return rx.cond(
        ~PlannerState.form_is_reschedule,
        rx.vstack(
            rx.hstack(
                rx.switch(
                    checked=row.repeat,
                    on_change=lambda v: PlannerState.set_item_repeat(row.post_id, v),
                    aria_label="Repetir cada semana",
                    size="2",
                ),
                rx.icon("repeat", size=14, color=T.TEXT_MUTED),
                rx.text("Repetir cada semana", size="2", weight="medium"),
                align="center",
                spacing="2",
            ),
            rx.cond(
                row.repeat,
                rx.box(
                    rx.box(
                        _label("Días"),
                        rx.flex(
                            *[_weekday_chip(row, day) for day in range(7)],
                            gap="0.35rem",
                            wrap="wrap",
                        ),
                    ),
                    rx.box(
                        rx.box(_label("Hora"), _time_picker(row)),
                        rx.box(
                            _label("Durante"),
                            rx.hstack(
                                rx.input(
                                    type="number",
                                    min="1",
                                    max="12",
                                    value=row.repeat_count,
                                    on_change=lambda v: PlannerState.set_item_repeat_count(
                                        row.post_id, v
                                    ),
                                    width="4.5rem",
                                    size="2",
                                    aria_label="Semanas",
                                ),
                                rx.text("semanas", size="2", color=T.TEXT_MUTED),
                                align="center",
                                spacing="2",
                            ),
                        ),
                        class_name="q-repeat-row",
                    ),
                    rx.cond(
                        row.series.error != "",
                        rx.text(row.series.error, size="1", color=T.tone_color("warn", 11)),
                        rx.vstack(
                            rx.text(
                                row.series.summary,
                                size="1",
                                weight="bold",
                                color=T.TEXT_MUTED,
                            ),
                            rx.flex(
                                rx.foreach(
                                    row.series.dates, lambda d: rx.box(d, class_name="q-date-chip")
                                ),
                                wrap="wrap",
                                gap="0.25rem",
                            ),
                            spacing="1",
                            width="100%",
                        ),
                    ),
                    class_name="q-repeat-box",
                ),
            ),
            spacing="2",
            width="100%",
        ),
    )


def _destination_button(row, d) -> rx.Component:
    on = row.destination == d.key
    return rx.el.button(
        destination_icon(d.key, 18),
        rx.text(d.label, as_="span", class_name="q-dest-word"),
        rx.cond(on, rx.icon("check", size=12, stroke_width=3, class_name="q-dest-tick")),
        type="button",
        role="radio",
        aria_checked=on,
        disabled=~d.available,
        title=rx.cond(d.available, d.label, d.label + ": " + d.reason),
        class_name=rx.cond(
            on, "q-dest-btn q-dest-btn--on q-dest-" + d.key, "q-dest-btn q-dest-" + d.key
        ),
        on_click=PlannerState.set_item_destination(row.post_id, d.key),
    )


def _destination_selector(row) -> rx.Component:
    """«¿Dónde quieres publicarlo?» (QUA-118 v2): one button per destination Instagram
    could take for this content; an impossible one is shown off, with its reason written
    under it — not only on hover. A move keeps its destination (read-only)."""
    return rx.cond(
        PlannerState.form_is_reschedule,
        rx.box(
            _label("Destino"),
            rx.hstack(
                destination_badge(row.destination, row.destination_label, prefix="Sale como "),
                rx.text("Reprogramar mantiene el destino.", size="1", color=T.TEXT_MUTED),
                align="center",
                spacing="2",
                wrap="wrap",
            ),
            width="100%",
        ),
        rx.box(
            rx.text(
                "¿Dónde quieres publicarlo?",
                as_="div",
                class_name="q-field-label",
                id="dest-" + row.post_id,
            ),
            rx.box(
                rx.foreach(row.destinations, lambda d: _destination_button(row, d)),
                class_name="q-dest-seg",
                role="radiogroup",
                aria_labelledby="dest-" + row.post_id,
            ),
            rx.vstack(
                rx.foreach(
                    row.destinations,
                    lambda d: rx.cond(
                        ~d.available & (d.reason != ""),
                        rx.hstack(
                            rx.icon("info", size=12, flex_shrink="0", margin_top="2px"),
                            rx.text(
                                rx.text(d.label + ": ", as_="span", weight="bold"),
                                d.reason,
                                size="1",
                            ),
                            align="start",
                            spacing="1",
                            color=T.TEXT_MUTED,
                        ),
                    ),
                ),
                spacing="1",
                margin_top="0.45rem",
            ),
            rx.cond(
                row.destination_warning != "",
                rx.hstack(
                    rx.icon("triangle-alert", size=13, flex_shrink="0"),
                    rx.text(row.destination_warning, size="1"),
                    class_name="q-plan-status q-plan-status--todo",
                    margin_top="0.45rem",
                    align="start",
                ),
            ),
            rx.cond(
                row.destination == "story",
                rx.text(STORY_CAPTION_NOTE, size="1", color=T.TEXT_MUTED, margin_top="0.3rem"),
            ),
            width="100%",
        ),
    )


def _plan_campaign(row) -> rx.Component:
    """QUA-143: the POST's campaign, from the piece. The campaign belongs to the POST:
    the selector shows the POST's own, a change is applied to the POST on «Confirmar»
    (only once its publications were created), and the warning says it reaches every
    publication the POST already has."""
    picker = rx.select.root(
        rx.select.trigger(placeholder="Sin campaña", aria_label="Campaña de la publicación"),
        rx.select.content(
            rx.select.item("Sin campaña", value="none"),
            rx.cond(PlannerState.campaigns.length() > 0, rx.select.separator()),
            rx.foreach(
                PlannerState.campaigns,
                lambda c: rx.select.item(c.name, value=c.id),
            ),
            rx.select.separator(),
            rx.select.item("+ Nueva campaña", value="new"),
        ),
        value=row.campaign_value,
        on_change=lambda v: PlannerState.set_item_campaign(row.post_id, v),
        size="2",
    )
    new_campaign = rx.hstack(
        rx.input(
            value=row.new_campaign_name,
            on_change=lambda v: PlannerState.set_item_new_campaign_name(row.post_id, v),
            placeholder="Nombre de la nueva campaña",
            max_length=60,
            size="2",
            flex="1",
            min_width="10rem",
            aria_label="Nombre de la nueva campaña",
        ),
        color_swatches(
            row.new_campaign_color,
            lambda key: PlannerState.set_item_new_campaign_color(row.post_id, key),
            COLOR_LABELS,
            label="Color de la nueva campaña",
        ),
        align="center",
        spacing="3",
        wrap="wrap",
        width="100%",
    )
    new_campaign = rx.vstack(
        new_campaign,
        rx.text("Se creará al confirmar la programación.", size="1", color=T.TEXT_MUTED),
        spacing="1",
        width="100%",
    )
    return rx.box(
        _label("Campaña"),
        rx.vstack(
            picker,
            rx.cond(row.creating_campaign, new_campaign),
            rx.cond(
                row.campaign_warning != "",
                rx.hstack(
                    rx.icon("info", size=14, flex_shrink="0"),
                    rx.text(row.campaign_warning, size="1"),
                    class_name="q-plan-status q-plan-status--todo",
                    align="start",
                    spacing="1",
                ),
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        width="100%",
    )


def _confirm_campaign(row) -> rx.Component:
    """QUA-143, «Confirmar»: the campaign the piece's POST will have once programmed — and,
    when that is a change, what happens (created, changed or cleared) and what it reaches."""
    note = rx.cond(
        row.creating_campaign,
        "Campaña nueva: se creará al programar.",
        rx.cond(
            row.chosen_campaign_name == "",
            "La publicación quedará sin campaña al programar.",
            "La campaña de la publicación cambiará al programar.",
        ),
    )
    return rx.fragment(
        campaign_badge(row.chosen_campaign_name, row.chosen_campaign_color),
        rx.cond(
            row.campaign_changed,
            rx.text(
                note,
                rx.cond(row.campaign_warning != "", " " + row.campaign_warning, ""),
                size="1",
                color=T.TEXT_MUTED,
            ),
        ),
    )


def _when_choice(row, now: bool, label: str, icon: str) -> rx.Component:
    """One of «Elegir día y hora» / «Ahora» (m-24842985): a radio pair, thumb-sized."""
    on = row.now if now else ~row.now
    return rx.el.button(
        rx.icon(icon, size=14),
        rx.text(label, as_="span"),
        type="button",
        role="radio",
        aria_checked=on,
        class_name=rx.cond(on, "q-choice q-choice--on", "q-choice"),
        on_click=PlannerState.set_item_now(row.post_id, now),
    )


def _when_fields(row) -> rx.Component:
    """«¿Cuándo sale?» — only the day and the hour, or «Ahora» (N6)."""
    return rx.vstack(
        rx.box(
            _when_choice(row, False, "Elegir día y hora", "calendar-days"),
            _when_choice(row, True, NOW_LABEL, "zap"),
            class_name="q-when-choice",
            role="radiogroup",
            aria_label="¿Cuándo sale?",
        ),
        rx.cond(
            row.now,
            rx.hstack(
                rx.icon("info", size=14, flex_shrink="0", margin_top="2px"),
                rx.text(
                    "Sale unos minutos después de que toques «"
                    + PlannerState.form_submit_label
                    + "».",
                    size="2",
                ),
                align="start",
                spacing="2",
                color=T.TEXT_MUTED,
            ),
            rx.box(
                rx.box(
                    rx.cond(row.repeat, _label("Desde"), _label("Día")),
                    rx.input(
                        type="date",
                        value=row.date,
                        on_change=lambda v: PlannerState.set_item_date(row.post_id, v),
                        min=PlannerState.today_iso,
                        width="100%",
                        aria_label="Día",
                    ),
                ),
                rx.box(_label("Hora"), _time_picker(row)),
                class_name="q-plan-grid",
            ),
        ),
        spacing="2",
        width="100%",
    )


def _where_line(row) -> rx.Component:
    """Where it goes out, already chosen («Sale en Instagram @cuenta»), so the owner
    does not have to open «Más opciones» to know it."""
    return rx.cond(
        row.accounts_line != "",
        rx.hstack(
            rx.icon("send", size=14, flex_shrink="0", margin_top="2px"),
            rx.text(row.accounts_line, size="2"),
            align="start",
            spacing="2",
            color=T.TEXT_MUTED,
        ),
        rx.cond(
            PlannerState.connections.length() == 0,
            rx.vstack(
                rx.text(
                    "No hay cuentas activas: conéctalas en Tus redes.",
                    size="2",
                    color=T.tone_color("warn", 11),
                ),
                rx.link(
                    rx.hstack(
                        rx.text("Ir a Tus redes", size="2"),
                        rx.icon("arrow-right", size=14),
                        align="center",
                        spacing="1",
                    ),
                    href="/connections",
                    class_name="q-plan-link",
                ),
                spacing="1",
            ),
        ),
    )


def _more_options(row) -> rx.Component:
    """Everything that is not the day and the hour (N6): format, where, accounts,
    campaign, tags and weekly repetition — closed by default, open on its own when what
    is missing is in here (`row.needs_more`)."""
    return rx.accordion.root(
        rx.accordion.item(
            header=MORE_OPTIONS,
            content=rx.vstack(
                rx.cond(
                    row.has_outputs,
                    rx.box(
                        _label("Formato"),
                        rx.segmented_control.root(
                            rx.foreach(
                                row.outputs,
                                lambda o: rx.segmented_control.item(o.label, value=o.port),
                            ),
                            value=row.output_port,
                            on_change=lambda v: PlannerState.set_item_output(row.post_id, v),
                            size="1",
                        ),
                        width="100%",
                    ),
                ),
                _destination_selector(row),
                # With no account at all, the warning and «Ir a Tus redes» sit above the
                # fold (`_where_line`), so this box says nothing then.
                rx.cond(
                    PlannerState.connections.length() > 0,
                    rx.box(
                        _label("Canales"),
                        rx.flex(
                            rx.foreach(PlannerState.connections, lambda c: _account_chip(row, c)),
                            wrap="wrap",
                            gap="0.4rem",
                        ),
                        width="100%",
                    ),
                ),
                rx.cond(~PlannerState.form_is_reschedule, _plan_campaign(row)),
                rx.box(
                    _label("Etiquetas"),
                    rx.flex(
                        rx.foreach(PlannerState.tags, lambda t: _tag_chip(row, t)),
                        rx.foreach(PlannerState.tag_suggestions, lambda s: _suggested_chip(row, s)),
                        wrap="wrap",
                        gap="0.35rem",
                    ),
                    width="100%",
                ),
                _new_tag_box(),
                rx.cond(~row.now, _repeat(row)),
                rx.cond(
                    PlannerState.form_count > 1,
                    rx.button(
                        rx.icon("copy", size=12),
                        "Usar canales, etiquetas y campaña en todas",
                        size="2",
                        variant="ghost",
                        on_click=PlannerState.apply_to_all(row.post_id),
                    ),
                ),
                spacing="4",
                width="100%",
            ),
            value="more",
        ),
        value=rx.cond(PlannerState.more_open.contains(row.post_id), "more", ""),
        on_value_change=lambda v: PlannerState.set_item_more(row.post_id, v),
        collapsible=True,
        type="single",
        variant="ghost",
        width="100%",
        class_name="q-plan-more",
    )


def _plan_card(row) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.box(
                media_fill(row.thumbnail_url, row.video_url, row.kind),
                class_name="q-plan-thumb",
                style={"aspect_ratio": row.aspect},
            ),
            rx.vstack(
                rx.hstack(
                    kind_chip(row.kind, row.kind_label),
                    rx.icon("arrow-right", size=12, color=T.TEXT_FAINT),
                    destination_badge(row.destination, row.destination_label),
                    temperature_badge(row.temperature, row.temperature_label, row.temperature_hint),
                    # QUA-143: the campaign the POST has today (nothing when independent).
                    campaign_badge(row.current_campaign_name, row.current_campaign_color),
                    spacing="1",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(row.title, size="2", weight="bold", style=_CLAMP_2),
                spacing="1",
                min_width="0",
                flex="1",
            ),
            rx.cond(
                row.error == "",
                rx.box(
                    rx.icon("clock", size=12),
                    rx.text(row.when_label, as_="span"),
                    class_name="q-when-pill",
                ),
            ),
            align="start",
            spacing="3",
            width="100%",
            class_name="q-plan-head",
        ),
        _when_fields(row),
        _where_line(row),
        rx.hstack(
            rx.cond(
                row.error != "",
                rx.hstack(
                    rx.icon("circle-alert", size=14, flex_shrink="0"),
                    rx.text(row.error, size="1"),
                    class_name="q-plan-status q-plan-status--todo",
                ),
                rx.hstack(
                    rx.icon("circle-check", size=14, flex_shrink="0"),
                    rx.text(
                        rx.cond(
                            row.event_count == 1,
                            "Lista · 1 publicación",
                            "Lista · " + row.event_count.to_string() + " publicaciones",
                        ),
                        size="1",
                    ),
                    class_name="q-plan-status q-plan-status--ok",
                ),
            ),
            align="center",
            width="100%",
            wrap="wrap",
            gap="0.5rem",
        ),
        _more_options(row),
        class_name="q-plan-card q-kind-" + row.kind,
    )


def _new_tag_box() -> rx.Component:
    return rx.hstack(
        rx.icon("tag", size=14, color=T.TEXT_MUTED),
        rx.input(
            value=PlannerState.form_tag_query,
            on_change=PlannerState.set_form_tag_query,
            placeholder="Nueva etiqueta (p. ej. Campaña octubre)",
            size="1",
            flex="1",
            max_length=40,
        ),
        rx.button(
            rx.icon("plus", size=T.ICON_SM),
            "Crear",
            size="1",
            variant="soft",
            disabled=~PlannerState.form_can_create_tag,
            on_click=PlannerState.create_tag_in_form,
        ),
        align="center",
        width="100%",
        class_name="q-soft-box",
    )


def _step_schedule() -> rx.Component:
    """m-24842985 (N6): «Paso 2 de 3 · ¿Cuándo sale?» — one question per piece."""
    return rx.vstack(
        rx.flex(
            _section_title(
                "calendar-clock",
                "¿Cuándo sale?",
                rx.cond(
                    PlannerState.form_is_reschedule,
                    "Elige el nuevo día y la hora.",
                    "Elige el día y la hora, o «Ahora».",
                ),
            ),
            rx.box(
                rx.icon("globe", size=12),
                rx.text(PlannerState.tz_city_label, as_="span"),
                class_name="q-tz-chip",
                title=PlannerState.tz_name,
            ),
            justify="between",
            align="center",
            wrap="wrap",
            gap="0.5rem",
            width="100%",
        ),
        rx.foreach(PlannerState.plan_rows, _plan_card),
        spacing="4",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Step «Confirmar» — the day as it will go out


def _avatar() -> rx.Component:
    return rx.box(class_name="q-mock-avatar")


def _story_mock(row) -> rx.Component:
    return rx.box(
        media_fill(row.thumbnail_url, row.video_url, row.kind),
        rx.box(class_name="q-mock-top-shade"),
        rx.box(
            rx.box(class_name="q-story-bar q-story-bar--on"),
            rx.box(class_name="q-story-bar"),
            rx.box(class_name="q-story-bar"),
            class_name="q-story-bars",
        ),
        rx.hstack(
            _avatar(),
            rx.text(row.first_account, class_name="q-mock-handle", style=_ONE_LINE),
            rx.text(row.time_label, class_name="q-mock-meta"),
            align="center",
            spacing="1",
            class_name="q-mock-story-head",
        ),
        rx.box(
            rx.box("Enviar mensaje", class_name="q-mock-reply"),
            rx.icon("heart", size=12),
            rx.icon("send", size=12),
            class_name="q-mock-story-foot",
        ),
        class_name="q-mock q-mock--tall",
    )


def _reel_mock(row) -> rx.Component:
    return rx.box(
        media_fill(row.thumbnail_url, row.video_url, row.kind),
        rx.box(class_name="q-mock-bottom-shade"),
        rx.text("Reels", class_name="q-mock-reels"),
        rx.vstack(
            rx.icon("heart", size=14),
            rx.icon("message-circle", size=14),
            rx.icon("send", size=14),
            rx.icon("ellipsis", size=14),
            spacing="2",
            class_name="q-mock-rail",
        ),
        rx.box(
            rx.hstack(
                _avatar(),
                rx.text(row.first_account, class_name="q-mock-handle", style=_ONE_LINE),
                align="center",
                spacing="1",
            ),
            rx.text(row.title, class_name="q-mock-caption", style=_ONE_LINE),
            class_name="q-mock-reel-foot",
        ),
        rx.center(rx.icon("play", size=16, fill="white"), class_name="q-mock-play"),
        class_name="q-mock q-mock--tall",
    )


def _feed_mock(row) -> rx.Component:
    return rx.box(
        rx.hstack(
            _avatar(),
            rx.text(row.first_account, class_name="q-mock-handle q-mock-handle--ink"),
            rx.spacer(),
            rx.icon("ellipsis", size=12),
            align="center",
            spacing="1",
            class_name="q-mock-feed-head",
        ),
        rx.box(
            media_fill(row.thumbnail_url, row.video_url, row.kind),
            rx.cond(
                row.mock == "carousel",
                rx.box("1/3", class_name="q-mock-counter"),
            ),
            class_name="q-mock-feed-media",
            style={"aspect_ratio": row.aspect},
        ),
        rx.hstack(
            rx.icon("heart", size=12),
            rx.icon("message-circle", size=12),
            rx.icon("send", size=12),
            rx.spacer(),
            rx.cond(
                row.mock == "carousel",
                rx.hstack(
                    rx.box(class_name="q-dot q-dot--on"),
                    rx.box(class_name="q-dot"),
                    rx.box(class_name="q-dot"),
                    spacing="1",
                ),
            ),
            rx.spacer(),
            rx.icon("bookmark", size=12),
            align="center",
            spacing="2",
            class_name="q-mock-feed-actions",
        ),
        rx.text(
            rx.text(row.first_account, as_="span", weight="bold"),
            " ",
            row.title,
            class_name="q-mock-feed-caption",
            style=_CLAMP_2,
        ),
        class_name="q-mock q-mock--feed",
    )


def _mock(row) -> rx.Component:
    return rx.match(
        row.mock,
        ("story", _story_mock(row)),
        ("reel", _reel_mock(row)),
        _feed_mock(row),
    )


def _timeline_item(row) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text(row.time_label, class_name="q-tl-time"),
            rx.text(row.day_label, size="1", color=T.TEXT_MUTED),
            rx.box(class_name="q-tl-node"),
            spacing="1",
            align="end",
            class_name="q-tl-when",
        ),
        rx.box(
            _mock(row),
            rx.vstack(
                rx.hstack(
                    kind_chip(row.kind, row.kind_label),
                    rx.icon("arrow-right", size=12, color=T.TEXT_FAINT),
                    destination_badge(row.destination, row.destination_label),
                    temperature_badge(row.temperature, row.temperature_label, row.temperature_hint),
                    rx.spacer(),
                    rx.icon_button(
                        rx.icon("pencil", size=14),
                        size="1",
                        variant="soft",
                        color_scheme="gray",
                        aria_label="Editar " + row.title,
                        title="Editar horario, canales y etiquetas",
                        on_click=PlannerState.edit_plan_item(row.post_id),
                    ),
                    rx.cond(
                        ~PlannerState.form_is_reschedule,
                        rx.icon_button(
                            rx.icon("trash-2", size=14),
                            size="1",
                            variant="soft",
                            color_scheme="red",
                            aria_label="Quitar " + row.title + " del plan",
                            title="Quitar del plan",
                            on_click=PlannerState.remove_plan_item(row.post_id),
                        ),
                    ),
                    align="center",
                    spacing="1",
                    width="100%",
                ),
                rx.text(row.title, size="2", weight="bold", style=_CLAMP_2),
                rx.cond(row.sale_line != "", rx.text(row.sale_line, size="2")),
                rx.flex(
                    rx.foreach(
                        row.accounts,
                        lambda c: rx.box(
                            platform_icon(c.platform, 12),
                            rx.text(c.label, as_="span"),
                            class_name="q-mini-chip",
                        ),
                    ),
                    wrap="wrap",
                    gap="0.3rem",
                ),
                _confirm_campaign(row),
                rx.cond(
                    row.tags.length() > 0,
                    rx.flex(rx.foreach(row.tags, tag_badge_plain), wrap="wrap", gap="0.25rem"),
                ),
                rx.cond(
                    row.repeat,
                    rx.hstack(
                        rx.icon("repeat", size=12),
                        rx.text(row.series.summary, size="1"),
                        align="center",
                        spacing="1",
                        color=T.TEXT_MUTED,
                    ),
                ),
                rx.cond(
                    row.destination_warning != "",
                    rx.hstack(
                        rx.icon("triangle-alert", size=12, flex_shrink="0"),
                        rx.text(row.destination_warning),
                        class_name="q-plan-status q-plan-status--todo",
                        align="start",
                    ),
                ),
                rx.cond(
                    row.destination == "story",
                    rx.text(STORY_CAPTION_NOTE, size="1", color=T.TEXT_MUTED),
                ),
                rx.cond(
                    row.note != "",
                    rx.hstack(
                        rx.icon("triangle-alert", size=12, flex_shrink="0"),
                        rx.text("Se programa, pero no sale hasta que esté listo: " + row.note),
                        class_name="q-plan-status q-plan-status--todo",
                        align="start",
                    ),
                ),
                spacing="2",
                min_width="0",
                flex="1",
            ),
            class_name="q-tl-card q-kind-" + row.kind,
        ),
        class_name="q-tl-item",
    )


def _goal(goal) -> rx.Component:
    on = PlannerState.form_goals.contains(goal.key)
    return rx.el.button(
        rx.center(rx.icon(goal.icon, size=16), class_name="q-goal-glyph"),
        rx.box(
            rx.text(goal.label, as_="div", class_name="q-goal-label"),
            rx.text(goal.hint, as_="div", class_name="q-goal-hint"),
            text_align="left",
            min_width="0",
        ),
        rx.box(
            rx.icon("check", size=12, stroke_width=3),
            class_name="q-goal-check",
            aria_hidden="true",
        ),
        type="button",
        role="checkbox",
        aria_checked=on,
        class_name=rx.cond(
            on, f"q-goal q-goal--on q-tint-{goal.color}", f"q-goal q-tint-{goal.color}"
        ),
        on_click=PlannerState.toggle_goal(goal.key),
    )


def _goals() -> rx.Component:
    return rx.vstack(
        _section_title("target", "Metas de esta planificación", "¿Qué buscas conseguir?"),
        rx.box(*[_goal(g) for g in PLAN_GOALS], class_name="q-goal-grid"),
        spacing="3",
        width="100%",
    )


def _step_confirm() -> rx.Component:
    return rx.vstack(
        rx.box(
            rx.center(rx.icon("calendar-check", size=20), class_name="q-hero-glyph"),
            rx.vstack(
                rx.text(
                    rx.cond(
                        PlannerState.form_is_reschedule,
                        "Así queda la publicación",
                        "Así sale tu plan",
                    ),
                    size="4",
                    weight="bold",
                ),
                rx.text(PlannerState.form_confirm_line, size="3", weight="medium"),
                rx.text(
                    "Hora de "
                    + PlannerState.form_tz_city
                    + " · Nada sale antes de que toques «"
                    + PlannerState.form_submit_label
                    + "».",
                    size="1",
                    opacity="0.8",
                ),
                spacing="1",
            ),
            class_name="q-hero",
        ),
        rx.box(rx.foreach(PlannerState.plan_rows_by_time, _timeline_item), class_name="q-tl"),
        rx.cond(
            ~PlannerState.form_is_reschedule,
            rx.accordion.root(
                rx.accordion.item(header=MORE_OPTIONS_GOALS, content=_goals(), value="goals"),
                collapsible=True,
                type="single",
                variant="ghost",
                width="100%",
                class_name="q-plan-more",
            ),
        ),
        rx.cond(
            PlannerState.form_story_warnings > 0,
            callout(
                "Tienes historias de video en este plan. Instagram rechaza una Historia de "
                "video de más de 60 segundos; revisa su duración antes de confirmar.",
                "warn",
            ),
        ),
        rx.cond(PlannerState.form_error != "", callout(PlannerState.form_error, "error")),
        spacing="5",
        width="100%",
    )


# ---------------------------------------------------------------------------
# The drawer


def _assign_footer() -> rx.Component:
    """The drawer's foot: «Cancelar» on the left, what is chosen (or what is missing)
    in the middle, «Atrás» / «Continuar» (or «Programar») on the right — every button
    the same size, each with its glyph, a clear gap between them."""
    return rx.flex(
        rx.button(
            rx.icon("x", size=16),
            "Cancelar",
            variant="soft",
            color_scheme="gray",
            size="3",
            on_click=PlannerState.close_form,
        ),
        rx.box(
            rx.cond(
                PlannerState.form_step == STEP_POST,
                rx.cond(
                    PlannerState.form_count > 0,
                    rx.box(
                        rx.icon("circle-check", size=13),
                        rx.text(PlannerState.form_selection_label, as_="span"),
                        class_name="q-selection-pill",
                    ),
                    rx.text(PlannerState.form_selection_label, size="1", color=T.TEXT_MUTED),
                ),
                rx.cond(
                    PlannerState.form_step_error != "",
                    rx.text(
                        PlannerState.form_step_error,
                        size="1",
                        color=T.tone_color("warn", 11),
                        style=_CLAMP_2,
                    ),
                ),
            ),
            flex="1",
            min_width="0",
            text_align="center",
            class_name="q-assign-foot-status",
        ),
        rx.flex(
            rx.cond(
                (PlannerState.form_step > STEP_POST)
                & ~(PlannerState.form_is_reschedule & (PlannerState.form_step == STEP_WHEN)),
                rx.button(
                    rx.icon("chevron-left", size=16),
                    "Atrás",
                    variant="soft",
                    color_scheme="gray",
                    size="3",
                    on_click=PlannerState.prev_step,
                ),
            ),
            rx.cond(
                PlannerState.form_is_last_step,
                rx.button(
                    rx.icon("calendar-check", size=16),
                    PlannerState.form_submit_label,
                    loading=PlannerState.saving,
                    size="3",
                    on_click=PlannerState.submit_form,
                    class_name="q-cta",
                ),
                rx.button(
                    "Continuar",
                    rx.icon("chevron-right", size=16),
                    size="3",
                    disabled=~PlannerState.form_can_advance,
                    title=PlannerState.form_step_error,
                    on_click=PlannerState.next_step,
                    class_name="q-cta",
                ),
            ),
            gap="0.75rem",
            flex_shrink="0",
            class_name="q-assign-foot-nav",
        ),
        align="center",
        gap="0.75rem",
        width="100%",
        class_name="q-assign-foot",
    )


def assign_drawer() -> rx.Component:
    """«Nueva publicación» / «Reprogramar publicación» (QUA-118 v2): Contenido →
    Programación → Confirmar. A step must be valid to leave it; a completed step is one
    click away to fix; «Confirmar» is where the service's answer lands."""
    return drawer(
        flow_sync(
            PlannerState.form_flow_name,
            PlannerState.form_flow_step,
            ready=PlannerState.flow_ready,
            objeto=PlannerState.form_event_id,
        ),
        rx.box(
            rx.cond(
                PlannerState.form_is_reschedule,
                stepper(
                    list(ASSIGN_STEPS[1:]),
                    current=PlannerState.form_step - 1,
                    completed=PlannerState.form_steps_done[1:],
                    on_select=lambda index: PlannerState.go_to_step(index + 1),
                    icons=list(ASSIGN_STEP_ICONS[1:]),
                ),
                stepper(
                    list(ASSIGN_STEPS),
                    current=PlannerState.form_step,
                    completed=PlannerState.form_steps_done,
                    on_select=PlannerState.go_to_step,
                    icons=list(ASSIGN_STEP_ICONS),
                ),
            ),
            class_name="q-stepper-wrap",
            display=rx.breakpoints(initial="none", sm="block"),
        ),
        rx.box(
            rx.match(
                PlannerState.form_step,
                (STEP_POST, _step_content()),
                (STEP_WHEN, _step_schedule()),
                (STEP_PREVIEW, _step_confirm()),
                _step_content(),
            ),
            margin_top="1.25rem",
            width="100%",
        ),
        open=PlannerState.form_open,
        on_open_change=PlannerState.set_form_open,
        title=PlannerState.form_title,
        step=rx.vstack(
            step_progress(PlannerState.form_flow_step, PlannerState.form_step_total),
            rx.text(PlannerState.form_step_name, size="2", weight="medium"),
            spacing="1",
            width="100%",
        ),
        description=rx.cond(
            PlannerState.form_is_reschedule,
            "Mueve la publicación a otra fecha, hora o cuenta.",
            "Arma tu día: elige las publicaciones, dales hora y cuenta, y confirma. "
            "Nada se publica hasta su hora.",
        ),
        footer=_assign_footer(),
        width="46rem",
        icon="calendar-plus",
    )


# ---------------------------------------------------------------------------
# The event's panel (was a dialog) — the planned publication AND its POST


def _detail_tag(tag) -> rx.Component:
    """A tag on the open event: click to take it off (saved right away)."""
    return rx.box(
        tag_badge(tag, closable=True),
        on_click=PlannerState.remove_detail_tag(tag.id),
        cursor="pointer",
        title="Quitar etiqueta",
    )


def _detail_add_tag() -> rx.Component:
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(rx.icon("plus", size=12), "Etiqueta", size="1", variant="ghost"),
        ),
        rx.dropdown_menu.content(
            rx.cond(
                PlannerState.detail_available_tags.length() > 0,
                rx.foreach(
                    PlannerState.detail_available_tags,
                    lambda t: rx.dropdown_menu.item(
                        rx.hstack(tag_dot(t), rx.text(t.name), align="center", spacing="2"),
                        on_click=PlannerState.add_detail_tag(t.id),
                    ),
                ),
                rx.dropdown_menu.item(
                    "No hay más etiquetas. Créalas desde «Etiquetas» o al programar.",
                    disabled=True,
                ),
            ),
            size="1",
        ),
    )


def _fact_tile(icon: str, label: str, *value: rx.Component) -> rx.Component:
    """One fact of the event as a tile of the panel's grid: glyph, small caps label,
    value. Every tile has the same edges, so the grid reads as one aligned block."""
    return rx.box(
        rx.hstack(
            rx.center(rx.icon(icon, size=13), class_name="q-fact-glyph"),
            rx.text(label, class_name="q-fact-label"),
            align="center",
            spacing="2",
        ),
        rx.box(*value, class_name="q-fact-value"),
        class_name="q-fact-tile",
    )


def _panel_section(icon: str, title: str, *children: rx.Component, action=None) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.icon(icon, size=14, color=T.TEXT_MUTED),
            rx.text(title, class_name="q-fact-label"),
            rx.spacer(),
            *([action] if action is not None else []),
            align="center",
            spacing="2",
            width="100%",
        ),
        *children,
        class_name="q-panel-section",
    )


def _detail_goal(goal) -> rx.Component:
    """One goal on the event's panel, in its own colour and glyph (as in «Nueva
    publicación»); a click turns it on or off, saved right away."""
    on = PlannerState.detail.goal_keys.contains(goal.key)
    return rx.el.button(
        rx.icon(goal.icon, size=13),
        rx.text(goal.label, as_="span"),
        rx.cond(on, rx.icon("check", size=12, stroke_width=3)),
        type="button",
        role="checkbox",
        aria_checked=on,
        title=goal.hint,
        class_name=rx.cond(
            on,
            f"q-goal-chip q-goal-chip--on q-tint-{goal.color}",
            f"q-goal-chip q-tint-{goal.color}",
        ),
        on_click=PlannerState.toggle_detail_goal(goal.key),
    )


def _detail_body() -> rx.Component:
    """The event panel's body (QUA-118 v2): a stage with the piece as it will look, the
    title and its states, an aligned grid of facts (when, channel, destination, content),
    then the POST's text, the tags and what may keep it from going out."""
    d = PlannerState.detail
    p = PlannerState.detail_post
    media = rx.cond(
        d.video_url != "",
        rx.video(
            src=BACKEND_BASE + d.video_url,
            controls=True,
            muted=True,
            preload="metadata",
            width="100%",
            height="100%",
            style={"object_fit": "cover", "background": "black"},
        ),
        media_fill(d.thumbnail_url, "", d.kind),
    )
    stage = rx.box(
        rx.box(
            rx.cond(
                d.thumbnail_url != "",
                rx.image(src=viewable_src(d.thumbnail_url), alt="", class_name="q-stage-blur"),
            ),
            class_name="q-stage-bg",
        ),
        rx.hstack(
            kind_chip(d.kind, d.kind_label, glass=True),
            rx.spacer(),
            temperature_badge(p.temperature, p.temperature_label, p.temperature_hint),
            class_name="q-stage-top",
            align="center",
        ),
        rx.box(media, class_name="q-detail-media q-detail-media--" + d.destination),
        rx.box(
            destination_badge(d.destination, d.destination_label, prefix="Sale como "),
            class_name="q-stage-bottom",
        ),
        class_name="q-stage q-dest-" + d.destination,
    )
    facts = rx.box(
        _fact_tile(
            "calendar-clock",
            "Cuándo",
            rx.text(d.when_label, size="2", weight="bold"),
        ),
        _fact_tile(
            "radio-tower",
            "Canal",
            rx.hstack(
                channel_mark(d.platform),
                rx.text(d.account_label, size="2", weight="bold", style=_ONE_LINE),
                align="center",
                spacing="2",
                min_width="0",
            ),
        ),
        _fact_tile(
            "send",
            "Destino",
            destination_badge(d.destination, d.destination_label),
        ),
        _fact_tile(
            "shapes",
            "Contenido",
            rx.hstack(
                kind_chip(d.kind, d.kind_label),
                rx.cond(
                    d.content_type_label != "",
                    rx.text(d.content_type_label, size="2", color=T.TEXT_MUTED),
                ),
                align="center",
                spacing="2",
                wrap="wrap",
            ),
        ),
        rx.cond(
            d.output_label != "",
            _fact_tile("layers", "Formato", rx.text(d.output_label, size="2", weight="bold")),
        ),
        # QUA-143: the POST's campaign — shown only when the POST belongs to one.
        rx.cond(
            d.campaign_name != "",
            _fact_tile("flag", "Campaña", campaign_badge(d.campaign_name, d.campaign_color)),
        ),
        # `revision` is the event's reschedule counter (it keys the publish attempt, so a
        # moved event can never collide with the old one) — internal. Shown only once it
        # means something: how many times the publication was moved.
        rx.cond(
            d.revision > 1,
            _fact_tile(
                "history",
                "Reprogramado",
                rx.text(
                    rx.cond(d.revision == 2, "1 vez", (d.revision - 1).to_string() + " veces"),
                    size="2",
                    weight="bold",
                ),
            ),
        ),
        class_name="q-fact-grid",
    )
    notes = rx.fragment(
        rx.cond(
            # QUA-115: an expired event will NOT publish when it is ready — only a
            # reschedule brings it back, so the expiry note replaces the readiness one.
            d.expired,
            callout(EXPIRED_NOTE, "warn"),
            rx.cond(
                d.publish_note != "",
                callout(
                    "No se publicará hasta completarlo: "
                    + d.publish_note
                    + " La publicación sigue programada y sale en el siguiente minuto en que "
                    "esté lista.",
                    "warn",
                ),
            ),
        ),
        rx.cond(
            d.destination == "story",
            callout(STORY_CAPTION_NOTE, "info"),
        ),
        # m-24842984: in review, what approving means — nothing goes out without the
        # owner, and if they approve it goes out on the day and hour they chose (N13).
        # The hour only when the worker can publish for this tenant and nothing else is
        # missing (UX review): otherwise just «Nada sale sin tu aprobación.».
        rx.cond(
            d.can_reject_post,
            rx.cond(
                PlannerState.auto_publish == AUTO_PUBLISH_ACTIVE,
                callout(d.review_line, "info"),
                callout(REVIEW_NOTHING_WITHOUT_YOU, "info"),
            ),
        ),
        # «Aprobar» refused for the text itself: the way out stays on the panel, with a
        # link to where it is edited (N3/N4 — the toast alone is a dead end).
        rx.cond(
            PlannerState.review_error != "",
            rx.vstack(
                callout(PlannerState.review_error, "warn"),
                rx.cond(
                    d.detail_href != "",
                    rx.link(
                        REVIEW_EDIT_LINK,
                        href=d.detail_href + PlannerState.week_return_query,
                        size="2",
                    ),
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.match(
            PlannerState.auto_publish,
            (
                AUTO_PUBLISH_ACTIVE,
                # N13 (m-24842959): nothing goes out without the owner's approval, so the
                # line names that approval and only shows for an approved, still
                # scheduled publication — never a generic «automatic publishing» promise.
                rx.cond(
                    (d.approval_tone == "ok")
                    & (d.status_tone == "info")
                    & ~d.expired
                    & (d.approved_line != ""),
                    rx.hstack(
                        rx.box(class_name="q-live-dot"),
                        rx.text(
                            d.approved_line,
                            size="1",
                            color=T.TEXT_MUTED,
                        ),
                        align="center",
                        spacing="2",
                    ),
                ),
            ),
            (
                AUTO_PUBLISH_NO_CONNECTION,
                rx.vstack(
                    callout(
                        "Conecta tu cuenta en Tus redes para que esta publicación pueda salir.",
                        "warn",
                    ),
                    rx.link(
                        rx.hstack(
                            rx.text("Ir a Tus redes", size="2"),
                            rx.icon("arrow-right", size=14),
                            align="center",
                            spacing="1",
                        ),
                        href="/connections",
                    ),
                    spacing="2",
                    width="100%",
                ),
            ),
            callout(
                "Ahora mismo no podemos publicar a la hora programada. Tus publicaciones "
                "siguen guardadas; revisa esta pantalla más tarde.",
                "warn",
            ),
        ),
    )
    return rx.vstack(
        stage,
        rx.vstack(
            rx.text(d.title, size="5", weight="bold", line_height="1.25"),
            rx.flex(
                pill(d.approval_label, d.approval_tone),
                pill(d.status_label, d.status_tone),
                wrap="wrap",
                gap="0.35rem",
            ),
            spacing="2",
            width="100%",
        ),
        facts,
        _panel_section(
            "file-text",
            "Lo que se publica",
            rx.cond(
                d.caption_excerpt != "",
                rx.text(d.caption_excerpt, size="2", class_name="q-caption-quote"),
                rx.text("Sin texto.", size="2", color=T.TEXT_MUTED),
            ),
            action=rx.cond(
                d.detail_href != "",
                # Stays in Qualify (N9: no ↗) and comes back with «‹ Tu semana».
                rx.link(
                    rx.button(
                        "Ver publicación",
                        size="2",
                        variant="ghost",
                        min_height="44px",
                    ),
                    href=d.detail_href + PlannerState.week_return_query,
                ),
            ),
        ),
        _panel_section(
            "target",
            "Metas de esta publicación",
            rx.box(*[_detail_goal(goal) for goal in PLAN_GOALS], class_name="q-goal-chips"),
            rx.text(
                "Toca para activar o quitar. Se guardan para analizar después qué buscaba "
                "cada publicación.",
                size="1",
                color=T.TEXT_MUTED,
            ),
        ),
        _panel_section(
            "tag",
            "Etiquetas",
            rx.flex(
                rx.foreach(d.tags, _detail_tag),
                _detail_add_tag(),
                wrap="wrap",
                gap="0.35rem",
                align="center",
            ),
        ),
        notes,
        spacing="4",
        width="100%",
    )


def _confirm_bar(text: str, action_label: str, on_confirm) -> rx.Component:
    """The panel asks before cancelling or removing: the question on top, then «Volver»
    and the red confirmation side by side — same size and shape as the actions."""
    return rx.vstack(
        rx.hstack(
            rx.icon("triangle-alert", size=16, color=T.tone_color("error", 11), flex_shrink="0"),
            rx.text(text, size="2"),
            align="start",
            spacing="2",
            width="100%",
        ),
        rx.box(
            rx.button(
                rx.icon("arrow-left", size=16),
                "Volver",
                variant="soft",
                color_scheme="gray",
                size="3",
                on_click=PlannerState.dismiss_confirm,
            ),
            rx.button(
                rx.icon("circle-x", size=16),
                action_label,
                color_scheme="red",
                size="3",
                on_click=on_confirm,
            ),
            class_name="q-panel-actions",
        ),
        spacing="3",
        width="100%",
        class_name="q-confirm-bar",
    )


def _detail_footer() -> rx.Component:
    """The event's actions as two equal buttons across the panel's foot — what undoes
    the plan (outlined red) on the left, what moves it (solid) on the right. Every
    button the same size, each with its glyph."""
    d = PlannerState.detail
    # m-24842984: a publication still in review is decided right here — «No la quiero»
    # (outlined red) and «Aprobar» (solid), the gallery's own approval. Its own row, so
    # the decision never gets mixed with moving or cancelling the date.
    review = rx.cond(
        d.can_reject_post,
        # «Aprobar» first: on a phone the grid is one column, so the first thing under
        # the thumb is approving, never discarding (UX review).
        rx.box(
            rx.button(
                rx.icon("check", size=16),
                "Aprobar",
                size="3",
                loading=PlannerState.review_busy,
                on_click=PlannerState.approve_post_from_detail,
            ),
            rx.button(
                rx.icon("thumbs-down", size=16),
                "No la quiero",
                variant="outline",
                color_scheme="red",
                size="3",
                disabled=PlannerState.review_busy,
                on_click=PlannerState.reject_post_from_detail,
            ),
            class_name="q-panel-actions",
        ),
    )
    actions = rx.box(
        rx.cond(
            d.can_remove_rejected,
            rx.button(
                rx.icon("trash-2", size=16),
                "Quitar del calendario",
                variant="outline",
                color_scheme="red",
                size="3",
                on_click=PlannerState.ask_remove_rejected,
            ),
        ),
        rx.cond(
            d.can_modify,
            rx.fragment(
                rx.button(
                    rx.icon("calendar-x", size=16),
                    "Cancelar publicación",
                    variant="outline",
                    color_scheme="red",
                    size="3",
                    on_click=PlannerState.ask_cancel_from_detail,
                ),
                rx.button(
                    rx.icon("calendar-clock", size=16),
                    "Reprogramar",
                    size="3",
                    on_click=PlannerState.reschedule_from_detail,
                ),
            ),
        ),
        class_name="q-panel-actions",
    )
    return rx.match(
        PlannerState.detail_confirm,
        (
            CONFIRM_CANCEL,
            _confirm_bar(
                "¿Cancelar esta publicación? Sale del calendario y vuelve a «Sin programar»; "
                "su contenido no cambia.",
                "Sí, cancelar",
                PlannerState.confirm_cancel,
            ),
        ),
        (
            CONFIRM_REMOVE,
            _confirm_bar(
                "¿Quitar la publicación rechazada del calendario? Se cancelan sus fechas "
                "programadas pendientes; lo ya publicado se conserva.",
                "Sí, quitar",
                PlannerState.confirm_remove_rejected,
            ),
        ),
        rx.vstack(review, actions, spacing="3", width="100%"),
    )


def event_panel() -> rx.Component:
    """The planned publication, in a side panel like «Nueva publicación» (never a
    modal): the POST itself — media, text, format, Cold/Hot — when and where it goes
    out, its tags, and what can be done with it. Confirmations happen in the footer."""
    return drawer(
        rx.vstack(
            # m-24842987 (N7): on a phone the panel is the whole screen; its way back
            # names where it goes — the same week, in the same view. Outside the
            # loading/error branches so it is always there; phone only, since on a
            # wide screen the week shows behind and the panel's X already says it.
            rx.el.div(
                rx.button(
                    rx.icon("chevron-left", size=T.ICON_MD),
                    BACK_TO_WEEK,
                    variant="ghost",
                    size="3",
                    min_height="44px",
                    on_click=PlannerState.set_detail_open(False),
                ),
                class_name="q-narrow-only",
            ),
            rx.cond(
                PlannerState.detail_loading,
                # content loading (the POST, its media, dates): a skeleton, never a spinner
                rx.box(skeleton_card(5), padding="0.5rem 0", width="100%"),
                rx.cond(
                    PlannerState.detail_error != "",
                    callout(PlannerState.detail_error, "error"),
                    _detail_body(),
                ),
            ),
            width="100%",
        ),
        open=PlannerState.detail_open,
        on_open_change=PlannerState.set_detail_open,
        title="Publicación planificada",
        icon="calendar-check",
        description="Qué sale, cuándo y dónde. Desde aquí la apruebas, la mueves o la cancelas.",
        footer=_detail_footer(),
        width="36rem",
    )
