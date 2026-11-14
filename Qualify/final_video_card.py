"""«Tu video completo» — the card of a video by parts (m-24921084,
`docs/ux-video-por-planos.md` §3e and §4; m-25016656 redesign: the piece page's two
columns, the whole video on the left, «Tus partes» as tiles that play in place).

Built only from the design system's primitives (Liquid Glass rule: no new primitive):
`card` as the surface, `progress_panel` while the parts are being joined (never a
spinner: the stage's comment sits above the bar), `callout` for what blocks, expired
parts and failures, `tag` for metadata and `signal_pill` for the join's state, by tone.
The player is the generator's (`content_generator._media_preview`): `rx.video` with
`controls`, its poster and the `q-rv-media q-rv-media--video` 9:16 frame.

State: `final_video_card_state.FinalVideoState`. Words: `final_video_vm`.
"""

from __future__ import annotations

import reflex as rx
from qualify_creative.schemas import PART_DESCRIPTION_MAX

from . import part_review_vm as RV
from .creative_pages import (
    APPROVED_BODY,
    APPROVED_NOT_READY_BODY,
    APPROVED_SCHEDULE,
    APPROVED_TITLE,
)
from .final_video_card_state import (
    APPROVE,
    CHANGE,
    CHANGE_DESCRIPTION_ID,
    CHANGE_PHOTOS_ID,
    CHANGE_TITLE_ID,
    CHOOSE_ID_PREFIX,
    CREATE,
    RECREATE,
    REJOIN,
    REVIEW_RETRY_ID,
    SCHEDULE_BUTTON_ID,
    USE,
    FinalVideoState,
    PhotoChoiceView,
)
from .final_video_vm import ExpiredPartVM
from .part_progress_state import PartProgressState
from .post_card import readiness_note
from .r2_media import BACKEND_BASE
from .ui import tokens as T
from .ui.clip_player import clip_player
from .ui.primitives import (
    callout,
    card,
    progress_panel,
    signal_pill,
    skeleton_card,
    tag,
)

S = FinalVideoState
P = PartProgressState

#: N12: every tap target at least 44 px tall on a phone.
_TAP = "2.75rem"
CARD_ID = "q-final-video"
APPROVE_WHY_ID = "q-final-video-approve-why"
CHANGE_PANEL_ID = "q-final-video-change"
#: m-24921083: the chosen part's fields and what «Crear otra versión» says
CHANGE_EXAMPLE_ID = "q-final-video-change-example"
CHANGE_USE_ID = "q-final-video-change-use"
CHANGE_WHY_ID = "q-final-video-change-why"
USE_NOTE_ID = "q-final-video-use-note"
_PHOTOS_LABEL_ID = "q-final-video-change-photos-label"
CHANGE_SUBMIT = "Crear otra versión"
CHANGE_CANCEL = "Cancelar"
PART_WORD = "Parte "
VIDEO_LABEL = "Vista previa de tu video completo"

# The card's one live region is read, not seen (WCAG 4.1.3).
_SCREEN_READER_ONLY = {
    "position": "absolute",
    "width": "1px",
    "height": "1px",
    "overflow": "hidden",
    "clip": "rect(0 0 0 0)",
    "clip_path": "inset(50%)",
    "white_space": "nowrap",
}


def _src(url: rx.Var[str], key: rx.Var[str]) -> rx.Var[str]:
    """An R2 object through `/r2media`, else the local upload store (the generator's
    `_item_src` rule)."""
    return rx.cond(url != "", BACKEND_BASE + url, rx.get_upload_url(key))


def _poster() -> rx.Var[str]:
    return rx.cond(
        S.poster_url != "",
        BACKEND_BASE + S.poster_url,
        rx.cond(S.poster_key != "", rx.get_upload_url(S.poster_key), ""),
    )


def _header() -> rx.Component:
    """«Tu video completo · 18 s · [Vista previa]» and, while joining or failed, its
    `signal_pill`."""
    return rx.flex(
        rx.heading(S.card.title, as_="h3", size="4", weight="bold"),
        rx.cond(S.card.seconds_label != "", tag(S.card.seconds_label, size="2")),
        tag(S.card.badge, size="2"),
        rx.cond(
            S.card.pill_word != "",
            rx.match(
                S.card.pill_tone,
                ("error", signal_pill(S.card.pill_word, "error", size="2")),
                ("info", signal_pill(S.card.pill_word, "info", size="2")),
                signal_pill(S.card.pill_word, "neutral", size="2"),
            ),
        ),
        gap="0.5rem",
        align="center",
        wrap="wrap",
        width="100%",
    )


