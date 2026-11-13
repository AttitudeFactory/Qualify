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

from . import clip_gallery_vm, part_editor_vm, reel_parts_vm, reel_wait_vm
from .ask_more_ui import ask_more_block
from .campaign_provider import COLOR_LABELS, NEW_CAMPAIGN, NO_CAMPAIGN
from .catalog_vm import ADD_PRODUCT_LABEL, CREATE_RETURN_PATH, new_product_href
from .creative_state import (
    _INSPIRATION_TARGETS,
    _NO_CATALOG_TARGETS,
    _OWN_HITS_TARGETS,
    CONTEXT_FIELD_ID,
    DURATIONS,
    INSPIRATION_PLACEHOLDERS,
    INSPIRATION_SLOT_LIMITS,
    PINTEREST_IMAGE_TARGETS,
    REEL_PART_CARD_ID,
    REEL_PART_UNDO_ID,
    REEL_WAIT_HEARTBEAT_MS,
    SLIDE_SECONDS,
    STOCK_MAX_PICKS,
    CreativeState,
    _own_key,
)
from .creative_vm import (
    BRAND_FIX_LABEL,
    BRAND_FIX_ROUTE,
    CATEGORY_OPTIONS,
    PHRASE_LIMIT,
    PHRASE_LIMIT_HINT,
    PRICE_FACT_LABEL,
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
from .final_video_card_state import FinalVideoState
from .generator_summary_vm import CLIP_MIDDLE_NOTE, LOGO_SIGNATURE_TEXT
from .media_carousel import media_carousel
from .part_editor_view import part_editor
from .part_progress_panel import part_progress_panel
from .part_progress_state import PartProgressState
from .part_progress_vm import (
    PARTS_HEADING_TEXT,
    PARTS_KIND_LABEL,
)
from .parts_start_view import parts_empty_notice, parts_start_card
from .photo_upload_vm import CUT_CONNECTION_HINT, PHOTO_ACCEPT
from .picker_tabs import upload_host_id
from .post_card import color_swatches
from .r2_media import BACKEND_BASE
from .reels_ideas_vm import IDEAS_BACK_LABEL
from .ui import (
    app_shell,
    callout,
    card,
    choice_card,
    choice_card_check,
    dropzone,
    empty_state,
    expandable_text,
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
from .ui.clip_player import clip_player, clip_player_notice, clip_player_script
from .ui.steps import step_foot, step_frame, step_head, step_sync
from .upload_images import PHOTO_MAX_BYTES
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


#: m-25017273: JPG, PNG, WEBP and the iPhone's HEIC/HEIF (converted to JPEG on the server)
_IMAGE_ACCEPT = PHOTO_ACCEPT


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
                            # UI-6: a reel's parts are «Video por partes», not «Clip»
                            rx.cond(
                                CreativeState.reel_plan_shown,
                                reel_parts_vm.PARTS_PIECE_LABEL,
                                rx.match(
                                    CreativeState.gen_category,
                                    *[(key, title) for key, title, _, _ in CATEGORY_OPTIONS],
                                    "Crear publicación",
                                ),
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
    # R7 (m-24854854, UX review 8): the weekly rhythm, and the accounts by the one name the
    # screen gives them («las cuentas que te inspiran»); what the filter keeps
    # (`referentes/reels_ai.py`, FITS = producto | categoria)
    "Cada lunes, los reels que mejor les funcionan a las cuentas que te inspiran, solo de "
    "tu producto o su categoría, para que hagas uno parecido.",
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
    """A file of the chosen product in a slot's «Galería» / «Inspiración» tab. A stock
    product's files live in R2 (`piece_views` maps them, a video to its POSTER), a
    catalog product's in the upload store."""
    label = rx.cond(CreativeState.product_source == "stock", "Inspiración", "De la Galería")
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


#: The slots that hold several files: their «Inspiración» stays open until they are full.
SEVERAL_FILE_TARGETS = tuple(INSPIRATION_SLOT_LIMITS)
INSPIRATION_FULL = "Este espacio ya está completo. Quita uno para tomar otra inspiración."
#: The box's hint outside a gallery picker (a gallery picker has its own: D5).
INSPIRATION_PLACEHOLDER = "Busca inspiración: hamburguesa, cocina, ciudad de noche…"


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
    # live test 2026-11-03: a slot of several folds only once it is full — a new search
    # could not add anything, so it says how to make room instead of «Buscar otra»
    several = target in SEVERAL_FILE_TARGETS
    folded = rx.hstack(
        rx.icon("check", size=T.ICON_SM, color=T.tone_color("accent", 11)),
        rx.text(
            INSPIRATION_FULL if several else "Ya tomaste inspiración para este espacio.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.fragment()
        if several
        else rx.button(
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
    # another slot's typed search is not this one's: its hits stay there
    ours = (CreativeState.stock_results_for == "") | (CreativeState.stock_results_for == target)
    bank_loading = CreativeState.stock_loading if image else CreativeState.vstock_loading
    shared = rx.cond(
        ours,
        CreativeState.stock_results if image else CreativeState.vstock_results,
        rx.Var.create([]),
    )
    noun = "imágenes" if image else "videos"
    empty_note = _picker_note(
        f"Aún no hay {noun}: busca arriba o deja la caja vacía para usar tu marca."
        if titled
        else f"Escribe qué buscas o deja la caja vacía para usar tu marca. "
        f"Solo {noun} sin personas."
    )
    if target in _OWN_HITS_TARGETS:
        # live bug 2026-11-04: in a gallery the background and the OPEN slide keep the
        # hits of their own search — the tap goes where it was made (same key as the state)
        key = _own_key(target, "image" if image else "video")
        own = CreativeState.inspiration_own_view.contains(key)
        hits = rx.cond(own, CreativeState.inspiration_own_shown[key], shared).to(
            list[dict[str, str]]
        )
        # UX review 2026-11-04 D4: this picker's own search replaces its grid with
        # «Buscando…» — the old tiles cannot be tapped meanwhile; the shared hits wait
        # only for a shared search (never another picker's)
        busy = bank_loading & (
            (CreativeState.inspiration_searching_here == target)
            | (~own & ours & (CreativeState.inspiration_searching == "") & (hits.length() == 0))
        )
        # D1/D2: after an own search with no hits, its own «no encontramos» — never
        # «deja la caja vacía», which would send the owner to repeat that search
        none = rx.cond(
            own, _picker_note(CreativeState.inspiration_own_empty[key].to(str)), empty_note
        )
    else:
        hits = shared.to(list[dict[str, str]])
        busy = bank_loading & ours & (hits.length() == 0)
        none = empty_note
    grid = rx.cond(
        busy,
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
            none,
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
    placeholder: rx.Var[str] | str = INSPIRATION_PLACEHOLDER
    loading: rx.Var[bool] = CreativeState.stock_any_loading
    disabled: rx.Var[bool] = ~CreativeState.stock_on
    error: rx.Var[str] = CreativeState.stock_error
    head: list[rx.Component] = []
    if target in _OWN_HITS_TARGETS:
        # UX review 2026-11-04: in a gallery only the picker that searches spins (D3),
        # the others wait without spinning; the box says what to look for there, a line
        # says what its grid is for (D5); the callout is only for a bank that is down
        # or an import that failed (D1)
        gallery = CreativeState.brief_kind == "carousel"
        placeholder = rx.cond(gallery, INSPIRATION_PLACEHOLDERS[target], INSPIRATION_PLACEHOLDER)
        loading = rx.cond(
            gallery,
            CreativeState.inspiration_searching_here == target,
            CreativeState.stock_any_loading,
        )
        disabled = ~CreativeState.stock_on | (gallery & CreativeState.stock_any_loading)
        error = rx.cond(gallery, CreativeState.inspiration_shared_error, CreativeState.stock_error)
        label = CreativeState.inspiration_picker_label[target].to(str)
        head = [
            rx.cond(
                label != "",
                rx.text(label, size="1", weight="medium", color=T.TEXT_MUTED),
            )
        ]
    return rx.vstack(
        rx.hstack(
            rx.input(
                rx.input.slot(rx.icon("search", size=T.ICON_SM)),
                # live test 2026-11-03: each slot's box has its own words
                value=CreativeState.inspiration_query_view[target].to(str),
                on_change=lambda value: CreativeState.set_inspiration_query(target, value),
                on_key_down=lambda key: CreativeState.inspiration_search_on_enter(target, key),
                placeholder=placeholder,
                max_length=100,
                size="2",
                flex="1",
                aria_label="Buscar inspiración",
            ),
            rx.button(
                "Buscar",
                size="2",
                loading=loading,
                disabled=disabled,
                on_click=CreativeState.search_inspiration(target),
            ),
            width="100%",
            spacing="2",
        ),
        rx.cond(error != "", callout(error, "warn")),
        *head,
        *grids,
        spacing="2",
        width="100%",
        align_items="start",
    )


def _picker_tabs(target: str, tab: rx.Var[str], *, uploads: bool = True) -> rx.Component:
    """The slot's sources. With a stock product, «Galería» becomes «Inspiración» (the
    stock picked) and a «Galería» beside it brings the brand's catalog (§ request
    2026-10-19). No «Stock» tab: stock is chosen once, as the inspiration."""

    from .picker_tabs import open_upload_picker_script, reveal_picker_tab_script

    def control(*items: tuple[str, str]) -> rx.Component:
        return rx.box(
            rx.segmented_control.root(
                *(
                    rx.segmented_control.item(
                        label,
                        value=value,
                        min_height="44px",
                        custom_attrs={"data-picker-tab": value},
                    )
                    for value, label in items
                ),
                value=tab,
                on_change=lambda value: CreativeState.set_picker_tab(target, value),
                size="1",
                aria_label="De dónde viene",
                class_name="q-seg-fit",
                min_width="max-content",
                min_height="44px",
            ),
            width="100%",
            max_width="100%",
            min_width="0",
            overflow_x="auto",
            id=f"picker-tabs-{target}",
            on_mount=[
                rx.call_script(reveal_picker_tab_script(f"picker-tabs-{target}")),
                rx.call_script(
                    open_upload_picker_script(f"picker-tabs-{target}", upload_host_id(target))
                ),
            ],
        )

    # UI-3 round 13: the clip's gallery has its own drop zone — no «Subir» in its picker
    pinterest = (("pinterest", "Pinterest"),) if target in PINTEREST_IMAGE_TARGETS else ()
    rest = ((("upload", "Subir"),) if uploads else ()) + (("pieces", "Publicaciones"),) + pinterest
    # with a catalog product, «Inspiración» searches — only where the licence lets stock
    # go (`_INSPIRATION_TARGETS`): never the product photos nor the avatar's reference
    search = (("inspiration", "Inspiración"),) if target in _INSPIRATION_TARGETS else ()
    # a background or a motion reference is not a product: no catalog tab there
    no_catalog = target in _NO_CATALOG_TARGETS
    brand = () if no_catalog else (("brandcat", "Galería"),)
    own = () if no_catalog else (("catalog", "Galería"),)
    return rx.cond(
        CreativeState.product_source == "stock",
        control(("catalog", "Inspiración"), *brand, *rest),
        control(*own, *search, *rest),
    )


def _pinterest_source_links(target: str) -> rx.Component:
    return rx.vstack(
        rx.foreach(
            CreativeState.picker_pinterest_sources[target],
            lambda source: rx.link(
                "Referencia de Pinterest ↗",
                href=source["url"],
                is_external=True,
                size="1",
            ),
        ),
        spacing="1",
        align_items="start",
        width="100%",
    )


def _upload_tab(target: str, tab: rx.Var[str], upload: rx.Component) -> rx.Component:
    """«Subir»'s drop zone, mounted whatever tab is open and shown only on «Subir»
    (m-25017273): its file input must exist at the very tap on «Subir», which opens the
    picker at once (`open_upload_picker_script`) — no second tap on the zone."""
    return rx.box(
        upload,
        id=upload_host_id(target),
        display=rx.cond(tab == "upload", "block", "none"),
        width="100%",
    )


def _media_picker(
    target: str, upload: rx.Component, *, media_type: str = "image", uploads: bool = True
) -> rx.Component:
    """A slot's sources: the chosen product's files (the stock inspiration's, when it
    came from stock — then the brand's catalog is a tab of its own), inspiration to
    search where the licence lets stock go, an upload (the slot's own drop zone,
    `upload`) and the brand's pieces. A tile is ticked while the slot holds it; a click
    puts it in or takes it out (`CreativeState.pick_media`)."""
    from .pinterest_ui import pinterest_picker

    image = media_type == "image"
    tab = CreativeState.picker_tab_view[target].to(str)
    if not uploads:
        # no «Subir» tab here: a slot that would open on it opens on «Galería»
        tab = rx.cond(tab == "upload", "catalog", tab).to(str)
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
                f"Tu inspiración no tiene {noun}: búscalas en la Galería o súbelas.",
                rx.cond(
                    CreativeState.selected_product_id != "",
                    f"El producto que elegiste no tiene {noun} en la Galería.",
                    f"Elige un producto de la Galería al empezar y sus {noun} aparecen aquí.",
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
        _picker_note("Cargando tu Galería…"),
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
            _picker_note(f"Tu Galería aún no tiene {noun}."),
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
        _picker_tabs(target, tab, uploads=uploads),
        rx.match(
            tab,
            ("catalog", catalog_tab),
            ("brandcat", brandcat_tab),
            ("inspiration", _inspiration_search(target, image) if searchable else rx.fragment()),
            ("pieces", pieces_tab),
            ("pinterest", pinterest_picker(target) if image else rx.fragment()),
            rx.fragment() if uploads else catalog_tab,
        ),
        _upload_tab(target, tab, upload) if uploads else rx.fragment(),
        _pinterest_source_links(target) if image else rx.fragment(),
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
    from .pinterest_ui import pinterest_picker

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
                "Tu inspiración no tiene fotos ni videos: búscalos en la Galería o súbelos.",
                rx.cond(
                    CreativeState.selected_product_id != "",
                    "El producto que elegiste no tiene fotos ni videos en la Galería.",
                    "Elige un producto de la Galería al empezar y sus fotos y videos "
                    "aparecen aquí.",
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
        _picker_note("Cargando tu Galería…"),
        rx.cond(
            (brand_photos.length() + brand_videos.length()) > 0,
            tiles(rx.foreach(brand_photos, brand_photo), rx.foreach(brand_videos, brand_video)),
            _picker_note("Tu Galería aún no tiene fotos ni videos."),
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
            ("pinterest", pinterest_picker(target)),
            rx.fragment(),
        ),
        _upload_tab(target, tab, upload),
        _pinterest_source_links(target),
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


def _clip_role_select(key: rx.Var[str], role: rx.Var[str]) -> rx.Component:
    """What a clip image is for (§ 2026-10-14: the prompt names it so) — «Producto»,
    «Lugar» or «Estilo», kept in `clip_images[].role`. The strip's selector, and (UI-3
    round 9) the one under each held image in «Imágenes» while a reel's parts show."""
    return rx.select.root(
        rx.select.trigger(width="100%", min_height="44px", aria_label="Para qué es esta foto"),
        rx.select.content(
            rx.select.item("Producto", value="product"),
            rx.select.item("Lugar", value="place"),
            rx.select.item("Estilo", value="style"),
        ),
        value=role,
        on_change=lambda value: CreativeState.set_clip_image_role(key, value),
        size="1",
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
        _preview_thumb(key, CreativeState.remove_clip_image(key), "Quitar foto"),
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
                # round 12: what an image is for is chosen in the gallery above
                rx.fragment(),
            ),
        ),
        on_drag_start=CreativeState.start_clip_image_drag(index),
        on_drop=CreativeState.drop_clip_image(index),
        custom_attrs={
            "data-slide-group": "clip",
            "data-slide-key": key,
            "aria-label": rx.cond(video, "Video ", "Foto ") + (index + 1).to(str) + " del clip",
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
    """The clip's step 2 (UI-3, Deivid 2026-11-09): «Orden del clip» first (a reel's parts,
    or the strip of files without a plan), the reel's own text choice, then «Referencias
    (opcional)» — ONE gallery of every image, video and audio, one drop zone and «Elegir
    de tus fotos y videos» — and the brand's resources."""
    return rx.vstack(
        # «Orden del clip»: a reel's parts (UI-3) or, without a plan, the strip of files —
        # same component, events and drag as before; the role is set in the gallery
        rx.cond(
            CreativeState.reel_plan_shown,
            _clip_parts_block(),
            rx.cond(
                CreativeState.clip_strip.length() > 0,
                _clip_block(
                    "Orden del clip",
                    "Arrastra las fotos y los videos para ordenarlos: el primero abre el clip y "
                    "el último lo cierra (de un video se toma su primer o su último fotograma). "
                    "Son los mismos de abajo.",
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
                        callout(CLIP_MIDDLE_NOTE, "info"),
                    ),
                ),
            ),
        ),
        # m-24820842: the reel's own text choice — right under «Orden del clip»: it acts on
        # the reel, like the parts
        rx.cond(CreativeState.clip_is_reel_replica, _replica_brand_text()),
        rx.vstack(
            rx.vstack(
                rx.heading(clip_gallery_vm.TITLE, size="4", as_="h3"),
                rx.text(clip_gallery_vm.HINT, size="1", color=T.TEXT_MUTED),
                spacing="0",
                align_items="start",
            ),
            _clip_gallery(),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        _brand_resources(),
        _upload_error(),
        # m-24921079: «¿Quieres un video más largo? Armar mi video por partes» — under what
        # step 2 of a Clip shows today, only while no plan is on screen
        rx.cond(CreativeState.parts_start_shown, parts_start_card()),
        spacing="5",
        width="100%",
        align_items="start",
    )


#: The gallery's tile side (the strip's item width).
_GALLERY_TILE = "6.5rem"


def _gallery_picture(picture: rx.Component, on_remove: rx.event.EventSpec) -> rx.Component:
    return rx.box(
        picture,
        _small_remove(on_remove, "Quitar"),
        position="relative",
        width=_GALLERY_TILE,
        height=_GALLERY_TILE,
        overflow="hidden",
        border_radius=T.RADIUS_CONTROL,
    )


def _image_tile(tile: rx.Var) -> rx.Component:
    """A photo with its small ✕ and «Producto / Lugar / Estilo» — the one place its role
    is chosen (`clip_images[].role`, what the strip used)."""
    key = tile["key"]
    return rx.vstack(
        _gallery_picture(
            _clip_thumb(key, size=_GALLERY_TILE), CreativeState.remove_clip_image(key)
        ),
        _clip_role_select(key, tile["role"]),
        spacing="1",
        width=_GALLERY_TILE,
        align_items="stretch",
    )


def _video_tile(tile: rx.Var) -> rx.Component:
    """A video of the owner's (never the reel's original), its ✕ and «Movimiento»."""
    key = tile["key"]
    return rx.vstack(
        _gallery_picture(
            rx.cond(
                CreativeState.piece_views.contains(key),
                _slide_thumb(
                    CreativeState.piece_views[key].to(str), rx.Var.create("video"), _GALLERY_TILE
                ),
                _video_thumb(rx.get_upload_url(key), size=_GALLERY_TILE),
            ),
            CreativeState.remove_clip_video(key),
        ),
        rx.text(clip_gallery_vm.VIDEO_TAG, size="1", color=T.TEXT_MUTED, text_align="center"),
        spacing="1",
        width=_GALLERY_TILE,
        align_items="center",
    )


def _audio_tile(tile: rx.Var) -> rx.Component:
    """An audio as a square like the others: a neutral ground, the music icon, its name
    on one line (whole in `title` and the label: the cut hides the extension), «Música»."""
    key = tile["key"]
    return rx.vstack(
        _gallery_picture(
            rx.box(
                rx.center(
                    rx.icon("music", size=T.ICON_LG, color=T.TEXT_MUTED),
                    width="100%",
                    height="100%",
                    aria_hidden="true",
                ),
                _strip_badge(
                    rx.text(tile["name"], size="1", truncate=True),
                    bottom="0.3rem",
                    left="0.3rem",
                    right="0.3rem",
                ),
                position="relative",
                width="100%",
                height="100%",
                background=T.SURFACE_BG_RAISED,
            ),
            CreativeState.remove_clip_audio(key),
        ),
        rx.text(clip_gallery_vm.AUDIO_TAG, size="1", color=T.TEXT_MUTED, text_align="center"),
        spacing="1",
        width=_GALLERY_TILE,
        align_items="center",
        role="group",
        title=tile["name"],
        aria_label=tile["name"],
    )


def _ref_tile(tile: rx.Var) -> rx.Component:
    """One chosen reference in the grid, drawn by its kind."""
    return rx.match(
        tile["kind"],
        (clip_gallery_vm.IMAGE, _image_tile(tile)),
        (clip_gallery_vm.VIDEO, _video_tile(tile)),
        _audio_tile(tile),
    )


def _ref_note(text: rx.Var[str]) -> rx.Component:
    """What could not be added; a file name has no spaces, so it breaks anywhere rather
    than scroll sideways at 375 px."""
    return rx.cond(
        text != "",
        rx.box(
            callout(text, "warn"),
            style={"& *": {"overflow_wrap": "anywhere"}},
            width="100%",
            min_width="0",
        ),
    )


def _ref_upload(kind: str, upload_id: str, accept: dict, handler: object) -> rx.Component:
    """A category's «Subir …» at the end of its picker: takes only that kind (its own
    handler, and what the browser refuses is said) — or, when the category is full,
    what to do instead. No `max_files`: the handler says what did not fit."""
    full = CreativeState.clip_full_notes[kind].to(str)
    return rx.cond(
        full != "",
        _picker_note(full),
        dropzone(
            rx.button(
                rx.icon("upload", size=T.ICON_MD),
                clip_gallery_vm.UPLOAD_LABELS[kind],
                variant="soft",
                size="3",
                min_height="44px",
            ),
            upload_id=upload_id,
            accept=accept,
            max_files=0,
            multiple=True,
            max_size=_CLIP_MAX_BYTES,
            on_drop=handler(rx.upload_files(upload_id=upload_id)),  # type: ignore[operator]
            on_drop_rejected=lambda rejected: CreativeState.clip_files_rejected(kind, rejected),
            variant="bare",
        ),
    )


def _ref_category(kind: str) -> rx.Component:
    """One category inside the picker: its sources (the usual tabs, without «Subir»),
    then «Subir …» at the end, then what it could not take."""
    image, video = clip_gallery_vm.IMAGE, clip_gallery_vm.VIDEO
    if kind == image:
        sources = _media_picker("clip_images", rx.fragment(), uploads=False)
        upload = _ref_upload(
            image, "clip_images", _CLIP_IMAGE_ACCEPT, CreativeState.handle_clip_image_uploads
        )
    elif kind == video:
        sources = _media_picker("clip_videos", rx.fragment(), media_type="video", uploads=False)
        upload = _ref_upload(
            video, "clip_videos", _CLIP_VIDEO_ACCEPT, CreativeState.handle_clip_video_uploads
        )
    else:
        # no source of audio but the owner's own files
        sources = rx.text(clip_gallery_vm.AUDIO_SOURCE_NOTE, size="2", color=T.TEXT_MUTED)
        upload = _ref_upload(
            kind, "clip_audios", _CLIP_AUDIO_ACCEPT, CreativeState.handle_clip_audio_uploads
        )
    return rx.vstack(
        rx.text(clip_gallery_vm.SECTION_HINTS[kind], size="1", color=T.TEXT_MUTED),
        sources,
        upload,
        _ref_note(CreativeState.clip_notes[kind].to(str)),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _clip_gallery() -> rx.Component:
    """The references, together (round 16, Deivid: «centralizado en un botón»): every
    chosen photo, video and audio in one grid (never the reel's original), what could
    not be added in one line under it (so it stays when the picker closes), and ONE
    button that opens the picker — «Fotos · Videos · Audios» first, each with its
    sources and «Subir …» at the end."""
    picker = rx.cond(
        CreativeState.clip_picker_open,
        rx.vstack(
            rx.segmented_control.root(
                *(
                    rx.segmented_control.item(clip_gallery_vm.SECTION_TITLES[k], value=k)
                    for k in clip_gallery_vm.KINDS
                ),
                value=CreativeState.clip_picker_kind,
                on_change=CreativeState.set_clip_picker_kind,
                size="3",
                min_height="44px",
                aria_label=clip_gallery_vm.PICK_SWITCH_LABEL,
            ),
            rx.match(
                CreativeState.clip_picker_kind,
                (clip_gallery_vm.VIDEO, _ref_category(clip_gallery_vm.VIDEO)),
                (clip_gallery_vm.AUDIO, _ref_category(clip_gallery_vm.AUDIO)),
                _ref_category(clip_gallery_vm.IMAGE),
            ),
            spacing="3",
            width="100%",
            align_items="start",
            padding="0.75rem",
            border=T.BORDER,
            border_radius=T.RADIUS_CARD,
            box_sizing="border-box",
            min_width="0",
        ),
    )
    return rx.vstack(
        rx.cond(
            CreativeState.clip_reference_tiles.length() > 0,
            rx.flex(
                rx.foreach(CreativeState.clip_reference_tiles, _ref_tile),
                gap="0.75rem",
                wrap="wrap",
                width="100%",
            ),
        ),
        # with the picker open its category says it there: the line only when closed
        rx.cond(~CreativeState.clip_picker_open, _ref_note(CreativeState.clip_notes_line)),
        rx.button(
            rx.icon("images", size=T.ICON_MD),
            clip_gallery_vm.PICK_LABEL,
            variant="soft",
            size="3",
            min_height="44px",
            on_click=CreativeState.toggle_clip_picker,
            aria_expanded=rx.cond(CreativeState.clip_picker_open, "true", "false"),
        ),
        picker,
        spacing="3",
        width="100%",
        align_items="start",
    )


#: m-24820842: the replica's brand phrases — the label names what the backend really uses
#: (the Brand Kit's «Cómo invitas a comprar»), the help where they go and what never happens.
REPLICA_TEXT_LABEL = "Usar tus frases para invitar a comprar"
REPLICA_TEXT_HINT = (
    "Si el video original muestra textos (letreros, carteles o letras en pantalla), los "
    "cambiamos por tus frases. Donde no hay texto, no agregamos ninguno."
)
REPLICA_TEXT_EMPTY = (
    "Aún no tienes frases para invitar a comprar. Agrégalas en Tu marca y vuelve para "
    "usarlas en este video."
)
REPLICA_TEXT_UNREADABLE = (
    "No pudimos cargar tus frases para invitar a comprar. Recarga la página para usarlas."
)
REPLICA_TEXT_ADD = "Agregar mis frases"
#: «Agregar mis frases»: «Cómo hablas» of Tu marca, with the way back to this piece
#: (`brand_kit_editor.SECTION_PARAM` / `RETURN_PARAM`); /create keeps the replica.
REPLICA_TEXT_ADD_HREF = "/brand/kit?seccion=habla&volver=/create"
_REPLICA_TEXT_HINT_ID = "q-replica-text-hint"


def _replica_brand_text() -> rx.Component:
    """«Textos del video» on a reel replica only (m-24820842, founder 2026-11-02): OFF by
    default, the replica keeps none of the brand's wording. Without phrases in the Brand
    Kit there is no switch — it would change nothing —, only where to add them; a failed
    read says so instead of claiming there are none."""
    has_phrases = CreativeState.brand_cta_phrases.length() > 0
    switch = rx.vstack(
        # UX review (N12): the text toggles the switch too, a ≥ 44 px target with a name
        rx.el.label(
            rx.hstack(
                rx.switch(
                    checked=CreativeState.replication_brand_text,
                    on_change=CreativeState.set_replication_brand_text,
                    size="2",
                    aria_label=REPLICA_TEXT_LABEL,
                    custom_attrs={"aria-describedby": _REPLICA_TEXT_HINT_ID},
                ),
                rx.text(REPLICA_TEXT_LABEL, size="2", min_width="0"),
                spacing="2",
                align="center",
                min_height="44px",
            ),
            cursor="pointer",
        ),
        rx.text(REPLICA_TEXT_HINT, size="1", color=T.TEXT_MUTED, id=_REPLICA_TEXT_HINT_ID),
        rx.text("Tus frases:", size="1", color=T.TEXT_MUTED),
        rx.foreach(
            CreativeState.brand_cta_lines,
            lambda line: rx.text(line, size="1", color=T.TEXT_MUTED, overflow_wrap="anywhere"),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )
    empty = rx.vstack(
        callout(REPLICA_TEXT_EMPTY, "info"),
        rx.link(
            rx.button(REPLICA_TEXT_ADD, variant="soft", size="3", min_height="44px"),
            href=REPLICA_TEXT_ADD_HREF,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )
    return rx.vstack(
        _field_label("Textos del video (opcional)"),
        rx.cond(
            CreativeState.brand_cta_unreadable,
            callout(REPLICA_TEXT_UNREADABLE, "warn"),
            rx.cond(has_phrases, switch, empty),
        ),
        spacing="2",
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
    "Es un video ilustrativo, no de tu producto: sirve para un Clip o un Carrusel. Revisa "
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
    """«Descubrir reels» (QUA-223 §2, built § request 2026-10-15; «Ideas para tus reels»,
    ADR 42): the stored ideas of the brand's latest run — the reels that work best among
    the accounts it follows, of its product — read from Postgres, never paid on open
    (`discover_reels`, R7 m-24854854)."""
    return discover_view()


def _upload_zone(upload_id: str, label: str, handler: object, *, multiple: bool) -> rx.Component:
    """A compact drop zone (`ui.dropzone`) for the pictures of a piece. m-25017273: up
    to 50 MB a photo, HEIC included; what it refuses is said in Spanish
    (`photo_upload_rejected`), and while a photo goes up it shows how far it got."""
    busy = CreativeState.photo_upload_id == upload_id
    return dropzone(
        rx.cond(
            busy,
            # hidden from screen readers: the live region below already says it
            rx.box(loading_spinner("sm"), aria_hidden="true"),
            rx.icon("image-up", size=T.ICON_MD, color=T.TEXT_FAINT),
        ),
        # one live region, always mounted: only its words change, so a screen reader
        # announces «Subiendo…» / «Preparando…» (UX review m-25017273)
        rx.box(
            rx.cond(
                busy,
                rx.vstack(
                    rx.text(
                        CreativeState.photo_upload_text,
                        size="1",
                        text_align="center",
                        color=T.TEXT_MUTED,
                    ),
                    rx.text(
                        CUT_CONNECTION_HINT,
                        size="1",
                        text_align="center",
                        color=T.TEXT_FAINT,
                    ),
                    align="center",
                    spacing="1",
                ),
                rx.text(label, size="1", text_align="center", color=T.TEXT_MUTED),
            ),
            role="status",
            aria_live="polite",
            width="100%",
        ),
        upload_id=upload_id,
        accept=_IMAGE_ACCEPT,
        max_files=10 if multiple else 1,
        max_size=PHOTO_MAX_BYTES,
        multiple=multiple,
        on_drop=[
            CreativeState.begin_photo_upload(upload_id, multiple),
            handler(
                rx.upload_files(
                    upload_id=upload_id,
                    on_upload_progress=CreativeState.photo_upload_progress,
                )
            ),
        ],
        on_drop_rejected=CreativeState.photo_upload_rejected,
        # never disabled while busy: an upload the network cut never reaches the
        # handler that clears `photo_upload_id`, and the owner must be able to retry
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
        (
            # UX review 2026-11-03: no «variante» — with several logos marked, the
            # main one is named in plain words
            rx.cond(
                (item["key"] == CreativeState.brand_logo_key)
                & (CreativeState.brand_logo_reference_keys.length() > 0),
                rx.text("Principal", size="1", color=T.TEXT_MUTED, text_align="center"),
            )
            if flag == "chosen"
            else rx.fragment()
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


#: «Recursos de tu marca» (UX review 2026-11-03): one decision per block — the logo,
#: where it goes, and the other brand images folded behind «Más opciones».
BRAND_LOGO_TITLE = "Tu logo"
BRAND_LOGO_HINT = "Toca el que quieras usar. Si marcas varios, el primero es el principal."
BRAND_LOGO_PLACE_TITLE = "¿Dónde lo ponemos?"
BRAND_OTHER_IMAGES_TITLE = "Otras imágenes de tu marca (opcional)"
BRAND_OTHER_IMAGES_CAP = "Puedes elegir hasta 6."


def _logo_place_card(value: str, title: str | rx.Var[str]) -> rx.Component:
    """One answer of «¿Dónde lo ponemos?» — the same radio `choice_card` as the slide's
    product picker, no new pattern."""
    selected = CreativeState.brand_logo_usage == value
    return choice_card(
        rx.hstack(
            rx.text(title, size="2", weight="medium"),
            rx.cond(selected, choice_card_check()),
            spacing="2",
            align="center",
            justify="between",
            width="100%",
        ),
        selected=selected,
        role="radio",
        on_select=CreativeState.set_brand_logo_usage(value),
        padding="0.75rem 1rem",
        min_height="44px",
        flex="1 1 12rem",
    )


def _brand_logo_place() -> rx.Component:
    """«¿Dónde lo ponemos?»: one tap, never an instruction to type. A template's logo
    always goes in its slot, so it is said instead of asked."""
    return rx.cond(
        CreativeState.brand_logo_key != "",
        rx.cond(
            CreativeState.brief_kind == "template",
            rx.text(
                "Tu logo va en el espacio para el logo de tu plantilla.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.vstack(
                rx.text(BRAND_LOGO_PLACE_TITLE, size="1", weight="medium", color=T.TEXT_MUTED),
                rx.flex(
                    _logo_place_card("scene", CreativeState.logo_in_scene_label),
                    _logo_place_card("signature", LOGO_SIGNATURE_TEXT),
                    spacing="2",
                    wrap="wrap",
                    width="100%",
                    role="radiogroup",
                    aria_label=BRAND_LOGO_PLACE_TITLE,
                ),
                spacing="1",
                width="100%",
                align_items="start",
            ),
        ),
    )


def _brand_other_images(*, folded: bool = True) -> rx.Component:
    """«Más opciones» → the brand's other images (a mascot, a pattern, the bag…), each
    used as its note in Tu marca says. The cap is said only near it. Already inside a
    «Más opciones» (an avatar's), they are not folded a second time."""
    body = rx.vstack(
        _brand_media_picker(
            CreativeState.brand_element_choices,
            "chosen",
            CreativeState.toggle_brand_element,
            BRAND_OTHER_IMAGES_TITLE,
        ),
        rx.cond(
            CreativeState.brand_additional_resource_count >= 5,
            rx.text(BRAND_OTHER_IMAGES_CAP, size="1", color=T.TEXT_MUTED),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )
    return rx.cond(
        (CreativeState.brief_kind != "template")
        & (CreativeState.brand_element_choices.length() > 0),
        _more_options(
            CreativeState.brand_more_open,
            CreativeState.toggle_brand_more_open,
            rx.cond(
                CreativeState.brand_element_keys.length() > 0,
                "Elegiste otras imágenes de tu marca. Puedes cambiarlas aquí.",
                "Otras imágenes de tu marca, como tu mascota o tu empaque.",
            ),
            body,
        )
        if folded
        else body,
    )


def _brand_resources(*, folded: bool = True) -> rx.Component:
    """«Recursos de tu marca» (§ request 2026-10-06): the Brand Kit's files as a resource
    of their own, apart from the background and products. UX review 2026-11-03: «Tu
    logo» (a tap; the first one marked is the main one), «¿Dónde lo ponemos?», and the
    other brand images behind «Más opciones» — no variants, usage notes or counts."""
    return rx.cond(
        (CreativeState.brand_media_items.length() > 0)
        | (CreativeState.brand_resources_notice != ""),
        rx.vstack(
            _field_label("Recursos de tu marca (opcional)"),
            rx.cond(
                CreativeState.brand_resources_notice != "",
                callout(CreativeState.brand_resources_notice, "warn"),
            ),
            _brand_media_picker(
                CreativeState.brand_logo_choices,
                "chosen",
                CreativeState.toggle_brand_logo,
                BRAND_LOGO_TITLE,
                BRAND_LOGO_HINT,
            ),
            _brand_logo_place(),
            _brand_other_images(folded=folded),
            spacing="3",
            width="100%",
            align_items="start",
        ),
    )


def _images_section() -> rx.Component:
    """Background and product images — optional for the avatar videos."""
    return rx.vstack(
        _background_upload("Fondo (opcional)", BACKGROUND_UPLOAD_HINT),
        _products_upload("Producto o productos (opcional)"),
        _upload_error(),
        spacing="2",
        width="100%",
        align_items="start",
    )


#: UX review 2026-11-03: the background is not always «tu local» (a travel agency's is a
#: beach), and a phone does not drag — a tap opens the picker.
BACKGROUND_UPLOAD_HINT = (
    "Toca para subir la foto del lugar donde quieres ver tu producto: tu local, una mesa, "
    "una playa…"
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
    # always mounted, `role="alert"`: a refusal is announced the moment it appears
    return rx.box(
        rx.cond(
            CreativeState.upload_error != "",
            rx.text(CreativeState.upload_error, size="1", color=T.tone_color("error", 11)),
        ),
        role="alert",
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
    "la IA con la voz de tu marca. Es el mismo texto para todo el carrusel, así que va en "
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
        aria_label="Diapositivas del carrusel",
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
                        "Toca para elegir otra foto o arrástrala aquí",
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


#: The guide slide's product choice (live test 2026-11-03).
SLIDE_GUIDE_LABEL = "Producto que aparece en esta diapositiva"
SLIDE_GUIDE_HINT = (
    "Tu foto de inspiración solo guía cómo se ve la escena. Elige cuál de tus productos "
    "aparece en ella; si no cambias nada, usamos el primero."
)


def _slide_guide_product() -> rx.Component:
    """When the open slide's photo is an inspiration guide and the gallery has product
    photos: which one appears in it (the first by default), one tap to change it."""
    return _slide_panel(
        rx.text(SLIDE_GUIDE_LABEL, size="1", weight="medium", color=T.TEXT_MUTED),
        rx.vstack(
            rx.text(SLIDE_GUIDE_HINT, size="1", color=T.TEXT_MUTED),
            rx.flex(
                rx.foreach(
                    CreativeState.slide_guide_choices,
                    lambda item: choice_card(
                        rx.box(
                            _clip_thumb(item["key"], size="4.5rem"),
                            rx.cond(
                                item["chosen"] != "",
                                rx.box(choice_card_check(), class_name="q-cr-ghost-check"),
                            ),
                            position="relative",
                        ),
                        selected=item["chosen"] != "",
                        role="radio",
                        on_select=CreativeState.set_slide_guide_product(item["key"]),
                        padding="0.3rem",
                        width="auto",
                        aria_label=item["name"],
                        title=item["name"],
                    ),
                ),
                wrap="wrap",
                spacing="2",
                role="radiogroup",
                aria_label=SLIDE_GUIDE_LABEL,
            ),
            spacing="2",
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
            "la animación (no aparece en el carrusel).",
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
        # live test 2026-11-03: an inspiration photo is a guide — which product it shows
        rx.cond(CreativeState.slide_guide_choices.length() > 0, _slide_guide_product()),
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
                        rx.text("Ya hay un video en el carrusel.", size="1", color=T.TEXT_MUTED),
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
                "La escena en movimiento. Solo uno por carrusel.",
                "clapperboard",
                selected=source == "animated",
                on_click=CreativeState.set_slide_source("animated"),
                compact=True,
                help_text=(
                    "Generamos la escena y la animamos en un video corto de 5 o 10 segundos, "
                    "sin voz ni música. Un carrusel lleva como máximo un video."
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
            BACKGROUND_UPLOAD_HINT + " Cada diapositiva elige si la usa.",
            help_text=(
                "Una foto de tu local o del lugar donde quieres ver tu producto. Sirve para "
                "todo el carrusel: en cada diapositiva decides si se usa."
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
    return _media_result(_post_text(), title="Carrusel", icon="gallery-horizontal-end")


def _ad_image_section() -> rx.Component:
    """The advertising image: the scene, generated by Seedream (§ 2026-10-07) with the
    operator's product and/or background as references when they upload them — both
    optional since 2026-10-12, no picker: whatever is uploaded is used (`AdImageMode`
    derived in the state); the words and the logo are set on top. Its scene is asked in
    «Contexto», like every option's context (§ request 2026-10-20)."""
    return rx.vstack(
        _background_upload("Foto del fondo (opcional)", BACKGROUND_UPLOAD_HINT),
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
            ("carousel", "¿De qué trata el carrusel?"),
            ("clip", "¿Qué quieres en el clip?"),
            "¿Qué quieres en el video?",
        ),
        rx.cond(
            flyer,
            "Qué se ve, dónde y cómo se siente. Es lo único obligatorio. La imagen sale sin "
            "letras ni precios: esos van en el texto de la publicación.",
            "Un contexto general: de qué trata, qué debe transmitir, a quién le habla y "
            "cualquier detalle que importe. Es lo único obligatorio.",
        ),
        _carried_text_notice(),
        rx.cond(
            flyer,
            rx.text_area(
                value=CreativeState.ad_scene_prompt,
                on_change=CreativeState.set_ad_scene_prompt,
                id=CONTEXT_FIELD_ID,
                placeholder=(
                    "Una mano sosteniendo el vaso a la altura del pecho, de frente, con el "
                    "local desenfocado detrás y luz cálida…"
                ),
                width="100%",
                rows="5",
                max_length=600,
            ),
            rx.text_area(
                value=CreativeState.brief_topic,
                on_change=CreativeState.set_brief_topic,
                id=CONTEXT_FIELD_ID,
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


NEW_VERSION_LABEL = "Hacer otra versión de esta"
NEW_PIECE_LABEL = "Crear una publicación nueva"
#: review 2026-11-04 B8: «Borrarlo» read alone under the notice — say what goes.
CLEAR_CARRIED_TEXT_LABEL = "Borrar este texto"
CARRIED_TEXT_NOTICE = "Este texto viene de tu publicación anterior."


def _carried_text_notice() -> rx.Component:
    """UX review 2026-11-03: after «Hacer otra versión de esta» the owner changed the
    kind and the last piece's text is still in the field — said, with one way out."""
    return rx.cond(
        CreativeState.carried_text_notice,
        rx.vstack(
            callout(CARRIED_TEXT_NOTICE, "info"),
            rx.button(
                rx.icon("eraser", size=T.ICON_SM),
                CLEAR_CARRIED_TEXT_LABEL,
                variant="soft",
                color_scheme="gray",
                size="2",
                min_height="44px",
                on_click=CreativeState.clear_carried_text,
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


#: m-25017274: what «Mejorar mi texto» says around its three cards.
ENHANCE_LABEL = "Mejorar mi texto"
ENHANCE_BUSY_LABEL = "Mejorando…"
ENHANCE_HINT = (
    "Te proponemos versiones con lo que sabemos de tu marca, sin inventar precios ni "
    "promociones. No gasta creaciones."
)
ENHANCE_PICK_TITLE = "Elige una versión"
ENHANCE_PICK_HINT = "Al tocarla, la copiamos arriba en tu texto. Puedes cambiarla antes de crear."
ENHANCE_AGAIN_LABEL = "Ver otras versiones"
ENHANCE_RESTORE_LABEL = "Volver a mi texto"


def _context_version_card(version: rx.Var[dict[str, str]], index: rx.Var[int]) -> rx.Component:
    """One version: its approach in small letters over the whole text, a radio card (the
    design system's `choice_card`) that fills the field when tapped."""
    selected = CreativeState.context_chosen == index
    return choice_card(
        rx.vstack(
            rx.hstack(
                rx.text(version["label"], size="1", weight="medium", color=T.TEXT_MUTED),
                rx.cond(selected, choice_card_check()),
                spacing="2",
                align="center",
                justify="between",
                width="100%",
            ),
            rx.text(version["text"], size="2", text_align="left", white_space="normal"),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        selected=selected,
        role="radio",
        disabled=CreativeState.context_enhancing,
        on_select=CreativeState.choose_context_version(index),
        padding="0.75rem 1rem",
        min_height="44px",
        width="100%",
        text_align="left",
    )


def _context_versions() -> rx.Component:
    """The cards of the last press (up to three), «Ver otras versiones» and the way back to the
    operator's own words (m-25017274). One column: they read whole on a phone. Once the
    owner edits the text they go (UX review): only «Mejorar mi texto» stays, from the
    new words. A polite live region, so a screen reader hears the cards arrive."""
    enhancing = CreativeState.context_enhancing
    return rx.el.div(
        rx.cond(
            (CreativeState.context_versions.length() > 0) & ~CreativeState.context_text_edited,
            _context_versions_block(enhancing),
        ),
        aria_live="polite",
        width="100%",
    )


def _context_versions_block(enhancing: rx.Var[bool]) -> rx.Component:
    return rx.vstack(
        rx.text(ENHANCE_PICK_TITLE, size="2", weight="medium"),
        rx.text(ENHANCE_PICK_HINT, size="1", color=T.TEXT_MUTED),
        rx.el.div(
            rx.foreach(CreativeState.context_versions, _context_version_card),
            role="radiogroup",
            aria_label=ENHANCE_PICK_TITLE,
            style={"display": "flex", "flexDirection": "column", "gap": "0.5rem"},
            width="100%",
        ),
        rx.hstack(
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                ENHANCE_AGAIN_LABEL,
                variant="soft",
                size="2",
                radius=_CONTROL_RADIUS,
                min_height="44px",
                loading=enhancing,
                on_click=CreativeState.enhance_context(True),
            ),
            spacing="3",
            align="center",
            wrap="wrap",
            width="100%",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _context_ai_tools() -> rx.Component:
    """«Mejorar mi texto» (§ request 2026-10-20; three versions since m-25017274): the
    text above rewritten three ways with the Brand Kit and the «Datos clave» — no invented
    facts — before anything is generated. The operator's text stays until a card is
    chosen, and «Volver a mi texto» brings it back."""
    enhancing = CreativeState.context_enhancing
    return rx.vstack(
        # right under the text field (UX review): after a card is chosen on a phone the
        # field is in view, and the way back sits next to it; it stays after an edit
        rx.cond(
            (CreativeState.context_before_enhance != "")
            & ~CreativeState.context_is_original
            & ~enhancing,
            rx.button(
                rx.icon("undo-2", size=T.ICON_SM),
                ENHANCE_RESTORE_LABEL,
                variant="ghost",
                color_scheme="gray",
                size="2",
                min_height="44px",
                on_click=CreativeState.undo_enhance_context,
            ),
        ),
        rx.cond(
            # with cards on screen it comes back only once the text was edited: a press
            # then starts from the new words (otherwise «Ver otras versiones» is the way)
            (CreativeState.context_versions.length() > 0) & ~CreativeState.context_text_edited,
            rx.fragment(),
            rx.hstack(
                rx.button(
                    rx.icon("sparkles", size=T.ICON_SM),
                    rx.cond(enhancing, ENHANCE_BUSY_LABEL, ENHANCE_LABEL),
                    variant="soft",
                    size="2",
                    radius=_CONTROL_RADIUS,
                    min_height="44px",
                    loading=enhancing,
                    on_click=CreativeState.enhance_context(False),
                ),
                rx.text(
                    ENHANCE_HINT,
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
        ),
        _context_versions(),
        rx.cond(
            CreativeState.context_enhance_error != "",
            callout(CreativeState.context_enhance_error, "warn"),
        ),
        rx.cond(
            # it names «estas versiones»: it goes with the cards
            (CreativeState.context_enhance_note != "")
            & (CreativeState.context_versions.length() > 0)
            & ~CreativeState.context_text_edited,
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
                rx.vstack(
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
                    # VE-21 U1: the seconds this length will use, before creating it
                    rx.cond(
                        CreativeState.video_seconds_notice != "",
                        rx.text(
                            CreativeState.video_seconds_notice,
                            size="1",
                            color=T.TEXT_MUTED,
                            aria_live="polite",
                        ),
                    ),
                    spacing="2",
                    width="100%",
                    align_items="start",
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


#: UX review 2026-11-03: the words are the opening line and the invitation to buy of the
#: text Qualify proposes (`qualify_creative.subtitles.clip_cues`), laid on the clip when
#: it is created — not words the owner wrote.
CLIP_SUBTITLES_LABEL = "Poner en el video la frase inicial y la invitación a comprar"
CLIP_SUBTITLES_HINT = (
    "Con la letra y los colores de tu marca. Las ves en el video antes de aprobarlo."
)
_CLIP_SUBTITLES_HINT_ID = "q-clip-subtitles-hint"


def _clip_subtitles_switch() -> rx.Component:
    """The clip's subtitles (founder, 2026-11-03): off by default; the words are laid
    over the finished clip, never drawn by the video model."""
    return rx.vstack(
        # UX review (N12): the text toggles the switch too, a ≥ 44 px target with a name
        rx.el.label(
            rx.hstack(
                rx.switch(
                    checked=CreativeState.clip_subtitles,
                    on_change=CreativeState.set_clip_subtitles,
                    size="2",
                    aria_label=CLIP_SUBTITLES_LABEL,
                    custom_attrs={"aria-describedby": _CLIP_SUBTITLES_HINT_ID},
                ),
                rx.text(CLIP_SUBTITLES_LABEL, size="2", min_width="0"),
                spacing="2",
                align="center",
                min_height="44px",
            ),
            cursor="pointer",
        ),
        rx.text(CLIP_SUBTITLES_HINT, size="1", color=T.TEXT_MUTED, id=_CLIP_SUBTITLES_HINT_ID),
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
                            "De la Galería: ", rx.text.strong(CreativeState.brief_product_ref)
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
        "La foto con la que empieza el clip y, si quieres, con la que termina.",
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
                        _brand_resources(folded=False),
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
        # A clip has the same resources in its own «Referencias» view.
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
    a phone (`.q-cr-highlight-row`) — and a ≥ 44 px «Quitar».

    The chosen catalog product's price row (`product` marker, founder 2026-11-04) has
    no «Quitar» and a fixed «Precio»; only its value is editable, with a note below
    (`remove_highlight`/`set_highlight` refuse the rest server-side too). An owner row
    named «Precio» beside it gets a note too: the brief keeps the catalog's price."""
    key_id = f"q-cr-hl-key-{index}"
    value_id = f"q-cr-hl-value-{index}"
    hint_id = f"q-cr-hl-hint-{index}"
    from_catalog = rx.cond(row["product"], True, False)
    # «Viene de la Galería…» (or, edited, what creating does to it) under the
    # catalog row, «Ya tienes el precio…» under an
    # owner «Precio» beside it (`highlight_notes`); "" = no note
    note = CreativeState.highlight_notes[index]
    has_note = note != ""

    def value_input(**props: str) -> rx.Component:
        return rx.input(
            id=value_id,
            value=row["value"],
            on_change=lambda value: CreativeState.set_highlight(index, "value", value),
            placeholder="Ej.: 18.900, 20 %, viernes 31",
            max_length=200,
            size="3",
            width="100%",
            **props,
        )

    fields = rx.hstack(
        rx.box(
            rx.cond(
                from_catalog,
                # the catalog row's name is fixed: plain text, never an input box
                rx.vstack(
                    rx.el.span("¿Qué dato?", class_name="q-cr-highlight-label"),
                    rx.text(PRICE_FACT_LABEL, size="3", class_name="q-cr-highlight-fixed"),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
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
            ),
            _highlight_field(
                "¿Cuánto o cuál?",
                value_id,
                # described by the note only when there is one: no empty attribute
                rx.cond(
                    has_note,
                    value_input(aria_describedby=hint_id),
                    value_input(),
                ),
            ),
            class_name="q-cr-highlight-row",
            flex="1",
            min_width="0",
        ),
        rx.cond(
            from_catalog,
            # same width as «Quitar», so the catalog row's fields line up with the rest
            rx.box(class_name="q-cr-highlight-spacer", aria_hidden="true"),
            rx.icon_button(
                rx.icon("x", size=16),
                on_click=CreativeState.remove_highlight(index),
                variant="ghost",
                color_scheme="gray",
                size="3",
                aria_label="Quitar este dato",
                flex_shrink="0",
            ),
        ),
        spacing="2",
        width="100%",
        align="end",
    )
    return rx.vstack(
        fields,
        rx.cond(has_note, rx.text(note, id=hint_id, size="1", color=T.TEXT_MUTED)),
        spacing="1",
        width="100%",
        align_items="start",
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
    on_submit: rx.event.EventHandler,
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
        # live test 2026-11-03: a form — Intro / «Listo» / «Agregar» send the phrase WITH
        # the submit, and the form's own submit handler empties the field in the SAME
        # tick (`reset_on_submit` → `$form.reset()`, before any server reply). The field
        # is uncontrolled (no `value`, never re-keyed), so no server update can put an
        # old phrase back while the owner types the next one («…WhatsAppCarne…»).
        rx.form(
            rx.hstack(
                rx.input(
                    name="phrase",
                    on_change=on_change,
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
                    type="submit",
                    variant="soft",
                    size="3",
                    # never disabled by the draft: a disabled submit button stops Intro
                    # from submitting the form (HTML implicit submission) — live regression
                    # 2026-11-03; an empty phrase is ignored by the handler
                    disabled=full,
                    # a click must not take the focus: the owner keeps typing in the field
                    on_mouse_down=rx.prevent_default,
                ),
                spacing="2",
                width="100%",
            ),
            on_submit=on_submit,
            reset_on_submit=True,
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
            CreativeState.submit_must_mention,
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
            CreativeState.submit_must_avoid,
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


def _reel_wait_button(label: str, on_click: rx.EventHandler, variant: str) -> rx.Component:
    return rx.button(
        label,
        variant=variant,
        size="3",
        min_height="44px",
        width=["100%", "auto"],
        on_click=on_click,
    )


def _reel_wait_actions() -> rx.Component:
    """The wait's ways forward: «Elegir otro reel» (back to the ideas, as the head's
    «‹») and «Armar sin el reel» (forget the analysis, keep the piece)."""
    return rx.flex(
        rx.cond(
            CreativeState.reel_wait_pick_other,
            _reel_wait_button(reel_wait_vm.PICK_OTHER_LABEL, CreativeState.exit_create, "outline"),
        ),
        rx.cond(
            # also whenever no loop is polling (a restart, a lost connection): a wait
            # that froze always has a way forward
            CreativeState.reel_wait_without
            | (CreativeState.reel_wait_pending & ~CreativeState.reel_poll_live),
            _reel_wait_button(reel_wait_vm.WITHOUT_LABEL, CreativeState.reel_go_without, "soft"),
        ),
        gap="0.75rem",
        wrap="wrap",
        width="100%",
    )


def _reel_wait_bar() -> rx.Component:
    """«Mirando el reel»: the stage over the bar (`progress_panel`, never a spinner),
    with the real value when the stage informs it and a creeping bar otherwise."""
    steps = CreativeState.reel_wait_steps
    return rx.cond(
        CreativeState.reel_wait_value >= 0,
        progress_panel(
            reel_wait_vm.WAIT_TITLE,
            reel_wait_vm.WAIT_DETAIL,
            value=CreativeState.reel_wait_value,
            steps=steps,
        ),
        progress_panel(
            reel_wait_vm.WAIT_TITLE, reel_wait_vm.WAIT_DETAIL, steps=steps, creep_seconds=90
        ),
    )


# -- UI-3 (m-24921077): the reel's parts in «Orden del clip» ----------------------------

#: A part's card (round 12, Deivid: «menos juntas», centred on a phone): one per row,
#: up to 18rem and centred below `sm`; 9.5rem side by side from `sm` up.
_PART_CARD_W = ["100%", "9.5rem"]
_PART_UNIT_W = ["min(100%, 18rem)", "auto"]
#: The why line: the description's clamp (`q-cr-product-name`) at 3 lines.
_WHY_CLAMP = {"WebkitLineClamp": "3"}
#: Round 15 (Deivid: «no las quiero»): no arrows on the cards. A keyboard user still
#: sees where the focus is.
_CARD_FOCUS = {"&:focus-visible": {"outline": "2px solid var(--accent-8)", "outline_offset": "2px"}}
#: The parts' keyboard (round 15): ←/→ with no modifier on a focused card press its
#: hidden «move» buttons (`data-part-move`) — only those keys reach the server, and the
#: page does not scroll with them. Nothing of it is on screen; a stuck part has none.
_PART_KEYS_JS = """
(function () {
  if (window.__qPartKeysV2) return;
  window.__qPartKeysV2 = true;
  document.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var card = e.target.closest && e.target.closest(".q-part-card");
    if (!card) return;
    e.preventDefault();
    var move = card.querySelector(
      '[data-part-move="' + (e.key === "ArrowLeft" ? "up" : "down") + '"]'
    );
    if (move) move.click();
  });
})();
"""


def _small_remove(on_click: rx.event.EventSpec, label: rx.Var[str] | str) -> rx.Component:
    """The ✕ of a tile (round 12, Deivid: «baje el tamaño a la x»): a 14 px muted icon on
    a 24 px translucent chip, inside a transparent 44 × 44 hit area in the corner."""
    return rx.el.button(
        rx.center(
            rx.icon("x", size=14),
            width="24px",
            height="24px",
            border_radius="9999px",
            background="rgba(0, 0, 0, 0.45)",
            color="rgba(255, 255, 255, 0.85)",
        ),
        type="button",
        on_click=on_click,
        aria_label=label,
        title=label,
        position="absolute",
        top="0",
        right="0",
        width="44px",
        height="44px",
        display="flex",
        align_items="center",
        justify_content="center",
        background="transparent",
        border="none",
        padding="0",
        cursor="pointer",
    )


def _part_move(direction: str, on_click: rx.event.EventSpec) -> rx.Component:
    """A hidden «move» button the keyboard script presses (never shown, never in the
    reading order): the server's `move_reel_part_up` / `move_reel_part_down`."""
    return rx.el.button(
        type="button",
        on_click=on_click,
        tab_index=-1,
        aria_hidden="true",
        display="none",
        custom_attrs={"data-part-move": direction},
    )


def _part_picture(row: rx.Var) -> rx.Component:
    """The part's scene across the card, square, cropped to fill: a frame of its cuts
    (`/avatar/frame/…`, signed; decorative, empty alt — the item's label names the
    part), or its film glyph while no frame is kept."""
    return rx.cond(
        row["thumb"] != "",
        rx.image(
            src=BACKEND_BASE + row["thumb"],
            alt="",
            width="100%",
            height="100%",
            object_fit="cover",
            loading="lazy",
        ),
        rx.center(
            rx.icon("film", size=T.ICON_MD, color=T.TEXT_MUTED),
            width="100%",
            height="100%",
            aria_hidden="true",
        ),
    )


def _with_n(template: str, n: rx.Var) -> rx.Var:
    """A `{n}` copy template filled with a row's number (a Var)."""
    before, after = template.split("{n}")
    return before + n + after


def _part_scene(row: rx.Var) -> rx.Component:
    """m-24992893: the part's scene, which plays ITS stretch of the original reel in
    place (`ui.clip_player`: one stored copy, `#t=start,end`, muted, a sound toggle)
    when the reel's copy is kept; just the scene when it is not (`source` "")."""
    n = row["index"]
    return rx.cond(
        row["source"] != "",
        clip_player(
            _part_picture(row),
            src=BACKEND_BASE + row["source"] + "#t=" + row["start_s"] + "," + row["end_s"],
            start=row["start_s"],
            end=row["end_s"],
            label=_with_n(reel_parts_vm.PLAY_ORIGINAL_TEXT, n),
            pause_label=_with_n(reel_parts_vm.PAUSE_PART_TEXT, n),
            broken_text=reel_parts_vm.ORIGINAL_GONE_TEXT,
            key=row["key"],
        ),
        _part_picture(row),
    )


def _part_item(row: rx.Var) -> rx.Component:
    """One part as a card: its scene with «Parte n · s s» («↳ Parte n · s s» when it is
    stuck to the one before) and the small ✕ of «Quitar»; under it what it shows (two
    lines) and why (three) — the form and «Aparece una persona» are in the item's label.
    It is reordered by dragging; with the focus on it, ←/→ move it too (nothing shown)."""
    key = row["key"]
    movable = row["movable"] != ""
    picture = rx.box(
        _part_scene(row),
        _strip_badge(
            rx.text(row["label"], size="1", weight="bold"), bottom="0.3rem", left="0.3rem"
        ),
        _small_remove(CreativeState.remove_reel_part(key), row["remove_label"]),
        position="relative",
        width="100%",
        aspect_ratio="1 / 1",
        overflow="hidden",
        border_radius=T.RADIUS_CONTROL,
        background=T.SURFACE_BG_RAISED,
    )
    return rx.flex(
        picture,
        rx.cond(
            row["description"] != "",
            # Deivid, 2026-11-10: cut at two lines, «Ver más» opens it in place
            expandable_text(
                row["description"],
                expanded=CreativeState.reel_expanded.contains(key),
                on_toggle=CreativeState.toggle_reel_part_text(key),
                id=REEL_PART_CARD_ID + "-text-" + key,
            ),
            rx.text(row["describe"], size="1", color=T.TEXT_MUTED),
        ),
        rx.cond(
            row["why"] != "",
            rx.text(
                row["why"],
                size="1",
                color=T.TEXT_MUTED,
                class_name="q-cr-product-name",
                style=_WHY_CLAMP,
            ),
        ),
        rx.cond(
            movable,
            rx.fragment(
                _part_move("up", CreativeState.move_reel_part_up(key)),
                _part_move("down", CreativeState.move_reel_part_down(key)),
            ),
        ),
        rx.button(
            "Cambiar",
            variant="soft",
            size="2",
            min_height="44px",
            on_click=CreativeState.edit_reel_part(key),
            id=part_editor_vm.CHANGE_ID + key,
            aria_label="Cambiar la parte " + row["index"],
            aria_disabled=CreativeState.reel_plan_edit_reason != "",
            aria_describedby="q-part-plan-locked",
            # UI-4: pinned to the card's foot, level across the row (`.q-part-card`)
            class_name="q-part-change",
            margin_top="auto",
        ),
        id=REEL_PART_CARD_ID + "-" + key,
        role="listitem",
        aria_label=row["aria"],
        tab_index=0,
        custom_attrs={
            "aria-keyshortcuts": rx.cond(movable, "ArrowLeft ArrowRight", ""),
            # `_PART_KEYS_JS` finds the card by it
            "data-part-key": key,
        },
        class_name="q-part-card",
        direction="column",
        align_items="start",
        gap="0.25rem",
        width=_PART_CARD_W,
        padding="0.25rem",
        border=T.BORDER,
        border_radius=T.RADIUS_CONTROL,
        style=_CARD_FOCUS,
    )


def _part_unit(unit: rx.Var) -> rx.Component:
    """A unit — a part and the «Sigue a la anterior» parts stuck to it, inside a soft
    border (stacked on a phone, side by side from `sm` up) — as ONE drag card of
    `slide-drag.js` (group `reel-parts`; the drop names the unit), so a pair travels
    together. The card is `role="none"`: the list's items stay the PARTS («Parte n de N»
    counts right)."""
    head = unit[0]
    return _SlideCard.create(
        rx.foreach(unit, _part_item),
        on_drag_start=CreativeState.start_reel_part_drag(head["unit"]),
        on_drop=CreativeState.drop_reel_part(head["unit"]),
        custom_attrs={
            "data-slide-group": "reel-parts",
            "data-slide-key": head["key"],
            "role": "none",
        },
        display="flex",
        flex_direction=["column", "row"],
        flex_wrap="wrap",
        gap=["1.25rem", "0.5rem"],
        align_items="stretch",
        width=_PART_UNIT_W,
        max_width="100%",
        margin_x=["auto", "0"],
        border=rx.cond(unit.length() > 1, T.BORDER, "none"),
        border_radius=T.RADIUS_CONTROL,
        padding=rx.cond(unit.length() > 1, "0.25rem", "0"),
        class_name="q-cr-slide--drag",
    )


def _parts_live() -> rx.Component:
    """The list's one polite live region: «Quitaste la parte n. Deshacer» (N3) — the
    keyboard lands on «Deshacer» after «Quitar» — or «Moviste la parte n: ahora es la parte m.»."""
    return rx.box(
        rx.cond(
            CreativeState.reel_undo_text != "",
            rx.flex(
                rx.text(CreativeState.reel_undo_text, size="2"),
                rx.button(
                    reel_parts_vm.UNDO_LABEL,
                    variant="ghost",
                    size="3",
                    min_height="44px",
                    on_click=CreativeState.undo_reel_part,
                    id=REEL_PART_UNDO_ID,
                ),
                gap="0.5rem",
                align="center",
                wrap="wrap",
            ),
            rx.cond(
                CreativeState.reel_move_text != "",
                rx.text(CreativeState.reel_move_text, size="2"),
            ),
        ),
        rx.cond(
            CreativeState.reel_parts_notice != "",
            rx.text(CreativeState.reel_parts_notice, size="2"),
        ),
        aria_live="polite",
        width="100%",
    )


def _parts_usage() -> rx.Component:
    """«Lo que usa de tu mes» — vistas previas and seconds of video, never money; it
    informs and never holds «Siguiente»."""
    return rx.cond(
        CreativeState.reel_usage_lines.length() > 0,
        rx.vstack(
            rx.text(reel_parts_vm.USAGE_TITLE, size="2", weight="medium"),
            rx.foreach(
                CreativeState.reel_usage_lines,
                lambda line: rx.text(line, size="2", color=T.TEXT_MUTED),
            ),
            spacing="1",
            border=T.BORDER,
            border_radius=T.RADIUS_CONTROL,
            padding="0.75rem 1rem",
            width="100%",
            align_items="start",
        ),
    )


def _parts_head() -> rx.Component:
    """«Orden del clip», «4 partes · 18 s», the hint and the reel it is based on."""
    href = CreativeState.reel_source_href
    return rx.vstack(
        rx.flex(
            _field_label(reel_parts_vm.LIST_TITLE),
            rx.cond(
                href != "",
                rx.link(
                    rx.text(
                        CreativeState.reel_based_on_text,
                        as_="span",
                        display=["none", "inline"],
                    ),
                    rx.text(reel_parts_vm.REEL_LINK_SHORT, as_="span", display=["inline", "none"]),
                    rx.icon("external-link", size=T.ICON_SM),
                    href=href,
                    is_external=True,
                    size="2",
                    display="inline-flex",
                    align_items="center",
                    gap="0.25rem",
                    min_height="44px",
                ),
            ),
            justify="between",
            align="center",
            gap="0.5rem",
            wrap="wrap",
            width="100%",
        ),
        # one part: its length and, for a reel of one scene, why (nothing to order)
        rx.cond(
            CreativeState.reel_parts_count > 1,
            rx.text(
                CreativeState.reel_parts_summary + ". " + reel_parts_vm.LIST_HELP,
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.cond(
                CreativeState.reel_parts_count == 1,
                rx.text(CreativeState.reel_parts_summary + ".", size="1", color=T.TEXT_MUTED),
            ),
        ),
        rx.cond(
            CreativeState.reel_single_part & (CreativeState.reel_parts_count == 1),
            rx.text(
                reel_wait_vm.SINGLE_PART_TITLE + " " + reel_wait_vm.SINGLE_PART_BODY,
                size="1",
                color=T.TEXT_MUTED,
            ),
        ),
        spacing="0",
        width="100%",
        align_items="start",
    )


def _clip_parts_block() -> rx.Component:
    """UI-3 round 6 (Deivid, 2026-11-09): with a reel's plan, «Orden del clip» holds its
    PARTS instead of the strip's files — one under the other (also at 375 px, never
    sideways), dragged or moved with «Antes» / «Después». «Siguiente» never waits."""
    return rx.vstack(
        _parts_head(),
        rx.text(
            CreativeState.reel_plan_edit_reason,
            id="q-part-plan-locked",
            size="1",
            color=T.TEXT_MUTED,
        ),
        # m-24921079: empty parts (with UI-4's «Prefiero armarlas yo»): none says what it shows
        rx.cond(CreativeState.reel_plan_empty, parts_empty_notice()),
        _parts_live(),
        rx.cond(
            CreativeState.reel_parts_count > 0,
            rx.flex(
                rx.foreach(CreativeState.reel_part_units, _part_unit),
                _script_on_mount(_SLIDE_DRAG_JS),
                _script_on_mount(_PART_KEYS_JS),
                clip_player_script(),
                role="list",
                aria_label=reel_parts_vm.LIST_TITLE,
                wrap="wrap",
                # every unit as tall as its row: «Cambiar» lines up at the cards' foot
                align_items="stretch",
                # round 12: one part per row, centred, with air on a phone
                gap=["1.25rem", "1rem"],
                justify=rx.breakpoints(initial="center", sm="start"),
                position="relative",
                width="100%",
                min_width="0",
            ),
            rx.vstack(
                rx.text(reel_parts_vm.EMPTY_TITLE, size="3", weight="medium"),
                rx.text(reel_parts_vm.EMPTY_BODY, size="2", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
                width="100%",
            ),
        ),
        # m-24992893: «Ya no podemos mostrar el reel original…», written by the clips'
        # script once the stored reel cannot be played (empty and hidden until then)
        clip_player_notice(),
        rx.vstack(
            rx.button(
                rx.icon("plus", size=T.ICON_SM),
                "Añadir parte",
                variant="soft",
                min_height="44px",
                on_click=CreativeState.add_reel_part,
                aria_disabled=CreativeState.reel_add_reason != "",
                aria_describedby="q-part-add-reason",
                id=part_editor_vm.ADD_ID,
            ),
            rx.text(
                CreativeState.reel_add_reason, size="1", color=T.TEXT_MUTED, id="q-part-add-reason"
            ),
            spacing="1",
            width="100%",
            align_items="start",
        ),
        _script_on_mount(_asset_script("part-editor.js")),
        part_editor(
            _part_media_editor("image"), _part_media_editor("video"), _part_media_editor("audio")
        ),
        _parts_usage(),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _part_media_editor(kind: str) -> rx.Component:
    image, video = kind == "image", kind == "video"
    held = (
        CreativeState.reel_edit_images
        if image
        else CreativeState.reel_edit_videos
        if video
        else CreativeState.reel_edit_audios
    )
    handler = (
        CreativeState.handle_part_image_uploads
        if image
        else CreativeState.handle_part_video_uploads
        if video
        else CreativeState.handle_part_audio_uploads
    )
    accept = _CLIP_IMAGE_ACCEPT if image else _CLIP_VIDEO_ACCEPT if video else _CLIP_AUDIO_ACCEPT
    target = "part_images" if image else "part_videos" if video else "part_audios"
    upload = _clip_drop(
        target,
        "Agregar fotos" if image else "Agregar video" if video else "Agregar audio",
        "Hasta 9 fotos." if image else "Hasta 3 videos." if video else "Hasta 3 audios.",
        accept,
        handler,
        max_files=9 if image else 3,
    )

    def item(file: rx.Var) -> rx.Component:
        return rx.vstack(
            _clip_thumb(file["key"])
            if image
            else rx.video(
                src=_key_src(file["key"]),
                controls=True,
                auto_play=False,
                loop=False,
                width="100%",
                max_height="8rem",
            )
            if video
            else rx.audio(src=_key_src(file["key"]), controls=True, width="100%"),
            rx.text(file["name"], size="1", style={"overflow_wrap": "anywhere"}),
            rx.button(
                "Quitar foto" if image else "Quitar video" if video else "Quitar audio",
                type="button",
                variant="ghost",
                min_height="44px",
                # the accessible name starts with the visible label (WCAG 2.5.3)
                aria_label=(
                    "Quitar foto " if image else "Quitar video " if video else "Quitar audio "
                )
                + file["name"].to(str),
                on_click=CreativeState.remove_part_media(kind, file["key"]),
            ),
            width="6rem" if image else "100%",
            max_width="100%",
            min_width="0",
            spacing="1",
        )

    return rx.vstack(
        rx.flex(rx.foreach(held, item), gap="0.5rem", wrap="wrap", width="100%"),
        _media_picker(target, upload, media_type=kind) if kind != "audio" else upload,
        spacing="2",
        width="100%",
        align_items="start",
        min_width="0",
    )


def _reel_wait_view() -> rx.Component:
    """UI-2 (m-24921076): step 2's wait for the reel's analysis, and how it ended. Only
    for a piece from «Hacer uno parecido» with an analysis in play; mounting it starts
    the poll (one at a time), unmounting stops it."""
    waiting = CreativeState.reel_wait_pending
    error = CreativeState.reel_wait_phase == reel_wait_vm.PHASE_ERROR
    return rx.box(
        rx.cond(
            waiting,
            _card(
                _reel_wait_bar(),
                rx.cond(
                    CreativeState.reel_wait_queue_note != "",
                    rx.text(
                        CreativeState.reel_wait_queue_note,
                        size="2",
                        color=T.TEXT_MUTED,
                        text_align="center",
                        width="100%",
                    ),
                ),
                rx.cond(
                    CreativeState.reel_wait_slow,
                    rx.vstack(
                        callout(CreativeState.reel_wait_notice, "warn"),
                        _reel_wait_actions(),
                        spacing="3",
                        width="100%",
                    ),
                    rx.cond(~CreativeState.reel_poll_live, _reel_wait_actions()),
                ),
                # the wait is still on screen: keeps the poll alive, restarts it after a
                # reconnect that did not remount the view (browser-side timer)
                rx.moment(
                    interval=REEL_WAIT_HEARTBEAT_MS,
                    on_change=lambda _tick: CreativeState.reel_wait_heartbeat,
                    display="none",
                ),
            ),
            rx.cond(
                error,
                _card(
                    rx.text(CreativeState.reel_wait_error_title, size="3", weight="medium"),
                    rx.text(CreativeState.reel_wait_error_body, size="2", color=T.TEXT_MUTED),
                    _reel_wait_actions(),
                    role="alert",
                ),
                # ready: the plan's parts live in «Orden del clip» (UI-3 round 6)
                rx.fragment(),
            ),
        ),
        width="100%",
        on_mount=CreativeState.poll_reel_analysis,
        on_unmount=CreativeState.leave_reel_wait,
    )


def _step_show() -> rx.Component:
    """① Qué mostrar: Avatar's types, the references, the presenter and the kind's own
    section — everything a kind cannot do without (CREAR-2). From «Hacer uno parecido»,
    the reel's analysis wait goes first (UI-2)."""
    usual = rx.vstack(
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
    # UI-2: while the reel is being looked at (or could not be) the wait is the whole
    # step (mockup §3a); a normal Clip and a finished analysis show the usual step
    return rx.vstack(
        rx.cond(CreativeState.reel_wait_shown, _reel_wait_view()),
        rx.cond(CreativeState.reel_wait_takes_step, rx.fragment(), usual),
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
            CreativeState.rules_hint,
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
            # live test 2026-11-03: a campaign kept by «Crear otra» is named here
            CreativeState.gen_campaign_hint,
            rx.vstack(
                # § request 2026-10-23: «generar el clip con audio» — on by default
                rx.cond(
                    is_clip,
                    _audio_switch(
                        checked=CreativeState.clip_audio,
                        on_change=CreativeState.set_clip_audio,
                    ),
                ),
                # founder, 2026-11-03: the copy «como subtítulos», laid by us after the video
                rx.cond(is_clip, _clip_subtitles_switch()),
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
        # live test 2026-11-03: «Basado en el reel» opens the original reel
        rx.cond(
            item["href"] != "",
            rx.link(
                item["value"],
                href=item["href"],
                is_external=True,
                size="2",
                class_name="q-cr-summary-value",
            ),
            rx.cond(
                item["thumb"] != "",
                # UX review 2026-11-03: the owner knows their logo by sight, not by name
                rx.hstack(
                    rx.image(
                        src=BACKEND_BASE + item["thumb"],
                        alt="",
                        width="2.5rem",
                        height="2.5rem",
                        min_width="2.5rem",
                        object_fit="contain",
                        padding="0.2rem",
                        background=T.SURFACE_BG_RAISED,
                        border=T.BORDER,
                        border_radius=T.RADIUS_CONTROL,
                    ),
                    rx.text(item["value"], size="2", min_width="0"),
                    spacing="2",
                    align="center",
                    class_name="q-cr-summary-value",
                ),
                rx.text(item["value"], size="2", class_name="q-cr-summary-value"),
            ),
        ),
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
        rx.cond(CreativeState.reel_plan_shown, _parts_review_text()),
        rx.vstack(
            rx.foreach(CreativeState.gen_summary, _summary_row),
            spacing="0",
            width="100%",
        ),
        rx.cond(CreativeState.reel_plan_shown, _parts_review()),
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


def brand_fix_link() -> rx.Component:
    """«Ir a Tu marca» under a refusal whose fix is there (UX review 2026-11-03 #4)."""
    return rx.link(
        rx.button(
            rx.icon("palette", size=T.ICON_SM),
            BRAND_FIX_LABEL,
            variant="soft",
            size="2",
            min_height="44px",
        ),
        href=BRAND_FIX_ROUTE,
    )


def _create_error() -> rx.Component:
    """Why «Crear» refused, and — when the fix is in «Tu marca» — the way there."""
    return rx.cond(
        CreativeState.create_error != "",
        rx.vstack(
            callout(CreativeState.create_error, "error"),
            rx.cond(CreativeState.create_error_brand_fix, brand_fix_link()),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


def _view_nav() -> rx.Component:
    """The view's footer: Atrás, and Siguiente — or, on the last view, Generar, the
    form's one solid action (§5.5), with what still keeps it from generating above it."""
    return rx.vstack(
        _create_error(),
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


# -- UI-6 (m-24921081): «Revisa y crea» por partes ---------------------------------------
#
# The main action, «Crear las n partes», is the step frame's own primary (its label,
# its disabled state and what it does come from `CreativeState.create_primary_*` /
# `create_continue`). The body, in order: the summary in words, the rows with «Editar»
# (`gen_summary`), «Lo que usa de tu mes», «Probar solo la parte 1» with what it uses,
# and — when the parts cannot be created — why, with the way out (and «Pedir más a
# Qualify» right under a counter at 0).

#: The line that says why the parts cannot be created (the secondary's
#: `aria-describedby`).
REEL_CREATE_REASON_ID = "reel-create-reason"


def _try_first_button() -> rx.Component:
    """«Probar solo la parte 1». Disabled it stays focusable (`aria-disabled`) and
    sends nothing; `aria-describedby` points to the reason only while one is written
    below (a press in progress has none)."""
    look = {
        "variant": "soft",
        "size": "3",
        "radius": _CONTROL_RADIUS,
        "min_height": "44px",
        "width": rx.breakpoints(initial="100%", sm="auto"),
    }
    label = (rx.icon("sparkles", size=T.ICON_SM), reel_parts_vm.TRY_FIRST_LABEL)
    off = {"aria_disabled": "true", "opacity": "0.55", "cursor": "not-allowed"}
    return rx.cond(
        CreativeState.reel_try_first_reason != "",
        rx.button(*label, aria_describedby=REEL_CREATE_REASON_ID, **off, **look),
        rx.cond(
            CreativeState.is_submitting | CreativeState.gen_generating,
            rx.button(*label, **off, **look),
            rx.button(*label, on_click=CreativeState.try_first_reel_part, **look),
        ),
    )


def _parts_way_out() -> rx.Component:
    """Where the fix is: another reel when no part can be created (the head's own
    «‹ Ideas para tus reels»), else the parts list («Volver al paso 2», the same step
    change as the summary's «Editar»)."""
    look = {
        "variant": "soft",
        "size": "3",
        "radius": _CONTROL_RADIUS,
        "min_height": "44px",
        "width": rx.breakpoints(initial="100%", sm="auto"),
    }
    return rx.cond(
        CreativeState.reel_to_ideas,
        rx.button(
            rx.icon("arrow-left", size=T.ICON_SM),
            IDEAS_BACK_LABEL,
            on_click=CreativeState.exit_create,
            **look,
        ),
        rx.cond(
            CreativeState.reel_back_to_parts,
            rx.button(
                rx.icon("arrow-left", size=T.ICON_SM),
                reel_parts_vm.BACK_TO_PARTS_LABEL,
                on_click=CreativeState.edit_view("reference"),
                **look,
            ),
        ),
    )


def _parts_reason() -> rx.Component:
    """Why the parts cannot be created yet, right under the actions; «Pedir más a
    Qualify» under a counter at 0; then the way out."""
    return rx.cond(
        CreativeState.reel_create_all_reason != "",
        rx.vstack(
            rx.box(
                callout(CreativeState.reel_create_all_reason, "warn"),
                id=REEL_CREATE_REASON_ID,
                width="100%",
            ),
            rx.match(
                CreativeState.reel_exhausted,
                ("videos", ask_more_block("videos")),
                ("previews", ask_more_block("previews")),
                rx.fragment(),
            ),
            rx.cond(
                CreativeState.reel_missing_description,
                rx.button(
                    CreativeState.reel_describe_label,
                    variant="soft",
                    min_height="44px",
                    on_click=CreativeState.describe_reel_part,
                ),
                rx.cond(
                    CreativeState.reel_unsupported_parts,
                    rx.button(
                        CreativeState.reel_change_label,
                        variant="soft",
                        min_height="44px",
                        on_click=CreativeState.change_unsupported_reel_part,
                    ),
                    _parts_way_out(),
                ),
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


def _parts_review_text() -> rx.Component:
    """What will be made, in words — first on step 5 of a video by parts."""
    return rx.cond(
        CreativeState.reel_review_text != "",
        rx.text(CreativeState.reel_review_text, size="3"),
    )


def _parts_review() -> rx.Component:
    """After the rows: what it uses of the month (UI-3's «Lo que usa de tu mes», the
    same lines), «Probar solo la parte 1» with what it uses (only with more than one
    part) and why nothing can be created yet, when so."""
    return rx.vstack(
        _parts_usage(),
        rx.cond(
            CreativeState.reel_try_first_shown,
            rx.vstack(
                _try_first_button(),
                rx.text(reel_parts_vm.TRY_FIRST_NOTE, size="2", color=T.TEXT_MUTED),
                spacing="1",
                width="100%",
                align_items="start",
            ),
        ),
        _parts_reason(),
        spacing="3",
        width="100%",
        align_items="start",
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
    video is silent, so its script is not "read" — it stays as the post's script. A video
    by parts (`shot_video`, ADR 44) has no file of its own: `_parts_video_result`."""
    return rx.cond(
        CreativeState.gen_kind == "shot_video",
        _parts_video_result(),
        _media_result(
            rx.fragment(
                rx.text(
                    rx.cond(CreativeState.video_on_seedance, "Guion", "Guion leído"),
                    class_name="q-rv-title",
                ),
                rx.text(
                    CreativeState.gen_variant_vm.script, class_name="q-rv-read q-rv-read--multi"
                ),
            ),
            _post_text(),
            title="Video",
            icon="video",
        ),
    )


def _parts_video_result() -> rx.Component:
    """A video by parts on its result (UI-7, m-24921082): how each part is doing
    (`part_progress_panel`, the screen's one poll), then «Tu video completo»
    (`final_video_card`, UI-9 — always mounted: it is the one that offers «Crear la
    parte N» while parts are missing), then the post's text. Never the empty video stage
    of a single video: its media is the join, not a file of the parent.

    Shown once the parent's own text came out (`gen_is_ready`, as every other kind):
    while the parent is `drafting` its parts do not exist yet (the creative worker
    creates them once its text passes, UI-6), so the rows would all read «Sin crear» —
    the generic wait (`_waiting`) says it better meanwhile."""
    # lazy: `final_video_card` imports `creative_pages`, which imports this module
    from .final_video_card import final_video_card  # noqa: PLC0415

    return rx.vstack(
        part_progress_panel(CreativeState.gen_draft_id),
        final_video_card(CreativeState.gen_draft_id),
        _card(_post_text(), actions=(_variant_switch(),)),
        spacing="3",
        width="100%",
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
    from .creative_pages import finish_gallery_button  # noqa: PLC0415

    return rx.vstack(
        callout(
            rx.cond(
                CreativeState.gen_failure_label != "",
                CreativeState.gen_failure_label,
                "No se pudo crear esta publicación.",
            ),
            "error",
        ),
        # m-24820842: a gallery that kept some slides makes only the missing ones
        rx.cond(
            CreativeState.gen_draft.can_finish_gallery,
            finish_gallery_button(
                CreativeState.finish_gallery_generated, CreativeState.gen_draft.missing_slides
            ),
            rx.cond(CreativeState.gen_failure_brand_fix, brand_fix_link()),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _result_view() -> rx.Component:
    from .queue_notice import queue_notice  # noqa: PLC0415

    return rx.vstack(
        rx.cond(
            CreativeState.gen_draft,
            queue_notice(CreativeState.gen_draft.queue, CreativeState.gen_draft.draft_id),
        ),
        rx.cond(CreativeState.action_error != "", callout(CreativeState.action_error, "warn")),
        # the catalog price edited in «Datos clave»: updated with this piece, or why not
        rx.cond(
            CreativeState.gen_price_note != "",
            rx.cond(
                CreativeState.gen_price_ok,
                callout(CreativeState.gen_price_note, "ok"),
                callout(CreativeState.gen_price_note, "warn"),
            ),
        ),
        # what the piece is — metadata, so `tag`s (§5.3), not state badges
        rx.hstack(
            rx.cond(
                CreativeState.gen_draft,
                tag(
                    rx.cond(
                        CreativeState.gen_kind == "shot_video",
                        PARTS_KIND_LABEL,
                        CreativeState.gen_kind_label,
                    ),
                    size="2",
                ),
            ),
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
        # UX review 2026-11-03: «otra» meant another publication to the owner, yet it
        # kept the last one's text, logos and products — two intentions, two buttons
        # review 2026-11-04: «otra versión de esta» only of a piece that came out — a
        # failed one or one still being made has nothing to make another version of
        rx.flex(
            rx.cond(
                CreativeState.gen_is_ready,
                rx.button(
                    rx.icon("copy", size=16),
                    NEW_VERSION_LABEL,
                    variant="soft",
                    color_scheme="gray",
                    on_click=CreativeState.new_generation,
                    size="3",
                    min_height="44px",
                ),
            ),
            rx.button(
                rx.icon("plus", size=16),
                NEW_PIECE_LABEL,
                variant="soft",
                on_click=CreativeState.start_new_piece,
                size="3",
                min_height="44px",
            ),
            spacing="3",
            wrap="wrap",
            width="100%",
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
                # UI-1 (m-24921075): «‹ Ideas para tus reels» for a piece opened by
                # «Hacer uno parecido», back to the ideas; else «‹ Inicio»
                back_label=CreativeState.create_back_label,
                on_exit=CreativeState.exit_create,
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
            # UI-7 (Deivid, «Solo el de la tarjeta»): a video by parts is approved only
            # with «Aprobar» in «Tu video completo»; its foot keeps «Atrás» and «Seguir
            # después», no primary
            rx.cond(
                _approves_on_card(),
                step_foot(
                    None,
                    step=CreativeState.create_step_n,
                    on_primary=None,
                    on_back=CreativeState.create_back,
                    on_later=CreativeState.save_for_later,
                ),
                step_foot(
                    CreativeState.create_primary_label,
                    step=CreativeState.create_step_n,
                    on_primary=CreativeState.create_continue,
                    on_back=CreativeState.create_back,
                    on_later=CreativeState.save_for_later,
                    primary_disabled=CreativeState.create_primary_disabled,
                    primary_loading=CreativeState.is_submitting | CreativeState.stock_importing,
                    primary_busy=CreativeState.create_primary_busy,
                    reason=CreativeState.create_reason,
                ),
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
    frame.class_name = rx.cond(
        active, "q-step-frame q-create-frame", "q-generator-form q-create-frame"
    )
    return frame


def generator_page() -> rx.Component:
    """Create's product and four real steps share one frame. Variations remains a form.
    CM-7 (m-24955928): `/create?medios=…` — what the owner chose in Galería — is its
    own short screen (`create_gallery_page`), never the product step."""
    from .create_gallery_page import create_gallery_view  # noqa: PLC0415
    from .create_gallery_state import CreateGalleryState  # noqa: PLC0415

    return app_shell(rx.cond(CreateGalleryState.active, create_gallery_view(), _generator_frame()))


def _kind_conflict_dialog() -> rx.Component:
    """«Este video no sirve aquí» (§ request 2026-10-16): the product is a stock video
    and the option picked cannot take one — use it in a Clip or a Carrusel, or change
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
                        "Usar en un Carrusel",
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


def _join_not_ready() -> rx.Var:
    """UI-9 has no joined video to review: waiting, joining, rejoining, failed, purged or
    not read yet (`FinalVideoState.join_state` other than `ready` / `approved`)."""
    return ~((FinalVideoState.join_state == "ready") | (FinalVideoState.join_state == "approved"))


def _approves_on_card() -> rx.Var:
    """UI-7: the result of a video by parts — approved only on its card (UI-9)."""
    return (CreativeState.generator_view == "result") & (CreativeState.gen_kind == "shot_video")


def _parts_hold() -> rx.Var:
    """UI-7: the result of a video by parts whose text came out (never a failed or
    cancelled one) with parts not made or waiting for the owner
    (`PartProgressState.parts_pending`) or no joined video yet (`_join_not_ready`): its
    heading says «Así va tu video…», not «Así quedó…»."""
    return (
        (CreativeState.generator_view == "result")
        & (CreativeState.gen_kind == "shot_video")
        & CreativeState.gen_is_ready
        & ~CreativeState.gen_draft.queue.cancelled
        & (PartProgressState.parts_pending | _join_not_ready())
    )


def _workspace(readiness: rx.Var) -> rx.Component:
    """The centre of /create: what was chosen, the brand's warnings, and then the
    discovery, the piece once generated, or the chosen option's views."""
    result = card(
        rx.vstack(
            # UI-7: a video by parts is not «Así quedó» while its parts are coming
            rx.text(
                rx.cond(_parts_hold(), PARTS_HEADING_TEXT, _RESULT_HEADING[1]),
                size="2",
                color=T.TEXT_MUTED,
            ),
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
        _create_error(),
        # The BrandReadiness gate is lifted for now (§ request 2026-09-30):
        # the warning stays, but it never blocks Generar. Both notices are about creating
        # a piece: the reels ideas (R7, UX review 6) do not show them — on a phone they
        # pushed the first idea below the screen.
        rx.cond(
            CreativeState.gen_mode != "discover",
            rx.fragment(
                rx.cond(
                    readiness,
                    rx.cond(
                        ~readiness.can_generate,
                        _brand_flag(),
                    ),
                ),
                rx.cond(CreativeState.kit_voice_missing, _voice_flag()),
            ),
        ),
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
                # m-25017276: printed as text, never a button
                rx.segmented_control.item("Invitación a comprar o escribir", value="cta"),
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
