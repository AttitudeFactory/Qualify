"""The content generator (§ request 2026-09-25), the whole of /create since 2026-09-30.

Since 2026-10-08 it is ONE view with numbered sections (it was a step-by-step wizard);
since 2026-10-14 it has two columns (§ request: "un panel lateral con las opciones"):

1. **¿Qué creamos?** in a side panel on the left — the content kind, which decides the
   rest; Video opens its types under it. The centre heads with what was chosen.
2. **Its sections**, in the centre, numbered, only the ones the kind uses
   (`creative_state.generator_sections`): ¿Qué quieres…? → ¿Dónde se publica? →
   ¿Quién lo presenta? (avatar kinds only) → the kind's own inputs. «Reglas» is a folded,
   optional extra, and Generar closes the form.
3. **Tu pieza** appears below, on the same page, filled in as the draft lands
   (`poll_generator`): the script for a real creator; the video for both avatar kinds;
   the image or the carousel's slides; a template's outputs.

Same `CreativeState` and the same service underneath: every piece is also a draft at
/drafts/{id}, where it is edited and approved."""

from __future__ import annotations

import reflex as rx

from .ask_more_ui import ask_more_block
from .campaign_provider import COLOR_LABELS, NEW_CAMPAIGN, NO_CAMPAIGN
from .catalog_vm import ADD_PRODUCT_LABEL, CREATE_RETURN_PATH, new_product_href
from .creative_state import (
    _INSPIRATION_TARGETS,
    _NO_CATALOG_TARGETS,
    DURATIONS,
    SLIDE_SECONDS,
    STOCK_MAX_PICKS,
    CreativeState,
)
from .creative_vm import (
    CATEGORY_OPTIONS,
    PHRASE_LIMIT,
    PHRASE_LIMIT_HINT,
    VIDEO_TYPE_OPTIONS,
    WAITING_VENDOR_TEXT,
)
from .creative_wizard_pages import (  # the Brand Kit's own chrome, shared
    _CONTROL_RADIUS,
    _asset_script,
    _loading_view,
    _script_on_mount,
)
from .discover_reels import discover_view
from .download_buttons import piece_download_button
from .media_carousel import media_carousel
from .post_card import color_swatches
from .r2_media import BACKEND_BASE
from .ui import (
    app_shell,
    callout,
    card,
    choice_card,
    choice_card_check,
    dropzone,
    empty_state,
    loading_spinner,
    media_thumb,
    page_header,
    progress_panel,
    removable_pill,
    skeleton_card,
    skeleton_rows,
    tag,
)
from .ui import tokens as T
from .ui.steps import step_foot, step_frame, step_head, step_sync
from .variations_state import VariationsState
from .variations_view import variations_view


def _card(
    *children: rx.Component,
    title: str | rx.Var | None = None,
    icon: str | None = None,
    actions: tuple[rx.Component, ...] = (),
    **props,
) -> rx.Component:
    """A generator block: design-system `card` with, optionally, its entity title
    (heading 4 — §3.2) and the block's own controls on the right."""
    header: list[rx.Component] = []
    if title is not None:
        header.append(
            rx.hstack(
                rx.icon(icon, size=T.ICON_MD, color=T.TEXT_MUTED) if icon else rx.fragment(),
                rx.heading(title, size="4", as_="h3"),
                rx.spacer(),
                *actions,
                spacing="2",
                width="100%",
                align="center",
            )
        )
    return card(
        rx.vstack(*header, *children, spacing="3", align_items="start", width="100%"),
        padding="1.25rem 1.5rem",
        **props,
    )


def _field_label(text: str | rx.Var, hint: str | None = None) -> rx.Component:
    """§5.6: visible label above, help below in size 1 muted."""
    return rx.vstack(
        rx.text(text, size="2", weight="medium"),
        rx.text(hint, size="1", color=T.TEXT_MUTED) if hint else rx.fragment(),
        spacing="0",
        align_items="start",
    )


_IMAGE_ACCEPT = {"image/*": [".png", ".jpg", ".jpeg", ".webp"]}


def _help(title: str, text: str) -> rx.Component:
    """A small «?» that explains an option (§ request 2026-10-09: "un pequeño icono de
    ayuda"). A click or a tap opens it — a hover-only tooltip never opens on a phone —
    and the click stops there, so the help inside a clickable card never picks it."""
    return rx.popover.root(
        rx.popover.trigger(
            rx.icon_button(
                rx.icon("circle-help", size=14),
                variant="ghost",
                color_scheme="gray",
                size="1",
                radius="full",
                aria_label=f"Qué es «{title}»",
                title=f"Qué es «{title}»",
                on_click=rx.stop_propagation,
                flex_shrink="0",
            )
        ),
        rx.popover.content(
            rx.vstack(
                rx.text(title, size="2", weight="bold"),
                rx.text(text, size="1", color=T.TEXT_MUTED),
                spacing="1",
                max_width="18rem",
            ),
            side="bottom",
            align="start",
        ),
    )


def _label_with_help(label: str, title: str, text: str, **props: object) -> rx.Component:
    """A field's label and its «?»."""
    return rx.hstack(
        rx.text(label, **props),
        _help(title, text),
        spacing="1",
        align="center",
    )