#: m-25016656: the card's two layouts — «columns» is the piece page's grid (the whole video
#: on the left, what is decided on the right; stacked under `md`), «stacked» one column
#: at any width. «columns» is the default: /create's result already uses that grid.
COLUMNS = "columns"
STACKED = "stacked"
EMPTY_STAGE_TEXT = "Cuando estén todas las partes, aquí ves tu video completo."
JOINING_STAGE_TEXT = "Estamos juntando tus partes. En un momento lo ves aquí."
PARTS_TITLE = "Tus partes"
PARTS_HINT_CHANGE = "Toca ▶ para ver cada parte. Si una no te gusta, cámbiala."
PARTS_HINT_WATCH = "Toca ▶ para ver cada parte."
PARTS_LIST_ID = "q-final-video-parts"
CHOOSE_LABEL = "Cambiar esta"
CHOSEN_LABEL = "Elegida"
#: a tile's width: two whole tiles and the edge of a third on a 375 px phone
_TILE_W = rx.breakpoints(initial="8.5rem", md="8rem")
#: The tones a part tile's pill can take.
_TONES = ("ok", "warn", "error", "info", "neutral")


def _player(layout: str) -> rx.Component:
    """The whole video, or — before there is one — the empty 9:16 frame saying when it
    comes. In «columns» it fills its column from `md` (20rem / 24rem); on a phone, and in
    «stacked», 14rem centred so «Tus partes» shows on the first screen."""
    has_file = S.card.show_video & ((S.video_url != "") | (S.video_key != ""))
    width = rx.breakpoints(initial="14rem", md="100%") if layout == COLUMNS else "14rem"
    return rx.box(
        rx.cond(
            has_file,
            rx.video(
                src=_src(S.video_url, S.video_key),
                poster=_poster(),
                controls=True,
                width="100%",
                height="auto",
                class_name="q-rv-media q-rv-media--video",
            ),
            rx.center(
                # what the empty frame says by the join's state: waiting for the parts,
                # joining them — or nothing when it failed or the files are gone (the
                # notice on the right says it)
                rx.cond(
                    (S.join_state == "failed") | (S.join_state == "purged"),
                    rx.icon("film", size=28, color=T.TEXT_MUTED),
                    rx.text(
                        rx.cond(S.wants_refresh, JOINING_STAGE_TEXT, EMPTY_STAGE_TEXT),
                        size="2",
                        color=T.TEXT_MUTED,
                        text_align="center",
                        padding="1rem",
                    ),
                ),
                class_name="q-rv-media-empty",
                height="auto",
                aspect_ratio="9 / 16",
                width="100%",
            ),
        ),
        role="group",
        aria_label=VIDEO_LABEL,
        width="100%",
        max_width=width,
        margin_x="auto",
        flex_shrink="0",
    )


def _approve_button() -> rx.Component:
    """«Aprobar» — the card's one solid action, last in its last row (Deivid, 2026-11-09).
    Off, it stays in the keyboard order as `aria-disabled` and the reader hears why
    (`aria-describedby`); the `approve` event itself refuses while it cannot approve."""
    blocked = ~S.card.approve_enabled | S.working
    return rx.button(
        rx.icon("check", size=16),
        S.card.approve_label,
        size="3",
        min_height=_TAP,
        loading=S.busy == APPROVE,
        on_click=S.approve,
        aria_disabled=rx.cond(blocked, "true", "false"),
        aria_describedby=APPROVE_WHY_ID,
    )


