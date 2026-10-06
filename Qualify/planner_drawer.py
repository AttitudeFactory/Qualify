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
2. **Programación** — one card per piece: date, time, accounts, tags, output and weekly
   repetition, each piece on its own (a story at 2 a. m., a carousel at 10 a. m., a reel
   at 11 a. m.).
3. **Confirmar** — the day as it will go out: a phone-shaped mock of each piece in its
   channel's shape (story bars, reel rail, feed header) on a timeline, each with ✎ / 🗑,
   and the plan's goals (likes, vistas, comentarios, ads, seguidores, interacción).

Colours are identity here, never state: a format has its scale (`q-kind-*` in
`assets/qualify.css`), a goal has its scale, and Cold/Hot their own gradient. States keep
speaking through `signal_pill` tones.
"""

from __future__ import annotations

import reflex as rx

from .planner_state import CONFIRM_CANCEL, CONFIRM_REMOVE, PlannerState
from .planner_vm import (
    ASSIGN_STEP_ICONS,
    ASSIGN_STEPS,
    AUTO_PUBLISH_ACTIVE,
    AUTO_PUBLISH_NO_CONNECTION,
    EXPIRED_NOTE,
    KIND_ICONS,
    PLAN_GOALS,
    STEP_POST,
    STEP_PREVIEW,
    STEP_WHEN,
    TAG_COLORS,
)
from .post_card import kind_chip, kind_icon, pill, temperature_badge
from .r2_media import BACKEND_BASE
from .ui import callout, drawer, platform_badge, stepper
from .ui import tokens as T

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
    ("reel", "Reels"),
    ("story", "Historias"),
    ("gallery", "Carruseles"),
    ("feed", "Feed"),
    ("pack", "Multiformato"),
)


# ---------------------------------------------------------------------------
# Small shared pieces (also used by the calendar)


def platform_icon(platform: rx.Var[str], size: int = T.ICON_SM) -> rx.Component:
    return rx.match(
        platform,
        *[
            (key, rx.icon(icon, size=size, color=rx.color(T.platform_scale(key), 9)))
            for key, icon in _PLATFORM_ICON.items()
        ],
        rx.icon("globe", size=size, color=T.TEXT_MUTED),
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


def media_fill(thumbnail_url: rx.Var[str], video_url: rx.Var[str], kind: rx.Var[str]):
    """A POST's picture filling its frame: the R2 video's first frame, the image, or —
    with neither — the format's own gradient and glyph."""
    return rx.cond(
        video_url != "",
        rx.el.video(
            src=BACKEND_BASE + video_url + "#t=0.1",
            muted=True,
            preload="metadata",
            plays_inline=True,
            aria_hidden="true",
            class_name="q-media-fill",
        ),
        rx.cond(
            thumbnail_url != "",
            rx.image(
                src=rx.cond(
                    thumbnail_url.startswith("http"),
                    thumbnail_url,
                    rx.get_upload_url(thumbnail_url),
                ),
                alt="",
                class_name="q-media-fill",
            ),
            rx.center(kind_icon(kind, 26), class_name="q-media-empty q-kind-" + kind),
        ),
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
                rx.text(post.media_label, size="1", color=T.TEXT_MUTED, style=_ONE_LINE),
                rx.text(
                    rx.cond(post.readiness_note != "", post.readiness_note, post.approval_label),
                    size="1",
                    color=rx.color("amber", 11),
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
        class_name="q-tile q-kind-" + post.kind + state_class,
        on_click=PlannerState.toggle_plan_post(post.post_id),
    )


def _temperature_legend() -> rx.Component:
    return rx.hstack(
        rx.box(
            rx.icon("snowflake", size=12),
            rx.text("Cold", as_="span"),
            class_name="q-temp q-temp--cold",
        ),
        rx.text("probado, evergreen", size="1", color=T.TEXT_MUTED),
        rx.box(
            rx.icon("flame", size=12), rx.text("Hot", as_="span"), class_name="q-temp q-temp--hot"
        ),
        rx.text("nuevo, en prueba", size="1", color=T.TEXT_MUTED),
        align="center",
        spacing="2",
        wrap="wrap",
    )


def _step_content() -> rx.Component:
    empty = rx.vstack(
        rx.center(rx.icon("layout-grid", size=22), class_name="q-section-glyph q-glyph-lg"),
        rx.text("No hay POSTs para planificar", size="3", weight="bold"),
        rx.text(
            "Crea una pieza y apruébala: aparecerá aquí lista para programar.",
            size="2",
            color=T.TEXT_MUTED,
            text_align="center",
        ),
        rx.link(rx.button("Crear pieza", variant="soft"), href="/create"),
        align="center",
        spacing="3",
        padding="2.5rem 1rem",
    )
    return rx.vstack(
        rx.flex(
            _section_title(
                "layout-grid",
                "¿Qué vas a publicar?",
                "Elige una o varias piezas listas. Cada una tendrá su propio horario.",
            ),
            _temperature_legend(),
            justify="between",
            align="center",
            wrap="wrap",
            gap="0.75rem",
            width="100%",
        ),
        rx.cond(
            PlannerState.schedulable.length() > 0,
            rx.fragment(
                rx.flex(
                    *[_kind_filter(key, label) for key, label in _KIND_FILTERS],
                    wrap="wrap",
                    gap="0.4rem",
                    width="100%",
                ),
                rx.box(rx.foreach(PlannerState.form_tiles, _tile), class_name="q-tile-grid"),
                rx.hstack(
                    rx.box(class_name="q-legend-solid"),
                    rx.text("Lista para programar", size="1", color=T.TEXT_MUTED),
                    rx.box(class_name="q-legend-dashed"),
                    rx.text(
                        "Aún no está lista (aprobación, texto o media pendiente)",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    align="center",
                    spacing="2",
                    wrap="wrap",
                ),
            ),
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


def _repeat(row) -> rx.Component:
    """QUA-118 A2: weekly, same weekday and time, N times. Hidden on a reschedule."""
    return rx.cond(
        ~PlannerState.form_is_reschedule,
        rx.vstack(
            rx.hstack(
                rx.switch(
                    checked=row.repeat,
                    on_change=lambda v: PlannerState.set_item_repeat(row.post_id, v),
                    aria_label="Repetir cada semana",
                    size="1",
                ),
                rx.icon("repeat", size=14, color=T.TEXT_MUTED),
                rx.text("Repetir cada semana", size="2"),
                rx.cond(
                    row.repeat,
                    rx.hstack(
                        rx.input(
                            type="number",
                            min="1",
                            max="12",
                            value=row.repeat_count,
                            on_change=lambda v: PlannerState.set_item_repeat_count(row.post_id, v),
                            width="4.2rem",
                            size="1",
                            aria_label="Número de veces",
                        ),
                        rx.text("veces", size="2", color=T.TEXT_MUTED),
                        align="center",
                        spacing="1",
                    ),
                ),
                align="center",
                spacing="2",
                wrap="wrap",
            ),
            rx.cond(
                row.repeat & (row.series.error == ""),
                rx.flex(
                    rx.foreach(row.series.dates, lambda d: rx.box(d, class_name="q-date-chip")),
                    wrap="wrap",
                    gap="0.25rem",
                ),
            ),
            spacing="2",
            width="100%",
        ),
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
                    temperature_badge(row.temperature, row.temperature_label, row.temperature_hint),
                    spacing="1",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(row.title, size="2", weight="bold", style=_CLAMP_2),
                rx.text(row.media_label, size="1", color=T.TEXT_MUTED),
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
        ),
        rx.box(
            rx.box(
                _label("Fecha"),
                rx.input(
                    type="date",
                    value=row.date,
                    on_change=lambda v: PlannerState.set_item_date(row.post_id, v),
                    min=PlannerState.today_iso,
                    width="100%",
                ),
            ),
            rx.box(_label("Hora"), _time_picker(row)),
            class_name="q-plan-grid",
        ),
        rx.cond(
            row.has_outputs,
            rx.box(
                _label("Salida"),
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
        rx.box(
            _label("Canales"),
            rx.cond(
                PlannerState.connections.length() > 0,
                rx.flex(
                    rx.foreach(PlannerState.connections, lambda c: _account_chip(row, c)),
                    wrap="wrap",
                    gap="0.4rem",
                ),
                rx.text(
                    "No hay cuentas activas: conéctalas en Conexiones.",
                    size="1",
                    color=rx.color("amber", 11),
                ),
            ),
            width="100%",
        ),
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
        _repeat(row),
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
            rx.spacer(),
            rx.cond(
                PlannerState.form_count > 1,
                rx.button(
                    rx.icon("copy", size=12),
                    "Usar canales y etiquetas en todas",
                    size="1",
                    variant="ghost",
                    on_click=PlannerState.apply_to_all(row.post_id),
                ),
            ),
            align="center",
            width="100%",
            wrap="wrap",
            gap="0.5rem",
        ),
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
    return rx.vstack(
        rx.flex(
            _section_title(
                "calendar-clock",
                "Programación",
                rx.cond(
                    PlannerState.form_is_reschedule,
                    "Mueve la publicación a otra fecha, hora o cuenta.",
                    "Cuándo y dónde sale cada pieza.",
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
        _new_tag_box(),
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
                row.kind == "gallery",
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
                row.kind == "gallery",
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
        row.kind,
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
                rx.text(PlannerState.form_plan_summary, size="2"),
                rx.text(
                    "Zona horaria " + PlannerState.tz_name + " · Nada se publica antes de su hora.",
                    size="1",
                    opacity="0.8",
                ),
                spacing="1",
            ),
            class_name="q-hero",
        ),
        rx.box(rx.foreach(PlannerState.plan_rows_by_time, _timeline_item), class_name="q-tl"),
        rx.cond(~PlannerState.form_is_reschedule, _goals()),
        rx.cond(PlannerState.form_error != "", callout(PlannerState.form_error, "error")),
        spacing="5",
        width="100%",
    )


# ---------------------------------------------------------------------------
# The drawer


def _assign_footer() -> rx.Component:
    return rx.hstack(
        rx.button(
            "Cancelar",
            variant="ghost",
            color_scheme="gray",
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
                        color=rx.color("amber", 11),
                        style=_CLAMP_2,
                    ),
                ),
            ),
            flex="1",
            min_width="0",
            text_align="center",
        ),
        rx.cond(
            (PlannerState.form_step > STEP_POST)
            & ~(PlannerState.form_is_reschedule & (PlannerState.form_step == STEP_WHEN)),
            rx.button(
                rx.icon("chevron-left", size=T.ICON_SM),
                "Atrás",
                variant="soft",
                color_scheme="gray",
                on_click=PlannerState.prev_step,
            ),
        ),
        rx.cond(
            PlannerState.form_is_last_step,
            rx.button(
                rx.icon("calendar-check", size=T.ICON_SM),
                PlannerState.form_submit_label,
                loading=PlannerState.saving,
                on_click=PlannerState.submit_form,
                class_name="q-cta",
            ),
            rx.button(
                "Continuar",
                rx.icon("chevron-right", size=T.ICON_SM),
                disabled=~PlannerState.form_can_advance,
                title=PlannerState.form_step_error,
                on_click=PlannerState.next_step,
            ),
        ),
        align="center",
        spacing="2",
        width="100%",
    )


def assign_drawer() -> rx.Component:
    """«Nueva publicación» / «Reprogramar publicación» (QUA-118 v2): Contenido →
    Programación → Confirmar. A step must be valid to leave it; a completed step is one
    click away to fix; «Confirmar» is where the service's answer lands."""
    return drawer(
        rx.box(
            stepper(
                list(ASSIGN_STEPS),
                current=PlannerState.form_step,
                completed=PlannerState.form_steps_done,
                on_select=PlannerState.go_to_step,
                icons=list(ASSIGN_STEP_ICONS),
            ),
            class_name="q-stepper-wrap",
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
        description=rx.cond(
            PlannerState.form_is_reschedule,
            "Mueve la publicación a otra fecha, hora o cuenta.",
            "Arma tu día: elige las piezas, dales hora y canal, y confirma. Nada se publica "
            "hasta su hora.",
        ),
        footer=_assign_footer(),
        width="46rem",
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


def _fact(icon: str, label: str, value: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.center(rx.icon(icon, size=14), class_name="q-fact-glyph"),
        rx.text(label, size="1", color=T.TEXT_MUTED, min_width="5.5rem"),
        rx.box(value, flex="1", min_width="0"),
        align="center",
        spacing="2",
        width="100%",
    )


def _detail_body() -> rx.Component:
    d = PlannerState.detail
    p = PlannerState.detail_post
    kind = rx.cond(p.post_id != "", p.kind, "feed")
    kind_label = rx.cond(p.post_id != "", p.kind_label, d.category_label)
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
        media_fill(d.thumbnail_url, "", kind),
    )
    return rx.vstack(
        rx.box(
            rx.box(media, class_name="q-detail-media"),
            rx.vstack(
                rx.hstack(
                    kind_chip(kind, kind_label),
                    temperature_badge(p.temperature, p.temperature_label, p.temperature_hint),
                    wrap="wrap",
                    spacing="1",
                ),
                rx.text(d.title, size="4", weight="bold", line_height="1.25"),
                rx.flex(
                    pill(d.approval_label, d.approval_tone),
                    pill(d.status_label, d.status_tone),
                    wrap="wrap",
                    gap="0.25rem",
                ),
                rx.box(
                    rx.icon("calendar-clock", size=14),
                    rx.text(d.when_label, as_="span"),
                    class_name="q-when-pill q-when-pill--lg",
                ),
                rx.hstack(
                    platform_icon(d.platform),
                    platform_badge(d.platform),
                    rx.text(d.account_label, size="2", weight="medium"),
                    align="center",
                    spacing="2",
                ),
                spacing="2",
                min_width="0",
                flex="1",
            ),
            class_name="q-detail-hero",
        ),
        rx.box(
            rx.hstack(
                rx.icon("file-text", size=14),
                rx.text("El POST", size="2", weight="bold"),
                rx.spacer(),
                rx.cond(
                    d.detail_href != "",
                    rx.link(
                        rx.hstack(
                            rx.text("Abrir en Borradores", size="1"),
                            rx.icon("external-link", size=12),
                            align="center",
                            spacing="1",
                        ),
                        href=d.detail_href,
                    ),
                ),
                align="center",
                spacing="2",
                width="100%",
            ),
            rx.cond(
                d.caption_excerpt != "",
                rx.text(d.caption_excerpt, size="2", class_name="q-caption-quote"),
                rx.text("Sin texto.", size="2", color=T.TEXT_MUTED),
            ),
            class_name="q-soft-box q-soft-box--stack",
        ),
        rx.vstack(
            rx.cond(
                d.content_type_label != "",
                _fact("shapes", "Contenido", rx.text(d.content_type_label, size="2")),
            ),
            rx.cond(
                d.output_label != "",
                _fact("layers", "Salida", rx.text(d.output_label, size="2")),
            ),
            # `revision` is the event's reschedule counter (it keys the publish attempt,
            # so a moved event can never collide with the old one) — internal. Shown only
            # once it means something: how many times the publication was moved.
            rx.cond(
                d.revision > 1,
                _fact(
                    "history",
                    "Reprogramado",
                    rx.text(
                        rx.cond(d.revision == 2, "1 vez", (d.revision - 1).to_string() + " veces"),
                        size="2",
                    ),
                ),
            ),
            _fact(
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
            spacing="3",
            width="100%",
        ),
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
                    + " El evento sigue programado y se publica en el siguiente minuto en que "
                    "esté listo.",
                    "warn",
                ),
            ),
        ),
        rx.match(
            PlannerState.auto_publish,
            (
                AUTO_PUBLISH_ACTIVE,
                rx.hstack(
                    rx.box(class_name="q-live-dot"),
                    rx.text(
                        "Publicación automática activa: un evento aprobado sale a su hora "
                        "(se revisa cada minuto).",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    align="center",
                    spacing="2",
                ),
            ),
            (
                AUTO_PUBLISH_NO_CONNECTION,
                callout(
                    "No hay una cuenta conectada y activa para publicar. Conéctala en "
                    "Conexiones: los eventos se publicarán en cuanto lo esté.",
                    "warn",
                ),
            ),
            callout(
                "El servicio de publicación automática no está disponible en este "
                "momento: los eventos no se publicarán a su hora.",
                "warn",
            ),
        ),
        spacing="4",
        width="100%",
    )


def _confirm_bar(text: str, action_label: str, on_confirm) -> rx.Component:
    return rx.hstack(
        rx.icon("triangle-alert", size=16, color=rx.color("red", 11), flex_shrink="0"),
        rx.text(text, size="2", flex="1", min_width="0"),
        rx.button(
            "Volver", variant="soft", color_scheme="gray", on_click=PlannerState.dismiss_confirm
        ),
        rx.button(action_label, color_scheme="red", on_click=on_confirm),
        align="center",
        spacing="2",
        width="100%",
        class_name="q-confirm-bar",
    )


def _detail_footer() -> rx.Component:
    d = PlannerState.detail
    actions = rx.hstack(
        rx.cond(
            d.can_remove_rejected,
            rx.button(
                rx.icon("trash-2", size=T.ICON_SM),
                "Quitar del calendario",
                variant="soft",
                color_scheme="red",
                on_click=PlannerState.ask_remove_rejected,
            ),
        ),
        # A POST still in review can be rejected from here (the creative FSM decides).
        rx.cond(
            d.can_reject_post,
            rx.button(
                rx.icon("thumbs-down", size=T.ICON_SM),
                "Rechazar POST",
                variant="soft",
                color_scheme="red",
                on_click=PlannerState.reject_post_from_detail,
            ),
        ),
        rx.spacer(),
        rx.cond(
            d.can_modify,
            rx.hstack(
                rx.button(
                    "Cancelar publicación",
                    variant="soft",
                    color_scheme="red",
                    on_click=PlannerState.ask_cancel_from_detail,
                ),
                rx.button(
                    rx.icon("calendar-clock", size=T.ICON_SM),
                    "Reprogramar",
                    on_click=PlannerState.reschedule_from_detail,
                ),
                spacing="2",
            ),
        ),
        width="100%",
        align="center",
        wrap="wrap",
        gap="2",
    )
    return rx.match(
        PlannerState.detail_confirm,
        (
            CONFIRM_CANCEL,
            _confirm_bar(
                "¿Cancelar esta publicación? Sale del calendario y el POST vuelve a «Sin "
                "programar»; su contenido no cambia.",
                "Sí, cancelar",
                PlannerState.confirm_cancel,
            ),
        ),
        (
            CONFIRM_REMOVE,
            _confirm_bar(
                "¿Quitar el POST rechazado del calendario? Se cancelan sus publicaciones "
                "pendientes; lo ya publicado se conserva.",
                "Sí, quitar",
                PlannerState.confirm_remove_rejected,
            ),
        ),
        actions,
    )


def event_panel() -> rx.Component:
    """The planned publication, in a side panel like «Nueva publicación» (never a
    modal): the POST itself — media, text, format, Cold/Hot — when and where it goes
    out, its tags, and what can be done with it. Confirmations happen in the footer."""
    return drawer(
        rx.cond(
            PlannerState.detail_loading,
            rx.center(rx.spinner(), padding="3rem"),
            rx.cond(
                PlannerState.detail_error != "",
                callout(PlannerState.detail_error, "error"),
                _detail_body(),
            ),
        ),
        open=PlannerState.detail_open,
        on_open_change=PlannerState.set_detail_open,
        title="Publicación planificada",
        description="Qué sale, cuándo y dónde. Desde aquí la mueves o la cancelas.",
        footer=_detail_footer(),
        width="36rem",
    )