def _choice_card(
    title: str,
    blurb: str,
    icon: str,
    *,
    selected: rx.Var[bool],
    on_click: rx.event.EventSpec,
    compact: bool = False,
    help_text: str = "",
) -> rx.Component:
    """One radio tile of «¿Qué quieres crear?»: a category, or a type within Video —
    or a kind of carousel slide, with its «?» (`help_text`). The tile is a `choice_card`
    (a real ``<button>``); the «?» is a button too, so it sits beside the tile, never
    inside it — nested buttons are not HTML."""
    tile = choice_card(
        rx.hstack(
            rx.icon(
                icon,
                size=T.ICON_MD,
                color=rx.cond(selected, T.tone_color("accent", 11), T.TEXT_FAINT),
                flex_shrink="0",
            ),
            rx.vstack(
                rx.text(title, size="2", weight="medium"),
                rx.text(blurb, size="1", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
                flex="1",
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        selected=selected,
        on_select=on_click,
        padding="0.65rem 0.85rem" if compact else "0.95rem 1rem",
        width="100%",
        height="100%",
    )
    if not help_text:
        return tile
    return rx.hstack(
        tile,
        _help(title, help_text),
        spacing="1",
        align="start",
        width="100%",
        height="100%",
    )


def _option(
    title: str,
    blurb: str,
    icon: str,
    *,
    selected: rx.Var[bool],
    on_click: rx.event.EventSpec,
    help_text: str = "",
) -> rx.Component:
    """One entry of the side panel: a compact `choice_card` (a real ``<button>``,
    ``role="radio"``) with its icon, its title and — CREAR-6 (m-24842980) — its blurb,
    visible on a phone where the panel is one column (`.q-cr-option-blurb`). On a wide
    screen the panel stays compact: the blurb is the centre's heading once chosen, and
    the longer explanation of an option that needs one is a «?» opened by a click or a
    tap (`_help`), never a hover-only tooltip (N12)."""
    entry = choice_card(
        rx.hstack(
            rx.icon(
                icon,
                size=T.ICON_MD,
                color=rx.cond(selected, T.tone_color("accent", 11), T.TEXT_FAINT),
                flex_shrink="0",
            ),
            rx.vstack(
                rx.text(title, size="2", weight="medium"),
                rx.text(blurb, size="1", color=T.TEXT_MUTED, class_name="q-cr-option-blurb"),
                spacing="1",
                align_items="start",
                flex="1",
                min_width="0",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        selected=selected,
        on_select=on_click,
        padding="0.6rem 0.8rem",
        width="100%",
        min_height="2.75rem",
    )
    if not help_text:
        return entry
    return rx.hstack(
        entry,
        rx.box(_help(title, help_text), class_name="q-cr-option-help"),
        spacing="1",
        align="center",
        width="100%",
    )


#: The longer explanation of an option, behind its «?» on a wide screen (§ request
#: 2026-10-14: «Generar guion» goes to a UGC creator; m-24842979: said without the word
#: «UGC»).
#: Where «Completar mi marca» goes: the kit inside the session (m-24842979 — `/brand`
#: is the onboarding flow and redirects once inside).
BRAND_KIT_ROUTE = "/brand/kit"

_OPTION_HELP = {
    "script": (
        "Este guion lo graba una persona real —un cliente, alguien de tu equipo o un "
        "creador— con su celular y en tono natural, como si recomendara tu marca. Funciona "
        "porque se siente auténtico, no como un anuncio."
    ),
}
#: m-24803289 — what «Variaciones» is, behind its «?».
_VARIATIONS_HELP = (
    "Parte de un producto de tu catálogo y propone diez ángulos visuales distintos para "
    "anunciarlo: otro escenario, otra composición y otro enfoque en cada uno. Tú eliges "
    "cuáles se convierten en publicaciones."
)


def _create_options(creating: rx.Var[bool]) -> list[rx.Component]:
    """What can be created, in the panel's order (`CATEGORY_OPTIONS`)."""
    options: list[rx.Component] = []
    for key, title, blurb, icon in CATEGORY_OPTIONS:
        options.append(
            _option(
                title,
                blurb,
                icon,
                selected=creating & (CreativeState.gen_category == key),
                on_click=CreativeState.choose_category(key),
                help_text=_OPTION_HELP.get(key, ""),
            )
        )
    return options


def _kind_picker() -> rx.Component:
    """The side panel's list (§ request 2026-10-14): what can be created — Guion · Clip ·
    Galería · Flyer · Plantilla · Ad — and, below them, «Descubrir ideas de videos»
    (ex «Descubrir reels», CREAR-6: no English word). Clip's types are its first view,
    in the centre, not a sub-list here. On a phone it is one column, every option with
    its blurb (CREAR-6, `.q-cr-option-blurb`)."""
    creating = CreativeState.gen_mode == "create"
    return rx.vstack(
        rx.vstack(
            *_create_options(creating),
            spacing="2",
            width="100%",
            role="radiogroup",
            aria_label="Tipo de contenido",
            class_name="q-cr-options-list",
        ),
        rx.divider(class_name="q-cr-options-rule"),
        # m-24803289: ten visual angles of one catalog product. Not a kind of piece —
        # it MAKES pieces of a kind — so it sits below the rule, next to «Descubrir
        # reels», and opens its own view with its own state.
        _option(
            _VARIATIONS_HEADING[0],
            _VARIATIONS_HEADING[1],
            _VARIATIONS_HEADING[2],
            selected=CreativeState.gen_mode == "variations",
            on_click=[CreativeState.open_variations, VariationsState.load],
            help_text=_VARIATIONS_HELP,
        ),
        _option(
            *_DISCOVER_HEADING,
            selected=CreativeState.gen_mode == "discover",
            on_click=CreativeState.open_discover,
        ),
        spacing="2",
        width="100%",
        class_name="q-cr-options-list",
    )


def _options_panel() -> rx.Component:
    """The side panel, the full height of the screen beside the views (§ request
    2026-10-14); on a phone, on top of them (`.q-cr-options`). Inert while a piece
    generates."""
    return rx.box(
        card(
            rx.vstack(
                rx.hstack(
                    rx.text(
                        rx.match(
                            CreativeState.gen_mode,
                            ("variations", _VARIATIONS_HEADING[0]),
                            ("discover", _DISCOVER_HEADING[0]),
                            rx.match(
                                CreativeState.gen_category,
                                *[(key, title) for key, title, _, _ in CATEGORY_OPTIONS],
                                "Crear publicación",
                            ),
                        ),
                        size="2",
                        weight="medium",
                        flex="1",
                        min_width="0",
                    ),
                    rx.button(
                        rx.cond(CreativeState.create_options_open, "Cerrar opciones", "Cambiar"),
                        on_click=CreativeState.toggle_create_options,
                        variant="ghost",
                        color_scheme="gray",
                        size="2",
                        min_height="44px",
                        aria_expanded=CreativeState.create_options_open,
                        aria_controls="create-kind-options",
                        disabled=CreativeState.gen_generating,
                    ),
                    width="100%",
                    align="center",
                    spacing="2",
                    display=rx.breakpoints({"0px": "flex", "900px": "none"}),
                ),
                rx.vstack(
                    rx.heading("¿Qué creamos?", size="4", as_="h2"),
                    rx.text("Elige qué hacer.", size="1", color=T.TEXT_MUTED),
                    # CREAR-5: the month's creations, never money («Te quedan 18 de 30»)
                    rx.cond(
                        CreativeState.creations_left_text != "",
                        rx.hstack(
                            rx.icon("sparkles", size=T.ICON_SM, color=T.TEXT_MUTED),
                            rx.text(CreativeState.creations_left_text, size="1", weight="medium"),
                            spacing="1",
                            align="center",
                            margin_top="0.35rem",
                        ),
                    ),
                    spacing="0",
                    align_items="start",
                    display=rx.breakpoints({"0px": "none", "900px": "flex"}),
                ),
                rx.box(
                    _kind_picker(),
                    id="create-kind-options",
                    width="100%",
                    display=rx.breakpoints(
                        {
                            "0px": rx.cond(CreativeState.create_options_open, "block", "none"),
                            "900px": "block",
                        }
                    ),
                ),
                _product_chip(),
                spacing="3",
                width="100%",
                align_items="start",
                class_name="q-cr-options-inner",
            ),
            padding="1rem",
            width="100%",
            height="100%",
        ),
        class_name=rx.cond(
            CreativeState.gen_generating,
            "q-cr-options q-cr-form q-cr-form--busy",
            "q-cr-options q-cr-form",
        ),
        aria_disabled=rx.cond(CreativeState.gen_generating, "true", "false"),
    )


_CATEGORY_BY_KEY = {key: (title, blurb, icon) for key, title, blurb, icon in CATEGORY_OPTIONS}
_VIDEO_TYPE_BY_KEY = {key: (title, blurb, icon) for key, title, blurb, icon in VIDEO_TYPE_OPTIONS}
_DISCOVER_HEADING = (
    "Descubrir ideas de videos",
    # what the filter keeps (`referentes/reels_ai.py`, FITS = producto | categoria)
    "Los videos con más vistas de las cuentas que tomas de referencia, solo de tu producto "
    "o su categoría, para inspirarte o hacer uno parecido.",
    "compass",
)
_VARIATIONS_HEADING = (
    "Variaciones",
    "Diez ángulos visuales distintos de un producto de tu catálogo: otro escenario, otra "
    "composición, otro enfoque en cada uno.",
    "layers",
)


def _kind_header_row(title: str, blurb: str, icon: str) -> rx.Component:
    return rx.hstack(
        rx.center(
            rx.icon(icon, size=T.ICON_MD, color=T.tone_color("accent", 11)),
            width="2.5rem",
            height="2.5rem",
            flex_shrink="0",
            border_radius=T.RADIUS_CONTROL,
            background=T.tone_color("accent", 3),
        ),
        rx.vstack(
            rx.heading(title, size="5", as_="h2"),
            rx.text(blurb, size="2", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
        ),
        spacing="3",
        align="center",
        width="100%",
    )


def _kind_header() -> rx.Component:
    """The centre's top: what was chosen in the side panel and what it makes — for
    Avatar, the chosen type once past its first view."""
    clip = rx.cond(
        CreativeState.gen_view == "avatar_type",
        _kind_header_row(*_CATEGORY_BY_KEY["video"]),
        rx.match(
            CreativeState.video_type,
            *(
                (key, _kind_header_row(title, blurb, icon))
                for key, (title, blurb, icon) in _VIDEO_TYPE_BY_KEY.items()
            ),
            _kind_header_row(*_CATEGORY_BY_KEY["video"]),
        ),
    )
    created = rx.match(
        CreativeState.gen_category,
        *(
            (key, _kind_header_row(title, blurb, icon))
            for key, (title, blurb, icon) in _CATEGORY_BY_KEY.items()
            if key != "video"
        ),
        ("video", clip),
        _kind_header_row(*_CATEGORY_BY_KEY["script"]),
    )
    return rx.match(
        CreativeState.gen_mode,
        ("discover", _kind_header_row(*_DISCOVER_HEADING)),
        ("variations", _kind_header_row(*_VARIATIONS_HEADING)),
        created,
    )


def _avatar_type_card(key: str, title: str, blurb: str, icon: str) -> rx.Component:
    """One clip type (§ request 2026-10-14): a skeleton box holding only the avatar —
    the ghost of who appears, no text-like bars — and, under it, the type's name and
    what it makes."""
    selected = CreativeState.video_type == key
    return choice_card(
        rx.vstack(
            rx.box(
                rx.box(rx.icon(icon, size=30), class_name="q-cr-ghost-head"),
                rx.cond(
                    selected,
                    rx.box(choice_card_check(), class_name="q-cr-ghost-check"),
                ),
                class_name="q-cr-ghost",
                aria_hidden="true",
            ),
            rx.vstack(
                rx.text(title, size="3", weight="bold"),
                rx.text(blurb, size="2", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
            spacing="3",
            width="100%",
        ),
        selected=selected,
        on_select=CreativeState.choose_video_type(key),
        padding="0.75rem",
        width="100%",
        height="100%",
    )


_VIDEO_ACCEPT = {"video/*": [".mp4", ".mov", ".webm", ".m4v"]}
_REFERENCE_MAX_BYTES = 200 * 1024 * 1024


_REFERENCE_HINT = (
    "Un clip que te guste: su ritmo, encuadre y estructura son la referencia para hacer tu video."
)


def _reference_view() -> rx.Component:
    """«Ad»'s «Referencia» (§ request 2026-10-14): a video to make the piece from —
    optional; from the catalog, uploaded or one of the pieces. An avatar asks it in
    «Guion y fondo» since 2026-10-20 (`_reference_body`)."""
    return rx.vstack(
        rx.vstack(
            rx.heading("Video de referencia (opcional)", size="4", as_="h3"),
            rx.text(_REFERENCE_HINT, size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
        ),
        _reference_body(),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _reference_body() -> rx.Component:
    """The reference video held, and its picker."""
    key = CreativeState.reference_video_key
    return rx.vstack(
        rx.cond(
            key != "",
            rx.vstack(
                rx.cond(
                    CreativeState.piece_views.contains(key),
                    _clip_thumb(key, size="9rem"),
                    rx.el.video(
                        src=rx.get_upload_url(key),
                        controls=True,
                        muted=True,
                        plays_inline=True,
                        preload="metadata",
                        class_name="q-cr-output q-cr-reference",
                    ),
                ),
                rx.hstack(
                    rx.icon("film", size=T.ICON_SM, color=T.TEXT_MUTED),
                    rx.text(
                        CreativeState.reference_video_name,
                        size="2",
                        weight="medium",
                        overflow="hidden",
                        text_overflow="ellipsis",
                        white_space="nowrap",
                    ),
                    rx.spacer(),
                    rx.button(
                        rx.icon("x", size=12),
                        "Quitar",
                        variant="ghost",
                        color_scheme="gray",
                        size="1",
                        on_click=CreativeState.clear_reference_video,
                    ),
                    width="100%",
                    align="center",
                    spacing="2",
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        _media_picker(
            "reference",
            dropzone(
                rx.vstack(
                    rx.icon("clapperboard", size=T.ICON_LG, color=T.TEXT_FAINT),
                    rx.text("Arrastra tu clip o elígelo", size="2", weight="medium"),
                    rx.text("MP4, MOV o WEBM · hasta 200 MB", size="1", color=T.TEXT_MUTED),
                    align="center",
                    spacing="1",
                ),
                upload_id="reference_video",
                accept=_VIDEO_ACCEPT,
                max_files=1,
                max_size=_REFERENCE_MAX_BYTES,
                on_drop=CreativeState.handle_reference_upload(
                    rx.upload_files(upload_id="reference_video")
                ),
                width="100%",
            ),
            media_type="video",
        ),
        _upload_error(),
        spacing="4",
        width="100%",
        align_items="start",
    )


# -- the media picker (§ request 2026-10-14) ----------------------------------------------
# «en todas partes se pueda ver y seleccionar lo que venga del catálogo, importarlo a mano
# y/o desde las piezas ya creadas»: every slot that takes a file has the same three tabs.


def _key_has(key: rx.Var[str]) -> rx.Var[bool]:
    """Whether `key` has a picture to show: a piece only when it got a thumbnail."""
    return rx.cond(
        CreativeState.piece_views.contains(key),
        CreativeState.piece_views[key].to(str) != "",
        key != "",
    )


def _key_src(key: rx.Var[str]) -> rx.Var[str]:
    """Where a slot's file is shown from: a piece through `/r2media` (it lives in R2),
    anything else — an upload, the catalog — from the upload store."""
    return rx.cond(
        CreativeState.piece_views.contains(key),
        BACKEND_BASE + CreativeState.piece_views[key].to(str),
        rx.get_upload_url(key),
    )


def _picker_tile(
    src: rx.Var[str],
    has: rx.Var[bool],
    selected: rx.Var[bool],
    on_select: object,
    icon: str,
    label: rx.Var[str] | str,
    *,
    video: bool = False,
) -> rx.Component:
    """One file of a slot's gallery; a video file shows its first frame as the preview
    (§ request 2026-10-15) instead of a film glyph."""
    return choice_card(
        rx.box(
            _video_thumb(src) if video else media_thumb(src, size="4.5rem", icon=icon, has=has),
            rx.cond(selected, rx.box(choice_card_check(), class_name="q-cr-ghost-check")),
            position="relative",
        ),
        selected=selected,
        role="checkbox",
        on_select=on_select,
        padding="0.3rem",
        width="auto",
        aria_label=label,
        title=label,
    )


def _play_button(on_click: object, top: str, *, small: bool = False) -> rx.Component:
    """The round play over a video's poster, as in «Descubrir reels» (§ requests
    2026-10-19): centred on the poster (`top` is its middle). A sibling of the tile's
    button — a button inside a button is not valid HTML."""
    return rx.el.button(
        rx.icon("play", size=14 if small else 22),
        type="button",
        on_click=on_click,
        aria_label="Ver el video aquí",
        title="Ver el video aquí",
        class_name="q-cr-stock-playbtn q-cr-stock-playbtn--sm" if small else "q-cr-stock-playbtn",
        top=top,
    )


def _pause_button(*, small: bool = False) -> rx.Component:
    """The round pause over a playing video, shown on hover (§ request 2026-10-19: no
    ✕ — «cuando se haga hover se ponga el iconito de pausar»): it stops the video and
    the poster comes back. On a touch screen it stays visible."""
    return rx.el.button(
        rx.icon("pause", size=14 if small else 22),
        type="button",
        on_click=CreativeState.stop_stock_video.stop_propagation,
        aria_label="Pausar el video",
        title="Pausar el video",
        class_name="q-cr-stock-playbtn q-cr-stock-playbtn--sm" if small else "q-cr-stock-playbtn",
        top="50%",
    )


def _pick_hit(on_select: object, selected: rx.Var[bool], label: rx.Var[str] | str) -> rx.Component:
    """The playing video's own pick: a real button over the whole frame, under the pause
    and the sound, so the keyboard can still pick a video while it plays (review
    2026-10-19 — a clickable box is not focusable)."""
    return rx.el.button(
        type="button",
        on_click=on_select,
        role="checkbox",
        aria_checked=rx.cond(selected, "true", "false"),
        aria_label=label,
        title=label,
        class_name="q-cr-pick-hit",
    )


def _sound_button(*, small: bool = False) -> rx.Component:
    """Sound on or off for a previewed stock video, on hover like the pause (§ request
    2026-10-19, «audio solo en la vista previa»): the bank's rendition is heard while
    choosing; the piece never takes a stock file's audio (the import drops it)."""
    return rx.el.button(
        rx.cond(
            CreativeState.preview_sound,
            rx.icon("volume-2", size=12 if small else 14),
            rx.icon("volume-x", size=12 if small else 14),
        ),
        type="button",
        on_click=CreativeState.toggle_preview_sound.stop_propagation,
        aria_label=rx.cond(CreativeState.preview_sound, "Quitar el sonido", "Poner el sonido"),
        title=rx.cond(CreativeState.preview_sound, "Quitar el sonido", "Poner el sonido"),
        class_name="q-cr-soundbtn q-cr-soundbtn--sm" if small else "q-cr-soundbtn",
    )


def _picker_video_tile(
    key: rx.Var[str],
    poster: rx.Var[str] | None,
    src: rx.Var[str],
    selected: rx.Var[bool],
    on_select: object,
    label: rx.Var[str] | str,
    *,
    on_play: object = None,
    sound: bool = False,
    busy: rx.Var[bool] | None = None,
) -> rx.Component:
    """A video in a slot's picker: its poster (`poster` — a stock video's, or a bank's
    thumbnail) or its first frame, with the round play in the centre. Play shows it
    moving in the SAME frame — the picker never grows or shifts (§ request 2026-10-19);
    a click on it picks it, the pause shown on hover stops it. `sound`: a bank's preview,
    which may be heard (an imported file has no audio)."""
    thumb = (
        media_thumb(
            poster,
            size="4.5rem",
            icon="film",
            has=poster != "",
            custom_attrs={"referrerpolicy": "no-referrer"},
        )
        if poster is not None
        else _video_thumb(src, mark=False)
    )
    tile = choice_card(
        rx.box(
            thumb,
            rx.cond(selected, rx.box(choice_card_check(), class_name="q-cr-ghost-check")),
            *(
                [rx.cond(busy, rx.center(loading_spinner("sm"), class_name="q-cr-stock-busy"))]
                if busy is not None
                else []
            ),
            position="relative",
        ),
        selected=selected,
        role="checkbox",
        on_select=on_select,
        padding="0.3rem",
        width="auto",
        aria_label=label,
        title=label,
    )
    player = rx.box(
        rx.el.video(
            src=src,
            auto_play=True,
            muted=~CreativeState.preview_sound if sound else True,
            loop=True,
            plays_inline=True,
            preload="auto",
            custom_attrs={"referrerPolicy": "no-referrer"},
            class_name="q-cr-pick-video",
        ),
        _pick_hit(on_select, selected, label),
        rx.cond(selected, rx.box(choice_card_check(), class_name="q-cr-ghost-check")),
        _pause_button(small=True),
        *([_sound_button(small=True)] if sound else []),
        class_name=rx.cond(selected, "q-cr-pick-player q-cr-pick-player--on", "q-cr-pick-player"),
    )
    return rx.box(
        rx.cond(
            # `on_play` is a bank hit's own play; without it the tile is a slot's file
            (CreativeState.hit_playing if on_play is not None else CreativeState.file_playing)
            == key,
            player,
            rx.fragment(
                tile,
                _play_button(
                    on_play if on_play is not None else CreativeState.play_media(key),
                    "calc(0.3rem + 2.25rem)",
                    small=True,
                ),
            ),
        ),
        position="relative",
        flex_shrink="0",
        class_name="q-cr-play-host",
    )


def _product_video_src(key: rx.Var[str]) -> rx.Var[str]:
    """Where a product video plays from: a stock one's mp4 through `/r2media`, a catalog
    one from the upload store."""
    return rx.cond(
        CreativeState.stock_video_views.contains(key),
        BACKEND_BASE + CreativeState.stock_video_views[key].to(str),
        rx.get_upload_url(key),
    )


def _catalog_picker_tile(
    key: rx.Var[str], selected: rx.Var[bool], on_select: object, image: bool
) -> rx.Component:
    """A file of the chosen product in a slot's «Catálogo» / «Inspiración» tab. A stock
    product's files live in R2 (`piece_views` maps them, a video to its POSTER), a
    catalog product's in the upload store."""
    label = rx.cond(CreativeState.product_source == "stock", "Inspiración", "Del catálogo")
    if image:
        return _picker_tile(_key_src(key), _key_has(key), selected, on_select, "image", label)
    src = _product_video_src(key)
    return rx.cond(
        CreativeState.piece_views.contains(key),
        _picker_video_tile(key, _key_src(key), src, selected, on_select, label),
        _picker_video_tile(key, None, src, selected, on_select, label),
    )


def _picker_note(text: rx.Var[str] | str) -> rx.Component:
    return rx.text(text, size="1", color=T.TEXT_MUTED)


def _inspiration_hit_tile(tile: rx.Var[dict[str, str]], target: str, image: bool) -> rx.Component:
    """One hit of a slot's inspiration search: a click imports it and puts it in the
    slot (the tile shows the wait); a video plays in its frame first, with its sound."""
    busy = CreativeState.inspiration_importing == tile["id"]
    media = "image" if image else "video"
    on_select = CreativeState.use_inspiration_hit(target, tile["id"], media)
    if image:
        return choice_card(
            rx.box(
                media_thumb(
                    tile["thumb"],
                    size="4.5rem",
                    alt=tile["author"],
                    custom_attrs={"referrerpolicy": "no-referrer"},
                ),
                rx.cond(busy, rx.center(loading_spinner("sm"), class_name="q-cr-stock-busy")),
                position="relative",
            ),
            selected=busy,
            role="button",
            on_select=on_select,
            disabled=CreativeState.inspiration_importing != "",
            padding="0.3rem",
            width="auto",
            aria_label="Usar " + tile["author"],
            title=tile["author"],
        )
    return _picker_video_tile(
        tile["id"],
        tile["thumb"],
        tile["preview"],
        busy,
        on_select,
        tile["author"],
        on_play=CreativeState.play_stock_video(tile["id"]),
        sound=True,
        busy=busy,
    )


def _inspiration_search(target: str, image: bool | None) -> rx.Component:
    """«Inspiración» inside a slot's picker: the Brand Kit's words searched straight
    away, or the operator's own; a click on a hit brings it into the slot. Once the slot
    holds something from inspiration the search folds away — no second discovery, and no
    preview of what was picked: the slot above already shows it — until «Buscar otra»
    (§ request 2026-10-19). The background keeps its search open. `image=None`: a mixed
    slot, its images and its videos under one search box (§ request 2026-10-20)."""
    search = _inspiration_search_body(target, image)
    if target == "background":
        return search
    folded = rx.hstack(
        rx.icon("check", size=T.ICON_SM, color=T.tone_color("accent", 11)),
        rx.text("Ya tomaste inspiración para este espacio.", size="1", color=T.TEXT_MUTED),
        rx.button(
            rx.icon("search", size=12),
            "Buscar otra",
            variant="ghost",
            size="1",
            on_click=CreativeState.reopen_inspiration(target),
        ),
        spacing="2",
        align="center",
        wrap="wrap",
    )
    return rx.cond(
        CreativeState.inspiration_held.contains(target)
        & ~CreativeState.inspiration_reopened.contains(target),
        folded,
        search,
    )


def _inspiration_hits(target: str, image: bool, *, titled: bool = False) -> rx.Component:
    """One bank's hits in a slot's inspiration search; `titled` (a mixed slot) names the
    grid, since images and videos sit one above the other."""
    hits = CreativeState.stock_results if image else CreativeState.vstock_results
    loading = CreativeState.stock_loading if image else CreativeState.vstock_loading
    noun = "imágenes" if image else "videos"
    grid = rx.cond(
        loading & (hits.length() == 0),
        _picker_note(f"Buscando {noun}…"),
        rx.cond(
            hits.length() > 0,
            rx.flex(
                rx.foreach(hits, lambda tile: _inspiration_hit_tile(tile, target, image)),
                wrap="wrap",
                spacing="2",
                max_height="18rem",
                overflow_y="auto",
                width="100%",
            ),
            _picker_note(
                f"Aún no hay {noun}: busca arriba o deja la caja vacía para usar tu marca."
                if titled
                else f"Escribe qué buscas o deja la caja vacía para usar tu marca. "
                f"Solo {noun} sin personas."
            ),
        ),
    )
    if not titled:
        return grid
    return rx.vstack(
        rx.text(noun.capitalize(), size="1", weight="medium", color=T.TEXT_MUTED),
        grid,
        spacing="1",
        width="100%",
        align_items="start",
    )


def _inspiration_search_body(target: str, image: bool | None) -> rx.Component:
    grids = (
        [
            _inspiration_hits(target, True, titled=True),
            _inspiration_hits(target, False, titled=True),
        ]
        if image is None
        else [_inspiration_hits(target, image)]
    )
    return rx.vstack(
        rx.hstack(
            rx.input(
                rx.input.slot(rx.icon("search", size=T.ICON_SM)),
                value=CreativeState.stock_query,
                on_change=CreativeState.set_stock_query,
                on_key_down=CreativeState.stock_search_on_enter,
                placeholder="Busca inspiración: hamburguesa, cocina, ciudad de noche…",
                max_length=100,
                size="2",
                flex="1",
                aria_label="Buscar inspiración",
            ),
            rx.button(
                "Buscar",
                size="2",
                loading=CreativeState.stock_any_loading,
                disabled=~CreativeState.stock_on,
                on_click=CreativeState.search_stock_products,
            ),
            width="100%",
            spacing="2",
        ),
        rx.cond(
            CreativeState.stock_error != "",
            callout(CreativeState.stock_error, "warn"),
        ),
        *grids,
        spacing="2",
        width="100%",
        align_items="start",
    )


def _picker_tabs(target: str, tab: rx.Var[str]) -> rx.Component:
    """The slot's sources. With a stock product, «Catálogo» becomes «Inspiración» (the
    stock picked) and a «Catálogo» beside it brings the brand's catalog (§ request
    2026-10-19). No «Stock» tab: stock is chosen once, as the inspiration."""

    def control(*items: tuple[str, str]) -> rx.Component:
        return rx.segmented_control.root(
            *(rx.segmented_control.item(label, value=value) for value, label in items),
            value=tab,
            on_change=lambda value: CreativeState.set_picker_tab(target, value),
            size="1",
            aria_label="De dónde viene",
            class_name="q-seg-fit",
        )

    rest = (("upload", "Subir"), ("pieces", "Publicaciones"))
    # with a catalog product, «Inspiración» searches — only where the licence lets stock
    # go (`_INSPIRATION_TARGETS`): never the product photos nor the avatar's reference
    search = (("inspiration", "Inspiración"),) if target in _INSPIRATION_TARGETS else ()
    # a background or a motion reference is not a product: no catalog tab there
    no_catalog = target in _NO_CATALOG_TARGETS
    brand = () if no_catalog else (("brandcat", "Catálogo"),)
    own = () if no_catalog else (("catalog", "Catálogo"),)
    return rx.cond(
        CreativeState.product_source == "stock",
        control(("catalog", "Inspiración"), *brand, *rest),
        control(*own, *search, *rest),
    )


def _media_picker(target: str, upload: rx.Component, *, media_type: str = "image") -> rx.Component:
    """A slot's sources: the chosen product's files (the stock inspiration's, when it
    came from stock — then the brand's catalog is a tab of its own), inspiration to
    search where the licence lets stock go, an upload (the slot's own drop zone,
    `upload`) and the brand's pieces. A tile is ticked while the slot holds it; a click
    puts it in or takes it out (`CreativeState.pick_media`)."""
    image = media_type == "image"
    tab = CreativeState.picker_tab_view[target].to(str)
    held = CreativeState.picker_selected[target].to(list[str])
    icon = "image" if image else "film"
    noun = "fotos" if image else "videos"
    stock = CreativeState.product_source == "stock"
    catalog = CreativeState.product_photo_keys if image else CreativeState.product_video_keys
    pieces = CreativeState.piece_images if image else CreativeState.piece_videos
    product_tiles = [
        rx.foreach(
            catalog,
            lambda key: _catalog_picker_tile(
                key, held.contains(key), CreativeState.pick_media(target, "catalog", key), image
            ),
        )
    ]
    has_product_files = catalog.length() > 0
    searchable = target in (*_INSPIRATION_TARGETS, "products")
    catalog_tab = rx.cond(
        has_product_files,
        rx.flex(*product_tiles, wrap="wrap", spacing="2"),
        _picker_note(
            rx.cond(
                stock,
                f"Tu inspiración no tiene {noun}: búscalas en «Tus productos» o súbelas.",
                rx.cond(
                    CreativeState.selected_product_id != "",
                    f"El producto que elegiste no tiene {noun} en el catálogo.",
                    f"Elige un producto del catálogo al empezar y sus {noun} aparecen aquí.",
                ),
            )
        ),
    )
    brand_files = (
        CreativeState.brand_catalog_photos if image else CreativeState.brand_catalog_videos
    )

    def brand_tile(item: rx.Var[dict[str, str]]) -> rx.Component:
        key = item["key"]
        on_select = CreativeState.pick_media(target, "brandcat", key)
        if image:
            return _picker_tile(
                _key_src(key), key != "", held.contains(key), on_select, icon, item["name"]
            )
        return _picker_video_tile(
            key, None, rx.get_upload_url(key), held.contains(key), on_select, item["name"]
        )

    brandcat_tab = rx.cond(
        CreativeState.catalog_loading,
        _picker_note("Cargando tu catálogo…"),
        rx.cond(
            brand_files.length() > 0,
            rx.flex(
                rx.foreach(brand_files, brand_tile),
                wrap="wrap",
                spacing="2",
                max_height="18rem",
                overflow_y="auto",
                width="100%",
            ),
            _picker_note(f"Tu catálogo aún no tiene {noun}."),
        ),
    )
    pieces_tab = rx.cond(
        CreativeState.pieces_loading,
        _picker_note("Cargando tus publicaciones…"),
        rx.cond(
            pieces.length() > 0,
            rx.flex(
                rx.foreach(
                    pieces,
                    lambda item: _picker_tile(
                        BACKEND_BASE + item["view"],
                        item["view"] != "",
                        held.contains(item["key"]),
                        CreativeState.pick_media(target, "pieces", item["key"]),
                        icon,
                        item["label"],
                    ),
                ),
                wrap="wrap",
                spacing="2",
                max_height="18rem",
                overflow_y="auto",
                width="100%",
            ),
            _picker_note(f"Aún no tienes publicaciones con {noun}."),
        ),
    )
    if target == "background":
        # a stock product: its picks, then the search for more — only for a background
        # (§ 2026-10-19: elsewhere «Inspiración» keeps to what was picked on the product
        # screen, no new search)
        catalog_tab = rx.vstack(
            catalog_tab,
            rx.cond(stock, _inspiration_search(target, image)),
            spacing="3",
            width="100%",
            align_items="start",
        )
    return rx.vstack(
        _picker_tabs(target, tab),
        rx.match(
            tab,
            ("catalog", catalog_tab),
            ("brandcat", brandcat_tab),
            ("inspiration", _inspiration_search(target, image) if searchable else upload),
            ("pieces", pieces_tab),
            upload,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _mixed_media_picker(target: str, upload: rx.Component) -> rx.Component:
    """A mixed slot's sources (§ request 2026-10-20: «cuando se quiera un video se junten
    … videos e imágenes»): the same tabs as `_media_picker`, each showing the images AND
    the videos it has — the product's (catalog or inspiration), the brand's catalog, an
    inspiration search, an upload and the pieces. A click sends the file to the slot of
    its type (`CreativeState.pick_mixed_media`)."""
    tab = CreativeState.picker_tab_view[target].to(str)
    held = CreativeState.picker_selected[target].to(list[str])
    stock = CreativeState.product_source == "stock"

    def pick(source: str, key: rx.Var[str], media: str) -> object:
        return CreativeState.pick_mixed_media(target, source, key, media)

    def tiles(*groups: rx.Component) -> rx.Component:
        return rx.flex(
            *groups,
            wrap="wrap",
            spacing="2",
            max_height="18rem",
            overflow_y="auto",
            width="100%",
        )

    photos, videos = CreativeState.product_photo_keys, CreativeState.product_video_keys
    catalog_tab = rx.cond(
        (photos.length() + videos.length()) > 0,
        tiles(
            rx.foreach(
                photos,
                lambda key: _catalog_picker_tile(
                    key, held.contains(key), pick("catalog", key, "image"), True
                ),
            ),
            rx.foreach(
                videos,
                lambda key: _catalog_picker_tile(
                    key, held.contains(key), pick("catalog", key, "video"), False
                ),
            ),
        ),
        _picker_note(
            rx.cond(
                stock,
                "Tu inspiración no tiene fotos ni videos: búscalos en «Tus productos» o súbelos.",
                rx.cond(
                    CreativeState.selected_product_id != "",
                    "El producto que elegiste no tiene fotos ni videos en el catálogo.",
                    "Elige un producto del catálogo al empezar y sus fotos y videos aparecen aquí.",
                ),
            )
        ),
    )

    def brand_photo(item: rx.Var[dict[str, str]]) -> rx.Component:
        key = item["key"]
        return _picker_tile(
            _key_src(key),
            key != "",
            held.contains(key),
            pick("brandcat", key, "image"),
            "image",
            item["name"],
        )

    def brand_video(item: rx.Var[dict[str, str]]) -> rx.Component:
        key = item["key"]
        return _picker_video_tile(
            key,
            None,
            rx.get_upload_url(key),
            held.contains(key),
            pick("brandcat", key, "video"),
            item["name"],
        )

    brand_photos, brand_videos = (
        CreativeState.brand_catalog_photos,
        CreativeState.brand_catalog_videos,
    )
    brandcat_tab = rx.cond(
        CreativeState.catalog_loading,
        _picker_note("Cargando tu catálogo…"),
        rx.cond(
            (brand_photos.length() + brand_videos.length()) > 0,
            tiles(rx.foreach(brand_photos, brand_photo), rx.foreach(brand_videos, brand_video)),
            _picker_note("Tu catálogo aún no tiene fotos ni videos."),
        ),
    )

    def piece(item: rx.Var[dict[str, str]], media: str) -> rx.Component:
        return _picker_tile(
            BACKEND_BASE + item["view"],
            item["view"] != "",
            held.contains(item["key"]),
            pick("pieces", item["key"], media),
            "image" if media == "image" else "film",
            item["label"],
        )

    piece_images, piece_videos = CreativeState.piece_images, CreativeState.piece_videos
    pieces_tab = rx.cond(
        CreativeState.pieces_loading,
        _picker_note("Cargando tus publicaciones…"),
        rx.cond(
            (piece_images.length() + piece_videos.length()) > 0,
            tiles(
                rx.foreach(piece_images, lambda item: piece(item, "image")),
                rx.foreach(piece_videos, lambda item: piece(item, "video")),
            ),
            _picker_note("Aún no tienes publicaciones con fotos o videos."),
        ),
    )
    return rx.vstack(
        _picker_tabs(target, tab),
        rx.match(
            tab,
            ("catalog", catalog_tab),
            ("brandcat", brandcat_tab),
            ("inspiration", _inspiration_search(target, None)),
            ("pieces", pieces_tab),
            upload,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


_CLIP_IMAGE_ACCEPT = {"image/*": [".png", ".jpg", ".jpeg", ".webp"]}
_CLIP_VIDEO_ACCEPT = {"video/mp4": [".mp4"], "video/quicktime": [".mov"]}
_CLIP_AUDIO_ACCEPT = {"audio/mpeg": [".mp3"], "audio/wav": [".wav"]}
_CLIP_MAX_BYTES = 200 * 1024 * 1024


def _clip_drop(
    upload_id: str, label: str, hint: str, accept: dict, handler: object, *, max_files: int
) -> rx.Component:
    """A compact drop zone for one kind of clip input."""
    return dropzone(
        rx.vstack(
            rx.icon("upload", size=T.ICON_MD, color=T.TEXT_FAINT),
            rx.text(label, size="1", weight="medium", text_align="center"),
            rx.text(hint, size="1", color=T.TEXT_MUTED, text_align="center"),
            align="center",
            spacing="1",
        ),
        upload_id=upload_id,
        accept=accept,
        max_files=max_files,
        multiple=max_files > 1,
        max_size=_CLIP_MAX_BYTES,
        on_drop=handler(rx.upload_files(upload_id=upload_id)),  # type: ignore[operator]
        variant="compact",
        width="100%",
    )


def _clip_thumb(key: rx.Var[str], *, size: str = "4.5rem") -> rx.Component:
    return media_thumb(_key_src(key), size=size, icon="image", has=_key_has(key))


def _clip_file_row(item: rx.Var[dict[str, str]], icon: str, on_remove: object) -> rx.Component:
    return rx.hstack(
        rx.icon(icon, size=T.ICON_SM, color=T.TEXT_MUTED, flex_shrink="0"),
        rx.text(
            item["name"],
            size="2",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
            flex="1",
        ),
        rx.button(
            rx.icon("x", size=12),
            "Quitar",
            variant="ghost",
            color_scheme="gray",
            size="1",
            on_click=on_remove(item["key"]),  # type: ignore[operator]
        ),
        width="100%",
        align="center",
        spacing="2",
    )


def _video_thumb(src: rx.Var[str], *, size: str = "4.5rem", mark: bool = True) -> rx.Component:
    """A video's small preview (§ request 2026-10-15): its first frame in the thumb
    frame, with the play mark (`mark`; a picker tile has the round play instead) — only
    the metadata is fetched, never the whole file."""
    return rx.box(
        rx.el.video(
            src=src + "#t=0.1",
            muted=True,
            preload="metadata",
            plays_inline=True,
            aria_hidden="true",
        ),
        *(
            [
                rx.box(
                    rx.icon("play", size=12),
                    class_name="q-cr-mark",
                    bottom="0.2rem",
                    right="0.2rem",
                    padding="0.15rem",
                )
            ]
            if mark
            else []
        ),
        class_name="q-thumb q-cr-video-thumb",
        width=size,
        height=size,
        min_width=size,
    )


def _preview_thumb(key: rx.Var[str], on_remove: object, label: str) -> rx.Component:
    """A picture the piece holds, with its ✕ — the previews of the clip, the products
    and the background (§ request 2026-10-14)."""
    return _removable(_clip_thumb(key, size="5rem"), on_remove, label)


def _removable(picture: rx.Component, on_remove: object, label: str) -> rx.Component:
    """A thumbnail with its ✕ in the corner."""
    return rx.box(
        picture,
        rx.icon_button(
            rx.icon("trash-2", size=13),
            size="1",
            variant="solid",
            color_scheme="gray",
            high_contrast=True,
            radius="full",
            aria_label=label,
            title=label,
            on_click=on_remove,
            position="absolute",
            top="0.25rem",
            right="0.25rem",
        ),
        position="relative",
        flex_shrink="0",
    )


def _clip_strip_item(item: rx.Var[dict[str, str]], index: rx.Var[int]) -> rx.Component:
    """One file of the clip — an image or a video — dragged into its place (§ requests
    2026-10-14/19: «según el orden sea el clip inicial/final», videos included): the
    first opens the clip, the last closes it — marked on the picture; an image between
    says what it is for, a video between lends its movement."""
    key = item["key"]
    video = item["kind"] == "video"
    first = CreativeState.clip_first_frame_key == key
    last = CreativeState.clip_last_frame_key == key
    picture = rx.cond(
        video,
        _removable(
            rx.cond(
                CreativeState.piece_views.contains(key),
                _slide_thumb(
                    CreativeState.piece_views[key].to(str), rx.Var.create("video"), "5rem"
                ),
                _video_thumb(rx.get_upload_url(key), size="5rem"),
            ),
            CreativeState.remove_clip_video(key),
            "Quitar video",
        ),
        _preview_thumb(key, CreativeState.remove_clip_image(key), "Quitar imagen"),
    )
    return _SlideCard.create(
        rx.box(
            picture,
            rx.cond(
                first | last,
                _strip_badge(
                    rx.text(rx.cond(first, "Inicio", "Final"), size="1", weight="bold"),
                    bottom="0.3rem",
                    left="0.3rem",
                ),
            ),
            position="relative",
        ),
        rx.cond(
            first | last,
            rx.text(
                rx.cond(first, "Abre el clip", "Cierra el clip"),
                size="1",
                color=T.TEXT_MUTED,
                text_align="center",
            ),
            rx.cond(
                video,
                rx.text("Movimiento", size="1", color=T.TEXT_MUTED, text_align="center"),
                # § 2026-10-14: what the image is for — the prompt names it so
                rx.select.root(
                    rx.select.trigger(width="100%", aria_label="Para qué es esta imagen"),
                    rx.select.content(
                        rx.select.item("Producto", value="product"),
                        rx.select.item("Lugar", value="place"),
                        rx.select.item("Estilo", value="style"),
                    ),
                    value=rx.cond(item["role"] != "", item["role"], "product"),
                    on_change=lambda role: CreativeState.set_clip_image_role(key, role),
                    size="1",
                ),
            ),
        ),
        on_drag_start=CreativeState.start_clip_image_drag(index),
        on_drop=CreativeState.drop_clip_image(index),
        custom_attrs={
            "data-slide-group": "clip",
            "data-slide-key": key,
            "aria-label": rx.cond(video, "Video ", "Imagen ") + (index + 1).to(str) + " del clip",
        },
        display="flex",
        flex_direction="column",
        align_items="center",
        gap="0.25rem",
        width="6.5rem",
        class_name="q-cr-slide--drag",
    )


def _clip_block(title: str, hint: str, *body: rx.Component) -> rx.Component:
    return rx.vstack(
        _field_label(title, hint),
        *body,
        spacing="2",
        width="100%",
        align_items="start",
    )


def _clip_references_view() -> rx.Component:
    """The clip's «Referencias» (§ request 2026-10-14): images (the catalog product's
    photos one click away, or uploaded), videos and audio — all optional. With any of
    them the clip is made on Seedance 2.x."""
    return rx.vstack(
        rx.vstack(
            rx.heading("Referencias (opcional)", size="4", as_="h3"),
            rx.text(
                "Lo que el clip debe seguir: el producto y su estilo, el movimiento de un "
                "video, la música de un audio.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            spacing="0",
            align_items="start",
        ),
        rx.cond(
            CreativeState.clip_strip.length() > 0,
            _clip_block(
                "Orden del clip",
                "Arrastra las imágenes y los videos para ordenarlos: el primero abre el clip y "
                "el último lo cierra (de un video se toma su primer o su último fotograma). "
                "Las imágenes del medio: di si son tu producto, tu lugar o un estilo a imitar.",
                rx.flex(
                    rx.foreach(CreativeState.clip_strip, _clip_strip_item),
                    _script_on_mount(_SLIDE_DRAG_JS),
                    spacing="3",
                    wrap="wrap",
                ),
                # review 2026-10-20: what sits between the first and the last file is a
                # reference — only the advanced video model takes it
                rx.cond(
                    CreativeState.clip_strip.length() > 2,
                    callout(
                        "Lo que va entre el primero y el último son referencias y necesitan "
                        "el modelo de video avanzado. Si no está activado, las imágenes del "
                        "medio se omiten y los videos o audios no se pueden usar.",
                        "info",
                    ),
                ),
            ),
        ),
        _clip_block(
            "Imágenes",
            "Hasta 9: tu producto, tu lugar o un estilo a imitar.",
            _media_picker(
                "clip_images",
                rx.cond(
                    CreativeState.clip_image_room > 0,
                    _clip_drop(
                        "clip_images",
                        "Sube imágenes",
                        "PNG, JPG o WEBP",
                        _CLIP_IMAGE_ACCEPT,
                        CreativeState.handle_clip_image_uploads,
                        max_files=9,
                    ),
                    _picker_note("Ya tienes las 9 imágenes."),
                ),
            ),
        ),
        _clip_block(
            "Videos",
            "Hasta 3, de 2 a 15 s: su movimiento, cámara y ritmo. Sin personas reales.",
            _media_picker(
                "clip_videos",
                rx.cond(
                    CreativeState.clip_videos.length() < 3,
                    _clip_drop(
                        "clip_videos",
                        "Sube un video",
                        "MP4 o MOV · hasta 200 MB",
                        _CLIP_VIDEO_ACCEPT,
                        CreativeState.handle_clip_video_uploads,
                        max_files=3,
                    ),
                    _picker_note("Ya tienes los 3 videos."),
                ),
                media_type="video",
            ),
        ),
        _clip_block(
            "Audios",
            "Hasta 3: la música o el sonido que acompaña el clip.",
            rx.foreach(
                CreativeState.clip_audios,
                lambda item: _clip_file_row(item, "music", CreativeState.remove_clip_audio),
            ),
            rx.cond(
                CreativeState.clip_audios.length() < 3,
                _clip_drop(
                    "clip_audios",
                    "Sube un audio",
                    "MP3 o WAV",
                    _CLIP_AUDIO_ACCEPT,
                    CreativeState.handle_clip_audio_uploads,
                    max_files=3,
                ),
            ),
        ),
        # § request 2026-10-20: «poner mis logos en mis clips» — laid over every frame
        rx.cond(
            CreativeState.brand_logo_choices.length() > 0,
            _clip_block(
                "Tu logo (opcional)",
                "Va en una esquina de todo el clip, encima del video. Elige uno.",
                _brand_media_picker(
                    CreativeState.brand_logo_choices,
                    "chosen",
                    CreativeState.toggle_brand_logo,
                    "Logo",
                ),
            ),
        ),
        _upload_error(),
        spacing="5",
        width="100%",
        align_items="start",
    )


def _product_screen() -> rx.Component:
    """Before the side panel (§ requests 2026-10-14/19): the catalog product the piece is
    about, or the inspiration that illustrates it — one or the other, switched with the
    button beside «Continuar» (no tabs, no «Continuar sin producto»)."""
    inspiration = CreativeState.product_tab == "stock"
    return card(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.heading(
                        rx.cond(
                            inspiration, "Busca tu inspiración", "¿Sobre qué producto creamos?"
                        ),
                        size="5",
                        as_="h2",
                    ),
                    rx.text(
                        rx.cond(
                            inspiration,
                            "Imágenes y videos que ilustran lo que vendes: elige uno o varios.",
                            "Elige un producto de tu catálogo: su nombre y sus fotos reales "
                            "entran en la publicación.",
                        ),
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    align_items="start",
                ),
                rx.spacer(),
                # m-24842973 (N4): the product that is missing is added in Tus
                # productos, and saving it comes back here with it chosen.
                rx.link(
                    rx.button(
                        rx.icon("plus", size=T.ICON_SM),
                        ADD_PRODUCT_LABEL,
                        variant="soft",
                        size="3",
                        width=rx.breakpoints(initial="100%", sm="auto"),
                    ),
                    href=new_product_href(CREATE_RETURN_PATH),
                    flex_shrink="0",
                    width=rx.breakpoints(initial="100%", sm="auto"),
                ),
                width="100%",
                align="start",
                spacing="3",
                # 360 px (N12): the button drops under the heading instead of squeezing it
                wrap="wrap",
            ),
            rx.cond(
                inspiration,
                _stock_product_panel(),
                _catalog_product_grid(),
            ),
            _product_screen_nav(),
            spacing="5",
            width="100%",
            flex="1",
        ),
        padding="1.5rem",
        width="100%",
        flex="1",
        display="flex",
        class_name="q-cr-view",
    )


def _catalog_product_grid() -> rx.Component:
    """«Mi catálogo»: the brand's products (the screen as it was before stock)."""
    return rx.fragment(
        rx.cond(
            CreativeState.catalog_error != "",
            callout(CreativeState.catalog_error, "warn"),
        ),
        rx.box(
            rx.cond(
                CreativeState.catalog_loading | ~CreativeState.catalog_loaded,
                rx.cond(
                    CreativeState.catalog_error == "",
                    skeleton_card(lines=4),
                    rx.button("Reintentar", on_click=CreativeState.load_catalog_products, size="3"),
                ),
                rx.cond(
                    CreativeState.catalog_items.length() > 0,
                    rx.grid(
                        rx.foreach(CreativeState.catalog_items, _catalog_card),
                        _script_on_mount(_CATALOG_HOVER_JS),
                        columns=rx.breakpoints(initial="1", sm="2", md="3", xl="4"),
                        spacing="3",
                        width="100%",
                        role="radiogroup",
                        aria_label="Producto del catálogo",
                    ),
                    empty_state(
                        "package",
                        "Aún no hay productos en tu catálogo",
                        "Agrega tu producto con sus fotos y vuelves aquí con él ya elegido. "
                        "También puedes usar una inspiración: imágenes y videos que ilustran "
                        "lo que vendes.",
                        # N8 (m-24842961); coming back with it chosen (m-24842973, N4)
                        action=rx.link(
                            rx.button(rx.icon("plus", size=T.ICON_SM), ADD_PRODUCT_LABEL, size="3"),
                            href=new_product_href(CREATE_RETURN_PATH),
                        ),
                    ),
                ),
            ),
            width="100%",
            flex="1",
        ),
    )


def _product_screen_nav() -> rx.Component:
    """The product screen's bottom bar: what is chosen, the switch to the other source
    — «Usar inspiración» on the catalog, «Usar mi catálogo» on the inspiration (§ request
    2026-10-19: it replaces «Continuar sin producto» and the tabs) — and «Continuar»."""
    return rx.hstack(
        rx.cond(
            (CreativeState.selected_product_id != "") & (CreativeState.product_tab == "catalog"),
            rx.hstack(
                rx.icon("check", size=T.ICON_SM, color=T.tone_color("accent", 11)),
                rx.text(CreativeState.brief_product_ref, size="2", weight="medium"),
                spacing="2",
                align="center",
            ),
        ),
        rx.spacer(),
        rx.cond(
            CreativeState.product_tab == "stock",
            rx.button(
                rx.icon("package", size=T.ICON_SM),
                "Usar mi catálogo",
                variant="soft",
                color_scheme="gray",
                size="3",
                radius=_CONTROL_RADIUS,
                on_click=CreativeState.set_product_tab("catalog"),
            ),
            rx.button(
                rx.icon("sparkles", size=T.ICON_SM),
                "Usar inspiración",
                variant="soft",
                color_scheme="gray",
                size="3",
                radius=_CONTROL_RADIUS,
                on_click=CreativeState.set_product_tab("stock"),
            ),
        ),
        width="100%",
        align="center",
        spacing="3",
        flex_wrap="wrap",
        class_name="q-cr-view-nav",
    )


# -- the product from stock (plan-integracion-stock R2, 2026-10-16) ----------------------

_STOCK_NOTE = (
    "Es una imagen ilustrativa, no la foto de tu producto. Revisa que la publicación no "
    "prometa algo distinto de lo que vendes."
)
_STOCK_VIDEO_NOTE = (
    "Es un video ilustrativo, no de tu producto: sirve para un Clip o una Galería. Revisa "
    "que la publicación no prometa algo distinto de lo que vendes."
)
_STOCK_MIXED_NOTE = (
    "Son imágenes y videos ilustrativos, no de tu producto: los videos sirven para un Clip "
    "o una Galería. Revisa que la publicación no prometa algo distinto de lo que vendes."
)


def _stock_picked(tile: rx.Var[dict[str, str]], media: str) -> rx.Var[bool]:
    """Whether `tile` is one of the product screen's picks (`CreativeState.stock_picks`)."""
    return CreativeState.stock_picks.contains(f"{media}|" + tile["id"])


def _stock_tile(tile: rx.Var[dict[str, str]]) -> rx.Component:
    """One stock image on the product screen: the bank's thumbnail (shown, never kept),
    its author, the bank. A click adds it to the picks or takes it out."""
    selected = _stock_picked(tile, "image")
    return rx.box(
        choice_card(
            rx.box(
                media_thumb(
                    tile["thumb"],
                    size=None,
                    width="100%",
                    height="9rem",
                    alt=tile["author"],
                    custom_attrs={"referrerpolicy": "no-referrer"},
                ),
                rx.cond(selected, rx.box(choice_card_check(), class_name="q-cr-ghost-check")),
                rx.text(tile["provider_label"], class_name="q-cr-mark q-cr-stock-bank"),
                position="relative",
            ),
            key=tile["id"],
            selected=selected,
            on_select=CreativeState.choose_stock_product(tile["id"], "image"),
            role="checkbox",
            padding="0.3rem",
            width="100%",
            aria_label=tile["author"],
        ),
        _stock_credit_link(tile),
        width="100%",
    )


def _stock_credit_link(tile: rx.Var[dict[str, str]]) -> rx.Component:
    """The author under a stock tile, linked to their page (the banks ask for it)."""
    return rx.link(
        tile["author"],
        href=tile["author_url"],
        is_external=True,
        size="1",
        class_name="q-cr-stock-credit",
        title=tile["author"],
    )


def _stock_video_tile(tile: rx.Var[dict[str, str]]) -> rx.Component:
    """One stock video on the product screen, picked like an image: its poster (shown,
    never kept), the bank, its length, «Vertical», the author and the round play in the
    centre. Play shows the bank's small rendition in the SAME frame — whole (letterboxed,
    never cropped) and without moving the grid (§ requests 2026-10-19); a click on the
    playing video picks it, the pause on hover stops it."""
    selected = _stock_picked(tile, "video")
    on_select = CreativeState.choose_stock_product(tile["id"], "video")
    poster = rx.box(
        choice_card(
            rx.box(
                media_thumb(
                    tile["thumb"],
                    size=None,
                    width="100%",
                    height="9rem",
                    icon="film",
                    alt=tile["author"],
                    custom_attrs={"referrerpolicy": "no-referrer"},
                ),
                rx.cond(selected, rx.box(choice_card_check(), class_name="q-cr-ghost-check")),
                rx.text(tile["provider_label"], class_name="q-cr-mark q-cr-stock-bank"),
                rx.cond(
                    tile["duration"] != "",
                    rx.text(tile["duration"], class_name="q-cr-mark q-cr-stock-length"),
                ),
                rx.cond(
                    tile["vertical"] != "",
                    rx.text("Vertical", class_name="q-cr-mark q-cr-stock-vertical"),
                ),
                position="relative",
            ),
            key=tile["id"],
            selected=selected,
            on_select=on_select,
            role="checkbox",
            padding="0.3rem",
            width="100%",
            aria_label=tile["author"],
        ),
        rx.cond(
            tile["preview"] != "",
            _play_button(CreativeState.play_stock_video(tile["id"]), "calc(0.3rem + 4.5rem)"),
        ),
        position="relative",
        class_name="q-cr-play-host",
    )
    player = rx.box(
        rx.el.video(
            src=tile["preview"],
            auto_play=True,
            muted=~CreativeState.preview_sound,
            loop=True,
            plays_inline=True,
            preload="auto",
            custom_attrs={"referrerPolicy": "no-referrer"},
            class_name="q-cr-stock-video",
        ),
        _pick_hit(on_select, selected, tile["author"]),
        rx.cond(selected, rx.box(choice_card_check(), class_name="q-cr-ghost-check")),
        _pause_button(),
        _sound_button(),
        class_name=rx.cond(
            selected, "q-cr-stock-player q-cr-stock-player--on", "q-cr-stock-player"
        ),
    )
    return rx.box(
        rx.cond(CreativeState.hit_playing == tile["id"], player, poster),
        _stock_credit_link(tile),
        width="100%",
    )


def _stock_mixed_tile(tile: rx.Var[dict[str, str]]) -> rx.Component:
    """«Stock»'s one grid holds images and videos: each tile as its kind."""
    return rx.cond(tile["media_type"] == "video", _stock_video_tile(tile), _stock_tile(tile))


def _stock_chosen_thumb(tile: rx.Var[dict[str, str]]) -> rx.Component:
    """One pick in the strip under the grid: its thumbnail and ✕ to take it out."""
    return rx.box(
        media_thumb(
            tile["thumb"],
            size="3.5rem",
            icon="film",
            alt=tile["author"],
            custom_attrs={"referrerpolicy": "no-referrer"},
        ),
        rx.cond(
            tile["media_type"] == "video",
            rx.center(rx.icon("film", size=11), class_name="q-cr-stock-chosen-kind"),
        ),
        rx.icon_button(
            rx.icon("x", size=11),
            size="1",
            variant="solid",
            color_scheme="gray",
            high_contrast=True,
            radius="full",
            aria_label="Quitar " + tile["author"],
            title="Quitar",
            on_click=CreativeState.choose_stock_product(tile["id"], tile["media_type"]),
            class_name="q-cr-stock-chosen-x",
        ),
        class_name="q-cr-stock-chosen",
    )


def _stock_product_panel() -> rx.Component:
    """«Stock»: images AND videos in one grid (§ requests 2026-10-16/17) — both banks
    searched at once (on Enter or the button, never while typing), pick one or several
    (§ request 2026-10-19) — inspiration, so no product name. A fixed note says it only
    illustrates it. A video fits the Clip and the Galería; with no image among the picks, the other
    options say so in a popup (`_kind_conflict_dialog`)."""
    results = rx.cond(
        CreativeState.stock_any_loading & (CreativeState.stock_tiles.length() == 0),
        skeleton_rows(rows=2, height="9rem"),
        rx.cond(
            CreativeState.stock_tiles.length() > 0,
            rx.vstack(
                rx.grid(
                    rx.foreach(CreativeState.stock_tiles, _stock_mixed_tile),
                    columns=rx.breakpoints(initial="2", sm="3", lg="4", xl="5"),
                    spacing="3",
                    width="100%",
                    role="group",
                    aria_label="Imágenes y videos de inspiración",
                ),
                rx.hstack(
                    rx.text("Imágenes y videos de ", size="1", color=T.TEXT_MUTED),
                    rx.foreach(
                        CreativeState.stock_credits,
                        lambda c: rx.link(c["name"], href=c["url"], is_external=True, size="1"),
                    ),
                    rx.spacer(),
                    rx.cond(
                        CreativeState.stock_any_more,
                        rx.button(
                            "Ver más",
                            variant="soft",
                            color_scheme="gray",
                            size="1",
                            loading=CreativeState.stock_any_loading,
                            on_click=CreativeState.more_stock_products,
                        ),
                    ),
                    width="100%",
                    align="center",
                    spacing="1",
                    class_name="q-cr-stock-credits",
                ),
                spacing="2",
                width="100%",
            ),
            empty_state(
                "image",
                "Busca una imagen o un video para tu producto",
                "Escribe qué vendes —«hamburguesa», «uñas acrílicas», «pastel de chocolate»— "
                "o deja la caja vacía para usar tu marca. Solo mostramos material sin "
                "personas; los videos, hasta 15 s y sin sonido.",
            ),
        ),
    )
    chosen = rx.cond(
        CreativeState.stock_chosen.length() > 0,
        rx.vstack(
            rx.hstack(
                rx.text(
                    rx.cond(
                        CreativeState.stock_chosen.length() == 1,
                        "1 elegido",
                        CreativeState.stock_chosen.length().to_string() + " elegidos",
                    ),
                    size="2",
                    weight="medium",
                ),
                rx.text(f"· hasta {STOCK_MAX_PICKS}", size="1", color=T.TEXT_MUTED),
                spacing="1",
                align="baseline",
            ),
            rx.flex(
                rx.foreach(CreativeState.stock_chosen, _stock_chosen_thumb),
                gap="0.5rem",
                wrap="wrap",
                role="list",
                aria_label="Lo que elegiste",
            ),
            rx.cond(
                CreativeState.stock_pick_notice != "",
                rx.text(CreativeState.stock_pick_notice, size="1", color=T.tone_color("warn", 11)),
            ),
            callout(
                rx.cond(
                    CreativeState.stock_chosen_has_video,
                    rx.cond(
                        CreativeState.stock_chosen_has_image, _STOCK_MIXED_NOTE, _STOCK_VIDEO_NOTE
                    ),
                    _STOCK_NOTE,
                ),
                "warn",
                class_name="q-cr-stock-note",
            ),
            spacing="3",
            width="100%",
        ),
    )
    from_kit = (CreativeState.stock_from_kit | CreativeState.vstock_from_kit) & (
        CreativeState.stock_tiles.length() > 0
    )
    kit_words = rx.cond(
        CreativeState.stock_kit_words.length() > 0,
        CreativeState.stock_kit_words.join(" · "),
        CreativeState.vstock_kit_words.join(" · "),
    )
    return rx.vstack(
        rx.hstack(
            rx.input(
                rx.input.slot(rx.icon("search", size=T.ICON_SM)),
                value=CreativeState.stock_query,
                on_change=CreativeState.set_stock_query,
                on_key_down=CreativeState.stock_search_on_enter,
                placeholder="Busca tu producto: hamburguesa, uñas, pastel…",
                max_length=100,
                size="3",
                flex="1",
                aria_label="Buscar imágenes y videos de inspiración",
            ),
            rx.button(
                "Buscar",
                size="3",
                radius=_CONTROL_RADIUS,
                loading=CreativeState.stock_any_loading,
                disabled=~CreativeState.stock_on,
                on_click=CreativeState.search_stock_products,
            ),
            width="100%",
            spacing="2",
        ),
        rx.cond(
            ~CreativeState.stock_on,
            callout("La inspiración no está disponible ahora mismo.", "warn"),
        ),
        rx.cond(
            from_kit,
            rx.text(
                "Con lo que sabemos de tu marca buscamos: ",
                rx.text.strong(kit_words),
                ". Escribe otras palabras si buscas otra cosa.",
                size="1",
                color=T.TEXT_MUTED,
            ),
        ),
        rx.cond(
            CreativeState.stock_view_error != "",
            callout(CreativeState.stock_view_error, "warn"),
        ),
        rx.cond(
            (CreativeState.stock_error != "") & (CreativeState.stock_tiles.length() > 0),
            callout(CreativeState.stock_error, "warn"),
        ),
        rx.box(results, width="100%", flex="1"),
        chosen,
        spacing="4",
        width="100%",
        flex="1",
    )


def _product_chip() -> rx.Component:
    """At the end of the side panel (§ requests 2026-10-19: beside the centre's heading
    it wrapped onto its own row and pushed the view down): the product the piece is
    about — or the stock it takes as inspiration — and «Cambiar», back to «Mi catálogo ·
    Stock»."""
    return rx.hstack(
        rx.cond(
            CreativeState.product_chip_key != "",
            media_thumb(
                _key_src(CreativeState.product_chip_key),
                has=_key_has(CreativeState.product_chip_key),
                size="2rem",
                alt=CreativeState.brief_product_ref,
            ),
            rx.center(
                rx.icon("package", size=T.ICON_SM, color=T.TEXT_MUTED),
                width="2rem",
                height="2rem",
                flex_shrink="0",
            ),
        ),
        rx.vstack(
            rx.hstack(
                rx.text(
                    rx.cond(CreativeState.product_source == "stock", "Inspiración", "Producto"),
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                spacing="1",
                align="center",
            ),
            rx.text(
                rx.cond(
                    CreativeState.product_source == "stock",
                    CreativeState.stock_inspiration_label,
                    rx.cond(
                        CreativeState.selected_product_id != "",
                        CreativeState.brief_product_ref,
                        "Sin producto",
                    ),
                ),
                size="2",
                weight="medium",
                class_name="q-cr-product-name",
                title=CreativeState.brief_product_ref,
            ),
            spacing="0",
            min_width="0",
            flex="1",
        ),
        rx.button(
            "Cambiar",
            variant="soft",
            color_scheme="gray",
            size="1",
            on_click=CreativeState.change_product,
            flex_shrink="0",
            aria_label="Cambiar el producto",
        ),
        spacing="2",
        align="center",
        width="100%",
        class_name="q-cr-product-chip",
    )


def _avatar_type_view() -> rx.Component:
    """Avatar's first view: which avatar — humano or animado. The animated avatar has
    no «Presentador» view and asks nothing more (§ request 2026-10-20): its character
    comes from the Brand Kit (`CreativeState.load_brand_character`), its voice is the
    brand's (`_sync_voice`)."""
    return rx.vstack(
        rx.vstack(
            rx.heading("¿Qué tipo de avatar?", size="4", as_="h3"),
            rx.text("Quién aparece en el video y lo cuenta.", size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
        ),
        rx.grid(
            *(_avatar_type_card(*option) for option in VIDEO_TYPE_OPTIONS),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="4",
            width="100%",
            role="radiogroup",
            aria_label="Tipo de avatar",
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _discover_view() -> rx.Component:
    """«Descubrir reels» (QUA-223 §2, built § request 2026-10-15): the most viewed reels
    of the brand's referentes, of its rubro, this week and this month
    (`discover_reels`)."""
    return discover_view()


def _upload_zone(upload_id: str, label: str, handler: object, *, multiple: bool) -> rx.Component:
    """A compact drop zone (`ui.dropzone`) for the pictures of a piece."""
    return dropzone(
        rx.vstack(
            rx.icon("image-up", size=T.ICON_MD, color=T.TEXT_FAINT),
            rx.text(label, size="1", text_align="center", color=T.TEXT_MUTED),
            align="center",
            spacing="1",
        ),
        upload_id=upload_id,
        accept=_IMAGE_ACCEPT,
        max_files=10 if multiple else 1,
        multiple=multiple,
        on_drop=handler(rx.upload_files(upload_id=upload_id)),
        variant="compact",
        width="100%",
    )


def _file_chip(name: rx.Var[str], on_remove: object) -> rx.Component:
    return rx.box(
        removable_pill(name, on_remove, icon="image", remove_label="Quitar imagen"),
        max_width="18rem",
    )


def _brand_media_tile(item: rx.Var, flag: str, handler: object) -> rx.Component:
    """One Brand Kit image: its thumbnail (through `/r2media`) and name; a click puts it
    in the piece or takes it out."""
    selected = item[flag] != ""
    return rx.vstack(
        rx.box(
            rx.cond(
                item["view"] != "",
                rx.image(
                    src=BACKEND_BASE + item["view"],
                    alt=item["label"],
                    width="100%",
                    height="100%",
                    object_fit="contain",
                ),
                rx.icon("image", size=T.ICON_MD, color=T.TEXT_FAINT),
            ),
            rx.cond(
                selected,
                rx.box(
                    rx.icon("check", size=12, color="white"),
                    position="absolute",
                    top="0.25rem",
                    right="0.25rem",
                    background=T.tone_color("accent", 9),
                    border_radius="9999px",
                    padding="0.15rem",
                    display="flex",
                ),
            ),
            position="relative",
            width="4.5rem",
            height="4.5rem",
            padding="0.35rem",
            display="flex",
            align_items="center",
            justify_content="center",
            background=T.SURFACE_BG_RAISED,
            border=rx.cond(selected, f"2px solid {T.tone_color('accent', 8)}", T.BORDER),
            border_radius=T.RADIUS_CONTROL,
            overflow="hidden",
        ),
        rx.text(
            item["label"],
            size="1",
            color=T.TEXT_MUTED,
            max_width="4.5rem",
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            text_align="center",
        ),
        spacing="1",
        align="center",
        on_click=handler(item["key"]),  # type: ignore[operator]
        role="checkbox",
        aria_checked=rx.cond(selected, "true", "false"),
        aria_label=item["label"],
        cursor="pointer",
    )


def _brand_media_picker(
    items: rx.Var, flag: str, handler: object, title: str, hint: str = ""
) -> rx.Component:
    """A row of Brand Kit images to pick from (`items`, each with its `flag` "1" when in
    use): the animated character's «O elige del Brand Kit», and both halves of
    «Recursos de tu marca»."""
    return rx.cond(
        items.length() > 0,
        rx.vstack(
            rx.text(title, size="1", weight="medium", color=T.TEXT_MUTED),
            rx.text(hint, size="1", color=T.TEXT_FAINT) if hint else rx.fragment(),
            rx.flex(
                rx.foreach(items, lambda item: _brand_media_tile(item, flag, handler)),
                wrap="wrap",
                spacing="2",
                role="group",
                aria_label=title,
            ),
            spacing="1",
            width="100%",
            align_items="start",
        ),
    )


def _brand_element_notes() -> rx.Component:
    """Each chosen element's usage note — what the generator will do with it."""
    return rx.foreach(
        CreativeState.brand_element_choices,
        lambda item: rx.cond(
            item["chosen"] != "",
            rx.text(
                rx.text.strong(item["label"]),
                ": ",
                rx.cond(item["usage"] != "", item["usage"], "sin nota de uso: donde encaje"),
                size="1",
                color=T.TEXT_MUTED,
            ),
        ),
    )


def _brand_resources() -> rx.Component:
    """«Recursos de tu marca» (§ request 2026-10-06): the Brand Kit's files as a resource
    of their own, apart from the background and the products. The logo takes the brand
    mark's place in the piece; every other element is used as its usage note (written in
    the Brand Kit) says — and the copy is told both."""
    return rx.cond(
        CreativeState.brand_media_items.length() > 0,
        rx.vstack(
            _field_label(
                "Recursos de tu marca (opcional)",
                "Lo que ya subiste a tu marca. El logo va donde va tu marca; cada "
                "elemento se usa según su nota de uso.",
            ),
            _brand_media_picker(
                CreativeState.brand_logo_choices,
                "chosen",
                CreativeState.toggle_brand_logo,
                "Logo",
                "Elige uno.",
            ),
            _brand_media_picker(
                CreativeState.brand_element_choices,
                "chosen",
                CreativeState.toggle_brand_element,
                "Elementos",
            ),
            _brand_element_notes(),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


def _images_section() -> rx.Component:
    """Background and product images — optional for the avatar videos."""
    return rx.vstack(
        _background_upload("Fondo (opcional)", "Arrastra la imagen de fondo o haz clic"),
        _products_upload("Producto o productos (opcional)"),
        _upload_error(),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _background_upload(label: str, hint: str, help_text: str = "") -> rx.Component:
    """The background, shown as a picture with its ✕, and its sources (§ request
    2026-10-19): «Inspiración» — the licence lets stock be a background —, an upload or
    a piece. No catalog tab: the catalog holds products, not places."""
    return rx.vstack(
        (
            _label_with_help(label, label, help_text, size="2", weight="medium")
            if help_text
            else rx.text(label, size="2", weight="medium")
        ),
        rx.cond(
            CreativeState.media_background_key != "",
            _preview_thumb(
                CreativeState.media_background_key,
                CreativeState.clear_background,
                "Quitar fondo",
            ),
        ),
        _media_picker(
            "background",
            _upload_zone(
                "creative_background",
                hint,
                CreativeState.handle_background_upload,
                multiple=False,
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _products_upload(label: str) -> rx.Component:
    """The piece's product photos: those it holds — uploaded or from a piece — and the
    catalog product's, each ticked in or out, an upload or a piece to add (2026-10-14)."""
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        # the photos it uses, as pictures (§ 2026-10-14: «las previews … como en los clips»)
        rx.cond(
            CreativeState.product_previews.length() > 0,
            rx.flex(
                rx.foreach(
                    CreativeState.product_previews,
                    lambda item: _preview_thumb(
                        item["key"],
                        CreativeState.remove_product_preview(item["key"]),
                        "Quitar foto",
                    ),
                ),
                wrap="wrap",
                spacing="2",
            ),
        ),
        _media_picker(
            "products",
            _upload_zone(
                "creative_products",
                "Arrastra una o varias fotos de producto (hasta 10). Con fondo transparente"
                " quedan mejor.",
                CreativeState.handle_product_uploads,
                multiple=True,
            ),
        ),
        # § 2026-10-09: no «Hacerlo carrusel» here any more — the carousel is its own kind
        spacing="2",
        width="100%",
        align_items="start",
    )


def _upload_error() -> rx.Component:
    return rx.cond(
        CreativeState.upload_error != "",
        rx.text(CreativeState.upload_error, size="1", color=T.tone_color("error", 11)),
    )


# -- the carousel (§ request 2026-10-09) ------------------------------------------------


def _slide_source_label(source: rx.Var) -> rx.Var:
    return rx.match(
        source,
        ("generated", "Imagen generada"),
        ("animated", "Video animado"),
        ("stock", "Video de inspiración"),
        "De una publicación",
    )


def _slide_source_icon(source: rx.Var) -> rx.Component:
    return rx.match(
        source,
        ("generated", rx.icon("image", size=T.ICON_SM)),
        ("animated", rx.icon("clapperboard", size=T.ICON_SM)),
        ("stock", rx.icon("film", size=T.ICON_SM)),
        rx.icon("library", size=T.ICON_SM),
    )


def _slide_thumb(view: rx.Var, media_type: rx.Var, size: str = "3.5rem") -> rx.Component:
    """A reused piece's thumbnail (a video shows its poster, or a film glyph)."""
    return rx.box(
        rx.cond(
            view != "",
            rx.image(
                src=BACKEND_BASE + view, alt="", width="100%", height="100%", object_fit="cover"
            ),
            rx.cond(
                media_type == "video",
                rx.icon("film", size=T.ICON_MD, color=T.TEXT_FAINT),
                rx.icon("image", size=T.ICON_MD, color=T.TEXT_FAINT),
            ),
        ),
        rx.cond(
            (view != "") & (media_type == "video"),
            rx.box(
                rx.icon("play", size=12),
                class_name="q-cr-mark",
                bottom="0.2rem",
                right="0.2rem",
                padding="0.15rem",
            ),
        ),
        position="relative",
        width=size,
        height=size,
        flex_shrink="0",
        display="flex",
        align_items="center",
        justify_content="center",
        background=T.SURFACE_BG_RAISED,
        border=T.BORDER,
        border_radius=T.RADIUS_CONTROL,
        overflow="hidden",
    )


def _slide_icon_button(icon: str, label: str, on_click: object, **props: object) -> rx.Component:
    return rx.icon_button(
        rx.icon(icon, size=14),
        on_click=on_click,
        variant="ghost",
        color_scheme="gray",
        size="1",
        aria_label=label,
        title=label,
        **props,
    )


#: The «?» of a slide's text options (§ request 2026-10-09: «Gancho» and «CTA»
#: renamed «Título» and «Botón de acción»).
_SLIDE_TEXT_HELP = (
    "La frase grande de arriba, la que hace que se detengan a mirar: el gancho que escribe "
    "la IA con la voz de tu marca. Es el mismo texto para toda la galería, así que va en "
    "una sola diapositiva (casi siempre la primera)."
)


def _strip_badge(content: rx.Component, **position: str) -> rx.Component:
    """A mark over a thumbnail's picture (`.q-cr-mark`: a dark pill, white on it)."""
    return rx.box(
        content,
        class_name="q-cr-mark",
        padding="0.05rem 0.4rem",
        line_height="1.4",
        **position,
    )


def _strip_picture(row: rx.Var) -> rx.Component:
    """What a thumbnail shows: the slide's own product photo, a reused piece's image, or
    the glyph of its kind while it has neither."""
    cover = {"width": "100%", "height": "100%", "object_fit": "cover"}
    return rx.cond(
        row["photo_key"] != "",
        rx.image(src=_key_src(row["photo_key"]), alt="", **cover),
        rx.cond(
            row["view"] != "",
            rx.image(src=BACKEND_BASE + row["view"], alt="", **cover),
            rx.center(
                rx.vstack(
                    _slide_source_icon(row["source"]),
                    rx.cond(
                        row["source"] != "existing",
                        rx.text("Sin foto", size="1"),
                    ),
                    spacing="1",
                    align="center",
                ),
                width="100%",
                height="100%",
                color=T.TEXT_FAINT,
            ),
        ),
    )


class _SlideCard(rx.el.Div):
    """A gallery thumbnail that can be dragged onto another (§ 2026-10-14).
    `assets/slide-drag.js` moves it with pointer events — animated, the others making
    room live — and dispatches a synthetic `dragstart` on it when it is lifted and a
    `drop` on the slide it is released over, the Brand Kit ranking's `_RankCard` trick;
    Reflex's elements declare no drag triggers of their own, so they are added here."""

    on_drag_start: rx.EventHandler[rx.event.no_args_event_spec]
    on_drop: rx.EventHandler[rx.event.no_args_event_spec]


#: The gallery's drag motion, sent when the gallery mounts (head scripts are not
#: reliable in dev, see `head_components` in Qualify.py); it guards against running twice.
_SLIDE_DRAG_JS = _asset_script("slide-drag.js")


def _strip_thumb(row: rx.Var, index: rx.Var[int]) -> rx.Component:
    """One slide in the strip (§ 2026-10-09, option A): its picture at the post's
    shape, its number, a play mark when it is a video and the words printed on it.
    A click opens it in the editor below."""
    selected = row["selected"] != ""
    return _SlideCard.create(
        _strip_picture(row),
        _strip_badge(rx.text(row["n"], size="1", weight="bold"), top="0.3rem", left="0.3rem"),
        rx.cond(
            row["media_type"] == "video",
            _strip_badge(rx.icon("play", size=11), top="0.3rem", right="0.3rem"),
        ),
        rx.cond(
            row["text_label"] != "",
            _strip_badge(rx.text(row["text_label"], size="1"), bottom="0.3rem", left="0.3rem"),
        ),
        on_click=CreativeState.select_carousel_slide(index),
        # § 2026-10-14: drag a thumbnail onto another to reorder the gallery — the
        # motion is `assets/slide-drag.js`'s, the order the server's
        on_drag_start=CreativeState.start_slide_drag(index),
        on_drop=CreativeState.drop_slide(index),
        custom_attrs={
            "data-slide-group": "gallery",
            "data-slide-key": row["uid"],
            "role": "button",
            "aria-label": "Diapositiva " + row["n"].to(str),
            "aria-pressed": rx.cond(selected, "true", "false"),
        },
        position="relative",
        width="100%",
        aspect_ratio="4 / 5",
        # a fixed class: the open slide is drawn from `aria-pressed`, so React never
        # rewrites `className` mid-drop and wipes the classes `slide-drag.js` sets
        class_name="q-cr-slide q-cr-slide--drag",
        tab_index=0,
        overflow="hidden",
    )


def _carousel_strip() -> rx.Component:
    """The gallery as Instagram will show it (§ 2026-10-14): its three slides in order,
    across the whole view, dragged onto one another to reorder them."""
    return rx.grid(
        rx.foreach(CreativeState.carousel_slide_rows, _strip_thumb),
        _script_on_mount(_SLIDE_DRAG_JS),
        columns="3",
        spacing="4",
        width="100%",
        role="list",
        aria_label="Diapositivas de la galería",
    )


def _slide_photo() -> rx.Component:
    """The open slide's product photo (§ 2026-10-14): none by default; picked among the
    catalog product's photos, uploaded or taken from a piece — the same tile again
    takes it off, and without one the scene comes from its words alone."""
    current = CreativeState.carousel_current
    return _slide_panel(
        _label_with_help(
            "Foto del producto",
            "Foto del producto",
            "La foto que la IA usa de referencia para que tu producto salga igual (forma, "
            "colores, etiqueta): del catálogo, subida o de una publicación que ya hiciste. Si no "
            "eliges ninguna, la escena se crea solo con tu descripción.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.vstack(
            rx.cond(
                current["photo_key"] != "",
                rx.hstack(
                    _clip_thumb(current["photo_key"], size="6rem"),
                    rx.vstack(
                        rx.text(current["photo_name"], size="2"),
                        rx.button(
                            rx.icon("x", size=12),
                            "Quitar",
                            variant="ghost",
                            color_scheme="gray",
                            size="1",
                            on_click=CreativeState.clear_slide_photo,
                        ),
                        spacing="1",
                        align_items="start",
                    ),
                    spacing="3",
                    align="end",
                ),
                _picker_note("Sin foto: la escena se crea solo con tu descripción."),
            ),
            _media_picker(
                "slide",
                rx.box(
                    _upload_zone(
                        "creative_slide_photo",
                        "Arrastra la foto o haz clic",
                        CreativeState.handle_slide_photo_upload,
                        multiple=False,
                    ),
                    width="100%",
                    max_width="20rem",
                ),
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        width="100%",
    )


def _slide_reference_thumb(key: rx.Var[str]) -> rx.Component:
    """The motion reference held: a piece by its poster, an inspiration or catalog video
    by its first frame (a stock one plays from R2, `_product_video_src`)."""
    return rx.cond(
        CreativeState.piece_views.contains(key),
        _slide_thumb(CreativeState.piece_views[key].to(str), rx.Var.create("video"), "4.5rem"),
        _video_thumb(_product_video_src(key)),
    )


def _slide_media() -> rx.Component:
    """An animated slide's files (§ request 2026-10-20: «cuando se quiera un video se
    junten … videos e imágenes»): ONE picker where every tab shows images and videos
    together — an image is the product photo the scene is generated from, a video the
    motion reference the animation follows (never shown in the gallery). One of each."""
    current = CreativeState.carousel_current
    photo = rx.hstack(
        _removable(
            _clip_thumb(current["photo_key"]), CreativeState.clear_slide_photo, "Quitar foto"
        ),
        rx.vstack(
            rx.text("Foto del producto", size="1", weight="medium"),
            rx.text(current["photo_name"], size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
        ),
        spacing="2",
        align="center",
    )
    reference = rx.hstack(
        _removable(
            _slide_reference_thumb(current["ref_key"]),
            CreativeState.clear_slide_reference,
            "Quitar video",
        ),
        rx.vstack(
            rx.text("Video de referencia", size="1", weight="medium"),
            rx.text(current["ref_name"], size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
        ),
        spacing="2",
        align="center",
    )
    return _slide_panel(
        _label_with_help(
            "Imágenes y video",
            "Imágenes y video",
            "Elige una foto y, si quieres, un video, de donde estén: tu catálogo, tu "
            "inspiración, tus publicaciones o subidos. La foto es la referencia para que tu "
            "producto salga igual; el video, el movimiento de cámara y el ritmo que sigue "
            "la animación (no aparece en la galería).",
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.vstack(
            rx.cond(
                (current["photo_key"] != "") | (current["ref_key"] != ""),
                rx.flex(
                    rx.cond(current["photo_key"] != "", photo),
                    rx.cond(current["ref_key"] != "", reference),
                    wrap="wrap",
                    spacing="4",
                ),
                _picker_note("Sin foto ni video: la escena se crea solo con tu descripción."),
            ),
            _mixed_media_picker(
                "slide_media",
                rx.box(
                    _clip_drop(
                        "creative_slide_media",
                        "Arrastra una foto y/o un video, o haz clic",
                        "JPG, PNG o WEBP · MP4 o MOV hasta 200 MB",
                        {**_CLIP_IMAGE_ACCEPT, **_CLIP_VIDEO_ACCEPT},
                        CreativeState.handle_slide_media_upload,
                        max_files=2,
                    ),
                    width="100%",
                    max_width="20rem",
                ),
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        width="100%",
    )


def _slide_panel(label: rx.Component, control: rx.Component, **props: object) -> rx.Component:
    """One block of the slide editor, visibly apart from its neighbours (§ request
    2026-10-09: "quiero separaciones"): its own raised panel with a border and padding —
    a hairline separator was invisible on the dark theme."""
    return rx.box(
        rx.vstack(label, control, spacing="2", align_items="start", width="100%"),
        padding="0.75rem 0.9rem",
        class_name="q-cr-tray",
        **props,
    )


def _slide_generated_fields() -> rx.Component:
    """The open generated or animated slide: its photo, what it shows, whether it uses
    the common background, its words and — a video — its length. One panel each."""
    current = CreativeState.carousel_current
    index = CreativeState.carousel_selected
    animated = current["source"] == "animated"
    muted = {"size": "1", "color": T.TEXT_MUTED}
    what_it_shows = _slide_panel(
        rx.text("¿Qué muestra?", **muted),
        rx.vstack(
            rx.input(
                value=current["scene"],
                on_change=lambda value: CreativeState.set_slide_field(index, "scene", value),
                placeholder="La hamburguesa de cerca, con el queso derritiéndose",
                max_length=600,
                width="100%",
            ),
            rx.cond(
                CreativeState.media_background_key != "",
                rx.hstack(
                    rx.switch(
                        checked=current["background"] != "",
                        on_change=lambda _: CreativeState.toggle_slide_background(index),
                        size="1",
                    ),
                    rx.text("Usar el fondo común", size="1"),
                    spacing="2",
                    align="center",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        width="100%",
    )
    # § 2026-10-14: only the title — the hook — and on one slide (it is the same words
    # on every slide); the «Botón de acción» left, the scene already holds the button
    text = _slide_panel(
        rx.hstack(
            rx.text("Título", **muted),
            _help("Título", _SLIDE_TEXT_HELP),
            spacing="1",
            align="center",
        ),
        rx.hstack(
            rx.switch(
                checked=current["text"] == "hook",
                on_change=lambda _: CreativeState.toggle_slide_title(index),
                size="2",
            ),
            rx.text("Poner el gancho encima de esta diapositiva", size="2"),
            spacing="2",
            align="center",
        ),
        width="100%",
    )
    length = _slide_panel(
        rx.text("Duración", **muted),
        rx.vstack(
            rx.segmented_control.root(
                *_seconds_items(SLIDE_SECONDS),
                value=current["seconds"],
                on_change=lambda value: CreativeState.set_slide_field(index, "seconds", value),
                size="2",
                width="100%",
                class_name="q-seg-fit q-seg-fit--nowrap",
            ),
            # § request 2026-10-23: the gallery's video may bring its sound — off by default
            _audio_switch(
                checked=current["audio"] != "",
                on_change=lambda _: CreativeState.toggle_slide_audio(index),
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )
    # § 2026-10-14: everything under the slides, across the whole view — the photo,
    # what it shows, then its text beside its length (a phone stacks them). An animated
    # slide takes its photo and its motion video from ONE picker (§ request 2026-10-20)
    return rx.vstack(
        rx.cond(animated, _slide_media(), _slide_photo()),
        what_it_shows,
        rx.grid(
            text,
            rx.cond(animated, length),
            columns=rx.cond(
                animated,
                rx.breakpoints(initial="1", sm="2"),
                "1",
            ),
            spacing="4",
            width="100%",
        ),
        spacing="4",
        width="100%",
        align_items="stretch",
    )


def _slide_kind_picker() -> rx.Component:
    """The open slide's kind (§ 2026-10-14: «que se pueda cambiar el tipo de
    diapositiva»): a generated scene, that scene animated — the gallery's one video — or
    a piece already made."""
    source = CreativeState.carousel_current["source"]
    return rx.grid(
        _choice_card(
            "Imagen generada",
            "Una escena nueva con tu producto.",
            "image",
            selected=source == "generated",
            on_click=CreativeState.set_slide_source("generated"),
            compact=True,
            help_text=(
                "Creamos una escena nueva con IA a partir de la foto de tu producto (y "
                "tu fondo, si lo usas). Encima va el texto que elijas y tu logo."
            ),
        ),
        rx.cond(
            CreativeState.carousel_video_taken & (source != "animated"),
            choice_card(
                rx.hstack(
                    rx.icon("clapperboard", size=T.ICON_MD, color=T.TEXT_FAINT),
                    rx.vstack(
                        rx.text("Video animado", size="2", weight="medium"),
                        rx.text("Ya hay un video en la galería.", size="1", color=T.TEXT_MUTED),
                        spacing="1",
                        align_items="start",
                    ),
                    spacing="3",
                    align="start",
                ),
                selected=False,
                disabled=True,
                padding="0.65rem 0.85rem",
                width="100%",
            ),
            _choice_card(
                "Video animado",
                "La escena en movimiento. Solo uno por galería.",
                "clapperboard",
                selected=source == "animated",
                on_click=CreativeState.set_slide_source("animated"),
                compact=True,
                help_text=(
                    "Generamos la escena y la animamos en un video corto de 5 o 10 segundos, "
                    "sin voz ni música. Una galería lleva como máximo un video."
                ),
            ),
        ),
        _choice_card(
            "De una publicación",
            "Una imagen o un video que ya hiciste.",
            "library",
            selected=source == "existing",
            on_click=CreativeState.set_slide_source("existing"),
            compact=True,
            help_text=(
                "Reutiliza una imagen o un video de una publicación que ya hiciste con esta "
                "marca. Se usa tal cual, recortado al formato de la publicación, sin texto "
                "nuevo."
            ),
        ),
        columns=rx.breakpoints(initial="1", sm="2"),
        spacing="2",
        width="100%",
        role="radiogroup",
        aria_label="Tipo de diapositiva",
    )


def _slide_editor() -> rx.Component:
    """The slide open in the strip: its number and kind, moving it left or right,
    removing it, and its own inputs — a reused piece shows what it reuses."""
    current = CreativeState.carousel_current
    index = CreativeState.carousel_selected
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text("Diapositiva ", current["n"], size="2", weight="bold"),
                rx.text("·", size="2", color=T.TEXT_FAINT),
                _slide_source_icon(current["source"]),
                rx.text(_slide_source_label(current["source"]), size="2"),
                rx.spacer(),
                _slide_icon_button(
                    "chevron-left",
                    "Mover a la izquierda",
                    CreativeState.move_carousel_slide(index, -1),
                    disabled=current["first"] != "",
                ),
                _slide_icon_button(
                    "chevron-right",
                    "Mover a la derecha",
                    CreativeState.move_carousel_slide(index, 1),
                    disabled=current["last"] != "",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            _slide_panel(
                rx.text("Tipo de diapositiva", size="1", color=T.TEXT_MUTED),
                _slide_kind_picker(),
                width="100%",
            ),
            rx.cond(
                CreativeState.carousel_notice != "",
                callout(CreativeState.carousel_notice, "warn"),
            ),
            rx.cond(CreativeState.piece_picker_open, _piece_picker()),
            rx.box(class_name="q-cr-rule"),
            rx.cond(
                current["source"] == "existing",
                rx.hstack(
                    _slide_thumb(current["view"], current["media_type"], size="5rem"),
                    rx.vstack(
                        rx.text(current["label"], size="2"),
                        rx.text(
                            rx.cond(current["media_type"] == "video", "Video", "Imagen"),
                            " · se usa tal cual, ajustada al formato",
                            size="1",
                            color=T.TEXT_MUTED,
                        ),
                        spacing="0",
                        align_items="start",
                    ),
                    spacing="3",
                    align="center",
                ),
                rx.cond(
                    current["source"] == "stock",
                    _slide_stock_fields(),
                    _slide_generated_fields(),
                ),
            ),
            spacing="4",
            width="100%",
            align_items="stretch",
        ),
        padding="1rem 1.15rem",
        class_name="q-cr-editor",
        width="100%",
    )


def _piece_tile(item: rx.Var) -> rx.Component:
    return rx.vstack(
        _slide_thumb(item["view"], item["media_type"], size="5rem"),
        rx.text(
            item["label"],
            size="1",
            color=T.TEXT_MUTED,
            max_width="5rem",
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
        ),
        spacing="1",
        align="center",
        on_click=CreativeState.pick_piece(item["key"]),
        role="button",
        aria_label=item["label"],
        cursor="pointer",
    )


def _piece_picker() -> rx.Component:
    """«De una pieza»: the images and videos the brand already made, the newest first."""
    return rx.vstack(
        rx.text("Elige una imagen o un video de tus publicaciones", size="1", weight="medium"),
        rx.cond(
            CreativeState.pieces_loading,
            rx.text("Cargando tus publicaciones…", size="1", color=T.TEXT_MUTED),
            rx.cond(
                CreativeState.piece_items.length() > 0,
                rx.flex(
                    rx.foreach(CreativeState.piece_items, _piece_tile),
                    wrap="wrap",
                    spacing="2",
                    max_height="16rem",
                    overflow_y="auto",
                    width="100%",
                ),
                rx.text(
                    "Aún no tienes publicaciones con imágenes o videos.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
        padding="0.75rem",
        class_name="q-cr-tray q-cr-tray--dashed",
    )


def _carousel_section() -> rx.Component:
    """The gallery (ex-carrusel; § 2026-10-14): one common background, then its three
    slides — dragged to reorder, a click opens one in the editor below, where its kind
    changes. One video at most; no closing slide."""
    return rx.vstack(
        _background_upload(
            "Fondo común (opcional)",
            "Arrastra la foto de tu local o del fondo; cada diapositiva elige si lo usa",
            help_text=(
                "Una foto de tu local o del lugar donde quieres ver tu producto. Sirve para "
                "toda la galería: en cada diapositiva decides si se usa."
            ),
        ),
        _upload_error(),
        rx.divider(),
        _field_label(
            "Diapositivas",
            "Son 3. Arrástralas para cambiar el orden (en el celular, mantén presionada "
            "una) y tócalas para editarlas abajo. Máximo 1 video.",
        ),
        _carousel_strip(),
        rx.cond(CreativeState.carousel_slides.length() > 0, _slide_editor()),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _carousel_result() -> rx.Component:
    """The carousel: its slides as Instagram shows them, then the post's text."""
    return _media_result(_post_text(), title="Galería", icon="gallery-horizontal-end")


def _ad_image_section() -> rx.Component:
    """The advertising image: the scene, generated by Seedream (§ 2026-10-07) with the
    operator's product and/or background as references when they upload them — both
    optional since 2026-10-12, no picker: whatever is uploaded is used (`AdImageMode`
    derived in the state); the words and the logo are set on top. Its scene is asked in
    «Contexto», like every option's context (§ request 2026-10-20)."""
    return rx.vstack(
        _background_upload("Foto del fondo (opcional)", "Arrastra la foto de tu local o del fondo"),
        _products_upload("Foto del producto (opcional)"),
        _upload_error(),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _voice_select() -> rx.Component:
    """The voice that reads the script (§ 2026-10-16, OmniHuman + Seed Speech): the
    brand's own cloned voice first when it is ready, then the public voices of one
    gender. With a woman or a man presenter the gender follows it; with a custom or
    animated presenter the operator picks it here."""
    voice_follows_avatar = (CreativeState.brief_kind == "avatar_video") & (
        CreativeState.human_avatar_mode != "custom"
    )
    return rx.vstack(
        rx.hstack(
            rx.text("Voz", size="2", weight="medium"),
            rx.cond(
                voice_follows_avatar,
                rx.text(
                    rx.cond(CreativeState.voice_gender == "female", "· de mujer", "· de hombre"),
                    size="2",
                    color=T.TEXT_MUTED,
                ),
            ),
            spacing="1",
        ),
        rx.cond(
            ~voice_follows_avatar,
            rx.segmented_control.root(
                rx.segmented_control.item("Femenina", value="female"),
                rx.segmented_control.item("Masculina", value="male"),
                value=CreativeState.voice_gender,
                on_change=CreativeState.set_voice_gender,
                size="2",
            ),
        ),
        rx.select.root(
            rx.select.trigger(placeholder="Elige la voz", width="100%"),
            rx.select.content(
                rx.foreach(
                    CreativeState.visible_voices,
                    lambda voice: rx.select.item(voice["name"], value=voice["id"]),
                ),
            ),
            value=CreativeState.voice_id,
            on_change=CreativeState.set_voice_id,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _avatar_section() -> rx.Component:
    """The presenter — a described woman or man, or a custom person (human avatar); or
    an animated character, described or animated from the operator's image — and, on
    OmniHuman (§ 2026-10-16), the voice that reads the script."""
    custom = rx.vstack(
        rx.text_area(
            value=CreativeState.human_avatar_prompt,
            on_change=CreativeState.set_human_avatar_prompt,
            placeholder=(
                "Describe a la persona: mujer de unos 30 años, pelo rizado castaño, blusa "
                "verde, sonriente, en una cocina luminosa…"
            ),
            width="100%",
            rows="3",
            max_length=600,
        ),
        rx.text(
            "Creamos una persona sintética (no es nadie real) para el video.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )
    animated = rx.vstack(
        rx.text("Personaje", size="2", weight="medium"),
        rx.segmented_control.root(
            rx.segmented_control.item("Generado por IA", value="ai"),
            rx.segmented_control.item("Desde una imagen", value="image"),
            value=CreativeState.avatar_source,
            on_change=CreativeState.set_avatar_source,
        ),
        rx.cond(
            CreativeState.avatar_source == "ai",
            rx.text_area(
                value=CreativeState.avatar_prompt,
                on_change=CreativeState.set_avatar_prompt,
                placeholder=(
                    "Describe al personaje: una hamburguesa sonriente con gorra roja, "
                    "un chef bigotón con delantal verde…"
                ),
                width="100%",
                rows="3",
                max_length=600,
            ),
            rx.vstack(
                rx.cond(
                    CreativeState.avatar_image_key != "",
                    _file_chip(CreativeState.avatar_image_name, CreativeState.clear_avatar_image),
                    _upload_zone(
                        "creative_avatar",
                        "Sube la imagen del personaje (tu mascota, una ilustración)",
                        CreativeState.handle_avatar_upload,
                        multiple=False,
                    ),
                ),
                _brand_media_picker(
                    CreativeState.brand_media_choices,
                    "avatar",
                    CreativeState.use_brand_avatar_image,
                    "O elige de tu marca",
                ),
                rx.checkbox(
                    "Tengo derecho a animar esta imagen (no es la foto de una persona real "
                    "sin su permiso).",
                    checked=CreativeState.avatar_rights_confirmed,
                    on_change=CreativeState.set_avatar_rights_confirmed,
                    size="2",
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )
    human = rx.vstack(
        rx.text("Presentador", size="2", weight="medium"),
        rx.segmented_control.root(
            rx.segmented_control.item("Mujer", value="female"),
            rx.segmented_control.item("Hombre", value="male"),
            rx.segmented_control.item("Personalizado", value="custom"),
            value=CreativeState.human_avatar_mode,
            on_change=CreativeState.set_human_avatar_mode,
            size="2",
        ),
        rx.cond(
            CreativeState.human_avatar_mode == "custom",
            custom,
            rx.text(
                "Una persona sintética (no es nadie real) generada con IA para tu video. Si "
                "quieres elegir cómo se ve, usa «Personalizado».",
                size="1",
                color=T.TEXT_MUTED,
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )
    voice = rx.cond(
        CreativeState.voices_loading,
        rx.hstack(
            loading_spinner("sm"),
            rx.text("Cargando las voces…", size="2", color=T.TEXT_MUTED),
            spacing="2",
            align="center",
        ),
        rx.cond(
            CreativeState.voices_error != "",
            callout(CreativeState.voices_error, "warn"),
            _voice_select(),
        ),
    )
    return rx.vstack(
        rx.cond(CreativeState.brief_kind == "avatar_video", human, animated),
        rx.cond(
            CreativeState.video_reads_with_voice,
            rx.vstack(
                voice,
                _subtitles_switch(),
                callout(
                    "Tu presentador dice el guion con la voz elegida, con los labios "
                    "sincronizados. Hasta un minuto de guion; el video tarda unos minutos.",
                    "info",
                ),
                spacing="4",
                width="100%",
                align_items="start",
            ),
            callout(
                "El video se arma con tu presentador, tus productos y tu fondo. Por ahora sale "
                "sin voz y dura como máximo 12 s: el guion queda en el texto de la publicación.",
                "info",
            ),
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _subtitles_switch() -> rx.Component:
    """Subtitles of what the presenter says (m-24828920), on or off for this video."""
    return rx.vstack(
        rx.hstack(
            rx.switch(
                checked=CreativeState.media_subtitles,
                on_change=CreativeState.set_media_subtitles,
            ),
            rx.text("Subtítulos", size="2"),
            spacing="2",
            align="center",
        ),
        rx.text(
            "Lo que dice el presentador, escrito en el video con la tipografía y los colores "
            "de tu marca.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _script_source() -> rx.Component:
    """Claude writes the script to the chosen length, or the operator writes it and the
    avatar reads it word for word."""
    return rx.vstack(
        # UX review (N12): the text toggles the switch too, a ≥ 44 px target with a name
        rx.el.label(
            rx.hstack(
                rx.switch(
                    checked=CreativeState.own_script_on,
                    on_change=CreativeState.set_own_script_on,
                    aria_label="Escribir mi propio guion",
                ),
                rx.text("Escribir mi propio guion", size="2"),
                spacing="2",
                align="center",
                min_height="44px",
            ),
            cursor="pointer",
        ),
        rx.cond(
            CreativeState.own_script_on,
            rx.text_area(
                value=CreativeState.own_script,
                on_change=CreativeState.set_own_script,
                placeholder="Lo que va a decir el avatar, palabra por palabra.",
                width="100%",
                rows="5",
                max_length=2000,
            ),
            _duration_select(),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _seconds_items(values: tuple[str, ...]) -> list[rx.Component]:
    """A duration control's options, «15 s»: number and unit joined by a no-break space,
    so a phone-width segment never splits them over two lines (m-24820845)."""
    return [rx.segmented_control.item(f"{s}\u00a0s", value=s) for s in values]


def _duration_select() -> rx.Component:
    """The avatar's length when Claude writes the script. The label sits above the
    control, as in `_field`, so the control has the full width and a phone never splits
    «15 s» over two lines (m-24820845)."""
    return rx.vstack(
        rx.text("Duración", size="2", weight="medium"),
        # CREAR-5: a presenter offers only the lengths the month still pays for
        rx.segmented_control.root(
            rx.foreach(
                CreativeState.duration_choices,
                lambda s: rx.segmented_control.item(s + "\u00a0s", value=s),
            ),
            value=CreativeState.media_duration,
            on_change=CreativeState.set_media_duration,
            class_name="q-seg-fit q-seg-fit--nowrap",
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _field(label: str, control: rx.Component, hint: str | None = None) -> rx.Component:
    return rx.vstack(
        _field_label(label, hint),
        control,
        spacing="2",
        width="100%",
        align_items="start",
    )


# -- the sections (§ request 2026-10-08: one view with numbered sections replaced the
# step-by-step wizard). Which sections a kind shows: `creative_state.generator_sections`.


def _section(
    key: str,
    title: str | rx.Var,
    subtitle: str | rx.Var,
    *body: rx.Component,
) -> rx.Component:
    """One section: its title and help, then its fields. It is the body of its own view
    since 2026-10-14 (the view's card frames it and the step bar numbers it); shown only
    when the chosen kind uses it."""
    return rx.cond(
        CreativeState.gen_sections.contains(key),
        rx.vstack(
            rx.vstack(
                rx.heading(title, size="4", as_="h3"),
                rx.text(subtitle, size="1", color=T.TEXT_MUTED),
                spacing="0",
                align_items="start",
            ),
            *body,
            spacing="4",
            width="100%",
            align_items="start",
        ),
    )


_CATALOG_HOVER_JS = _asset_script("catalog-hover.js")


def _catalog_card(item: rx.Var[dict[str, str]]) -> rx.Component:
    """«Mi catálogo»: one product as a large card (§ request 2026-10-19, option A) — its
    photo big with what it has in the corner, the name and a check under it, no price.
    On hover its other photos follow one another (`assets/catalog-hover.js`), the dots
    under the name marking which."""
    selected = CreativeState.selected_product_id == item["id"]
    photos = item["photo_keys"].to(str).split("\n")
    return rx.box(
        choice_card(
            rx.box(
                rx.cond(
                    item["photo_key"] != "",
                    rx.foreach(
                        photos,
                        lambda key, i: rx.image(
                            src=rx.get_upload_url(key),
                            alt=item["name"],
                            loading="lazy",
                            class_name=rx.cond(i == 0, "q-cr-cat-photo is-on", "q-cr-cat-photo"),
                        ),
                    ),
                    rx.center(rx.icon("image-off", size=22, color=T.TEXT_FAINT), height="100%"),
                ),
                rx.cond(
                    item["counts_label"] != "",
                    rx.text(item["counts_label"], class_name="q-cr-mark q-cr-cat-count"),
                ),
                class_name="q-cr-cat-photos",
            ),
            rx.hstack(
                rx.text(
                    item["name"],
                    size="2",
                    weight="medium",
                    white_space="nowrap",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    min_width="0",
                ),
                rx.spacer(),
                rx.cond(
                    selected,
                    rx.icon("circle-check", size=T.ICON_SM, color=T.tone_color("accent", 11)),
                ),
                align="center",
                width="100%",
                padding="0.45rem 0.25rem 0.2rem",
            ),
            rx.cond(
                photos.length() > 1,
                rx.hstack(
                    rx.foreach(
                        photos,
                        lambda _, i: rx.box(
                            class_name=rx.cond(i == 0, "q-cr-cat-dot is-on", "q-cr-cat-dot")
                        ),
                    ),
                    spacing="1",
                    padding="0 0.25rem 0.25rem",
                ),
            ),
            key=item["id"],
            selected=selected,
            on_select=CreativeState.choose_product(item["id"]),
            padding="0.3rem",
            width="100%",
            aria_label=item["name"],
        ),
        class_name="q-cr-cat-card",
        width="100%",
    )


def _section_topic() -> rx.Component:
    # § request 2026-10-06: not a topic or a product name — the general context of what
    # the operator wants, in their own words. Objetivo was asked here until 2026-10-05;
    # the brief keeps `brief_objective` at its default.
    # § request 2026-10-20: the second-to-last view of every option (after «Datos
    # clave»); the flyer's context is its scene, asked here too since that day
    flyer = CreativeState.brief_kind == "static_flyer"
    return _section(
        "topic",
        rx.match(
            CreativeState.gen_category,
            ("script", "¿Qué quieres en el guion?"),
            ("image", "Describe la escena"),
            ("template", "¿Qué quieres en la publicación?"),
            ("carousel", "¿De qué trata la galería?"),
            ("clip", "¿Qué quieres en el clip?"),
            "¿Qué quieres en el video?",
        ),
        rx.cond(
            flyer,
            "Qué se ve, dónde y cómo se siente. Es lo único obligatorio.",
            "Un contexto general: de qué trata, qué debe transmitir, a quién le habla y "
            "cualquier detalle que importe. Es lo único obligatorio.",
        ),
        rx.cond(
            flyer,
            rx.text_area(
                value=CreativeState.ad_scene_prompt,
                on_change=CreativeState.set_ad_scene_prompt,
                placeholder=(
                    "Una mano sosteniendo el vaso a la altura del pecho, la etiqueta de "
                    "frente, con el local desenfocado detrás y luz cálida…"
                ),
                width="100%",
                rows="5",
                max_length=600,
            ),
            rx.text_area(
                value=CreativeState.brief_topic,
                on_change=CreativeState.set_brief_topic,
                placeholder=(
                    "Ej.: quiero mostrar nuestra hamburguesa doble con papas, en promo solo "
                    "este fin de semana. Que se sienta antojable y cercano, para gente joven "
                    "que pide a domicilio, y que cierre invitando a pedir por WhatsApp."
                ),
                width="100%",
                rows="7",
            ),
        ),
        _context_ai_tools(),
    )


def _context_ai_tools() -> rx.Component:
    """«Potenciar con IA» (§ request 2026-10-20): the text above rewritten into a fuller
    brief with the Brand Kit and the «Datos clave» — no invented facts — before anything
    is generated; «Deshacer» brings the operator's own words back."""
    enhancing = CreativeState.context_enhancing
    return rx.vstack(
        rx.hstack(
            rx.button(
                rx.icon("sparkles", size=T.ICON_SM),
                rx.cond(enhancing, "Mejorando…", "Mejorar mi texto"),
                variant="soft",
                size="2",
                radius=_CONTROL_RADIUS,
                loading=enhancing,
                on_click=CreativeState.enhance_context,
            ),
            rx.cond(
                (CreativeState.context_before_enhance != "") & ~enhancing,
                rx.button(
                    rx.icon("undo-2", size=T.ICON_SM),
                    "Deshacer",
                    variant="ghost",
                    color_scheme="gray",
                    size="2",
                    on_click=CreativeState.undo_enhance_context,
                ),
            ),
            rx.text(
                "Ordenamos tu texto con lo que sabemos de tu marca, sin inventar precios ni "
                "promociones. Revísalo antes de crear.",
                size="1",
                color=T.TEXT_MUTED,
                flex="1",
                min_width="12rem",
            ),
            spacing="3",
            align="center",
            wrap="wrap",
            width="100%",
        ),
        rx.cond(
            CreativeState.context_enhance_error != "",
            callout(CreativeState.context_enhance_error, "warn"),
        ),
        rx.cond(
            CreativeState.context_enhance_note != "",
            callout(CreativeState.context_enhance_note, "warn"),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _section_channel() -> rx.Component:
    # Destino was asked here until 2026-10-05; the brief keeps `brief_intent` at its
    # default.
    return _section(
        "channel",
        "¿Cómo la quieres?",
        "El formato en que sale. Ya elegimos uno por ti; cámbialo si quieres.",
        _field(
            "Tipo de publicación",
            rx.select.root(
                rx.select.trigger(width="100%"),
                rx.select.content(
                    rx.foreach(
                        CreativeState.content_type_choices,
                        lambda pair: rx.select.item(pair[1], value=pair[0]),
                    ),
                ),
                value=CreativeState.brief_content_type,
                on_change=CreativeState.set_content_type,
            ),
        ),
        # UX review (N12): one option per line, so a long name such as «Reel (video
        # corto) 9:16» never pushes the screen sideways at 360 px
        _field(
            "Formato",
            rx.radio_group.root(
                rx.foreach(
                    CreativeState.format_options,
                    lambda option: rx.radio_group.item(
                        option[1], value=option[0], min_height="44px"
                    ),
                ),
                value=CreativeState.effective_format,
                on_change=CreativeState.set_brief_format,
                size="3",
                aria_label="Formato",
            ),
        ),
        # § request 2026-10-14: the script's length is asked here, with the format
        rx.cond(
            CreativeState.brief_kind == "creator_script",
            _field(
                "Duración",
                rx.segmented_control.root(
                    *_seconds_items(DURATIONS),
                    value=CreativeState.media_duration,
                    on_change=CreativeState.set_media_duration,
                    size="2",
                    class_name="q-seg-fit q-seg-fit--nowrap",
                ),
            ),
        ),
        # § request 2026-10-23: a clip's length, from 5 s up to 15 s
        rx.cond(
            CreativeState.brief_kind == "clip",
            _field(
                "Duración",
                # CREAR-5 v2: only the lengths the month can pay for
                rx.segmented_control.root(
                    rx.foreach(
                        CreativeState.clip_duration_choices,
                        lambda s: rx.segmented_control.item(s + "\u00a0s", value=s),
                    ),
                    value=CreativeState.clip_duration,
                    on_change=CreativeState.set_clip_duration,
                    size="2",
                    class_name="q-seg-fit q-seg-fit--nowrap",
                ),
            ),
        ),
        # The clip's «Con sonido» (§ request 2026-10-23) is behind «Más opciones» in
        # `_step_how` (UX review 2026-10-24, finding 4).
    )


#: What «Con sonido» adds (§ request 2026-10-23; wording from the UX review 2026-10-24,
#: finding 4 — no line about models that make no sound: a kind that cannot bring sound
#: does not show the switch).
_AUDIO_HINT = "Sonido de ambiente y voces, creados junto con el video."


def _audio_switch(*, checked: object, on_change: object) -> rx.Component:
    """«Con sonido»: the sound the video model makes with the video (clip and the
    gallery's animated slide)."""
    return rx.vstack(
        # UX review (N12): the text toggles the switch too, a ≥ 44 px target with a name
        rx.el.label(
            rx.hstack(
                rx.switch(checked=checked, on_change=on_change, size="2", aria_label="Con sonido"),
                rx.text("Con sonido", size="2"),
                spacing="2",
                align="center",
                min_height="44px",
            ),
            cursor="pointer",
        ),
        rx.text(_AUDIO_HINT, size="1", color=T.TEXT_MUTED),
        spacing="1",
        width="100%",
    )


def _section_presenter() -> rx.Component:
    """The two avatar kinds only: who presents the video (and, on OmniHuman, with
    which voice)."""
    return _section(
        "presenter",
        "¿Quién lo presenta?",
        rx.cond(
            CreativeState.video_reads_with_voice,
            "El presentador y la voz que va a leer el guion.",
            "Cómo es la persona o el personaje que aparece en el video.",
        ),
        _avatar_section(),
    )


def _template_details() -> rx.Component:
    """The template kind: the catalog product's photos already count; the operator may
    add more for THIS piece (the template takes 2 to 4)."""
    return rx.vstack(
        # § 2026-10-13: no «Sin producto del catálogo» note — only what the piece uses
        rx.cond(
            CreativeState.selected_product_id != "",
            callout(
                rx.text(
                    rx.cond(
                        CreativeState.product_source == "stock",
                        rx.fragment(
                            "Inspiración: ",
                            rx.text.strong(CreativeState.stock_inspiration_label),
                        ),
                        rx.fragment(
                            "Del catálogo: ", rx.text.strong(CreativeState.brief_product_ref)
                        ),
                    ),
                    rx.cond(
                        CreativeState.template_photo_count == 1,
                        " · 1 foto",
                        rx.text.span(" · ", CreativeState.template_photo_count, " fotos"),
                    ),
                    size="2",
                ),
                "info",
                icon="package",
            ),
        ),
        _products_upload("Fotos de la publicación"),
        _upload_error(),
        spacing="3",
        width="100%",
        align_items="start",
    )


#: Title + help of the kind's own section.
_DETAILS_HEADINGS: dict[str, tuple[str, str]] = {
    "creator_script": (
        "El guion",
        "Generamos lo que dice la persona, toma por toma, y el texto de la publicación.",
    ),
    "static_flyer": ("El anuncio", "Con qué fotos y qué escena armamos la imagen."),
    "template": ("Tus fotos", "Necesita al menos 2 fotos; las del catálogo ya cuentan."),
    "carousel": (
        "Las diapositivas",
        "Imágenes generadas, videos animados o publicaciones que ya hiciste, en el orden "
        "en que salen.",
    ),
    "video": ("El fondo", "Qué se ve detrás del avatar y, si quieres, un video de referencia."),
    "clip": (
        "Fotogramas",
        "La imagen con la que empieza el clip y, si quieres, con la que termina.",
    ),
}


def _details_heading(index: int) -> rx.Var[str]:
    return rx.match(
        CreativeState.brief_kind,
        ("creator_script", _DETAILS_HEADINGS["creator_script"][index]),
        ("static_flyer", _DETAILS_HEADINGS["static_flyer"][index]),
        ("template", _DETAILS_HEADINGS["template"][index]),
        ("carousel", _DETAILS_HEADINGS["carousel"][index]),
        ("clip", _DETAILS_HEADINGS["clip"][index]),
        _DETAILS_HEADINGS["video"][index],
    )


def _section_details() -> rx.Component:
    """What the chosen kind takes beyond the brief (the presenter has its own section),
    and the brand's own resources for any kind."""
    return _section(
        "details",
        _details_heading(0),
        _details_heading(1),
        rx.match(
            CreativeState.brief_kind,
            ("static_flyer", _ad_image_section()),
            ("template", _template_details()),
            ("carousel", _carousel_section()),
            rx.vstack(
                # CREAR-2: the script is asked in step 2, «Qué decir»
                _field_label(
                    "Fondo y productos",
                    "Se componen en una sola imagen detrás del avatar.",
                ),
                _images_section(),
                # § request 2026-10-20: no «Referencia» view of its own for an avatar; UX
                # review (N6): it and the brand resources are folded under «Más opciones»
                rx.divider(),
                _more_options(
                    CreativeState.show_more_open,
                    CreativeState.toggle_show_more,
                    "Un video de referencia y tus fotos de marca. Puedes crear sin tocarlos.",
                    rx.vstack(
                        _field_label("Video de referencia (opcional)", _REFERENCE_HINT),
                        _reference_body(),
                        rx.cond(CreativeState.brand_media_items.length() > 0, rx.divider()),
                        _brand_resources(),
                        spacing="4",
                        align_items="start",
                        width="100%",
                    ),
                ),
                spacing="4",
                align_items="start",
                width="100%",
            ),
        ),
        # a real creator's script takes no brand resources (§ request 2026-10-08): they
        # record with whatever they have
        # nor does a clip here: it takes only a logo, in its own «Referencias» view
        # (§ request 2026-10-20)
        # an avatar's are behind its «Más opciones», above
        rx.cond(
            (CreativeState.brief_kind != "creator_script")
            & (CreativeState.brief_kind != "clip")
            & (CreativeState.gen_category != "video"),
            rx.fragment(
                rx.cond(CreativeState.brand_media_items.length() > 0, rx.divider()),
                _brand_resources(),
            ),
        ),
    )


def _highlight_field(
    label: str,
    field_id: str,
    control: rx.Component,
) -> rx.Component:
    """One labelled half of a «Datos clave» row (CREAR-6: a visible label, not only a
    placeholder)."""
    return rx.vstack(
        rx.el.label(label, html_for=field_id, class_name="q-cr-highlight-label"),
        control,
        spacing="1",
        width="100%",
        align_items="start",
    )


def _highlight_row(row: rx.Var[dict[str, str]], index: rx.Var[int]) -> rx.Component:
    """One fact of «Datos clave» (CREAR-6, m-24842980): «¿Qué dato?» and «¿Cuánto o
    cuál?», each with its label — side by side on a wide screen, one under the other on
    a phone (`.q-cr-highlight-row`) — and a ≥ 44 px «Quitar»."""
    key_id = f"q-cr-hl-key-{index}"
    value_id = f"q-cr-hl-value-{index}"
    return rx.hstack(
        rx.box(
            _highlight_field(
                "¿Qué dato?",
                key_id,
                rx.input(
                    id=key_id,
                    value=row["key"],
                    on_change=lambda value: CreativeState.set_highlight(index, "key", value),
                    placeholder="Ej.: precio, descuento, fecha",
                    max_length=40,
                    size="3",
                    width="100%",
                ),
            ),
            _highlight_field(
                "¿Cuánto o cuál?",
                value_id,
                rx.input(
                    id=value_id,
                    value=row["value"],
                    on_change=lambda value: CreativeState.set_highlight(index, "value", value),
                    placeholder="Ej.: 18.900, 20 %, viernes 31",
                    max_length=200,
                    size="3",
                    width="100%",
                ),
            ),
            class_name="q-cr-highlight-row",
            flex="1",
            min_width="0",
        ),
        rx.icon_button(
            rx.icon("x", size=16),
            on_click=CreativeState.remove_highlight(index),
            variant="ghost",
            color_scheme="gray",
            size="3",
            aria_label="Quitar este dato",
            flex_shrink="0",
        ),
        spacing="2",
        width="100%",
        align="end",
    )


def _phrase_chip(phrase: rx.Var[str], on_remove: rx.event.EventSpec) -> rx.Component:
    """A phrase of «Debe mencionar» / «Debe evitar» (CREAR-6): the chip itself only
    shows it — a tap to read it never removes it (UX review) — and the ✕ beside it, a
    ≥ 44 px target, removes it."""
    return rx.hstack(
        rx.el.span(phrase, class_name="q-rv-chip q-cr-phrase-chip"),
        rx.icon_button(
            rx.icon("x", size=16),
            on_click=on_remove,
            variant="ghost",
            color_scheme="gray",
            size="3",
            aria_label="Quitar «" + phrase + "»",
            flex_shrink="0",
        ),
        spacing="1",
        align="center",
    )


def _phrase_field(
    label: str,
    hint: str,
    items: rx.Var[list[str]],
    draft: rx.Var[str],
    on_change: rx.event.EventHandler,
    on_add: rx.event.EventHandler,
    on_key: rx.event.EventHandler,
    on_remove: object,
    placeholder: str,
) -> rx.Component:
    """«Debe mencionar» / «Debe evitar» (CREAR-6): one phrase per «Agregar» (or the
    keyboard's Intro / «Listo»), each a chip — never a single field «separado por
    comas». At `PHRASE_LIMIT` phrases the field and «Agregar» are off and the help says
    why (UX review)."""
    full = items.length() >= PHRASE_LIMIT
    return rx.vstack(
        rx.vstack(
            rx.text(label, size="2", weight="medium"),
            rx.text(rx.cond(full, PHRASE_LIMIT_HINT, hint), size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
        ),
        rx.cond(
            items.length() > 0,
            rx.flex(
                rx.foreach(items, lambda phrase: _phrase_chip(phrase, on_remove(phrase))),
                wrap="wrap",
                gap="2",
                width="100%",
            ),
        ),
        rx.hstack(
            rx.input(
                value=draft,
                on_change=on_change,
                on_key_down=on_key,
                enter_key_hint="done",
                placeholder=placeholder,
                max_length=80,
                size="3",
                flex="1",
                min_width="0",
                aria_label=label,
                disabled=full,
            ),
            rx.button(
                rx.icon("plus", size=T.ICON_SM),
                "Agregar",
                on_click=on_add,
                variant="soft",
                size="3",
                disabled=full | (draft.strip() == ""),
            ),
            spacing="2",
            width="100%",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _section_rules() -> rx.Component:
    """«Datos clave» (ex «Reglas», § request 2026-10-14 — and before «Contexto» now):
    the facts the piece must feature exactly — the price, a discount, a date… — as
    rows of name and value, or as one JSON object; then what it must say or avoid —
    CREAR-6: one labelled row per fact and one chip per phrase, never «separado por
    comas»; every control a ≥ 44 px target (`.q-cr-rules`)."""
    return rx.vstack(
        rx.vstack(
            rx.heading("Datos clave (opcional)", size="4", as_="h3"),
            rx.text(
                "Lo que la publicación tiene que destacar tal cual: el precio, un descuento, una "
                "fecha, un código… La IA los usa exactos, sin cambiarlos ni inventar otros.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            # CREAR-2: these facts never edit the brand
            rx.text(
                "Solo para esta publicación: tu marca no cambia.",
                size="1",
                weight="medium",
                color=T.TEXT_MUTED,
            ),
            spacing="0",
            align_items="start",
        ),
        rx.vstack(
            rx.foreach(CreativeState.brief_highlights, _highlight_row),
            rx.hstack(
                rx.button(
                    rx.icon("plus", size=T.ICON_SM),
                    "Agregar dato",
                    variant="soft",
                    color_scheme="gray",
                    size="2",
                    on_click=CreativeState.add_highlight,
                    disabled=CreativeState.brief_highlights.length() >= 12,
                ),
                spacing="2",
                wrap="wrap",
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        rx.divider(),
        _phrase_field(
            "Debe mencionar",
            "Escribe una frase y toca «Agregar». Para quitarla, toca la ✕.",
            CreativeState.brief_must_mention_items,
            CreativeState.brief_must_mention_draft,
            CreativeState.set_brief_must_mention_draft,
            CreativeState.add_must_mention,
            CreativeState.add_must_mention_on_key,
            CreativeState.remove_must_mention,
            "Ej.: envío gratis",
        ),
        _phrase_field(
            "Debe evitar",
            "Palabras o frases que no quieres en la publicación, una por vez. "
            "Para quitarla, toca la ✕.",
            CreativeState.brief_must_avoid_items,
            CreativeState.brief_must_avoid_draft,
            CreativeState.set_brief_must_avoid_draft,
            CreativeState.add_must_avoid,
            CreativeState.add_must_avoid_on_key,
            CreativeState.remove_must_avoid,
            "Ej.: barato",
        ),
        spacing="4",
        width="100%",
        align_items="start",
        class_name="q-cr-rules",
    )


def _campaign_view() -> rx.Component:
    """«Campaña» (m-24820838, optional): the piece joins one of the brand's campaigns, a
    new one named and coloured here, or none — the same choice the planner's drawer
    offers. It is applied once Generar created the piece, and the Planificador groups it
    with its campaign."""
    picker = rx.select.root(
        rx.select.trigger(placeholder="Sin campaña", aria_label="Campaña de la publicación"),
        rx.select.content(
            rx.select.item("Sin campaña", value=NO_CAMPAIGN),
            rx.cond(CreativeState.gen_campaigns.length() > 0, rx.select.separator()),
            rx.foreach(
                CreativeState.gen_campaigns,
                lambda c: rx.select.item(c.name, value=c.id),
            ),
            rx.select.separator(),
            rx.select.item("+ Nueva campaña", value=NEW_CAMPAIGN),
        ),
        value=CreativeState.gen_campaign,
        on_change=CreativeState.set_gen_campaign,
        size="2",
    )
    new_campaign = rx.vstack(
        rx.hstack(
            rx.input(
                value=CreativeState.gen_campaign_new_name,
                on_change=CreativeState.set_gen_campaign_new_name,
                placeholder="Nombre de la nueva campaña",
                max_length=60,
                size="2",
                flex="1",
                min_width="10rem",
                aria_label="Nombre de la nueva campaña",
            ),
            color_swatches(
                CreativeState.gen_campaign_new_color,
                CreativeState.set_gen_campaign_new_color,
                COLOR_LABELS,
                label="Color de la nueva campaña",
            ),
            align="center",
            spacing="3",
            wrap="wrap",
            width="100%",
        ),
        rx.text("Se creará al crear la publicación.", size="1", color=T.TEXT_MUTED),
        spacing="1",
        width="100%",
    )
    return rx.vstack(
        rx.vstack(
            rx.heading("Campaña (opcional)", size="4", as_="h3"),
            rx.text(
                "Agrupa la publicación con otras de la misma campaña: así se ven juntas en "
                "Tu semana. Sin campaña, la publicación queda independiente.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            spacing="0",
            align_items="start",
        ),
        _field(
            "Campaña",
            rx.vstack(
                picker,
                rx.cond(CreativeState.gen_campaign == NEW_CAMPAIGN, new_campaign),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _view_step(step: rx.Var[dict[str, str]]) -> rx.Component:
    """One step of the bar — the design system's stepper look (`.q-step*`), built from
    the kind's own views, so its labels are dynamic."""
    done = step["done"] == "true"
    current = step["current"] == "true"
    return rx.fragment(
        rx.cond(
            step["index"] != "0",
            rx.box(
                class_name=rx.cond(done | current, "q-step-line q-step-line--on", "q-step-line"),
                aria_hidden="true",
            ),
        ),
        rx.el.button(
            rx.box(
                rx.cond(
                    done,
                    rx.icon("check", size=12, stroke_width=3),
                    rx.text(step["number"], size="1", weight="bold", line_height="1"),
                ),
                class_name=rx.cond(
                    done,
                    "q-step-dot q-step-dot--done",
                    rx.cond(current, "q-step-dot q-step-dot--current", "q-step-dot"),
                ),
                aria_hidden="true",
            ),
            rx.text(
                step["label"],
                size="1",
                weight=rx.cond(current, "bold", "medium"),
                color=rx.cond(current | done, T.TEXT_STRONG, T.TEXT_MUTED),
                class_name="q-step-label",
            ),
            type="button",
            title=step["label"],
            class_name=rx.cond(current, "q-step q-step--current", "q-step"),
            aria_current=rx.cond(current, "step", "false"),
            on_click=CreativeState.go_to_view(step["index"]),
        ),
    )


def _view_steps() -> rx.Component:
    """The optional desktop index; the frame owns the one visible step count."""
    return rx.vstack(
        rx.box(
            rx.foreach(CreativeState.gen_view_steps, _view_step),
            class_name="q-stepper",
            role="list",
            aria_label="Pasos",
            width="100%",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _has_view(view: str) -> rx.Var[bool]:
    return CreativeState.gen_step_views.contains(view)


def _step_show() -> rx.Component:
    """① Qué mostrar: Avatar's types, the references, the presenter and the kind's own
    section — everything a kind cannot do without (CREAR-2)."""
    return rx.vstack(
        rx.cond(_has_view("avatar_type"), _avatar_type_view()),
        rx.cond(
            _has_view("reference"),
            rx.cond(
                CreativeState.gen_category == "clip",
                _clip_references_view(),
                _reference_view(),
            ),
        ),
        rx.cond(_has_view("presenter"), _section_presenter()),
        rx.cond(_has_view("details"), _section_details()),
        spacing="6",
        width="100%",
        align_items="start",
    )


def _step_say() -> rx.Component:
    """② Qué decir: the context, «Mejorar mi texto», for an avatar its script, and
    «Datos clave» behind «Más opciones»."""
    return rx.vstack(
        _section_topic(),
        rx.cond(
            CreativeState.gen_category == "video",
            rx.vstack(
                rx.divider(),
                _field_label("El guion", "Lo escribimos con tu texto, o lo escribes tú."),
                _script_source(),
                spacing="3",
                width="100%",
                align_items="start",
            ),
        ),
        rx.divider(),
        # UX review: the price or a promotion are what the piece says
        _more_options(
            CreativeState.rules_open,
            CreativeState.toggle_rules,
            "El precio o una promoción, y qué decir o evitar. Puedes crear sin tocarlos.",
            _section_rules(),
        ),
        spacing="5",
        width="100%",
        align_items="start",
    )


def _more_options(
    is_open: rx.Var[bool],
    toggle: rx.event.EventHandler,
    hint: str | rx.Var[str],
    body: rx.Component,
) -> rx.Component:
    """«Más opciones» (N6): a step's optional fields, folded until the owner opens them,
    with a hint of what is inside while it is closed."""
    return rx.vstack(
        rx.button(
            rx.icon(rx.cond(is_open, "chevron-up", "chevron-down"), size=T.ICON_SM),
            "Más opciones",
            variant="ghost",
            color_scheme="gray",
            size="3",
            min_height="44px",
            on_click=toggle,
            aria_expanded=rx.cond(is_open, "true", "false"),
        ),
        rx.cond(~is_open, rx.text(hint, size="1", color=T.TEXT_MUTED)),
        rx.cond(is_open, body),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _step_how() -> rx.Component:
    """③ Cómo la quieres: format and length; behind «Más opciones» the campaign and,
    for a clip, «Con sonido» (UX review 2026-10-24, finding 4)."""
    is_clip = CreativeState.brief_kind == "clip"
    return rx.vstack(
        _section_channel(),
        rx.divider(),
        _more_options(
            CreativeState.campaign_open,
            CreativeState.toggle_campaign_open,
            rx.cond(
                is_clip,
                "El sonido del video y la campaña. Puedes crear sin tocarlos.",
                "Agrupa esta publicación en una campaña. Puedes crear sin tocarla.",
            ),
            rx.vstack(
                # § request 2026-10-23: «generar el clip con audio» — on by default
                rx.cond(
                    is_clip,
                    _audio_switch(
                        checked=CreativeState.clip_audio,
                        on_change=CreativeState.set_clip_audio,
                    ),
                ),
                _campaign_view(),
                spacing="4",
                width="100%",
                align_items="start",
            ),
        ),
        spacing="5",
        width="100%",
        align_items="start",
    )


def _summary_row(item: rx.Var[dict[str, str]]) -> rx.Component:
    """One choice of the piece, and «Editar» back to the view that sets it. A grid
    (`.q-cr-summary-row`, assets/qualify-creative.css): label · value · Editar on one
    line, and on a phone the label with «Editar» on top and the value the full width
    under them — a 10rem label beside it left ~6 letters a line at 375 px and broke
    words in half («Product/o», m-24820845)."""
    return rx.box(
        rx.text(item["label"], size="2", color=T.TEXT_MUTED, class_name="q-cr-summary-label"),
        rx.text(item["value"], size="2", class_name="q-cr-summary-value"),
        rx.cond(
            item["index"] != "",
            rx.button(
                rx.icon("pencil", size=12),
                "Editar",
                variant="ghost",
                color_scheme="gray",
                size="1",
                on_click=CreativeState.edit_view(item["view"]),
                aria_label="Editar " + item["label"],
                min_height="44px",
                class_name="q-cr-summary-edit",
            ),
        ),
        width="100%",
        border_bottom=T.BORDER,
        class_name="q-cr-summary-row",
    )


def _summary_view() -> rx.Component:
    """«Resumen» (§ request 2026-10-20): every option's last view — what the piece will
    be made from, each choice with «Editar» back to its view, and what still keeps
    Generar from running. Generar is in its footer."""
    return rx.vstack(
        rx.vstack(
            rx.heading("Revisa y crea", size="4", as_="h3"),
            rx.text(
                "Revisa lo que vamos a crear. Crear no publica nada: después la revisas y tú "
                "decides si sale.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            spacing="0",
            align_items="start",
        ),
        rx.cond(
            CreativeState.gen_problem != "",
            callout(CreativeState.gen_problem, "warn"),
        ),
        # m-24852129: a counter at 0 — Crear is disabled; the one way out is to ask
        rx.match(
            CreativeState.gen_exhausted,
            ("videos", ask_more_block("videos")),
            ("previews", ask_more_block("previews")),
            ("creations", ask_more_block("creations")),
            rx.fragment(),
        ),
        rx.vstack(
            rx.foreach(CreativeState.gen_summary, _summary_row),
            spacing="0",
            width="100%",
        ),
        _creations_notice(),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _creations_notice() -> rx.Component:
    """CREAR-5 (m-24848531): before Crear, what the piece uses of the month's creations
    and what would be left — never money. A presenter the month cannot pay offers the
    shorter one instead, when that one fits."""
    return rx.fragment(
        rx.cond(
            CreativeState.gen_creations_notice != "",
            callout(CreativeState.gen_creations_notice, "info", icon="sparkles"),
        ),
        rx.cond(
            CreativeState.gen_presenter_fallback != "",
            rx.vstack(
                callout(CreativeState.gen_presenter_fallback, "info"),
                rx.button(
                    rx.icon("timer", size=T.ICON_SM),
                    "Usar el video de 15 segundos",
                    variant="soft",
                    size="3",
                    radius=_CONTROL_RADIUS,
                    min_height="44px",
                    on_click=CreativeState.use_short_presenter,
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
    )


def _view_nav() -> rx.Component:
    """The view's footer: Atrás, and Siguiente — or, on the last view, Generar, the
    form's one solid action (§5.5), with what still keeps it from generating above it."""
    return rx.vstack(
        rx.cond(
            CreativeState.create_error != "",
            callout(CreativeState.create_error, "error"),
        ),
        rx.hstack(
            rx.cond(
                ~CreativeState.gen_is_first_view,
                rx.button(
                    rx.icon("arrow-left", size=T.ICON_SM),
                    "Atrás",
                    variant="soft",
                    color_scheme="gray",
                    size="3",
                    radius=_CONTROL_RADIUS,
                    min_height="44px",
                    on_click=CreativeState.prev_view,
                ),
            ),
            rx.spacer(),
            rx.cond(
                CreativeState.gen_is_last_view,
                rx.button(
                    rx.icon("sparkles", size=T.ICON_SM),
                    rx.cond(CreativeState.gen_generating, "Creando…", "Crear"),
                    size="3",
                    radius=_CONTROL_RADIUS,
                    min_height="44px",
                    on_click=CreativeState.submit_generator_form,
                    loading=CreativeState.is_submitting,
                    # m-24852129: never an active Crear that is then refused
                    disabled=CreativeState.gen_generating | (CreativeState.gen_exhausted != ""),
                ),
                rx.button(
                    "Siguiente",
                    rx.icon("arrow-right", size=T.ICON_SM),
                    size="3",
                    radius=_CONTROL_RADIUS,
                    min_height="44px",
                    on_click=CreativeState.next_view,
                ),
            ),
            width="100%",
            align="center",
            spacing="3",
        ),
        spacing="3",
        width="100%",
        class_name="q-cr-view-nav",
    )


def _create_view() -> rx.Component:
    """The current step's fields; the frame owns the head and the fixed actions."""
    return card(
        rx.vstack(
            rx.box(
                rx.match(
                    CreativeState.gen_step_key,
                    ("show", _step_show()),
                    ("say", _step_say()),
                    ("how", _step_how()),
                    _summary_view(),
                ),
                width="100%",
                max_width="52rem",
                margin_x="auto",
                class_name="q-settle",
                key=CreativeState.gen_step_key,
            ),
            spacing="5",
            width="100%",
            flex="1",
        ),
        padding="1.25rem 1.5rem",
        width="100%",
        flex="1",
        display="flex",
        class_name="q-cr-view",
    )


_RESULT_HEADING = ("Tu publicación", "Así quedó. Revísala y apruébala para poder programarla.")


# -- the result view -------------------------------------------------------------------


def _media_src(key: rx.Var[str]) -> rx.Var[str]:
    """A file in the local upload store."""
    return rx.get_upload_url(key)


def _item_src(item: rx.Var) -> rx.Var[str]:
    """A generated piece: through `/r2media` — its only copy is in R2 since 2026-10-06 —
    or, for one generated before, from the local upload store."""
    return rx.cond(item.url != "", BACKEND_BASE + item.url, rx.get_upload_url(item.key))


def _item_poster(item: rx.Var) -> rx.Var[str]:
    return rx.cond(
        item.poster_url != "",
        BACKEND_BASE + item.poster_url,
        rx.cond(item.poster_key != "", rx.get_upload_url(item.poster_key), ""),
    )


def _download(key: rx.Var[str], label: str = "Descargar") -> rx.Component:
    return rx.link(
        rx.hstack(rx.icon("download", size=14), rx.text(label, size="2"), spacing="1"),
        href=_media_src(key),
        is_external=True,
        download=True,
    )


def _item_download(item: rx.Var) -> rx.Component:
    """§ request 2026-10-21: the ONE «Descargar» — the whole piece (its files and its
    words, m-24828908); the file alone only when the .zip link could not be minted."""
    return piece_download_button(
        CreativeState.gen_draft.download_path,
        CreativeState.gen_draft.download_name,
        file_url=rx.cond(
            item.url != "", BACKEND_BASE + item.url + "?download=1", rx.get_upload_url(item.key)
        ).to(str),
        file_name=rx.cond(item.media_type == "video", "qualify-video.mp4", "qualify-imagen.jpg"),
    )


def _variant_switch() -> rx.Component:
    return rx.cond(
        CreativeState.gen_variant_labels.length() > 1,
        rx.segmented_control.root(
            rx.foreach(
                CreativeState.gen_variant_labels,
                lambda option: rx.segmented_control.item(option[1], value=option[0]),
            ),
            value=CreativeState.gen_variant.to_string(),
            on_change=CreativeState.choose_gen_variant,
            size="1",
        ),
    )


def _shot_row(line: rx.Var[str]) -> rx.Component:
    return rx.box(
        rx.text(line, size="2"),
        padding="0.6rem 0.8rem",
        border_left=f"3px solid {T.tone_color('accent', 7)}",
        background=T.SURFACE_BG_RAISED,
        border_radius=T.RADIUS_CONTROL,
        width="100%",
    )


def _script_result() -> rx.Component:
    """Creator's script: only the script — what is said, and the shots to record. "Copiar"
    takes both, the shots under the script (§ request 2026-10-06)."""
    variant = CreativeState.gen_variant_vm
    has_shots = variant.shots.length() > 0
    return _card(
        rx.text(variant.script, size="3", white_space="pre-wrap", line_height="1.6"),
        rx.cond(
            has_shots,
            rx.vstack(
                rx.text("Tomas", size="2", weight="medium", color=T.TEXT_MUTED),
                rx.foreach(variant.shots, _shot_row),
                spacing="2",
                width="100%",
            ),
        ),
        rx.hstack(
            rx.button(
                rx.icon("copy", size=14),
                rx.cond(has_shots, "Copiar guion y tomas", "Copiar guion"),
                variant="soft",
                size="1",
                on_click=[
                    rx.set_clipboard(variant.script_clipboard),
                    rx.toast.success("Guion copiado"),
                ],
            ),
            # a script has no file: its «Descargar» is the .zip of its words (m-24828908)
            piece_download_button(
                CreativeState.gen_draft.download_path, CreativeState.gen_draft.download_name
            ),
            spacing="2",
            align="center",
            wrap="wrap",
        ),
        rx.divider(),
        _copy_block("Descripción de la publicación", variant.description, "Descripción copiada"),
        rx.cond(
            variant.hashtags_text != "",
            _copy_block("Etiquetas", variant.hashtags_text, "Etiquetas copiadas"),
        ),
        title="Guion",
        icon="clapperboard",
        actions=(_variant_switch(),),
    )


def _copy_block(label: str, text: rx.Var[str], copied: str) -> rx.Component:
    """A labelled piece of the post under a creator's script (§ request 2026-10-08) —
    the description or the hashtags — with its own Copiar."""
    return rx.vstack(
        rx.text(label, size="2", weight="medium", color=T.TEXT_MUTED),
        rx.text(text, size="2", white_space="pre-wrap"),
        rx.button(
            rx.icon("copy", size=14),
            "Copiar",
            variant="soft",
            size="1",
            on_click=[rx.set_clipboard(text), rx.toast.success(copied)],
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _post_text() -> rx.Component:
    """The post's own copy under a video or an image: what goes in the caption."""
    variant = CreativeState.gen_variant_vm
    return rx.vstack(
        rx.text("Texto de la publicación", size="2", weight="medium", color=T.TEXT_MUTED),
        rx.text(variant.rendered_caption, size="2", white_space="pre-wrap"),
        rx.button(
            rx.icon("copy", size=14),
            "Copiar texto",
            variant="soft",
            size="1",
            on_click=rx.set_clipboard(variant.rendered_caption),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _media_preview(item: rx.Var) -> rx.Component:
    """One generated file as Borradores shows it (`creative_pages._media_item`): a rounded
    frame with its ring and shadow, the file's bar under it. A video keeps the 9:16 frame;
    an image keeps its own shape — a story or a square is never cropped to 4:5."""
    is_video = item.media_type == "video"
    return rx.vstack(
        rx.cond(
            is_video,
            rx.video(
                src=_item_src(item),
                poster=_item_poster(item),
                controls=True,
                width="100%",
                height="auto",
                # a carousel's video is a feed slide (4:5 or 1:1): framed at its own
                # shape — in the 9:16 frame of a Reel its sides, and the words on
                # them, were cut off (2026-10-09: "las letras se cortan")
                class_name=rx.cond(
                    item.is_slide, "q-rv-media q-rv-media--slide", "q-rv-media q-rv-media--video"
                ),
            ),
            rx.image(src=_item_src(item), alt="", height="auto", class_name="q-rv-media"),
        ),
        rx.hstack(
            rx.center(
                rx.cond(is_video, rx.icon("film", size=15), rx.icon("image", size=15)),
                class_name="q-rv-glyph",
            ),
            rx.vstack(
                rx.text(item.label, size="2", weight="bold"),
                rx.text(rx.cond(is_video, "Video", "Imagen"), size="1", color=T.TEXT_MUTED),
                spacing="0",
                min_width="0",
            ),
            rx.spacer(),
            _item_download(item),
            align="center",
            spacing="2",
            width="100%",
            class_name="q-rv-mediabar",
        ),
        spacing="3",
        align="center",
        width="100%",
    )


def _media_result(
    *sections: rx.Component,
    title: str,
    icon: str,
    empty: str = "",
) -> rx.Component:
    """Every piece with media is shown the same way (§ request 2026-10-08), laid out as
    Borradores lays a draft out (`creative_pages._review_panel`): a grid, the media on its
    own stage in a fixed track, a real gutter, the text in its sections beside it."""
    media = rx.cond(
        # § request 2026-10-08: a carousel's slides as a real carousel, not stacked
        CreativeState.gen_is_carousel,
        media_carousel(
            CreativeState.gen_draft.media,
            CreativeState.gen_slide,
            on_prev=CreativeState.gen_slide_step(-1),
            on_next=CreativeState.gen_slide_step(1),
            on_pick=CreativeState.gen_slide_pick,
            on_tick=CreativeState.gen_slide_auto,
            render_item=_media_preview,
        ),
        rx.vstack(
            rx.foreach(CreativeState.gen_draft.media, _media_preview),
            spacing="3",
            width="100%",
        ),
    )
    if empty:
        # a template's outputs land one by one; until the first, say so
        media = rx.cond(
            CreativeState.gen_draft.media.length() > 0,
            media,
            rx.text(empty, size="2", color=T.TEXT_MUTED),
        )
    return _card(
        rx.box(
            rx.box(
                media,
                class_name="q-rv-stage",
                width="100%",
                max_width=rx.breakpoints(initial="22rem", md="none"),
                margin_x=rx.breakpoints(initial="auto", md="0"),
            ),
            rx.vstack(
                *(rx.box(section, class_name="q-rv-section") for section in sections),
                spacing="3",
                min_width="0",
                width="100%",
            ),
            display="grid",
            grid_template_columns=rx.breakpoints(
                initial="minmax(0, 1fr)",
                md="18rem minmax(0, 1fr)",
                xl="20rem minmax(0, 1fr)",
            ),
            column_gap=rx.breakpoints(initial="0", md="2rem", xl="2.5rem"),
            row_gap="1.5rem",
            align_items="start",
            width="100%",
        ),
        title=title,
        icon=icon,
        actions=(_variant_switch(),),
    )


def _video_result() -> rx.Component:
    """Avatar video (human or animated): the video, its script, the post. A Seedance 1.0
    video is silent, so its script is not "read" — it stays as the post's script."""
    return _media_result(
        rx.fragment(
            rx.text(
                rx.cond(CreativeState.video_on_seedance, "Guion", "Guion leído"),
                class_name="q-rv-title",
            ),
            rx.text(CreativeState.gen_variant_vm.script, class_name="q-rv-read q-rv-read--multi"),
        ),
        _post_text(),
        title="Video",
        icon="video",
    )


def _image_result() -> rx.Component:
    """Ad image: the image, or the carousel's slides in order (the scene generated by
    Seedream, the words and the logo set on top)."""
    return _media_result(_post_text(), title="Imagen", icon="image")


def _template_result() -> rx.Component:
    """Template run: every output as it lands (Reel, feed, story), then the post's text.
    An output still rendering is simply not in the list yet (plan §2.2: a still never
    waits for the video)."""
    return _media_result(
        _post_text(),
        title="Tu paquete",
        icon="layout-template",
        empty="Las salidas aparecen aquí según van saliendo.",
    )


def _waiting() -> rx.Component:
    # § request 2026-10-02: every Brand Kit loader is the progress-bar one. A render
    # reports no progress, so the bar creeps; a video can outlast it (gen_timed_out).
    return _card(
        progress_panel(
            CreativeState.gen_waiting_label,
            "Puedes quedarte aquí: el resultado aparece solo cuando esté listo.",
            creep_seconds=60,
        ),
        rx.cond(
            CreativeState.gen_waiting_vendor,
            # m-24852154: true now — the video lands in Por aprobar on its own
            callout(WAITING_VENDOR_TEXT, "warn"),
            rx.cond(
                CreativeState.gen_timed_out,
                callout(
                    "Está tardando más de lo normal, pero sigue en preparación. Cuando "
                    "esté lista, aparecerá en Por aprobar.",
                    "warn",
                ),
            ),
        ),
    )


def _failed() -> rx.Component:
    return callout(
        rx.cond(
            CreativeState.gen_failure_label != "",
            CreativeState.gen_failure_label,
            "No se pudo crear esta publicación.",
        ),
        "error",
    )


def _result_view() -> rx.Component:
    from .queue_notice import queue_notice  # noqa: PLC0415

    return rx.vstack(
        rx.cond(
            CreativeState.gen_draft,
            queue_notice(CreativeState.gen_draft.queue, CreativeState.gen_draft.draft_id),
        ),
        rx.cond(CreativeState.action_error != "", callout(CreativeState.action_error, "warn")),
        # what the piece is — metadata, so `tag`s (§5.3), not state badges
        rx.hstack(
            rx.cond(CreativeState.gen_draft, tag(CreativeState.gen_kind_label, size="2")),
            tag(CreativeState.effective_format_label, size="2"),
            spacing="2",
        ),
        rx.cond(
            CreativeState.gen_is_ready,
            rx.match(
                CreativeState.gen_kind,
                ("creator_script", _script_result()),
                ("static_flyer", _image_result()),
                ("template", _template_result()),
                ("carousel", _carousel_result()),
                _video_result(),
            ),
            rx.cond(
                CreativeState.gen_is_failed,
                rx.cond(CreativeState.gen_draft.queue.cancelled, rx.fragment(), _failed()),
                _waiting(),
            ),
        ),
        rx.button(
            rx.icon("plus", size=16),
            "Crear otra",
            variant="soft",
            color_scheme="gray",
            on_click=CreativeState.new_generation,
            size="3",
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _voice_flag() -> rx.Component:
    """The Brand Kit's Tu voz y tono is still to configure (§ request 2026-10-06): a small
    warning above the step, with the one button that goes to configure it. It never
    blocks Generar — the piece just comes out with the default tone."""
    return rx.hstack(
        rx.icon("mic-off", size=T.ICON_SM, color=T.tone_color("warn", 11), flex_shrink="0"),
        rx.text(
            "Tu marca todavía no tiene su voz: lo que crees sonará genérico.",
            size="2",
            color=T.tone_color("warn", 11),
            flex="1",
        ),
        rx.button(
            "Preparar mi voz",
            rx.icon("arrow-right", size=14),
            size="1",
            variant="soft",
            **T.tone_scheme("warn"),
            on_click=CreativeState.configure_voice,
            flex_shrink="0",
        ),
        spacing="3",
        align="center",
        width="100%",
        padding="0.6rem 0.85rem",
        background=T.tone_color("warn", 2),
        border=f"1px solid {T.tone_color('warn', 6)}",
        border_radius=T.RADIUS_CONTROL,
        role="status",
        flex_wrap="wrap",
    )


def _brand_flag() -> rx.Component:
    """The brand is not ready to create from (m-24842979): say it in the owner's words,
    with the one button that goes to complete it — the kit inside the session. It never
    blocks Generar (the readiness gate is lifted, § request 2026-09-30)."""
    return rx.hstack(
        rx.icon("palette", size=T.ICON_SM, color=T.tone_color("warn", 11), flex_shrink="0"),
        rx.text(
            "Completa tu marca (colores, logo y forma de hablar) para que todo salga con tu "
            "estilo.",
            size="2",
            color=T.tone_color("warn", 11),
            flex="1",
        ),
        rx.link(
            rx.button(
                "Completar mi marca",
                rx.icon("arrow-right", size=14),
                size="1",
                variant="soft",
                **T.tone_scheme("warn"),
            ),
            href=BRAND_KIT_ROUTE,
            flex_shrink="0",
        ),
        spacing="3",
        align="center",
        width="100%",
        padding="0.6rem 0.85rem",
        background=T.tone_color("warn", 2),
        border=f"1px solid {T.tone_color('warn', 6)}",
        border_radius=T.RADIUS_CONTROL,
        role="status",
        flex_wrap="wrap",
    )


def _generator_body() -> rx.Component:
    """The product or workspace, shared by the step frame and the non-wizard modes."""
    return rx.cond(
        CreativeState.create_loading | ~CreativeState.create_entered,
        card(_loading_view("Cargando el generador"), width="100%"),
        rx.cond(
            CreativeState.product_confirmed,
            rx.box(
                _options_panel(),
                _workspace(CreativeState.readiness),
                class_name="q-cr-layout",
                width="100%",
                flex="1",
            ),
            _product_screen(),
        ),
    )


def _generator_frame() -> rx.Component:
    loading = CreativeState.create_loading | ~CreativeState.create_entered
    active = CreativeState.create_uses_step_frame
    frame = step_frame(
        rx.cond(
            active & CreativeState.create_entered & ~CreativeState.create_loading,
            step_sync(
                CreativeState.create_step_n,
                CreativeState.gen_direction,
                epoch=CreativeState.create_entry_epoch,
            ),
        ),
        _generator_body(),
        _kind_conflict_dialog(),
        head=rx.cond(
            active,
            step_head(
                rx.cond(loading, "Crear publicación", CreativeState.create_step_title),
                step=CreativeState.create_step_n,
                total=CreativeState.create_step_m,
                back_label="Inicio",
                on_exit=CreativeState.save_for_later,
                below=rx.cond(
                    CreativeState.product_confirmed & (CreativeState.generator_view != "result"),
                    _view_steps(),
                ),
            ),
            page_header(
                "Crear publicación",
                "Elige el producto, luego qué quieres crear.",
                kicker=rx.cond(
                    (CreativeState.gen_mode == "variations") & VariationsState.has_set,
                    rx.button(
                        rx.icon("chevron-left", size=T.ICON_SM),
                        "Tus grupos",
                        variant="ghost",
                        color_scheme="gray",
                        size="3",
                        min_height="44px",
                        on_click=VariationsState.close_set,
                        aria_label="Volver a tus grupos",
                    ),
                ),
            ),
        ),
        foot=rx.cond(
            active & ~loading,
            step_foot(
                CreativeState.create_primary_label,
                step=CreativeState.create_step_n,
                on_primary=CreativeState.create_continue,
                on_back=CreativeState.create_back,
                on_later=CreativeState.save_for_later,
                primary_disabled=CreativeState.create_primary_disabled,
                primary_loading=CreativeState.is_submitting | CreativeState.stock_importing,
                reason=CreativeState.create_reason,
            ),
        ),
        step=CreativeState.create_step_n,
        direction=CreativeState.gen_direction,
        on_pop=CreativeState.enter_create_step,
        on_enter=CreativeState.enter_create_step,
        on_leave=CreativeState.leave_create_frame,
    )
    # Discovery and variations are forms, not numbered wizards. Keep one workspace
    # mounted when changing mode, and restore the usual mobile navigation for them.
    frame.class_name = rx.cond(active, "q-step-frame", "q-generator-form")
    return frame


def generator_page() -> rx.Component:
    """Create's product and four real steps share one frame. Variations remains a form."""
    return app_shell(_generator_frame())


def _kind_conflict_dialog() -> rx.Component:
    """«Este video no sirve aquí» (§ request 2026-10-16): the product is a stock video
    and the option picked cannot take one — use it in a Clip or a Galería, or change
    the product."""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Este video no sirve aquí", size="4"),
            rx.alert_dialog.description(CreativeState.kind_conflict, size="2"),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button(
                        "Cambiar el producto",
                        variant="soft",
                        color_scheme="gray",
                        size="2",
                        on_click=CreativeState.resolve_kind_conflict("product"),
                    ),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        rx.icon("images", size=T.ICON_SM),
                        "Usar en una Galería",
                        variant="soft",
                        size="2",
                        on_click=CreativeState.resolve_kind_conflict("carousel"),
                    ),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        rx.icon("clapperboard", size=T.ICON_SM),
                        "Usar en un Clip",
                        size="2",
                        on_click=CreativeState.resolve_kind_conflict("clip"),
                    ),
                ),
                justify="end",
                gap="0.75rem",
                margin_top="1.25rem",
                flex_wrap="wrap",
            ),
            max_width="30rem",
        ),
        open=CreativeState.kind_conflict != "",
        on_open_change=CreativeState.set_kind_conflict_open,
    )


def _workspace(readiness: rx.Var) -> rx.Component:
    """The centre of /create: what was chosen, the brand's warnings, and then the
    discovery, the piece once generated, or the chosen option's views."""
    result = card(
        rx.vstack(
            rx.text(_RESULT_HEADING[1], size="2", color=T.TEXT_MUTED),
            _result_view(),
            spacing="4",
            width="100%",
            align_items="start",
        ),
        padding="1.75rem",
        width="100%",
        id="gen-result",
        scroll_margin_top=T.SCROLL_MARGIN_TOP,
    )
    return rx.vstack(
        rx.cond(~CreativeState.create_uses_step_frame, _kind_header()),
        rx.cond(
            CreativeState.create_error != "",
            callout(CreativeState.create_error, "error"),
        ),
        # The BrandReadiness gate is lifted for now (§ request 2026-09-30):
        # the warning stays, but it never blocks Generar.
        rx.cond(
            readiness,
            rx.cond(
                ~readiness.can_generate,
                _brand_flag(),
            ),
        ),
        rx.cond(CreativeState.kit_voice_missing, _voice_flag()),
        # § request 2026-10-09: while a piece generates the form is off — it
        # comes back on its own when the piece is ready (or failed)
        rx.cond(
            CreativeState.gen_generating,
            callout(
                "Creando tu publicación. El formulario se reactiva cuando termine; "
                "te avisamos aquí.",
                "info",
                icon="loader-circle",
            ),
        ),
        rx.match(
            CreativeState.gen_mode,
            ("discover", _discover_view()),
            ("variations", variations_view()),
            rx.cond(CreativeState.generator_view == "result", result, _create_view()),
        ),
        spacing="4",
        width="100%",
        min_width="0",
        min_height="100%",
        # CREAR-6: where choosing an option scrolls to on a phone (`_scroll_to_view`)
        id="q-cr-view",
        scroll_margin_top=T.SCROLL_MARGIN_TOP,
    )


def _slide_stock_fields() -> rx.Component:
    """A slide holding an inspiration video (picked from the slide's «Inspiración»
    tab): the video it uses and its words — always the title or the button: the words and
    the logo over it are what make it the brand's piece."""
    current = CreativeState.carousel_current
    index = CreativeState.carousel_selected
    return rx.vstack(
        rx.hstack(
            _slide_thumb(current["view"], current["media_type"], size="5rem"),
            rx.vstack(
                rx.text(current["label"], size="2"),
                rx.text(
                    "Video · ajustado al formato, con tu texto y tu logo encima",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                rx.button(
                    "Quitar video",
                    variant="ghost",
                    color_scheme="gray",
                    size="1",
                    on_click=CreativeState.set_slide_source("generated"),
                ),
                spacing="1",
                align_items="start",
            ),
            spacing="3",
            align="center",
        ),
        _slide_panel(
            rx.text("Texto encima", size="1", color=T.TEXT_MUTED),
            rx.segmented_control.root(
                rx.segmented_control.item("Título", value="hook"),
                rx.segmented_control.item("Botón de acción", value="cta"),
                value=current["text"],
                on_change=lambda value: CreativeState.set_slide_field(index, "text", value),
                size="2",
                width="100%",
            ),
            width="100%",
        ),
        spacing="4",
        width="100%",
        align_items="stretch",
    )