def _approve_texts() -> rx.Component:
    """What «Aprobar» says, as ONE block right above the last row: why it is off, what
    approving uses of the month (seconds, ADR 44 F1), and what does not count again."""
    return rx.vstack(
        rx.cond(
            S.card.approve_hint != "",
            rx.text(S.card.approve_hint, size="2", color=T.TEXT_MUTED),
        ),
        rx.cond(
            S.card.quota_text != "",
            rx.text(S.card.quota_text, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
        ),
        rx.cond(
            S.card.charged_note != "",
            rx.text(S.card.charged_note, size="2", color=T.TEXT_MUTED),
        ),
        id=APPROVE_WHY_ID,
        spacing="1",
        width="100%",
    )


def _changing() -> rx.Var[bool]:
    """A part is chosen in «Tus partes»: its words and «Crear otra versión» show."""
    return S.change_open & S.card.change_part_visible & (S.change_index != "")


def _actions() -> rx.Component:
    """The card's last row, «Aprobar» first (founder's call) — and, with a part chosen
    in «Tus partes», [Crear otra versión] [Cancelar]. On a 375 px phone it may take two
    lines; «Aprobar» stays the solid one. m-24921083: «Crear otra versión» waits, still
    focusable (`aria-disabled`), while its panel says why (empty description, no photo,
    no vista previa left this month)."""
    waits = S.review_blocked != ""
    return rx.flex(
        rx.cond(S.card.approve_visible, _approve_button()),
        rx.cond(
            _changing(),
            rx.fragment(
                rx.button(
                    rx.icon("refresh-cw", size=16),
                    CHANGE_SUBMIT,
                    variant="soft",
                    size="3",
                    min_height=_TAP,
                    disabled=S.working | S.review_loading,
                    loading=S.busy == CHANGE,
                    aria_disabled=rx.cond(waits, "true", "false"),
                    aria_describedby=CHANGE_WHY_ID + " " + CHANGE_USE_ID,
                    opacity=rx.cond(waits, "0.6", "1"),
                    on_click=S.change_part,
                ),
                rx.button(
                    CHANGE_CANCEL,
                    variant="ghost",
                    color_scheme="gray",
                    size="3",
                    min_height=_TAP,
                    on_click=S.cancel_change,
                ),
            ),
        ),
        gap="0.75rem",
        align="center",
        wrap="wrap",
        width="100%",
    )


def _create_missing() -> rx.Component:
    """A part of the plan never created (visual review 2026-11-09): «La parte 6 todavía no
    se creó.», then «Crear la parte 6» / «Crear las que faltan» and what it uses."""
    return rx.vstack(
        _note(S.card.unmade_text, "info", icon="circle-plus"),
        rx.button(
            rx.icon("plus", size=16),
            S.card.create_label,
            variant="soft",
            size="3",
            min_height=_TAP,
            disabled=S.working,
            loading=S.busy == CREATE,
            on_click=S.create_missing,
        ),
        rx.text(S.card.create_text, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _note(text: rx.Var | str, tone: str, icon: str | None = None) -> rx.Component:
    """A `callout` that is a plain `note`: `callout` gives every tone a live role
    (`status` / `alert`), and the card keeps ONE live region (`announce`), as the parts'
    panel does."""
    note = callout(text, tone, icon=icon) if icon else callout(text, tone)
    note.role = rx.Var.create("note")
    return note


def _pill(word: rx.Var, tone: rx.Var) -> rx.Component:
    """`signal_pill` takes its tone at build time: one branch per tone."""
    return rx.match(
        tone,
        *[(t, signal_pill(word, t)) for t in _TONES if t != "neutral"],
        signal_pill(word, "neutral"),
    )


def _peeking(tile: rx.Var) -> rx.Var[bool]:
    """This tile's part is chosen and the owner looks at one of its earlier versions."""
    return (S.change_index == tile.index) & (S.review_peek.version_id != "")


def _peek_frame(tile: rx.Var) -> rx.Component:
    """Deivid, 2026-11-13: «Ver la anterior» plays THAT version in the part's tile —
    the same `clip_player` and lazy load, keyed by the version (a new player), marked
    «Versión 1 de 2» above it and named by it. The whole video does not change until
    «Usar esta versión»."""
    peek = S.review_peek
    return rx.vstack(
        tag(peek.label, size="1"),
        rx.cond(
            peek.video_url != "",
            clip_player(
                rx.cond(peek.poster_url != "", BACKEND_BASE + peek.poster_url, ""),
                src=BACKEND_BASE + peek.video_url,
                label=peek.play_label,
                pause_label=peek.pause_label,
                key=tile.key + "-" + peek.version_id,
                framed=True,
                renew=True,
                width="100%",
                aspect_ratio="9 / 16",
            ),
            rx.center(
                rx.icon("film", size=20, color=T.TEXT_MUTED),
                class_name="q-thumb",
                width="100%",
                aspect_ratio="9 / 16",
            ),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _tile_frame(tile: rx.Var) -> rx.Component:
    """The part's own vista previa, played inside its tile (the parts' rows' player:
    `ui.clip_player`, muted with a sound button, renewed when its address expired) —
    an earlier version while the owner looks at it (`_peek_frame`) — or, with no clip
    yet, an empty 9:16 frame with a film glyph."""
    return rx.cond(
        _peeking(tile),
        _peek_frame(tile),
        _current_frame(tile),
    )


def _current_frame(tile: rx.Var) -> rx.Component:
    return rx.cond(
        tile.preview_url != "",
        clip_player(
            rx.cond(tile.poster_url != "", BACKEND_BASE + tile.poster_url, ""),
            src=BACKEND_BASE + tile.preview_url,
            label=tile.play_label,
            pause_label=tile.pause_label,
            key=tile.key,
            framed=True,
            renew=True,
            width="100%",
            aspect_ratio="9 / 16",
        ),
        rx.center(
            rx.icon("film", size=20, color=T.TEXT_MUTED),
            class_name="q-thumb",
            width="100%",
            aspect_ratio="9 / 16",
        ),
    )


def _like_button(tile: rx.Var) -> rx.Component:
    """«Me gusta así» / «✓ Lista» (m-24921083): one tap marks the part, another takes
    the mark off. Pressed = the word, the tick and `aria-pressed`, never the colour
    alone; its name starts with its visible words and says which part."""
    liked = tile.liked
    return rx.button(
        rx.cond(liked, rx.icon("check", size=14)),
        rx.cond(liked, RV.LIKED_LABEL, RV.LIKE_LABEL),
        # «Aprobar» stays the card's one filled button
        variant=rx.cond(liked, "soft", "outline"),
        size="2",
        width="100%",
        min_height=_TAP,
        aria_pressed=rx.cond(liked, "true", "false"),
        # a fixed name (UX review): the state is `aria-pressed` alone
        aria_label=RV.LIKE_LABEL + ": parte " + tile.number.to_string(),
        on_click=P.toggle_like(tile.index),
    )


def _part_card(tile: rx.Var) -> rx.Component:
    """One part (m-25016656): its vista previa playing in place, «Parte N», its seconds,
    the word of its state while it has no clip, and «Cambiar esta» / «✓ Elegida» when
    it can change — its own button (the tile holds a ▶: no nested buttons). Chosen =
    the word, the tick and `aria-pressed`, never the colour alone; a second tap lets it
    go. An approved video shows its parts to watch only."""
    chosen = S.change_open & (S.change_index == tile.index)
    can_choose = S.card.change_part_visible & S.part_options.contains(tile.index)
    return card(
        rx.vstack(
            _tile_frame(tile),
            rx.vstack(
                rx.text(PART_WORD + tile.number.to_string(), size="2", weight="medium"),
                rx.text(tile.seconds_text, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                spacing="0",
            ),
            # an approved video's parts are only to watch: no decision word
            rx.cond((tile.word != "") & ~S.closed, _pill(tile.word, tile.tone)),
            # m-24921083 (Deivid, «A: en cada tarjeta»): «Me gusta así» above «Cambiar
            # esta»; liked, «✓ Lista» — a second tap takes it off. Never a condition of
            # «Aprobar»; an approved video has none.
            rx.cond(tile.can_like & ~S.closed, _like_button(tile)),
            rx.cond(
                can_choose,
                rx.button(
                    rx.cond(chosen, rx.icon("check", size=14)),
                    rx.cond(chosen, CHOSEN_LABEL, CHOOSE_LABEL),
                    # «Aprobar» stays the card's one filled button
                    variant=rx.cond(chosen, "soft", "outline"),
                    size="2",
                    width="100%",
                    min_height=_TAP,
                    disabled=S.working,
                    aria_pressed=rx.cond(chosen, "true", "false"),
                    # the name starts with the visible words (WCAG 2.5.3)
                    aria_label=rx.cond(chosen, CHOSEN_LABEL, CHOOSE_LABEL)
                    + ": parte "
                    + tile.number.to_string(),
                    id=CHOOSE_ID_PREFIX + tile.index,
                    on_click=S.choose_part(tile.index, tile.draft_id),
                ),
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        padding="0.5rem",
        role="listitem",
        width=_TILE_W,
        flex_shrink="0",
    )


def _parts_strip(layout: str) -> rx.Component:
    """«Tus partes»: every part as a tile, in order (`PartProgressState.part_tiles`, the
    parts' panel's own read — it is mounted wherever this card is). A row that wraps in
    the desktop column, one that slides sideways on a phone (never a hidden part)."""
    tiles = PartProgressState.part_tiles
    can_change = S.card.change_part_visible & (S.part_options.length() > 0)
    side = rx.breakpoints(initial="nowrap", md="wrap") if layout == COLUMNS else "nowrap"
    return rx.cond(
        tiles.length() > 0,
        rx.vstack(
            rx.heading(PARTS_TITLE, as_="h4", size="3", id=PARTS_LIST_ID),
            rx.text(
                rx.cond(can_change, PARTS_HINT_CHANGE, PARTS_HINT_WATCH),
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.flex(
                rx.foreach(tiles, _part_card),
                role="list",
                aria_labelledby=PARTS_LIST_ID,
                gap="0.75rem",
                wrap=side,
                overflow_x="auto",
                width="100%",
                padding_bottom="0.25rem",
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


def _joining_only() -> rx.Component:
    """The card while its parts are joined (Deivid, 2026-11-13: «que se oculte todo y
    solo esté el loader en el medio»): no video, no «Tus partes», no panel, no buttons
    — the house's `progress_panel`, its stage line above the bar, centred. The poll
    already running brings everything back once the join ends."""
    return rx.center(
        rx.box(
            progress_panel(S.card.title, steps=S.joining_steps, creep_seconds=90),
            width="100%",
            max_width="28rem",
        ),
        min_height="16rem",
        width="100%",
    )


def _versions() -> rx.Component:
    """«Versión 2 de 2 · Ver la anterior» (only with two or more): an earlier version
    shows its own video and description, and [Usar esta versión] — no vista previa used;
    an expired one keeps the button off, with its reason."""
    version = S.review_version
    nav = rx.flex(
        rx.text(version.label, size="2", class_name="q-nums"),
        rx.text("·", size="2", color=T.TEXT_MUTED, aria_hidden="true"),
        rx.cond(
            S.review_has_previous,
            rx.button(
                RV.SEE_PREVIOUS,
                variant="ghost",
                size="2",
                min_height=_TAP,
                on_click=S.show_version(-1),
            ),
        ),
        rx.cond(
            S.review_has_next,
            rx.button(
                RV.SEE_NEXT,
                variant="ghost",
                size="2",
                min_height=_TAP,
                on_click=S.show_version(1),
            ),
        ),
        gap="0.5rem",
        align="center",
        wrap="wrap",
    )
    off = (version.use_reason != "") | S.working
    earlier = rx.vstack(
        rx.cond(version.made_with != "", rx.text(version.made_with, size="2")),
        rx.button(
            rx.icon("history", size=16),
            RV.USE_VERSION,
            variant="outline",
            size="3",
            min_height=_TAP,
            loading=S.busy == USE,
            aria_disabled=rx.cond(off, "true", "false"),
            aria_describedby=USE_NOTE_ID,
            opacity=rx.cond(off, "0.6", "1"),
            on_click=S.use_version,
        ),
        rx.text(
            rx.cond(version.use_reason != "", version.use_reason, RV.USE_VERSION_NOTE),
            size="2",
            color=T.TEXT_MUTED,
            id=USE_NOTE_ID,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )
    return rx.cond(
        S.review_versions.length() > 1,
        rx.vstack(
            nav,
            rx.cond(~version.current & (version.version_id != ""), earlier),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


def _photo(photo: PhotoChoiceView) -> rx.Component:
    """One photo of the product: a tap puts it in or takes it out of the part. Chosen =
    the tick and `aria-pressed`, never the border alone."""
    on = S.review_selected.contains(photo.key)
    src = rx.cond(photo.url != "", BACKEND_BASE + photo.url, rx.get_upload_url(photo.key))
    return rx.el.button(
        rx.image(
            src=src,
            alt="",
            width="100%",
            height="100%",
            object_fit="cover",
            border_radius=T.RADIUS_CONTROL,
        ),
        rx.cond(
            on,
            rx.center(
                rx.icon("check", size=14),
                position="absolute",
                top="0.25rem",
                right="0.25rem",
                width="1.25rem",
                height="1.25rem",
                border_radius="9999px",
                background=T.SURFACE_BG_RAISED,
                color=T.TEXT_STRONG,
            ),
        ),
        type="button",
        aria_pressed=rx.cond(on, "true", "false"),
        aria_label=photo.label,
        on_click=S.toggle_photo(photo.key),
        # the system's choice ring (`ui.choice_card`'s classes): accent ring when on
        class_name=rx.cond(on, "q-choice-card q-choice-card--on", "q-choice-card"),
        position="relative",
        width="4.5rem",
        height="4.5rem",
        padding="0.25rem",
        flex_shrink="0",
    )


def _fields() -> rx.Component:
    """«¿Cómo la hacemos?» read only, «¿Qué pasa en esta parte?» filled in with the
    description of the version on screen, and «Fotos de tu producto»."""
    return rx.vstack(
        rx.cond(
            S.review_mode_label != "",
            rx.vstack(
                rx.text(RV.QUESTION, size="2", weight="medium"),
                rx.text(S.review_mode_label, size="2"),
                rx.text(S.review_mode_help, size="2", color=T.TEXT_MUTED),
                spacing="0",
                width="100%",
                align_items="start",
            ),
        ),
        rx.vstack(
            rx.el.label(
                RV.DESCRIPTION_LABEL,
                html_for=CHANGE_DESCRIPTION_ID,
                style={"fontWeight": "500", "fontSize": "var(--font-size-2)"},
            ),
            rx.text_area(
                value=S.change_text,
                on_change=S.set_change_text,
                id=CHANGE_DESCRIPTION_ID,
                aria_describedby=CHANGE_EXAMPLE_ID,
                max_length=PART_DESCRIPTION_MAX,
                rows="3",
                width="100%",
            ),
            rx.text(RV.DESCRIPTION_EXAMPLE, size="1", color=T.TEXT_MUTED, id=CHANGE_EXAMPLE_ID),
            spacing="1",
            width="100%",
            align_items="start",
        ),
        rx.vstack(
            rx.text(RV.PHOTOS_LABEL, size="2", weight="medium", id=_PHOTOS_LABEL_ID),
            rx.cond(
                S.review_photos.length() > 0,
                rx.flex(
                    rx.foreach(S.review_photos, _photo),
                    # the keyboard lands on its first photo when one is missing
                    id=CHANGE_PHOTOS_ID,
                    role="group",
                    aria_labelledby=_PHOTOS_LABEL_ID,
                    gap="0.5rem",
                    wrap="wrap",
                    width="100%",
                ),
                # live test 2026-11-13: said, never an empty section
                rx.text(RV.NO_PHOTOS_TEXT, size="2", color=T.TEXT_MUTED),
            ),
            spacing="1",
            width="100%",
            align_items="start",
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _review_failed() -> rx.Component:
    """«No pudimos abrir esta parte.» and [Intentar de nuevo] (one more read). Its text
    also describes the waiting «Crear otra versión» (`CHANGE_WHY_ID`)."""
    return rx.vstack(
        rx.box(_note(S.review_error, "warn"), id=CHANGE_WHY_ID, width="100%"),
        rx.button(
            rx.icon("refresh-cw", size=16),
            RV.REVIEW_RETRY,
            variant="soft",
            size="3",
            min_height=_TAP,
            id=REVIEW_RETRY_ID,
            on_click=S.retry_review,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _change_panel() -> rx.Component:
    """m-24921083 «Revisar y rehacer una parte»: the chosen part (its tile says «✓
    Elegida»), under «Tus partes» — its versions (the one looked at plays in the
    part's tile), how it is made, what happens in it, its photos and what another version
    uses. Its buttons stay in the card's last row, beside «Aprobar» (`_actions`)."""
    return rx.vstack(
        rx.heading(
            PART_WORD + S.change_number,
            as_="h4",
            size="3",
            id=CHANGE_TITLE_ID,
            tab_index=-1,
        ),
        # Deivid, 2026-11-13: while it is read, nothing at all — no box shaped like a
        # video, no skeleton (the read is short; the title says which part)
        rx.cond(
            S.review_loading,
            rx.fragment(),
            rx.cond(
                S.review_ready,
                rx.fragment(
                    _versions(),
                    _fields(),
                    rx.cond(
                        (S.review_blocked != "") & (S.review_blocked != S.review_use_text),
                        rx.text(S.review_blocked, size="2", color=T.TEXT_MUTED, id=CHANGE_WHY_ID),
                    ),
                    rx.text(
                        rx.cond(S.review_use_text != "", S.review_use_text, RV.CHANGE_NOTE),
                        size="2",
                        color=T.TEXT_MUTED,
                        class_name="q-nums",
                        id=CHANGE_USE_ID,
                    ),
                ),
                # UX review: unread, no fields at all (never an empty box that would
                # replace the description) — the reason and [Intentar de nuevo]
                rx.cond(S.review_error != "", _review_failed()),
            ),
        ),
        id=CHANGE_PANEL_ID,
        role="region",
        aria_labelledby=CHANGE_TITLE_ID,
        spacing="3",
        width="100%",
        align_items="start",
    )


def _expired(item: ExpiredPartVM) -> rx.Component:
    return _note(item.text, "warn", icon="clock")


def _recreate() -> rx.Component:
    """The ONE button for the expired parts, and what it uses of the month."""
    return rx.vstack(
        rx.foreach(S.card.expired_parts, _expired),
        rx.button(
            rx.icon("rotate-ccw", size=16),
            S.card.recreate_label,
            variant="soft",
            size="3",
            min_height=_TAP,
            disabled=S.working,
            loading=S.busy == RECREATE,
            on_click=S.recreate,
        ),
        rx.cond(
            S.card.recreate_text != "",
            rx.text(S.card.recreate_text, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _failed() -> rx.Component:
    """«No pudimos juntar tus partes…» [Juntar otra vez] — ours, nothing charged."""
    return rx.vstack(
        _note(S.card.status_text, "error"),
        rx.button(
            rx.icon("refresh-cw", size=16),
            S.card.rejoin_label,
            variant="soft",
            size="3",
            min_height=_TAP,
            disabled=S.working,
            loading=S.busy == REJOIN,
            on_click=S.rejoin,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _approved() -> rx.Component:
    """Right after approving here — as on the piece's own page (m-24842978): it is not
    out yet, and «Elegir día y hora» opens Tu semana on it; if it cannot be planned yet,
    what is missing instead."""
    ready = S.approved_ready
    return rx.vstack(
        rx.hstack(
            rx.center(rx.icon("circle-check", size=16), class_name="q-rv-glyph"),
            rx.vstack(
                rx.text(APPROVED_TITLE, class_name="q-rv-title"),
                rx.text(
                    rx.cond(ready, APPROVED_BODY, APPROVED_NOT_READY_BODY),
                    class_name="q-rv-hint",
                ),
                spacing="0",
            ),
            align="center",
            spacing="2",
        ),
        rx.cond(~ready, readiness_note(S.approved_note)),
        rx.cond(
            ready,
            rx.button(
                rx.icon("calendar-clock", size=16),
                APPROVED_SCHEDULE,
                size="3",
                min_height=_TAP,
                on_click=S.go_schedule,
                id=SCHEDULE_BUTTON_ID,  # focused right after approving
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _decisions(layout: str) -> rx.Component:
    """Everything decided about the video, in the order of the design (m-25016656):
    title, its two lines, what blocks or is missing, «Tus partes», the chosen part's
    words, what «Aprobar» says and the last row."""
    joining = S.wants_refresh
    return rx.vstack(
        _header(),
        rx.cond(
            S.card.preview_text != "",
            rx.text(S.card.preview_text, size="2"),
        ),
        rx.cond(
            S.card.deadline_text != "",
            rx.text(S.card.deadline_text, size="2", weight="medium"),
        ),
        rx.cond(
            S.join_state == "purged",
            _note(S.card.status_text, "neutral"),
        ),
        rx.cond(S.card.rejoin_visible, _failed()),
        # the join on its way (first time, or again while the earlier one stays)
        rx.cond(
            joining,
            progress_panel(S.card.status_text, steps=S.join_steps, creep_seconds=90),
        ),
        # a refusal sits right above the actions it is about (UX review), not at the top
        rx.cond(S.error != "", _note(S.error, "warn")),
        # a part still being made: the card says so (visual review 2026-11-09)
        rx.cond(S.card.creating_text != "", _note(S.card.creating_text, "info", icon="clock")),
        rx.cond(S.card.create_visible, _create_missing()),
        rx.cond(S.card.recreate_visible, _recreate()),
        rx.cond(S.approved_here, _approved()),
        _parts_strip(layout),
        # m-24921083: a «Me gusta así» that did not go through (the tile went back)
        rx.cond(P.like_error != "", _note(P.like_error, "warn")),
        rx.cond(_changing(), _change_panel()),
        rx.cond(S.card.approve_visible, _approve_texts()),
        _actions(),  # «Aprobar» is always last (Deivid, 2026-11-09)
        spacing="4",
        width="100%",
        min_width="0",
        align_items="start",
    )


def _body(layout: str) -> rx.Component:
    """«columns»: the piece page's grid (`creative_pages._review_panel`) — the whole video
    on the left, sticky from `md` (`q-rv-stage`), the decisions on the right; one column
    under `md`. «stacked»: the video centred on top, the decisions under it."""
    stage = rx.box(_player(layout), class_name="q-rv-stage")
    if layout != COLUMNS:
        return rx.vstack(stage, _decisions(layout), spacing="4", width="100%")
    return rx.box(
        stage,
        _decisions(layout),
        display="grid",
        grid_template_columns=rx.breakpoints(
            initial="minmax(0, 1fr)",
            md="20rem minmax(0, 1fr)",
            xl="24rem minmax(0, 1fr)",
        ),
        column_gap=rx.breakpoints(initial="0", md="2rem", xl="2.5rem"),
        row_gap="1.5rem",
        align_items="start",
        width="100%",
    )


def final_video_card(parent_id: rx.Var[str] | str, layout: str = COLUMNS) -> rx.Component:
    """«Tu video completo» of the video by parts `parent_id` (the parent draft's id).

    `layout`: `COLUMNS` (default — /create's result and /drafts) or `STACKED`. The tiles
    of «Tus partes» play the parts' own vistas previas from the parts' panel
    (`part_progress_panel`), mounted on the same screen.

    It reads on mount (`FinalVideoState.load`). It never polls: while
    `FinalVideoState.wants_refresh` is True (the parts are being joined) the screen's
    own poll calls `FinalVideoState.refresh(parent_id)` on each tick — ONE read each.
    Renders nothing for an id that is not a video by parts of this business."""
    if layout not in (COLUMNS, STACKED):
        raise ValueError(f"unknown layout {layout!r}")
    return rx.box(
        rx.cond(
            S.missing,
            rx.fragment(),
            rx.cond(
                S.loaded,
                rx.cond(
                    # Deivid, 2026-11-13: while the parts are joined, only the wait —
                    # a failed join is not joining: its notice and actions still show
                    S.wants_refresh,
                    card(_joining_only(), padding="1.25rem 1.5rem"),
                    card(_body(layout), padding="1.25rem 1.5rem"),
                ),
                # the first read failed (or no session): say so, never a skeleton forever
                rx.cond(S.error != "", callout(S.error, "warn"), skeleton_card(3)),
            ),
        ),
        rx.text(S.announce, aria_live="polite", role="status", style=_SCREEN_READER_ONLY),
        id=CARD_ID,
        position="relative",
        width="100%",
        on_mount=FinalVideoState.load(parent_id),
    )


__all__ = ["COLUMNS", "STACKED", "final_video_card"]
